"""Sub-surveyor: File Size → ResourceMeasureAnnotation + RequestForAction.

Uses project_file_inventory (populated during add/refresh) to produce
precise per-file size metrics.  The FileStructureSurveyor reports a rough
`repo_size_kb` from the GitHub API; this surveyor gives exact sizing from
the actual stored inventory and flags oversized individual files.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.file_classifier.type_cache import get_cache
from resource_explorer.surveyors.scoping import path_matches_scope
from resource_explorer.surveyors.survey_report import (
    Annotation,
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
)

log = logging.getLogger(__name__)

STEP = "FileSizeAnalysis"

_LARGE_FILE_THRESHOLD_MB = 50
_VERY_LARGE_FILE_THRESHOLD_MB = 200


def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.1f} MB"
    if size_bytes >= 1_024:
        return f"{size_bytes / 1_024:.1f} KB"
    return f"{size_bytes} B"


class FileSizeSurveyor(BaseSurveyor):
    """
    Reads project_file_inventory to produce size-based annotations:
      - ResourceMeasureAnnotation: total size, average file size, size by type group
      - ResourceMeasureAnnotation: top-10 largest files
      - RequestForActionAnnotation: any file exceeding the large-file threshold
    """

    def __init__(
        self, project: Project, registry: ProjectRegistry,
        scope_locator: str = "",
    ) -> None:
        super().__init__(project, registry)
        # Repo scope-narrowing funnel plan (docs/repo-scope-narrowing-funnel.md),
        # D5/D6 — "" (default) = whole-repo, unchanged from every existing
        # caller; a non-empty locator narrows to one cataloged sub-resource
        # (this kind is target_shape="corpus" — a path-prefix filter).
        self._scope_locator = scope_locator

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            rows = self.registry.get_file_inventory_with_sizes(self.project.slug)
            if self._scope_locator:
                rows = [r for r in rows if path_matches_scope(r["file_path"], self._scope_locator)]
            if not rows:
                log.debug("FileSizeSurveyor: no inventory for %s", self.project.slug)
                return results

            cache = get_cache()
            total_bytes = sum(r["file_size_bytes"] for r in rows)
            total_files = len(rows)
            avg_bytes = total_bytes // total_files if total_files else 0

            # Group total size by deployedImplementationType label
            size_by_type: dict[str, int] = defaultdict(int)
            count_by_type: dict[str, int] = defaultdict(int)
            large_files: list[dict] = []

            for r in rows:
                p = Path(r["file_path"])
                ext = p.suffix.lstrip(".").lower() if p.suffix else ""
                meta = cache.lookup(p.name, ext or None)
                label = (
                    meta.get("deployedImplementationType")
                    or meta.get("fileType")
                    or "Other"
                )
                size_by_type[label] += r["file_size_bytes"]
                count_by_type[label] += 1

                if r["file_size_bytes"] >= _LARGE_FILE_THRESHOLD_MB * 1_048_576:
                    large_files.append(r)

            # Sort size_by_type descending for readability
            size_by_type_sorted = dict(
                sorted(size_by_type.items(), key=lambda kv: -kv[1])
            )
            size_by_type_fmt = {k: _fmt_size(v) for k, v in size_by_type_sorted.items()}

            results.append(
                ResourceMeasureAnnotation(
                    summary=(
                        f"Repository disk footprint: {_fmt_size(total_bytes)} "
                        f"across {total_files:,} files (avg {_fmt_size(avg_bytes)}/file)"
                    ),
                    analysis_step=STEP,
                    confidence=95,
                    resource_properties={
                        "total_size_bytes": total_bytes,
                        "total_size_human": _fmt_size(total_bytes),
                        "total_files": total_files,
                        "avg_size_bytes": avg_bytes,
                        "size_by_type": size_by_type_fmt,
                        "count_by_type": dict(
                            sorted(count_by_type.items(), key=lambda kv: -kv[1])
                        ),
                    },
                    json_properties={"source": "project_file_inventory"},
                )
            )

            # Top-10 largest files
            top10 = sorted(rows, key=lambda r: r["file_size_bytes"], reverse=True)[:10]
            if top10:
                results.append(
                    ResourceMeasureAnnotation(
                        summary=f"Largest file: {_fmt_size(top10[0]['file_size_bytes'])} ({top10[0]['file_path']})",
                        analysis_step=STEP,
                        confidence=100,
                        resource_properties={
                            "top_largest_files": {
                                r["file_path"]: _fmt_size(r["file_size_bytes"])
                                for r in top10
                            }
                        },
                        json_properties={"threshold_shown": 10},
                    )
                )

            # Flag large files
            for r in large_files:
                mb = r["file_size_bytes"] / 1_048_576
                severity = "very large" if mb >= _VERY_LARGE_FILE_THRESHOLD_MB else "large"
                results.append(
                    RequestForActionAnnotation(
                        summary=f"{severity.title()} file: {r['file_path']} ({_fmt_size(r['file_size_bytes'])})",
                        analysis_step=STEP,
                        confidence=100,
                        explanation=(
                            f"File exceeds {_LARGE_FILE_THRESHOLD_MB} MB. "
                            "Consider using Git LFS, storing in object storage, "
                            "or referencing a versioned data release instead of committing directly."
                        ),
                        action_requested="Review large file — consider Git LFS or external storage",
                        action_target_name=r["file_path"],
                    )
                )

        except Exception as exc:
            log.exception("FileSizeSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
