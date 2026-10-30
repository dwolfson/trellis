"""One generic reader per annotation type (R7; extensibility brief 2c, its first instance).

A step's stored annotations are read by their TYPE, not by the step that wrote them, so a new step of a known
type needs no reader of its own. The reader derives each row's state from the annotation's envelope
(`additionalProperties.resultState`, the interim carrier, owner ruling 2026-10-07) and never from its value: a
value of 0 is not "nothing found", and a missing value is not "not established". A row with no envelope says
"no envelope"; it is never given a state the step did not state.

Rows come back in the Analysis pane's measurement shape (`{name, value, opens, note}`, plus `state`,
`state_words` and `reason`), so `stage_page.build_measurements` hands them over unflattened.
"""
from __future__ import annotations

from collections.abc import Callable

#: The four envelope states and their words (the same words as trellis_analytics' ResultState). Kept here so
#: Resource Explorer reads stored rows without the library installed.
STATE_WORDS = {
    "measured": "measured",
    "nothing_found": "nothing found",
    "not_established": "not established",
    "not_applicable": "not applicable",
}
NO_ENVELOPE = "no envelope"


def _envelope_state(detail: dict) -> tuple[str, str, str]:
    """(state, words, reason) from the stored envelope alone."""
    props = (detail or {}).get("additionalProperties") or {}
    state = props.get("resultState") or ""
    if state not in STATE_WORDS:
        return "", NO_ENVELOPE, ""
    return state, STATE_WORDS[state], props.get("resultStateReason") or ""


def read_resource_measure_rows(registry, entity_type: str, slug: str, analysis_step: str) -> tuple[str, list[dict]]:
    """ResourceMeasureAnnotation: one row per annotation of the step's latest run."""
    run, stored = registry.query_step_annotations(entity_type, slug, analysis_step)
    rows = []
    for a in stored:
        detail = a.get("detail") or {}
        state, words, reason = _envelope_state(detail)
        rows.append({
            "name": a.get("scope") or detail.get("scope") or "",
            # The step's own sentence for what it measured; empty when it did not measure (the reason is
            # shown beside the state words instead, once).
            "value": a.get("summary") or "",
            "opens": None,
            "note": "",
            "state": state,
            "state_words": words,
            "reason": reason,
            "properties": detail.get("resourceProperties") or {},
            # Which of the step's declared measures this row is ("" its own, primary one), where the row says. The
            # host stores each further measure under its own key (`measure_step_key`), so a reader of one key sees
            # one measure; `declared_context.measure_records` reads each measure from its key.
            "measure": detail.get("measure") or (detail.get("additionalProperties") or {}).get("measure") or "",
            "annotation_type": a.get("annotation_type") or "",
            "run": run,
        })
    return run, rows


#: annotation type -> reader. One entry per type; a step of a listed type is readable with no new code.
READERS: dict[str, Callable] = {
    "ResourceMeasureAnnotation": read_resource_measure_rows,
    # A file system's library steps (Files build step 6) publish Egeria's folder-survey types. Their stored rows carry
    # the same envelope, scope, summary and resourceProperties, so they are read the same way.
    "ResourceProfileAnnotation": read_resource_measure_rows,
    "RequestForActionAnnotation": read_resource_measure_rows,
}


def measurement_rows(registry, entity_type: str, slug: str, analysis_step: str, annotation_type: str) -> list[dict]:
    reader = READERS.get(annotation_type)
    if reader is None:
        raise LookupError(f"no reader for annotation type '{annotation_type}' (readers: {', '.join(READERS)})")
    return reader(registry, entity_type, slug, analysis_step)[1]


def results_reader(entity_type: str, analysis_step: str, annotation_type: str) -> Callable:
    """A `(registry, slug) -> dict` results reader for the analysis maps: `measurement_rows` (already shaped,
    which build_measurements passes through), the run they came from, and a count per state."""
    def read(registry, slug: str) -> dict:
        run, rows = READERS[annotation_type](registry, entity_type, slug, analysis_step)
        if not rows:
            return {}
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["state_words"]] = counts.get(r["state_words"], 0) + 1
        return {"measurement_rows": rows, "run": run, "state_counts": counts}
    read.__name__ = f"{analysis_step}_results"
    return read


