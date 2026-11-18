import io
import stat
from types import SimpleNamespace

import pytest
from conftest import FakeResponse

from stormdb_catalog import extract
from stormdb_catalog.extract import (
    LoginError,
    fetch_series,
    login,
    parse_filteredseries,
)

URL = "http://example.invalid/extract/"
PASSWORD = "s3cret&pw"


def test_parse_filteredseries(fixtures):
    series = parse_filteredseries((fixtures / "filteredseries.txt").read_text())
    assert len(series) == 5
    s = series[0]
    assert (
        s["subjectcode"],
        s["study"],
        s["modality"],
        s["serieno"],
        s["seriename"],
    ) == (
        "0001",
        "20150101_000000",
        "MEG",
        "001",
        "rest_raw",
    )
    assert s["type"] == "MEG"
    assert series[4]["subjectcode"] == "9999_XYZ"  # explicit value wins over the path
    assert series[4]["modality"] == "MR"


def test_parse_filteredseries_unmatched_path():
    assert parse_filteredseries("path:/somewhere/else\n\n") == [
        {"path": "/somewhere/else"}
    ]


def test_fetch_series(fake_get, fixtures):
    fake_get.reply = FakeResponse((fixtures / "filteredseries.txt").read_text())
    series = fetch_series("MEG_vision", "login=abc", URL)
    assert len(series) == 5
    assert fake_get.calls[0].startswith(
        URL + "filteredseries?login=abc&projectCode=MEG_vision&"
    )


def test_fetch_series_error(fake_get):
    fake_get.reply = FakeResponse("error: no such project")
    with pytest.raises(RuntimeError, match="no such project"):
        fetch_series("x", "login=abc", URL)


def test_fetch_series_expired_login_hint(fake_get):
    fake_get.reply = FakeResponse("Error: Your login is not working")
    with pytest.raises(RuntimeError, match="login --force"):
        fetch_series("x", "login=abc", URL)


def test_login_writes_readonly_file(fake_get, tmp_path):
    fake_get.reply = FakeResponse("login=abc123\n")
    p = login("alice", PASSWORD, URL, tmp_path / "loginfile")
    assert p.read_text() == "login=abc123"
    assert stat.S_IMODE(p.stat().st_mode) == 0o400
    assert fake_get.calls == [URL + "login/username/alice/password/s3cret%26pw"]


def test_login_bad_password_writes_nothing(fake_get, tmp_path):
    fake_get.reply = FakeResponse("Error: Could not login")
    with pytest.raises(LoginError, match="invalid username or password"):
        login("alice", PASSWORD, URL, tmp_path / "loginfile")
    assert not (tmp_path / "loginfile").exists()


@pytest.mark.parametrize(
    "reply", [FakeResponse("", 500), FakeResponse(""), FakeResponse("some error")]
)
def test_login_bad_responses(fake_get, tmp_path, reply):
    fake_get.reply = reply
    with pytest.raises(LoginError):
        login("alice", PASSWORD, URL, tmp_path / "loginfile")
    assert not (tmp_path / "loginfile").exists()


def test_login_connection_error_hides_password(fake_get, tmp_path):
    import requests

    fake_get.reply = requests.ConnectionError(
        f"failed: {URL}login/username/alice/password/{PASSWORD}"
    )
    with pytest.raises(LoginError) as exc:
        login("alice", PASSWORD, URL, tmp_path / "loginfile")
    assert PASSWORD not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_login_refuses_existing_file(fake_get, tmp_path):
    p = tmp_path / "loginfile"
    p.write_text("old")
    with pytest.raises(LoginError, match="--force"):
        login("alice", PASSWORD, URL, p)
    assert p.read_text() == "old"
    assert fake_get.calls == []


def test_login_force_replaces_readonly_file(fake_get, tmp_path):
    p = tmp_path / "loginfile"
    p.write_text("old")
    p.chmod(0o400)
    fake_get.reply = FakeResponse("login=new")
    login("alice", PASSWORD, URL, p, force=True)
    assert p.read_text() == "login=new"
    assert stat.S_IMODE(p.stat().st_mode) == 0o400


def _args(tmp_path, force=False, password_stdin=False):
    return SimpleNamespace(
        user="alice",
        login_file=str(tmp_path / "loginfile"),
        extract_url=URL,
        force=force,
        password_stdin=password_stdin,
    )


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(extract.sys.stdin, "isatty", lambda: True)


def test_run_login_never_prints_password(fake_get, tmp_path, monkeypatch, capsys, tty):
    monkeypatch.setattr(extract.getpass, "getpass", lambda prompt: PASSWORD)
    fake_get.reply = FakeResponse("login=abc123")
    extract.run_login(_args(tmp_path))
    fake_get.reply = FakeResponse("Error: Could not login")
    with pytest.raises(SystemExit) as exc:
        extract.run_login(_args(tmp_path, force=True))
    out = capsys.readouterr()
    assert "Wrote login code" in out.out
    assert "invalid username or password" in str(exc.value)
    assert PASSWORD not in out.out + out.err + str(exc.value)


def test_run_login_existing_file_does_not_prompt(tmp_path, monkeypatch):
    (tmp_path / "loginfile").write_text("old")
    monkeypatch.setattr(
        extract.getpass, "getpass", lambda prompt: pytest.fail("prompted")
    )
    with pytest.raises(SystemExit, match="--force"):
        extract.run_login(_args(tmp_path))


def test_read_login_code(tmp_path):
    (tmp_path / "loginfile").write_text("login=abc\n")
    assert extract.read_login_code(tmp_path / "loginfile") == "login=abc"
    with pytest.raises(SystemExit, match="stormdb-catalog login"):
        extract.read_login_code(tmp_path / "missing")


def test_run_login_without_terminal_does_not_prompt(fake_get, tmp_path, monkeypatch):
    monkeypatch.setattr(extract.sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(
        extract.getpass, "getpass", lambda prompt: pytest.fail("prompted")
    )
    with pytest.raises(SystemExit, match="--password-stdin"):
        extract.run_login(_args(tmp_path))
    assert fake_get.calls == []


def test_run_login_password_stdin(fake_get, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(extract.sys, "stdin", io.StringIO(PASSWORD + "\nignored\n"))
    monkeypatch.setattr(
        extract.getpass, "getpass", lambda prompt: pytest.fail("prompted")
    )
    fake_get.reply = FakeResponse("login=abc123")
    extract.run_login(_args(tmp_path, password_stdin=True))
    assert fake_get.calls == [URL + "login/username/alice/password/s3cret%26pw"]
    assert (tmp_path / "loginfile").read_text() == "login=abc123"
    assert PASSWORD not in capsys.readouterr().out


def test_run_login_password_stdin_empty(fake_get, tmp_path, monkeypatch):
    monkeypatch.setattr(extract.sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit, match="No password"):
        extract.run_login(_args(tmp_path, password_stdin=True))
    assert fake_get.calls == []
