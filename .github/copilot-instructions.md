# Copilot Instructions

Read [AGENTS.md](../AGENTS.md) for the full agent guide. The rules below are the highest-priority constraints — violations here cause real data loss or game corruption.

## Non-Negotiable Rules

**RocksDB NoCompression** — All write paths in `db.py` must set `DBCompressionType.none()` on both the DB options object and every column family options object. Compressed writes corrupt save files silently and break game boot.

**Backup before write** — Every write command must create a backup snapshot before mutation. Never weaken or bypass the backup model.

**Dry-run default** — Write commands default to `--dry-run`. Do not flip this default.

**No root-level artifacts** — Route all generated files (JSON, HTML, scripts, notes) to `tmp/<task-name>/`. Do not create files at the repository root.

**No top-level imports from `save_context` in `db.py`** — `save_context.py` imports from `db.py`. Any `db.py` function that needs `save_context` helpers must use a lazy import inside the function body to avoid a circular import.

## Key Architecture Facts

- Save root contains one `Accounts/` DB and N `Players/` DBs (one per captain).
- `save_context.resolve_player_dir(save_root, captain_uuid=None)` is the single source of truth for which Players DB to open. Use it everywhere. Do not call `_locate_single_subdir` on `Players/` directly.
- All domain functions that touch Players DB accept `captain_uuid: str | None = None` and thread it through to `open_players_db()`.
- CLI entrypoint: `.venv\Scripts\r5-save.exe`. Do not use `python -m r5_save_tool.cli`.

## Voice and Commit Style

Lightly nautical tone, one subtle term per message max (`aye`, `ahoy`, `matey`). No pirate phrasing in security fixes, incident notes, or user-facing safety content. See AGENTS.md for examples.
