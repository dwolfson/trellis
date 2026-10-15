"""Install the Analytic Library's example step `database_staleness` the way pip would, for one test.

The step is a package outside RE (packages/trellis-analytics/examples/steps/database_staleness) and is not
installed in RE's environment, which is this suite's normal state. `install(tmp_path)` writes a dist-info that
carries the entry points the step's own pyproject declares, and returns the two path entries that make it
importable and discoverable; `staleness_installed` puts them on sys.path and re-attaches RE's user steps, and
puts everything back afterwards. `pythonpath(tmp_path)` is the same for a subprocess.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "packages" / "trellis-analytics" / "examples" / "steps" / "database_staleness"


def install(tmp_path: Path) -> tuple[str, str]:
    """(dist-info directory's parent, the step's source root). Writes the dist-info once per tmp_path."""
    project = tomllib.loads((EXAMPLE / "pyproject.toml").read_text())["project"]
    eps = project["entry-points"]["trellis.analytics"]
    version = re.search(r'__version__ = "([^"]+)"',
                        (EXAMPLE / "src" / "database_staleness" / "__init__.py").read_text()).group(1)
    root = tmp_path / "site"
    d = root / f"trellis_step_database_staleness-{version}.dist-info"
    if not d.exists():
        d.mkdir(parents=True)
        (d / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {project['name']}\nVersion: {version}\n")
        (d / "entry_points.txt").write_text(
            "[trellis.analytics]\n" + "".join(f"{k} = {v}\n" for k, v in eps.items()))
    return str(root), str(EXAMPLE / "src")


def pythonpath(tmp_path: Path) -> str:
    """A PYTHONPATH value with the step installed, for a subprocess (the generator's --check)."""
    parts = list(install(tmp_path)) + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    return os.pathsep.join(parts)


@pytest.fixture
def staleness_installed(tmp_path, monkeypatch):
    from resource_explorer.surveyors import survey_step_host

    for entry in reversed(install(tmp_path)):
        monkeypatch.syspath_prepend(entry)
    survey_step_host.refresh("database")
    yield
    monkeypatch.undo()
    survey_step_host.refresh("database")
