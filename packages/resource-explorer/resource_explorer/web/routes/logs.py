"""Application log records, for Admin → Observe → Logs.

Reads the in-process ring buffer that `observability/logging_setup.py` installs
on the root logger. There is no file to tail and nothing is shipped anywhere:
the buffer holds the most recent `RING_CAPACITY` records and is empty after a
restart.

**That is why this returns metadata alongside the records.** An empty list here
has at least three causes — nothing has been logged, the buffer was emptied by a
restart, or the level filter excluded everything — and they are not the same
fact. A viewer that renders all three as "no logs" would be the exact failure
this codebase keeps finding: an absence presented as an answer.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from resource_explorer.observability import logging_setup

router = APIRouter()

#: Offered as filter options. Not derived from what happens to be in the buffer:
#: deriving them would hide ERROR from the dropdown precisely when no error has
#: occurred yet, which is when someone is most likely to go looking for it.
LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


@router.get("/")
def list_logs(limit: int = 200, level: str = "", logger: str = "") -> dict:
    """Recent records, newest first.

    `level` is an exact match rather than a threshold — "show me the warnings"
    is the common request, and a threshold buries them under INFO.
    """
    if level and level.upper() not in LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown level {level!r}; expected one of {', '.join(LEVELS)}",
        )
    limit = max(1, min(int(limit), logging_setup.RING_CAPACITY))

    records = logging_setup.ring_handler.records(
        limit=limit, level=level, logger=logger)

    held = len(logging_setup.ring_handler)
    return {
        "records": records,
        "filtered": bool(level or logger),
        "buffer": {
            # Everything a reader needs to interpret an empty list correctly.
            "held": held,
            "capacity": logging_setup.RING_CAPACITY,
            "full": held >= logging_setup.RING_CAPACITY,
            "durable": False,
            "note": "In-memory and bounded — the oldest records are dropped once "
                    "full, and the buffer is empty after a restart. An empty list "
                    "does not mean nothing happened.",
        },
        "levels": LEVELS,
        "root_level": logging.getLevelName(logging.getLogger().level),
    }
