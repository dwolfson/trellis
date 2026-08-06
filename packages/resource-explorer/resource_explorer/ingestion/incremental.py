"""Incremental indexer — re-indexes only collection types affected by changed files."""
from __future__ import annotations

from pathlib import PurePath

from resource_explorer.github.client import GitHubClient
from resource_explorer.ingestion.pipeline import IngestionPipeline
from resource_explorer.multi_collection_store import MultiCollectionStore
from resource_explorer.registry import Project, ProjectRegistry, ProjectStatus


class IncrementalIndexer:
    """
    Commit-diff based incremental update strategy:
      1. Fetch latest commit SHA from GitHub
      2. Compare against stored last_commit_sha in registry
      3. git diff --name-only last_sha..HEAD → list of changed files
      4. Determine which collection types are affected by the changed files
      5. Drop and re-ingest only affected collections

    Re-indexes at collection granularity (not per-file) to avoid the complexity
    of Milvus delete-by-metadata-filter on arbitrary schemas.
    """

    def __init__(self) -> None:
        self.registry = ProjectRegistry()
        self.client = GitHubClient()

    def refresh(self, project: Project) -> None:
        import tempfile
        from pathlib import Path

        repo = self.client.get_repo(project.github_url)
        latest_sha = self.client.get_latest_commit_sha(repo)

        last_sha = self._get_last_sha(project.slug)
        if last_sha == latest_sha:
            print(f"No changes since last index ({latest_sha[:8]})")
            # Still profile data files if that step was never run
            if not self.registry.get_data_profiles(project.slug):
                self._run_profile_only(repo, project)
            return

        changed_files = self._get_changed_files(repo, last_sha, latest_sha)
        n = len(changed_files)
        print(f"{n} file{'s' if n != 1 else ''} changed since {last_sha[:8] if last_sha else 'initial index'}")

        if not changed_files:
            self._store_last_sha(project.slug, latest_sha)
            return

        # Find which collection types are touched by the changed files
        from config.collection_config import COLLECTION_TYPES
        affected_names = set()
        for path in changed_files:
            ext = PurePath(path).suffix.lower()
            for ctype in COLLECTION_TYPES.values():
                if ext in ctype.file_extensions:
                    affected_names.add(ctype.name)

        # release_notes are always worth refreshing when anything changed
        affected_names.add("release_notes")

        # Filter to collections the project actually has
        project_ctypes = {
            name: COLLECTION_TYPES[name]
            for name in affected_names
            if name in COLLECTION_TYPES
            and f"{project.slug}_{name}" in (project.collections or [])
        }

        if not project_ctypes:
            self._store_last_sha(project.slug, latest_sha)
            return

        print(f"Re-indexing {len(project_ctypes)} collection(s): {', '.join(project_ctypes)}")

        store = MultiCollectionStore()
        pipeline = IngestionPipeline()

        # Download repo once for all affected file-based collections
        file_ctypes = {k: v for k, v in project_ctypes.items() if k != "release_notes"}
        surviving = [
            c for c in (project.collections or [])
            if not any(c == f"{project.slug}_{name}" for name in project_ctypes)
        ]

        subproject_path = project.subproject_path or None
        extra_docs_paths = project.extra_docs_paths or []

        _doc_ctypes = frozenset({"markdown_docs", "web_docs", "api_reference", "examples", "pdfs"})

        with tempfile.TemporaryDirectory() as tmp:
            local_root = None
            resolved_extra: list[tuple[str, Path]] = []
            if file_ctypes:
                print("Downloading repository...")
                if subproject_path and extra_docs_paths:
                    # Need full repo to access extra_docs_paths outside subproject_path
                    full_root = self.client.download_zipball(repo, Path(tmp))
                    local_root = full_root / subproject_path
                    resolved_extra = [(p, full_root / p) for p in extra_docs_paths]
                else:
                    local_root = self.client.download_zipball(repo, Path(tmp), subproject_path)

            for name, ctype in project_ctypes.items():
                collection_name = f"{project.slug}_{name}"
                store.drop_collection(collection_name)
                extra = resolved_extra if (name in _doc_ctypes and resolved_extra) else []
                count = pipeline._ingest_collection(
                    repo, project.slug, collection_name, ctype,
                    local_root if name != "release_notes" else None,
                    extra_paths=extra,
                )
                if count > 0:
                    surviving.append(collection_name)
                    print(f"  {collection_name}: {count} chunks")

            if local_root is not None:
                file_count, loc = pipeline._count_repo_stats(local_root)
                self.registry.update_ingestion_stats(project.slug, file_count, loc)
                pipeline._store_file_inventory(project.slug, local_root)
                pipeline._parse_dependencies(project.slug, local_root)
                pipeline._profile_data_files(project.slug, local_root)

        self.registry.update_indexed_at(project.slug, surviving)
        self.registry.update_status(project.slug, ProjectStatus.ACTIVE)
        self._store_last_sha(project.slug, latest_sha)

    def _run_profile_only(self, repo, project: Project) -> None:
        """Download the repo just to populate file inventory and data profiles."""
        import tempfile
        from pathlib import Path

        pipeline = IngestionPipeline()
        subproject_path = project.subproject_path or None
        print("  Downloading repository for data profiling…")
        with tempfile.TemporaryDirectory() as tmp:
            local_root = self.client.download_zipball(repo, Path(tmp), subproject_path)
            pipeline._store_file_inventory(project.slug, local_root)
            pipeline._profile_data_files(project.slug, local_root)
        print("  Data profiles updated.")

    def _get_changed_files(self, repo, old_sha: str, new_sha: str) -> list[str]:
        if not old_sha:
            return []  # first run — full ingestion handled by IngestionPipeline
        try:
            comparison = repo.compare(old_sha, new_sha)
            return [f.filename for f in comparison.files]
        except Exception:
            return []

    def _get_last_sha(self, slug: str) -> str:
        project = self.registry.get(slug)
        return project.last_commit_sha if project else ""

    def _store_last_sha(self, slug: str, sha: str) -> None:
        self.registry.update_commit_sha(slug, sha)
