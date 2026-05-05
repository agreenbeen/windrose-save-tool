"""
CLI entry point.

Usage examples:
  r5-save dump players --cf R5BLPlayer
  r5-save dump accounts
  r5-save search-key "Health"
  r5-save search-value "Ketch"
  r5-save get R5BLPlayer <hex-key>
  r5-save put R5BLPlayer <hex-key> <hex-value>   # backs up first
  r5-save backups
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import click

from .backup import backup_db, backup_details, list_backups, restore_backup
from .db import (
    _locate_single_subdir,
    open_accounts_db,
    open_players_db,
)
from .dump import dump_db, dump_to_json, search_key, search_value_strings
from .inventory_targets import resolve_inventory_asset_target
from .manifest import locate_windrose_manifest, search_manifest_inventory_assets
from .schema import decode_key, format_decoded

# ---------------------------------------------------------------------------
# Default save-root path — override via --save-root or R5_SAVE_ROOT env var
# ---------------------------------------------------------------------------
_DEFAULT_ROOT = (
    Path.home()
    / "AppData" / "Local" / "R5" / "Saved" / "SaveProfiles"
)
_WINDROSE_PLAYERS_ROOT = Path.home() / "AppData" / "Local" / "Windrose" / "Saved" / "Players"
_ROCKSDB_DIR_NAMES = ("RocksDB_v2", "RocksDB")


class DirectoryComparison(TypedDict):
    a_only: list[str]
    b_only: list[str]
    a_count: int
    b_count: int


def _find_save_root(save_root: str | None) -> Path:
    """Locate the versioned RocksDB root, preferring RocksDB_v2 over RocksDB."""
    base = Path(save_root) if save_root else _DEFAULT_ROOT
    if not base.exists():
        raise click.ClickException(f"Save root not found: {base}")

    for dir_name in _ROCKSDB_DIR_NAMES:
        versioned = base / dir_name / "0.10.0"
        if versioned.exists():
            return versioned

    for child in base.iterdir():
        if child.is_dir() and child.name.isdigit():
            for dir_name in _ROCKSDB_DIR_NAMES:
                candidate = child / dir_name / "0.10.0"
                if candidate.exists():
                    return candidate

    raise click.ClickException(
        f"Could not locate RocksDB_v2/0.10.0 or RocksDB/0.10.0 under {base}. "
        "Use --save-root to specify the exact path."
    )


def _resolve_db_dir(save_root: Path, db: str) -> Path:
    db_dir_parent = save_root / ("Players" if db == "players" else "Accounts")
    return _locate_single_subdir(db_dir_parent)


def _read_current_marker(db_path: Path) -> str | None:
    current_path = db_path / "CURRENT"
    if not current_path.exists():
        return None
    return current_path.read_text(encoding="utf-8", errors="ignore").strip()


def _file_count(root: Path) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file()) if root.exists() else 0


def _windrose_player_dir(save_root: Path) -> Path | None:
    try:
        player_dir = _resolve_db_dir(save_root, "players")
    except FileNotFoundError:
        return None
    candidate = _WINDROSE_PLAYERS_ROOT / player_dir.name
    return candidate if candidate.exists() else None


def _echo_resolved_db_path(db: str, db_dir: Path) -> None:
    click.echo(f"Resolved {db} DB path: {db_dir}")


def _compare_dirs(a: Path, b: Path) -> DirectoryComparison:
    a_files = {path.relative_to(a).as_posix() for path in a.rglob("*") if path.is_file()}
    b_files = {path.relative_to(b).as_posix() for path in b.rglob("*") if path.is_file()}
    return {
        "a_only": sorted(a_files - b_files),
        "b_only": sorted(b_files - a_files),
        "a_count": len(a_files),
        "b_count": len(b_files),
    }


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------

@click.group()
@click.option(
    "--save-root", envvar="R5_SAVE_ROOT", default=None,
    help="Path to the SaveProfiles folder (or R5_SAVE_ROOT env var).",
)
@click.pass_context
def cli(ctx: click.Context, save_root: str | None) -> None:
    """Windrose Save Tool — save-file inspection and editing tool."""
    ctx.ensure_object(dict)
    ctx.obj["save_root"] = save_root


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("db", type=click.Choice(["players", "accounts"]))
@click.option("--cf", multiple=True, help="Limit to specific column family(s).")
@click.option("--max", "max_entries", default=None, type=int,
              help="Max entries to print per column family.")
@click.option("--json-out", default=None, type=click.Path(),
              help="Also write structured JSON summary to this file.")
@click.pass_context
def dump(ctx: click.Context, db: str, cf: tuple[str, ...], max_entries: int | None,
         json_out: str | None) -> None:
    """Dump all key-value pairs from the database."""
    save_root = _find_save_root(ctx.obj["save_root"])
    opener = open_players_db if db == "players" else open_accounts_db

    with opener(save_root) as r5db:
        cf_filter = list(cf) if cf else None
        if json_out:
            dump_to_json(r5db, Path(json_out), cf_filter=cf_filter, max_per_cf=max_entries)
        else:
            dump_db(r5db, cf_filter=cf_filter, max_per_cf=max_entries)


# ---------------------------------------------------------------------------
# search-key
# ---------------------------------------------------------------------------

@cli.command("search-key")
@click.argument("pattern")
@click.option("--db", "db_choice", type=click.Choice(["players", "accounts", "both"]),
              default="both")
@click.pass_context
def search_key_cmd(ctx: click.Context, pattern: str, db_choice: str) -> None:
    """Search for keys containing PATTERN (case-insensitive substring)."""
    save_root = _find_save_root(ctx.obj["save_root"])
    dbs_to_open = []
    if db_choice in ("players", "both"):
        dbs_to_open.append(("players", open_players_db))
    if db_choice in ("accounts", "both"):
        dbs_to_open.append(("accounts", open_accounts_db))

    found = False
    for label, opener in dbs_to_open:
        with opener(save_root) as r5db:
            results = search_key(r5db, pattern)
            if results:
                found = True
                for cf_name, key_str, val_len in results:
                    click.echo(f"[{label}/{cf_name}] key={key_str!r}  value={val_len} bytes")

    if not found:
        click.echo(f"No keys matching {pattern!r} found.")


# ---------------------------------------------------------------------------
# search-value
# ---------------------------------------------------------------------------

@cli.command("search-value")
@click.argument("pattern")
@click.option("--db", "db_choice", type=click.Choice(["players", "accounts", "both"]),
              default="both")
@click.pass_context
def search_value_cmd(ctx: click.Context, pattern: str, db_choice: str) -> None:
    """Search for values containing PATTERN as an embedded string."""
    save_root = _find_save_root(ctx.obj["save_root"])
    dbs_to_open = []
    if db_choice in ("players", "both"):
        dbs_to_open.append(("players", open_players_db))
    if db_choice in ("accounts", "both"):
        dbs_to_open.append(("accounts", open_accounts_db))

    found = False
    for label, opener in dbs_to_open:
        with opener(save_root) as r5db:
            results = search_value_strings(r5db, pattern)
            if results:
                found = True
                for cf_name, key_str, matches in results:
                    click.echo(f"[{label}/{cf_name}] key={key_str!r}")
                    for m in matches[:5]:
                        click.echo(f"    matched: {m!r}")

    if not found:
        click.echo(f"No values containing {pattern!r} found.")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("db", type=click.Choice(["players", "accounts"]))
@click.argument("cf_name")
@click.argument("key_hex")
@click.pass_context
def get(ctx: click.Context, db: str, cf_name: str, key_hex: str) -> None:
    """Read a single value by column-family and hex-encoded key."""
    save_root = _find_save_root(ctx.obj["save_root"])
    opener = open_players_db if db == "players" else open_accounts_db

    try:
        key_bytes = bytes.fromhex(key_hex)
    except ValueError:
        # Allow plain string keys too
        key_bytes = key_hex.encode("utf-8")

    with opener(save_root) as r5db:
        value = r5db.get(cf_name, key_bytes)
        if value is None:
            click.echo("Key not found.")
        else:
            click.echo(format_decoded(key_bytes, value, cf_name))


# ---------------------------------------------------------------------------
# put  (WRITE — backs up first)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("db", type=click.Choice(["players", "accounts"]))
@click.argument("cf_name")
@click.argument("key_hex")
@click.argument("value_hex")
@click.option("--no-backup", is_flag=True, default=False,
              help="Skip backup (not recommended).")
@click.pass_context
def put(ctx: click.Context, db: str, cf_name: str, key_hex: str, value_hex: str,
        no_backup: bool) -> None:
    """Write a value by column-family and hex-encoded key/value. Backs up first."""
    save_root = _find_save_root(ctx.obj["save_root"])
    db_dir = _resolve_db_dir(save_root, db)
    _echo_resolved_db_path(db, db_dir)
    opener = open_players_db if db == "players" else open_accounts_db

    try:
        key_bytes = bytes.fromhex(key_hex)
    except ValueError:
        key_bytes = key_hex.encode("utf-8")

    try:
        value_bytes = bytes.fromhex(value_hex)
    except ValueError:
        raise click.BadParameter("value_hex must be a valid hex string")

    if not no_backup:
        backup_db(db_dir)

    with opener(save_root, read_only=False) as r5db:
        r5db.put(cf_name, key_bytes, value_bytes)
        click.echo(f"Written {len(value_bytes)} bytes to [{cf_name}] key={decode_key(key_bytes)!r}")


# ---------------------------------------------------------------------------
# report  (HTML viewer)
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--out",
    "out_path",
    default=None,
    type=click.Path(),
    help="Deprecated: custom output path is ignored; report always writes to tmp/report/r5_save_report.html.",
)
@click.pass_context
def report(ctx: click.Context, out_path: str | None) -> None:
    """Generate a self-contained HTML report for all save data."""
    from .report import generate_html_report

    save_root = _find_save_root(ctx.obj["save_root"])
    canonical_out = Path("tmp") / "report" / "r5_save_report.html"
    canonical_out.parent.mkdir(parents=True, exist_ok=True)
    if out_path:
        click.echo(
            "Note: --out is deprecated for report; writing to tmp/report/r5_save_report.html"
        )
    generate_html_report(save_root, canonical_out)


# ---------------------------------------------------------------------------
# decode  (UE property parse)
# ---------------------------------------------------------------------------
@cli.command()
@click.argument("db", type=click.Choice(["players", "accounts"]))
@click.argument("cf_name")
@click.option("--out", "out_path", default=None, type=click.Path(),
              help="Write JSON output to this file instead of stdout.")
@click.pass_context
def decode(ctx: click.Context, db: str, cf_name: str, out_path: str | None) -> None:
    """Decode all entries in a column family using the UE property parser."""
    import json
    from .ue_parser import parse_r5_value

    save_root = _find_save_root(ctx.obj["save_root"])
    opener = open_players_db if db == "players" else open_accounts_db

    results = {}
    with opener(save_root) as r5db:
        for key_bytes, val_bytes in r5db.iter_cf(cf_name):
            key_str = decode_key(key_bytes)
            parsed = parse_r5_value(val_bytes)
            results[key_str] = parsed

    output = json.dumps(results, indent=2, ensure_ascii=False, default=str)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(output)
        click.echo(f"Decoded {len(results)} entries → {out_path}")
    else:
        click.echo(output)


# ---------------------------------------------------------------------------
# coin-inspect
# ---------------------------------------------------------------------------

@cli.command("coin-inspect")
@click.option(
    "--out",
    "out_path",
    default="coin_inspect.json",
    type=click.Path(),
    help="Write structured coin analysis JSON to this file.",
)
@click.pass_context
def coin_inspect_cmd(ctx: click.Context, out_path: str) -> None:
    """Inspect coin entries, inferred amounts, and candidate writable offsets."""
    from .coin import inspect_coins

    save_root = _find_save_root(ctx.obj["save_root"])
    result = inspect_coins(save_root, Path(out_path))

    click.echo(f"Analyzed containers: {len(result['containers'])}")
    for c in result["containers"]:
        click.echo(
            f"  [{c['cf']}] key={c['key_hex'][:16]}... size={c['blob_size']} "
            f"coins={len(c['coin_items'])} counters={len(c['counter_objects'])}"
        )

    click.echo(f"Found coin entries: {len(result['coin_items'])}")
    for item in result["coin_items"]:
        click.echo(
            f"  [{item['cf']}] {item['coin_type']}: obj={item['object_id']} "
            f"amount={item['inferred_amount']} "
            f"max={item['inferred_max']} amount_offset={item['inferred_amount_offset']} "
            f"confidence={item['confidence']}"
        )
    click.echo(f"Wrote detailed analysis: {out_path}")


@cli.command("coin-probe")
@click.option(
    "--cf",
    "cf_name",
    default="R5BLPlayer",
    type=click.Choice(["R5BLPlayer", "R5BLShip"]),
    help="Column family to probe (default: R5BLPlayer).",
)
@click.option(
    "--out",
    "out_path",
    required=True,
    type=click.Path(),
    help="Write int32 snapshot JSON to this file.",
)
@click.pass_context
def coin_probe_cmd(ctx: click.Context, cf_name: str, out_path: str) -> None:
    """Dump every int32 field in a coin container blob for delta-probe analysis.

    Run once before and once after changing a coin value in-game by a small
    amount.  Diff the two outputs: the authoritative field is the only offset
    whose value moved by exactly the delta.
    """
    import json
    import struct
    from .coin import _parse_fields_with_offsets, extract_type3_objects

    save_root = _find_save_root(ctx.obj["save_root"])
    containers: list[dict] = []

    with open_players_db(save_root) as db:
        for key_bytes, val_bytes in db.iter_cf(cf_name):
            fields_by_object: list[dict] = []
            for obj in extract_type3_objects(val_bytes):
                if not obj.name.isdigit():
                    continue
                fields = _parse_fields_with_offsets(obj.payload, obj.payload_start)
                int_fields = [
                    {"offset": f["int_offset"], "value": f["value"], "name": f["name"]}
                    for f in fields
                    if f.get("int_offset") is not None and isinstance(f.get("value"), int)
                ]
                if int_fields:
                    fields_by_object.append({
                        "object_id": obj.name,
                        "object_offset": obj.offset,
                        "int_fields": int_fields,
                    })

            # Also include every raw int32 in the full blob for completeness.
            raw_int32s: list[dict] = []
            for i in range(0, len(val_bytes) - 3, 4):
                v = struct.unpack_from("<i", val_bytes, i)[0]
                raw_int32s.append({"offset": i, "value": v})

            containers.append({
                "cf": cf_name,
                "key_hex": key_bytes.hex(),
                "blob_size": len(val_bytes),
                "parsed_objects": fields_by_object,
                "raw_int32s": raw_int32s,
            })

    result = {"cf": cf_name, "containers": containers}
    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    total_objects = sum(len(c["parsed_objects"]) for c in containers)
    click.echo(f"Probed {len(containers)} container(s), {total_objects} object(s) → {out_path}")



@cli.command("coin-map")
@click.option("--person-piastre", required=True, type=int, help="Known current player piastre.")
@click.option("--person-guinea", required=True, type=int, help="Known current player guinea.")
@click.option("--ship-piastre", required=True, type=int, help="Known current ship piastre.")
@click.option("--ship-guinea", required=True, type=int, help="Known current ship guinea.")
@click.option(
    "--out",
    "out_path",
    default="coin_mapping.json",
    type=click.Path(),
    help="Write calibrated offset mapping JSON to this file.",
)
@click.pass_context
def coin_map_cmd(
    ctx: click.Context,
    person_piastre: int,
    person_guinea: int,
    ship_piastre: int,
    ship_guinea: int,
    out_path: str,
) -> None:
    """Find coin value offsets using known calibration values."""
    import json
    from .coin import map_coin_offsets_by_known_values

    save_root = _find_save_root(ctx.obj["save_root"])
    result = map_coin_offsets_by_known_values(
        save_root,
        person_piastre=person_piastre,
        person_guinea=person_guinea,
        ship_piastre=ship_piastre,
        ship_guinea=ship_guinea,
    )

    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    for label, hit in result["mappings"].items():
        if not hit:
            click.echo(f"{label}: no match")
            continue
        click.echo(
            f"{label}: [{hit['cf']}] obj={hit['coin_object_id']} "
            f"value={hit['known_value']} off={hit['value_offset']} "
            f"dist={hit['distance']} conf={hit['confidence']}"
        )
    click.echo(f"Wrote mapping: {out_path}")


@cli.command("coin-set")
@click.option("--known-person-piastre", required=True, type=int)
@click.option("--known-person-guinea", required=True, type=int)
@click.option("--known-ship-piastre", required=True, type=int)
@click.option("--known-ship-guinea", required=True, type=int)
@click.option("--set-person-piastre", default=None, type=int)
@click.option("--set-person-guinea", default=None, type=int)
@click.option("--set-ship-piastre", default=None, type=int)
@click.option("--set-ship-guinea", default=None, type=int)
@click.option("--dry-run/--write", default=True, help="Default dry-run. Use --write to apply.")
@click.option(
    "--out",
    "out_path",
    default="coin_set_result.json",
    type=click.Path(),
    help="Write set-operation result JSON to this file.",
)
@click.pass_context
def coin_set_cmd(
    ctx: click.Context,
    known_person_piastre: int,
    known_person_guinea: int,
    known_ship_piastre: int,
    known_ship_guinea: int,
    set_person_piastre: int | None,
    set_person_guinea: int | None,
    set_ship_piastre: int | None,
    set_ship_guinea: int | None,
    dry_run: bool,
    out_path: str,
) -> None:
    """Apply coin value updates using calibrated offsets with safety checks."""
    import json
    from .coin import apply_coin_values

    if all(v is None for v in (set_person_piastre, set_person_guinea, set_ship_piastre, set_ship_guinea)):
        raise click.ClickException("No target values specified. Use --set-* options.")

    save_root = _find_save_root(ctx.obj["save_root"])
    _echo_resolved_db_path("players", _resolve_db_dir(save_root, "players"))
    result = apply_coin_values(
        save_root,
        known_person_piastre=known_person_piastre,
        known_person_guinea=known_person_guinea,
        known_ship_piastre=known_ship_piastre,
        known_ship_guinea=known_ship_guinea,
        new_person_piastre=set_person_piastre,
        new_person_guinea=set_person_guinea,
        new_ship_piastre=set_ship_piastre,
        new_ship_guinea=set_ship_guinea,
        dry_run=dry_run,
    )

    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    mode = "DRY-RUN" if result.get("dry_run", True) else "WRITE"
    click.echo(f"Mode: {mode}")
    for u in result.get("updates", []):
        click.echo(
            f"{u['label']}: [{u['cf']}] off={u['offset']} {u['old_value']} -> {u['new_value']} "
            f"conf={u['confidence']}"
        )
    if result.get("backup_path"):
        click.echo(f"Backup: {result['backup_path']}")
    click.echo(f"Wrote result: {out_path}")


@cli.command("inventory-inspect")
@click.option(
    "--ship-capacity",
    default=28,
    type=int,
    show_default=True,
    help="Total ship inventory slot capacity.",
)
@click.option(
    "--out",
    "out_path",
    default="inventory_inspect.json",
    type=click.Path(),
    help="Write structured inventory inspection JSON to this file.",
)
@click.pass_context
def inventory_inspect_cmd(ctx: click.Context, ship_capacity: int, out_path: str) -> None:
    """Inspect current inventory items, counts, and observed stack limits."""
    import json
    from .inventory import inspect_inventory

    save_root = _find_save_root(ctx.obj["save_root"])
    result = inspect_inventory(save_root, ship_capacity=ship_capacity)

    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    click.echo(f"Containers analyzed: {len(result['containers'])}")
    click.echo(f"Visible item stacks: {len(result['items'])}")
    click.echo(f"Distinct visible items: {len(result['aggregates'])}")
    click.echo(f"Detached item objects: {len(result['detached_items'])}")
    cap = result["capacity"]
    click.echo(
        "Capacity: "
        f"player_quick={cap['player_quick_slots_used_observed']} "
        f"player_storage={cap['player_storage_slots_used_observed']} "
        f"ship_used={cap['ship_used_slots_observed']} "
        f"ship_free={cap['ship_free_slots']}/{cap['ship_total_capacity']}"
    )
    click.echo(f"Wrote inventory inspection: {out_path}")


@cli.command("inventory-plan")
@click.option(
    "--target",
    "targets",
    multiple=True,
    required=True,
    help="Target total in the form name=amount, e.g. nails=300",
)
@click.option(
    "--player-open-slots-per-stage",
    default=20,
    type=int,
    show_default=True,
    help="Open player slots available per stage.",
)
@click.option(
    "--ship-capacity",
    default=28,
    type=int,
    show_default=True,
    help="Total ship inventory slot capacity.",
)
@click.option(
    "--strict-manifest/--no-strict-manifest",
    default=False,
    show_default=True,
    help="Require requested targets to be present in the Windrose Steam manifest when a manifest is available.",
)
@click.option(
    "--out",
    "out_path",
    default="inventory_stage_plan.json",
    type=click.Path(),
    help="Write stage-plan JSON to this file.",
)
@click.pass_context
def inventory_plan_cmd(
    ctx: click.Context,
    targets: tuple[str, ...],
    player_open_slots_per_stage: int,
    ship_capacity: int,
    strict_manifest: bool,
    out_path: str,
) -> None:
    """Estimate stage count for target item totals under slot constraints."""
    import json
    from .inventory import build_inventory_stage_plan

    parsed_targets: dict[str, int] = {}
    for t in targets:
        if "=" not in t:
            raise click.BadParameter(f"Invalid --target {t!r}. Use name=amount")
        raw_name, raw_amt = t.split("=", 1)
        name = raw_name.strip()
        if not name:
            raise click.BadParameter(f"Invalid --target {t!r}. Empty item name")
        try:
            amt = int(raw_amt.strip())
        except ValueError:
            raise click.BadParameter(f"Invalid --target {t!r}. Amount must be an integer")
        parsed_targets[name] = amt

    save_root = _find_save_root(ctx.obj["save_root"])
    result = build_inventory_stage_plan(
        save_root,
        targets=parsed_targets,
        player_open_slots_per_stage=player_open_slots_per_stage,
        ship_capacity=ship_capacity,
        strict_manifest=strict_manifest,
    )

    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = result["summary"]
    click.echo(f"Feasible: {summary['feasible']}")
    click.echo(f"Estimated stages: {summary['estimated_stage_count']}")
    click.echo(
        "Stack demand: "
        f"total={summary['total_required_stacks']} "
        f"player={summary['player_stacks_needed']} "
        f"ship_overflow={summary['ship_overflow_assigned_stacks']}"
    )
    if result["missing_items"]:
        click.echo("Missing items:")
        for m in result["missing_items"]:
            click.echo(f"  - {m['requested']}")
    if result["unknown_stack_caps"]:
        click.echo("Unknown max stack:")
        for u in result["unknown_stack_caps"]:
            detail = f"  - {u['requested']} (resolved={u['resolved_item']})"
            if u.get("mapping_source"):
                detail += f" source={u['mapping_source']}"
            click.echo(detail)
    if summary.get("reason"):
        click.echo(f"Reason: {summary['reason']}")
    click.echo(f"Wrote inventory stage plan: {out_path}")


@cli.command("inventory-add-ship")
@click.option(
    "--target",
    "targets",
    multiple=True,
    required=True,
    help="Target stack in the form name=amount, e.g. nails=300",
)
@click.option(
    "--write/--dry-run",
    default=False,
    show_default=True,
    help="Write changes to the save. Dry-run is the default and makes no changes.",
)
@click.option(
    "--confirm-assumed/--no-confirm-assumed",
    default=False,
    show_default=True,
    help="Allow writes when a target resolves via an assumption-based item ID.",
)
@click.option(
    "--strict-manifest/--no-strict-manifest",
    default=False,
    show_default=True,
    help="Require requested targets to be present in the Windrose Steam manifest when a manifest is available.",
)
@click.option(
    "--ship-key-prefix",
    default=None,
    help="Optional R5BLShip key prefix to target a specific ship blob.",
)
@click.option(
    "--out",
    "out_path",
    default=None,
    type=click.Path(),
    help="Optionally write the planned/applied result JSON to this file.",
)
@click.pass_context
def inventory_add_ship_cmd(
    ctx: click.Context,
    targets: tuple[str, ...],
    write: bool,
    confirm_assumed: bool,
    strict_manifest: bool,
    ship_key_prefix: str | None,
    out_path: str | None,
) -> None:
    """Repurpose empty ship chest slots into requested shopping-list stacks."""
    import json

    from .inventory_write import apply_ship_chest_additions

    parsed_targets: dict[str, int] = {}
    for target in targets:
        if "=" not in target:
            raise click.BadParameter(f"Invalid --target {target!r}. Use name=amount")
        raw_name, raw_amount = target.split("=", 1)
        name = raw_name.strip()
        if not name:
            raise click.BadParameter(f"Invalid --target {target!r}. Empty item name")
        try:
            amount = int(raw_amount.strip())
        except ValueError:
            raise click.BadParameter(f"Invalid --target {target!r}. Amount must be an integer")
        parsed_targets[name] = amount

    save_root = _find_save_root(ctx.obj["save_root"])
    _echo_resolved_db_path("players", _resolve_db_dir(save_root, "players"))
    result = apply_ship_chest_additions(
        save_root,
        targets=parsed_targets,
        dry_run=not write,
        allow_assumed_assets=confirm_assumed,
        strict_manifest=strict_manifest,
        preferred_ship_key_prefix=ship_key_prefix,
    )

    if out_path:
        Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    click.echo(f"Mode: {'write' if write else 'dry-run'}")
    click.echo(f"Ship container: {result['key_hex']}")
    click.echo(f"Planned stacks: {len(result['planned_updates'])}")
    for update in result["planned_updates"]:
        slot_text = update["slot_index"] if update["slot_index"] is not None else "?"
        confidence = update.get("mapping_confidence", "unknown")
        source = update.get("mapping_source", "unknown")
        click.echo(
            f"  slot={slot_text} object={update['object_id']} {update['requested']}={update['count']} mapping={confidence} source={source}"
        )
        if update.get("manifest_path"):
            click.echo(f"    manifest: {update['manifest_path']}")
    if result.get("assumed_mappings"):
        click.echo("Assumed mappings detected:")
        for assumed in result["assumed_mappings"]:
            click.echo(
                f"  - {assumed['requested']} -> {assumed['asset_path']}"
                f" source={assumed.get('mapping_source', 'unknown')}"
            )
        if write and not confirm_assumed:
            click.echo("Writes with assumed mappings are blocked. Re-run with --confirm-assumed to force.")
    if result.get("backup_path"):
        click.echo(f"Backup: {result['backup_path']}")
    if out_path:
        click.echo(f"Wrote ship inventory plan: {out_path}")


@cli.command("inventory-set-ship-count")
@click.option(
    "--target",
    required=True,
    help="Inventory target to update (alias, item name, or full asset path).",
)
@click.option(
    "--count",
    "new_count",
    required=True,
    type=int,
    help="New stack count value to set.",
)
@click.option(
    "--current-count",
    default=None,
    type=int,
    help="Optional safety guard: only match stacks currently at this count.",
)
@click.option(
    "--all-matches/--single-match",
    default=False,
    show_default=True,
    help="Update all matching logical stacks or require a single unambiguous match.",
)
@click.option(
    "--write/--dry-run",
    default=False,
    show_default=True,
    help="Write changes to the save. Dry-run is the default and makes no changes.",
)
@click.option(
    "--strict-manifest/--no-strict-manifest",
    default=False,
    show_default=True,
    help="Require the target to resolve against the Windrose Steam manifest when available.",
)
@click.option(
    "--ship-key-prefix",
    default=None,
    help="Optional R5BLShip key prefix to target a specific ship blob.",
)
@click.option(
    "--out",
    "out_path",
    default=None,
    type=click.Path(),
    help="Optionally write the planned/applied result JSON to this file.",
)
@click.pass_context
def inventory_set_ship_count_cmd(
    ctx: click.Context,
    target: str,
    new_count: int,
    current_count: int | None,
    all_matches: bool,
    write: bool,
    strict_manifest: bool,
    ship_key_prefix: str | None,
    out_path: str | None,
) -> None:
    """Update the count of existing ship chest stack(s) with backup-first safety."""
    import json

    from .inventory_write import apply_ship_chest_count_update

    if new_count < 0:
        raise click.BadParameter("--count must be >= 0")

    save_root = _find_save_root(ctx.obj["save_root"])
    _echo_resolved_db_path("players", _resolve_db_dir(save_root, "players"))

    result = apply_ship_chest_count_update(
        save_root,
        target=target,
        new_count=new_count,
        expected_current_count=current_count,
        update_all_matches=all_matches,
        dry_run=not write,
        strict_manifest=strict_manifest,
        preferred_ship_key_prefix=ship_key_prefix,
    )

    if out_path:
        Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    click.echo(f"Mode: {'write' if write else 'dry-run'}")
    click.echo(f"Target: {result['target']} -> {result['asset_path']}")
    click.echo(
        "Matches: "
        f"logical={result['match_count_logical']} "
        f"physical={result['match_count_physical']}"
    )
    for upd in result.get("plan", []):
        slot_text = upd.get("slot_index") if upd.get("slot_index") is not None else "?"
        click.echo(
            "  "
            f"slot={slot_text} item_id={upd.get('item_id') or '<none>'} "
            f"{upd['current_count']} -> {upd['new_count']} "
            f"physical_records={upd['physical_record_count']}"
        )
        confidence = upd.get("mapping_confidence", "unknown")
        source = upd.get("mapping_source", "unknown")
        click.echo(f"    mapping={confidence} source={source}")
        if upd.get("manifest_path"):
            click.echo(f"    manifest: {upd['manifest_path']}")

    if result.get("backup_path"):
        click.echo(f"Backup: {result['backup_path']}")
    if out_path:
        click.echo(f"Wrote ship count update result: {out_path}")


@cli.command("manifest-check")
@click.argument("targets", nargs=-1)
@click.option("--query", default=None, help="Filter manifest inventory assets by substring.")
@click.option("--limit", default=25, show_default=True, type=int, help="Maximum manifest assets to list.")
@click.option(
    "--strict-manifest/--no-strict-manifest",
    default=False,
    show_default=True,
    help="When resolving provided targets, fail if a manifest exists and the target cannot be validated against it.",
)
@click.option("--out", "out_path", default=None, type=click.Path(), help="Optionally write JSON output to this file.")
def manifest_check_cmd(
    targets: tuple[str, ...],
    query: str | None,
    limit: int,
    strict_manifest: bool,
    out_path: str | None,
) -> None:
    """Inspect the Windrose Steam manifest and preview resolvable inventory targets."""
    import json

    manifest_path = locate_windrose_manifest()
    if manifest_path is None:
        raise click.ClickException(
            "Windrose Steam manifest not found. Set WINDROSE_MANIFEST_PATH or install the game in a scanned Steam library."
        )

    target_results: list[dict[str, object]] = []
    asset_results: list[dict[str, str]] = []

    click.echo(f"Manifest: {manifest_path}")

    if targets:
        click.echo(f"Target checks: {len(targets)}")
        for target in targets:
            try:
                resolved = resolve_inventory_asset_target(target, strict_manifest=strict_manifest)
                status = {
                    "requested": target,
                    "resolved": True,
                    **resolved,
                }
                target_results.append(status)
                click.echo(
                    f"  {target} -> {resolved['asset_path']} mapping={resolved['mapping_confidence']} source={resolved['mapping_source']}"
                )
            except KeyError as exc:
                status = {
                    "requested": target,
                    "resolved": False,
                    "error": str(exc),
                }
                target_results.append(status)
                click.echo(f"  {target} -> ERROR: {exc}")

    assets = search_manifest_inventory_assets(query, limit=limit)
    asset_results = assets
    if query or not targets:
        heading = f"Manifest assets matching {query!r}:" if query else "Manifest assets:"
        click.echo(heading)
        for asset in assets:
            click.echo(f"  {asset['asset_name']} -> {asset['asset_path']}")
        if not assets:
            click.echo("  No manifest assets matched.")

    if out_path:
        result = {
            "manifest_path": str(manifest_path),
            "targets": target_results,
            "assets": asset_results,
        }
        Path(out_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        click.echo(f"Wrote manifest check: {out_path}")


# ---------------------------------------------------------------------------
# backups
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("db", type=click.Choice(["players", "accounts"]))
@click.pass_context
def backups(ctx: click.Context, db: str) -> None:
    """List existing backups for a database."""
    save_root = _find_save_root(ctx.obj["save_root"])
    db_dir = _resolve_db_dir(save_root, db)
    _echo_resolved_db_path(db, db_dir)
    existing = list_backups(db_dir)
    if not existing:
        click.echo("No backups found.")
    else:
        for p in existing:
            info = backup_details(p)
            size_mb = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1_048_576
            current_marker = info.get("current_marker") or "?"
            file_count = info.get("file_count") or 0
            click.echo(
                f"  {p.name}  ({size_mb:.1f} MB, files={file_count}, current={current_marker})"
            )


@cli.command("restore-backup")
@click.argument("db", type=click.Choice(["players", "accounts"]))
@click.argument("backup_name")
@click.pass_context
def restore_backup_cmd(ctx: click.Context, db: str, backup_name: str) -> None:
    """Restore a backup into the active DB path using an exact replace, not an overlay copy."""
    save_root = _find_save_root(ctx.obj["save_root"])
    db_dir = _resolve_db_dir(save_root, db)
    _echo_resolved_db_path(db, db_dir)

    backup_root = Path(__file__).resolve().parent / "_backups" / db_dir.parent.name
    backup_path = backup_root / backup_name
    if not backup_path.exists():
        raise click.ClickException(f"Backup not found: {backup_path}")

    result = restore_backup(backup_path, db_dir)
    click.echo(f"Restored from: {result['backup_path']}")
    click.echo(f"Destination: {result['destination_db_path']}")
    click.echo(f"File count: {result['restored_file_count']} / expected {result['expected_file_count']}")
    click.echo(f"CURRENT: {result['current_marker']}")
    click.echo(f"Exact match: {result['matches_backup']}")


@cli.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Report active save paths and flag divergent live save locations."""
    save_root = _find_save_root(ctx.obj["save_root"])
    player_dir = _resolve_db_dir(save_root, "players")
    accounts_dir = _resolve_db_dir(save_root, "accounts")
    windrose_player_dir = _windrose_player_dir(save_root)

    click.echo(f"Resolved save root: {save_root}")
    click.echo(f"Players DB path: {player_dir}")
    click.echo(f"Accounts DB path: {accounts_dir}")
    click.echo(f"Players CURRENT: {_read_current_marker(player_dir) or '?'}")
    click.echo(f"Players files: {_file_count(player_dir)}")

    if windrose_player_dir is None:
        click.echo(f"Windrose mirror: not found under {_WINDROSE_PLAYERS_ROOT}")
        return

    click.echo(f"Windrose mirror path: {windrose_player_dir}")
    click.echo(f"Windrose CURRENT: {_read_current_marker(windrose_player_dir) or '?'}")
    click.echo(f"Windrose files: {_file_count(windrose_player_dir)}")

    comparison = _compare_dirs(player_dir, windrose_player_dir)
    click.echo(
        f"Divergence: R5-only={len(comparison['a_only'])} Windrose-only={len(comparison['b_only'])}"
    )
    for rel_path in comparison["a_only"][:5]:
        click.echo(f"  R5-only: {rel_path}")
    for rel_path in comparison["b_only"][:5]:
        click.echo(f"  Windrose-only: {rel_path}")
