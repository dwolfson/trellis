"""Generate RE's database Survey Definition Dr.Egeria docs — cloned from
scripts/generate_repo_survey_definition.py for PostgreSQL databases (Phase 1
slice 12, packages/resource-explorer/docs/design-notes/
COORDINATOR-BRIEF-MULTI-RESOURCE.md, gated on Phase 0 streams 2
question-catalog-multi-type and 4 db-questions-csv, both merged before this
script was written).

Unlike repo, databases have no STEP_REGISTRY-shaped registry of ~20 steps —
resource_explorer/surveyors/database/survey_definition_adapter.py registers
exactly three `re_analysis_step`s today: `postgres_schema_and_stats`,
`postgres_operations`, `sql_analysis`. So this script hardcodes SPECS
directly (three SurveyDefSpec entries below) instead of reading a
repo_survey_types.csv-shaped CSV — there is no database_survey_types.csv,
and building a one-row-per-step CSV machinery for three fixed tiers would be
scaffolding with nothing to scaffold. Regenerate (by editing SPECS below and
re-running) whenever the database adapter's `re_analysis_steps` dict
changes — the `_validate_steps()` guard below fails loudly if a spec names a
step that isn't registered, or warns if a registered step is referenced by
no spec at all, mirroring repo's CSV-loader guards.

Three tiers, not repo's seven, because that is what real database questions
support today (docs/dr-egeria/resource_questions.csv, 31 database-tagged
rows — see DATABASE-SURVEY-DEFINITIONS-IMPLEMENTED.md for the full
breakdown):

- **scouting** — "Database Scouting Scan": `postgres_schema_and_stats`
  alone — the fast schema/row-count/size pass. Answers the Scouting-stage
  database questions this step's data actually backs (schema_inventory,
  row_count_snapshot).
- **analysis** — "Database Analysis Survey": every registered step, chained
  — schema/stats, then operations (privileges, activity, resilience,
  external dependencies), then SQL view analysis. The comprehensive,
  already-tracked-database bundle, matching repo's Analysis Survey being
  "everything Analysis extracts."
- **assessment** — "Database Assessment Survey": `postgres_schema_and_stats`
  then `postgres_operations` — the two evaluative angles real Assessment-
  stage database questions resolve to today (sensitive-data exposure via
  privilege_audit, health via db_activity_signals, resilience via
  db_resilience). `sql_analysis` is omitted: no Assessment-stage database
  question resolves to it, and design §5.7 does not call SQL-view analysis
  an assessment.

No discovery/coarse-profile/full tier: repo's Discovery and Architecture-
Discovery tiers exist because repo already has zero-new-fetch signals
(license classification, maturity, conventions) to reason over data
Scouting collected. No database analysis does that yet — every Discovery-
stage database question in the CSV is still `direct` (registry/human) or
`GAP:` (see the IMPLEMENTED doc). Padding out an empty Discovery tier would
be exactly the invented-tier scaffolding the slice-12 brief says not to
build; scope stays at the three tiers the data supports.

`DATABASE_ANALYSIS_SOURCE_STEPS` below is this script's analogue of repo's
`REPO_ANALYSIS_SOURCE_STEPS` — analysis_catalog.yaml id -> the
`re_analysis_step` key(s) that produce its data — hand-built against the
real, registered steps (there is no database equivalent of repo's
StepInfo/`ANALYSIS_KINDS` dataclass registry to derive it from). A
question's `answering.kind` being `"gap"` in question_catalog.yaml does
**not** exclude it from this join — `_build_step_key_to_questions()` below
mirrors repo's exactly, joining on `analysis_ids` regardless of `kind` (see
docs/dr-egeria/resource_questions_guide.md: "kind still governs
answerability... just do not be surprised to see the id in the generated
YAML"). Several database `GAP:` rows name a *proposed* analysis id (e.g.
`"GAP: db_activity_signals (proposed)"`) that Phase 1 slices 7/8 have since
actually built: `db_activity_signals`, `db_resilience` and
`db_external_dependencies` are real `analysis_catalog.yaml` ids today
(backed by `postgres_operations`), so they appear in the map below despite
the question catalog's `kind: gap` label being stale relative to the
CSV-authoring date. See DATABASE-SURVEY-DEFINITIONS-IMPLEMENTED.md for the
by-name list of `GAP:` ids that are still genuinely unbuilt and which slice
would resolve each.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from resource_explorer.surveyors.dr_egeria_survey_publisher import (
    PublishableStep,
    generate_survey_definition_markdown,
)
from resource_explorer.surveyors.question_catalog_reader import get_questions
from resource_explorer.surveyors.survey_definition_executor import get_adapter

TECHNOLOGY_TYPE = "PostgreSQL Database"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria"
# Generated documents live in the survey-definitions batch folder alongside
# repo's, not at the dr-egeria root — see docs/dr-egeria/_folder_order.json
# and resource_explorer/bootstrap.py. That folder's _batch.json manifest
# gets its own entry added for these three files (see
# DATABASE-SURVEY-DEFINITIONS-IMPLEMENTED.md for why a new manifest, not a
# reused canary).
SURVEY_DEFS_DIR = DOCS_DIR / "survey-definitions"

# get_adapter() imports resource_explorer.surveyors.database.survey_definition_adapter
# as a side effect the first time it's called for "database", which is what
# registers the real _ADAPTER this script reads from — matching repo's
# script importing STEP_REGISTRY directly from repo_survey_definition_adapter.
_ADAPTER = get_adapter("database")
#: step_key -> handler callable. The set of steps that ACTUALLY EXIST and are
#: dispatchable today — the guard this whole script exists to honor (slice 12's
#: instruction: reference real, already-registered re_analysis_step values,
#: not steps future slices 9/10/11 will add).
STEP_REGISTRY: dict = _ADAPTER.re_analysis_steps
#: step_key -> {"description": str, "annotation_types": [...]
STEP_INFO: dict = _ADAPTER.re_analysis_step_info


@dataclass(frozen=True)
class SurveyDefSpec:
    survey_kind: str
    survey_group: str
    survey_display_name: str
    description: str
    step_keys: list[str]  # order matters — this is the chain order
    output_filename: str


SPECS: list[SurveyDefSpec] = [
    SurveyDefSpec(
        survey_kind="scouting",
        survey_group="DatabaseScoutingScan",
        survey_display_name="Database Scouting Scan",
        description=(
            "Fast schema-and-statistics pass — is this database big, alive, "
            "and worth a closer look? Single step (postgres_schema_and_stats): "
            "schema/table/column inventory, row-count and size statistics, "
            "pg_stats column profiling, and index usage. Regenerated by "
            "scripts/generate_database_survey_definition.py."
        ),
        step_keys=["postgres_schema_and_stats"],
        output_filename="database-survey-definition-scouting.md",
    ),
    SurveyDefSpec(
        survey_kind="analysis",
        survey_group="DatabaseAnalysisSurvey",
        survey_display_name="Database Analysis Survey",
        description=(
            "Everything Analysis extracts about a database today: schema/stats "
            "(postgres_schema_and_stats), operations — privileges, activity "
            "signals, resilience, external dependencies (postgres_operations) "
            "— and SQL view dependency/lineage analysis (sql_analysis). "
            "Prefixed by postgres_schema_and_stats because postgres_operations' "
            "activity-signal roll-up and sql_analysis's view analysis both read "
            "the schema_info table it writes. Regenerated by "
            "scripts/generate_database_survey_definition.py."
        ),
        step_keys=["postgres_schema_and_stats", "postgres_operations", "sql_analysis"],
        output_filename="database-survey-definition-analysis.md",
    ),
    SurveyDefSpec(
        survey_kind="assessment",
        survey_group="DatabaseAssessmentSurvey",
        survey_display_name="Database Assessment Survey",
        description=(
            "Everything Assessment evaluates about a database today: "
            "postgres_schema_and_stats as the prerequisite refresh step, then "
            "postgres_operations for the three evaluative angles a real "
            "Assessment-stage question currently resolves to — sensitive-data "
            "exposure (privilege_audit), health (db_activity_signals), and "
            "resilience (db_resilience). sql_analysis is deliberately excluded "
            "— no Assessment-stage database question resolves to it today. "
            "Regenerated by scripts/generate_database_survey_definition.py."
        ),
        step_keys=["postgres_schema_and_stats", "postgres_operations"],
        output_filename="database-survey-definition-assessment.md",
    ),
]


class DatabaseSurveySpecError(ValueError):
    """Raised when SPECS references a step_key not in STEP_REGISTRY —
    deliberately loud (mirrors repo's SurveyTypesCsvError) rather than
    silently generating a Survey Definition that chains a step the executor
    cannot dispatch."""


def _validate_specs() -> None:
    referenced: set[str] = set()
    for spec in SPECS:
        unknown = [k for k in spec.step_keys if k not in STEP_REGISTRY]
        if unknown:
            raise DatabaseSurveySpecError(
                f"{spec.survey_group}: step_key(s) not found in the database "
                f"adapter's STEP_REGISTRY: {unknown} (a typo in SPECS above, or "
                f"the step was removed from survey_definition_adapter.py without "
                f"updating this script)"
            )
        referenced.update(spec.step_keys)

    # Coverage guard, mirrors repo's: a registered step with zero SPECS
    # reference is invisible to every generated Survey Definition, silently.
    # Warn rather than hard-fail — a step legitimately excluded from every
    # tier (rare, but not impossible) shouldn't block generating the rest.
    unreferenced = [k for k in STEP_REGISTRY if k not in referenced]
    if unreferenced:
        print(
            f"WARNING: database re_analysis_step(s) with no SPECS reference "
            f"in {Path(__file__).name}: {unreferenced}"
        )


_validate_specs()


#: analysis_catalog.yaml id -> the re_analysis_step key(s) that PRODUCE its
#: data — see module docstring for why this is hand-built rather than
#: derived, and why entries appear here despite the question catalog's
#: `kind: gap` label on the questions that reference them.
DATABASE_ANALYSIS_SOURCE_STEPS: dict[str, list[str]] = {
    "schema_inventory": ["postgres_schema_and_stats"],
    "row_count_snapshot": ["postgres_schema_and_stats"],
    "privilege_audit": ["postgres_operations"],
    "db_activity_signals": ["postgres_operations"],
    "db_resilience": ["postgres_operations"],
    "db_external_dependencies": ["postgres_operations"],
}


def build_steps(step_keys: list[str]) -> list[PublishableStep]:
    return [
        PublishableStep(
            step_key=key,
            description=STEP_INFO.get(key, {}).get("description", key),
            technology_type=TECHNOLOGY_TYPE,
            executes_at="resource-explorer",
        )
        for key in step_keys
    ]


def _build_step_key_to_questions() -> dict[str, list[str]]:
    """Invert question_catalog.yaml's `answering.analysis_ids` (analysis_catalog
    id, e.g. "privilege_audit") through DATABASE_ANALYSIS_SOURCE_STEPS
    (analysis id -> the re_analysis_step key(s) that produce its data) to get
    step_key -> [question display names]. Identical join to repo's
    scripts/generate_repo_survey_definition.py — see that module's docstring
    for why `kind` (e.g. "gap"/"human") is never consulted here: this join
    answers "running this step, which questions become answerable", and
    kind governs answerability for the Questions tab, not for this join."""
    mapping: dict[str, list[str]] = {}
    for entry in get_questions(resource_type="database"):
        for analysis_id in entry["answering"]["analysis_ids"]:
            for step_key in DATABASE_ANALYSIS_SOURCE_STEPS.get(analysis_id, []):
                mapping.setdefault(step_key, [])
                if entry["question"] not in mapping[step_key]:
                    mapping[step_key].append(entry["question"])
    return mapping


def _answered_questions(step_keys: list[str], step_key_to_questions: dict[str, list[str]]) -> list[str]:
    """Union of questions answered by any step in this Survey Definition,
    order-stable and de-duplicated."""
    seen: list[str] = []
    for key in step_keys:
        for question in step_key_to_questions.get(key, []):
            if question not in seen:
                seen.append(question)
    return seen


#: Records the sha256 of the content this script last wrote for each
#: document — same untouched-vs-hand-authored provenance mechanism as
#: scripts/generate_repo_survey_definition.py (see that module's
#: PROVENANCE_FILE docstring for the full rationale). Deliberately the SAME
#: file as repo's generator writes to: one provenance record per directory,
#: keyed by filename, not one sidecar per document.
PROVENANCE_FILE = SURVEY_DEFS_DIR / ".generated.json"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_provenance() -> dict:
    try:
        return json.loads(PROVENANCE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _write_provenance(record: dict) -> None:
    PROVENANCE_FILE.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def _first_divergent_line(existing: str, generated: str) -> str:
    a, b = existing.splitlines(), generated.splitlines()
    for i in range(max(len(a), len(b))):
        old_line = a[i] if i < len(a) else "(end of file)"
        new_line = b[i] if i < len(b) else "(end of file)"
        if old_line != new_line:
            return f"line {i + 1}:\n      on disk:   {old_line[:100]}\n      generated: {new_line[:100]}"
    return "(no line differs — whitespace only)"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite documents that have been edited since they were "
             "generated. This DISCARDS guards, request parameters and any "
             "other detail SPECS cannot express.",
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
            survey_kind=spec.survey_kind,
            answers_questions=answers_questions,
        )
        output_path = SURVEY_DEFS_DIR / spec.output_filename
        existing = output_path.read_text() if output_path.exists() else None

        if existing is not None and existing != markdown:
            untouched = provenance.get(spec.output_filename) == _digest(existing)
            if not untouched and not args.force:
                skipped.append(spec.output_filename)
                print(
                    f"[{spec.survey_kind}] SKIPPED {output_path.name} — it has been "
                    f"edited since it was generated.\n"
                    f"      This file is the definition; SPECS is only a "
                    f"specification of it, and cannot express guards, request "
                    f"parameters or branching.\n"
                    f"      First difference at {_first_divergent_line(existing, markdown)}\n"
                    f"      Re-run with --force to discard those edits."
                )
                continue

        if existing == markdown:
            provenance[spec.output_filename] = _digest(markdown)
            print(f"[{spec.survey_kind}] unchanged: {output_path.name}")
            continue

        output_path.write_text(markdown)
        provenance[spec.output_filename] = _digest(markdown)
        verb = "wrote" if existing is None else "regenerated"
        print(
            f"[{spec.survey_kind}] {verb} {len(steps)} step(s), "
            f"{len(answers_questions)} question link(s) to {output_path}"
        )

    _write_provenance(provenance)
    if skipped:
        print(
            f"\n{len(skipped)} document(s) left untouched: {', '.join(skipped)}\n"
            "Nothing was lost. Reconcile them by hand, or re-run with --force."
        )


if __name__ == "__main__":
    main()
