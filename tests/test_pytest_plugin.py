from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

pytestmark = pytest.mark.usefixtures("cached_jar", "credentials")


def test_fixture_starts_one_tunnel_for_the_session(pytester: pytest.Pytester, fake_java) -> None:  # type: ignore[no-untyped-def]
    fake_java.behave("ready")
    pytester.makepyfile(
        """
        PIDS = set()

        def test_one(testingbot_tunnel):
            assert testingbot_tunnel.is_running()
            assert testingbot_tunnel.tunnel_identifier == "ci-42"
            PIDS.add(testingbot_tunnel.pid)

        def test_two(testingbot_tunnel):
            PIDS.add(testingbot_tunnel.pid)
            assert len(PIDS) == 1
        """
    )
    result = pytester.runpytest_subprocess("--tb-tunnel-identifier", "ci-42")
    result.assert_outcomes(passed=2)
    starts = [call for call in fake_java.calls() if " -f " in call]
    assert len(starts) == 1
    assert "--tunnel-identifier ci-42" in starts[0]


def test_tb_tunnel_starts_it_for_tests_that_do_not_ask(pytester: pytest.Pytester, fake_java) -> None:  # type: ignore[no-untyped-def]
    fake_java.behave("ready")
    pytester.makepyfile("def test_plain():\n    pass\n")
    result = pytester.runpytest_subprocess("--tb-tunnel")
    result.assert_outcomes(passed=1)
    assert len([call for call in fake_java.calls() if " -f " in call]) == 1


def test_no_tunnel_without_flag_or_fixture(pytester: pytest.Pytester, fake_java) -> None:  # type: ignore[no-untyped-def]
    pytester.makepyfile("def test_plain():\n    pass\n")
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)
    assert fake_java.calls() == []


def test_options_fixture_can_be_overridden(pytester: pytest.Pytester, fake_java) -> None:  # type: ignore[no-untyped-def]
    fake_java.behave("ready")
    pytester.makeconftest(
        """
        import pytest

        @pytest.fixture(scope="session")
        def testingbot_tunnel_options():
            return {"se_port": 4999, "no_bump": True}
        """
    )
    pytester.makepyfile("def test_it(testingbot_tunnel):\n    assert testingbot_tunnel.is_running()\n")
    pytester.runpytest_subprocess().assert_outcomes(passed=1)
    start = next(call for call in fake_java.calls() if " -f " in call)
    assert "--se-port 4999 --nobump" in start


def test_failure_to_start_is_reported(pytester: pytest.Pytester, fake_java) -> None:  # type: ignore[no-untyped-def]
    fake_java.behave("unauthorized")
    pytester.makepyfile("def test_it(testingbot_tunnel):\n    pass\n")
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*Invalid credentials*"])


def test_help_lists_the_options(pytester: pytest.Pytester) -> None:
    result = pytester.runpytest_subprocess("--help")
    result.stdout.fnmatch_lines(["*--tb-tunnel *", "*--tb-tunnel-identifier=ID*", "*--tb-tunnel-version=VERSION*"])
