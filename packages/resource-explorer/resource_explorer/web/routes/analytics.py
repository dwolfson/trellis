"""Curate's "By analysis" tab: the Analytic Library's `curation_coverage`, run over RE's own registry, read-only.

The route never constructs `ProjectRegistry` (whose constructor migrates): `OdsReader` opens the store itself
read-only. When the library is not installed the answer is `not_applicable` with its reason, never a 500 and
never a table of zeros.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

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


# Entity types the route knows. The library answers `not_applicable` (with its reason) for the ones it does
# not yet measure; a type outside this set is a caller error (404).
KNOWN_ENTITY_TYPES = ("database", "file_system", "document_source")


def require_caller(request: Request) -> dict:
    """Authenticate a tile read: RE's session JWT, or the Portal's SSO JWT. Never anonymous.

    `Authorization: Bearer <jwt>` either way. The Portal's token is HS256 under the shared portal secret
    (`TRELLIS_PORTAL_SECRET` here, `EGERIA_ADVISOR_SSO_SECRET` in the Portal) with claims
    `{sub, role, display_name, egeria_token, iat, exp}`; an expired or forged one is 401.
    """
    import jwt
    from resource_explorer.auth import exchange_portal_token, get_current_user
    from resource_explorer.egeria_clients import DaemonSignInRefused, refuse_daemon_sign_in

    claims = get_current_user(request)
    if claims is None:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required: send Authorization: Bearer <jwt>.")
        try:
            claims = exchange_portal_token(token)
        except HTTPException as exc:
            if exc.status_code == 503:
                raise HTTPException(status_code=401, detail="Authentication required: not a valid session token, "
                                    "and Portal SSO is not configured on this server.") from None
            raise
        except jwt.PyJWTError as exc:       # pragma: no cover - exchange maps these already
            raise HTTPException(status_code=401, detail=str(exc)) from None
    user = claims.get("user_id") or claims.get("sub") or ""
    if not user:
        raise HTTPException(status_code=401, detail="Token carries no subject.")
    try:
        refuse_daemon_sign_in(user)
    except DaemonSignInRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    return claims


def curation_coverage_tile_for(entity_type: str, slug: str, url: str | None = None) -> dict:
    """The Portal tile dict, from the library's own `curation_coverage_tile` (one reshape, not a copy)."""
    try:
        from trellis_analytics.portal import curation_coverage_tile
    except ImportError as exc:
        reason = f"the Analytic Library (trellis-analytics) is not installed: {exc}"
        return {"state": "not_applicable", "state_reason": reason, "subtitle": f"Not applicable \u00b7 {reason}",
                "summary": "", "groups": [], "kpis": []}
    return curation_coverage_tile(slug, url or registry_url(), entity_type)


@router.get("/curation-coverage-tile/{entity_type}/{slug}")
async def read_curation_coverage_tile(entity_type: str, slug: str, request: Request) -> dict:
    require_caller(request)
    if entity_type not in KNOWN_ENTITY_TYPES:
        raise HTTPException(status_code=404, detail=f"unknown entity type {entity_type!r}; known: {', '.join(KNOWN_ENTITY_TYPES)}")
    return await asyncio.to_thread(curation_coverage_tile_for, entity_type, slug)