def _step_sentence(row: dict) -> str:
    """The step's own sentence for one stored result, the way the Survey tab's "Derived from the walk" reads it: the state
    words, then what the step said, and its reason when it could not measure (never a count of results)."""
    said = row.get("summary") or row.get("value") or ""
    out = f"{row.get('state_words') or NO_ENVELOPE} · {said}".rstrip(" ·") if said else str(row.get("state_words") or NO_ENVELOPE)
    reason = row.get("reason")
    return f"{out} · {reason}" if reason and row.get("state") in ("not_established", "not_applicable") else out


def _declared_summary(registry, entity_type: str, slug: str, step: str) -> dict | None:
    """The step's resource-scoped measure record (its one-per-database summary), when it declares one and it ran.

    A step declaring several takes the FIRST in the manifest's declaration order that ran and has a summary
    (`measure_records` walks `dec.measures` in order), so the headline is stable across reads and the author picks it
    by ordering the declaration. The others are not dropped: `declared_measure_rows` gives each its own drill-down row."""
    from resource_explorer.surveyors.analysis_catalog_reader import _load
    from resource_explorer import declared_context

    for entry in _load().get(entity_type, []):
        provided = getattr(entry, "provided_by", None) or {}
        if (provided.get("step") or entry.id) != step or not getattr(entry, "declaration", None):
            continue
        for rec in declared_context.measure_records(registry, entity_type, slug, step, entry.declaration, entry.id).values():
            if rec.get("summary"):
                return {**rec, "state_words": STATE_WORDS.get(rec.get("state") or "", NO_ENVELOPE)}
    return None


def declared_measure_rows(registry, entity_type: str, slug: str, step: str) -> list[dict]:
    """The step's further resource-scoped measures as drill-down rows, each with its own stated state (F19).

    The host stores the step's own measure under the step key and each further declared measure under its own key, so
    the results reader sees only the first. A measure that could not be measured (fs_activity's access bands on a walk
    that kept no access times) is its own row: its state word and its reason, the sentence the step gave, never a
    number and never the whole step's state. Empty when the step declares nothing more."""
    from resource_explorer.surveyors.analysis_catalog_reader import _load
    from resource_explorer import declared_context

    for entry in _load().get(entity_type, []):
        provided = getattr(entry, "provided_by", None) or {}
        if (provided.get("step") or entry.id) != step or not getattr(entry, "declaration", None):
            continue
        names = [m.name for m in entry.declaration.measures]
        primary = next((n for n in (step, entry.id) if n in names), names[0] if names else "")
        out = []
        for name, rec in declared_context.measure_records(registry, entity_type, slug, step, entry.declaration, entry.id).items():
            if name == primary:
                continue          # the results reader already returned the step's own measure
            state = rec.get("state") or ""
            words = STATE_WORDS.get(state, NO_ENVELOPE)
            out.append({"name": name, "value": rec.get("summary") or rec.get("reason") or words, "opens": None, "note": "",
                        "state": state, "state_words": words, "reason": rec.get("reason") or "",
                        "properties": rec.get("value") or {}, "measure": name, "annotation_type": "", "run": rec.get("run")})
        return out
    return []


def headline_reader(entity_type: str, analysis_step: str, annotation_type: str) -> Callable:
    """The one-line answer for a library step: the step's own sentence, the one the Survey tab shows for the same rows
    (F21). A step with one result says it; one with a declared resource-scoped summary says that; only a step with
    several plain results and no summary says how many, by state."""
    reader = results_reader(entity_type, analysis_step, annotation_type)

    def headline(registry, slug: str) -> dict | None:
        value = reader(registry, slug)
        if not value:
            return None
        rows = value["measurement_rows"]
        summary = _declared_summary(registry, entity_type, slug, analysis_step)
        if summary:
            return {"label": _step_sentence(summary), "status": "info"}
        if len(rows) == 1:
            return {"label": _step_sentence(rows[0]), "status": "info"}
        counts = value["state_counts"]
        order = [*STATE_WORDS.values(), NO_ENVELOPE]
        parts = [f"{counts[w]} {w}" for w in order if counts.get(w)]
        n = len(rows)
        return {"label": f"{n} results: " + " · ".join(parts), "status": "info"}
    return headline
