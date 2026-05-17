![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/agreenbeen/windrose-save-tool/total)

# Windrose Save Tool

A desktop app for safely editing your Windrose save game. Add items to your ship's hold, adjust coin amounts, and manage backups — all through a graphical interface, no commands required.

## Requirements

- Windows 10 or Windows 11
- Windrose installed on Steam

## Getting Started

1. **Launch the app** — double-click `windrose-save-tool.exe`
2. **Check the Config screen** — the app should find your save automatically. If anything shows a warning, see [First-Time Setup](docs/ui.md#first-time-setup) in the user guide.
3. **Make your changes** — use the sidebar to navigate to Inventory, Coins, or Backups

The app opens a small dark-themed window. If no window appears, look for it in your taskbar.

### Networking (one port for UI + API)

The desktop app runs a single local web server. The **same** `http://127.0.0.1:PORT` is used for both the on-screen UI (`/ui/…`) and the backing API (`/api/…`) — not two different ports.

If something else is already using the default port (**8765**), you can pick a fixed port or let the app choose one:

| Environment variable | Meaning |
|---------------------|---------|
| `R5_SAVE_UI_PORT` | Port number (default `8765`), or `0` / `auto` to use a free port at launch |
| `R5_SAVE_UI_HOST` | Host to open in the browser (default `127.0.0.1`) |

Set these in Windows *Environment Variables* for your user, or only for one session in PowerShell, for example: `set R5_SAVE_UI_PORT=auto` before starting the EXE.

## What You Can Do

| Screen | What it does |
|---|---|
| **Config** | Verify that your save file was found correctly. |
| **Inventory → Add Items** | Search for items by name and add them to your ship's hold with a quantity you choose. |
| **Inventory → Edit Counts** | Change the quantity of an item already sitting in your ship's storage. |
| **Coins** | Adjust your Guinea and Piastre coin amounts. |
| **Backups** | Browse automatic backups and restore a previous save with one click. |

## Safety

The tool **always backs up your save before making any change**. If something goes wrong, open the **Backups** screen and restore the most recent backup.

Every change also goes through a preview step — you'll see exactly what will happen before you confirm anything.

See [Safety & Recovery](docs/SAFETY.md) for more detail on backups and how to recover if something goes wrong.

## Documentation

- [User Guide](docs/ui.md) — step-by-step instructions for every screen
- [Safety & Recovery](docs/SAFETY.md) — backup and restore reference

---

## For Developers

The tool is a Python package with a Click CLI (`r5-save`) and a FastAPI-backed desktop UI (`r5-save-ui`). See [AGENTS.md](AGENTS.md) for workspace conventions, development practices, and build instructions.

Quick start for contributors:

```powershell
uv sync
.venv\Scripts\r5-save-ui.exe        # development UI launch
.venv\Scripts\r5-save.exe --help    # CLI
```

Build the distributable EXE:

```powershell
uv sync --extra build
.venv\Scripts\pyinstaller.exe build_exe.spec --noconfirm
# Output: dist\windrose-save-tool.exe (onefile) or dist\windrose-save-tool\ (onedir build)
```

See [Windows packaging & size measurement](docs/windows-packaging.md) for onedir builds and comparing artifact sizes.

Additional developer docs:

- [Architecture](docs/architecture.md) — system design and module breakdown
- [Asset Mappings](docs/MAPPINGS.md) — confirmed item ID mappings and confidence levels
- [CLI Examples](docs/examples.md) — command-line usage examples
