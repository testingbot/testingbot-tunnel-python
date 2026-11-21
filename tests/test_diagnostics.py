from __future__ import annotations

import pytest

from testingbot_tunnel import TunnelError, doctor, pac_test

from .conftest import FakeJava

pytestmark = pytest.mark.usefixtures("cached_jar")


def test_doctor_reports_checks(fake_java: FakeJava, credentials: tuple) -> None:
    report = doctor(se_port=4446)
    assert report.ok
    assert [(check.status, check.message) for check in report.checks] == [("ok", "Proxy port 8087 can be opened")]
    call = next(call for call in fake_java.calls() if "--doctor" in call)
    assert "--se-port 4446 --log-format json --doctor" in call
    assert fake_java.env_log.exists() is False  # credentials are only passed through the environment
    assert credentials[1] not in call


def test_doctor_reports_failed_check(fake_java: FakeJava) -> None:
    fake_java.behave("port-in-use")
    report = doctor()
    assert not report.ok
    assert report.checks[-1].status == "fail"


def test_doctor_raises_when_checks_could_not_run(fake_java: FakeJava) -> None:
    fake_java.behave("crash")
    with pytest.raises(TunnelError, match="Exit code 2\nOK - Proxy port 8087 can be opened\nUnknown option: --bogus"):
        doctor()


def test_pac_test(fake_java: FakeJava) -> None:
    result = pac_test("https://intranet.example.com/", pac_local="/etc/proxy.pac")
    assert result.result == "PROXY proxy.example.com:3128; DIRECT"
    assert result.direct is False
    call = next(call for call in fake_java.calls() if "--pac-test" in call)
    assert call.endswith("--pac-local /etc/proxy.pac --pac-test https://intranet.example.com/")


def test_pac_test_reports_what_the_tunnel_says(fake_java: FakeJava) -> None:
    fake_java.behave("bad-pac")
    with pytest.raises(TunnelError, match="does not match --pac-local-sha256"):
        pac_test("https://intranet.example.com/", pac_local="/etc/proxy.pac", pac_local_sha256="0" * 64)


def test_pac_test_needs_tunnel_5(fake_java: FakeJava) -> None:
    fake_java.set("FAKE_JAVA_TUNNEL", "4.9")
    with pytest.raises(ValueError, match="pac_local requires TestingBot Tunnel 5.0"):
        pac_test("https://intranet.example.com/", pac_local="/etc/proxy.pac")


def test_pac_test_arguments() -> None:
    with pytest.raises(ValueError, match="needs the URL"):
        pac_test("", pac_local="/etc/proxy.pac")
    with pytest.raises(ValueError, match="needs pac_local"):
        pac_test("https://x/", pac_local="")
    with pytest.raises(TypeError, match="does not take se_port"):
        pac_test("https://x/", pac_local="/p.pac", se_port=1)
