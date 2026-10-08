"""The blueprint cache keyed by Egeria identity, on the real Postgres registry (pg tier, run by CI).

architecture_materialized_blueprints is a CACHE of Egeria elements, not a proof or a decision: re-recording
under the same qualifiedName replaces the stale row, and proof rows are never deleted. Each test uses its own
project slug (the pg schema is shared within a session).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_pgvector

G1 = "11111111-1111-1111-1111-111111111111"
G2 = "22222222-2222-2222-2222-222222222222"
G3 = "33333333-3333-3333-3333-333333333333"


def _qn(slug, tail="deployment"):
    return f"SolutionBlueprint::repo::{slug}::{tail}"


def test_two_blueprints_are_read_back_by_identity_and_unknown_is_none(pg_registry):
    slug = "bpid_pg_read"
    pg_registry.record_materialized_blueprint("repo", slug, "deployment", "root", _qn(slug), G1)
    pg_registry.record_materialized_blueprint("repo", slug, "deployment", "web", _qn(slug, "deployment::Servers"), G2)
    one = pg_registry.get_materialized_blueprint_by_identity("repo", slug, _qn(slug))
    two = pg_registry.get_materialized_blueprint_by_identity("repo", slug, _qn(slug, "deployment::Servers"))
    assert (one["guid"], one["cluster_name"]) == (G1, "root")
    assert (two["guid"], two["cluster_name"]) == (G2, "web")
    assert pg_registry.get_materialized_blueprint_by_identity("repo", slug, _qn(slug, "build")) is None


def test_re_recording_under_the_same_identity_rekeys_the_row_and_keeps_two(pg_registry):
    slug = "bpid_pg_rekey"
    pg_registry.record_materialized_blueprint("repo", slug, "deployment", "root", _qn(slug), G1)
    pg_registry.record_materialized_blueprint("repo", slug, "deployment", "web", _qn(slug, "deployment::Servers"), G2)
    pg_registry.record_materialized_blueprint("repo", slug, "deployment", "root-renamed", _qn(slug), G1)
    rows = pg_registry.get_materialized_blueprints("repo", slug)
    assert set(rows) == {"deployment::root-renamed", "deployment::web"}
    assert pg_registry.get_materialized_blueprint_by_identity("repo", slug, _qn(slug))["cluster_name"] == "root-renamed"


def test_another_slugs_row_under_the_same_qualified_name_is_untouched(pg_registry):
    mine, other = "bpid_pg_mine", "bpid_pg_other"
    shared = "SolutionBlueprint::repo::shared::deployment"
    pg_registry.record_materialized_blueprint("repo", other, "deployment", "c", shared, G3)
    pg_registry.record_materialized_blueprint("repo", mine, "deployment", "c", shared, G1)
    pg_registry.record_materialized_blueprint("repo", mine, "deployment", "c2", shared, G2)
    assert pg_registry.get_materialized_blueprint_by_identity("repo", other, shared)["guid"] == G3
    assert pg_registry.get_materialized_blueprint_by_identity("repo", mine, shared)["guid"] == G2


def test_re_recording_returns_the_cluster_it_displaced(pg_registry):
    slug = "bpid_pg_displaced"
    first = pg_registry.record_materialized_blueprint("repo", slug, "deployment", "web", _qn(slug), G1)
    assert first["displaced"] == []
    second = pg_registry.record_materialized_blueprint("repo", slug, "deployment", "db", _qn(slug), G1)
    assert second["displaced"] == ["web"]
    again = pg_registry.record_materialized_blueprint("repo", slug, "deployment", "db", _qn(slug), G1)
    assert again["displaced"] == []
