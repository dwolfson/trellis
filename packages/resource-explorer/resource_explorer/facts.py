"""What is known about a resource, and how well it is known.

Every agent that answers a question about a resource needs the same two things:
the value, and whether the value means anything. Today each one goes to the
tables itself, so an empty table becomes "none found" in the answer — and
"none found" and "we never looked" read identically to whoever asked. That is
the failure this codebase keeps finding in new places, and an LLM narrating raw
rows is the most efficient way yet devised to produce it at scale.

So facts leave this layer already judged. A `Fact` carries a state from
result_status's vocabulary, never a bare value:

    measured         ran, and there is something here
    nothing_found    ran, and there is genuinely nothing — a real zero
    never_run        never ran, so nothing is known either way
    not_established  ran, but this analysis cannot be credited with the result
    partial          ran over part of what it covers

The distinction that matters most is `nothing_found` vs `never_run`. They are
the same number and opposite answers.

Two consumers, one layer. The catalogued questions (docs/dr-egeria/
resource_questions.csv) are a curated index into these facts — each declares
which analyses answer it. Free text reaches the same facts through the existing
agents. Neither should be able to assert something this layer did not.

`can_run` is what makes a follow-up honest: when a fact is `never_run`, the
step keys that would establish it are already known, so "shall I run X?" is
derived rather than guessed.

Deliberately NOT here: any judgement a human has to make. A component recovered
from a repo is a proposal, not a validated part of an architecture — see
`Fact.provenance`. Validation is a Curate-stage act, and when it exists it will
be a distinct provenance rather than a higher confidence, because "a person
agreed" and "the detector was sure" are different claims.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from resource_explorer.surveyors.result_status import (
    MEASURED,
    NEVER_RUN,
    NOT_ESTABLISHED,
    NOTHING_FOUND,
)

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)

#: A run happened but covered only part of what the analysis owns. Its own
#: state rather than a flag on `measured`: a partial result is usable, and
#: saying so is different from claiming the analysis completed.
PARTIAL = "partial"

#: Where a fact came from. `recovered` is the important one — a proposal a
#: detector made, which nobody has agreed with yet. Kept separate from
#: confidence on purpose: a high-confidence proposal is still a proposal.
PROVENANCE_MEASURED = "measured"      # a surveyor computed it
PROVENANCE_RECOVERED = "recovered"    # a detector proposed it
PROVENANCE_EGERIA = "egeria"          # materialised from an Egeria annotation
PROVENANCE_HUMAN = "human"            # someone stated or validated it


@dataclass
class Fact:
    """One analysis's contribution to what is known about one resource."""

    analysis_id: str
    state: str
    value: dict = field(default_factory=dict)
    provenance: str = PROVENANCE_MEASURED
    last_run_at: str = ""
    #: Step keys that would establish or improve this fact. Present even when
    #: the state is `measured` — re-running is how a stale fact is refreshed.
    can_run: list = field(default_factory=list)
    #: Why the state is what it is, in words, when there is something to say.
    note: str = ""

    @property
    def is_known(self) -> bool:
        """Did we actually look, and get an answer?

        `nothing_found` counts: a measured zero is knowledge. `never_run` and
        `not_established` do not.
        """
        return self.state in (MEASURED, NOTHING_FOUND, PARTIAL)

    def as_dict(self) -> dict:
        return {
            "analysis_id": self.analysis_id, "state": self.state,
            "value": self.value, "provenance": self.provenance,
            "last_run_at": self.last_run_at, "can_run": self.can_run,
            "note": self.note, "is_known": self.is_known,
        }


@dataclass
class Envelope:
    """An answer, with everything needed to state it honestly.

    `answerable` is false when nothing was ever measured. A caller must not
    turn an unanswerable envelope into a negative answer -- that is the whole
    reason this type exists rather than returning the values directly.
    """

    subject: str                       # entity slug
    question: str = ""                 # the question text, when there was one
    question_id: str = ""
    kind: str = ""                     # catalog answering.kind, when catalogued
    facts: list = field(default_factory=list)
    #: Why no answer is possible, when none is. Empty when `answerable`.
    blocked_reason: str = ""

    @property
    def answerable(self) -> bool:
        return any(f.is_known for f in self.facts)

    @property
    def can_run(self) -> list:
        """Every step that would improve this answer, deduped, order kept."""
        out: list = []
        for f in self.facts:
            for k in f.can_run:
                if k not in out:
                    out.append(k)
        return out

    def as_dict(self) -> dict:
        return {
            "subject": self.subject, "question": self.question,
            "question_id": self.question_id, "kind": self.kind,
            "answerable": self.answerable,
            "blocked_reason": self.blocked_reason,
            "facts": [f.as_dict() for f in self.facts],
            "can_run": self.can_run,
            # Counted here rather than left to each caller, so two agents
            # cannot disagree about whether the same envelope had an answer.
            "known_count": sum(1 for f in self.facts if f.is_known),
            "unknown_count": sum(1 for f in self.facts if not f.is_known),
        }


