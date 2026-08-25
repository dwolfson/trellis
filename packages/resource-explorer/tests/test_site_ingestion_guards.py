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
