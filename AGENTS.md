# Agent Guide

## Purpose

This repository is a Python desktop tool for inspecting and safely editing Windrose (R5) game saves stored in RocksDB. It ships as a FastAPI + pywebview app (UI mode) and a Click CLI (terminal mode).

Agents working here should optimize for three things:

- keep save edits reversible and observable
- prefer changes in packaged code over throwaway root scripts
- keep the workspace root clean by routing temporary outputs into `tmp/`

---

## Voice and Commit Message Style

Use a lightly nautical tone for agent-authored prose and commit messages.

- Keep clarity and technical precision first.
- Use at most one subtle pirate term per message (for example: `aye`, `ahoy`, `matey`).
- Do not force pirate phrasing when it would sound unnatural.
- Do not alter technical terms, file paths, commands, symbol names, issue IDs, or error text for style.
- Keep Conventional Commit structure and normal project conventions intact.
- Disable pirate flavor for security-sensitive fixes, incident response, migration notes, release notes, and user-facing safety instructions.

Commit message examples (light touch):

- `feat(inventory): add strict manifest validation, aye`
- `fix(db): preserve NoCompression across all column families`
- `docs(cli): clarify --dry-run output for inventory plan, ahoy`

---

## Project Shape

```
r5_save_tool/       package code — the real implementation surface
docs/               durable project documentation
tests/              pytest test suite
tmp/                clearable scratch area for generated artifacts and exploratory scripts
r5_save_tool/_backups/  tool-managed backups created before writes
```

Key modules inside `r5_save_tool/`:

| Module | Role |
|---|---|
| `cli.py` | Click commands and user-facing entrypoints |
| `db.py` | RocksDB open/read/write helpers and column-family setup |
| `save_context.py` | Save root discovery, captain enumeration, directory resolution |
| `backup.py` | Full-directory backup helpers (create, list, restore) |
| `dump.py` | Raw key-value dumping and text search |
| `schema.py` | Key/value formatting helpers |
| `ue_parser.py` | Parser for the Unreal-style binary record format inside values |
| `report.py` | Self-contained HTML report generator |
| `coin.py` | Coin inspection, calibration, and patching |
| `inventory.py` | Inventory inspection and stage planning |
| `inventory_targets.py` | Shared alias + manifest-backed inventory target resolution |
| `inventory_write.py` | Ship inventory modification with mapping confidence |
| `manifest.py` | Windrose Steam manifest discovery and inventory asset parsing |
| `paths.py` | Writable base path resolution (supports PyInstaller bundles) |
| `ui_api.py` | FastAPI app: REST endpoints for the web UI |
| `ui_service.py` | Service layer: bridges domain functions to the UI API |
| `ui_window.py` | pywebview window launcher |

---

## Command Entry Points

Prefer the installed console script from the repository virtual environment:

```powershell
.venv\Scripts\r5-save.exe --help
```

Do not assume `python -m r5_save_tool.cli` is the CLI entrypoint. `cli.py` does not expose a `__main__` guard.

If the console script is unavailable, invoke Click directly:

```powershell
.venv\Scripts\python.exe -c "from r5_save_tool.cli import cli; cli()" --help
```

---

## Save Directory Layout

The tool targets a save root that resolves through `find_save_root()` in `save_context.py`:

```
SaveProfiles/{SteamID}/RocksDB_v2/0.10.0/   ← save root
    Accounts/{UUID}/                          ← one shared account DB
    Players/{UUID}/                           ← one DB per captain (may be N > 1)
    Worlds/{UUID}/
```

### Multi-Captain Support

The save root may contain multiple `Players/{UUID}/` directories — one per captain. The tool auto-selects the correct one using `DefaultPlayerId` from the shared `Accounts` blob.

Key functions in `save_context.py`:

- `list_captains(save_root)` — returns `[{uuid, name, is_default, db_path}]` for every captain
- `resolve_player_dir(save_root, captain_uuid=None)` — resolves the active Players DB:
  1. One dir → use it
  2. Multiple dirs + no `captain_uuid` → auto-select via `DefaultPlayerId` from Account
  3. Multiple dirs + explicit `captain_uuid` → find that UUID
- `get_default_player_id(save_root)` — reads `DefaultPlayerId` from the `R5BLAccount` blob
- `extract_player_name(player_db_dir)` — reads `PlayerName` from the `R5BLPlayer` blob
- `resolve_db_dir(save_root, db, captain_uuid=None)` — dispatches to `resolve_player_dir` for `"players"` or `_locate_single_subdir` for `"accounts"`

### `captain_uuid` Threading

