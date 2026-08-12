"""
Generate a Dr.Egeria markdown "questions" document from a CSV, using the
Question/Perspective/Intent authoring pattern established in
docs/dr-egeria/foundations.md and docs/dr-egeria/scouting-questions.md.

Why this exists: hand-converting a CSV of questions x perspectives into raw
Dr.Egeria command blocks is slow and error-prone (wrong attribute names
silently produce "Not Found" validation errors, not loud failures) — this
was proven real while building the Scouting questions file by hand. This
script encodes the field-name mapping once (discovered empirically against
a real Dr.Egeria instance, not guessed) so every future stage's questions
file is generated, not hand-typed.

CSV schema (columns, in order):
    Question           - required; becomes the Question's Display Name
    Asked At            - required; Funnel Stage term this question is
                          naturally raised at (usually "Scouting")
    Answered At          - required; Funnel Stage term whose data can
                          actually answer it (may differ from Asked At —
                          e.g. asked at Scouting, answered at Assessment)
    Why is this important? - optional; becomes the term's Summary
    Rationale/Source    - optional; becomes the term's Description (falls
                          back to the question text itself if blank)
    <perspective columns...> - one column per Perspective (must match a
                          Display Name already created in foundations.md,
                          e.g. "App/AI Builder"), any non-empty cell
                          (conventionally "X") links that perspective to
                          the question via Link Perspective to Question.
                          Every column after Rationale/Source is treated
                          as a perspective column — order doesn't matter.

Model generated per row (matches foundations.md's documented pattern):
    Create Glossary Term (Glossary Name=<--questions-glossary>, Display
      Name=<question>, Description=<Rationale/Source>, Summary=<Why is
      this important?>, Usage=<derived Asked At / Answered At sentence>,
      classified as Question) -> Classify Term as Question
      -> Link Perspective to Question (one per marked perspective column)
      -> Link Element To Scope / ScopedBy, twice: once with
         Scope Category "Asked At" (Scope Reference=<Asked At>), once with
         Scope Category "Answered At" (Scope Reference=<Answered At>) —
         emitted even when Asked At == Answered At, so every question has
         the same two-relationship shape regardless (uniform, queryable).

Output is a plain Dr.Egeria markdown file — run `foundations.md` first
(creates the shared glossaries/perspectives/stage-terms this file
references by name), then VALIDATE this file before PROCESS, exactly like
every other Dr.Egeria document in this repo.

This is a generator, not a live Egeria client — it does not connect to
Egeria or execute anything. Feed the output through Dr.Egeria's own
validate/process pipeline (the `dr_egeria_run_block` MCP tool, or
whatever CLI/agent has that capability) — never process blind.

Usage:
    uv run --package resource-explorer \\
        python packages/resource-explorer/scripts/csv_to_dr_egeria_questions.py \\
        docs/dr-egeria/scouting-questions.csv \\
        [--output docs/dr-egeria/scouting-questions.md] \\
        [--questions-glossary "User Questions"] \\
        [--stage-glossary "Funnel Stages"]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REQUIRED_COLUMNS = ["Question", "Asked At", "Answered At"]
# "Answering Analysis" is RE-internal roadmap documentation (which
# analysis_catalog.yaml id, if any, actually answers this question today)
# — CSV/human-facing only, deliberately not sent to Egeria. It's excluded
# here so the "everything after Rationale/Source is a perspective column"
# rule in generate() doesn't try to link it as a Perspective.
OPTIONAL_LEAD_COLUMNS = ["Why is this important?", "Rationale/Source", "Answering Analysis"]


def _block(command: str, **fields: str) -> str:
    """One Dr.Egeria command block: '## Command\\n\\n### Label\\nValue\\n\\n...'.
    Fields with empty/whitespace-only values are omitted entirely — an
    empty '### Label\\n\\n' block is not the same as the attribute being
    absent, and every field here is optional except the command name."""
    lines = [f"## {command}", ""]
    for label, value in fields.items():
        value = (value or "").strip()
        if not value:
            continue
        lines.append(f"### {label}")
        lines.append(value)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n\n___\n"


def _question_summary(why: str, rationale: str) -> str:
    """Egeria's Summary is user-facing — only 'Why is this important?'
    (the reason a user would care about this question) goes into it.
    'Rationale/Source' is deliberately excluded: it now goes into the
    term's Description instead (see _question_description), which is a
    better semantic fit and confirmed live to be a real, recognized
    Create Glossary Term attribute (not guessed). `rationale` is kept as
    a parameter (not dropped from the signature) so a future caller can
    still opt back in without re-deriving this decision."""
    return (why or "").strip()


def _question_description(question: str, rationale: str) -> str:
    """Description defaulted to a bare repeat of the question text before
    (wasted attribute). Rationale/Source — which RE table/surveyor would
    answer this, candidate tooling for real gaps — is genuine elaboration
    on the question, so it's a better fit for Description than Summary.
    Falls back to the question text itself when Rationale/Source is
    blank, so Description is never empty."""
    rationale = (rationale or "").strip()
    return rationale if rationale else question


def _question_usage(asked_at: str, answered_at: str) -> str:
    """Confirmed live (2026-08-12 probe) that Create Glossary Term
    recognizes a real 'Usage' attribute — put to use here as a
    human-readable restatement of the two ScopedBy relationships this
    question gets (Asked At / Answered At), so someone browsing the term
    directly in Egeria's glossary doesn't have to traverse relationships
    to see when it's raised vs. when it's actually answerable."""
    asked_at = (asked_at or "").strip()
    answered_at = (answered_at or "").strip()
    if not asked_at:
        return ""
    if answered_at and answered_at != asked_at:
        return (
            f"Typically asked during {asked_at}; best answered using data "
            f"available by the {answered_at} stage."
        )
    return f"Typically asked and answerable during {asked_at}."


def generate(
    rows: list[dict],
    *,
    questions_glossary: str,
    title: str,
) -> str:
    perspective_columns = [
        c for c in rows[0].keys()
        if c not in REQUIRED_COLUMNS and c not in OPTIONAL_LEAD_COLUMNS
    ] if rows else []

    out: list[str] = [
        f"# {title}",
        "",
        "> Generated by scripts/csv_to_dr_egeria_questions.py — do not hand-edit,",
        "> regenerate from the source CSV instead. Run docs/dr-egeria/foundations.md",
        "> first (creates the shared glossaries/perspectives/stage-terms this file",
        "> references by name). Run with VALIDATE first, then PROCESS.",
        "",
        "---",
        "",
        "# Questions",
        "",
    ]

    skipped: list[str] = []
    for row in rows:
        question = (row.get("Question") or "").strip()
        if not question:
            continue
        asked_at = (row.get("Asked At") or "").strip()
        answered_at = (row.get("Answered At") or "").strip()
        if not asked_at:
            skipped.append(f"{question!r} — missing 'Asked At', skipped")
            continue

        rationale = row.get("Rationale/Source", "")
        summary = _question_summary(row.get("Why is this important?", ""), rationale)
        description = _question_description(question, rationale)
        usage = _question_usage(asked_at, answered_at)

        out.append(_block(
            "Create Glossary Term",
            **{
                "Glossary Name": questions_glossary,
                "Display Name": question,
                "Description": description,
                "Summary": summary,
                "Usage": usage,
            },
        ))
        out.append(_block("Classify Term as Question", **{"Term Name": question}))

        for persp_col in perspective_columns:
            marked = (row.get(persp_col) or "").strip()
            if marked:
                out.append(_block(
                    "Link Perspective to Question",
                    **{"Perspective Name": persp_col, "Question Name": question},
                ))

        out.append(_block(
            "Link Element To Scope",
            **{
                "Target Element": question,
                "Scope Reference": asked_at,
                "Scope Category": "Asked At",
            },
        ))
        if answered_at:
            out.append(_block(
                "Link Element To Scope",
                **{
                    "Target Element": question,
                    "Scope Reference": answered_at,
                    "Scope Category": "Answered At",
                },
            ))
        else:
            skipped.append(f"{question!r} — no 'Answered At', only Asked-At ScopedBy emitted")

    if skipped:
        print("Warnings:", file=sys.stderr)
        for s in skipped:
            print(f"  - {s}", file=sys.stderr)

    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv_path", type=Path, help="Source CSV (see module docstring for schema)")
    parser.add_argument("--output", type=Path, default=None, help="Output .md path (default: <csv stem>.md next to the CSV)")
    parser.add_argument("--questions-glossary", default="User Questions", help='Glossary Name questions are created in (default: "User Questions")')
    parser.add_argument("--title", default=None, help="H1 title for the generated file (default: derived from the CSV filename)")
    args = parser.parse_args()

    if not args.csv_path.exists():
        parser.error(f"CSV not found: {args.csv_path}")

    with open(args.csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        parser.error(f"CSV has no data rows: {args.csv_path}")

    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        parser.error(f"CSV missing required column(s): {missing}")

    output_path = args.output or args.csv_path.with_suffix(".md")
    title = args.title or f"{args.csv_path.stem.replace('-', ' ').title()} — Generated"

    content = generate(rows, questions_glossary=args.questions_glossary, title=title)
    output_path.write_text(content)
    n_questions = sum(1 for r in rows if (r.get("Question") or "").strip())
    print(f"Wrote {output_path} ({n_questions} questions from {len(rows)} CSV rows)")


if __name__ == "__main__":
    main()
