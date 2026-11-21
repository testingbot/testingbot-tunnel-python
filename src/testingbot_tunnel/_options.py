"""The options of TestingBot Tunnel, how they are spelled on its command line and checked."""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

OptionValue = Union[str, int, bool, Sequence[Union[str, int]], None]

# Options handled by the launcher itself, the tunnel does not know about them
LAUNCHER_OPTIONS = frozenset(
    {"api_key", "api_secret", "verbose", "tunnel_version", "timeout", "java_runtime", "extra_args"}
)

JAVA_RUNTIMES = ("auto", "system", "bundled")

# How many SSH connections tunnel 5.1 and up can open to the tunnel server
MAX_SSH_CONNECTIONS = 8

# Every option of the tunnel, by its Python keyword, as spelled on the tunnel's command line.
# Options the launcher manages itself (--readyfile) and commands that make the tunnel do
# something else than run (--doctor, --pac-test, --ready, --help, --version) are left out.
TUNNEL_OPTIONS: Dict[str, str] = {
    "tunnel_identifier": "tunnel-identifier",
    "shared": "shared",
    "se_port": "se-port",
    "localproxy": "localproxy",
    "hubport": "hubport",
    "no_proxy": "noproxy",
    "no_cache": "nocache",
    "no_bump": "nobump",
    "web": "web",
    "fast_fail_regexps": "fast-fail-regexps",
    "dns": "dns",
    "auth": "auth",
    "extra_headers": "extra-headers",
    "pac": "pac",
    "proxy": "proxy",
    "proxy_userpwd": "proxy-userpwd",
    "logfile": "logfile",
    "debug": "debug",
    "metrics_port": "metrics-port",
    "metrics_auth": "metrics-auth",
    # Added in TestingBot Tunnel 5.0
    "config": "config",
    "allow_hosts": "allow-hosts",
    "bind_address": "bind-address",
    "cacert_file": "cacert-file",
    "connect_to": "connect-to",
    "dns_round_robin": "dns-round-robin",
    "dns_timeout": "dns-timeout",
    "header": "header",
    "response_header": "response-header",
    "http_dial_timeout": "http-dial-timeout",
    "http_idle_timeout": "http-idle-timeout",
    "krb5_hosts": "krb5-hosts",
    "krb5_keytab": "krb5-keytab",
    "krb5_principal": "krb5-principal",
    "localhost_policy": "localhost-policy",
    "log_format": "log-format",
    "log_http": "log-http",
    "log_level": "log-level",
    "request_id_header": "request-id-header",
    "no_bump_domains": "nobump-domains",
    "pac_local": "pac-local",
    "pac_local_sha256": "pac-local-sha256",
    "proxy_auth_scheme": "proxy-auth-scheme",
    "proxy_spn": "proxy-spn",
    "proxy_testingbot": "proxy-testingbot",
    "proxy_testingbot_userpwd": "proxy-testingbot-userpwd",
    "ssh_host_key": "ssh-host-key",
    "ssh_host_key_policy": "ssh-host-key-policy",
    "ws_proxy_mode": "ws-proxy-mode",
    # Added in TestingBot Tunnel 5.1
    "ssh_connections": "ssh-connections",
}

# Options the tunnel only knows about from version 5.0 on, as spelled on its command line.
# Older tunnels refuse to start with them.
VERSION_5_OPTIONS = frozenset(
    {
        "allow-hosts", "bind-address", "cacert-file", "config", "connect-to",
        "dns-round-robin", "dns-timeout", "header", "response-header",
        "http-dial-timeout", "http-idle-timeout", "krb5-hosts", "krb5-keytab",
        "krb5-principal", "localhost-policy", "log-format", "log-http", "log-level",
        "request-id-header", "nobump-domains", "pac-local", "pac-local-sha256",
        "proxy-auth-scheme", "proxy-spn", "proxy-testingbot", "proxy-testingbot-userpwd",
        "ssh-host-key", "ssh-host-key-policy", "ws-proxy-mode",
    }
)  # fmt: skip

# Options the tunnel only knows about from version 5.1 on
VERSION_5_1_OPTIONS = frozenset({"ssh-connections"})

# Option values that are credentials, kept out of verbose output
SECRET_OPTIONS = frozenset({"proxy_userpwd", "metrics_auth", "auth", "proxy_testingbot_userpwd"})

_VERSION = re.compile(r"^\s*(\d+(?:\.\d+)*)")


def minimum_tunnel_version(option_name: str) -> Optional[str]:
    """The first tunnel version that knows about an option (as spelled on its command line)."""
    if option_name in VERSION_5_1_OPTIONS:
        return "5.1"
    if option_name in VERSION_5_OPTIONS:
        return "5.0"
    return None


def _parse_version(version: object) -> Optional[List[int]]:
    match = _VERSION.match(str(version)) if version is not None else None
    return [int(part) for part in match.group(1).split(".")] if match else None


