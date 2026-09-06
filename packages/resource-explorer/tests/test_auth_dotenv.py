"""Regression test for a real bug found live 2026-09-06: RE's own JWT/Portal
secrets and JWT TTL were read straight from `os.environ`
(`resource_explorer/auth.py`'s `jwt_secret()`/`portal_secret()`/
`_jwt_ttl_hours()`), bypassing pydantic-settings entirely — the only
settings in the package that did. Every other setting goes through a
`BaseSettings` class declaring `env_file=_ENV_FILES` (see
`config.py`'s `_ENV_FILE_CONFIG` and its own comment about the same bug
shape happening twice already for GITHUB_TOKEN and friends), so a value
set only in `.env` was silently invisible to auth: no error, just a
fallback (a derived per-host JWT secret, or Portal SSO silently and
wrongly reported "disabled"). Found on an install where the operator set
RE_JWT_SECRET in `.env`, restarted, and the log still said neither var
was set.

Fixed by giving auth.py its own `_AuthSecretsConfig(BaseSettings)` reusing
`config.py`'s `_ENV_FILE_CONFIG`, and combining `RE_*`/`TRELLIS_*` with a
plain `or` in Python (not `AliasChoices`) so RE-wins-over-TRELLIS stays an
explicit, source-independent precedence rather than something that could
flip depending on which var happened to be a real env var vs. a `.env`
entry — see `_AuthSecretsConfig`'s docstring for the full reasoning.
"""
from __future__ import annotations

import hashlib

import resource_explorer.auth as auth


#: All five vars this module cares about. Written explicitly (blank unless a
#: test sets them) into every throwaway `.env` below — not just the ones a
#: given test's `contents` happen to mention.
_AUTH_ENV_KEYS = (
    "RE_JWT_SECRET", "TRELLIS_JWT_SECRET",
    "RE_PORTAL_SECRET", "TRELLIS_PORTAL_SECRET",
    "RE_JWT_TTL_HOURS",
)


def _write_env(tmp_path, monkeypatch, contents: str):
    """Same shape as test_config.py's `_write_env`, with one addition this
    module needs and that one didn't: every key in `_AUTH_ENV_KEYS` a test
    doesn't set is written out blank, not merely omitted.

    Two sources otherwise leak in and are unreachable via plain
    `monkeypatch.delenv`, because neither is a real process env var:
    conftest.py sets a REAL `RE_JWT_SECRET` (delenv handles that one), but
    the package's own `.env` (`_PACKAGE_ENV`, always loaded regardless of
    cwd, merged with — not replaced by — this throwaway one) carries real
    leftover values for `TRELLIS_JWT_SECRET` and `RE_PORTAL_SECRET` on this
    checkout. A later dotenv file only overrides a key it actually
    mentions, so a test that wants "RE_PORTAL_SECRET unset" has to say
    `RE_PORTAL_SECRET=` explicitly to blank out the package .env's real
    value — this helper does that for every key not otherwise given."""
    for key in _AUTH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    given: dict[str, str] = {}
    for line in contents.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition("=")
        given[key.strip()] = value
    full = {key: given.get(key, "") for key in _AUTH_ENV_KEYS}
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(f"{k}={v}" for k, v in full.items()) + "\n")
    monkeypatch.chdir(tmp_path)
    return env_file


def _reset(monkeypatch):
    """Every test needs both caches dropped: `_auth_secrets_cache` (this
    module's own fix) so `.env`/env changes actually take effect, and
    `_DERIVED_SECRET_WARNED` (module-global, warns only once per process)
    so the derived-secret warning path is independently testable."""
    auth.reset_auth_secrets_cache()
    monkeypatch.setattr(auth, "_DERIVED_SECRET_WARNED", False)


