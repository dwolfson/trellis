"""Who can read a file system's path, and so who leads its folder survey (Files step 2).

Design: `docs/design-notes/DESIGN-FILES-REMOTE-REACH.md` sections 1, 2 and 5 (slice 1). Outcomes 1 and 2 only; outcome 3
(remote) is a later step.

One probe, one recorded outcome with a date. The outcome is NEVER taken from what was typed: Egeria's engine host is
asked (the existing CHECK_ASSET engine action, `reachability.check_filesystem_reachability`), and the answer, with
Resource Explorer's own read of the path, is what is stored.

    Outcome 1  "Egeria can read <container path> · checked <date>"          Egeria's Folder Survey leads
    Outcome 2  "only Resource Explorer can read this path · checked <date>" Resource Explorer's walk leads
    (neither)  "not checked yet" is its own state, and so is "could not tell"; neither is shown as 1 or 2.

Every state here is DERIVED from the stored `resource_reachability` rows (`fork_from_row`), never from which branch the
code took. A run whose probe died leaves no row, and reads "not checked yet".

No DDL: outcome 2 is stored as a row whose `outcome` is `re_only` (a word added to `REACHABILITY_OUTCOMES`), written only
after Egeria answered `network_unreachable` for this path AND Resource Explorer read the path itself.

What the existing call really is (read from Egeria's source, 2026-10-20, and reported to the coordinator): the CHECK_ASSET
engine action is a Folder Survey launch. `FolderSurveyService` does not read `finalAnalysisStep`, so on a path Egeria CAN
read the "probe" is a full survey of the tree. It is the only call that asks Egeria's engine host about a path; there is
no cheaper stat. `probe_filesystem` takes it as a seam (`egeria_probe`) so a cheaper call can replace it without touching
the rest.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger(__name__)

# The states. `egeria` and `re_only` are the two outcomes; the rest are not outcomes.
EGERIA = "egeria"
RE_ONLY = "re_only"
NOT_CHECKED = "not_checked"
UNDECIDED = "undecided"

#: Who surveyed, in the words the report and the screens carry.
SURVEYOR_EGERIA = "Egeria's Folder Survey"
SURVEYOR_RE = "Resource Explorer"

#: The sentence on the SurveyReport RE publishes when it leads (design section 2).
RE_REPORT_SENTENCE = "surveyed by Resource Explorer · Egeria could not reach the path"
EGERIA_REPORT_SENTENCE = "surveyed by Egeria's Folder Survey"

#: Egeria's own code for "the engine host's file system cannot see this folder" (reachability.py, live probe 7).
NOT_VISIBLE_CODE = "BASIC-FILE-CONNECTOR-404-001"

NOT_CHECKED_WORDS = "not checked yet"
#: Placeholder words for the designer, kept in one place.
UNDECIDED_WORDS = "could not tell whether Egeria can read this path"


def date_of(iso: str) -> str:
    """The date part of a stored timestamp ('' when there is none)."""
    return (iso or "")[:10]


@dataclass(frozen=True)
class ForkState:
    """Who can read the path, as the stored rows prove it."""

    state: str = NOT_CHECKED
    #: The one sentence on the resource ("" never: not-checked says so).
    sentence: str = NOT_CHECKED_WORDS
    checked_at: str = ""
    #: Who leads the survey: SURVEYOR_EGERIA, SURVEYOR_RE, or "" when nobody can be named yet.
    surveyor: str = ""
    #: What the probe observed, for a state that is neither outcome (Egeria's own words).
    why: str = ""
    #: The container path Egeria was asked about (outcome 1 only).
    container_path: str = ""
    #: The sentence a report carries ("surveyed by ..."), "" unless an outcome is decided.
    report_sentence: str = ""

    @property
    def decided(self) -> bool:
        return self.state in (EGERIA, RE_ONLY)

    def as_dict(self) -> dict:
        return {"state": self.state, "sentence": self.sentence, "checked_at": self.checked_at,
                "checked_date": date_of(self.checked_at), "surveyor": self.surveyor, "why": self.why,
                "container_path": self.container_path, "report_sentence": self.report_sentence,
                "decided": self.decided}


def container_path_of(fs) -> str:
    """The path Egeria's container sees: the canonical mount (the same expression the root folder is attached with)."""
    local = (getattr(fs, "local_mount_point", "") or "").rstrip("/")
    return ((getattr(fs, "canonical_mount_point", "") or local) or "").rstrip("/")


