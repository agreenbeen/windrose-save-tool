"""Pytest configuration and shared fixtures."""
import struct
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Synthetic fixture data builders
# ---------------------------------------------------------------------------

def _make_opts():
    from rocksdict import Options, DBCompressionType
    o = Options(raw_mode=True)
    o.set_compression_type(DBCompressionType.none())
    o.set_bottommost_compression_type(DBCompressionType.none())
    return o


def _make_type3_object(name: str, payload: bytes) -> bytes:
    """Encode a type-0x03 object as scanned by extract_type3_objects."""
    return b"\x03" + name.encode("ascii") + b"\x00" + struct.pack("<I", len(payload)) + payload


def _make_item_payload(item_path: str, slot_path: str, count: int) -> bytes:
    """Build a payload whose text scan yields item+slot asset paths and a parseable count."""
    text = (item_path + slot_path).encode("ascii") + b"\x00"
    count_field = b"Count\x00" + struct.pack("<i", count)
    stack = b"ItemsStack\x00" + struct.pack("<I", len(count_field)) + count_field
    return text + stack


def _player_blob() -> bytes:
    """One Wood item in the quick (DA_BL_Slot_Default) player slot."""
    payload = _make_item_payload(
        "/R5BusinessRules/InventoryItems/Resources/Wood.Wood",
        "/R5BusinessRules/Inventory/SlotsParams/DA_BL_Slot_Default.DA_BL_Slot_Default",
        50,
    )
    return _make_type3_object("1", payload)


def _ship_blob() -> bytes:
    """Named ship with one Rope item in the chest (DA_BL_Slot_Chest) slot."""
    ship_name = b"Windrose I\x00"
    name_field = b"ShipName\x00" + struct.pack("<I", len(ship_name)) + ship_name
    payload = _make_item_payload(
        "/R5BusinessRules/InventoryItems/Resources/Rope.Rope",
        "/R5BusinessRules/Inventory/SlotsParams/DA_BL_Slot_Chest.DA_BL_Slot_Chest",
        25,
    )
    return name_field + _make_type3_object("1", payload)


def _create_db(path: Path, extra_cfs: list[str], data: dict[str, dict[bytes, bytes]]) -> None:
    from rocksdict import Rdict, AccessType
    path.mkdir(parents=True, exist_ok=True)
    db = Rdict(str(path), options=_make_opts(), access_type=AccessType.read_write())
    for cf in extra_cfs:
        db.create_column_family(cf, _make_opts())
    for cf_name, records in data.items():
        cf_handle = db.get_column_family(cf_name)
        for k, v in records.items():
            cf_handle[k] = v
    db.close()


def _create_players_db(path: Path) -> None:
    _create_db(
        path,
        ["R5LargeObjects", "R5BLPlayer", "R5BLShip", "R5BLBuilding", "R5BLActor_BuildingBlock"],
        {
            "R5BLPlayer": {b"player-key-0001": _player_blob()},
            "R5BLShip": {b"ship-key-0001": _ship_blob()},
        },
    )


def _create_accounts_db(path: Path) -> None:
    _create_db(path, ["R5LargeObjects", "R5BLAccount"], {})


def create_test_fixtures(root: Path) -> None:
    """Create all synthetic RocksDB fixture databases under *root*."""
    _create_players_db(root / "Players" / "ActiveProfile")
    _create_accounts_db(root / "Accounts" / "ActiveProfile")
    _create_players_db(root / "RocksDB" / "0.10.0" / "Players" / "ActiveProfile")
    _create_accounts_db(root / "RocksDB" / "0.10.0" / "Accounts" / "ActiveProfile")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _ensure_test_fixtures():
    """Create synthetic fixture databases once per session if they are missing."""
    root = Path(__file__).parent.parent / "test_saves"
    sentinel = root / "Players" / "ActiveProfile" / "CURRENT"
    if not sentinel.exists():
        create_test_fixtures(root)


@pytest.fixture
def test_save_root() -> Path:
    """Return the path to the test save directory."""
    return Path(__file__).parent.parent / "test_saves"


@pytest.fixture
def test_save_exists(test_save_root: Path) -> bool:
    """Verify that test save data exists and is accessible."""
    return (test_save_root / "Players" / "ActiveProfile").exists()


@pytest.fixture
def configured_service(test_save_root: Path):
    """Return the service singleton configured with the test save root.

    The test save root must have the RocksDB/0.10.0/ structure expected by
    find_save_root(). Restores original save_root after the test.
    """
    from r5_save_tool.ui_service import service

    # find_save_root expects a path containing RocksDB/0.10.0/
    # test_saves/RocksDB/0.10.0/ is created as a junction pointing to test_saves/Players
    service_root = test_save_root  # find_save_root will locate RocksDB/0.10.0 under here
    original = service._config.save_root
    service._config.save_root = str(service_root)
    yield service
    service._config.save_root = original
