from __future__ import annotations

import http.server
import io
import os
import tarfile
import threading
from pathlib import Path
from typing import Callable, Dict, Iterator, Tuple

import pytest

from testingbot_tunnel import _runtime, tunnel

# A stand-in for java, so the tests can make the tunnel behave in ways the real one only does
# on a bad day. It understands what the launcher asks of java:
#   java -version                    reports FAKE_JAVA_RUNTIME (default 17)
#   java -jar tunnel.jar -h          exits 0, or FAKE_JAVA_VALID when set
#   java -jar tunnel.jar --version   reports FAKE_JAVA_TUNNEL (default 5.2)
#   java -jar tunnel.jar ... -f F    behaves as FAKE_JAVA says:
#     (unset)    keeps running without ever becoming ready
#     ready      touches the readyfile, reports a failed API call a second later and keeps running
#     unauthorized / minutes / limit / http-error  writes that error and waits to be stopped
#     crash      writes a line and exits with code 3
#     stubborn   touches the readyfile and ignores SIGINT
# The arguments are appended to FAKE_JAVA_LOG and the credentials it got to FAKE_JAVA_ENV_LOG.
FAKE_JAVA = r"""#!/bin/sh
[ -n "$FAKE_JAVA_LOG" ] && echo "$*" >> "$FAKE_JAVA_LOG"
if [ "$1" = "-version" ]; then
  echo "openjdk version \"${FAKE_JAVA_RUNTIME:-17}.0.1\" 2024-10-15" >&2
  exit 0
fi
for arg in "$@"; do
  [ "$arg" = "-h" ] && exit "${FAKE_JAVA_VALID:-0}"
  [ "$arg" = "--version" ] && echo "Version: testingbot-tunnel.jar ${FAKE_JAVA_TUNNEL:-5.2}" && exit 0
  if [ "$arg" = "--doctor" ]; then
    echo '{"level":"INFO","message":"OK - Proxy port 8087 can be opened"}' >&2
    if [ "$FAKE_JAVA" = "port-in-use" ]; then
      echo '{"level":"ERROR","message":"Port 4445 is in use"}' >&2; exit 1
    fi
    [ "$FAKE_JAVA" = "crash" ] && echo "Unknown option: --bogus" >&2 && exit 2
    exit 0
  fi
  if [ "$arg" = "--pac-test" ]; then
    [ "$FAKE_JAVA" = "bad-pac" ] && echo "The PAC file does not match --pac-local-sha256" >&2 && exit 1
    echo "Result   : PROXY proxy.example.com:3128; DIRECT"
    echo "Egress   : via proxy.example.com:3128"
    exit 0
  fi
done
[ -n "$FAKE_JAVA_ENV_LOG" ] && echo "$TESTINGBOT_KEY:$TESTINGBOT_SECRET" >> "$FAKE_JAVA_ENV_LOG"
READY=""
while [ $# -gt 0 ]; do [ "$1" = "-f" ] && READY="$2"; shift; done
trap "exit 0" INT TERM
case "$FAKE_JAVA" in
  ready)
    echo "Tunnel is starting with key $TESTINGBOT_KEY"
    touch "$READY"
    sleep 1
    echo "Failed : HTTP error code : 503" >&2
    ;;
  unauthorized) echo 'Failed : HTTP error code : 401 - {"error":"401 Unauthorized."}' >&2 ;;
  minutes) echo "An error ocurred: You have no minutes left" >&2 ;;
  limit) echo "An error ocurred: You already have 2 tunnels active - please close another tunnel first" >&2 ;;
  http-error) echo 'Failed : HTTP error code : 403 - {"error":"Your account is suspended"}' >&2 ;;
  java-too-old) echo "TestingBot Tunnel requires Java 17 or higher" >&2; exit 1 ;;
  crash) echo "Unknown option: --bogus" >&2; exit 3 ;;
  stubborn) trap "" INT TERM; touch "$READY" ;;
esac
while true; do sleep 0.1; done
"""


