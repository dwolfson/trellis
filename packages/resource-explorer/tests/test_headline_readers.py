"""Every headline reader must be callable the way the caller calls it.

`web/routes/projects.py` invokes every headline reader uniformly as
`headline_reader(registry, slug)` and wraps it in a bare
`except Exception: headline = None`. So a reader with the wrong signature does
not fail — it raises TypeError on every call, the tile silently never renders,
and nothing is logged.

That is exactly what `_website_ingestion_headline` did: declared `(results)`,
called as `(registry, slug)`, 0 of 60 repos, undetected. A bare except around a
uniform call is where an interface mismatch goes to hide, so the interface needs
asserting somewhere the except cannot reach.
"""
from __future__ import annotations

import inspect

import pytest

from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS

_WITH_HEADLINE = sorted(
    (aid, k.results.headline_reader)
    for aid, k in ANALYSIS_KINDS.items()
    if k.results and getattr(k.results, "headline_reader", None)
)


@pytest.mark.parametrize("analysis_id,reader", _WITH_HEADLINE, ids=[a for a, _ in _WITH_HEADLINE])
def test_headline_reader_takes_registry_and_slug(analysis_id, reader):
    params = [
        p for p in inspect.signature(reader).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    assert len(params) == 2, (
        f"{reader.__name__} takes {[p.name for p in params]}, but "
        "projects.py calls every headline reader as (registry, slug). A mismatch "
        "raises TypeError into a bare except and the tile silently never renders."
    )


@pytest.mark.parametrize("analysis_id,reader", _WITH_HEADLINE, ids=[a for a, _ in _WITH_HEADLINE])
def test_headline_reader_actually_runs(analysis_id, reader):
    """Signature agreement is necessary, not sufficient — call it for real.

    Returning None is a legitimate answer (nothing to headline for this repo);
    raising is not.
    """
    from resource_explorer.registry import ProjectRegistry

    reg = ProjectRegistry()
    slugs = [p.slug for p in reg.list_all()[:3]]
    if not slugs:
        pytest.skip("no registered repos")
    for slug in slugs:
        try:
            result = reader(reg, slug)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{reader.__name__}({slug!r}) raised {type(exc).__name__}: {exc}")
        assert result is None or isinstance(result, dict)