def fork_from_row(fs, row: dict | None) -> ForkState:
    """The state the newest probe row proves. Pure: a row (or none) in, a state out."""
    if not row:
        return ForkState()
    outcome = row.get("outcome") or ""
    at = row.get("probed_at") or ""
    date = date_of(at)
    if outcome == "reachable":
        path = container_path_of(fs)
        return ForkState(
            state=EGERIA, sentence=f"Egeria can read {path} · checked {date}", checked_at=at,
            surveyor=SURVEYOR_EGERIA, container_path=path, report_sentence=EGERIA_REPORT_SENTENCE)
    if outcome == "re_only":
        return ForkState(
            state=RE_ONLY, sentence=f"only Resource Explorer can read this path · checked {date}", checked_at=at,
            surveyor=SURVEYOR_RE, report_sentence=RE_REPORT_SENTENCE)
    # Anything else is a probe that did not establish who can read: it is neither outcome. Egeria's own words stay.
    why = (row.get("error_detail") or row.get("error_code") or outcome).strip()
    return ForkState(state=UNDECIDED, sentence=f"{UNDECIDED_WORDS} · checked {date}", checked_at=at, why=why)


def fork_for(registry, fs) -> ForkState:
    """The state from the newest stored probe row for this file system. Registry-only: no Egeria call."""
    if registry is None or fs is None:
        return ForkState()
    return fork_from_row(fs, registry.get_latest_reachability(fs.slug))


def re_can_read(path: str) -> tuple[bool, str]:
    """Can THIS server open the folder? Opens the directory entry and reads no file: a stat and an access check."""
    path = (path or "").strip()
    if not path:
        return False, "no path"
    if not os.path.isdir(path):
        return False, "not a folder on this server"
    if not os.access(path, os.R_OK | os.X_OK):
        return False, "this server may not list it"
    return True, ""


def _default_egeria_probe(slug: str, registry):
    """The one live call: Egeria's engine host, asked through the existing CHECK_ASSET engine action. A module-level
    function (resolved when the probe runs) so a test can replace it and no test launches an engine action by accident."""
    from resource_explorer.reachability import check_filesystem_reachability

    return check_filesystem_reachability(slug, registry)


def probe_filesystem(slug: str, registry, *, egeria_probe: Callable | None = None,
                     read_check: Callable[[str], tuple[bool, str]] = re_can_read) -> ForkState:
    """Ask Egeria's engine host about the canonical mount, add Resource Explorer's own read, record the outcome, and
    return the state the stored rows now prove. Never raises for an Egeria-side failure (that is a recorded
    `unknown`, which reads as "could not tell"). Runs at registration (when the root folder is attached) and before
    each survey.

    `egeria_probe(slug, registry)` defaults to `reachability.check_filesystem_reachability`, which records its own row.
    """
    fs = registry.get_filesystem(slug)
    if fs is None:
        return ForkState()
    if egeria_probe is None:
        egeria_probe = _default_egeria_probe
    try:
        result = egeria_probe(slug, registry)
    except Exception as exc:  # noqa: BLE001 -- the probe must not break the press that asked for it
        log.warning("reachability probe for %s raised: %r", slug, exc)
        return fork_for(registry, fs)
    if result.outcome == "network_unreachable" and result.error_code == NOT_VISIBLE_CODE:
        # Egeria's engine host cannot see the folder. Whether Resource Explorer can is a second, separate fact.
        readable, why = read_check(fs.local_mount_point)
        if readable:
            registry.record_reachability_check(
                slug, probed_at=datetime.now(timezone.utc).isoformat(), outcome="re_only",
                probed_from="resource-explorer", error_code=result.error_code,
                error_detail=f"{result.error_detail} | Resource Explorer read {fs.local_mount_point}",
                latency_ms=None, engine_action_guid=result.engine_action_guid)
        else:
            log.info("%s: Egeria cannot see the path and Resource Explorer could not read it (%s)", slug, why)
    return fork_for(registry, fs)


def refusal_words(state: ForkState, *, for_egeria_lead: bool) -> str:
    """Why a press that needs this lead cannot go ahead, '' when it can. Words come from the state."""
    if for_egeria_lead:
        if state.state == EGERIA:
            return ""
        if state.state == RE_ONLY:
            return "only Resource Explorer can read this path · it surveys it itself"
        if state.state == UNDECIDED:
            return f"{UNDECIDED_WORDS}" + (f" · {state.why}" if state.why else "")
        return NOT_CHECKED_WORDS
    # Resource Explorer's report claim ("Egeria could not reach the path") needs proof that Egeria could not.
    if state.state == RE_ONLY:
        return ""
    if state.state == EGERIA:
        return "Egeria can read this path · its Folder Survey leads"
    if state.state == UNDECIDED:
        return f"{UNDECIDED_WORDS}" + (f" · {state.why}" if state.why else "")
    return NOT_CHECKED_WORDS
