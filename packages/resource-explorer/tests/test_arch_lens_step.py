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

    def query_metrics(self, slug, kind):
        return {}

    def upsert_finding(self, slug, kind, findings, surveyed_at=None, scope_locator=""):
        self.writes.append({"kind": kind, "scope": scope_locator,
                            "checks": [f["check_name"] for f in findings]})


class _Lens:
    """Stands in for `DocLens`, and has now lagged it four times.

    Each miss cost a confusing failure somewhere unrelated: `sources` was
    missing when the offer was added, `terms or [...]` turned an explicit empty
    list into a populated one, `undetected_usable` arrived without it, and
    `evidence_kind` was absent while `_persist` reads it inside a try/except —
    so the AttributeError was SWALLOWED and the write simply did not happen,
    which surfaced as a scope assertion failing for no visible reason.

    The general point is worth more than the fixes: **a hand-written fake is a
    duplicate of a shape, and nothing tells it when the original moves.** A
    swallowing caller turns that into a silent no-op rather than an error.
    """
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
        # `sources` is every location found, readable or not — the fake carries
        # it because the production object does, and a fake that lags the real
        # shape fails for a reason that has nothing to do with the behaviour
        # under test.
        self.sources, self.read_sources = [(outcome, self.evidence)], []
        # Kept in step with the real DocLens. A fake that lags the shape it
        # stands for fails for reasons that have nothing to do with the
        # behaviour under test — this is the third time in this file.
        self.undetected_usable, self.undetected_reason = False, "test fake"
        self.evidence_kind = {k: "emphasised" for k in self.documented}

    @property
    def consulted(self):
        return bool(self.terms)


class TestAnnotatingMustNotShadowWhatItAnnotates:
    """The bug this step found. Any future step that labels another step's
    output has the same trap waiting for it."""

    def test_every_run_records_a_marker_even_when_nothing_is_documented(self, monkeypatch):
        """A run that documents nothing wrote nothing at all, so the newest rows
        in the table were whatever the last successful run left — `docling_eval`
        and `docling_java` kept rows through a full refresh that labelled
        neither, and both read as current. The marker is the smallest thing that
        makes staleness detectable."""
        reg = _Reg(scopes=["a"])
        monkeypatch.setattr(AL.ad, "apply", lambda *a, **k: _Lens(documented={}))
        AL.ArchLensSurveyor(_Proj(), reg, surveyed_at="t").run()
        markers = [w for w in reg.writes if "lens_run" in w["checks"]]
        assert len(markers) == 1
        assert markers[0]["scope"] == "", "a run is about the resource, not a component"

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
        # By check_name, not by index: the step also writes a whole-resource
        # `lens_run` marker, and an index-based assertion silently became an
        # assertion about write ORDER the moment that arrived.
        labels = [w for w in reg.writes if "documented_by" in w["checks"]]
        assert [w["scope"] for w in labels] == ["client/index"]


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
        anns = AL.ArchLensSurveyor(_Proj(), _Reg(scopes=["a"])).run()
        ann = anns[0]
        assert ann.json_properties["doc_outcome"] == "doc-site"
        assert ann.json_properties["produced_guard"] == AL.GUARD_NO_DOCUMENT
        # A located-but-unreadable site now also produces the ingest offer, so
        # this branch legitimately returns two annotations: the state, and what
        # can be done about it.
        assert any(getattr(a, "action_requested", "") for a in anns)

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
        assert jp["undetected_usable"] is False
        assert jp["undetected_reason"], (
            "a bare False reads as 'we checked and it was not meaningful'; the "
            "reason is what distinguishes that from 'not computed on this path'"
        )

    def test_both_guards_are_declared(self):
        """0462 producedGuards — a coordinator needs to know a guard is
        expected before an absent one means anything."""
        assert set(AL.PRODUCED_GUARDS) == {AL.GUARD_CONSULTED, AL.GUARD_NO_DOCUMENT}

    def test_the_step_fetches_no_shared_resource(self):
        """No zipball, no clone — but it is NOT zero-fetch either; it makes its
        own API calls, which is why the registry entry declares fetch_cost=api
        and records that as a third exception to the discovery tier."""
        assert AL.ArchLensSurveyor.requires_resources == {}


