from __future__ import annotations

from pathlib import Path

import pytest

from hiab.config import Settings, load_settings
from hiab.logging_setup import setup_logging


@pytest.fixture(autouse=True)
def quiet_logging() -> None:
    setup_logging("WARNING")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        {"data_dir": str(tmp_path / "data"), "map_width": 48, "map_height": 48}, {}
    )
