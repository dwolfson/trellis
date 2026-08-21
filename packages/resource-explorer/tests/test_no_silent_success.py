"""Ratchet test against the "broad except, log-only body, still returns
success" shape — a defect reported as an ordinary operational hiccup.

Two real bugs in one session had exactly this shape:

  * `EgeriaDatabaseSurveyor._catalog_and_survey` caught the stale-GUID 404
    from `_initiate_survey`, logged it at WARNING, and returned success with
    `server_survey_guid=''`. The catalog work genuinely had succeeded, so a
    hard failure would have been wrong too — but nothing distinguished "no
    server survey because none was requested" from "no server survey because
    Egeria rejected a bad GUID" anywhere a caller could see.
  * `surveyors/prefect_adapter.py::run_prefect_step` raised
    `UnboundLocalError` on the very first line of its Prefect API branch (a
    closure-cell bug: a redundant inner `import asyncio` turned the name into
    a cell the first line read before anything wrote to it). The broad
    `except Exception` logged "Prefect API dispatch failed" and fell back to
    local execution — indistinguishable from Prefect simply being
    unreachable. The API path had therefore never executed, for the entire
    life of the integration, and every run "succeeded" via the fallback.

Neither bug was a missing test for the function's happy path — both
functions had one. The gap was structural: a broad `except` whose body only
logs, inside a function whose contract is to hand back a result, silently
converts "this failed" into "this succeeded, technically." No amount of
testing the success path finds that, because the success path is exactly
what still runs.

This file walks resource_explorer with `ast` and flags every site with that
shape. It does not fix them — 112 existing sites were found on first run,
(an initial hand count said 115; that attributed handlers inside nested
functions to every enclosing function rather than the nearest one, and
counted three of them twice)
far too many to fix as a side effect of writing a test — so instead it
ratchets: a baseline in `no_silent_success_baseline.json` records where they
are today, keyed by "<path>::<function>" (never by line number, which churns
on unrelated edits and would make the baseline stale within a day, or by
column/count-of-total, which would hide *which* function regressed). The
test fails if a new key appears, if an existing key's count goes up, or if
the baseline still lists a key that's gone — so the file can only shrink,
never rot, and never silently grow.
"""
from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1] / "resource_explorer"
BASELINE_PATH = Path(__file__).resolve().parent / "no_silent_success_baseline.json"

# Exact match only, on the called function's own name (the attribute name for
# `x.y()`, the bare name otherwise) — not a substring test. A helper like
# `self._log_error(...)` records something beyond a log line by definition
# (it is at minimum a distinct, greppable call site with its own contract),
# so it must NOT be treated as equivalent to `log.error(...)`.
LOG_CALL_NAMES = {
    "debug", "info", "warning", "warn", "error", "exception", "critical", "print",
}


def _call_name(call: ast.Call) -> str | None:
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _is_log_only_body(body: list[ast.stmt]) -> bool:
    """True only if every statement is a no-op `pass` or a call to something
    in LOG_CALL_NAMES. A `return`, `raise`, assignment, or any other call
    (including a differently-named logging helper) means the handler does
    more than log — which is exactly the distinction that matters here."""
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if _call_name(stmt.value) in LOG_CALL_NAMES:
                continue
        return False
    return True


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """Bare `except:` or `except Exception:` only. A named subclass, or a
    tuple of specific exceptions, is a deliberate decision about what's
    expected to fail and is not what hid either bug — those two were both
    `except Exception`, wide enough to swallow a bug wearing a runtime
    error's clothes."""
    if handler.type is None:
        return True
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def _fn_returns_value(fn: ast.AST) -> bool:
    # A generator's `yield` doesn't count — only an explicit `return <expr>`
    # is the "handed back a success value" contract this test is about.
    return any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(fn))


def find_silent_success_handlers(tree: ast.AST) -> list[tuple[str, ast.ExceptHandler]]:
    """Yield (enclosing_function_name, handler) for every broad, log-only
    except handler whose nearest enclosing FunctionDef/AsyncFunctionDef
    returns a value somewhere in its body.

    "Nearest enclosing" (not "any enclosing"): a handler inside a nested
    helper function is attributed to that helper, not to whatever function
    the helper is defined in — the helper is what actually owns the return
    contract being violated.
    """
    results: list[tuple[str, ast.ExceptHandler]] = []

    def visit(node: ast.AST, fn_stack: list[ast.AST]) -> None:
        is_fn = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        new_stack = fn_stack + [node] if is_fn else fn_stack
        if isinstance(node, ast.ExceptHandler):
            if _is_broad(node) and _is_log_only_body(node.body) and new_stack:
                enclosing = new_stack[-1]
                if _fn_returns_value(enclosing):
                    results.append((enclosing.name, node))
        for child in ast.iter_child_nodes(node):
            visit(child, new_stack)

    visit(tree, [])
    return results


def _iter_py_files():
    return sorted(PKG_ROOT.rglob("*.py"))


def _current_findings() -> dict[str, int]:
    """Map "<relative_path>::<function_name>" -> count of flagged handlers,
    across the whole package. Stable across line-number churn by design —
    two functions of the same name in different modules stay distinct
    because the path is part of the key."""
    counts: dict[str, int] = {}
    for path in _iter_py_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        rel = path.relative_to(PKG_ROOT.parent).as_posix()
        for fn_name, _handler in find_silent_success_handlers(tree):
            key = f"{rel}::{fn_name}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _baseline() -> dict[str, int]:
    return json.loads(BASELINE_PATH.read_text())


