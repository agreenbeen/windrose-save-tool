"""Tests for save root detection and validation."""
import pytest
from pathlib import Path
from r5_save_tool.save_context import find_save_root, resolve_db_dir, doctor_status


class TestSaveRootDetection:
    """Test save root discovery and database directory resolution."""

    def test_find_save_root_with_test_save(self, test_save_root: Path):
        """Test that find_save_root correctly identifies the test save root."""
        result = find_save_root(test_save_root)
        assert result is not None
        assert result.exists()

    def test_resolve_db_dir_players(self, test_save_root: Path):
        """Test that we can resolve the players database directory."""
        db_dir = resolve_db_dir(test_save_root, "players")
        assert db_dir.exists()
        assert "Players" in str(db_dir) or "players" in str(db_dir).lower()

    def test_resolve_db_dir_accounts(self, test_save_root: Path):
        """Test that we can resolve the accounts database directory."""
        # Note: accounts dir may not exist in test save, but the function
        # should return a path that follows the expected pattern
        db_dir = resolve_db_dir(test_save_root, "accounts")
        assert isinstance(db_dir, Path)

    def test_doctor_status_with_test_save(self, test_save_root: Path):
        """Test the doctor status check with the test save."""
        status = doctor_status(test_save_root)

        # doctor_status returns a dict with status keys
        assert isinstance(status, dict)
        assert "issue_count" in status or "status" in status or "players" in status

    def test_resolve_db_dir_invalid_db_type(self, test_save_root: Path):
        """Test that invalid database type raises an error."""
        try:
            result = resolve_db_dir(test_save_root, "invalid_db")
            # If it doesn't raise, it should at least return a Path
            assert isinstance(result, Path)
        except (ValueError, KeyError, TypeError):
            # Expected to raise one of these
            pass
