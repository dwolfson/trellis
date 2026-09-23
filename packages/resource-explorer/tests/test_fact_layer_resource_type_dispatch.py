"""FactLayer reads a resource type's own maps, not the repository's.

`docs/multi-resource-questions-design.md` §1.1 item 5: `facts.py` imported
`REPO_ANALYSIS_RESULTS_MAP` unconditionally and consulted a
`RESOURCE_STATE_SOURCES` table keyed by repo question text, so the fact layer
answered every question about every resource type out of the repository's
maps. §13 Phase 0 item 3 moves those onto `ResourceTypeAdapter` and dispatches
through it.

The repo case is a refactor and must be indistinguishable from before; the
other cases are the ones that could not previously be expressed at all.
"""
from __future__ import annotations

import pytest

from resource_explorer.facts import FactLayer
from resource_explorer.surveyors.result_status import MEASURED, NOT_ESTABLISHED
from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    _ADAPTERS,
    get_adapter,
)


@pytest.fixture
def registry():
    """A registry stub with the two surfaces FactLayer reaches for. The real
    one needs a database; these tests are about dispatch, not storage."""

    class _Registry:
        def get_analysis_last_run(self, entity_type, slug, limit=500):
            self.last_run_calls.append((entity_type, slug))
            return {}

        def get(self, slug):                      # used by _resource_state_fact
            return object()                       # "a resource exists", nothing more

    reg = _Registry()
    reg.last_run_calls = []
    return reg


class TestTheRepoAdapterDeclaresItsMaps:
    def test_the_four_providers_are_registered(self):
        adapter = get_adapter("repo")
        for name in ("analysis_results_map", "analysis_source_steps",
                     "analysis_kinds", "state_sources"):
            assert callable(getattr(adapter, name)), name

    def test_the_results_map_is_the_repo_one(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_RESULTS_MAP,
        )

        assert get_adapter("repo").analysis_results_map() is REPO_ANALYSIS_RESULTS_MAP

    def test_the_state_sources_are_factss_repo_table(self):
        from resource_explorer.facts import RESOURCE_STATE_SOURCES

        assert get_adapter("repo").state_sources() is RESOURCE_STATE_SOURCES

    def test_the_state_source_keys_really_are_repo_question_text(self):
        """Why this table is per-type rather than shared: its keys are the
        exact repo question strings, so a database would match none of them
        and be told "nothing is recorded for this yet"."""
        keys = get_adapter("repo").state_sources()
        assert "Is this repository actively maintained?" in keys


class TestTheRepoPathIsUnchanged:
    def test_the_default_resource_type_is_repo(self, registry):
        assert FactLayer(registry).resource_type == "repo"

    def test_can_run_still_names_the_source_steps(self, registry):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_SOURCE_STEPS,
        )

        f = FactLayer(registry).fact("no-such-repo", "repository_health")
        assert f.can_run == list(REPO_ANALYSIS_SOURCE_STEPS.get("repository_health", []))
        assert f.can_run  # not vacuously equal to []

    def test_an_action_with_no_results_reader_still_says_so(self, registry):
        f = FactLayer(registry).fact("no-such-repo", "egeria_publish")
        assert f.state == NOT_ESTABLISHED
        assert "action rather than findings" in f.note

    def test_the_last_run_lookup_uses_this_resource_type(self, registry):
        """`get_analysis_last_run` has always taken an entity_type and always
        got the literal "repo". A database asking for its own last run got a
        repository's activity rows, which is to say none."""
        FactLayer(registry, resource_type="database").fact("coco_ods", "schema_inventory")
        FactLayer(registry).fact("some-repo", "repository_health")
        assert ("repo", "some-repo") in registry.last_run_calls
        assert not any(et == "repo" and slug == "coco_ods"
                       for et, slug in registry.last_run_calls)


class TestAResourceTypeThatDeclaresNoMapsAtAll:
    """Filesystem today: an adapter exists, and it declares no fact maps at
    all (database used to be this case too -- see
    TestTheDatabaseAdapterNowDeclaresResults below for why it no longer is).

    The honest answer is "nothing can be read about this resource type here
    yet", not "this analysis has never run" -- the second is a claim about
    the resource, made by a layer that never had anywhere to look.
    """

    def test_fact_reports_undeclared_not_never_run(self, registry):
        f = FactLayer(registry, resource_type="filesystem").fact(
            "some-fs", "filesystem_inventory")
        assert f.state == NOT_ESTABLISHED
        assert "filesystem" in f.note
        assert "never run" not in f.note.lower()

    def test_a_question_is_not_answered_out_of_the_repo_state_table(self, registry):
        """The bug, directly: this repo question text used to be matched for
        any resource type, because the table was imported rather than looked
        up per type."""
        question = {
            "question": "Is this repository actively maintained?",
            "answering": {"kind": "direct", "analysis_ids": []},
        }
        env = FactLayer(registry, resource_type="filesystem").answer("some-fs", question)
        assert not env.answerable
        assert env.blocked_reason

    def test_the_same_question_still_resolves_for_a_repo(self, registry):
        assert "Is this repository actively maintained?" in (
            get_adapter("repo").state_sources()
        )


