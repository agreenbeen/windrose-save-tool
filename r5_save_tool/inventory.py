"""
Inventory inspection and stage-planning helpers.

This module provides discovery for current item stacks/counts across player and
ship containers and a stage planner that respects slot constraints.
"""
from __future__ import annotations

import math
import re
import struct
from pathlib import Path
from typing import Any

from .coin import _parse_fields_with_offsets, extract_type3_objects
from .db import open_players_db
from .inventory_targets import normalize_inventory_name, resolve_inventory_asset_target
from .ue_parser import parse_r5_value


_ITEM_ASSET_RE = re.compile(
    r"(/R5BusinessRules/InventoryItems/(?:[^./]+/)*[A-Za-z0-9_]+\.[A-Za-z0-9_]+)"
)
_SLOT_ASSET_RE = re.compile(
    r"(/R5BusinessRules/Inventory/SlotsParams/(?:[^./]+/)*[A-Za-z0-9_]+\.[A-Za-z0-9_]+)"
)

_ITEMSSTACK_NAME = b"ItemsStack\x00"
_ITEM_NAME = b"Item\x00"
_COUNT_NAME = b"Count\x00"
_ITEMID_NAME = b"ItemId\x00"
_ITEMPARAMS_NAME = b"ItemParams\x00"


# ---------------------------------------------------------------------------
# Ship name extraction helpers (inline to avoid circular import with report.py)
# ---------------------------------------------------------------------------

