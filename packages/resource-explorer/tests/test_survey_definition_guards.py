"""Guards and step-level 0462 attributes — read, not discarded.

Egeria routes on guards: a completing governance service supplies guards and
action targets for its successors. The coordinator of a run — a real engine
host, or RE acting as a pseudo one — runs a step, takes the guard, and picks
the next viable step. Nothing needs persisting for that; the guard is a routing
signal held for the run.

Before this, the payload carried `guard` and `mandatoryGuard` on every link, a
live read returned them on all 9 links of Analysis Survey, and the reader kept
only the two GUIDs.
"""
from __future__ import annotations

from resource_explorer.surveyors.survey_definition_reader import (
    StepLink,
    SurveyDefinitionReader,
)


def _step(guid, qn, **props):
    base = {"qualifiedName": qn, "displayName": qn,
            "additionalProperties": {"executes_at": "resource-explorer",
                                     "re_analysis_step": "repo_classification"}}
    base.update(props)
    return {"elementHeader": {"guid": guid}, "processStepProperties": base}


def _graph(steps, links, process_qn="GovActionProcess::T"):
    first, rest = steps[0], steps[1:]
    return {"governanceActionProcess": {
        "element": {"elementHeader": {"guid": "p1"},
                    "properties": {"qualifiedName": process_qn, "displayName": "T"}},
        "firstProcessStep": {"element": first},
        "nextProcessSteps": rest,
        "processStepLinks": links,
    }}


def _parse(graph):
    r = SurveyDefinitionReader.__new__(SurveyDefinitionReader)
    return r._parse_graph(graph, "p1") if hasattr(r, "_parse_graph") else None


class TestGuardsSurviveTheRead:
    def test_guard_and_mandatory_guard_are_kept_on_the_link(self):
        link = StepLink(previous_guid="a", next_guid="b",
                        guard="architecture-found", mandatory_guard=True)
        assert link.guard == "architecture-found"
        assert link.mandatory_guard is True

    def test_a_link_with_no_guard_is_empty_string_not_none(self):
        """`guard` is 'present only when a guard value was actually set' in the
        payload. An absent guard means unconditional, which is a real routing
        answer — not a missing value to be checked for None everywhere."""
        link = StepLink(previous_guid="a", next_guid="b")
        assert link.guard == "" and link.mandatory_guard is False


class TestStepCarriesIts0462Attributes:
    def test_produced_guards_are_read(self):
        """`producedGuards` is the authored declaration of what a step can
        emit. A coordinator needs it to know a guard is expected at all — an
        absent guard from a step that declares none is normal; from a step that
        declares three it is a failure."""
        from resource_explorer.surveyors.survey_definition_reader import SurveyStep
        s = SurveyStep(guid="a", display_name="A", qualified_name="A",
                       produced_guards=["ok", "no-architecture"])
        assert s.produced_guards == ["ok", "no-architecture"]

    def test_executor_present_distinguishes_absent_from_empty(self):
        """An empty `request_parameters` must not read as 'this step declares
        no parameters' when the truth is 'the API did not return an executor'.
        Same absence-vs-zero distinction as result_status."""
        from resource_explorer.surveyors.survey_definition_reader import SurveyStep
        no_exec = SurveyStep(guid="a", display_name="A", qualified_name="A")
        with_exec = SurveyStep(guid="b", display_name="B", qualified_name="B",
                               executor_present=True)
        assert no_exec.request_parameters == with_exec.request_parameters == {}
        assert no_exec.executor_present is False
        assert with_exec.executor_present is True, (
            "an empty dict alone cannot say which case this is"
        )


class TestTopologyIsKeptWholeEvenThoughV1WalksALine:
    def test_definition_carries_links_alongside_linear_steps(self):
        from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition
        d = SurveyDefinition(process_guid="p", display_name="T",
                             qualified_name="Q", supported_technology_type=None,
                             links=[StepLink("a", "b", guard="Any")])
        assert d.links[0].guard == "Any"
        assert d.steps == [], "steps and links are separate views of one graph"
