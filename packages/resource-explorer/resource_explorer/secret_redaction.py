"""Keep one secret out of everything a run writes down.

Parity slice G2 (PI-016): a credential override for one run lives in memory
only. Two things can still carry it by accident, both of them somebody else's
error text: a driver exception that echoes the password it was handed, and the
log line written about that exception. This module is the two guards.

* `scrub(obj, secret)` returns a copy of any JSON-shaped structure with every
  occurrence of `secret` inside a string replaced by `***`.
* `redacting_logs(secret)` is a context manager that, for the duration of a
  run, installs a filter on every root-logger handler that rewrites the
  message and the formatted traceback of any record carrying `secret`.

Neither one stores, prints or returns the secret. An empty secret is a no-op.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

MASK = "***"


def scrub(obj, secret: str):
    if not secret or not isinstance(secret, str):
        return obj
    if isinstance(obj, str):
        return obj.replace(secret, MASK)
    if isinstance(obj, dict):
        return {k: scrub(v, secret) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, secret) for v in obj]
    if isinstance(obj, tuple):
        return tuple(scrub(v, secret) for v in obj)
    return obj


class _RedactFilter(logging.Filter):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        if self._secret in msg:
            record.msg, record.args = msg.replace(self._secret, MASK), ()
        if record.exc_info:
            text = logging.Formatter().formatException(record.exc_info)
            if self._secret in text:
                record.exc_text = text.replace(self._secret, MASK)
                record.exc_info = None
        if record.exc_text and self._secret in record.exc_text:
            record.exc_text = record.exc_text.replace(self._secret, MASK)
        return True


@contextmanager
def redacting_logs(secret: str):
    if not secret or not isinstance(secret, str):
        yield
        return
    flt = _RedactFilter(secret)
    handlers = list(logging.getLogger().handlers)
    for h in handlers:
        h.addFilter(flt)
    try:
        yield
    finally:
        for h in handlers:
            h.removeFilter(flt)
