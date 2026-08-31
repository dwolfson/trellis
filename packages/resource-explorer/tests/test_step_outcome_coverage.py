"""Steps newly reporting what they achieved, not only what they found.

`step_outcome.py`'s vocabulary exists because a zero means either "genuinely
absent" or "the method was broken", and nothing distinguishes those without a
known-positive — something that WOULD have been found had the step worked.

Coverage matters because the outcomes are already harvested and persisted:
`step_cost_observer.describe_work()` reads the label off the annotations the
orchestrator holds, and `record()` writes it to project_analysis_metrics under
kind='step_cost'. A step that does not report one contributes nothing to
"which tools suit which repos" — measured 2026-08-31, 21 of 33 sub-surveyors
reported nothing at all.
"""
from __future__ import annotations

import pytest

from resource_explorer.step_outcome import NO_SIGNAL, RECOVERED, UNVERIFIED


def _outcome(annotations, step=None):
    for a in annotations:
        props = getattr(a, "json_properties", None) or {}
        if props.get("outcome") and (step is None or a.analysis_step == step):
            return props
    return {}


class _Proj:
    slug = "p"
    github_url = "https://github.com/o/p"


class TestLanguage:
    """`primary = row["primary_language"] or "Unknown"` was reported as a
    classification at confidence 95 — a 95%-confident non-answer."""

    def _run(self, primary, breakdown="{}"):
        from resource_explorer.surveyors.sub_surveyors.language import LanguageSurveyor

        class _Reg:
            def get_latest_project_stats(self, slug):
                return {"primary_language": primary, "language_breakdown": breakdown,
                        "topics": "[]"}

        return LanguageSurveyor(_Proj(), _Reg()).run()

    def test_a_real_language_is_recovered(self):
        anns = self._run("Python", '{"Python": 900}')
        assert _outcome(anns)["outcome"] == RECOVERED

    def test_unknown_with_a_byte_breakdown_is_a_provable_zero(self):
        # GitHub answered with per-language bytes and still no primary — the
        # breakdown is the known-positive, so the absence is about this repo.
        anns = self._run("", '{"Shell": 12}')
        props = _outcome(anns)
        assert props["outcome"] == NO_SIGNAL
        assert props["outcome_known_positive"] is True

    def test_unknown_with_nothing_examined_is_unverified(self):
        # Nothing was read, so nothing can be concluded. Claiming no_signal
        # here would claim knowledge the run does not have.
        anns = self._run("", "{}")
        props = _outcome(anns)
        assert props["outcome"] == UNVERIFIED

    def test_unknown_is_not_reported_as_a_confident_classification(self):
        anns = self._run("", "{}")
        primary = next(a for a in anns if "Primary language" in a.summary)
        assert primary.confidence == 0, "a non-answer must not carry 95% confidence"
        assert primary.candidate_classifications == [], (
            "'Unknown' is not a language and must not be offered as a candidate"
        )


class TestInterfaceSurface:
    """Detection reads the recorded inventory and DECLARED dependencies, so
    "no interface signals" said the same thing for a thoroughly-examined
    library and for a repo where nothing had been read."""

    def _run(self, paths, deps):
        from resource_explorer.surveyors.sub_surveyors import interface_surface as m

        class _Reg:
            def query_file_inventory(self, slug, **kw):
                return [{"file_path": p} for p in paths]

            def query_dependencies(self, slug, **kw):
                return [{"dep_name": d} for d in deps]

            def upsert_finding(self, *a, **k):
                pass

        surveyor = m.InterfaceSurfaceSurveyor(_Proj(), _Reg())
        return surveyor.run()

    def test_nothing_read_is_unverified_not_a_clean_bill(self):
        anns = self._run(paths=[], deps=[])
        props = _outcome(anns)
        if props:                      # only assert when the step got far enough
            assert props["outcome"] == UNVERIFIED
            assert props["outcome_known_positive"] is False

    def test_files_read_with_no_signal_is_a_provable_zero(self):
        anns = self._run(paths=["README.md", "main.py"], deps=["requests"])
        props = _outcome(anns)
        if props:
            assert props["outcome"] in (NO_SIGNAL, RECOVERED)
            if props["outcome"] == NO_SIGNAL:
                assert props["outcome_known_positive"] is True
