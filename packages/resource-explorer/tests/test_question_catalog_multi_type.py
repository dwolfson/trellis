"""The question-catalog generator is no longer repo-only.

`docs/multi-resource-questions-design.md` §1.1 named five places RE hardcoded
`repo`; two of them are in `scripts/csv_to_question_catalog_yaml.py`:

  item 1  `_load_known_analysis_ids()` read only `repo_analyses`, so a
          database question naming `schema_inventory` -- a real entry in
          `database_analyses` -- got no `analysis_ids` and `kind: unknown`.
  item 2  `generate()` emitted a literal `{"repo_questions": ...}`.

The guard test (`test_question_catalog_generator_guard.py`) already pins that
the committed YAML is what the committed CSV generates. These tests pin the
behaviour that guard cannot see: what the generator does with a CSV row for a
resource type that has no authored rows in the real CSV yet, since stream 4's
database rows do not exist in this worktree.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "csv_to_question_catalog_yaml.py"
CSV_PATH = ROOT / "docs" / "dr-egeria" / "resource_questions.csv"
YAML_PATH = ROOT / "resource_explorer" / "configdata" / "question_catalog.yaml"


@pytest.fixture(scope="module")
def generator():
    """The real generator module, imported by path the way
    question_catalog_writer.py imports it."""
    spec = importlib.util.spec_from_file_location("csv_to_question_catalog_yaml_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _rows() -> tuple[list[str], list[dict]]:
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _as_csv(fieldnames: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    return buf.getvalue()


class TestTheCsvGainedItsColumn:
    def test_resource_types_is_a_real_column(self):
        fieldnames, _ = _rows()
        assert "Resource Types" in fieldnames

    def test_every_row_declares_its_resource_types(self):
        _, rows = _rows()
        blank = [r["Question"] for r in rows if not (r.get("Resource Types") or "").strip()]
        assert blank == []

    def test_the_existing_rows_are_all_repo_questions(self):
        # Stream 2 backfills; rewording rows to be cross-type (`*`) is the
        # authoring stream's job (design §4), not this one's.
        _, rows = _rows()
        assert {r["Resource Types"] for r in rows} == {"repo"}

    def test_the_column_is_excluded_from_both_generators_perspective_scan(self, generator):
        """The by-elimination trap that produced 17 phantom Perspectives when
        "Catalog History" was added without this step."""
        assert "Resource Types" in generator.NON_PERSPECTIVE_COLUMNS

        spec = importlib.util.spec_from_file_location(
            "csv_to_dr_egeria_questions_test", ROOT / "scripts" / "csv_to_dr_egeria_questions.py",
        )
        dr_egeria = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(spec.name, dr_egeria)
        spec.loader.exec_module(dr_egeria)
        assert "Resource Types" in dr_egeria.OPTIONAL_LEAD_COLUMNS


class TestFunnelStageDroppedAutomate:
    """Decision (project owner, 2026-09-20), design §2.1: automation is a
    property of any survey, not a funnel stage. The one row that used it asks
    whether a re-run is worth paying for, which is a Discovery judgement."""

    def test_no_row_uses_automate_as_a_funnel_stage(self):
        _, rows = _rows()
        stages = {
            part.strip()
            for r in rows
            for part in (r.get("Funnel Stage") or "").split("/")
            if part.strip()
        }
        assert "Automate" not in stages

    def test_the_changed_since_survey_question_is_now_discovery(self):
        from resource_explorer.surveyors import question_catalog_reader as qcr

        qcr.clear_cache()
        entry = next(
            e for e in qcr.get_questions("repo")
            if e["question"].startswith("How much has changed since the last time")
        )
        assert entry["stage"] == "Discovery"


class TestRepoRoundTripsUnchanged:
    def test_the_committed_catalog_still_has_exactly_the_52_repo_questions(self):
        raw = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
        assert list(raw) == ["repo_questions"]
        assert len(raw["repo_questions"]) == 52

    def test_generating_from_the_committed_csv_is_byte_identical(self, tmp_path):
        # The same guard test_question_catalog_generator_guard.py runs; kept
        # here too because this file's other tests mutate row copies, and a
        # reader of this file should see the invariant they are held against.
        out = tmp_path / "question_catalog.yaml"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), str(CSV_PATH), "--output", str(out)],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert out.read_text(encoding="utf-8") == YAML_PATH.read_text(encoding="utf-8")


class TestAHypotheticalDatabaseRow:
    """Stream 4 authors the real database rows; these fixtures stand in for
    them so the plumbing is tested before they land."""

    def _generated(self, generator, extra: dict):
        fieldnames, rows = _rows()
        row = {c: "" for c in fieldnames}
        row.update(extra)
        return yaml.safe_load(generator.generate(rows + [row]))

    def test_a_database_row_gets_its_own_yaml_key(self, generator):
        raw = self._generated(generator, {
            "Question": "Which schemas carry the data?",
            "Funnel Stage": "Scouting",
            "Resource Types": "database",
            "Answering Analysis": "schema_inventory",
            "Data Expert": "X",
        })
        assert "database_questions" in raw
        assert len(raw["repo_questions"]) == 52          # repo is untouched
        entry = raw["database_questions"][0]
        assert entry["question"] == "Which schemas carry the data?"
        assert entry["perspectives"] == ["Data Expert"]

    def test_a_database_analysis_id_is_recognised_not_unknown(self, generator):
        """Design §1.1 item 1, the whole point: `schema_inventory` lives in
        `database_analyses`, and reading only `repo_analyses` made this row
        `kind: unknown` with no analysis_ids."""
        raw = self._generated(generator, {
            "Question": "Which schemas carry the data?",
            "Funnel Stage": "Scouting",
            "Resource Types": "database",
            "Answering Analysis": "schema_inventory",
        })
        answering = raw["database_questions"][0]["answering"]
        assert answering["kind"] == "analysis"
        assert answering["analysis_ids"] == ["schema_inventory"]

    def test_schema_inventory_really_is_a_database_only_analysis(self):
        """Pins the premise of the test above -- if `schema_inventory` were
        also in `repo_analyses`, that test would pass for the wrong reason."""
        cat = yaml.safe_load(
            (ROOT / "resource_explorer" / "configdata" / "analysis_catalog.yaml").read_text()
        )
        repo_ids = {a["id"] for a in cat["repo_analyses"]}
        db_ids = {a["id"] for a in cat["database_analyses"]}
        assert "schema_inventory" in db_ids
        assert "schema_inventory" not in repo_ids

    def test_a_star_row_lands_in_every_resource_type(self, generator):
        from resource_explorer.resource_types import RESOURCE_TYPES

        raw = self._generated(generator, {
            "Question": "Who owns this data?",
            "Funnel Stage": "Scouting",
            "Resource Types": "*",
            "Answering Analysis": "GAP: Egeria Ownership read not built",
        })
        for rt in RESOURCE_TYPES:
            entries = raw[f"{rt}_questions"]
            assert any(e["question"] == "Who owns this data?" for e in entries), rt

    def test_a_multi_type_row_lands_in_exactly_those_types(self, generator):
        raw = self._generated(generator, {
            "Question": "What is the grain of each table?",
            "Funnel Stage": "Discovery",
            "Resource Types": "database;filesystem",
            "Answering Analysis": "GAP: grain_determination not built",
        })
        assert "database_questions" in raw and "filesystem_questions" in raw
        assert "dataset_questions" not in raw
        assert not any(
            e["question"] == "What is the grain of each table?"
            for e in raw["repo_questions"]
        )

    def test_a_cross_type_row_is_not_a_shared_yaml_anchor(self, generator):
        """`yaml.safe_dump` emits `&id001`/`*id001` for a repeated object, and
        two resource types would then share one mutable entry."""
        fieldnames, rows = _rows()
        row = {c: "" for c in fieldnames}
        row.update({
            "Question": "Who owns this data?",
            "Funnel Stage": "Scouting",
            "Resource Types": "database;filesystem",
            "Answering Analysis": "GAP: not built",
        })
        text = generator.generate(rows + [row])
        assert "&id00" not in text and "*id00" not in text

    def test_an_unknown_resource_type_fails_loudly(self, generator):
        fieldnames, rows = _rows()
        row = {c: "" for c in fieldnames}
        row.update({"Question": "Q?", "Funnel Stage": "Scouting", "Resource Types": "databse"})
        with pytest.raises(ValueError, match="databse"):
            generator.generate(rows + [row])

    def test_the_reader_sees_the_generated_database_section(self, generator, tmp_path):
        """End to end: a CSV row through the generator, through the reader,
        and out as an AUTHORED question set rather than a NOT_AUTHORED one."""
        from resource_explorer.surveyors import question_catalog_reader as qcr

        fieldnames, rows = _rows()
        row = {c: "" for c in fieldnames}
        row.update({
            "Question": "Which schemas carry the data?",
            "Funnel Stage": "Scouting",
            "Resource Types": "database",
            "Answering Analysis": "schema_inventory",
        })
        out = tmp_path / "question_catalog.yaml"
        out.write_text(generator.generate(rows + [row]), encoding="utf-8")

        loaded = qcr._load(out)
        assert set(loaded) == {"repo", "database"}
        assert [e.question for e in loaded["database"]] == ["Which schemas carry the data?"]


class TestKnownAnalysisIdsSpanEverySection:
    def test_ids_from_all_three_sections_are_known(self, generator):
        known = set(generator.KNOWN_ANALYSIS_IDS)
        assert "repository_health" in known        # repo_analyses
        assert "schema_inventory" in known         # database_analyses
        assert "filesystem_inventory" in known     # filesystem_analyses

    def test_publish_actions_are_still_excluded(self, generator):
        assert "egeria_publish" not in generator.KNOWN_ANALYSIS_IDS

    def test_ids_are_deduped(self, generator):
        ids = generator.KNOWN_ANALYSIS_IDS
        assert len(ids) == len(set(ids))
