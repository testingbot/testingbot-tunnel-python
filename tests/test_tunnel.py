from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Tuple

import pytest

from testingbot_tunnel import (
    CredentialsError,
    Tunnel,
    TunnelError,
    TunnelStartError,
    TunnelTimeoutError,
    active_tunnels,
    stop_all,
)
from testingbot_tunnel import (
    tunnel as tunnel_module,
)
from testingbot_tunnel._output import INVALID_CREDENTIALS, NO_MINUTES

from .conftest import FakeJava

pytestmark = pytest.mark.usefixtures("cached_jar", "credentials")


def test_starts_and_stops(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    tunnel = Tunnel(tunnel_identifier="build-1").start()
    try:
        assert tunnel.is_running()
        assert tunnel.version == "5.2"
        assert tunnel in active_tunnels()
        readyfile = tunnel.readyfile
        assert readyfile is not None and os.path.exists(readyfile)
    finally:
        tunnel.stop()
    assert not tunnel.is_running()
    assert tunnel.process is not None and tunnel.process.returncode is not None
    assert not os.path.exists(os.path.dirname(readyfile))
    assert tunnel not in active_tunnels()
    tunnel.stop()  # a second stop does nothing


def test_context_manager(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    with Tunnel() as tunnel:
        assert tunnel.is_running()
        process = tunnel.process
    assert process is not None and process.poll() is not None


def test_passes_credentials_through_environment_not_arguments(
    fake_java: FakeJava, credentials: Tuple[str, str]
) -> None:
    fake_java.behave("ready")
    with Tunnel(tunnel_identifier="build-1", se_port=4446, no_bump=True):
        pass
    start = next(call for call in fake_java.calls() if "-f" in call.split())
    key, secret = credentials
    assert key not in start and secret not in start
    assert "--tunnel-identifier build-1 --se-port 4446 --nobump -f " in start
    assert fake_java.env_log.read_text().strip() == f"{key}:{secret}"


def test_explicit_credentials_win(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    with Tunnel("explicit-key", "explicit-secret"):
        pass
    assert fake_java.env_log.read_text().strip() == "explicit-key:explicit-secret"


def test_every_tunnel_gets_a_private_readyfile(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    with Tunnel(tunnel_identifier="a") as first, Tunnel(tunnel_identifier="b", se_port=4446) as second:
        assert first.readyfile != second.readyfile
        for tunnel in (first, second):
            directory = Path(tunnel.readyfile or "").parent
            assert directory.parent == Path(tempfile.gettempdir())
            assert directory.name.startswith("testingbot-tunnel-")
            if os.name != "nt":
                assert directory.stat().st_mode & 0o077 == 0
        assert set(active_tunnels()) == {first, second}


def test_without_credentials(fake_java: FakeJava, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_KEY")
    with pytest.raises(CredentialsError):
        Tunnel().start()
    assert fake_java.calls() == []


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("unauthorized", INVALID_CREDENTIALS),
        ("minutes", NO_MINUTES),
        ("limit", "You already have 2 tunnels active - please close another tunnel first"),
        ("http-error", "Your account is suspended"),
        ("java-too-old", "TestingBot Tunnel requires Java 17 or higher"),
    ],
)
def test_reports_why_the_tunnel_did_not_start(fake_java: FakeJava, mode: str, message: str) -> None:
    fake_java.behave(mode)
    tunnel = Tunnel()
    started = time.monotonic()
    with pytest.raises(TunnelStartError) as raised:
        tunnel.start()
    assert str(raised.value) == message
    assert time.monotonic() - started < 10
    assert tunnel.process is not None and tunnel.process.poll() is not None
    assert not os.path.exists(os.path.dirname(tunnel.readyfile or ""))
    assert active_tunnels() == []


def test_reports_exit_code_and_last_lines(fake_java: FakeJava) -> None:
    fake_java.behave("crash")
    with pytest.raises(
        TunnelStartError, match="Could not start TestingBot Tunnel. Exit code 3\nUnknown option: --bogus"
    ):
        Tunnel().start()


def test_java_that_can_not_be_started(fake_java: FakeJava, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from testingbot_tunnel import _runtime

    monkeypatch.setattr(
        _runtime, "prepare_runtime", lambda options: _runtime.Runtime(str(tmp_path / "no-java"), "x.jar", "5.2")
    )
    with pytest.raises(TunnelStartError, match="Could not start TestingBot Tunnel:"):
        Tunnel().start()


def test_times_out_and_stops_the_tunnel(fake_java: FakeJava) -> None:
    tunnel = Tunnel(timeout=1)
    with pytest.raises(TunnelTimeoutError, match="Tunnel failed to launch in 1 seconds."):
        tunnel.start()
    assert tunnel.process is not None and tunnel.process.poll() is not None
    assert active_tunnels() == []


def test_keeps_running_when_an_api_call_fails_after_it_is_ready(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    with Tunnel() as tunnel:
        # The fake tunnel reports "HTTP error code : 503" a second after it is ready
        time.sleep(2)
        assert tunnel.is_running()


def test_kills_a_tunnel_that_does_not_stop(fake_java: FakeJava) -> None:
    fake_java.behave("stubborn")
    tunnel = Tunnel().start()
    started = time.monotonic()
    tunnel.stop(timeout=1)
    assert 0.9 < time.monotonic() - started < 5
    assert tunnel.process is not None and tunnel.process.returncode is not None


def test_stop_all(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    first = Tunnel(tunnel_identifier="a").start()
    second = Tunnel(tunnel_identifier="b").start()
    stop_all()
    assert not first.is_running() and not second.is_running()
    assert active_tunnels() == []


def test_refuses_starting_twice(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    with Tunnel() as tunnel, pytest.raises(TunnelError, match="already started"):
        tunnel.start()


def test_can_be_started_again_after_stop(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    tunnel = Tunnel()
    with tunnel:
        first = tunnel.pid
    with tunnel:
        assert tunnel.pid != first


def test_refuses_options_the_tunnel_version_does_not_know(fake_java: FakeJava) -> None:
    fake_java.set("FAKE_JAVA_TUNNEL", "4.9")
    with pytest.raises(ValueError, match="allow_hosts requires TestingBot Tunnel 5.0 or higher, but version 4.9"):
        Tunnel(allow_hosts="example.com").start()


def test_verbose_output_is_redacted(
    fake_java: FakeJava, caplog: pytest.LogCaptureFixture, credentials: Tuple[str, str]
) -> None:
    fake_java.behave("ready")
    with caplog.at_level(logging.INFO, logger="testingbot_tunnel"), Tunnel(verbose=True, proxy_userpwd="user:pw"):
        deadline = time.monotonic() + 5
        while "Tunnel is starting" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.1)
    assert "Tunnel is starting with key ***" in caplog.text
    assert "Starting tunnel with options" in caplog.text
    for secret in (*credentials, "user:pw"):
        assert secret not in caplog.text


def test_options_property_hides_credentials() -> None:
    tunnel = Tunnel("k", "s", tunnel_identifier="x")
    assert tunnel.options == {"tunnel_identifier": "x"}
    assert tunnel.tunnel_identifier == "x"
    assert "k" not in repr(tunnel).replace("identifier", "")


def test_exit_handler_is_registered(fake_java: FakeJava) -> None:
    fake_java.behave("ready")
    with Tunnel():
        assert tunnel_module._exit_handler_registered
