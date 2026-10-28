"""The declaration (DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE §1/§2/§4): what it accepts, what it
refuses and in what words, how a step manifest carries it, and that every library step declares one in full."""
import importlib
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from trellis_analytics.declaration import (
    ABSENCE_STATES,
    CONFIDENCE_FORMS,
    FULL_FIELDS,
    RESULT_KINDS,
    Declaration,
    refusal,
)
from trellis_analytics.manifest import StepManifest

STEPS = Path(__file__).resolve().parents[1] / "examples" / "steps"
LIBRARY_STEPS = ("database_staleness", "hub_tables", "change_rates", "statistics_freshness")

ABSENCE = {s: f"{s.replace('_', ' ')}: a sentence" for s in ABSENCE_STATES}
MEASURE = {"name": "s", "unit": "tables", "as_of": "asOf", "value_field": "count"}
EXTENT = {"name": "rows", "fields": ["scope", "count"], "rows": 10, "order": "by count, most first",
          "truncation": "{shown} of {total} tables shown", "token_cost": 200, "citation": "{analysis} · {scope}"}


def minimum(**over):
    return {"result_kind": "measure", "measures": [MEASURE], "absence": ABSENCE, **over}


def full(**over):
    return minimum(**{"extents": [EXTENT], "confidence": {"form": "measured"}, "answers": ["Q-0001"],
                      "scope": "resource", **over})


def refused(body) -> str:
    with pytest.raises(ValidationError) as exc:
        Declaration.model_validate(body)
    return refusal(exc.value)


def test_the_vocabularies_are_the_design_notes():
    assert RESULT_KINDS == ("measure", "series", "distribution", "list", "graph", "finding", "proposal", "table")
    assert ABSENCE_STATES == ("not_measured", "not_permitted", "not_applicable", "measured_nothing")
    assert CONFIDENCE_FORMS == ("measured", "estimated", "inferred", "judged", "generated")


def test_the_minimum_runs_and_says_what_a_full_declaration_still_needs():
    d = Declaration.model_validate(minimum())
    assert d.missing() == list(FULL_FIELDS) and not d.is_complete()
    assert Declaration.model_validate(full()).missing() == []


def test_answers_empty_is_a_declaration_and_absent_is_not():
    """[] says "answers no question, by design"; None says nobody has said yet."""
    assert "answers" not in Declaration.model_validate(full(answers=[])).missing()
    assert "answers" in Declaration.model_validate({k: v for k, v in full().items() if k != "answers"}).missing()


@pytest.mark.parametrize("body, words", [
    (minimum(result_kind="chart"), "result_kind 'chart' is not one of the 8 kinds"),
    (minimum(result_kind="table"), "result_kind 'table' declares no result_kind_note"),
    (minimum(measures=[]), "declares no measures"),
    (minimum(measures=[{**MEASURE, "unit": " "}]), "measure 's' declares no unit"),
    (minimum(measures=[{**MEASURE, "as_of": ""}]), "measure 's' declares no as_of"),
    (minimum(measures=[MEASURE, MEASURE]), "measure s is declared more than once"),
    (minimum(measures=[{**MEASURE, "annotation": {"type": ""}}]), "annotation type is empty"),
    (minimum(absence={**ABSENCE, "not_permitted": ""}), "absence sentence for not_permitted is empty"),
    (minimum(absence={k: v for k, v in ABSENCE.items() if k != "measured_nothing"}),
     "absence.measured_nothing is required"),
    (minimum(absence={**ABSENCE, "never_run": "x"}), "absence.never_run is not a declaration field"),
    (minimum(colour="blue"), "colour is not a declaration field"),
    (minimum(scope="table"), "scope 'table' is not one of the levels"),
    (minimum(extents=[{**EXTENT, "truncation": "some rows shown"}]), "lacks {shown}, {total}"),
    (minimum(extents=[{**EXTENT, "fields": []}]), "extent 'rows' declares no fields"),
    (minimum(extents=[{**EXTENT, "token_cost": 0}]), "extent 'rows' declares token_cost 0"),
    (minimum(confidence={"form": "guessed"}), "confidence form 'guessed' is not one of the five forms"),
    (minimum(confidence={"form": "inferred", "score": "confidence", "calibrated": False}),
     "confidence form 'inferred' declares no basis"),
    (minimum(confidence={"form": "inferred", "basis": "rules", "method": "the rules that matched"}), "does not say whether its score is calibrated"),
    (minimum(confidence={"form": "estimated"}), "confidence form 'estimated' declares no basis and no method"),
    (minimum(confidence={"form": "measured", "score": "confidence"}), "confidence form 'measured' declares a score"),
    (minimum(confidence={"form": "estimated", "method": "a sample", "calibrated": True}),
     "only an inferred score is calibrated or not"),
    (minimum(confidence={"form": "generated", "method": "a model"},
             measures=[{**MEASURE, "annotation": {"type": "ResourceMeasureAnnotation"}}]),
     "a generated answer is not published"),
])
def test_a_refusal_names_the_field_and_what_was_refused(body, words):
    assert words in refused(body)


def test_a_refusal_reads_as_sentences_not_as_pydantic_framing():
    words = refused(minimum(result_kind="chart"))
    assert "validation error" not in words and "Value error" not in words
    assert words.startswith("result_kind ")


