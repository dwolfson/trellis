"""The doc-lens step, and the storage trap that annotating another step's
output walks straight into.

`upsert_finding` appends, but `query_findings` returns only the rows at
`MAX(surveyed_at)` for a (slug, kind, scope). So a step that annotates another
step's findings under the SAME kind makes what it annotates invisible — the
rows survive, the read does not. Measured live: Milvus's candidate count fell
218 -> 203, exactly the 15 scopes labelled, and one scope returned only
`documented_by`.
"""
from __future__ import annotations

import dataclasses

import pytest

from resource_explorer.surveyors.sub_surveyors import arch_lens as AL


@dataclasses.dataclass
class _Proj:
    slug: str = "milvus"
    github_url: str = "https://github.com/milvus-io/milvus"


class _Reg:
    def __init__(self, scopes=None):
        self._scopes = scopes or []
        self.writes = []

    def query_finding_scopes(self, slug, kind):
        return list(self._scopes)

    def query_findings(self, slug, kind, scope=""):
        return []

    def upsert_finding(self, slug, kind, findings, surveyed_at=None, scope_locator=""):
        self.writes.append({"kind": kind, "scope": scope_locator,
                            "checks": [f["check_name"] for f in findings]})


class _Lens:
    # `terms is None` vs `terms == []` are different setups and the fake must
    # keep them apart: `terms or ["proxy"]` turned an explicit empty list back
    # into a populated one, so the doc-site case silently tested the opposite
    # of what it claimed. The same empty-vs-absent confusion the production
    # code is careful about, in four characters of test helper.
    def __init__(self, documented=None, terms=None, outcome="in-repo"):
        self.documented = documented or {}
        self.terms = ["proxy"] if terms is None else list(terms)
        self.undetected, self.notes = [], []
        self.outcome, self.evidence, self.date = outcome, "docs/design-docs", "2026-08-21"

    @property
    def consulted(self):
        return bool(self.terms)


class TestAnnotatingMustNotShadowWhatItAnnotates:
    """The bug this step found. Any future step that labels another step's
    output has the same trap waiting for it."""

    def test_labels_are_written_under_their_own_kind(self, monkeypatch):
        reg = _Reg(scopes=["client/index"])
        monkeypatch.setattr(AL.ad, "apply",
                            lambda *a, **k: _Lens(documented={"index": "index"}))
        AL.ArchLensSurveyor(_Proj(), reg, surveyed_at="2026-08-25T00:00:00").run()
        assert reg.writes, "no label was persisted at all"
        for w in reg.writes:
            assert w["kind"] == AL.LENS_KIND
            assert w["kind"] != AL.SOURCE_KIND, (
                "writing into the annotated kind with a newer surveyed_at hides "
                "that scope's component finding from every reader"
            )

    def test_the_label_keeps_the_components_own_scope(self, monkeypatch):
        """A whole-resource label could not say WHICH component is documented,
        and the point of the lens is per-component.

        monkeypatch, not a bare attribute assignment: the first draft of this
        test patched `AL.ad.apply` directly and leaked into the next test,
        which then saw a consulted document where it expected none. Same
        shared-state shape as the conftest schema collision, one layer up."""
        reg = _Reg(scopes=["client/index"])
        monkeypatch.setattr(AL.ad, "apply",
                            lambda *a, **k: _Lens(documented={"index": "index"}))
        AL.ArchLensSurveyor(_Proj(), reg, surveyed_at="t").run()
        assert reg.writes[0]["scope"] == "client/index"


class TestNoDocumentIsAnAnswer:
    def test_no_components_to_label_is_reported_not_silent(self, monkeypatch):
        (ann,) = AL.ArchLensSurveyor(_Proj(), _Reg(scopes=[])).run()
        assert "the step it annotates has not" in ann.explanation
        assert ann.json_properties["produced_guard"] == AL.GUARD_NO_DOCUMENT

    def test_an_unread_document_is_distinct_from_a_missing_one(self, monkeypatch):
        """`doc-site` is located and unreadable. Reporting it as 'no document'
        would claim the project has none when it has one we cannot open."""
        monkeypatch.setattr(AL.ad, "apply",
                            lambda *a, **k: _Lens(terms=[], outcome="doc-site"))
        (ann,) = AL.ArchLensSurveyor(_Proj(), _Reg(scopes=["a"])).run()
        assert ann.json_properties["doc_outcome"] == "doc-site"
        assert ann.json_properties["produced_guard"] == AL.GUARD_NO_DOCUMENT

    def test_a_repo_with_no_github_url_says_so(self):
        p = _Proj(github_url="")
        (ann,) = AL.ArchLensSurveyor(p, _Reg(scopes=["a"])).run()
        assert "no GitHub URL" in ann.explanation


class TestItStaysALens:
    def test_undetected_is_reported_as_a_count_with_a_caveat_not_a_list(self, monkeypatch):
        """On Milvus this is 506 section headings from 25 design documents.
        Publishing them as findings would dress prose as a detection gap."""
        lens = _Lens(documented={"index": "index"})
        lens.undetected = [f"heading-{i}" for i in range(506)]
        monkeypatch.setattr(AL.ad, "apply", lambda *a, **k: lens)
        (ann,) = AL.ArchLensSurveyor(_Proj(), _Reg(scopes=["client/index"])).run()
        jp = ann.json_properties
        assert jp["undetected_count"] == 506
        assert "undetected" not in jp, "the raw list must not be published"
        assert "overview" in jp["undetected_note"]

    def test_both_guards_are_declared(self):
        """0462 producedGuards — a coordinator needs to know a guard is
        expected before an absent one means anything."""
        assert set(AL.PRODUCED_GUARDS) == {AL.GUARD_CONSULTED, AL.GUARD_NO_DOCUMENT}

    def test_the_step_fetches_no_shared_resource(self):
        """No zipball, no clone — but it is NOT zero-fetch either; it makes its
        own API calls, which is why the registry entry declares fetch_cost=api
        and records that as a third exception to the discovery tier."""
        assert AL.ArchLensSurveyor.requires_resources == {}