def _inv_find_first_string_key_like(obj: Any, key_fragment: str) -> str | None:
    """Recursively find the first string value whose key contains key_fragment."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if key_fragment.lower() in str(k).lower() and isinstance(v, str) and v:
                return v
            found = _inv_find_first_string_key_like(v, key_fragment)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _inv_find_first_string_key_like(item, key_fragment)
            if found:
                return found
    return None


def _inv_extract_ship_name_from_blob(blob: bytes) -> str | None:
    """Extract the ship custom name from a raw R5BLShip blob."""
    tag = b"ShipName\x00"
    try:
        idx = blob.find(tag)
        if idx < 0:
            return None
        length_offset = idx + len(tag)
        if length_offset + 4 > len(blob):
            return None
        length = struct.unpack("<I", blob[length_offset:length_offset + 4])[0]
        string_offset = length_offset + 4
        if string_offset + length > len(blob):
            return None
        name = blob[string_offset:string_offset + length].rstrip(b"\x00").decode("utf-8", errors="ignore")
        return name if name else None
    except (struct.error, UnicodeDecodeError, ValueError):
        return None


def _inv_extract_ship_type_from_refs(obj: Any, depth: int = 0) -> str | None:
    """Extract ship type label (e.g. 'Ketch') from asset references like DA_Ship_Ketch."""
    if depth > 8:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and "DA_Ship_" in v:
                m = re.search(r"DA_Ship_(\w+)", v)
                if m:
                    return m.group(1)
            if isinstance(v, (dict, list)):
                result = _inv_extract_ship_type_from_refs(v, depth + 1)
                if result:
                    return result
    elif isinstance(obj, list):
        for item in obj:
            result = _inv_extract_ship_type_from_refs(item, depth + 1)
            if result:
                return result
    return None


def _decode_fstring_bytes(buf: bytes, pos: int) -> tuple[str | None, int]:
    if pos + 4 > len(buf):
        return None, pos
    size = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if size <= 0:
        return "", pos
    end = pos + size
    if end > len(buf):
        return None, pos
    raw = buf[pos:end]
    return raw.decode("utf-8", errors="ignore").rstrip("\x00"), end


def _extract_itemsstack_fields(payload: bytes) -> dict[str, Any]:
    """Extract count/item fields directly from ItemsStack binary structure."""
    result: dict[str, Any] = {
        "count": None,
        "item_id": None,
        "item_params": None,
        "max_value": None,
    }

    try:
        stack_size_off = payload.index(_ITEMSSTACK_NAME) + len(_ITEMSSTACK_NAME)
        if stack_size_off + 4 > len(payload):
            return result
        stack_size = struct.unpack_from("<I", payload, stack_size_off)[0]
        stack_blob_off = stack_size_off + 4
        stack_blob_end = stack_blob_off + stack_size
        if stack_blob_end > len(payload):
            return result
        stack_blob = payload[stack_blob_off:stack_blob_end]

        count_pos = stack_blob.find(_COUNT_NAME)
        if count_pos != -1 and count_pos + len(_COUNT_NAME) + 4 <= len(stack_blob):
            result["count"] = struct.unpack_from("<i", stack_blob, count_pos + len(_COUNT_NAME))[0]

        item_size_off = stack_blob.find(_ITEM_NAME)
        if item_size_off == -1:
            return result
        item_size_off += len(_ITEM_NAME)
        if item_size_off + 4 > len(stack_blob):
            return result
        item_size = struct.unpack_from("<I", stack_blob, item_size_off)[0]
        item_blob_off = item_size_off + 4
        item_blob_end = item_blob_off + item_size
        if item_blob_end > len(stack_blob):
            return result
        item_blob = stack_blob[item_blob_off:item_blob_end]

        itemid_pos = item_blob.find(_ITEMID_NAME)
        if itemid_pos != -1:
            itemid_pos += len(_ITEMID_NAME)
            decoded_item_id, _ = _decode_fstring_bytes(item_blob, itemid_pos)
            if isinstance(decoded_item_id, str):
                result["item_id"] = decoded_item_id

        itemparams_pos = item_blob.find(_ITEMPARAMS_NAME)
        if itemparams_pos != -1:
            itemparams_pos += len(_ITEMPARAMS_NAME)
            decoded_item_params, _ = _decode_fstring_bytes(item_blob, itemparams_pos)
            if isinstance(decoded_item_params, str):
                result["item_params"] = decoded_item_params
    except Exception:
        return result

    return result


def _item_name_from_params(item_params: str) -> str:
    tail = item_params.rsplit("/", 1)[-1]
    return tail.split(".", 1)[0] if tail else item_params


def _normalize_name(name: str) -> str:
    return normalize_inventory_name(name)


def _extract_asset_path(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).rstrip(".")


def _extract_inventory_refs(item_params: str) -> dict[str, Any]:
    item_asset = _extract_asset_path(item_params, _ITEM_ASSET_RE)
    slot_asset = _extract_asset_path(item_params, _SLOT_ASSET_RE)
    slot_name = _item_name_from_params(slot_asset) if slot_asset else None
    slot_index = None
    if slot_asset:
        tail = item_params[item_params.find(slot_asset) + len(slot_asset):]
        match = re.search(r"\.+(\d+)", tail)
        if match:
            slot_index = int(match.group(1))
    return {
        "resolved_item_params": item_asset,
        "slot_params": slot_asset,
        "slot_name": slot_name,
        "slot_index": slot_index,
        "is_slot_record": bool(slot_asset),
    }


def _classify_inventory_scope(cf_name: str, slot_name: str | None, is_slot_record: bool) -> str:
    if not is_slot_record:
        return "detached"

    slot_name = slot_name or ""
    if cf_name == "R5BLPlayer":
        if slot_name == "DA_BL_Slot_Default" or slot_name.startswith("DA_BL_Slot_Ammo_"):
            return "player_quick"
        if slot_name.startswith("DA_BL_Slot_Equipment_"):
            return "player_equipped"
        if slot_name == "DA_BL_Slot_Chest":
            return "player_storage"
        if slot_name in {
            "DA_BL_Slot_In",
            "DA_BL_Slot_Invisibl",
            "DA_BL_Slot_Invisible",
            "DA_BL_Slot_LootChest",
            "DA_BL_Slot_NPC_Common",
            "DA_BL_Slot_Quest",
        }:
            return "player_hidden"
        return "player_other_slot"

    if slot_name == "DA_BL_Slot_Chest":
        return "ship_storage"
    if slot_name.startswith("DA_BL_Slot_ShipEquipment_"):
        return "ship_equipped"
    return "ship_other_slot"


def _is_visible_inventory_scope(scope: str) -> bool:
    return scope in {"player_quick", "player_storage", "ship_storage"}


def _aggregate_inventory(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for item in items:
        norm = _normalize_name(item["item_name"])
        rec = aggregates.setdefault(
            norm,
            {
                "item_name": item["item_name"],
                "normalized": norm,
                "item_params": item["item_params"],
                "stacks": 0,
                "total_count": 0,
                "max_stack_observed": None,
                "player_stacks": 0,
                "ship_stacks": 0,
            },
        )
        rec["stacks"] += 1
        if isinstance(item.get("count"), int):
            rec["total_count"] += int(item["count"])
        maxv = item.get("max_value")
        if isinstance(maxv, int):
            if rec["max_stack_observed"] is None or maxv > rec["max_stack_observed"]:
                rec["max_stack_observed"] = maxv
        if item["cf"] == "R5BLPlayer":
            rec["player_stacks"] += 1
        else:
            rec["ship_stacks"] += 1
    return sorted(aggregates.values(), key=lambda x: x["item_name"].lower())


def _slot_record_score(item: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        1 if item.get("item_id") else 0,
        1 if isinstance(item.get("count"), int) else 0,
        1 if isinstance(item.get("max_value"), int) else 0,
        len(item.get("raw_item_params") or ""),
    )


def _dedupe_visible_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slotted: dict[tuple[Any, ...], dict[str, Any]] = {}
    detached: list[dict[str, Any]] = []

    for item in items:
        if item.get("is_slot_record"):
            key = (
                item["cf"],
                item["key_hex"],
                item.get("slot_name"),
                item.get("slot_index"),
                item["item_name"],
            )
            existing = slotted.get(key)
            if existing is None or _slot_record_score(item) > _slot_record_score(existing):
                slotted[key] = item
        else:
            detached.append(item)

    return list(slotted.values()) + detached


def _extract_inventory_items(blob: bytes) -> list[dict[str, Any]]:
    """Extract inventory-like item objects from one container blob."""
    objects = [o for o in extract_type3_objects(blob) if o.name.isdigit()]

    counters: list[dict[str, Any]] = []
    for obj in objects:
        fields = _parse_fields_with_offsets(obj.payload, obj.payload_start)
        tag_name = None
        value = None
        max_value = None
        for f in fields:
            leaf = f["name"].split(".")[-1]
            if leaf == "TagName" and isinstance(f["value"], str):
                tag_name = f["value"]
            elif leaf == "Value" and isinstance(f["value"], int):
                value = f["value"]
            elif leaf == "MaxValue" and isinstance(f["value"], int):
                max_value = f["value"]
        if tag_name == "Inventory.Item.Attribute.Counter":
            counters.append(
                {
                    "object_id": obj.name,
                    "value": value,
                    "max_value": max_value,
                }
            )

    out: list[dict[str, Any]] = []
    for obj in objects:
        fields = _parse_fields_with_offsets(obj.payload, obj.payload_start)
        stack_fields = _extract_itemsstack_fields(obj.payload)

        item_params = None
        item_id = None
        attrs_ref = None
        slot_id = None
        for f in fields:
            leaf = f["name"].split(".")[-1]
            if leaf == "ItemParams" and isinstance(f["value"], str):
                item_params = f["value"]
            elif leaf == "ItemId" and isinstance(f["value"], str):
                item_id = f["value"]
            elif leaf == "Attributes" and isinstance(f["value"], int):
                attrs_ref = f["value"]
            elif slot_id is None and leaf == "SlotId" and isinstance(f["value"], int):
                slot_id = f["value"]

        if not item_id and isinstance(stack_fields.get("item_id"), str):
            item_id = stack_fields["item_id"]

        if not isinstance(item_params, str) and isinstance(stack_fields.get("item_params"), str):
            item_params = stack_fields["item_params"]

        raw_item_params = item_params
        text_candidate = None
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in obj.payload)
        marker = "/R5BusinessRules/InventoryItems"
        p = text.find(marker)
        if p != -1:
            q = text.find("\x00", p)
            if q == -1:
                q = min(len(text), p + 260)
            text_candidate = text[p:q].strip(".")

        if not isinstance(raw_item_params, str):
            raw_item_params = text_candidate
        elif isinstance(text_candidate, str):
            # Prefer the richer payload text when it carries slot metadata.
            has_slot_in_raw = "/R5BusinessRules/Inventory/SlotsParams/" in raw_item_params
            has_slot_in_text = "/R5BusinessRules/Inventory/SlotsParams/" in text_candidate
            if has_slot_in_text and not has_slot_in_raw:
                raw_item_params = text_candidate

        if not isinstance(raw_item_params, str) or "/R5BusinessRules/InventoryItems" not in raw_item_params:
            continue

        refs = _extract_inventory_refs(raw_item_params)
        item_params = refs["resolved_item_params"] or raw_item_params
        if "/R5BusinessRules/InventoryItems" not in item_params:
            continue

        linked = None
        if attrs_ref is not None:
            linked = next((c for c in counters if c["object_id"] == str(attrs_ref)), None)

        local_count = None
        local_max = None
        for f in fields:
            leaf = f["name"].split(".")[-1]
            if local_count is None and leaf in ("Count", "Value") and isinstance(f["value"], int):
                local_count = f["value"]
            if local_max is None and leaf == "MaxValue" and isinstance(f["value"], int):
                local_max = f["value"]

        if local_count is None and isinstance(stack_fields.get("count"), int):
            local_count = stack_fields["count"]
        if local_max is None and isinstance(stack_fields.get("max_value"), int):
            local_max = stack_fields["max_value"]

        out.append(
            {
                "object_id": obj.name,
                "item_name": _item_name_from_params(item_params),
                "item_params": item_params,
                "raw_item_params": raw_item_params,
                "item_id": item_id,
                "slot_id": slot_id,
                "slot_name": refs["slot_name"],
                "slot_params": refs["slot_params"],
                "slot_index": refs["slot_index"],
                "is_slot_record": refs["is_slot_record"],
                "count": linked.get("value") if linked else local_count,
                "max_value": linked.get("max_value") if linked else local_max,
                "attributes_ref": attrs_ref,
            }
        )

    return out


def inspect_inventory(save_root: Path, *, ship_capacity: int = 28, captain_uuid: str | None = None) -> dict[str, Any]:
    """Inspect player and ship inventory items and aggregate totals."""
    containers: list[dict[str, Any]] = []
    raw_items: list[dict[str, Any]] = []
    ship_labels: dict[str, str] = {}  # key_hex -> human name

    with open_players_db(save_root, captain_uuid=captain_uuid) as db:
        # First pass: build ship name labels so every item can reference them
        ship_index = 0
        for key_bytes, val_bytes in db.iter_cf("R5BLShip"):
            ship_index += 1
            key_hex = key_bytes.hex()
            parsed = parse_r5_value(val_bytes)
            name = _inv_extract_ship_name_from_blob(val_bytes)
            if not name:
                name = _inv_find_first_string_key_like(parsed, "ShipName")
            if not name:
                ship_type = _inv_extract_ship_type_from_refs(parsed)
                name = ship_type or f"Ship #{ship_index}"
            ship_labels[key_hex] = name

        for cf_name in ("R5BLPlayer", "R5BLShip"):
            for key_bytes, val_bytes in db.iter_cf(cf_name):
                items = _extract_inventory_items(val_bytes)
                container = {
                    "cf": cf_name,
                    "key_hex": key_bytes.hex(),
                    "blob_size": len(val_bytes),
                    "item_stacks": len(items),
                }
                containers.append(container)
                for item in items:
                    rec = {"cf": cf_name, "key_hex": key_bytes.hex(), **item}
                    rec["inventory_scope"] = _classify_inventory_scope(
                        cf_name,
                        rec.get("slot_name"),
                        bool(rec.get("is_slot_record")),
                    )
                    if cf_name == "R5BLShip":
                        rec["ship_name"] = ship_labels.get(key_bytes.hex(), key_bytes.hex()[:8])
                    raw_items.append(rec)

    deduped_items = _dedupe_visible_items(raw_items)
    visible_items = [item for item in deduped_items if _is_visible_inventory_scope(item["inventory_scope"])]
    detached_items = [item for item in deduped_items if item["inventory_scope"] == "detached"]

    slot_keys: dict[tuple[Any, ...], str] = {}
    for item in deduped_items:
        if not item.get("is_slot_record"):
            continue
        key = (item["cf"], item["key_hex"], item.get("slot_name"), item.get("slot_index"))
        slot_keys[key] = item["inventory_scope"]

    player_quick_used = sum(1 for scope in slot_keys.values() if scope == "player_quick")
    player_storage_used = sum(1 for scope in slot_keys.values() if scope == "player_storage")
    player_equipped_used = sum(1 for scope in slot_keys.values() if scope == "player_equipped")
    player_hidden_used = sum(1 for scope in slot_keys.values() if scope == "player_hidden")
    ship_storage_used = sum(1 for scope in slot_keys.values() if scope == "ship_storage")
    ship_equipped_used = sum(1 for scope in slot_keys.values() if scope == "ship_equipped")

    return {
        "containers": containers,
        "raw_items": raw_items,
        "items": visible_items,
        "detached_items": detached_items,
        "raw_aggregates": _aggregate_inventory(raw_items),
        "aggregates": _aggregate_inventory(visible_items),
        "capacity": {
            "player_used_slots_observed": player_quick_used + player_storage_used,
            "player_quick_slots_used_observed": player_quick_used,
            "player_storage_slots_used_observed": player_storage_used,
            "player_equipped_slots_used_observed": player_equipped_used,
            "player_hidden_slots_observed": player_hidden_used,
            "ship_used_slots_observed": ship_storage_used,
            "ship_storage_used_slots_observed": ship_storage_used,
            "ship_equipped_slots_used_observed": ship_equipped_used,
            "ship_total_capacity": ship_capacity,
            "ship_free_slots": max(0, ship_capacity - ship_storage_used),
            "detached_item_objects": len(detached_items),
        },
    }


def build_inventory_stage_plan(
    save_root: Path,
    *,
    targets: dict[str, int],
    player_open_slots_per_stage: int = 20,
    ship_capacity: int = 28,
    strict_manifest: bool = False,
    captain_uuid: str | None = None,
) -> dict[str, Any]:
    """
    Build a stage estimate for target totals under player/ship slot constraints.
    """
    inv = inspect_inventory(save_root, ship_capacity=ship_capacity, captain_uuid=captain_uuid)
    by_norm = {a["normalized"]: a for a in inv["aggregates"]}

    item_plan: list[dict[str, Any]] = []
    missing_items: list[dict[str, Any]] = []
    unknown_stack_caps: list[dict[str, Any]] = []
    total_required_stacks = 0

    for name, target_total in targets.items():
        resolved_target = None
        try:
            resolved_target = resolve_inventory_asset_target(name, strict_manifest=strict_manifest)
        except KeyError:
            resolved_target = None

        lookup_norms = [_normalize_name(name)]
        if resolved_target is not None:
            lookup_norms.append(_normalize_name(resolved_target["asset_name"]))

        agg = None
        for norm in lookup_norms:
            agg = by_norm.get(norm)
            if agg is not None:
                break

        if not agg:
            if resolved_target is None:
                missing_items.append({"requested": name, "normalized": _normalize_name(name)})
            else:
                unknown_stack_caps.append(
                    {
                        "requested": name,
                        "resolved_item": resolved_target["asset_name"],
                        "asset_path": resolved_target["asset_path"],
                        "mapping_source": resolved_target["mapping_source"],
                    }
                )
                item_plan.append(
                    {
                        "requested": name,
                        "resolved_item": resolved_target["asset_name"],
                        "item_params": resolved_target["asset_path"],
                        "current_total": 0,
                        "target_total": int(target_total),
                        "required_add": int(target_total),
                        "max_stack": None,
                        "stacks_needed": None,
                        "player_stacks_existing": 0,
                        "ship_stacks_existing": 0,
                        "mapping_confidence": resolved_target["mapping_confidence"],
                        "mapping_source": resolved_target["mapping_source"],
                        "manifest_path": resolved_target["manifest_path"],
                    }
                )
            continue

        current_total = int(agg.get("total_count") or 0)
        required_add = max(0, int(target_total) - current_total)
        max_stack = agg.get("max_stack_observed")
        if not isinstance(max_stack, int) or max_stack <= 0:
            unknown_stack_caps.append({"requested": name, "resolved_item": agg["item_name"]})
            stacks_needed = None
        else:
            stacks_needed = int(math.ceil(required_add / max_stack)) if required_add > 0 else 0
            total_required_stacks += stacks_needed

        item_plan.append(
            {
                "requested": name,
                "resolved_item": agg["item_name"],
                "item_params": agg["item_params"],
                "current_total": current_total,
                "target_total": int(target_total),
                "required_add": required_add,
                "max_stack": max_stack,
                "stacks_needed": stacks_needed,
                "player_stacks_existing": agg["player_stacks"],
                "ship_stacks_existing": agg["ship_stacks"],
                "mapping_confidence": resolved_target["mapping_confidence"] if resolved_target else None,
                "mapping_source": resolved_target["mapping_source"] if resolved_target else None,
                "manifest_path": resolved_target["manifest_path"] if resolved_target else None,
            }
        )

    ship_free = int(inv["capacity"]["ship_free_slots"])
    ship_overflow_capacity = ship_free
    ship_assigned = min(ship_overflow_capacity, total_required_stacks)
    player_stacks_needed = max(0, total_required_stacks - ship_assigned)

    if total_required_stacks == 0:
        stage_count = 0
    else:
        stage_count = int(math.ceil(player_stacks_needed / player_open_slots_per_stage))
        if stage_count == 0:
            stage_count = 1

    feasible = not missing_items and not unknown_stack_caps
    reason = None
    if missing_items:
        feasible = False
        reason = "Missing requested items in current inventory; canonical item identity unresolved."
    elif unknown_stack_caps:
        feasible = False
        reason = "Unknown max stack for one or more requested items."

    return {
        "constraints": {
            "player_open_slots_per_stage": player_open_slots_per_stage,
            "ship_total_capacity": ship_capacity,
            "ship_used_slots_observed": inv["capacity"]["ship_used_slots_observed"],
            "ship_free_slots": ship_free,
        },
        "targets": item_plan,
        "missing_items": missing_items,
        "unknown_stack_caps": unknown_stack_caps,
        "summary": {
            "total_required_stacks": total_required_stacks,
            "ship_overflow_assigned_stacks": ship_assigned,
            "player_stacks_needed": player_stacks_needed,
            "estimated_stage_count": stage_count,
            "feasible": feasible,
            "reason": reason,
        },
        "notes": [
            "Stage count is an estimate based on required stacks and slot constraints.",
            "Manifest-backed resolution is used when available to canonicalize requested item targets.",
            "A concrete per-stage plan still requires stack-cap evidence for every requested item.",
        ],
    }
