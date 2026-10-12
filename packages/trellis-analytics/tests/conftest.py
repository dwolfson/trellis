import sqlite3
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def entry_point_dist(tmp_path, monkeypatch):
    """A dist-info built from the package's own pyproject entry-points, so the declared entry point is what's tested."""
    eps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["entry-points"]["trellis.analytics"]
    d = tmp_path / "trellis_analytics_fixture-0.1.0.dist-info"
    d.mkdir()
    (d / "METADATA").write_text("Metadata-Version: 2.1\nName: trellis-analytics-fixture\nVersion: 0.1.0\n")
    (d / "entry_points.txt").write_text(
        "[trellis.analytics]\n" + "".join(f"{k} = {v}\n" for k, v in eps.items()))
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


DDL = """
CREATE TABLE database_tables (id INTEGER PRIMARY KEY, database_slug TEXT, surveyed_at TEXT, schema_name TEXT, table_name TEXT);
CREATE TABLE catalogue_commit_proofs (id INTEGER PRIMARY KEY, database_slug TEXT, node_kind TEXT, schema_name TEXT,
  table_name TEXT, proof TEXT, element_guid TEXT, read_at TEXT, detail_json TEXT);
CREATE TABLE catalogue_scope_events (id INTEGER PRIMARY KEY, database_slug TEXT, node_kind TEXT, schema_name TEXT,
  table_name TEXT, choice TEXT, action TEXT, source TEXT, proposal_rule TEXT, changed_at TEXT);
CREATE TABLE resource_scope_events (id INTEGER PRIMARY KEY, resource_type TEXT, resource_slug TEXT, locator TEXT,
  kind TEXT, choice TEXT, action TEXT, source TEXT, proposal_rule TEXT, changed_at TEXT);
CREATE TABLE egeria_outbox (id INTEGER PRIMARY KEY, entity_type TEXT, entity_slug TEXT, status TEXT);
"""


@pytest.fixture
def make_ods(tmp_path):
    """Build a scratch SQLite registry (never the real one) and return its path."""
    def build(slug="demo", schemas=(), proofs=(), events=(), outbox=()):
        path = tmp_path / "ods.sqlite"
        c = sqlite3.connect(path)
        c.executescript(DDL)
        for s in schemas:
            c.execute("INSERT INTO database_tables (database_slug, surveyed_at, schema_name, table_name) VALUES (?,?,?,?)",
                      (slug, "2026-10-01T00:00:00Z", s, "t"))
        for p in proofs:   # (node_kind, schema, proof, read_at, detail_json)
            c.execute("INSERT INTO catalogue_commit_proofs (database_slug,node_kind,schema_name,table_name,proof,element_guid,read_at,detail_json)"
                      " VALUES (?,?,?,?,?,?,?,?)", (slug, p[0], p[1], "", p[2], "g", p[3], p[4]))
        for e in events:   # (schema, choice, source)
            c.execute("INSERT INTO catalogue_scope_events (database_slug,node_kind,schema_name,table_name,choice,action,source,proposal_rule,changed_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?)", (slug, "schema", e[0], "", e[1], "set", e[2], "", "2026-10-02T00:00:00Z"))
        for st in outbox:
            c.execute("INSERT INTO egeria_outbox (entity_type, entity_slug, status) VALUES ('database',?,?)", (slug, st))
        c.commit()
        c.close()
        return f"sqlite:///{path}"
    return build
