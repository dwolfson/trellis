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
    BlueprintAmbiguous,
    BlueprintIdentifierNeeded,
    BlueprintMaterializationError,
    BlueprintMaterializer,
)

NEW = "11111111-1111-1111-1111-111111111111"
OLD = "22222222-2222-2222-2222-222222222222"
G_WEB = "44444444-4444-4444-4444-444444444444"
ROOT = "OMAG-Server-Platform"
LEGACY_556 = f"SolutionBlueprint::repo::egeria_git::Deployment Blueprint::{ROOT}"
LEGACY_PRE = f"SolutionBlueprint::repo::egeria_git::deployment::{ROOT}"
SENTENCE = "a Deployment Blueprint already exists for egeria_git · give this one an identifier"


@pytest.fixture
def reg(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


DISPLAY = "Egeria Deployment Blueprint"


def _element(qn, guid, display=DISPLAY, props=None, type_name="SolutionBlueprint"):
    return {"elementHeader": {"guid": guid, "type": {"typeName": type_name}},
            "properties": {"qualifiedName": qn, "displayName": display, "additionalProperties": props or {}}}


def _m(reg, found=None, search_error=None):
    """`found`: qn -> guid, or qn -> {"guid", "display", "props", "type"} for an element with a displayName and
    provenance. The recording fake answers the search AND the read-back by guid."""
    m = BlueprintMaterializer(platform_url="https://fake", registry=reg)
    m._solution_architect = MagicMock()
    m._automated_curation = MagicMock()
    m._connect = MagicMock()
    searched = []
    entries = {qn: (v if isinstance(v, dict) else {"guid": v}) for qn, v in (found or {}).items()}

    def find(qn, property_name=None, type_name=None):
        searched.append((qn, property_name, type_name))
        if search_error:
            raise search_error
        return [entries[qn]["guid"]] if qn in entries else []

    def read(guid):
        for qn, e in entries.items():
            if e["guid"] == guid:
                return _element(qn, guid, e.get("display", DISPLAY), e.get("props"), e.get("type", "SolutionBlueprint"))
        return "no elements"

    m._automated_curation.get_guid_for_name.side_effect = find
    m._solution_architect.get_solution_blueprint_by_guid.side_effect = read
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
    row = reg.list_activity(entity_type="repo", entity_slug="egeria_git")[0]
    assert row["entity_name"] == DISPLAY and row["entity_location"] == legacy    # on the repository's feed
    assert reg.get_materialized_blueprint("repo", "egeria_git", "deployment", ROOT)["qualified_name"] == legacy
    _make(_m(reg, found={legacy: OLD}))                      # a re-accept (cache hit) logs nothing more
    with reg._conn() as conn:                                # a cleared row, adopted again by search
        conn.execute("DELETE FROM architecture_materialized_blueprints")
    _make(_m(reg, found={legacy: OLD}))
    assert len(_activity(reg)) == 1                          # logged once per adoption, not per hit


def test_the_new_name_is_searched_first_and_wins_over_a_legacy_one(reg):
    m = _m(reg, found={"SolutionBlueprint::repo::egeria_git::deployment": NEW, LEGACY_556: OLD})
    assert _make(m)["guid"] == NEW and not any("legacy" in x for x in _activity(reg))


@pytest.mark.parametrize("failing", ["search", "legacy-search"])
def test_an_unreadable_search_still_raises_and_creates_nothing(reg, failing):
    m = _m(reg)
    if failing == "search":
        m._automated_curation.get_guid_for_name.side_effect = RuntimeError("503")
    else:
        def find(qn, **kw):
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
    assert _created(m) == [] and _activity(reg) == []    # logged when adopted, not on every cache hit


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


# ── provenance: the primary adoption rule; the displayName is the fallback ───────────────────────────────

BASE = "SolutionBlueprint::repo::egeria_git::deployment"


def _prov(cluster, **extra):
    return {"re_entity_type": "repo", "re_slug": "egeria_git", "re_kind": "deployment",
            "re_cluster_key": cluster, "re_version": "1", **extra}


def _activity_rows(reg):
    return reg.list_activity(entity_type="repo", entity_slug="egeria_git")


def test_a_created_blueprint_carries_the_provenance_keys_and_re_identifier_only_when_given(reg):
    first = _m(reg)
    _make(first, cluster=ROOT)
    assert _created(first)[0]["additionalProperties"] == {
        "recoveredBy": "architecture_recovery", "re_entity_type": "repo", "re_slug": "egeria_git",
        "re_kind": "deployment", "re_cluster_key": ROOT, "re_version": "1"}
    second = _m(reg)
    _make(second, cluster="web", identifier="Servers")
    extra = _created(second)[0]["additionalProperties"]
    assert extra["re_identifier"] == "Servers" and extra["re_cluster_key"] == "web"


def test_a_cleared_row_with_this_clusters_provenance_is_adopted_and_the_row_rewritten(reg):
    m = _m(reg, found={BASE: {"guid": OLD, "display": "renamed since", "props": _prov(ROOT)}})
    out = _make(m)
    assert out == {"status": "already_materialized", "guid": OLD, "qualified_name": BASE}
    assert _created(m) == []
    row = reg.get_materialized_blueprint("repo", "egeria_git", "deployment", ROOT)
    assert (row["guid"], row["qualified_name"]) == (OLD, BASE)
    assert any("adopted blueprint" in s and OLD in s for s in _activity(reg))


def test_provenance_naming_another_cluster_refuses_and_attaches_nothing(reg):
    m = _m(reg, found={BASE: {"guid": OLD, "props": _prov("web")}})
    with pytest.raises(BlueprintIdentifierNeeded) as exc:
        _make(m, cluster=ROOT)
    assert str(exc.value) == (f"an element named {BASE} already exists in Egeria for another cluster (web) "
                              "· give this one an identifier")
    assert _created(m) == [] and reg.get_materialized_blueprints("repo", "egeria_git") == {}
    assert any("refused to adopt" in s and OLD in s for s in _activity(reg))


def test_provenance_naming_another_cluster_with_an_identifier_given_says_a_different_one(reg):
    m = _m(reg, found={f"{BASE}::Servers": {"guid": OLD, "props": _prov("web")}})
    with pytest.raises(BlueprintMaterializationError, match="different identifier"):
        _make(m, cluster=ROOT, identifier="Servers")
    assert _created(m) == []


def test_no_provenance_and_a_lost_row_adopts_only_for_the_cluster_whose_displayName_it_is(reg, tmp_path):
    elem = {"guid": OLD, "display": DISPLAY}
    # A's row is lost and A accepts: its displayName is the element's -> adopted
    a = _m(reg, found={BASE: elem})
    assert _make(a, cluster=ROOT)["guid"] == OLD and _created(a) == []
    # a fresh registry: B accepts, its displayName differs -> refused, nothing attached or created
    b_reg = ProjectRegistry(db_path=str(tmp_path / "b.db"))
    b = _m(b_reg, found={BASE: elem})
    with pytest.raises(BlueprintIdentifierNeeded) as exc:
        b.materialize_blueprint_element("repo", "egeria_git", "deployment", "web",
                                        display_name=DISPLAY + " · web")
    assert str(exc.value) == (f"an element named {BASE} already exists in Egeria and RE cannot tell which cluster "
                              "it is for · give this one an identifier")
    assert _created(b) == []


def test_no_provenance_with_another_clusters_row_recording_the_name_is_refused_even_if_the_name_matches(reg):
    reg.record_materialized_blueprint("repo", "egeria_git", "deployment", "web", BASE, G_WEB)
    m = _m(reg, found={BASE: {"guid": G_WEB, "display": DISPLAY}})
    with pytest.raises(BlueprintIdentifierNeeded):
        _make(m, cluster=ROOT, live_clusters={"web"})
    assert _created(m) == []


def test_a_renamed_cluster_is_not_silently_given_the_old_clusters_element(reg):
    reg.record_materialized_blueprint("repo", "egeria_git", "deployment", ROOT, BASE, OLD)
    with_prov = _m(reg, found={BASE: {"guid": OLD, "props": _prov(ROOT)}})
    with pytest.raises(BlueprintIdentifierNeeded, match=r"for another cluster \(OMAG-Server-Platform\)"):
        _make(with_prov, cluster="OMAG-renamed", live_clusters={"OMAG-renamed"})
    without = _m(reg, found={BASE: {"guid": OLD, "display": DISPLAY}})
    with pytest.raises(BlueprintIdentifierNeeded, match="cannot tell which cluster"):
        _make(without, cluster="OMAG-renamed", live_clusters={"OMAG-renamed"})
    assert _created(with_prov) == [] and _created(without) == []


# ── the search is typed and verified ─────────────────────────────────────────────────────────────────────


def test_the_search_is_restricted_to_qualified_name_and_the_blueprint_type(reg):
    m = _m(reg)
    _make(m)
    assert m.searched[0] == (BASE, ["qualifiedName"], "SolutionBlueprint")


class _Multi(Exception):
    pass


def test_more_than_one_hit_is_ambiguous_not_a_search_failure(reg):
    m = _m(reg, search_error=_Multi("Multiple elements found for supplied name!"))
    with pytest.raises(BlueprintAmbiguous, match="ambiguous"):
        _make(m)
    assert _created(m) == []
    m2 = _m(reg)
    m2._automated_curation.get_guid_for_name.side_effect = lambda qn, **kw: [OLD, NEW]
    with pytest.raises(BlueprintAmbiguous, match="ambiguous"):
        _make(m2)
    assert _created(m2) == []


def test_a_hit_of_another_type_or_another_qualified_name_is_not_adopted_and_nothing_is_created(reg):
    wrong_type = _m(reg, found={BASE: {"guid": OLD, "type": "SolutionComponent"}})
    with pytest.raises(BlueprintMaterializationError, match="not that SolutionBlueprint"):
        _make(wrong_type)
    other_qn = _m(reg)
    other_qn._automated_curation.get_guid_for_name.side_effect = lambda qn, **kw: [OLD]
    other_qn._solution_architect.get_solution_blueprint_by_guid.side_effect = lambda g: _element("x::other", g)
    with pytest.raises(BlueprintMaterializationError, match="not that SolutionBlueprint"):
        _make(other_qn)
    assert _created(wrong_type) == [] and _created(other_qn) == []


# ── displaced rows, and identifiers that give the same Egeria identifier ────────────────────────────────


def test_re_keying_a_row_names_the_cluster_it_displaced(reg):
    out = reg.record_materialized_blueprint("repo", "egeria_git", "deployment", "web", BASE, OLD)
    assert out["displaced"] == []
    out = reg.record_materialized_blueprint("repo", "egeria_git", "deployment", "db", BASE, OLD)
    assert out["displaced"] == ["web"]
    m = _m(reg, found={BASE: {"guid": OLD, "props": _prov("web")}})
    _make(m, cluster="web", live_clusters={"web"})   # rewrites web's row, displacing db's
    assert any("displaced" in s and "'db'" in s for s in _activity(reg))


@pytest.mark.parametrize("first,second", [("a b", "a-b"), ("Servers", "servers"), ("x.y", "X_Y")])
def test_two_identifiers_that_give_the_same_egeria_identifier_are_refused(reg, first, second):
    _make(_m(reg), cluster=ROOT)
    _make(_m(reg), cluster="web", identifier=first)
    m = _m(reg)
    with pytest.raises(BlueprintMaterializationError, match="already used"):
        _make(m, cluster="db", identifier=second)
    assert _created(m) == []
