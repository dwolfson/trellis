"""PI-072: component search in the Curate tree reads every component at once.

`/components/leaves?branch=` named one branch; the empty branch (the root, as `/components/tree?prefix=`
already treats it) returned nothing, so a search had no whole-repository list to look in. The root is
now every component, from the SAME function that returns one branch's, so a hit in a search and the
row in its branch cannot disagree."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.component_tree import leaves
from resource_explorer.registry import Project, ProjectRegistry

COMPS = [
    {"path": "pyegeria", "name": "pyegeria", "type": "Software Library", "confidence": 80,
     "proposals": [{"perspective": "physical", "run_label": "detect", "confidence": 80}]},
    {"path": "pyegeria/commands", "name": "commands", "type": "Console Command", "confidence": 70,
     "proposals": [{"perspective": "logical", "run_label": "coupling", "confidence": 70}]},
    {"path": "server", "name": "hive-server", "type": "Long Running Daemon", "confidence": 90},
    {"path": "", "name": "root", "type": "", "confidence": 0},
    {"path": "build", "name": "build", "type": "", "confidence": 0, "structural": True},
]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p", description=""))
    monkeypatch.setattr("resource_explorer.component_tree._components", lambda reg, slug: [dict(c) for c in COMPS])
    return r


def test_the_root_branch_is_every_component_and_a_branch_is_unchanged(registry):
    every = leaves(registry, "p", "")
    assert [l["path"] for l in every] == ["pyegeria", "pyegeria/commands", "server"]   # no grouping node, no pathless row
    assert [l["path"] for l in leaves(registry, "p", "pyegeria")] == ["pyegeria", "pyegeria/commands"]
    # the rows are the branch rows, byte for byte
    by = {l["path"]: l for l in every}
    assert by["pyegeria/commands"] == next(l for l in leaves(registry, "p", "pyegeria") if l["path"] == "pyegeria/commands")


def test_the_route_serves_the_root(registry, monkeypatch):
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    from resource_explorer.web.app import app
    out = TestClient(app).get("/api/projects/p/components/leaves", params={"branch": ""}).json()
    assert [l["path"] for l in out["leaves"]] == ["pyegeria", "pyegeria/commands", "server"]
