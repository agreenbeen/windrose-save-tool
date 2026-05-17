# Windows Packaging and EXE Size

This document captures how we measure bundle size, the default packaging choice, optional layouts, and time-boxed alternate toolchains.

## Size measurement harness

After a PyInstaller build, record artifact sizes into `tmp/exe-size/` (gitignored):

```powershell
cd $env:WINDROSE_REPO_ROOT
mkdir tmp\exe-size -Force | Out-Null
.venv\Scripts\python.exe scripts\measure_exe_size.py `
  --out tmp\exe-size\latest-measure.json
```

(`--dist-glob` defaults to `dist/windrose-save-tool.exe`.)

If the app is already responding (warm run), optionally capture latency to `/api/health`:

```powershell
.venv\Scripts\python.exe scripts\measure_exe_size.py `
  --path dist\windrose-save-tool.exe `
  --health-url http://127.0.0.1:8765/api/health `
  --out tmp\exe-size\latest-measure-with-health.json
```

Copy `tmp/exe-size/latest-measure.json` to `baseline.json` when you intentionally freeze a baseline for regressions.

**One-file note:** Disk footprint of `%TEMP%\_ME*` extraction matches total payload (~same order as onefile exe size minus compression). Prefer **onedir** if antivirus or disk churn from extraction is problematic.

---

## Recommended deliverable (current strategy)

- **Packager:** PyInstaller from [build_exe.spec](../build_exe.spec).
- **Window shell:** pywebview uses the platform default on Windows (Edge Chromium / WebView2 via `webview.platforms.edgechromium`). **PySide6 / Qt are not bundled** — this is the largest size win vs the older Qt-forced path.
- **Prerequisite:** WebView2 Runtime (present on supported Windows 10/11 per [docs/ui.md](ui.md)).
- **Double-click vs terminal:** The onefile build uses `console=False` (GUI subsystem). End users never get a console window. The launcher assigns safe `stdout`/`stderr` when they are `None` (discarded to `nul` / in-memory), so Explorer launches do not crash on the first `print` before the API starts—without `AllocConsole()` or flipping the PE to a console app.

See [Strategy decision](#strategy-decision) below for rationale and when to revisit.

---

## Further PyInstaller tuning

- **`strip=True`** is set in both spec files. On Windows this is a no-op (no `strip` binary on `PATH`) so the warnings in the build log are harmless and expected. It takes effect on Linux/macOS if the tool is ever built there.
- **Excluded modules:** unused pywebview backends (`mshtml`, `cef`, `gtk`, `cocoa`, `qt`), `pygments`, `setuptools`/`pkg_resources`, `pytest`, `coverage` — removes ~1.4 MiB. **`bottle` must stay bundled** — pywebview's `http` module imports it at the top level for the `BottleServer` default.
- Prefer measured A/B over guessing: run `scripts/measure_exe_size.py` after each change.

## Onedir build (faster cold start, no single huge exe)

Use [build_exe_onedir.spec](../build_exe_onedir.spec):

```powershell
.venv\Scripts\python.exe -m PyInstaller build_exe_onedir.spec --noconfirm
```

Distribute the entire `dist\windrose-save-tool\` folder. Total bytes on disk is similar to onefile unpacked payload but avoids self-extraction on every cold start.

---

## Alternate packagers (time-box trials)

Only adopt if beats optimized PyInstaller on **size**, **cold start**, and **rocksdict** stability.

| Tool      | Spike command sketch | Record |
|-----------|---------------------|--------|
| **Nuitka** | Install Nuitka + MSVC toolchain; `--standalone`/`--onefile` on `r5_save_tool/ui_window.py` | final artifact MB, `--show-progress` timings, stderr for missing DLLs |
| **PyOxidizer** | `pyoxidizer init` minimal config targeting same entry | binary MB, startup, libc/runtime quirks |
| **cx_Freeze** | Control / comparison only | same metrics |

Write results under `tmp/exe-size/nuitka-spike.json` (etc.) using `scripts/measure_exe_size.py` where applicable.

---

## Strategy decision

**Chosen path:** PyInstaller + WebView2-first pywebview + trimmed `hidden_imports` (no Qt stack).

**Revisit** if:

- measured onefile or onedir remains above an agreed release budget, or
- an alternate packager wins on size and startup without weakening backup-first write safety.

**Not default:** shipping a separate native WebView2 host (Rust/.NET) plus Python worker — reserved for a future epic if PyInstaller cannot meet goals.

---

## Releasing

Tag a commit with a `v*` tag and push it — GitHub Actions (`.github/workflows/release.yml`) will build the EXE on `windows-latest`, measure the artifact, and create a GitHub Release with the EXE attached and the matching section from `RELEASE_NOTES.md` as the release body.

```powershell
git tag v1.2
git push origin v1.2
```

Pre-release versions (tags containing a hyphen, e.g. `v1.3-beta.1`) are automatically marked as pre-releases.

## Assets

- `assets/windrose-save-tool-icon.png` — master app icon (1024×1024).
- `assets/icon.ico` — multi-size icon for PyInstaller and the UI. Regenerate with `python scripts/create_icon.py` (requires `uv sync --extra build`).
- `assets/windows_version_info.txt` — Windows VERSIONINFO (right-click → Properties). Update `filevers`/`prodvers`/`FileVersion`/`ProductVersion` when bumping the release version.

## Related

- [docs/ui.md](ui.md) — desktop UI behavior and build commands
- [AGENTS.md](../AGENTS.md) — safety and validation expectations
