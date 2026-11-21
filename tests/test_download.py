from __future__ import annotations

from pathlib import Path

import pytest

from testingbot_tunnel import _download

from .conftest import Server


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    """An empty directory, apart from the home directory the other fixtures make."""
    directory = tmp_path / "downloads"
    directory.mkdir()
    return directory


def test_downloads_file(server: Server, downloads: Path) -> None:
    server.file("/tunnel.jar", b"jar contents")
    destination = downloads / "tunnel.jar"
    assert _download.download(f"{server.url}/tunnel.jar", str(destination)) == str(destination)
    assert destination.read_bytes() == b"jar contents"
    assert list(downloads.iterdir()) == [destination]


def test_follows_redirects(server: Server, downloads: Path) -> None:
    server.redirect("/a", "/b")
    server.redirect("/b", f"{server.url}/c", code=301)
    server.file("/c", b"moved")
    destination = downloads / "file"
    _download.download(f"{server.url}/a", str(destination))
    assert destination.read_bytes() == b"moved"


def test_too_many_redirects(server: Server, downloads: Path) -> None:
    server.redirect("/loop", "/loop")
    with pytest.raises(OSError, match=r"Too many redirects \(max 5\)"):
        _download.download(f"{server.url}/loop", str(downloads / "file"))
    assert len(server.requests) == 6


def test_reports_status_code(server: Server, downloads: Path) -> None:
    with pytest.raises(OSError, match="statusCode: 404"):
        _download.download(f"{server.url}/missing", str(downloads / "file"))
    assert not (downloads / "file").exists()


def test_times_out_on_stalled_download_and_leaves_nothing_behind(server: Server, downloads: Path) -> None:
    server.stall("/slow", 5)
    with pytest.raises(OSError, match="Timed out after 0.5s"):
        _download.download(f"{server.url}/slow", str(downloads / "file"), timeout=0.5)
    assert list(downloads.iterdir()) == []


def test_keeps_the_previous_file_when_download_fails(server: Server, downloads: Path) -> None:
    destination = downloads / "file"
    destination.write_bytes(b"old")
    server.stall("/slow", 5)
    with pytest.raises(OSError):
        _download.download(f"{server.url}/slow", str(destination), timeout=0.5)
    assert destination.read_bytes() == b"old"


class TestHttpsOnlyRedirects:
    def test_resolves_relative_location(self) -> None:
        assert (
            _download.resolve_redirect("https://testingbot.com/tunnel/a.jar", "/b.jar")
            == "https://testingbot.com/b.jar"
        )

    def test_allows_https_to_https(self) -> None:
        assert _download.resolve_redirect("https://a.example/x", "https://b.example/y") == "https://b.example/y"

    def test_refuses_https_to_http(self) -> None:
        with pytest.raises(ValueError, match="would no longer be encrypted"):
            _download.resolve_redirect("https://testingbot.com/tunnel.jar", "http://evil.example/tunnel.jar")

    def test_download_refuses_downgrade(self, monkeypatch: pytest.MonkeyPatch, downloads: Path) -> None:
        calls = []

        def fake_open(url: str, method: str, timeout: float):  # type: ignore[no-untyped-def]
            calls.append(url)
            return None, "http://evil.example/tunnel.jar"

        monkeypatch.setattr(_download, "_open", fake_open)
        with pytest.raises(ValueError, match="Refusing to follow a redirect from https://testingbot.com"):
            _download.download("https://testingbot.com/tunnel/testingbot-tunnel.jar", str(downloads / "jar"))
        assert calls == ["https://testingbot.com/tunnel/testingbot-tunnel.jar"]
        assert list(downloads.iterdir()) == []


def test_redirect_location(server: Server) -> None:
    server.redirect("/latest", "/tag/v5.2")
    server.file("/plain", b"")
    assert _download.redirect_location(f"{server.url}/latest") == f"{server.url}/tag/v5.2"
    assert _download.redirect_location(f"{server.url}/plain") is None
    assert server.requests[0][0] == "HEAD"


def test_parse_checksum() -> None:
    digest = "a" * 64
    assert _download.parse_checksum(f"{digest}  testingbot-tunnel-linux-x64.tar.gz\n") == digest
    assert _download.parse_checksum(digest.upper()) == digest
    assert _download.parse_checksum("<html>Not Found</html>") is None
