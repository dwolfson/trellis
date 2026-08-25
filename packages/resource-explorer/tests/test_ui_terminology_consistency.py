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

#: Stages whose sub-navigation offers a list of runnable analyses. Scouting and
#: Enrichment are deliberately absent: they run one thing, not a catalog.
_CATALOG_STAGES = ("_discoverySubnavHtml", "_assessmentSubnavHtml", "_analysisSubnavHtml")


def _tabs(fn: str) -> list[tuple[str, str]]:
    s = INDEX.read_text()
    i = s.find(f"function {fn}(")
    assert i >= 0, f"{fn} not found"
    return re.findall(r"tab:\s*'([^']+)',\s*label:\s*'([^']+)'", s[i:i + 2000])


@pytest.mark.parametrize("fn", _CATALOG_STAGES)
def test_the_analyses_tab_is_called_the_same_thing_everywhere(fn):
    labels = [lab for _, lab in _tabs(fn)]
    assert any(lab == "📋 Analyses" for lab in labels), (
        f"{fn} labels its analyses tab {labels!r}. Assessment, Analysis and "
        "Discovery offer the identical concept and must name it identically — a "
        "different word or glyph makes the same thing read as a different thing."
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
