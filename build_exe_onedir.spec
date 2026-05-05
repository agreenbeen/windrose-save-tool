# Onedir PyInstaller layout — same payload as onefile but without self-extraction to %TEMP%.
#
# Keep ``hidden_imports`` in sync with ``build_exe.spec`` (same Analysis inputs).
#
# Build:
#   pyinstaller build_exe_onedir.spec --noconfirm
#
# Output: dist/windrose-save-tool/ (folder — distribute the whole tree)

import importlib.util
from pathlib import Path

block_cipher = None


def _load_dotnet_bridge_runtime_datas() -> list[tuple[str, str]]:
    helper = Path(SPECPATH) / "scripts" / "pyinstaller_dotnet_datas.py"
    spec = importlib.util.spec_from_file_location("_pyi_dotnet_datas", helper)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load PyInstaller helper: {helper}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.dotnet_bridge_runtime_datas()


datas = [
    (str(Path('r5_save_tool/ui_static').resolve()), 'r5_save_tool/ui_static'),
]
datas += _load_dotnet_bridge_runtime_datas()

hidden_imports = [
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
    'fastapi',
    'fastapi.staticfiles',
    'starlette',
    'starlette.staticfiles',
    'starlette.responses',
    'starlette.routing',
    'pydantic',
    'webview',
    'webview.platforms',
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',
    'anyio',
    'anyio._backends._asyncio',
    'h11',
]

a = Analysis(
    ['r5_save_tool/ui_window.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'httptools',
        'uvloop',
        'watchfiles',
        'pydantic.mypy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='windrose-save-tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='windrose-save-tool',
)
