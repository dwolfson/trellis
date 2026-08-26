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
`project_egeria_surveys` rows and its `project_published_annotation_types` rows —
local claims about surveys and published annotations Egeria no longer holds; both
counts are reported so the deletion is never silent.

Three kinds of cached GUID are checked, not one. The asset GUIDs came first; an
investigation's Egeria Project and each disposition WorkingSet's Collection were
added later and were left dangling by every sweep before this one — an
investigation would keep rendering as "linked" to a Project that no longer
exists, and promoting it again would fail on a Project GUID nothing resolves.

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
        print("No cached Egeria asset GUIDs.")
        # Investigations and working sets dangle independently, and orphaned
        # publish claims outlive the GUID this sweep keys on. Returning here --
        # the third early return in this script to make that mistake -- is how
        # a previous pass left 97 publish claims and 7 GUIDs unreachable.
        _report_orphan_publish_claims(registry, apply=args.apply)
        maker = _connect(get_config)
        if maker is not None:
            _report_orphan_publish_claims(registry, apply=args.apply)
        _sweep_investigations(registry, maker, apply=args.apply)
        return 0
    print(f"{len(cached)} project(s) carry a cached Egeria asset GUID.\n")

    # Never guess. An unreachable Egeria must not be read as "everything is
    # stale" — that would clear every valid GUID in the catalog.
    maker = _connect(get_config)
    if maker is None:
        return 2

    # Verified the same way EgeriaPublisher._find_or_create_asset verifies before
    # reusing a cached GUID: search by qualifiedName and check the GUID is among
    # the results.
    #
    # NOT get_asset_by_guid. That was the original test here and it is wrong:
    # against a live catalog it raises PyegeriaNotFoundException/400 for GUIDs
    # that plainly exist -- measured 2026-08-26, when it declared all 23 cached
    # GUIDs stale while find_asset_guid returned those exact GUIDs for the same
    # repos. Running --apply on that verdict would have cleared every valid
    # registration in the catalog, with their survey records and publish claims.
    #
    # Two systems disagreeing about whether the same asset exists is worse than
    # either answer, so this now asks the question the publisher asks.
    with registry._conn() as conn:
        urls = {
            r["slug"]: r["github_url"]
            for r in conn.execute("SELECT slug, github_url FROM projects").fetchall()
        }

    stale, live, unknown = [], [], []
    for slug, guid in cached:
        url = urls.get(slug, "")
        if not url:
            unknown.append((slug, guid, "no github_url on the project row"))
            continue
        try:
            check = maker.find_software_capabilities(
                search_string=f"SourceControlLibrary::{url}",
                starts_with=True, ignore_case=False, output_format="JSON",
            )
            if not isinstance(check, list):
                # pyegeria returns a string when nothing matched -- a real
                # "not there", distinct from an exception.
                stale.append((slug, guid))
            elif any(e.get("elementHeader", {}).get("guid") == guid for e in check):
                live.append((slug, guid))
            else:
                stale.append((slug, guid))
        except Exception as exc:
            # An error is never read as stale. The publisher trusts the cache on
            # a failed verification for exactly this reason.
            unknown.append((slug, guid, f"{type(exc).__name__}: {str(exc)[:60]}"))

    print(f"  resolves in Egeria : {len(live)}")
    print(f"  STALE (dangling)   : {len(stale)}")
    print(f"  could not determine: {len(unknown)}\n")
    for slug, guid in stale:
        print(f"    stale  {slug:32} {guid}")
    for slug, guid, why in unknown:
        print(f"    ?      {slug:32} {guid}  ({why})")

    if not stale:
        print("\nNo stale asset GUIDs.")
        # Still sweep the other two kinds: they dangle independently, and an
        # early return here is why they went unchecked for as long as they did.
        _report_orphan_publish_claims(registry, apply=args.apply)
        _sweep_investigations(registry, maker, apply=args.apply)
        return 0
    if not args.apply:
        print(f"\nDry run. Re-run with --apply to clear {len(stale)} stale entr(ies).")
        print("Projects that could not be determined are never cleared.")
        _sweep_investigations(registry, maker, apply=False)
        return 0

    total_surveys = total_published = 0
    for slug, _ in stale:
        result = registry.clear_egeria_registration(slug)
        total_surveys += result["surveys_deleted"]
        total_published += result.get("published_types_deleted", 0)
        print(f"    cleared {slug} (surveys removed: {result['surveys_deleted']}, "
              f"publish claims removed: {result.get('published_types_deleted', 0)})")
    print(f"\nCleared {len(stale)} stale GUID(s), {total_surveys} local survey record(s) "
          f"and {total_published} published-annotation claim(s).")
    print("Those repos now read as un-published, which is the truth. Re-publish to recreate them.")
    _report_orphan_publish_claims(registry, apply=args.apply)
    _sweep_investigations(registry, maker, apply=args.apply)
    return 0


