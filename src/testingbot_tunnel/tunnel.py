"""The :class:`Tunnel`: download, start and stop TestingBot Tunnel."""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from types import TracebackType
from typing import IO, Any, Deque, Dict, List, Optional, Set, Tuple, Type

from . import _runtime
from ._credentials import resolve_credentials
from ._options import create_args, redact, secret_values, validate_options, validate_options_for_version
from ._output import MAX_REMEMBERED_LINES, classify_tunnel_error, describe_startup_failure, parse_log_line
from .errors import TunnelError, TunnelStartError, TunnelTimeoutError

logger = logging.getLogger("testingbot_tunnel")

DEFAULT_TIMEOUT = 90.0
STOP_TIMEOUT = 10.0
_POLL_INTERVAL = 0.2

# Every tunnel that has been started and not stopped yet
_active: Set[Tunnel] = set()
_active_lock = threading.Lock()
_exit_handler_registered = False
_verbose_handler: Optional[logging.Handler] = None


def _show_verbose_output() -> None:
    """Make verbose output visible when the application has not configured logging itself."""
    global _verbose_handler
    if _verbose_handler is not None or logger.handlers or logging.getLogger().handlers:
        return
    _verbose_handler = logging.StreamHandler(sys.stderr)
    _verbose_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_verbose_handler)
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)


