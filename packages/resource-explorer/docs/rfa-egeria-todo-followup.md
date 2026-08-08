# RFA response actions — backing them with a real Egeria ToDo

The RFA drawer's defer/reassign/complete/reopen actions are currently local-only
(`rfa_actions` SQLite table — see its docstring in `registry.py`). That table's
docstring already named this as "a stepping stone toward real Egeria ToDo/
governance actions, not that integration itself." This doc is the scoped
follow-up that names what that integration would actually look like, confirmed
against pyegeria's real API surface (not assumed) — not built yet.

## What Egeria actually offers

Confirmed by reading pyegeria's source directly (`pyegeria/omvs/my_profile.py`,
`pyegeria/omvs/asset_maker.py`):

- **`ToDo`** is a real `PersonAction` type — a general-purpose human work item,
  separate from `RequestForAction` (which is an `Annotation` subtype, already
  how RE's own surveyors create RFAs — see `docs/survey-activity-design.md`).
  Fields include `activityStatus` (`REQUESTED`/`WAITING`/`IN_PROGRESS`/etc.),
  `priority`, `dueTime`, `startTime`, `requestedTime`, `completionTime`.
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

**Gap in pyegeria's own surface**: there is no single "complete a ToDo" or
"update ToDo status" convenience method. Status/due-date changes would go
through the generic element/action update path, not a purpose-built helper.
Any implementation needs to account for that lower-level call.

## What this would change

| RE concept today | Would become |
|---|---|
| `rfa_actions` table (`rfa_status`, `assignee`, `defer_until`, `resolution_note`) | A real Egeria `ToDo`, created per open RFA, linked via `add_action_target` to the RFA's `Annotation` GUID |
| Defer (local `defer_until` field) | `ToDo.dueTime`/`startTime` set via element update |
| Reassign (local `assignee` field) | `reassign_action(todo_guid, new_actor_guid)` |
| Complete (local `rfa_status = "completed"`) | `activityStatus` update via element update (no dedicated helper — see gap above) |
| `GET /api/activity/rfas` overlay | Would need to query both the RFA `Annotation` (already Egeria-native) AND its linked `ToDo`'s current status, rather than a local SQLite join |

## Open questions before building

1. **Who is the ToDo assigned to initially?** RE has no per-user identity yet
   (`whoami` is a single shared service account — see `egeria.py`). Real
   per-user assignment needs that solved first, or the initial assignee is
   just "unassigned"/the service account until reassigned.
2. **Migration**: does an existing local `rfa_actions` row get backfilled into
   a real `ToDo` on first load, or does this only apply going forward? Backfill
   means creating N `ToDo`s retroactively; going-forward-only is simpler but
   leaves historical RFA responses in two different places.
3. **Visibility trade-off**: this makes RFA response state visible to *any*
   Egeria client, not just RE — likely desirable (the whole point), but worth
   confirming that's actually wanted before every "defer this" click becomes a
   durable, catalog-wide-visible action instead of a quiet local note.
4. **Completion mechanics**: since pyegeria has no single "complete" call,
   decide whether to build a small RE-side helper wrapping the generic
   element-update call, or go through pyegeria's lower-level primitives
   directly at each call site.

None of this is scoped for implementation yet — this is the "what would it
take" writeup, so the next design conversation starts from confirmed facts
instead of assumptions.
