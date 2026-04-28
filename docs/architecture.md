# Architecture

## High-Level Shape

The tool is organized as a thin CLI over a small set of focused modules:

- `r5_save_tool/cli.py`: Click commands and user-facing entrypoints
- `r5_save_tool/db.py`: RocksDB open/read/write helpers and column-family setup
- `r5_save_tool/backup.py`: full-directory backup helpers (create, list, restore)
- `r5_save_tool/dump.py`: raw dumping and text search
- `r5_save_tool/schema.py`: key/value formatting helpers
- `r5_save_tool/ue_parser.py`: parser for the Unreal-style binary record format used inside values
- `r5_save_tool/report.py`: self-contained HTML report generator
- `r5_save_tool/coin.py`: coin inspection, calibration, and patching logic
- `r5_save_tool/inventory.py`: inventory inspection and stage planning
- `r5_save_tool/inventory_targets.py`: shared alias + manifest-backed inventory target resolution
- `r5_save_tool/inventory_write.py`: ship inventory modification with mapping confidence
- `r5_save_tool/manifest.py`: Windrose Steam manifest discovery and inventory asset parsing

## Operational Conventions

Two repository conventions matter for day-to-day work:

1. Use the installed console script as the primary CLI entrypoint.
2. Keep generated artifacts out of the repository root.

The preferred validation command in this repository is:

```powershell
.venv\Scripts\r5-save.exe --help
```

If you need a source-only fallback, invoke Click directly:

```powershell
.venv\Scripts\python.exe -c "from r5_save_tool.cli import cli; cli()" --help
```

Do not rely on `python -m r5_save_tool.cli`; `cli.py` does not expose a `__main__` guard.

## CLI Command Categories

The tool's commands are organized around three main workflows:

### Inspection Commands (Read-Only)

- `dump` – dump raw key-value pairs from column families
- `search-key` / `search-value` – find entries by pattern
- `get` – retrieve a single key-value pair
- `decode` – decode a full column family to structured JSON
- `report` – generate an HTML report of all save data
- `inventory-inspect` – analyze inventory items and counts
- `manifest-check` – inspect manifest-backed item resolution and preview target canonicalization
- `coin-inspect` – find coin objects and calibration offsets
- `doctor` – report save paths and detect divergence
- `backups` – list existing backups with metadata

### Write Commands (With Backup & Dry-Run)

- `put` – raw key-value write (low-level)
- `coin-map` – calibrate coin offsets from known values
- `coin-set` – modify coin amounts (with confidence gating)
- `inventory-add-ship` – add item stacks to empty ship slots
- `inventory-set-ship-count` – update counts for existing ship chest stacks

All write commands:
1. Accept `--dry-run` (default) to preview changes without applying them
2. Create automatic backups before writing
3. Require high confidence or explicit `--confirm-assumed` flag for assumed mappings

Inventory-specific safeguard:

- `inventory-add-ship` and `inventory-plan` can use `--strict-manifest` to fail closed when a target cannot be validated against the Windrose Steam manifest.
- `inventory-set-ship-count` supports `--current-count` and single-match default behavior to reduce accidental updates.

## Report UX

The HTML report now includes an inventory-first navigation flow:

- `Inventory Snapshot` is its own sidebar tab and the default landing view
- `Hide null/empty` toggle is enabled by default
- `Inventory At a Glance` projection keys summarize item totals by scope and item

The full key/value browser remains available via `All` and section tabs.

### Safety Commands

- `restore-backup` – restore a specific backup using clean directory replacement
- `backups` – list backups with size, file count, and manifest markers

## Operational Safeguards

The tool implements three layers of safety:

1. **Automatic backups**: Every write creates a snapshot before mutation
2. **Dry-run validation**: All write commands accept `--dry-run` (the default) for verification
3. **Clean restore**: `restore-backup` replaces the entire DB directory atomically, avoiding stale files

### Backup Workflow

```powershell
# 1. Inspect and plan
r5-save inventory-inspect --out tmp/plan.json

# 2. Dry-run the changes
r5-save inventory-add-ship --target nails=300 --dry-run --out tmp/dryrun.json

# 3. Review dry-run output

# 4. Apply the write (backup is automatic)
r5-save inventory-add-ship --target nails=300 --write --out tmp/write.json

# 5. Test in-game

# 6. If problems: restore from backup
r5-save restore-backup players [BACKUP_NAME]
```

### Divergence Detection

The `doctor` command detects when the R5 and Windrose save directories diverge:

```powershell
r5-save doctor
```

Output includes:
- Resolved R5 save path
- Resolved Windrose mirror path
- File count and CURRENT manifest marker for each
- Divergence summary (R5-only, Windrose-only files)

If divergence is detected:
1. Restore a known-good backup to both paths
2. Verify with `doctor` that they're synchronized again

## Workspace Hygiene

