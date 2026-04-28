# Windrose Save Tool

## Why This Exists

This project exists to inspect and safely edit Windrose (R5) save data stored in local RocksDB databases.

The immediate use case was coin editing, but the codebase is broader than that:

- dump raw key/value pairs from the save databases
- search keys and embedded string values
- decode Unreal-style binary value blobs into structured JSON
- generate a searchable HTML report for manual inspection
- calibrate and edit coin counts with backup-first write protection
- add manifest-validated item stacks into ship inventory slots
- inspect and validate inventory targets against the Windrose Steam manifest

The main design goal is simple: make reversible, observable save edits without hand-editing RocksDB files or guessing offsets blindly.

## What It Works With

The tool targets the save layout under:

`%USERPROFILE%\AppData\Local\R5\Saved\SaveProfiles\<steam_id>\RocksDB\0.10.0`

It understands two databases:

- `Players`
- `Accounts`

For `Players`, it currently knows these column families:

- `default`
- `R5LargeObjects`
- `R5BLPlayer`
- `R5BLShip`
- `R5BLBuilding`
- `R5BLActor_BuildingBlock`

For `Accounts`, it knows:

- `default`
- `R5LargeObjects`
- `R5BLAccount`

## Install And Run

This project is a Python package with a Click CLI.

Install editable:

```powershell
pip install -e .
```

Then use either of these entrypoints:

```powershell
r5-save --help
```

or, if you are running directly from source without the generated console script:

```powershell
python -c "from r5_save_tool.cli import cli; cli()" --help
```

Prefer the generated console script from `.venv\Scripts\r5-save.exe` for validation work inside this repository. Do not assume `python -m r5_save_tool.cli` is a supported entrypoint.

### Desktop UI

For desktop UI usage details, see `docs/ui.md`.

Preferred launch paths:

```powershell
# Repository/dev launch
.venv\Scripts\r5-save-ui.exe

# Distributable launch
dist\r5-save-tool\r5-save-tool.exe
```

Fresh dist build:

```powershell
Get-Process | Where-Object { $_.Path -like "*dist\\r5-save-tool*" } | Stop-Process -Force
Remove-Item -Recurse -Force .\dist\r5-save-tool -ErrorAction SilentlyContinue
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller build_exe.spec --noconfirm
```

You can point the tool at a specific save root with `--save-root`, or set `R5_SAVE_ROOT`.

The tool now prints the resolved live DB path for write-oriented commands so you can confirm which save location is being mutated.

## Core Commands

Inspection:

```powershell
r5-save dump players --cf R5BLPlayer
r5-save decode players R5BLPlayer --out player_decoded.json
r5-save report --out r5_save_report.html
r5-save search-key Inventory
r5-save search-value CoinGuinea
```

Single-key read/write:

```powershell
r5-save get players R5BLPlayer <hex-key>
r5-save put players R5BLPlayer <hex-key> <hex-value>
```

Coin workflow:

```powershell
r5-save coin-inspect --out coin_inspect.json
r5-save coin-map --person-piastre 3 --person-guinea 2 --ship-piastre 909 --ship-guinea 7
r5-save coin-set --known-person-piastre 3 --known-person-guinea 2 --known-ship-piastre 909 --known-ship-guinea 7 --set-person-piastre 1003 --set-person-guinea 102 --set-ship-piastre 1909 --set-ship-guinea 107 --dry-run
r5-save coin-set --known-person-piastre 3 --known-person-guinea 2 --known-ship-piastre 909 --known-ship-guinea 7 --set-person-piastre 1003 --set-person-guinea 102 --set-ship-piastre 1909 --set-ship-guinea 107 --write
```

Manifest-backed inventory workflow:

```powershell
r5-save manifest-check rope /R5BusinessRules/InventoryItems/DefaultItems/Misc/DA_DID_Misc_CoinGuinea_T03.DA_DID_Misc_CoinGuinea_T03 --query Coin --limit 5
r5-save inventory-add-ship --target rope=10 --strict-manifest --dry-run --out tmp/inventory/rope_plan.json
r5-save inventory-add-ship --target rope=10 --strict-manifest --write --out tmp/inventory/rope_write.json
```

Backups:

```powershell
r5-save doctor
r5-save backups players
r5-save backups accounts
r5-save restore-backup players 0A4AA38532484CFE4D874A73ABC43A82_20260418_155218
```

## Safety Model

The write path is intentionally conservative.

- `put` backs up the target DB before writing unless `--no-backup` is used
- `coin-set` defaults to `--dry-run`
- `coin-set` requires high-confidence mappings by default
- `inventory-add-ship` can run with `--strict-manifest` to fail closed when a manifest exists but a target is not present in it
- the tool stores full RocksDB directory backups under `r5_save_tool/_backups/`
- each backup now includes a metadata manifest with the original DB path, `CURRENT` marker, and file inventory
- `restore-backup` performs an exact replace restore instead of an overlay copy
- `doctor` reports the resolved active save path and flags divergence between the R5 and Windrose live locations

You should still treat every write as experimental and keep a known-good restore point.

## Workspace Hygiene

Use `tmp/` for scratch artifacts, generated reports, ad hoc scripts, and disposable notes. Keep the repository root reserved for durable source files, package code, and stable documentation.

## Important Write Constraint

The most important implementation detail discovered during live testing is this:

**new SST files must be written with `NoCompression`**

R5 uses RocksDB options that expect uncompressed SST blocks. `rocksdict` enables compression by default, which produced valid RocksDB files that the game still failed to boot from. The fix was to explicitly set both normal and bottommost compression to `none` for the DB and every column family.

Without that setting, even a no-op write can make the save unbootable.

See `docs/architecture.md` for the details.

## Document Set

- `docs/architecture.md`: module layout and write-path behavior
- `docs/examples.md`: practical command sequences and recovery flows
- `docs/SAFETY.md`: operational safety, backups, and restore procedures
- `docs/MAPPINGS.md`: item and coin mapping confidence guidance
- `docs/piastre-mapping-notes.md`: why player Piastre mapping is hard and the deterministic path forward

Key developer modules for the inventory workflow:

- `r5_save_tool/manifest.py`: manifest discovery and parsing
- `r5_save_tool/inventory_targets.py`: shared alias + manifest-backed target resolution
- `r5_save_tool/inventory_write.py`: write path for ship slot mutation

## Current Status

- Ship inventory insertion via manifest-backed item targets is now validated in game.
- The first confirmed live test inserted `222` Guinea and `10` rope correctly into ship storage.
- Coin counter mutation remains a harder problem and should not be conflated with inventory item insertion.
