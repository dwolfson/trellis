"""Check compiler output against the audit's expected rendering rules.

Read-only against the registry (record_compile is stubbed to a no-op so this
never persists a compile row). Recompiles each row from
docs/experiments/audits/2026-09-09-run4-unsupported-claims-vs-packed-text.md's
sample set live, and checks `c.text` / `c.manifest` against the target format
described in the fix brief:

  - the `cve_scan` section leads with a headline stating coverage, not a bare
    fenced JSON dump
  - no fenced ```json block anywhere in the packed text
  - no bare "structure only" mid rung (`- key: (list|mapping)` lines); any
    section whose header says "abridged" carries a `first N of M` marker
  - `repository_health`, where packed, exposes `forks`/`stars` as flat
    `- key: value` bullets, not nested inside a JSON object
  - for direct/human/gap/chart catalog questions, the manifest carries
    `coverage.kind` and the text carries a `Coverage:` line; for
    analysis/mixed/partial questions it does not
  - `manifest["used"] <= manifest["budget"]`, and the compile id is stable
    across two compiles of the same (repo, question)

Run this BEFORE the context_compile.py fix lands to get the baseline — the
known-broken behaviour is expected to show FAILs. Re-run after the fix to
confirm the FAILs above flip to PASS.

Usage (from packages/resource-explorer, per-package convention — `uv run
python`, never `uv sync`):

    uv run python scripts/check_compiler_audit_rows.py
    uv run python scripts/check_compiler_audit_rows.py --sample /path/to/sample_compiled.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_SAMPLE = Path(
    "/private/tmp/claude-501/-Users-dwolfson/0743e0a6-7380-4828-ae6b-5abaf6a0c576"
    "/scratchpad/audit-run4/sample_compiled.json"
)
DEFAULT_AUDIT_MD = DEFAULT_SAMPLE.parent / "audit.md"

BUDGET = 6000

_COVERAGE_KINDS = {"direct", "human", "gap", "chart"}
_NO_COVERAGE_KINDS = {"analysis", "mixed", "partial"}

_FENCED_JSON_RE = re.compile(r"```json")
_OLD_MID_RUNG_LINE_RE = re.compile(r"^- \w+: \((list|mapping)\)$", re.MULTILINE)
_STRUCTURE_ONLY_RE = re.compile(r"structure only")
_FIRST_N_OF_M_RE = re.compile(r"first \d+ of \d+")
_CVE_HEADLINE_RE = re.compile(r"(none in \d+ of \d+|advisor)", re.IGNORECASE)
_COVERAGE_LINE_RE = re.compile(r"^Coverage:", re.MULTILINE)
_SECTION_HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def _sections(text: str) -> dict[str, str]:
    """Map section name -> body text (from its '## name' header to the next
    '## ' header or end of text), keyed by the first token after '## '."""
    out: dict[str, str] = {}
    matches = list(_SECTION_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = name.split()[0] if name else name
        out[key] = text[start:end]
        out.setdefault(name, text[start:end])
    return out


def load_sample_rows(sample_path: Path, audit_md_path: Path) -> list[tuple[str, str]]:
    """(repo, question) pairs to recompile. Prefers sample_compiled.json;
    falls back to parsing audit.md's per-row table if the json is missing
    repo/question fields."""
    rows: list[tuple[str, str]] = []
    if sample_path.exists():
        try:
            data = json.loads(sample_path.read_text())
        except Exception as exc:
            print(f"WARN: could not parse {sample_path}: {exc}", file=sys.stderr)
            data = []
        for d in data:
            repo = d.get("repo")
            question = d.get("question")
            if repo and question:
                rows.append((repo, question))
    if rows:
        return rows

    print(f"WARN: falling back to audit.md table at {audit_md_path}", file=sys.stderr)
    if not audit_md_path.exists():
        return rows
    row_re = re.compile(
        r"^\|\s*\d+\s*\|\s*([\w_]+)\s*\|\s*(.+?)\s*\|", re.MULTILINE
    )
    for m in row_re.finditer(audit_md_path.read_text()):
        repo, question = m.group(1), m.group(2)
        rows.append((repo, question))
    return rows


def _norm(question: str) -> str:
    return question.strip().rstrip("?").strip().lower()


def _catalog_kind_for(question: str, catalog: list[dict]) -> str | None:
    """Exact match first, then a loose fallback (strip trailing '?' and
    case), since audit.md's table truncates some question text."""
    for entry in catalog:
        if entry["question"] == question:
            return entry["answering"]["kind"]
    norm_q = _norm(question)
    for entry in catalog:
        if _norm(entry["question"]) == norm_q:
            return entry["answering"]["kind"]
    return None


