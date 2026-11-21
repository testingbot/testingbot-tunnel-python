from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from testingbot_tunnel import DownloadError, JavaError, _runtime

from .conftest import FakeJava, Server, make_bundle

PLATFORM = "linux-x64"


class TestJavaVersion:
    @pytest.mark.parametrize(
        ("output", "version"),
        [
            ('java version "1.8.0_292"', 8),
            ('openjdk version "11.0.2" 2019-01-15', 11),
            ('openjdk version "17.0.1" 2021-10-19', 17),
            ('openjdk version "21" 2023-09-19', 21),
            ("garbage", None),
            ("", None),
        ],
    )
    def test_parse(self, output: str, version: object) -> None:
        assert _runtime.parse_java_version(output) == version

    def test_required_version(self) -> None:
        assert _runtime.required_java_version("5.0") == 17
        assert _runtime.required_java_version("4.9") == 11
        assert _runtime.required_java_version(None) == 11

    def test_check_java_accepts_recent_java(self, fake_java: FakeJava) -> None:
        fake_java.set("FAKE_JAVA_RUNTIME", "21")
        assert _runtime.check_java(17) == 21

    def test_check_java_refuses_old_java(self, fake_java: FakeJava) -> None:
        fake_java.set("FAKE_JAVA_RUNTIME", "11")
        with pytest.raises(JavaError, match="Java 11 is installed, but Java 17 or higher is required"):
            _runtime.check_java(17)

    def test_check_java_without_java(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))
        with pytest.raises(JavaError, match=r"Java might not be installed or not in \$PATH"):
            _runtime.check_java()