#: answering.kind values that no amount of surveying will satisfy. Each is a
#: real answer -- "nothing can answer this yet" is useful and true -- but never
#: an answer about the resource.
UNANSWERABLE_KINDS = {
    "gap": "No mechanism exists for this yet — no analysis produces it.",
    "human": "This comes from human-supplied context (the Enrichment form), "
             "not from any survey.",
    "unknown": "This question has not been classified, so how to answer it "
               "is not recorded.",
}

#: Questions answerable from the resource's own recorded state rather than from
#: an analysis. Declared here, keyed by the catalog's own question text.
#:
#: In code rather than as a CSV column because a field NAME is not enough for
#: most of them: "has this been catalogued in Egeria and when" is two fields
#: read together, "is this worth investigating" is a disposition looked up by
#: github_url in a different table, and "any known feedback" is a row count. A
#: column could name a field; it could not express any of those.
#:
#: Each resolver returns (value_dict, state) — and returns NOTHING_FOUND rather
#: than a fabricated negative when the state is genuinely absent, so "no
#: description" cannot become "this repo does nothing".
def _r_description(reg, p) -> tuple:
    d = (getattr(p, "description", "") or "").strip()
    return ({"description": d}, MEASURED if d else NOTHING_FOUND)


def _r_catalogued(reg, p) -> tuple:
    guid = getattr(p, "egeria_asset_guid", "") or ""
    # The GUID alone says "published at some point"; the publish claims say
    # when. Both, or the answer is half of one.
    published = reg.get_last_published_annotation_types(p.slug) or {}
    when = max(published.values(), default="")
    return ({"catalogued": bool(guid), "egeria_asset_guid": guid,
             "last_published_at": when},
            MEASURED if guid else NOTHING_FOUND)


def _r_surveyed(reg, p) -> tuple:
    when = getattr(p, "last_surveyed_at", "") or ""
    return ({"last_surveyed_at": when, "surveyed": bool(when)},
            MEASURED if when else NOTHING_FOUND)


def _r_disposition(reg, p) -> tuple:
    d = reg.get_disposition(p.github_url) or {}
    verdict = d.get("disposition") or ""
    # `undecided` is the default a resource has before anyone judged it, so it
    # is the absence of an answer, not an answer.
    known = verdict and verdict != "undecided"
    return ({"disposition": verdict, "reason": d.get("reason", ""),
             "decided_at": d.get("decided_at", "")},
            MEASURED if known else NOTHING_FOUND)


def _r_feedback(reg, p) -> tuple:
    rows = reg.list_resource_feedback("repo", p.slug) or []
    return ({"feedback_count": len(rows)}, MEASURED if rows else NOTHING_FOUND)


#: question text -> (resolver, subject). The subject is what the fact is
#: ABOUT, used as the analysis_id slot so the envelope reads sensibly.
RESOURCE_STATE_SOURCES = {
    "What does this repository do?": (_r_description, "description"),
    "Has this repository already been catalogued in Egeria and when?":
        (_r_catalogued, "egeria_catalogue_state"),
    "Has this resource already been surveyed at any tier, and what did earlier signals reveal?":
        (_r_surveyed, "survey_history"),
    "Based on what's already known, is this worth investigating further, or should it be deprioritized?":
        (_r_disposition, "disposition"),
    "Any known feedback?": (_r_feedback, "resource_feedback"),
}

#: Kinds that ARE answerable, but not from analysis results — and not yet
#: readable here. `direct` questions come from a field on the resource
#: (Project.description and the like) and `chart` from a trend series. The
#: catalog names the field in prose ("N/A — direct field (Project.description)")
#: but does not declare it machine-readably, so this layer cannot fetch it
#: without parsing English.
#:
#: Kept apart from UNANSWERABLE_KINDS deliberately: reporting these as "nothing
#: can answer this" would be false, and would hide the largest and cheapest fix
#: in the catalog — 11 of 41 questions, needing a field name each.
UNDECLARED_KINDS = {
    "direct": "Answerable from a field on the resource, but the catalog records "
              "which field only in prose, so it cannot be read automatically yet.",
    "chart": "Answerable from a trend series, which this layer does not read yet.",
}


