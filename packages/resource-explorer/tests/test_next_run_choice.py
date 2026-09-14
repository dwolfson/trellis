"""REPORT-RECORD-AND-TWO-CALLS §A (designer, 2026-09-13): the one-click
re-run stops being one click. A popover anchored to the link, Background
first, Run and wait keeps its name, four price variants, both buttons in
all four."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


class TestNothingQueuesFromTheLink:
    def test_the_link_opens_the_choice_and_only_a_button_runs(self):
        app = _app()
        assert "openRunChoice(entry, i, ev.currentTarget)" in app
        body = app[app.index("async function openRunChoice("):app.index("async function rerun(")]
        assert 'data-run-mode="background"' in body and 'data-run-mode="wait"' in body
        assert body.index('data-run-mode="background"') < body.index('data-run-mode="wait"'), "Background first"
        assert ">Run and wait<" in body, "the waiting option keeps its own name"
        assert "rerun(entry, i, { background:" in body

    def test_background_enqueues_and_stops_watching(self):
        app = _app()
        body = app[app.index("async function rerun("):app.index("/** One measure, rendered")]
        assert "if (background) {" in body and "reload to read the result" in body
        assert "pollActivity" not in body.split("if (background) {")[1].split("return;")[0]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
class TestTheFourPriceVariants:
    def _run(self, expr, tmp_path):
        app = _app()
        src = app[app.index("function fmtSeconds("):app.index("async function openRunChoice(")]
        mod = tmp_path / "price.mjs"
        mod.write_text("const esc = (s) => String(s); const tnum = (s) => s;\n" + src + "\nexport { priceLineHtml, fmtSeconds };\n")
        script = f"import {{ priceLineHtml, fmtSeconds }} from '{mod.as_uri()}';\nconsole.log(JSON.stringify({expr}));"
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_measured_split_uses_the_servers_sentence(self, tmp_path):
        cost = {"basis": "measured", "runs": 4, "split_runs": 2, "seconds": 92.1,
                "sentence": "about 0.1s to run and about 1m 32s to publish — 1m 32s in all, nearly all of it publishing."}
        html = self._run(f"priceLineHtml({json.dumps(cost)}, 'x')", tmp_path)
        assert "nearly all of it publishing" in html and "not yet split" not in html

    def test_measured_unsplit_is_labelled(self, tmp_path):
        cost = {"basis": "measured", "runs": 3, "split_runs": 0, "seconds": 70}
        html = self._run(f"priceLineHtml({json.dumps(cost)}, 'x')", tmp_path)
        assert "1m 10s" in html and "median of" in html and "not yet split into run and publish" in html

    def test_declared_is_the_word_and_says_declared(self, tmp_path):
        cost = {"basis": "declared", "declared": "fast", "runs": 0}
        html = self._run(f"priceLineHtml({json.dumps(cost)}, 'x')", tmp_path)
        assert "declared" in html and "fast" in html and "not measured" in html

    def test_not_known_says_so_and_names_the_fix(self, tmp_path):
        for cost in ("null", json.dumps({"basis": "unknown"}), json.dumps({"basis": "measured", "runs": 0})):
            html = self._run(f"priceLineHtml({cost}, 'cve_scan')", tmp_path)
            assert "Price not known" in html and "cve_scan" in html and "first run is what fixes it" in html

    def test_seconds_read_as_a_person_would_say_them(self, tmp_path):
        assert self._run("[fmtSeconds(0.13), fmtSeconds(42), fmtSeconds(92), fmtSeconds(180)]", tmp_path) == ["0.1s", "42s", "1m 32s", "3m"]
