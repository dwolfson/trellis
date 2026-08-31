#!/usr/bin/env python3
"""Do the 12 Perspectives from foundations.md exist in live Egeria?

`docs/open-stack-checklist.md` §7 gives three post-redeploy checks — questions
resolve, no duplicate/stale links, both surveys load — and **none of them looks
at Perspectives**. They are authored by `docs/dr-egeria/foundations/foundations.md`
in the same batch as the glossary and funnel stages, so a heal that reports
success can leave them missing exactly the way 8 of 49 questions went missing on
2026-08-31.

**Compared against the generative source, not a snapshot.**
`docs/egeria-redeploy-baseline-2026-08-26.json` records 12 perspectives and was
verified identical to foundations.md on 2026-08-31 — so the snapshot adds
nothing the repo does not already hold, and a generator says what SHOULD be
there where a snapshot only says what once was.

    uv run python scripts/verify_perspectives.py

Exit codes: 0 all present · 1 some missing · 2 could not determine.

**UNREACHABLE IS NOT MISSING, and that distinction is the point of this file.**
Written while the platform was down for a redeploy, so it has never been
exercised against a live server and its first real run is the post-redeploy
verification itself. A check that cannot tell "the platform is not answering"
from "the perspectives are gone" would report 0/12 at precisely the moment that
reads as catastrophe — so a connection failure exits 2 and says so, and only a
definite not-found counts as missing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_FOUNDATIONS = (Path(__file__).resolve().parents[1]
                / "docs" / "dr-egeria" / "foundations" / "foundations.md")

#: `## Create Perspective` followed by `### Display Name` and its value. Reading
#: the authored document rather than a list in this file: a hard-coded list here
#: would be a second copy to keep in step, which is the duplication this
#: codebase keeps removing.
_PERSPECTIVE_RE = re.compile(
    r"##\s*Create Perspective\s*\n+###\s*Display Name\s*\n+([^\n]+)")


def expected_perspectives() -> list[str]:
    if not _FOUNDATIONS.is_file():
        raise FileNotFoundError(f"foundations document not found: {_FOUNDATIONS}")
    names = [m.strip() for m in _PERSPECTIVE_RE.findall(_FOUNDATIONS.read_text())]
    return sorted(n for n in names if n)


def main() -> int:
    expected = expected_perspectives()
    if not expected:
        print("No perspectives found in foundations.md — the parse, not the platform.")
        print(f"  looked in {_FOUNDATIONS}")
        return 2
    print(f"{len(expected)} perspective(s) declared in foundations.md\n")

    try:
        from resource_explorer.surveyors.survey_definition_reader import (
            SurveyDefinitionReader,
        )
        client = SurveyDefinitionReader()._connect_classification_explorer()
    except Exception as exc:
        print(f"Could not reach Egeria ({type(exc).__name__}). "
              "NOT reporting the perspectives as missing — this says nothing "
              "about whether they exist.")
        return 2

    missing: list[str] = []
    undetermined: list[str] = []
    for name in expected:
        found = None
        errors = 0
        # qualifiedName first: `Perspective::<name>` is the pattern
        # foundations.md authors, and display names are not guaranteed unique
        # across types. Display name is the fallback, not the primary.
        for prop, value in (("qualifiedName", f"Perspective::{name}"),
                            ("displayName", name)):
            try:
                got = client.get_guid_for_name(value, property_name=[prop])
            except Exception:
                errors += 1
                continue
            text = str(got or "")
            if text and "No elements" not in text and "not found" not in text.lower():
                found = text
                break
        if found:
            print(f"  ok       {name}")
        elif errors == 2:
            # Both lookups raised: cannot distinguish absent from unaskable.
            undetermined.append(name)
            print(f"  ?        {name}  (lookup failed — not counted as missing)")
        else:
            missing.append(name)
            print(f"  MISSING  {name}")

    print()
    if undetermined:
        print(f"{len(undetermined)} could not be determined and are NOT counted as missing.")
    if missing:
        print(f"{len(missing)} of {len(expected)} perspective(s) are absent from Egeria.")
        print("Re-run the foundations document, then "
              "scripts/reconcile_survey_definition_links.py.")
        return 1
    if undetermined:
        return 2
    print(f"All {len(expected)} perspectives resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
