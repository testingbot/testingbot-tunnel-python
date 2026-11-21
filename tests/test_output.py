from __future__ import annotations

from testingbot_tunnel._output import (
    INVALID_CREDENTIALS,
    NO_MINUTES,
    classify_tunnel_error,
    describe_startup_failure,
    parse_log_line,
)
from testingbot_tunnel.diagnostics import DoctorCheck, parse_doctor_output, parse_pac_test_output


class TestClassifyTunnelError:
    def test_wrong_credentials(self) -> None:
        assert classify_tunnel_error("An error ocurred: 401 Unauthorized") == INVALID_CREDENTIALS
        assert (
            classify_tunnel_error('Failed : HTTP error code : 401 - {"error":"401 Unauthorized."}')
            == INVALID_CREDENTIALS
        )

    def test_no_minutes(self) -> None:
        assert classify_tunnel_error("An error ocurred: You have no minutes left") == NO_MINUTES

    def test_tunnel_limit_in_the_tunnels_wording(self) -> None:
        line = "An error ocurred: You already have 2 tunnels active - please close another tunnel first"
        assert classify_tunnel_error(line) == "You already have 2 tunnels active - please close another tunnel first"

    def test_whole_line_when_nothing_follows_the_prefix(self) -> None:
        assert classify_tunnel_error("An error ocurred:") == "An error ocurred:"

    def test_reason_the_api_gives(self) -> None:
        line = 'Failed : HTTP error code : 403 - {"error":"Your account is suspended"}'
        assert classify_tunnel_error(line) == "Your account is suspended"

    def test_answer_that_is_not_json(self) -> None:
        assert classify_tunnel_error("Failed : HTTP error code : 502 - Bad Gateway") == "Bad Gateway"

    def test_status_without_reason(self) -> None:
        assert classify_tunnel_error("Failed : HTTP error code : 503") == (
            "TestingBot refused to create the tunnel, HTTP status 503"
        )

    def test_can_not_reach_testingbot(self) -> None:
        line = "Creating a new tunnel failed, please check your internet connection"
        assert classify_tunnel_error(line) == line

    def test_java_too_old(self) -> None:
        line = "TestingBot Tunnel requires Java 17 or higher, this is Java 11"
        assert classify_tunnel_error(line) == line

    def test_leaves_ordinary_output_alone(self) -> None:
        assert classify_tunnel_error("Tunnel is starting") is None
        assert classify_tunnel_error("") is None


class TestParseLogLine:
    def test_unpacks_json_record(self) -> None:
        assert parse_log_line('{"level":"info","message":"Tunnel is ready"}') == ["Tunnel is ready"]

    def test_splits_record_holding_several_lines(self) -> None:
        assert parse_log_line('{"message":"one\\ntwo"}') == ["one", "two"]

    def test_leaves_text_and_brace_output_alone(self) -> None:
        assert parse_log_line("plain") == ["plain"]
        assert parse_log_line("{not json") == ["{not json"]
        assert parse_log_line('{"no":"message"}') == ['{"no":"message"}']


class TestDescribeStartupFailure:
    def test_adds_what_the_tunnel_wrote(self) -> None:
        assert describe_startup_failure(None, 1, ["", "Unknown option: --bogus"]) == (
            "Could not start TestingBot Tunnel. Exit code 1\nUnknown option: --bogus"
        )

    def test_keeps_recognised_reason(self) -> None:
        assert describe_startup_failure(INVALID_CREDENTIALS, 1, ["x"]) == INVALID_CREDENTIALS

    def test_exit_code_alone_when_tunnel_said_nothing(self) -> None:
        assert describe_startup_failure(None, 1) == "Could not start TestingBot Tunnel. Exit code 1"


class TestDiagnosticsParsing:
    def test_doctor_json(self) -> None:
        lines = [
            '{"level":"INFO","message":"OK - Proxy port 8087 can be opened"}',
            '{"level":"WARN","message":"WARN - DNS is slow"}',
            '{"level":"ERROR","message":"Port 4445 is in use"}',
            '{"level":"INFO","message":"Checking"}',
        ]
        assert parse_doctor_output(lines) == [
            DoctorCheck("ok", "Proxy port 8087 can be opened"),
            DoctorCheck("warn", "DNS is slow"),
            DoctorCheck("fail", "Port 4445 is in use"),
            DoctorCheck("info", "Checking"),
        ]

    def test_doctor_text(self) -> None:
        lines = [
            "Nov 05, 2026 11:03:51 AM com.testingbot.tunnel.Doctor performCheck",
            "INFO: OK - Proxy port 8087 can be opened",
            "Nov 05, 2026 11:03:52 AM com.testingbot.tunnel.Doctor performCheck",
            "SEVERE: Port 4445 is in use",
            "by another process",
        ]
        assert parse_doctor_output(lines) == [
            DoctorCheck("ok", "Proxy port 8087 can be opened"),
            DoctorCheck("fail", "Port 4445 is in use\nby another process"),
        ]

    def test_pac_test(self) -> None:
        result = parse_pac_test_output(
            [
                "PAC file : /etc/proxy.pac",
                "URL      : https://intranet.example.com/",
                "Host     : intranet.example.com",
                "Result   : PROXY proxy.example.com:3128; DIRECT",
                "Egress   : via proxy.example.com:3128",
            ]
        )
        assert result is not None
        assert result.result == "PROXY proxy.example.com:3128; DIRECT"
        assert result.egress == "via proxy.example.com:3128"
        assert result.direct is False
        assert parse_pac_test_output(["Result : DIRECT", "Egress : direct connection"]).direct is True  # type: ignore[union-attr]
        assert parse_pac_test_output(["nothing"]) is None
