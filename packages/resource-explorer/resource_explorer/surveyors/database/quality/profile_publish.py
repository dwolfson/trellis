"""Profile publish reshape: re-link an unchanged value-profile measure, create a changed one.

BRIEF-PROFILE-PUBLISH-RESHAPE (ruling 2026-10-22): Egeria's own survey re-links unchanged annotations to its new
report and creates annotations only for changed measures. RE does the same for the value profile's per-column
`ResourceProfileAnnotation`s (`value_profile.build_annotations`).

The key is (resource, analysis step, `item_key`), the column path "schema.table.column". A measure is unchanged
when the sha256 of its canonical JSON (`content_hash`: `value_count` plus `generalType`, `profileDates` and
`sampleRatio` from `json_properties`) equals the hash on RE's own proof row of the LAST PUBLISHED annotation for
that key (`registry.latest_profile_publish`), never a re-read of Egeria. Pure: no Egeria, no registry.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from resource_explorer.surveyors.database.quality.value_profile import ANALYSIS_STEP

#: The json_properties keys a measure is compared on. `ranAs` (who ran the profile) is provenance, not a measure.
COMPARED_PROPERTIES = ("generalType", "profileDates", "sampleRatio")

CREATED, RELINKED, NO_LONGER_MEASURED = "created", "relinked", "no_longer_measured"


def is_profile_measure(annotation) -> bool:
    """One of the value profile's per-column measures (the only annotations this reshape re-links)."""
    from resource_explorer.surveyors.survey_report import ResourceProfileAnnotation

    return (isinstance(annotation, ResourceProfileAnnotation) and annotation.analysis_step == ANALYSIS_STEP
            and bool(annotation.item_key))


def canonical_measures(annotation) -> dict:
    """What a measure is compared on: `value_count`, and the compared keys of `json_properties`. A key absent
    from json_properties is absent here (absent then present is a change)."""
    props = annotation.json_properties or {}
    return {"value_count": dict(annotation.value_count or {}),
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
    measure ({item_key: previous annotation GUID})."""
    previous_report_guid: str = ""
    previous_report_at: str = ""
    keys: dict[int, str] = field(default_factory=dict)
    hashes: dict[int, str] = field(default_factory=dict)
    relink: dict[int, str] = field(default_factory=dict)
    gone: dict[str, str] = field(default_factory=dict)

    @property
    def create(self) -> list[int]:
        return [i for i in self.keys if i not in self.relink]


def plan_profile_publish(annotations: list, previous: dict | None) -> ProfilePlan:
    """Which profile measures to re-link and which to create, against `previous`
    (`registry.latest_profile_publish`, or None when nothing was published before)."""
    measures = (previous or {}).get("measures") or {}
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
    plan.gone = {k: v["annotation_guid"] for k, v in measures.items() if k not in seen and v.get("annotation_guid")}
    return plan


def _date(at: str) -> str:
    return (at or "")[:10]


def profile_publish_words(counts: dict | None) -> str:
    """The run card's line, from the publish's proof rows only (`registry.profile_publish_counts`):
    "N measures published · M changed since <previous report date> · K re-used · J no longer measured".
    With no earlier publish to compare with, "N measures published · first profile published". "" when the
    publish has no profile proof rows."""
    if not counts or not counts.get("rows"):
        return ""
    n, m, k, j = (counts.get(x, 0) for x in ("published", CREATED, RELINKED, NO_LONGER_MEASURED))
    if not counts.get("previous_report_at"):
        return f"{n} measures published · first profile published"
    return (f"{n} measures published · {m} changed since {_date(counts['previous_report_at'])}"
            f" · {k} re-used · {j} no longer measured")
