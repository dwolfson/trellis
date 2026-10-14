"""RE's host side of a user step (extensibility brief 2c, 2c'): `SurveyStepHost`, the brief's `ExternalStep`.

A user step is an installable package outside RE: a plain `run(inputs) -> results` (level 1) and a
`StepManifest` that the Analytic Library's `SurveyStep` wrapper runs (level 2), found through the
`trellis.analytics` entry point. A Survey Definition (level 3) names it by `re_analysis_step`, like any built-in.

This module puts such steps BESIDE a resource type's step registry, never in it by hand:

- `attach()` reads the catalog entries GENERATED from manifests (`provided_by` in analysis_catalog.yaml, written
  by scripts/generate_external_step_entries.py) and the installed manifests, and fills, per step, the adapter's
  `re_analysis_steps` (so the executor dispatches it exactly as a built-in, inside `step_cost_observer.observe`,
  where the cost vector and the OpenLineage run event are taken), the step registry (`StepInfo`), the
  analysis->step map, and the results/headline readers (the one generic reader per annotation type,
  `annotation_readers`).
- An entry whose package is not installed here still attaches, as `NotInstalledStep`: running it fails with the
  sentence naming the package, rather than the card saying "no mapped survey step".
- An installed step with no catalog entry is attached as a runnable step and logged: run the generator.

What the host gives the wrapper: the resource, an ODS reader that can only read (the registry's own connection,
read-only at the database: Postgres `SET TRANSACTION READ ONLY`, SQLite `PRAGMA query_only`), and a store that
keeps the annotations with their envelope in `additionalProperties` (`ProjectRegistry.record_step_annotations`).
It never gives a password: the runner kwargs (`db_user`, `db_pwd`) stop here. It opens no connection to the
resource yet, so a step declaring the `connection` input is refused by the wrapper with that sentence.

The step's own annotations are not published to Egeria in this slice. A run's publish, when the resource has an
Egeria project, goes through the adapter's existing `publish` and its refusals (`person_write_refusal`, and the
publisher's own zone rules), with no publish code here.
"""
from __future__ import annotations

import logging
from datetime import datetime

log = logging.getLogger(__name__)

#: Problems found loading manifests, per resource type, for the honest sentence a page or the CLI can show.
LOAD_ERRORS: dict[str, str] = {}


class StepNotInstalled(RuntimeError):
    """The catalog names a step whose package is not installed in this environment."""


def _registry_ods(registry):
    """An ODS reader over the registry's own connection, read-only at the database for every query."""
    from trellis_analytics.readers.ods import OdsReader, OdsUnreadable

    class RegistryOds(OdsReader):
        def __init__(self, reg):
            super().__init__(reg.database_url)
            self._reg = reg

        def query(self, sql: str, params: tuple = ()) -> list[dict]:
            if not sql.lstrip().lower().startswith("select"):
                raise ValueError("the ODS reader runs SELECT statements only")
            try:
                with self._reg._conn() as conn:
                    if conn.is_postgres:
                        conn.execute("SET TRANSACTION READ ONLY")
                        return [dict(r) for r in conn.execute(sql, params).fetchall()]
                    conn.execute("PRAGMA query_only = ON")
                    try:
                        return [dict(r) for r in conn.execute(sql, params).fetchall()]
                    finally:
                        conn.execute("PRAGMA query_only = OFF")
            except Exception as exc:  # noqa: BLE001
                raise OdsUnreadable(f"the registry did not answer: {exc}") from exc

    return RegistryOds(registry)


class SurveyStepHost:
    """The runner the executor calls for a user step: `(entity, registry, **runner_kwargs) -> dict`."""

    def __init__(self, manifest, entity_type: str, provided_by: dict | None = None):
        self.manifest = manifest
        self.entity_type = entity_type
        self.provided_by = dict(provided_by or {})

    def __call__(self, entity, registry, **runner_kwargs) -> dict:
        from trellis_analytics.step import HostContext, SurveyStep

        step = self.manifest.name
        # The run's own time when the executor stamped one (a database scan's), so the annotations name the run.
        run = runner_kwargs.get("scan_surveyed_at") or datetime.utcnow().isoformat()

        def store(annotations) -> int:
            measured_at = annotations[0].envelope.measured_at if annotations else run
            return registry.record_step_annotations(
                self.entity_type, entity.slug, step, run=run, measured_at=measured_at,
                annotations=[a.to_record() for a in annotations])

        host = HostContext(resource_type=self.entity_type, slug=entity.slug, producing_run=run,
                           ods=_registry_ods(registry), connect=None, store=store)
        annotations = SurveyStep(self.manifest).run(host)
        counts: dict[str, int] = {}
        for a in annotations:
            counts[a.envelope.result_state.value] = counts.get(a.envelope.result_state.value, 0) + 1
        return {
            "step_annotations": [a.to_record() for a in annotations],
            "annotation_count": len(annotations),
            "state_counts": counts,
            "producer": {"step": step, "version": self.manifest.version,
                         "package": self.provided_by.get("package", "")},
        }


#: The brief's name for the adapter; `SurveyStepHost` is the name the three-levels framing gives it.
ExternalStep = SurveyStepHost


class NotInstalledStep:
    """The runner for a catalogued step whose package is absent: it says so, naming the package."""

    def __init__(self, provided_by: dict, step_key: str):
        self.provided_by = dict(provided_by)
        self.step_key = step_key

    def __call__(self, entity, registry, **_):
        p = self.provided_by
        raise StepNotInstalled(
            f"step not installed here: '{self.step_key}' comes from package {p.get('package') or '(unnamed)'} "
            f"{p.get('version', '')}; install it into this environment (and the Prefect worker's, when one runs "
            "steps): installing it is registering it")


