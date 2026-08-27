"""Tests for egeria_delegated_step.py — case 4 of
docs/re-as-engine-host-plan.md (RE's local SurveyOrchestrator delegates one
step to a real Egeria governance/survey action service, instead of running
it locally). Every pyegeria client is mocked; these tests verify the local
polling/annotation logic, not pyegeria's real network behavior.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.egeria_delegated_step import (
    EgeriaDelegatedStepSurveyor,
    EgeriaEngineActionTimeoutError,
    initiate_action_type_and_wait,
    initiate_and_wait,
)
from resource_explorer.surveyors.survey_report import (
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="delproj", display_name="Del Proj", github_url="https://github.com/a/delproj")
    registry.add(p)
    return p


def _mock_element(status: str, completion_message: str = "") -> dict:
    return {
        "elementProperties": {
            "propertyValueMap": {
                "activityStatus": {"class": "EnumTypePropertyValue", "symbolicName": status},
                "completionMessage": {"class": "PrimitiveTypePropertyValue", "primitiveValue": completion_message},
            }
        }
    }


class TestInitiateAndWait:
    def test_returns_guid_status_and_message_on_immediate_completion(self):
        automated_curation = MagicMock()
        automated_curation.initiate_engine_action.return_value = "action-guid-1"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = _mock_element("COMPLETED", "all good")

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ):
            guid, status, message = initiate_and_wait(
                qualified_name="qn", display_name="dn", description="desc",
                governance_engine_name="AssetSurvey", request_type="SomeRequestType",
            )

        assert guid == "action-guid-1"
        assert status == "COMPLETED"
        assert message == "all good"
        automated_curation.initiate_engine_action.assert_called_once()
        kwargs = automated_curation.initiate_engine_action.call_args.kwargs
        assert kwargs["request_type"] == "SomeRequestType"

    def test_polls_until_terminal_status(self):
        automated_curation = MagicMock()
        automated_curation.initiate_engine_action.return_value = "action-guid-2"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.side_effect = [
            _mock_element("IN_PROGRESS"),
            _mock_element("IN_PROGRESS"),
            _mock_element("COMPLETED", "done"),
        ]

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ), patch("resource_explorer.surveyors.egeria_delegated_step.time.sleep"):
            guid, status, message = initiate_and_wait(
                qualified_name="qn", display_name="dn", description="desc",
                governance_engine_name="AssetSurvey", request_type="SomeRequestType", poll_interval=0.01,
            )

        assert status == "COMPLETED"
        assert metadata_expert.get_metadata_element_by_guid.call_count == 3

    def test_raises_when_action_not_initiated(self):
        automated_curation = MagicMock()
        automated_curation.initiate_engine_action.return_value = "Action not initiated"
        metadata_expert = MagicMock()

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ):
            with pytest.raises(RuntimeError, match="did not initiate"):
                initiate_and_wait(
                    qualified_name="qn", display_name="dn", description="desc",
                    governance_engine_name="AssetSurvey", request_type="SomeRequestType",
                )

    def test_raises_timeout_when_never_terminal(self):
        automated_curation = MagicMock()
        automated_curation.initiate_engine_action.return_value = "action-guid-3"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = _mock_element("IN_PROGRESS")

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ), patch("resource_explorer.surveyors.egeria_delegated_step.time.sleep"):
            with pytest.raises(EgeriaEngineActionTimeoutError):
                initiate_and_wait(
                    qualified_name="qn", display_name="dn", description="desc",
                    governance_engine_name="AssetSurvey", request_type="SomeRequestType", poll_interval=0.01, timeout=0.02,
                )


class TestEgeriaDelegatedStepSurveyor:
    def test_success_produces_resource_measure_annotation(self, registry, project):
        automated_curation = MagicMock()
        automated_curation.initiate_engine_action.return_value = "action-guid-4"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = _mock_element("COMPLETED")

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ):
            results = EgeriaDelegatedStepSurveyor(
                project, registry, governance_engine_name="AssetSurvey", request_type="SomeRequestType",
            ).run()

        assert len(results) == 1
        assert isinstance(results[0], ResourceMeasureAnnotation)
        assert results[0].source == "egeria"
        assert results[0].resource_properties["engine_action_guid"] == "action-guid-4"
        assert results[0].resource_properties["final_status"] == "COMPLETED"
        assert results[0].resource_properties["delegated_to"] == "SomeRequestType"

    def test_failure_status_produces_request_for_action(self, registry, project):
        automated_curation = MagicMock()
        automated_curation.initiate_engine_action.return_value = "action-guid-5"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = _mock_element(
            "FAILED", "connector blew up"
        )

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ):
            results = EgeriaDelegatedStepSurveyor(
                project, registry, governance_engine_name="AssetSurvey", request_type="SomeRequestType",
            ).run()

        assert len(results) == 1
        assert isinstance(results[0], RequestForActionAnnotation)
        assert "FAILED" in results[0].summary
        assert results[0].explanation == "connector blew up"
        assert results[0].action_target_name == "action-guid-5"

    def test_timeout_never_raises_produces_request_for_action(self, registry, project):
        automated_curation = MagicMock()
        automated_curation.initiate_engine_action.return_value = "action-guid-6"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = _mock_element("WAITING")

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ), patch("resource_explorer.surveyors.egeria_delegated_step.time.sleep"):
            results = EgeriaDelegatedStepSurveyor(
                project, registry, governance_engine_name="AssetSurvey", request_type="SomeRequestType",
                poll_interval=0.01, timeout=0.02,
            ).run()  # must not raise

        assert len(results) == 1
        assert isinstance(results[0], RequestForActionAnnotation)
        assert "still WAITING" in results[0].explanation

    def test_initiation_error_never_raises_produces_request_for_action(self, registry, project):
        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            side_effect=RuntimeError("connection refused"),
        ):
            results = EgeriaDelegatedStepSurveyor(
                project, registry, governance_engine_name="AssetSurvey", request_type="SomeRequestType",
            ).run()  # must not raise

        assert len(results) == 1
        assert isinstance(results[0], RequestForActionAnnotation)
        assert "connection refused" in results[0].explanation

    def test_step_name_includes_request_type(self, registry, project):
        surveyor = EgeriaDelegatedStepSurveyor(project, registry, governance_engine_name="AssetSurvey", request_type="SomeRequestType")
        assert surveyor.step_name == "EgeriaDelegatedStep[SomeRequestType]"

    def test_requires_exactly_one_of_request_type_or_action_type(self, registry, project):
        with pytest.raises(ValueError, match="exactly one"):
            EgeriaDelegatedStepSurveyor(project, registry)
        with pytest.raises(ValueError, match="exactly one"):
            EgeriaDelegatedStepSurveyor(
                project, registry,
                governance_engine_name="AssetSurvey", request_type="SomeRequestType",
                action_type_qualified_name="GovActionType::Probe",
            )


class TestInitiateActionTypeAndWait:
    """The ISSUE-50 workaround path -- AutomatedCuration.
    initiate_gov_action_type(), unaffected by the direct
    initiate_engine_action() URL bug (see module docstring)."""

    def test_returns_guid_status_and_message_on_immediate_completion(self):
        automated_curation = MagicMock()
        automated_curation.initiate_gov_action_type.return_value = "action-guid-10"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = _mock_element("COMPLETED", "all good")

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ):
            guid, status, message = initiate_action_type_and_wait(
                action_type_qualified_name="GovActionType::Probe",
            )

        assert guid == "action-guid-10"
        assert status == "COMPLETED"
        assert message == "all good"
        automated_curation.initiate_gov_action_type.assert_called_once()
        kwargs = automated_curation.initiate_gov_action_type.call_args.kwargs
        assert kwargs["action_type_qualified_name"] == "GovActionType::Probe"
        # No governance-engine-name argument anywhere in this call -- the
        # whole point of this path is that the engine is resolved from the
        # GovernanceActionType's own metadata, not passed by the caller.
        automated_curation.initiate_engine_action.assert_not_called()

    def test_raises_when_action_not_initiated(self):
        automated_curation = MagicMock()
        automated_curation.initiate_gov_action_type.return_value = "Action not initiated"
        metadata_expert = MagicMock()

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ):
            with pytest.raises(RuntimeError, match="did not initiate"):
                initiate_action_type_and_wait(action_type_qualified_name="GovActionType::Probe")


class TestEgeriaDelegatedStepSurveyorActionTypePath:
    def test_success_via_action_type_qualified_name(self, registry, project):
        automated_curation = MagicMock()
        automated_curation.initiate_gov_action_type.return_value = "action-guid-11"
        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = _mock_element("COMPLETED")

        with patch(
            "resource_explorer.surveyors.egeria_delegated_step._get_clients",
            return_value=(automated_curation, metadata_expert),
        ):
            results = EgeriaDelegatedStepSurveyor(
                project, registry, action_type_qualified_name="GovActionType::Probe",
            ).run()

        assert len(results) == 1
        assert isinstance(results[0], ResourceMeasureAnnotation)
        assert results[0].resource_properties["delegated_to"] == "GovActionType::Probe"
        automated_curation.initiate_gov_action_type.assert_called_once()
        automated_curation.initiate_engine_action.assert_not_called()

    def test_step_name_includes_action_type_qualified_name(self, registry, project):
        surveyor = EgeriaDelegatedStepSurveyor(
            project, registry, action_type_qualified_name="GovActionType::Probe",
        )
        assert surveyor.step_name == "EgeriaDelegatedStep[GovActionType::Probe]"


# ── ISSUE-50 retired (2026-08-27) ───────────────────────────────────────────
def test_the_engine_name_is_required_alongside_a_request_type(project, registry):
    """`governance_engine_name` is a URL path segment on the initiate endpoint,
    so a request_type alone cannot address anything.

    pyegeria's initiate_engine_action had no parameter for it until 6.0.18.4,
    and the omission surfaced as a bare 404 that read as a pyegeria bug
    (ISSUE-50) rather than a missing argument. Refusing here names it.
    """
    with pytest.raises(ValueError) as exc:
        EgeriaDelegatedStepSurveyor(
            project, registry, request_type="SomeRequestType")
    assert "governance_engine_name" in str(exc.value)


def test_the_action_type_path_needs_no_engine_name(project, registry):
    """The GovernanceActionType carries its own executor link, so the engine is
    resolved server-side. That is now a genuine choice between two valid paths
    rather than the only one that worked."""
    surveyor = EgeriaDelegatedStepSurveyor(
        project, registry,
        action_type_qualified_name="GovernanceActionType::Demo")
    assert surveyor._governance_engine_name is None
