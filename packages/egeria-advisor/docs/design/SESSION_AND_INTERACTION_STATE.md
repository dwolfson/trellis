# Session & Interaction State Design

**Status:** Design only — not yet implemented. Captures the diagnosis and target
design from a review conversation (Jul 2026) before surgery begins.

## Problem 1: Plan/report mode confusion (confirmed root cause)

Symptom: user completes work in one flow (e.g. a report spec / plan draft),
switches to a different action (e.g. "run a pre-built report" from the
sidebar), and the system responds as if still inside the previous flow.

### Root cause (original diagnosis, since partially reworked — see below)

The frontend originally tracked "is a plan draft active" with a single
flag, `_activeDraftId`, mirrored to `sessionStorage`, cleared only on
specific response types, and never touched by the report-run sidebar flow.
`submitQuery()` always sent `draft_id: _activeDraftId || null` regardless of
what else was being requested, and the backend's `if draft_id:` branch
(`_process_query`) took unconditional priority over `intent_override`.

### Update (post `fix/report-selection-execution-rework`, PR #8): bug persists in relocated form

A rework landed (merged via PR #8, `docs/design/REPORT_SPEC_BUILDER_DESIGN.md`
era) that introduced a unified client-side context object as the intended
single source of truth:

```js
// index.html:585 — "authoritative task/phase state"
let _ctx = JSON.parse(sessionStorage.getItem('ea_ctx') || 'null') || {};
// task values: "report_spec_elicitor" | "plan_elicitor" | "act_confirm" |
//              "report_disambiguation" | null
```

`setContext()`/`clearContext()` (`index.html:587-631`) centralize updates,
and a "New Task" UI indicator (`index.html:276`, `clearContext()` button)
lets the user manually clear a stale context. This is a real structural
improvement — one object instead of four independent flags — **but the
underlying bug is unchanged, just relocated**:

