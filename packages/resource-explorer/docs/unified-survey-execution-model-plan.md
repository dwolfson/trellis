# Unified Survey execution model — one mechanism, choreographed by locus

**Status: planned, not yet built, except D7a's first slice (shipped
2026-08-14, live-verified — see D7a below for exactly what's covered)
and Enrichment's survey-panel host (shipped 2026-08-15, one of D7a's
named-but-undone items). D6 (dependency/sequencing mechanism) is now
fully designed (2026-08-15, see D6 below) — not yet implemented; D6.5
flags one real behavior-change question needing confirmation before it
is.**
Synthesizes a design discussion
(2026-08-14) that started from `docs/dr-egeria/resource_questions.csv`'s
"Answering Mechanism" review and grew into a real architecture proposal.
Builds directly on `docs/survey-question-context-plan.md` (D1/D2/D3,
already built and live-verified) and the "Scouting/Analysis/Assessment
boundary" plans referenced there — this doc is the next layer on top of
that work, not a replacement for it.

## Context

Reviewing what answers each Question in `resource_questions.csv` surfaced
an observation: RE's UI presents four differently-named surfaces —
Scouting's **Survey**, Scouting's **Profile**, Discovery's **Survey
Definitions**, Assessment/Analysis's **Analyses** — that read as four
different concepts. Checked directly against the code: they're mostly the
same mechanism wearing different names.

- Scouting's "Survey" (Run Scouting Scan) → `run_survey_definition()`.
- Discovery's "Survey Definitions" (an Egeria-authored
  `GovernanceActionProcess` chain) → `survey_definition_executor.py`
  looks up each `executes_at="resource-explorer"` step in
  `adapter.re_analysis_steps`, which is just
  `SurveyOrchestrator.run(steps=[key])` per step.
