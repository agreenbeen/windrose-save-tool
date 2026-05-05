from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from .db import _locate_single_subdir


DEFAULT_SAVE_PROFILES_ROOT = Path.home() / "AppData" / "Local" / "R5" / "Saved" / "SaveProfiles"
WINDROSE_PLAYERS_ROOT = Path.home() / "AppData" / "Local" / "Windrose" / "Saved" / "Players"

_ROCKSDB_DIR_NAMES = ("RocksDB_v2", "RocksDB")


class DirectoryComparison(TypedDict):
    a_only: list[str]
    b_only: list[str]
    a_count: int
    b_count: int


def find_save_root(save_root: str | Path | None) -> Path:
    """Locate the active versioned RocksDB root, preferring RocksDB_v2 over RocksDB."""
    base = Path(save_root) if save_root else DEFAULT_SAVE_PROFILES_ROOT
    if not base.exists():
        raise FileNotFoundError(f"Save root not found: {base}")

    for dir_name in _ROCKSDB_DIR_NAMES:
        versioned = base / dir_name / "0.10.0"
        if versioned.exists():
            return versioned

    for child in base.iterdir():
        if child.is_dir() and child.name.isdigit():
            for dir_name in _ROCKSDB_DIR_NAMES:
                candidate = child / dir_name / "0.10.0"
                if candidate.exists():
                    return candidate

    raise FileNotFoundError(
        f"Could not locate RocksDB_v2/0.10.0 or RocksDB/0.10.0 under {base}. "
        "Use an explicit save-root path."
    )


def resolve_db_dir(save_root: Path, db: Literal["players", "accounts"]) -> Path:
    db_dir_parent = save_root / ("Players" if db == "players" else "Accounts")
    return _locate_single_subdir(db_dir_parent)


def read_current_marker(db_path: Path) -> str | None:
    current_path = db_path / "CURRENT"
    if not current_path.exists():
        return None
    return current_path.read_text(encoding="utf-8", errors="ignore").strip()


def file_count(root: Path) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file()) if root.exists() else 0


def compare_dirs(a: Path, b: Path) -> DirectoryComparison:
    a_files = {path.relative_to(a).as_posix() for path in a.rglob("*") if path.is_file()}
    b_files = {path.relative_to(b).as_posix() for path in b.rglob("*") if path.is_file()}
    return {
        "a_only": sorted(a_files - b_files),
        "b_only": sorted(b_files - a_files),
        "a_count": len(a_files),
        "b_count": len(b_files),
    }


def find_windrose_player_dir(save_root: Path) -> Path | None:
    try:
        player_dir = resolve_db_dir(save_root, "players")
    except FileNotFoundError:
        return None
    candidate = WINDROSE_PLAYERS_ROOT / player_dir.name
    return candidate if candidate.exists() else None


def doctor_status(save_root: Path) -> dict[str, object]:
    player_dir = resolve_db_dir(save_root, "players")
    accounts_dir = resolve_db_dir(save_root, "accounts")
    windrose_player_dir = find_windrose_player_dir(save_root)

    result: dict[str, object] = {
        "resolved_save_root": str(save_root),
        "players": {
            "path": str(player_dir),
            "current_marker": read_current_marker(player_dir),
            "file_count": file_count(player_dir),
        },
        "accounts": {
            "path": str(accounts_dir),
            "current_marker": read_current_marker(accounts_dir),
            "file_count": file_count(accounts_dir),
        },
        "windrose": None,
        "divergence": None,
    }

    if windrose_player_dir is None:
        result["windrose"] = {
            "path": None,
            "current_marker": None,
            "file_count": 0,
            "found": False,
        }
        return result

    divergence = compare_dirs(player_dir, windrose_player_dir)
    result["windrose"] = {
        "path": str(windrose_player_dir),
        "current_marker": read_current_marker(windrose_player_dir),
        "file_count": file_count(windrose_player_dir),
        "found": True,
    }
    result["divergence"] = divergence
    return result