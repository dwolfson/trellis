"""Logging is configured, and the ways it silently was not stay fixed.

Before 2026-08-31 the root logger had no handlers and sat at WARNING, and
`uvicorn.run()` got no `log_config`. Nothing errored — `log.info(...)` was simply
discarded at the call site, and warnings reached stderr through
`logging.lastResort` with no timestamp, level or logger name.

Every assertion here corresponds to one of those silent failures.
"""
from __future__ import annotations

import logging

import pytest

from resource_explorer.observability import logging_setup as ls


@pytest.fixture(autouse=True)
def _restore_root():
    """Leave the root logger exactly as found — these tests mutate it."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_info_is_not_discarded():
    """The original defect. INFO was below the root level, so it went nowhere."""
    ls.configure_logging(force=True)
    ls.ring_handler.clear()

    logging.getLogger("resource_explorer.test").info("an info line")

    msgs = [r["message"] for r in ls.ring_handler.records()]
    assert "an info line" in msgs, (
        "INFO did not reach a handler — this is exactly the state that made "
        "every log.info() in the codebase invisible"
    )


def test_records_carry_the_fields_lastresort_dropped():
    """`lastResort`'s format is `%(message)s`: no time, no level, no logger.

    A warning you cannot attribute to a component or place in time is close to
    useless, which is why this asserts the fields rather than the formatting.
    """
    ls.configure_logging(force=True)
    ls.ring_handler.clear()
    logging.getLogger("resource_explorer.attribution").warning("careful")

    rec = ls.ring_handler.records(limit=1)[0]
    assert rec["level"] == "WARNING"
    assert rec["logger"] == "resource_explorer.attribution"
    assert rec["ts"], "no timestamp"


def test_configure_is_idempotent():
    """Two entry points call this (the CLI, and the web app at import). Neither
    may be able to double the handlers, which is how every line gets printed
    twice."""
    ls.configure_logging(force=True)
    before = len(logging.getLogger().handlers)

    second = ls.configure_logging()
    assert second["configured"] is False, second

    ls.configure_logging(force=True)
    assert len(logging.getLogger().handlers) == before, (
        "forcing reconfiguration added handlers instead of replacing its own"
    )


def test_reconfiguring_does_not_evict_someone_elses_handler():
    """pytest's caplog, and any host application, install their own handlers.
    `force=True` must remove only the ones this module installed."""
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)

    ls.configure_logging(force=True)
    assert foreign in root.handlers, "reconfiguration removed a handler it did not install"


def test_the_ring_is_bounded():
    """It is a debugging aid, not storage. Unbounded, a long survey would grow
    it without limit in a long-lived server process."""
    h = ls.RingBufferHandler(capacity=5)
    h.setFormatter(logging.Formatter(ls.LOG_FORMAT, datefmt=ls.DATE_FORMAT))
    for i in range(20):
        h.emit(logging.LogRecord("t", logging.INFO, __file__, i, f"line {i}", None, None))
    assert len(h) == 5
    assert h.records(limit=1)[0]["message"] == "line 19", "newest-first ordering lost"


def test_uvicorn_config_does_not_declare_root():
    """The bug this guards is invisible and asymmetric.

    `dictConfig` REPLACES root's handler list when a "root" key is present, and
    uvicorn applies its log_config after our setup runs. Declaring root here
    would tear out the console and ring handlers, so the log viewer would be
    empty under the server and full under the CLI.
    """
    cfg = ls.uvicorn_log_config()
    assert "root" not in cfg, (
        "uvicorn_log_config declares 'root', which would replace the handlers "
        "configure_logging installed — including the ring buffer"
    )
    assert cfg["disable_existing_loggers"] is False
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert cfg["loggers"][name]["propagate"] is True, (
            f"{name} must propagate, or server lines never reach the ring buffer"
        )
    assert cfg["loggers"]["uvicorn.access"]["level"] == "WARNING", (
        "access logging at INFO is one line per request and would drown the buffer"
    )


def test_the_cli_passes_a_log_config():
    """Configuring our own logging is not enough: uvicorn installs
    non-propagating handlers of its own unless told otherwise."""
    from pathlib import Path
    src = (Path(ls.__file__).resolve().parents[1] / "cli" / "main.py").read_text()
    run = src[src.index("uvicorn.run("):]
    run = run[:run.index(")") + 1]
    assert "log_config" in run, f"uvicorn.run has no log_config: {run!r}"


@pytest.mark.parametrize("raw,expected", [
    ("DEBUG", logging.DEBUG),
    ("warning", logging.WARNING),
    ("", logging.INFO),
    ("nonsense", logging.INFO),
])
def test_level_resolution_falls_back_rather_than_raising(raw, expected, monkeypatch):
    """A typo in RE_LOG_LEVEL must not stop the server booting."""
    monkeypatch.setenv("RE_LOG_LEVEL", raw)
    assert ls.resolve_level() == expected
