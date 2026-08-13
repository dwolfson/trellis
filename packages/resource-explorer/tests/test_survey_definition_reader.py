import pytest

from resource_explorer.surveyors.survey_definition_reader import (
    SurveyDefinitionReader,
    SurveyDefinitionReaderError,
    UnsupportedSurveyDefinitionError,
)

# Fixtures below match the real GovernanceOfficer.get_governance_process_graph
# response shape, confirmed against a live qs-view-server for both a single-step
# and a two-step chained Survey Definition (2026-07-07/08): a flat node list
# ("firstProcessStep" + "nextProcessSteps") plus a separate flat edge list
# ("processStepLinks", keyed by GUID via "previousProcessStep"/"nextProcessStep").
# Step properties live under "processStepProperties" (not "properties" — only
# the process element itself uses that).


def _step_element(guid, qualified_name, additional_properties=None, display_name=None):
    return {
        "elementHeader": {"guid": guid},
        "processStepProperties": {
            "qualifiedName": qualified_name,
            "displayName": display_name or qualified_name,
            "additionalProperties": additional_properties or {},
        },
    }


def _link(prev_guid, next_guid, guard=None, mandatory_guard=False):
    link = {
        "previousProcessStep": {"guid": prev_guid},
        "nextProcessStep": {"guid": next_guid},
        "nextProcessStepLinkGUID": "link-guid",
        "mandatoryGuard": mandatory_guard,
    }
    if guard is not None:
        link["guard"] = guard
    return link


def _graph(process_guid, qualified_name, additional_properties=None,
           first_step=None, next_steps=None, links=None):
    graph = {
        "governanceActionProcess": {
            "elementHeader": {"guid": process_guid},
            "properties": {
                "qualifiedName": qualified_name,
                "displayName": qualified_name,
                "additionalProperties": additional_properties or {},
            },
        },
    }
    if first_step is not None:
        graph["firstProcessStep"] = {"element": first_step, "linkGUID": "first-link-guid"}
    if next_steps is not None:
        graph["nextProcessSteps"] = next_steps
    if links is not None:
        graph["processStepLinks"] = links
    return graph


def _reader() -> SurveyDefinitionReader:
    # _parse_graph is side-effect-free and needs no live connection/pyegeria client.
    return SurveyDefinitionReader()


def test_parse_single_step_graph():
    step = _step_element(
        "step-1", "GovActionProcessStep::Survey::SchemaAndStats",
        additional_properties={"executes_at": "resource-explorer", "re_analysis_step": "postgres_schema_and_stats"},
    )
    graph = _graph(
        "proc-1", "GovActionProcess::Survey",
        additional_properties={"supported_technology_type": "PostgreSQL Database"},
        first_step=step,
    )

    survey_def = _reader()._parse_graph(graph)

    assert survey_def.process_guid == "proc-1"
    assert survey_def.supported_technology_type == "PostgreSQL Database"
    assert len(survey_def.steps) == 1
    assert survey_def.steps[0].guid == "step-1"
    assert survey_def.steps[0].executes_at == "resource-explorer"
    assert survey_def.steps[0].re_analysis_step == "postgres_schema_and_stats"
    assert survey_def.survey_kind is None  # not present in additional_properties above


def test_parse_survey_kind_when_present():
    step = _step_element(
        "step-1", "GovActionProcessStep::Survey::Step",
        additional_properties={"executes_at": "resource-explorer"},
    )
    graph = _graph(
        "proc-1", "GovActionProcess::Survey",
        additional_properties={"supported_technology_type": "Git Repository", "survey_kind": "discovery"},
        first_step=step,
    )

    survey_def = _reader()._parse_graph(graph)

    assert survey_def.survey_kind == "discovery"


def test_parse_linear_two_step_graph():
    step1 = _step_element(
        "step-1", "GovActionProcessStep::Survey::SchemaAndStats",
        additional_properties={"executes_at": "resource-explorer", "re_analysis_step": "postgres_schema_and_stats"},
    )
    step2 = _step_element(
        "step-2", "GovActionProcessStep::Survey::RowCountSnapshot",
        additional_properties={"executes_at": "egeria"},
    )
    graph = _graph(
        "proc-1", "GovActionProcess::Survey",
        additional_properties={"supported_technology_type": "PostgreSQL Database"},
        first_step=step1,
        next_steps=[step2],
        links=[_link("step-1", "step-2", mandatory_guard=False)],
    )

    survey_def = _reader()._parse_graph(graph)

    assert [s.guid for s in survey_def.steps] == ["step-1", "step-2"]
    assert survey_def.steps[1].executes_at == "egeria"


def test_parse_graph_with_no_first_step():
    graph = _graph("proc-empty", "GovActionProcess::Empty")
    survey_def = _reader()._parse_graph(graph)
    assert survey_def.steps == []


def test_branching_step_is_rejected():
    step1 = _step_element("step-1", "Step::First", additional_properties={"executes_at": "resource-explorer"})
    branch_a = _step_element("a", "Step::A", additional_properties={"executes_at": "resource-explorer"})
    branch_b = _step_element("b", "Step::B", additional_properties={"executes_at": "resource-explorer"})
    graph = _graph(
        "proc-branch", "GovActionProcess::Branching",
        first_step=step1,
        next_steps=[branch_a, branch_b],
        links=[_link("step-1", "a", guard="ok"), _link("step-1", "b", guard="not-ok")],
    )

    with pytest.raises(UnsupportedSurveyDefinitionError):
        _reader()._parse_graph(graph)


