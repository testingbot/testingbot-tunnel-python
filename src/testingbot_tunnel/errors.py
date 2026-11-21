"""Exceptions raised by testingbot_tunnel."""

from __future__ import annotations


class TunnelError(Exception):
    """Base class for everything that goes wrong while starting or running the tunnel."""


class CredentialsError(TunnelError):
    """No TestingBot key and secret could be found, or they are not usable."""


class JavaError(TunnelError):
    """Java could not be found, or it is too old for the tunnel version."""


class DownloadError(TunnelError):
    """The tunnel (or the download with Java included) could not be downloaded or verified."""


class TunnelStartError(TunnelError):
    """The tunnel process exited, or reported an error, before it became ready."""


class TunnelTimeoutError(TunnelStartError):
    """The tunnel did not become ready within ``timeout`` seconds."""
