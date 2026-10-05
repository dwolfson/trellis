"""The shared-registry guard fails closed, with a FAKE connect only.

Nothing here opens a real connection: the real psycopg2.connect is replaced by
a recorder, and a refusal is proven by the recorder never being called.
"""
from __future__ import annotations

import pytest
import sqlalchemy

from tests import shared_registry_guard as G

SHARED = (
    "postgresql://u:p@localhost:5442/egeria_advisor"
    "?options=-csearch_path%3Dresource_explorer"
)
TEST_SCHEMA = (
    "postgresql://u:p@localhost:5442/egeria_advisor"
    "?options=-csearch_path%3Dresource_explorer_test_123"
)


class _Reached(Exception):
    """Raised by the fake connect: the guard let the connection through."""


@pytest.fixture
def fake_connect(monkeypatch):
    calls: list = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        raise _Reached()

    monkeypatch.setitem(G._state, "real_psycopg2_connect", fake)
    monkeypatch.delenv(G.ALLOW_ENV, raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return calls


def _open(url: str):
    engine = sqlalchemy.create_engine(url)
    try:
        engine.connect()
    finally:
        engine.dispose()


def test_guard_is_installed_by_conftest():
    assert G._state["installed"]


def test_shared_dsn_fails_closed_before_any_connect(fake_connect):
    with pytest.raises(G.SharedRegistryAccessError) as exc:
        _open(SHARED)
    assert fake_connect == []
    msg = str(exc.value)
    assert "test_shared_dsn_fails_closed_before_any_connect" in msg
    assert G.ALLOW_ENV in msg and "localhost:5442/egeria_advisor" in msg


def test_url_without_search_path_is_refused_on_the_registry_path(fake_connect):
    with pytest.raises(G.SharedRegistryAccessError):
        _open("postgresql://u:p@127.0.0.1:5442/egeria_advisor")
    assert fake_connect == []


def test_raw_psycopg2_connect_to_the_real_schema_is_refused(fake_connect):
    import psycopg2

    with pytest.raises(G.SharedRegistryAccessError):
        psycopg2.connect(SHARED)
    with pytest.raises(G.SharedRegistryAccessError):
        psycopg2.connect(host="localhost", port=5442, dbname="egeria_advisor",
                         options="-csearch_path=resource_explorer")
    assert fake_connect == []


def test_temp_sqlite_registry_passes(fake_connect, tmp_path):
    from resource_explorer.registry import ProjectRegistry

    reg = ProjectRegistry(database_url=f"sqlite:///{tmp_path}/r.db")
    assert reg.database_url.startswith("sqlite:///")
    assert fake_connect == []


def test_per_test_postgres_schema_on_a_test_database_passes(fake_connect):
    with pytest.raises(_Reached):        # the fake was reached, not the guard
        _open(TEST_SCHEMA)
    assert len(fake_connect) == 1


def test_other_host_or_database_passes(fake_connect):
    for url in (
        "postgresql://u:p@db.internal:5442/egeria_advisor",
        "postgresql://u:p@localhost:5999/egeria_advisor",
        "postgresql://u:p@localhost:5442/scratch",
    ):
        with pytest.raises(_Reached):
            _open(url)


def test_opt_in_env_var_lets_it_through(fake_connect, monkeypatch):
    monkeypatch.setenv(G.ALLOW_ENV, "1")
    with pytest.raises(_Reached):
        _open(SHARED)


def test_github_actions_service_container_is_exempt(fake_connect, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(_Reached):
        _open(SHARED)


def test_cached_config_pointing_at_the_shared_dsn_is_caught(fake_connect, monkeypatch, tmp_path):
    """The incident: config cached with the shared URL, env var ignored."""
    import resource_explorer.config as config
    from resource_explorer.registry import ProjectRegistry

    monkeypatch.delenv("REGISTRY_DATABASE_URL", raising=False)
    cached = config.ExplorerConfig()
    cached.registry.database_url = SHARED
    monkeypatch.setattr(config, "_config", cached)
    # The fixture's env var is ignored because the config is already cached.
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite:///{tmp_path}/ignored.db")
    ProjectRegistry._pg_schema_ready.discard(SHARED)
    ProjectRegistry._pg_engine_cache.pop(SHARED, None)
    with pytest.raises(G.SharedRegistryAccessError):
        ProjectRegistry()
    assert fake_connect == []


def test_conftest_resets_the_cached_config_between_tests(monkeypatch):
    import resource_explorer.config as config

    assert config._config is None
    monkeypatch.setenv("REGISTRY_DATABASE_URL", "sqlite:///from_env.db")
    assert config.get_config().registry.database_url == "sqlite:///from_env.db"


def test_shared_instance_is_derived_from_declared_defaults(monkeypatch):
    monkeypatch.setenv("PGVECTOR_PORT", "1")        # ambient env cannot move it
    assert (5442, "egeria_advisor") in G.shared_instances()


def test_default_config_without_env_file_fails_closed(fake_connect, monkeypatch):
    """The 2026-10-05 scenario: a worktree has no .env and no env var, so the
    declared DEFAULT (the shared Postgres) is what ProjectRegistry() resolves.
    The guard must refuse at connect, before the schema migration runs."""
    import resource_explorer.config as config
    from resource_explorer.registry import ProjectRegistry

    monkeypatch.delenv("REGISTRY_DATABASE_URL", raising=False)
    monkeypatch.setitem(config.RegistryConfig.model_config, "env_file", None)
    monkeypatch.setattr(config, "_config", None)
    url = config.get_config().registry.database_url
    assert "localhost:5442/egeria_advisor" in url            # really the default
    ProjectRegistry._pg_schema_ready.discard(url)
    ProjectRegistry._pg_engine_cache.pop(url, None)
    with pytest.raises(G.SharedRegistryAccessError) as exc:
        ProjectRegistry()                                    # no args, as a command does
    assert fake_connect == []
    assert url not in ProjectRegistry._pg_schema_ready       # never reached migration
