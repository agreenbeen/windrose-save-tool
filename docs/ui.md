# Windrose Save Tool — Desktop UI

The desktop UI wraps the full CLI feature set in a polished dark-theme interface. It runs a local FastAPI server and serves a web frontend that communicates with the save tool's Python logic directly (no CLI subprocesses).

## System Requirements

| Requirement | Notes |
|---|---|
| Python 3.11+ | Already satisfied by the repo venv |
| Windows 10 / 11 | Save data path is Windows-specific |
| WebView2 Runtime | Included with Windows 10 1803+ and all Windows 11 builds — no install needed for most users |

---

## Quick Start — Runs Today, No Extra Setup

### 1. Install the package editable (if not already done)

```powershell
cd C:\Users\<you>\r5-save-tool
.venv\Scripts\python.exe -m pip install -e .
```

### 2. Launch the UI

```powershell
.venv\Scripts\r5-save-ui.exe
```

This is the preferred launch path for repository users. For packaged distribution users, launch:

```powershell
dist\windrose-save-tool.exe
```

(or the full `dist\windrose-save-tool\` folder after an onedir build — see [windows-packaging.md](windows-packaging.md)).

**What happens:**

- The API server starts on `http://127.0.0.1:8765`
- A native desktop window opens via `pywebview` using the **platform default on Windows** (WebView2 / Edge Chromium — no bundled Qt).
- If the native backend is unavailable, the launcher falls back gracefully: it starts the API server and opens `http://127.0.0.1:8765/ui/` in your default browser. The experience is identical.

Press **Ctrl+C** in the terminal to stop the server (browser mode). Closing the native window stops the server automatically (native window mode).

### 3. Use the UI

| Screen | What it does |
|---|---|
| **Config** | Set and validate the save root path and Windrose manifest path. Shows live status for both databases and Windrose mirror divergence. |
| **Report** | Generate and view the full save HTML report inline. |
| **Inventory → Add Items** | Search manifest-backed and built-in item aliases, add to a list with counts, dry-run preview, then apply with auto-backup. |
| **Inventory → Edit Counts** | Load visible ship chest stacks, edit counts in-place, confirm and apply with auto-backup. |
| **Coins** | Calibrate coin offsets from current known values, preview and apply new values. Guinea and ship piastre are highlighted as reliable; player piastre is marked with a lower-confidence warning. |
| **Backups** | Browse backup history for Players and Accounts databases. Restore any backup with a single click and confirmation. |

---

## Run API Only (Browser Mode, No Window)

If you want to use the UI in a browser tab without any window shell:

```powershell
.venv\Scripts\r5-save-ui-api.exe
```

Then open `http://127.0.0.1:8765/ui/` in any browser. The API docs are at `http://127.0.0.1:8765/docs`.

Override the bind address or port via environment variables:

```powershell
$env:R5_SAVE_UI_HOST = "127.0.0.1"
$env:R5_SAVE_UI_PORT = "8766"
.venv\Scripts\r5-save-ui-api.exe
```

---

## Building an EXE

> **Prerequisite:** PyInstaller must be installed. The build runs inside the repo venv.

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller build_exe.spec
```

### Fresh Dist Build (recommended for release testing)

```powershell
# Stop any running built app to avoid file locks in dist/
Get-Process | Where-Object { $_.Path -like "*dist\\windrose-save-tool*" } | Stop-Process -Force

# Remove previous output (onefile default)
Remove-Item -Force .\dist\windrose-save-tool.exe -ErrorAction SilentlyContinue

# Rebuild clean
.venv\Scripts\python.exe -m PyInstaller build_exe.spec --noconfirm
```

The default onefile output is:

```
dist\windrose-save-tool.exe
```

For an unpacked folder build (often better cold start), use `build_exe_onedir.spec` (see [windows-packaging.md](windows-packaging.md)). Distribute the produced EXE plus any bundled folder PyInstaller emits next to it.

### Troubleshooting the EXE Build

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: rocksdict` | rocksdict's compiled extension was not collected. Re-run PyInstaller from the correct venv and confirm `rocksdict` imports cleanly first. |
| `webview` import error at runtime | Add `webview.platforms.edgechromium` / `webview.platforms.winforms` to `hiddenimports` in `build_exe.spec`. |
| Window is blank on launch | WebView2 Runtime may not be installed. Download from https://developer.microsoft.com/en-us/microsoft-edge/webview2/ |

### Note on native backend choice

Packaged builds rely on pywebview's **Windows default** (WebView2) to keep installer size small. `pythonnet` may still resolve as a transitive dependency of pywebview but is **not required** when WebView2 is available.

Optional **Qt backend** (`PySide6` + `qtpy`) is intentionally **not** a project dependency anymore; browser fallback remains if the native window cannot start.

### Measuring artifact size

Use `scripts/measure_exe_size.py` and capture JSON under `tmp/exe-size/` — see [windows-packaging.md](windows-packaging.md).

---

## Configuration

The UI reads these environment variables on startup (same as the CLI):

| Variable | Purpose |
|---|---|
| `R5_SAVE_ROOT` | Override the save profiles root path |
| `WINDROSE_MANIFEST_PATH` | Override the Steam manifest path |
| `STEAM_MANIFEST_PATH` | Alternative manifest path env var |

These can also be set and saved from the **Config** screen inside the UI.

---

## Development Mode

To run the frontend and API separately during development (useful for live-editing the HTML/CSS/JS):

```powershell
# Terminal 1 — start the API with auto-reload
.venv\Scripts\python.exe -c "import uvicorn; uvicorn.run('r5_save_tool.ui_api:app', reload=True, port=8765)"

# Then open in browser
start http://127.0.0.1:8765/ui/
```

The frontend static files at `r5_save_tool/ui_static/` are served live — edit and refresh.

---

## Architecture

```
r5_save_tool/
  ui_static/          Browser-served frontend (HTML + CSS + JS, no build step)
    index.html
    styles.css
    app.js
  ui_api.py           FastAPI server — /api/* routes + /ui/ static mount
  ui_service.py       Package-native service layer (wraps existing modules)
  ui_window.py        Desktop window launcher (pywebview or browser fallback)
  save_context.py     Shared save-root resolution helpers
```

The frontend communicates with the API using plain `fetch()` calls — no build tools, no TypeScript compiler, no npm required. Upgrade to a TypeScript/Vite frontend later by replacing `r5_save_tool/ui_static/` contents and re-mounting.
