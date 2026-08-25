#!/usr/bin/env python
"""Find (and optionally clear) cached Egeria GUIDs that no longer resolve.

Why this exists: RE caches `projects.egeria_asset_guid` so repeat publishes reuse
the same asset. When Egeria's metadata store is reseeded — a redeploy, a wipe,
a fresh quickstart — every cached GUID is left pointing at nothing, while RE
still renders those repos as ☁ Published. "Published to a catalog that no longer
holds it" and "published" look identical, which is the failure this codebase
keeps finding in other guises.

They self-heal on the NEXT publish (`egeria_publisher._find_or_create_asset`
verifies before reuse and clears a stale entry), but until something republishes,
the badge lies and any operation that needs the asset — adding it to an
investigation's working set, for one — fails with a bare NotFound.

Read-only by default. Pass --apply to clear. Clearing also removes that project's
`project_egeria_surveys` rows, which are local claims about surveys that Egeria
no longer holds; the count is reported so the deletion is never silent.

    uv run python scripts/sweep_stale_egeria_guids.py
    uv run python scripts/sweep_stale_egeria_guids.py --apply
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="clear the stale entries (default: report only)")
    args = ap.parse_args()

    from resource_explorer.config import get_config
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    with registry._conn() as conn:
        rows = conn.execute(
            "SELECT slug, egeria_asset_guid FROM projects "
            "WHERE egeria_asset_guid IS NOT NULL AND egeria_asset_guid <> '' "
            "ORDER BY slug"
        ).fetchall()
    cached = [(r["slug"], r["egeria_asset_guid"]) for r in rows]
    if not cached:
        print("No cached Egeria asset GUIDs. Nothing to sweep.")
        return 0
    print(f"{len(cached)} project(s) carry a cached Egeria asset GUID.\n")

    try:
        from pyegeria import AssetMaker
        cfg = get_config().egeria
        maker = AssetMaker(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
        maker.create_egeria_bearer_token()
    except Exception as exc:
        # Never guess. An unreachable Egeria must not be read as "everything is
        # stale" — that would clear every valid GUID in the catalog.
        print(f"Could not reach Egeria ({type(exc).__name__}: {exc}).")
        print("Refusing to sweep: unreachable is not the same as stale.")
        return 2

    stale, live, unknown = [], [], []
    for slug, guid in cached:
        try:
            found = maker.get_asset_by_guid(guid)
            (live if found and "No elements" not in str(found) else stale).append((slug, guid))
        except Exception as exc:
            if "NotFound" in type(exc).__name__ or "404" in str(exc) or "400" in str(exc):
                stale.append((slug, guid))
            else:
                unknown.append((slug, guid, f"{type(exc).__name__}: {str(exc)[:60]}"))

    print(f"  resolves in Egeria : {len(live)}")
    print(f"  STALE (dangling)   : {len(stale)}")
    print(f"  could not determine: {len(unknown)}\n")
    for slug, guid in stale:
        print(f"    stale  {slug:32} {guid}")
    for slug, guid, why in unknown:
        print(f"    ?      {slug:32} {guid}  ({why})")

    if not stale:
        print("\nNothing stale. No action needed.")
        return 0
    if not args.apply:
        print(f"\nDry run. Re-run with --apply to clear {len(stale)} stale entr(ies).")
        print("Projects that could not be determined are never cleared.")
        return 0

    total_surveys = 0
    for slug, _ in stale:
        result = registry.clear_egeria_registration(slug)
        total_surveys += result["surveys_deleted"]
        print(f"    cleared {slug} (survey records removed: {result['surveys_deleted']})")
    print(f"\nCleared {len(stale)} stale GUID(s) and {total_surveys} local survey record(s).")
    print("Those repos now read as un-published, which is the truth. Re-publish to recreate them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
