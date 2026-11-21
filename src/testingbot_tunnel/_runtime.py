"""Finding the tunnel jar and the Java to run it with: system Java, or the download with Java included."""

from __future__ import annotations

import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional

from . import _download
from ._options import is_version_5_or_up
from ._output import JAVA_REQUIREMENT
from .errors import DownloadError, JavaError

logger = logging.getLogger("testingbot_tunnel")

MIN_JAVA_VERSION = 11
# TestingBot Tunnel 5.0 and up are built for Java 17
MIN_JAVA_VERSION_5 = 17

# Where the tunnel jar is downloaded from
TUNNEL_DOWNLOAD_URL = "https://testingbot.com/tunnel"

# Where TestingBot Tunnel 5.0 and up are published with a Java runtime included.
# Can be pointed at a mirror with the TESTINGBOT_TUNNEL_RELEASES_URL environment variable.
RELEASES_URL = "https://github.com/testingbot/Testingbot-Tunnel/releases"

# The platforms there is a download with Java included for
BUNDLED_PLATFORMS = {
    ("darwin", "x64"): "macos-x64",
    ("darwin", "arm64"): "macos-arm64",
    ("linux", "x64"): "linux-x64",
    ("linux", "arm64"): "linux-arm64",
    ("win32", "x64"): "windows-x64",
}

_ARCHITECTURES = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}

_PROBE_TIMEOUT = 60


@dataclass(frozen=True)
class Runtime:
    """The jar to run and the java to run it with."""

    java: str
    jar: str
    version: Optional[str]
    bundled: bool = False


def _platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _arch() -> str:
    machine = platform.machine().lower()
    return _ARCHITECTURES.get(machine, machine)


def bundled_platform(system: Optional[str] = None, arch: Optional[str] = None) -> Optional[str]:
    """The name TestingBot gives a platform in its downloads with Java included, e.g. ``macos-arm64``."""
    return BUNDLED_PLATFORMS.get((system or _platform(), arch or _arch()))


def bundled_archive_name(platform_name: str) -> str:
    extension = "zip" if platform_name.startswith("windows") else "tar.gz"
    return f"testingbot-tunnel-{platform_name}.{extension}"


def bundled_java_path(directory: Path) -> Path:
    return directory / "runtime" / "bin" / ("java.exe" if _platform() == "win32" else "java")


def bundled_jar_path(directory: Path) -> Path:
    return directory / "lib" / "testingbot-tunnel.jar"


def is_bundle_complete(directory: Path) -> bool:
    return bundled_java_path(directory).exists() and bundled_jar_path(directory).exists()


def cache_directory() -> Path:
    """Where the tunnel is kept. ``TESTINGBOT_TUNNEL_CACHE_DIR`` overrides it.

    The same directory the Node launcher uses, so both share their downloads.
    """
    override = os.environ.get("TESTINGBOT_TUNNEL_CACHE_DIR")
    if override:
        return Path(override)
    home = Path.home()
    system = _platform()
    if system == "darwin":
        base = home / "Library" / "Caches"
    elif system == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return base / "testingbot-tunnel-launcher"


def bundles_directory() -> Path:
    return cache_directory() / "bundles"


def releases_url() -> str:
    return (os.environ.get("TESTINGBOT_TUNNEL_RELEASES_URL") or RELEASES_URL).rstrip("/")


def _writable_directory(directory: Path) -> Path:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if not os.access(directory, os.W_OK):
        raise DownloadError(
            f"Could not write the tunnel to {directory}. "
            "Set TESTINGBOT_TUNNEL_CACHE_DIR to a directory that can be written to."
        )
    return directory


# Java ------------------------------------------------------------------------------------------

_JAVA_VERSION = re.compile(r'version "(\d+)(?:\.(\d+))?')


def parse_java_version(output: str) -> Optional[int]:
    """The major version in the output of ``java -version``. ``1.8`` is read as 8."""
    match = _JAVA_VERSION.search(output)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2):
        return int(match.group(2))
    return major


def required_java_version(tunnel_version: Optional[str]) -> int:
    return MIN_JAVA_VERSION_5 if is_version_5_or_up(tunnel_version) else MIN_JAVA_VERSION


def _run(args: List[str], **kwargs: Any) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    return subprocess.run(args, timeout=_PROBE_TIMEOUT, stdin=subprocess.DEVNULL, **kwargs)


def is_java_installed(java: str = "java") -> bool:
    return shutil.which(java) is not None


def check_java(min_version: int = MIN_JAVA_VERSION, java: str = "java") -> Optional[int]:
    """The major version of the installed Java.

    :raises JavaError: when Java is not installed or older than ``min_version``.
        A version that can not be read is only warned about.
    """
    try:
        result = _run([java, "-version"], capture_output=True, text=True, errors="replace")
    except (OSError, subprocess.SubprocessError) as err:
        raise JavaError(
            f"Java might not be installed or not in $PATH. Java is necessary to use testingbot-tunnel {err}"
        ) from err
    version = parse_java_version(result.stderr + result.stdout)
    if version is None:
        logger.warning(
            "Could not determine Java version. Please ensure Java %s or higher is installed for testingbot-tunnel.",
            min_version,
        )
        return None
    if version < min_version:
        raise JavaError(
            f"Java {version} is installed, but Java {min_version} or higher is required for testingbot-tunnel."
        )
    return version


