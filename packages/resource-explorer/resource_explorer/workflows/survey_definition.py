"""Running an authored Survey Definition, off any web framework.

Unlike the other three workflows, this one was never really web-only: the CLI
and `web/routes/survey_definitions.py` already called the same core
`run_survey_definition` (plan §3 names that as the evidence the core is
separable). What lived only in the route was the small amount *around* it — the
portal-URL decoration, and the "write the terminal status back onto the activity
entry" wrapper the frontend's poll depends on.

That wrapper is what the run queue needs, so it moves here rather than being
reimplemented: a queued Survey Definition run must leave exactly the same
activity row a route-spawned thread left, or the run modal reads a different
shape depending on which process happened to execute it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class SurveyDefinitionRunParams:
    """The run's inputs, as a plain dataclass rather than the route's pydantic
    body — so the queue can round-trip them through the `runs.target` JSON
    column and hand them back to the same function."""

    survey_definition_ref: str = ""
    refresh_definition: bool = False
    db_user: str = ""
    db_pwd: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> SurveyDefinitionRunParams:
        return cls(**{k: v for k, v in (data or {}).items()
                      if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {
            "survey_definition_ref": self.survey_definition_ref,
            "refresh_definition": self.refresh_definition,
            "db_user": self.db_user,
            "db_pwd": self.db_pwd,
        }


@dataclass
class SurveyDefinitionRunResult:
    status: str  # "ok" | "error"
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)


def run_definition(entity_type: str, slug: str, params: SurveyDefinitionRunParams,
                   *, registry=None) -> dict:
    """Execute one Survey Definition and return the executor's own result dict.

    Raises SurveyDefinitionExecutorError / SurveyDefinitionReaderError on a
    reader/executor-level failure — the caller decides how to surface that (an
    HTTP status for the route, an errored activity entry and a failed `runs`
    row for the queue).
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_definition_executor import (
        run_survey_definition,
    )

    registry = registry or ProjectRegistry()
    result = run_survey_definition(
        entity_type, slug, registry=registry,
        survey_definition_ref=params.survey_definition_ref,
        refresh_definition=params.refresh_definition,
        db_user=params.db_user,
        db_pwd=params.db_pwd,
    )

    report_guid = result.get("egeria_report_guid", "")
    if report_guid:
        from resource_explorer.config import get_config

        portal_url = get_config().egeria.portal_url.rstrip("/")
        result["egeria_portal_report_url"] = f"{portal_url}/tech-catalog?guid={report_guid}"
    return result


def execute_and_record_definition(entity_type: str, slug: str,
                                  params: SurveyDefinitionRunParams,
                                  activity_id: str, *, registry=None
                                  ) -> SurveyDefinitionRunResult:
    """Run a Survey Definition and write its terminal status onto `activity_id`.

    The full structured result (steps report, egeria_report_guid, portal URL,
    errors — everything the run modal renders) is JSON-encoded into that same
    entry's `detail`. No separate result store, and — unlike an in-memory dict
    — it survives a restart like any other activity entry.

    `survey_definition_ref` is embedded in `detail` on every terminal path. The
    running row's `summary` does carry it, but this call always overwrites
    `summary`, so by the time anything queries a completed run the ref only
    survives if it is also in `detail` — which is what
    registry.get_survey_definition_last_activity() scans for.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutorError,
    )
    from resource_explorer.surveyors.survey_definition_reader import (
        SurveyDefinitionReaderError,
    )

    registry = registry or ProjectRegistry()
    ref = params.survey_definition_ref
    try:
        result = run_definition(entity_type, slug, params)
    except (SurveyDefinitionExecutorError, SurveyDefinitionReaderError) as exc:
        registry.update_activity_status(
            activity_id, "error", summary=str(exc),
            detail=json.dumps({"errors": [str(exc)], "survey_definition_ref": ref}),
        )
        return SurveyDefinitionRunResult(status="error", summary=str(exc), errors=[str(exc)])
    except Exception as exc:  # pragma: no cover — genuinely unexpected
        log.exception("Survey Definition run crashed for %s/%s", entity_type, slug)
        registry.update_activity_status(
            activity_id, "error", summary=f"Survey Definition run crashed: {exc}",
            detail=json.dumps({"errors": [str(exc)], "survey_definition_ref": ref}),
        )
        return SurveyDefinitionRunResult(
            status="error", summary=f"Survey Definition run crashed: {exc}", errors=[str(exc)],
        )

    errors = result.get("errors") or []
    summary = (f"Completed with {len(errors)} error(s)" if errors
               else "Survey Definition run complete")
    result["survey_definition_ref"] = ref
    registry.update_activity_status(
        activity_id, "error" if errors else "ok", summary=summary,
        detail=json.dumps(result),
    )
    return SurveyDefinitionRunResult(
        status="error" if errors else "ok", summary=summary, errors=errors, result=result,
    )
