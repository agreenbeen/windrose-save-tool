"""
Ship inventory write operations with mapping confidence gating.

This module provides the ability to add item stacks to empty ship inventory slots.
All writes are gated by mapping confidence:
  - Confirmed mappings: always allowed
  - Assumed mappings: require --confirm-assumed flag
  - Unknown items: blocked until mapped

A backup is created before any write operation, and the entire ship container
is written as a single atomic blob update.
"""
from __future__ import annotations

import re
import struct
import uuid
from pathlib import Path
from typing import Any

from .backup import backup_db
from .checkpoint_zip import update_checkpoint_zip
from .coin import extract_type3_objects
from .db import open_players_db
from .save_context import resolve_player_dir
from .inventory_targets import resolve_inventory_asset_target
from .ue_parser import parse_r5_value


_ITEMSSTACK_NAME = b"ItemsStack\x00"
_ITEM_NAME = b"Item\x00"
_COUNT_NAME = b"Count\x00"
_ITEMID_NAME = b"ItemId\x00"
_ITEMPARAMS_NAME = b"ItemParams\x00"
_CHEST_SLOT_MARKER = b"/R5BusinessRules/Inventory/SlotsParams/DA_BL_Slot_Chest.DA_BL_Slot_Chest"


def _encode_fstring(text: str) -> bytes:
    raw = text.encode("utf-8") + b"\x00"
    return struct.pack("<i", len(raw)) + raw


def _decode_fstring(buf: bytes, pos: int) -> tuple[str, int]:
    size = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if size <= 0:
        return "", pos
    raw = buf[pos : pos + size]
    return raw.decode("utf-8", errors="ignore").rstrip("\x00"), pos + size


def _parse_slot_index_from_text(text: str) -> int | None:
    match = re.search(r"DA_BL_Slot_Chest\.DA_BL_Slot_Chest\.+(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def _extract_ship_chest_slots(blob: bytes) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for obj in extract_type3_objects(blob):
        if not obj.name.isdigit():
            continue

        payload = obj.payload
        if _ITEMSSTACK_NAME not in payload or _CHEST_SLOT_MARKER not in payload:
            continue

        count_pos = payload.find(_COUNT_NAME)
        itemparams_pos = payload.find(_ITEMPARAMS_NAME)
        itemid_pos = payload.find(_ITEMID_NAME)
        if count_pos == -1 or itemparams_pos == -1 or itemid_pos == -1:
            continue

        count = struct.unpack_from("<i", payload, count_pos + len(_COUNT_NAME))[0]
        item_id, _ = _decode_fstring(payload, itemid_pos + len(_ITEMID_NAME))
        item_params, _ = _decode_fstring(payload, itemparams_pos + len(_ITEMPARAMS_NAME))
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in payload)

        slots.append(
            {
                "object_id": obj.name,
                "offset": obj.offset,
                "payload_start": obj.payload_start,
                "size": obj.size,
                "end": obj.payload_start + obj.size,
                "count": count,
                "item_id": item_id,
                "item_params": item_params,
                "slot_index": _parse_slot_index_from_text(text),
                "empty": count == 0 and not item_params,
            }
        )

    slot_offsets = {s["offset"] for s in slots}
    slots = [
        s for s in slots
        if sum(1 for o in slot_offsets if s["offset"] < o < s["end"]) < 2
    ]
    return sorted(slots, key=lambda slot: slot["offset"])


def _collect_named_values(obj: Any, name: str) -> list[str]:
    values: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == name and isinstance(v, str) and v.strip():
                values.append(v.strip())
            values.extend(_collect_named_values(v, name))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_collect_named_values(item, name))
    return values


