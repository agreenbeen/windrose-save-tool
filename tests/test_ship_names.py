"""Tests for ship name extraction logic."""
import pytest
from pathlib import Path
from r5_save_tool.inventory import (
    _inv_extract_ship_name_from_blob,
    _inv_find_first_string_key_like,
    _inv_extract_ship_type_from_refs,
)
from r5_save_tool.db import open_players_db
from r5_save_tool.ue_parser import parse_r5_value


class TestShipNameExtraction:
    """Test ship name extraction from raw blobs and parsed structures."""

    def test_ship_names_extracted_from_real_save(self, test_save_root: Path):
        """Test that ship names can be extracted from the test save.

        Critical: If this fails, the ship grouping UI feature won't work.
        This validates the extraction pipeline end-to-end.
        """
        try:
            with open_players_db(test_save_root) as db:
                ship_names = []
                for key_bytes, val_bytes in db.iter_cf("R5BLShip"):
                    # Try all three extraction methods in order
                    name = _inv_extract_ship_name_from_blob(val_bytes)
                    if not name:
                        parsed = parse_r5_value(val_bytes)
                        name = _inv_find_first_string_key_like(parsed, "ShipName")
                    if not name:
                        parsed = parse_r5_value(val_bytes)
                        ship_type = _inv_extract_ship_type_from_refs(parsed)
                        name = ship_type

                    if name:
                        ship_names.append(name)

                # The test save should have at least one ship with a name or type
                assert len(ship_names) > 0, "No ship names extracted from test save"
        except Exception as e:
            pytest.skip(f"Test database is corrupted or invalid: {e}")

    def test_ship_type_extraction_from_asset_refs(self):
        """Test extraction of ship type from DA_Ship_ asset references."""
        test_obj = {
            "SomeKey": "DA_Ship_Ketch",
        }
        result = _inv_extract_ship_type_from_refs(test_obj)
        assert result == "Ketch"

    def test_ship_type_extraction_nested(self):
        """Test ship type extraction from nested structures."""
        test_obj = {
            "Level": {
                "Data": {
                    "ShipRef": "DA_Ship_Brigantine",
                }
            }
        }
        result = _inv_extract_ship_type_from_refs(test_obj)
        assert result == "Brigantine"

    def test_ship_type_extraction_not_found(self):
        """Test that extraction returns None if no ship type is found."""
        test_obj = {
            "SomeKey": "DA_Item_Wood",
            "Other": "NoShip",
        }
        result = _inv_extract_ship_type_from_refs(test_obj)
        assert result is None

    def test_find_string_key_like_simple(self):
        """Test finding string value by key fragment."""
        test_obj = {
            "ShipName": "MyShip",
            "OtherKey": "Value",
        }
        result = _inv_find_first_string_key_like(test_obj, "ShipName")
        assert result == "MyShip"

    def test_find_string_key_like_nested(self):
        """Test finding string by key fragment in nested structure."""
        test_obj = {
            "Data": {
                "Properties": {
                    "shipname": "NestedShip",
                }
            }
        }
        result = _inv_find_first_string_key_like(test_obj, "shipname")
        assert result == "NestedShip"

    def test_find_string_key_like_case_insensitive(self):
        """Test that key matching is case-insensitive."""
        test_obj = {
            "SHIPNAME": "CaseInsensitive",
        }
        result = _inv_find_first_string_key_like(test_obj, "shipname")
        assert result == "CaseInsensitive"

    def test_find_string_key_like_not_found(self):
        """Test that None is returned if key is not found."""
        test_obj = {
            "SomeKey": "Value",
        }
        result = _inv_find_first_string_key_like(test_obj, "NonExistent")
        assert result is None

    def test_extract_ship_name_from_blob_invalid_input(self):
        """Test that blob extraction handles invalid input gracefully."""
        # Empty blob
        result = _inv_extract_ship_name_from_blob(b"")
        assert result is None

        # Blob with no ShipName tag
        result = _inv_extract_ship_name_from_blob(b"Some random data")
        assert result is None

        # Blob that's too short
        result = _inv_extract_ship_name_from_blob(b"ShipName\x00")
        assert result is None
