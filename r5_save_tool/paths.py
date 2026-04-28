"""
Runtime path resolution — handles both source and PyInstaller frozen builds.
"""
from __future__ import annotations

import sys
from pathlib import Path


def get_writable_base() -> Path:
    """Return the directory to use for tool-managed writable data (e.g. backups).

    - Frozen (PyInstaller onefile or onedir): directory containing the EXE.
    - Development / installed package: the r5_save_tool package directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
