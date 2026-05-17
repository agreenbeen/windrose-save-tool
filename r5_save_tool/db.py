"""
Database open/close helpers and column-family definitions.

Both databases must be opened with ALL of their column families declared
up front — RocksDB will refuse to open if any CF in the MANIFEST is absent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from rocksdict import Rdict, Options, ColumnFamily, AccessType, DBCompressionType

# ---------------------------------------------------------------------------
# Known column-family layouts
# ---------------------------------------------------------------------------

ACCOUNTS_CFS: list[str] = [
    "default",
    "R5LargeObjects",
    "R5BLAccount",
]

PLAYERS_CFS: list[str] = [
    "default",
    "R5LargeObjects",
    "R5BLPlayer",
    "R5BLShip",
    "R5BLBuilding",
    "R5BLActor_BuildingBlock",
]


@dataclass
class R5Database:
    """Wraps a single RocksDB database and exposes column-family handles."""

    path: Path
    column_families: list[str]
    read_only: bool = True

    _db: Rdict | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    def open(self) -> "R5Database":
        opts = Options(raw_mode=True)  # raw bytes keys/values — no Python overhead
        # Match the game's NoCompression setting so new SST blocks are readable
        opts.set_compression_type(DBCompressionType.none())
        opts.set_bottommost_compression_type(DBCompressionType.none())
        # rocksdict requires column_families as {name: Options}
        def _make_cf_opts() -> Options:
            o = Options(raw_mode=True)
            o.set_compression_type(DBCompressionType.none())
            o.set_bottommost_compression_type(DBCompressionType.none())
            return o
        cf_opts = {cf: _make_cf_opts() for cf in self.column_families}
        access = AccessType.read_only() if self.read_only else AccessType.read_write()
        self._db = Rdict(
            str(self.path),
            options=opts,
            column_families=cf_opts,
            access_type=access,
        )
        return self

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "R5Database":
        return self.open()

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    def cf(self, name: str) -> Rdict:
        """Return a column-family handle (still backed by the same DB connection)."""
        if self._db is None:
            raise RuntimeError("Database is not open. Use as a context manager or call open().")
        return self._db.get_column_family(name)

    def iter_cf(self, cf_name: str) -> Iterator[tuple[bytes, bytes]]:
        """Yield all (key, value) pairs from a column family."""
        handle = self.cf(cf_name)
        it = handle.iter()
        it.seek_to_first()
        while it.valid():
            yield it.key(), it.value()
            it.next()

    def get(self, cf_name: str, key: bytes) -> bytes | None:
        """Read a single value by key from the given column family."""
        return self.cf(cf_name).get(key)

    def put(self, cf_name: str, key: bytes, value: bytes) -> None:
        """Write a key/value pair into the given column family."""
        if self.read_only:
            raise RuntimeError("Database is opened read-only. Re-open with read_only=False.")
        self.cf(cf_name)[key] = value

    def delete(self, cf_name: str, key: bytes) -> None:
        """Delete a key from the given column family."""
        if self.read_only:
            raise RuntimeError("Database is opened read-only.")
        del self.cf(cf_name)[key]


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------

def _locate_single_subdir(parent: Path) -> Path:
    """Return the active RocksDB subdirectory inside parent, ignoring backup folders."""
    dirs = [d for d in parent.iterdir() if d.is_dir() and not d.name.startswith("_")]
    if len(dirs) == 1:
        return dirs[0]

    # Prefer directories that look like RocksDB roots (contain CURRENT/MANIFEST files).
    rocks_like = [
        d
        for d in dirs
        if (d / "CURRENT").exists() and any(p.name.startswith("MANIFEST") for p in d.iterdir())
    ]
    if len(rocks_like) == 1:
        return rocks_like[0]

    raise FileNotFoundError(
        f"Expected exactly one active subdirectory in {parent}, found: {[d.name for d in dirs]}"
    )


def open_accounts_db(save_root: Path, read_only: bool = True) -> R5Database:
    """Open the Accounts database."""
    db_path = _locate_single_subdir(save_root / "Accounts")
    return R5Database(db_path, ACCOUNTS_CFS, read_only=read_only)


def open_players_db(save_root: Path, read_only: bool = True, captain_uuid: str | None = None) -> R5Database:
    """Open the Players database, auto-selecting the default captain when multiple exist."""
    from .save_context import resolve_player_dir  # lazy import avoids circular dependency
    db_path = resolve_player_dir(save_root, captain_uuid)
    return R5Database(db_path, PLAYERS_CFS, read_only=read_only)
