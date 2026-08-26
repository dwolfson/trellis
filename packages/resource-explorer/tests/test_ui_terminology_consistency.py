"""One word per concept, and one glyph per word.

Terminology drifted because each stage's sub-navigation was built separately:
the identical concept — the analyses runnable at this stage — was called
"Analyses" in Assessment, "Catalog" in Analysis, and given a different icon in
Discovery. Nothing was broken; it just made the same thing look like three
things.

Same for the user-visible name of a position in the sequence, which appeared as
"Funnel stage", "phase" and "scouting-tier" on different screens.

These assert the vocabulary rather than the layout, so restyling is free and
renaming is deliberate.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"

#: Every stage whose sub-navigation offers something runnable. All of them,
#: because "Survey" is the generic container: an analysis is a STEP inside a
#: survey, and a survey type may do ingestion instead of or as well as analysis.
#: Naming the tab after one kind of step misdescribes everything else it runs.
_CATALOG_STAGES = ("_scoutingSubnavHtml", "_discoverySubnavHtml", "_assessmentSubnavHtml",
                   "_analysisSubnavHtml", "_enrichmentSubnavHtml")


def _tabs(fn: str) -> list[tuple[str, str]]:
    s = INDEX.read_text()
    i = s.find(f"function {fn}(")
    assert i >= 0, f"{fn} not found"
    return re.findall(r"tab:\s*'([^']+)',\s*label:\s*'([^']+)'", s[i:i + 2000])


@pytest.mark.parametrize("fn", _CATALOG_STAGES)
def test_the_runnable_tab_is_called_survey_everywhere(fn):
    """Survey, not Analyses or Catalog.

    A survey type may run ingestion instead of, or as well as, analysis, and an
    analysis is a step (a microflow) inside a survey that produces annotations.
    An earlier pass unified these on "Analyses", which named the container after
    one kind of thing it contains — narrower than the truth, and wrong for every
    survey that does not analyse.
    """
    labels = [lab for _, lab in _tabs(fn)]
    assert any(lab == "📊 Survey" for lab in labels), (
        f"{fn} labels its runnable tab {labels!r}. Survey is the generic term; "
        "naming it after analysis misdescribes ingestion and anything else a "
        "survey type can run."
    )


def test_the_common_trailing_tabs_are_shared():
    """Results / Questions / Disposition mean the same at every stage that has
    them, so they must be spelled the same. This is what makes the sub-nav
    learnable once rather than per stage."""
    common = ["📈 Results", "❓ Questions", "🧭 Disposition"]
    for fn in ("_scoutingSubnavHtml", "_discoverySubnavHtml", "_assessmentSubnavHtml",
               "_analysisSubnavHtml", "_enrichmentSubnavHtml"):
        labels = [lab for _, lab in _tabs(fn)]
        assert labels[-3:] == common, f"{fn} ends with {labels[-3:]!r}, expected {common!r}"


def test_one_user_visible_word_for_a_position_in_the_sequence():
    """'Funnel stage', 'phase' and 'scouting-tier' all named the same idea on
    different screens. 'Stage' is the one the question data itself uses."""
    visible = re.findall(r">([^<>{}\n]{6,90})<", INDEX.read_text())
    offenders = [
        t.strip() for t in visible
        if re.search(r"\b(funnel|phase|tier)s?\b", t.lower())
    ]
    assert not offenders, (
        f"user-visible text still uses a rejected synonym for 'stage': {offenders[:4]}"
    )


def test_stage_survey_lists_are_scoped_by_both_filters():
    """A stage's Survey tab must list the surveys that BELONG to that stage.

    Two filters exist and each is wrong alone, measured 2026-08-25 against the
    real corpus:

      phase        narrows by which cataloged QUESTIONS a definition is scoped
                   to, so a survey appears under any stage whose questions it
                   can help answer. phase=discovery returned 8 including
                   Assessment Survey and Scouting Survey; phase=assessment
                   returned Full Survey and Repo Discovery Survey and NOT
                   Assessment Survey.
      survey_kind  is the definition's own declared stage — what a reader
                   expects — but filtering by it alone runs the unscoped scan,
                   which misses definitions the question-scoped lookup finds.
                   Repo Architecture Discovery is real, is survey_kind=discovery,
                   and is absent from that scan entirely.

    So the fetch must send both. This asserts the call site still does, because
    dropping either silently restores one of those two failures — neither of
    which errors, and both of which just show a plausible wrong list.
    """
    src = INDEX.read_text()
    assert "const _candParams = { phase: intent, survey_kind: intent };" in src, (
        "the Survey Definition candidates fetch no longer sends both phase and "
        "survey_kind — see this test's docstring for what each one gets wrong alone"
    )
    assert "survey_kind: 'automate_full'" in src, (
        "cross-stage surveys (Full Survey) belong to no single stage and are "
        "fetched separately; without this they vanish from every stage's tab"
    )


def test_folder_selection_uses_the_same_visibility_as_the_rendered_list():
    """A folder checkbox must select exactly the rows the sidebar is showing.

    The bug this guards against is a folder that selects resources the user
    cannot see -- filtered out, or hidden by disposition. Both the renderer and
    the group toggle have to read from one shared definition of "visible", so
    a later change to either filter cannot move them apart.
    """
    html = INDEX.read_text()
    assert "function _visibleProjects()" in html
    # The group toggle derives its members from the shared helper, never by
    # re-filtering _allProjectSummaries itself.
    toggle = html.split("function _toggleGroupSelected(")[1].split("\n}")[0]
    assert "_visibleProjects()" in toggle
    assert "_allProjectSummaries" not in toggle


def test_partly_selected_folder_is_indeterminate_not_unchecked():
    """Showing a partial selection as unchecked would invite a click that
    silently DESELECTS the members already chosen -- the tri-state is what
    makes the control's next click predictable."""
    html = INDEX.read_text()
    assert "box.indeterminate = selectedHere > 0 && selectedHere < memberSlugs.length" in html
    toggle = html.split("function _toggleGroupSelected(")[1].split("\n}")[0]
    # Only a fully-selected folder clears; any gap means "select the rest".
    assert "const allSelected = members.every(" in toggle


