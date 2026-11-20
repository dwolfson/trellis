#!/usr/bin/env python3
"""Generate all of RE's filesystem Survey Definition Dr.Egeria docs from the
filesystem STEP_REGISTRY — reproducible artifacts that publish filesystem
analysis steps as real GovernanceActionProcessStep elements and chain them into
runnable Survey Definitions, one per UI surface (survey_kind).

This mirrors generate_repo_survey_definition.py but for filesystem resources.

Analysis-step Egeria registration plan, D1-D3
(docs/analysis-step-egeria-registration-plan.md), extended per
docs/discovery-automate-project-context-plan.md Part 1 to generate separate
Survey Definitions for different survey kinds:

- **scouting** — "Filesystem Scouting Survey": the fast pass (reachability,
  walk, file_profiles)
- **analysis** — "Filesystem Analysis Survey": every current analysis step,
  chained — the comprehensive bundle for an already-tracked resource.

Run this whenever filesystem STEP_REGISTRY changes (a step added/removed/re-described),
then execute the regenerated doc(s) against Egeria to keep Discovery/
Scouting/Automate's candidate lists in sync. IMPORTANT: after executing a
regenerated doc against an *already-linked* process (i.e. every time except
the very first authoring), run
`uv run python scripts/reconcile_survey_definition_links.py` afterward —
Dr.Egeria's "Link First/Next Process Step" commands are not idempotent and
will duplicate or leave stale the step-to-step links, which makes
SurveyDefinitionReader see "branching" and refuse to run the Survey
Definition at all (a real live incident, 2026-08-13 — see that script's and
survey_definition_reconciler.py's docstrings for the full story).

Also emits one "Link Element To Scope" ScopedBy block per Question each
generated Survey Definition answers (docs/survey-question-context-plan.md
D1) — the join is: each step_key's containing analysis_catalog id (via
FILESYSTEM_ANALYSIS_STEP_MAP) cross-referenced against question_catalog.yaml's
per-question answering.analysis_ids. Run docs/dr-egeria/foundations.md and
docs/dr-egeria/scouting-questions.md (or their generated equivalents)
first — the Question terms these blocks reference by name must already
exist in Egeria before this doc is executed.

This is the one resource-type-specific piece of the mechanism — everything
it calls (resource_explorer.surveyors.dr_egeria_survey_publisher) is
resource-type-agnostic, so a future database/filesystem equivalent of this
script just needs its own PublishableStep list(s) built from whatever
registry that resource type uses.
"""
from __future__ import annotations

import argparse
import os
import hashlib
import json

import csv
from dataclasses import dataclass
from pathlib import Path

# Import the common publisher module
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resource_explorer.surveyors.dr_egeria_survey_publisher import (
    PublishableStep,
    generate_survey_definition_markdown,
)
from resource_explorer.surveyors.question_catalog_reader import get_questions
from resource_explorer.surveyors.filesystem.survey_definition_adapter import (
    FILESYSTEM_ANALYSIS_STEP_MAP,
    FILESYSTEM_ANALYSIS_KINDS,
)

# Technology type for filesystem resources
TECHNOLOGY_TYPE = "File System Directory"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria"
SPECS_CSV = DOCS_DIR / "filesystem_survey_types.csv"

# Generated documents live in the survey-definitions *batch folder*
SURVEY_DEFS_DIR = DOCS_DIR / "survey-definitions"
ALL_STEPS_SENTINEL = "*"


@dataclass(frozen=True)
class SurveyDefSpec:
    survey_kind: str
    survey_group: str
    survey_display_name: str
    description: str
    step_keys: list[str]  # order matters — this is the chain order
    output_filename: str


class SurveyTypesCsvError(ValueError):
    """Raised on a malformed or STEP_REGISTRY-mismatched filesystem_survey_types.csv."""


