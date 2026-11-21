"""Downloads over https, following redirects only as long as they stay encrypted."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import socket
import ssl
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 5
DOWNLOAD_TIMEOUT = 60.0
_CHUNK = 1024 * 256


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand redirects back to us, so every hop can be checked before it is followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())


def resolve_redirect(url: str, location: str) -> str:
    """The absolute URL a redirect points to.

    :raises ValueError: when the redirect would take an https download to plain http.
        The download ends up being executed, so it should not travel in the clear.
    """
    target = urljoin(url, location)
    current, redirect = urlsplit(url), urlsplit(target)
    if current.scheme == "https" and redirect.scheme != "https":
        raise ValueError(
            f"Refusing to follow a redirect from {current.scheme}://{current.netloc} to "
            f"{redirect.scheme}://{redirect.netloc}, the download would no longer be encrypted"
        )
    return target


def _open(url: str, method: str, timeout: float):  # type: ignore[no-untyped-def]
    """Open a URL without following redirects. Returns (response, redirect_location)."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise OSError(f"Refusing to download {url}, only http and https are supported")
    headers = {"User-Agent": "testingbot-tunnel-python"}
    request = urllib.request.Request(url, method=method, headers=headers)  # noqa: S310 - scheme checked above
    try:
        return _opener().open(request, timeout=timeout), None
    except urllib.error.HTTPError as err:
        location = err.headers.get("Location") if err.headers else None
        if 300 <= err.code < 400 and location:
            err.close()
            return None, location
        err.close()
        raise OSError(f"Could not download {url}, statusCode: {err.code}") from None


def download(url: str, destination: str, timeout: float = DOWNLOAD_TIMEOUT) -> str:
    """Download ``url`` to ``destination``.

    The file is written to a temporary file next to it and renamed once complete, so an
    interrupted download never ends up at the destination and downloads running next to each
    other do not write over each other. ``timeout`` applies to every read, so a stalled
    download fails instead of waiting forever.

    :raises OSError: when the download fails
    :raises ValueError: when a redirect would drop encryption
    """
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response, location = _open(url, "GET", timeout)
        except socket.timeout:
            raise OSError(f"Timed out after {timeout:g}s while downloading {url}") from None
        if location is not None:
            url = resolve_redirect(url, location)
            continue

        temporary = f"{destination}.{os.getpid()}.{secrets.token_hex(6)}.download"
        try:
            with response, open(temporary, "wb") as file:
                while True:
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    file.write(chunk)
            os.replace(temporary, destination)
        except socket.timeout:
            _remove(temporary)
            raise OSError(f"Timed out after {timeout:g}s while downloading {url}") from None
        except BaseException:
            _remove(temporary)
            raise
        return destination

    raise OSError(f"Too many redirects (max {MAX_REDIRECTS}) for {url}")


def redirect_location(url: str, timeout: float = DOWNLOAD_TIMEOUT) -> Optional[str]:
    """Where a URL redirects to (an absolute URL), without following it. None when it does not redirect."""
    try:
        response, location = _open(url, "HEAD", timeout)
    except socket.timeout:
        raise OSError(f"Timed out after {timeout:g}s while reaching {url}") from None
    if response is not None:
        response.close()
        return None
    return resolve_redirect(url, location)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


_CHECKSUM = re.compile(r"^([a-f0-9]{64})\b", re.IGNORECASE)


def parse_checksum(contents: str) -> Optional[str]:
    """The checksum in a ``.sha256`` file, as written by sha256sum. None when there is none."""
    match = _CHECKSUM.match(str(contents).strip())
    return match.group(1).lower() if match else None


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
