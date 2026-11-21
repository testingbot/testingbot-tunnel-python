"""Running the tunnel's own checks (``--doctor``, ``--pac-test``) without starting a tunnel."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import _runtime
from ._credentials import resolve_credentials
from ._options import (
    create_args,
    is_version_5_or_up,
    redact,
    secret_values,
    validate_options,
    validate_options_for_version,
)
from ._output import MAX_REMEMBERED_LINES, describe_startup_failure, parse_log_line, parse_log_records
from .errors import CredentialsError, TunnelError
from .tunnel import DEFAULT_TIMEOUT

logger = logging.getLogger("testingbot_tunnel")


@dataclass(frozen=True)
class DoctorCheck:
    #: ``"ok"`` passed, ``"warn"`` needs attention, ``"fail"`` stops the tunnel from working, ``"info"`` is a note
    status: str
    message: str


@dataclass(frozen=True)
class DoctorReport:
    #: whether every check passed
    ok: bool
    checks: List[DoctorCheck] = field(default_factory=list)
    #: everything the tunnel wrote, with credentials redacted
    output: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PacTestResult:
    pac_file: Optional[str]
    url: Optional[str]
    host: Optional[str]
    #: what FindProxyForURL returned, e.g. ``"PROXY proxy:3128; DIRECT"``
    result: str
    #: the way the tunnel would go, e.g. ``"via proxy:3128"`` or ``"direct connection"``
    egress: str
    direct: bool


def parse_doctor_output(lines: Sequence[str]) -> List[DoctorCheck]:
    checks = []
    for record in parse_log_records(lines):
        level, message = record["level"], record["message"]
        if level in ("SEVERE", "ERROR"):
            checks.append(DoctorCheck("fail", message))
        elif level in ("WARNING", "WARN"):
            checks.append(DoctorCheck("warn", message[len("WARN - ") :] if message.startswith("WARN - ") else message))
        elif message.startswith("OK - "):
            checks.append(DoctorCheck("ok", message[len("OK - ") :]))
        else:
            checks.append(DoctorCheck("info", message))
    return checks


def parse_pac_test_output(lines: Sequence[str]) -> Optional[PacTestResult]:
    names = ("PAC file", "URL", "Host", "Result", "Egress")
    fields: Dict[str, str] = {}
    for line in lines:
        # "Result   : PROXY proxy:3128; DIRECT", split on the first colon
        name, separator, value = line.partition(":")
        if separator and name.strip() in names:
            fields[name.strip()] = value.strip()
    if "Result" not in fields or "Egress" not in fields:
        return None
    return PacTestResult(
        pac_file=fields.get("PAC file"),
        url=fields.get("URL"),
        host=fields.get("Host"),
        result=fields["Result"],
        egress=fields["Egress"],
        direct=fields["Egress"] == "direct connection",
    )


def _prepare(options: Dict[str, Any]) -> Tuple[_runtime.Runtime, Dict[str, str], Tuple[str, ...]]:
    validate_options(options)
    env = dict(os.environ)
    key: Optional[str]
    secret: Optional[str]
    try:
        key, secret = resolve_credentials(options.pop("api_key", None), options.pop("api_secret", None))
        env.update(TESTINGBOT_KEY=key, TESTINGBOT_SECRET=secret)
    except CredentialsError:
        key = secret = None
    runtime = _runtime.prepare_runtime(options)
    validate_options_for_version(options, runtime.version)
    return runtime, env, secret_values({**options, "api_key": key, "api_secret": secret})


def _run(
    runtime: _runtime.Runtime,
    args: List[str],
    env: Dict[str, str],
    secrets: Tuple[str, ...],
    options: Mapping[str, Any],
) -> Tuple[int, List[str], List[str]]:
    timeout = float(options.get("timeout") or DEFAULT_TIMEOUT)
    command = [runtime.java, "-jar", runtime.jar, *args]
    if options.get("verbose"):
        logger.info("Running tunnel with options %s", [redact(arg, secrets) for arg in command])
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TunnelError(f"TestingBot Tunnel did not finish within {timeout:g} seconds.") from None
    except OSError as err:
        raise TunnelError(f"Could not start TestingBot Tunnel: {err}") from err

    def lines(output: bytes) -> List[str]:
        return [redact(line.strip(), secrets) for line in output.decode("utf-8", errors="replace").splitlines()]

    return result.returncode, lines(result.stdout), lines(result.stderr)


def doctor(api_key: Optional[str] = None, api_secret: Optional[str] = None, **options: Any) -> DoctorReport:
    """Let the tunnel check its configuration and connection (``--doctor``) without starting it.

    Takes the same options as :class:`~testingbot_tunnel.Tunnel`. Returns the checks, also when
    some fail, and raises :class:`~testingbot_tunnel.TunnelError` when they could not be run.
    """
    options = {**options, "api_key": api_key, "api_secret": api_secret}
    runtime, env, secrets = _prepare(options)
    args = create_args(options)
    # The json log format is read most reliably, tunnels before 5.0 only have text
    if not options.get("log_format") and is_version_5_or_up(runtime.version):
        args += ["--log-format", "json"]
    args.append("--doctor")

    code, stdout, stderr = _run(runtime, args, env, secrets, options)
    output = [line for line in [*stderr, *stdout] if line]
    checks = parse_doctor_output([*stderr, *stdout])
    failed = any(check.status == "fail" for check in checks)
    # Exiting without a failed check means the checks did not get to run, such as for an unknown option
    if code != 0 and not failed:
        messages = [entry for line in output for entry in parse_log_line(line) if entry]
        raise TunnelError(describe_startup_failure(None, code, messages[-MAX_REMEMBERED_LINES:]))
    return DoctorReport(ok=code == 0 and not failed, checks=checks, output=output)


def pac_test(url: str, pac_local: str, pac_local_sha256: Optional[str] = None, **options: Any) -> PacTestResult:
    """Ask the tunnel which way it would send ``url`` with the PAC file ``pac_local`` (``--pac-test``).

    Needs TestingBot Tunnel 5.0 or higher. Raises :class:`~testingbot_tunnel.TunnelError` with the
    reason when the PAC file can not be used.
    """
    if not isinstance(url, str) or url.strip() == "":
        raise ValueError("pac_test needs the URL to test")
    if not isinstance(pac_local, str) or pac_local.strip() == "":
        raise ValueError("pac_test needs pac_local, the PAC file or URL to test")
    unknown = set(options) - {"tunnel_version", "java_runtime", "timeout", "verbose"}
    if unknown:
        raise TypeError(f"pac_test does not take {', '.join(sorted(unknown))}")

    options = {**options, "pac_local": pac_local, "pac_local_sha256": pac_local_sha256}
    runtime, env, secrets = _prepare(options)
    if is_version_5_or_up(runtime.version) is False:
        raise TunnelError(
            f"pac_test requires TestingBot Tunnel 5.0 or higher, but version {runtime.version} is used. "
            'Set tunnel_version to "5.0" or higher.'
        )

    pac_options = {"pac_local": pac_local, "pac_local_sha256": pac_local_sha256}
    code, stdout, stderr = _run(runtime, [*create_args(pac_options), "--pac-test", url], env, secrets, options)
    result = parse_pac_test_output(stdout)
    if code != 0 or result is None:
        reason = "\n".join(line for line in stderr if line)
        raise TunnelError(reason or describe_startup_failure(None, code, stdout[-MAX_REMEMBERED_LINES:]))
    return result
