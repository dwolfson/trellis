"""Generate, from installed step manifests, what RE and Egeria need to know about user steps (extensibility brief 2c):

1. the `analysis_catalog.yaml` entries, written between the GENERATED markers at the end of each
   `<type>_analyses` list (`survey_step_host.catalog_entry`), and
2. the Dr.Egeria document declaring each step (`trellis_analytics.declare.declaration_markdown`), written to
   `docs/dr-egeria/analytic-functions/<step>.md`. Generated only: this script never talks to Egeria.

Manifests are read from the `trellis.analytics` entry point, so the step's package must be installed where this
runs, for example:

    uv run --with-editable packages/trellis-analytics/examples/steps/database_staleness \\
        python packages/resource-explorer/scripts/generate_external_step_entries.py

`--check` writes nothing and exits 1 when a committed file differs from what would be generated.
tests/test_database_staleness_step.py (trellis-analytics) holds the committed files to the generator.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
CATALOG = PKG / "resource_explorer" / "configdata" / "analysis_catalog.yaml"
DOCS = PKG / "docs" / "dr-egeria" / "analytic-functions"
SECTIONS = {"database": "database_analyses"}
BEGIN = "  # BEGIN GENERATED user steps ({type}): scripts/generate_external_step_entries.py. Do not hand-edit."
END = "  # END GENERATED user steps ({type})"


def _step_manifests(entity_type: str) -> list:
    from trellis_analytics.discovery import discover
    return sorted((m for m in discover().values()
                   if m.kind == "step" and entity_type in m.resource_types), key=lambda m: m.name)


def render_catalog_block(entity_type: str) -> str:
    """The marked block of catalog entries for one resource type, as it appears in analysis_catalog.yaml."""
    from trellis_analytics.discovery import origin
    from resource_explorer.surveyors.survey_step_host import catalog_entry

    entries = [catalog_entry(m, origin(m.name)) for m in _step_manifests(entity_type)]
    body = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=100) if entries else ""
    indented = "".join(f"  {line}\n" if line else "\n" for line in body.splitlines())
    return f"{BEGIN.format(type=entity_type)}\n{indented}{END.format(type=entity_type)}\n"


def render_declarations() -> dict[Path, str]:
    from trellis_analytics.declare import declaration_markdown
    from trellis_analytics.discovery import origin

    out = {}
    for entity_type in SECTIONS:
        for m in _step_manifests(entity_type):
            out[DOCS / f"{m.name}.md"] = declaration_markdown(m, origin(m.name))
    return out


def _with_block(text: str, entity_type: str) -> str:
    block = render_catalog_block(entity_type)
    begin, end = BEGIN.format(type=entity_type), END.format(type=entity_type)
    if begin in text:
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end + "\n", 1)
        return head + block + tail
    # First run: the block goes at the end of the section's list, before the next top-level key.
    section = SECTIONS[entity_type] + ":\n"
    start = text.index(section) + len(section)
    nxt = min((i for i in (text.find("\n" + k, start) for k in
                           ("repo_analyses:", "filesystem_analyses:", "database_analyses:")) if i != -1),
              default=len(text))
    return text[:nxt + 1].rstrip("\n") + "\n\n" + block + "\n" + text[nxt + 1:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when anything is stale")
    args = ap.parse_args(argv)

    want: dict[Path, str] = {}
    text = CATALOG.read_text()
    for entity_type in SECTIONS:
        text = _with_block(text, entity_type)
    want[CATALOG] = text
    want.update(render_declarations())

    stale = [p for p, body in want.items() if not p.exists() or p.read_text() != body]
    if args.check:
        for p in stale:
            print(f"stale: {p.relative_to(PKG)}")
        return 1 if stale else 0
    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(want[p])
        print(f"wrote {p.relative_to(PKG)}")
    if not stale:
        print("nothing to write: every generated file is current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
