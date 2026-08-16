# RFA response actions — backing them with a real Egeria ToDo

**Status (2026-08-16): implemented, unit-tested (44 tests), AND live-verified
against a real Egeria platform.** Live verification found and fixed one real
bug — see "Live verification results" near the end of this doc.

The RFA drawer's defer/reassign/complete/reopen actions used to be local-only
(`rfa_actions` SQLite table — see its docstring in `registry.py`). That table's
docstring already named this as "a stepping stone toward real Egeria ToDo/
governance actions, not that integration itself." This doc names what that
integration actually looks like, confirmed against pyegeria's real API surface
(not assumed).

**Decided (2026-08-15):** the real problem with `rfa_actions` today isn't that
it's *local* — it's that it's a second, independently-invented vocabulary
(`rfa_status`/`defer_until`/`assignee`) requiring translation to and from
`ToDo`'s real properties. **One model, not one location**: `rfa_actions`
should mirror `ToDoProperties` directly (`activityStatus`, `dueTime`,
`startTime`, `priority`, …) and stay synced with a real Egeria `ToDo`, rather
than keeping its own bespoke schema translated back and forth. Whether the
local copy is a genuine two-way sync, a write-through cache, or something
else is still open (see below) — the model itself is the decided part.

## What Egeria actually offers

Confirmed by reading pyegeria's source directly (`pyegeria/omvs/my_profile.py`,
`pyegeria/omvs/asset_maker.py`, `pyegeria/omvs/metadata_expert.py`) and the
ground-truth REST surface (`pyegeria/http clients/Egeria-api-asset-maker.http`):

