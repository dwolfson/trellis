# Survey Definition ↔ Question/Perspective context, phase-tab propagation

**Status: D1/D2/D3 built, unit-tested (2026-08-13, 1100 tests green), and
live-verified — the Egeria-linkage core is done. All 3 regenerated Survey
Definitions ("Repo Coarse Scout", "Repo Discovery Survey", "Repo Full
Survey") executed live via Dr.Egeria (VALIDATE then PROCESS, 9/16/48
commands respectively, zero failures) — every `ScopedBy` link landed.
Confirmed live end-to-end: `find_candidate_process_guids_by_questions(["Is
this repository actively maintained?"], "Git Repository")` correctly
returns exactly `["Repo Full Survey", "Repo Coarse Scout"]` (not "Repo
Discovery Survey", which never claims to answer that question) — real
scoped lookup, zero `search_string="*"` full-instance scan. D4
(annotation-types linkage) and D5 (authoring UI, deferred by design) not
yet started. **D6 (Questions/Disposition tab propagation) built and
live-verified (2026-08-13)** — Discovery, Assessment, Analysis, and
Enrichment each gained ❓ Questions / 🧭 Disposition sub-tabs, reusing the
exact same shared `#scouting-questions-view`/`#scouting-disposition-view`
panels and backend routes Scouting already used (confirmed live: setting
Discovery's Disposition tab shows the identical repo state/history
Scouting's own tab shows — genuinely shared, not duplicated). Repo-only,
gated by `resourceTypeFacet==='repo' && selectedProject` (`_qdTabsApply()`)
— confirmed live that switching to the DB facet collapses the subnav to
nothing rather than showing an unusable 1-tab bar. Each host defaults
Questions to its own funnel-stage phase on entry (still switchable via the
existing phase chips). No backend changes needed — this was purely a
frontend surfacing of already-phase-agnostic Questions and already-global
Disposition state.

**Pivot (2026-08-14): "what's needed to answer each Question" reuses Egeria's
own Reference Data types, not a new RE-local file/representation.** Per
direct review of https://egeria-project.org/types/5/0545-Reference-Data/ —
`ValidValueDefinition`/`ValidValueSet` (+ `ValidValueMember` hierarchy) is
exactly the mechanism for externalizing an interpretation rule (e.g. "is
this repo actively maintained" → a `ValidValueSet` of labeled tiers, each
citing a real external standard) instead of inventing a parallel format.
Confirmed via pyegeria SDK inspection: `ReferenceDataManager.
create_valid_value_definition()`/`link_valid_value_definition()` are real,
dedicated, well-documented methods — safe to use today. Three related
relationship types (`ValidValuesAssignment` — Question-to-measure-set,
`ReferenceValueAssignment` — tagging an actual result with its resolved
value, `SpecificationPropertyAssignment` — attaching a value to a specific
Annotation Type property) are real Egeria types with **no dedicated
pyegeria method yet** — the user is adding these three in a separate
session. `ScopedBy` (already proven this session) is the interim
substitute for the Question-to-measure-set link until then.

**Pilot built and live-verified (2026-08-14):**
`scripts/create_measure_definitions.py` — idempotent, live-writing script
(no Dr.Egeria command exists yet for Valid Value creation/linking,
confirmed via a full search of egeria-python's compact command specs —
flagged as a real follow-up for whoever adds the 3 pyegeria methods) —
creates a "Repository Maintenance Activity" `ValidValueSet` with 3 members
(Actively/Partially/Not Maintained), each `usage` field citing OpenSSF
Scorecard's real, public "Maintained" check
(https://github.com/ossf/scorecard/blob/main/docs/checks.md) rather than
an invented threshold. Confirmed live: `RepositoryMaintenanceActivity` +
all 3 members exist, an `ExternalReference` to the Scorecard doc was
created and linked via the already-real "Create/Link External Reference"
Dr.Egeria commands (`docs/dr-egeria/measure-definitions-external-
references.md`), and the link shows up in a live `get_valid_value_
definition_by_guid()` graph read (`externalReferences[0].relationshipHeader.
type.typeName == "ExternalReferenceLink"`).

**Two real pyegeria bugs found live, for the user's upcoming SDK session:**
1. `ReferenceDataManager.find_valid_value_definitions()`/
   `get_valid_value_definitions_by_name()` do not reliably surface a
   just-created `ValidValueDefinition` — confirmed via a 409 "qualifiedName
   already in use" on a duplicate-create attempt for an element neither
   method's wildcard/name search could find. Worked around with
   `ClassificationExplorer.get_guid_for_name()` (same generic lookup this
   session already uses for Question GlossaryTerms), which finds it
   reliably. `get_guid_for_name()` itself has its own quirk: returns the
   bare string `"No elements found"` on a miss instead of `None`/`[]` —
   handled in the script, same class of gotcha `survey_definition_reader.py`
   already guards against for other pyegeria calls.
2. **Fixed upstream 2026-08-15, pyegeria 6.0.18.1** (filed as ISSUE-56 in
   egeria-python's `PYEGERIA_ISSUES.md`).
   `ReferenceDataManager.link_valid_value_definition()`'s own documented
   sample body (`"class": "NewRelationshipRequestBody"`) failed
   client-side Pydantic validation — `_async_link_valid_value_member()`
   routed through `_async_create_element_body_request()`, which validated
   via `validate_new_element_request()` (expects `NewElementRequestBody`'s
   Literal, not `NewRelationshipRequestBody`'s). Confirmed reproducible on
   every member-link attempt at the time. **Resumed and re-verified live
   2026-08-15**, same session that reported it: bumped pyegeria to
   6.0.18.1 (`uv lock --upgrade-package pyegeria`), confirmed via
   `inspect.getsource` that the fixed method now calls
   `_async_new_relationship_request` instead, and re-ran
   `create_measure_definitions.py` for real — all 3 `ValidValueMember`
   links that previously failed 100% of the time now succeed, and a
   second run confirms idempotency (find-or-create skips existing
   elements, re-linking an already-linked member doesn't error). The
   `RepositoryMaintenanceActivity` set is now a real, linked hierarchy in
   Egeria, not 4 standalone elements.

**Done (2026-08-15):** the measure-set-to-Question `ScopedBy` link landed —
`create_measure_definitions.py` (with its `link_measure_set_to_question()`
now implemented) re-run live: `Repository Maintenance Activity` is
`ScopedBy` `Is this repository actively maintained?`. This was the
original explicit ask that started the pass below.

**Major unplanned incident + full recovery, same session (2026-08-15):**
mid-way through the above, live discovery that Egeria's state had been
lost to (at least one, likely two) `quickstart-egeria-main` container
restarts caused by another, unrelated session — not by anything in this
codebase or this session's own actions (confirmed via `docker ps` uptime +
`PyegeriaNotFoundException`/`OMAG-MULTI-TENANT-404-001` messages). Lost:
the `User Questions`/`Funnel Stages` glossaries and every term in them (all
41 Questions, all 8 Funnel Stage terms, all 12 Perspective terms), and all
3 repo Survey Definitions (`Repo Coarse Scout`, `Repo Discovery Survey`,
`Repo Full Survey`). The `Repository Maintenance Activity` measure set
itself and its 3 members survived intact (confirmed via
`create_measure_definitions.py`'s own idempotent find-or-create logging —
"found existing", not "created new" — on the re-run above).

User confirmed "re-author everything now" rather than defer. Full
restoration, in order:
1. **Foundations** (`docs/dr-egeria/foundations.md`) — glossaries, 8 Funnel
   Stage terms, 12 Perspective terms. Re-executed clean via Dr.Egeria
   VALIDATE→PROCESS (23/23 commands).
2. **Questions** (`docs/dr-egeria/scouting-questions.md`, regenerated via
   `scripts/csv_to_dr_egeria_questions.py` — which itself needed a schema-
   drift fix first, since the CSV's `Asked At`/`Answered At` columns had
   already collapsed to one `Funnel Stage` column on 2026-08-14 and the
   generator hadn't been updated to match). All 41 questions re-created
   across 6 batched `process` calls (full-file VALIDATE timed out at
   ~50KB; batching by ~7 questions worked). A second, unrelated
   `quickstart-egeria-main` restart happened mid-restoration (again another
   session, again confirmed via `docker ps`) — paused, verified server
   health, resumed per the user's explicit go-ahead, no data loss from the
   already-completed batches.
3. **Survey Definitions** — all 3 regenerated fresh via
   `scripts/generate_repo_survey_definition.py` (cross-references the
   then-freshly-restored Questions) and executed live: Repo Coarse Scout
   (9/9), Repo Discovery Survey (16/16), Repo Full Survey (48/48) — zero
   failures.
4. **Measure-set ScopedBy link** — see "Done" above.

**One real, structural gap found and fixed, plus one authoring-convention
gap in this repo's own docs (corrected 2026-08-15 — see below for the
correction itself):**
- **`Automate` had no Funnel Stage term at all** — missed when the
  original 7-intent set was authored; `Automate` became the 8th canonical
  intent on 2026-08-13 (CLAUDE.md rule 17) but its Funnel Stages glossary
  term was never added. Caught when a Question's `Link Element To Scope`
  against `Automate` failed "not found." Fixed: added the term to
  `foundations.md` and created it live (`82d199eb-...`).
- **5 of the 12 Perspective names collide with pre-existing element names
  in this Egeria instance** (almost certainly the stock Coco
  Pharmaceuticals demo data sharing the same `GlossaryTerm` display
  names): `Governance`, `Steward`, `Privacy`, `Community`, `Security`.
  Every `Link Perspective to Question` command against these 5 failed
  100% of the time (~50+ instances) with `"Multiple elements found for
  supplied name!"`.

  **Correction (2026-08-15, same day, prompted by direct user feedback):**
  the initial write-up here called this a Dr.Egeria resolver defect and
  filed it as such — that was wrong, and worth recording precisely so the
  wrong framing doesn't stick. `Link Perspective to Question`'s
  `Perspective Name` attribute is documented in its own compact-spec
  `description` as **"Qualified name of the Perspective"** — it was never
  meant to take a bare display name at all. `foundations.md` had simply
  never given its Perspective terms an explicit `### Qualified Name`, so
  every `Link Perspective to Question` command in this repo was passing
  the bare `### Display Name` instead — a genuine misuse of the field,
  not a resolver bug. Confirmed live: passing the correct qualified name
  (`Coco Pharmaceuticals::Perspective::Governance::1.0`) resolved cleanly
  on the first try, no ambiguity at all — my own initial attempt to prove
  this had used the wrong qualified-name pattern (`::Term::` instead of
  `::Perspective::`, copied from the Questions' own pattern) and that
  false negative is what led to the wrong "resolver bug" conclusion.
  `egeria-python`'s `PYEGERIA_ISSUES.md` ISSUE-58 has been corrected to
  `n/a — not a bug` with the full story.

  **Real fix landed (2026-08-15):** every Perspective in `foundations.md`
  now gets an explicit, unique `### Qualified Name` (`Perspective::
  <Name>` — deliberately not the auto-generated `Coco Pharmaceuticals::
  Perspective::<Name>::1.0`, to stay portable across Egeria instances
  rather than baking in this instance's default local qualifier/org
  name), applied to all 12 (not just the 5 that happened to collide, for
  consistency). `scripts/csv_to_dr_egeria_questions.py` now emits
  `Perspective::<Name>` in every `Link Perspective to Question` command's
  `### Perspective Name`, and `scouting-questions.md` was regenerated to
  match — future re-authoring passes never hit this wall.

  **A second, real bug found and filed along the way (`PYEGERIA_ISSUES.md`
  ISSUE-59, open):** attempting to apply the new qualified name to the 12
  *already-existing* Perspective elements via Dr.Egeria's own
  `Create Perspective` (`upsert: true`) markdown command — the natural
  way to "rename" something — silently created a **second**, duplicate
  element sharing the same display name each time, rather than updating
  the existing one in place; an explicit `### GUID` attribute on the same
  command had no effect on this either. Caught immediately via
  `get_guid_for_name()` (which started raising "Multiple elements found"
  again right after each attempt) and cleaned up both accidental
  duplicates via `MetadataExpert.delete_metadata_element()` before they
  could cause any real damage. **Actual fix used:** dropped to raw
  pyegeria — `ActorManager.update_perspective(guid, {"class":
  "UpdateElementRequestBody", "mergeUpdate": True, "properties": {"class":
  "PerspectiveProperties", "qualifiedName": "<new value>"}})` — targets
  purely by GUID, no name/QN-based as-is lookup involved, and correctly
  updated all 12 in place (same GUID before/after, confirmed via
  read-back and via the new qualified name resolving to the unchanged
  GUID for every one).

**Follow-up incident + fix (2026-08-13, same day):** executing the
regenerated docs against already-linked processes exposed a real Dr.Egeria
footgun — "Link First/Next Process Step" commands aren't idempotent, so
re-running them duplicated every existing step-to-step edge (1/2/27
duplicates across the three definitions), and Repo Full Survey also had one
genuinely stale edge left over from an earlier chain reordering. Both
looked identical to `SurveyDefinitionReader` — a step with >1 outgoing
edge — and broke `UnsupportedSurveyDefinitionError` ("branching... not
supported") for every candidate. Fixed live via
`MetadataExpert.delete_related_elements()` (confirmed real, generic
relationship-delete method — no dedicated "unlink process step" method
exists in pyegeria), then made repeatable:
`resource_explorer/surveyors/survey_definition_reconciler.py` (pure diff
logic, unit-tested), `SurveyDefinitionReader.reconcile_step_links()` (live
fetch+delete), and `scripts/reconcile_survey_definition_links.py` (CLI,
`--dry-run` supported) — safe to run after any future doc regeneration+
re-execution, idempotent on an already-clean graph. All 3 repo Survey
Definitions live-verified clean and reconciler confirmed no-op against
them.**

## Context

A live-use pass on Discovery surfaced three related gaps (full investigation
already done, no code changed yet):

1. **Slow, uncached Discovery loads.** `SurveyDefinitionReader.find_candidate_process_guids()`
   (`resource_explorer/surveyors/survey_definition_reader.py`) does a live,
   uncached `find_governance_definitions(search_string="*",
   metadata_element_type="GovernanceActionProcess", page_size=1000)` —
   scans **every** `GovernanceActionProcess` in the whole Egeria instance on
   every request, filtering client-side on
   `additionalProperties.supported_technology_type`/`survey_kind`. Plus a
   second live call per candidate (`.fetch()` →
   `get_governance_process_graph`), plus a third live call via a
   freshly-instantiated `EgeriaTechTypeCatalog()` per request (its own cache
   never persists across requests). The existing `survey_definition_cache`
   table (`registry.py` ~L1503) only memoizes one resolved GUID per
   `(entity_type, entity_slug, technology_type)` — it isn't used by, and
   can't help, the candidates-listing route.
2. **`annotation_types` unlinked to any real registry.** Three sources of
   truth exist today with no cross-reference: RE's local Admin "Annotation
   Types" table (`web/routes/analyses.py`, human-curated), `STEP_REGISTRY`'s
   hardcoded Python string lists (`repo_survey_definition_adapter.py`'s
   `StepInfo.annotation_types`), and Egeria's own live native-process data
   (`EgeriaTechTypeCatalog.get_produced_annotation_types()`, shown only for
   non-RE steps). They overlap by naming convention only.
3. **No authoring/editing UI for Survey Definitions**, no phase-assignment
   mechanism, no explicit step→Question link — only the indirect coupling
   of both sides independently referencing the same `analysis_id`/
   `re_analysis_step` string. Definitions are created only by
   `scripts/generate_repo_survey_definition.py`, executed by hand through
   Dr.Egeria.

Discussing (3) surfaced the real fix, not just a UI gap: **`docs/dr-egeria/
foundations.md` already built the exact model needed** — a `User Questions`
glossary (Question terms), a `Funnel Stages` glossary (Scouting/Discovery/
Assessment/.../Curate terms), and `ScopedBy` relationships linking a
Question to its Perspective(s) and its funnel stage(s) via `Asked At`/
`Answered At` scope categories. `question_catalog_reader.py`'s own header
comment already names this exact next step and defers it: *"A future pass
could query Egeria's real Question/Perspective/ScopedBy elements directly
... deliberately not built yet."* Survey Definitions (the `GovernanceActionProcess`
elements) are the missing link — they carry `additionalProperties` today
(`supported_technology_type`, `survey_kind`) but nothing connecting them to
Questions or Perspectives. Explicit user direction this session: build
*real* Question/Perspective association onto Survey Definitions in Egeria,
then use that association to drive **better, narrower queries** — replacing
(or augmenting) the current `search_string="*"` full-catalog scan with a
scoped lookup, rather than only caching the slow scan.

Separately, a related but distinct request: surface the (already
phase-agnostic) Questions checklist tab, and the currently Scouting-only
Disposition tab, inside Discovery, Assessment, Analysis, and possibly
Enrichment — not just Scouting.

## Key decisions

**D1 — Link Survey Definitions to Questions/Perspectives via Egeria
relationships, reusing `foundations.md`'s existing glossaries — no new
Egeria concepts.** Each Survey Definition (`GovernanceActionProcess`) gets
`ScopedBy` relationships to the specific `User Questions` terms it answers
(mirroring how a Question is already `ScopedBy` its `Funnel Stages`/
Perspective terms) — i.e. the same pattern foundations.md already applies
to Question elements gets applied one level up, to the Survey Definition
that answers those Questions. This is additive to the existing
`docs/dr-egeria/repo-survey-definition-*.md` generator output — the Dr.Egeria
command needs a new "Link Element To Scope" (or equivalent
Question-relationship) block appended per generated Survey Definition,
driven by `STEP_REGISTRY`'s existing step→description knowledge
cross-referenced against `question_catalog.yaml`'s `answering.analysis_ids`
(the join key already exists: `analysis_ids` on a `QuestionAnswering` ↔
`analysis_catalog.yaml` id ↔ `STEP_REGISTRY` step key, confirmed at
`repo_survey_definition_adapter.py` and `question_catalog_reader.py`).
`scripts/generate_repo_survey_definition.py` gains this cross-reference
step so regeneration keeps the links current — not a one-off hand edit.
**Confirmed real pyegeria method for the write side**:
`ClassificationExplorer.add_scope_to_element(scoped_by_guid, element_guid)`
(`pyegeria/omvs/classification_explorer.py` ~L6627) — creates exactly the
`ScopedBy` relationship this needs, `scoped_by_guid` = the Question term's
GUID, `element_guid` = the Survey Definition's GUID. No generic-body
guessing required here (unlike the Automate NotificationType case) — this
is a small, dedicated, already-real method. `generate_repo_survey_definition.py`
calls it directly per (step, question) pair after creating/finding both
elements, rather than routing through a Dr.Egeria markdown "Link Element
To Scope" block — simpler and avoids depending on that command actually
existing/matching this exact relationship shape.

**D1a — Funnel Stage representation: GlossaryTerm, confirmed (already
built, not being reconsidered).** `foundations.md`'s "Funnel Stages"
glossary — one term per stage — is the right, minimal-risk choice, not
just an accident of how it happened to get built. The alternative Egeria
offers for a closed enumeration is `ValidValueDefinition`/
`ValidValueAssignment`, which is the more "correct" construct for a
type-checked, single-select controlled vocabulary — but stages here aren't
being used as a constrained field value on some other element's property;
they're being used as a **shared relationship endpoint** that Questions,
Perspectives, and (via D1) Survey Definitions all point at via `ScopedBy`.
GlossaryTerm already satisfies that (it's a `Referenceable`, same as
everything else in this graph), is human-browsable/editable through the
existing glossary UI without any new tooling, and keeps Perspectives and
Funnel Stages in the same representational family (a glossary term either
way) rather than splitting the vocabulary mechanism in two for one part of
it. Introducing `ValidValueDefinition` now would mean re-authoring what's
already live for a type-enforcement benefit nothing in this design actually
needs. Decision: keep GlossaryTerm, don't reopen it.

**D1b — Relationship mechanism: `ScopedBy`, confirmed.** Per direct
confirmation: `ScopedBy` works between any two `Referenceable` (sub)types,
which covers Questions, Perspectives, Funnel Stage terms, and Survey
Definitions (`GovernanceActionProcess` is a `Referenceable`) uniformly —
no type-specific relationship needed. Other Egeria relationship types could
carry similar semantics (e.g. a generic `SemanticAssignment`, or a
bespoke new relationship type), but `ScopedBy` is already the mechanism
`foundations.md` uses for the identical "this element belongs to that
broader concept" shape (Question → Perspective, Question → Funnel Stage),
so reusing it for Survey Definition → Question keeps one relationship
vocabulary across the whole graph instead of introducing a second one for
no semantic gain.

**D2 — Scoped query, not just a cache. Confirmed pyegeria method, no
capability-check gap.** `ClassificationExplorer.get_scoped_elements(scope_guid)`
(`pyegeria/omvs/classification_explorer.py` ~L1773) returns every element
linked via `ScopedBy` to a given scope element — exactly the query D1's
links need: given a Question's (or Funnel Stage's, or Perspective's) GUID,
this returns every Survey Definition scoped to it directly, no
`search_string="*"` full-instance scan required. (`get_scopes(element_guid)`,
~L1639, is the inverse direction — given a Survey Definition, list what
it's scoped to — useful for the eventual authoring/editing UI in D5, not
needed for candidate-finding itself.) `SurveyDefinitionReader` gains a new
candidate-finding path: resolve the relevant Question/Perspective/Funnel-Stage
term GUID(s) for the requested phase (small, cacheable lookup — these
change rarely), then call `get_scoped_elements()` per relevant scope GUID
and union/intersect the results, instead of today's
`find_governance_definitions(search_string="*", ...)`. The full-scan path
stays as an explicit "show all Survey Definitions" fallback (e.g. an
Admin/debug view), not removed.

**D3 — Cache what D2 can't avoid.** Even a scoped query still needs the
occasional full-catalog view and the per-candidate `.fetch()` graph call.
Add a request-scoped-to-short-TTL cache (e.g. an in-memory dict keyed by
`(phase, perspectives, technology_type)` with a short TTL — minutes, not
persisted — since Survey Definitions change rarely but not never) around
`find_candidate_process_guids()` and `.fetch()`, and make
`EgeriaTechTypeCatalog` a module-level singleton instead of
per-request-instantiated, so its own internal cache actually persists.
This is the mechanical "make it fast" half; D2 is the "make it correct"
half — both are needed, D2 doesn't make D3 redundant since even a scoped
query benefits from not re-fetching on every page load.

**D4 — `annotation_types` linkage stays a separate, later concern.**
Investigated but not solved by D1-D3 — noted here so it isn't lost, but
explicitly deferred: reconciling RE's local Admin registry, `STEP_REGISTRY`'s
hardcoded lists, and Egeria's live native data needs its own pass once the
Question/Perspective linkage (which touches the same generator script) is
solid, so the two efforts don't collide mid-flight.

**D5 — Survey Definition authoring/editing UI stays deferred.** D1's
Dr.Egeria-generator approach is still the creation path for now — a live
in-app authoring UI is a bigger, separate piece of work not undertaken in
this pass. Only the generator script and its Dr.Egeria template output
change (to emit the new ScopedBy links).

**D6 — Propagate Questions + Disposition tabs to Discovery, Assessment,
Analysis, and Enrichment.** Questions: mechanical — `GET /{slug}/
scouting-questions?phase=X` (`web/routes/projects.py:461`) already accepts
any phase string and `question_catalog_reader.get_questions(phase=...)` is
already phase-agnostic; each target intent gets its own sub-tab calling the
same route with its own phase name, reusing Scouting's existing render
function rather than duplicating it. Disposition needs more care —
`repo_dispositions` (`decided_by`/`reason`/history) was modeled around
Scouting's specific triage decision (`undecided/tracking/investigating/
abandoned/ignored`); reusing the identical table/states elsewhere is
probably right (a resource's disposition is one fact, not one fact per
phase — matches D10 from the Scouting redesign plan, which already made
disposition global-not-per-phase), so this is a **read/write-access
change, not a data-model change**: add the same disposition control +
history view to each target intent's own sub-tab rail, all reading/writing
the same `github_url`-keyed row Scouting already does. "Maybe Enrichment"
(the user's own hedge) resolved as: yes — Enrichment is exactly where a
human might revisit and change a disposition after adding context, so it
belongs there too, no different treatment needed.

## Implementation

**`docs/dr-egeria/foundations.md`**: no change (already has the model).

**`scripts/generate_repo_survey_definition.py`**: extend to cross-reference
`question_catalog.yaml` via each step's `analysis_catalog.yaml` id, emit
`ScopedBy`/Question-link Dr.Egeria blocks per generated Survey Definition.

**`resource_explorer/surveyors/survey_definition_reader.py`**: D2's scoped
candidate-finding method (exact call shape TBD pending pyegeria
capability check); D3's caching around `find_candidate_process_guids()`/
`.fetch()`.

**`resource_explorer/web/routes/survey_definitions.py`**: `EgeriaTechTypeCatalog`
becomes a module-level singleton (D3); candidates route gains optional
`phase`/`perspectives` query params wired to D2's scoped path.

**`resource_explorer/web/static/index.html`** (D6): Discovery/Assessment/
Analysis/Enrichment intent panels each gain a "❓ Questions" sub-tab
(reusing Scouting's existing Questions render function, parameterized by
phase name) and a "⚖ Disposition" sub-tab (reusing Scouting's existing
`loadScoutingDispositionView()`, generalized to not assume the Scouting
sub-nav's own state variable).

## Open questions (before implementation)

None remaining that block starting — D1's write side
(`add_scope_to_element`) and D2's read side (`get_scoped_elements`/
`get_scopes`) are both confirmed real, dedicated `ClassificationExplorer`
methods, not generic-body guesses.

**Resolved:** whether Discovery should show Disposition/Questions at all —
yes. Discovery launches Survey Definitions against a *particular cataloged
asset* (confirmed by the user directly) even though it adds no new data of
its own — it has the same per-entity context Scouting/Assessment/Analysis
do, so D6's tab propagation applies to it the same way, no special case
needed.

## Verification

- Unit tests: generator script's new Question-link emission (given a step
  with known `analysis_catalog.yaml` id, confirm the right Question terms
  are cross-referenced); D2's scoped-query builder (mocked pyegeria call,
  various phase/perspective combos); D3's cache (TTL expiry, singleton
  reuse across requests).
- Route tests: candidates route with `phase`/`perspectives` params;
  Questions/Disposition sub-tab routes for each of the 4 newly-added
  intents.
- Live: regenerate one repo Survey Definition via Dr.Egeria, confirm its
  ScopedBy Question links appear when reading it back; confirm a
  phase-scoped Discovery load is measurably faster than today's full scan;
  confirm Disposition set from e.g. Assessment is visible from Scouting's
  own Disposition tab (same row, same history) and vice versa.
- Full RE test suite green.
