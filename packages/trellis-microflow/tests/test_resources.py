"""Unit tests for trellis_microflow.resources — no live dependencies."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager

import pytest

from trellis_microflow import ResourceProvider, resolve_resources


def _counting_provider(name: str, calls: list[str], yield_value=None):
    """Build a ResourceProvider whose acquire() records each call in
    `calls` and yields `yield_value` (or the provider's own name)."""

    @contextmanager
    def acquire():
        calls.append(name)
        yield yield_value if yield_value is not None else f"<{name}>"

    return ResourceProvider(name=name, acquire=acquire)


def test_resolves_needed_resources_and_returns_their_values():
    calls: list[str] = []
    providers = {
        "zipball_root": _counting_provider("zipball_root", calls, yield_value="/tmp/repo"),
        "db_connection": _counting_provider("db_connection", calls, yield_value="<conn>"),
    }
    with ExitStack() as stack:
        resolved = resolve_resources(stack, providers, {"zipball_root"})
    assert resolved == {"zipball_root": "/tmp/repo"}
    assert calls == ["zipball_root"]


def test_unrequested_providers_are_never_acquired():
    calls: list[str] = []
    providers = {
        "zipball_root": _counting_provider("zipball_root", calls),
        "db_connection": _counting_provider("db_connection", calls),
    }
    with ExitStack() as stack:
        resolve_resources(stack, providers, {"zipball_root"})
    assert calls == ["zipball_root"]  # db_connection never touched


def test_same_resource_requested_by_multiple_needs_still_acquired_exactly_once():
    # The dedup guarantee: the caller computes `needed` as a set (union
    # across every selected step) *before* calling resolve_resources, so
    # a resource named by N different steps is still acquired exactly
    # once — this test locks in that the function itself doesn't
    # re-acquire per "requester," since `needed` is a plain set.
    calls: list[str] = []
    providers = {"zipball_root": _counting_provider("zipball_root", calls)}
    needed = {"zipball_root"}  # as if 3 different steps all named it — still one entry
    with ExitStack() as stack:
        resolve_resources(stack, providers, needed)
    assert calls == ["zipball_root"]


def test_empty_needed_set_touches_nothing():
    calls: list[str] = []
    providers = {"zipball_root": _counting_provider("zipball_root", calls)}
    with ExitStack() as stack:
        resolved = resolve_resources(stack, providers, set())
    assert resolved == {}
    assert calls == []


def test_unknown_resource_name_raises_keyerror():
    providers: dict[str, ResourceProvider] = {}
    with ExitStack() as stack:
        with pytest.raises(KeyError):
            resolve_resources(stack, providers, {"nonexistent"})


def test_cleanup_runs_on_exitstack_close_not_before():
    entered = []
    exited = []

    @contextmanager
    def acquire():
        entered.append("zipball_root")
        try:
            yield "/tmp/repo"
        finally:
            exited.append("zipball_root")

    providers = {"zipball_root": ResourceProvider(name="zipball_root", acquire=acquire)}
    with ExitStack() as stack:
        resolve_resources(stack, providers, {"zipball_root"})
        assert entered == ["zipball_root"]
        assert exited == []  # still open while the caller's own work continues
    assert exited == ["zipball_root"]  # released when the caller's stack closes


def test_resource_provider_acquire_takes_no_arguments_by_contract():
    # Zero-argument by design (see ResourceProvider's own docstring) --
    # a caller binds its own context via closure/functools.partial when
    # building the provider, not by passing args through resolve_resources.
    captured = {}

    def build_provider(project_slug: str) -> ResourceProvider:
        @contextmanager
        def acquire():
            captured["slug"] = project_slug
            yield project_slug

        return ResourceProvider(name="zipball_root", acquire=acquire)

    providers = {"zipball_root": build_provider("odpi/trellis")}
    with ExitStack() as stack:
        resolved = resolve_resources(stack, providers, {"zipball_root"})
    assert resolved == {"zipball_root": "odpi/trellis"}
    assert captured == {"slug": "odpi/trellis"}
