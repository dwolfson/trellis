"""What must never be ingested as a project's documentation.

Measured 2026-08-25: a pilot fed `repo_website_ingestion` three deliberately
bad homepages and it ingested all three. `repo_homepage` falls back to manifest
and README URLs when GitHub declares no homepage, and a README's first link is
very often a badge — so these are not exotic inputs, they are what the corpus
actually contains.
"""
from __future__ import annotations

import pytest

from resource_explorer.ingestion.site_discovery import (
    host_relates_to_project,
    is_code_host,
    is_non_doc_host,
)


class TestHostsThatAreNeverDocumentation:
    @pytest.mark.parametrize("url", [
        "https://static.pepy.tech/badge/docling-mcp/month",   # the live case
        "https://img.shields.io/badge/x-y-blue",
        "https://codecov.io/gh/o/r",
        "https://quay.io/repository/docling-project/docling-serve",  # the live case
        "https://hub.docker.com/r/o/r",
        "https://pypi.org/project/x/",
        "https://huggingface.co/datasets/lmms-lab/DocVQA",   # the live case
    ])
    def test_badges_registries_and_hubs_are_refused(self, url):
        assert is_non_doc_host(url)

    @pytest.mark.parametrize("url", [
        "https://kafka.apache.org/",
        "https://docling-project.github.io/docling",
        "https://sqlglot.com/",
        "https://docs.unitycatalog.com",
    ])
    def test_real_documentation_sites_are_not(self, url):
        assert not is_non_doc_host(url)

    def test_a_project_hosting_docs_on_a_forge_page_is_still_documentation(self):
        """github.io is how a large share of projects publish docs at all — the
        one thing these guards must not exclude."""
        assert not is_non_doc_host("https://docling-project.github.io/docling")
        assert not is_code_host("https://docling-project.github.io/docling")


class TestSomebodyElsesDocumentation:
    """The case no host list catches, and the one that did real damage:
    `docling-nlp`'s homepage resolved to `docs.astral.sh/uv/`, and ingesting it
    pulled 3096 chunks of the uv package manager's documentation into a
    collection attributed to docling. The host is a perfectly good
    documentation site — just not this project's."""

    def test_the_live_case_is_refused(self):
        assert not host_relates_to_project("https://docs.astral.sh/uv/",
                                           "docling-project/docling-nlp")

    @pytest.mark.parametrize("url,repo", [
        ("https://kafka.apache.org/", "apache/kafka"),
        ("https://polaris.apache.org/", "apache/polaris"),
        ("https://www.deepcausality.com", "deepcausality-rs/deep_causality"),
        ("https://docling-project.github.io/docling", "docling-project/docling"),
        ("https://sqlglot.com/", "tobymao/sqlglot"),
        ("https://docs.unitycatalog.com", "unitycatalog/unitycatalog"),
        ("https://egeria-project.org", "odpi/egeria"),
    ])
    def test_a_projects_own_site_relates_however_it_is_spelled(self, url, repo):
        assert host_relates_to_project(url, repo)

    def test_underscores_and_concatenation_still_match(self):
        """`deep_causality` and `deepcausality.com` are the same name with the
        separator dropped, which is the common shape for a project domain."""
        assert host_relates_to_project("https://www.deepcausality.com",
                                       "deepcausality-rs/deep_causality")

    def test_generic_host_parts_cannot_carry_the_match(self):
        """`docs`, `io`, `com`, `github` appear in almost every host. If they
        counted, every site would relate to every project and the guard would
        be inert while looking present — the `_STOPWORDS` failure again."""
        assert not host_relates_to_project("https://docs.example.io/", "acme/widget")

    def test_no_evidence_means_no_refusal(self):
        """Refusing on an empty comparison would turn 'we could not tell' into
        'this is wrong', which is the substitution this codebase keeps
        avoiding elsewhere."""
        assert host_relates_to_project("https://x/", "")