def load_specs_from_csv(csv_path: Path = SPECS_CSV) -> list[SurveyDefSpec]:
    groups: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["survey_kind"], row["survey_group"])
            if key not in groups:
                groups[key] = {
                    "survey_display_name": row["survey_display_name"],
                    "description": row["description"],
                    "output_filename": row["output_filename"],
                    "steps": [],  # (step_order, step_key)
                }
                order.append(key)
            groups[key]["steps"].append((int(row["step_order"]), row["step_key"]))

    specs = []
    for survey_kind, survey_group in order:
        g = groups[(survey_kind, survey_group)]
        step_keys = [key for _, key in sorted(g["steps"])]
        if step_keys == [ALL_STEPS_SENTINEL]:
            # Get all steps from FILESYSTEM_ANALYSIS_STEP_MAP
            step_keys = list(FILESYSTEM_ANALYSIS_STEP_MAP.keys())
        else:
            # Check both FILESYSTEM_ANALYSIS_STEP_MAP (steps) and FILESYSTEM_ANALYSIS_KINDS (analysis kinds)
            all_known_keys = set(FILESYSTEM_ANALYSIS_STEP_MAP.keys()) | set(FILESYSTEM_ANALYSIS_KINDS.keys())
            unknown = [k for k in step_keys if k not in all_known_keys]
            if unknown:
                raise SurveyTypesCsvError(
                    f"{survey_group}: step_key(s) not found in FILESYSTEM_ANALYSIS_STEP_MAP or FILESYSTEM_ANALYSIS_KINDS: {unknown} "
                    f"(typo in {csv_path.name}, or a step was removed from FILESYSTEM_ANALYSIS_STEP_MAP "
                    f"without updating the CSV)"
                )
        specs.append(
            SurveyDefSpec(
                survey_kind=survey_kind,
                survey_group=survey_group,
                survey_display_name=g["survey_display_name"],
                description=g["description"],
                step_keys=step_keys,
                output_filename=g["output_filename"],
            )
        )

    # Coverage guard: every FILESYSTEM_ANALYSIS_STEP_MAP step should appear in at least
    # one CSV-authored survey (directly, or via the "*" sentinel)
    referenced = {key for spec in specs for key in spec.step_keys}
    # Only check steps, not analysis kinds (like resource_reachability)
    referenced_steps = {key for spec in specs for key in spec.step_keys if key in FILESYSTEM_ANALYSIS_STEP_MAP}
    unreferenced = [key for key in FILESYSTEM_ANALYSIS_STEP_MAP if key not in referenced_steps]
    if unreferenced:
        print(
            f"WARNING: FILESYSTEM_ANALYSIS_STEP_MAP step(s) with no Survey Type reference "
            f"in {csv_path.name}: {unreferenced}"
        )
    return specs


SPECS = load_specs_from_csv()


def build_steps(step_keys: list[str]) -> list[PublishableStep]:
    """Build PublishableStep objects for each step_key.

    For filesystem resources, all steps run via the local RE walk path
    (executes_at: resource-explorer) since Egeria's Folder Survey handles
    the reach decision and RE's walk is the fallback.
    """
    return [
        PublishableStep(
            step_key=key,
            description=_get_step_description(key),
            technology_type=TECHNOLOGY_TYPE,
            executes_at="resource-explorer",  # All filesystem steps run locally
        )
        for key in step_keys
    ]


def _get_step_description(step_key: str) -> str:
    """Get the description for a filesystem step."""
    descriptions = {
        "resource_reachability": "Check whether Egeria's Folder Survey or Resource Explorer's walk leads for this filesystem path.",
        "filesystem_inventory": "Walk the filesystem (counts, sizes, hidden/symlink/executable/writable flags, timestamps), flag inaccessible/unclassified files, and profile data file schemas.",
        "file_profiles": "Profile tabular data files (CSV, Excel, Parquet) for column schemas and types.",
        "narrative_docs": "Read narrative files (README, docs) for content extraction.",
        "file_data_class_match": "Match file columns to data classes from Egeria's catalog.",
        "fs_activity": "Track file system activity patterns over time.",
        "fs_change_rates": "Measure file and folder change rates.",
        "fs_duplicates": "Detect duplicate files in the filesystem.",
        "fs_permissions": "Analyze file and folder permissions.",
        "fs_layout_signals": "Extract layout signals from the filesystem structure.",
    }
    return descriptions.get(step_key, f"Filesystem analysis step: {step_key}")


