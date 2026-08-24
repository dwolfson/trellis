"""Tests for site_discovery — deciding which pages of a website to ingest.

The judgement calls here are what make website ingestion useful or harmful, and
all three were found by running against real projects rather than by design:
version collapse (openlineage.io), the self-published skip (egeria-project.org),
and picking between candidate sites (docling).
"""
from __future__ import annotations

import pytest

from resource_explorer.ingestion.site_discovery import (
    collapse_versioned,
    filter_doc_pages,
    is_sitemap_index,
    parse_sitemap,
    pick_richest,
    repo_publishes_site,
    site_collection_name,
)


class TestVersionCollapse:
    def test_keeps_highest_numeric_version(self):
        """openlineage.io publishes ~220 docs pages across ten releases. Ingesting
        all of them embeds ten near-identical copies of every passage, so a query
        matches a dozen versions with no basis for choosing. Measured live:
        2398 docs URLs collapse to 447."""
        out = collapse_versioned([
            "https://x.io/docs/1.44.0/a", "https://x.io/docs/1.50.0/a",
            "https://x.io/docs/1.49.0/a",
        ])
        assert out == ["https://x.io/docs/1.50.0/a"]

    def test_prefers_a_release_over_moving_pointers(self):
        """`next` is a preview of a version nobody is running yet."""
        out = collapse_versioned(["https://x.io/docs/next/a", "https://x.io/docs/1.2.0/a"])
        assert out == ["https://x.io/docs/1.2.0/a"]

    def test_unversioned_pages_are_always_kept(self):
        """A site can mix both — openlineage.io has /docs/1.50.0/... and
        /docs/spec/... — so collapsing must not drop the unversioned half."""
        out = collapse_versioned([
            "https://x.io/docs/1.44.0/a", "https://x.io/docs/1.50.0/a",
            "https://x.io/docs/spec/b",
        ])
        assert set(out) == {"https://x.io/docs/1.50.0/a", "https://x.io/docs/spec/b"}

    def test_distinct_pages_are_not_merged(self):
        out = collapse_versioned(["https://x.io/docs/1.0/a", "https://x.io/docs/1.0/b"])
        assert len(out) == 2

    def test_a_version_like_segment_deeper_in_the_path_still_collapses(self):
        """openlineage has /docs/<ver>/integrations/.../dbt/1.8.0 — the trailing
        1.8.0 is part of the page identity, not the docs version."""
        out = collapse_versioned([
            "https://x.io/docs/1.44.0/i/dbt/1.8.0", "https://x.io/docs/1.50.0/i/dbt/1.8.0",
        ])
        assert out == ["https://x.io/docs/1.50.0/i/dbt/1.8.0"]


class TestSelfPublished:
    @pytest.mark.parametrize("marker", [
        "site/mkdocs.yml",          # egeria-docs — real case, not at repo root
        "docusaurus.config.js",
        "docs/CNAME",
        "_config.yml",
    ])
    def test_detects_a_repo_that_builds_its_own_site(self, marker):
        assert repo_publishes_site(["README.md", marker]) == marker

    def test_plain_repo_is_not_a_site_source(self):
        assert repo_publishes_site(["src/main.py", "README.md", "pyproject.toml"]) == ""

    def test_bare_conf_py_is_not_enough(self):
        """conf.py is a common filename; treating every Python repo as a website
        would skip ingestion for projects that genuinely have a separate site."""
        assert repo_publishes_site(["src/conf.py"]) == ""
        assert repo_publishes_site(["docs/conf.py"]) == "docs/conf.py"


class TestCollectionNaming:
    def test_keyed_on_host_not_repo(self):
        """A website belongs to the project, not one repo. Four registered repos
        here declare egeria-project.org; per-repo keying would embed it four
        times and leave each repo searching only its own copy."""
        for url in ("https://egeria-project.org", "https://egeria-project.org/docs/",
                    "http://www.egeria-project.org/"):
            assert site_collection_name(url) == "web_docs_egeria_project_org"


class TestSitemap:
    def test_parses_locs(self):
        xml = "<urlset><url><loc>https://x.io/a</loc></url><url><loc>https://x.io/b</loc></url></urlset>"
        assert parse_sitemap(xml) == ["https://x.io/a", "https://x.io/b"]

    def test_detects_an_index(self):
        assert is_sitemap_index("<sitemapindex><sitemap><loc>x</loc></sitemap></sitemapindex>")
        assert not is_sitemap_index("<urlset></urlset>")

    def test_blog_and_tag_pages_are_dropped(self):
        out = filter_doc_pages(["https://x.io/docs/a", "https://x.io/blog/b", "https://x.io/tags/c"])
        assert out == ["https://x.io/docs/a"]

    def test_a_site_with_no_docs_prefix_still_returns_pages(self):
        """Returning nothing here would look like a fetch failure rather than a
        filter result — a small project site is still worth ingesting."""
        out = filter_doc_pages(["https://x.io/a", "https://x.io/b"])
        assert len(out) == 2