class Checks:
    """Accumulates (name, status, detail) for one row. status in
    PASS/FAIL/SKIP."""

    def __init__(self, row_label: str):
        self.row_label = row_label
        self.results: list[tuple[str, str, str]] = []

    def record(self, name: str, ok: bool | None, detail: str = "") -> None:
        status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        self.results.append((name, status, detail))

    def counts(self) -> tuple[int, int]:
        passed = sum(1 for _, s, _ in self.results if s == "PASS")
        total = sum(1 for _, s, _ in self.results if s in ("PASS", "FAIL"))
        return passed, total

    def print_row(self) -> None:
        print(f"\n=== {self.row_label} ===")
        for name, status, detail in self.results:
            line = f"  [{status:4s}] {name}"
            if detail:
                snippet = detail.strip().replace("\n", " \\n ")
                if len(snippet) > 160:
                    snippet = snippet[:160] + "..."
                line += f" — {snippet}"
            print(line)


def check_row(repo: str, question: str, text: str, manifest: dict, catalog: list[dict]) -> Checks:
    c = Checks(f"{repo} :: {question}")
    packed = manifest.get("packed") or []
    sections = _sections(text)

    # 1. cve_scan headline + not fenced-JSON-first.
    if "cve_scan" in packed:
        body = sections.get("cve_scan")
        if body is None:
            c.record("cve_scan headline present", False, "cve_scan packed but no '## cve_scan' section found in text")
            c.record("cve_scan not raw-JSON-first", False, "cve_scan packed but no '## cve_scan' section found in text")
        else:
            lines = [ln for ln in body.strip("\n").split("\n") if ln.strip()]
            first_line = lines[0] if lines else ""
            headline_ok = bool(_CVE_HEADLINE_RE.search(first_line))
            c.record(
                "cve_scan headline states coverage",
                headline_ok,
                first_line if not headline_ok else "",
            )
            starts_json = first_line.strip().startswith("```json")
            c.record(
                "cve_scan section not fenced-JSON-first",
                not starts_json,
                first_line if starts_json else "",
            )
    else:
        c.record("cve_scan headline states coverage", None, "cve_scan not packed for this row")
        c.record("cve_scan section not fenced-JSON-first", None, "cve_scan not packed for this row")

    # 2. No fenced JSON anywhere.
    m = _FENCED_JSON_RE.search(text)
    c.record("no fenced ```json block anywhere", m is None, text[m.start():m.start() + 60] if m else "")

    # 3. No old bare mid-rung ("(list)"/"(mapping)" lines, "structure only" text).
    old_line = _OLD_MID_RUNG_LINE_RE.search(text)
    structure_only = _STRUCTURE_ONLY_RE.search(text)
    c.record(
        "no bare '- key: (list|mapping)' mid rung",
        old_line is None,
        old_line.group(0) if old_line else "",
    )
    c.record(
        "no 'structure only' phrasing",
        structure_only is None,
        text[max(0, structure_only.start() - 20):structure_only.start() + 40] if structure_only else "",
    )

    # 3b. Any section header claiming "abridged" must carry a "first N of M" marker.
    abridged_headers = [
        m2.group(1) for m2 in _SECTION_HEADER_RE.finditer(text)
        if "abridged" in m2.group(1).lower()
    ]
    if abridged_headers:
        all_matches = list(_SECTION_HEADER_RE.finditer(text))
        ok = True
        bad_header = ""
        for i, m2 in enumerate(all_matches):
            if "abridged" not in m2.group(1).lower():
                continue
            start = m2.end()
            end = all_matches[i + 1].start() if i + 1 < len(all_matches) else len(text)
            if not _FIRST_N_OF_M_RE.search(text[start:end]):
                ok = False
                bad_header = m2.group(1)
                break
        c.record("'abridged' sections carry a 'first N of M' marker", ok, bad_header)
    else:
        c.record("'abridged' sections carry a 'first N of M' marker", None, "no section header says 'abridged'")

    # 4. repository_health: flat forks/stars bullets, not nested JSON.
    if "repository_health" in packed:
        body = sections.get("repository_health", "")
        has_json_fence = "```json" in body
        forks_flat = bool(re.search(r"^-\s*[\w.]*forks:", body, re.MULTILINE))
        stars_flat = bool(re.search(r"^-\s*[\w.]*stars:", body, re.MULTILINE))
        ok = forks_flat and stars_flat and not has_json_fence
        detail = ""
        if not ok:
            detail = f"forks_flat={forks_flat} stars_flat={stars_flat} has_json_fence={has_json_fence}"
        c.record("repository_health exposes flat forks/stars bullets", ok, detail)
    else:
        c.record("repository_health exposes flat forks/stars bullets", None, "repository_health not packed for this row")

    # 5. Coverage line + manifest coverage.kind, gated on catalog answering kind.
    kind = _catalog_kind_for(question, catalog)
    coverage_line = _COVERAGE_LINE_RE.search(text)
    manifest_kind = (manifest.get("coverage") or {}).get("kind")
    if kind in _COVERAGE_KINDS:
        ok = (manifest_kind == kind) and (coverage_line is not None)
        detail = "" if ok else f"catalog_kind={kind} manifest_coverage_kind={manifest_kind} coverage_line_present={coverage_line is not None}"
        c.record(f"coverage surfaced for kind={kind}", ok, detail)
    elif kind in _NO_COVERAGE_KINDS:
        ok = coverage_line is None
        detail = "" if ok else f"unexpected 'Coverage:' line for kind={kind}"
        c.record(f"no coverage line for kind={kind}", ok, detail)
    else:
        c.record("coverage check", None, f"question not found in catalog or kind={kind!r} not in scope")

    # 6. used <= budget.
    used, budget = manifest.get("used"), manifest.get("budget")
    ok = used is not None and budget is not None and used <= budget
    c.record("manifest used <= budget", ok, f"used={used} budget={budget}")

    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    ap.add_argument("--audit-md", type=Path, default=DEFAULT_AUDIT_MD)
    args = ap.parse_args()

    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.context_compile import compile_context
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    reg = ProjectRegistry()
    reg.record_compile = lambda *a, **k: None  # persist nothing

    catalog = get_questions("repo")

    rows = load_sample_rows(args.sample, args.audit_md)
    if not rows:
        print("No sample rows found — check --sample / --audit-md paths.", file=sys.stderr)
        return 2

    # Dedupe: many audit rows repeat the same (repo, question); compiling
    # each unique pair once (twice, for the stability check) is enough.
    seen: dict[tuple[str, str], None] = {}
    for r in rows:
        seen.setdefault(r, None)
    unique_rows = list(seen.keys())

    print(f"Loaded {len(rows)} sample rows ({len(unique_rows)} unique repo/question pairs) "
          f"from {args.sample if args.sample.exists() else '(fallback) ' + str(args.audit_md)}")

    all_checks: list[Checks] = []
    any_fail = False

    for repo, question in unique_rows:
        try:
            c1 = compile_context(reg, repo, question, perspectives=[], budget=BUDGET)
        except Exception as exc:
            checks = Checks(f"{repo} :: {question}")
            checks.record("compile succeeded", False, f"{type(exc).__name__}: {exc}")
            all_checks.append(checks)
            any_fail = True
            checks.print_row()
            continue

        try:
            c2 = compile_context(reg, repo, question, perspectives=[], budget=BUDGET)
            stable = c1.compile_id == c2.compile_id
        except Exception as exc:
            stable = False

        checks = check_row(repo, question, c1.text, c1.manifest, catalog)
        checks.record(
            "compile id stable across two compiles",
            stable,
            "" if stable else f"{c1.compile_id} != (second compile failed or differed)",
        )
        checks.print_row()
        all_checks.append(checks)
        if any(s == "FAIL" for _, s, _ in checks.results):
            any_fail = True

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for c in all_checks:
        passed, total = c.counts()
        skipped = len(c.results) - total
        flag = "FAIL" if passed < total else "ok"
        print(f"  [{flag:4s}] {c.row_label:60.60s} {passed}/{total} passed"
              + (f" ({skipped} skipped)" if skipped else ""))

    total_pass = sum(c.counts()[0] for c in all_checks)
    total_checks = sum(c.counts()[1] for c in all_checks)
    print(f"\nTotal: {total_pass}/{total_checks} checks passed across {len(all_checks)} rows.")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
