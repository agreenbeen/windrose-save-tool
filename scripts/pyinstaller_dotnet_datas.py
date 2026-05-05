"""
PyInstaller ``datas`` tuples for pythonnet + clr_loader (frozen pywebview on Windows).

Loaded from ``build_exe.spec`` / ``build_exe_onedir.spec`` via importlib; keep this
file free of repo package imports so PyInstaller analysis stays predictable.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


def dotnet_bridge_runtime_datas() -> list[tuple[str, str]]:
    """Smallest file set needed for pythonnet in a frozen Windows UI build."""
    if sys.platform == "win32":
        import clr_loader
        import pythonnet

        out: list[tuple[str, str]] = []
        rt = Path(pythonnet.__file__).resolve().parent / "runtime"
        for name in ("Python.Runtime.dll", "Python.Runtime.deps.json"):
            p = rt / name
            if p.is_file():
                out.append((str(p), "pythonnet/runtime"))
        ff = Path(clr_loader.__file__).resolve().parent / "ffi" / "dlls"
        arch = platform.machine().lower()
        sub = "amd64" if arch in ("amd64", "x86_64") else "x86"
        dll = ff / sub / "ClrLoader.dll"
        if dll.is_file():
            out.append((str(dll), f"clr_loader/ffi/dlls/{sub}"))
        return out
    rows = list(collect_data_files("pythonnet"))
    rows.extend(
        (s, d)
        for s, d in collect_data_files("clr_loader")
        if not str(s).lower().endswith(".pdb")
    )
    return rows
