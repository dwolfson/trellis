"""Keep one secret out of everything a run writes down.

Parity slice G2 (PI-016): a credential override for one run lives in memory
only. Two things can still carry it by accident, both of them somebody else's
error text: a driver exception that echoes the password it was handed, and the
log line written about that exception. This module is the two guards.

* `scrub(obj, secret)` returns a copy of any JSON-shaped structure with every
  occurrence of `secret` (and its encoded forms) inside a string replaced by
  `***`.
* `redacting_logs(secret)` is a context manager that, for the duration of a
  run, rewrites every log record that carries the secret AT CREATION, through
  the logging record factory. That covers every logger and every handler:
  loggers with their own handlers and propagate=False (uvicorn, Prefect),
  handlers added mid-run, and handlers attached to no root. Overlapping runs
  share one installed factory (a lock-guarded set of active secrets), so one
  run ending never unprotects another, and the original factory is restored
  when the last one ends.

Encoded forms covered: percent-encoding (a password inside a DSN), form
encoding, repr/escaped and JSON-escaped text. None of it stores, prints or
returns the secret. An empty secret is a no-op.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from contextlib import contextmanager

MASK = "***"


def variants(secret: str) -> list[str]:
    """The secret and its encoded spellings, longest first (so a long form is
    replaced before a shorter form inside it)."""
    if not secret or not isinstance(secret, str):
        return []
    forms = {
        secret,
        urllib.parse.quote(secret, safe=""),
        urllib.parse.quote(secret),
        urllib.parse.quote_plus(secret),
        repr(secret)[1:-1],
        secret.encode("unicode_escape").decode("ascii", "replace"),
        json.dumps(secret)[1:-1],
    }
    return sorted((f for f in forms if f), key=len, reverse=True)


def _mask(text: str, forms: list[str]) -> str:
    for f in forms:
        if f in text:
            text = text.replace(f, MASK)
    return text


def scrub(obj, secret: str):
    forms = variants(secret)
    return _scrub(obj, forms) if forms else obj


def _scrub(obj, forms):
    if isinstance(obj, str):
        return _mask(obj, forms)
    if isinstance(obj, dict):
        return {k: _scrub(v, forms) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, forms) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_scrub(v, forms) for v in obj)
    return obj


_lock = threading.Lock()
_active: dict[str, int] = {}          # secret -> number of overlapping runs holding it
_forms: list[str] = []
_original_factory = None


def _recompute() -> None:
    global _forms
    allf = {f for s in _active for f in variants(s)}
    _forms = sorted(allf, key=len, reverse=True)


def _factory(*args, **kwargs):
    record = _original_factory(*args, **kwargs)
    forms = _forms
    if not forms:
        return record
    try:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        if any(f in msg for f in forms):
            record.msg, record.args = _mask(msg, forms), ()
        if record.exc_info:
            text = logging.Formatter().formatException(record.exc_info)
            if any(f in text for f in forms):
                record.exc_text = _mask(text, forms)
                record.exc_info = None
        if record.exc_text and any(f in record.exc_text for f in forms):
            record.exc_text = _mask(record.exc_text, forms)
        if record.stack_info and any(f in record.stack_info for f in forms):
            record.stack_info = _mask(record.stack_info, forms)
    except Exception:  # redaction must never break logging
        pass
    return record


@contextmanager
def redacting_logs(secret: str):
    global _original_factory
    if not secret or not isinstance(secret, str):
        yield
        return
    with _lock:
        if not _active:
            _original_factory = logging.getLogRecordFactory()
            logging.setLogRecordFactory(_factory)
        _active[secret] = _active.get(secret, 0) + 1
        _recompute()
    try:
        yield
    finally:
        with _lock:
            _active[secret] -= 1
            if _active[secret] <= 0:
                del _active[secret]
            _recompute()
            if not _active:
                logging.setLogRecordFactory(_original_factory)
                _original_factory = None
