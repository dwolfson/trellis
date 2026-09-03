# Blueprint materialization — implementation plan

**Status:** planned, not yet built. Written 2026-09-03 (Opus-model plan pass), scoping
Backlog.md item 1 ("Phase 2 — Egeria projection of recovered architecture").

Referenced from `docs/Backlog.md`'s item 1. Read that entry first for how this plan's
prerequisites (outbox/retry, candidate-cluster proposal) were confirmed already built before
this plan was written.

---

## Context (verified by reading, 2026-09-03)

**What exists and must be reused, not redesigned:**

- `resource_explorer/surveyors/arch_recovery/materializer.py` — `ComponentMaterializer`. Owns its own `SolutionArchitect`/`AutomatedCuration` connection, find-or-create by qualifiedName (`SolutionComponent::{entity_type}::{entity_slug}::{scope_locator}`), backed by `architecture_materialized_components` (one row per scope, `INSERT OR REPLACE`-keyed). Builds `properties["class"] = "SolutionComponentProperties"` inside a **`NewElementRequestBody`** (`isOwnAnchor: true`) — which pyegeria's own docstring says defaults the element to **ACTIVE**, not Draft. Triggered synchronously from `curate.py`, one write, no outbox.
- `egeria_outbox.py` + `registry.py`'s `egeria_outbox` table. `enqueue_outbox_element(entity_type, entity_slug, element_kind, qualified_name, payload, *, run_id="", depends_on_id=None)` records a row; `claim_due_outbox_elements` only returns a row once its **single** `depends_on_id` (if any) is `done`; `drain_outbox` applies via a `_CREATORS: dict[element_kind, Callable]` registry, keyed by `element_kind`. Two idempotency shapes already proven live, and they are NOT the same shape:
  - **qualifiedName search-then-create** (`annotation`) — safe to retry because there's a stable name to search for.
  - **create-blind, relationship measured uni-link** (`collection_membership`, `resource_list`, `annotation_link`) — safe to retry *only because* each of `add_to_collection`, `attach_collection`, and `AnnotationExtension` was independently measured live (2026-08-25, 2026-09-01) to collapse a duplicate create onto the single existing relationship.
- `clustering.py`/`persist.py._persist_blueprints`. Writes `candidate_blueprint` findings under **`check_name="candidate_blueprint"`, kind=`"architecture_blueprints"` (the `BLUEPRINT_KIND` constant), scope_locator=""** — i.e. every cluster for a repo is a separate finding row at the *same* empty scope, distinguished by `label=cluster.name`. `detail` carries `name`, `perspective`, `signal`, `carrier`, `composed_into`, `size`, `members` (**component *slugs*, not scope_locators** — confirmed by reading `clustering._build`: `Cluster.members = sorted(slugs)`, built from `by_scope[scope] = [slug, ...]`), `children` (child cluster *names*), `parent`, `oversized`, `target_size`, `run_scope`, `not_a_claim: True`.
- `curate.py`'s single-component verdict route + `registry.py`'s `architecture_component_verdicts` (append-only, keyed by `scope_locator`) / `architecture_materialized_components` (current-state, `INSERT OR REPLACE`, also keyed by `scope_locator`).

**The one identity mismatch that will bite silently if missed:** clustering keys a blueprint's members by **component slug**; verdicts and materialization are keyed by **`scope_locator`**. `_architecture_recovery_results` (`repo_survey_definition_adapter.py:2374`) already builds a `slug_to_path: dict[str, str]` (from each component finding's `detail["slug"]` → its scope) for exactly this reason. Any blueprint code that reads `cluster.members` and looks them up in `get_materialized_components()`/`get_component_verdicts()` directly, without going through that slug→scope_locator map first, will silently find nothing for every member — a confident-empty-answer bug, the exact failure class `find-absence-as-answer` names.

**A second load-bearing measurement gap, confirmed by reading pyegeria (not assumed):** `SolutionLinkingWire` (`solution_architect.py:4169`, `link_solution_linking_wire`) is explicitly **multi-link** — its own docstring says "SolutionLinkingWire allows more than one wire between the same pair of components" and it returns the new relationship's own GUID (needed to target it later for update/detach), unlike `CollectionMembership`/`ResourceList`/`AnnotationExtension`, which the outbox's existing `_CREATORS` rely on being uni-link. **Wires cannot reuse the create-blind pattern.** This is a real, unresolved risk this plan has to design around explicitly (see Decision 5).

