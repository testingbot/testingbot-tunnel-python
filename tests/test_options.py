from __future__ import annotations

import pytest

from testingbot_tunnel import Tunnel
from testingbot_tunnel._options import (
    compare_versions,
    create_args,
    is_version_5_or_up,
    minimum_tunnel_version,
    redact,
    secret_values,
    validate_options,
    validate_options_for_version,
)


class TestValidateOptions:
    def test_accepts_valid_options(self) -> None:
        validate_options(
            {
                "api_key": "k",
                "api_secret": "s",
                "tunnel_identifier": "x",
                "timeout": 30,
                "shared": True,
                "se_port": 4446,
            }
        )

    def test_refuses_unknown_option_and_suggests_the_right_one(self) -> None:
        with pytest.raises(TypeError, match="did you mean 'tunnel_identifier'"):
            validate_options({"tunnel_identifer": "x"})

    def test_refuses_unknown_option_without_lookalike(self) -> None:
        with pytest.raises(TypeError, match="extra_args"):
            validate_options({"completely_made_up": True})

    def test_refuses_unknown_options_when_tunnel_is_created(self) -> None:
        with pytest.raises(TypeError):
            Tunnel(tunnelIdentifier="x")

    @pytest.mark.parametrize("name", ["api_key", "api_secret"])
    def test_refuses_non_string_credentials(self, name: str) -> None:
        with pytest.raises(ValueError, match=f"{name} must be a string"):
            validate_options({name: 123})

    @pytest.mark.parametrize("name", ["api_key", "api_secret"])
    def test_refuses_empty_credentials(self, name: str) -> None:
        with pytest.raises(ValueError, match=f"{name} cannot be empty"):
            validate_options({name: "  "})

    @pytest.mark.parametrize("name", ["tunnel_version", "tunnel_identifier"])
    def test_refuses_non_string(self, name: str) -> None:
        with pytest.raises(ValueError, match=f"{name} must be a string"):
            validate_options({name: 5.0})

    @pytest.mark.parametrize("timeout", [0, -1, "10", True])
    def test_refuses_invalid_timeout(self, timeout: object) -> None:
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            validate_options({"timeout": timeout})

    def test_java_runtime(self) -> None:
        for runtime in ("auto", "system", "bundled"):
            validate_options({"java_runtime": runtime})
        with pytest.raises(ValueError, match='java_runtime must be one of "auto", "system", "bundled"'):
            validate_options({"java_runtime": "docker"})

    def test_shared_must_be_boolean(self) -> None:
        with pytest.raises(ValueError, match="shared must be a boolean"):
            validate_options({"shared": "yes"})

    @pytest.mark.parametrize("connections", [0, 9, 2.5, True])
    def test_ssh_connections_range(self, connections: object) -> None:
        with pytest.raises(ValueError, match="ssh_connections must be a whole number from 1 to 8"):
            validate_options({"ssh_connections": connections})

    def test_lists_must_hold_strings(self) -> None:
        validate_options({"header": ["X-Test: 1", "-Cookie"]})
        with pytest.raises(ValueError, match="header must be a list of strings"):
            validate_options({"header": ["ok", {"no": "dict"}]})

    def test_extra_args_must_be_list_of_strings(self) -> None:
        validate_options({"extra_args": ["--something", "1"]})
        with pytest.raises(ValueError, match="extra_args"):
            validate_options({"extra_args": "--something"})


