"""Step 4 of docs/architecture-recovery-scope-tombstoning.md — withdraw the
orphaned scopes that no ordinary run can ever reach.

**Why a script and not a survey step.** R2 forbids a step withdrawing scopes it
is not recorded as having written, and every pre-`run_label` row belongs to no
step. Those rows are therefore unwithdrawable by any amount of re-surveying —
measured 2026-08-30, `egeria_git` carries 165 of them and 27 of its 35
deployment components are dead.

**This is weaker evidence than a withdrawal from a real run**, and it says so in
every row it writes. A run *observes* that it no longer proposes a scope; this
*asserts* it, from a human deciding that the most recent complete picture is the
current one. A backfill writing rows indistinguishable from earned ones would
launder an assertion into an observation, so each row carries
`source: backfill` and the date.

**The live set.** Component rows are grouped by `run_label`, and each group's
most recent run contributes its scopes:

* if any LABELLED group exists, unlabelled rows are treated as history — they
  are the same two steps before attribution existed, and keeping their last run
  alive would defeat the whole exercise;
* if no labelled group exists, the latest unlabelled run IS the current picture.

Dry-run by default. `--write` is required to change anything.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import sys

from resource_explorer.registry import WITHDRAWN_LABEL, ProjectRegistry
from resource_explorer.surveyors.arch_recovery.persist import KIND, WITHDRAWN_CHECK


def live_and_orphaned(registry, slug: str) -> tuple[set[str], set[str], dict]:
    """`(live, orphaned, per-group detail)` for one resource."""
    groups: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set))
    for row in registry.query_findings_history_raw(slug, KIND):
        if row.get("check_name") != "component":
            continue
        detail = row.get("detail_json") or "{}"
        if isinstance(detail, str):
            try:
                detail = json.loads(detail or "{}")
            except ValueError:
                detail = {}
        label = detail.get("run_label") or "(unlabelled)"
        groups[label][row.get("surveyed_at") or ""].add(row.get("scope_locator") or "")

    if not groups:
        return set(), set(), {}
    labelled = [g for g in groups if g != "(unlabelled)"]
    contributing = labelled or list(groups)

    live: set[str] = set()
    report: dict = {}
    for label in sorted(groups):
        latest = max(groups[label])
        report[label] = {"runs": len(groups[label]), "latest": latest,
                         "scopes": len(groups[label][latest]),
                         "counts_as_live": label in contributing}
        if label in contributing:
            live |= groups[label][latest]

    everything = {s for runs in groups.values() for scopes in runs.values() for s in scopes}
    return live, everything - live, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slugs", nargs="+", help="resource slugs to sweep")
    ap.add_argument("--write", action="store_true",
                    help="actually write withdrawals (default: dry run)")
    args = ap.parse_args()

    registry = ProjectRegistry()
    stamp = datetime.datetime.now(datetime.UTC).isoformat()
    total = 0
    for slug in args.slugs:
        live, orphaned, report = live_and_orphaned(registry, slug)
        print(f"\n=== {slug}")
        for label, info in report.items():
            mark = "live" if info["counts_as_live"] else "HISTORY"
            print(f"   {label:14} runs={info['runs']:2} latest={info['latest'][:19]} "
                  f"scopes={info['scopes']:5}  -> {mark}")
        print(f"   live={len(live)}  orphaned={len(orphaned)}")
        for scope in sorted(orphaned)[:10]:
            print(f"      would withdraw: {scope[:100]}")
        if len(orphaned) > 10:
            print(f"      ... and {len(orphaned) - 10} more")
        total += len(orphaned)

        if not args.write or not orphaned:
            continue
        for scope in sorted(orphaned):
            registry.upsert_finding(
                slug, KIND,
                [{
                    "check_name": WITHDRAWN_CHECK,
                    "label": WITHDRAWN_LABEL,
                    "summary": "withdrawn by backfill — no current run proposes this scope",
                    "confidence": 100,
                    # `source` is what keeps this distinguishable from a
                    # withdrawal a run EARNED. A run observes; this asserts.
                    "detail": {"cause": "unclaimed", "source": "backfill",
                               "backfilled_at": stamp,
                               "note": "asserted by a one-off sweep, not observed by a run"},
                }],
                surveyed_at=stamp, scope_locator=scope,
            )
        print(f"   WROTE {len(orphaned)} withdrawal(s) at {stamp}")

    print(f"\ntotal orphaned across {len(args.slugs)} resource(s): {total}")
    if not args.write:
        print("dry run — nothing written. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
