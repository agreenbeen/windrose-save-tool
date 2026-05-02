# Agent Guide

## Purpose

This repository is a Python CLI for inspecting and safely editing Windrose (R5) save data stored in RocksDB databases.

Agents working here should optimize for three things:

- keep save edits reversible and observable
- prefer changes in packaged code over throwaway root scripts
- keep the workspace root clean by routing temporary outputs into `tmp/`

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

## Project Shape

- `r5_save_tool/`: package code and the real implementation surface
- `docs/`: durable project documentation
- `tmp/`: clearable scratch area for generated artifacts, ad hoc notes, and exploratory scripts
- `r5_save_tool/_backups/`: tool-managed backups created before writes

## Command Entry Points

Prefer the installed console script from the repository virtual environment:

```powershell
.venv\Scripts\r5-save.exe --help
```

Do not assume `python -m r5_save_tool.cli` is the CLI entrypoint. This module does not expose a `__main__` guard.

If the console script is unavailable, invoke Click directly:

```powershell
.venv\Scripts\python.exe -c "from r5_save_tool.cli import cli; cli()" --help
```

## Save Safety Rules

- Treat every write as experimental unless proven otherwise.
- Preserve the backup-first model already implemented by the tool.
- Do not weaken write verification or mapping confidence checks without a concrete reason.
- Keep the verified RocksDB compatibility fix intact: writes must use `NoCompression` for the DB and every column family.
- Prefer manifest-backed inventory resolution and use `--strict-manifest` for inventory validation work when the Steam manifest is available.

## Workspace Hygiene

The root currently contains many historical scan artifacts. Do not add to that pattern.

When generating temporary files:

- put them under `tmp/<task-name>/`
- use descriptive names and keep related files together
- prefer deleting stale scratch outputs instead of creating more root-level files
- promote only stable, reusable assets into `docs/` or packaged code

Examples:

- `tmp/inventory-validation/inventory_inspect_current.json`
- `tmp/coin-mapping/probe_a.json`
- `tmp/scripts/repro_inventory_parse.py`

## Python Conventions

- Target Python 3.11+ compatible code unless the repo intentionally moves higher.
- Prefer `pathlib.Path`, typed function signatures, and small focused helpers.
- Keep business logic in `r5_save_tool/`, not in ad hoc root scripts.
- Add new dependencies only when they clearly simplify the code or reduce risk.
- Match the existing Click CLI style for new commands and options.
- Update docs when command behavior or output semantics change.

## Inventory-Specific Context

Current inventory inspection semantics distinguish:

- `raw_items`: all discovered inventory-like records
- `items`: visible slotted inventory records used for current-state summaries
- `detached_items`: unresolved inventory-like objects not tied to visible slot scopes

Keep that distinction intact unless you are intentionally redesigning the model.

Inventory target resolution now has three important layers:

- `r5_save_tool/inventory_targets.py` is the shared resolver for aliases, explicit paths, and Steam manifest validation.
- `r5-save manifest-check` is the fastest way to preview how an item target resolves.
- `inventory-add-ship` and `inventory-plan` support `--strict-manifest` and should use it for cautious automation.

Validated workflow status:

- Ship inventory insertion with manifest-backed targets is validated in game.
- Confirmed live test: `222` Guinea and `10` rope inserted correctly into ship storage.
- Coin counter mutation remains a separate workflow and is still constrained by field-mapping quality.

## Validation

After changing behavior, run the narrowest validation that proves the change.

Examples:

- `r5-save report --out tmp/report/report.html`
- `r5-save inventory-inspect --out tmp/inventory/inventory_inspect.json`
- `r5-save manifest-check rope --query Coin --limit 5`
- `r5-save inventory-add-ship --target rope=10 --strict-manifest --dry-run --out tmp/inventory/ship_dryrun.json`

If you change output shape, verify both the CLI summary and the written JSON or HTML artifact.

After changing Windows packaging or heavyweight dependencies, rebuild the EXE and capture size with `python scripts/measure_exe_size.py --out tmp/exe-size/latest-measure.json` (see [docs/windows-packaging.md](docs/windows-packaging.md)).

## Known Pitfalls

### RocksDB test fixture integrity

- `test_saves/Players/ActiveProfile/CURRENT` must contain a valid manifest pointer line ending in newline, e.g. `MANIFEST-031233\n`.
- If this file is empty or malformed, many tests will fail or skip with RocksDB corruption errors.

### Save-root shape expectations

- `find_save_root` expects `RocksDB/0.10.0` layout.
- Service-level tests that call `UIService` paths should configure save roots that satisfy that layout.

### Test reliability

- Avoid broad `except Exception` in tests around assertions.
- Catch only expected infrastructure exceptions and let assertion failures fail loudly.

### PowerShell command portability

- Prefer `Select-Object -Last N` over `tail -N` when inspecting output in PowerShell.
- Prefer `.venv\Scripts\*.exe` entrypoints over implicit global tools.

## Unit Testing

The project uses pytest for unit testing. Tests are located in the `tests/` directory and validate critical paths that are likely to break with game updates.

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

Current test suite covers:

- **Database operations** (`tests/test_db.py`): RocksDB reading, column family access, compression constraints
- **Inventory parsing** (`tests/test_inventory.py`): Item classification, scope detection, aggregation
- **Ship name extraction** (`tests/test_ship_names.py`): Custom names, ship type detection (critical for UI grouping)
- **Save root detection** (`tests/test_save_context.py`): Path resolution, doctor status
- **Backup operations** (`tests/test_backup.py`): Backup creation, listing, safety model
- **UI API contracts** (`tests/test_ui_api_contracts.py`): Pydantic models, request/response validation
- **Service contracts** (`tests/test_service_contracts.py`): Response data structures, field presence and types
- **Data contracts** (`tests/test_data_contracts.py`): Item fields, scope classification, asset paths
- **CLI contracts** (`tests/test_cli_contracts.py`): Command structure, argument validation, help output

### Adding Tests

When adding a feature or fixing a bug, add tests that verify:

1. Happy path: the feature works as intended
2. Edge cases: empty inputs, missing data, malformed data
3. Game update resilience: if the game changes the data format, the test will catch it
4. External contracts: if you change a public API/response shape, the test will fail

Example: if the game changes how ship names are stored, tests will reveal that extraction fails.

### Critical Test Paths

These tests MUST continue to pass and should be run before any release:

- `test_db.py::TestDatabaseOperations::test_db_compression_setting_preserved` — validates RocksDB constraint
- `test_inventory.py::TestInventoryInspection::test_inventory_items_have_required_fields` — validates data contract
- `test_ship_names.py::TestShipNameExtraction::test_ship_names_extracted_from_real_save` — validates UI grouping works
- `test_backup.py::TestBackupOperations::test_backup_database_creates_backup` — validates safety model
- `test_ui_api_contracts.py::TestRequestModelValidation` — validates API request contracts
- `test_service_contracts.py::TestInventoryInspectResponseContract` — validates response data structures
- `test_data_contracts.py::TestInventoryScopeClassificationContract` — validates scope classification logic
- `test_cli_contracts.py::TestCLICommandStructure` — validates command-line interface stability