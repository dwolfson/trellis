# Curate as evidence-based decision-making — outside-in design

**Status:** design pass, not yet built. Companion to `docs/blueprint-materialization-plan.md` (the
inside-out pass, same day, 2026-09-03). This document does not replace that plan; §D reconciles
the two file by file.

**Origin:** the project owner's own framing, verbatim — "My main comment on the Blueprint
Materialization Plan is that it looks at the issue from the inside out... I think we need to
complement it by looking at the outside-in... how does someone use this and where. I think it is
assumed that there are new tabs under curate. These tabs might be different for different kinds
of resources. For Repos, we might have tabs about Blueprints/Components and Information Supply
Chains, maybe some certification ones to test if a repo could be certified by local (organization)
certification standards... things where we present evidence and ask a human for judgement or
approval of recommendations. For databases, we might have tabs more focused on schema recovery
and class determination... take another look at Blueprint Materialization as a first example /
experiment of evidence based decision making... see how the outside in and inside out, meet in
the middle."

---

## Context (confirmed by reading, 2026-09-03)

- **Curate is flat, single-pane, one entry point.** `showCuratePane()` (`index.html:2119`) calls
  `showMainView('curate')`; `loadCuratePanel()`/`renderCuratePanel()` (`index.html:8748-8895`)
  render one scrolling `<div id="curate-view">` with Project Group, Tags, Feedback, Curator Notes,
  and a closing "not here yet" note. No sub-tab structure exists anywhere in Curate today — the
  shape Automate already has (`_automateSubnavHtml`, `index.html:8377-8388`: a `subnav-bar` of
  buttons, `_setAutomateSubTab`, one `loadAutomatePanel()` dispatcher) is real, working, and
  unused by Curate. This is the ready-made mechanism for tabs, not something to invent.
- **`analysis_catalog.yaml` already differentiates by `resource_types` per entry** (confirmed,
  header comment + every entry). Two `intent: curate` entries exist today (`egeria_publish` for
  repos, `egeria_db_survey` for databases), both `action: "publish"`, one-click, no evidence, no
  human verdict on a proposal — nothing in the catalog today is shaped like "review evidence,
  render a verdict."
