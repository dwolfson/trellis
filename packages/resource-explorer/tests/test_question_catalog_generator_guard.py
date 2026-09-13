"""The question catalog YAML is generated from its CSV and says so in its
own header. Nothing checked it: a hand-edit to the YAML passed 144 tests
on 2026-09-12 (caught in review of a peer's branch, not by the suite). The
survey definitions have had this guard since their generator landed --
test_survey_definition_generator_guard -- and this is the same shape for
the catalog: a clean tree regenerates to byte-identical output, so a YAML
that drifts from its CSV fails here and names the fix.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "csv_to_question_catalog_yaml.py"
CSV = ROOT / "docs" / "dr-egeria" / "resource_questions.csv"
YAML = ROOT / "resource_explorer" / "configdata" / "question_catalog.yaml"


def test_the_committed_catalog_is_what_its_csv_generates(tmp_path):
    out = tmp_path / "question_catalog.yaml"
    r = subprocess.run([sys.executable, str(SCRIPT), str(CSV), "--output", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    committed = YAML.read_text(encoding="utf-8")
    generated = out.read_text(encoding="utf-8")
    assert committed == generated, (
        "resource_explorer/configdata/question_catalog.yaml does not match what "
        "docs/dr-egeria/resource_questions.csv generates. Edit the CSV, then run\n"
        f"  python scripts/csv_to_question_catalog_yaml.py {CSV.relative_to(ROOT)} "
        f"--output {YAML.relative_to(ROOT)}\n"
        "-- never the YAML by hand."
    )