class TestJwtSecretReadsDotEnv:
    def test_re_jwt_secret_read_from_dotenv(self, tmp_path, monkeypatch):
        """The actual bug: RE_JWT_SECRET set only in .env used to be invisible."""
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_JWT_SECRET=from-dotenv-secret\n")
        assert auth.jwt_secret() == "from-dotenv-secret"

    def test_real_env_var_still_overrides_dotenv(self, tmp_path, monkeypatch):
        """Regression guard on the fix itself: pydantic-settings' documented
        precedence (real env > .env) must be preserved, matching every other
        setting in the package (test_config.py's equivalent test)."""
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_JWT_SECRET=from-dotenv\n")
        monkeypatch.setenv("RE_JWT_SECRET", "from-real-env")
        assert auth.jwt_secret() == "from-real-env"

    def test_re_jwt_secret_wins_over_trellis_jwt_secret(self, tmp_path, monkeypatch):
        """Both set in .env: RE_* must win, exactly as the raw os.environ
        version's `RE_JWT_SECRET or TRELLIS_JWT_SECRET` did."""
        _reset(monkeypatch)
        _write_env(
            tmp_path, monkeypatch,
            "RE_JWT_SECRET=re-wins\nTRELLIS_JWT_SECRET=trellis-loses\n",
        )
        assert auth.jwt_secret() == "re-wins"

    def test_trellis_jwt_secret_used_when_re_unset(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "TRELLIS_JWT_SECRET=trellis-only\n")
        assert auth.jwt_secret() == "trellis-only"

    def test_derived_secret_when_neither_is_set(self, tmp_path, monkeypatch, caplog):
        """Missing entirely (not a .env-visibility bug — the honest fallback)
        must still derive the per-host secret and log the once-per-process
        warning, unchanged from before this fix."""
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "")
        monkeypatch.setenv("HOSTNAME", "hedwig")
        import logging

        with caplog.at_level(logging.WARNING, logger="resource_explorer.auth"):
            secret = auth.jwt_secret()

        expected = hashlib.sha256(b"resource-explorer-hedwig").hexdigest()
        assert secret == expected
        assert "neither RE_JWT_SECRET nor TRELLIS_JWT_SECRET is set" in caplog.text

    def test_derived_secret_warning_logged_once_per_process(self, tmp_path, monkeypatch, caplog):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "")
        import logging

        with caplog.at_level(logging.WARNING, logger="resource_explorer.auth"):
            auth.jwt_secret()
            auth.jwt_secret()

        assert caplog.text.count("neither RE_JWT_SECRET nor TRELLIS_JWT_SECRET is set") == 1


class TestPortalSecretReadsDotEnv:
    def test_re_portal_secret_read_from_dotenv(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_PORTAL_SECRET=portal-from-dotenv\n")
        assert auth.portal_secret() == "portal-from-dotenv"

    def test_re_portal_secret_wins_over_trellis_portal_secret(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(
            tmp_path, monkeypatch,
            "RE_PORTAL_SECRET=re-wins\nTRELLIS_PORTAL_SECRET=trellis-loses\n",
        )
        assert auth.portal_secret() == "re-wins"

    def test_trellis_portal_secret_used_when_re_unset(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "TRELLIS_PORTAL_SECRET=trellis-only\n")
        assert auth.portal_secret() == "trellis-only"

    def test_empty_string_when_neither_is_set(self, tmp_path, monkeypatch):
        """Not an error — Portal SSO is simply disabled (the tile shows
        'Not configured' rather than erroring; see .env.example)."""
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "")
        assert auth.portal_secret() == ""

    def test_real_env_var_still_overrides_dotenv(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_PORTAL_SECRET=from-dotenv\n")
        monkeypatch.setenv("RE_PORTAL_SECRET", "from-real-env")
        assert auth.portal_secret() == "from-real-env"


class TestJwtTtlHoursReadsDotEnv:
    def test_ttl_read_from_dotenv(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_JWT_TTL_HOURS=12\n")
        assert auth._jwt_ttl_hours() == 12

    def test_ttl_defaults_to_eight_when_unset(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "")
        assert auth._jwt_ttl_hours() == 8

    def test_ttl_clamps_to_minimum_one(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_JWT_TTL_HOURS=0\n")
        assert auth._jwt_ttl_hours() == 1

        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_JWT_TTL_HOURS=-5\n")
        assert auth._jwt_ttl_hours() == 1

    def test_non_integer_ttl_falls_back_to_eight_rather_than_raising(self, tmp_path, monkeypatch):
        """A malformed value must degrade gracefully, not take down auth
        (and therefore the whole app) at request time."""
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_JWT_TTL_HOURS=not-a-number\n")
        assert auth._jwt_ttl_hours() == 8

    def test_real_env_var_still_overrides_dotenv(self, tmp_path, monkeypatch):
        _reset(monkeypatch)
        _write_env(tmp_path, monkeypatch, "RE_JWT_TTL_HOURS=4\n")
        monkeypatch.setenv("RE_JWT_TTL_HOURS", "24")
        assert auth._jwt_ttl_hours() == 24
