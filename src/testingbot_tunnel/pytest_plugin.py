"""pytest plugin: a session-wide TestingBot Tunnel.

* The ``testingbot_tunnel`` fixture starts a tunnel the first time a test asks for it and stops
  it at the end of the session.
* ``--tb-tunnel`` starts it at the beginning of the session, also for tests that do not ask for it.
* ``--tb-tunnel-identifier`` and ``--tb-tunnel-version`` set those options. Override the
  ``testingbot_tunnel_options`` fixture to pass any other option.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import pytest

from .tunnel import Tunnel


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("testingbot", "TestingBot Tunnel")
    group.addoption(
        "--tb-tunnel",
        action="store_true",
        default=False,
        help="Start TestingBot Tunnel for the whole test session.",
    )
    group.addoption(
        "--tb-tunnel-identifier",
        default=None,
        metavar="ID",
        help="Tunnel identifier, to use as the tunnel-identifier capability.",
    )
    group.addoption(
        "--tb-tunnel-version",
        default=None,
        metavar="VERSION",
        help="TestingBot Tunnel version to run, e.g. 5.2 (default: the latest).",
    )


@pytest.fixture(scope="session")
def testingbot_tunnel_options(pytestconfig: pytest.Config) -> Dict[str, Any]:
    """The options the tunnel is started with. Override this fixture to pass more of them."""
    options: Dict[str, Any] = {}
    identifier = pytestconfig.getoption("tb_tunnel_identifier")
    if identifier:
        options["tunnel_identifier"] = identifier
    version = pytestconfig.getoption("tb_tunnel_version")
    if version:
        options["tunnel_version"] = version
    return options


@pytest.fixture(scope="session")
def testingbot_tunnel(testingbot_tunnel_options: Dict[str, Any]) -> Iterator[Tunnel]:
    """A running TestingBot Tunnel, shared by every test in the session."""
    tunnel = Tunnel(**testingbot_tunnel_options)
    tunnel.start()
    try:
        yield tunnel
    finally:
        tunnel.stop()


@pytest.fixture(scope="session", autouse=True)
def _testingbot_tunnel_autostart(request: pytest.FixtureRequest) -> None:
    if request.config.getoption("tb_tunnel"):
        request.getfixturevalue("testingbot_tunnel")
