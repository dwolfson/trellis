"""Dashboard Sheets held in Egeria: list, show, run one report placement (brief B5, read only).

Every route reads as the signed-in user (their Egeria token); see advisor.egeria_dashboards for the
visibility and cache rules. No route writes to Egeria.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

router = APIRouter()


def _viewer_creds(request: Request) -> Dict[str, str]:
    from advisor.auth import get_egeria_credentials, refuse_service_account, require_egeria_user
    require_egeria_user(request)
    creds = get_egeria_credentials(request) or {}
    refuse_service_account(creds.get("user_id"))
    return creds


async def _call(fn, *args, **kwargs) -> Dict[str, Any]:
    from advisor import egeria_dashboards as ed
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except ed.SignInRequired as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"})
    except ed.TokenRefused as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"})
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/api/dashboards")
async def list_dashboards(request: Request, refresh: bool = False) -> Dict[str, Any]:
    """The Dashboard Sheets this user can see: state ok / no_sheets / read_failed, with a message."""
    from advisor import egeria_dashboards as ed
    return await _call(ed.list_sheets, _viewer_creds(request), refresh=refresh)


@router.get("/api/dashboards/{name}")
async def show_dashboard(request: Request, name: str, perspective: Optional[str] = None,
                         refresh: bool = False) -> Dict[str, Any]:
    """One sheet resolved for this user: state ok / not_visible / read_failed. No report is run."""
    from advisor import egeria_dashboards as ed
    return await _call(ed.show_sheet, _viewer_creds(request), name, perspective=perspective or None,
                       refresh=refresh)


@router.post("/api/dashboards/{name}/placements/{position}/run")
async def run_dashboard_placement(request: Request, name: str, position: int,
                                  body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run one report placement with EA's report execution, as this user. Restricted, missing and text
    placements are refused with their reason."""
    from advisor import egeria_dashboards as ed
    body = body or {}
    return await _call(ed.run_placement, _viewer_creds(request), name, position,
                       perspective=body.get("perspective") or None, output_format=body.get("output_format"))
