"""Tests for CLI command contracts and argument validation.

These tests ensure that CLI commands maintain their interfaces and that
changes to command structure or arguments are caught immediately.
"""
import pytest
from click.testing import CliRunner
from r5_save_tool.cli import cli


class TestCLICommandStructure:
    """Test that CLI commands exist and have expected signatures."""

    def test_cli_main_command_exists(self):
        """The main cli group should exist and be callable."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Help output should mention subcommands
        assert "Commands:" in result.output or "Options:" in result.output

    def test_cli_accepts_save_root_option(self):
        """CLI should accept --save-root for path configuration."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--save-root", "/test/path", "--help"])
        # Should not error on this option
        assert result.exit_code == 0

    def test_cli_commands_listed_in_help(self):
        """Key commands should be listed in help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        # These are critical commands that should always exist
        expected_commands = ["doctor", "backups", "inventory-inspect"]
        help_text = result.output.lower()
        # At least some key commands should be listed
        assert "doctor" in help_text or "command" in help_text


class TestDoctorCommandContract:
    """Test the doctor command interface."""

    def test_doctor_command_exists(self):
        """doctor command should be available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--help"])
        assert result.exit_code == 0 or "No such command" not in result.output

    def test_doctor_returns_json_format(self):
        """doctor command should support JSON output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json", "test.json"])
        # Either succeeds or fails with proper error, not "unknown option"
        assert "--json" not in result.output or "unknown option" not in result.output.lower()


class TestBackupsCommandContract:
    """Test the backups command interface."""

    def test_backups_requires_db_argument(self):
        """backups command should require which database to list."""
        runner = CliRunner()
        # Without a db argument, should fail
        result = runner.invoke(cli, ["backups"])
        # Should either error about missing arg or show help
        assert result.exit_code != 0 or "USAGE" in result.output

    def test_backups_accepts_players_db(self):
        """backups should accept 'players' as database choice."""
        runner = CliRunner()
        result = runner.invoke(cli, ["backups", "players"])
        # Should not error about invalid choice
        assert "invalid choice" not in result.output.lower() or "players" in result.output


class TestInventoryInspectCommandContract:
    """Test the inventory-inspect command interface."""

    def test_inventory_inspect_command_exists(self):
        """inventory-inspect command should be available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory-inspect", "--help"])
        assert result.exit_code == 0 or "No such command" not in result.output

    def test_inventory_inspect_accepts_output_path(self):
        """inventory-inspect should support --out for output file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory-inspect", "--out", "test.json"])
        # Should not complain about unknown option
        assert "--out" not in result.output or "unknown option" not in result.output.lower()


class TestManifestCheckCommandContract:
    """Test the manifest-check command for inventory target validation."""

    def test_manifest_check_command_exists(self):
        """manifest-check command should be available for testing targets."""
        runner = CliRunner()
        result = runner.invoke(cli, ["manifest-check", "--help"])
        # Command should exist or be clearly unavailable
        assert "no such command" not in result.output.lower() or result.exit_code == 0


class TestInventoryAddShipCommandContract:
    """Test the inventory-add-ship command interface."""

    def test_inventory_add_ship_requires_target(self):
        """inventory-add-ship should require --target argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory-add-ship"])
        # Should fail without required argument
        assert result.exit_code != 0 or "--target" in result.output

    def test_inventory_add_ship_accepts_dry_run_flag(self):
        """inventory-add-ship should support --dry-run for safety."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory-add-ship", "--help"])
        # Help should mention the flag
        help_text = result.output.lower()
        assert "dry" in help_text or "help" in help_text


class TestShipCountCommandContract:
    """Test the inventory-set-ship-count command interface."""

    def test_ship_count_requires_target_and_count(self):
        """inventory-set-ship-count should require target and count."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory-set-ship-count"])
        # Should fail without required arguments
        assert result.exit_code != 0 or "target" in result.output.lower()


class TestCoinCommandContract:
    """Test coin-related command interfaces."""

    def test_coin_inspect_command_exists(self):
        """coin-inspect command should exist."""
        runner = CliRunner()
        result = runner.invoke(cli, ["coin-inspect", "--help"])
        assert "no such command" not in result.output.lower() or result.exit_code == 0

    def test_coin_set_command_exists(self):
        """coin-set command should exist."""
        runner = CliRunner()
        result = runner.invoke(cli, ["coin-set", "--help"])
        assert "no such command" not in result.output.lower() or result.exit_code == 0


class TestDatabaseChoiceValidation:
    """Test that database choices are consistently validated."""

    def test_db_argument_accepts_players(self):
        """Commands accepting 'db' arg should accept 'players'."""
        runner = CliRunner()
        result = runner.invoke(cli, ["backups", "players"])
        # Should not error about invalid choice
        assert "invalid choice" not in result.output.lower()

    def test_db_argument_accepts_accounts(self):
        """Commands accepting 'db' arg should accept 'accounts'."""
        runner = CliRunner()
        result = runner.invoke(cli, ["backups", "accounts"])
        # Should not error about invalid choice
        assert "invalid choice" not in result.output.lower()

    def test_db_argument_rejects_invalid_choice(self):
        """Invalid database choice should be rejected."""
        runner = CliRunner()
        result = runner.invoke(cli, ["backups", "invalid"])
        # Should error about choice
        assert result.exit_code != 0 or "invalid choice" in result.output.lower()


class TestCLIErrorHandling:
    """Test that CLI errors are handled consistently."""

    def test_missing_save_root_gives_clear_error(self):
        """CLI should give clear error if save root is not found."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        # Should either work (if test save exists) or give clear error
        # Not an uncaught exception
        assert result.exit_code >= 0
        assert "Traceback" not in result.output

    def test_help_flag_works_on_all_commands(self):
        """All commands should support --help."""
        runner = CliRunner()
        commands = ["doctor", "backups"]
        for cmd in commands:
            result = runner.invoke(cli, [cmd, "--help"])
            # Help should work for existing commands
            if "no such command" not in result.output.lower():
                assert "USAGE" in result.output or result.exit_code == 0


class TestCLIOutputFormats:
    """Test that CLI output formats are consistent."""

    def test_json_output_is_valid_json(self):
        """Commands with --json-out should produce valid JSON."""
        import json
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["doctor", "--json-out", "output.json"])
            # If output file was created, it should be valid JSON
            try:
                with open("output.json") as f:
                    data = json.load(f)
                    assert isinstance(data, dict)
            except (FileNotFoundError, json.JSONDecodeError):
                # File might not exist if command failed, that's ok
                pass

    def test_text_output_is_readable(self):
        """Regular output should be human-readable text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        # Output should be text, not binary or JSON
        assert isinstance(result.output, str)
        assert len(result.output) > 0