class TestTheIngestOfferFiresOnlyWhereItIsRealAndUndone:
    """The most actionable negative result in the chain — we know a document
    exists, we know its address, we cannot read it. But an offer to do
    something already done is noise from the one place a reader expects signal,
    so this needs four states, not a boolean."""

    class _MReg(_Reg):
        def __init__(self, metrics, **kw):
            super().__init__(**kw)
            self._metrics = metrics

        def query_metrics(self, slug, kind):
            return self._metrics

    def _run_with(self, monkeypatch, metrics, sites=("https://a", "https://b")):
        lens = _Lens(terms=[], outcome="doc-site")
        lens.sources = [("doc-site", s) for s in sites]
        monkeypatch.setattr(AL.ad, "apply", lambda *a, **k: lens)
        reg = self._MReg(metrics, scopes=["x"])
        return AL.ArchLensSurveyor(_Proj(), reg).run()

    def test_never_attempted_gets_the_offer(self, monkeypatch):
        anns = self._run_with(monkeypatch, {})
        rfa = [a for a in anns if getattr(a, "action_requested", "")]
        assert len(rfa) == 1
        assert "repo_website_ingestion" in rfa[0].action_requested
        assert rfa[0].json_properties["sites"] == ["https://a", "https://b"]

    def test_already_ingested_gets_no_offer(self, monkeypatch):
        """sqlglot's site is 97 chunks in web_docs_sqlglot_com. Offering to
        ingest it again is the failure mode this state exists to prevent."""
        anns = self._run_with(monkeypatch, {"detail": {
            "ingested": True, "collection": "web_docs_sqlglot_com"}})
        assert not [a for a in anns if getattr(a, "action_requested", "")]

    def test_a_deliberate_refusal_gets_no_offer(self, monkeypatch):
        """`self_published` means the repo BUILDS the site, so its source is
        already ingested in a better form — the ingestion step refused on
        purpose and re-offering would override a correct decision."""
        for reason in ("self_published", "code_host"):
            anns = self._run_with(monkeypatch, {"detail": {
                "ingested": False, "reason": reason}})
            assert not [a for a in anns if getattr(a, "action_requested", "")], reason

    def test_attempted_and_empty_is_not_never_attempted(self, monkeypatch):
        """Ran and got nothing is a different problem from never having run,
        and re-offering the same action would not fix it."""
        anns = self._run_with(monkeypatch, {"detail": {"ingested": False, "reason": ""}})
        assert not [a for a in anns if getattr(a, "action_requested", "")]
        assert AL.ingestion_status(self._MReg({"detail": {"ingested": False,
                                                          "reason": ""}}), "x")[0] \
            == AL.ING_ATTEMPTED_EMPTY

    def test_no_doc_site_means_no_offer(self, monkeypatch):
        anns = self._run_with(monkeypatch, {}, sites=())
        assert not [a for a in anns if getattr(a, "action_requested", "")]

    def test_status_is_read_from_metrics_not_findings(self):
        """repo_website_ingestion writes metrics and NO findings. A findings
        query reports nothing for a step that has run six times — finding 105,
        the mistake that produced three wrong published numbers."""
        import inspect
        src = inspect.getsource(AL.ingestion_status)
        assert "query_metrics" in src
        assert "query_findings" not in src

    def test_the_offer_says_nothing_is_wrong_with_the_repo(self, monkeypatch):
        """It is an offer, not a finding. A repo that publishes its docs on a
        website has done nothing wrong, and an RFA that reads as a defect would
        make the funnel's most useful signal feel like criticism."""
        (rfa,) = [a for a in self._run_with(monkeypatch, {})
                  if getattr(a, "action_requested", "")]
        assert "nothing is wrong with" in rfa.explanation


class TestUnknownIsNotNotAttempted:
    """Split at the presentation session's request, and for the better of the
    two reasons available: their renderer coped by matching my DETAIL STRING to
    tell "nobody read the site" from "we could not tell" — their code depending
    on my wording across a module boundary, with nothing to notice a reword.

    They wrote two guards against that and asked for them to be deleted the day
    this split lands. These tests replace them."""

    class _BrokenReg(_Reg):
        def query_metrics(self, slug, kind):
            raise RuntimeError("registry unreachable")

    def test_an_unreadable_record_is_unknown_not_not_attempted(self):
        state, detail = AL.ingestion_status(self._BrokenReg(), "x")
        assert state == AL.ING_UNKNOWN
        assert state != AL.ING_NOT_ATTEMPTED, (
            "'we could not find out' is a fact about the lookup; 'the step has "
            "never run here' is a fact about the repository"
        )
        assert "unreadable" in detail

    def test_an_absent_record_is_still_not_attempted(self):
        assert AL.ingestion_status(_Reg(), "x")[0] == AL.ING_NOT_ATTEMPTED

    def test_no_offer_is_made_when_the_status_is_unknown(self, monkeypatch):
        """The specific failure the split prevents: confidently offering to
        ingest a site whose status merely failed to load."""
        lens = _Lens(terms=[], outcome="doc-site")
        lens.sources = [("doc-site", "https://a")]
        monkeypatch.setattr(AL.ad, "apply", lambda *a, **k: lens)
        anns = AL.ArchLensSurveyor(_Proj(), self._BrokenReg(scopes=["x"])).run()
        assert not [a for a in anns if getattr(a, "action_requested", "")]

    def test_the_state_set_is_declared_so_a_caller_can_switch_on_it(self):
        """A renderer branching on these should be able to enumerate them
        rather than discover a new one at runtime."""
        assert set(AL.ING_STATES) == {
            AL.ING_INGESTED, AL.ING_DECLINED, AL.ING_ATTEMPTED_EMPTY,
            AL.ING_NOT_ATTEMPTED, AL.ING_UNKNOWN}

    def test_every_returned_state_is_in_the_declared_set(self):
        cases = [
            _Reg(),                                                        # absent
            self._BrokenReg(),                                             # unreadable
            TestTheIngestOfferFiresOnlyWhereItIsRealAndUndone._MReg(
                {"chunks": 97.0, "detail": {"outcome": "recovered"}}),      # ingested
            TestTheIngestOfferFiresOnlyWhereItIsRealAndUndone._MReg(
                {"chunks": 0.0, "detail": {"reason": "self_published"}}),   # declined
            TestTheIngestOfferFiresOnlyWhereItIsRealAndUndone._MReg(
                {"chunks": 0.0, "detail": {"outcome": "unverified"}}),      # attempted
        ]
        for reg in cases:
            assert AL.ingestion_status(reg, "x")[0] in AL.ING_STATES
