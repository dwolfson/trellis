"""Application logging — configured, rather than left to Python's fallback.

**What this replaces.** Nothing configured logging in this package. The root
logger had no handlers and sat at WARNING, and `uvicorn.run()` was called with
no `log_config`. Two consequences, measured 2026-08-31 before this existed:

- **Every `log.info(...)` in the codebase was discarded.** Not written
  anywhere, not slow, not filtered later — dropped at the call site. Anyone who
  added an info-level line expecting to find it afterwards was mistaken.
- **WARNING and ERROR fell through to `logging.lastResort`**, a bare
  `StreamHandler` whose format is `%(message)s`. They reached stderr with no
  timestamp, no logger name and no level — so a warning could not be attributed
  to a component or placed in time.

That is why survey failures are recorded in the activity log rather than logged
(CLAUDE.md rule 16): the log was not somewhere anything could be found. Rule 16
still stands — this does not make logging an alternative to the activity log for
anything a user needs to see.

**The ring buffer.** A bounded in-memory handler keeps the most recent records
so a viewer can read them without tailing a file or shipping logs anywhere. It
is deliberately not durable: it holds `RING_CAPACITY` records and loses them on
restart. A log viewer built on it must say so, because "no records" after a
restart is not "nothing happened" — the distinction this codebase cares about
most.
"""
from __future__ import annotations

import collections
import logging
import os
import threading
from typing import Any

#: Records kept in memory for the viewer. ~5k lines is minutes of a busy survey
#: and costs a few MB; the buffer is a debugging aid, not storage.
RING_CAPACITY = 5000

#: Timestamp, level, logger name, message. The logger name is the part
#: `lastResort` dropped, and it is what makes a line attributable.
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False
_lock = threading.Lock()


class RingBufferHandler(logging.Handler):
    """Keeps the last `capacity` records so they can be read back in-process."""

    def __init__(self, capacity: int = RING_CAPACITY) -> None:
        super().__init__()
        self._records: collections.deque = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        # A logging handler must never raise into the caller: a failure here
        # would turn "this survey logged something" into "this survey crashed".
        try:
            entry = {
                "ts": self.formatter.formatTime(record, DATE_FORMAT) if self.formatter
                      else str(record.created),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "exc": self.formatter.formatException(record.exc_info)
                       if (record.exc_info and self.formatter) else "",
            }
            with self._lock:
                self._records.append(entry)
        except Exception:  # pragma: no cover - defensive, see above
            self.handleError(record)

    def records(self, limit: int = 500, level: str = "", logger: str = "") -> list[dict]:
        """Newest first. Filters are exact on level, prefix on logger name."""
        with self._lock:
            items = list(self._records)
        if level:
            want = level.upper()
            items = [r for r in items if r["level"] == want]
        if logger:
            items = [r for r in items if r["logger"].startswith(logger)]
        return list(reversed(items))[:limit]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


#: The process-wide buffer. Module-level so a route can read what the surveyors
#: wrote without either of them knowing about the other.
ring_handler = RingBufferHandler()


def resolve_level(explicit: str | None = None) -> int:
    """`explicit` > `$RE_LOG_LEVEL` > INFO.

    INFO is the default deliberately. The previous effective default was
    WARNING-and-unformatted, which is how info-level lines came to be written
    across the codebase by people who reasonably assumed they would appear.
    """
    raw = (explicit or os.getenv("RE_LOG_LEVEL") or "INFO").strip().upper()
    resolved = logging.getLevelName(raw)
    # getLevelName returns the string "Level XYZ" for anything unrecognised.
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Attach a console handler and the ring buffer to the root logger.

    Idempotent: repeated calls are a no-op unless `force`. Several entry points
    legitimately want to guarantee logging is configured (the CLI, the web app's
    import) and none of them should be able to double up handlers, which is how
    every line ends up printed twice.

    Returns what it did, so a caller can report it rather than assume.
    """
    global _configured
    with _lock:
        if _configured and not force:
            return {"configured": False, "reason": "already configured"}

        root = logging.getLogger()
        lvl = resolve_level(level)
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

        # Replace only handlers this module installed, so a host application
        # (or pytest's caplog) keeps its own.
        for h in list(root.handlers):
            if getattr(h, "_re_installed", False):
                root.removeHandler(h)

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console._re_installed = True  # type: ignore[attr-defined]
        root.addHandler(console)

        ring_handler.setFormatter(formatter)
        ring_handler._re_installed = True  # type: ignore[attr-defined]
        root.addHandler(ring_handler)

        root.setLevel(lvl)

        # These are chatty at INFO and say nothing about this application.
        for noisy in ("urllib3", "httpx", "httpcore", "asyncio", "botocore",
                      "sentence_transformers", "filelock"):
            logging.getLogger(noisy).setLevel(max(lvl, logging.WARNING))

        _configured = True
        return {"configured": True, "level": logging.getLevelName(lvl),
                "handlers": ["console", "ring"]}


def uvicorn_log_config(level: str | None = None) -> dict:
    """A `log_config` for `uvicorn.run()` matching this module's format.

    Without one, uvicorn installs its own handlers on `uvicorn`/`uvicorn.access`
    with `propagate` disabled, so server lines are formatted differently from
    application lines and never reach the ring buffer. `propagate: true` with no
    handlers of their own is what puts both through the root configuration.
    """
    lvl = logging.getLevelName(resolve_level(level))
    return {
        "version": 1,
        # False, so the loggers `configure_logging` already set up survive this
        # being applied afterwards.
        "disable_existing_loggers": False,
        "formatters": {"re": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT}},
        "handlers": {},
        "loggers": {
            "uvicorn": {"handlers": [], "level": lvl, "propagate": True},
            "uvicorn.error": {"handlers": [], "level": lvl, "propagate": True},
            # Access logs at INFO are one line per request, which would drown a
            # ring buffer whose purpose is application events.
            "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": True},
        },
        # NOTE: no "root" key, deliberately. dictConfig REPLACES root's handler
        # list when one is given, so declaring root here would tear out the
        # console and ring handlers `configure_logging` installed — and
        # uvicorn applies its log_config after our setup runs. The symptom
        # would be a log viewer that is empty in the server and full in the
        # CLI, which is a confusing way to find out.
    }
