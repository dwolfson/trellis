"""RepoAnalyzer — inspects a repo and proposes which collection types to create."""
from __future__ import annotations

from collections import Counter
from pathlib import PurePath

from github.Repository import Repository

from resource_explorer.configdata.collection_config import COLLECTION_TYPES, CollectionType
from resource_explorer.github.client import GitHubClient


class RepoAnalyzer:
    """
    Given a GitHub repo, analyzes its file tree and proposes which
    CollectionTypes to create. Called during onboarding before any ingestion.

    Returns an IngestionPlan the wizard presents to the user for confirmation.
    """

    DOCS_SITE_MARKERS = ["mkdocs.yml", "docs/conf.py", "_config.yml", "docusaurus.config.js"]
    EXAMPLE_DIRS = ["examples", "samples", "tutorials", "demo", "demos", "cookbook"]
    API_SPEC_NAMES = ["openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"]

    def __init__(self) -> None:
        self._client = GitHubClient()

    def analyze(self, github_url: str, subpath: str | None = None) -> "IngestionPlan":
        repo = self._client.get_repo(github_url)
        files = self._client.list_files(repo, recursive=True)
        if subpath:
            prefix = subpath.strip("/") + "/"
            files = [f for f in files if f.startswith(prefix)]
        return self._build_plan(repo, files)

    def _build_plan(self, repo: Repository, files: list[str]) -> "IngestionPlan":
        ext_counts: Counter[str] = Counter()
        has_docs_site = False
        has_examples = False
        has_api_spec = False
        pdf_count = 0

        for path in files:
            p = PurePath(path)
            ext_counts[p.suffix.lower()] += 1
            if p.name in self.DOCS_SITE_MARKERS:
                has_docs_site = True
            if any(p.parts[0].lower() == d for d in self.EXAMPLE_DIRS if p.parts):
                has_examples = True
            if p.name in self.API_SPEC_NAMES:
                has_api_spec = True
            if p.suffix.lower() == ".pdf":
                pdf_count += 1

        proposed: list[CollectionType] = []
        for ctype in COLLECTION_TYPES.values():
            if ctype.name in ("web_docs", "api_reference", "examples", "pdfs", "release_notes"):
                continue  # handled below
            total = sum(ext_counts.get(ext, 0) for ext in ctype.file_extensions)
            if total >= ctype.min_file_count:
                proposed.append(ctype)

        if has_docs_site:
            proposed.append(COLLECTION_TYPES["web_docs"])
        if has_examples:
            proposed.append(COLLECTION_TYPES["examples"])
        if has_api_spec:
            proposed.append(COLLECTION_TYPES["api_reference"])
        if pdf_count >= 1:
            proposed.append(COLLECTION_TYPES["pdfs"])

        proposed.append(COLLECTION_TYPES["release_notes"])

        return IngestionPlan(
            github_url=repo.clone_url,
            display_name=repo.name,
            description=repo.description or "",
            homepage_url=repo.homepage or "",
            proposed_collections=proposed,
            file_counts={ct.name: sum(ext_counts.get(e, 0) for e in ct.file_extensions)
                         for ct in proposed},
        )


class IngestionPlan:
    def __init__(
        self,
        github_url: str,
        display_name: str,
        description: str,
        homepage_url: str,
        proposed_collections: list[CollectionType],
        file_counts: dict[str, int],
    ) -> None:
        self.github_url = github_url
        self.display_name = display_name
        self.description = description
        self.homepage_url = homepage_url
        self.proposed_collections = proposed_collections
        self.file_counts = file_counts
