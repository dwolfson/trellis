"""Profile publish reshape: re-link an unchanged value-profile measure, create a changed one.

BRIEF-PROFILE-PUBLISH-RESHAPE (ruling 2026-10-22): Egeria's own survey re-links unchanged annotations to its new
report and creates annotations only for changed measures. RE does the same for the value profile's per-column
`ResourceProfileAnnotation`s (`value_profile.build_annotations`).

The key is (resource, analysis step, `item_key`), the column path as the compact JSON array
`["schema","table","column"]` (`value_profile.measure_key`). A measure is unchanged when the sha256 of its canonical
JSON (`content_hash`: `PROFILE_SHAPE_VERSION`, `value_count` plus `generalType`, `profileDates` and `sampleRatio`
from `json_properties`) equals the hash on RE's own LATEST HASHED proof row for that key across every RE report of
the resource (`registry.latest_profile_publish`), never a re-read of Egeria. Pure: no Egeria, no registry.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from resource_explorer.surveyors.database.quality.value_profile import ANALYSIS_STEP

#: The shape of the canonical measures, hashed with them: a change to what is compared (a new key, a renamed one)
#: bumps it, so every measure reads as changed once instead of matching an old hash by accident.
PROFILE_SHAPE_VERSION = 1

#: The json_properties keys a measure is compared on. `ranAs` (who ran the profile) is provenance, not a measure.
COMPARED_PROPERTIES = ("generalType", "profileDates", "sampleRatio")

CREATED, RELINKED, NO_LONGER_MEASURED = "created", "relinked", "no_longer_measured"
#: A previous measure whose TABLE was not profiled this run (timed out, refused, not profiled): not measured, which
#: is never "no longer measured" (the column may well still be there).
NOT_MEASURED_THIS_RUN = "not_measured_this_run"
#: The proof-row note of a measure planned for re-link that Egeria refused (the annotation archived, deleted or
#: wiped), and so created again in the same run.
RECREATED_NOTE = "re-created: the re-used annotation was gone"


def table_of(item_key: str) -> str:
    """The "schema.table" of a measure's key, as the value profile names a table it did not profile; "" for a key
    that is not the JSON array."""
    try:
        schema, table, _column = json.loads(item_key)
    except (TypeError, ValueError):
        return ""
    return f"{schema}.{table}"


def tables_not_profiled(annotations: list) -> set[str]:
    """The tables this run's value profile did not profile: its `ResourceMeasureAnnotation`s (one per such table,
    `item_key` "schema.table")."""
    from resource_explorer.surveyors.survey_report import ResourceMeasureAnnotation

    return {a.item_key for a in annotations
            if isinstance(a, ResourceMeasureAnnotation) and a.analysis_step == ANALYSIS_STEP and a.item_key}


def is_profile_measure(annotation) -> bool:
    """One of the value profile's per-column measures (the only annotations this reshape re-links)."""
    from resource_explorer.surveyors.survey_report import ResourceProfileAnnotation

    return (isinstance(annotation, ResourceProfileAnnotation) and annotation.analysis_step == ANALYSIS_STEP
            and bool(annotation.item_key))


def canonical_measures(annotation) -> dict:
    """What a measure is compared on: `value_count`, and the compared keys of `json_properties`. A key absent
    from json_properties is absent here (absent then present is a change)."""
    props = annotation.json_properties or {}
    return {"shape_version": PROFILE_SHAPE_VERSION,
            "value_count": dict(annotation.value_count or {}),
            "json_properties": {k: props[k] for k in COMPARED_PROPERTIES if k in props}}


def content_hash(annotation) -> str:
    """sha256 over the canonical JSON: keys sorted, no whitespace, numbers exact (an int and a float are
    different text, so they never compare equal by accident), dates as strings."""
    text = json.dumps(canonical_measures(annotation), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ProfilePlan:
    """For each profile measure in this publish (by its index in the publish's annotation list): its key, its
    hash, and the previous annotation's GUID when it is to be re-linked. `gone`: previous measures this run did not
    measure and whose table it did profile ({item_key: previous annotation GUID}), each counted once (a key whose
    latest proof row already says so is not counted again). `not_measured`: previous measures whose table this run
    did not profile. `recreated`: indices planned for re-link that Egeria refused, created instead."""
    previous_report_guid: str = ""
    previous_report_at: str = ""
    keys: dict[int, str] = field(default_factory=dict)
    hashes: dict[int, str] = field(default_factory=dict)
    relink: dict[int, str] = field(default_factory=dict)
    gone: dict[str, str] = field(default_factory=dict)
    not_measured: dict[str, str] = field(default_factory=dict)
    recreated: set[int] = field(default_factory=set)

    @property
    def create(self) -> list[int]:
        return [i for i in self.keys if i not in self.relink]

    def recreate(self, indices) -> None:
        """Egeria refused these re-links (the annotation is gone): create them in this run instead."""
        for i in indices:
            if self.relink.pop(i, None) is not None:
                self.recreated.add(i)


def plan_profile_publish(annotations: list, previous: dict | None) -> ProfilePlan:
    """Which profile measures to re-link and which to create, against `previous`
    (`registry.latest_profile_publish`, or None when nothing was published before)."""
    measures = (previous or {}).get("measures") or {}
    already_gone = set((previous or {}).get("gone_keys") or ())
    unprofiled = tables_not_profiled(annotations)
    plan = ProfilePlan(previous_report_guid=(previous or {}).get("report_guid", ""),
                       previous_report_at=(previous or {}).get("report_at", ""))
    seen: set[str] = set()
    for i, ann in enumerate(annotations):
        if not is_profile_measure(ann):
            continue
        key = ann.item_key
        plan.keys[i], plan.hashes[i] = key, content_hash(ann)
        seen.add(key)
        before = measures.get(key)
        if before and before.get("content_hash") == plan.hashes[i] and before.get("annotation_guid"):
            plan.relink[i] = before["annotation_guid"]
    for key, before in measures.items():
        if key in seen or not before.get("annotation_guid"):
            continue
        if table_of(key) in unprofiled:
            plan.not_measured[key] = before["annotation_guid"]
        elif key not in already_gone:
            plan.gone[key] = before["annotation_guid"]
    return plan


def _date(at: str) -> str:
    return (at or "")[:10]


def profile_publish_words(counts: dict | None) -> str:
    """The run card's line, from the publish's proof rows only (`registry.profile_publish_counts`):
    "N measures published · M changed since <previous report date> · K re-used · J no longer measured", and
    " · T not measured this run" when a previous measure's table was not profiled this run.
    With no earlier publish to compare with, "N measures published · first profile published". "" when the
    publish has no profile proof rows."""
    if not counts or not counts.get("rows"):
        return ""
    n, m, k, j, t = (counts.get(x, 0) for x in ("published", CREATED, RELINKED, NO_LONGER_MEASURED,
                                                  NOT_MEASURED_THIS_RUN))
    if not counts.get("previous_report_at"):
        return f"{n} measures published · first profile published"
    return (f"{n} measures published · {m} changed since {_date(counts['previous_report_at'])}"
            f" · {k} re-used · {j} no longer measured" + (f" · {t} not measured this run" if t else ""))
