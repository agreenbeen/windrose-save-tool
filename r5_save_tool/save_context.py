from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

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


def list_player_dirs(save_root: Path) -> list[Path]:
    """Return all non-underscore Player UUID directories, sorted by name."""
    players_parent = save_root / "Players"
    if not players_parent.exists():
        return []
    return sorted(
        d for d in players_parent.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


def get_default_player_id(save_root: Path) -> str | None:
    """Read DefaultPlayerId from the shared Account blob."""
    from .db import R5Database, ACCOUNTS_CFS  # lazy — avoids circular import at module level
    accounts_parent = save_root / "Accounts"
    try:
        accounts_dir = _locate_single_subdir(accounts_parent)
    except FileNotFoundError:
        return None
    try:
        with R5Database(accounts_dir, ACCOUNTS_CFS, read_only=True) as db:
            for _, val in db.iter_cf("R5BLAccount"):
                field_tag = b"DefaultPlayerId\x00"
                idx = val.find(field_tag)
                if idx >= 0:
                    str_start = idx + len(field_tag) + 4  # skip 4-byte length prefix
                    null_pos = val.find(b"\x00", str_start)
                    if null_pos > str_start:
                        candidate = val[str_start:null_pos]
                        if len(candidate) == 32:
                            return candidate.decode("ascii", errors="ignore")
    except Exception:
        pass
    return None


def extract_player_name(player_db_dir: Path) -> str | None:
    """Extract PlayerName from R5BLPlayer blob for a given player directory."""
    from .db import R5Database, PLAYERS_CFS  # lazy import
    try:
        with R5Database(player_db_dir, PLAYERS_CFS, read_only=True) as db:
            val = db.get("R5BLPlayer", player_db_dir.name.encode())
            if val is None:
                return None
            field_tag = b"PlayerName\x00"
            idx = val.find(field_tag)
            if idx < 0:
                return None
            str_start = idx + len(field_tag) + 4  # skip 4-byte length prefix
            null_pos = val.find(b"\x00", str_start)
            if null_pos > str_start:
                return val[str_start:null_pos].decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def list_captains(save_root: Path) -> list[dict[str, Any]]:
    """Return info for all captains: uuid, name, is_default, db_path."""
    default_id = get_default_player_id(save_root)
    captains = []
    for d in list_player_dirs(save_root):
        name = extract_player_name(d)
        captains.append({
            "uuid": d.name,
            "name": name or d.name,
            "is_default": d.name == default_id,
            "db_path": str(d),
        })
    return captains


def resolve_player_dir(save_root: Path, captain_uuid: str | None = None) -> Path:
    """Resolve the Players DB dir, auto-selecting the default captain when multiple exist."""
    dirs = list_player_dirs(save_root)
    if not dirs:
        raise FileNotFoundError(f"No player directories found under {save_root / 'Players'}")

    if captain_uuid is not None:
        matches = [d for d in dirs if d.name == captain_uuid]
        if not matches:
            raise FileNotFoundError(
                f"Captain UUID {captain_uuid!r} not found. "
                f"Available: {[d.name for d in dirs]}"
            )
        return matches[0]

    if len(dirs) == 1:
        return dirs[0]

    # Multiple captains — auto-select DefaultPlayerId from Account
    default_id = get_default_player_id(save_root)
    if default_id:
        matches = [d for d in dirs if d.name == default_id]
        if matches:
            return matches[0]

    raise FileNotFoundError(
        f"Multiple captains found but could not determine default. "
        f"Use --captain to specify a UUID. Found: {[d.name for d in dirs]}"
    )


def resolve_db_dir(save_root: Path, db: Literal["players", "accounts"], captain_uuid: str | None = None) -> Path:
    if db == "players":
        return resolve_player_dir(save_root, captain_uuid)
    db_dir_parent = save_root / "Accounts"
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