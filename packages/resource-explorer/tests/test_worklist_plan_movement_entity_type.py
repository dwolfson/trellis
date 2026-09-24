"""`reportPlanMovement` (worklist.js) calls `getAnalysisTrend(slug, analysis)`
with no entity type, inside a `catch (_) { return null }` — for a
database/filesystem work list, every one of those calls would fail (the
route it hits, `/api/projects/{slug}/analyses/{id}/trend`, is repo-only and
has no entity_type parameter or non-repo backend equivalent), and the
generic catch cannot tell that apart from "checked, this measurement is
unreadable". The plan-movement callout would then simply never appear for a
non-repo work list — a quiet undercount of the "would repeat an unchanged
measurement" heuristic, not a loud one.

`getAnalysisTrend` still has no non-repo support after this session's Tier 1
batch (it wasn't in that batch's scope either) — a real dependency, not
something this fix builds. The minimal safe fix: skip the doomed requests
entirely for a non-repo work list and say so honestly, the same shape as
this session's curate.js/understanding.js fixes for other repo-only panes.

Pinned at the source level (this codebase's established technique for JS
with no test runner wired in).
"""
from __future__ import annotations

from pathlib import Path

WORKLIST_JS = (Path(__file__).resolve().parents[1] / "resource_explorer" / "web"
               / "static" / "next" / "worklist.js")


def _fn(src: str, name: str) -> str:
    marker = f"function {name}("
    start = src.index(marker)
    brace = src.index("{", start)
    depth = 1
    i = brace + 1
    while depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start:i]


def test_report_plan_movement_checks_entity_type_before_probing_trend():
    src = WORKLIST_JS.read_text()
    fn = _fn(src, "reportPlanMovement")
    assert "entity_type" in fn or "entityType" in fn, (
        "reportPlanMovement must know the work list's entity type before "
        "deciding whether getAnalysisTrend can answer anything for it")
    gate_pos = fn.index("entityType")
    probe_pos = fn.index("getAnalysisTrend(")
    assert gate_pos < probe_pos, (
        "the entity-type gate must run BEFORE the getAnalysisTrend probes, "
        "not after — otherwise every non-repo pair still fires a doomed "
        "request that lands in the generic catch block")


def test_non_repo_work_lists_skip_the_doomed_probes_and_say_why():
    src = WORKLIST_JS.read_text()
    fn = _fn(src, "reportPlanMovement")
    gate_start = fn.index("if (entityType !== 'repo')")
    gate_block = fn[gate_start:fn.index("getAnalysisTrend(")]
    assert "return;" in gate_block, (
        "the non-repo branch must return before reaching the repo-only "
        "getAnalysisTrend probes")
    assert "isn't tracked yet" in gate_block or "isn&#39;t tracked yet" in gate_block, (
        "must say the heuristic isn't available for this type, not just "
        "silently render nothing (the pre-fix behavior for a non-repo work "
        "list, since every probe would fail into the generic catch)")