def compare_versions(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Below 0 when ``a`` is older than ``b``, above 0 when newer, None when either is not a version."""
    left, right = _parse_version(a), _parse_version(b)
    if left is None or right is None:
        return None
    for i in range(max(len(left), len(right))):
        difference = (left[i] if i < len(left) else 0) - (right[i] if i < len(right) else 0)
        if difference:
            return difference
    return 0


def is_version_5_or_up(tunnel_version: Optional[str]) -> Optional[bool]:
    """Whether a tunnel version is 5.0 or newer, None when the version is not known."""
    parsed = _parse_version(tunnel_version)
    return None if parsed is None else parsed[0] >= 5


def _is_off(value: Any) -> bool:
    return value is None or value is False


def validate_options(options: Mapping[str, Any]) -> None:
    """Check the options passed to :class:`~testingbot_tunnel.Tunnel`.

    :raises TypeError: for an option the tunnel does not know about
    :raises ValueError: for a value the tunnel would refuse
    """
    for name in options:
        if name in LAUNCHER_OPTIONS or name in TUNNEL_OPTIONS:
            continue
        message = f"Unknown TestingBot Tunnel option {name!r}"
        suggestion = difflib.get_close_matches(name, [*TUNNEL_OPTIONS, *LAUNCHER_OPTIONS], n=1)
        if suggestion:
            message += f", did you mean {suggestion[0]!r}?"
        else:
            message += ". Options the launcher does not know yet can be passed with extra_args."
        raise TypeError(message)

    for name in ("api_key", "api_secret"):
        value = options.get(name)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            if value.strip() == "":
                raise ValueError(f"{name} cannot be empty")

    for name in ("tunnel_version", "tunnel_identifier"):
        value = options.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be a string")

    timeout = options.get("timeout")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0):
        raise ValueError("timeout must be a positive number")

    java_runtime = options.get("java_runtime")
    if java_runtime is not None and java_runtime not in JAVA_RUNTIMES:
        raise ValueError("java_runtime must be one of " + ", ".join(f'"{runtime}"' for runtime in JAVA_RUNTIMES))

    shared = options.get("shared")
    if shared is not None and not isinstance(shared, bool):
        raise ValueError("shared must be a boolean")

    ssh_connections = options.get("ssh_connections")
    if ssh_connections is not None and (
        isinstance(ssh_connections, bool)
        or not isinstance(ssh_connections, int)
        or not 1 <= ssh_connections <= MAX_SSH_CONNECTIONS
    ):
        raise ValueError(f"ssh_connections must be a whole number from 1 to {MAX_SSH_CONNECTIONS}")

    extra_args = options.get("extra_args")
    if extra_args is not None and (isinstance(extra_args, str) or not all(isinstance(arg, str) for arg in extra_args)):
        raise ValueError("extra_args must be a list of strings")

    for name, value in options.items():
        if name in LAUNCHER_OPTIONS:
            continue
        if isinstance(value, (list, tuple)):
            if not all(isinstance(entry, (str, int)) and not isinstance(entry, bool) for entry in value):
                raise ValueError(f"{name} must be a list of strings")
        elif not (value is None or isinstance(value, (str, int, float, bool))):
            raise ValueError(f"{name} must be a string, number, boolean or list of strings")


def validate_options_for_version(options: Mapping[str, Any], tunnel_version: Optional[str]) -> None:
    """Refuse options the tunnel version does not know about yet. Nothing is refused for an unknown version."""
    if is_version_5_or_up(tunnel_version) is None:
        return
    for name, value in options.items():
        if name in LAUNCHER_OPTIONS or _is_off(value):
            continue
        minimum = minimum_tunnel_version(TUNNEL_OPTIONS[name])
        comparison = compare_versions(tunnel_version, minimum) if minimum else None
        if minimum and comparison is not None and comparison < 0:
            raise ValueError(
                f"{name} requires TestingBot Tunnel {minimum} or higher, but version {tunnel_version} "
                f'is used. Set tunnel_version to "{minimum}" or higher.'
            )


def create_args(options: Mapping[str, Any]) -> List[str]:
    """The tunnel's command line arguments for the options (credentials are not among them).

    Booleans are passed as a flag without a value, lists pass the option once for every value.
    """
    args: List[str] = []
    for name, value in options.items():
        if name in LAUNCHER_OPTIONS or _is_off(value):
            continue
        flag = "--" + TUNNEL_OPTIONS[name]
        values = value if isinstance(value, (list, tuple)) else [value]
        for entry in values:
            if entry is True:
                args.append(flag)
            elif isinstance(entry, (int, float)) and not isinstance(entry, bool):
                args.extend([flag, str(entry)])
            elif isinstance(entry, str) and entry.strip() != "":
                args.extend([flag, entry])
    args.extend(options.get("extra_args") or [])
    return args


def secret_values(options: Mapping[str, Any]) -> Tuple[str, ...]:
    """Values that must never show up in output: the credentials and secret option values."""
    secrets: List[str] = []
    for name in ("api_key", "api_secret", *SECRET_OPTIONS):
        value = options.get(name)
        for entry in value if isinstance(value, (list, tuple)) else [value]:
            if isinstance(entry, str) and entry.strip():
                secrets.append(entry)
    # Longest first, so a secret that contains another one is replaced whole
    return tuple(sorted(set(secrets), key=len, reverse=True))


def redact(value: str, secrets: Sequence[str]) -> str:
    """Replace every occurrence of the secrets with ``***``."""
    for secret in secrets:
        value = value.replace(secret, "***")
    return value
