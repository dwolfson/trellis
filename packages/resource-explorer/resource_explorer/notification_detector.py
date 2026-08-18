"""Change detection for Automate subscriptions (Discovery-tier Part 4).

Generic across every analysis kind that persists through the shared
project_analysis_findings/project_analysis_metrics tables (upsert_finding/
upsert_metric in registry.py) — no per-analysis-kind code here. Compares
the latest two survey-run batches for one (entity_slug, analysis_id) and
reports whether anything changed, plus a short human-readable diff summary
for the RFA that gets written when it has.

Deliberately reads existing history rather than needing a before/after
snapshot passed in — by the time a scheduled run completes, the new batch
is already the last row in history, so "did this change" is just "do the
last two batches differ," which query_findings_history_raw/
query_metrics_history already give us for free.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChangeResult:
    changed: bool
    summary: str = ""


def _group_by_surveyed_at(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """rows already ordered by surveyed_at ASC (both history readers
    guarantee this) — group into (surveyed_at, [rows]) batches, preserving
    order, without assuming how many distinct timestamps exist."""
    batches: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in rows:
        ts = r["surveyed_at"]
        if ts not in batches:
            batches[ts] = []
            order.append(ts)
        batches[ts].append(r)
    return [(ts, batches[ts]) for ts in order]


def _detect_findings_change(registry, slug: str, analysis_id: str) -> ChangeResult | None:
    """None (not just False) means "no findings history to compare at
    all" for this kind — the caller falls back to trying metrics instead,
    since not every analysis kind is findings-shaped."""
    history = registry.query_findings_history_raw(slug, analysis_id)
    if not history:
        return None
    batches = _group_by_surveyed_at(history)
    if len(batches) < 2:
        return ChangeResult(changed=False)

    _, prev_rows = batches[-2]
    _, latest_rows = batches[-1]
    prev = {r["check_name"]: r["label"] for r in prev_rows}
    latest = {r["check_name"]: r["label"] for r in latest_rows}

    diffs = []
    for check_name in sorted(set(prev) | set(latest)):
        old, new = prev.get(check_name), latest.get(check_name)
        if old != new:
            diffs.append(f"{check_name}: {old!r} -> {new!r}")

    if not diffs:
        return ChangeResult(changed=False)
    return ChangeResult(changed=True, summary="; ".join(diffs))


def _detect_metrics_change(registry, slug: str, analysis_id: str) -> ChangeResult:
    """Metrics-shaped kinds (data_file_profiling, api_structure, ...) have
    no single query_metrics_history_raw — query_metrics_history() is
    per-metric-name, so we discover the metric names from the latest
    snapshot first, then check each one's own history."""
    latest = registry.query_metrics(slug, analysis_id)
    metric_names = [k for k in latest.keys() if k not in ("surveyed_at", "detail")]
    if not metric_names:
        return ChangeResult(changed=False)

    diffs = []
    for name in sorted(metric_names):
        history = registry.query_metrics_history(slug, analysis_id, name)
        if len(history) < 2:
            continue
        old, new = history[-2]["metric_value"], history[-1]["metric_value"]
        if old != new:
            diffs.append(f"{name}: {old} -> {new}")

    if not diffs:
        return ChangeResult(changed=False)
    return ChangeResult(changed=True, summary="; ".join(diffs))


def detect_change(registry, slug: str, analysis_id: str) -> ChangeResult:
    """Did (slug, analysis_id)'s most recent run differ from the one
    before it? Tries findings first (the common case), falls back to
    metrics for kinds with no findings history at all. A kind with fewer
    than 2 runs of either shape is never "changed" — there's nothing to
    compare against yet."""
    findings_result = _detect_findings_change(registry, slug, analysis_id)
    if findings_result is not None:
        return findings_result
    return _detect_metrics_change(registry, slug, analysis_id)
