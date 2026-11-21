"""End to end: a real tunnel, a local web server and a Selenium session on TestingBot."""

from __future__ import annotations

import http.server
import os
import subprocess
import threading
import uuid
from typing import Iterator

import pytest

from testingbot_tunnel import Tunnel, resolve_credentials

HUB = "https://hub.testingbot.com/wd/hub"


@pytest.fixture
def local_site() -> Iterator[tuple]:
    """A page only this machine serves, with a title nobody else could guess."""
    title = f"testingbot-tunnel-python {uuid.uuid4().hex[:12]}"
    page = f"<!doctype html><html><head><title>{title}</title></head><body>hello</body></html>".encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://localhost:{server.server_address[1]}/", title
    finally:
        server.shutdown()
        server.server_close()


def assert_process_gone(tunnel: Tunnel) -> None:
    process = tunnel.process
    assert process is not None
    assert process.poll() is not None, "the tunnel process is still running"
    with pytest.raises(ProcessLookupError):
        os.kill(process.pid, 0)
    if os.name != "nt":
        listing = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
        assert tunnel.readyfile is not None
        assert os.path.dirname(tunnel.readyfile) not in listing, "a tunnel process is left behind"
        assert not os.path.exists(os.path.dirname(tunnel.readyfile))


def test_selenium_session_through_the_tunnel(local_site: tuple) -> None:
    webdriver = pytest.importorskip("selenium.webdriver")
    url, title = local_site
    key, secret = resolve_credentials()
    identifier = f"python-live-{uuid.uuid4().hex[:8]}"

    tunnel = Tunnel(tunnel_identifier=identifier, timeout=120)
    with tunnel:
        assert tunnel.is_running()
        options = webdriver.ChromeOptions()
        options.browser_version = "latest"
        options.platform_name = "WIN11"
        options.set_capability(
            "tb:options",
            {
                "key": key,
                "secret": secret,
                "name": "testingbot-tunnel-python live test",
                "tunnel-identifier": identifier,
            },
        )
        driver = webdriver.Remote(command_executor=HUB, options=options)
        try:
            driver.get(url)
            seen = driver.title
        finally:
            driver.quit()
        assert seen == title

    assert not tunnel.is_running()
    assert_process_gone(tunnel)


def test_bundled_java_starts_and_stops() -> None:
    tunnel = Tunnel(java_runtime="bundled", tunnel_identifier=f"python-bundled-{uuid.uuid4().hex[:8]}", timeout=120)
    with tunnel:
        assert tunnel.is_running()
        assert tunnel.runtime is not None and tunnel.runtime.bundled
    assert_process_gone(tunnel)
