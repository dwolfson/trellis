"""Understanding is reachable for any resource type, but every one of
REPO_CHARTS' 8 kinds resolves via `/api/stats/{slug}/charts/{kind}`, which
404s through the repo-only `ProjectRegistry.exists` for a database/
filesystem slug -- every tile rendered a uniform "unavailable" with no way to
tell a permanent non-equivalence from a real wiring gap.

Source-level test (no JS runner in this suite), same technique
test_fact_answer_rendering.py/test_re_api_entity_type_threading.py use.
"""
from __future__ import annotations

from pathlib import Path

UNDERSTANDING = (
    Path(__file__).resolve().parents[1]
    / "resource_explorer" / "web" / "static" / "next" / "stages" / "understanding.js"
)


def _source() -> str:
    return UNDERSTANDING.read_text()


class TestNonRepoChartsAreHandledHonestly:
    def test_a_non_repo_entity_type_short_circuits_before_probing(self):
        src = _source()
        assert "entityType !== 'repo'" in src

    def test_two_distinct_honest_reasons_exist(self):
        src = _source()
        # "does not apply" (permanent) vs "not wired up yet" (a gap) --
        # never the generic "unavailable" a probe failure produces.
        assert "does not apply to this resource type" in src
        assert "not wired up yet" in src

    def test_repo_path_is_unchanged(self):
        """The repo branch must still probe every chart kind exactly as
        before -- this fix must not touch working behaviour for repos."""
        src = _source()
        assert "REPO_CHARTS.map(async ([kind, label])" in src
        assert "await getChart(slug, kind)" in src
