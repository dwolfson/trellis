"""Is everything RE can do actually reachable by a user?

Four separate faults this session were all the same shape: the capability
existed, its code ran, nothing errored, and no surface exposed it.

  * `repo_website_ingestion` sat in STEP_REGISTRY belonging to no survey type
    and no catalog entry — runnable only from Python.
  * Four analysis kinds had working results readers and no frontend render-mode
    entry, so their cards rendered without a Results button.
  * Three of the seven Survey Definition documents were missing from the batch
    manifest, so a heal would have restored four and silently skipped three.
  * A subscription with no schedule could never fire, and said so only in a
    toast at creation.

None of these is detectable from inside one module. Each is a gap *between* a
registry and the surface meant to expose it, and every one of them was found by
hand, late, after the code had been "done" for a while. This file is that
comparison, made cheap and automatic.

Deliberately structural, not behavioural: it asserts that things are wired
together, never that they work. Behaviour is the job of each capability's own
tests. The bugs above all passed their own tests.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
from resource_explorer.surveyors.repo_survey_definition_adapter import (
    ANALYSIS_KINDS,
    REPO_ANALYSIS_STEP_MAP,
    STEP_REGISTRY,
)

DOCS = Path(__file__).resolve().parents[1] / "docs" / "dr-egeria"
SURVEY_TYPES_CSV = DOCS / "repo_survey_types.csv"
SURVEY_DEFS_DIR = DOCS / "survey-definitions"

# The "*" sentinel means "every step in STEP_REGISTRY" — it is how Full Survey
# (all steps) is generated. Counting it would make every reachability question
# below trivially true, and would have called repo_website_ingestion reachable
# on the day it was reachable from nothing a user could click.
FULL_SURVEY_SENTINEL = "*"

# Steps deliberately absent from every stage-specific survey, with the reason.
# A step landing here is a decision, not a default — which is the point: adding
# one to STEP_REGISTRY without placing it now fails this file rather than
# quietly producing another capability nobody can reach.
STEPS_NOT_IN_A_STAGE_SURVEY = {
    "repo_file_size": (
        "No catalog entry and never independently schedulable — bundled only in "
        "Full Survey by design (docs/Backlog.md, repo-scheduling plan D3)."
    ),
    "repo_arch_detect": (
        "Architecture-recovery prototype (scripts/arch-spike), added 2026-08-20 and "
        "not yet assigned to a stage. Remove this entry when it is placed."
    ),
    "repo_arch_coupling": (
        "Same architecture-recovery prototype as repo_arch_detect."
    ),
}


def _csv_rows() -> list[dict]:
    with SURVEY_TYPES_CSV.open() as fh:
        return list(csv.DictReader(fh))


def _stage_survey_steps() -> set[str]:
    return {r["step_key"] for r in _csv_rows() if r["step_key"] != FULL_SURVEY_SENTINEL}


def _repo_catalog() -> dict[str, dict]:
    return {e["id"]: e for e in get_analyses("repo")}


class TestStepsAreReachable:
    """A step nothing runs is not a feature, however well it works."""

    def test_every_step_belongs_to_a_stage_specific_survey(self):
        orphans = {
            k for k in STEP_REGISTRY
            if k not in _stage_survey_steps() and k not in STEPS_NOT_IN_A_STAGE_SURVEY
        }
        assert not orphans, (
            f"steps in STEP_REGISTRY but in no stage-specific survey type: {sorted(orphans)}. "
            "Add them to docs/dr-egeria/repo_survey_types.csv and regenerate, or record why "
            "not in STEPS_NOT_IN_A_STAGE_SURVEY. Being inside Full Survey does not count — "
            "that bundle is generated from STEP_REGISTRY itself, so it can never be missing "
            "anything and can never reveal this."
        )

    def test_the_exception_list_has_no_stale_entries(self):
        """An entry that is now placed, or now gone, is misinformation."""
        stale = {k for k in STEPS_NOT_IN_A_STAGE_SURVEY if k not in STEP_REGISTRY}
        assert not stale, f"exception listed for steps that no longer exist: {sorted(stale)}"

        placed = {k for k in STEPS_NOT_IN_A_STAGE_SURVEY if k in _stage_survey_steps()}
        assert not placed, (
            f"these are in a stage survey now, so their exception is obsolete: {sorted(placed)}")

    def test_every_survey_type_step_actually_exists(self):
        """The reverse: a CSV step key with no STEP_REGISTRY entry is authored
        into a real Egeria definition that reports "unknown_step" at run time."""
        unknown = _stage_survey_steps() - set(STEP_REGISTRY)
        assert not unknown, (
            f"survey types reference steps that do not exist: {sorted(unknown)}")


class TestAnalysesAreReachable:
    """An analysis is reached from a card, which comes from the catalog."""

    def test_every_analysis_kind_has_a_catalog_entry(self):
        missing = set(ANALYSIS_KINDS) - set(_repo_catalog())
        # sub_resource_survey is reached from the Survey Results dashboard rather
        # than a card of its own — see its AnalysisKind docstring.
        missing -= {"sub_resource_survey"}
        assert not missing, (
            f"analysis kinds with no analysis_catalog.yaml entry: {sorted(missing)}. "
            "Without one there is no card, so the kind can only be run from code.")

    def test_every_catalog_entry_can_be_dispatched(self):
        """A card whose Run does nothing is worse than no card."""
        undispatchable = {
            i for i, e in _repo_catalog().items()
            if not REPO_ANALYSIS_STEP_MAP.get(i)
            and e.get("action") not in ("publish", "ingest", "profile")
        }
        assert not undispatchable, (
            f"catalog entries with no steps and no dispatchable action: {sorted(undispatchable)}")

    def test_every_catalog_intent_is_canonical(self):
        """CLAUDE.md rule 17 — a typo'd intent silently files a card under an
        intent nothing renders."""
        canonical = {"scouting", "discovery", "assessment", "analysis",
                     "enrichment", "understanding", "curate", "automate"}
        bad = {(i, e.get("intent")) for i, e in _repo_catalog().items()
               if e.get("intent") not in canonical}
        assert not bad, f"catalog entries with a non-canonical intent: {sorted(bad)}"


class TestSurveyDefinitionsAreRestorable:
    """The batch manifest is what rebuilds these after a platform reset. A
    document missing from it is invisible until the day it is needed."""

    def test_every_generated_document_is_in_the_batch_manifest(self):
        manifest = json.loads((SURVEY_DEFS_DIR / "_batch.json").read_text())
        on_disk = {p.name for p in SURVEY_DEFS_DIR.glob("*.md")}
        missing = on_disk - set(manifest["files"])
        assert not missing, (
            f"survey definition documents absent from _batch.json: {sorted(missing)}. "
            "A heal would restore the rest and skip these, while the canary reported "
            "the batch healthy.")

    def test_the_manifest_lists_nothing_that_is_gone(self):
        manifest = json.loads((SURVEY_DEFS_DIR / "_batch.json").read_text())
        on_disk = {p.name for p in SURVEY_DEFS_DIR.glob("*.md")}
        assert not set(manifest["files"]) - on_disk

    def test_every_survey_group_generates_a_document(self):
        """A group in the CSV with no generated file never reaches Egeria."""
        by_group = {r["survey_group"]: r["output_filename"] for r in _csv_rows()}
        on_disk = {p.name for p in SURVEY_DEFS_DIR.glob("*.md")}
        missing = {g: f for g, f in by_group.items() if f not in on_disk}
        assert not missing, (
            f"survey groups whose document was never generated: {missing}. "
            "Run scripts/generate_repo_survey_definition.py.")


class TestNothingIsReachableOnlyFromCode:
    """The summarising check, and the one that would have caught
    repo_website_ingestion on the day it was written."""

    def test_every_step_is_reachable_from_a_survey_or_a_card(self):
        stage_steps = _stage_survey_steps()
        card_steps = {s for keys in REPO_ANALYSIS_STEP_MAP.values() for s in keys}
        reachable = stage_steps | card_steps

        unreachable = {
            k for k in STEP_REGISTRY
            if k not in reachable and k not in STEPS_NOT_IN_A_STAGE_SURVEY
        }
        assert not unreachable, (
            f"steps reachable from neither a survey type nor an analysis card: "
            f"{sorted(unreachable)} — runnable only by writing Python.")
