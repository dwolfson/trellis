# RFA response actions — backing them with a real Egeria ToDo

The RFA drawer's defer/reassign/complete/reopen actions are currently local-only
(`rfa_actions` SQLite table — see its docstring in `registry.py`). That table's
docstring already named this as "a stepping stone toward real Egeria ToDo/
governance actions, not that integration itself." This doc names what that
integration actually looks like, confirmed against pyegeria's real API surface
(not assumed) — not built yet.

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
| `GET /api/activity/rfas` overlay | Reads the local mirror (fast, same shape as today's UI) kept in sync with the `ToDo`'s real state — exact sync mechanism (poll vs. write-through vs. event) still open |

## Open questions before building

1. **Who is the ToDo assigned to initially?** RE has no per-user identity yet
   (`whoami` is a single shared service account — see `egeria.py`). Real
   per-user assignment needs that solved — **confirmed still needed, standing
   requirement, not deferred indefinitely** (2026-08-15) — until then the
   initial assignee is "unassigned"/the service account.
2. **Migration**: does an existing local `rfa_actions` row get backfilled into
   a real `ToDo` on first load, or does this only apply going forward? Backfill
   means creating N `ToDo`s retroactively; going-forward-only is simpler but
   leaves historical RFA responses in two different places.
3. **Visibility trade-off**: this makes RFA response state visible to *any*
   Egeria client, not just RE — likely desirable (the whole point), but worth
   confirming that's actually wanted before every "defer this" click becomes a
   durable, catalog-wide-visible action instead of a quiet local note.
4. **Sync mechanics**: given the model is now settled (mirror `ToDoProperties`,
   keep both in sync), the actual sync mechanism is still undecided —
   write-through on every local action (RE writes local + calls Egeria
   synchronously), a background reconciliation pass, or something
   event-driven. Each has different failure-mode implications (what happens
   if the Egeria write fails after the local write succeeds, or vice versa)
   that need their own pass before implementation.

None of this is scoped for implementation yet — this is the "what would it
take" writeup, so the next design conversation starts from confirmed facts
instead of assumptions.
