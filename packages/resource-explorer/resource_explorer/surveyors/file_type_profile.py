"""File types and file counts as Egeria's own folder-survey annotations.

Ruling 2026-10-07 (DESIGN-FILE-TYPES-AS-ANNOTATIONS.md): a file type is a MEASUREMENT, published as
profile annotations in the survey report under Egeria's names, verbatim, never as a DataSet per type.

    Capture File Counts      ResourceMeasureAnnotation   files, directories, distinct extensions, types
    Profile File Extensions  ResourceProfileAnnotation   count per extension
    Profile File Types       ResourceProfileAnnotation   count per file type (resolve_technology_type)
    Profile Asset Types      ResourceProfileAnnotation   what cataloging the SELECTED items would create
    Profile File Names       ResourceProfileLogAnnotation  only when a person asks, a CSV (never default)

Every count here comes from `project_file_inventory`, the table the inventory step refreshes, so the
profile equals the inventory by construction. The envelope (resultState, measuredAt, producingRun,
scope) rides in `additionalProperties`, which Egeria's own types do not carry.
"""
from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

from resource_explorer.surveyors.survey_report import (
    Annotation, ResourceMeasureAnnotation, ResourceProfileAnnotation, ResourceProfileLogAnnotation,
)

CAPTURE_FILE_COUNTS = "Capture File Counts"
PROFILE_FILE_EXTENSIONS = "Profile File Extensions"
PROFILE_FILE_TYPES = "Profile File Types"
PROFILE_ASSET_TYPES = "Profile Asset Types"
PROFILE_FILE_NAMES = "Profile File Names"

#: The names the default publish carries. Profile File Names is deliberately absent (size).
DEFAULT_NAMES = (CAPTURE_FILE_COUNTS, PROFILE_FILE_EXTENSIONS, PROFILE_FILE_TYPES, PROFILE_ASSET_TYPES)

STEP = "FileInventory"


def _extension(path: str) -> str:
    name = PurePosixPath(path).name
    return name.rsplit(".", 1)[-1].lower() if "." in name.lstrip(".") else ""


def _directories(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for p in paths:
        parent = PurePosixPath(p).parent
        while str(parent) not in (".", ""):
            out.add(str(parent))
            parent = parent.parent
    return out


def envelope(*, measured_at: str, producing_run: str, partial_reason: str = "") -> dict:
    env = {"resultState": "MEASURED", "measuredAt": measured_at, "producingRun": producing_run,
           "scope": "PARTIAL" if partial_reason else "WHOLE"}
    if partial_reason:
        env["scopeReason"] = partial_reason
    return env


def selected_asset_types(registry, slug: str) -> Counter:
    """What cataloging the selected items WOULD create, by Egeria asset type: the rows of the
    `sub_resources` table are the selection, and publish creates one FileFolder or DataFile per row,
    so this equals the Curate manifest's file and folder counts by construction."""
    out: Counter = Counter()
    for r in registry.list_sub_resources("repo", slug):
        out["FileFolder" if r.get("kind") == "folder" else "DataFile"] += 1
    return out


def build_file_type_annotations(registry, slug: str, *, surveyed_at: str,
                                partial_reason: str = "") -> list[Annotation]:
    """The four default annotations for one repository, from its stored inventory.

    `Profile Asset Types` is emitted only when something is selected: an empty selection is "nothing
    chosen", not a measured zero, so it is left out rather than published as an empty profile."""
    from resource_explorer.surveyors.sub_resource_templates import resolve_technology_type

    rows = registry.get_file_inventory_with_sizes(slug, include_vendored=True)
    paths = [r["file_path"] for r in rows]
    ext_counts = Counter(_extension(p) or "(none)" for p in paths)
    type_counts = Counter(resolve_technology_type(p) for p in paths)
    env = envelope(measured_at=surveyed_at, producing_run=f"{slug}::{surveyed_at}", partial_reason=partial_reason)
    vendored = sum(1 for r in rows if r.get("vendored"))

    out: list[Annotation] = [
        ResourceMeasureAnnotation(
            check_name="file_counts", analysis_step=STEP, annotation_type_name=CAPTURE_FILE_COUNTS,
            summary=f"{len(paths)} file(s) in {len(_directories(paths))} director(ies)",
            explanation="Counted from the stored file inventory, as Egeria's folder survey counts a folder.",
            resource_properties={"fileCount": len(paths), "directoryCount": len(_directories(paths)),
                                 "numberOfFileExtensions": len(ext_counts), "numberOfFileTypes": len(type_counts),
                                 "vendoredFileCount": vendored},
            additional_properties=dict(env)),
        ResourceProfileAnnotation(
            check_name="file_extensions", analysis_step=STEP, annotation_type_name=PROFILE_FILE_EXTENSIONS,
            summary=f"{len(ext_counts)} extension(s) across {len(paths)} file(s)",
            value_count=dict(ext_counts), additional_properties=dict(env)),
        ResourceProfileAnnotation(
            check_name="file_types", analysis_step=STEP, annotation_type_name=PROFILE_FILE_TYPES,
            summary=f"{len(type_counts)} file type(s) across {len(paths)} file(s)",
            value_count=dict(type_counts), additional_properties=dict(env)),
    ]
    chosen = selected_asset_types(registry, slug)
    if chosen:
        out.append(ResourceProfileAnnotation(
            check_name="asset_types", analysis_step=STEP, annotation_type_name=PROFILE_ASSET_TYPES,
            summary=f"cataloging the {sum(chosen.values())} selected item(s) would create {len(chosen)} asset type(s)",
            value_count=dict(chosen), additional_properties={**env, "basis": "the selection on Curate"}))
    return out


def file_names_log_annotation(registry, slug: str, *, surveyed_at: str, csv_path: str) -> ResourceProfileLogAnnotation:
    """"Profile File Names", ON REQUEST only: the per-name counts are written to `csv_path` (one
    `name,count` line each) and the annotation points at that file. Never part of the default publish."""
    import csv
    names = Counter(PurePosixPath(r["file_path"]).name
                    for r in registry.get_file_inventory_with_sizes(slug, include_vendored=True))
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fileName", "count"])
        for name, n in sorted(names.items(), key=lambda kv: (-kv[1], kv[0])):
            w.writerow([name, n])
    return ResourceProfileLogAnnotation(
        check_name="file_names", analysis_step=STEP, annotation_type_name=PROFILE_FILE_NAMES,
        summary=f"{len(names)} distinct file name(s), logged to a CSV", log_file=csv_path,
        additional_properties=envelope(measured_at=surveyed_at, producing_run=f"{slug}::{surveyed_at}"))
