"""The report record: a named, dated, authored record of what was true
about a list at a moment, with its provenance attached.

REPORT-RECORD-AND-TWO-CALLS C1-C4 (designer, 2026-09-13). A report is
Curate's commit record with no steps, and it shares that table (`kind =
report`). What must be true: both kinds list together under the resource,
newest first, and neither is edited after the fact.

The header sentence is the part that matters -- "32 of 32 dependencies —
nothing capped." or "200 of 1,412 — capped by the request." -- in the
header, never a footnote: a saved artefact outlives the person who knew
about the cap. Under it one provenance line, the one promotion already
composes; a report is its fourth destination. Then the rows, grouped as
the member tree groups them, any group's `truncated` flag surviving.

Markdown and CSV are EXPORTS of the record, carrying the same header
sentence and the same provenance line. The record is the thing; a file
is a view of it -- which is the gap this closes: every provenance line
the project composes so carefully currently lives on the clipboard and
dies on the first paste.
"""
from __future__ import annotations

import csv
import io

from resource_explorer.members import provenance_line, proposed_name


def header_sentence(*, total: int, shown: int, noun: str) -> str:
    """'32 of 32 dependencies — nothing capped.' / '200 of 1,412 dependencies
    — capped by the request.'"""
    # The noun names the SET ("1 of 9 advisories"), so it stays plural.
    if shown >= total:
        return f"{shown:,} of {total:,} {noun} — nothing capped."
    return f"{shown:,} of {total:,} {noun} — capped by the request."


def correction_clause(corrected: dict | None) -> str:
    """When the corrected record was a SELECTION, the correction (the whole
    current list) has a different population, and a reader cannot tell
    whether a row is absent because it was fixed or because it fell out of
    the facet. So the header names what it is not carrying (designer,
    2026-09-14): 'Corrects "High advisories with a fix", whose selection was
    high, fix available; this record is the whole list.' No clause when the
    populations already match -- a sentence explaining that they match is
    noise."""
    if not corrected:
        return ""
    rep = corrected.get("report") or {}
    facet = (rep.get("facet") or "").strip()
    if not facet:
        return ""
    return (f' Corrects "{corrected.get("name", "")}", whose selection was {facet}; '
            f"this record is the whole list.")


def build_report(*, question: str, slug: str, display_name: str, analysis_id: str, metric: str,
                 run_at: str, facet: str, members_payload: dict, selected: list[str] | None = None) -> dict:
    """The record's body, from a members payload as the pane received it.
    `selected` narrows to a picked set; None means the whole list. Rows are
    a snapshot of names with their detail, grouped as the tree groups them;
    a group's `truncated` flag survives into the record."""
    groups_in = members_payload.get("groups") or []
    pick = set(selected) if selected is not None else None
    groups = []
    names: list[str] = []
    for g in groups_in:
        rows = []
        for m in g.get("members") or []:
            if m.get("children_key"):
                continue
            if pick is not None and m.get("name") not in pick:
                continue
            rows.append({"name": m.get("name", ""), "detail": m.get("detail", "") or ""})
            names.append(m.get("name", ""))
        if rows or (pick is None and g.get("truncated")):
            groups.append({"name": g.get("name", ""), "count": int(g.get("count") or len(rows)),
                           "rows": rows, "truncated": bool(g.get("truncated"))})
    total = int(members_payload.get("total") or 0)
    shown = len(names) if pick is None else len(names)
    noun = (metric or members_payload.get("metric") or "members").replace("_", " ")
    capped_total = total if pick is None else len(names)
    return {
        "question": question,
        "resource": slug,
        "display_name": display_name,
        "analysis_id": analysis_id,
        "metric": metric or members_payload.get("metric") or "",
        "run_at": run_at,
        "facet": facet,
        "total": capped_total,
        "shown": shown,
        "noun": noun,
        "header": header_sentence(total=capped_total, shown=shown, noun=noun),
        "provenance": provenance_line(analysis_id=analysis_id, run_at=run_at, total=capped_total,
                                      members=names, facet=facet, metric=metric),
        "groups": groups,
        "source": members_payload.get("source", ""),
        "corrects": "",
    }


