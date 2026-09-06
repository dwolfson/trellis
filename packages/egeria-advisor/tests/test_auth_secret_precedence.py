"""EA's JWT and Portal secrets must honour the workspace-wide TRELLIS_* names.

The trellis compose overlay
(egeria-workspaces-fs compose-configs/optional-associated-runtimes/trellis)
sets TRELLIS_JWT_SECRET on all three services, with a comment stating why:
a session minted by one container has to stay valid in another, because each
otherwise derives a secret from its own hostname -- which under Docker is
per-container.

Until 2026-09-06 EA read only ADVISOR_JWT_SECRET, so it never saw that
variable and every EA container fell through to the per-hostname derivation.
Nothing errored; sessions simply stopped being portable, and on the reference
dev box .env carried a TRELLIS_JWT_SECRET that nothing consumed.

These pin the precedence rather than the values: ADVISOR_* wins, TRELLIS_* is
the shared fallback, and the derivation is last. Same order as
resource_explorer/auth.py's RE_* / TRELLIS_* pair.
"""
from __future__ import annotations

import hashlib

import advisor.auth as auth


def _derived(monkeypatch) -> str:
    machine = "a-fixed-test-host"
    monkeypatch.setenv("HOSTNAME", machine)
    return hashlib.sha256(f"egeria-advisor-{machine}".encode()).hexdigest()


def _clear(monkeypatch):
    for k in ("ADVISOR_JWT_SECRET", "TRELLIS_JWT_SECRET",
              "ADVISOR_PORTAL_SECRET", "TRELLIS_PORTAL_SECRET"):
        monkeypatch.delenv(k, raising=False)
    # advisor.yaml is a real file on disk and is the layer *below* the env
    # vars; blank it so these test the env precedence and not the shipped yaml.
    monkeypatch.setattr(auth, "_auth_cfg", lambda: {})


class TestJwtSecret:
    def test_advisor_name_wins(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("ADVISOR_JWT_SECRET", "from-advisor")
        monkeypatch.setenv("TRELLIS_JWT_SECRET", "from-trellis")
        assert auth._jwt_secret() == "from-advisor"

    def test_trellis_name_is_the_shared_fallback(self, monkeypatch):
        """The regression this file exists for: with only the workspace-wide
        name set -- which is exactly what the compose overlay provides -- EA
        must use it rather than deriving one."""
        _clear(monkeypatch)
        monkeypatch.setenv("TRELLIS_JWT_SECRET", "from-trellis")
        assert auth._jwt_secret() == "from-trellis"

    def test_derives_only_when_neither_is_set(self, monkeypatch):
        """Known-negative for the two above: the derivation must still happen
        when nothing is configured, or they would pass against a stub."""
        _clear(monkeypatch)
        expected = _derived(monkeypatch)
        assert auth._jwt_secret() == expected

    def test_a_configured_secret_is_not_the_derived_one(self, monkeypatch):
        """Guards the check itself. An openssl-generated secret is 64 hex
        characters and so is the sha256 derivation, so 'looks like hex' cannot
        tell them apart -- compare against the actual derived value."""
        _clear(monkeypatch)
        derived = _derived(monkeypatch)
        monkeypatch.setenv("TRELLIS_JWT_SECRET", "0" * 64)
        got = auth._jwt_secret()
        assert got != derived
        assert got == "0" * 64


class TestPortalSecret:
    def test_advisor_name_wins(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("ADVISOR_PORTAL_SECRET", "from-advisor")
        monkeypatch.setenv("TRELLIS_PORTAL_SECRET", "from-trellis")
        assert auth._portal_secret() == "from-advisor"

    def test_trellis_name_is_the_shared_fallback(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("TRELLIS_PORTAL_SECRET", "from-trellis")
        assert auth._portal_secret() == "from-trellis"

    def test_empty_when_neither_set_so_portal_sso_is_off_not_broken(self, monkeypatch):
        """Absence must stay absence here: an unset Portal secret disables the
        handoff, and must never resolve to some derived value that would make
        a mismatched token look merely invalid."""
        _clear(monkeypatch)
        assert auth._portal_secret() == ""