All domain functions that touch the Players DB accept `captain_uuid: str | None = None` and pass it to `open_players_db()` or `resolve_player_dir()`. The chain is:

```
cli.py --captain flag
  → ctx.obj["captain"]
  → domain functions (inventory.py, coin.py, inventory_write.py, report.py)
  → open_players_db(save_root, captain_uuid=captain_uuid)
  → resolve_player_dir(save_root, captain_uuid)
```

```
ui_api.py PUT /api/config {captain_uuid}
  → ui_service.py UIConfigState.captain_uuid
  → self._captain_uuid()
  → domain functions
```

### Circular Import Constraint

`save_context.py` imports from `db.py` at the module level. `db.py` must therefore import from `save_context.py` only via **lazy imports inside function bodies**:

```python
def open_players_db(save_root, read_only=True, captain_uuid=None):
    from .save_context import resolve_player_dir  # lazy — avoids circular import
    db_path = resolve_player_dir(save_root, captain_uuid)
    ...
```

Never add a top-level `from .save_context import ...` in `db.py`.

---

## Save Safety Rules

- Treat every write as experimental unless proven otherwise.
- Preserve the backup-first model already implemented by the tool.
- Do not weaken write verification or mapping confidence checks without a concrete reason.
- **Keep the verified RocksDB compatibility fix intact**: writes must use `NoCompression` for the DB options and every column family options object.
- Prefer manifest-backed inventory resolution. Use `--strict-manifest` for inventory validation work when the Steam manifest is available.

### RocksDB NoCompression Requirement

This is the single most critical write rule. The game's RocksDB build cannot read blocks written with compression. `db.py` must always apply:

```python
opts.set_compression_type(DBCompressionType.none())
opts.set_bottommost_compression_type(DBCompressionType.none())
```

This is applied to both the top-level DB options **and** every column family options object. If you see any compression settings, the write path is broken.

---

## CLI Command Reference

### Inspection Commands (Read-Only)

- `dump` — raw key-value pairs from column families
- `search-key` / `search-value` — find entries by pattern
- `get` — retrieve a single key-value pair
- `decode` — decode a full column family to structured JSON
- `report` — generate an HTML report of all save data
- `inventory-inspect` — analyze inventory items and counts
- `manifest-check` — preview item target resolution against the Steam manifest
- `coin-inspect` — find coin objects and calibration offsets
- `doctor` — report save paths and detect divergence
- `backups` — list existing backups with metadata
- `list-captains` — list all captains found in the save, with names and default marker

### Write Commands (With Backup & Dry-Run)

- `put` — raw key-value write (low-level)
- `coin-map` — calibrate coin offsets from known values
- `coin-set` — modify coin amounts (with confidence gating)
- `inventory-add-ship` — add item stacks to empty ship slots
- `inventory-set-ship-count` — update counts for existing ship chest stacks

### Safety Commands

- `restore-backup` — restore a specific backup using clean directory replacement

### Multi-Captain Flag

```powershell
r5-save --captain <UUID> inventory-inspect
```

`--captain` accepts a full UUID string and can also be set via `R5_CAPTAIN` env var. When omitted with multiple captains present, the tool auto-selects the `DefaultPlayerId`.

---

## Validation

After changing behavior, run the narrowest validation that proves the change.

```powershell
# Import sanity (catches circular import regressions)
.venv\Scripts\python.exe -c "from r5_save_tool.cli import cli; from r5_save_tool.ui_api import app; print('ok')"

# Report generation
r5-save report --out tmp/report/report.html

# Inventory inspection
r5-save inventory-inspect --out tmp/inventory/inventory_inspect.json

# Manifest check
r5-save manifest-check rope --query Coin --limit 5

# Inventory dry-run
r5-save inventory-add-ship --target rope=10 --strict-manifest --dry-run --out tmp/inventory/ship_dryrun.json

# List captains
r5-save list-captains
```

If you change output shape, verify both the CLI summary and the written JSON or HTML artifact.

---

## Workspace Hygiene

The root contains historical scan artifacts. Do not add to that pattern.

When generating temporary files:

- put them under `tmp/<task-name>/`
- use descriptive names and keep related files together
- prefer deleting stale scratch outputs instead of creating more root-level files
- promote only stable, reusable assets into `docs/` or packaged code

Examples:

- `tmp/inventory-validation/inventory_inspect_current.json`
- `tmp/coin-mapping/probe_a.json`
- `tmp/scripts/repro_inventory_parse.py`

---

## Python Conventions

