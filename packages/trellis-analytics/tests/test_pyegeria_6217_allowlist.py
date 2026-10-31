"""pyegeria 6.2.17 (#516, ISSUE-169): a report spec's analytic_function resolves only as a registry name, a dotted
path some registered entry declares, or a dotted path under an allowed prefix (pyegeria, trellis_analytics).
Everything this library names must still resolve; a name outside those is refused before any import."""
import pytest

fse = pytest.importorskip("pyegeria.view.format_set_executor")

from trellis_analytics.manifests import CONTEXT_PACK, CURATION_COVERAGE  # noqa: E402
from trellis_analytics.portal import TILE_FUNCTION  # noqa: E402


@pytest.mark.parametrize("name", [
    TILE_FUNCTION,                                   # the Portal tile's FormatSet (portal.py, examples/curation_coverage_tile.md)
    "trellis_analytics.routines.curation_coverage",  # the walking-skeleton brief's spelling
    CURATION_COVERAGE.function, CONTEXT_PACK.function,
    "curation_coverage", "context_pack",             # registry names, read from the trellis.analytics entry points
])
def test_every_name_the_library_uses_resolves(name, monkeypatch):
    monkeypatch.delenv("PYEGERIA_ANALYTIC_MODULE_PREFIXES", raising=False)
    assert callable(fse._resolve_analytic_function(name))


def test_an_unregistered_path_outside_the_prefixes_is_refused(monkeypatch):
    monkeypatch.delenv("PYEGERIA_ANALYTIC_MODULE_PREFIXES", raising=False)
    with pytest.raises(fse.AnalyticFunctionRefused):
        fse._resolve_analytic_function("os.system")