- `runReport()` / `confirmRunReport()` (`index.html:739-770`, the "run a
  pre-built report" sidebar flow) still never call `clearContext()` or
  otherwise touch `_ctx`. A stale `_ctx.task` left over from an abandoned
  report-spec or plan Q&A session rides along unchanged.
- `submitQuery()`'s draft-id resolution (`index.html:1195-1197`):
  ```js
  const hasCtx = _ctx && _ctx.task;
  const draftId = hasCtx ? (_ctx.draft_id || null)
                : (selectedIntent ? null : (_activeDraftId || null));
  ```
  When `hasCtx` is true, `draftId` (and the full `context` payload) is sent
  **unconditionally** — not gated on `selectedIntent` or the caller's
  `intent_override` at all. `confirmRunReport()`'s `extra.intent_override =
  'report'` has no effect on whether the stale context is attached.
- Backend `_process_query` (`advisor/rag_system.py:474-540`) checks
  `context.task` first, still with no cross-check against
  `intent_override`/`query_type_override`:
  ```python
  _ctx_task = (context or {}).get("task")
  if _ctx_task == "report_spec_elicitor" and _ctx_draft_id:
      ...
  elif _ctx_task == "plan_elicitor" and _ctx_draft_id:
      ...
  ```
- The bare-word regex false positive also survives, now in the
  `report_spec_elicitor` context block (`rag_system.py:487`):
  ```python
  if re.search(r'\b(execute|run|go ahead|proceed)\b', _q):
  ```
  `"run report X"` still matches on bare `run`, so it still executes the
  **stale draft's report spec**, not the one the user clicked. (The
  `plan_elicitor` block was tightened to require `run\s+the\s+plan`,
  `rag_system.py:524` — the same fix was not applied to the
  `report_spec_elicitor` block.)
- A legacy fallback (`rag_system.py:623`, `if draft_id and
  draft_id.startswith("draft_report_"):`) still exists for backward
  compatibility and carries the same unconditional-priority shape.

**Net effect: the fix needs to happen in two places now** — the `_ctx`
object needs an explicit clearing trigger on any action that starts a
different flow (report run, different intent button, different sidebar
report), *and* the backend needs to stop trusting `context.task` when the
request also carries an explicit, conflicting `intent_override`.

### Contributing structural issue (unchanged)

`PlanCanvas` still keeps its own closure-scoped `_draftId`
(`advisor/web/static/plan_canvas.js`), synced to `_activeDraftId`/`_ctx`
only by convention from call sites, not enforced. The backend still has no
independent way to verify a client-submitted context/draft_id belongs to
the flow the client claims to be in — see Problem 2.

## Problem 2: No backend-owned session concept (concurrency/isolation)

Investigating problem 1 surfaced a related, larger gap: the backend has no
session concept at all today.

- `DraftManager` is a process-wide singleton
  (`advisor/governance_draft.py:204-210`, module-level `_dm`) writing to one
  flat shared directory, `~/egeria-plans/drafts/`.
- `draft_id` generation has no user or session scoping —
  `draft_id = f"draft_{ts}_{_slug(title)}"` (`governance_draft.py:97`), a
  timestamp + title slug. Any client that knows or guesses a `draft_id` can
  resume, edit, or execute another user's in-progress plan.
- `DocumentManager` (`advisor/governance_docs.py:39`) has the identical
  pattern: one shared `~/egeria-plans/{inbox,outbox}` regardless of caller.
  `PlanTemplateManager` and `SessionLogger` follow the same convention.
- The newer Report Spec Builder feature (`ReportDraftManager`,
  `advisor/report_draft.py:39`; `ReportSpecDocumentManager`,
  `advisor/report_spec_docs.py:24`) replicated the identical unscoped
  pattern against a second shared root, `~/egeria-reports/` — so the surface
  area for this fix grew, not shrank, since the original diagnosis.
- The JWT already carries a `user_id` (`get_current_user()` /
  `advisor/auth.py`), but `/api/query` (`advisor/web/app.py:268-270`) only
  uses it as a boolean (`egeria_authenticated`) — the actual `user_id` is
  discarded, never threaded into `rag.query()`, `DraftManager`, or anywhere
  else.
- `EgeriaContext` and the MCP report agent
  (`ReportPipeline.self._agent`, lazily created in `_ensure_agent()`) are
  also global singletons authenticating as one shared service account, not
  per-user. Lower priority — flagged, not solved by this design.
- `RAGSystem`'s core query pipeline was checked and holds no mutable
  per-query instance state (no `self.current_*` / `self.session*`) — it
  appears safe to call concurrently. **The risk is concentrated in the
  draft/document/report-agent layer, not the whole RAG stack.**

### Why `user_id` scoping alone is insufficient

Demo/shared-account environments run multiple concurrent browser sessions
under the *same* `user_id`. Scoping storage by `user_id` alone would still
let two concurrent tabs of the same demo user stomp on each other's
"currently active draft" pointer. Two scoping dimensions are needed, with
different lifetimes:

| Scope | Key | Lifetime | What lives there |
|---|---|---|---|
| **User** | `user_id` (JWT `sub`) | Persistent, survives logout/browser close | Drafts (durable records), inbox/outbox plan documents, templates, session logs |
| **Session** | new `session_id` | Ephemeral, dies with the tab | Active-draft pointer, current interaction mode, pending clarification |

A draft is a **user-scoped artifact** (so closing a tab and resuming later,
or from a different tab, still finds it) but "which draft is active in this
conversation right now" is **session-scoped** (so concurrent tabs of the
same user don't collide).

## Target design

### Storage layout — namespace by user

```
~/egeria-plans/users/{user_id}/drafts/
~/egeria-plans/users/{user_id}/inbox/
~/egeria-plans/users/{user_id}/outbox/
~/egeria-plans/users/{user_id}/templates/
~/egeria-plans/users/{user_id}/sessions/     (JSONL transcripts)
~/egeria-reports/users/{user_id}/drafts/     (report spec drafts)
~/egeria-reports/users/{user_id}/...         (mirror report_spec_docs.py's existing subfolders)
```

`DraftManager`, `DocumentManager`, `PlanTemplateManager`, `SessionLogger`,
`ReportDraftManager`, `ReportSpecDocumentManager` each take a `user_id` at
construction (or per-call) instead of resolving one global
`Path.home() / "egeria-plans"` / `Path.home() / "egeria-reports"`. Same
path-resolution pattern as today (`_drafts_path()` in
`governance_draft.py`, `_paths` dict in `governance_docs.py:39-54`, the
equivalent helpers in `report_draft.py`/`report_spec_docs.py`), just
parameterized by `user_id`. These stop being process-wide singletons and
become per-user instances (or a small cache keyed by `user_id`).

### Session store — new, small, in-memory

The app runs single-process today (`uvicorn advisor.web.app:app`, no worker
flag), so a simple in-memory store is sufficient for now:

```python
SessionState = {
    "user_id": str,
    "active_draft_id": Optional[str],
    "mode": str,           # "idle" | "draft" | "report_modal"
    "last_seen": float,
}
SESSIONS: Dict[str, SessionState]   # keyed by session_id, TTL-evicted
```

`session_id` is minted **client-side** as a UUID and stored in
`sessionStorage` (not `localStorage`) — this is already the right
primitive, since `sessionStorage` is tab-scoped and dies on tab close,
matching the desired session lifetime. Sent as a header (`X-Session-Id`) on
every request. No cookie/CORS complexity needed since JWT already handles
auth.

If this app ever moves to multi-worker or multi-instance deployment, the
in-memory dict would need to move to Redis or the deployment would need
sticky routing on `session_id`. Not needed for the current single-process
deployment.

### Routing fix

Backend stops trusting a client-sent `draft_id` as ground truth. Instead:

1. Look up `SESSIONS[session_id].active_draft_id`.
2. If the incoming request also carries an explicit `intent_override` that
   signals a mode switch (e.g. `report`), that is the backend's cue to park
   the session's active draft server-side — not something the client has to
   remember to do by clearing a JS variable.
3. `_process_query`'s `if draft_id:` branch (`rag_system.py:388`) is
   replaced by a check against the session's own active draft, not a raw
   client-supplied value.
4. The `_exec_pattern` bare-`run` false positive
   (`rag_system.py:430-435`) should also be tightened to require an object
   (`run (the )?plan`, `run it`, `execute`) regardless of the session fix —
   it's a latent bug independent of the state-machine issue.

### Known edge case (deferred, not blocking)

Two sessions of the *same* user opening the *same* draft concurrently (two
tabs, one demo login, same draft). The draft spec already has `updated_at`.
Cheap optimistic-concurrency check — reject/warn a save if the on-disk
`updated_at` moved since this session last read it — would catch silent
overwrites without building real locking/checkout UI. Treated as a
follow-on, not part of the initial surgery.

## Open question

`session_id` minting: client-generated (simplest, no extra round trip) vs.
backend-minted and handed back (more robust against a hostile/broken
client, more plumbing). Leaning client-generated given the trust model is
already JWT-based and this is an internal/demo tool, not a public API.
