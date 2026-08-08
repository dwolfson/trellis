"""
Externalized table of Egeria Technology Types and their known native
governance action processes/types — loaded from
config/technology_type_processes.yaml, so adding support for a new
Technology Type or a newly-authored native survey/catalog process is a
config change, not a code change here.

See that file's header comment for the schema and the meaning of `kind`.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "configdata" / "technology_type_processes.yaml"

KIND_SURVEY_EXISTING = "survey_existing"
KIND_CATALOG_AND_SURVEY = "catalog_and_survey"
KIND_DELETE = "delete"


@dataclass(frozen=True)
class NativeProcess:
    qualified_name: str
    display_name: str
    kind: str
    description: str = ""


@functools.lru_cache(maxsize=1)
def _load(config_path: Path = _DEFAULT_CONFIG_PATH) -> dict[tuple[str, str], list[NativeProcess]]:
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    result: dict[tuple[str, str], list[NativeProcess]] = {}
    for tt in raw.get("technology_types") or []:
        key = (tt.get("entity_type", ""), tt.get("name", ""))
        result[key] = [
            NativeProcess(
                qualified_name=p["qualified_name"],
                display_name=p.get("display_name", p["qualified_name"]),
                kind=p.get("kind", "unknown"),
                description=(p.get("description") or "").strip(),
            )
            for p in tt.get("processes") or []
        ]
    return result


def get_native_processes(entity_type: str, technology_type: str) -> list[NativeProcess]:
    """All known native processes for this (entity_type, technology_type) pair
    (Egeria's real Technology Type display name — see the config file's
    header), or [] if none are configured yet."""
    return _load().get((entity_type, technology_type), [])


def get_process_by_kind(entity_type: str, technology_type: str, kind: str) -> NativeProcess | None:
    """First configured process of a given kind for this (entity_type,
    technology_type) pair, or None if not configured."""
    for p in get_native_processes(entity_type, technology_type):
        if p.kind == kind:
            return p
    return None


def clear_cache() -> None:
    """Testing hook — the loader result is cached via lru_cache."""
    _load.cache_clear()
