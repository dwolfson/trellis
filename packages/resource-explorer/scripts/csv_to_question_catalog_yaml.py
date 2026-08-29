"""
Generate resource_explorer/configdata/question_catalog.yaml from the same
Scouting questions CSV that scripts/csv_to_dr_egeria_questions.py consumes
(docs/dr-egeria/resource_questions.csv) — the CSV stays the single source
of truth for both outputs (Dr.Egeria markdown for Egeria itself, this YAML
for RE's own runtime "Questions" checklist).

Why a separate script rather than folding this into
csv_to_dr_egeria_questions.py: that script's whole job is producing
Dr.Egeria command blocks — this one produces a config file consumed by
Python at runtime (question_catalog_reader.py, matching
analysis_catalog_reader.py's loading convention). Different output,
different consumer, kept separate on purpose.

Parses the CSV's free-text "Answering Analysis" column into a light,
queryable structure (kind + analysis_ids + the original note text) rather
than requiring a second, redundant structured column in the CSV — the free
text already follows a consistent convention (GAP:/PARTIAL:/MIXED:/"N/A —"
prefixes, established when that column was authored) that a human keeps
writing naturally; this script just recognizes it.

Usage:
    uv run --package resource-explorer \\
        python packages/resource-explorer/scripts/csv_to_question_catalog_yaml.py \\
        docs/dr-egeria/resource_questions.csv \\
        [--output resource_explorer/configdata/question_catalog.yaml]
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml

_ANALYSIS_CATALOG_PATH = (
    Path(__file__).parent.parent / "resource_explorer" / "configdata" / "analysis_catalog.yaml"
)


def _load_known_analysis_ids() -> list[str]:
    """Valid repo analysis ids, read live from configdata/analysis_catalog.yaml.

    This was a hand-synced literal of 15 ids until 2026-08-28, when the real
    catalog had 29. The 14 it had never been re-synced with — `cve_scan`,
    `foss_scorecard`, `chaoss_metrics`, `cii_badge`, `community_support`,
    `interface_surface` among them — were unrecognizable to `_parse_answering`,
    so a CSV row naming one was silently emptied of its `analysis_ids` and
    tagged `kind: unknown`. A question could not be wired to a real analysis
    that the generator did not know existed, and nothing said so.

    Read live for the same reason `_load_known_checks` below is: a stale copy
    drops refs silently, where reading the real file fails loudly if it moves.
    Still no import dependency on the resource_explorer package — this parses
    the YAML directly.
    """
    if not _ANALYSIS_CATALOG_PATH.exists():
        raise FileNotFoundError(
            f"analysis catalog not found at {_ANALYSIS_CATALOG_PATH}; the "
            f"question catalog cannot be generated without it."
        )
    cat = yaml.safe_load(_ANALYSIS_CATALOG_PATH.read_text()) or {}
    # `action: publish` entries are excluded. They write to Egeria and produce
    # no findings, so naming one as answering a question can only ever yield a
    # permanent gap asserting a result that will never exist. `egeria_publish`
    # reached the compile exactly this way: "Does it fit into our governance
    # frameworks?" mentions it in PROSE — "plus Curate zone/catalog membership
    # (egeria_publish)" — and this extraction matches any known id anywhere in
    # the note, so an explanatory aside became a dispatch target.
    #
    # `profile` and `ingest` actions stay: they refresh real stored results.
    # Only `publish` is write-only.
    return [a["id"] for a in (cat.get("repo_analyses") or [])
            if a.get("id") and a.get("action") != "publish"]


KNOWN_ANALYSIS_IDS = _load_known_analysis_ids()


# Purpose vocabulary — the controlled kinds from
# docs/investigation-framing-design.md §2. Mirrors Egeria's ProjectCharter
# `purposes`, which is a valid metadata set: controlled so dispatch can key on
# it, extensible without a rebuild. Extend here when the charter vocabulary
# does.
KNOWN_PURPOSES = [
    "Explore",
    "Select",
    "Assess",
    "Maintain",
    "Share",
    "Learn",
    "Certify",
    "Remediate",
    "Attest",
    "Deploy",
]

# Columns that are NOT perspectives. Perspectives are identified by
# elimination, so anything missing here silently becomes a phantom Perspective
# on every row — keep in sync with csv_to_dr_egeria_questions.py's
# OPTIONAL_LEAD_COLUMNS, which does the same by-elimination trick.
NON_PERSPECTIVE_COLUMNS = (
    "Question", "Funnel Stage", "Why is this important?", "Rationale/Source",
    "Answering Analysis", "Answering Mechanism", "Purposes",
)

_CHECK_REGISTRY_PATH = (
    Path(__file__).parent.parent / "resource_explorer" / "configdata" / "check_registry.yaml"
)


def _load_known_checks() -> set[str]:
    """Valid `analysis_id:check_name` refs, from configdata/check_registry.yaml.

    Read live (unlike KNOWN_ANALYSIS_IDS above, which is a hand-synced literal)
    because the check vocabulary is ~28 entries and still moving — a stale copy
    here would silently drop refs rather than fail. Still no import dependency
    on the resource_explorer package: this reads the YAML directly."""
    if not _CHECK_REGISTRY_PATH.exists():
        return set()
    reg = yaml.safe_load(_CHECK_REGISTRY_PATH.read_text()) or {}
    return {
        f"{analysis_id}:{check}"
        for analysis_id, spec in (reg.get("analyses") or {}).items()
        for check in (spec.get("checks") or [])
    }


_CHECKS_SUFFIX_RE = re.compile(r"\s*\[checks:[^\]]*\]")


def _strip_checks_suffix(note: str) -> str:
    """Remove the `[checks: ...]` block before prose classification.

    The suffix is structured metadata bolted onto a free-text column. Leaving
    it in breaks `kind` detection for every row whose note is exactly an
    analysis id (that test is a whole-string equality), silently downgrading
    e.g. "license_classification" from kind=analysis to kind=unknown."""
    return _CHECKS_SUFFIX_RE.sub("", note).strip()


def _parse_checks(note: str, known: set[str]) -> tuple[list[str], list[str]]:
    """Extract `analysis_id:check_name` refs from the CSV note.

    Returns (valid_refs, unknown_refs). Unknown refs are returned rather than
    dropped so the caller can fail loudly — a typo'd check name that silently
    vanished would look identical to a question nobody has tagged yet, which is
    the failure mode this whole join exists to remove."""
    found = re.findall(r"\b([a-z_]+:[a-z0-9_\-]+)\b", note)
    valid = [r for r in dict.fromkeys(found) if r in known]
    unknown = [r for r in dict.fromkeys(found) if r not in known]
    return valid, unknown


def _parse_purposes(raw: str) -> list[str]:
    """Parse the semicolon-separated Purposes column.

    Purposes get one shared column rather than a column each (the shape the
    Perspective columns use) precisely because of the by-elimination problem
    above: ten more columns would be ten more chances for a typo'd header to
    become a phantom Perspective. One column, validated, fails loudly instead."""
    values = [v.strip() for v in (raw or "").split(";") if v.strip()]
    unknown = [v for v in values if v not in KNOWN_PURPOSES]
    if unknown:
        raise ValueError(
            f"unknown Purpose(s) {unknown}; valid values are {KNOWN_PURPOSES}. "
            f"Fix the CSV, or add the purpose to KNOWN_PURPOSES if the "
            f"ProjectCharter vocabulary genuinely gained one."
        )
    return list(dict.fromkeys(values))


_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _is_pure_analysis_list(prose: str) -> bool:
    """Whether the note names only known analyses, joined by `+`.

    A single bare id was the only shape recognized as `kind: analysis` until
    2026-08-28. A question answered by two analyses together — "repository_health
    + chaoss_metrics" — fell through to `unknown`, which reads as "nobody has
    classified this" rather than "answered, by two things". Eight rows sat in
    that state.

    A trailing `(parenthetical)` gloss is stripped before the test, so an author
    can say which part each analysis contributes without losing the
    classification. Anything else in the prose — a dash, a "RAG read?", a
    GAP/PARTIAL/MIXED prefix (already handled above) — leaves this False, so
    genuinely mixed notes still surface as such rather than being flattened
    into a confident `analysis`.
    """
    stripped = _PARENTHETICAL_RE.sub("", prose).strip()
    if not stripped:
        return False
    parts = [p.strip() for p in stripped.split("+")]
    return all(p in KNOWN_ANALYSIS_IDS for p in parts if p)


def _parse_answering(note: str, known_checks: set[str] | None = None) -> dict:
    note = (note or "").strip()
    prose = _strip_checks_suffix(note)
    upper = prose.upper()
    if upper.startswith("GAP:"):
        kind = "gap"
    elif upper.startswith("PARTIAL:"):
        kind = "partial"
    elif upper.startswith("MIXED:"):
        kind = "mixed"
    elif "human-supplied" in prose.lower():
        kind = "human"
    elif "trend chart" in prose.lower():
        kind = "chart"
    elif prose.upper().startswith("N/A"):
        kind = "direct"
    elif _is_pure_analysis_list(prose):
        kind = "analysis"
    else:
        # Free text that doesn't match any known convention — surfaced as
        # "unknown" rather than silently mis-tagged; a real gap in the CSV
        # authoring convention, not something to guess past.
        kind = "unknown"

    analysis_ids = [
        aid for aid in KNOWN_ANALYSIS_IDS
        if re.search(rf"\b{re.escape(aid)}\b", note)
    ]

    checks, unknown = _parse_checks(note, known_checks or set())
    if unknown:
        raise ValueError(
            f"unknown check ref(s) {unknown} in Answering Analysis text: {note!r}\n"
            f"Valid refs are declared in {_CHECK_REGISTRY_PATH.name} "
            f"(analysis_id:check_name). Fix the CSV or add the check to the registry."
        )

    # A check ref implies its analysis, so authors don't have to write both.
    for ref in checks:
        aid = ref.split(":", 1)[0]
        if aid not in analysis_ids:
            analysis_ids.append(aid)

    return {"kind": kind, "analysis_ids": analysis_ids, "checks": checks, "note": note}


def generate(rows: list[dict]) -> str:
    known_checks = _load_known_checks()
    entries = []
    for row in rows:
        question = (row.get("Question") or "").strip()
        if not question:
            continue
        perspective_cols = [c for c in row if c not in NON_PERSPECTIVE_COLUMNS]
        perspectives = [c for c in perspective_cols if (row.get(c) or "").strip()]

        entries.append({
            "question": question,
            "stage": (row.get("Funnel Stage") or "").strip(),
            "perspectives": perspectives,
            "purposes": _parse_purposes(row.get("Purposes", "")),
            "answering": _parse_answering(row.get("Answering Analysis", ""), known_checks),
            "answering_mechanism": (row.get("Answering Mechanism") or "").strip(),
        })

    header = (
        "# Question checklist catalog — generated by\n"
        "# scripts/csv_to_question_catalog_yaml.py from\n"
        "# docs/dr-egeria/resource_questions.csv (the source of truth — edit that\n"
        "# CSV, then regenerate this file, don't hand-edit it directly). Backs the\n"
        "# Scouting \"Questions\" checklist tab (question_catalog_reader.py).\n"
        "#\n"
        "# Each entry:\n"
        "#   question      - display text; matches the Egeria GlossaryTerm Display\n"
        "#                   Name exactly (case+punctuation-sensitive) since it's\n"
        "#                   also the join key back to Egeria's own Question\n"
        "#                   elements, if/when RE ever queries them live.\n"
        "#   stage         - single Funnel Stage this question belongs to (collapsed\n"
        "#                   from the earlier separate Asked At/Answered At columns\n"
        "#                   2026-08-14 — see docs/survey-question-context-plan.md).\n"
        "#                   May be a slash-combined value (e.g. \"Analysis/Enrichment\")\n"
        "#                   signaling an Analysis-first, Enrichment-fallback pattern\n"
        "#                   (see docs/confidence-gated-validation-plan.md) — treated\n"
        "#                   as a literal string match, not split, until that plan is\n"
        "#                   built.\n"
        "#   perspectives  - Perspective names this question is linked to.\n"
        "#   purposes      - Purpose kinds this question serves (added 2026-08-24).\n"
        "#                   Purpose is the PRIMARY dispatch axis and Perspective the\n"
        "#                   secondary one: Perspective was measured and cannot\n"
        "#                   discriminate (no perspective reaches an analysis another\n"
        "#                   doesn't also reach). Purpose ORDERS what runs by default;\n"
        "#                   it never excludes. See docs/investigation-framing-design.md.\n"
        "#   answering:\n"
        "#     kind        - \"analysis\" | \"direct\" | \"registry\" | \"human\" |\n"
        "#                   \"chart\" | \"gap\" | \"partial\" | \"mixed\" | \"unknown\" —\n"
        "#                   how (or whether) RE can answer this today.\n"
        "#     analysis_ids - analysis_catalog.yaml repo_analyses ids that answer\n"
        "#                   (fully or partially) this question; may be empty.\n"
        "#     checks       - finer `analysis_id:check_name` refs, validated against\n"
        "#                   configdata/check_registry.yaml. Added 2026-08-24 because\n"
        "#                   analysis-level joins are too coarse to dispatch on (one\n"
        "#                   analysis, repo_conventions, answers 7 of the 16\n"
        "#                   analysis-answerable questions). Empty means \"no check\n"
        "#                   refs authored yet\" — fall back to analysis_ids, do not\n"
        "#                   read it as \"no checks apply\". A check ref implies its\n"
        "#                   analysis, which is added to analysis_ids automatically.\n"
        "#     note        - the CSV's \"Answering Analysis\" column, verbatim —\n"
        "#                   human-readable detail (candidate tooling for gaps,\n"
        "#                   which direct field/table, etc.).\n"
        "#   answering_mechanism - the CSV's \"Answering Mechanism\" column, verbatim —\n"
        "#                   which kind of engine answers this (Git Statistics /\n"
        "#                   Code Analysis / RAG Queries / Agent-Based Analysis /\n"
        "#                   Egeria Queries / Local Registry Query / Human-Supplied /\n"
        "#                   Direct Field / Trend Chart / Gap / Automate Change\n"
        "#                   Detection, or a \"+\"-joined combination) — orthogonal to\n"
        "#                   stage and to answering.kind, added 2026-08-14.\n\n"
    )
    body = yaml.safe_dump({"repo_questions": entries}, sort_keys=False, allow_unicode=True, width=100)
    return header + body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("csv_path", type=Path, help="Source CSV (see module docstring)")
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).parent.parent / "resource_explorer" / "configdata" / "question_catalog.yaml",
        help="Output YAML path (default: resource_explorer/configdata/question_catalog.yaml)",
    )
    args = parser.parse_args()

    if not args.csv_path.exists():
        parser.error(f"CSV not found: {args.csv_path}")

    with open(args.csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        parser.error(f"CSV has no data rows: {args.csv_path}")

    content = generate(rows)
    args.output.write_text(content)
    n_questions = sum(1 for r in rows if (r.get("Question") or "").strip())
    print(f"Wrote {args.output} ({n_questions} questions from {len(rows)} CSV rows)")


if __name__ == "__main__":
    main()
