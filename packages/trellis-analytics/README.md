# trellis-analytics (Analytic Library)

Routines and steps with a result envelope, discovered through the
`trellis.analytics` entry point. Pieces 2a (library) and 2b (the
`curation_coverage` routine) of `docs/extensibility-walking-skeleton-brief.md`.

- `trellis_analytics.envelope`: `Envelope` and the four states.
- `trellis_analytics.manifest`: `RoutineManifest` / `StepManifest`, subclasses of
  pyegeria's `AnalyticFunctionSpec` carrying the five additive fields themselves.
- `trellis_analytics.discovery`: `discover()` and `register()` (into pyegeria's registry).
- `trellis_analytics.readers.ods`: read-only access to RE's registry (SQLite file or Postgres).
- `trellis_analytics.routines.curation_coverage`: published / not yet / blocked.

- `trellis_analytics.portal`: host 3, the Portal tile. `curation_coverage_tile` reshapes the routine's result (no
  computing of its own) and `report_specs()` is the tile's `FormatSet`; load it with
  `PYEGERIA_REPORT_SPEC_MODULES=trellis_analytics.portal:report_specs`.
- `examples/`: host 1 `curation_coverage.py`, host 2 `curation_coverage.ipynb` (papermill: `slug`, `ods_url`),
  and `curation_coverage_tile.md`, the tile's spec as a Dr.Egeria report-spec document (the Advisor's parser reads it to
  the same `FormatSet`).

- `trellis_analytics.step`: `SurveyStep`, level 2 of a step (brief 2c'): declared inputs only, never a password,
  read-only on the resource at most, the envelope on every result, the host's store.
- `trellis_analytics.declare`: the Dr.Egeria declaration of a step, generated from its manifest (never run here).
- `examples/steps/database_staleness/`: piece 2c, a user step as its own installable package (`run(inputs)` plus
  a `StepManifest` entry point). Resource Explorer runs it through `survey_step_host`; its catalog entry and
  Dr.Egeria document come from `packages/resource-explorer/scripts/generate_external_step_entries.py`.

No executor: a routine is called directly; a step is run by a host.

```python
from trellis_analytics.readers.ods import OdsReader
from trellis_analytics.routines import curation_coverage
r = curation_coverage(OdsReader("postgresql://..."), "database", "coco_pharma")
print(r.envelope.result_state, r.to_dict())
```
