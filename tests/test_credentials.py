from __future__ import annotations

from pathlib import Path

import pytest

from testingbot_tunnel import CredentialsError, resolve_credentials


def test_arguments_come_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_KEY", "env-key")
    monkeypatch.setenv("TB_SECRET", "env-secret")
    assert resolve_credentials("arg-key", "arg-secret") == ("arg-key", "arg-secret")


def test_half_a_pair_of_arguments_is_refused() -> None:
    with pytest.raises(CredentialsError, match="api_secret is missing"):
        resolve_credentials("arg-key", None)


def test_tb_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_KEY", "tb-key")
    monkeypatch.setenv("TB_SECRET", "tb-secret")
    monkeypatch.setenv("TESTINGBOT_KEY", "other-key")
    monkeypatch.setenv("TESTINGBOT_SECRET", "other-secret")
    assert resolve_credentials() == ("tb-key", "tb-secret")


def test_testingbot_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTINGBOT_KEY", "other-key")
    monkeypatch.setenv("TESTINGBOT_SECRET", "other-secret")
    assert resolve_credentials() == ("other-key", "other-secret")


def test_never_mixes_sources(monkeypatch: pytest.MonkeyPatch, isolated: Path) -> None:
    monkeypatch.setenv("TB_KEY", "only-a-key")
    monkeypatch.setenv("TESTINGBOT_KEY", "k2")
    monkeypatch.setenv("TESTINGBOT_SECRET", "s2")
    assert resolve_credentials() == ("k2", "s2")


def test_testingbot_file(isolated: Path) -> None:
    (isolated / ".testingbot").write_text("file-key:file-secret\n")
    assert resolve_credentials() == ("file-key", "file-secret")


def test_malformed_testingbot_file(isolated: Path) -> None:
    (isolated / ".testingbot").write_text("no separator here")
    with pytest.raises(CredentialsError, match="key:secret"):
        resolve_credentials()


def test_nothing_found() -> None:
    with pytest.raises(CredentialsError, match="No TestingBot credentials found"):
        resolve_credentials()
