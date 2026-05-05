from __future__ import annotations

from typing import Any

from .manifest import locate_windrose_manifest, resolve_manifest_inventory_asset


_MAPPED_ASSET_PATHS = {
    "wood": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_Wood_T01.DA_DID_Resource_Wood_T01",
        "confirmed": True,
    },
    "nails": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_Nails_T01.DA_DID_Resource_Nails_T01",
        "confirmed": True,
    },
    "foothillsironingot": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Metal_Ingot_Iron_T02.DA_DID_Metal_Ingot_Iron_T02",
        "confirmed": True,
    },
    "ironingot": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Metal_Ingot_Iron_T02.DA_DID_Metal_Ingot_Iron_T02",
        "confirmed": True,
    },
    "plank": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_PlanksWood_T01.DA_DID_Resource_PlanksWood_T01",
        "confirmed": True,
    },
    "planks": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_PlanksWood_T01.DA_DID_Resource_PlanksWood_T01",
        "confirmed": True,
    },
    "timber": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_WoodenBeam_T02.DA_DID_Resource_WoodenBeam_T02",
        "confirmed": True,
    },
    "tarredplanks": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_TarredPlanks_T03.DA_DID_Resource_TarredPlanks_T03",
        "confirmed": True,
    },
    "linnenfabric": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_LinenFabric_T02.DA_DID_Resource_LinenFabric_T02",
        "confirmed": True,
    },
    "linenfabric": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_LinenFabric_T02.DA_DID_Resource_LinenFabric_T02",
        "confirmed": True,
    },
    "tarredfabric": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_TarredFabric_T03.DA_DID_Resource_TarredFabric_T03",
        "confirmed": True,
    },
    "rope": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_Rope_T01.DA_DID_Resource_Rope_T01",
        "confirmed": True,
    },
    "shiprighttools": {
        "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Trading/DA_DID_TradeCraft_ShipTools_01.DA_DID_TradeCraft_ShipTools_01",
        "confirmed": True,
    },
}


def normalize_inventory_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def asset_name_from_path(asset_path: str) -> str:
    return asset_path.rsplit("/", 1)[-1].split(".", 1)[0]


def resolve_inventory_asset_target(name_or_path: str, *, strict_manifest: bool = False) -> dict[str, Any]:
    manifest_exists = locate_windrose_manifest() is not None
    manifest_hit = resolve_manifest_inventory_asset(name_or_path)
    if manifest_hit is not None:
        asset_path = manifest_hit["asset_path"]
        return {
            "requested": name_or_path,
            "asset_path": asset_path,
            "asset_name": asset_name_from_path(asset_path),
            "mapping_confidence": "manifest",
            "mapping_confirmed": True,
            "mapping_source": "steam_manifest"
            if name_or_path.startswith("/R5BusinessRules/InventoryItems/")
            else "name+steam_manifest",
            "manifest_path": manifest_hit["manifest_path"],
        }

    if name_or_path.startswith("/R5BusinessRules/InventoryItems/"):
        if strict_manifest and manifest_exists:
            raise KeyError(
                "Explicit inventory asset path was not found in the Windrose Steam manifest"
            )
        return {
            "requested": name_or_path,
            "asset_path": name_or_path,
            "asset_name": asset_name_from_path(name_or_path),
            "mapping_confidence": "explicit-unverified",
            "mapping_confirmed": True,
            "mapping_source": "explicit_path",
            "manifest_path": None,
        }

    normalized = normalize_inventory_name(name_or_path)
    if normalized in _MAPPED_ASSET_PATHS:
        mapped = _MAPPED_ASSET_PATHS[normalized]
        mapped_asset_path = str(mapped["asset_path"])
        alias_manifest_hit = resolve_manifest_inventory_asset(mapped_asset_path)
        if alias_manifest_hit is not None:
            return {
                "requested": name_or_path,
                "asset_path": alias_manifest_hit["asset_path"],
                "asset_name": asset_name_from_path(alias_manifest_hit["asset_path"]),
                "mapping_confidence": "manifest",
                "mapping_confirmed": True,
                "mapping_source": "built_in_alias+steam_manifest",
                "manifest_path": alias_manifest_hit["manifest_path"],
            }
        if strict_manifest and manifest_exists:
            raise KeyError(
                "Built-in alias resolved to an asset path that was not found in the Windrose Steam manifest"
            )

        confirmed = bool(mapped["confirmed"])
        return {
            "requested": name_or_path,
            "asset_path": mapped_asset_path,
            "asset_name": asset_name_from_path(mapped_asset_path),
            "mapping_confidence": "confirmed" if confirmed else "assumed",
            "mapping_confirmed": confirmed,
            "mapping_source": "built_in_alias",
            "manifest_path": None,
        }

    raise KeyError(f"Unknown shopping-list item: {name_or_path}")