def discover_steps(entity_type: str) -> dict:
    """name -> StepManifest for every installed step that measures `entity_type`. Empty when the Analytic
    Library is not installed; a broken entry point is logged with its name and recorded in LOAD_ERRORS."""
    try:
        from trellis_analytics.discovery import discover
    except ImportError:
        return {}
    try:
        found = discover()
    except Exception as exc:  # noqa: BLE001 - one broken package must not stop RE from starting
        LOAD_ERRORS[entity_type] = str(exc)
        log.error("user steps not loaded for %s: %s", entity_type, exc)
        return {}
    LOAD_ERRORS.pop(entity_type, None)
    return {n: m for n, m in found.items()
            if getattr(m, "kind", "") == "step" and entity_type in (m.resource_types or [])}


def catalog_entry(manifest, origin: dict) -> dict:
    """The analysis_catalog.yaml entry for one step manifest, in the catalog's own vocabulary. The generator
    writes exactly this; a test holds the committed file to it."""
    m = manifest
    return {
        "id": m.name,
        "name": m.display_name or m.name.replace("_", " ").title(),
        "description": m.description,
        "resource_types": list(m.resource_types),
        "intent": m.stage,
        "perspectives": list(m.perspectives),
        "annotation_types": [m.annotation_type],
        # RE runs it (its own engine), so `local` in this catalog's sense; where it reads is provided_by.source.
        "source": "local",
        "run_time": "fast",
        # A step never runs in the web process (brief 3a): queued, through the run queue.
        "availability": "queued",
        "action": "survey",
        "target_shape": "whole_resource_only",
        "recommended": False,
        "egeria_registration": {"candidate": True, "native_process_ref": None},
        "provided_by": {
            "package": origin.get("package", ""), "entry_point": origin.get("entry_point", ""),
            "step": m.name, "version": m.version, "kind": m.kind, "source": m.source,
            "credential_tier": m.credential_tier, "questions": list(m.questions), "purposes": list(m.purposes),
        },
    }


def _step_info(step_key: str, description: str, annotation_type: str, source: str, tier: str):
    from resource_explorer.surveyors.repo_survey_definition_adapter import StepInfo

    return StepInfo(step_key, None, description, [annotation_type],
                    # An ODS step reads RE's own stored rows: no fetch from the resource.
                    fetch_cost="none" if source == "ods" else "api", compute_cost="low",
                    requires_capability="" if tier in ("", "none") else "read")


def attach(entity_type: str, adapter, step_registry: dict, step_map: dict, results_map: dict,
           kinds: dict, headline_map: dict) -> list[str]:
    """Attach every generated catalog entry's step (installed or not) and every installed step to one resource
    type's maps. Idempotent: a second call replaces what the first attached. Returns the step keys attached."""
    from resource_explorer.surveyors import annotation_readers
    from resource_explorer.surveyors.analysis_catalog_reader import _load
    from resource_explorer.surveyors.repo_survey_definition_adapter import AnalysisKind, AnalysisKindResults

    found = discover_steps(entity_type)
    attached: list[str] = []
    for entry in _load().get(entity_type, []):
        if not entry.provided_by:
            continue
        step_key = entry.provided_by.get("step") or entry.id
        annotation_type = (entry.annotation_types or ["ResourceMeasureAnnotation"])[0]
        manifest = found.get(step_key)
        runner = (SurveyStepHost(manifest, entity_type, entry.provided_by) if manifest
                  else NotInstalledStep(entry.provided_by, step_key))
        adapter.re_analysis_steps[step_key] = runner
        adapter.re_analysis_step_info[step_key] = {"description": entry.description,
                                                   "annotation_types": [annotation_type]}
        step_registry[step_key] = _step_info(step_key, entry.description, annotation_type,
                                             entry.provided_by.get("source", ""),
                                             entry.provided_by.get("credential_tier", ""))
        reader = annotation_readers.results_reader(entity_type, step_key, annotation_type)
        headline = annotation_readers.headline_reader(entity_type, step_key, annotation_type)
        step_map[entry.id] = [step_key]
        results_map[entry.id] = (reader, None)
        headline_map[entry.id] = headline
        kinds[entry.id] = AnalysisKind(entry.id, [step_key], results=AnalysisKindResults(
            reader, None, render="custom", headline_reader=headline, live_read=True))
        attached.append(step_key)
    for name, manifest in found.items():
        if name in attached:
            continue
        log.warning("installed step '%s' has no analysis catalog entry; it can run from a Survey Definition but "
                    "shows no card: run scripts/generate_external_step_entries.py", name)
        adapter.re_analysis_steps[name] = SurveyStepHost(manifest, entity_type)
        adapter.re_analysis_step_info[name] = {"description": manifest.description,
                                               "annotation_types": [manifest.annotation_type]}
        step_registry[name] = _step_info(name, manifest.description, manifest.annotation_type,
                                         manifest.source, manifest.credential_tier)
        attached.append(name)
    return attached


def refresh(entity_type: str = "database") -> list[str]:
    """Discover again and re-attach (after a package is installed into a running process, or in a test)."""
    if entity_type != "database":
        raise ValueError(f"user steps attach to databases only so far, not {entity_type}")
    from resource_explorer.surveyors.analysis_catalog_reader import clear_cache
    from resource_explorer.surveyors.database import survey_definition_adapter as db

    clear_cache()
    return attach("database", db._ADAPTER, db.DATABASE_STEP_REGISTRY, db.DATABASE_ANALYSIS_RE_STEP_MAP,
                  db.DATABASE_ANALYSIS_RESULTS_MAP, db.DATABASE_ANALYSIS_KINDS, db.DATABASE_ANALYSIS_HEADLINE_MAP)