class TestPickRichest:
    def test_prefers_the_site_with_more_pages(self):
        """docling publishes both docling.ai and docling-project.github.io.
        Measured 2026-08-20: the first had 16 sitemap entries, the second
        returned one byte. Taking whichever a manifest mentioned first would
        pick the dead one about half the time."""
        big = "<urlset>" + "".join(
            f"<url><loc>https://big.io/docs/{i}</loc><lastmod>2026-08-19</lastmod></url>"
            for i in range(10)) + "</urlset>"

        def fetch(url):
            return big if "big.io" in url else ""

        best, info = pick_richest(["https://small.io", "https://big.io"], fetch)
        assert best == "https://big.io"
        assert info["pages"] == 10 and info["newest"] == "2026-08-19"

    def test_a_dead_candidate_does_not_lose_the_live_one(self):
        live = "<urlset><url><loc>https://live.io/docs/a</loc></url></urlset>"

        def fetch(url):
            if "dead.io" in url:
                raise RuntimeError("unreachable")
            return live if "live.io" in url else ""

        best, _ = pick_richest(["https://dead.io", "https://live.io"], fetch)
        assert best == "https://live.io"


class TestIsCodeHost:
    """A homepage pointing back at the forge is not a documentation site.

    Real instance: kedro_plugins declares https://github.com/kedro-org/kedro-plugins
    as its homepage, because HomepageSurveyor falls back to manifest/README URLs
    when GitHub declares no homepage, and those are sometimes the repo's own URL.
    """

    def test_forge_pages_are_not_documentation_sites(self):
        from resource_explorer.ingestion.site_discovery import is_code_host

        assert is_code_host("https://github.com/kedro-org/kedro-plugins")
        assert is_code_host("https://www.gitlab.com/g/p")
        assert is_code_host("https://bitbucket.org/t/r")

    def test_forge_hosted_pages_sites_are_real_documentation(self):
        """The distinction that matters: github.io is how a large share of
        projects publish docs at all, so excluding it would skip exactly the
        sites most worth ingesting."""
        from resource_explorer.ingestion.site_discovery import is_code_host

        assert not is_code_host("https://docling-project.github.io/docling/")
        assert not is_code_host("https://egeria-project.org")
        assert not is_code_host("https://sqlglot.com/")


class TestFollowMetaRefresh:
    """urllib follows HTTP redirects but not <meta http-equiv="refresh">.

    Found live: sqlglot.com is a 138-byte stub pointing at ./sqlglot.html, so
    the ingest fetched a page successfully, extracted nothing, and reported
    "0 chunks from 1 page" — a success-shaped result with no content in it.
    pdoc emits this shape by default, so it is a family of sites.
    """

    STUB = ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0; url=./sqlglot.html"/>'
            '</head></html>')

    def test_resolves_the_target_against_the_landing_page(self):
        from resource_explorer.ingestion.site_discovery import follow_meta_refresh

        assert (follow_meta_refresh(self.STUB, "https://sqlglot.com/")
                == "https://sqlglot.com/sqlglot.html")

    def test_ordinary_page_is_not_a_redirect(self):
        from resource_explorer.ingestion.site_discovery import follow_meta_refresh

        assert follow_meta_refresh("<html><body>Real docs</body></html>",
                                   "https://example.org/") is None

    def test_off_host_target_is_ignored(self):
        """A redirect to another domain is a different project's docs, not a
        deeper page of this one — following it would file someone else's
        content under this project."""
        from resource_explorer.ingestion.site_discovery import follow_meta_refresh

        html = '<meta http-equiv="refresh" content="0; url=https://elsewhere.example/docs">'
        assert follow_meta_refresh(html, "https://sqlglot.com/") is None

    def test_discovery_returns_the_target_when_there_is_no_sitemap(self):
        from resource_explorer.ingestion.site_discovery import discover_pages

        def fetch(url):
            return None if url.endswith("sitemap.xml") else self.STUB

        pages, how = discover_pages("https://sqlglot.com/", fetch)
        assert pages == ["https://sqlglot.com/sqlglot.html"]
        assert "meta-refresh" in how
