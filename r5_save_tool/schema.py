"""
Schema analysis: attempt to decode raw RocksDB key/value bytes into human-readable form.

Values in R5 are likely Unreal Engine binary-serialized structs, but we can still
surface all printable strings and numeric patterns embedded in them.

Analysis strategy (most to least structured):
  1. Try UTF-8 / UTF-16LE text decode (JSON or plain string keys/values)
  2. Scan for embedded printable ASCII runs (field names, asset paths, enum labels)
  3. Extract candidate numeric fields (4- and 8-byte little-endian int/float)
  4. Report raw hex for opaque blobs
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any


# Minimum run of printable ASCII bytes to report as a string fragment
_MIN_STRING_RUN = 4
_PRINTABLE = re.compile(rb'[ -~]{%d,}' % _MIN_STRING_RUN)

# UE4/5 FName-style length-prefixed string pattern (uint16 LE length, then bytes)
_MAX_UE_STRING = 2048


@dataclass
class DecodedValue:
    raw: bytes
    text: str | None = None          # if the whole value is printable text / JSON
    strings: list[str] = field(default_factory=list)  # embedded string fragments
    numerics: list[tuple[int, Any]] = field(default_factory=list)  # (offset, value)
    hex_preview: str = ""


def decode_key(raw: bytes) -> str:
    """Best-effort key decode — keys are usually ASCII strings or UUIDs."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.hex()


def decode_value(raw: bytes) -> DecodedValue:
    result = DecodedValue(raw=raw)

    # --- Try whole-value text decode first ---
    for enc in ("utf-8", "utf-16-le"):
        try:
            text = raw.decode(enc).strip("\x00")
            if text.isprintable() or enc == "utf-8":
                result.text = text
                return result
        except (UnicodeDecodeError, ValueError):
            pass

    # --- Embedded printable string fragments ---
    result.strings = [m.group().decode("ascii", errors="replace") for m in _PRINTABLE.finditer(raw)]

    # --- Candidate numeric fields (every 4-byte boundary) ---
    numerics: list[tuple[int, Any]] = []
    for offset in range(0, len(raw) - 3, 4):
        chunk = raw[offset : offset + 4]
        i32 = struct.unpack_from("<i", chunk)[0]
        f32 = struct.unpack_from("<f", chunk)[0]
        # Only surface values that look "interesting"
        if 0 < i32 < 1_000_000:
            numerics.append((offset, f"int32={i32}"))
        elif -1.0e6 < f32 < 1.0e6 and f32 != 0.0 and not (0.999 < abs(f32) < 1.001):
            numerics.append((offset, f"float32={f32:.4f}"))
    result.numerics = numerics[:32]  # cap to avoid noise

    # --- Hex preview (first 128 bytes) ---
    result.hex_preview = raw[:128].hex(" ")

    return result


def format_decoded(key_raw: bytes, value_raw: bytes, cf_name: str) -> str:
    """Format a single key-value pair as a human-readable block."""
    key_str = decode_key(key_raw)
    val = decode_value(value_raw)
    lines = [f"  [{cf_name}] key={key_str!r}  ({len(value_raw)} bytes)"]

    if val.text is not None:
        # Truncate very long text
        preview = val.text if len(val.text) <= 512 else val.text[:512] + "…"
        lines.append(f"    value (text): {preview}")
    else:
        if val.strings:
            lines.append(f"    strings: {val.strings}")
        if val.numerics:
            lines.append(f"    numerics: {val.numerics}")
        lines.append(f"    hex[0:128]: {val.hex_preview}")

    return "\n".join(lines)
