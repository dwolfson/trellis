"""Both kinds of survey card offer the same actions.

Resource Explorer renders surveys through two independent renderers -- local
analysis_catalog entries, and Egeria Survey Definitions -- and Discovery shows
both on one screen. They drifted into disjoint feature sets: Notify on one,
Publish on the other, Results on one, and a perspective filter that narrowed
only half the list while looking like it acted on the panel.

These assert the union, so a feature added to one renderer and not the other
fails here rather than being found by eye.
"""
from __future__ import annotations

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"

#: The renderer function bodies, split out so each assertion names which card
#: kind it is talking about.
def _local_card() -> str:
    html = INDEX.read_text()
    return html.split("const localCardsHtml = analyses.map(a => {")[1].split("\n  });")[0]


def _survey_card() -> str:
    html = INDEX.read_text()
    return html.split("function _renderSurveyDefCandidateCard(")[1].split("\nfunction ")[0]


def test_both_card_kinds_offer_run_schedule_publish_notify():
    local, survey = _local_card(), _survey_card()
    for token, label in (("Run →", "run"), ("⏱", "schedule"),
                         ("☁ Publish", "publish"), ("🔔 Notify me", "notify")):
        assert token in local, f"local analysis card lost its {label} action"
        assert token in survey, f"Egeria survey card lost its {label} action"


def test_both_card_kinds_offer_results():
    local, survey = _local_card(), _survey_card()
    assert "toggleAnalysisResults(" in local
    # A survey runs several analyses, so it opens every one that stores
    # results rather than picking one arbitrarily.
    assert "_toggleSurveyResults(" in survey
    assert "_REPO_RESULTS_RENDER_MODE" in survey


def test_both_card_kinds_say_when_something_is_unpublished():
    """"Never published" and "we did not look" must not both render as nothing.

    The survey card used to emit '' for an unpublished survey while the local
    card beside it said "Not published".
    """
    local, survey = _local_card(), _survey_card()
    assert "☁ Not published" in local
    assert "☁ Not published" in survey


def test_publish_is_scoped_by_step_keys_on_both():
    """_publishScopedSteps takes re_analysis_step KEYS, never an analysis id.

    Passing the id would publish under a name no step answers to. The local
    card could not offer Publish at all until the catalog carried the keys;
    it must use them now rather than the id it has closer to hand.
    """
    local = _local_card()
    assert "a.re_analysis_steps" in local
    assert "_publishScopedSteps(${JSON.stringify(slug)}, ${JSON.stringify(_localStepKeys)}" in local


def test_perspective_filter_applies_to_survey_definitions_too():
    html = INDEX.read_text()
    block = html.split("const validCandidates = candidates")[1].split(";")[0]
    assert "activePerspectives" in block, "perspective filter narrowed only the local cards"
    # An errored candidate has no steps to derive perspectives from, so it must
    # not be filtered away by a test it cannot be judged against.
    assert "!(c.perspectives || []).length" in block


def test_perspective_row_is_shown_on_every_card_rendering_intent():
    html = INDEX.read_text()
    decl = html.split("const _PERSPECTIVE_AWARE_INTENTS = new Set([")[1].split("]")[0]
    for intent in ("assessment", "analysis", "discovery", "enrichment",
                   "understanding", "curate"):
        assert f"'{intent}'" in decl, f"{intent} renders cards but has no perspective row"
    # Scouting is excluded deliberately -- its Questions checklist carries a
    # filter over a DIFFERENT perspective vocabulary, and showing both would
    # stack two rows that disagree on what a perspective is.
    assert "'scouting'" not in decl


# ── the backend halves the cards depend on ──────────────────────────────────

def test_catalog_entries_carry_their_step_keys():
    """Without these the local cards can offer no Publish button at all --
    which is exactly why they had none."""
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    entries = {e["id"]: e for e in get_analyses("repo", include_egeria_live=False)}
    assert entries["repository_health"]["re_analysis_steps"] == ["repo_health"]
    # A multi-step analysis keeps all of them: publishing one third of what an
    # analysis produced, under its name, would be worse than publishing none.
    assert entries["language_file_classification"]["re_analysis_steps"] == [
        "repo_language", "repo_file_classification", "repo_file_structure",
    ]
    assert all("re_analysis_steps" in e for e in entries.values())


def test_survey_perspectives_are_the_union_over_its_steps():
    """A Survey Definition declares no perspectives in Egeria. Deriving them
    from its steps is what lets one filter act on both card kinds; inventing
    them would make the filter agree with nothing."""
    from resource_explorer.web.routes.survey_definitions import _derived_from_steps

    got = _derived_from_steps([
        {"re_analysis_step": "repo_health"},
        {"re_analysis_step": "repo_security"},
    ])
    assert got["analysis_ids"] == ["repository_health", "security_scan"]
    assert "security" in got["perspectives"]

    # A native/prefect-routed survey has no local steps, so it derives nothing
    # -- and must return empty rather than a plausible-looking default, since
    # the UI treats "no perspectives" as "do not filter this card out".
    assert _derived_from_steps([{"re_analysis_step": None}]) == {
        "analysis_ids": [], "perspectives": [],
    }
    assert _derived_from_steps([]) == {"analysis_ids": [], "perspectives": []}


def test_a_survey_reports_every_analysis_its_steps_run():
    """The Results button opens all of them, so a missing id is a silently
    missing results panel."""
    from resource_explorer.web.routes.survey_definitions import _derived_from_steps

    # repo_language belongs to language_file_classification, which owns three
    # step keys -- matching ANY of them must claim the analysis.
    got = _derived_from_steps([{"re_analysis_step": "repo_language"}])
    assert got["analysis_ids"] == ["language_file_classification"]
