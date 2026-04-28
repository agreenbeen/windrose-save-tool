"""
Backup utility — always take a snapshot before any write operation.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from r5_save_tool.paths import get_writable_base


_TOOL_BACKUP_ROOT = get_writable_base() / "_backups"
_TRANSIENT_BACKUP_SKIP = {"LOCK"}
_BACKUP_MANIFEST_NAME = "_backup_manifest.json"


def _iter_backup_files(root: Path) -> list[Path]:
    return sorted(
        p.relative_to(root)
        for p in root.rglob("*")
        if p.is_file() and p.name != _BACKUP_MANIFEST_NAME
    )


def _read_current_marker(db_path: Path) -> str | None:
    current_path = db_path / "CURRENT"
    if not current_path.exists():
        return None
    return current_path.read_text(encoding="utf-8", errors="ignore").strip()


def _build_backup_manifest(db_path: Path, backup_path: Path) -> dict[str, object]:
    current_marker = _read_current_marker(db_path)
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_db_path": str(db_path),
        "backup_path": str(backup_path),
        "current_marker": current_marker,
        "file_count": len(_iter_backup_files(backup_path)),
        "files": [str(path).replace("\\", "/") for path in _iter_backup_files(backup_path)],
    }


def _write_backup_manifest(backup_path: Path, manifest: dict[str, object]) -> Path:
    manifest_path = backup_path / _BACKUP_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def backup_details(path: Path) -> dict[str, object]:
    manifest_path = path / _BACKUP_MANIFEST_NAME
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    current_marker = _read_current_marker(path)
    files = _iter_backup_files(path)
    return {
        "created_at": None,
        "source_db_path": None,
        "backup_path": str(path),
        "current_marker": current_marker,
        "file_count": len(files),
        "files": [str(file).replace("\\", "/") for file in files],
    }


def restore_backup(backup_path: Path, destination_db_path: Path) -> dict[str, object]:
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    destination_db_path.mkdir(parents=True, exist_ok=True)
    for child in destination_db_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for child in backup_path.iterdir():
        if child.name == _BACKUP_MANIFEST_NAME:
            continue
        target = destination_db_path / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)

    backup_info = backup_details(backup_path)
    destination_files = _iter_backup_files(destination_db_path)
    destination_current = _read_current_marker(destination_db_path)
    return {
        "backup_path": str(backup_path),
        "destination_db_path": str(destination_db_path),
        "restored_file_count": len(destination_files),
        "expected_file_count": int(backup_info["file_count"]),
        "current_marker": destination_current,
        "matches_backup": len(destination_files) == int(backup_info["file_count"])
        and destination_current == backup_info.get("current_marker"),
    }


def backup_db(db_path: Path, backup_root: Path | None = None) -> Path:
    """
    Copy the entire RocksDB directory to a timestamped backup folder.

    Args:
        db_path:     Path to the live database directory to back up.
        backup_root: Where to store backups. Defaults to a sibling '_backups' folder.

    Returns:
        Path to the backup directory that was created.
    """
    if backup_root is None:
        backup_root = _TOOL_BACKUP_ROOT / db_path.parent.name

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_root / f"{db_path.name}_{timestamp}"

    print(f"Backing up {db_path.name} -> {dest} ...", end=" ", flush=True)
    shutil.copytree(
        str(db_path),
        str(dest),
        ignore=lambda _dir, names: [name for name in names if name in _TRANSIENT_BACKUP_SKIP],
    )
    _write_backup_manifest(dest, _build_backup_manifest(db_path, dest))
    print("done.")
    return dest


def list_backups(db_path: Path, backup_root: Path | None = None) -> list[Path]:
    """Return all existing backups for a given database, sorted newest-first."""
    if backup_root is None:
        backup_root = _TOOL_BACKUP_ROOT / db_path.parent.name
    if not backup_root.exists():
        return []
    prefix = db_path.name + "_"
    return sorted(
        (p for p in backup_root.iterdir() if p.is_dir() and p.name.startswith(prefix)),
        reverse=True,
    )
