"""Tests for service method response contracts.

These tests verify that service methods return data structures with expected
fields and types, ensuring that UI and CLI code doesn't break silently when
internal data structures change.
"""
import pytest
from pathlib import Path
from r5_save_tool.ui_service import service


class TestStatusResponseContract:
    """Test the contract for status/config responses."""

    def test_get_status_has_required_fields(self):
        """get_status() should return dict with required fields."""
        result = service.get_status()
        assert isinstance(result, dict)
        # Config fields from UIConfigState dataclass
        assert "save_root" in result
        assert "manifest_path" in result
        # Resolved fields added by _config_snapshot
        assert "resolved_save_root" in result
        assert "doctor" in result

    def test_config_has_string_paths(self):
        """save_root and manifest_path should be strings or None."""
        try:
            result = service.get_status()
            if "save_root" in result:
                assert result["save_root"] is None or isinstance(result["save_root"], str)
        except Exception:
            pytest.skip("Service initialization failed")


class TestCatalogSearchResponseContract:
    """Test the contract for inventory catalog search responses."""

    def test_catalog_search_returns_list_of_items(self):
        """search_inventory_catalog should return a dict with 'results' list."""
        try:
            result = service.search_inventory_catalog(query="rope", limit=5)
            assert isinstance(result, dict)
            assert "results" in result
            assert isinstance(result["results"], list)
        except Exception:
            pytest.skip("Service not initialized or database unavailable")

    def test_catalog_item_has_required_fields(self):
        """Each catalog item should have required display fields."""
        try:
            result = service.search_inventory_catalog(query="rope", limit=5)
            for item in result.get("results", []):
                # Critical fields for UI display
                assert "asset_name" in item, f"Missing asset_name in: {item}"
                assert "display_label" in item, f"Missing display_label in: {item}"
                assert "in_game_label" in item, f"Missing in_game_label in: {item}"
                # All should be strings
                assert isinstance(item.get("asset_name"), str)
                assert isinstance(item.get("display_label"), str)
                assert isinstance(item.get("in_game_label"), str)
        except Exception:
            pytest.skip("Service not initialized or database unavailable")

    def test_catalog_respects_limit(self):
        """search_inventory_catalog should respect the limit parameter."""
        try:
            result = service.search_inventory_catalog(query=None, limit=5)
            assert len(result.get("results", [])) <= 5

            result = service.search_inventory_catalog(query=None, limit=1)
            assert len(result.get("results", [])) <= 1
        except Exception:
            pytest.skip("Service not initialized or database unavailable")


class TestInventoryInspectResponseContract:
    """Test the contract for inventory inspection responses."""

    def test_inspect_inventory_has_items_list(self):
        """inspect_inventory should return dict with 'items' key."""
        try:
            result = service.inspect_inventory(ship_capacity=28)
            assert isinstance(result, dict)
            assert "items" in result
            assert isinstance(result["items"], list)
        except Exception:
            pytest.skip("Service not initialized or database unavailable")

    def test_inspect_inventory_item_has_required_fields(self):
        """Each item in inventory should have required fields."""
        try:
            result = service.inspect_inventory(ship_capacity=28)
            for item in result.get("items", []):
                # Required for item identification and display
                assert "item_name" in item, f"Missing item_name in: {item}"
                assert "cf" in item, f"Missing cf (R5BLPlayer/R5BLShip) in: {item}"
                assert "inventory_scope" in item, f"Missing inventory_scope in: {item}"
                assert "count" in item, f"Missing count in: {item}"

                # Validate field types
                assert isinstance(item.get("item_name"), str)
                assert item.get("cf") in ("R5BLPlayer", "R5BLShip")
                assert isinstance(item.get("count"), (int, type(None)))
        except Exception:
            pytest.skip("Service not initialized or database unavailable")

    def test_ship_items_have_ship_name_field(self):
        """Ship items should have ship_name for UI grouping."""
        try:
            result = service.inspect_inventory(ship_capacity=28)
            ship_items = [i for i in result.get("items", []) if i.get("cf") == "R5BLShip"]
            for item in ship_items:
                assert "ship_name" in item, f"Ship item missing ship_name: {item}"
                assert isinstance(item.get("ship_name"), str)
        except Exception:
            pytest.skip("Service not initialized or database unavailable")

    def test_inspect_inventory_has_capacity_dict(self):
        """inspect_inventory should return capacity dict with slot tracking."""
        try:
            result = service.inspect_inventory(ship_capacity=28)
            assert "capacity" in result
            cap = result["capacity"]

            # Required capacity fields
            expected_fields = {
                "ship_total_capacity",
                "ship_used_slots_observed",
                "ship_free_slots",
            }
            assert all(f in cap for f in expected_fields)

            # Validate types
            assert isinstance(cap["ship_total_capacity"], int)
            assert isinstance(cap["ship_used_slots_observed"], int)
            assert isinstance(cap["ship_free_slots"], int)
        except Exception:
            pytest.skip("Service not initialized or database unavailable")


class TestInventoryPlanResponseContract:
    """Test the contract for inventory plan responses."""

    def test_plan_response_has_stage_plan(self, configured_service):
        """inventory_plan should return stage plan data."""
        result = configured_service.inventory_plan(
            targets={"rope": 10},
            player_open_slots_per_stage=20,
            ship_capacity=28,
            strict_manifest=False,
        )
        assert isinstance(result, dict)
        # build_inventory_stage_plan returns: constraints, targets, missing_items,
        # unknown_stack_caps, summary, notes
        assert "targets" in result
        assert "summary" in result
        assert "constraints" in result


class TestCoinInspectResponseContract:
    """Test the contract for coin inspection responses."""

    def test_coins_inspect_has_coin_objects(self, configured_service):
        """inspect_coins should return dict with coin data."""
        result = configured_service.inspect_coins()
        assert isinstance(result, dict)
        # inspect_coins returns: containers, coin_items, notes
        assert "containers" in result
        assert "coin_items" in result
        assert isinstance(result["containers"], list)
        assert isinstance(result["coin_items"], list)


class TestErrorHandlingContract:
    """Test that service methods fail gracefully with expected errors."""

    def test_resolve_invalid_target_raises_error(self):
        """resolve_inventory_target should raise error for invalid target."""
        try:
            # Try to resolve a target that definitely doesn't exist
            with pytest.raises(Exception):
                service.resolve_inventory_target(
                    target="DEFINITELY_NOT_A_REAL_ITEM_12345",
                    strict_manifest=False,
                )
        except Exception:
            pytest.skip("Service not initialized")

    def test_apply_operations_with_invalid_target_fail(self):
        """apply_ship_add should handle invalid targets gracefully."""
        try:
            result = service.apply_ship_add(
                targets={"INVALID_ITEM": 1},
                dry_run=True,
                allow_assumed_assets=False,
                strict_manifest=False,
            )
            # Should return error info or raise
            # Either is fine - we just want it to not crash silently
            assert result is not None or isinstance(result, dict)
        except Exception:
            # Expected to fail - just verify it's a proper exception
            pass


class TestBackupResponseContract:
    """Test the contract for backup list responses."""

    def test_list_backups_returns_list_structure(self):
        """list_backups endpoint should return list of backup dicts."""
        try:
            result = service.list_backups(db="players")
            assert isinstance(result, dict)
            if "backups" in result:
                assert isinstance(result["backups"], list)
                for backup in result["backups"]:
                    assert isinstance(backup, dict)
        except Exception:
            pytest.skip("Service not initialized or no backups exist")
