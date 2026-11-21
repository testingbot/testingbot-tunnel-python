from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from testingbot_tunnel import stop_all


def pytest_collection_modifyitems(items: list) -> None:
    for item in items:
        item.add_marker(pytest.mark.live)


@pytest.fixture(scope="session")
def live_cache() -> Iterator[Path]:
    """Downloads go to a temporary directory, shared by the live tests and removed afterwards."""
    with tempfile.TemporaryDirectory(prefix="testingbot-tunnel-live-") as directory:
        yield Path(directory)


@pytest.fixture(autouse=True)
def isolated(live_cache: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Replaces the isolation of the unit tests: the live tests use the real credentials."""
    if os.environ.get("TESTINGBOT_LIVE") != "1":
        pytest.skip("set TESTINGBOT_LIVE=1 to run the live tests")
    monkeypatch.setenv("TESTINGBOT_TUNNEL_CACHE_DIR", str(live_cache))
    yield
    stop_all()