class TestJar:
    def test_is_jar_valid(self, fake_java: FakeJava, cached_jar: Path) -> None:
        assert _runtime.is_jar_valid(str(cached_jar)) is True
        fake_java.set("FAKE_JAVA_VALID", "1")
        assert _runtime.is_jar_valid(str(cached_jar)) is False

    def test_read_jar_version(self, fake_java: FakeJava, cached_jar: Path) -> None:
        fake_java.set("FAKE_JAVA_TUNNEL", "4.9")
        assert _runtime.read_jar_version(str(cached_jar)) == "4.9"

    def test_uses_a_working_cached_jar(self, fake_java: FakeJava, cached_jar: Path) -> None:
        assert _runtime.download_jar() == str(cached_jar)

    def test_redownloads_a_corrupt_jar(
        self, fake_java: FakeJava, cached_jar: Path, server: Server, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_java.set("FAKE_JAVA_VALID", "1")
        monkeypatch.setattr(_runtime, "TUNNEL_DOWNLOAD_URL", f"{server.url}/tunnel")
        server.file("/tunnel/testingbot-tunnel.jar", b"fresh jar")
        assert _runtime.download_jar() == str(cached_jar)
        assert cached_jar.read_bytes() == b"fresh jar"

    def test_downloads_the_version_asked_for(
        self, fake_java: FakeJava, server: Server, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_runtime, "TUNNEL_DOWNLOAD_URL", f"{server.url}/tunnel")
        server.file("/tunnel/testingbot-tunnel-4.9.jar", b"jar 4.9")
        location = _runtime.download_jar("4.9")
        assert location == str(tmp_path / "cache" / "testingbot-tunnel-4.9.jar")

    def test_explains_a_failed_download(
        self, fake_java: FakeJava, server: Server, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_runtime, "TUNNEL_DOWNLOAD_URL", f"{server.url}/tunnel")
        with pytest.raises(
            DownloadError, match="Could not download the tunnel from TestingBot - please check your connection"
        ):
            _runtime.download_jar("0.0")

    def test_explains_a_cache_that_can_not_be_written(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        if os.name == "nt" or os.geteuid() == 0:
            pytest.skip("permissions are not enforced")
        readonly = tmp_path / "readonly"
        readonly.mkdir(mode=0o500)
        monkeypatch.setenv("TESTINGBOT_TUNNEL_CACHE_DIR", str(readonly / "cache"))
        with pytest.raises(DownloadError, match="Set TESTINGBOT_TUNNEL_CACHE_DIR"):
            _runtime.download_jar()


def test_cache_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _runtime.cache_directory() == tmp_path / "cache"
    monkeypatch.delenv("TESTINGBOT_TUNNEL_CACHE_DIR")
    assert _runtime.cache_directory().name == "testingbot-tunnel-launcher"


def test_bundled_platform() -> None:
    assert _runtime.bundled_platform("darwin", "arm64") == "macos-arm64"
    assert _runtime.bundled_platform("linux", "x64") == "linux-x64"
    assert _runtime.bundled_platform("win32", "x64") == "windows-x64"
    assert _runtime.bundled_platform("win32", "arm64") is None
    assert _runtime.bundled_platform("freebsd", "x64") is None
    assert _runtime.bundled_archive_name("windows-x64") == "testingbot-tunnel-windows-x64.zip"
    assert _runtime.bundled_archive_name("macos-arm64") == "testingbot-tunnel-macos-arm64.tar.gz"


@pytest.fixture
def releases(server: Server, monkeypatch: pytest.MonkeyPatch) -> Server:
    """A mirror of the TestingBot Tunnel releases, publishing 5.2 for linux-x64."""
    if os.name == "nt":
        pytest.skip("the bundle holds a shell script")
    monkeypatch.setattr(_runtime, "bundled_platform", lambda *args: PLATFORM)
    monkeypatch.setenv("TESTINGBOT_TUNNEL_RELEASES_URL", f"{server.url}/releases/")
    publish(server, "5.2")
    server.redirect("/releases/latest", f"{server.url}/releases/tag/v5.2")
    return server


def publish(server: Server, version: str, checksum: str = "") -> bytes:
    bundle = make_bundle(PLATFORM)
    path = f"/releases/download/v{version}/testingbot-tunnel-{PLATFORM}.tar.gz"
    server.file(path, bundle)
    digest = checksum or hashlib.sha256(bundle).hexdigest()
    server.file(path + ".sha256", f"{digest}  testingbot-tunnel-{PLATFORM}.tar.gz\n".encode())
    return bundle


class TestBundled:
    def test_downloads_latest_and_unpacks_it(self, releases: Server, tmp_path: Path) -> None:
        runtime = _runtime.download_bundled()
        directory = tmp_path / "cache" / "bundles" / f"5.2-{PLATFORM}"
        assert runtime == _runtime.Runtime(
            java=str(directory / "runtime" / "bin" / "java"),
            jar=str(directory / "lib" / "testingbot-tunnel.jar"),
            version="5.2",
            bundled=True,
        )
        assert os.access(runtime.java, os.X_OK)
        # Nothing but the unpacked bundle is left behind
        assert os.listdir(directory.parent) == [directory.name]

    def test_downloads_the_version_asked_for(self, releases: Server) -> None:
        publish(releases, "5.0")
        assert _runtime.download_bundled("5.0").version == "5.0"

    def test_uses_a_download_already_unpacked(self, releases: Server) -> None:
        _runtime.download_bundled()
        downloads = len(releases.requests)
        _runtime.download_bundled("5.2")
        assert len(releases.requests) == downloads

    def test_uses_the_newest_cached_download_when_offline(
        self, releases: Server, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        publish(releases, "5.0")
        _runtime.download_bundled("5.0")
        _runtime.download_bundled("5.2")
        monkeypatch.setenv("TESTINGBOT_TUNNEL_RELEASES_URL", "http://127.0.0.1:9/offline")
        assert _runtime.download_bundled().version == "5.2"

    def test_fails_offline_without_cached_download(self, releases: Server, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TESTINGBOT_TUNNEL_RELEASES_URL", "http://127.0.0.1:9/offline")
        with pytest.raises(DownloadError, match="Could not find the latest version of TestingBot Tunnel"):
            _runtime.download_bundled()

    def test_refuses_a_download_that_does_not_match_its_checksum(self, releases: Server, tmp_path: Path) -> None:
        publish(releases, "5.1", checksum="0" * 64)
        with pytest.raises(DownloadError, match="does not match its published checksum, it was not used"):
            _runtime.download_bundled("5.1")
        assert os.listdir(tmp_path / "cache" / "bundles") == []

    def test_refuses_tunnels_older_than_5(self) -> None:
        with pytest.raises(JavaError, match="has no download with Java included, those exist for 5.0 and up"):
            _runtime.download_bundled("4.9")

    def test_reports_a_version_that_is_not_published(self, releases: Server) -> None:
        with pytest.raises(DownloadError, match="Could not download TestingBot Tunnel 9.9 with Java included"):
            _runtime.download_bundled("9.9")

    def test_unsupported_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_runtime, "bundled_platform", lambda *args: None)
        with pytest.raises(JavaError, match="There is no TestingBot Tunnel download with Java included"):
            _runtime.download_bundled()

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    @pytest.mark.parametrize("with_filter", [True, False])
    def test_refuses_archive_escaping_its_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_filter: bool
    ) -> None:
        import io
        import tarfile

        if not with_filter:
            # Pythons before 3.9.17 have no extraction filters
            monkeypatch.delattr(tarfile, "data_filter", raising=False)
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("../escaped")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        target = tmp_path / "out"
        target.mkdir()
        with pytest.raises(DownloadError):
            _runtime.extract_archive(archive, target)
        assert not (tmp_path / "escaped").exists()

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_unpacks_without_extraction_filters(self, releases: Server, monkeypatch: pytest.MonkeyPatch) -> None:
        import tarfile

        monkeypatch.delattr(tarfile, "data_filter", raising=False)
        runtime = _runtime.download_bundled()
        assert os.access(runtime.java, os.X_OK)


class TestPrepareRuntime:
    def test_system_java(self, fake_java: FakeJava, cached_jar: Path) -> None:
        runtime = _runtime.prepare_runtime({})
        assert runtime == _runtime.Runtime(java="java", jar=str(cached_jar), version="5.2")

    def test_bundled_when_java_is_not_installed(
        self, releases: Server, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        assert _runtime.prepare_runtime({}).bundled is True

    def test_bundled_when_java_is_too_old(self, fake_java: FakeJava, cached_jar: Path, releases: Server) -> None:
        fake_java.set("FAKE_JAVA_RUNTIME", "11")
        runtime = _runtime.prepare_runtime({})
        assert runtime.bundled is True
        assert runtime.version == "5.2"

    def test_old_tunnel_runs_on_java_11(
        self, fake_java: FakeJava, cached_jar: Path, server: Server, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_java.set("FAKE_JAVA_RUNTIME", "11")
        monkeypatch.setattr(_runtime, "TUNNEL_DOWNLOAD_URL", f"{server.url}/tunnel")
        server.file("/tunnel/testingbot-tunnel-4.9.jar", b"jar")
        assert _runtime.prepare_runtime({"tunnel_version": "4.9"}).java == "java"

    def test_system_does_not_fall_back(self, fake_java: FakeJava, cached_jar: Path, releases: Server) -> None:
        fake_java.set("FAKE_JAVA_RUNTIME", "11")
        with pytest.raises(JavaError, match="Java 11 is installed, but Java 17"):
            _runtime.prepare_runtime({"java_runtime": "system"})

    def test_system_without_java(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        with pytest.raises(JavaError, match="Java might not be installed"):
            _runtime.prepare_runtime({"java_runtime": "system"})

    def test_bundled_always(self, fake_java: FakeJava, releases: Server) -> None:
        assert _runtime.prepare_runtime({"java_runtime": "bundled"}).bundled is True
        assert fake_java.calls() == []