class TestOwnershipEvidenceOutranksTheNameHeuristic:
    """Caught by an existing test, not by design. The relatedness check must run
    AFTER the self-published check: a marker in the repo's own file inventory is
    direct evidence that this project publishes this site, where a shared name
    is only a guess. `odpi/egeria` builds `egeria-project.org`; a project whose
    site is named nothing like its repo would otherwise be refused as somebody
    else's while we hold proof that it is theirs."""

    @staticmethod
    def _guard_order() -> list:
        """Order of the refusal guards as they actually execute.

        Read from the RUN METHOD, not the class: the first draft inspected the
        whole class and matched `self_published` in its docstring, which sits
        above every guard and made the assertion meaningless. A test that reads
        prose and reports on behaviour is worse than no test.
        """
        import inspect
        import re

        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        src = inspect.getsource(w.WebsiteIngestionSurveyor.run)
        return [m.group(1) for m in
                re.finditer(r'"reason": "(\w+)"', src)]

    def test_the_unrelated_check_comes_after_self_published(self):
        order = self._guard_order()
        assert order.index("self_published") < order.index("unrelated_host"), (
            f"a name heuristic must not pre-empt direct evidence of ownership: {order}"
        )

    def test_non_doc_host_comes_before_the_inventory_fetch(self):
        """A badge host is not documentation whoever owns it, so it is cheap and
        unconditional and belongs before self_published, which fetches the file
        inventory."""
        order = self._guard_order()
        assert order.index("non_doc_host") < order.index("self_published"), order

    def test_all_the_refusals_are_present_and_in_order(self):
        """Relative order, not absolute position — `no_homepage` legitimately
        comes first (you cannot check a URL you do not have) and
        `no_collection_type` last, and pinning indices would make this test fail
        on any unrelated insertion."""
        order = self._guard_order()
        expected = ["no_homepage", "code_host", "non_doc_host",
                    "self_published", "unrelated_host"]
        positions = [order.index(name) for name in expected]
        assert positions == sorted(positions), (
            f"refusals out of order: {order}"
        )


class TestNothingStoredIsNotIngested:
    """`milvus`: 400 pages found by sitemap, 400 fetches failed, 685 seconds
    spent, and it recorded `ingested: True`. The StepOutcome beside it had the
    answer right — `unverified`, because `known_positive=bool(fetched)` was
    False — so the codebase held the truth and a redundant boolean contradicted
    it, and downstream code read the boolean."""

    def test_the_ingested_flag_reflects_what_landed(self):
        import inspect

        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        src = inspect.getsource(w.WebsiteIngestionSurveyor.run)
        assert '"ingested": bool(chunks_added)' in src, (
            "a hardcoded True can disagree with the outcome beside it"
        )

    def test_nothing_fetched_has_its_own_cause(self):
        """One `else` covered both 'reached the site, no text' and 'never
        reached the site', even though its own comment distinguished them — so
        milvus reported `no_extractable_text` about text it never had the
        chance to read."""
        import inspect
        import re

        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        causes = set(re.findall(r'cause="(\w+)"',
                                inspect.getsource(w.WebsiteIngestionSurveyor.run)))
        assert "no_pages_fetched" in causes
        assert "pages_unreachable" in causes


class TestIngestionStatusReadsTheAuthoritativeField:
    class _R:
        def __init__(self, metrics):
            self._m = metrics

        def query_metrics(self, slug, kind):
            return self._m

    def test_a_lying_ingested_flag_does_not_produce_ingested(self):
        """The live milvus record. If this reported `ingested`, the repo whose
        lens result would benefit most would never be offered an ingest."""
        from resource_explorer.surveyors.sub_surveyors import arch_lens as AL

        rec = {"chunks": 0.0, "detail": {"ingested": True, "outcome": "unverified",
                                         "outcome_cause": "no_extractable_text"}}
        assert AL.ingestion_status(self._R(rec), "milvus")[0] == AL.ING_ATTEMPTED_EMPTY

    def test_a_real_ingest_still_reads_ingested(self):
        from resource_explorer.surveyors.sub_surveyors import arch_lens as AL

        rec = {"chunks": 97.0, "detail": {"ingested": True, "outcome": "recovered",
                                          "collection": "web_docs_sqlglot_com"}}
        state, detail = AL.ingestion_status(self._R(rec), "sqlglot")
        assert state == AL.ING_INGESTED
        assert detail == "web_docs_sqlglot_com"

    def test_a_partial_ingest_counts_as_ingested(self):
        """Some pages unreachable but chunks stored is a usable collection."""
        from resource_explorer.surveyors.sub_surveyors import arch_lens as AL

        rec = {"chunks": 12.0, "detail": {"outcome": "partial", "collection": "c"}}
        assert AL.ingestion_status(self._R(rec), "x")[0] == AL.ING_INGESTED

    def test_the_new_refusals_count_as_declined(self):
        from resource_explorer.surveyors.sub_surveyors import arch_lens as AL

        for reason in ("self_published", "code_host", "non_doc_host", "unrelated_host"):
            rec = {"chunks": 0.0, "detail": {"ingested": False, "reason": reason}}
            assert AL.ingestion_status(self._R(rec), "x") == (AL.ING_DECLINED, reason)


