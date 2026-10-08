"""A SolutionBlueprint's Egeria identity is KIND + REPOSITORY, never the root cluster's name.

Architect's ruling 2026-10-08 (docs/design-notes/DESIGN-BLUEPRINT-NAMING-WHAT-IT-REPRESENTS.md §2a):
`SolutionBlueprint::<type>::<slug>::<kind>[::<identifier>]`, the identifier a person's and only for a second
blueprint of one kind; the two older forms (carrying the cluster name) are adopted, never created. Recording
fakes for Egeria; a temp SQLite registry; nothing live.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resource_explorer import blueprint_kinds as bk
from resource_explorer.registry import ProjectRegistry
from resource_explorer.surveyors.arch_recovery.blueprint_materializer import (
    BlueprintIdentifierNeeded,
    BlueprintMaterializationError,
    BlueprintMaterializer,
)

NEW = "11111111-1111-1111-1111-111111111111"
OLD = "22222222-2222-2222-2222-222222222222"
ROOT = "OMAG-Server-Platform"
LEGACY_556 = f"SolutionBlueprint::repo::egeria_git::Deployment Blueprint::{ROOT}"
LEGACY_PRE = f"SolutionBlueprint::repo::egeria_git::deployment::{ROOT}"
SENTENCE = "a Deployment Blueprint already exists for egeria_git · give this one an identifier"


@pytest.fixture
def reg(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


def _m(reg, found=None, search_error=None):
    m = BlueprintMaterializer(platform_url="https://fake", registry=reg)
    m._solution_architect = MagicMock()
    m._automated_curation = MagicMock()
    m._connect = MagicMock()
    searched = []

    def find(qn):
        searched.append(qn)
        if search_error:
            raise search_error
        return [(found or {})[qn]] if qn in (found or {}) else []

    m._automated_curation.get_guid_for_name.side_effect = find
    m._solution_architect.create_solution_blueprint.return_value = NEW
    m.searched = searched
    return m


def _created(m):
    return [c[0][0]["properties"] for c in m._solution_architect.create_solution_blueprint.call_args_list]


def _make(m, cluster=ROOT, **kw):
    return m.materialize_blueprint_element("repo", "egeria_git", "deployment", cluster,
                                           display_name="Egeria Deployment Blueprint", **kw)


def _activity(reg):
    return [a["summary"] for a in reg.list_activity(entity_type="repo", entity_slug="egeria_git")]


def test_a_deployment_blueprint_is_kind_and_repository_with_the_owners_identifier():
    m = _m(MagicMock(get_materialized_blueprint=MagicMock(return_value=None)))
    out = _make(m)
    props = _created(m)[0]
    assert out["qualified_name"] == props["qualifiedName"] == "SolutionBlueprint::repo::egeria_git::deployment"
    assert props["identifier"] == "EGERIA-GIT-DEPLOYMENT"


def test_a_second_blueprint_of_a_kind_without_an_identifier_is_refused_and_creates_nothing(reg):
    first = _m(reg)
    _make(first, cluster=ROOT)
    m = _m(reg)
    with pytest.raises(BlueprintIdentifierNeeded) as exc:
        _make(m, cluster="web")
    assert str(exc.value) == SENTENCE
    assert _created(m) == [] and m.searched == []
    m._connect.assert_not_called()


def test_a_second_blueprint_with_an_identifier_creates_the_fifth_segment_and_never_the_cluster_name(reg):
    _make(_m(reg), cluster=ROOT)
    m = _m(reg)
    out = _make(m, cluster="web", identifier="  Servers ")
    props = _created(m)[0]
    assert out["qualified_name"] == "SolutionBlueprint::repo::egeria_git::deployment::Servers"
    assert props["identifier"] == "EGERIA-GIT-DEPLOYMENT-SERVERS"
    assert "web" not in props["qualifiedName"]
    # both blueprints are cached, each under its own identity, the cluster name kept on the row
    rows = reg.get_materialized_blueprints("repo", "egeria_git")
    assert {r["qualified_name"] for r in rows.values()} == {
        "SolutionBlueprint::repo::egeria_git::deployment",
        "SolutionBlueprint::repo::egeria_git::deployment::Servers"}
    assert rows["deployment::web"]["cluster_name"] == "web"


def test_an_identifier_already_in_use_is_refused(reg):
    _make(_m(reg), cluster=ROOT)
    _make(_m(reg), cluster="web", identifier="Servers")
    m = _m(reg)
    with pytest.raises(BlueprintMaterializationError, match="already used"):
        _make(m, cluster="db", identifier="Servers")
    assert _created(m) == []


def test_a_row_for_a_cluster_that_no_longer_exists_is_taken_over_not_a_second_blueprint(reg):
    _make(_m(reg), cluster=ROOT)
    m = _m(reg)
    out = _make(m, cluster="renamed", live_clusters={"renamed"})
    assert out["qualified_name"] == "SolutionBlueprint::repo::egeria_git::deployment"
    assert set(reg.get_materialized_blueprints("repo", "egeria_git")) == {"deployment::renamed"}


@pytest.mark.parametrize("legacy", [LEGACY_556, LEGACY_PRE], ids=["556-form", "pre-556-form"])
def test_a_legacy_named_blueprint_is_adopted_not_duplicated_and_the_owner_is_told(reg, legacy):
    m = _m(reg, found={legacy: OLD})
    out = _make(m)
    assert out == {"status": "already_materialized", "guid": OLD, "qualified_name": legacy}
    assert _created(m) == []
    assert _activity(reg) == [f"adopted legacy-named blueprint {OLD} · delete it in Egeria to recreate "
                              "under the new name"]
    assert reg.get_materialized_blueprint("repo", "egeria_git", "deployment", ROOT)["qualified_name"] == legacy


def test_the_new_name_is_searched_first_and_wins_over_a_legacy_one(reg):
    m = _m(reg, found={"SolutionBlueprint::repo::egeria_git::deployment": NEW, LEGACY_556: OLD})
    assert _make(m)["guid"] == NEW and _activity(reg) == []


@pytest.mark.parametrize("failing", ["search", "legacy-search"])
def test_an_unreadable_search_still_raises_and_creates_nothing(reg, failing):
    m = _m(reg)
    if failing == "search":
        m._automated_curation.get_guid_for_name.side_effect = RuntimeError("503")
    else:
        def find(qn):
            if qn == LEGACY_PRE:
                raise RuntimeError("503")
            return []
        m._automated_curation.get_guid_for_name.side_effect = find
    with pytest.raises(BlueprintMaterializationError, match="nothing was created"):
        _make(m)
    assert _created(m) == []


def test_a_cached_legacy_row_is_read_through_the_mapping_and_adopted(reg):
    reg.record_materialized_blueprint("repo", "egeria_git", "deployment", ROOT, LEGACY_556, OLD)
    m = _m(reg)
    out = _make(m)
    assert out == {"status": "already_materialized", "guid": OLD, "qualified_name": LEGACY_556}
    m._connect.assert_not_called()
    assert _created(m) == [] and len(_activity(reg)) == 1


def test_a_legacy_row_does_not_count_as_a_blueprint_of_the_kind_for_a_different_cluster(reg):
    reg.record_materialized_blueprint("repo", "egeria_git", "deployment", ROOT, LEGACY_556, OLD)
    m = _m(reg)
    assert _make(m, cluster="web")["qualified_name"] == "SolutionBlueprint::repo::egeria_git::deployment"


def test_no_qualified_name_created_contains_a_cluster_root_name(reg):
    ms = [_m(reg), _m(reg)]
    _make(ms[0], cluster=ROOT)
    _make(ms[1], cluster="OMAG-Server-Platform-2", identifier="second")
    for m in ms:
        for props in _created(m):
            assert "OMAG" not in props["qualifiedName"] and "OMAG" not in props["identifier"]


@pytest.mark.parametrize("bad", ["a::b", "   ", "-lead", "x" * 65, "semi;colon"])
def test_a_bad_identifier_is_refused_before_anything_happens(reg, bad):
    m = _m(reg)
    with pytest.raises(BlueprintMaterializationError, match="nothing was created"):
        _make(m, identifier=bad)
    assert _created(m) == [] and m.searched == []


def test_identifier_validation_trims():
    assert bk.validate_identifier("  Runtimes ") == "Runtimes" and bk.validate_identifier("") == ""


def test_the_accept_pane_is_told_to_ask_only_when_another_live_cluster_holds_the_identity(reg):
    from resource_explorer.registry import Project
    from resource_explorer.surveyors.repo_survey_definition_adapter import _candidate_blueprints_results
    reg.add(Project(slug="egeria_git", display_name="egeria_git", github_url="https://github.com/o/e"))
    reg.upsert_finding("egeria_git", "architecture_blueprints", [
        {"check_name": "candidate_blueprint", "label": n,
         "detail": {"name": n, "perspective": "deployment", "members": [], "children": [], "parent": "",
                    "oversized": False}} for n in (ROOT, "web")], surveyed_at="2026-10-01T00:00:00")
    ids = lambda: {b["cluster_name"]: b["identity"] for b in _candidate_blueprints_results(reg, "egeria_git")}  # noqa: E731
    assert not ids()[ROOT]["needs_identifier"] and not ids()["web"]["needs_identifier"]
    _make(_m(reg), cluster=ROOT)
    got = ids()
    assert not got[ROOT]["needs_identifier"]            # its own blueprint: nothing to ask
    assert got["web"]["needs_identifier"] and got["web"]["sentence"] == SENTENCE
