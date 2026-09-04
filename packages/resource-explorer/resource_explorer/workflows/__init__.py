"""Workflows — the units of work RE runs, with no web framework attached.

`docs/runtime-architecture-plan.md` §3 lists what was "web-only today": the
analysis-run-and-auto-publish flow, GitHub discovery, and curate
materialization all lived inside `web/routes/` modules, reachable only by
serving an HTTP request. That is why the CLI had no `analysis` command and no
`discovery` command at all — not because the core could not do it, but because
the code was on the wrong side of a route decorator.

Every function here:

* takes explicit arguments and returns a result dataclass — never a `Request`,
  never a pydantic response model, never an `HTTPException`;
* imports no FastAPI (`tests/test_workflows_are_fastapi_free.py` pins this);
* is safe to call from a request handler, from a Typer command, and from the
  run queue's worker thread, because none of those three is special to it.

The three callers do differ in what they do with a failure: a route turns it
into a status code, the CLI prints it, the queue writes it onto the `runs` row.
So a workflow reports failure in its result rather than raising for anything it
can anticipate — the same split `_run_single_analysis_sync` already made
between "an analysis-level failure" and "something genuinely unexpected".
"""
from __future__ import annotations
