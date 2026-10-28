# Declared extensibility: the publish table's four questions, answered and built (2026-10-28)

Follow-up to `DECLARED-EXTENSIBILITY-SLICE1-PR2-PUBLISH-TABLE.md` §4, which asked the owner four questions. On
2026-10-28 the project owner said the questions had been answered before ("I answered all the questions previously -
we should be able to move forward?"), so the sources were searched before anything was built:

- the design notes: `DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE.md` (owner's answers 1-4 of 2026-10-21),
  `DECLARED-EXTENSIBILITY-SLICE1-PR1-GAPS.md` and the PR 2 note itself;
- every `RULING-*` file under `docs/design-notes/` (including `rulings/` and `implemented/`);
- the Architect Session's transcript (2026-10-21 to 10-25), the coordinator's transcript and its hand-off log, and
  the transcripts of the builders that touched the table.

None of them records an answer to these four. The 2026-10-21 answers are the ones the table was built on (generic
route, who declares, the table itself, dashboards). The Architect session ended on 10-25, before the questions were
written on 10-27, and the coordinator's log carries them as still waiting on 10-28. So, as the coordinator directed,
each answer below is this builder's recommendation, built and marked **assumed: owner to confirm**. Each one can be
reversed in one place (named in the table).

| # | Question | Answer built | Source | Where to reverse it |
|---|---|---|---|---|
| 1 | A row whose analysis already publishes another way: say so and offer no Publish, or offer a second copy? | Say so; offer Keep in RE only | **assumed: owner to confirm** | `publish_table.published_elsewhere` |
| 2 | Which native types should the publisher learn first? | SchemaAnalysisAnnotation and ResourcePhysicalStatusAnnotation | **assumed: owner to confirm** (the two the declarations name most after ResourceMeasureAnnotation) | `publish_table.NATIVE_WRITABLE`, `annotation_for` |
| 3 | File systems: wait for a file-system survey report of RE's own, or ride on the root-folder publish? | Wait; the row says so | **assumed: owner to confirm** | `publish_table.NOT_FOR_KIND_WORDS` |
| 4 | Choice lifetime: kept across surveys, or per survey? | Kept across surveys, and the row says so | **assumed: owner to confirm** | `publish_table.STANDING_WORDS` and the choice read in `build_rows` |

## 1. Already in Egeria another way: Keep in RE only

**Assumed (owner to confirm), 2026-10-28:** a measure already in Egeria by another route is not offered for Publish.
Publishing it from the table would write the same number twice under two names, and a reader of Egeria could not
tell which one is authoritative.

The row's state shows the route instead of a publish state, and Publish is disabled with the reason
"already in Egeria via <route>; publishing it here would write the same number twice". Keep in RE is still offered.
A Publish chosen before the measure became "elsewhere" is no longer sent, because the press sends only publishable
rows.

The table recognises three routes. None of them is written per analysis:

- **Egeria's own survey.** The catalogue entry's `source` is `egeria` (today, `egeria_db_survey`).
- **RE's own survey report.** The commit's step 3 always writes the survey's database counts, its database size and
  its views under their own annotations (`DatabaseSurveyor._create_schema_annotations`,
  `_create_statistics_annotations` and `_create_views_annotations`). Four declared measures say the same numbers:
  `schema_inventory` relations and columns, `row_count_snapshot` total_size, and `sql_analysis` views
  (`IN_SURVEY_REPORT`).
  - This is a fixed fact of RE's own survey, not of any analysis a person adds.
  - A test pins every pair to a measure the shipped catalogue declares, so renaming one cannot quietly make it
    publishable again.
  - It is per measure: `schema_inventory`'s `schemas_with_tables` is not in the report and stays publishable.
- **The engine host.** The newest `engine_action` run on this database whose stored outcome is `survey-completed`
  with a report GUID, for the analysis's step key (a library step's `provided_by.step`, else the catalogue id).
  - The row says "already in Egeria via the engine host · report <time>".
  - A failed run, or another database's run, does not count.
  - When the runs cannot be read, the row stays publishable. It never guesses that a measure is in Egeria.

## 2. Native types: SchemaAnalysisAnnotation and ResourcePhysicalStatusAnnotation

**Assumed (owner to confirm), 2026-10-28:** these two come next.

The declarations name them most after ResourceMeasureAnnotation:

- SchemaAnalysisAnnotation: 14 measures;
- ResourcePhysicalStatusAnnotation: 2 measures.

Both can be built from a declaration alone. Each keeps the value and the declared envelope (route, analysis,
measure, unit, as-of, confidence form and basis, scope) where Egeria's type can carry them:

- **ResourcePhysicalStatusAnnotation**
  - Its typed fields (create, update and access times, size, encoding) describe a file, not a database finding.
  - So the value goes into its property bag, published as `additionalProperties`, under the mapped property or the
    measure's name. The envelope goes beside it. This is the convention `db_resilience` already uses.
- **SchemaAnalysisAnnotation**
  - Its only typed fields are `schemaName` and `schemaType`. Each is filled only when the declaration's property map
    sends the value field to it; neither is ever invented.
  - The value and the envelope go in `jsonProperties`, which every annotation type carries.
  - `annotation_props.build_annotation_props` sends no `additionalProperties` for this type, and changing that would
    alter every schema annotation RE already publishes. That is why the values go in `jsonProperties` instead.

Every other declared type (DataClass, ResourceProfile, Classification, QualityScore, Fingerprint, DataGrain,
Relationship, RequestForAction) still shows what it writes as and offers Keep in RE only. Each needs a construction
that no declaration's property map carries yet.

Many SchemaAnalysisAnnotation rows also fall under answer 1. `schema_inventory` and `sql_analysis` are in RE's survey
report, and `egeria_db_survey` is Egeria's own. The rows the answer actually opens are:

- `db_external_dependencies` (five);
- `db_relationship_graph`'s foreign_key_edges;
- `schema_diff` (three);
- `nested_column_profile`;
- `db_resilience` (two).

## 3. File systems wait for a survey report of RE's own

**Assumed (owner to confirm), 2026-10-28:** a file system's measures wait for a file-system survey report of RE's
own.

The other option was to ride on the root-folder publish. That would hang measures off a folder element with no
report to read them back from, and read-back by name is how every published measure is proven. The table's words for
a file system now say why it cannot publish: "a file system's measures wait for a survey report of Resource
Explorer's own for file systems; its Publish attaches the root folder only". The rows are still listed by the route
and still not offered on screen.

## 4. A choice stands across surveys

**Assumed (owner to confirm), 2026-10-28:** a Publish choice is standing. Every commit sends the measure, from
whichever survey is current, until someone chooses Keep in RE. This is how Curate's other choices (scope, leave-out)
already behave. A per-survey choice would make a person re-choose every measure after each survey, and a measure
would silently stop being published.

So that it is never a surprise, the row says so:

- the choice line reads "will publish · <who> · <when> · sent by every commit until Keep in RE";
- a published value that has since moved reads "changed since published · read back <time> · the next commit sends
  the new value".

## Tests

- `tests/test_publish_table.py`: 31 tests (9 new), one or more per answer. They cover:
  - each route of answer 1, including a stale choice no longer being sent;
  - each native type published and read back through the real surveyor publish code against a fake Egeria;
  - the property map reaching `schemaType`;
  - a standing choice sent by two commits and ended by Keep in RE.
- `frontend-build/test-harness/curate-publish-table.test.mjs`: 2 new tests, for the "elsewhere" state and the
  standing words.
- Nothing here writes to Egeria or the shared registry.
