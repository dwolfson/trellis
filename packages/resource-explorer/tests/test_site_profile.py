"""Look before you crawl.

Ingestion fetched, chunked and embedded in one pass with no decision point, so
`milvus` spent 685 seconds finding 400 pages by sitemap and failing all 400
fetches, and nothing could notice until it was over. The same two fetches now
answer it in under two seconds.
"""
from __future__ import annotations

import pytest

from resource_explorer.ingestion import site_profile as sp

_PROSE = "<html><body><p>" + ("documentation text " * 40) + "</p></body></html>"
_THIN = "<html><body><a href='/guide'>Guide</a></body></html>"
_STUB = '<html><meta http-equiv="refresh" content="0;url=./real.html"></html>'


@pytest.fixture(autouse=True)
def _dns_resolves(monkeypatch):
    """Every test here uses invented hostnames, and `profile_site` now does a
    real DNS lookup before fetching. Without this the whole file short-circuits
    to `host_not_found` and tests about text extraction silently stop testing
    it — the precheck quietly making a unit path depend on the network.

    Tests that are ABOUT resolution override it explicitly.
    """
    monkeypatch.setattr(sp, "host_resolves", lambda url: True)


def _fetcher(pages: dict):
    calls = []

    def fetch(url):
        calls.append(url)
        return pages.get(url)

    fetch.calls = calls
    return fetch


class TestUnreachableIsAnsweredInOneFetch:
    def test_a_site_that_cannot_be_fetched_is_refused(self):
        """`milvus.io` 302-loops for a non-browser client. One request answers
        it; 400 requests answered it too, 685 seconds later."""
        f = _fetcher({})
        p = sp.profile_site("https://milvus.io", f)
        assert p.verdict == sp.VERDICT_UNREACHABLE
        assert not p.worth_ingesting
        assert len(f.calls) == 1, "one fetch is enough to know"

    def test_the_refusal_says_what_a_crawl_would_have_done(self):
        p = sp.profile_site("https://x", _fetcher({}))
        assert "once per page" in p.reason


class TestNoTextIsDistinctFromUnreachable:
    def test_a_reachable_page_with_no_prose_is_refused_differently(self):
        f = _fetcher({"https://x": "<html><body></body></html>"})
        p = sp.profile_site("https://x", f)
        assert p.verdict == sp.VERDICT_NO_TEXT
        assert p.reachable is True, (
            "reached-and-empty and never-reached are different facts; the "
            "outcome vocabulary keys on which"
        )

    def test_a_thin_landing_page_samples_a_linked_page_before_refusing(self):
        """A landing page can legitimately be an index. 'This site has no prose'
        and 'this PAGE has no prose' are different claims."""
        f = _fetcher({"https://x": _THIN, "https://x/guide": _PROSE})
        p = sp.profile_site("https://x", f)
        assert p.worth_ingesting
        assert p.sampled_url == "https://x/guide"

    def test_thin_everywhere_is_refused(self):
        f = _fetcher({"https://x": _THIN, "https://x/guide": "<html></html>"})
        assert sp.profile_site("https://x", f).verdict == sp.VERDICT_NO_TEXT

    def test_a_thin_page_linking_nowhere_internal_is_refused(self):
        f = _fetcher({"https://x": "<html><a href='https://other.example'>o</a></html>"})
        assert sp.profile_site("https://x", f).verdict == sp.VERDICT_NO_TEXT


class TestTheProfileModelsWhatTheCrawlDoes:
    """The rule this module turns on, and it is not a detail. Profiling with a
    MORE capable fetcher clears sites the crawl then fails on; profiling with a
    LESS capable one refuses sites the crawl would have managed. Both are worse
    than not profiling, because both are confident."""

    def test_a_meta_refresh_stub_is_followed_as_discovery_follows_it(self):
        """`sqlglot.com` is a 138-byte stub pointing at ./sqlglot.html and
        ingests 97 chunks today. The first version of this module refused it —
        caught before it shipped, by checking against sites that really
        ingested rather than against invented ones."""
        f = _fetcher({"https://x": _STUB, "https://x/real.html": _PROSE})
        p = sp.profile_site("https://x", f)
        assert p.worth_ingesting
        assert p.sampled_url == "https://x/real.html"

    def test_an_unfetchable_stub_target_is_unreachable_not_textless(self):
        f = _fetcher({"https://x": _STUB})
        p = sp.profile_site("https://x", f)
        assert p.verdict == sp.VERDICT_UNREACHABLE

    def test_it_uses_the_callers_fetcher(self):
        """Passed in rather than constructed, so the profile is measured through
        the same client that would do the real work."""
        import inspect
        assert "fetch" in inspect.signature(sp.profile_site).parameters


class TestARefusalIsAResultNotAFailure:
    def test_every_verdict_carries_a_reason_in_prose(self):
        for pages in ({}, {"https://x": "<html></html>"}):
            p = sp.profile_site("https://x", _fetcher(pages))
            assert len(p.reason) > 40 and p.reason.endswith(".")

    def test_the_good_case_says_so_too(self):
        p = sp.profile_site("https://x", _fetcher({"https://x": _PROSE}))
        assert p.worth_ingesting and "readable text" in p.reason

    def test_two_fetches_at_most(self):
        f = _fetcher({"https://x": _THIN, "https://x/guide": _PROSE})
        sp.profile_site("https://x", f)
        assert len(f.calls) <= 2, "the point of a cheap tier is that it is cheap"


class TestANonExistentDomainIsItsOwnAnswer:
    """`docs.unitycatalog.com` does not resolve, and `unitycatalog_python` still
    carries it as its homepage. "The domain does not exist" and "the site would
    not serve us" ask different things of a reader: the first is stale data
    somebody can fix, the second is out of everyone's reach. A fetcher returning
    None for both cannot tell them apart, and a caller should not have to parse
    an exception string to find out."""

    def test_an_unresolvable_host_is_not_merely_unreachable(self, monkeypatch):
        monkeypatch.setattr(sp, "host_resolves", lambda url: False)
        p = sp.profile_site("https://nope.invalid", _fetcher({}))
        assert p.verdict == sp.VERDICT_HOST_NOT_FOUND
        assert p.verdict != sp.VERDICT_UNREACHABLE

    def test_it_costs_no_fetch_at_all(self, monkeypatch):
        """One DNS lookup, before any HTTP. The cheapest question asked first."""
        monkeypatch.setattr(sp, "host_resolves", lambda url: False)
        f = _fetcher({})
        sp.profile_site("https://nope.invalid", f)
        assert f.calls == []

    def test_the_reason_says_it_is_the_record_that_is_wrong(self):
        """Not the project. A repo whose recorded homepage rotted has done
        nothing wrong, and a message that reads as a defect would be the same
        mistake as rendering a deliberate skip in amber."""
        import types
        p = sp.SiteProfile(url="https://nope.invalid",
                           verdict=sp.VERDICT_HOST_NOT_FOUND)
        assert "worth correcting" in p.reason
        assert "nothing about the project is wrong" in p.reason

    def test_a_resolvable_host_still_gets_fetched(self, monkeypatch):
        monkeypatch.setattr(sp, "host_resolves", lambda url: True)
        f = _fetcher({"https://x": _PROSE})
        assert sp.profile_site("https://x", f).worth_ingesting
        assert f.calls == ["https://x"]
