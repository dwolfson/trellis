"""
Sub-surveyor: File Classification

Walks the project's indexed file paths (from project_code_symbols + registry
collections) and produces:
  - One ClassificationAnnotation per distinct (deployedImplementationType, fileType)
    group summarising what categories of files were found.
  - One ResourceMeasureAnnotation with aggregate counts per file extension.

Runs in all cases — with or without Egeria credentials.  When Egeria
credentials are available the FileTypeCache is refreshed first, giving richer
classifications; when offline the last-persisted cache is used.

The actual (filename, extension) -> Egeria reference-data lookup has no repo
dependency at all — `classify_file_paths()` below is the resource-agnostic
core, callable with any plain list of paths (e.g. from a filesystem walk).
`FileClassifierSurveyor` is the repo-specific wrapper: it sources paths from
repo registry tables and shapes the result into repo's existing annotation
conventions (kept unchanged here for backward compatibility).
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.file_classifier.file_classifier import FileClassifier
from resource_explorer.surveyors.file_classifier.type_cache import get_cache
from resource_explorer.surveyors.survey_report import (
    Annotation,
    ClassificationAnnotation,
    ResourceMeasureAnnotation,
)

log = logging.getLogger(__name__)


@dataclass
class FileClassificationResult:
    """Raw output of classify_file_paths() — callers shape this into whatever
    Annotation types suit their resource type (repo groups unrecognized files
    into a low-confidence "Other" ClassificationAnnotation; a filesystem
    survey may instead want an RFA, matching Egeria's native "Missing File
    Reference Data" annotation — see docs/filesystem-survey-analytics-plan.md)."""
    file_paths: list[str]
    type_groups: dict[str, list[str]] = field(default_factory=dict)   # label -> paths
    ext_counter: Counter = field(default_factory=Counter)             # extension -> count
    other_paths: list[str] = field(default_factory=list)              # unclassified paths
    other_ext_counter: Counter = field(default_factory=Counter)       # extension -> count, unclassified only
    source: str = "extension"                                        # "egeria" | "extension"


def classify_file_paths(
    file_paths: list[str],
    pyegeria_client=None,
    force_refresh: bool = False,
) -> FileClassificationResult:
    """Classify a plain list of file paths by (deployedImplementationType,
    fileType, assetTypeName) using the shared, Egeria-reference-data-backed
    FileTypeCache. No registry/project dependency — works for repo, filesystem,
    or any other resource type that can produce a flat path list."""
    cache = get_cache()
    if pyegeria_client and (force_refresh or cache.needs_refresh()):
        cache.refresh_from_egeria(pyegeria_client)

    classifier = FileClassifier(pyegeria_client=None)  # use cache-backed lookup
    classifier.fileNameReferenceDataCache = {}          # reset instance cache
    classifier.fileExtensionReferenceDataCache = {}

    ext_counter: Counter = Counter()
    type_groups: dict[str, list[str]] = defaultdict(list)
    other_ext_counter: Counter = Counter()
    other_paths: list[str] = []

    for path_str in file_paths:
        p = Path(path_str)
        ext = classifier.get_file_extension(p.name) or "(none)"
        ext_counter[ext] += 1

        meta = cache.lookup(p.name, classifier.get_file_extension(p.name))
        label = (
            meta.get("deployedImplementationType")
            or meta.get("fileType")
            or meta.get("assetTypeName")
        )
        if label:
            type_groups[label].append(path_str)
        else:
            other_ext_counter[ext] += 1
            other_paths.append(path_str)

    source = "egeria" if pyegeria_client or not cache.needs_refresh() else "extension"
    return FileClassificationResult(
        file_paths=file_paths,
        type_groups=dict(type_groups),
        ext_counter=ext_counter,
        other_paths=other_paths,
        other_ext_counter=other_ext_counter,
        source=source,
    )


class FileClassifierSurveyor(BaseSurveyor):
    """
    Wraps the existing FileClassifier to produce survey annotations.

    Parameters
    ----------
    project         : Project from registry
    registry        : open ProjectRegistry
    pyegeria_client : optional — if provided the FileTypeCache is refreshed
                      from Egeria's ValidMetadataValues before classification.
    force_refresh   : force a cache refresh even if not stale
    """

    STEP = "FileClassification"

    def __init__(
        self,
        project: Project,
        registry: ProjectRegistry,
        pyegeria_client=None,
        force_refresh: bool = False,
    ) -> None:
        super().__init__(project, registry)
        self._pyegeria_client = pyegeria_client
        self._force_refresh = force_refresh

    @property
    def step_name(self) -> str:
        return self.STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            file_paths = self._collect_file_paths()
            if not file_paths:
                self._warn(results, "No file paths found in registry for this project.")
                return results

            classification = classify_file_paths(
                file_paths, pyegeria_client=self._pyegeria_client, force_refresh=self._force_refresh
            )
            type_groups = classification.type_groups
            ext_counter = classification.ext_counter
            other_ext_counter = classification.other_ext_counter
            other_paths = classification.other_paths

            # One ClassificationAnnotation per recognized type group
            for label, paths in sorted(type_groups.items()):
                results.append(
                    ClassificationAnnotation(
                        summary=f"{len(paths)} file(s) classified as '{label}'",
                        analysis_step=self.STEP,
                        candidate_classifications=[label],
                        confidence=90,
                        json_properties={
                            "file_count": len(paths),
                            "sample_paths": paths[:5],
                        },
                    )
                )

            # All unrecognized files → single "Other" annotation with extension breakdown
            if other_paths:
                results.append(
                    ClassificationAnnotation(
                        summary=f"{len(other_paths)} file(s) with unrecognized type",
                        analysis_step=self.STEP,
                        candidate_classifications=["Other"],
                        confidence=50,
                        json_properties={
                            "file_count": len(other_paths),
                            "unrecognized_extensions": dict(other_ext_counter.most_common()),
                            "sample_paths": other_paths[:5],
                        },
                    )
                )
                type_groups["Other"] = other_paths

            # One ResourceMeasureAnnotation with full extension breakdown
            results.append(
                ResourceMeasureAnnotation(
                    summary=f"File extension breakdown across {len(file_paths)} indexed files",
                    analysis_step=self.STEP,
                    resource_properties={"by_extension": dict(ext_counter.most_common())},
                    json_properties={
                        "total_files": len(file_paths),
                        "unrecognized_extensions": dict(other_ext_counter.most_common()),
                    },
                )
            )

            # Persist type group counts to SQLite so the web chart can use them.
            type_counts = {label: len(paths) for label, paths in type_groups.items()}
            source = classification.source
            details: dict[str, dict] = {}
            if other_ext_counter:
                details["Other"] = dict(other_ext_counter.most_common())
            try:
                self.registry.upsert_file_type_counts(
                    self.project.slug, type_counts, source=source, details=details
                )
            except Exception as exc:
                log.warning("FileClassifierSurveyor: could not persist type counts: %s", exc)

        except Exception as exc:
            log.exception("FileClassifierSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results

    def _collect_file_paths(self) -> list[str]:
        """Return all file paths for this project.

        Primary source: project_file_inventory (populated during add/refresh — covers
        every file in the repo).  Falls back to three partial sources for projects
        that pre-date the inventory table:
          • project_code_symbols  — Python/JS/Java/Go source files
          • Milvus metadata       — markdown, examples, release notes, web docs, PDFs
          • project_dependencies.source_file — package manifests
        """
        slug = self.project.slug

        # Primary: full file inventory (populated by ingestion pipeline)
        inventory = self.registry.get_file_inventory(slug)
        if inventory:
            log.debug("_collect_file_paths: %s → %d files from inventory", slug, len(inventory))
            return inventory

        # Fallback for projects indexed before the inventory table existed
        log.debug("_collect_file_paths: %s — no inventory; using partial sources", slug)
        with self.registry._conn() as conn:
            code_rows = conn.execute(
                "SELECT DISTINCT file_path FROM project_code_symbols WHERE project_slug = ?",
                (slug,),
            ).fetchall()
            dep_rows = conn.execute(
                "SELECT DISTINCT source_file FROM project_dependencies "
                "WHERE project_slug = ? AND source_file != ''",
                (slug,),
            ).fetchall()

        paths: set[str] = {r["file_path"] for r in code_rows}
        code_count = len(paths)
        dep_paths = {r["source_file"] for r in dep_rows}
        paths.update(dep_paths)

        project = self.registry.get(slug)
        if project and project.collections:
            from resource_explorer.multi_collection_store import MultiCollectionStore
            store = MultiCollectionStore()
            milvus_paths = store.list_source_files(project.collections)
            paths.update(p for p in milvus_paths if p and not p.startswith("http"))

        log.debug(
            "_collect_file_paths: %s → %d code + %d dep + %d milvus = %d total (partial)",
            slug, code_count, len(dep_paths),
            len(paths) - code_count - len(dep_paths), len(paths),
        )
        return list(paths)
