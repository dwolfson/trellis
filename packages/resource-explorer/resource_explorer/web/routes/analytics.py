"""Curate's "By analysis" tab: the Analytic Library's `curation_coverage`, run over RE's own registry, read-only.

The route never constructs `ProjectRegistry` (whose constructor migrates): `OdsReader` opens the store itself
read-only. When the library is not installed the answer is `not_applicable` with its reason, never a 500 and
never a table of zeros.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

router = APIRouter()


def registry_url() -> str:
    """The registry RE itself reads (the same default ProjectRegistry takes)."""
    from resource_explorer.config import get_config
    return get_config().registry.database_url


def _unavailable(resource_type: str, slug: str, reason: str) -> dict:
    return {"resource_type": resource_type, "slug": slug, "groups": [], "summary": "",
            "envelope": {"result_state": "not_applicable", "result_state_reason": reason,
                         "scope": f"{resource_type}:{slug}"}}


def curation_coverage_for(resource_type: str, slug: str, url: str | None = None) -> dict:
    """Run the routine and return its result dict. Blocking (a registry read); call off the loop."""
    try:
        from trellis_analytics.readers.ods import OdsReader
        from trellis_analytics.routines import curation_coverage
    except ImportError as exc:
        return _unavailable(resource_type, slug, f"the Analytic Library (trellis-analytics) is not installed: {exc}")
    return curation_coverage(OdsReader(url or registry_url()), resource_type, slug).to_dict()


@router.get("/curation-coverage/{resource_type}/{slug}")
async def read_curation_coverage(resource_type: str, slug: str) -> dict:
    return await asyncio.to_thread(curation_coverage_for, resource_type, slug)