**Confirmed NOT built, matching the Backlog entry:**
- No `BlueprintMaterializer` (`grep -rn "SolutionBlueprint" resource_explorer/` hits only `clustering.py`'s design comment and `mermaid.py`'s unrelated diagram code).
- No blueprint verdict route/table — `curate.py`'s `ComponentVerdictCreate`/`add_component_verdict` and `registry.py`'s `COMPONENT_VERDICTS`/`architecture_component_verdicts` are single-component-scope-locator only.
- Zero frontend surface — `grep -n "candidate_blueprint" index.html` returns nothing, and `_architecture_recovery_results` never reads `kind="architecture_blueprints"` findings at all, so nothing produces `data.blueprints` for the renderer to show even in principle.

---

## Decisions (with the alternative rejected, and why)

**1. Nested clusters: each level gets its own independent verdict, not "accept parent → cascade to children."**

Rejected alternative: accepting a parent cluster implicitly accepts and materializes every descendant blueprint too (fewer clicks). Rejected because §3.3a is explicit that a parent blueprint's *membership* is of its child blueprints as `Collection` members via ordinary `CollectionMembership` — nesting is a fact about Egeria's Collection type, not a governance shortcut — and §17's whole premise ("a curator may decline to materialise... only meaningful if declining is the default") applies per-level: a curator may want the top-level "Egeria" blueprint but reject one bloated auto-generated child cluster underneath it. Cascading acceptance silently forecloses that. Concretely: `candidate_blueprint` findings for a parent and its children are **separate findings** (same `detail.parent` linkage `_persist_blueprints.rows_for` already writes), so they get **separate verdict rows**, keyed by cluster name (see Decision 3). `BlueprintMaterializer.materialize()` on a parent blueprint attaches only children that already have their own `accepted` verdict *and* are already materialized (their `SolutionBlueprint` GUID looked up the same way `ComponentMaterializer` looks up components) — an unaccepted/unmaterialized child is a member the parent write **cannot yet attach**, reported back to the curator rather than silently skipped or auto-materialized on their behalf.

**2. Member components: accepting a blueprint requires every member to already be individually accepted+materialized. It does NOT implicitly accept them.**

Rejected alternative: "accept blueprint" as one click that accept-and-materializes every member component that isn't already accepted (fewer clicks, matches curator intuition — "yes, ship this whole group"). Rejected for the governance reason the task brief names directly: a `SolutionComponent` a curator never explicitly looked at, attached into a real blueprint because a *different* decision ("group these together") implicitly decided it too, is exactly the "confident wrong answer nobody checked" pattern. It's also consistent with what's already shipped: `ComponentMaterializer` is deliberately the *only* thing that mints a `SolutionComponent`, and its own docstring frames "accepted" as a human decision about one entity — reusing that class for members means a blueprint accept can't skip it. Concretely: `BlueprintMaterializer.materialize()` resolves each `cluster.members` slug → scope_locator (via the same map `_architecture_recovery_results` builds) → `registry.get_materialized_component(entity_type, entity_slug, scope_locator)`. Any member with no row is **not attached**, and is reported in the result (`{"unmaterialized_members": [...]}`) so the curator sees exactly which components still need their own accept. The frontend surfaces this as a blocking (or at minimum loudly-flagged) state — see Phase C.

