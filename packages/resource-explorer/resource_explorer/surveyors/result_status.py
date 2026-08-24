"""What a results card should SAY when it has no rows to show.

Every render mode in index.html falls back to one string:

    "No results yet — click Run to scan."

It is shown for three different situations, and it asserts the one that is
often false. Measured across the corpus 2026-08-24, the persisted outcomes say:

  * data_profile            36 no_signal   — scanned, provably no data files
  * manifest_parse_deps      9 no_signal, 4 unverified
  * manifest_parse_ci       11 unverified  — no GitHub Actions workflows to read
  * website_ingestion        3 no_signal

So 36 cards invite a user to "click Run to scan" a repo that has already been
scanned and has nothing to profile, and 15 more invite a re-run that will
produce the same non-answer, because the missing prerequisite is a different
step. Telling someone to repeat an action that cannot help is worse than saying
nothing: it spends their time to reach the same screen.

`step_outcome.py` already draws the distinction the run needs; this draws the
one the *reader* needs, which is not quite the same. A run cares whether its
zero is provable. A reader cares what to do next — and "nothing to do, this is
the answer" and "do something else first" are the two ends of that.

    recovered / partial / regression -> measured          the card has content
    no_signal                        -> nothing_found     a real, final answer
    unverified                       -> not_established   a prerequisite is missing
    (no persisted run at all)        -> never_run         the original message, now
                                                          only shown when it is true
"""
from __future__ import annotations

import json
from typing import Any

MEASURED = "measured"
NOTHING_FOUND = "nothing_found"
NOT_ESTABLISHED = "not_established"
NEVER_RUN = "never_run"

_OUTCOME_TO_STATE = {
    "recovered": MEASURED,
    "partial": MEASURED,
    "regression": MEASURED,
    "no_signal": NOTHING_FOUND,
    "unverified": NOT_ESTABLISHED,
}

#: cause -> what the reader should do about it. Only causes that have an
#: actionable answer appear here; anything else falls back to the generic text,
#: which is honest rather than inventing a remedy.
_CAUSE_HINTS = {
    "empty_file_inventory": "Run Coarse Profile first — it builds the file inventory this reads.",
    "empty_code_symbols": "Run Code Symbol Extraction first — no symbols have been extracted yet.",
    "no_dependency_manifest": "This repo ships no recognised dependency manifest.",
    "manifest_present_no_deps_parsed":
        "A manifest is present but could not be parsed — see docs/Backlog.md "
        "(DependencyParser covers Python/Node/Go/Maven, not Gradle or Cargo).",
    "manifests_present_no_deps_extracted":
        "A manifest is present but no dependencies were extracted. Run Coarse Profile.",
    "no_github_actions_workflows_found":
        "No .github/workflows content to read. CI running elsewhere (Travis, Jenkins, "
        "CircleCI) is not visible to this check.",
    "no_homepage": "Run Homepage Discovery first — this needs the project's site URL.",
    "self_published": "The project publishes its own site; nothing to ingest separately.",
    "code_host": "The declared homepage points back at the code host, not a docs site.",
    "no_data_files": "Scanned — this repo contains no CSV/Parquet/XLSX data files.",
    "no_hygiene_files": "Scanned — none of the recognised hygiene files are present.",
    "no_files_in_scope": "The scope locator matched none of this resource's files.",
    "no_symbols_in_scope": "The scope locator matched none of the extracted symbols.",
}


def _as_dict(detail: Any) -> dict:
    if isinstance(detail, str):
        try:
            return json.loads(detail)
        except Exception:
            return {}
    return detail if isinstance(detail, dict) else {}


def status_from_detail(detail: Any) -> dict | None:
    """The status envelope for one persisted row's detail blob, or None when it
    carries no outcome (a kind that has not adopted the vocabulary yet — those
    keep today's behaviour rather than being given a guessed status)."""
    d = _as_dict(detail)
    outcome = d.get("outcome")
    if not outcome:
        return None
    cause = d.get("outcome_cause") or ""
    return {
        "state": _OUTCOME_TO_STATE.get(outcome, NOT_ESTABLISHED),
        "outcome": outcome,
        "cause": cause,
        "hint": _CAUSE_HINTS.get(cause, ""),
        "known_positive": bool(d.get("outcome_known_positive")),
    }


def attach(result: dict, detail: Any) -> dict:
    """Add `_status` to a results dict, in place, when a status is derivable.

    Additive on purpose: every existing top-level key keeps its meaning and its
    consumers, so a render mode that ignores `_status` behaves exactly as before.
    """
    status = status_from_detail(detail)
    if status:
        result["_status"] = status
    return result