def _find_active_ship_markers(save_root: Path, captain_uuid: str | None = None) -> list[str]:
    # Priority order matters for default ship targeting.
    wanted = ("PossessedShipId", "FlagshipId", "DefaultShipId")
    markers: list[str] = []
    with open_players_db(save_root, captain_uuid=captain_uuid) as db:
        for _, blob in db.iter_cf("R5BLPlayer"):
            try:
                parsed = parse_r5_value(blob)
            except Exception:
                continue
            for key in wanted:
                for value in _collect_named_values(parsed, key):
                    if len(value) >= 8 and value not in markers:
                        markers.append(value)

            # Fallback: recover marker IDs from raw bytes near marker field names.
            for key in wanted:
                needle = key.encode("ascii", errors="ignore") + b"\x00"
                start = 0
                while True:
                    pos = blob.find(needle, start)
                    if pos == -1:
                        break
                    window = blob[pos : pos + 256].decode("latin1", errors="ignore")
                    for match in re.findall(r"[A-F0-9]{32}", window):
                        if match not in markers:
                            markers.append(match)
                    start = pos + len(needle)
    return markers


def _patch_empty_slot_object(object_bytes: bytes, *, asset_path: str, count: int) -> bytes:
    name_end = object_bytes.index(0, 1)
    size_off = name_end + 1
    payload_off = size_off + 4
    payload = object_bytes[payload_off:]

    stack_size_off = payload.index(_ITEMSSTACK_NAME) + len(_ITEMSSTACK_NAME)
    stack_size = struct.unpack_from("<I", payload, stack_size_off)[0]
    stack_blob_off = stack_size_off + 4
    stack_blob = payload[stack_blob_off : stack_blob_off + stack_size]

    item_size_off = stack_blob.index(_ITEM_NAME) + len(_ITEM_NAME)
    item_size = struct.unpack_from("<I", stack_blob, item_size_off)[0]
    item_blob_off = item_size_off + 4
    item_blob = stack_blob[item_blob_off : item_blob_off + item_size]

    itemid_len_off = item_blob.index(_ITEMID_NAME) + len(_ITEMID_NAME)
    old_itemid_len = struct.unpack_from("<i", item_blob, itemid_len_off)[0]
    old_itemid_end = itemid_len_off + 4 + old_itemid_len
    item_id = uuid.uuid4().hex.upper()
    patched_item_blob = (
        item_blob[:itemid_len_off]
        + _encode_fstring(item_id)
        + item_blob[old_itemid_end:]
    )

    itemparams_len_off = patched_item_blob.index(_ITEMPARAMS_NAME) + len(_ITEMPARAMS_NAME)
    old_itemparams_len = struct.unpack_from("<i", patched_item_blob, itemparams_len_off)[0]
    old_itemparams_end = itemparams_len_off + 4 + old_itemparams_len
    patched_item_blob = (
        patched_item_blob[:itemparams_len_off]
        + _encode_fstring(asset_path)
        + patched_item_blob[old_itemparams_end:]
    )

    patched_stack_blob = bytearray()
    patched_stack_blob += stack_blob[:item_size_off]
    patched_stack_blob += struct.pack("<I", len(patched_item_blob))
    patched_stack_blob += patched_item_blob
    patched_stack_blob += stack_blob[item_blob_off + item_size :]

    count_val_off = stack_blob.index(_COUNT_NAME) + len(_COUNT_NAME)
    struct.pack_into("<i", patched_stack_blob, count_val_off, count)

    patched_payload = bytearray()
    patched_payload += payload[:stack_size_off]
    patched_payload += struct.pack("<I", len(patched_stack_blob))
    patched_payload += patched_stack_blob
    patched_payload += payload[stack_blob_off + stack_size :]

    return object_bytes[:size_off] + struct.pack("<I", len(patched_payload)) + patched_payload


