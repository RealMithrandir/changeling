"""Shared test fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _use_test_db(tmp_path: Path) -> None:  # type: ignore[misc]
    """Point DB at a temp file for every test."""
    os.environ["CHANGELING_DB_PATH"] = str(tmp_path / "test.db")
    # Ensure grimoire path is correct
    os.environ["CHANGELING_GRIMOIRE_PATH"] = str(
        Path(__file__).parent.parent / "config" / "grimoire.toml"
    )
