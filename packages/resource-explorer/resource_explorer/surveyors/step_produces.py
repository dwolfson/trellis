"""Which step fills which table — the inverse of `StepInfo.produces`.

Design §17.1, condition 2. Preconditions name **stored data**, deliberately
(`step_preconditions`'s own docstring: so the check does not encode an
execution order it cannot enforce). That is the right vocabulary for the
*check* and the wrong one for the *remedy*: a person told "no parsed
dependencies" wants to know what to run, and until now the answer was a
producer step key typed by hand next to each check, in a module that is
otherwise careful never to name steps.

**The reconciliation, stated plainly, because the design leaves room for
judgement here.** `PRODUCES` becomes the single declaration and
`step_preconditions` derives from it:

* a step declares the tables it writes, on itself, where its author already
  knows the answer;
* this module inverts that at import into `table -> step_key`;
* `step_preconditions.PRECONDITIONS` declares the *table* a check reads and
  no longer carries a producer string at all — `producer_of(table)` answers
  that, so the pair cannot drift.

The precondition-checking mechanism itself is untouched: it still asks
whether stored data exists, and an unmet precondition still produces a named,
emitted skip. Only *who knows the remedy* moved.

**Two steps producing one table is an error, not a merge.** The resolver's
question is "run which one?", and a map that silently keeps the last writer
would answer it wrongly and invisibly. `validate()` raises instead, and is
called at import from the one place that builds the combined index.

**Several registries, one index.** Repo steps live in
`repo_survey_definition_adapter.STEP_REGISTRY`; database steps in
`database/survey_definition_adapter.DATABASE_STEP_REGISTRY`. They are
disjoint by construction (a repo step never writes `database_tables`), so
one flat index across both is safe and is what the resolver wants — it is
handed a registry for the resource type it is resolving within, and the
precondition's remedy text is looked up globally so a cross-type mistake
reads as a wrong-type producer rather than as "nothing produces this".
"""
from __future__ import annotations

import logging
from typing import Mapping

log = logging.getLogger(__name__)


class DuplicateProducerError(RuntimeError):
    """Two steps declare `produces` over the same table.

    Not a warning. The inverse map exists to answer "which step do I run to
    fill this", and there is no honest answer when two claim it.
    """


def invert(registry: Mapping[str, object]) -> dict[str, str]:
    """{table: step_key} from one step registry's `produces` declarations."""
    out: dict[str, str] = {}
    for step_key, info in registry.items():
        for table in getattr(info, "produces", ()) or ():
            if table in out and out[table] != step_key:
                raise DuplicateProducerError(
                    f"both {out[table]!r} and {step_key!r} declare "
                    f"produces={table!r} — a precondition on that table cannot "
                    "say which one to run. Declare it on the step that actually "
                    "writes the rows the precondition counts."
                )
            out[table] = step_key
    return out


#: {entity_type: why it could not be read}, for the most recent `_registries()`
#: call. Observable on purpose: "no step declares this table" and "the registry
#: that would have declared it could not be imported" are different facts, and
#: only the first one is a declaration gap. `unavailable()` is how a caller — or
#: a person reading a remedy that says nothing can satisfy a precondition —
#: tells them apart.
_UNAVAILABLE: dict[str, str] = {}


def unavailable() -> dict[str, str]:
    """Registries that could not be imported on the last lookup, and why.

    Empty is the normal case and means every registry was read. A non-empty
    result means any "nothing produces this table" answer from this module is
    unreliable for that resource type.
    """
    return dict(_UNAVAILABLE)


def _registries() -> dict[str, Mapping[str, object]]:
    """Every step registry that carries `produces`, keyed by entity type.

    Imported lazily and defensively: `repo_survey_definition_adapter` pulls in
    the whole repo surveyor stack, and the database adapter pulls in pyegeria.
    A checkout where one of those cannot import must not take the other's
    producer lookups down with it — a missing registry degrades to "nothing
    produces this table", which the precondition text already handles, rather
    than to an ImportError at the top of a survey.

    …but it does not degrade SILENTLY. A failed import is recorded in
    `_UNAVAILABLE`, because a degraded lookup that reads exactly like an
    honest "nothing declares this" is the shape this codebase keeps removing.
    """
    out: dict[str, Mapping[str, object]] = {}
    for entity_type, importer in (
        ("repo", _import_repo_registry),
        ("database", _import_database_registry),
    ):
        try:
            out[entity_type] = importer()
            _UNAVAILABLE.pop(entity_type, None)
        except Exception as exc:  # pragma: no cover - import guard
            _UNAVAILABLE[entity_type] = str(exc)
            log.warning(
                "%s step registry unavailable for producer lookup — every "
                "precondition over its tables will report that nothing "
                "produces them: %s", entity_type, exc)
    return out


def _import_repo_registry() -> Mapping[str, object]:
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        STEP_REGISTRY,
    )

    return STEP_REGISTRY


def _import_database_registry() -> Mapping[str, object]:
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        DATABASE_STEP_REGISTRY,
    )

    return DATABASE_STEP_REGISTRY


def index() -> dict[str, str]:
    """{table: step_key} across every registry. Built on each call rather than
    cached at import: `STEP_REGISTRY` is monkeypatched by several tests, and a
    module-level cache would read past that the way `REPO_ANALYSIS_HEADLINE_MAP`
    did (see `ResourceTypeAdapter.analysis_headline_map`'s own note). The maps
    are tens of entries; building one is free next to any step it gates."""
    combined: dict[str, str] = {}
    for entity_type, registry in _registries().items():
        for table, step_key in invert(registry).items():
            if table in combined and combined[table] != step_key:
                raise DuplicateProducerError(
                    f"{combined[table]!r} and {step_key!r} (in the {entity_type} "
                    f"registry) both declare produces={table!r}"
                )
            combined[table] = step_key
    return combined


def producer_of(table: str) -> str:
    """The step that fills `table`, or "" when nothing declares it.

    "" is a real answer and the caller must render it as one: a precondition
    over a table no step claims is unsatisfiable by running something, which
    is different from, and more useful than, naming a step that does not
    exist.
    """
    return index().get(table, "")


def step_info(entity_type: str, step_key: str):
    """The `StepInfo` for one step, or None. The resolver's way of reaching a
    producer's own costs and preconditions without knowing which module the
    registry lives in."""
    return _registries().get(entity_type, {}).get(step_key)


def registry_for(entity_type: str) -> Mapping[str, object]:
    return _registries().get(entity_type, {})


def validate() -> None:
    """Raise if the declarations cannot form an index. Called by
    `tests/test_step_produces.py`; deliberately NOT called at import, because
    a duplicate declaration should fail a test run loudly rather than make
    the package unimportable for everyone including the person fixing it."""
    index()
