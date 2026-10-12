"""Find manifests through the `trellis.analytics` entry-point group, and register them in pyegeria's registry."""
from __future__ import annotations

from importlib.metadata import entry_points

from trellis_analytics.manifest import _TrellisManifest

GROUP = "trellis.analytics"


def discover() -> dict[str, _TrellisManifest]:
    """name -> manifest for every entry point. An entry point may name a manifest, or a callable returning
    one manifest or a list of them. A broken entry point raises, naming it: a silent skip would be absence
    shown as 'nothing installed'."""
    found: dict[str, _TrellisManifest] = {}
    for ep in entry_points(group=GROUP):
        try:
            obj = ep.load()
            if callable(obj) and not isinstance(obj, _TrellisManifest):
                obj = obj()
            items = obj if isinstance(obj, (list, tuple)) else [obj]
            for m in items:
                if not isinstance(m, _TrellisManifest):
                    raise TypeError(f"{type(m).__name__} is not a RoutineManifest or StepManifest")
                found[m.name] = m
        except Exception as exc:  # noqa: BLE001 - re-raised with the entry point named
            raise RuntimeError(f"entry point {GROUP}:{ep.name} ({ep.value}) failed to load: {exc}") from exc
    return found


def register() -> list[str]:
    """Register discovered manifests into pyegeria's analytic registry; names already present are skipped
    (so calling it twice is harmless) and returned names are the ones added."""
    from pyegeria.view.analytic_registry import get_analytic_registry, register_analytic_functions
    existing = set(get_analytic_registry().keys())
    new = {n: m for n, m in discover().items() if n not in existing}
    if new:
        register_analytic_functions(new, source=GROUP)
    return sorted(new)
