#!/usr/bin/env python3
"""Create synthetic RocksDB fixture databases for the test suite.

Run once from the project root:
    uv run python scripts/create_test_fixtures.py

The generated files live under test_saves/ and can be committed to version
control. They contain no real game data — only minimal synthetic records that
satisfy the structure expected by the test suite.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import create_test_fixtures

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "test_saves"
    create_test_fixtures(root)
    print(f"Test fixtures created at: {root}")
