# Annotation-to-annotation linking — audit

Audit only. No production code changed.

## The capability, and what RE does today

Egeria model 0610 (`OpenMetadataType.java:6010`) defines `AnnotationExtension`
(GUID `605aaa6d-682e-405c-964b-ca6aaa94be1b`), *"Additional information to
augment an annotation."* — a relationship linking one Annotation to another.
Adjacent at `:6020`, `AnnotationReview` (model 0612) links an Annotation to a
steward's review of it. The doc page
(https://egeria-project.org/types/6/0610-Annotations/) describes the same
pair; where it and the Java disagree only in description wording, not in
GUID or which model number owns which relationship, the Java is authoritative
per the task brief. I did not find a substantive disagreement between the two
— the doc page's prose is a looser paraphrase of the same relationship, not a
conflicting claim.

Confirmed by grep: `AnnotationExtension` and `AnnotationReview` appear nowhere
in `resource_explorer/` except one line in `surveyors/surveyor_design.md`
that names `AnnotationReview` in a table of Egeria concepts — never
constructed, never referenced in code. **RE has never created either
relationship.** This matches the task brief; I found nothing that changes it.

Every annotation RE publishes today attaches to its `SurveyReport` by exactly
one relationship — `ReportedAnnotation` (`annotation_props.py:200`,
`build_annotation_body`). All annotations from one `SurveyResult` are created
in a single flat loop (`publish_annotations`, `annotation_props.py:205–267`,
and its outbox twin `egeria_outbox.enqueue_annotations`) with no ordering or
grouping semantics between them — they are unrelated siblings under the
report, whatever data relationship they actually have to one another.

**A load-bearing structural fact for every candidate below:** the GUID
`discovery.create_annotation(body=body)` returns is discarded
(`annotation_props.py:261`) — nothing captures it, and nothing writes it back
to the local `project_analysis_findings` table, which has no GUID column at
all (`registry.py:947–958`). So even where RE already publishes both a
summary and its evidence as real Egeria annotations, there is currently no
way to look up "the Egeria GUID for this local finding row" after the fact.
That capability has to be built before any `AnnotationExtension` can be
created — it is not optional plumbing on top of the relationship call, it is
a precondition for it.

## Ranked candidates

### Tier 1 — real annotations on both ends, already published, link only implicit

These are the strongest candidates: both the summary and its evidence are
already distinct `Annotation` objects in the same `SurveyResult.annotations`
list, both get published to Egeria in the same `publish()` call, and the only
thing missing is the relationship between them.

**1. `sub_surveyors/data_profiler.py` — data-file profiling.**
`_tier2_stored`/`_tier2_local` (lines ~300–420) emit one
`SchemaAnalysisAnnotation` per data file, each carrying its own column list,
row count, and null-rate detail in `json_properties`. `run()` also emits one
`ResourceMeasureAnnotation` up front (~line 305) with only aggregate counts
(`total_data_files`, `formats`, `total_data_size`) — no reference to which
files or schemas make up that count.
- Summary vs. evidence: cleanly separable — one aggregate, N per-file schema
  annotations.
- Link today: none. Only shared `report_guid`/`surveyed_at` (i.e., they are
  siblings under the same report, indistinguishable from any other pair of
  annotations from an unrelated step in the same run).
- What breaks without it: a consumer holding the summary annotation
  ("23 CSV files, 4.2MB") has no way to enumerate which `SchemaAnalysisAnnotation`s
  are "its" evidence, short of a heuristic like "same report, same step name,
  right annotation type" — which happens to work here but is not a
  relationship, it's a filter that would as easily match nothing after a
  refactor.
- Would linking help: yes. This is exactly the shape the capability is for.

**2. `sub_surveyors/dependency.py` — dependency inventory.**
`run()` (~line 111 onward) emits one `DataClassAnnotation` per ecosystem
(each with the full per-package list in `json_properties["dependencies"]`),
then one `ResourceMeasureAnnotation` totalling `len(deps)` across
`len(by_ecosystem)` ecosystems, with only counts (`by_ecosystem`, `by_type`)
— no reference to the per-ecosystem annotations.
- Same shape as #1: aggregate + N already-published evidence annotations,
  linked only by convention (same report, `analysis_step="DependencyAnalysis"`).
- Note: `cve_scan.py` separately re-reads the *same* `query_dependencies()`
  rows to compute its own summary (see Tier 2, #5) — so a well-designed
  `AnnotationExtension` graph here could let `cve_scan`'s summary point at
  the same per-ecosystem `DataClassAnnotation`s dependency.py already
  publishes, rather than every consumer re-deriving "what are the
  dependencies" from scratch. That's a second-order win worth flagging, not
  something to build now.
- Would linking help: yes, same reasoning as #1.

### Tier 2 — real summary annotation, but the evidence is local-only (not yet an Egeria annotation)

These are reducers in the strict sense the task describes — a verdict
derived from several inputs — but today only the *verdict* becomes an Egeria
annotation. The "evidence" lives in `project_analysis_findings`
(`registry.upsert_finding`), a local SQLite/Postgres table, and is never
published to Egeria as its own `Annotation` at all. `AnnotationExtension`
cannot link to something that was never created, so for these, adding the
relationship is not just a publisher change — it first requires deciding
whether (and how) to publish the granular findings as annotations, which is
a design question, not an audit finding I can resolve here. I rank these
below Tier 1 for that reason, though the underlying case for *some* form of
linking is often stronger.

**3. `sub_surveyors/security_summary.py` — the reducer named explicitly in the brief.**
This is the most self-aware file in the codebase about exactly this problem
— its own docstring calls itself "a REDUCER, not a measurement" and
carefully engineers `oldest_input_at`, `missing`, and `supersessions` to
avoid exactly the failure mode this task's "one thing to weigh" section
warns about. It reduces over 8 `INPUT_KINDS` (`security_hygiene`,
`security_features`, `ci_quality`, `license_classification`,
`repo_conventions`, `foss_scorecard`, `cii_badge`, `cve_scan`), read via
`registry.query_findings(slug, kind)` — i.e., from local storage, at
`MAX(surveyed_at)` **per kind independently**, so the inputs can be from
different survey runs and different `SurveyReport`s entirely.
- Summary vs. evidence: clean — `findings_for()` emits three findings
  (`security_posture`, `input_coverage`, `summary_freshness`); `run()`
  publishes one `ClassificationAnnotation` to Egeria whose `json_properties`
  flattens `{check_name: label}` for all three plus the raw `counts` dict.
  The actual per-input rows (e.g., which specific `security_hygiene` check
  failed) are never in that annotation and never published as their own
  annotations — they exist only as rows in `project_analysis_findings`.
- Link today: none, and — critically — some of the sub-surveyors whose
  findings feed this (`security_features.py`, `repo_conventions.py`,
  `ci_quality.py`) *do* publish one `ClassificationAnnotation` per
  check_name to Egeria in their own `run()` (see Tier 3 below), from
  possibly a different, earlier report. So the evidence sometimes exists in
  Egeria, just not findable from the summary, and sometimes doesn't exist in
  Egeria at all (`foss_scorecard`, `cve_scan`, `cii_badge` publish only
  their own aggregate — see #4/#5 below).
- What breaks without it: a dashboard rendering "Security: concerns" today
  has no way to jump to "which of the 8 inputs said what" without re-running
  `gather()`+`summarise()` against local storage — which only this codebase
  can do; an external Egeria consumer (a different tool reading the catalog)
  cannot re-derive it at all, because the reduction logic (`PRECEDENCE`,
  `_BAD`/`_GOOD` labels, the 4-of-8 floor) lives in Python, not in Egeria.
  That is real write-only evidence from an external-consumer point of view,
  even though RE itself can always recompute it.
- Would linking help: yes, but it exposes the cross-run problem squarely:
  linking `AnnotationExtension` from this summary to eight other annotations
  requires those eight to (a) exist in Egeria and (b) have their GUIDs
  discoverable from a local finding row that currently carries none. Both
  are missing today.
- **The absence-flattening risk, called out specifically:** `summarise()`
  already carries `known: bool`, `missing: list[str]`, and
  `oldest_input_age_days` as explicit fields precisely so a reader can tell
  "we looked at 4 of 8 and here's what's missing" from "we have a clean bill
  of health." Do not let an `AnnotationExtension` design remove those fields
  from the summary's own `json_properties` on the theory that "the links
  show which inputs are missing" — an unlinked or broken relationship must
  not be the only way to detect that an input never ran. Keep `missing`
  in the summary as written; add links as an *additional*, not
  *replacement*, way to reach the evidence.

**4. `sub_surveyors/foss_scorecard.py` — 16-check reducer.**
`run()` (~line 333) evaluates 16 `CHECKS`, writes all 16 results via
`upsert_finding` (local only), then publishes exactly one
`QualityScoreAnnotation` whose `json_properties["checks"]` is
`{check_name: label}` for all 16 — a flattened dict, no `summary`/`detail`
per check survives into Egeria.
- Same Tier-2 shape as security_summary: evidence exists locally, never
  published individually.
- Notably disciplined about absence already: `unknown` checks are excluded
  from the score and reported via `checks_unknown`/`coverage`, not zeroed —
  worth preserving exactly as it does now if this is ever linked.
- Would linking help: yes, once the 16 checks are worth publishing as
  annotations in their own right (they currently aren't, and that's a
  separate call — 16 annotations per repo per run is a real volume increase
  to weigh against how often anyone drills into an individual check).

**5. `sub_surveyors/cve_scan.py` — package-vulnerability aggregate.**
Not "one finding per package" as the brief's framing question suggested —
I read it and confirmed: `run()` (~line 254) computes `findings`, one row
**per affected package** (`check_name = f"{ecosystem}:{dep_name}"`, with
full advisory IDs, severities, CVSS vectors in `detail`), writes all of them
via `upsert_finding` (local only), then publishes exactly **one** annotation
(`ResourceMeasureAnnotation` or `RequestForActionAnnotation` depending on
whether anything was found) with only `coverage` counts
(`checked`, `advisories`, `packages_affected`) in `json_properties` — no
per-package detail.
- This is the starkest instance of the pattern in the codebase: real,
  specific, actionable evidence (which package, which CVE, what severity)
  computed and stored, and reduced to a single count before it ever reaches
  Egeria. A security dashboard or a recommender reading Egeria annotations
  today gets "12 advisories across 5 packages" and nothing that says which
  five.
- Would linking help: yes, and arguably more here than anywhere else in the
  audit — this is exactly the "can a later consumer re-read the evidence
  without re-running the survey" test from the brief, and the answer today
  is no for anything outside RE's own local tables.
- Watch for the same absence trap: the summary already distinguishes
  "0 advisories across N queryable packages" (`recovered`) from
  "0 advisories because nothing was queryable" (`no_signal`,
  `known_positive=len(pairs) > 0`) — keep that in the summary's own fields.

**6. `sub_surveyors/community_support.py` and `sub_surveyors/chaoss_metrics.py`.**
Same shape as foss_scorecard, smaller: `assess(stats)` produces N dimension
dicts, all written to `upsert_finding` (local only), one
`ClassificationAnnotation` published with `{check_name: label}` flattened
into `json_properties`. Lower priority than #3–#5 — fewer dimensions,
lower stakes than a security or CVE verdict — but the same pattern.

### Tier 3 — architecture-recovery family: verified, does NOT clearly qualify yet

I read `arch_summary.py`, `arch_lens.py`, `arch_recovery_detect.py`,
`arch_recovery_coupling.py`, and the underlying persistence
(`egeria_annotation_materializer.py`, `arch_recovery/persist.py` by
inspection of callers). The pattern is real but one level removed from an
`AnnotationExtension` candidate:

- `arch_recovery_detect.py` (`ArchDetectSurveyor.run()`, ~line 87) proposes
  components + evidence and calls `persist_ir(...)` (~line 251), which
  writes them into the architecture-recovery IR tables (Postgres,
  `arch_recovery/persist.py`) — **not** as Egeria annotations. It then
  publishes exactly one `ResourceMeasureAnnotation`
  ("N candidate component(s) detected...") with aggregate counts.
- `arch_summary.py` is explicit about being a reduction —
  `explanation="... A count, not a listing — the underlying per-component
  findings are unchanged and remain the detail view."` — but "the detail
  view" it means is a local UI view over the IR tables, not an Egeria
  annotation. Same for `arch_lens.py`'s `candidate_classifications`/
  `documented`/`undetected` lists, and `arch_recovery_coupling.py`'s
  aggregate summary.
- **Conclusion: this family is Tier-2-shaped (summary real, evidence
  local-only) but with an extra step Tier 2 doesn't have** — the "evidence"
  here (proposed components, coupling edges, interface wires) isn't even
  modeled as `Annotation` objects internally; it's a separate IR data model
  (`arch_recovery/ir.py`) that would need its own translation into
  Annotation-shaped elements before `AnnotationExtension` could apply at
  all. That's a larger design decision than "add a relationship call" — it's
  "decide whether architecture-recovery IR should ever become Egeria
  annotations," which is out of scope for this audit to resolve. I'm not
  ranking it above Tier 2 because the plumbing gap is bigger, not because
  the underlying case is weaker — arguably it's the richest evidence in the
  whole codebase (proposed components with confidence, coupling strength,
  wire direction) and the worst served by today's flat single-annotation
  publish.

### Verified NOT to qualify

**`sub_surveyors/ci_quality.py`, `repo_conventions.py`** — both publish one
`ClassificationAnnotation` per `check_name`, with **no aggregate/summary
annotation at all** in the same run. This is a flat list of independent
findings, exactly the case the brief says does not need linking. There is no
summary to name, so criterion 1 ("can you name both separately") fails by
construction. Confirmed by reading both files in full — no reducer step
exists for either at the sub-surveyor level (their aggregation, if any,
happens inside `foss_scorecard`/`security_summary`, already covered above).

**`sub_surveyors/security_features.py`** — same flat-list shape: one
`ClassificationAnnotation` per feature name, no aggregate annotation.
Does not qualify for the same reason.

**`sub_surveyors/file_structure.py`** — three `ResourceMeasureAnnotation`s
per run, but they answer three *independent* questions (total size,
per-language breakdown, per-directory breakdown) — none is a summary
*of* the others; each measures something the others don't. No
summary/evidence relationship exists to link.

**`sub_surveyors/documentation.py`** — closest call in this "does not
qualify" section. It publishes up to 6 "collection present"
`ClassificationAnnotation`s, 1 "hygiene files found" annotation, and 1
overall "quality" `ClassificationAnnotation` — which looks like a
summary-over-evidence shape. But I checked what the quality annotation's
`json_properties` actually carries (`doc_collection_types`, `hygiene_files`,
`signal_count`) — it already **inlines** the same information the sibling
annotations state, not a pointer to a count of something hidden. Nothing is
write-only here: the full set of collection types and hygiene files a reader
would want is already sitting in the summary's own `json_properties`, just
duplicated rather than linked. Per the brief's test #4 ("would linking
help, or just add relationships"), the answer is "just add relationships" —
the evidence is small (booleans over ~11 fixed names), cheap to inline, and
already inlined. Not worth it.

## Summary table

| File | Summary annotation published? | Evidence published as annotations? | Verdict |
|---|---|---|---|
| `data_profiler.py` | yes | yes (per-file, same run) | **Tier 1 — strongest** |
| `dependency.py` | yes | yes (per-ecosystem, same run) | **Tier 1 — strongest** |
| `security_summary.py` | yes | partial — some inputs' annotations exist (in other reports), some don't | Tier 2 — needs GUID tracking + decide on cross-run linking |
| `cve_scan.py` | yes | no (local only) | Tier 2 — highest-value evidence, none of it in Egeria today |
| `foss_scorecard.py` | yes | no (local only) | Tier 2 |
| `community_support.py` / `chaoss_metrics.py` | yes | no (local only) | Tier 2, lower stakes |
| `arch_summary.py` / `arch_lens.py` / `arch_recovery_detect.py` / `arch_recovery_coupling.py` | yes | no — not even modeled as Annotation objects (separate IR model) | Tier 2+, larger plumbing |
| `ci_quality.py`, `repo_conventions.py`, `security_features.py` | no (flat list only) | n/a | does not qualify |
| `file_structure.py` | no (independent measures) | n/a | does not qualify |
| `documentation.py` | yes, but self-contained | yes, but redundant with it | does not qualify — already inlined |

## Is creating the first `AnnotationExtension` small or large plumbing?

**Medium, leaning large — not a one-line addition, and the hard part is not
the relationship call itself.**

What's genuinely small: `annotation_props.py`'s existing
`NewElementRequestBody`/`parentRelationshipTypeName` pattern
(`build_annotation_body`, line 187) already generalizes to any Egeria
relationship type — creating an element parented via `AnnotationExtension`
instead of `ReportedAnnotation` is a one-string change *if* you're creating
the evidence annotation for the first time with the summary's GUID already
in hand (true for same-run cases like data_profiler/dependency, false for
security_summary's cross-run inputs).

What's not small:

1. **GUID capture is entirely missing.** `discovery.create_annotation(body=body)`
   at `annotation_props.py:261` discards its return value. Nothing in RE
   today knows the Egeria GUID of an annotation it just created, or of one
   created in a past run. Before any relationship can be built, this needs
   to be captured and — for cross-run cases — persisted somewhere
   (`project_analysis_findings` has no GUID column; `registry.py:947`).
2. **`Annotation` (survey_report.py) has no relationship model.** There's no
   field expressing "this annotation is evidence for that one" — not even
   an index into the same `SurveyResult.annotations` list. Sub-surveyors
   that produce both a summary and its evidence (`data_profiler.py`,
   `dependency.py`) currently have no way to say so in the data they hand to
   the publisher; that has to be added before the publisher can act on it.
3. **No "link two existing elements" primitive exists anywhere in this
   codebase.** Every relationship RE creates today is the
   create-with-parent shape (`NewElementRequestBody` +
   `parentRelationshipTypeName`) — always *creating* a new element and
   parenting it in the same call. `security_summary.py`'s case (link a
   just-created annotation to up to 8 *already-existing* annotations, some
   from earlier reports) needs a genuinely new call shape — a bare
   relationship-create between two known GUIDs — that has to be built and
   verified against the real Egeria REST/pyegeria surface before it can be
   trusted. `egeria_publisher.py:233`'s `_connect()` and the surrounding
   class would be the natural home for it, but the capability itself does
   not exist today, in any form, anywhere in `surveyors/`.
4. **Ordering.** `publish_annotations`/`enqueue_annotations` treat all
   annotations from one result as an unordered flat batch, retried
   independently via the outbox. Linking requires a second pass, after
   creation, that knows which GUIDs go together — the outbox's retry/backoff
   model would need to account for "the evidence annotation exists but its
   link to the summary hasn't been created yet" as a distinct, resumable
   state, not just "annotation exists or doesn't."

Net: for the same-run cases (`data_profiler.py`, `dependency.py`), the work
is real but bounded — GUID capture, one new field on `Annotation`, a
second linking pass in `_create_annotations`. For the reducer cases
(`security_summary.py` and the rest of Tier 2), it additionally requires a
design decision this audit deliberately does not make: whether to start
publishing granular findings as Egeria annotations at all, and if so, how to
find an existing annotation's GUID from a local finding row written in a
past run.

## What I could not determine

- Whether `DataDiscovery.create_annotation` (or the pyegeria layer beneath
  it) already returns a usable GUID in its response body — I read that the
  return value is discarded, not what it contains. Worth checking before
  scoping the "GUID capture" work above as small; if the GUID is already in
  the response and just needs to be read, that piece shrinks.
- Whether pyegeria exposes a bare "create relationship between two existing
  GUIDs" call anywhere outside this codebase's own usage (i.e., whether the
  primitive exists in the library and RE simply never needed it, versus
  needing to be built fresh against the Egeria REST API). I did not find it
  used anywhere in `resource_explorer/`, which only tells me RE hasn't
  needed it yet, not whether pyegeria has it.
- Whether `AnnotationExtension` in the real Egeria model is directional in a
  way that matters here (does "summary extends evidence" or "evidence
  extends summary" — end1/end2 semantics) — the task brief said not to
  re-derive the capability's existence, and I did not go further into the
  Java than the two cited line numbers, so I have not confirmed which
  direction the relationship's ends imply for a summary/evidence pair.