class TestTheDatabaseAdapterNowDeclaresResults:
    """RULING-DB-QUESTION-CATALOG-CONSISTENCY.md §0: the database adapter
    used to declare no `analysis_results_map` at all, so every database
    question -- whatever the catalog said -- was answered (or, before that,
    misrouted to the repo's own results) out of a layer with nowhere to
    read from. Fixed by declaring `analysis_results_map` on the database
    adapter and passing the caller's resource_type into FactLayer at the
    `/facts/{slug}/answer` route (`web/routes/analyses.py`).

    `analysis_source_steps`/`analysis_kinds`/`state_sources` stay
    undeclared for the database adapter for now -- this only closes the gap
    that made every prior database-catalog fix invisible on screen, not
    every gap in the database fact layer.
    """

    def test_the_results_map_is_the_database_one(self):
        from resource_explorer.surveyors.database.survey_definition_adapter import (
            DATABASE_ANALYSIS_RESULTS_MAP,
        )

        assert get_adapter("database").analysis_results_map() is DATABASE_ANALYSIS_RESULTS_MAP

    def test_a_known_database_analysis_is_no_longer_reported_undeclared(self, registry):
        f = FactLayer(registry, resource_type="database").fact("coco_ods", "schema_inventory")
        # No analysis_kinds map means the live-read path never fires and no
        # run is recorded by this stub registry, so the honest state here is
        # NEVER_RUN -- a claim about the resource this stub's `coco_ods` has
        # never made a survey run for. The point being pinned is what it is
        # NOT: the "no results map declared" note this analysis_id used to
        # get regardless of which database was asked about.
        assert "no analysis results are registered" not in f.note.lower()


class TestAnUnknownResourceType:
    def test_no_adapter_at_all_is_reported_not_crashed(self, registry):
        f = FactLayer(registry, resource_type="model").fact("some-model", "model_card")
        assert f.state == NOT_ESTABLISHED
        assert "model" in f.note


class TestDispatchGoesThroughTheAdapter:
    """A synthetic adapter proves the dispatch is real: if FactLayer still
    read the repo maps directly, these readers would never be called."""

    @pytest.fixture
    def fake_type(self, registry):
        calls: list = []

        def _results_reader(reg, slug):
            calls.append(slug)
            return {"tables": 12}

        adapter = ResourceTypeAdapter(
            entity_type="_fake_for_test",
            technology_type="Fake",
            re_analysis_steps={},
            get_entity=lambda reg, slug: None,
            publish=lambda *a, **k: "",
            analysis_results_map=lambda: {"fake_analysis": (_results_reader, None)},
            analysis_source_steps=lambda: {"fake_analysis": ["fake_step"]},
            analysis_kinds=lambda: {},
            state_sources=lambda: {"What is this?": (lambda reg, e: ({"x": 1}, MEASURED), "desc")},
        )
        _ADAPTERS["_fake_for_test"] = adapter
        try:
            yield adapter, calls
        finally:
            _ADAPTERS.pop("_fake_for_test", None)

    def test_the_adapters_own_reader_is_called(self, registry, fake_type, monkeypatch):
        adapter, calls = fake_type
        layer = FactLayer(registry, resource_type="_fake_for_test")
        monkeypatch.setattr(layer, "_last_run", lambda slug: {
            "fake_analysis": {"last_run_at": "2026-09-20T00:00:00"},
        })
        f = layer.fact("thing", "fake_analysis")
        assert calls == ["thing"]
        assert f.state == MEASURED
        assert f.value == {"tables": 12}
        assert f.can_run == ["fake_step"]

    def test_the_adapters_own_state_source_answers_the_question(self, registry, fake_type):
        layer = FactLayer(registry, resource_type="_fake_for_test")
        env = layer.answer("thing", {
            "question": "What is this?",
            "answering": {"kind": "direct", "analysis_ids": []},
        })
        assert env.answerable

    def test_a_repo_question_does_not_leak_into_the_fake_type(self, registry, fake_type):
        layer = FactLayer(registry, resource_type="_fake_for_test")
        env = layer.answer("thing", {
            "question": "Is this repository actively maintained?",
            "answering": {"kind": "direct", "analysis_ids": []},
        })
        assert not env.answerable