class TestDetectorSemantics:
    """Verify the detector on constructed shapes before trusting it on the
    real tree — including the two bugs that motivated this file."""

    def test_flags_the_database_surveyor_bug_shape(self):
        src = textwrap.dedent('''
            def _catalog_and_survey(self, db_entity, registry):
                server_survey_guid = ""
                if server_guid:
                    try:
                        server_survey_guid = self._initiate_survey("PostgreSQL Server", server_guid)
                        log.info(f"Egeria server survey initiated: {server_survey_guid}")
                    except Exception as exc:
                        log.warning(f"Server survey initiation failed (non-fatal): {exc}")
                return {"server_survey_guid": server_survey_guid}
        ''')
        found = find_silent_success_handlers(ast.parse(src))
        assert [name for name, _ in found] == ["_catalog_and_survey"]

    def test_flags_the_prefect_adapter_bug_shape(self):
        src = textwrap.dedent('''
            def run_prefect_step(entity_type, slug, step_name, runner_kwargs):
                if config.prefect.enabled:
                    try:
                        loop = asyncio.get_running_loop()
                        return asyncio.run(_run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
                    except Exception as e:
                        logging.warning(
                            "Prefect API dispatch failed (%s), falling back: %s",
                            type(e).__name__, e, exc_info=True,
                        )
                return re_survey_flow(entity_type, slug, step_name, runner_kwargs)
        ''')
        found = find_silent_success_handlers(ast.parse(src))
        assert [name for name, _ in found] == ["run_prefect_step"]

    def test_does_not_flag_a_narrow_except(self):
        """A specific exception class is a deliberate contract, not a net
        cast wide enough to also catch a bug."""
        src = textwrap.dedent('''
            def do_thing():
                try:
                    risky()
                except ConnectionError as exc:
                    log.warning("failed: %s", exc)
                return {"ok": True}
        ''')
        assert find_silent_success_handlers(ast.parse(src)) == []

    def test_does_not_flag_a_handler_that_reraises(self):
        """A re-raise propagates the failure — nothing is hidden."""
        src = textwrap.dedent('''
            def do_thing():
                try:
                    risky()
                except Exception as exc:
                    log.warning("failed: %s", exc)
                    raise
                return {"ok": True}
        ''')
        assert find_silent_success_handlers(ast.parse(src)) == []

    def test_does_not_flag_a_handler_that_returns_a_value(self):
        """Returning an explicit failure value (e.g. an error result) is
        exactly the fix this test wants to see, not the bug it hunts."""
        src = textwrap.dedent('''
            def do_thing():
                try:
                    risky()
                except Exception as exc:
                    log.warning("failed: %s", exc)
                    return {"ok": False, "error": str(exc)}
                return {"ok": True}
        ''')
        assert find_silent_success_handlers(ast.parse(src)) == []

    def test_does_not_flag_log_only_handler_in_a_function_returning_nothing(self):
        """No return value means no success to falsely report — there is no
        caller reading a result and being misled by it."""
        src = textwrap.dedent('''
            def do_thing():
                try:
                    risky()
                except Exception as exc:
                    log.warning("failed: %s", exc)
        ''')
        assert find_silent_success_handlers(ast.parse(src)) == []


class TestRatchet:
    """The baseline may only shrink. New sites, or growth at an existing
    site, must fail here rather than in a code review months later."""

    def test_no_new_silent_success_sites(self):
        current = _current_findings()
        baseline = _baseline()

        new_keys = sorted(set(current) - set(baseline))
        grown = sorted(
            k for k in set(current) & set(baseline) if current[k] > baseline[k]
        )

        assert not new_keys and not grown, (
            "New or worsened broad-except/log-only/value-returning site(s) found:\n"
            + "\n".join(f"  NEW  {k}: {current[k]}" for k in new_keys)
            + ("\n" if new_keys and grown else "")
            + "\n".join(
                f"  GREW {k}: {baseline[k]} -> {current[k]}" for k in grown
            )
            + "\n\nFor each site, either: (1) record something observable in the "
            "handler — a metric, an error field on the returned result, a status "
            "flag the caller can branch on — so a failure there is distinguishable "
            "from ordinary success; or (2) narrow the `except` to the specific "
            "exception(s) actually expected, so an unrelated bug isn't silently "
            "absorbed; or (3), if the site is genuinely best-effort and this is a "
            "deliberate, reviewed decision, add it to "
            "tests/no_silent_success_baseline.json explicitly rather than letting "
            "this test paper over it."
        )

    def test_baseline_has_no_stale_entries(self):
        """A key that no longer exists is not evidence of nothing — it's
        evidence the baseline wasn't updated when the site was fixed, which
        would let a *regression* back to the same key hide as "already
        accounted for." The baseline must track reality or it isn't a
        ratchet."""
        current = _current_findings()
        baseline = _baseline()

        stale = sorted(set(baseline) - set(current))
        assert not stale, (
            "Baseline entries for sites that no longer exist (fixed, renamed, or "
            "removed) — delete them from tests/no_silent_success_baseline.json "
            f"so the baseline reflects only what's still true:\n"
            + "\n".join(f"  {k}: {baseline[k]}" for k in stale)
        )

    def test_total_does_not_exceed_baseline(self):
        """The headline number: explicit direction of travel. Individual key
        checks above are more precise, but this is the one number that
        should only ever go down."""
        current_total = sum(_current_findings().values())
        baseline_total = sum(_baseline().values())
        assert current_total <= baseline_total, (
            f"Total silent-success sites grew from {baseline_total} to "
            f"{current_total} — this count must never increase."
        )