def default_name(display_name: str, *, total: int, names: list[str], facet: str, metric: str, written_on: str) -> str:
    """'egeria-python — 32 dependencies, 2026-09-12'. Learn from promotion:
    the proposal is not clever, and a typed name wins until cleared."""
    base = proposed_name(display_name, total=total, members=names, facet=facet, metric=metric)
    return f"{base}, {written_on[:10]}" if written_on else base


def out_of_date(report: dict, current_run_at: str) -> str:
    """The sentence a record carries on itself when its evidence has moved
    and no correcting record exists: 'out of date — cve_scan re-ran on
    09-12. No correcting record has been written yet.' '' when current."""
    if not current_run_at or not report.get("run_at"):
        return ""
    if current_run_at[:19] <= report["run_at"][:19]:
        return ""
    return (f"out of date — {report.get('analysis_id')} re-ran on {current_run_at[5:10]}. "
            f"No correcting record has been written yet.")


def to_markdown(rec: dict) -> str:
    r = rec.get("report") or {}
    lines = [f"# {rec.get('name', '')}", "",
             f"**{r.get('header', '')}**", "",
             f"{r.get('provenance', '')} · a snapshot, not a query", "",
             f"Asked as: *{r.get('question', '')}* · written by {rec.get('author', '')} on {str(rec.get('requested_at', ''))[:10]}", ""]
    for g in r.get("groups") or []:
        lines.append(f"## {g['name']} · {g['count']}")
        for row in g["rows"]:
            lines.append(f"- `{row['name']}`" + (f" — {row['detail']}" if row.get("detail") else ""))
        if g.get("truncated"):
            lines.append(f"- … and more — the first {len(g['rows'])} are shown")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_csv(rec: dict) -> str:
    r = rec.get("report") or {}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["# " + r.get("header", "")])
    w.writerow(["# " + r.get("provenance", "") + " · a snapshot, not a query"])
    w.writerow(["group", "name", "detail", "group_truncated"])
    for g in r.get("groups") or []:
        for row in g["rows"]:
            w.writerow([g["name"], row["name"], row.get("detail", ""), "yes" if g.get("truncated") else ""])
    return buf.getvalue()


def act_line(rec: dict, *, rows: list[str] | None = None, out_of_date_sentence: str = "") -> str:
    """What each act creates points at the record: the provenance line
    promotion composes, plus 'as recorded in "<name>"', and -- when the
    record's evidence has since moved -- the staleness carried into the
    work item rather than a disabled button (REPORT-ACTS §2, §3). `rows`
    narrows to a picked subset of the frozen snapshot; never a re-query."""
    r = rec.get("report") or {}
    names = [row["name"] for g in r.get("groups") or [] for row in g.get("rows") or []]
    if rows is not None:
        keep = set(rows)
        names = [n for n in names if n in keep]
    line = provenance_line(analysis_id=r.get("analysis_id", ""), run_at=r.get("run_at", ""),
                           total=int(r.get("total") or len(names)), members=names,
                           facet=r.get("facet", ""), metric=r.get("metric", ""))
    line += f' · as recorded in "{rec.get("name", "")}"'
    if out_of_date_sentence:
        # "out of date — cve_scan re-ran on 09-12. No correcting record …"
        moved = out_of_date_sentence.split(".")[0].replace("out of date — ", "")
        line += f", whose evidence has since moved — {moved}"
    return line


def citation(rec: dict) -> str:
    """The journal seed: a citation, not a sentence. The person writes the
    thought; the machine supplies only this."""
    return f'Per "{rec.get("name", "")}" ({str(rec.get("requested_at", ""))[:10]}): '
