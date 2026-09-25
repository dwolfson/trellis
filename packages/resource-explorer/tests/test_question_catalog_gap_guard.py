"""A question may not advertise a gap that the analysis catalog contradicts.

`kind: gap` is a load-bearing claim: the UI renders "No mechanism exists for
this yet" and offers no Run button (`can_run` is empty). The guide is explicit
that this is the honest answer more often than it feels like it is -- but only
while it is true.

It stopped being true for the database work. The rows were authored on
2026-09-20 with `GAP: <id> (proposed)` where no analysis existed yet, which was
correct then. The slices that followed built those analyses and registered them
in `analysis_catalog.yaml`, but each slice is forbidden from editing the CSV
(see COORDINATOR-BRIEF-MULTI-RESOURCE.md stream 4, and
POSTGRES-NESTED-COLUMNS-IMPLEMENTED.md section 5, which observes that
restriction "to the letter" and refreshes only the generated YAML). So the
regeneration picks up `analysis_ids: [<id>]` while `kind` stays `gap`, because
kind comes from the `GAP:` prefix in the CSV that the slice may not touch.

`test_a_clean_tree_regenerates_to_nothing` cannot see this: the YAML is exactly
what the CSV generates. Both artifacts agree, and both are wrong about the code.
This guard closes that loop by checking the claim against the built analyses
instead of against the CSV.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "resource_explorer" / "configdata" / "question_catalog.yaml"
ANALYSES = ROOT / "resource_explorer" / "configdata" / "analysis_catalog.yaml"


def _built_analysis_ids() -> set[str]:
    """Every id registered in analysis_catalog.yaml, across all `*_analyses`
    sections -- the ids the fact layer can actually resolve."""
    catalog = yaml.safe_load(ANALYSES.read_text(encoding="utf-8")) or {}
    ids: set[str] = set()
    for section, entries in catalog.items():
        if not section.endswith("_analyses") or not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id"):
                ids.add(entry["id"])
    return ids


def test_no_question_claims_a_gap_for_an_analysis_that_exists():
    built = _built_analysis_ids()
    assert built, f"{ANALYSES.name} yielded no analysis ids -- the loader is wrong, not the catalog"

    offenders: list[str] = []
    for section, questions in (yaml.safe_load(QUESTIONS.read_text(encoding="utf-8")) or {}).items():
        if not isinstance(questions, list):
            continue
        for question in questions:
            answering = question.get("answering") or {}
            if answering.get("kind") != "gap":
                continue
            live = sorted(set(answering.get("analysis_ids") or []) & built)
            if live:
                offenders.append(
                    f"  [{section}] {question.get('question', '')[:78]}\n"
                    f"      claims a gap, but {', '.join(live)} "
                    f"{'is' if len(live) == 1 else 'are'} in {ANALYSES.name}"
                )

    assert not offenders, (
        f"{len(offenders)} question(s) advertise 'No mechanism exists for this yet' "
        f"for an analysis that is built and registered:\n\n"
        + "\n".join(offenders)
        + "\n\nThe UI hides a working analysis behind each of these, and offers no Run "
        "button. Fix the CSV row -- replace `GAP: <id> (proposed) ...` in "
        "`Answering Analysis` with the bare id (or MIXED:/PARTIAL: if it only answers "
        "part of the question) -- then regenerate:\n"
        "  python scripts/csv_to_question_catalog_yaml.py "
        "docs/dr-egeria/resource_questions.csv "
        "--output resource_explorer/configdata/question_catalog.yaml\n"
        "Never edit the YAML by hand."
    )
