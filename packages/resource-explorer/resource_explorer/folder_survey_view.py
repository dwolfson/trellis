"""One read of a file system's folder survey, whoever led it (Files step 2).

The survey card and Understanding read ONE shape for both leads. This module picks the newest folder survey RE holds for
a file system and returns it as `read_folder_survey` does:

* **Egeria led:** the stored annotations of the newest COMPLETED native run of `FileSurvey::survey-folder` (the rows the
  native-survey port read back from Egeria's SurveyReport). "Complete" is `native_survey_run.derive_native_state`'s word,
  which needs the action's status, a stored report GUID and the stored annotation count to match.
* **Resource Explorer led:** the newest stored walk that carries `surveyed_by` (the walk's own `survey_data`), read through
  the SAME annotation specs it publishes (`folder_survey_annotations.folder_specs`), so what the screen shows is what
  Egeria is sent.

Words come from stored rows (the probe row, the run row, the walk's own limits), never from the branch a press took. A
file system with no survey is `state: "none"`: "no folder survey yet", not zeros.
"""
from __future__ import annotations

from datetime import datetime, timezone

from resource_explorer import file_reach
from resource_explorer.surveyors.filesystem.folder_survey_annotations import folder_specs, read_folder_survey


def _when(text: str) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _egeria_candidate(registry, slug: str) -> dict | None:
    """The newest completed Egeria Folder Survey run with its stored annotations, plus the state of the newest run."""
    from resource_explorer import native_survey_run as nsr

    runs = registry.list_native_survey_runs("filesystem", slug, nsr.FOLDER_SURVEY_QN)
    newest_state = ""
    for i, run in enumerate(runs):
        report = run.get("survey_report_guid") or ""
        stored = registry.count_native_survey_annotations(report) if report else None
        state = nsr.derive_native_state(run, stored_annotation_count=stored).get("state", "")
        if i == 0:
            newest_state = state
        if state == nsr.COMPLETE and report:
            return {"surveyor": file_reach.SURVEYOR_EGERIA, "at": run.get("survey_report_at") or run.get("surveyed_at") or "",
                    "report_guid": report, "annotations": registry.query_native_survey_annotations(report),
                    "run_state": newest_state, "limits": None, "published": True,
                    "report_sentence": file_reach.EGERIA_REPORT_SENTENCE}
    return {"none": True, "run_state": newest_state} if runs else None


def _re_candidate(registry, slug: str) -> dict | None:
    """The newest stored Resource Explorer walk (one that records who led it)."""
    rows = registry.list_filesystem_surveys(slug)
    walks = [r for r in rows if (r.get("survey_data") or {}).get("surveyed_by")]
    if not walks:
        return None
    newest = max(walks, key=lambda r: _when((r["survey_data"] or {}).get("surveyed_at") or r.get("surveyed_at")) or
                 datetime.min.replace(tzinfo=timezone.utc))
    sd = newest["survey_data"]
    at = sd.get("surveyed_at") or newest.get("surveyed_at") or ""
    # The published report is the row stored with the same run time and a report GUID (publish stores its own row).
    guid = next((r.get("egeria_report_guid") for r in rows
                 if r.get("egeria_report_guid") and r.get("surveyed_at") == newest.get("surveyed_at")), "")
    reach = (sd.get("surveyed_by") or {}).get("reach") or {}
    return {"surveyor": file_reach.SURVEYOR_RE, "at": at, "report_guid": guid or "", "published": bool(guid),
            "annotations": folder_specs(sd), "limits": sd.get("walk_limits"), "run_state": "",
            "reach_at_run": reach, "report_sentence": file_reach.RE_REPORT_SENTENCE}


def folder_survey_view(registry, slug: str) -> dict:
    """The newest folder survey, whoever led it, with the probe state and who leads NOW."""
    fs = registry.get_filesystem(slug)
    fork = file_reach.fork_for(registry, fs)
    egeria = _egeria_candidate(registry, slug)
    re_walk = _re_candidate(registry, slug)
    candidates = [c for c in (egeria, re_walk) if c and not c.get("none")]
    base = {"slug": slug, "reach": fork.as_dict(), "leads": fork.surveyor,
            "egeria_run_state": (egeria or {}).get("run_state", "")}
    if not candidates:
        return {**base, "state": "none", "surveyor": "", "surveyed_at": "", "report_guid": "", "published": False,
                "report_sentence": "", "results": None, "limits": None}
    best = max(candidates, key=lambda c: _when(c["at"]) or datetime.min.replace(tzinfo=timezone.utc))
    return {**base, "state": "measured", "surveyor": best["surveyor"], "surveyed_at": best["at"],
            "report_guid": best["report_guid"], "published": best["published"],
            "report_sentence": best["report_sentence"], "results": read_folder_survey(best["annotations"]),
            "limits": best["limits"]}
