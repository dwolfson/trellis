"""Env beats advisor.yaml for the vector store's Postgres connection (trevor, 2026-09-04)."""
from advisor.vector_store import resolve_pgvector_kwargs


def test_env_wins_over_yaml(monkeypatch):
    monkeypatch.setenv("PGVECTOR_HOST", "egeria-shared-postgres")
    monkeypatch.setenv("PGVECTOR_PORT", "5442")
    kw = resolve_pgvector_kwargs({"host": "localhost", "port": 5433})
    assert kw["host"] == "egeria-shared-postgres"
    assert kw["port"] == 5442


def test_yaml_used_when_env_unset(monkeypatch):
    monkeypatch.delenv("PGVECTOR_HOST", raising=False)
    kw = resolve_pgvector_kwargs({"host": "yaml-host"})
    assert kw["host"] == "yaml-host"


def test_empty_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv("PGVECTOR_HOST", "")
    kw = resolve_pgvector_kwargs({"host": "yaml-host"})
    assert kw["host"] == "yaml-host"