def _connect(get_config):
    """AssetMaker, or None with the reason printed. Never raises."""
    try:
        from pyegeria import AssetMaker
        cfg = get_config().egeria
        maker = AssetMaker(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
        maker.create_egeria_bearer_token()
        return maker
    except Exception as exc:
        print(f"Could not reach Egeria ({type(exc).__name__}: {exc}).")
        print("Refusing to sweep: unreachable is not the same as stale.")
        return None


def _report_orphan_publish_claims(registry, *, apply: bool) -> None:
    """Publish claims for projects that no longer hold an asset GUID.

    project_published_annotation_types is what the Analyses cards' Published
    badge is derived from. Clearing was keyed on the project HAVING a stale
    GUID, so any row an earlier pass missed became unreachable the moment that
    GUID was cleared -- the badge keeps claiming a publish while nothing points
    at a catalog entry, and no sweep can ever see it again. Measured after the
    2026-08-26 redeploy: 97 rows across the same 23 projects, stranded exactly
    this way by a sweep run from an older checkout.
    """
    with registry._conn() as conn:
        rows = conn.execute(
            "SELECT p.slug AS slug, count(*) AS n "
            "FROM project_published_annotation_types t "
            "JOIN projects p ON p.slug = t.project_slug "
            "WHERE coalesce(p.egeria_asset_guid, '') = '' "
            "GROUP BY p.slug ORDER BY n DESC"
        ).fetchall()
    if not rows:
        print("\nNo orphaned publish claims.")
        return
    total = sum(r["n"] for r in rows)
    print(f"\n{total} publish claim(s) across {len(rows)} project(s) have no asset GUID behind them.")
    print("Those repos render as Published while nothing points at a catalog entry.")
    for r in rows[:10]:
        print(f"    orphan  {r['slug']:32} {r['n']}")
    if len(rows) > 10:
        print(f"    ... and {len(rows) - 10} more")
    if not apply:
        print("    Dry run — re-run with --apply to clear these too.")
        return
    with registry._conn() as conn:
        deleted = conn.execute(
            "DELETE FROM project_published_annotation_types WHERE project_slug IN ("
            "SELECT slug FROM projects WHERE coalesce(egeria_asset_guid, '') = '')"
        ).rowcount
    print(f"    Cleared {deleted} orphaned publish claim(s). Those repos now read as "
          "un-published, which is the truth.")


def _resolves(lookup, guid: str) -> bool | None:
    """True / False / None for "could not determine".

    `lookup` is a callable taking a GUID. It is passed in rather than picked
    here because Projects and Collections need their OWN clients --
    ProjectManager.get_project_by_guid and
    CollectionManager.get_collection_by_guid. An earlier version of this
    function called AssetMaker.get_element_by_guid, which does not exist: every
    lookup raised AttributeError, every result became "could not determine",
    and the caller -- which collected only definite-False -- printed "all
    resolve. Nothing to clear." A sweep that reports confidence it does not
    have is worse than the stale GUIDs it was meant to find.

    Never collapse None into False: an unreachable Egeria must not read as
    everything being stale.
    """
    try:
        found = lookup(guid)
    except Exception as exc:
        name = type(exc).__name__
        if "NotFound" in name or "404" in str(exc):
            return False
        # AttributeError, auth failures, transport errors -- all genuinely
        # unknown, and all reported rather than silently dropped.
        return None
    if isinstance(found, str):
        return "No elements" not in found and bool(found.strip())
    return bool(found)


def _sweep_investigations(registry, maker, *, apply: bool) -> None:
    """Investigation -> Egeria Project, and each WorkingSet -> Collection.

    Reported and cleared separately from the asset sweep because they fail
    differently: a dangling asset GUID makes a badge lie, while a dangling
    Project GUID makes promote() fail outright against a Project nothing
    resolves.
    """
    with registry._conn() as conn:
        invs = conn.execute(
            "SELECT slug, egeria_project_guid FROM investigations "
            "WHERE egeria_project_guid IS NOT NULL AND egeria_project_guid <> ''"
        ).fetchall()
        sets = conn.execute(
            "SELECT slug, egeria_collection_guid FROM working_sets "
            "WHERE egeria_collection_guid IS NOT NULL AND egeria_collection_guid <> ''"
        ).fetchall()
    if not invs and not sets:
        print("\nNo investigation or working-set GUIDs cached. Nothing further to sweep.")
        return

    print(f"\n{len(invs)} investigation(s) and {len(sets)} working set(s) carry a cached GUID.")
    try:
        from resource_explorer.config import get_config
        from pyegeria import CollectionManager, ProjectManager

        cfg = get_config().egeria
        pm = ProjectManager(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
        cm = CollectionManager(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
        pm.create_egeria_bearer_token()
        cm.create_egeria_bearer_token()
    except Exception as exc:
        print(f"    Could not open Project/Collection clients ({type(exc).__name__}: {exc}).")
        print("    Skipping — unreachable is not the same as stale.")
        return

    stale_inv, stale_set, unknown = [], [], []
    for r in invs:
        verdict = _resolves(pm.get_project_by_guid, r["egeria_project_guid"])
        if verdict is False:
            stale_inv.append((r["slug"], r["egeria_project_guid"]))
        elif verdict is None:
            unknown.append(("investigation", r["slug"], r["egeria_project_guid"]))
    for r in sets:
        verdict = _resolves(cm.get_collection_by_guid, r["egeria_collection_guid"])
        if verdict is False:
            stale_set.append((r["slug"], r["egeria_collection_guid"]))
        elif verdict is None:
            unknown.append(("working set", r["slug"], r["egeria_collection_guid"]))

    for slug, guid in stale_inv:
        print(f"    stale investigation  {slug:28} {guid}")
    for slug, guid in stale_set:
        print(f"    stale working set    {slug:28} {guid}")
    # Reported, never dropped: silently swallowing these is what made an
    # entirely broken lookup print "all resolve".
    for kind, slug, guid in unknown:
        print(f"    ? {kind:18} {slug:28} {guid}  (could not determine — not cleared)")

    if not stale_inv and not stale_set:
        print(f"    Nothing stale ({len(unknown)} undetermined)." if unknown
              else "    All resolve. Nothing to clear.")
        return
    if not apply:
        print("    Dry run — re-run with --apply to clear these too.")
        return
    with registry._conn() as conn:
        for slug, _ in stale_inv:
            conn.execute(
                "UPDATE investigations SET egeria_project_guid = '', "
                "egeria_project_status = 'local' WHERE slug = ?", (slug,))
        for slug, _ in stale_set:
            conn.execute(
                "UPDATE working_sets SET egeria_collection_guid = '' WHERE slug = ?", (slug,))
    print(f"    Cleared {len(stale_inv)} investigation and {len(stale_set)} working-set GUID(s). "
          "Those investigations read as local-only again — promote to rebuild them.")


if __name__ == "__main__":
    sys.exit(main())