class FactLayer:
    """Reads what is known about a resource. Never writes, never runs anything."""

    def __init__(self, registry: "ProjectRegistry | None" = None) -> None:
        from resource_explorer.registry import ProjectRegistry

        self._registry = registry or ProjectRegistry()
        self._run_cache: dict = {}

    # ── one analysis ────────────────────────────────────────────────────────
    def fact(self, slug: str, analysis_id: str) -> Fact:
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_RESULTS_MAP,
            REPO_ANALYSIS_STEP_MAP,
        )

        can_run = list(REPO_ANALYSIS_STEP_MAP.get(analysis_id, []))
        run = self._last_run(slug).get(analysis_id, {})
        entry = REPO_ANALYSIS_RESULTS_MAP.get(analysis_id)

        if entry is None:
            # An id with no results reader cannot be read from, whatever it did.
            # egeria_publish is the live example: an action, not an analysis.
            return Fact(
                analysis_id=analysis_id, state=NOT_ESTABLISHED, can_run=can_run,
                note="No results are stored for this analysis — it produces an "
                     "action rather than findings.",
            )

        if not run.get("last_run_at"):
            # The three-state distinction from the Analyses cards, carried
            # through: a repo surveyed by runs too old to record their steps
            # has NOT never-run, we simply cannot say.
            unattributed = run.get("basis") == NOT_ESTABLISHED
            return Fact(
                analysis_id=analysis_id,
                state=NOT_ESTABLISHED if unattributed else NEVER_RUN,
                can_run=can_run,
                note=("This resource was surveyed by runs that predate per-step "
                      "recording, so whether this analysis was among them cannot "
                      "be determined.") if unattributed else
                     "This analysis has never run against this resource.",
            )

        try:
            value = self._read_results(slug, analysis_id, entry)
        except Exception as exc:
            log.debug("results read failed for %s/%s: %s", slug, analysis_id, exc)
            return Fact(
                analysis_id=analysis_id, state=NOT_ESTABLISHED, can_run=can_run,
                last_run_at=run.get("last_run_at", ""),
                note=f"Results could not be read ({type(exc).__name__}).",
            )

        state = self._state_for(value, run)
        return Fact(
            analysis_id=analysis_id, state=state, value=value,
            provenance=self._provenance_for(value),
            last_run_at=run.get("last_run_at", ""), can_run=can_run,
            note=self._note_for(state, value, run),
        )

    def _read_results(self, slug: str, analysis_id: str, entry) -> dict:
        reader = entry[0] if isinstance(entry, (tuple, list)) else entry
        if callable(reader):
            return reader(self._registry, slug) or {}
        reader = getattr(entry, "results_reader", None)
        return (reader(self._registry, slug) or {}) if callable(reader) else {}

    @staticmethod
    def _state_for(value: dict, run: dict) -> str:
        """Measured, nothing-found, or partial — decided from the results.

        A results dict that carries its own `_status` wins: the surveyor knew
        more about its own run than this layer can infer. Only when it says
        nothing do we fall back to looking at whether there is content.
        """
        status = (value or {}).get("_status") or {}
        if status.get("state"):
            return status["state"]
        if run.get("partial"):
            return PARTIAL
        if (value or {}).get("partial"):
            return PARTIAL
        return MEASURED if _has_content(value) else NOTHING_FOUND

    @staticmethod
    def _provenance_for(value: dict) -> str:
        detail = (value or {}).get("detail") or {}
        if isinstance(detail, dict) and detail.get("source") == "egeria":
            return PROVENANCE_EGERIA
        # Components are proposals a detector made. Saying so is what keeps a
        # recovered partition from being reported as an established one.
        if (value or {}).get("components") is not None:
            return PROVENANCE_RECOVERED
        return PROVENANCE_MEASURED

    @staticmethod
    def _note_for(state: str, value: dict, run: dict) -> str:
        if state == NOTHING_FOUND:
            return "This analysis ran and found nothing — a measured zero, not a gap in coverage."
        if state == PARTIAL:
            return "This run covered only part of what the analysis reports on."
        unverified = (value or {}).get("unverified") or []
        if unverified:
            return f"{len(unverified)} item(s) in this result are unverified."
        return ""

    # ── many analyses ───────────────────────────────────────────────────────
    def facts(self, slug: str, analysis_ids: list) -> list:
        return [self.fact(slug, a) for a in analysis_ids]

    def answer(self, slug: str, question: dict) -> Envelope:
        """An envelope for one catalogued question.

        The catalog already states how each question is answerable, so routing
        is a lookup rather than an inference — and for 18 of the 41 the correct
        behaviour is to produce no answer about the resource at all.
        """
        answering = question.get("answering") or {}
        kind = answering.get("kind") or "unknown"
        env = Envelope(
            subject=slug, question=question.get("question", ""),
            question_id=question.get("question", ""), kind=kind,
        )
        # A declared resource-state source answers before the kind is
        # consulted: `direct` describes where the answer lives, and once that
        # is declared the question is answerable regardless of the label.
        declared = RESOURCE_STATE_SOURCES.get(question.get("question", ""))
        if declared:
            env.facts = [self._resource_state_fact(slug, *declared)]
            if not env.answerable:
                env.blocked_reason = (
                    "Nothing is recorded for this on this resource yet."
                )
            return env

        for table in (UNANSWERABLE_KINDS, UNDECLARED_KINDS):
            if kind in table:
                env.blocked_reason = table[kind]
                note = (answering.get("note") or "").strip()
                if note:
                    env.blocked_reason += f" ({note[:200]})"
                return env

        ids = answering.get("analysis_ids") or []
        if not ids:
            env.blocked_reason = (
                "This question declares no analysis that answers it, so there is "
                "nothing to read."
            )
            return env
        env.facts = self.facts(slug, ids)
        if not env.answerable:
            env.blocked_reason = (
                "Nothing has been measured for this yet."
                + (f" Run: {', '.join(env.can_run)}." if env.can_run else "")
            )
        return env

    # ── internals ───────────────────────────────────────────────────────────
    def _resource_state_fact(self, slug: str, resolver, subject: str) -> Fact:
        """A fact read from the resource's own state, not from an analysis.

        `can_run` is empty on purpose: no survey step establishes these. Saying
        "run X to find out" when nothing would change the answer is the same
        false offer the envelope exists to prevent, one step further on.
        """
        project = self._registry.get(slug)
        if not project:
            return Fact(subject, NOT_ESTABLISHED,
                        note=f"No resource named {slug!r} is registered.")
        try:
            value, state = resolver(self._registry, project)
        except Exception as exc:
            log.debug("resource-state resolver failed for %s/%s: %s", slug, subject, exc)
            return Fact(subject, NOT_ESTABLISHED,
                        note=f"Could not be read ({type(exc).__name__}).")
        return Fact(
            subject, state, value=value, provenance=PROVENANCE_MEASURED,
            note=("Nothing is recorded for this — a real absence, not an "
                  "unrun analysis." if state == NOTHING_FOUND else ""),
        )

    def _last_run(self, slug: str) -> dict:
        """{analysis_id: {last_run_at, basis, partial}} — one query per resource.

        Reuses get_analysis_last_run, which credits an analysis for running as
        part of a SURVEY, not only via its own Run button. Reading only the
        latter is what made every analysis on every repo report never-run.
        """
        if slug in self._run_cache:
            return self._run_cache[slug]
        raw = self._registry.get_analysis_last_run("repo", slug)
        unattributed = raw.pop("__unattributed_surveys__", {}).get("count", 0)
        out = {
            k: {
                "last_run_at": v.get("last_run_at", ""),
                "partial": bool(v.get("last_run_partial")),
                "basis": MEASURED if v.get("last_run_at") else NEVER_RUN,
            }
            for k, v in raw.items()
        }
        if unattributed:
            # Recorded per-analysis so `fact()` can tell "never ran" from
            # "cannot say", without every caller re-deriving it.
            out.setdefault("__unattributed__", {"count": unattributed})
        self._run_cache[slug] = _WithDefault(out, unattributed)
        return self._run_cache[slug]


class _WithDefault(dict):
    """Missing analyses report not_established when unattributed surveys exist.

    A repo whose only surveys predate step recording has no row for ANY
    analysis, and every one of them is "cannot say" rather than "never ran".
    Expressing that as a dict default keeps the distinction in one place.
    """

    def __init__(self, data: dict, unattributed: int) -> None:
        super().__init__(data)
        self._unattributed = unattributed

    def get(self, key, default=None):  # type: ignore[override]
        if key in self:
            return dict.__getitem__(self, key)
        if self._unattributed:
            return {"last_run_at": "", "partial": False, "basis": NOT_ESTABLISHED}
        return default if default is not None else {}


def _has_content(value) -> bool:
    """Is there anything here beyond the envelope keys?

    `_status`, `surveyed_at` and `detail` describe the run, not the finding. A
    results dict carrying only those has measured nothing, and counting them as
    content is how an empty result came to render as a populated one.
    """
    envelope = {"_status", "surveyed_at", "detail", "scoped_to", "run_outcomes"}
    if isinstance(value, dict):
        return any(
            _has_content(v) for k, v in value.items() if k not in envelope
        )
    if isinstance(value, (list, tuple, set)):
        return any(_has_content(v) for v in value)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return value is not None
