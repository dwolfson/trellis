"""Slice 17, item 3 (docs/design-notes/COORDINATOR-BRIEF-MULTI-RESOURCE.md,
Phase 1b row 17; docs/multi-resource-questions-design.md §18.3): a checkmark
is withheld when the question is asked below `resource` level (`container`,
`member`, `field` — design §18.3's engine-neutral vocabulary) and every
analysis that answered it only produced a whole-resource rollup.

`QuestionCatalogEntry.levels` (from #290) is the new field this reads —
consumers here, not the CSV/YAML machinery that produces it (already merged
and stable, per this slice's own ground rules).

The signal used is the `target_shape` field every `analysis_catalog.yaml`
entry already carries (`whole_resource_only` vs. `corpus`/
`single_container`) — real data, not a new declaration. Design §18.3 itself
notes the FULL guard (did this run actually PRODUCE per-member rows) needs
slice 20's `scopes` declaration to be checkable; this is the signal already
available, and it catches the exact live case the coordinator brief names:
`subject_signals`/`coverage_signals`/`preliminary_fit` are `container`/
`member`-level questions (per `question_catalog.yaml`) answered by
`target_shape: whole_resource_only` analyses.
"""
from __future__ import annotations

import pytest

from resource_explorer.facts import Envelope, Fact, FactLayer, clear_target_shape_cache
from resource_explorer.surveyors.result_status import MEASURED


@pytest.fixture(autouse=True)
def _clear_shape_cache():
    clear_target_shape_cache()
    yield
    clear_target_shape_cache()


def _fact_layer(monkeypatch, catalog: list[dict]) -> FactLayer:
    monkeypatch.setattr(
        "resource_explorer.surveyors.analysis_catalog_reader.get_analyses",
        lambda resource_type, **kwargs: catalog,
    )
    fl = FactLayer.__new__(FactLayer)  # skip __init__ -- no registry needed here
    fl.resource_type = "database"
    return fl


def _measured_envelope(analysis_ids: list[str]) -> Envelope:
    env = Envelope(subject="coco_ods")
    env.facts = [Fact(analysis_id=aid, state=MEASURED, value={}) for aid in analysis_ids]
    return env


class TestWholeResourceRollupBelowResourceLevel:
    def test_container_level_question_with_only_a_rollup_withholds_the_tick(self, monkeypatch):
        fl = _fact_layer(monkeypatch, [
            {"id": "subject_signals", "target_shape": "whole_resource_only"},
        ])
        env = _measured_envelope(["subject_signals"])
        fl._check_level(env, {"levels": ["container", "member"]})
        assert env.answerable is True  # something real WAS measured
        assert env.level_mismatch is True
        assert "subject_signals" in env.level_note
        assert "rollup" in env.level_note

    def test_member_level_question_with_only_a_rollup_withholds_the_tick(self, monkeypatch):
        # coverage_signals's own real levels (question_catalog.yaml): ["member"].
        fl = _fact_layer(monkeypatch, [
            {"id": "coverage_signals", "target_shape": "whole_resource_only"},
        ])
        env = _measured_envelope(["coverage_signals"])
        fl._check_level(env, {"levels": ["member"]})
        assert env.level_mismatch is True

    def test_the_real_preliminary_fit_row_names_all_four_contributing_ids(self, monkeypatch):
        # preliminary_fit's real question row names four analysis_ids, all
        # target_shape: whole_resource_only in the real catalog.
        fl = _fact_layer(monkeypatch, [
            {"id": "grain_determination", "target_shape": "whole_resource_only"},
            {"id": "subject_signals", "target_shape": "whole_resource_only"},
            {"id": "coverage_signals", "target_shape": "whole_resource_only"},
            {"id": "preliminary_fit", "target_shape": "whole_resource_only"},
        ])
        env = _measured_envelope(
            ["grain_determination", "subject_signals", "coverage_signals", "preliminary_fit"]
        )
        fl._check_level(env, {"levels": ["container"]})
        assert env.level_mismatch is True
        for aid in ("grain_determination", "subject_signals", "coverage_signals", "preliminary_fit"):
            assert aid in env.level_note


