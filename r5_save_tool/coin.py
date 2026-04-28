"""
Coin inspection helpers.

Scans R5BLPlayer and R5BLShip blobs, identifies coin item objects,
and attempts to resolve amount/count fields using stack-style
counter objects.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import open_players_db
from .ue_parser import _Buf, _parse_records


@dataclass
class ObjectRecord:
    name: str
    offset: int
    payload_start: int
    size: int
    payload: bytes
    parsed: dict[str, Any]


def _read_cstring(data: bytes, start: int, max_len: int = 80) -> tuple[str | None, int]:
    j = start
    while j < len(data) and data[j] != 0 and (j - start) <= max_len:
        b = data[j]
        if b < 0x20 or b > 0x7E:
            return None, start
        j += 1
    if j >= len(data) or data[j] != 0 or j == start:
        return None, start
    return data[start:j].decode("ascii", errors="ignore"), j + 1


def extract_type3_objects(blob: bytes) -> list[ObjectRecord]:
    """Extract all top-level type=0x03 objects that have ASCII names."""
    out: list[ObjectRecord] = []
    i = 0
    n = len(blob)
    while i < n - 6:
        if blob[i] != 0x03:
            i += 1
            continue

        name, name_end = _read_cstring(blob, i + 1)
        if not name:
            i += 1
            continue
        if name_end + 4 > n:
            i += 1
            continue

        size = struct.unpack_from("<I", blob, name_end)[0]
        payload_start = name_end + 4
        payload_end = payload_start + size
        if size <= 0 or payload_end > n:
            i += 1
            continue

        payload = blob[payload_start:payload_end]
        try:
            parsed = _parse_records(_Buf(payload), len(payload), 1)
        except Exception:
            parsed = {}

        out.append(
            ObjectRecord(
                name=name,
                offset=i,
                payload_start=payload_start,
                size=size,
                payload=payload,
                parsed=parsed,
            )
        )
        i += 1
    return out


def _parse_fields_with_offsets(payload: bytes, base_abs_offset: int) -> list[dict[str, Any]]:
    """
    Parse fields and record absolute byte offsets of writable int32 values.
    """
    fields: list[dict[str, Any]] = []
    b = _Buf(payload)
    end = len(payload)

    while b.pos < end and b.remaining >= 2:
        field_start = b.pos
        t = b.read_u8()
        if t == 0x00:
            break
        name = b.read_null_str()
        if not name:
            break

        value: Any = None
        int_offset: int | None = None

        if t == 0x02:
            if b.remaining >= 4:
                value = b.read_fstring()
        elif t in (0x04, 0x05):
            if b.remaining >= 5:
                int_offset = base_abs_offset + b.pos
                value = b.read_i32()
                b.read(1)
        elif t == 0x10:
            if b.remaining >= 4:
                int_offset = base_abs_offset + b.pos
                value = b.read_i32()
        elif t == 0x03:
            if b.remaining >= 4:
                size = b.read_u32()
                if b.remaining >= size:
                    nested_abs = base_abs_offset + b.pos
                    nested = b.read(size)
                    value = f"<obj {size}B>"
                    # Flatten nested fields using parent.field path for linkage.
                    for nf in _parse_fields_with_offsets(nested, nested_abs):
                        nested_name = f"{name}.{nf['name']}"
                        fields.append(
                            {
                                "name": nested_name,
                                "type": nf["type"],
                                "value": nf["value"],
                                "int_offset": nf.get("int_offset"),
                                "field_start": nf.get("field_start"),
                            }
                        )
                else:
                    value = None
        else:
            if b.remaining >= 4:
                size = b.read_u32()
                if 0 < size <= b.remaining:
                    b.read(size)
                    value = f"<t{t:02x} {size}B>"
                else:
                    break

        fields.append(
            {
                "name": name,
                "type": t,
                "value": value,
                "int_offset": int_offset,
                "field_start": base_abs_offset + field_start,
            }
        )

    return fields


def _is_counter_tag(tag_name: str) -> bool:
    """Return True for counter-like inventory attribute tag names."""
    if tag_name == "Inventory.Item.Attribute.Counter":
        return True
    if tag_name.endswith(".Counter"):
        return True
    return "Attribute.Counter" in tag_name


def _inspect_blob(blob: bytes) -> dict[str, Any]:
    objects = extract_type3_objects(blob)
    numeric_objects: list[ObjectRecord] = [o for o in objects if o.name.isdigit()]

    counter_objects: list[dict[str, Any]] = []
    for obj in numeric_objects:
        fields = _parse_fields_with_offsets(obj.payload, obj.payload_start)
        tag_name = None
        value = None
        value_offset = None
        max_value = None
        max_value_offset = None
        for f in fields:
            leaf = f["name"].split(".")[-1]
            if leaf == "TagName" and isinstance(f["value"], str):
                tag_name = f["value"]
            elif leaf == "Value" and isinstance(f["value"], int):
                value = f["value"]
                value_offset = f["int_offset"]
            elif leaf == "MaxValue" and isinstance(f["value"], int):
                max_value = f["value"]
                max_value_offset = f["int_offset"]

        if tag_name:
            counter_objects.append(
                {
                    "object_id": obj.name,
                    "offset": obj.offset,
                    "tag_name": tag_name,
                    "value": value,
                    "value_offset": value_offset,
                    "max_value": max_value,
                    "max_value_offset": max_value_offset,
                }
            )

    stack_counters = [
        c
        for c in counter_objects
        if isinstance(c.get("tag_name"), str) and _is_counter_tag(c["tag_name"])
    ]

    coin_items: list[dict[str, Any]] = []
    for obj in numeric_objects:
        fields = _parse_fields_with_offsets(obj.payload, obj.payload_start)

        item_params = None
        item_id = None
        attrs_ref = None
        effects_ref = None
        for f in fields:
            if f["name"].endswith("ItemParams") and isinstance(f["value"], str):
                item_params = f["value"]
            elif f["name"].endswith("ItemId") and isinstance(f["value"], str):
                item_id = f["value"]
            elif f["name"].endswith("Attributes") and isinstance(f["value"], int):
                attrs_ref = f["value"]
            elif f["name"].endswith("Effects") and isinstance(f["value"], int):
                effects_ref = f["value"]

        if not isinstance(item_params, str):
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in obj.payload)
            marker = "/R5BusinessRules/InventoryItems"
            p = text.find(marker)
            if p != -1:
                q = text.find("\x00", p)
                if q == -1:
                    q = min(len(text), p + 240)
                item_params = text[p:q].strip(".")

        if not isinstance(item_params, str):
            continue
        if "CoinGuinea" not in item_params and "CoinPiastre" not in item_params:
            continue

        linked_counter = None
        confidence = "low"

        if attrs_ref is not None:
            aid = str(attrs_ref)
            same_id = [c for c in stack_counters if c["object_id"] == aid]
            if same_id:
                # Prefer exact references that also expose a writable Value field.
                linked_counter = min(
                    same_id,
                    key=lambda c: (c.get("value") is None, abs(c["offset"] - obj.offset)),
                )
                confidence = "high"

        if linked_counter is None and stack_counters:
            with_value = [c for c in stack_counters if c.get("value") is not None]
            nearest_pool = with_value if with_value else stack_counters
            nearest = min(nearest_pool, key=lambda c: abs(c["offset"] - obj.offset))
            distance = abs(nearest["offset"] - obj.offset)
            if distance <= 900:
                linked_counter = nearest
                confidence = "medium"

        inferred_amount = None
        inferred_amount_offset = None
        max_amount = None
        max_amount_offset = None
        quantity_model = "unknown"

        if linked_counter is not None:
            inferred_amount = linked_counter.get("value")
            inferred_amount_offset = linked_counter.get("value_offset")
            max_amount = linked_counter.get("max_value")
            max_amount_offset = linked_counter.get("max_value_offset")
            quantity_model = "stack_counter"

        if inferred_amount is None:
            same_type_count = sum(
                1
                for o in numeric_objects
                if isinstance(o.parsed.get("ItemParams"), str)
                and o.parsed.get("ItemParams") == item_params
            )
            if same_type_count == 0:
                marker = "CoinGuinea" if "CoinGuinea" in item_params else "CoinPiastre"
                same_type_count = sum(1 for o in numeric_objects if marker.encode("ascii") in o.payload)
            inferred_amount = same_type_count
            quantity_model = "entry_count"
            confidence = "medium" if same_type_count > 0 else "low"

        coin_items.append(
            {
                "coin_type": "CoinGuinea" if "CoinGuinea" in item_params else "CoinPiastre",
                "object_id": obj.name,
                "offset": obj.offset,
                "item_id": item_id,
                "item_params": item_params,
                "attributes_ref": attrs_ref,
                "effects_ref": effects_ref,
                "linked_counter": linked_counter,
                "inferred_amount": inferred_amount,
                "inferred_amount_offset": inferred_amount_offset,
                "inferred_max": max_amount,
                "inferred_max_offset": max_amount_offset,
                "quantity_model": quantity_model,
                "confidence": confidence,
            }
        )

    return {
        "blob_size": len(blob),
        "objects_total": len(objects),
        "numeric_objects": len(numeric_objects),
        "counter_objects": counter_objects,
        "coin_items": sorted(coin_items, key=lambda x: x["offset"]),
    }


def inspect_coins(save_root: Path, out_path: Path | None = None) -> dict[str, Any]:
    """Inspect coin data for player and ship containers and return an analysis dict."""
    containers: list[dict[str, Any]] = []
    all_coin_items: list[dict[str, Any]] = []

    with open_players_db(save_root) as db:
        for cf_name in ("R5BLPlayer", "R5BLShip"):
            for key_bytes, val_bytes in db.iter_cf(cf_name):
                blob_result = _inspect_blob(val_bytes)
                container = {
                    "cf": cf_name,
                    "key_hex": key_bytes.hex(),
                    **blob_result,
                }
                containers.append(container)

                for item in blob_result["coin_items"]:
                    all_coin_items.append(
                        {
                            "cf": cf_name,
                            "key_hex": key_bytes.hex(),
                            **item,
                        }
                    )

    if not containers:
        raise RuntimeError("No player containers found in Players DB")

    result = {
        "containers": containers,
        "coin_items": all_coin_items,
        "notes": [
            "confidence=high means coin attributes reference resolved directly to a counter object",
            "confidence=medium means nearest counter fallback was used",
            "confidence=low means no counter linkage found",
            "offsets are absolute byte offsets inside each container value blob",
        ],
    }

    if out_path is not None:
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    return result


def _find_coin_objects(blob: bytes) -> list[dict[str, Any]]:
    coins: list[dict[str, Any]] = []
    for obj in extract_type3_objects(blob):
        if not obj.name.isdigit() or obj.name == "0":
            continue
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in obj.payload)
        if "CoinPiastre" in text:
            coins.append({"coin_type": "CoinPiastre", "object_id": obj.name, "offset": obj.offset})
        elif "CoinGuinea" in text:
            coins.append({"coin_type": "CoinGuinea", "object_id": obj.name, "offset": obj.offset})
    return coins


def _find_value_offsets(blob: bytes, value: int) -> list[int]:
    pattern = struct.pack("<i", value)
    out: list[int] = []
    start = 0
    while True:
        pos = blob.find(pattern, start)
        if pos == -1:
            break
        out.append(pos)
        start = pos + 1
    return out


def _confidence_rank(confidence: str | None) -> int:
    if confidence == "high":
        return 0
    if confidence == "medium":
        return 1
    return 2


def _find_candidate_from_inspection(
    *,
    container: dict[str, Any],
    coin_type: str,
    known_value: int,
    label: str,
) -> dict[str, Any] | None:
    """
    Prefer offsets resolved through coin-object -> counter linkage over raw int32 proximity.
    """
    inspected = container.get("inspected") or {}
    items = inspected.get("coin_items") or []
    candidates: list[dict[str, Any]] = []

    for item in items:
        if item.get("coin_type") != coin_type:
            continue
        if item.get("inferred_amount") != known_value:
            continue
        value_offset = item.get("inferred_amount_offset")
        if value_offset is None:
            continue

        coin_offset = int(item.get("offset", 0))
        candidates.append(
            {
                "label": label,
                "cf": container["cf"],
                "key_hex": container["key_hex"],
                "coin_type": coin_type,
                "coin_object_id": item.get("object_id"),
                "coin_offset": coin_offset,
                "known_value": known_value,
                "value_offset": int(value_offset),
                "distance": abs(int(value_offset) - coin_offset),
                "confidence": item.get("confidence", "low"),
                "source": "inspection_linked",
            }
        )

    if not candidates:
        return None

    return min(candidates, key=lambda c: (_confidence_rank(c.get("confidence")), c["distance"]))


def map_coin_offsets_by_known_values(
    save_root: Path,
    *,
    person_piastre: int,
    person_guinea: int,
    ship_piastre: int,
    ship_guinea: int,
) -> dict[str, Any]:
    """
    Locate candidate writable int32 offsets for coin amounts using known current values.
    """
    targets = [
        ("person_piastre", "R5BLPlayer", "CoinPiastre", person_piastre),
        ("person_guinea", "R5BLPlayer", "CoinGuinea", person_guinea),
        ("ship_piastre", "R5BLShip", "CoinPiastre", ship_piastre),
        ("ship_guinea", "R5BLShip", "CoinGuinea", ship_guinea),
    ]

    entries: dict[str, list[dict[str, Any]]] = {"R5BLPlayer": [], "R5BLShip": []}
    with open_players_db(save_root) as db:
        for cf_name in ("R5BLPlayer", "R5BLShip"):
            for key_bytes, val_bytes in db.iter_cf(cf_name):
                inspected = _inspect_blob(val_bytes)
                entries[cf_name].append(
                    {
                        "cf": cf_name,
                        "key_hex": key_bytes.hex(),
                        "key_bytes": key_bytes,
                        "blob": val_bytes,
                        "coins": _find_coin_objects(val_bytes),
                        "inspected": inspected,
                    }
                )

    mappings: dict[str, dict[str, Any] | None] = {}
    for label, cf_name, coin_type, known_value in targets:
        best: dict[str, Any] | None = None
        for entry in entries.get(cf_name, []):
            linked = _find_candidate_from_inspection(
                container=entry,
                coin_type=coin_type,
                known_value=known_value,
                label=label,
            )
            if linked is not None:
                if best is None or (_confidence_rank(linked.get("confidence")), linked["distance"]) < (
                    _confidence_rank(best.get("confidence")),
                    best["distance"],
                ):
                    best = linked

            # Fallback path: nearest raw int32 match to coin object offset.
            if not entry["coins"]:
                continue
            value_offsets = _find_value_offsets(entry["blob"], known_value)
            if not value_offsets:
                continue
            for coin in entry["coins"]:
                if coin["coin_type"] != coin_type:
                    continue
                nearest = min(value_offsets, key=lambda o: abs(o - coin["offset"]))
                distance = abs(nearest - coin["offset"])
                candidate = {
                    "label": label,
                    "cf": cf_name,
                    "key_hex": entry["key_hex"],
                    "coin_type": coin_type,
                    "coin_object_id": coin["object_id"],
                    "coin_offset": coin["offset"],
                    "known_value": known_value,
                    "value_offset": nearest,
                    "distance": distance,
                    "confidence": (
                        "high"
                        if distance <= 64
                        else "medium" if distance <= 512 else "low"
                    ),
                    "source": "fallback_raw",
                }
                if best is None or (
                    _confidence_rank(candidate.get("confidence")),
                    candidate["distance"],
                    candidate["coin_offset"],
                ) < (
                    _confidence_rank(best.get("confidence")),
                    best["distance"],
                    best["coin_offset"],
                ):
                    best = candidate

        if best is not None:
            if "confidence" not in best:
                if best["distance"] <= 64:
                    best["confidence"] = "high"
                elif best["distance"] <= 512:
                    best["confidence"] = "medium"
                else:
                    best["confidence"] = "low"
        mappings[label] = best

    result = {
        "mappings": mappings,
        "notes": [
            "Mappings prefer inspection-linked counter offsets when available.",
            "Fallback uses nearest raw int32 offset matching known calibration value.",
            "confidence=high uses <=64 byte proximity between coin object and located int32 value.",
        ],
    }
    return result


def apply_coin_values(
    save_root: Path,
    *,
    known_person_piastre: int,
    known_person_guinea: int,
    known_ship_piastre: int,
    known_ship_guinea: int,
    new_person_piastre: int | None,
    new_person_guinea: int | None,
    new_ship_piastre: int | None,
    new_ship_guinea: int | None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Apply calibrated coin updates directly to mapped int32 offsets.

    Safety is enforced by the calibration check: the field at the mapped offset
    must contain the known_value before patching. The backup is created before
    any write is applied.
    """
    mapping = map_coin_offsets_by_known_values(
        save_root,
        person_piastre=known_person_piastre,
        person_guinea=known_person_guinea,
        ship_piastre=known_ship_piastre,
        ship_guinea=known_ship_guinea,
    )

    desired = {
        "person_piastre": new_person_piastre,
        "person_guinea": new_person_guinea,
        "ship_piastre": new_ship_piastre,
        "ship_guinea": new_ship_guinea,
    }

    updates: list[dict[str, Any]] = []
    with open_players_db(save_root) as db:
        for label, new_val in desired.items():
            if new_val is None:
                continue
            hit = mapping["mappings"].get(label)
            if not hit:
                raise RuntimeError(f"No mapping found for {label}")

            key_bytes = bytes.fromhex(hit["key_hex"])
            blob = db.get(hit["cf"], key_bytes)
            if blob is None:
                raise RuntimeError(f"Missing live blob for {label}")
            off = int(hit["value_offset"])
            if off + 4 > len(blob):
                raise RuntimeError(f"Out-of-range offset for {label}: {off}")

            old_val = struct.unpack_from("<i", blob, off)[0]
            if old_val != int(hit["known_value"]):
                raise RuntimeError(
                    f"Calibration mismatch for {label}: expected {hit['known_value']} at offset {off}, found {old_val}"
                )

            updates.append(
                {
                    "label": label,
                    "cf": hit["cf"],
                    "key_hex": hit["key_hex"],
                    "offset": off,
                    "old_value": old_val,
                    "new_value": int(new_val),
                    "confidence": hit["confidence"],
                }
            )

    if not dry_run and updates:
        from .backup import backup_db
        from .db import _locate_single_subdir

        db_dir = _locate_single_subdir(save_root / "Players")
        backup_path = backup_db(db_dir)

        by_blob: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for u in updates:
            by_blob.setdefault((u["cf"], u["key_hex"]), []).append(u)

        with open_players_db(save_root, read_only=False) as dbw:
            for (cf_name, key_hex), blob_updates in by_blob.items():
                key_bytes = bytes.fromhex(key_hex)
                raw = dbw.get(cf_name, key_bytes)
                if raw is None:
                    raise RuntimeError(f"Cannot write missing blob [{cf_name}] {key_hex}")
                patched = bytearray(raw)
                for u in blob_updates:
                    struct.pack_into("<i", patched, int(u["offset"]), int(u["new_value"]))
                dbw.put(cf_name, key_bytes, bytes(patched))

        return {
            "dry_run": False,
            "backup_path": str(backup_path),
            "mapping": mapping,
            "updates": updates,
        }

    return {
        "dry_run": True,
        "mapping": mapping,
        "updates": updates,
    }
