"""The repo-classification card, and the three ways it is easy to get wrong.

Design reference: docs/architecture-recovery-design.md §5.5b. These are checks
on the rendering contract, not on the analysis — they exist because each rule
is violated by reaching for the obvious component, and none of them would fail
a test that only looked at the data.

1. An expected artifact resolves to a LOCATION, not a boolean. Rendered as a
   checkmark column, "does Kubernetes document its architecture?" answers no —
   its in-repo docs/ is a tombstone untouched ~1400 days — when the answer is
   kubernetes/website, updated the same day.
2. No score, grade, percentage or completeness bar. A checklist becomes a score
   and a score punishes deliberate choices: a small stable library documents
   lightly on purpose.
3. A skip is the funnel working — the expensive tier correctly declining to
   run — so it must not render as a failure or a degraded state.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_HTML = pathlib.Path(__file__).parent.parent / "resource_explorer" / "web" / "static" / "index.html"


@pytest.fixture(scope="module")
def renderer() -> str:
    src = _HTML.read_text()
    m = re.search(r"function _renderRepoClassificationResults\(data\) \{.*?\n\}", src, re.S)
    assert m, "the classification renderer is missing"
    return m.group(0)


class TestNoScore:
    """§5.5a(c)/§5.5b — the constraint most likely to be eroded by someone
    'improving' the card, because a completeness bar looks like a favour."""

    @pytest.mark.parametrize("banned", [
        "score", "grade", "rating", "maturity", "percentage",
        "progress", "completeness", "%",
    ])
    def test_the_renderer_contains_no_scoring_vocabulary(self, renderer, banned):
        assert banned not in renderer.lower(), (
            f"the classification card must not introduce '{banned}' — a checklist "
            "becomes a score, and a score punishes deliberate choices"
        )

    def test_it_never_counts_located_against_expected(self, renderer):
        """"3 of 5 artifacts" is a completeness score wearing a sentence."""
        assert not re.search(r"\$\{[^}]*\.length\}[^`]*\bof\b", renderer), \
            "found an N-of-M construction — that is a score in prose form"


class TestLocationNotBoolean:

    def test_all_four_locations_are_rendered(self):
        """not-found is one of four outcomes, not the negative half of a
        boolean — and the other three are all successes in different places."""
        src = _HTML.read_text()
        m = re.search(r"_CLASSIFICATION_LOCATIONS = \[(.*?)\];", src, re.S)
        assert m
        for loc in ("in-repo", "sibling-repo", "doc-site", "not-found"):
            assert loc in m.group(1), f"{loc} is not rendered"

    def test_evidence_and_date_are_shown(self, renderer):
        """A location without the artifact that proved it, and when it was last
        touched, is an assertion rather than a finding — the Kubernetes case
        turns entirely on the date."""
        assert "evidence" in renderer
        assert "date" in renderer

    def test_a_missing_artifact_is_not_styled_as_a_fault(self, renderer):
        """Absence may be a deliberate choice. Amber/red on not-found would
        editorialise it into a deficiency, which is rule 2 by another route."""
        not_found_styling = re.findall(r"not-found'[^\n]*\n?[^\n]*", renderer)
        joined = " ".join(not_found_styling)
        for fault_colour in ("amber", "rose", "red"):
            assert fault_colour not in joined, (
                f"not-found is styled with {fault_colour} — absence is not a fault"
            )


class TestSkipIsNotAFailure:

    def test_a_skip_renders_neutral(self, renderer):
        skip_block = renderer[renderer.index("const skipped"):renderer.index("expected artifacts")] \
            if "expected artifacts" in renderer else renderer[renderer.index("const skipped"):]
        assert "amber" not in skip_block and "rose" not in skip_block, \
            "a gate declining to run is the funnel working, not a degraded result"

    def test_the_gate_reason_is_always_shown(self, renderer):
        """A skip with no reason is indistinguishable from a failure."""
        assert "gate.summary" in renderer