def write_fake_java(directory: Path, name: str = "java") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    location = directory / name
    location.write_text(FAKE_JAVA)
    location.chmod(0o755)
    return location


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Keep every test away from the real home directory, cache, credentials and TestingBot."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("TESTINGBOT_TUNNEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TESTINGBOT_TUNNEL_RELEASES_URL", "http://127.0.0.1:9/unreachable")
    monkeypatch.setattr(_runtime, "TUNNEL_DOWNLOAD_URL", "http://127.0.0.1:9/unreachable")
    for variable in ("TB_KEY", "TB_SECRET", "TESTINGBOT_KEY", "TESTINGBOT_SECRET"):
        monkeypatch.delenv(variable, raising=False)
    yield home
    tunnel.stop_all(timeout=5)


class FakeJava:
    def __init__(self, directory: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.path = write_fake_java(directory)
        self.log = tmp_path / "java-args.log"
        self.env_log = tmp_path / "java-env.log"
        self._monkeypatch = monkeypatch
        monkeypatch.setenv("FAKE_JAVA_LOG", str(self.log))
        monkeypatch.setenv("FAKE_JAVA_ENV_LOG", str(self.env_log))

    def behave(self, mode: str) -> None:
        self._monkeypatch.setenv("FAKE_JAVA", mode)

    def set(self, name: str, value: str) -> None:
        self._monkeypatch.setenv(name, value)

    def calls(self) -> list:
        return self.log.read_text().splitlines() if self.log.exists() else []


@pytest.fixture
def fake_java(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeJava:
    if os.name == "nt":
        pytest.skip("the fake java is a shell script")
    directory = tmp_path / "fake-java-bin"
    java = FakeJava(directory, tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    return java


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> Tuple[str, str]:
    monkeypatch.setenv("TB_KEY", "the-key-123")
    monkeypatch.setenv("TB_SECRET", "the-secret-456")
    return "the-key-123", "the-secret-456"


@pytest.fixture
def cached_jar(tmp_path: Path) -> Path:
    """A jar already in the cache, so no download is needed."""
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    jar = cache / "testingbot-tunnel.jar"
    jar.write_bytes(b"PK fake jar")
    return jar


Route = Callable[[http.server.BaseHTTPRequestHandler], None]


class Server:
    """A local web server, answering every path from the routes it is given."""

    def __init__(self) -> None:
        self.routes: Dict[str, Route] = {}
        self.requests: list = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _handle(self) -> None:
                server.requests.append((self.command, self.path))
                route = server.routes.get(self.path)
                if route is None:
                    self.send_error(404)
                    return
                route(self)

            do_GET = _handle
            do_HEAD = _handle

            def log_message(self, *args: object) -> None:
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def file(self, path: str, body: bytes) -> None:
        def route(handler: http.server.BaseHTTPRequestHandler) -> None:
            handler.send_response(200)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            if handler.command == "GET":
                handler.wfile.write(body)

        self.routes[path] = route

    def redirect(self, path: str, location: str, code: int = 302) -> None:
        def route(handler: http.server.BaseHTTPRequestHandler) -> None:
            handler.send_response(code)
            handler.send_header("Location", location)
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        self.routes[path] = route

    def stall(self, path: str, seconds: float) -> None:
        def route(handler: http.server.BaseHTTPRequestHandler) -> None:
            handler.send_response(200)
            handler.send_header("Content-Length", "1000")
            handler.end_headers()
            handler.wfile.write(b"x" * 10)
            handler.wfile.flush()
            threading.Event().wait(seconds)

        self.routes[path] = route

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server() -> Iterator[Server]:
    server = Server()
    yield server
    server.close()


def make_bundle(platform_name: str, java_script: str = FAKE_JAVA) -> bytes:
    """A download with Java included, holding the fake java and a jar."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        root = f"testingbot-tunnel-{platform_name}"
        for name, data, mode in (
            (f"{root}/runtime/bin/java", java_script.encode(), 0o755),
            (f"{root}/lib/testingbot-tunnel.jar", b"PK bundled jar", 0o644),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()
