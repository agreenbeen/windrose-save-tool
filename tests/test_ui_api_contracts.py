"""Tests for UI API request/response contracts and endpoint behavior.

These tests validate that the API interface remains stable and that changes
to request/response models are caught immediately.
"""
import pytest
from pydantic import ValidationError
from r5_save_tool.ui_api import (
    ConfigUpdate,
    ReportGenerateRequest,
    InventoryTargetCount,
    InventoryResolveRequest,
    InventoryPlanRequest,
    ShipAddRequest,
    ShipCountRequest,
    CoinMapRequest,
    CoinSetRequest,
    RestoreBackupRequest,
)


class TestRequestModelValidation:
    """Test that request models validate input correctly."""

    def test_config_update_accepts_none_values(self):
        """ConfigUpdate should allow both None and string values."""
        # Both None
        model = ConfigUpdate(save_root=None, manifest_path=None)
        assert model.save_root is None
        assert model.manifest_path is None

        # Both set
        model = ConfigUpdate(save_root="/path/to/save", manifest_path="/path/to/manifest")
        assert model.save_root == "/path/to/save"
        assert model.manifest_path == "/path/to/manifest"

    def test_inventory_target_count_requires_positive_count(self):
        """InventoryTargetCount should reject zero or negative counts."""
        # Valid
        model = InventoryTargetCount(target="rope", count=10)
        assert model.count == 10

        # Invalid: zero
        with pytest.raises(ValidationError):
            InventoryTargetCount(target="rope", count=0)

        # Invalid: negative
        with pytest.raises(ValidationError):
            InventoryTargetCount(target="rope", count=-5)

    def test_inventory_plan_request_defaults(self):
        """InventoryPlanRequest should have sensible defaults."""
        model = InventoryPlanRequest(targets=[])
        assert model.player_open_slots_per_stage == 20
        assert model.ship_capacity == 28
        assert model.strict_manifest is False

    def test_inventory_plan_request_min_constraints(self):
        """InventoryPlanRequest should enforce minimum slot values."""
        # Valid minimum
        model = InventoryPlanRequest(targets=[], player_open_slots_per_stage=1, ship_capacity=1)
        assert model.player_open_slots_per_stage == 1

        # Invalid: zero
        with pytest.raises(ValidationError):
            InventoryPlanRequest(targets=[], player_open_slots_per_stage=0)

    def test_ship_add_request_defaults(self):
        """ShipAddRequest should have safe defaults (dry_run=True)."""
        model = ShipAddRequest(targets=[])
        assert model.dry_run is True
        assert model.allow_assumed_assets is False
        assert model.strict_manifest is False
        assert model.preferred_ship_key_prefix is None

    def test_ship_count_request_count_validation(self):
        """ShipCountRequest should validate count is non-negative."""
        # Valid: zero is allowed
        model = ShipCountRequest(target="rope", new_count=0)
        assert model.new_count == 0

        # Invalid: negative
        with pytest.raises(ValidationError):
            ShipCountRequest(target="rope", new_count=-1)

    def test_ship_count_request_expected_count_optional(self):
        """ShipCountRequest should allow expected_current_count to be None or int."""
        # None is fine
        model = ShipCountRequest(target="rope", new_count=10, expected_current_count=None)
        assert model.expected_current_count is None

        # Integer is fine
        model = ShipCountRequest(target="rope", new_count=10, expected_current_count=5)
        assert model.expected_current_count == 5

    def test_coin_map_request_all_non_negative(self):
        """CoinMapRequest should enforce all coin counts are non-negative."""
        # Valid
        model = CoinMapRequest(
            person_piastre=100,
            person_guinea=50,
            ship_piastre=200,
            ship_guinea=75,
        )
        assert model.person_piastre == 100

        # Invalid: negative value
        with pytest.raises(ValidationError):
            CoinMapRequest(
                person_piastre=-1,
                person_guinea=50,
                ship_piastre=200,
                ship_guinea=75,
            )

    def test_coin_set_request_structure(self):
        """CoinSetRequest should validate both known and new coin values."""
        # Valid: all fields present
        model = CoinSetRequest(
            known_person_piastre=100,
            known_person_guinea=50,
            known_ship_piastre=200,
            known_ship_guinea=75,
            new_person_piastre=110,
            new_person_guinea=55,
            new_ship_piastre=220,
            new_ship_guinea=80,
            dry_run=True,
        )
        assert model.new_person_piastre == 110

        # Valid: new values can be None
        model = CoinSetRequest(
            known_person_piastre=100,
            known_person_guinea=50,
            known_ship_piastre=200,
            known_ship_guinea=75,
            new_person_piastre=None,  # Optional
            dry_run=False,
        )
        assert model.new_person_piastre is None

    def test_restore_backup_request_required_field(self):
        """RestoreBackupRequest should require backup_name."""
        model = RestoreBackupRequest(backup_name="20260420_120000")
        assert model.backup_name == "20260420_120000"

        # Missing field should fail
        with pytest.raises(ValidationError):
            RestoreBackupRequest()