class TestCreateArgs:
    def test_spells_options_the_way_the_tunnel_does(self) -> None:
        args = create_args(
            {
                "tunnel_identifier": "build-1",
                "se_port": 4446,
                "no_bump": True,
                "no_cache": True,
                "no_proxy": True,
                "fast_fail_regexps": ".*google.*",
                "bind_address": "0.0.0.0",
                "no_bump_domains": "bank.example.com",
                "proxy_testingbot_userpwd": "u:p",
                "ssh_connections": 4,
            }
        )
        assert args == [
            "--tunnel-identifier", "build-1",
            "--se-port", "4446",
            "--nobump",
            "--nocache",
            "--noproxy",
            "--fast-fail-regexps", ".*google.*",
            "--bind-address", "0.0.0.0",
            "--nobump-domains", "bank.example.com",
            "--proxy-testingbot-userpwd", "u:p",
            "--ssh-connections", "4",
        ]  # fmt: skip

    def test_does_not_pass_launcher_options_or_credentials(self) -> None:
        args = create_args(
            {
                "api_key": "k",
                "api_secret": "s",
                "verbose": True,
                "tunnel_version": "5.2",
                "timeout": 5,
                "java_runtime": "auto",
            }
        )
        assert args == []

    def test_skips_unset_false_and_empty_options(self) -> None:
        assert create_args({"no_bump": False, "proxy": None, "logfile": "  ", "shared": True}) == ["--shared"]

    def test_passes_a_list_once_per_value(self) -> None:
        args = create_args({"header": ["X-Test: 1", "", "-Cookie"], "cacert_file": ["/a.pem", "/b.pem"]})
        assert args == [
            "--header",
            "X-Test: 1",
            "--header",
            "-Cookie",
            "--cacert-file",
            "/a.pem",
            "--cacert-file",
            "/b.pem",
        ]

    def test_appends_extra_args_as_they_are(self) -> None:
        assert create_args({"shared": True, "extra_args": ["--new-option", "x"]}) == ["--shared", "--new-option", "x"]


class TestVersions:
    def test_compare(self) -> None:
        assert compare_versions("4.9", "5.0") < 0
        assert compare_versions("5.1", "5.0") > 0
        assert compare_versions("5.0", "5") == 0
        assert compare_versions("5.10", "5.9") > 0
        assert compare_versions("latest", "5.0") is None

    def test_is_version_5_or_up(self) -> None:
        assert is_version_5_or_up("5.0") is True
        assert is_version_5_or_up("6") is True
        assert is_version_5_or_up("4.9") is False
        assert is_version_5_or_up(None) is None
        assert is_version_5_or_up("nightly") is None

    def test_minimum_tunnel_version(self) -> None:
        assert minimum_tunnel_version("ssh-connections") == "5.1"
        assert minimum_tunnel_version("allow-hosts") == "5.0"
        assert minimum_tunnel_version("se-port") is None

    def test_refuses_5_0_options_for_older_tunnel(self) -> None:
        with pytest.raises(ValueError, match="allow_hosts requires TestingBot Tunnel 5.0 or higher, but version 4.9"):
            validate_options_for_version({"allow_hosts": "example.com"}, "4.9")

    def test_refuses_5_1_options_for_5_0(self) -> None:
        with pytest.raises(ValueError, match="ssh_connections requires TestingBot Tunnel 5.1"):
            validate_options_for_version({"ssh_connections": 2}, "5.0")

    def test_accepts_new_options_for_new_or_unknown_versions(self) -> None:
        validate_options_for_version({"allow_hosts": "x", "ssh_connections": 2}, "5.2")
        validate_options_for_version({"allow_hosts": "x"}, None)

    def test_ignores_new_options_that_are_switched_off(self) -> None:
        validate_options_for_version({"dns_round_robin": False, "log_level": None}, "4.9")


class TestRedaction:
    def test_redacts_credentials_and_secret_options(self) -> None:
        secrets = secret_values({"api_key": "KEY", "api_secret": "SECRET", "proxy_userpwd": "user:pw", "logfile": "x"})
        line = "key=KEY secret=SECRET proxy=user:pw logfile=x"
        assert redact(line, secrets) == "key=*** secret=*** proxy=*** logfile=x"

    def test_leaves_output_alone_without_secrets(self) -> None:
        assert redact("nothing to see", secret_values({})) == "nothing to see"