class TestNotGatedWhenItShouldNotBe:
    def test_resource_level_question_is_exempt(self, monkeypatch):
        """"resource" is the default level -- a whole-database answer at
        that level genuinely IS the answer, not a rollup standing in for one."""
        fl = _fact_layer(monkeypatch, [
            {"id": "subject_signals", "target_shape": "whole_resource_only"},
        ])
        env = _measured_envelope(["subject_signals"])
        fl._check_level(env, {"levels": ["resource"]})
        assert env.level_mismatch is False
        assert env.level_note == ""

    def test_missing_levels_defaults_to_resource_and_is_exempt(self, monkeypatch):
        """Entries generated before the Level column existed carry no
        `levels` key at all -- must default to `["resource"]`, not gate."""
        fl = _fact_layer(monkeypatch, [
            {"id": "subject_signals", "target_shape": "whole_resource_only"},
        ])
        env = _measured_envelope(["subject_signals"])
        fl._check_level(env, {})
        assert env.level_mismatch is False

    def test_a_per_member_analysis_satisfies_a_sub_resource_level(self, monkeypatch):
        """One analysis with a real per-member breakdown is enough -- the
        question is answered at its own level, even if a rollup-only
        analysis also contributed a fact."""
        fl = _fact_layer(monkeypatch, [
            {"id": "schema_inventory", "target_shape": "corpus"},
            {"id": "subject_signals", "target_shape": "whole_resource_only"},
        ])
        env = _measured_envelope(["schema_inventory", "subject_signals"])
        fl._check_level(env, {"levels": ["member"]})
        assert env.level_mismatch is False

    def test_single_container_shape_also_satisfies_the_level(self, monkeypatch):
        fl = _fact_layer(monkeypatch, [
            {"id": "grant_change", "target_shape": "single_container"},
        ])
        env = _measured_envelope(["grant_change"])
        fl._check_level(env, {"levels": ["container"]})
        assert env.level_mismatch is False

    def test_no_known_facts_does_not_gate(self, monkeypatch):
        """`_check_level` is only reached from `answer()` when `env.answerable`
        is already true, but pinned directly here too: an envelope with
        nothing known must not fabricate a level_mismatch on top of already
        having no answer."""
        fl = _fact_layer(monkeypatch, [
            {"id": "subject_signals", "target_shape": "whole_resource_only"},
        ])
        env = Envelope(subject="coco_ods")
        env.facts = []
        fl._check_level(env, {"levels": ["member"]})
        assert env.level_mismatch is False


class TestEnvelopeSerialization:
    def test_level_mismatch_and_note_are_in_as_dict(self):
        env = Envelope(subject="x", level_mismatch=True, level_note="a note")
        d = env.as_dict()
        assert d["level_mismatch"] is True
        assert d["level_note"] == "a note"

    def test_defaults_are_false_and_empty(self):
        env = Envelope(subject="x")
        d = env.as_dict()
        assert d["level_mismatch"] is False
        assert d["level_note"] == ""


class TestRealCatalogAgreesWithTheLiveBugReport(object):
    """Confirms, against the REAL analysis_catalog.yaml and question_catalog.
    yaml on disk (not a fake catalog), that the exact three ids the review
    named (REVIEW-SURVEY-PANE-285.md's small-findings list: "which schemas
    carry the data... no schema named") are genuinely `target_shape:
    whole_resource_only` while being asked at `container`/`member` level --
    i.e. that this gate has real work to do today, not only in a fixture."""

    def test_subject_signals_is_whole_resource_only_but_asked_below_resource(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        from resource_explorer.surveyors.question_catalog_reader import get_questions

        catalog = {a["id"]: a for a in get_analyses("database", include_egeria_live=False)}
        assert catalog["subject_signals"]["target_shape"] == "whole_resource_only"

        questions = get_questions("database")
        row = next(
            q for q in questions
            if "subject_signals" in (q["answering"].get("analysis_ids") or [])
            and q["answering"]["kind"] == "analysis"
        )
        assert set(row["levels"]) & {"container", "member", "field"}