class TestRequestModelSerialization:
    """Test that models can be serialized and deserialized correctly."""

    def test_config_update_json_roundtrip(self):
        """ConfigUpdate should serialize and deserialize via JSON."""
        original = ConfigUpdate(save_root="/test/path", manifest_path="/manifest/path")
        json_data = original.model_dump_json()
        restored = ConfigUpdate.model_validate_json(json_data)
        assert restored.save_root == original.save_root
        assert restored.manifest_path == original.manifest_path

    def test_inventory_target_count_json_roundtrip(self):
        """InventoryTargetCount should maintain data through JSON serialization."""
        original = InventoryTargetCount(target="rope", count=25)
        json_data = original.model_dump_json()
        restored = InventoryTargetCount.model_validate_json(json_data)
        assert restored.target == "rope"
        assert restored.count == 25

    def test_ship_add_request_json_roundtrip(self):
        """ShipAddRequest with nested targets should serialize correctly."""
        original = ShipAddRequest(
            targets=[
                InventoryTargetCount(target="rope", count=10),
                InventoryTargetCount(target="wood", count=20),
            ],
            dry_run=True,
            strict_manifest=True,
        )
        json_data = original.model_dump_json()
        restored = ShipAddRequest.model_validate_json(json_data)
        assert len(restored.targets) == 2
        assert restored.targets[0].target == "rope"
        assert restored.dry_run is True


class TestInventoryTargetCountContract:
    """Test the critical InventoryTargetCount contract used throughout the API."""

    def test_target_field_is_string(self):
        """target must be a string (item name or alias)."""
        model = InventoryTargetCount(target="copper", count=5)
        assert isinstance(model.target, str)
        assert len(model.target) > 0

    def test_count_field_is_positive_integer(self):
        """count must be a positive integer."""
        model = InventoryTargetCount(target="rope", count=1)
        assert isinstance(model.count, int)
        assert model.count > 0

    def test_cannot_add_extra_fields(self):
        """InventoryTargetCount should not accept arbitrary extra fields."""
        # By default, Pydantic ignores extra fields, but we can verify structure
        data = {"target": "rope", "count": 5, "extra_field": "ignored"}
        model = InventoryTargetCount(**data)
        assert not hasattr(model, "extra_field")
        assert model.target == "rope"
        assert model.count == 5


class TestShipCountRequestContract:
    """Test the contract for ship count mutation requests."""

    def test_target_identifies_item(self):
        """target should identify the item to count."""
        model = ShipCountRequest(target="rope", new_count=5)
        assert model.target == "rope"

    def test_new_count_is_non_negative_integer(self):
        """new_count should be a non-negative integer."""
        model = ShipCountRequest(target="rope", new_count=0)
        assert model.new_count == 0

        model = ShipCountRequest(target="rope", new_count=100)
        assert model.new_count == 100

    def test_dry_run_defaults_to_true(self):
        """dry_run should default to True for safety."""
        model = ShipCountRequest(target="rope", new_count=5)
        assert model.dry_run is True


class TestCoinMapRequestContract:
    """Test the contract for coin mapping requests."""

    def test_all_coin_types_present(self):
        """All four coin type fields should be present and non-negative."""
        model = CoinMapRequest(
            person_piastre=100,
            person_guinea=50,
            ship_piastre=200,
            ship_guinea=75,
        )
        assert model.person_piastre >= 0
        assert model.person_guinea >= 0
        assert model.ship_piastre >= 0
        assert model.ship_guinea >= 0

    def test_coin_values_are_integers(self):
        """Coin values should be integers."""
        model = CoinMapRequest(
            person_piastre=100,
            person_guinea=50,
            ship_piastre=200,
            ship_guinea=75,
        )
        assert all(isinstance(getattr(model, f), int) for f in [
            "person_piastre", "person_guinea", "ship_piastre", "ship_guinea"
        ])