- **`ToDo`** is a real `PersonAction` type — a general-purpose human work item,
  separate from `RequestForAction` (which is an `Annotation` subtype, already
  how RE's own surveyors create RFAs — see `docs/survey-activity-design.md`).
  Fields include `activityStatus` (`REQUESTED`/`WAITING`/`IN_PROGRESS`/
  `COMPLETE`/etc.), `priority`, `dueTime`, `startTime`, `requestedTime`,
  `completionTime`.
- **Creation**: `create_action(body)` with `properties.class = "ToDoProperties"`
  (or the `create_my_todo()` convenience wrapper).
- **Assignment**: `assign_action(action_guid, actor_guid)` /
  `reassign_action(action_guid, actor_guid)` — the server enforces that
  reassigning unassigns all previous assignees.
- **Linking to the resource/RFA it's about**: `add_action_target(action_guid, target_guid, ...)`
  — this is how a `ToDo` would be linked to the specific `RequestForAction`
  annotation it's meant to resolve.
- **Querying**: `get_my_assigned_actions` / `get_my_requested_actions` /
  `get_my_to_dos`, filterable by `activity_status_list`.
- **Completing a ToDo (or changing any other property, including
  reassignment via property rather than the dedicated call above)**:
  **no gap, no missing method — verified live, corrected 2026-08-15.** An
  earlier pass through this doc claimed pyegeria was missing a "complete a
  ToDo" convenience method; that was checking for the wrong thing. The real
  REST surface under `/asset-maker/actions` (confirmed directly against the
  `.http` ground truth) has no bespoke per-action-type update endpoint at
  all — but it doesn't need one. `MetadataExpert.update_metadata_element_
  properties(todo_guid, body)` is a genuinely generic method, backed by the
  generic metadata-element `update-properties` REST endpoint, and works for
  *any* element type — a `ToDo` is just another `Referenceable`. Completing
  one is exactly:
  ```python
  me.update_metadata_element_properties(todo_guid, {
      "class": "UpdatePropertiesRequestBody",
      "properties": {"class": "ToDoProperties", "activityStatus": "COMPLETE"},
  })
  ```
  Nothing to file in `egeria-python`'s `PYEGERIA_ISSUES.md` for this — fully
  covered today.

## What this would change

| RE concept today | Would become |
|---|---|
| `rfa_actions` table with its own vocabulary (`rfa_status`, `assignee`, `defer_until`, `resolution_note`) | `rfa_actions` mirrors `ToDoProperties` directly (`activity_status`, `due_time`, `start_time`, `priority`), synced with a real `ToDo` per open RFA, linked via `add_action_target` to the RFA's `Annotation` GUID |
| Defer (local `defer_until` field) | `ToDo.dueTime`/`startTime`, set via `update_metadata_element_properties` (generic — confirmed above, no gap) |
| Reassign (local `assignee` field) | `reassign_action(todo_guid, new_actor_guid)` (dedicated method — enforces single-assignee) |
| Complete (local `rfa_status = "completed"`) | `activityStatus = "COMPLETE"` via `update_metadata_element_properties` (generic — confirmed above, no gap) |
| `GET /api/activity/rfas` overlay | Reads the local mirror (fast, same shape as today's UI) — kept in sync via write-through + periodic two-direction reconciliation, see "Sync mechanics" below |

## Open questions before building

1. **Who is the ToDo assigned to initially?** RE has no per-user identity yet
   (`whoami` is a single shared service account — see `egeria.py`). Real
   per-user assignment needs that solved — **confirmed still needed, standing
   requirement, not deferred indefinitely** (2026-08-15) — until then the
   initial assignee is "unassigned"/the service account. **UI implication,
   noted 2026-08-16**: today's Reassign form is a free-text "name or email"
   input (`assignee`, local-only string, never resolved to a real actor) —
   once real per-user identity exists, this should become a searchable
   dropdown of actual known users/actors, not free text, so `reassign_action`
   (currently never called — see rfa_egeria_sync.py's module docstring) has
   a real actor GUID to pass. Blocked on the same identity gap, not a
   separate piece of work.
2. **Migration**: does an existing local `rfa_actions` row get backfilled into
   a real `ToDo` on first load, or does this only apply going forward? Backfill
   means creating N `ToDo`s retroactively; going-forward-only is simpler but
   leaves historical RFA responses in two different places.
3. **Visibility trade-off**: this makes RFA response state visible to *any*
   Egeria client, not just RE — likely desirable (the whole point), but worth
   confirming that's actually wanted before every "defer this" click becomes a
   durable, catalog-wide-visible action instead of a quiet local note.
4. ~~**Sync mechanics**~~ — **decided 2026-08-15**, see "Sync mechanics" below.

## Sync mechanics (decided 2026-08-15)

Grounded in the one directly-analogous precedent already in this codebase —
`egeria_publisher.py`'s activity-log write faces the identical shape of
problem (a secondary Egeria-side write that must not fail the primary
operation): `except Exception as exc: log.warning("Could not write activity
log entry: %s", exc)`. No outbox/queue table exists anywhere in this repo
today; build on the established pattern, not a new one.

1. **Local write is authoritative for the response.** A drawer action
   (defer/reassign/complete) writes the local `rfa_actions` row first (now
   `ToDoProperties`-shaped) — that write alone defines what the API response
   returns. The user's action never blocks on Egeria's reachability.
2. **Egeria `ToDo` call attempted synchronously, same request, non-blocking
   of the outer result** — same shape as the activity-log precedent: try the
   matching pyegeria call (`reassign_action`, `update_metadata_element_
   properties`, …), catch and log on failure, never fail the user's action
   because Egeria was unreachable. Success: store `egeria_todo_guid` +
   `synced_at`. Failure: set a `sync_error` field, log a warning.
3. **Reconciliation, both directions, one pass, reusing `scheduler.py`'s
   existing background loop** (the same one already running
   `_check_subscriptions()` — not a new subsystem):
   - **Write direction** (closes the gap #2 above leaves): rows with no
     `egeria_todo_guid` or a set `sync_error` get their write retried.
   - **Read direction** (per direct confirmation, closes what was
     previously named explicitly out of scope): periodically pull `ToDo`s
     via `get_my_assigned_actions`/`get_my_to_dos` and reconcile against the
     local mirror, so a change made by *another* Egeria client (not through
     RE's own drawer) still shows up locally. Symmetric to the write-side
     retry, same pass, same cadence.
   - The activity log can afford pure "log and forget" because it's an
     audit trail; RFA/ToDo state is live workflow truth both systems must
     agree on, so unlike the activity-log precedent, silent permanent drift
     here would be a real bug, not a cosmetic gap — this reconciliation
     pass is the one genuinely new piece beyond what the precedent alone
     would give.

## Related, broader idea — not scoped to RFA, noted here so it isn't lost

Per direct discussion: significant changes to an **Asset's** status
(disposition changes, survey outcomes, anything worth a durable note beyond
what a property update alone conveys) can be logged as a real Egeria
`ActivityEntry` attached to the asset — **confirmed fully supported today,
no pyegeria gap**, verified directly against `pyegeria/core/_server_client.py`
(the shared base every OMVS client inherits, not a dedicated
`feedback_manager.py` module — an earlier check in this same conversation
wrongly assumed one was missing and needed correcting):
```python
note_log_guid = client.create_note_log(element_guid=asset_guid, display_name="Status changes")
client.create_note(note_log_guid, body={
    "class": "NewElementRequestBody",
    "properties": {"class": "ActivityEntryProperties", "typeName": "ActivityEntry",
                   "description": "Disposition changed to abandoned — see linked ToDo for reason"},
})
```
Both `create_note_log`/`create_note` are generic (any `element_guid`, not
"my profile"-scoped). One pre-existing, already-filed, unrelated wrinkle:
`update_note` 404s server-side (`egeria-python` `PYEGERIA_ISSUES.md`
ISSUE-30, Egeria-Server layer, not pyegeria's to fix) — irrelevant here
since status-change logging is naturally append-only (a new `ActivityEntry`
per change, never an edit of a past one). This is a separate mechanism from
the RFA/`ToDo` sync above, not a replacement for any part of it — captured
here so it isn't lost before its own scoped design pass.

The RFA/`ToDo` sync above is now implemented; this related idea (Asset-level
`ActivityEntry` logging) is still just the "what would it take" writeup —
not scoped for implementation, no code written.

## Implementation notes (2026-08-16)

What shipped, matching this doc's decisions exactly:

- **Registry**: `rfa_actions` gained `activity_status`/`due_time`/
  `start_time`/`priority` (mirroring `ToDoProperties` directly, Egeria's
  real `ACTIVITY_STATUS` vocabulary — confirmed via
  `pyegeria/core/_globals.py`) plus `egeria_todo_guid`/`synced_at`/
  `sync_error` (sync bookkeeping). `rfa_status`/`defer_until` (RE's
  friendly verbs — open/deferred/reassigned/completed) are kept, not
  dropped — they're still the API/frontend's wire contract, unchanged, so
  the drawer UI (`index.html`) needed zero changes. One translation seam,
  in `web/routes/activity.py`'s `_STATUS_TO_ACTIVITY_STATUS`, maps friendly
  verb → real `activityStatus` exactly once; the sync module reads
  `activity_status`/`due_time` straight through, no second translation —
  this is the "one model, not one location" decision's practical shape:
  one internal representation, one seam at the API boundary, not a
  bespoke vocabulary re-derived at multiple points.
- **New `resource_explorer/rfa_egeria_sync.py`**: `sync_rfa_action()` (the
  per-row create-or-update call, same non-blocking try/except/log shape as
  `egeria_publisher.py`'s activity-log write) and `reconcile_rfa_actions()`
  (both-direction reconciliation pass).
- **`web/routes/activity.py`**: `PATCH /rfas/{rfa_id}` now attempts
  `sync_rfa_action()` synchronously, same request, after the local write —
  never fails the response.
- **`scheduler.py`**: `_scheduler_loop()` now calls
  `_reconcile_rfa_actions()` every iteration (own try/except, independent
  of `_run_due()` — a failure in one never blocks the other), reusing the
  existing background thread rather than starting a second one.

**Scoping decisions made during implementation, not previously nailed down
in this doc:**
- **`add_action_target` linking is NOT implemented.** Today's local RFAs
  are flattened from `activity_log` rows at read time and don't reliably
  carry a real Egeria annotation GUID to link a `ToDo` against — the
  created `ToDo` stands alone (real, visible to any Egeria client, correct
  lifecycle) but isn't relationship-linked to the specific
  `RequestForAction` it's about. Revisit once/if local RFAs carry a real
  annotation GUID.
- **`reassign_action` is NOT called.** Open question #1 (per-user identity)
  is still unresolved — `assignee` stays a local free-text field; the sync
  module never calls Egeria's actor-assignment API since there's no real
  actor GUID to pass it.
- **Read-direction reconciliation is scoped to already-linked rows.** It
  pulls the caller's open `ToDo`s (`get_my_to_dos`) and reconciles any
  local row whose `egeria_todo_guid` matches one already returned — it
  does NOT discover and create new local rows for `ToDo`s that originated
  entirely outside RE (there's no way to map an arbitrary Egeria `ToDo`
  back to a specific local RFA/annotation without the linking above).

## Live verification results (2026-08-16)

Every pyegeria call in `rfa_egeria_sync.py` was exercised against a real,
running Egeria platform (not just mocked clients) — creating/updating a
real `ToDo`, reading it back two different ways, and creating a real
`NoteLog`/`ActivityEntry` `Note` anchored to it. Confirmed, by GUID
round-trip against the live server:

1. `MyProfile.create_my_todo()` — **confirmed working as called.** Created
   a real `ToDo` with `activityStatus`/`description`/`priority` set exactly
   as passed.
2. `MetadataExpert.update_metadata_element_properties()` — **found broken,
   then fixed.** The original body shape
   (`{"class": "ToDoProperties", "activityStatus": "WAITING", ...}`) was
   silently accepted by the server (HTTP success, no error) and changed
   *nothing* — a live GET immediately after showed the `ToDo` unchanged.
   Root cause: this is the fully generic metadata-element endpoint, not a
   `ToDo`-aware convenience method like `create_my_todo()` — its real wire
   contract (confirmed via `_async_update_metadata_element_properties()`'s
   own docstring) is `properties: {"class": "ElementProperties",
   "propertyValueMap": {...}}`, with each value individually typed
   (`EnumTypePropertyValue` for `activityStatus`, `PrimitiveTypePropertyValue`
   for scalars, and — a second real finding — date properties as
   **epoch-millisecond integers**, not ISO date strings). Fixed in
   `rfa_egeria_sync.py`; re-verified live afterward: a real `defer` PATCH
   now correctly flips the `ToDo`'s `activityStatus` to `WAITING` and sets
   a real `dueTime`.
3. `get_my_to_dos()`'s actual JSON response shape — **confirmed matches
   `_extract_todo_fields()`'s defensive parsing exactly**, with one
   real, useful asymmetry worth knowing: this list/report endpoint returns
   already-flattened `properties` (`activityStatus` as a plain string,
   dates as ISO strings), unlike `get_metadata_element_by_guid()`'s raw
   `elementProperties.propertyValueMap` shape (typed values, dates as
   epoch millis) used in point #2 above — the same field is represented
   two different ways depending which endpoint returns it. A full
   `reconcile_rfa_actions()` pass (write-direction retry + read-direction
   pull) ran live end-to-end with no errors.
4. `create_note_log()` / `create_note()` with a `typeName: "ActivityEntry"`
   properties override — **confirmed working exactly as designed.** A real
   `NoteLog` was created anchored to the `ToDo`; a real `Note` of type
   `ActivityEntry` was created under it, anchored to the same `ToDo` via
   `associated_element` — verified by reading both back by GUID.

## Notes sync to Egeria (2026-08-16)

Per direct decision, the drawer's real, persisted `notes` field (see
"Implementation notes" above — the fix for "Record answer never
persisted") also syncs to Egeria, as an `ActivityEntry`-typed `Note`
attached to a `NoteLog` anchored on the RFA's own `ToDo` — reusing the
"Related, broader idea" section's already-confirmed `create_note_log`/
`create_note` mechanism, just anchored on the `ToDo` rather than an Asset.

**Only synced once the `ToDo` already exists** (`egeria_todo_guid` set) —
a note is never forced to create a `ToDo` just to have something to link
against; it stays purely local until a later Defer/Reassign/Complete
creates one, at which point the next `reconcile_rfa_actions()` pass picks
it up automatically (`list_unsynced_rfa_notes()` requires a `ToDo`).

**One `ActivityEntry` per distinct note text, never edited in place** —
matches the append-only framing the "Related, broader idea" section
already established for Asset-level status-change logging, and sidesteps
`update_note`'s known-broken server-side behavior (`egeria-python`
`PYEGERIA_ISSUES.md` ISSUE-30) entirely rather than working around it.
`notes_synced_value` is the dedup key on the local side — an unchanged
note is never re-pushed as a duplicate entry. `egeria_notelog_guid` caches
the `NoteLog` GUID (created once per RFA, reused across edits — a fresh
`NoteLog` isn't created for every note revision, only the `Note`
underneath it).

`rfa_egeria_sync.sync_rfa_note()` is the implementation, called from
`PATCH /rfas/{rfa_id}/notes` (non-blocking, same guarantee as the status
route) and retried from `reconcile_rfa_actions()`'s write-direction pass.
No read-direction reconciliation for notes — Egeria-side `ActivityEntry`
notes created by another client aren't pulled back into RE's local
`notes` field; that field stays "the current local note," not a mirror of
the full Egeria-side history.