def _build_step_key_to_questions() -> dict[str, list[str]]:
    """Invert question_catalog.yaml's answering.analysis_ids through
    FILESYSTEM_ANALYSIS_STEP_MAP to get step_key -> [question display names].
    """
    mapping: dict[str, list[str]] = {}
    for entry in get_questions(resource_type="filesystem"):
        for analysis_id in entry.get("answering", {}).get("analysis_ids", []):
            for step_key in FILESYSTEM_ANALYSIS_STEP_MAP.get(analysis_id, []):
                mapping.setdefault(step_key, [])
                if entry["question"] not in mapping[step_key]:
                    mapping[step_key].append(entry["question"])
    return mapping


def _answered_questions(step_keys: list[str], step_key_to_questions: dict[str, list[str]]) -> list[str]:
    """Union of questions answered by any step in this Survey Definition."""
    seen: list[str] = []
    for key in step_keys:
        for question in step_key_to_questions.get(key, []):
            if question not in seen:
                seen.append(question)
    return seen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite documents that have been edited since they were "
             "generated. This DISCARDS guards, request parameters and any "
             "other detail the CSV cannot express.",
    )
    args = parser.parse_args()

    SURVEY_DEFS_DIR.mkdir(parents=True, exist_ok=True)
    provenance = _load_provenance()
    skipped: list[str] = []
    step_key_to_questions = _build_step_key_to_questions()

    for spec in SPECS:
        steps = build_steps(spec.step_keys)
        answers_questions = _answered_questions(spec.step_keys, step_key_to_questions)

        markdown = generate_survey_definition_markdown(
            survey_group=spec.survey_group,
            survey_display_name=spec.survey_display_name,
            technology_type=TECHNOLOGY_TYPE,
            description=spec.description,
            steps=steps,
            answers_questions=answers_questions,
        )

        output_path = SURVEY_DEFS_DIR / spec.output_filename
        existing_content = ""
        try:
            existing_content = output_path.read_text()
        except OSError:
            pass

        if not args.force and _file_has_been_edited(output_path, existing_content, markdown, provenance):
            print(f"SKIPPED: {output_path.name} (has been edited since last generation)")
            skipped.append(output_path.name)
            continue

        output_path.write_text(markdown)
        print(f"WROTE: {output_path.name}")

    # Update provenance
    new_provenance = _load_provenance()
    for spec in SPECS:
        output_path = SURVEY_DEFS_DIR / spec.output_filename
        try:
            content = output_path.read_text()
            new_provenance[output_path.name] = _digest(content)
        except OSError:
            pass
    _write_provenance(new_provenance)

    if skipped:
        print(f"\nSkipped {len(skipped)} file(s) that have been edited:")
        for name in skipped:
            print(f"  - {name}")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_provenance() -> dict:
    try:
        return json.loads(PROVENANCE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _write_provenance(record: dict) -> None:
    PROVENANCE_FILE.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def _file_has_been_edited(path: Path, existing: str, generated: str, provenance: dict) -> bool:
    """Check if a file has been edited since it was last generated."""
    filename = path.name
    if filename not in provenance:
        return False  # No record means we can't prove it's untouched
    if _digest(existing) == provenance[filename]:
        return False  # Content matches what we last wrote
    return True


PROVENANCE_FILE = SURVEY_DEFS_DIR / ".generated_filesystem.json"


if __name__ == "__main__":
    main()
