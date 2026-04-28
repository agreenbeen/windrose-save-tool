"""
R5 binary record parser.

From byte-by-byte inspection the outer format is:

  uint32 LE   total_byte_count  (== len(data))
  [records…]

Each record:
  uint8        type_byte
  null-term    field_name  (ASCII / UTF-8)
  <value>      depends on type_byte:
    0x02  →  uint32 length + string bytes (null-terminated FString)
    0x03  →  uint32 blob_size  (inline nested blob; value = raw bytes)
    0x04  →  int32 LE  +  1 trailing flag/pad byte
    0x05  →  int32 LE  +  1 trailing flag/pad byte  (alias of 0x04 seen so far)
        0x10  →  int32 LE
    other →  treated as blob: uint32 size + bytes

Nested blobs are recursively decoded when they look like records.

The blackboard section stores quest/scenario state as a flat sequence of
sub-records with keys like:
  TagName       → string key   (e.g. "Quest.Main.Revenge.Sub1")
  ValueType     → "Bool" | "Integer"
  BlackboardValues → "true"/"false" or omitted (integer stored as raw int32)
"""
from __future__ import annotations

import struct
from typing import Any


# ---------------------------------------------------------------------------
# Low-level reader
# ---------------------------------------------------------------------------

class _Buf:
    __slots__ = ("_d", "_p")

    def __init__(self, data: bytes) -> None:
        self._d = data
        self._p = 0

    @property
    def pos(self) -> int:
        return self._p

    @pos.setter
    def pos(self, v: int) -> None:
        self._p = v

    @property
    def remaining(self) -> int:
        return len(self._d) - self._p

    def peek(self, n: int = 1) -> bytes:
        return self._d[self._p : self._p + n]

    def read(self, n: int) -> bytes:
        out = self._d[self._p : self._p + n]
        self._p += n
        return out

    def read_u8(self) -> int:
        b = self._d[self._p]
        self._p += 1
        return b

    def read_u32(self) -> int:
        v = struct.unpack_from("<I", self._d, self._p)[0]
        self._p += 4
        return v

    def read_i32(self) -> int:
        v = struct.unpack_from("<i", self._d, self._p)[0]
        self._p += 4
        return v

    def read_null_str(self) -> str:
        start = self._p
        while self._p < len(self._d) and self._d[self._p] != 0:
            self._p += 1
        s = self._d[start : self._p].decode("utf-8", errors="replace")
        self._p += 1  # consume null
        return s

    def read_fstring(self) -> str:
        length = self.read_i32()
        if length == 0:
            return ""
        if length < 0:
            n = (-length) * 2
            raw = self.read(n)
            return raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        raw = self.read(length)
        return raw.decode("utf-8", errors="replace").rstrip("\x00")


# ---------------------------------------------------------------------------
# Record-level parser
# ---------------------------------------------------------------------------

_MAX_NESTED_DEPTH = 6


def _parse_records(buf: _Buf, end: int, depth: int = 0) -> dict[str, Any]:
    """Parse a sequence of typed records from buf up to byte offset *end*."""
    out: dict[str, Any] = {}
    while buf.pos < end and buf.remaining >= 2:
        type_byte = buf.read_u8()

        # A type byte of 0x00 usually signals the end of a section
        if type_byte == 0x00:
            break

        name = buf.read_null_str()
        if not name:
            break  # corrupt / end padding

        if type_byte == 0x02:
            # FString value
            if buf.remaining >= 4:
                value = buf.read_fstring()
            else:
                value = None

        elif type_byte in (0x04, 0x05):
            # int32 + 1 trailing byte
            if buf.remaining >= 5:
                value = buf.read_i32()
                buf.read(1)  # trailing flag/pad
            else:
                value = None

        elif type_byte == 0x10:
            # plain int32
            if buf.remaining >= 4:
                value = buf.read_i32()
            else:
                value = None

        elif type_byte == 0x03:
            # Nested blob: uint32 byte-count then raw bytes
            if buf.remaining >= 4:
                blob_size = buf.read_u32()
                if buf.remaining >= blob_size:
                    blob = buf.read(blob_size)
                    if depth < _MAX_NESTED_DEPTH and blob_size > 8:
                        try:
                            inner = _parse_records(_Buf(blob), len(blob), depth + 1)
                            value = inner if inner else blob.hex()
                        except Exception:
                            value = f"<blob {blob_size}B>"
                    else:
                        value = f"<blob {blob_size}B>"
                else:
                    value = None
            else:
                value = None

        else:
            # Unknown type — try to skip using uint32 size prefix
            if buf.remaining >= 4:
                blob_size = buf.read_u32()
                if 0 < blob_size <= buf.remaining:
                    blob = buf.read(blob_size)
                    value = f"<t{type_byte:02x} {blob_size}B>"
                else:
                    # Can't safely skip; stop parsing this block
                    break
            else:
                break

        # Deduplicate keys
        if name in out:
            existing = out[name]
            if not isinstance(existing, list):
                out[name] = [existing]
            out[name].append(value)
        else:
            out[name] = value

    return out


