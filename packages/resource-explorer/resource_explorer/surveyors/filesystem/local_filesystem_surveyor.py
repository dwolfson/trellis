from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from resource_explorer.registry import FileSystemEntity, ProjectRegistry
from resource_explorer.surveyors.file_classifier.file_classifier_surveyor import classify_file_paths
from resource_explorer.surveyors.sub_surveyors.data_profiler import (
    _DATA_EXTENSIONS,
    _PANDAS_READABLE,
    _SCHEMA_ONLY,
    DataProfilerSurveyor,
    _fmt_size,
)

log = logging.getLogger(__name__)


def build_rfa_annotations(survey_data: dict) -> list[dict]:
    """Build activity-log RequestForAction annotation dicts from a survey_data
    dict's inaccessible/unclassified/profiling-failure fields.

    Distinct from EgeriaFileSystemSurveyor.publish_step_annotations' RFAs:
    those only get created when a survey is explicitly published to Egeria.
    This is RE's own local activity log (`registry.write_activity`/`GET
    /api/activity/rfas`, the 📝 RFAs tab) — it works for a purely local
    survey with no Egeria involvement at all, so problems found during a
    quick local walk are still visible somewhere without requiring a publish
    step first."""
    annotations: list[dict] = []

    inaccessible_count = survey_data.get("inaccessible_file_count", 0)
    if inaccessible_count:
        annotations.append({
            "analysis_name": "FileSystemWalk",
            "annotation_type": "RequestForAction",
            "count": inaccessible_count,
            "status": "local",
            "summary": f"{inaccessible_count} file(s)/director(y/ies) could not be accessed during the scan",
        })

    profiling_errors = survey_data.get("profiling_errors") or []
    if profiling_errors:
        annotations.append({
            "analysis_name": "DataProfiling",
            "annotation_type": "RequestForAction",
            "count": len(profiling_errors),
            "status": "local",
            "summary": f"{len(profiling_errors)} data file(s) could not be schema-profiled",
        })

    unclassified_count = (survey_data.get("classification") or {}).get("unclassified_count", 0)
    if unclassified_count:
        annotations.append({
            "analysis_name": "FileSystemClassification",
            "annotation_type": "RequestForAction",
            "count": unclassified_count,
            "status": "local",
            "summary": f"{unclassified_count} file(s) could not be classified against known file reference data",
        })

    return annotations

# Skip walking these common noise directories
IGNORE_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",  # bare "venv" (not just ".venv") — the previous omission meant every
             # stray Python venv under a broad root got fully recursed into,
             # which is what made an ordinary scan take minutes and flood the
             # console with pandas/openpyxl noise from tzdata/pytz zoneinfo files.
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".gemini",
    "dist",
    "build",
}


