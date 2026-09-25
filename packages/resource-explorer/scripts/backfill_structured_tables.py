"""Backfill the structured DB/FS detail tables from existing survey_data blobs.

Until 2026-09-20, every database and filesystem survey result lived only as an
opaque `survey_data` JSON blob on `database_surveys` / `filesystem_surveys`.
`multi-resource-questions-design.md` §5.7 and §6 replace that with structured,
queryable rows (`database_schemas`, `database_tables`, `database_columns`, …,
`filesystem_entries`, `filesystem_data_files`), keyed
`(slug, surveyed_at, source)`.

New surveys write those rows as they run. This script converts the ones
already stored, so shipping the tables does not lose the history that exists —
the two live `database_surveys` rows in particular.

## Why a script rather than a migration step

`ProjectRegistry._init_schema()` runs on *every* `ProjectRegistry(...)`
construction, which in the web app is every request path that touches the
registry. Three reasons this work does not belong there:

1. **Cost.** Decoding every historical blob and rewriting its rows is bounded
   by survey history, not by startup. Paying it per construction is wrong, and
   paying it once behind a "have I run yet" flag means inventing a migration-
   version table this registry deliberately does not have (its whole migration
   idiom is `_get_table_columns` + `ALTER TABLE ADD COLUMN`, which is
   per-column and has no notion of a data migration).
2. **Reportability.** A back-fill that silently succeeds or silently skips is
   the thing nobody checks. Run explicitly, it prints per-survey counts and a
   non-zero exit on failure.
3. **Reversibility.** Re-running is safe and cheap; a step wired into schema
   init would re-run at moments nobody chose.

## Idempotence

`write_detail_rows` replaces a `(slug, surveyed_at, source)`'s rows rather than
appending, so running this twice leaves exactly the same table contents as
running it once. It is additive with respect to Egeria: nothing here reads or
writes Egeria at all.

## What it cannot recover

A blob only carries what its surveyor stored. Column profiles, grants and
`pg_settings` were never in it, so those tables stay empty for back-filled
runs — recorded explicitly as `survey_section_coverage` rows with state
`not_measured`, so a consumer reads "this survey never looked" rather than
"there are none". That distinction is the point of the coverage table; see
`registry.py`'s `STATE_*` constants.

Usage:
    uv run --package resource-explorer python scripts/backfill_structured_tables.py [--dry-run]
        [--slug SLUG] [--resource-type database|filesystem]

    --dry-run         Report what would be written without touching the DB.
    --slug SLUG       Limit to one database or filesystem slug.
    --resource-type   Limit to one resource type (default: both).
"""
from __future__ import annotations

import argparse
import json
import sys

from resource_explorer.registry import ProjectRegistry
from resource_explorer.surveyors.result_materializer import (
    backfill_database_survey,
    backfill_filesystem_survey,
    database_rows_from_survey_data,
    filesystem_rows_from_survey_data,
)


def _as_dict(survey_data) -> dict:
    """`get_database_surveys` returns survey_data as raw text; the filesystem
    helpers decode it. Accept either rather than depending on which."""
    if isinstance(survey_data, dict):
        return survey_data
    if isinstance(survey_data, str) and survey_data.strip():
        try:
            return json.loads(survey_data)
        except ValueError:
            return {}
    return {}


def backfill_databases(
    registry: ProjectRegistry, only_slug: str | None, dry_run: bool
) -> tuple[int, int]:
    """Returns (surveys processed, rows written)."""
    databases = registry.list_databases()
    surveys_done = 0
    rows_done = 0
    for database in databases:
        slug = database.slug
        if only_slug and slug != registry._normalize_slug(only_slug):
            continue
        surveys = registry.get_database_surveys(slug)
        if not surveys:
            print(f"  {slug}: no stored surveys")
            continue
        for survey in surveys:
            surveyed_at = survey.get("surveyed_at") or ""
            source = survey.get("source") or "local"
            blob = _as_dict(survey.get("survey_data"))
            if not blob:
                print(
                    f"  {slug} @ {surveyed_at} [{source}]: blob empty or "
                    f"unparseable — skipped, nothing to convert"
                )
                continue
            if dry_run:
                rows = database_rows_from_survey_data(blob)
                counts = {t: len(r) for t, r in rows.items() if r}
                print(f"  {slug} @ {surveyed_at} [{source}]: would write {counts}")
                rows_done += sum(counts.values())
            else:
                written = backfill_database_survey(
                    registry, slug, surveyed_at, blob, source=source
                )
                counts = {t: n for t, n in written.items() if n}
                print(f"  {slug} @ {surveyed_at} [{source}]: wrote {counts}")
                rows_done += sum(counts.values())
            surveys_done += 1
    return surveys_done, rows_done


def backfill_filesystems(
    registry: ProjectRegistry, only_slug: str | None, dry_run: bool
) -> tuple[int, int]:
    filesystems = registry.list_filesystems()
    surveys_done = 0
    rows_done = 0
    for filesystem in filesystems:
        slug = filesystem.slug
        if only_slug and slug != registry._normalize_slug(only_slug):
            continue
        surveys = registry.list_filesystem_surveys(slug)
        if not surveys:
            print(f"  {slug}: no stored surveys")
            continue
        for survey in surveys:
            surveyed_at = survey.get("surveyed_at") or ""
            source = survey.get("source") or "local"
            blob = _as_dict(survey.get("survey_data"))
            if not blob:
                print(
                    f"  {slug} @ {surveyed_at} [{source}]: blob empty or "
                    f"unparseable — skipped, nothing to convert"
                )
                continue
            if dry_run:
                rows = filesystem_rows_from_survey_data(blob)
                counts = {t: len(r) for t, r in rows.items() if r}
                print(f"  {slug} @ {surveyed_at} [{source}]: would write {counts}")
                rows_done += sum(counts.values())
            else:
                written = backfill_filesystem_survey(
                    registry, slug, surveyed_at, blob, source=source
                )
                counts = {t: n for t, n in written.items() if n}
                print(f"  {slug} @ {surveyed_at} [{source}]: wrote {counts}")
                rows_done += sum(counts.values())
            surveys_done += 1
    return surveys_done, rows_done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--slug", default=None)
    parser.add_argument(
        "--resource-type", choices=("database", "filesystem"), default=None
    )
    args = parser.parse_args(argv)

    registry = ProjectRegistry()
    total_surveys = 0
    total_rows = 0

    if args.resource_type in (None, "database"):
        print("Databases:")
        surveys, rows = backfill_databases(registry, args.slug, args.dry_run)
        total_surveys += surveys
        total_rows += rows
    if args.resource_type in (None, "filesystem"):
        print("File systems:")
        surveys, rows = backfill_filesystems(registry, args.slug, args.dry_run)
        total_surveys += surveys
        total_rows += rows

    verb = "would write" if args.dry_run else "wrote"
    print(f"\n{total_surveys} survey(s) processed, {verb} {total_rows} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