class TestASiteIsIngestedOnceNotOncePerSiblingRepo:
    """`site_collection_name`'s docstring already said a site should be
    "ingested once and every repo pointing at it" shares the copy. The naming
    did that; nothing enforced it. Measured: `egeria-project.org` fetched and
    embedded three times in one batch — 187 pages and 6018 chunks each, ~175
    seconds — because host-keying dedupes the DESTINATION and not the FETCH."""

    class _P:
        def __init__(self, slug, chunks, collection, when, url="https://x"):
            self.slug, self._c, self._col, self._w = slug, chunks, collection, when

    class _Reg:
        def __init__(self, rows):
            self._rows = rows

        def list_all(self):
            return self._rows

        def query_metrics(self, slug, kind):
            for r in self._rows:
                if r.slug == slug:
                    return {"chunks": r._c, "surveyed_at": r._w,
                            "detail": {"collection": r._col}}
            return {}

    @staticmethod
    def _now(offset_hours=0):
        from datetime import datetime, timedelta
        return (datetime.utcnow() - timedelta(hours=offset_hours)).isoformat()

    def _reg(self, *rows):
        return self._Reg(list(rows))

    def test_a_recent_ingest_by_a_sibling_is_found(self):
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        reg = self._reg(self._P("sibling", 6018.0, "web_docs_x", self._now(1)))
        owner, when = w._already_ingested(reg, "web_docs_x", "me")
        assert owner == "sibling"

    def test_this_repos_own_recent_ingest_also_counts(self):
        """The first version excluded the repo itself, and that was wrong.
        Skipping writes a zero-chunk record over what this repo held, so after
        two siblings skip only the third still carries the evidence — run last,
        it re-ingests. Observed: two skips in under a second, then 103 seconds
        re-fetching a site the repo's own record said was current."""
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        reg = self._reg(self._P("me", 6018.0, "web_docs_x", self._now(1)))
        assert w._already_ingested(reg, "web_docs_x", "me")[0] == "me"

    def test_a_stale_ingest_does_not_count(self):
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        reg = self._reg(self._P("sibling", 6018.0, "web_docs_x",
                                self._now(w.SITE_FRESHNESS_HOURS + 1)))
        assert w._already_ingested(reg, "web_docs_x", "me") == (None, None)

    def test_a_run_that_stored_nothing_does_not_count(self):
        """milvus recorded a completed ingest with zero chunks after 400 failed
        fetches. Treating that as 'already done' would make a bad run
        permanent."""
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        reg = self._reg(self._P("milvus", 0.0, "web_docs_x", self._now(1)))
        assert w._already_ingested(reg, "web_docs_x", "me") == (None, None)

    def test_a_different_collection_does_not_count(self):
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        reg = self._reg(self._P("other", 99.0, "web_docs_somewhere_else", self._now(1)))
        assert w._already_ingested(reg, "web_docs_x", "me") == (None, None)


class TestTheSkipStillWiresTheRepoToTheCollection:
    def test_attribution_survives_the_props_allowlist(self):
        """`_note` filters props through a fixed allowlist, so a key added
        upstream and not added there is dropped SILENTLY — which is what
        happened to `ingested_by`, and to `operationCount` in
        arch_recovery/persist.py the same day."""
        import inspect

        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        # Against the constant, not the method body: the allowlist moved out of
        # `_note` into `_DETAIL_FIELDS`, and a source-substring assertion would
        # have gone green-then-silently-wrong on that refactor rather than
        # failing loudly. The same how-versus-what distinction the presentation
        # session's sentinel guard demonstrated.
        for key in ("ingested_by", "ingested_at"):
            assert key in w._DETAIL_FIELDS, f"{key} would be dropped from the record"

    def test_skipping_the_fetch_must_not_skip_the_registration(self):
        """The query router searches a repo's OWN collection list. Skipping the
        fetch without registering would leave this repo unable to search a site
        it points at — a saving that costs the thing the ingest was for."""
        import inspect

        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        src = inspect.getsource(w.WebsiteIngestionSurveyor.run)
        skip = src[src.index("already_ingested(self.registry"):src.index("no_signal(\"already_ingested\"")]
        assert "update_indexed_at" in skip