- Target Python 3.11+ compatible code unless the repo intentionally moves higher.
- Prefer `pathlib.Path`, typed function signatures, and small focused helpers.
- Keep business logic in `r5_save_tool/`, not in ad hoc root scripts.
- Add new dependencies only when they clearly simplify the code or reduce risk.
- Match the existing Click CLI style for new commands and options.
- Update docs when command behavior or output semantics change.

---

## Inventory-Specific Context

Current inventory inspection semantics distinguish:

- `raw_items`: all discovered inventory-like records
- `items`: visible slotted inventory records used for current-state summaries
- `detached_items`: unresolved inventory-like objects not tied to visible slot scopes

Keep that distinction intact unless you are intentionally redesigning the model.

Inventory target resolution layers:

- `inventory_targets.py` — shared resolver for aliases, explicit paths, and Steam manifest validation
- `r5-save manifest-check` — fastest way to preview how an item target resolves
- `inventory-add-ship` and `inventory-plan` support `--strict-manifest` and should use it for cautious automation

Validated workflow status:

- Ship inventory insertion with manifest-backed targets is validated in game.
- Confirmed live test: `222` Guinea and `10` rope inserted correctly into ship storage.
- Coin counter mutation remains a separate workflow and is still constrained by field-mapping quality.

---

## Unit Testing

The project uses pytest. Tests live in `tests/` and validate critical paths that are likely to break with game updates.

### Running Tests

```powershell
# Install dev dependencies (one-time)
uv sync --extra dev

# Run all tests with coverage
pytest tests/ -v --cov=r5_save_tool --cov-report=html

# Run tests for a specific module
pytest tests/test_inventory.py -v

# Run tests matching a pattern
pytest tests/ -k "ship_name" -v
```

### Test Coverage

| Test file | What it guards |
|---|---|
| `test_db.py` | RocksDB reading, column family access, NoCompression constraint |
| `test_inventory.py` | Item classification, scope detection, aggregation |
| `test_ship_names.py` | Custom name extraction, ship type detection (critical for UI grouping) |
| `test_save_context.py` | Path resolution, doctor status, multi-captain enumeration |
| `test_backup.py` | Backup creation, listing, safety model |
| `test_ui_api_contracts.py` | Pydantic models, request/response validation |
| `test_service_contracts.py` | Response data structures, field presence and types |
| `test_data_contracts.py` | Item fields, scope classification, asset paths |
| `test_cli_contracts.py` | Command structure, argument validation, help output |

### Critical Tests (Must Pass Before Release)

- `test_db.py::TestDatabaseOperations::test_db_compression_setting_preserved`
- `test_inventory.py::TestInventoryInspection::test_inventory_items_have_required_fields`
- `test_ship_names.py::TestShipNameExtraction::test_ship_names_extracted_from_real_save`
- `test_backup.py::TestBackupOperations::test_backup_database_creates_backup`
- `test_ui_api_contracts.py::TestRequestModelValidation`
- `test_service_contracts.py::TestInventoryInspectResponseContract`
- `test_data_contracts.py::TestInventoryScopeClassificationContract`
- `test_cli_contracts.py::TestCLICommandStructure`

### Adding Tests

When adding a feature or fixing a bug, add tests that verify:

1. Happy path: the feature works as intended
2. Edge cases: empty inputs, missing data, malformed data
3. Game update resilience: if the game changes the data format, the test catches it
4. External contracts: if you change a public API/response shape, the test fails

---

## Known Pitfalls

### RocksDB Test Fixture Integrity

`test_saves/Players/ActiveProfile/CURRENT` must contain a valid manifest pointer line ending in newline, e.g. `MANIFEST-031233\n`. If this file is empty or malformed, many tests will fail or skip with RocksDB corruption errors.

### Save-Root Shape Expectations

`find_save_root` expects `RocksDB_v2/0.10.0` or `RocksDB/0.10.0` layout. Service-level tests that call `UIService` paths should configure save roots that satisfy that layout.

### Multi-Captain Auto-Selection Dependency

`resolve_player_dir` auto-selection requires a readable `Accounts` DB. If the account DB is missing or unreadable, `get_default_player_id` returns `None` and the function raises `FileNotFoundError` with an instruction to use `--captain`. This is intentional fail-safe behavior.

### Circular Import

`db.py` must never import from `save_context.py` at module scope. Any new functions in `db.py` that need save context helpers must use lazy imports inside the function body.

### Test Reliability

- Avoid broad `except Exception` in tests around assertions.
- Catch only expected infrastructure exceptions and let assertion failures fail loudly.

### PowerShell Command Portability

- Prefer `Select-Object -Last N` over `tail -N` when inspecting output in PowerShell.
- Prefer `.venv\Scripts\*.exe` entrypoints over implicit global tools.
