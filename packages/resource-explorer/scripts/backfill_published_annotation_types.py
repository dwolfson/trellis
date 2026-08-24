"""Backfill project_published_annotation_types from Egeria's own SurveyReport
history, for publishes that happened before that local table existed
(added 2026-08-24 alongside the Survey Results dashboards' per-card
"last published" badge — see registry.py's own get_last_published_
annotation_types()/record_published_annotation_types() docstrings).

Why this is possible at all: EgeriaPublisher.publish() already writes one
row to project_egeria_surveys per publish (project_slug, surveyed_at,
egeria_report_guid, published_at) — that's been there since before this
table existed. So for any repo that's ever been published, we already know
exactly which SurveyReport to ask Egeria about; this script just asks it
(via the same engine-agnostic get_annotations_by_report_guid() the live
publish-attribution code doesn't need, because it already has the
annotations in memory at publish time — a backfill has to go get them).

Idempotent — safe to run repeatedly, and worth keeping around for exactly
that: it's the standing tool for "attach real Egeria history to local
tracking after adding a new local-tracking table," not a one-off throwaway.
Every SurveyReport already recorded (registry.has_published_annotation_
types_for_report) is skipped, not re-inserted. Never touches Egeria data —
read-only against Egeria, and additive-only locally (no existing local rows
are ever modified or removed).

Usage:
    uv run --package resource-explorer python scripts/backfill_published_annotation_types.py [--dry-run] [--slug REPO_SLUG]

    --dry-run          Report what would be written without touching the local DB.
    --slug REPO_SLUG    Limit to one repo (default: every published repo).
    --platform-url / --view-server / --user-id / --user-password
                        Override the .env-derived Egeria connection, same as
                        every other script in this directory that talks to Egeria.
"""
from __future__ import annotations

import argparse


def _distinct_annotation_types(annotations: list[dict]) -> set[str]:
    return {a["annotation_type"] for a in annotations if a.get("annotation_type")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be written without writing it.")
    parser.add_argument("--slug", default=None, help="Limit to one repo slug (default: every published repo).")
    parser.add_argument("--platform-url", default=None)
    parser.add_argument("--view-server", default=None)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--user-password", default=None)
    args = parser.parse_args()

    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

    registry = ProjectRegistry()
    publisher = EgeriaPublisher(
        platform_url=args.platform_url, view_server=args.view_server,
        user_id=args.user_id, user_password=args.user_password,
        registry=registry,
    )

    if args.slug:
        projects = [p for p in registry.list_all() if p.slug == args.slug]
        if not projects:
            parser.error(f"No project with slug {args.slug!r}")
    else:
        projects = [p for p in registry.list_all() if getattr(p, "egeria_asset_guid", "")]

    reports_backfilled = 0
    reports_skipped_existing = 0
    reports_skipped_empty = 0
    reports_errored = 0
    types_written = 0

    for project in projects:
        surveys = registry.get_egeria_surveys(project.slug)
        if not surveys:
            continue
        for survey in surveys:
            report_guid = survey.get("egeria_report_guid") or ""
            if not report_guid:
                continue
            if registry.has_published_annotation_types_for_report(project.slug, report_guid):
                reports_skipped_existing += 1
                continue

            try:
                annotations = publisher.get_annotations_by_report_guid(report_guid)
            except Exception as exc:
                print(f"[{project.slug}] {report_guid[:12]}…: ERROR fetching annotations — {exc}")
                reports_errored += 1
                continue

            types = _distinct_annotation_types(annotations)
            if not types:
                # A real, non-error outcome — an old/empty report, or one
                # Egeria no longer has annotations for. Not backfillable,
                # not a failure either.
                print(f"[{project.slug}] {report_guid[:12]}…: no annotation types found — skip")
                reports_skipped_empty += 1
                continue

            verb = "would record" if args.dry_run else "recorded"
            print(f"[{project.slug}] {report_guid[:12]}… ({survey.get('published_at', '?')}): {verb} {len(types)} type(s) — {', '.join(sorted(types))}")
            if not args.dry_run:
                registry.record_published_annotation_types(
                    project.slug, types, report_guid, published_at=survey.get("published_at"),
                )
            reports_backfilled += 1
            types_written += len(types)

    print()
    print(
        f"{'Would backfill' if args.dry_run else 'Backfilled'} {reports_backfilled} report(s), "
        f"{types_written} annotation-type row(s) across {len(projects)} project(s). "
        f"Skipped {reports_skipped_existing} already-recorded, {reports_skipped_empty} empty, {reports_errored} errored."
    )


if __name__ == "__main__":
    main()
