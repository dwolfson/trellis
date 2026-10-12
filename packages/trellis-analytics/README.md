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

No executor: a routine is called directly; a step is run by a host.

```python
from trellis_analytics.readers.ods import OdsReader
from trellis_analytics.routines import curation_coverage
r = curation_coverage(OdsReader("postgresql://..."), "database", "coco_pharma")
print(r.envelope.result_state, r.to_dict())
```