- Assessment/Analysis's "Analyses" cards (`POST /{slug}/analyses/
  {analysis_id}/run`) → the *same* `SurveyOrchestrator.run(steps=[...])`
  call, just with `REPO_ANALYSIS_STEP_MAP`'s 1-3 steps for one
  `analysis_id` instead of a whole chain.

Three UI surfaces, three names, one underlying call. Scouting's "Profile"
looked like the one real outlier (`IngestionPipeline.refresh_profile()`,
not `STEP_REGISTRY`/`SurveyOrchestrator` at all) — but see D5 below, that
turned out to be a miscall, corrected during the discussion.

## Key decisions

**D1 — One Survey concept: a named, ordered bundle of Analytic Steps
(`STEP_REGISTRY` entries), execution choreographed by where its steps
run, not by which UI surface asked for it.** Three execution cases:

1. **All steps `executes_at="resource-explorer"`** → RE manages the
   entire execution locally via `SurveyOrchestrator.run()` — already real,
   this is today's normal path.
2. **All steps `executes_at="egeria"`** → Egeria's own Governance Action
   Process engine sequences the internal steps; RE still has to *trigger*
   it and *read results back* (not fully hands-off — matches
   `HybridDatabaseSurveyor`'s existing pattern: trigger the native async
   survey, then read/reconcile). Egeria doesn't need RE to sequence its
   own steps, but RE isn't uninvolved either.
3. **Mixed, or a third platform involved** → RE choreographs. The skeleton
   for this already exists in `survey_definition_executor.py`'s dispatch
   loop (`executes_at` branches to `resource-explorer` /
   `other_engine_handlers` / `egeria`), **but the `egeria` branch is
   currently a stub** — confirmed live: it logs "Skipping step... no
   trigger handler registered" and does nothing. A mixed survey with an
   Egeria-native step in it silently drops that step today. Closing this
   gap (real trigger-and-wait for an Egeria-native step from within a
   mixed choreographed run) is the concrete implementation work D1 needs.

**D2 — Two separable kinds of "publish," with a real precondition between
them.**
- **Asset cataloging** — registering/finding the `SourceControlLibrary`/
  `Database`/`FileFolder` asset itself.
- **Survey/annotation result storage** — attaching a `SurveyReport` +
  `Annotations` to that asset.

These are NOT independently optional in every case:
- **Any Egeria-native step in the bundle** → asset cataloging is a
  *precondition* to even running the step (Egeria's native survey engine
  operates on an already-cataloged asset — `initiate_postgres_database_
  survey()`-style calls take an existing asset GUID, they don't create
  one as a side effect). Once that step runs, its results land in Egeria
  automatically, inherently — there's no "run this Egeria-native step but
  don't publish its results" option, because there was never a local
  copy to withhold.
- **All steps RE-executed** → both are genuinely optional and separable.
  `EgeriaPublisher.publish()` today bundles `_find_or_create_asset()` +
  report-attach into one call; decomposing that isn't required for D2 to
  be true, just for a UI to expose the distinction (see D3).

**D3 — For pure-RE surveys, publish-results defaults to ON, reversing
today's "always a separate, deliberate action" convention — a deliberate,
explicit reversal, not an accretion.** Simplified to two real states (the
middle "asset cataloged but skip publishing this run's results" state is
possible but judged not common enough to build a control for — noted as a
real option, deliberately not exposed):
1. Skip both (asset + results) → pure local sniff test.
2. Both (the new default) → normal case, asset cataloged and this run's
   results published.

This inverts language used elsewhere in this codebase's own docs (e.g.
the Automate spec: "matching the existing convention that publish is
always a separate, deliberate action, not inferred") — noted here
explicitly so it isn't silently treated as consistent with prior work. It
is a considered choice, confirmed in this discussion, not a contradiction
that slipped in unnoticed.

**D4 — Sniff-test-ability is *derived* from a Survey's execution tier, not
configured per-survey.** A Survey's tier (pure-RE / mixed / pure-Egeria)
is fully determined by its steps' `executes_at` values — data that
already has to exist for D1's choreography to work at all. So:
- Pure-RE Survey → sniff-testable by construction (no Egeria step forces
  the D2 asset precondition).
- Any Egeria-native step present → committed by construction (D2's
  precondition already applies).

No separate "is this a sniff test" flag to design, store, or maintain.
Confirmed consistent with what's already built: both existing repo Survey
Definitions ("Repo Coarse Scout": `repo_health`+`repo_language`; "Repo
Discovery Survey": `repo_license_classification`+`repo_maturity`+
`repo_conventions`) are 100% `executes_at="resource-explorer"` — the
early-funnel/cheap-and-safe correlation isn't a design target, it's
already true of the two Survey Definitions that exist.

**D5 — File Profiling is an under-recognized Survey, not a peer category
— correction from an earlier mischaracterization in this same
discussion.** `FileClassifierSurveyor`/`FileStructureSurveyor` (the steps
`IngestionPipeline.refresh_profile()` chains) already write real
`ClassificationAnnotation`/`ResourceMeasureAnnotation` output — this is
already survey-shaped, not a housekeeping refresh. Egeria's own native
`FileDirectory:CreateAndSurvey` process treats the same kind of
file-type-count directory scan as a first-class survey with real results,
confirming the shape, not inventing it. Profile currently runs through
its own bespoke pipeline instead of `SurveyOrchestrator` for one
legitimate reason — avoiding a second zipball download when code-symbol
extraction is also requested (`refresh_profile()`'s whole reason for
existing, per the earlier Profile-tab plan). Folding it into the unified
model means migrating those steps into `STEP_REGISTRY`-compatible form
while preserving that single-download efficiency — not discarding the
optimization, relocating it (see D6).

**D6 — Dependency/sequencing between Steps or Surveys.** Designed
2026-08-15 (was previously scoped to "name the gap, don't design the
resolution" — this supersedes that placeholder).

**Grounding: the same underlying need already exists in 3
non-composable forms**, confirmed via direct code read rather than
assumed:
1. `SurveyOrchestrator.run()` hardcodes two `if step_key == "X":`
   branches to build special constructor kwargs
   (`repo_file_classification` → `pyegeria_client`/`force_refresh`;
   `repo_data_profiling` → `local_path`) — not declared on `StepInfo`,
   doesn't scale past 2 cases.
2. `refresh_profile()` downloads one zipball into a tempdir and threads
   the local root through 4–5 hand-written calls
   (`_store_file_inventory`, `_profile_data_files`,
   `_parse_ci_workflows`, `_parse_repo_conventions`, optional symbol
   extraction) — real, valuable sharing, entirely bespoke to that one
   function, invisible to `STEP_REGISTRY`.
3. Any *new* step wanting zipball content has no declarative way to ask
   for it — the established workaround (`CiQualitySurveyor`'s own
   docstring names it explicitly) is "parse it once inside
   `refresh_profile()` at ingest/profile-refresh time, and read the
   already-persisted row read-only at survey time" — which works, but
   means every new zipball-dependent step requires hand-editing
   `refresh_profile()`, not just registering itself.

**A real, separate finding that reframes the concrete need**: grepping
every `SurveyOrchestrator(` call site shows `data_path` is never
actually supplied by any real caller today — `DataProfilerSurveyor`'s
"Tier 2" local-clone deep-profiling code path
(`local_path`-gated) is dead in practice; only Tier 1 (reading
already-materialized `project_file_inventory` rows) ever runs. So the
zipball-sharing case named in this doc's original D6 text doesn't
actually occur inside `SurveyOrchestrator` today at all — it only
occurs in `refresh_profile()`. This changes what "solving D6" buys:
activating `DataProfilerSurveyor`'s Tier 2 for the first time is a real
side effect of this design, not a hypothetical (see D6.5, flagged
explicitly since it adds real network cost).

### Decisions

**D6.1 — Model shared *resources*, not step-to-step data dependencies.**
The concrete, motivating need in every case above is "N steps want the
same expensive external thing" (a zipball download, a live pyegeria
client) — not "step B consumes step A's `Annotation` output." No case of
the latter exists anywhere in `STEP_REGISTRY` today (confirmed: no
surveyor reads another surveyor's returned annotations). Scoping this
design to resource-sharing keeps it small and grounded in what's
actually needed; a real step-to-step data-dependency graph is a
different, larger problem (would need annotation-passing, topological
ordering, cycle detection) and isn't motivated by any real case —
explicitly deferred, named so it isn't silently assumed solved by this
pass.

**D6.2 — `ResourceProvider` + `RESOURCE_PROVIDERS` registry**, colocated
with `STEP_REGISTRY` in `repo_survey_definition_adapter.py` (same file
already owns step-key semantics):
```python
@dataclass
class ResourceProvider:
    name: str                                    # e.g. "zipball_root"
    acquire: Callable[[Project, ProjectRegistry], AbstractContextManager]
    # acquire(project, registry) returns a context manager whose __enter__
    # yields the resource value (a Path, a client instance, …) and whose
    # __exit__ does cleanup (tempdir removal). Reuses Python's own
    # contextlib idiom rather than inventing a bespoke acquire/release
    # pair or a separate teardown-registration mechanism.

RESOURCE_PROVIDERS: dict[str, ResourceProvider] = {
    "zipball_root": ResourceProvider("zipball_root", _acquire_zipball_root),
}
```
`_acquire_zipball_root(project, registry)` is a `@contextmanager`
wrapping exactly what `refresh_profile()` already does
(`GitHubClient().download_zipball(repo, Path(tmp))` inside a
`tempfile.TemporaryDirectory()`) — a straight extraction of existing,
proven logic, not a new algorithm.

**D6.3 — `StepInfo` gains `requires_resources: dict[str, str] = {}`**
(resource name → constructor kwarg name — a dict, not a list, since
different surveyors may each name their own kwarg differently; e.g.
`DataProfilerSurveyor` calls it `local_path`, not `zipball_root`).
Replaces the `repo_data_profiling` special case in
`SurveyOrchestrator.run()` outright:
```python
"repo_data_profiling": StepInfo(
    "repo_data_profiling", DataProfilerSurveyor, ...,
    requires_resources={"zipball_root": "local_path"},
),
```

**D6.4 — `SurveyOrchestrator.run()` resolves resources once, before
constructing any surveyor, deduped by the actual set of steps
selected** (this is the literal "resolving/ordering/deduping" this
doc's original D6 text asked for):
```python
needed = {r for key in step_keys_to_run for r in STEP_REGISTRY[key].requires_resources}
with ExitStack() as stack:
    resources = {
        name: stack.enter_context(RESOURCE_PROVIDERS[name].acquire(project, self._registry))
        for name in needed
    }
    for step_key, info in ...:
        kwargs = {...}  # existing per-step kwargs, unchanged
        for resource_name, kwarg_name in info.requires_resources.items():
            kwargs[kwarg_name] = resources[resource_name]
        all_surveyors[step_key] = info.surveyor_cls(project, self._registry, **kwargs)
    for surveyor in surveyors:
        ...  # existing run loop, unchanged, still inside the `with` block
```
`ExitStack` guarantees any resource needing cleanup (the zipball
tempdir) is released exactly once, after every step that used it has
run — the `with` block spans the *entire* `run()` call, not just
construction, so nothing is torn down between two steps that both need
it. Steps with an empty `requires_resources` are completely unaffected
(`needed` stays empty for a run that touches none of them, `ExitStack`
is a no-op) — this is the regression guard: every existing zero-resource
step must produce byte-identical behavior before and after this change.

**D6.5 — Activating `DataProfilerSurveyor` Tier 2 is a real, flagged
behavior change, not incidental.** Once `repo_data_profiling` declares
`requires_resources={"zipball_root": "local_path"}`, selecting that step
makes `SurveyOrchestrator.run()` *actually* download a zipball and
supply a real local path — something that never happens today (D6's own
grounding finding above). This is the point of the mechanism working,
but it has a real cost (one more GitHub API call + zipball transfer per
`repo_data_profiling` run) that today's callers have never paid.
**Confirm this is wanted before implementing** — the alternative is
leaving `repo_data_profiling` as Tier-1-only (no `requires_resources`
entry) and treating D6.2–D6.4's mechanism as proven-but-unused until a
step that actually needs it is ready (the next real candidate: any
future zipball-content step migrating off the `CiQualitySurveyor`
read-persisted-row workaround, see D6.7).

**D6.6 — Plain scalar flags (e.g. `force_refresh`) stay ordinary
orchestrator-constructor parameters, not resources.** Only genuinely
*acquired* (fetched/computed/opened, needing dedup and possibly cleanup)
values belong in `RESOURCE_PROVIDERS` — forcing a boolean straight
through `SurveyOrchestrator.__init__` into this mechanism would be
over-generalizing for no real gain. `repo_file_classification`'s
existing `pyegeria_client`/`force_refresh` special case is left as-is by
this design (implementer's call whether to also register
`pyegeria_client` as a resource for symmetry — it's already a cheap,
pre-opened client with no acquire/release cost, so there's no strong
reason to move it, but doing so isn't wrong either).

**D6.7 — `refresh_profile()` itself is explicitly NOT migrated onto this
mechanism here.** That migration is this doc's own D5 ("migrating
`refresh_profile()`'s steps into `STEP_REGISTRY`... real, nontrivial
refactor, not scoped in detail here") — D6 exists to define the shared
primitive D5 will need, not to perform D5's refactor. `refresh_profile()`
keeps its own hand-written tempdir/download logic unchanged for now.
Once D5 lands, `refresh_profile()`'s steps become real `StepInfo`
entries using `requires_resources={"zipball_root": ...}` the same way
`repo_data_profiling` does here — at that point `_acquire_zipball_root`
has exactly one real implementation shared by both call paths, not two
copies of the same download logic.

### Implementation

- `repo_survey_definition_adapter.py`: `ResourceProvider` dataclass,
  `RESOURCE_PROVIDERS` dict, `_acquire_zipball_root()` (`@contextmanager`,
  extracted from `refresh_profile()`'s existing download+tempdir logic —
  `refresh_profile()` itself is untouched per D6.7, this is a new
  standalone function, not a refactor of the old one).
  `StepInfo.requires_resources: dict[str, str] = field(default_factory=dict)`.
  `repo_data_profiling`'s `StepInfo` entry gains
  `requires_resources={"zipball_root": "local_path"}` (pending the D6.5
  confirmation).
- `survey_orchestrator.py`: `run()`'s surveyor-construction section moves
  inside `with ExitStack() as stack:`; computes `needed` from the
  selected step keys; resolves each via
  `RESOURCE_PROVIDERS[name].acquire(project, self._registry)` entered
  into the stack; injects into each surveyor's kwargs per
  `StepInfo.requires_resources`. Removes the
  `elif step_key == "repo_data_profiling": kwargs = {"local_path": self._data_path}`
  branch (superseded by the generic path). `SurveyOrchestrator.__init__`'s
  `data_path` param can be dropped entirely — confirmed no real caller
  ever passes it (D6's own grounding finding) — a clean removal, not a
  deprecation.

### Verification

- Unit test: a `run()` call touching only zero-`requires_resources`
  steps never consults `RESOURCE_PROVIDERS` at all (mock it, assert zero
  calls) — the core regression guard.
- Unit test: two steps in the same `run()` call both requiring
  `"zipball_root"` → `_acquire_zipball_root` is entered exactly once
  (mock it, assert call count) — the actual "dedup" guarantee this
  design exists to provide.
- Unit test: `repo_data_profiling` run in isolation, `_acquire_zipball_root`
  mocked to yield a fixture directory → `DataProfilerSurveyor` receives
  a real `local_path` and its Tier 2 code path activates — untestable in
  practice before this change, since nothing ever supplied `local_path`.
- Live (only after D6.5's confirmation): run `repo_data_profiling` alone
  against a real small repo, confirm a zipball download actually happens
  (log/network check) and Tier 2 profiling numbers differ meaningfully
  from a Tier-1-only run (richer per-file stats) — the concrete proof
  this mechanism does something real, not a refactor of dead code into
  differently-dead code.
- Full RE test suite green.

**D7 — Stage/perspective visibility should be *driven by* the Question/
Perspective `ScopedBy` graph already built (D1/D2 in
`docs/survey-question-context-plan.md`), not a second, separately
hand-maintained `survey_kind` tag.** Since Questions already carry
Perspectives (the CSV's perspective columns) and Funnel Stage, one
`get_scoped_elements()`-style query against "which Surveys are `ScopedBy`
a Question tagged this stage/perspective" answers both axes the UI needs
at once. Today only Discovery's candidates route uses this mechanism;
this decision says it should become the general answer everywhere a stage
surfaces "which Surveys can I run here," replacing `survey_kind` as
source of truth rather than living alongside it as a second system.

**D7a — Concretely, this means one reusable Survey panel, instantiated
per phase, pulling forward the "UI naming consolidation" item this doc
originally deferred** (2026-08-14 follow-up discussion). Confirmed via
direct code read: Discovery's `loadSurveyDefinitionsPanel()`/
`renderSurveyDefinitionsPanel()` is the only current caller of the
`/candidates` route, and it filters via a hardcoded `survey_kind=
"discovery"` — `phase` is never passed by any real caller today, even
though the backend (`survey_definitions.py`'s `list_candidates()`) has
supported it since D2 (`docs/survey-question-context-plan.md`). Per
direct instruction: *"Every phase that runs a survey should have
basically the same panel that presents the users with the surveys scoped
for that phase. A perspective filter, like we have in Questions, can also
be used to further filter the Surveys that show. The panel allows
available surveys to be run or scheduled. Results of the survey
executions should be presented in the panel."*

This generalizes the *existing* `renderSurveyDefinitionsPanel()` (Egeria
Survey Definition candidates: `/candidates` route) into a reusable
component parameterized by `(phase, entityType, slug)`:
- Fetches `/candidates?phase=<stage>` (dropping the `survey_kind=
  "discovery"` hardcode) + a Perspective multi-select feeding
  `&perspectives=...`, mirroring the Questions tab's own filter row
  exactly (same `activePerspectives` convention).
- Each candidate keeps its existing Run action; gains a Schedule action
  (reusing `schedules.py`'s existing per-`analysis_id` CRUD — Survey
  Definitions don't have an `analysis_id` today, so this needs a keying
  decision, see open question below).
- Results: today a Survey Definition run's output is only ever the deep
  report (`GET .../survey-report`) or an ad hoc toast — this decision
  requires an inline results view per candidate. `analysis_catalog.yaml`'s
  `AnalysisKind`/`AnalysisKindResults` registry (Phase B) already solved
  exactly this for the *other* survey mechanism (local Analyses cards:
  results_reader/trend_reader/render mode) — reusing that same
  results/trend infrastructure for Survey Definition candidates (keyed by
  the step keys a Survey Definition's steps resolve to, not a single
  `analysis_id`) is the natural fit, not a new results system.
- **Open question, not yet resolved**: today's `AnalysisKind` catalog
  cards (Assessment/Analysis's existing "Analyses" panel) and Egeria
  Survey Definition candidates are still two structurally different
  systems (a YAML-driven local registry vs. a live Egeria
  `GovernanceActionProcess` read) even after this doc's D1 unifies what
  each one *executes*. Whether "basically the same panel" means (a) one
  literal shared render function used by both call sites, each still
  fetching its own data shape, or (b) actually merging Analyses cards and
  Survey Definition candidates into one fetched list per phase, is a real
  design decision for the implementation pass, not decided here.
- Phase → stage-tag mapping for existing UI hosts: Scouting's Survey
  sub-tab → `phase=scouting`, Assessment's Analyses sub-tab →
  `phase=assessment`, Analysis's Catalog sub-tab → `phase=analysis`,
  Enrichment (if it ever gets a survey panel) → `phase=enrichment`.
  Discovery itself has no funnel-stage identity of its own (per CLAUDE.md,
  it's the general launch surface) — it keeps showing every candidate
  unscoped by phase (only the new Perspective filter narrows it), which
  is also the natural way to retire `survey_kind="discovery"` without
  losing Discovery's "see everything" role.

**D7a — shipped, first slice (2026-08-14).** Per direct confirmation,
scoped to "one shared render function, two data sources" (not a full
merge of Egeria Survey Definition candidates with the separate
`AnalysisKind` local-analyses system — that convergence is real future
work, explicitly not attempted here). What actually shipped:
- `renderSurveyDefinitionsPanel()` → `renderSurveyPanel()`, generalized
  to `(data, entityType, slug, schedules, phase, viewElId, subnavHtml)` —
  any host can call it against any DOM element.
- New `_loadSurveyPanel()`/`_toggleSurveyPanelPerspective()` — fetches
  `/candidates?phase=X&perspectives=Y...`, plus a Perspective filter row
  using the *same* 12-name vocabulary and toggle pattern as the Questions
  tab (derived from `/scouting-questions?phase=X`'s own perspective
  union — repo-only, matching `question_catalog_reader.py`'s "repo" only
  scope; db/filesystem hosts get no perspective filter, not an error).
- Discovery (`loadSurveyDefinitionsPanel()`) now calls `phase=''`
  (unscoped — every candidate, narrowed only by Perspective) instead of
  the old hardcoded `survey_kind="discovery"` — confirmed live: Discovery
  and Scouting now show genuinely different candidate sets (Discovery:
  "Repo Discovery Survey" + "Repo Coarse Scout"; Scouting's `phase=
  scouting` scoped lookup fell back to the full scan and surfaced "Repo
  Full Survey" instead — a real, honest finding that the ScopedBy links
  between Scouting-stage Questions and the right Survey Definitions
  aren't fully populated in Egeria yet, not a bug in this slice; matches
  the user's own "we do have a bit more work to do on the implementation
  registry of analysis steps" caveat).
- Scouting's Survey sub-tab (`renderScoutingOverview()`) gained a second
  panel instance, scoped `phase='scouting'`, appended below the existing
  overview card (not replacing it) — "Run Scouting Scan" stays as its own
  button for now; the same Survey Definition it triggers can also appear
  as a candidate in the new panel below it, a real near-term duplication
  named here, not resolved in this pass.
- **Real bug found and fixed live during this build**: the first version
  threaded the full rendered `subnavHtml` fragment through each
  Perspective chip's inline `onclick='...'` via `JSON.stringify` — since
  `subnavHtml` itself contains `onclick="..."` attributes with their own
  single-quoted arguments, an unescaped single quote inside it terminated
  the outer attribute early and spilled raw markup onto the page (caught
  via live browser verification, not by the test suite — this is
  string-templated HTML, not covered by the Python test suite at all).
  Fixed by keeping `subnavHtml` (and the other loader args) in module
  state (`_surveyPanelArgs`) instead of re-serializing it into every
  chip's attribute — same "avoid inline-serializing a big object into
  HTML" discipline `_surveyDefCandidatesCache` already used for candidate
  objects, just not yet applied to this new data.
- **Second slice, shipped (2026-08-14, same day).** Assessment's Analyses
  sub-tab and Analysis's Catalog sub-tab now also render the panel, below
  their existing `AnalysisKind` cards — `renderAnalysisCatalogCards()`
  gained a `${viewId}-survey-panel` placeholder div (mirroring
  `renderScoutingOverview()`'s own), and `_loadAnalysisCatalogPanel()`
  calls `_loadSurveyPanel(resourceType, slug, intent, ...)` right after
  rendering the cards, using `intent` (`"assessment"`/`"analysis"`)
  directly as `phase` — same funnel-stage vocabulary Questions/Scouting
  already use, no new mapping needed. Only fires when a resource is
  actually selected (an unselected Assessment/Analysis view has no slug
  to scope Survey Definition candidates to). Live-verified against
  `egeria_git`: both sub-tabs render "SURVEYS — EGERIA_GIT (ASSESSMENT)"
  / "(ANALYSIS)" with their own perspective-filter row below the local
  cards, correctly reporting no Survey Definitions found for those phases
  yet — an honest, expected gap (no assessment/analysis-tier ScopedBy
  links exist in Egeria today), not a bug in this wiring. Full RE test
  suite green (1110 passed, 9 skipped — pre-existing live-Egeria-only
  skips, not new) after this slice, same as after D7a's first slice.
- **Scheduling gap closed (2026-08-14, same day).** `scheduler.py` gained
  repo's own case (d) — `_run_repo_survey_definition()`, mirroring
  database's long-standing `_run_survey_definition()` (case (d) already
  existed for database; repo never had an equivalent). When a scheduled
  `analysis_id` isn't found in the local `AnalysisKind`/
  `REPO_ANALYSIS_STEP_MAP` registry, it's now dispatched as a Survey
  Definition `qualified_name` through `run_survey_definition()` — the same
  executor the panel's own "Run →" button uses — instead of being
  reported as a stale/removed catalog entry. No credentials threaded
  through (repo Survey Definition steps run entirely locally via
  `repo_survey_definition_adapter`'s `runner(project, registry, **_)`
  signature — nothing to authenticate, unlike database's `db_user`/
  `db_pwd`). `web/routes/schedules.py`'s `save_schedule()` needed no
  change — `analysis_id` was already a free-form string, never validated
  against the catalog. Verified live: `POST /api/schedules/repo/
  egeria_git` with `analysis_id="GovActionProcess::RepoFullSurvey"` (a
  real Survey Definition qualified_name) stores and reads back correctly;
  actually letting the scheduler fire it against real Egeria wasn't
  triggered live (a 16-step full survey run is a real side-effecting
  action, left for the user's own pace) — the dispatch logic itself is
  covered by new unit tests (`TestRunDueRepoDispatch`): successful
  dispatch with the right `survey_definition_ref` and no `db_user`/
  `db_pwd` kwargs, a stale/deleted Survey Definition reference recorded
  as a clean activity-log error (not a scheduler crash), and step-error
  propagation — mirroring the coverage pattern
  `test_discovery_candidate_dispatches_to_run_survey_definition()`
  already established for database. Full RE test suite green (1112
  passed, 9 pre-existing skips) after this fix. Inline
  "results of survey executions" per candidate (the third part of the
  original request) is also not done — today a run's outcome still only
  surfaces in the existing run modal, not persisted/rendered back into
  the panel itself; needs the `AnalysisKindResults`-style results/trend
  wiring extended to Survey Definition candidates (keyed by their steps'
  step keys, not a single `analysis_id`) as its own follow-up.

## Where D7a is paused (resume point, 2026-08-14)

Work is intentionally paused here to go pick up the `create_measure_definitions.py`
`ValidValueMember`-linking pyegeria bug (docs/survey-question-context-plan.md
— blocked earlier this session, now possibly unblocked per new pyegeria/
Dr.Egeria commands). **Not a completed thread** — resume by re-reading this
doc's D7a section in full before continuing. State as of the pause:

- **Shipped and live-verified**: the shared `renderSurveyPanel()` component,
  phase+perspective-scoped fetch, wired into all 4 hosts that can show it
  today (Scouting's Survey sub-tab, Discovery unscoped, Assessment's
  Analyses sub-tab, Analysis's Catalog sub-tab) — each phase's own
  `phase=` value threaded through correctly, confirmed against real
  `egeria_git` candidates differing per phase. Repo scheduling of a
  Survey Definition candidate (`_run_repo_survey_definition()` in
  `scheduler.py`) is also shipped, tested, and live-verified (storage
  round-trip only — not fired against real Egeria, see D7a's own note).
- **Real, named, NOT yet done** (in priority order for whoever resumes):
  1. Inline "results of survey executions" per candidate — the third part
     of the original direct request ("Results of the survey executions
     should be presented in the panel"). Today a run's outcome only
     surfaces in the existing run modal, not persisted/rendered back into
     the panel. Needs `AnalysisKindResults`-style results/trend wiring
     extended to Survey Definition candidates, keyed by their steps' step
     keys rather than a single `analysis_id` — real design work, not
     started.
  2. Enrichment's Survey panel instance — **shipped 2026-08-15**, wired
     the same shared `_loadSurveyPanel()` component in, live-verified.
  3. `run_survey_definition()`'s own real gaps this thread surfaced but
     didn't touch: D1 case 3's `executes_at="egeria"` stub — pre-existing,
     named earlier in this doc, unrelated to D7a specifically, still
     open. D6's dependency/sequencing gap is now designed (2026-08-15,
     see D6 above) though not yet implemented.
- **Known duplication, not resolved**: Scouting's "Run Scouting Scan"
  button and the Survey panel below it can both trigger the same
  "Repo Coarse Scout" Survey Definition — named in D7a's own bullet list,
  not fixed.

## What this doc deliberately does NOT resolve yet

- The exact mechanism for exposing D3's two-state choice in the UI
  (a toggle? two buttons, like Scouting's current "Run Scouting Scan"/
  "Publish registration only" split, generalized?) — simplified to two
  states per direct confirmation ("we only do publish/sniff test").
- ~~D6's actual dependency-declaration design~~ — designed 2026-08-15,
  see D6 above; not yet implemented, D6.5 flags an open confirmation.
- Migrating `refresh_profile()`'s steps into `STEP_REGISTRY` (D5) —
  real, nontrivial refactor, not scoped in detail here.
- Closing the `survey_definition_executor.py` Egeria-trigger stub (D1
  case 3) — named precisely, not designed in detail.
- D7a's open question above (one shared render fn vs. one merged data
  model) — needs to be settled at the start of D7a's implementation pass,
  not guessed at.

## Verification (once pieces of this are built)

- Unit tests per decision as it's implemented — no single verification
  plan for the whole doc, since D1-D7 are separable, differently-sized
  pieces of work, not one PR.
- Live regression check that matters most: after D1's choreography fix,
  re-run a mixed survey (once one exists) and confirm the Egeria-native
  step actually executes and its results are readable back, instead of
  silently skipping as it does today.
- Live check for D3/D4: run a pure-RE Survey Definition, confirm the
  default now publishes; explicitly opt out, confirm it doesn't; run one
  containing an Egeria-native step, confirm there's no opt-out control
  shown for it at all (not just disabled — absent, since it's not a real
  choice).