This is the most consequential UX trade-off in the plan (many clicks for a large cluster) and it's made deliberately, matching the project's own precedent of choosing correctness/governance over convenience (e.g. the append-only verdict table, the "no cascade reconciliation" rule in `materializer.py`'s own docstring).

**3. Verdict identity for a blueprint: reuse the SAME `architecture_component_verdicts` mechanism, with a distinguishing `verdict_target` column — not a parallel table.**

Rejected alternative: a wholly separate `architecture_blueprint_verdicts` table, parallel in shape to the component one. Considered because a blueprint verdict's "scope" isn't a `scope_locator` at all — it's `(perspective, cluster.name)`, since `candidate_blueprint` findings all share `scope_locator=""` and are disambiguated by `label`. Chose the single-table-with-a-kind-column route instead because: (a) `get_component_verdicts`/`list_component_verdict_history`/the append-only-history convention/`_ENTITY_SLUG_TABLES` rename wiring all already exist and are correct for this shape too — duplicating them into a second table is exactly the "same shape, second home" failure `CLAUDE.md`'s reasoning about docs (and this codebase's `_row_to_*`/dataclass convention) warns against; (b) a curator-facing "what have I decided about this repo" query benefits from one table, not two, especially once blueprint acceptance needs to *read* component verdicts (Decision 2) and vice versa is plausible later. Concretely: extend the existing table with `verdict_target TEXT NOT NULL DEFAULT 'component'` (`'component' | 'blueprint'`) and repurpose `scope_locator` to hold, for a blueprint row, the string `f"{perspective}::{cluster_name}"` (stable, matches how `candidate_blueprint` findings are already keyed by `label` within a perspective — verified no two clusters share a name within one perspective, since `groups` in `clustering.propose` is keyed by scope-derived name). `COMPONENT_VERDICTS` becomes `BLUEPRINT_VERDICTS = {"accepted", "rejected"}` — no `"retyped"` for a blueprint (there is no free-text "type" field on a cluster the way there is on a component), which the route validates by `verdict_target`.

**4. Materialized-blueprint tracking: a new table, `architecture_materialized_blueprints`, parallel in shape to `architecture_materialized_components` but keyed by `(entity_type, entity_slug, perspective, cluster_name)` instead of `scope_locator`** — mirroring Decision 3's key choice for the same reason (no scope_locator exists for a blueprint). Columns: `id, entity_type, entity_slug, perspective, cluster_name, qualified_name, guid, materialized_at`. `INSERT OR REPLACE` on the natural key, same as the component table's docstring reasoning ("nothing append-only about *does this exist in Egeria*").

**5. Idempotency & partial-failure recovery — through the outbox, blueprint-first-then-dependents, with wires flagged as a real open risk rather than a false all-clear.**

- **Blueprint element itself**: `BlueprintMaterializer` mirrors `ComponentMaterializer`'s pattern exactly — local-cache check (`get_materialized_blueprint`) → qualifiedName search (`_find_element_guid`, byte-identical copy, same reasoning `ComponentMaterializer._find_element_guid`'s own docstring gives for not sharing one) → create. **Divergence from `ComponentMaterializer` #1**: `architecture-recovery.md` §10 Phase 2 says explicitly "**All at `ContentStatus = Draft`**" — so the blueprint create body uses **`class: "NewSolutionElementRequestBody"`**, not `NewElementRequestBody` (which pyegeria's own docstring says defaults to ACTIVE). `ComponentMaterializer` uses `NewElementRequestBody` today, i.e. it is NOT Draft — that's a pre-existing gap against the design doc this plan does not silently inherit; flagged as its own follow-up (see "Out of scope / follow-ups"), and `BlueprintMaterializer` gets this right from the start rather than copying the drift.
- **Membership + wires must go through the outbox** (per §8.4: "a half-published blueprint is worse than none") rather than being written synchronously like `ComponentMaterializer` does for its single element, because a blueprint write is N+1+M elements (1 blueprint, N `CollectionMembership`, M `SolutionLinkingWire`) and a crash mid-write must leave a resumable, visible state, not a half-formed live blueprint with no record of what's missing.
- **Enqueue order, mirroring `_link_evidence_outbox`'s two-phase shape**: `BlueprintMaterializer.materialize()` runs synchronously (find-or-create the blueprint element itself — same as `ComponentMaterializer`, since callers need the GUID back immediately to report success), *then* the route enqueues membership rows via a new `enqueue_blueprint_members(registry, entity_type, entity_slug, blueprint_guid, member_guids, *, run_id="")` (parallel to `enqueue_collection_members`, reusing `_create_collection_membership`'s **existing** `element_kind="collection_membership"` creator unchanged — `CollectionMembership` doesn't care whether the collection is an investigation's Collection or a `SolutionBlueprint`, it's still Collection→Referenceable). No `depends_on_id` needed for these, since the blueprint GUID is already known synchronously before enqueueing (unlike the annotation-link case, where both ends might still be in-flight).
- **Wires — the real open risk, stated plainly rather than hidden behind a false "same as membership" claim**: a new `element_kind="solution_linking_wire"` creator cannot safely reuse the create-blind pattern, because a crash between "Egeria created the wire" and "the outbox row is marked done" means a retry creates a **second, distinct** wire relationship — silently, since multi-link means no 409. Two options considered:
  - (a) Ship it anyway with create-blind semantics and accept the risk, same posture the codebase already takes toward `claim_due_outbox_elements`'s documented "two drainers is a real hazard for annotation links" — acceptable only if it's written down with the same honesty that docstring uses, not asserted safe.
  - (b) Do a pre-check before create — but there is no `get_solution_linking_wires`/`get_all_related_elements`-style read exposed for this relationship in the pyegeria surface checked (`solution_architect.py`), so a real pre-check would need a new pyegeria method, which is out of scope for an RE-only plan.
  **Chosen: (a), with the risk written into the outbox row's own payload and into this plan's Verification section as a required live measurement before the wire creator ships** — exactly the same discipline the outbox module already applied to `CollectionMembership`/`AnnotationExtension` (measure live, then document), which for wires has NOT yet been done. Phase A explicitly does not include wire enqueueing until that measurement exists (see Phased build order, Phase A.5).
- **Cross-boundary wires** (one endpoint inside the cluster, one outside): written as-is, not dropped and not specially transformed. Rationale: a wire is a fact about the code (`w.get("source")`/`w.get("target")`), not a fact about which blueprint someone drew around it — dropping it would make the blueprint's own diagram lie about what the component actually talks to, and Egeria's model has no "boundary-crossing wire" concept to special-case into. The *outside* endpoint's `SolutionComponent` must itself already be materialized (found via the same slug→scope_locator→materialized lookup as an in-boundary member) or the wire is skipped and reported (not enqueued to a GUID that doesn't exist — same rule `enqueue_annotation_links`'s docstring states for its own case: "enqueuing a link to a GUID that does not exist would just fail loudly later for a reason this module cannot diagnose").

---

## Registry additions (`resource_explorer/registry.py`)

New tables, in the same `CREATE TABLE IF NOT EXISTS` block as the existing two (near line 1295-1324):

```sql
-- extends the existing table (migration: ALTER TABLE ... ADD COLUMN, same
-- pattern as the last_run_status/target_kind migrations on resource_schedules)
ALTER TABLE architecture_component_verdicts
    ADD COLUMN verdict_target TEXT NOT NULL DEFAULT 'component';
-- 'component' | 'blueprint'. For a blueprint row, scope_locator holds
-- f"{perspective}::{cluster_name}" (see Decision 3).

CREATE TABLE IF NOT EXISTS architecture_materialized_blueprints (
    id              TEXT PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    entity_slug     TEXT NOT NULL,
    perspective     TEXT NOT NULL,
    cluster_name    TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    guid            TEXT NOT NULL,
    materialized_at TEXT NOT NULL
);
CREATE INDEX idx_architecture_materialized_blueprints_scope
    ON architecture_materialized_blueprints(entity_type, entity_slug, perspective, cluster_name);
```

New/changed methods (mirroring the existing pairs exactly):
- `BLUEPRINT_VERDICTS = {"accepted", "rejected"}` class constant.
- `record_component_verdict(..., verdict_target: str = "component")` — extend signature, extend the `INSERT` column list; existing single-component callers unaffected (default preserved).
- `get_component_verdicts` gains no signature change but its docstring note updates: callers filtering to one `verdict_target` filter client-side (small map, not worth a second query parameter for what's currently one filter).
- `get_materialized_blueprint(entity_type, entity_slug, perspective, cluster_name) -> dict | None`, `get_materialized_blueprints(entity_type, entity_slug) -> dict[str, dict]` (keyed by `f"{perspective}::{cluster_name}"`), `record_materialized_blueprint(...)` — byte-for-byte the same shape as the component trio.
- Add `"architecture_materialized_blueprints"` to `_ENTITY_SLUG_TABLES` so `rename_project_slug` covers it — **easy to miss, and missing it silently breaks a repo rename for any repo with a materialized blueprint.**

---

## `BlueprintMaterializer` (new file: `resource_explorer/surveyors/arch_recovery/blueprint_materializer.py`)

Mirrors `materializer.py`'s module docstring convention (states scope, states what it deliberately does NOT do) and its `_connect`/`_find_element_guid` pattern verbatim (own connection, not `EgeriaPublisher`, not shared with `ComponentMaterializer`).

```python
class BlueprintMaterializer:
    def __init__(self, platform_url=None, view_server=None, user_id=None,
                 user_password=None, timeout=None, registry: "ProjectRegistry | None" = None): ...

    @staticmethod
    def qualified_name_for(entity_type: str, entity_slug: str, perspective: str, cluster_name: str) -> str:
        # "SolutionBlueprint::{entity_type}::{entity_slug}::{perspective}::{cluster_name}"

    def materialize_blueprint_element(
        self, entity_type: str, entity_slug: str, perspective: str, cluster_name: str, *,
        display_name: str, oversized: bool = False,
    ) -> dict:
        """Find-or-create ONLY the SolutionBlueprint element itself (Draft,
        via NewSolutionElementRequestBody — see Decision 5's divergence note).
        Synchronous, same shape as ComponentMaterializer.materialize().
        Returns {"status": ..., "guid": ..., "qualified_name": ...}."""

    def resolve_member_guids(
        self, registry, entity_type: str, entity_slug: str, member_slugs: list[str],
        slug_to_scope: dict[str, str],
    ) -> tuple[dict[str, str], list[str]]:
        """slug -> materialized SolutionComponent GUID, for members that ARE
        materialized; the second list is member slugs that are NOT (missing
        verdict or missing materialization) — Decision 2's enforcement point.
        Never raises; an unmaterialized member is data, not an error."""

    def resolve_child_blueprint_guids(
        self, registry, entity_type: str, entity_slug: str, perspective: str,
        child_names: list[str],
    ) -> tuple[dict[str, str], list[str]]:
        """Same shape as resolve_member_guids, for Decision 1's per-level
        acceptance: child_names -> materialized blueprint GUID, or unmet."""
```

**Enqueueing** (membership + wires) is NOT a method on this class — it's the route's job, via the two new `egeria_outbox.py` helpers below, exactly the separation `ComponentMaterializer` (sync, single write) vs. `egeria_publisher.py` (enqueue-then-drain) already models. Keeping `BlueprintMaterializer` itself outbox-agnostic (it returns GUIDs; it doesn't enqueue) keeps it unit-testable with a fake registry and no outbox machinery, matching how `ComponentMaterializer` is tested today.

---

## `egeria_outbox.py` additions

```python
def _create_solution_linking_wire(clients: "OutboxClients", payload: dict) -> str:
    """NOT proven idempotent on replay — see Decision 5. Ships anyway (2026-09,
    same posture as claim_due_outbox_elements' documented concurrent-drain
    hazard for annotation links) pending a live measurement of
    SolutionLinkingWire's create-twice behavior. If that measurement finds it
    is NOT safely re-createable even by qualifiedName-adjacent means, this
    creator must be revisited before wire enqueueing is turned on by default."""
    sa = clients.require("solution_architect")
    guid = sa.link_solution_linking_wire(payload["source_guid"], payload["target_guid"], {
        "class": "NewRelationshipRequestBody",
        "properties": {
            "class": "SolutionLinkingWireProperties",
            "label": payload.get("label", ""),
            "description": payload.get("description", ""),
        },
    })
    return guid or ""

_CREATORS["solution_linking_wire"] = _create_solution_linking_wire
```

`OutboxClients` gains a `solution_architect: object | None = None` field — a fourth client, same reasoning `collection_manager`/`metadata_expert` were added for ("element kinds reach different managers"). `_default_clients()` needs a connected `SolutionArchitect` too; simplest is instantiating one alongside the existing `EgeriaPublisher()` connect (same platform/view-server/user, a second lightweight client object, matching how `ComponentMaterializer` already keeps its own rather than trying to extend `EgeriaPublisher`'s surface).

```python
def enqueue_blueprint_members(
    registry, entity_type: str, entity_slug: str, blueprint_guid: str,
    member_guids: list[str], *, run_id: str = "",
) -> list[int]:
    """One row per member component attached to the blueprint Collection.
    Reuses element_kind='collection_membership' unchanged — CollectionMembership
    doesn't distinguish a SolutionBlueprint collection from an investigation's."""
    row_ids = []
    for member_guid in member_guids:
        qualified_name = f"CollectionMembership::{blueprint_guid}::{member_guid}"
        row_ids.append(registry.enqueue_outbox_element(
            entity_type, entity_slug, "collection_membership", qualified_name,
            {"collection_guid": blueprint_guid, "member_guid": member_guid},
            run_id=run_id,
        ))
    return row_ids

def enqueue_blueprint_wires(
    registry, entity_type: str, entity_slug: str, wires: list[dict], *, run_id: str = "",
) -> list[int]:
    """wires: [{source_guid, target_guid, label}]. Synthetic qualifiedName —
    SolutionLinkingWire has none — kept for the outbox's own bookkeeping only;
    see _create_solution_linking_wire's docstring for why this key does NOT
    make a retry safe the way it does for the other kinds."""
    row_ids = []
    for w in wires:
        qualified_name = f"SolutionLinkingWire::{w['source_guid']}::{w['target_guid']}::{w.get('label','')}"
        row_ids.append(registry.enqueue_outbox_element(
            entity_type, entity_slug, "solution_linking_wire", qualified_name, w, run_id=run_id,
        ))
    return row_ids
```

No `depends_on_id` on either — the blueprint GUID (for membership) and both component GUIDs (for wires) are already resolved synchronously before enqueueing (Decision 5), so there is nothing left to wait on inside the outbox itself. This differs from `enqueue_annotations`→`enqueue_annotation_links`'s dependency chain precisely because that chain's dependency (the annotation write) is itself queued; here the prerequisite writes (component materialization, blueprint materialization) already happened synchronously in an earlier accept, not in this same enqueue batch.

---

## Route (`resource_explorer/web/routes/curate.py`)

New Pydantic model + endpoints, placed after the existing component-verdict section:

```python
class BlueprintVerdictCreate(BaseModel):
    perspective: str
    cluster_name: str
    verdict: str  # "accepted" | "rejected"
    note: str = ""

@router.get("/blueprint-verdicts/{entity_type}/{slug}")
def list_blueprint_verdicts(entity_type: str, slug: str) -> dict[str, dict]:
    """{f"{perspective}::{cluster_name}": latest verdict}."""
    all_verdicts = _registry().get_component_verdicts(entity_type, slug)
    return {k: v for k, v in all_verdicts.items() if v.get("verdict_target") == "blueprint"}

@router.post("/blueprint-verdicts/{entity_type}/{slug}")
def add_blueprint_verdict(entity_type: str, slug: str, body: BlueprintVerdictCreate) -> dict:
    # validate against ProjectRegistry.BLUEPRINT_VERDICTS
    # scope_locator = f"{body.perspective}::{body.cluster_name}"
    # record_component_verdict(..., verdict_target="blueprint")
    # if accepted and entity_type == "repo": _materialize_blueprint_if_accepted(...)
    ...
```

`_materialize_blueprint_if_accepted` (new function, same non-fatal-but-visible shape as `_materialize_if_accepted`):
1. Look up the `candidate_blueprint` finding by `(perspective, cluster_name)` — `registry.query_findings(slug, "architecture_blueprints", "")`, filter `check_name=="candidate_blueprint" and detail["perspective"]==perspective and detail["name"]==cluster_name`.
2. Build `slug_to_scope` the same way `_architecture_recovery_results` does (query `architecture_recovery` component findings, `detail["slug"] → scope`).
3. `BlueprintMaterializer(registry=registry).materialize_blueprint_element(...)` — synchronous, gets the blueprint GUID.
4. `resolve_member_guids(...)` — if any member is unmet, return `{"status": "partial", "guid": ..., "unmaterialized_members": [...]}` **and still enqueue membership/wires for the members that ARE ready** (partial progress is real progress, matching the outbox's own "leave what already landed in place" ethic) rather than all-or-nothing.
5. If `cluster.children`: `resolve_child_blueprint_guids(...)`, same partial-progress handling.
6. `enqueue_blueprint_members(...)` for resolved member/child GUIDs.
7. Resolve in-boundary wires from `architecture_interfaces` findings scoped to each member's `scope_locator` (check_name starting `"wire:"`), keep only those whose target also resolves to a materialized component (in-cluster or out-of-cluster per Decision 5's cross-boundary rule); `enqueue_blueprint_wires(...)`.
8. Return a result dict the route merges into the verdict response exactly as `add_component_verdict` does with `verdict["materialization"]`.

---

## Frontend (`resource_explorer/web/static/index.html`)

1. **Backend prerequisite**: `_architecture_recovery_results` (`repo_survey_definition_adapter.py:2374`) must start reading `kind="architecture_blueprints"` findings and add a `data.blueprints` key (`{perspective: [cluster dicts with verdict/materialization merged, nested via detail.children]}`) to its return — today it reads only `kind="architecture_recovery"`, so `candidate_blueprint` rows are invisible to this reader regardless of what the frontend does. This is new backend work this plan must call out explicitly (not implied by "frontend section") — add it as its own step in Phase C, not folded silently into the renderer change.
2. **New renderer**, `_renderCandidateBlueprints(blueprints)`, called from `_renderArchitectureRecoveryResults` (append after `_structuralBlock`, same place `_renderDeploymentInterfaces` is appended) — one collapsible block per perspective, each cluster shown with member count, member list (names, not slugs — resolve via the existing component list already in `data.components`), and for a cluster with children, a nested indented list (mirrors how `_archStructuralHtml` already nests structural nodes).
3. **Verdict controls**, modeled directly on `_archVerdictControlsHtml`/`_archSubmitVerdict` — same accept/reject/change pattern, POSTing to `/api/curate/blueprint-verdicts/{entity_type}/{slug}` instead, with `perspective`/`cluster_name` instead of `scope_locator`. On an `accepted` response with `unmaterialized_members` non-empty, render a distinct warning state (not the same green "materialized" toast) naming which member components still need their own accept — directly surfacing Decision 2's governance boundary rather than leaving the curator to infer it from silence.
4. **Oversized clusters** (`detail.oversized`) get the same "⚠" treatment `_renderArchitectureRecoveryResults`'s `completeness` block already uses for partial runs — visually distinct, not just a plain row, since an oversized cluster is explicitly "no further declared structure" per `persist.py`'s own summary text.

---

## Phased build order

**Phase A — registry + `BlueprintMaterializer`, no route/frontend, unit-testable in isolation.**
- Registry migration (`architecture_component_verdicts.verdict_target`, `architecture_materialized_blueprints` table + accessor methods + `_ENTITY_SLUG_TABLES` entry).
- `blueprint_materializer.py`: `qualified_name_for`, `materialize_blueprint_element` (with a fake/mocked `SolutionArchitect`, same test shape the existing `ComponentMaterializer` tests use — check for that test file before writing new ones, to match its mocking style), `resolve_member_guids`, `resolve_child_blueprint_guids`.
- Tests: idempotency (repeat `materialize_blueprint_element` call finds cached/existing), Draft-status body shape (`NewSolutionElementRequestBody`, not `NewElementRequestBody`), member resolution correctly reports unmet members without raising.

**Phase A.5 — the wire-safety measurement, gating whether wire enqueueing ships at all.**
- A one-off live-server script (in `scripts/arch-spike/`, the existing home for this kind of measurement) calling `link_solution_linking_wire` twice with identical arguments against a throwaway pair of components, reading back via whatever pyegeria exposes to confirm duplication. **If it duplicates** (expected, given the docstring): document the risk in `_create_solution_linking_wire`'s docstring as written above, and decide with the project owner whether wire enqueueing ships with that known gap in Phase B or is deferred to its own follow-up entry — this is a project-owner call, not a design call this plan makes silently.

**Phase B — route.**
- `egeria_outbox.py`: `OutboxClients.solution_architect`, `_create_solution_linking_wire`, `enqueue_blueprint_members`, `enqueue_blueprint_wires`, `_default_clients()` update.
- `curate.py`: `BlueprintVerdictCreate`, `list_blueprint_verdicts`, `add_blueprint_verdict`, `_materialize_blueprint_if_accepted`.
- Tests: route-level, with `BlueprintMaterializer`/outbox mocked — verdict recorded regardless of Egeria reachability (same non-fatal-but-visible contract as the component route); partial-member-materialization case returns the right shape; child-blueprint nesting resolves correctly for a two-level cluster fixture (reuse `tests/test_arch_clustering.py`'s own fixtures rather than inventing new ones).

**Phase C — frontend, plus the backend reader gap it depends on.**
- `_architecture_recovery_results` gains `data.blueprints` (new backend step, per above).
- `index.html`: `_renderCandidateBlueprints`, blueprint verdict controls, oversized-cluster styling, unmaterialized-member warning state.
- Manual verification against a real survey run with clusters (e.g. `egeria_workspaces_git`, which already has candidate blueprints computed) — confirm the rendered tree matches `detail.children`/`detail.parent` linkage correctly, and that accepting a leaf cluster before its members are individually accepted correctly blocks/warns rather than silently doing nothing.

---

## Verification

- `uv run pytest tests/ -k "blueprint or arch_clustering or arch_materializer" -v` after each phase.
- Phase A.5's live measurement is a **hard gate**, not a nice-to-have — shipping wire enqueueing without it repeats the exact mistake the outbox module's own docstrings warn against (asserting idempotency from "how the code is written" rather than a live check), on a relationship type that's already been proven NOT to have the property the reused code path assumes.
- Before Phase B ships against the shared Egeria instance, invoke the `coordinate-shared-writes` convention (shared Postgres registry + shared live Egeria) — ask any live peer sessions before a real accept-and-materialize run, same as any other write to the shared corpus.
- After Phase C, re-run the same presentation-audit style as §17a ("what does a curator actually see") against at least one real clustered repo, since that section's own history (20 rows shown out of 1035, chosen alphabetically) is exactly the failure mode a new UI surface can reintroduce if cluster ordering/truncation isn't considered.

## Out of scope / follow-ups this plan surfaces but does not fix

- `ComponentMaterializer` is not actually Draft-status today (`NewElementRequestBody`, defaults ACTIVE) despite §10 Phase 2 saying components should be Draft too — a pre-existing gap, not introduced here, worth its own small follow-up.
- `Confidence` classification (`confidenceLevel=Derived`, `confidence` 0-100, `source`=analyzer id) on components/ports per §10 Phase 2 — neither `ComponentMaterializer` nor this plan's `BlueprintMaterializer` applies it; both currently only stuff analogous data into `additionalProperties`. Real typed `Confidence` classification is separate follow-up work touching both materializers.
- `ImplementedBy` linking (Logical perspective → code) — explicitly listed in §10 Phase 2 alongside blueprints/wires but not covered by this plan; a separate slice.
- A live pyegeria read method for existing `SolutionLinkingWire`s (to make wire retries genuinely safe rather than merely documented-risky) — would need to originate in `egeria-python`, not this repo.

### Critical files for implementation
- `packages/resource-explorer/resource_explorer/surveyors/arch_recovery/materializer.py`
- `packages/resource-explorer/resource_explorer/surveyors/arch_recovery/clustering.py`
- `packages/resource-explorer/resource_explorer/surveyors/arch_recovery/persist.py`
- `packages/resource-explorer/resource_explorer/egeria_outbox.py`
- `packages/resource-explorer/resource_explorer/registry.py`
- `packages/resource-explorer/resource_explorer/web/routes/curate.py`
- `packages/resource-explorer/resource_explorer/surveyors/repo_survey_definition_adapter.py`
- `packages/resource-explorer/resource_explorer/web/static/index.html`