Temporary outputs should go under `tmp/`, not at the repository root.

Use `tmp/<task-name>/` for:

- generated JSON and HTML outputs
- exploratory scripts
- short-lived notes and reports

Durable assets belong in:

- `r5_save_tool/` for product code
- `docs/` for stable documentation

## Save Layout Assumptions

The code assumes a save root that contains:

- `Accounts/<active_db_dir>`
- `Players/<active_db_dir>`

`db.py` resolves the active child directory by looking for the only non-underscore directory, or the one containing `CURRENT` and `MANIFEST-*`.

## Database Access

`R5Database` wraps a single `rocksdict.Rdict` instance and exposes:

- `iter_cf()`
- `get()`
- `put()`
- `delete()`

Two details matter here:

1. RocksDB must be opened with every column family declared up front.
2. Writes must use the same compression behavior the game expects.

## Critical Write Detail: NoCompression

This project hit a real failure mode during testing:

- reads worked
- dry-runs worked
- writes completed successfully
- the game stopped booting afterward

Root cause:

- `rocksdict` writes compressed SST blocks by default
- the game database options are `NoCompression`
- the game's RocksDB build appears unable or unwilling to read the compressed blocks generated by the default `rocksdict` write path

The fix in `db.py` is to force:

- `set_compression_type(DBCompressionType.none())`
- `set_bottommost_compression_type(DBCompressionType.none())`

This is applied both to the top-level DB options and to every column family options object.

That change made no-op writes bootable again and restored compatibility with live saves.

## Value Format

`ue_parser.py` documents the outer blob layout as:

```text
uint32 total_byte_count
[records...]
```

Each record is a simple tagged structure using a type byte, a null-terminated field name, and a type-specific payload.

Relevant scalar types seen so far:

- `0x02`: FString-like string
- `0x03`: nested object/blob
- `0x04` and `0x05`: int32 plus a trailing byte
- `0x10`: int32

The parser is intentionally pragmatic rather than formal. It is optimized for inspection and discovery.

## Inventory Inspection Model

The current inventory inspection flow distinguishes between several levels of certainty:

- `raw_items`: all discovered inventory-like objects
- `items`: visible slot-backed records used for current inventory summaries
- `detached_items`: inventory-like objects that are not currently tied to visible slot scopes

This distinction matters because not every `/R5BusinessRules/InventoryItems/...` reference is a visible backpack or ship-storage item. Quest, equipment, invisible, NPC, and other slot scopes can all carry inventory-like references.

## Inventory Target Resolution

Inventory target resolution is now shared rather than duplicated in command-specific code.

Resolution order:

1. exact or normalized match against the Windrose Steam manifest
2. built-in alias resolution
3. explicit inventory path fallback

When `--strict-manifest` is enabled and a Steam manifest is available, step 3 is rejected unless the explicit path also exists in the manifest.

This same resolution model is used by:

- `manifest-check`
- `inventory-add-ship`
- `inventory-plan`

That alignment matters because planning and writing now canonicalize targets the same way.

## Validation Status

The manifest-backed ship inventory insertion path has been validated in game.

Confirmed live test:

- `CoinGuinea` inserted as a ship inventory item stack with count `222`
- `Rope` inserted as a ship inventory item stack with count `10`

This validation applies to manifest-backed item insertion, not to coin counter mutation logic.

## Coin Workflow Internals

Coin editing lives in `coin.py` and works in three stages.

### 1. Inspect

`inspect_coins()` scans `R5BLPlayer` and `R5BLShip` blobs, extracts type `0x03` objects with ASCII names, and identifies objects whose payloads contain `CoinPiastre` or `CoinGuinea`.

### 2. Calibrate

`map_coin_offsets_by_known_values()` does not assume a fixed field path. Instead, it:

- finds coin objects in each container blob
- finds every raw int32 offset matching a user-supplied known value
- chooses the nearest matching int32 to the coin object's byte offset
- assigns confidence from distance thresholds

This is why coin editing needs current known values first.

### 3. Patch

`apply_coin_values()`:

- recalculates mappings from known values
- verifies the current value at each target offset still matches calibration
- groups writes by blob
- patches int32 values in a `bytearray`
- writes the full updated value back through RocksDB

This is an in-place payload patch inside the logical blob, not a structural rewrite of the Unreal record format.

## Why Coin Writes Are Safe Enough To Iterate On

The write strategy avoids several common failure modes:

- it refuses missing mappings
- it refuses low-confidence mappings by default
- it verifies the old value before writing
- it writes a complete backup before mutation

That makes it suitable for iterative experiments like cap-testing or binary searching max values.

## Limitations

- the parser is partial and based on observed formats
- the coin workflow depends on proximity heuristics, not a complete schema
- large structural edits are not yet modeled as first-class operations
- restore is now available in the CLI, but it still assumes the backup itself is internally healthy
