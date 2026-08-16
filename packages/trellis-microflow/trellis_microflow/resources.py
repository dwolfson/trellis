"""Shared-resource acquisition/dedup primitives — see the package README
and docs/unified-survey-execution-model-plan.md's D6 for the full design
and the concrete motivating case (resource-explorer's repo-survey
zipball, shared across whichever microflows selected in one run need
file/data content, downloaded exactly once regardless of how many)."""
from __future__ import annotations

from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from typing import Callable, Mapping


@dataclass(frozen=True)
class ResourceProvider:
    """Names a shared resource and how to acquire it.

    `acquire` is a zero-argument callable returning a context manager —
    `__enter__` yields the resource value (a `Path`, a client instance,
    a connection, ...), `__exit__` does cleanup (e.g. removing a
    tempdir). Deliberately the standard `contextlib` idiom, not a
    bespoke acquire/release pair or a separate teardown-registration
    mechanism.

    Zero-argument by design: a caller that needs to bind its own context
    (a project, a registry, a connection string — anything this package
    has no business knowing about) does so via a closure or
    `functools.partial` when constructing the `ResourceProvider`, not by
    passing arguments through `resolve_resources`. This is what keeps
    this package genuinely generic across apps rather than shaped around
    resource-explorer's own domain types.
    """
    name: str
    acquire: Callable[[], AbstractContextManager]


def resolve_resources(
    stack: ExitStack,
    providers: Mapping[str, ResourceProvider],
    needed: set[str],
) -> dict[str, object]:
    """Resolve each name in `needed` via its provider exactly once,
    entering each into `stack` so cleanup happens together when the
    caller's own `with ExitStack() as stack:` block exits.

    Callers get the "resolve once, dedupe across however many steps
    asked for it" guarantee for free: compute `needed` as the union of
    every selected step's resource requirements *before* calling this
    (not per-step), and pass the same `stack` across the whole run — each
    named resource is then acquired exactly once, no matter how many
    steps requested it, and released together when the run completes.

    Parameters
    ----------
    stack : the caller's own ExitStack, spanning the whole run (not just
        resource acquisition) — resources must stay open for as long as
        any step that uses them is still executing.
    providers : the full registry of known providers, keyed by name.
    needed : the resource names actually required by the steps selected
        for this run — a strict subset of `providers`' keys, computed by
        the caller.

    Returns
    -------
    {resource_name: resource_value} for every name in `needed`.

    Raises
    ------
    KeyError if `needed` names a resource with no registered provider —
    deliberately not swallowed; a step declaring a resource dependency
    that doesn't exist is a caller-side bug, not a runtime condition to
    degrade gracefully from.
    """
    return {name: stack.enter_context(providers[name].acquire()) for name in needed}
