"""Look at a documentation site before deciding whether and how to ingest it.

Dan, 2026-08-25, after three ingestion defects in a session: *"what are your
assumptions as you make an ingestion? Do we need to do some pre-analysis first,
and perhaps internally stage the content and then profile it before we decide
how to ingest it?"*

The answer was that ingestion **fetched, chunked and embedded in one pass with
no decision point**, so every assumption it made was made implicitly and none was
visible in the result. The cost of that is concrete: `milvus` spent **685 seconds
finding 400 pages by sitemap and failing all 400 fetches**, and nothing could
notice until it was over.

This module is the cheap tier that gates the expensive one — the same shape
architecture recovery already uses, where a fast classification decides whether
the costly step is even the right question (design §5.5b). Two things are checked
here because they are the two that can be answered from **one or two fetches**:

* **Is it reachable by us?** `milvus.io` 302-loops for a non-browser client. One
  request answers it; 400 answered it too, 685 seconds later.
* **Does readable text come out?** A client-rendered page returns HTML with no
  prose in it, which is indistinguishable from a page with nothing to say — and
  embedding a few hundred of them produces a collection full of navigation.

**Deliberately not answered here:** what *kind* of documentation it is (which
should select a chunking profile), how much is boilerplate, and whether it is
versioned or duplicates something already held. Those are real and are in the
Backlog; each needs several pages and a judgement, where these two need one page
and a measurement. Building the cheap half first is the point of a cheap tier.

**A profile that says "do not ingest" is a result, not a failure.** It carries
its reason, and the caller renders it the way a gate's skip is rendered. Three of
the defects that prompted this were the system being right and recording it in a
way that read as being wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Minimum readable characters on the landing page for a site to be worth
#: crawling. A site that renders its content client-side typically yields a
#: shell of nav and script tags — measured on `sqlglot.com`, whose landing page
#: is 138 bytes of meta-refresh and extracts to nothing at all. Low on purpose:
#: this rejects "there is no prose here", not "there is little prose here".
MIN_LANDING_TEXT = 200

#: A landing page can legitimately be a thin index that links to real content, so
#: a low yield is not on its own a refusal — one linked page is sampled before
#: giving up. Two fetches total, against 400.
SAMPLE_PAGES = 1

VERDICT_OK = "ok"
VERDICT_UNREACHABLE = "unreachable"
VERDICT_NO_TEXT = "no_extractable_text"


@dataclass
class SiteProfile:
    """What one or two fetches can establish before committing to a crawl."""
    url: str
    verdict: str = VERDICT_OK
    reachable: bool = False
    landing_chars: int = 0
    sampled_chars: int = 0
    sampled_url: str = ""
    notes: list = field(default_factory=list)

    @property
    def worth_ingesting(self) -> bool:
        return self.verdict == VERDICT_OK

    @property
    def reason(self) -> str:
        """One sentence a person can act on, never a bare verdict."""
        if self.verdict == VERDICT_UNREACHABLE:
            return (f"{self.url} could not be fetched at all — it may require a "
                    f"browser-like client, or be unreachable from here. Crawling it "
                    f"would repeat this failure once per page.")
        if self.verdict == VERDICT_NO_TEXT:
            return (f"{self.url} was reached but yielded no readable text "
                    f"({self.landing_chars} characters on the landing page"
                    + (f", {self.sampled_chars} on {self.sampled_url}" if self.sampled_url else "")
                    + "). It is most likely rendered client-side, so ingesting it "
                      "would embed markup and navigation rather than documentation.")
        return f"{self.url} is reachable and yields readable text."


def _readable_chars(html: str) -> int:
    """Rough count of prose in a page. Deliberately the same shape as the
    ingestion step's own extractor — a profile that measured text differently
    from the thing it gates would be answering a different question."""
    body = re.sub(r"(?s)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", body)
    return len(re.sub(r"\s+", " ", text).strip())


def _first_internal_link(html: str, base_url: str) -> str:
    from urllib.parse import urljoin, urlparse

    host = (urlparse(base_url).hostname or "").lower()
    for m in re.finditer(r'href=["\']([^"\'#?]+)', html):
        target = urljoin(base_url, m.group(1))
        parsed = urlparse(target)
        if (parsed.hostname or "").lower() != host:
            continue
        if target.rstrip("/") == base_url.rstrip("/"):
            continue
        if parsed.path.lower().endswith((".png", ".jpg", ".svg", ".css", ".js", ".ico")):
            continue
        return target
    return ""


def profile_site(url: str, fetch) -> SiteProfile:
    """Fetch one page — two at most — and say whether a crawl is worth starting.

    `fetch(url) -> str | None`, the caller's own fetcher, so the profile is
    measured through the same client that would do the real work. Profiling with
    a more capable fetcher than the crawl uses would be worse than not profiling
    at all: it would clear sites the crawl then fails on.
    """
    profile = SiteProfile(url=url)
    html = fetch(url)
    if not html:
        profile.verdict = VERDICT_UNREACHABLE
        profile.notes.append(f"landing page {url} returned nothing")
        return profile

    profile.reachable = True

    # Follow a meta-refresh stub exactly as `discover_pages` does. Without this
    # the profile refuses sites the crawl handles perfectly well: `sqlglot.com`
    # is a 138-byte stub pointing at ./sqlglot.html, ingests 97 chunks today,
    # and the first version of this module would have blocked it. pdoc generates
    # that shape by default, so it is a family of sites, not one project's quirk.
    #
    # The general rule, and the reason this is not a detail: **a profile must
    # model what the crawl actually does.** Profiling with a more capable
    # fetcher clears sites the crawl then fails on; profiling with a less
    # capable one refuses sites the crawl would have managed. Both are worse
    # than not profiling, because both are confident.
    from resource_explorer.ingestion.site_discovery import follow_meta_refresh

    stub_target = follow_meta_refresh(html, url)
    if stub_target:
        profile.notes.append(f"landing page is a meta-refresh stub -> {stub_target}")
        followed = fetch(stub_target)
        if followed:
            html = followed
            profile.sampled_url = stub_target
            profile.sampled_chars = _readable_chars(followed)
        else:
            profile.verdict = VERDICT_UNREACHABLE
            profile.notes.append(f"meta-refresh target {stub_target} could not be fetched")
            return profile

    profile.landing_chars = _readable_chars(html)
    if profile.landing_chars >= MIN_LANDING_TEXT:
        return profile

    # A thin landing page may be an index. Sample one linked page before
    # refusing — the difference between "this site has no prose" and "this
    # PAGE has no prose", which is exactly the kind of distinction that costs
    # recall when collapsed.
    link = _first_internal_link(html, url)
    if not link:
        profile.verdict = VERDICT_NO_TEXT
        profile.notes.append("landing page is thin and links nowhere internal")
        return profile

    profile.sampled_url = link
    sampled = fetch(link)
    if not sampled:
        profile.verdict = VERDICT_NO_TEXT
        profile.notes.append(f"landing page is thin and the sampled page {link} "
                             f"could not be fetched")
        return profile

    profile.sampled_chars = _readable_chars(sampled)
    if profile.sampled_chars < MIN_LANDING_TEXT:
        profile.verdict = VERDICT_NO_TEXT
        profile.notes.append(f"neither the landing page nor {link} yields readable text")
    return profile
