## Plan: Windrose Save Tool Branding Rename

Branding-only text update: replace all user-visible "R5 Save Tool" labels with **Windrose Save Tool** across Python sources, static UI assets, and docs. No package paths, CLI command names, env vars, game constants, or import paths change.

**Files modified (in dependency order)**

| File | What changes |
|---|---|
| [r5_save_tool/__init__.py](r5_save_tool/__init__.py) | Module docstring |
| [r5_save_tool/cli.py](r5_save_tool/cli.py) | Module docstring + `cli()` help text |
| [r5_save_tool/ui_api.py](r5_save_tool/ui_api.py) | FastAPI `title=` string |
| [r5_save_tool/ui_window.py](r5_save_tool/ui_window.py) | Module docstring, `WINDOW_TITLE`, startup print |
| [r5_save_tool/report.py](r5_save_tool/report.py) | HTML `<title>` and `<h1>` in template |
| [r5_save_tool/ui_static/app.js](r5_save_tool/ui_static/app.js) | Top comment + iframe `title=` attribute |
| [r5_save_tool/ui_static/styles.css](r5_save_tool/ui_static/styles.css) | Top comment |
| [README.md](README.md) | H1 title |
| [docs/README.md](docs/README.md) | H1 title + opening prose sentence |
| [docs/ui.md](docs/ui.md) | H1 title + opening prose sentence |
| [docs/architecture.md](docs/architecture.md) | Check prose, no H1 change needed |

**Steps**

### Phase 1 — Python source branding (*all parallel*)

**Step 1: Update `__init__.py` module docstring**
Change line 2 from `R5 Save Tool — read/write R5 RocksDB save game data.` to `Windrose Save Tool — read/write Windrose (R5) RocksDB save game data.`

**Step 2: Update `cli.py` module docstring and help text**
- Line 1 module docstring: `CLI entry point.` stays, but the usage header block at the top of the file has no "R5 Save Tool" title to change (examples use `r5-save` command, which is intentionally unchanged).
- Line 123 `cli()` docstring: `"""R5 save-file inspection and editing tool."""` → `"""Windrose Save Tool — save-file inspection and editing tool."""`

**Step 3: Update `ui_api.py` FastAPI title**
Line 85: `app = FastAPI(title="R5 Save UI API", version="0.1.0")` → `app = FastAPI(title="Windrose Save Tool UI API", version="0.1.0")`

**Step 4: Update `ui_window.py` three spots**
- Line 2 module docstring: `Desktop window launcher for R5 Save Tool UI.` → `Desktop window launcher for Windrose Save Tool UI.`
- Line 28: `WINDOW_TITLE = "R5 Save Tool"` → `WINDOW_TITLE = "Windrose Save Tool"`
- Line 91: `print(f"Starting R5 Save Tool API on port {API_PORT}…", flush=True)` → `print(f"Starting Windrose Save Tool API on port {API_PORT}…", flush=True)`

**Step 5: Update `report.py` HTML template**
- Line 73: `<title>R5 Save Data — {title}</title>` → `<title>Windrose Save Tool — {title}</title>`
- Line 131: `  <h1>R5 Save</h1>` → `  <h1>Windrose Save Tool</h1>`

**Step 6: Commit Phase 1**
```bash
git add r5_save_tool/__init__.py r5_save_tool/cli.py r5_save_tool/ui_api.py r5_save_tool/ui_window.py r5_save_tool/report.py
git commit -m "rebrand: update Python source branding to Windrose Save Tool"
```

### Phase 2 — Static UI assets (*parallel*)

**Step 7: Update `app.js` top comment and iframe title**
- Line 2: `   R5 Save Tool UI — app.js` → `   Windrose Save Tool UI — app.js`
- Line 300: `<iframe id="report-frame" title="R5 Save Report"` → `<iframe id="report-frame" title="Windrose Save Report"`

**Step 8: Update `styles.css` top comment**
Line 2: `   R5 Save Tool UI — dark theme matching the HTML report` → `   Windrose Save Tool UI — dark theme matching the HTML report`

**Step 9: Commit Phase 2**
```bash
git add r5_save_tool/ui_static/app.js r5_save_tool/ui_static/styles.css
git commit -m "rebrand: update UI static asset comments/labels to Windrose Save Tool"
```

### Phase 3 — Docs (*parallel*)

**Step 10: Update `README.md` title**
Line 1: `# R5 Save Tool` → `# Windrose Save Tool`
(Line 3 already correctly says "Windrose (R5) save game data" — no change needed.)

**Step 11: Update `docs/README.md` title and prose**
- Line 1: `# R5 Save Tool` → `# Windrose Save Tool`
- Line 5: `This project exists to inspect and safely edit R5 save data stored in local RocksDB databases.` → `This project exists to inspect and safely edit Windrose (R5) save data stored in local RocksDB databases.`

**Step 12: Update `docs/ui.md` title and prose**
- Line 1: `# R5 Save Tool — Desktop UI` → `# Windrose Save Tool — Desktop UI`
- Line 3: `The desktop UI wraps the full CLI feature set in a polished dark-theme interface.` — check for "R5 Save Tool" in line 3 and update; rest stays as-is.

**Step 13: Commit Phase 3**
```bash
git add README.md docs/README.md docs/ui.md
git commit -m "rebrand: update docs titles and prose to Windrose Save Tool"
```

### Phase 4 — Verification

**Step 14: Run contract tests to confirm no regressions**
```bash
pytest tests/test_cli_contracts.py tests/test_ui_api_contracts.py tests/test_data_contracts.py -v
```
Expected: all PASS.

**Step 15: Guardrail grep — confirm no unintended renames**
Confirm these identifiers are unchanged (none should appear in diff of code files):
```bash
grep -rn "r5_save_tool\|R5_SAVE_ROOT\|R5BLPlayer\|R5BLShip\|Local.R5.Saved" r5_save_tool/ --include="*.py" | head -20
```

**Step 16: Spot-check runtime strings**
- Run `r5-save --help` and confirm output says `Windrose Save Tool` in the description line.
- Check `WINDOW_TITLE` in ui_window.py visually (or search for the string): `grep "WINDOW_TITLE" r5_save_tool/ui_window.py`
- Generate a report: `r5-save report` then open `tmp/report/r5_save_report.html` and confirm the `<title>` and `<h1>` read "Windrose Save Tool".

---

**Explicit do-not-touch list**
- `pyproject.toml` — `name`, `r5-save`, `r5-save-ui`, `r5-save-ui-api` script names stay
- All `r5_save_tool/` import paths in tests and source
- `R5_SAVE_ROOT`, `R5_SAVE_UI_HOST`, `R5_SAVE_UI_PORT` env var names
- `R5BLPlayer`, `R5BLShip`, `R5BLBuilding`, `R5BLAccount`, `R5LargeObjects` column family constants
- `AppData/Local/R5/Saved/SaveProfiles` save path
- `r5_save_report.html` output filename