def _patch_existing_slot_object_count(object_bytes: bytes, *, count: int) -> bytes:
    """Patch only Count for an existing non-empty ship chest stack object."""
    name_end = object_bytes.index(0, 1)
    size_off = name_end + 1
    payload_off = size_off + 4
    payload = object_bytes[payload_off:]

    stack_size_off = payload.index(_ITEMSSTACK_NAME) + len(_ITEMSSTACK_NAME)
    stack_size = struct.unpack_from("<I", payload, stack_size_off)[0]
    stack_blob_off = stack_size_off + 4
    stack_blob = bytearray(payload[stack_blob_off : stack_blob_off + stack_size])

    count_val_off = stack_blob.index(_COUNT_NAME) + len(_COUNT_NAME)
    struct.pack_into("<i", stack_blob, count_val_off, int(count))

    patched_payload = bytearray()
    patched_payload += payload[:stack_size_off]
    patched_payload += struct.pack("<I", len(stack_blob))
    patched_payload += stack_blob
    patched_payload += payload[stack_blob_off + stack_size :]

    return object_bytes[:size_off] + struct.pack("<I", len(patched_payload)) + patched_payload


def _select_target_ship_blob(
    save_root: Path,
    *,
    preferred_ship_key_prefix: str | None = None,
    captain_uuid: str | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    with open_players_db(save_root, captain_uuid=captain_uuid) as db:
        for key_bytes, blob in db.iter_cf("R5BLShip"):
            slots = _extract_ship_chest_slots(blob)
            empty_slots = [slot for slot in slots if slot["empty"]]
            candidates.append(
                {
                    "cf": "R5BLShip",
                    "key_hex": key_bytes.hex(),
                    "key_text": key_bytes.decode("ascii", errors="ignore").strip("\x00"),
                    "blob": blob,
                    "slots": slots,
                    "empty_slots": empty_slots,
                }
            )

    if not candidates:
        raise RuntimeError("No ship containers found in Players DB")

    if preferred_ship_key_prefix:
        normalized = preferred_ship_key_prefix.strip().lower()
        filtered = [c for c in candidates if c["key_hex"].lower().startswith(normalized)]
        if not filtered:
            known = ", ".join(c["key_hex"][:12] for c in candidates)
            raise RuntimeError(
                "No ship container matched --ship-key-prefix "
                f"{preferred_ship_key_prefix!r}. Known prefixes: {known}"
            )
        if len(filtered) > 1:
            matched = ", ".join(c["key_hex"][:16] for c in filtered)
            raise RuntimeError(
                "--ship-key-prefix is ambiguous; matches multiple ship blobs: "
                f"{matched}"
            )
        return filtered[0]

    # Default behavior: prefer the active ship referenced by player marker IDs.
    active_markers = _find_active_ship_markers(save_root, captain_uuid=captain_uuid)
    if active_markers:
        # Most reliable mapping: marker values correspond to R5BLShip key hex.
        by_key: dict[str, dict[str, Any]] = {}
        for c in candidates:
            by_key[c["key_hex"].lower()] = c
            key_text = (c.get("key_text") or "").lower()
            if key_text:
                by_key[key_text] = c
        for marker in active_markers:
            hit = by_key.get(marker.lower())
            if hit is not None:
                return hit

        # Fallback for unusual layouts: marker appears inside blob text.
        marker_matches: list[dict[str, Any]] = []
        for candidate in candidates:
            # Latin-1 preserves byte values and is robust for substring checks.
            text = candidate["blob"].decode("latin1", errors="ignore")
            if any(marker in text for marker in active_markers):
                marker_matches.append(candidate)
        if len(marker_matches) == 1:
            return marker_matches[0]

    return max(candidates, key=lambda candidate: (len(candidate["empty_slots"]), len(candidate["slots"])))


def plan_ship_chest_additions(
    save_root: Path,
    targets: dict[str, int],
    *,
    preferred_ship_key_prefix: str | None = None,
    captain_uuid: str | None = None,
) -> dict[str, Any]:
    ship = _select_target_ship_blob(save_root, preferred_ship_key_prefix=preferred_ship_key_prefix, captain_uuid=captain_uuid)
    requested: list[dict[str, Any]] = []
    for name, amount in targets.items():
        resolved = resolve_inventory_asset_target(name)
        requested.append(
            {
                "requested": name,
                "asset_path": resolved["asset_path"],
                "count": int(amount),
                "mapping_confidence": resolved["mapping_confidence"],
                "mapping_confirmed": resolved["mapping_confirmed"],
                "mapping_source": resolved["mapping_source"],
                "manifest_path": resolved["manifest_path"],
            }
        )

    empty_slots = ship["empty_slots"]
    if len(empty_slots) < len(requested):
        raise RuntimeError(
            f"Not enough empty ship chest slots: need {len(requested)}, found {len(empty_slots)}"
        )

    plan_items = []
    for slot, req in zip(empty_slots, requested):
        plan_items.append(
            {
                "requested": req["requested"],
                "asset_path": req["asset_path"],
                "count": req["count"],
                "object_id": slot["object_id"],
                "slot_index": slot["slot_index"],
                "offset": slot["offset"],
                "mapping_confidence": req["mapping_confidence"],
                "mapping_confirmed": req["mapping_confirmed"],
                "mapping_source": req["mapping_source"],
                "manifest_path": req["manifest_path"],
            }
        )

    return {
        "cf": ship["cf"],
        "key_hex": ship["key_hex"],
        "available_empty_slots": len(empty_slots),
        "plan": plan_items,
    }


def apply_ship_chest_additions(
    save_root: Path,
    *,
    targets: dict[str, int],
    dry_run: bool = True,
    allow_assumed_assets: bool = False,
    strict_manifest: bool = False,
    preferred_ship_key_prefix: str | None = None,
    captain_uuid: str | None = None,
) -> dict[str, Any]:
    if strict_manifest:
        for target_name in targets:
            resolve_inventory_asset_target(target_name, strict_manifest=True)

    plan = plan_ship_chest_additions(
        save_root,
        targets,
        preferred_ship_key_prefix=preferred_ship_key_prefix,
        captain_uuid=captain_uuid,
    )
    assumed_items = [item for item in plan["plan"] if not item["mapping_confirmed"]]
    if assumed_items and not (dry_run or allow_assumed_assets):
        names = ", ".join(sorted({item["requested"] for item in assumed_items}))
        raise RuntimeError(
            "Refusing write because some targets use assumed item IDs: "
            f"{names}. Re-run with --confirm-assumed to proceed intentionally."
        )
    key_bytes = bytes.fromhex(plan["key_hex"])

    with open_players_db(save_root, captain_uuid=captain_uuid) as db:
        original_blob = db.get(plan["cf"], key_bytes)
    if original_blob is None:
        raise RuntimeError("Ship container disappeared before update")

    slot_map = {slot["offset"]: slot for slot in _extract_ship_chest_slots(original_blob) if slot["empty"]}
    mutable_blob = bytearray(original_blob)

    applied: list[dict[str, Any]] = []
    for item in sorted(plan["plan"], key=lambda entry: entry["offset"], reverse=True):
        slot = slot_map[item["offset"]]
        object_bytes = original_blob[slot["offset"] : slot["end"]]
        patched_object = _patch_empty_slot_object(
            object_bytes,
            asset_path=item["asset_path"],
            count=item["count"],
        )
        mutable_blob[slot["offset"] : slot["end"]] = patched_object
        applied.append(item)

    if len(mutable_blob) >= 4:
        struct.pack_into("<I", mutable_blob, 0, len(mutable_blob))

    verified_slots = _extract_ship_chest_slots(bytes(mutable_blob))
    for item in plan["plan"]:
        matched = next(
            (
                slot
                for slot in verified_slots
                if slot["item_params"] == item["asset_path"] and slot["count"] == item["count"]
            ),
            None,
        )
        if matched is None:
            raise RuntimeError(
                f"Verification failed for {item['requested']}: slot was not readable after patch"
            )

    result = {
        "cf": plan["cf"],
        "key_hex": plan["key_hex"],
        "dry_run": dry_run,
        "planned_updates": plan["plan"],
        "assumed_mappings": [
            {
                "requested": item["requested"],
                "asset_path": item["asset_path"],
                "mapping_source": item.get("mapping_source"),
            }
            for item in assumed_items
        ],
        "backup_path": None,
        "new_blob_size": len(mutable_blob),
    }

    if dry_run:
        return result

    db_dir = resolve_player_dir(save_root, captain_uuid)
    backup_path = backup_db(db_dir)
    try:
        with open_players_db(save_root, read_only=False, captain_uuid=captain_uuid) as db:
            db.put(plan["cf"], key_bytes, bytes(mutable_blob))
    except Exception as exc:
        message = str(exc)
        if "lock file" in message.lower():
            raise RuntimeError(
                "Players DB is locked by another process. Close the game and any save-sync tool, "
                "then retry the write. The backup created for this attempt remains available."
            ) from exc
        raise
    update_checkpoint_zip(save_root, db_dir)
    result["backup_path"] = str(backup_path)
    return result


def plan_ship_chest_count_update(
    save_root: Path,
    *,
    target: str,
    new_count: int,
    expected_current_count: int | None = None,
    update_all_matches: bool = False,
    strict_manifest: bool = False,
    preferred_ship_key_prefix: str | None = None,
    captain_uuid: str | None = None,
) -> dict[str, Any]:
    """
    Plan a count-only update for existing ship chest stack(s).

    Matching is by resolved asset path and optional expected current count.
    The plan keeps physical duplicate records together per logical stack key.
    """
    resolved = resolve_inventory_asset_target(target, strict_manifest=strict_manifest)
    asset_path = resolved["asset_path"]

    physical_matches: list[dict[str, Any]] = []
    normalized_prefix = preferred_ship_key_prefix.strip().lower() if preferred_ship_key_prefix else None
    with open_players_db(save_root, captain_uuid=captain_uuid) as db:
        for key_bytes, blob in db.iter_cf("R5BLShip"):
            key_hex = key_bytes.hex()
            if normalized_prefix and not key_hex.lower().startswith(normalized_prefix):
                continue
            for slot in _extract_ship_chest_slots(blob):
                if slot["empty"]:
                    continue
                if slot["item_params"] != asset_path:
                    continue
                if expected_current_count is not None and int(slot["count"]) != int(expected_current_count):
                    continue
                physical_matches.append(
                    {
                        "cf": "R5BLShip",
                        "key_hex": key_hex,
                        **slot,
                    }
                )

    if not physical_matches:
        count_note = (
            f" with current_count={expected_current_count}" if expected_current_count is not None else ""
        )
        raise RuntimeError(
            f"No matching ship stack found for {target!r} -> {asset_path}{count_note}."
        )

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for match in physical_matches:
        logical_key = (
            match["cf"],
            match["key_hex"],
            match.get("item_id") or f"obj:{match['object_id']}",
            match["item_params"],
            match.get("slot_index"),
            int(match["count"]),
        )
        grouped.setdefault(logical_key, []).append(match)

    logical_groups = sorted(
        grouped.values(),
        key=lambda grp: (
            grp[0]["key_hex"],
            grp[0].get("slot_index") if grp[0].get("slot_index") is not None else 9999,
            grp[0]["offset"],
        ),
    )

    if not update_all_matches and len(logical_groups) > 1:
        raise RuntimeError(
            "Multiple logical stacks matched target. Re-run with --all-matches or narrow with --current-count."
        )

    selected_groups = logical_groups if update_all_matches else logical_groups[:1]

    plan: list[dict[str, Any]] = []
    for grp in selected_groups:
        primary = grp[0]
        plan.append(
            {
                "requested": target,
                "asset_path": asset_path,
                "mapping_confidence": resolved["mapping_confidence"],
                "mapping_confirmed": resolved["mapping_confirmed"],
                "mapping_source": resolved["mapping_source"],
                "manifest_path": resolved["manifest_path"],
                "cf": primary["cf"],
                "key_hex": primary["key_hex"],
                "slot_index": primary.get("slot_index"),
                "item_id": primary.get("item_id"),
                "current_count": int(primary["count"]),
                "new_count": int(new_count),
                "object_ids": sorted({entry["object_id"] for entry in grp}),
                "physical_offsets": sorted(entry["offset"] for entry in grp),
                "physical_record_count": len(grp),
            }
        )

    return {
        "target": target,
        "asset_path": asset_path,
        "new_count": int(new_count),
        "expected_current_count": expected_current_count,
        "update_all_matches": update_all_matches,
        "match_count_physical": len(physical_matches),
        "match_count_logical": len(logical_groups),
        "plan": plan,
    }


def apply_ship_chest_count_update(
    save_root: Path,
    *,
    target: str,
    new_count: int,
    expected_current_count: int | None = None,
    update_all_matches: bool = False,
    dry_run: bool = True,
    strict_manifest: bool = False,
    preferred_ship_key_prefix: str | None = None,
    captain_uuid: str | None = None,
) -> dict[str, Any]:
    """Apply a count-only update for existing ship chest stacks."""
    plan_result = plan_ship_chest_count_update(
        save_root,
        target=target,
        new_count=new_count,
        expected_current_count=expected_current_count,
        update_all_matches=update_all_matches,
        strict_manifest=strict_manifest,
        preferred_ship_key_prefix=preferred_ship_key_prefix,
        captain_uuid=captain_uuid,
    )

    plans = plan_result["plan"]
    result: dict[str, Any] = {
        **plan_result,
        "dry_run": dry_run,
        "backup_path": None,
    }
    if dry_run:
        return result

    by_blob: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in plans:
        by_blob.setdefault((p["cf"], p["key_hex"]), []).append(p)

    with open_players_db(save_root, captain_uuid=captain_uuid) as db:
        originals = {
            (cf, key_hex): db.get(cf, bytes.fromhex(key_hex))
            for (cf, key_hex) in by_blob
        }

    patched_blobs: dict[tuple[str, str], bytes] = {}
    for (cf, key_hex), updates in by_blob.items():
        original_blob = originals[(cf, key_hex)]
        if original_blob is None:
            raise RuntimeError(f"Ship container {key_hex} disappeared before update")

        mutable_blob = bytearray(original_blob)
        for update in updates:
            offsets = sorted((int(o) for o in update["physical_offsets"]), reverse=True)
            slot_map = {slot["offset"]: slot for slot in _extract_ship_chest_slots(original_blob)}
            for off in offsets:
                slot = slot_map.get(off)
                if slot is None:
                    raise RuntimeError(f"Offset {off} not found during patch for {update['requested']}")
                object_bytes = original_blob[slot["offset"] : slot["end"]]
                patched_object = _patch_existing_slot_object_count(
                    object_bytes,
                    count=int(update["new_count"]),
                )
                mutable_blob[slot["offset"] : slot["end"]] = patched_object

        if len(mutable_blob) >= 4:
            struct.pack_into("<I", mutable_blob, 0, len(mutable_blob))

        verified_slots = _extract_ship_chest_slots(bytes(mutable_blob))
        for update in updates:
            found = [
                s
                for s in verified_slots
                if s["item_params"] == update["asset_path"]
                and (s.get("item_id") or "") == (update.get("item_id") or "")
                and int(s["count"]) == int(update["new_count"])
            ]
            if not found:
                raise RuntimeError(
                    f"Verification failed for {update['requested']} (item_id={update.get('item_id')})"
                )

        patched_blobs[(cf, key_hex)] = bytes(mutable_blob)

    db_dir = resolve_player_dir(save_root, captain_uuid)
    backup_path = backup_db(db_dir)
    try:
        with open_players_db(save_root, read_only=False, captain_uuid=captain_uuid) as dbw:
            for (cf, key_hex), blob in patched_blobs.items():
                dbw.put(cf, bytes.fromhex(key_hex), blob)
    except Exception as exc:
        message = str(exc)
        if "lock file" in message.lower():
            raise RuntimeError(
                "Players DB is locked by another process. Close the game and any save-sync tool, "
                "then retry the write. The backup created for this attempt remains available."
            ) from exc
        raise
    update_checkpoint_zip(save_root, db_dir)
    result["backup_path"] = str(backup_path)
    return result