def is_jar_valid(jar: str, java: str = "java") -> bool:
    """Whether a cached jar can be run.

    Only the exit code counts: the JVM writes messages such as "Picked up JAVA_TOOL_OPTIONS" to
    stderr for a perfectly valid jar. A tunnel that refuses to run on the installed Java is not
    corrupt either, downloading it again would not help.
    """
    try:
        result = _run(
            [java, "-jar", jar, "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace"
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 or bool(JAVA_REQUIREMENT.search(result.stderr))


_JAR_VERSION = re.compile(r"Version: \S+ (\d+(?:\.\d+)*)")


def read_jar_version(jar: str, java: str = "java") -> Optional[str]:
    """Ask a jar which version of the tunnel it is, e.g. ``"5.1"``. None when that can not be told."""
    try:
        result = _run(
            [java, "-jar", jar, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _JAR_VERSION.search(result.stdout)
    return match.group(1) if match else None


# The jar ---------------------------------------------------------------------------------------


def download_jar(tunnel_version: Optional[str] = None) -> str:
    """Download the tunnel jar into the cache directory, unless a working copy is there already.

    :returns: the location of the jar
    """
    jar_name = f"testingbot-tunnel-{tunnel_version}.jar" if tunnel_version else "testingbot-tunnel.jar"
    location = cache_directory() / jar_name

    if location.exists():
        if is_jar_valid(str(location)):
            return str(location)
        logger.info("Found a cached %s file in %s, but it might be corrupt. Redownloading.", jar_name, location.parent)

    _writable_directory(location.parent)
    url = f"{TUNNEL_DOWNLOAD_URL}/{jar_name}"
    logger.info("Downloading %s", url)
    try:
        _download.download(url, str(location))
    except (OSError, ValueError) as err:
        raise DownloadError(
            f"Could not download the tunnel from TestingBot - please check your connection. {err}"
        ) from err
    return str(location)


# The download with Java included ---------------------------------------------------------------


def latest_release_version() -> str:
    """The newest version of the tunnel that has been published, e.g. ``"5.2"``."""
    url = f"{releases_url()}/latest"
    error: Optional[Exception] = None
    location: Optional[str] = None
    try:
        location = _download.redirect_location(url, timeout=15)
    except (OSError, ValueError) as err:
        error = err
    match = re.search(r"/tag/v?(\d+(?:\.\d+)*)/?$", location or "")
    if error is not None or not match:
        raise DownloadError(f"Could not find the latest version of TestingBot Tunnel at {url}. {error or ''}".strip())
    return match.group(1)


def _version_key(version: str) -> List[int]:
    return [int(part) for part in version.split(".")]


def newest_cached_bundle(platform_name: str) -> Optional[str]:
    """The newest download with Java included that is already unpacked for a platform."""
    root = bundles_directory()
    try:
        entries = os.listdir(root)
    except OSError:
        return None
    suffix = f"-{platform_name}"
    versions = [
        entry[: -len(suffix)] for entry in entries if entry.endswith(suffix) and is_bundle_complete(root / entry)
    ]
    versions = [version for version in versions if re.fullmatch(r"\d+(\.\d+)*", version)]
    return max(versions, key=_version_key) if versions else None


def _safe_extract_tar(archive: Path, directory: Path) -> None:
    with tarfile.open(archive) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(directory, filter="data")
            return
        # Pythons without extraction filters: refuse members that would land outside the directory
        root = directory.resolve()
        for member in tar.getmembers():
            target = (directory / member.name).resolve()
            if root not in target.parents and target != root:
                raise DownloadError(f"{archive.name} holds {member.name}, which is outside the archive")
            if (member.issym() or member.islnk()) and root not in (target.parent / member.linkname).resolve().parents:
                raise DownloadError(f"{archive.name} holds a link {member.name} pointing outside the archive")
            if member.isdev():
                raise DownloadError(f"{archive.name} holds a device file {member.name}")
        tar.extractall(directory)  # noqa: S202 - members checked above


def _safe_extract_zip(archive: Path, directory: Path) -> None:
    root = directory.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for name in zipped.namelist():
            target = (directory / name).resolve()
            if root not in target.parents and target != root:
                raise DownloadError(f"{archive.name} holds {name}, which is outside the archive")
        zipped.extractall(directory)  # noqa: S202 - members checked above


def extract_archive(archive: Path, directory: Path) -> None:
    try:
        if archive.name.endswith(".zip"):
            _safe_extract_zip(archive, directory)
        else:
            _safe_extract_tar(archive, directory)
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as err:
        raise DownloadError(f"Could not unpack {archive.name}: {err}") from err


def download_bundled(tunnel_version: Optional[str] = None) -> Runtime:
    """Download and unpack TestingBot Tunnel with Java included (5.0 and up), which needs no Java installed.

    Every download is checked against the checksum published next to it. Downloads the latest
    version unless ``tunnel_version`` is given.
    """
    platform_name = bundled_platform()
    if platform_name is None:
        raise JavaError(
            f"There is no TestingBot Tunnel download with Java included for {_platform()} {_arch()}. "
            f"Install Java {MIN_JAVA_VERSION_5} or higher instead."
        )
    if tunnel_version and is_version_5_or_up(tunnel_version) is False:
        raise JavaError(
            f"TestingBot Tunnel {tunnel_version} has no download with Java included, those exist for 5.0 and up. "
            f'Install Java {MIN_JAVA_VERSION} or higher, or set tunnel_version to "5.0" or higher.'
        )

    version = tunnel_version
    if not version:
        try:
            version = latest_release_version()
        except DownloadError:
            # Without a connection, a version that was downloaded before is still good to use
            version = newest_cached_bundle(platform_name)
            if not version:
                raise

    root = bundles_directory()
    directory = root / f"{version}-{platform_name}"

    def result() -> Runtime:
        return Runtime(
            java=str(bundled_java_path(directory)), jar=str(bundled_jar_path(directory)), version=version, bundled=True
        )

    if is_bundle_complete(directory):
        return result()

    _writable_directory(root)
    archive_name = bundled_archive_name(platform_name)
    url = f"{releases_url()}/download/v{version}/{archive_name}"
    # Unique names, so launchers unpacking next to each other do not get in each other's way
    unique = f"{os.getpid()}.{secrets.token_hex(6)}"
    archive = root / f"{unique}.{archive_name}"
    checksum_file = Path(f"{archive}.sha256")
    extract_directory = root / f"{unique}.unpacking"

    logger.info("Downloading TestingBot Tunnel %s with Java included for %s", version, platform_name)
    try:
        try:
            _download.download(url, str(archive))
            _download.download(f"{url}.sha256", str(checksum_file))
        except (OSError, ValueError) as err:
            raise DownloadError(
                f"Could not download TestingBot Tunnel {version} with Java included from {url} - "
                f"please check your connection. {err}"
            ) from err

        expected = _download.parse_checksum(checksum_file.read_text(encoding="utf-8", errors="replace"))
        if not expected or expected != _download.sha256_file(str(archive)):
            raise DownloadError(f"The download of {url} does not match its published checksum, it was not used.")

        extract_directory.mkdir()
        extract_archive(archive, extract_directory)

        # The archives hold a single directory, such as testingbot-tunnel-macos-arm64/
        unpacked = extract_directory
        if not is_bundle_complete(unpacked):
            unpacked = next(
                (entry for entry in extract_directory.iterdir() if is_bundle_complete(entry)), extract_directory
            )
        if not is_bundle_complete(unpacked):
            raise DownloadError(f"The download of {url} does not hold the tunnel and Java where they were expected.")

        try:
            os.rename(unpacked, directory)
        except OSError:
            # Another launcher was first, its copy is just as good
            if not is_bundle_complete(directory):
                raise
    finally:
        for entry in (archive, checksum_file):
            try:
                entry.unlink()
            except OSError:
                pass
        shutil.rmtree(extract_directory, ignore_errors=True)

    return result()


def can_use_bundled_java(tunnel_version: Optional[str]) -> bool:
    return bundled_platform() is not None and is_version_5_or_up(tunnel_version) is not False


def prepare_runtime(options: Mapping[str, Any]) -> Runtime:
    """Find the jar to run and the java to run it with.

    With ``java_runtime="auto"`` the installed Java is used when it is recent enough for the
    tunnel, and the download with Java included otherwise.
    """
    mode = options.get("java_runtime") or "auto"
    tunnel_version: Optional[str] = options.get("tunnel_version")

    if mode == "bundled":
        return download_bundled(tunnel_version)

    if not is_java_installed():
        if mode == "auto" and can_use_bundled_java(tunnel_version):
            logger.info("Java is not installed, using the TestingBot Tunnel download with Java included.")
            return download_bundled(tunnel_version)
        # Raises with the reason, before a jar is downloaded that can not be run
        check_java(required_java_version(tunnel_version))

    jar = download_jar(tunnel_version)
    if not os.path.exists(jar):
        raise DownloadError(f"Tunnel jar file is not present in {jar}")

    # Without a tunnel_version the latest tunnel is downloaded, ask it which version that is
    version = tunnel_version or read_jar_version(jar)

    try:
        check_java(required_java_version(version))
    except JavaError as err:
        if mode != "auto" or not can_use_bundled_java(version):
            raise
        logger.info("%s Using the TestingBot Tunnel download with Java included instead.", err)
        return download_bundled(tunnel_version)

    return Runtime(java="java", jar=jar, version=version)