class Tunnel:
    """TestingBot Tunnel, downloaded when needed and started as a Java process.

    >>> with Tunnel(tunnel_identifier="my-build") as tunnel:
    ...     run_tests()

    :param api_key: TestingBot key. Falls back to ``TB_KEY``, ``TESTINGBOT_KEY`` and ``~/.testingbot``.
    :param api_secret: TestingBot secret, found the same way as the key.
    :param options: options of the tunnel in snake_case (``tunnel_identifier``, ``se_port``,
        ``no_bump``, ...) and of the launcher: ``verbose``, ``tunnel_version``, ``timeout``
        (seconds to wait for the tunnel to become ready, default 90), ``java_runtime``
        (``"auto"``, ``"system"`` or ``"bundled"``) and ``extra_args`` (arguments passed to the
        tunnel as they are). See the README for the full list.
    :raises TypeError: for an option the tunnel does not know about
    :raises ValueError: for an option value the tunnel would refuse
    """

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, **options: Any) -> None:
        if api_key is not None:
            options["api_key"] = api_key
        if api_secret is not None:
            options["api_secret"] = api_secret
        validate_options(options)
        self._options: Dict[str, Any] = options
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._readers: List[threading.Thread] = []
        self._ready_dir: Optional[str] = None
        self._ready = False
        self._error: Optional[str] = None
        self._closing = False
        self._recent: Deque[str] = deque(maxlen=MAX_REMEMBERED_LINES)
        self._secrets: Tuple[str, ...] = ()
        self._lock = threading.Lock()
        self.runtime: Optional[_runtime.Runtime] = None

    # Information ----------------------------------------------------------------------------

    @property
    def options(self) -> Dict[str, Any]:
        """The options the tunnel was created with, without the credentials."""
        return {name: value for name, value in self._options.items() if name not in ("api_key", "api_secret")}

    @property
    def tunnel_identifier(self) -> Optional[str]:
        """The identifier to put in the ``tunnel-identifier`` capability, None when not set."""
        return self._options.get("tunnel_identifier")

    @property
    def version(self) -> Optional[str]:
        """The version of the tunnel that runs, once started. None when it could not be told."""
        return self.runtime.version if self.runtime else None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    @property
    def process(self) -> Optional[subprocess.Popen[bytes]]:
        """The Java process of the tunnel."""
        return self._process

    @property
    def readyfile(self) -> Optional[str]:
        """The file the tunnel touches once it is ready, in a directory of its own."""
        return os.path.join(self._ready_dir, "testingbot.ready") if self._ready_dir else None

    def is_running(self) -> bool:
        """Whether the tunnel became ready and its process is still running."""
        return self._ready and self._process is not None and self._process.poll() is None

    def __repr__(self) -> str:
        state = "running" if self.is_running() else "stopped"
        return f"<Tunnel {state} identifier={self.tunnel_identifier!r} pid={self.pid}>"

    # Starting -------------------------------------------------------------------------------

    def start(self) -> Tunnel:
        """Download the tunnel when needed, start it and wait until it is ready.

        :returns: the tunnel itself
        :raises CredentialsError: when no key and secret can be found
        :raises JavaError: when no suitable Java is available
        :raises DownloadError: when the tunnel can not be downloaded or verified
        :raises TunnelStartError: when the tunnel exits or reports an error before it is ready
        :raises TunnelTimeoutError: when it is not ready within ``timeout`` seconds
        """
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise TunnelError("This tunnel is already started")
            self._reset()

        options = dict(self._options)
        api_key, api_secret = resolve_credentials(options.pop("api_key", None), options.pop("api_secret", None))
        verbose = bool(options.get("verbose"))
        if verbose:
            _show_verbose_output()
        self._secrets = secret_values({**options, "api_key": api_key, "api_secret": api_secret})

        runtime = _runtime.prepare_runtime(options)
        validate_options_for_version(options, runtime.version)
        self.runtime = runtime

        self._ready_dir = tempfile.mkdtemp(prefix="testingbot-tunnel-")
        readyfile = self.readyfile
        assert readyfile is not None
        args = [runtime.java, "-jar", runtime.jar, *create_args(options), "-f", readyfile]
        if verbose:
            logger.info("Starting tunnel with options %s", [redact(arg, self._secrets) for arg in args])

        # The credentials go through the environment, so they do not show up in the process list
        env = dict(os.environ, TESTINGBOT_KEY=api_key, TESTINGBOT_SECRET=api_secret)
        try:
            self._process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
            )
        except OSError as err:
            self._remove_ready_dir()
            raise TunnelStartError(f"Could not start TestingBot Tunnel: {err}") from err

        _register(self)
        for stream, is_stderr in ((self._process.stdout, False), (self._process.stderr, True)):
            assert stream is not None
            reader = threading.Thread(
                target=self._read, args=(stream, is_stderr, verbose), name="testingbot-tunnel-output", daemon=True
            )
            reader.start()
            self._readers.append(reader)

        try:
            self._wait_until_ready(readyfile, float(options.get("timeout") or DEFAULT_TIMEOUT))
        except BaseException:
            self.stop()
            raise

        logger.info("Tunnel is ready")
        return self

    def _reset(self) -> None:
        self._process = None
        self._readers = []
        self._ready = False
        self._error = None
        self._closing = False
        self._recent.clear()

    def _wait_until_ready(self, readyfile: str, timeout: float) -> None:
        process = self._process
        assert process is not None
        deadline = time.monotonic() + timeout
        while True:
            if os.path.exists(readyfile) and process.poll() is None and self._error is None:
                self._ready = True
                return
            code = process.poll()
            if code is not None:
                self._join_readers()
                raise TunnelStartError(describe_startup_failure(self._error, code, list(self._recent)))
            if time.monotonic() >= deadline:
                message = f"Tunnel failed to launch in {timeout:g} seconds."
                if self._recent:
                    message += "\n" + "\n".join(self._recent)
                raise TunnelTimeoutError(message)
            time.sleep(_POLL_INTERVAL)

    def _read(self, stream: IO[bytes], is_stderr: bool, verbose: bool) -> None:
        try:
            for raw in iter(stream.readline, b""):
                for line in parse_log_line(raw.decode("utf-8", errors="replace").strip()):
                    self._handle_line(redact(line, self._secrets), is_stderr, verbose)
        except (OSError, ValueError):
            pass  # The stream was closed while the tunnel stopped
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _handle_line(self, line: str, is_stderr: bool, verbose: bool) -> None:
        if line == "":
            return
        self._recent.append(line)
        if verbose:
            logger.info(line)
        if "is available for download" in line:
            logger.warning(line)
        if not is_stderr:
            return
        # Once the tunnel is up, a failed API call (for example while it reconnects)
        # is something the tunnel recovers from, not a reason to close it
        error = None if self._ready else classify_tunnel_error(line)
        if error:
            self._error = error
            self._signal_stop()

    # Stopping -------------------------------------------------------------------------------

    def _signal_stop(self) -> None:
        """Ask the tunnel to stop, letting it remove itself from TestingBot."""
        process = self._process
        if process is None or process.poll() is not None or self._closing:
            return
        self._closing = True
        try:
            if os.name == "nt":
                process.terminate()
            else:
                process.send_signal(signal.SIGINT)
        except OSError:
            pass  # Already gone

    def stop(self, timeout: float = STOP_TIMEOUT) -> None:
        """Stop the tunnel and wait until its process has exited.

        A tunnel that does not stop within ``timeout`` seconds is killed. Safe to call more than once.
        """
        process = self._process
        if process is not None:
            if process.poll() is None:
                if self._options.get("verbose"):
                    logger.info("Closing TestingBot Tunnel")
                self._signal_stop()
                try:
                    process.wait(timeout)
                except subprocess.TimeoutExpired:
                    logger.warning("TestingBot Tunnel did not stop within %g seconds, killing it", timeout)
                    process.kill()
                    process.wait()
            self._join_readers()
        self._ready = False
        self._remove_ready_dir()
        _unregister(self)

    close = stop

    def _join_readers(self) -> None:
        for reader in self._readers:
            reader.join(timeout=2)

    def _remove_ready_dir(self) -> None:
        if self._ready_dir:
            shutil.rmtree(self._ready_dir, ignore_errors=True)

    # Context manager ------------------------------------------------------------------------

    def __enter__(self) -> Tunnel:
        if not self.is_running():
            self.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.stop()


def _register(tunnel: Tunnel) -> None:
    global _exit_handler_registered
    with _active_lock:
        _active.add(tunnel)
        if not _exit_handler_registered:
            _exit_handler_registered = True
            atexit.register(stop_all)


def _unregister(tunnel: Tunnel) -> None:
    with _active_lock:
        _active.discard(tunnel)


def active_tunnels() -> List[Tunnel]:
    """Every tunnel this process started that has not been stopped."""
    with _active_lock:
        return list(_active)


def stop_all(timeout: float = STOP_TIMEOUT) -> None:
    """Stop every tunnel this process started. Runs on interpreter exit as well.

    All tunnels are asked to stop at once and given ``timeout`` seconds together.
    """
    tunnels = active_tunnels()
    for tunnel in tunnels:
        tunnel._signal_stop()
    deadline = time.monotonic() + timeout
    for tunnel in tunnels:
        tunnel.stop(timeout=max(0.0, deadline - time.monotonic()))