- **Component verdicts are the one existing instance of the shape the brief names**
  (`curate.py`'s `ComponentVerdictCreate`/`add_component_verdict`, `registry.py`'s
  `architecture_component_verdicts`/`architecture_materialized_components`,
  `ComponentMaterializer`). Confirmed: proposal (a `candidate_blueprint`/component finding) →
  evidence (the finding's `detail`) → human verdict (`accepted|rejected|retyped`) → action on
  accept (`ComponentMaterializer.materialize`) → audit trail (append-only verdict table +
  `list_component_verdict_history`). This is real, live-shaped precedent, not aspiration.
- **Certification does not exist in any form.** `grep -rn "certif" resource_explorer/ -i`
  (excluding tests/pycache) returns nothing. But the raw evidence a certification check would read
  already exists and is check-by-check: `foss_scorecard.py` (OpenSSF-Scorecard-shaped, explicit
  `pass/fail/not_established` per check, deliberately excludes unevaluable checks from the score
  rather than penalizing them — same "absence ≠ measured-zero" discipline this whole codebase
  enforces), `security_features.py` (GitHub's native security-toggle state, one
  `ClassificationAnnotation` per feature), `security_hygiene.py` (artifact presence: SECURITY.md,
  CI config, LICENSE, emits `RequestForActionAnnotation` per gap). All three already compute "does
  this repo meet bar X" at check granularity; none packages that into a certification a human
  approves. This is a materialization gap, not an evidence gap.
- **Database schema/class-determination evidence exists**
  (`resource_explorer/surveyors/database/`: `database_surveyor.py`, `egeria_database_surveyor.py`,
  `hybrid_database_surveyor.py`, `sql_analyzer.py`) but no existing *proposal* object analogous to
  `candidate_blueprint` — no "candidate schema class" finding, no verdict route. **This is stated
  as unresolved, not designed concretely** — see §A for what would need to be true first.
- **Information Supply Chains are explicitly deferred**, §9 of `architecture-recovery.md`: "derive
  wires, offer candidates, let humans/agents name and bound them... explicitly not in the Phase
  1–5 plan." Confirmed real and cross-repo by nature (§9: "real supply chains cross system
  boundaries").
- **RFA (`rfa_actions`) is a different mechanism.** It answers "someone needs to look at this and
  decide what to do about it" for a *request* — assign/defer/reassign/complete/dismiss, syncing to
  a real Egeria `ToDo`. It carries no evidence bundle, no accept/reject-a-proposal semantics, and
  no materialization-on-accept action; it is about disposing of a task, not judging a claim.
  `architecture-recovery.md` §7.3 already names RFAs as a *feeder* into curation — RFA points a
  curator *at* Curate, it doesn't replace it. `egeria-integration.md` §11 also records the broader
  intent directly: "any RE-side item needing a human decision is a candidate for the same [ToDo]
  projection" — which argues for verdicts eventually projecting to Egeria ToDos too, not for
  reusing RFA's local table as the verdict store itself.
- **CLAUDE.md's Curate row**: "make a resource easier to find and more trustworthy to reuse —
  search tags, resource-level feedback, curator notes." The Enrichment-vs-Curate paragraph draws
  its line on *what kind of statement* is being recorded (facts about the resource vs. ongoing
  curatorial commentary), not on *whether a system proposed something*. Evidence-based
  accept/reject of a system-generated proposal is neither "facts about the resource" (Enrichment)
  nor "commentary/discoverability work" (Curate's current wording) — it's a third thing that
  already lives inside Curate's code (`add_component_verdict`) without living inside Curate's
  *definition*.

---

## A. The terrain, extended past the brief's own examples

| Resource type | Evidence topic | State today |
|---|---|---|
| Repo | Blueprints/Components | Real: `candidate_blueprint`/component findings exist, single-component verdict route exists, blueprint verdict route is the inside-out plan's subject. |
| Repo | Information Supply Chains | Real signal (`iscQualifiedNames` on wires), explicitly deferred, and *structurally different*: cross-repo, so its evidence review can't be scoped to "one resource's Curate tab" the way blueprints/components can — a repo-scoped tab would show nothing until multiple repos are analysed and joined. This is not a later arrival of the same tab; it needs a resource-*group*-scoped or cross-resource surface. Treat as its own, later design problem, not a stub inside the Repo tab set. |
| Repo | Certification | Does not exist. Evidence exists per-check (`foss_scorecard`, `security_features`, `security_hygiene`). A certification check-by-check evidence would read from three already-computed per-check verdicts (`pass`/`fail`/`not_established`) plus their scores, packaged as one proposal ("does this repo meet org standard X") with a recommended verdict derived from a policy threshold, and a human accept/reject of *that* recommendation — not of each underlying check individually. This is the shape §B generalizes toward, but is not scoped to a route/table in this pass — no policy-threshold model, no "org standard" catalog exists yet, and that's a real prerequisite, not a detail to invent here. |
| Database | Schema recovery / class determination | Evidence-collection real; no candidate-proposal object, no verdict route. Genuinely not enough is known to design the proposal shape concretely — what does a "candidate schema class" finding even look like (a table? a group of tables? a semantic type over columns?) is itself unanswered by what exists today. What would need to be true first: a pass that emits a *proposal* finding (candidate class per table/column-group, analogous to `candidate_blueprint`) before there's anything for a curator to accept or reject. |
| Filesystem | — | **Considered, not silently excluded.** No analog named in the brief, and no evidence-generating surveyor producing proposal-shaped findings for filesystem resources was found. The honest placeholder: filesystem's Curate tab set stays exactly what it is today (tags/feedback/notes only) until a filesystem analysis exists that proposes something a human would judge. |

---

## B. The general shape

**Decision: yes, one general shape holds, tested against all four (blueprints, components,
certification, and the deferred/unknown schema-class case) — a proposal is `(evidence,
recommended_verdict | none, decision, action_on_accept, audit_trail)`.**

- **evidence** — the finding(s) the proposal rests on (`detail` JSON, confidence, source
  analyzer).
- **recommended_verdict** — present for component/blueprint (none — the analysis proposes, does
  not itself judge) and would be present for certification (a policy-threshold pass/fail computed
  from the underlying checks) — the shape tolerates "no recommendation, just evidence" and "a
  computed recommendation" as two instances of the same optional field, not two different shapes.
- **decision** — `accepted | rejected | retyped` today; certification would need at minimum
  `accepted | rejected`, arguably `waived` (a human overriding a failed policy check with a
  reason) — an extension of the vocabulary, not a break from it.
- **action_on_accept** — `ComponentMaterializer`/`BlueprintMaterializer` for repo structure; for
  certification, plausibly nothing structural in Egeria at all, or a
  `GovernanceDefinition`/certification-type element — genuinely open, not invented here.
- **audit_trail** — append-only verdict history, already generalized (the inside-out plan's
  Decision 3 extends `architecture_component_verdicts` with `verdict_target` for exactly this
  reason).

**Recommendation: extend `analysis_catalog.yaml` with a new field marking an entry as
review-and-decide-shaped, rather than building a parallel catalog.**

Rejected alternative: a wholly separate "decision catalog," parallel to `analysis_catalog.yaml`.
Rejected because the catalog's existing `resource_types`/`intent`/`action` fields already carry
exactly the differentiation this needs, and a parallel catalog would immediately face the same
"two homes for one shape" problem the inside-out plan's Decision 3 explicitly avoided for verdict
tables. Concretely: add `action: "review"` as a third value alongside the existing
`"survey"`/`"publish"` (`egeria_publish`'s comment already gestures at this axis — `"review"` is a
third kind of catalog-of-record interaction, "a human judges a proposal before anything writes").
A `review`-shaped entry additionally declares which finding `kind`/`check_name` supplies its
evidence and, optionally, a `verdict_target` string identifying which table/column shape its
verdicts use (`"component"`, `"blueprint"`, and later `"certification"`, `"schema_class"`) —
reusing the inside-out plan's `verdict_target` column convention rather than minting a fourth
mechanism. `egeria_publish`/`egeria_db_survey` stay `action: "publish"` (one-click writes with
nothing to review); the *new* blueprint/certification/schema-class entries become `action:
"review"` entries with `resource_types` scoping exactly as today.

**What is not recommended yet:** a fully generalized `ReviewableProposal` base class/route in
Python. `ComponentMaterializer`/`BlueprintMaterializer` are correctly resource-type-specific and
forcing a shared abstraction across only two real instances (component, blueprint) plus one
hypothetical (certification) is premature — the same "don't build it repo-shaped, but don't
over-abstract from n=2" tension `architecture-recovery.md` §17 already names. The catalog-level
marker (`action: "review"`) is the generalization that's ready now; a shared verdict-route helper
is worth doing once there are three real instances, not two.

---

## C. Navigation/UI shape

**Decision: tabbed by resource type first is wrong — resource type is already the ambient
context, so the first-level split is by evidence-topic, resource-type-scoped content within each
topic, reusing `_automateSubnavHtml`'s exact pattern.**

Rejected alternative: resource-type-first (Repos → {Blueprints, ISC, Certification}, Databases →
{Schema, Class}). Rejected because Curate, like every other intent pane in this app, is already
entered *from* a selected resource — `showCuratePane()` already knows the entity type before the
pane renders, the same way Assessment/Analysis/Understanding do. What varies per resource type is
*which tabs appear at all* — exactly what `analysis_catalog.yaml`'s existing `resource_types`
filter already computes for every other intent pane's menu.

```js
function _curateSubnavHtml(entityType, active) {
  const tabs = [
    { tab: 'general', label: '🏷 Tags & Feedback' },   // today's flat content, unchanged
  ];
  if (entityType === 'repo') {
    tabs.push({ tab: 'blueprints', label: '🧩 Blueprints / Components' });
    // Certification tab added once a certification review entry exists in
    // the catalog — gated the same way, not hardcoded, so an empty tab
    // never ships ahead of real content.
  }
  // database: schema/class tab added once a proposal-shaped finding exists
  // (see §A) — not stubbed in ahead of it.
  ...
}
```

- **What a curator lands on for a repo**: `🏷 Tags & Feedback` (today's whole `renderCuratePanel`
  content, unchanged, just now under one tab instead of the whole pane) is the default/first tab;
  `🧩 Blueprints / Components` is a new tab holding the inside-out plan's
  `_renderCandidateBlueprints` output plus the existing single-component verdict controls (today
  those render inline in the architecture-recovery results panel under Analysis — see §D for what
  moves).
- **What a curator lands on for a database**: `🏷 Tags & Feedback` only, today — no second tab
  ships until a proposal-shaped finding exists to review (§A).
- **Where today's content goes**: nowhere new — Project Group/Tags/Feedback/Curator Notes stay
  exactly as `renderCuratePanel` builds them today, just wrapped under the `general` tab. Nothing
  currently in Curate disappears or moves function; only the pane's outer chrome changes.

---

## D. Reconciliation with the inside-out plan — concrete, file by file

Going through `blueprint-materialization-plan.md`'s decisions in order:

1. **Decision 1 (per-level verdicts, no cascade) — still holds as designed.** Nothing about where
   the UI lives changes the governance rule about parent/child cluster acceptance. No change.
2. **Decision 2 (member components must be individually accepted first) — still holds as
   designed.** Same reasoning, unaffected by placement. No change.
3. **Decision 3 (reuse `architecture_component_verdicts` with `verdict_target`, not a parallel
   table) — holds, and §B extends the same instinct one level up:** the catalog-level `action:
   "review"`/`verdict_target` marker this document proposes is the *catalog* analog of the
   *table* decision the inside-out plan already made. When certification eventually needs a
   verdict store, it should extend `verdict_target` (`'certification'`) on the same table,
   following this precedent, rather than a third table. **No substance change to Decision 3
   itself** — this document confirms it generalizes correctly rather than overturning it.
4. **Decision 4 (`architecture_materialized_blueprints` table) — still holds as designed.**
   Unaffected by UI placement.
5. **Decision 5 (outbox-first, wires flagged as open risk) — still holds as designed.** Entirely a
   backend/registry concern, orthogonal to where the review UI lives.
6. **Registry additions section — still holds as designed**, no schema changes.
7. **`BlueprintMaterializer` (new file) — still holds as designed.** Backend, unaffected.
8. **`egeria_outbox.py` additions — still holds as designed.** Same.
9. **Route (`curate.py`'s `BlueprintVerdictCreate`/`add_blueprint_verdict`/
   `list_blueprint_verdicts`) — holds but needs the catalog marker added alongside it.**
   Concretely: when `analysis_catalog.yaml` gains the `action: "review"` marker (§B), add one new
   entry (`id: blueprint_verdict_review` or similar), `resource_types: ["repo"]`, `intent:
   curate`, `action: "review"`, pointing at `kind="architecture_blueprints"`/
   `check_name="candidate_blueprint"` — new work the inside-out plan didn't need to specify (it
   assumed the results lived inside Analysis's existing architecture-recovery panel, not a
   catalog-driven Curate tab). The route's actual endpoints are unchanged in substance — only
   which frontend surface calls them changes.
10. **Frontend section — this is where outside-in changes something real, in substance, not just
    placement.** The inside-out plan's frontend step 2 bolted `_renderCandidateBlueprints` onto
    Analysis's existing architecture-recovery results panel. Outside-in's finding (§C) is that
    this is the wrong home: architecture-recovery is an Analysis-intent surface
    (structural/quantitative, not scored — CLAUDE.md's own Analysis row), and blueprint *review*
    is a Curate-shaped activity that happens to read Analysis's own findings as its evidence.
    Three concrete changes to the plan's Phase C:
    - `_renderCandidateBlueprints(blueprints)` itself is **unchanged code**, but is called from a
      new `loadCurateBlueprintsPanel()` under Curate's new `blueprints` sub-tab (§C), not from
      `_renderArchitectureRecoveryResults`. Category: *holds but needs to move*.
    - The backend prerequisite (`_architecture_recovery_results` gaining `data.blueprints`) still
      holds exactly as written — a data-shape concern, not a UI-placement concern.
    - **What changes in substance**: the plan's verdict controls
      (`_archVerdictControlsHtml`/`_archSubmitVerdict` pattern) currently live embedded in
      Analysis's results tree. Under the outside-in shape, Curate's Blueprints/Components tab
      becomes the *only* place verdict controls render — Analysis's architecture-recovery panel
      becomes read-only evidence display, and Curate is where a curator actually clicks
      accept/reject, consistent with Analysis being "not scored" (CLAUDE.md) and Curate being
      where judgment happens. This also resolves an inconsistency the inside-out plan didn't have
      to confront: `add_component_verdict`'s controls today already render inside Analysis's
      results view (single-component case) — the recommendation is that this was itself already
      slightly wrong, and blueprint verdicts moving to a proper Curate tab is the moment to also
      relocate the existing single-component verdict controls there, so both proposal kinds
      (component, blueprint) live in the same tab rather than splitting one evidence-topic across
      two intents. **This is a real, if modest, scope addition to the inside-out plan's Phase C**:
      moving `add_component_verdict`'s existing frontend controls, not just adding new ones.
11. **A third evidence-topic (certification) does NOT change how
    `BlueprintVerdictCreate`/`verdict_target` should be modeled** — Decision 3's `verdict_target`
    column design already anticipated exactly this (an enumerated string, not a fixed two-value
    type) and extending it to `'certification'` needs no schema change, only a new enum value and
    a new route module. No revision needed there.

---

## Verification / what this pass leaves open

- The certification evidence-packaging (policy thresholds, what "the bar" is per org standard) is
  named but not designed — needs its own pass once a project owner defines what a "local
  certification standard" concretely checks.
- Database schema/class-determination has no proposal-generating analysis yet — this document does
  not invent one; it names the prerequisite.
- ISC's cross-repo review surface is named as structurally distinct from the per-resource tab
  shape and explicitly not designed here — it needs its own outside-in pass once multiple repos'
  wire graphs are being joined, which nothing in the codebase does yet.
- The `action: "review"` catalog field, `_curateSubnavHtml`/`_setCurateSubTab` frontend scaffold,
  and the "move `add_component_verdict`'s controls out of Analysis into Curate" step are concrete
  enough to scope into the inside-out plan's Phase C now; everything else beyond blueprints stays
  a named gap, not an invented spec, per the brief's own instruction (first example/experiment,
  not a finished spec).

### Critical files for implementation

- `resource_explorer/web/static/index.html` (lines 2119, 8377-8402 for the `_automateSubnavHtml`
  pattern to mirror, 8748-8895 for `loadCuratePanel`/`renderCuratePanel` to wrap under a new
  `general` sub-tab)
- `resource_explorer/web/routes/curate.py` (existing `ComponentVerdictCreate`/
  `add_component_verdict` — controls to relocate; new `BlueprintVerdictCreate`/
  `add_blueprint_verdict` per the inside-out plan, now targeted at the new Curate tab instead of
  Analysis)
- `resource_explorer/configdata/analysis_catalog.yaml` (add `action: "review"` value and a
  `blueprint_verdict_review`-style entry; future certification/schema-class entries follow the
  same marker)
- `resource_explorer/surveyors/repo_survey_definition_adapter.py` (`_architecture_recovery_results`
  — still needs `data.blueprints`, per the inside-out plan, now consumed by Curate's tab rather
  than Analysis's panel)
- `docs/blueprint-materialization-plan.md` (Phase C section — needs the frontend-placement
  amendment described in §D above)
