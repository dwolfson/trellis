"""Bootstrap status + manual run — backs the reinitializing banner and Admin.

Read-mostly. The automatic path (startup check + periodic loop) lives in
resource_explorer/bootstrap.py and needs no HTTP surface; these routes exist so
the UI can say "definitions are being restored" instead of showing a silently
degraded Survey tab, and so an admin can trigger a pass without restarting.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resource_explorer import bootstrap as bootstrap_mod

router = APIRouter()


class RunRequest(BaseModel):
    force: bool = False
    """Re-run every batch regardless of canary presence.

    Defaults to False, and the UI must confirm before sending True: for a batch
    with idempotent=false (RE's survey definitions) a forced re-run duplicates
    every step link and takes those Survey Definitions out of service until the
    reconciler runs. This is the exact failure the missing-only gate prevents on
    the automatic path, so the manual path has to ask rather than assume.
    """


@router.get("/status")
async def bootstrap_status() -> dict:
    """Per-batch presence/heal state. Cheap — reads in-process state, does not
    hit Egeria, so the banner can poll it without adding load."""
    return bootstrap_mod.get_status()


@router.post("/run")
async def bootstrap_run(body: RunRequest | None = None) -> dict:
    """Run a check-and-heal pass now.

    Blocking work (subprocess dr_egeria calls) is pushed to a thread, matching
    the asyncio.to_thread pattern the other long-running routes use.
    """
    force = bool(body and body.force)
    try:
        return await asyncio.to_thread(bootstrap_mod.check_and_heal, bootstrap_mod.DOCS_DIR, force)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"bootstrap run failed: {exc}")