class TestProjectFamiliesVouchForAFamilySite:
    """A name comparison knows nothing about project families, so `trellis` was
    refused for declaring `egeria-project.org` — and it IS an Egeria project,
    sitting in the registry's own `egeria` group beside four repos declaring
    that exact homepage. The evidence was already recorded; the function could
    not see it."""

    def test_a_sibling_name_can_carry_the_match(self):
        assert not host_relates_to_project("https://egeria-project.org/", "odpi/trellis")
        assert host_relates_to_project("https://egeria-project.org/", "odpi/trellis",
                                       ["odpi/egeria", "odpi/egeria-docs"])

    def test_a_family_does_not_launder_an_unrelated_host(self):
        """The check that matters. `docling-nlp` and `docling-parse` both point
        at `docs.astral.sh/uv/` and both sit in a 13-repo docling family — if
        family membership were enough to wave anything through, the guard would
        be inert exactly where it did the most good."""
        siblings = [f"docling-project/docling-{n}" for n in
                    ("core", "serve", "eval", "java", "mcp", "sdg")]
        assert not host_relates_to_project("https://docs.astral.sh/uv/",
                                           "docling-project/docling-nlp", siblings)

    @pytest.mark.parametrize("url,repo", [
        ("https://community.intel.com/t5/Blogs/x", "opea-project/Enterprise-RAG"),
        ("https://kubernetes.io/docs/setup/", "opea-project/GenAIInfra"),
    ])
    def test_the_other_live_refusals_survive_family_awareness(self, url, repo):
        siblings = [f"opea-project/{n}" for n in ("GenAIComps", "GenAIExamples", "docs")]
        assert not host_relates_to_project(url, repo, siblings)

    def test_no_siblings_behaves_exactly_as_before(self):
        for extra in ((), None, []):
            assert host_relates_to_project("https://kafka.apache.org/", "apache/kafka", extra)
            assert not host_relates_to_project("https://docs.astral.sh/uv/", "acme/widget", extra)

    def test_sibling_lookup_failure_does_not_stop_an_ingest(self):
        """Best-effort by design: a registry that cannot answer must not block
        the ingest, it must fall back to the name comparison alone."""
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        class _Broken:
            def list_groups(self):
                raise RuntimeError("registry down")

        class _P:
            slug = "x"

        assert w._group_sibling_names(_Broken(), _P()) == []


class TestTheDetailAllowlistCoversEveryCaller:
    """A curated field list discards anything added upstream, without saying so.

    Three instances in one day — `ingested_by` when the dedup skip was written,
    `landing_chars`/`sampled_chars` when profiling was added, and
    `operationCount` in `arch_recovery/persist.py`'s equivalent. Each is
    individually defensible; three is a pattern, and the pattern is that nothing
    tells the list when a call site grows a key.

    This closes it structurally for this module: the list must be a superset of
    what its callers actually pass. Filed as a cross-cutting item in
    `docs/Backlog.md` for the sites this test cannot reach.
    """

    @staticmethod
    def _keys_passed_to_note() -> set:
        """Every literal dict key handed to `_note` in this module."""
        import ast
        import inspect
        import textwrap

        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        tree = ast.parse(textwrap.dedent(inspect.getsource(w)))
        keys = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name != "_note":
                continue
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Dict):
                    keys |= {k.value for k in arg.keys
                             if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        return keys

    @staticmethod
    def _keys_written_as_metrics() -> set:
        """Props that reach the record as METRICS rather than detail.

        The first version of this test asserted every prop must be in
        `_DETAIL_FIELDS`, and it immediately failed on `chunks` and
        `pages_fetched` — which are not dropped at all, they are written as
        metrics because they are numbers. The property that actually matters is
        that a prop reaches SOMEWHERE, so this makes the guard more accurate
        rather than looser.
        """
        import inspect
        import re

        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        src = inspect.getsource(w.WebsiteIngestionSurveyor._note)
        block = src[src.index("upsert_metric"):]
        return set(re.findall(r'props\.get\("(\w+)"', block))

    def test_every_key_a_caller_passes_reaches_the_record(self):
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        passed = self._keys_passed_to_note()
        assert passed, "found no _note call sites — the extractor is broken, not the code"
        reaches = set(w._DETAIL_FIELDS) | self._keys_written_as_metrics()
        dropped = passed - reaches
        assert not dropped, (
            f"these keys are passed to _note and reach neither the detail nor "
            f"the metrics: {sorted(dropped)}. Add them to _DETAIL_FIELDS, write "
            f"them as metrics, or stop passing them."
        )

    def test_the_allowlist_has_no_entries_nobody_passes(self):
        """The other direction is worth knowing but not worth failing on — a
        field kept for a caller that no longer exists is dead weight, not a
        bug. Reported so it can be pruned deliberately."""
        from resource_explorer.surveyors.sub_surveyors import website_ingestion as w

        unused = set(w._DETAIL_FIELDS) - self._keys_passed_to_note()
        # `owner_repo` is passed inside an f-string-built dict in one branch;
        # tolerate a small residue rather than assert emptiness we cannot verify.
        assert len(unused) <= 3, f"allowlist has drifted from its callers: {sorted(unused)}"
