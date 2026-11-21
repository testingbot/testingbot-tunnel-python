"""Download and launch TestingBot Tunnel from Python.

>>> from testingbot_tunnel import Tunnel
>>> with Tunnel(tunnel_identifier="my-build") as tunnel:
...     run_tests()
"""

from __future__ import annotations

from ._credentials import resolve_credentials
from ._options import TUNNEL_OPTIONS
from ._runtime import cache_directory
from .diagnostics import DoctorCheck, DoctorReport, PacTestResult, doctor, pac_test
from .errors import (
    CredentialsError,
    DownloadError,
    JavaError,
    TunnelError,
    TunnelStartError,
    TunnelTimeoutError,
)
from .tunnel import Tunnel, active_tunnels, stop_all

__version__ = "0.1.0"

__all__ = [
    "TUNNEL_OPTIONS",
    "CredentialsError",
    "DoctorCheck",
    "DoctorReport",
    "DownloadError",
    "JavaError",
    "PacTestResult",
    "Tunnel",
    "TunnelError",
    "TunnelStartError",
    "TunnelTimeoutError",
    "__version__",
    "active_tunnels",
    "cache_directory",
    "doctor",
    "pac_test",
    "resolve_credentials",
    "stop_all",
]
