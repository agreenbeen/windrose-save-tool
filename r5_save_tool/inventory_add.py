"""
Inventory add helper - safely adds items to player/ship inventory with backup-first writes.

Usage:
  python -m r5_save_tool.inventory_add --container ship --items nails=300 iron_ingot=120 ...

This module:
1. Reads current inventory blob
2. Parses and modifies it
3. Backs up before writing (via put command)
4. Provides rollback info
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from .db import open_players_db, _locate_single_subdir
from .inventory import inspect_inventory
from .backup import backup_db


# Mapping of human-friendly names to asset IDs
SHOPPING_LIST_ASSETS = {
    "nails": "DA_DID_Resource_Nails_T01",
    "iron_ingot": "DA_DID_Metal_Ingot_Iron_T02",
    "foothills_iron_ingot": "DA_DID_Metal_Ingot_Iron_T02",
    "plank": "DA_DID_Resource_Planks_T01",
    "timber": "DA_DID_Resource_Wood_T01",
    "tarred_planks": "DA_DID_Resource_Planks_T02",
    "linnen_fabric": "DA_DID_Resource_Fabric_T01",
    "tarred_fabric": "DA_DID_Resource_Fabric_T02",
    "rope": "DA_DID_Resource_Rope_T01",
    "shipright_tools": "DA_DID_TradeCraft_FineTools_01",
}

def resolve_asset_id(name: str) -> str | None:
    """Resolve human-readable name to asset ID."""
    normalized = "".join(ch.lower() for ch in name if ch.isalnum())
    for key, asset_id in SHOPPING_LIST_ASSETS.items():
        if "".join(ch.lower() for ch in key if ch.isalnum()) == normalized:
            return asset_id
    return None


def get_container_key(save_root: Path, container: str) -> tuple[str, bytes] | None:
    """Get (cf_name, key_bytes) for a container (ship or player)."""
    result = inspect_inventory(save_root)
    containers = result.get("containers", [])

    if container == "ship":
        # Return first ship container found
        for cont in containers:
            if cont["cf"] == "R5BLShip":
                return "R5BLShip", bytes.fromhex(cont["key_hex"])
    elif container == "player":
        # Return player container
        for cont in containers:
            if cont["cf"] == "R5BLPlayer":
                return "R5BLPlayer", bytes.fromhex(cont["key_hex"])

    return None


def preview_add(save_root: Path, container: str, items_to_add: dict[str, int]) -> dict[str, Any]:
    """Preview what will be added without writing."""
    result = inspect_inventory(save_root)

    containers = result.get("containers", [])
    cf_name = None
    key_hex = None

    for cont in containers:
        if (container == "ship" and cont["cf"] == "R5BLShip") or \
           (container == "player" and cont["cf"] == "R5BLPlayer"):
            cf_name = cont["cf"]
            key_hex = cont["key_hex"]
            break

    if not cf_name:
        return {"error": f"Container {container} not found"}

    return {
        "container": container,
        "cf_name": cf_name,
        "key_hex": key_hex,
        "items_to_add": items_to_add,
        "assets_resolved": {name: resolve_asset_id(name) for name in items_to_add},
        "note": "Preview only - no changes made. Run with --execute to write."
    }


@click.command()
@click.option(
    "--container",
    type=click.Choice(["ship", "player"]),
    required=True,
    help="Target container (ship or player inventory).",
)
@click.option(
    "--items",
    "items_str",
    required=True,
    help="Items to add as item_name=quantity. Repeat for multiple: --items nails=300 --items rope=80",
    multiple=True,
)
@click.option(
    "--preview-only",
    is_flag=True,
    default=False,
    help="Show what would be added without writing.",
)
@click.option(
    "--save-root",
    envvar="R5_SAVE_ROOT",
    default=None,
    help="Path to save root (or R5_SAVE_ROOT env var).",
)
def cmd_inventory_add(
    container: str,
    items_str: tuple[str, ...],
    preview_only: bool,
    save_root: str | None,
) -> None:
    """Add items to inventory with backup-first safety."""
    from .db import R5Database

    if not save_root:
        from .cli import _find_save_root
        save_root_obj = _find_save_root(None)
    else:
        save_root_obj = Path(save_root)

    # Parse items
    items_to_add: dict[str, int] = {}
    for item_str in items_str:
        if "=" not in item_str:
            raise click.BadParameter(f"Invalid item spec {item_str!r}. Use name=quantity")
        name, qty_str = item_str.split("=", 1)
        try:
            qty = int(qty_str.strip())
        except ValueError:
            raise click.BadParameter(f"Invalid quantity for {name}: {qty_str!r}")
        items_to_add[name.strip()] = qty

    # Preview
    preview = preview_add(save_root_obj, container, items_to_add)

    if "error" in preview:
        raise click.ClickException(preview["error"])

    click.echo(f"\n{'='*60}")
    click.echo(f"Preview: Adding to {container.upper()} inventory")
    click.echo(f"{'='*60}")
    for name, qty in items_to_add.items():
        asset = preview["assets_resolved"].get(name)
        status = "✓" if asset else "✗"
        click.echo(f"  {status} {name:20} x{qty:4}  →  {asset or '(unknown)'}")

    click.echo(f"\nContainer: {preview['cf_name']}")
    click.echo(f"Key:       {preview['key_hex'][:16]}...")

    if preview_only:
        click.echo("\n[PREVIEW MODE] No changes written. Use without --preview-only to execute.")
        return

    # Confirm before writing
    if not click.confirm("\nProceed with adding items to save file?"):
        click.echo("Cancelled.")
        return

    click.echo("\n⚠️  This will create a backup before writing.")
    click.echo("Backup location will be shown after completion.\n")

    # TODO: Implement actual item addition
    # For now, show what would happen
    click.echo("✓ Items would be added to container")
    click.echo("✓ Backup would be created automatically")
    click.echo("✓ Modified inventory blob would be written via put command")
    click.echo("\n⚠️  FEATURE NOT YET IMPLEMENTED")
    click.echo("Need to build binary blob modification logic.")


if __name__ == "__main__":
    cmd_inventory_add()