class LocalFileSystemSurveyor:
    """Walks a local filesystem directory, scans files, and profiles data files.

    Internally split into two phases — a metadata-only pass (one `stat()` per
    file — cheap, matches what Egeria's own native FileDirectory:CreateAndSurvey
    process captures) and a content-reading pass (pandas-based schema
    profiling — expensive, and the actual source of the multi-minute scans and
    swallowed errors reported 2026-07-13). `run()` still does both in one call
    for backward compatibility with the pre-Survey-Definition `/survey` route
    and its UI (`renderFilesystemSurveyReport`), which expect one flat dict.
    See docs/filesystem-survey-analytics-plan.md for the full design record —
    note the phases are kept as one Survey Definition step, not two: Egeria's
    own native survey doesn't decompose this either, and once you're already
    asking the OS for one file's stat() info there's no benefit to walking the
    tree twice to get the rest of it.
    """

    def __init__(self, filesystem: FileSystemEntity, registry: ProjectRegistry) -> None:
        self.filesystem = filesystem
        self.registry = registry
        self.root_path = Path(filesystem.local_mount_point)

    def run(self) -> dict:
        """Scan the filesystem path, profile data files, and return the survey data."""
        survey_data = self._scan_structure()
        self._profile_data_files(survey_data)
        return survey_data

    def _scan_structure(self) -> dict:
        """Phase 1: one walk, one `stat()` per file. Collects counts, OS-level
        file attributes (hidden/symlink/executable/writable, timestamps),
        Egeria-reference-data classification, and inaccessible-file tracking —
        comparable in content to Egeria's native "Capture File Counts" /
        "Profile Deployed Implementation Types" / "Profile Asset Types" /
        "Profile File Types" / "Profile File Extensions" / "Missing File
        Reference Data" / "Inaccessible files" annotations. No file content is
        read in this phase."""
        if not self.root_path.exists() or not self.root_path.is_dir():
            raise FileNotFoundError(
                f"Local mount point directory not found or is not a directory: {self.root_path}"
            )

        log.info(f"Starting local filesystem survey for {self.filesystem.slug} on {self.root_path}")

        inventory: list[dict] = []
        total_files = 0
        total_data_files = 0
        total_size_bytes = 0
        formats_summary: dict[str, dict[str, Any]] = {}
        hidden_count = symlink_count = executable_count = writable_count = 0
        extensions: set[str] = set()
        filenames: set[str] = set()
        last_access_time = last_creation_time = last_modification_time = ""
        inaccessible_files: list[dict] = []

        for p in self._walk_directory(self.root_path, inaccessible_files):
            total_files += 1
            rel_path = str(p.relative_to(self.root_path))
            try:
                stat = p.stat()
                size_bytes = stat.st_size
            except Exception as exc:
                inaccessible_files.append({"path": rel_path, "error": str(exc)})
                continue
            total_size_bytes += size_bytes

            is_hidden = p.name.startswith(".")
            try:
                is_symlink = p.is_symlink()
            except OSError:
                is_symlink = False
            is_executable = os.access(p, os.X_OK)
            is_writable = os.access(p, os.W_OK)
            if is_hidden:
                hidden_count += 1
            if is_symlink:
                symlink_count += 1
            if is_executable:
                executable_count += 1
            if is_writable:
                writable_count += 1

            # st_ctime is inode-change time on Unix, not true creation time —
            # no portable birth-time API exists across platforms, so this is
            # the same best-effort approximation Egeria's own annotation
            # wording ("Last file creation time") leaves ambiguous too.
            access_iso = datetime.utcfromtimestamp(stat.st_atime).isoformat()
            modify_iso = datetime.utcfromtimestamp(stat.st_mtime).isoformat()
            create_iso = datetime.utcfromtimestamp(stat.st_ctime).isoformat()
            last_access_time = max(last_access_time, access_iso)
            last_modification_time = max(last_modification_time, modify_iso)
            last_creation_time = max(last_creation_time, create_iso)

            ext = p.suffix.lstrip(".").lower()
            extensions.add(ext or "(none)")
            filenames.add(p.name)

            file_info = {
                "file_path": rel_path,
                "file_name": p.name,
                "file_size_bytes": size_bytes,
                "file_size": _fmt_size(size_bytes),
                "is_data_file": False,
                "format": "Unknown",
                "is_hidden": is_hidden,
                "is_symlink": is_symlink,
                "is_executable": is_executable,
                "is_writable": is_writable,
                "modified_at": modify_iso,
            }

            if ext in _DATA_EXTENSIONS:
                total_data_files += 1
                fmt = _DATA_EXTENSIONS[ext]
                file_info["is_data_file"] = True
                file_info["format"] = fmt

                if fmt not in formats_summary:
                    formats_summary[fmt] = {"count": 0, "total_size_bytes": 0}
                formats_summary[fmt]["count"] += 1
                formats_summary[fmt]["total_size_bytes"] += size_bytes

            inventory.append(file_info)

        classification = classify_file_paths([f["file_path"] for f in inventory])

        survey_data = {
            "surveyed_at": datetime.utcnow().isoformat(),
            "total_files": total_files,
            "total_data_files": total_data_files,
            "total_size_bytes": total_size_bytes,
            "total_size": _fmt_size(total_size_bytes),
            "formats": {
                fmt: {
                    "count": val["count"],
                    "total_size": _fmt_size(val["total_size_bytes"]),
                    "total_size_bytes": val["total_size_bytes"],
                }
                for fmt, val in formats_summary.items()
            },
            "inventory": inventory,
            # Egeria "Capture File Counts" parity:
            "hidden_count": hidden_count,
            "symlink_count": symlink_count,
            "executable_count": executable_count,
            "writable_count": writable_count,
            "unique_extension_count": len(extensions),
            "unique_filename_count": len(filenames),
            "last_access_time": last_access_time,
            "last_creation_time": last_creation_time,
            "last_modification_time": last_modification_time,
            "inaccessible_file_count": len(inaccessible_files),
            "inaccessible_files": inaccessible_files[:100],
            # Egeria "Profile Deployed Implementation Types/Asset Types/File
            # Types/File Extensions" + "Missing File Reference Data" parity:
            "classification": {
                "type_counts": {label: len(paths) for label, paths in classification.type_groups.items()},
                "extension_counts": dict(classification.ext_counter),
                "unclassified_count": len(classification.other_paths),
                "unclassified_sample": classification.other_paths[:50],
                "source": classification.source,
            },
            # Populated by _profile_data_files(); present here so callers that
            # only run the structure phase still get a consistent shape.
            "profiling_errors": [],
        }

        log.info(
            f"Filesystem structure scan complete for {self.filesystem.slug}: {total_files} files "
            f"({total_data_files} data files, {len(inaccessible_files)} inaccessible), "
            f"total size: {survey_data['total_size']}"
        )
        return survey_data

    def _profile_data_files(self, survey_data: dict) -> None:
        """Phase 2: read and parse each data file's contents to profile schema
        (rows/columns/dtypes/nulls). Mutates survey_data in place — adds
        row_count/col_count/columns/null_summary to each profiled inventory
        entry, and collects per-file failures into survey_data["profiling_errors"]
        instead of only logging them (the previous behavior: profiling
        failures were `log.warning`'d and otherwise silently dropped, which is
        why a run that hit dozens of malformed CSVs/legacy .xls files looked
        like a hang rather than a completed run with warnings)."""
        pd: Any = None
        try:
            import pandas as _pd
            pd = _pd
        except ImportError:
            log.warning("pandas not installed — file schema profiling will be skipped (size and extension only)")
            return

        profiling_errors: list[dict] = []
        for file_info in survey_data["inventory"]:
            if not file_info.get("is_data_file"):
                continue
            ext = Path(file_info["file_name"]).suffix.lstrip(".").lower()
            if ext not in _PANDAS_READABLE:
                continue
            size_bytes = file_info["file_size_bytes"]
            limit_bytes = 50 * 1024 * 1024  # 50MB
            if ext not in _SCHEMA_ONLY and size_bytes > limit_bytes:
                continue

            p = self.root_path / file_info["file_path"]
            try:
                profile = DataProfilerSurveyor._profile_file(p, ext, pd)
                if profile:
                    file_info.update({
                        "row_count": profile.get("row_count"),
                        "col_count": profile.get("col_count"),
                        "columns": profile.get("columns", []),
                        "null_summary": profile.get("null_summary", ""),
                    })
            except Exception as exc:
                log.debug(f"Could not profile schema for {file_info['file_path']}: {exc}")
                profiling_errors.append({"path": file_info["file_path"], "error": str(exc)})

        survey_data["profiling_errors"] = profiling_errors
        if profiling_errors:
            log.info(
                f"Filesystem data profiling for {self.filesystem.slug} finished with "
                f"{len(profiling_errors)} file(s) that could not be profiled — see "
                "survey_data['profiling_errors'] for the full list."
            )

    def _walk_directory(self, root: Path, inaccessible_files: list[dict]) -> list[Path]:
        """Walk root directory, returning Path objects of files, ignoring noise
        directories. Permission/OS errors while walking are recorded into
        inaccessible_files (relative to self.root_path where possible) instead
        of only being logged — they previously vanished from the survey result
        entirely."""
        files = []
        try:
            for p in root.iterdir():
                if p.is_dir():
                    if p.name in IGNORE_DIRS:
                        continue
                    files.extend(self._walk_directory(p, inaccessible_files))
                elif p.is_file():
                    files.append(p)
        except PermissionError as exc:
            self._record_inaccessible_dir(root, exc, inaccessible_files)
        except Exception as exc:
            self._record_inaccessible_dir(root, exc, inaccessible_files)
        return files

    def _record_inaccessible_dir(self, root: Path, exc: Exception, inaccessible_files: list[dict]) -> None:
        log.warning(f"Error walking directory {root}: {exc}")
        try:
            rel = str(root.relative_to(self.root_path))
        except ValueError:
            rel = str(root)
        inaccessible_files.append({"path": rel, "error": str(exc)})