def parse_r5_value(data: bytes) -> dict[str, Any]:
    """
    Top-level parser.  First 4 bytes are uint32 total size, then records.
    """
    if len(data) < 4:
        return {}
    buf = _Buf(data)
    total_size = buf.read_u32()   # == len(data) in practice
    end = min(total_size, len(data))
    result = _parse_records(buf, end)
    result["__total_bytes"] = total_size
    return result


# ---------------------------------------------------------------------------
# Blackboard extractor  (quest / scenario state)
# ---------------------------------------------------------------------------

def extract_blackboard(data: bytes) -> dict[str, Any]:
    """
    Extract all quest/scenario blackboard key-value pairs from a player blob.

    The blackboard is stored as a sequence of sub-records, each containing:
      TagName      → dotted key string
      ValueType    → "Bool" or "Integer"
      BlackboardValues → "true"/"false"  (Bool), or raw int32 (Integer)

    Returns { "Quest.Main.Revenge.Sub1": True, "Quest.Main.Score": 5, … }
    """
    result: dict[str, Any] = {}

    # Scan all embedded strings for the TagName / ValueType / BlackboardValues pattern
    # We use a simple state-machine scan over the raw bytes.
    i = 0
    d = data
    n = len(d)

    # Find all null-terminated strings quickly
    strings: list[tuple[int, str]] = []  # (offset, value)
    j = 0
    while j < n:
        if 0x20 <= d[j] <= 0x7e:
            start = j
            while j < n and d[j] != 0:
                j += 1
            if j - start >= 2:
                try:
                    s = d[start:j].decode("ascii")
                    strings.append((start, s))
                except Exception:
                    pass
        j += 1

    # Look for TagName→value→ValueType→Bool/Integer→BlackboardValues→value pattern
    tag_name: str | None = None
    value_type: str | None = None

    for idx, (offset, s) in enumerate(strings):
        if s == "TagName":
            # Next string is the actual key
            if idx + 1 < len(strings):
                tag_name = strings[idx + 1][1]
        elif s == "ValueType":
            if idx + 1 < len(strings):
                value_type = strings[idx + 1][1]
        elif s == "BlackboardValues":
            if idx + 1 < len(strings):
                raw_val = strings[idx + 1][1]
                if tag_name:
                    if value_type == "Bool":
                        # Bool values are stored as text payloads ("true"/"false").
                        result[tag_name] = raw_val.lower() == "true"
                    elif value_type == "Integer":
                        # The 4 bytes after "BlackboardValues\0" are metadata (length/count),
                        # not the integer value itself.  Parse only explicit numeric payload text.
                        txt = raw_val.strip()
                        if txt and (txt.isdigit() or (txt.startswith("-") and txt[1:].isdigit())):
                            result[tag_name] = int(txt)
                        elif txt.lower() in ("true", "false"):
                            # Some entries marked Integer still carry bool payloads.
                            result[tag_name] = (txt.lower() == "true")
                        else:
                            # Unknown integer encoding for this entry; skip to avoid fake enum values.
                            result[tag_name] = None
                    else:
                        result[tag_name] = raw_val
                    tag_name = None
                    value_type = None
        elif s in ("true", "false") and tag_name and value_type == "Bool":
            result[tag_name] = s == "true"
            tag_name = None
            value_type = None

    return result
