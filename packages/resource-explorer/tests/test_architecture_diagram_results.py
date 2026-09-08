"""architecture_diagram (repo_survey_definition_adapter.py) — new 2026-09-08.

The Mermaid diagram + caption arch_recovery/persist.py's `_persist_diagram`
computes and writes at survey time (alongside repo_arch_detect/coupling's
own findings) was never read back by anything before this — see
BACKLOG.md's "how do components relate" investigation. This pins the read
path: a persisted `architecture_diagram` finding round-trips through
`_architecture_diagram_results`/`_architecture_diagram_headline` into the
shape `_renderEnvelopeMarkdown` (index.html) actually consumes — `mermaid`,
`caption`/headline, and the too-large flag.
"""
from __future__ import annotations

from resource_explorer.surveyors.repo_survey_definition_adapter import (
    _architecture_diagram_headline,
    _architecture_diagram_results,
)


class _Reg:
    def __init__(self, rows):
        self._rows = rows

    def query_findings(self, slug, kind):
        assert kind == "architecture_diagram"
        return self._rows


def _row(caption="3 component(s) shown at depth 2.", mermaid="graph TD\n  a --> b",
         char_count=None, exceeds=False, surveyed_at="2026-09-08T00:00:00"):
    return {
        "summary": caption,
        "surveyed_at": surveyed_at,
        "detail_json": {
            "mermaid": mermaid,
            "char_count": char_count if char_count is not None else len(mermaid),
            "exceeds_renderer_limit": exceeds,
            "projection_depth": 2,
        },
    }


class TestResultsReadBack:
    def test_never_run_reports_its_own_empty_state(self):
        r = _architecture_diagram_results(_Reg([]), "acme-widget")
        assert r["state"] == "never_run"

    def test_a_persisted_diagram_round_trips(self):
        r = _architecture_diagram_results(_Reg([_row()]), "acme-widget")
        assert r["mermaid"] == "graph TD\n  a --> b"
        assert r["caption"] == "3 component(s) shown at depth 2."
        assert r["exceeds_renderer_limit"] is False
        assert r["char_count"] == len("graph TD\n  a --> b")

    def test_the_latest_run_wins(self):
        rows = [
            _row(caption="old", mermaid="graph TD\n  x", surveyed_at="2026-09-01T00:00:00"),
            _row(caption="new", mermaid="graph TD\n  y", surveyed_at="2026-09-08T00:00:00"),
        ]
        r = _architecture_diagram_results(_Reg(rows), "acme-widget")
        assert r["caption"] == "new"

    def test_a_json_string_detail_column_is_parsed(self):
        """Postgres hands back JSONB as a dict; a string-backed store (or a
        row read a different way) hands back the same content as text --
        the same backend split _architecture_summary_results already
        guards against."""
        import json
        row = _row()
        row["detail_json"] = json.dumps(row["detail_json"])
        r = _architecture_diagram_results(_Reg([row]), "acme-widget")
        assert r["mermaid"] == "graph TD\n  a --> b"


class TestHeadline:
    def test_never_run_has_no_headline(self):
        assert _architecture_diagram_headline(_Reg([]), "acme-widget") is None

    def test_the_caption_becomes_the_headline_label(self):
        h = _architecture_diagram_headline(_Reg([_row(caption="4 component(s) shown.")]), "acme-widget")
        assert h == {"label": "4 component(s) shown.", "status": "info"}

    def test_an_oversized_diagram_warns_instead_of_info(self):
        """caption() (mermaid.py) already appends "NOT RENDERABLE: ..." to
        its own text when this is true -- the badge must agree with the
        words rather than a reader having to notice only in the sentence."""
        h = _architecture_diagram_headline(
            _Reg([_row(caption="200 component(s) shown. NOT RENDERABLE: too large.", exceeds=True)]),
            "acme-widget",
        )
        assert h["status"] == "warn"

    def test_a_missing_caption_falls_back_to_a_generic_label(self):
        row = _row(caption="")
        h = _architecture_diagram_headline(_Reg([row]), "acme-widget")
        assert h["label"] == "Architecture diagram"