def test_scope_filter_is_not_called_working_set():
    """`WorkingSet` is now the Egeria type for ONE disposition's Collection.

    The sidebar filter shows the Folio -- everything in scope, across every
    disposition -- so calling it "Working set" pointed a user-facing label at a
    different thing than the type of the same name.
    """
    html = INDEX.read_text()
    assert ">🎯 In scope<" in html
    assert ">🎯 Working set<" not in html
    # The two other user-visible uses of the phrase named different concepts
    # again (the investigation's scope, and a personal hide toggle).
    for stale in ("Add to the current investigation's working set",
                  "Hide from my working set",
                  "None of those are in the working set"):
        assert stale not in html, f"user-facing label still says: {stale}"


def test_every_disposition_is_offered_not_just_the_populated_ones():
    """The API returns only dispositions that HAVE members ({} when none), so
    deriving the chips from it taught the user nothing until after they had
    already used the feature -- and made "nothing judged yet" render identically
    to "this app has no such thing as disposition"."""
    html = INDEX.read_text()
    assert "const _DISPOSITION_ORDER = [" in html
    for d in ("tracking", "investigating", "recommended", "using", "abandoned", "ignored"):
        assert f"'{d}'" in html.split("const _DISPOSITION_ORDER = [")[1].split("]")[0]
    # Empty lanes render, but cannot be clicked into an unavoidably empty list.
    assert "${count ? `onclick=" in html and "'disabled'" in html
    # Mid-load must not render six zeroes as if measured.
    assert "!_dispositionsLoaded" in html


def test_unjudged_is_computed_not_stored():
    """`undecided` is deliberately NOT a WorkingSet -- a Collection for "nobody
    judged this" would make unjudged and judged-as-undecided indistinguishable.
    So the triage lane must be scope minus every disposition set."""
    html = INDEX.read_text()
    fn = html.split("function _unjudgedKeys()")[1].split("\n}")[0]
    assert "_workingSetKeys" in fn and "_dispositionMembers" in fn