def test_a_basis_that_is_a_field_path_must_come_with_words():
    refusal = refused(minimum(confidence={"form": "estimated", "basis": "tables.row_count_is_estimate"}))
    assert "names a result field and no method" in refusal and "tables.row_count_is_estimate" in refusal
    ok = Declaration.model_validate(full(confidence={"form": "estimated", "basis": "tables.row_count_is_estimate",
                                                     "method": "PostgreSQL's row-count estimate"}))
    assert ok.confidence.method


def test_an_estimate_may_declare_its_method_instead_of_a_field():
    d = Declaration.model_validate(full(confidence={"form": "estimated", "method": "n_live_tup, an estimate"}))
    assert d.confidence.basis == "" and d.confidence.method


# ── the declaration on a step manifest ──────────────────────────────────────

BASE = dict(name="s", function="a.b", source="ods", version="1", resource_types=["database"], questions=["Q-0001"])


def test_a_step_declaration_takes_its_answers_from_the_manifests_questions():
    m = StepManifest(**BASE, declaration=minimum())
    assert m.declaration.answers == ["Q-0001"]


def test_a_step_declaration_may_not_name_other_questions():
    with pytest.raises(ValueError, match="one list of questions, not two"):
        StepManifest(**BASE, declaration=minimum(answers=["Q-0002"]))


def test_every_measure_the_step_reports_is_declared_and_no_other():
    with pytest.raises(ValueError, match="declaration gives no unit or as-of for measure o"):
        StepManifest(**BASE, measures=["s", "o"], declaration=minimum())
    with pytest.raises(ValueError, match="declares measure x, which the step does not report"):
        StepManifest(**BASE, declaration=minimum(measures=[MEASURE, {**MEASURE, "name": "x"}]))


def test_a_measure_writes_as_what_the_step_publishes():
    two = [MEASURE, {**MEASURE, "name": "p"}]
    kw = dict(measures=["s", "p"], measure_annotation_types={"p": "ClassificationAnnotation"})
    # left generic while the step publishes a native type: refused, since the publish table would say "generic"
    with pytest.raises(ValueError, match="publishes it as ClassificationAnnotation, so declare that type"):
        StepManifest(**BASE, **kw, declaration=minimum(measures=two))
    with pytest.raises(ValueError, match="writes as DataClassAnnotation; the step publishes it as"):
        StepManifest(**BASE, **kw, declaration=minimum(measures=[
            MEASURE, {**MEASURE, "name": "p", "annotation": {"type": "DataClassAnnotation"}}]))
    StepManifest(**BASE, **kw, declaration=minimum(measures=[
        MEASURE, {**MEASURE, "name": "p", "annotation": {"type": "ClassificationAnnotation"}}]))


def test_a_manifest_without_a_declaration_still_loads():
    assert StepManifest(**BASE).declaration is None


@pytest.mark.parametrize("name", LIBRARY_STEPS)
def test_every_library_step_declares_in_full(monkeypatch, name):
    monkeypatch.syspath_prepend(str(STEPS / name / "src"))
    for mod in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        monkeypatch.delitem(sys.modules, mod)
    m = importlib.import_module(f"{name}.manifest").MANIFEST
    d = m.declaration
    assert d is not None and d.missing() == [], name
    assert [x.name for x in d.measures] == m.measure_names()
    assert d.answers == m.questions


# ── the owner's answers of 2026-10-28: per-measure confidence, not built ────

def test_a_measure_may_carry_its_own_confidence_and_the_headline_is_the_weakest():
    body = minimum(measures=[{**MEASURE, "confidence": {"form": "measured"}},
                             {**MEASURE, "name": "e", "confidence": {"form": "estimated", "method": "a sample"}}])
    d = Declaration.model_validate(body)
    assert d.confidence.form == "estimated"
    assert d.confidence_of(d.measures[0]).form == "measured"


def test_a_measure_without_its_own_confidence_inherits_the_declarations():
    d = Declaration.model_validate(minimum(confidence={"form": "estimated", "method": "a sample"},
                                           measures=[{**MEASURE, "confidence": {"form": "measured"}},
                                                     {**MEASURE, "name": "e"}]))
    assert d.confidence_of(d.measures[1]).form == "estimated"


@pytest.mark.parametrize("body, words", [
    (minimum(confidence={"form": "measured"},
             measures=[{**MEASURE, "confidence": {"form": "estimated", "method": "a sample"}}]),
     "confidence form 'measured' is not the weakest of its measures' ('estimated')"),
    (minimum(measures=[{**MEASURE, "confidence": {"form": "measured"}}, {**MEASURE, "name": "e"}]),
     "the measures without one have no confidence to inherit"),
    (minimum(measures=[{**MEASURE, "confidence": {"form": "generated", "method": "a model"},
                        "annotation": {"type": "ResourceMeasureAnnotation"}}]),
     "a generated answer is not published"),
])
def test_per_measure_confidence_refusals_name_what_was_refused(body, words):
    assert words in refused(body)


def test_built_is_the_default_and_a_planned_analysis_says_so():
    assert Declaration.model_validate(minimum()).built is True
    assert Declaration.model_validate(minimum(built=False)).built is False
