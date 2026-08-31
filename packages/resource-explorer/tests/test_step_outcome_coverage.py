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


class TestSymbolExtraction:
    """The bug `step_outcome.py`'s own docstring records: a run read source
    files from a `--no-checkout` clone whose root holds only `.git`, scanned an
    empty tree, and reported its zero as though it were a finding.

    The step counted symbols and never counted the FILES it read, so it had no
    way to tell "this code declares no symbols" from "there was no code here".
    """

    def _run(self, monkeypatch, tree_files):
        from resource_explorer.surveyors.sub_surveyors import symbol_extraction as m

        class _Reg:
            def clear_code_symbols(self, *a, **k):
                pass

            def upsert_code_symbols(self, *a, **k):
                pass

            def get_code_relationships(self, slug):
                return []

            def upsert_metric(self, *a, **k):
                pass

        # Honour the extension filter the real `_local_files` applies: the
        # surveyor loops once per language, so a stub that ignores extensions
        # counts every file once per language and the count stops meaning what
        # it means in production. (First version of this test asserted 2 and
        # got 8 — the fake, not the code.)
        def _files(root, exts):
            return iter([(p, c) for p, c in tree_files
                         if any(str(p).endswith(e) for e in exts)])

        class _Extractor:
            def extract(self, *a, **k):
                return []

        import resource_explorer.ingestion.code_symbol_extractor as cse

        # monkeypatch, NOT `m._local_files = ...`. The first version of this
        # file assigned the module attributes directly, so the fakes outlived
        # the test and every later test in the session ran against them —
        # test_symbol_extraction_surveyor.py passed alone and failed in the
        # suite, which is the same "a record that outlived what it described"
        # shape this whole file is about, committed inside the test for it.
        monkeypatch.setattr(m, "_local_files", _files)
        monkeypatch.setattr(cse, "CodeSymbolExtractor", _Extractor)
        return m.SymbolExtractionSurveyor(_Proj(), _Reg(), local_path="/tmp").run()

    def test_an_empty_tree_is_unverified_not_a_repo_with_no_code(self, monkeypatch):
        anns = self._run(monkeypatch, tree_files=[])
        props = _outcome(anns)
        assert props.get("outcome") == UNVERIFIED
        assert props.get("outcome_known_positive") is False

    def test_the_summary_says_the_zero_is_about_the_checkout(self, monkeypatch):
        anns = self._run(monkeypatch, tree_files=[])
        measure = next(a for a in anns if "symbol(s)" in a.summary)
        assert "about the checkout, not the code" in measure.summary
        assert measure.confidence == 0

    def test_files_read_but_no_symbols_is_a_provable_zero(self, monkeypatch):
        anns = self._run(monkeypatch, tree_files=[("a.py", "x = 1"), ("b.py", "y = 2")])
        props = _outcome(anns)
        assert props.get("outcome") == NO_SIGNAL
        assert props.get("outcome_known_positive") is True
        measure = next(a for a in anns if "symbol(s)" in a.summary)
        assert measure.confidence == 100
        assert measure.resource_properties["files_scanned"] == 2


class TestCveScan:
    """cve_scan already distinguished its three cases carefully in prose. What
    none of them did was say so in the shared vocabulary, so the distinction
    stopped at a human reader and never reached the tool-fit query."""

    def _surveyor(self, monkeypatch, deps, osv_error=None, vulns=None):
        from resource_explorer.surveyors.sub_surveyors import cve_scan as m

        class _Reg:
            def query_dependencies(self, slug, **k):
                return list(deps)

            def upsert_finding(self, *a, **k):
                pass

            def upsert_metric(self, *a, **k):
                pass

        s = m.CveScanSurveyor(_Proj(), _Reg())
        # Same reason as above — these leak to every later test otherwise.
        monkeypatch.setattr(m, "query_osv",
                            lambda q, **k: ((vulns or [{} for _ in q]), osv_error))
        monkeypatch.setattr(m, "fetch_severities", lambda ids, **k: {})
        return s.run()

    def test_no_recorded_dependencies_is_unverified(self, monkeypatch):
        # "No dependencies recorded is not no dependencies" — the step's own
        # comment. Now machine-readable.
        anns = self._surveyor(monkeypatch, deps=[])
        assert _outcome(anns).get("outcome") == UNVERIFIED

    def test_a_failed_lookup_is_unverified_not_a_clean_bill(self, monkeypatch):
        anns = self._surveyor(
            monkeypatch, deps=[{"dep_name": "requests", "dep_version": "2.0.0", "ecosystem": "pypi"}],
            osv_error="connection refused")
        props = _outcome(anns)
        assert props.get("outcome") == UNVERIFIED
        assert "lookup failed" in props.get("outcome_cause", "")

    def test_a_real_scan_with_no_advisories_is_a_provable_zero(self, monkeypatch):
        anns = self._surveyor(
            monkeypatch, deps=[{"dep_name": "requests", "dep_version": "2.0.0", "ecosystem": "pypi"}])
        props = _outcome(anns)
        if props:
            assert props["outcome"] in (NO_SIGNAL, UNVERIFIED)
            if props["outcome"] == NO_SIGNAL:
                assert props["outcome_known_positive"] is True
