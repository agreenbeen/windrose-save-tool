# build_exe.spec
# PyInstaller spec for Windrose Save Tool desktop app.
#
# Build with:
#   pyinstaller build_exe.spec
#
# Output: dist/r5-save-tool.exe  (single-file onefile build)
#
# Note: on first launch Windows extracts ~150-250 MB to %TEMP%\_MEIxxxxxx\.
# Subsequent launches reuse the same extraction folder until it is cleaned up.
# Backups are written next to r5-save-tool.exe, not inside the temp folder.
#
# Notes:
# - rocksdict ships compiled extensions; PyInstaller auto-detects most DLLs.
# - pywebview uses the system WebView2 Runtime (built-in on Windows 10 1803+
#   and Windows 11). No bundling of the WebView2 runtime is needed.
# - uvicorn / starlette have dynamic import patterns that require hidden imports.

from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Collect files
# ---------------------------------------------------------------------------
datas = [
    # UI static frontend files
    (str(Path('r5_save_tool/ui_static').resolve()), 'r5_save_tool/ui_static'),
]

hidden_imports = [
    # r5_save_tool modules
    'r5_save_tool',
    'r5_save_tool.paths',
    'r5_save_tool.ui_api',
    'r5_save_tool.ui_service',
    'r5_save_tool.ui_window',
    'r5_save_tool.save_context',
    'r5_save_tool.backup',
    'r5_save_tool.coin',
    'r5_save_tool.db',
    'r5_save_tool.dump',
    'r5_save_tool.inventory',
    'r5_save_tool.inventory_targets',
    'r5_save_tool.inventory_write',
    'r5_save_tool.manifest',
    'r5_save_tool.report',
    'r5_save_tool.schema',
    'r5_save_tool.ue_parser',
    # uvicorn dynamic imports
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    # fastapi / starlette
    'fastapi',
    'fastapi.staticfiles',
    'starlette',
    'starlette.staticfiles',
    'starlette.responses',
    'starlette.routing',
    # pydantic
    'pydantic',
    'pydantic.v1',
    # pywebview
    'webview',
    'webview.platforms',
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',
    # anyio async backend
    'anyio',
    'anyio._backends._asyncio',
    'anyio._backends._trio',
    # h11 HTTP parser
    'h11',
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['r5_save_tool/ui_window.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='r5-save-tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # Hide the console window
    icon=None,       # Add a .ico path here if you have an icon
    onefile=True,
)
