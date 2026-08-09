"""Catalog-only registration for repos discovered via GitHubClient.search_repos().

Deliberately NOT OnboardingWizard (cli/wizard.py) — that always triggers a full
IngestionPipeline run (pgvector embedding, can take minutes per repo) with no
way to opt out. Bulk-importing a whole GitHub org needs a lighter path: get
each repo into the registry (survey/curate-ready immediately), skip RAG
ingestion, and let it be ingested later (per-repo, via the existing
add/refresh flows) if and when someone actually wants code search on it.

_run_import_batch() mirrors scheduler.py's _run_due()/_scheduler_loop() shape —
the only existing precedent in this codebase for work that runs independently
of the HTTP request that kicked it off. Each repo is isolated in its own
try/except so one bad repo can't take down the rest of the batch, matching
the same isolation _run_due() already gives each due schedule.
"""
from __future__ import annotations

import logging
import re

from resource_explorer.activity_logger import log_scout
from resource_explorer.registry import Project, ProjectRegistry

log = logging.getLogger(__name__)


def _url_to_slug(url: str) -> str:
    """Same derivation as cli/wizard.py's OnboardingWizard._url_to_slug —
    repo name (last URL path segment), not owner/repo. Kept in sync
    deliberately: both are the "no explicit slug_override" case of
    registering a repo, and must land on the same slug for the same repo
    however it was registered."""
    url = url.rstrip("/")
    slug = url.split("/")[-1]
    return re.sub(r"[^a-z0-9_]", "_", slug.lower())


def _slugify_source_label(label: str) -> str:
    """A source_label can be a plain org name (already slug-shaped) or a
    free-text search description ("search: language:python stars:>=500") —
    sanitize either into something safe to use as an activity-log
    entity_slug ("Discover repos to scout" plan, D7)."""
    return re.sub(r"[^a-z0-9_]+", "_", label.lower()).strip("_")[:80] or "import_batch"


class OrgImporterError(RuntimeError):
    """Raised for import-setup errors (e.g. re-registering an existing repo)."""


class OrgImporter:
    """Registers a single discovered repo into the catalog, no ingestion."""

    def __init__(self, registry: ProjectRegistry | None = None) -> None:
        self.registry = registry or ProjectRegistry()

    def import_repo(
        self,
        github_url: str,
        display_name: str,
        description: str = "",
        group_slug: str = "",
    ) -> Project:
        slug = _url_to_slug(github_url)
        if self.registry.get_by_github_url(github_url) or self.registry.exists(slug):
            raise OrgImporterError(f"'{github_url}' is already registered.")

        project = Project(
            slug=slug,
            display_name=display_name,
            github_url=github_url,
            description=description,
            group_slug=group_slug or "",
        )
        self.registry.add(project)

        # Best-effort — stars/forks/commits are nice-to-have on the catalog
        # view immediately, but a stats-fetch failure (rate limit, transient
        # network error) must never undo a registration that already succeeded.
        try:
            from resource_explorer.github.stats_fetcher import StatsFetcher
            StatsFetcher().fetch(slug)
        except Exception as exc:
            log.warning("Stats fetch failed for newly-imported repo '%s': %s", slug, exc)

        return self.registry.get(slug)


def _run_import_batch(
    source_label: str,
    repos: list[dict],
    group_slug: str,
) -> None:
    """repos: list of {"github_url", "display_name", "description"} dicts —
    already filtered to not-yet-registered repos by the caller (the route).
    Runs in a daemon thread; nothing here returns to an HTTP response.

    source_label describes what produced this batch — a GitHub org name
    (e.g. "cncf") or a search description (e.g. "search: language:python
    stars:>=500") — threaded into the activity-log summary text only; unlike
    an org name it isn't necessarily a valid URL path, so it's never used to
    build entity_location for the batch-summary entry below."""
    registry = ProjectRegistry()
    importer = OrgImporter(registry)

    succeeded = 0
    failed = 0
    for repo in repos:
        github_url = repo["github_url"]
        display_name = repo.get("display_name") or github_url
        try:
            importer.import_repo(
                github_url, display_name, repo.get("description", ""), group_slug,
            )
            succeeded += 1
            log_scout(
                registry, entity_type="repo", entity_slug=_url_to_slug(github_url),
                entity_name=display_name, entity_location=github_url,
                status="ok", summary=f"Imported '{display_name}' from {source_label}",
            )
        except Exception as exc:
            failed += 1
            log.exception("Import: failed to register %s", github_url)
            log_scout(
                registry, entity_type="repo", entity_slug=_url_to_slug(github_url),
                entity_name=display_name, entity_location=github_url,
                status="error", summary=f"Failed to import '{display_name}' from {source_label}",
                detail=str(exc),
            )

    log_scout(
        registry, entity_type="repo", entity_slug=_slugify_source_label(source_label),
        entity_name=source_label, entity_location=source_label,
        status="error" if failed else "ok",
        summary=f"Import batch complete ({source_label}): {succeeded} succeeded, {failed} failed, out of {len(repos)} requested",
    )