def test_missing_executes_at_is_rejected():
    step1 = _step_element("step-1", "Step::NoExecutesAt", additional_properties={})
    graph = _graph("proc-missing", "GovActionProcess::Missing", first_step=step1)

    with pytest.raises(SurveyDefinitionReaderError):
        _reader()._parse_graph(graph)


def test_unrecognized_executes_at_value_parses_fine():
    """The reader only rejects unsupported *shapes* (branching, missing keys) —
    an unfamiliar-but-well-formed executes_at value (e.g. a future engine like
    Airflow) is not the reader's job to reject; that's the executor's call."""
    step1 = _step_element(
        "step-1", "Step::Airflow",
        additional_properties={"executes_at": "airflow", "re_analysis_step": "some_dag"},
    )
    graph = _graph("proc-airflow", "GovActionProcess::Airflow", first_step=step1)

    survey_def = _reader()._parse_graph(graph)
    assert survey_def.steps[0].executes_at == "airflow"


def test_cycle_is_rejected():
    step1 = _step_element("step-1", "Step::One", additional_properties={"executes_at": "egeria"})
    step2 = _step_element("step-2", "Step::Two", additional_properties={"executes_at": "egeria"})
    graph = _graph(
        "proc-cycle", "GovActionProcess::Cycle",
        first_step=step1,
        next_steps=[step2],
        links=[_link("step-1", "step-2"), _link("step-2", "step-1")],  # cycle back to step1
    )

    with pytest.raises(UnsupportedSurveyDefinitionError):
        _reader()._parse_graph(graph)


class _FakeGovernanceOfficer:
    def __init__(self, results):
        self._results = results

    def find_governance_definitions(self, **_kwargs):
        return self._results


def _reader_with_fake_results(results) -> SurveyDefinitionReader:
    reader = _reader()
    reader._governance_officer = _FakeGovernanceOfficer(results)  # short-circuits connect()
    return reader


def _governance_process_result(qualified_name, technology_type, survey_kind=None, guid="g"):
    additional = {"supported_technology_type": technology_type}
    if survey_kind is not None:
        additional["survey_kind"] = survey_kind
    return {
        "properties": {"qualifiedName": qualified_name, "displayName": qualified_name, "additionalProperties": additional},
        "elementHeader": {"guid": guid},
    }


class TestFindCandidateProcessGuidsSurveyKindFilter:
    """Analysis-step Egeria registration plan D1 (survey_kind filtering) —
    docs/discovery-automate-project-context-plan.md Part 1."""

    def test_no_survey_kind_filter_returns_everything_matching_technology_type(self):
        results = [
            _governance_process_result("GovActionProcess::A", "Git Repository", survey_kind="discovery"),
            _governance_process_result("GovActionProcess::B", "Git Repository", survey_kind="automate_full"),
            _governance_process_result("GovActionProcess::C", "PostgreSQL Database", survey_kind="discovery"),
        ]
        reader = _reader_with_fake_results(results)
        candidates = reader.find_candidate_process_guids("Git Repository")
        assert {c["qualified_name"] for c in candidates} == {"GovActionProcess::A", "GovActionProcess::B"}

    def test_survey_kind_filter_narrows_to_exact_match(self):
        results = [
            _governance_process_result("GovActionProcess::A", "Git Repository", survey_kind="discovery"),
            _governance_process_result("GovActionProcess::B", "Git Repository", survey_kind="automate_full"),
        ]
        reader = _reader_with_fake_results(results)
        candidates = reader.find_candidate_process_guids("Git Repository", survey_kind="discovery")
        assert [c["qualified_name"] for c in candidates] == ["GovActionProcess::A"]

    def test_survey_kind_filter_excludes_definitions_with_no_survey_kind_at_all(self):
        # A Survey Definition authored before this convention existed (no
        # survey_kind key at all) must not leak into a kind-filtered list.
        results = [_governance_process_result("GovActionProcess::Legacy", "Git Repository", survey_kind=None)]
        reader = _reader_with_fake_results(results)
        assert reader.find_candidate_process_guids("Git Repository", survey_kind="discovery") == []
        # ...but shows up fine when no filter is applied (backward compatibility).
        assert len(reader.find_candidate_process_guids("Git Repository")) == 1


def test_missing_node_for_linked_guid_is_rejected():
    """A link pointing at a guid with no corresponding node (malformed/partial
    graph) should fail loudly, not silently stop the chain early."""
    step1 = _step_element("step-1", "Step::One", additional_properties={"executes_at": "egeria"})
    graph = _graph(
        "proc-dangling", "GovActionProcess::Dangling",
        first_step=step1,
        next_steps=[],  # step "step-2" is linked but never listed as a node
        links=[_link("step-1", "step-2")],
    )

    with pytest.raises(SurveyDefinitionReaderError):
        _reader()._parse_graph(graph)
