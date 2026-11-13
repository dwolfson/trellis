"""EA's elicitor uses functional status, not element status (EA_SPEC_AUTHORING_V2 + EA_SPEC_ELICITOR_FIXES).

The owner, 2026-11-13: "Make sure EA's elicitor uses functional status". Status words ("draft", "active",
"in development") are a `functional_status` condition on the grounded type's own property, found by walking
its supertypes, filtered on the server by a finder that takes it. A value the property doesn't take is
`unmet`, in words. No status word ever reaches Egeria as `limitResultsByStatus` (laz quiet run 31e359c5:
B02 a no-op, B05/B10/B11/B15/H05 400s).

Offline: a fake LLM, temp stores, and pyegeria's real client classes, executor and preview with only the
HTTP transport faked. Needs pyegeria with `pyegeria.authoring`.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("pyegeria.authoring")

from advisor import spec_authoring_v2 as v2  # noqa: E402


@pytest.fixture
def stores(tmp_path, monkeypatch):
    import advisor.report_draft as rd
    import advisor.report_spec_docs as rsd

    def _drafts():
        p = tmp_path / "drafts"
        p.mkdir(parents=True, exist_ok=True)
        return p
    monkeypatch.setattr(rd, "_drafts_path", _drafts)
    monkeypatch.setattr(rsd, "_load_paths", lambda: {k: tmp_path / k for k in ("inbox", "outbox", "trash", "versions")})
    return tmp_path


@pytest.fixture
def fixes_on(monkeypatch):
    monkeypatch.setenv(v2.FLAG, "1")
    monkeypatch.setenv(v2.FIXES_FLAG, "1")


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _llm(monkeypatch, *replies):
    fake = FakeLLM(*[r if isinstance(r, str) else json.dumps(r) for r in replies])
    monkeypatch.setattr("advisor.agents.report_spec_elicitor_v2.get_planning_llm", lambda: fake)
    monkeypatch.setattr("advisor.agents.report_spec_elicitor.get_planning_llm", lambda: fake)
    return fake


def _elicit(monkeypatch, question, target, words, legacy=False):
    """Run the elicitor on `question` with an LLM that proposes `target` and the status `words`."""
    from advisor.agents.report_spec_elicitor import ReportSpecElicitor
    from advisor.report_draft import get_report_draft_manager
    key = v2.LEGACY_STATUS_PARAM if legacy else "functional_status"
    _llm(monkeypatch, {"title": "t", "heading": "H", "description": "d", "target_type": target,
                       "conditions": {key: words}, "columns": [{"name": "Name", "key": "display_name"}]})
    r = ReportSpecElicitor().start(question)
    return r, get_report_draft_manager().load(r["draft_id"])


def _sent_params(spec):
    return v2.build_format_set(spec).action.spec_params


# ── the read-back's proof cases ──────────────────────────────────────────────

@pytest.mark.parametrize("question, target, words, prop, values, finder, column", [
    ("Which glossary terms are still in draft status?", "GlossaryTerm", ["draft"], "contentStatus", ["DRAFT"],
     "ClassificationExplorer.find_authored_elements", "content_status"),
    ("Which products are still in development?", "DigitalProduct", ["in development"], "deploymentStatus",
     ["UNDER_DEVELOPMENT"], "CollectionManager.find_digital_products", "deployment_status"),
    ("What projects are currently active?", "Project", ["active"], "projectStatus", ["Active"],
     "ClassificationExplorer.find_elements_by_property_value", "project_status"),
    ("Which processes failed?", "Process", ["FAILED"], "activityStatus", ["FAILED"],
     "AssetMaker.find_processes", "activity_status"),
    ("Which governance policies are active and approved?", "GovernancePolicy", ["ACTIVE", "APPROVED"],
     "contentStatus", ["ACTIVE", "APPROVED"], "ClassificationExplorer.find_authored_elements", "content_status"),
    ("Which governance rules are still in draft?", "GovernanceRule", ["draft"], "contentStatus", ["DRAFT"],
     "ClassificationExplorer.find_authored_elements", "content_status"),
])
@pytest.mark.parametrize("legacy", [False, True])
def test_status_words_become_the_types_own_status(fixes_on, stores, monkeypatch, question, target, words,
                                                  prop, values, finder, column, legacy):
    r, spec = _elicit(monkeypatch, question, target, words, legacy=legacy)
    status = spec["conditions"]["functional_status"]
    assert (status["property"], status["values"]) == (prop, values)
    assert spec["action_function"] == finder and finder in r["response"]
    assert column in [c["key"] for c in spec["columns"]]          # the filter is visible as a column
    assert prop in r["response"] and not spec.get("unmet")
    params = _sent_params(spec)
    assert v2.LEGACY_STATUS_PARAM not in params and "limit_results_by_status" not in params


def test_a_value_the_types_status_does_not_take_is_unmet_in_words(fixes_on, stores, monkeypatch):
    r, spec = _elicit(monkeypatch, "Which processes are still in draft?", "Process", ["draft"])
    assert "functional_status" not in spec["conditions"]
    assert spec["unmet"].startswith("Processes have no 'draft' status; their statuses are activityStatus: ")
    assert "Not applied:** Processes have no 'draft' status" in r["response"]
    assert v2.LEGACY_STATUS_PARAM not in _sent_params(spec)       # never falls back to the element status


def test_a_type_with_no_status_of_its_own_is_unmet(fixes_on, stores, monkeypatch):
    r, spec = _elicit(monkeypatch, "Which teams are active?", "Team", ["active"])
    assert "functional_status" not in spec["conditions"]
    assert "Teams have no status of their own" in spec["unmet"]
    assert v2.LEGACY_STATUS_PARAM not in _sent_params(spec)


def test_draft_projects_is_projects_content_status(fixes_on, stores, monkeypatch):
    """The brief expected "draft projects" to be unmet. Egeria's type system says otherwise: Project's
    supertype is AuthoredReferenceable (OpenMetadataTypesArchive1_2.getProjectEntity), so it carries
    contentStatus as well as projectStatus, and DRAFT is a contentStatus value."""
    assert v2.is_a("Project", "AuthoredReferenceable")
    _, spec = _elicit(monkeypatch, "Which projects are still drafts?", "Project", ["draft"])
    status = spec["conditions"]["functional_status"]
    assert (status["property"], status["values"]) == ("contentStatus", ["DRAFT"])
    assert spec["action_function"] == "ClassificationExplorer.find_authored_elements"


def test_two_properties_one_report_the_rest_unmet(fixes_on, stores, monkeypatch):
    # B10: "in development or draft". DigitalProduct has both; one report filters one of them.
    r, spec = _elicit(monkeypatch, "Which products are still in development or draft?", "DigitalProduct",
                      ["in development", "draft"])
    status = spec["conditions"]["functional_status"]
    assert (status["property"], status["values"]) == ("deploymentStatus", ["UNDER_DEVELOPMENT"])
    assert "'draft' is a contentStatus value of DigitalProduct" in spec["unmet"]


def test_a_value_both_properties_take_goes_to_the_most_specific_and_the_note_says_so():
    status, unmet = v2.ground_functional_status("DigitalProduct", ["ACTIVE"])
    assert status["property"] == "deploymentStatus" and not unmet
    assert "ACTIVE is also a contentStatus value" in status["note"] and "most specific" in status["note"]
    status, _ = v2.ground_functional_status("Project", ["active"])
    assert (status["property"], status["values"]) == ("projectStatus", ["Active"])   # its valid-value case


@pytest.mark.parametrize("target", ["GlossaryTerm", "Project", "DigitalProduct", "Process", "GovernancePolicy",
                                    "GovernanceRule", "GovernanceMetric", "Team", "Host", "DataSet",
                                    "SolutionComponent", "Risk"])
@pytest.mark.parametrize("legacy", [False, True])
def test_no_spec_ever_carries_the_element_status_from_a_status_word(target, legacy):
    words = sorted({v for vals in v2.FUNCTIONAL_STATUS_VALUES.values() for v in vals} | {"COMPLETE", "SHINY"})
    key = v2.LEGACY_STATUS_PARAM if legacy else "functional_status"
    for word in words:
        cond, _, _ = v2.ground_conditions({key: [word]}, target)
        params = _sent_params({"title": "t", "target_type": target, "conditions": cond,
                               "columns": [{"name": "Name", "key": "display_name"}]})
        assert v2.LEGACY_STATUS_PARAM not in params and "limit_results_by_status" not in params, (target, word)


# ── the supertype walk ───────────────────────────────────────────────────────

@pytest.mark.parametrize("type_name, ancestor, want", [
    ("GlossaryTerm", "AuthoredReferenceable", True), ("DataSet", "DataAsset", True), ("CSVFile", "Asset", True),
    ("Host", "Infrastructure", True), ("DeployedSoftwareComponent", "Process", True),
    ("Process", "DataAsset", False), ("GlossaryTerm", "Asset", False), ("SoftwareCapability", "Infrastructure", False),
])
def test_is_a_walks_the_supertypes(type_name, ancestor, want):
    assert v2.is_a(type_name, ancestor) is want


@pytest.mark.parametrize("type_name, want", [
    ("DigitalProduct", ["deploymentStatus", "contentStatus"]), ("Project", ["projectStatus", "contentStatus"]),
    ("SolutionComponent", ["deploymentStatus", "contentStatus"]), ("GlossaryTerm", ["contentStatus"]),
    ("Process", ["activityStatus"]), ("Infrastructure", ["deploymentStatus"]), ("Team", []),
])
def test_status_properties_most_specific_first(type_name, want):
    assert v2.status_properties(type_name) == want


@pytest.mark.parametrize("type_name, prop, finder", [
    ("GlossaryTerm", "contentStatus", "ClassificationExplorer.find_authored_elements"),
    ("DataSet", "contentStatus", "AssetMaker.find_data_assets"),
    ("Host", "deploymentStatus", "AssetMaker.find_infrastructure"),
    ("DigitalProduct", "deploymentStatus", "CollectionManager.find_digital_products"),
    ("SolutionComponent", "deploymentStatus", "ClassificationExplorer.find_elements_by_property_value"),
    ("Process", "activityStatus", "AssetMaker.find_processes"),
    ("Project", "projectStatus", "ClassificationExplorer.find_elements_by_property_value"),
])
def test_each_property_has_a_server_side_finder_that_takes_it(type_name, prop, finder):
    action = v2.status_find_action(type_name, prop, ["X"])
    assert action["function"] == finder
    param = {"contentStatus": "content_status_list", "deploymentStatus": "deployment_status_list",
             "activityStatus": "activity_status_list"}.get(prop)
    named = "property_value" if finder.endswith("property_value") else param
    assert v2.finder_takes(finder, named)
    assert action["spec_params"]["metadata_element_type"] == type_name


def test_a_one_value_finder_takes_one_value_and_says_so():
    status, unmet = v2.ground_functional_status("Project", ["Active", "planned"])
    assert status["values"] == ["Active"] and "Planned isn't applied" in unmet[0]


def test_a_name_filter_cannot_ride_with_a_property_value_status():
    cond, _, unmet = v2.ground_conditions({"functional_status": ["active"], "search_string": "Coco"}, "Project")
    assert "search_string" not in cond and any("'Coco'" in u for u in unmet)
    cond, _, unmet = v2.ground_conditions({"functional_status": ["draft"], "search_string": "Coco"}, "GlossaryTerm")
    assert cond["search_string"] == "Coco" and not unmet          # find_authored_elements takes both


# ── element status: only an explicit "deleted", only where the finder takes it ──────────────────────

def test_deleted_is_the_element_status_where_the_finder_takes_it():
    cond, _, unmet = v2.ground_conditions({"functional_status": ["failed"], "element_status": "INCLUDE_DELETED"},
                                          "Process")
    assert cond["element_status"] == ["ACTIVE", "DELETED"] and not unmet
    params = _sent_params({"title": "t", "target_type": "Process", "conditions": cond,
                           "columns": [{"name": "Name", "key": "display_name"}]})
    assert params[v2.LEGACY_STATUS_PARAM] == ["ACTIVE", "DELETED"] and params["activity_status_list"] == ["FAILED"]


def test_deleted_is_unmet_where_the_finder_cannot_list_it():
    cond, _, unmet = v2.ground_conditions({"functional_status": ["deleted"]}, "GlossaryTerm")
    assert cond == {} and unmet == ["deleted elements: this report's finder can't list them"]


# ── the LLM's menu ───────────────────────────────────────────────────────────

def test_the_llm_is_never_offered_the_element_status_filter():
    from advisor.agents import report_spec_elicitor_v2 as v2e
    for text in (v2e._condition_help(), v2e._condition_help("DigitalProduct"), v2e._condition_help("Team")):
        assert v2.LEGACY_STATUS_PARAM not in text and "functional_status" in text
    assert "deploymentStatus" in v2e._condition_help("DigitalProduct")
    assert "activityStatus" not in v2e._condition_help("DigitalProduct")
    assert "has no status of its own" in v2e._condition_help("Team")


def test_retarget_reads_the_status_again_for_the_new_type(fixes_on, stores, monkeypatch):
    from advisor.agents import report_spec_elicitor_v2 as v2e
    _, spec = _elicit(monkeypatch, "Which glossary terms are approved?", "GlossaryTerm", ["approved"])
    v2e.retarget(spec, "target type is Process")
    status = spec["conditions"]["functional_status"]
    assert (spec["target_type"], status["property"], status["values"]) == ("Process", "activityStatus", ["APPROVED"])
    assert spec["action_function"] == "AssetMaker.find_processes"
    assert "activity_status" in [c["key"] for c in spec["columns"]]


# ── offline end to end: pyegeria's executor, the request Egeria would get, the rows a user would see ──

def _bean(**props):
    return {"elementHeader": {"guid": "g-1", "type": {"typeName": "X"},
                              "origin": {"homeMetadataCollectionId": "mc1", "homeMetadataCollectionName": "mc"},
                              "versions": {"createdBy": "u", "createTime": "2026-11-07T00:00:00Z", "version": 1},
                              "status": "ACTIVE", "class": "ElementHeader"},
            "properties": {"qualifiedName": "X::one", "displayName": "One", **props}}


@pytest.fixture
def egeria_offline(monkeypatch):
    from pyegeria.core._server_client import ServerClient
    calls, beans = [], []

    class _Resp:
        def json(self):
            return {"elements": list(beans)}

    async def fake_make_request(self, request_type, endpoint, payload=None, *args, **kwargs):
        calls.append((request_type, endpoint, json.loads(payload) if isinstance(payload, str) else payload))
        return _Resp()
    monkeypatch.setattr(ServerClient, "_async_make_request", fake_make_request)
    monkeypatch.setattr(ServerClient, "create_egeria_bearer_token", lambda self, *a, **k: "token")
    monkeypatch.setattr(ServerClient, "set_bearer_token", lambda self, token: None)
    monkeypatch.setattr(ServerClient, "check_connection", lambda self: "ok", raising=False)
    return calls, beans


class _Client:
    server_name, platform_url, user_id, user_pwd, token = "v", "https://x", "erin", None, "t"


@pytest.mark.parametrize("target, words, endpoint, body_key, body_value, bean_prop, cell", [
    ("GlossaryTerm", ["draft"], "/authored-elements/by-search-string", "contentStatusList", ["DRAFT"],
     {"contentStatus": "DRAFT"}, ("content_status", "DRAFT")),
    ("DigitalProduct", ["in development"], "/digital-products/by-search-string", "deploymentStatusList",
     ["UNDER_DEVELOPMENT"], {"deploymentStatus": "UNDER_DEVELOPMENT"}, ("deployment_status", "UNDER_DEVELOPMENT")),
    ("Process", ["failed"], "/processes/find-by-search-string", "activityStatusList", ["FAILED"],
     {"activityStatus": "FAILED"}, ("activity_status", "FAILED")),
    ("Project", ["active"], "/by-property-value-search", "propertyValue", "Active",
     {"projectStatus": "Active"}, ("project_status", "Active")),
])
def test_the_request_filters_on_the_server_and_the_column_shows_it(egeria_offline, target, words, endpoint,
                                                                    body_key, body_value, bean_prop, cell):
    calls, beans = egeria_offline
    beans.append(_bean(**bean_prop))
    cond, _, unmet = v2.ground_conditions({"functional_status": words}, target)
    cols = v2.condition_columns(target, [{"name": "Name", "key": "display_name"}], cond)
    out = v2.answer({"title": "t", "target_type": target, "answers": {"Heading": "H"}, "conditions": cond,
                     "columns": cols}, _Client())
    assert out["ok"], out
    (_, url, body), = calls
    assert url.endswith(endpoint), url
    assert body[body_key] == body_value
    assert "limitResultsByStatus" not in body
    assert body.get("metadataElementTypeName") == target
    if target == "Project":
        assert body["propertyNames"] == ["projectStatus"]
    assert out["result"]["rows"][0][cell[0]] == cell[1]
