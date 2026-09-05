"""`egeria-advisor login` / `logout`, and how the rest of the CLI reads the session.

`login_with_password` is mocked throughout — these tests must not need an Egeria
platform, and the live path is covered by the change's own manual verification.
Every test redirects `XDG_CONFIG_HOME`, so the developer's real
`~/.config/trellis/egeria-advisor/session.json` is never touched.
"""
from __future__ import annotations

import stat
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from click.testing import CliRunner

from advisor import auth
from advisor.cli import session as cli_session
from advisor.cli.main import cli


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("ADVISOR_JWT_SECRET", raising=False)
    auth.reset_policy_cache()
    yield
    auth.reset_policy_cache()


def make_egeria_token(user_id: str = "peterprofile", ttl_seconds: int = 3600) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"iss": "self", "sub": user_id, "iat": now,
         "exp": now + timedelta(seconds=ttl_seconds)},
        "egeria-view-server-key",
        algorithm="HS256",
    )


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def test_login_caches_a_session(runner, monkeypatch):
    egeria_token = make_egeria_token()
    monkeypatch.setattr("advisor.auth.login_with_password", lambda u, p: egeria_token)

    result = runner.invoke(cli, ["login", "--user", "peterprofile"], input="hunter2\n")

    assert result.exit_code == 0, result.output
    assert "Signed in as peterprofile" in result.output

    record = cli_session.load_session()
    assert record is not None
    assert record.user_id == "peterprofile"
    assert record.is_expired is False


def test_the_password_is_prompted_hidden_and_never_stored(runner, monkeypatch):
    """The one thing this whole mechanism exists to guarantee.

    Asserts on the raw bytes of the session file rather than on the parsed
    record: a password would have to be *somewhere* in that file to be
    recoverable, whatever key it hid under.
    """
    seen = {}

    def fake_login(user_id, password):
        seen["password"] = password
        return make_egeria_token()

    monkeypatch.setattr("advisor.auth.login_with_password", fake_login)
    result = runner.invoke(cli, ["login", "--user", "peterprofile"], input="hunter2\n")

    assert seen["password"] == "hunter2"          # it reached Egeria...
    assert "hunter2" not in result.output          # ...but was never echoed
    raw = cli_session.session_file.session_path(cli_session.APP_NAME).read_bytes()
    assert b"hunter2" not in raw                   # ...and was never written


def test_the_cached_session_is_the_app_jwt_not_the_egeria_token(runner, monkeypatch):
    """What is stored must be verifiable by this app, so it works as a header."""
    egeria_token = make_egeria_token()
    monkeypatch.setattr("advisor.auth.login_with_password", lambda u, p: egeria_token)
    runner.invoke(cli, ["login", "--user", "peterprofile"], input="hunter2\n")

    record = cli_session.load_session()
    claims = auth.decode_token(record.token)       # verifies EA's own signature
    assert claims["user_id"] == "peterprofile"
    assert claims["egeria_token"] == egeria_token


def test_the_session_file_is_0600(runner, monkeypatch):
    monkeypatch.setattr("advisor.auth.login_with_password", lambda u, p: make_egeria_token())
    runner.invoke(cli, ["login", "--user", "peterprofile"], input="hunter2\n")

    path = cli_session.session_file.session_path(cli_session.APP_NAME)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_failed_login_writes_nothing_and_exits_1(runner, monkeypatch):
    monkeypatch.setattr("advisor.auth.login_with_password", lambda u, p: None)

    result = runner.invoke(cli, ["login", "--user", "peterprofile"], input="wrong\n")

    assert result.exit_code == 1
    assert "Sign-in failed" in result.output
    assert cli_session.load_session() is None


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------

def test_logout_removes_the_session(runner, monkeypatch):
    monkeypatch.setattr("advisor.auth.login_with_password", lambda u, p: make_egeria_token())
    runner.invoke(cli, ["login", "--user", "peterprofile"], input="hunter2\n")

    result = runner.invoke(cli, ["logout"])

    assert result.exit_code == 0
    assert "Signed out" in result.output
    assert cli_session.load_session() is None


def test_logout_with_no_session_is_not_an_error(runner):
    result = runner.invoke(cli, ["logout"])
    assert result.exit_code == 0
    assert "Not signed in" in result.output


# ---------------------------------------------------------------------------
# How commands read the session
# ---------------------------------------------------------------------------

def test_resolve_identity_is_none_when_nothing_is_signed_in():
    assert cli_session.resolve_identity() == (None, None)


def test_resolve_identity_uses_the_cached_login():
    egeria_token = make_egeria_token()
    cli_session.save_login("peterprofile", egeria_token)

    user_id, creds = cli_session.resolve_identity()

    assert user_id == "peterprofile"
    assert creds == {"user_id": "peterprofile", "password": "", "token": egeria_token}


def test_explicit_user_overrides_the_namespace_but_not_the_token():
    """--user picks the namespace; the Egeria call still runs as who signed in."""
    egeria_token = make_egeria_token()
    cli_session.save_login("peterprofile", egeria_token)

    user_id, creds = cli_session.resolve_identity("erinoverview")

    assert user_id == "erinoverview"
    assert creds["token"] == egeria_token


def test_an_expired_session_does_not_supply_credentials():
    cli_session.save_login("peterprofile", make_egeria_token(ttl_seconds=-60))
    assert cli_session.resolve_identity() == (None, None)


def test_require_credentials_prints_one_line_and_exits_2_on_expiry(capsys):
    """Exactly one line, naming the time and the command. Exit 2, not 1."""
    cli_session.save_login("peterprofile", make_egeria_token(ttl_seconds=-60))
    record = cli_session.load_session()

    with pytest.raises(SystemExit) as excinfo:
        cli_session.require_egeria_credentials()

    assert excinfo.value.code == 2
    printed = capsys.readouterr().err.strip().splitlines()
    assert len(printed) == 1
    assert printed[0] == (
        f"session expired at {record.expires_at_local:%H:%M}, run `egeria-advisor login`"
    )


def test_require_credentials_returns_them_when_signed_in():
    egeria_token = make_egeria_token()
    cli_session.save_login("peterprofile", egeria_token)
    assert cli_session.require_egeria_credentials()["token"] == egeria_token


# ---------------------------------------------------------------------------
# The default-command group still routes a bare question to `ask`
# ---------------------------------------------------------------------------

def test_a_bare_query_still_routes_to_ask():
    """`egeria-advisor "how do I ..."` must not become an unknown command."""
    import click
    name, _cmd, _args = cli.resolve_command(click.Context(cli), ["what is a glossary?"])
    assert name == "ask"


def test_the_subcommand_names_still_win():
    import click
    for name in ("login", "logout", "ask"):
        resolved, _cmd, _args = cli.resolve_command(click.Context(cli), [name])
        assert resolved == name
