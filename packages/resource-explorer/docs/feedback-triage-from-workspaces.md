# Feedback triage — what Egeria Workspaces Portal does that RE doesn't

Dan's ask: "look at how egeria-workspaces portal handles feedback and user editing in their
admin page - ours has no way to change the status or anything." This doc verifies that claim,
describes what Workspaces actually does (from code and a real database, not the design docs
alone), and reconciles it with RE's own vocabulary and with EA's (per
`docs/feedback-signals-shared.md`, the companion survey this one was asked to build on).

**Read-only survey.** Nothing in either `egeria-workspaces` checkout was modified. All Postgres
access was blocked by this session's sandbox (`psql -h localhost -p 5442 ...` was denied by the
permission classifier before it could run) — findings that would have come from the live
Postgres `demo.feedback` table are explicitly marked as unverified below, not asserted.

## 0. Verifying the gap: is RE's Admin feedback pane really read-only?

Yes. `resource_explorer/web/routes/feedback.py` exposes `POST` (submit), `GET` (list), `GET
/stats`, and `PATCH /{feedback_id}` (`:95-97`) — so RE *does* have a triage-status PATCH
endpoint, gated by `_require_admin` (`:44-46` calling
`resource_explorer/web/admin_auth.py:21-38`). But nothing in
`resource_explorer/web/static/admin-feedback.html` calls it:

```
grep -n "PATCH\|patch(" resource_explorer/web/static/admin-feedback.html   →  no matches
```

The page renders `triage_status` as read-only text (no `<select>`, no button wired to a PATCH).
So the backend has the capability; the UI Dan is looking at does not expose it. That is the
gap — narrower than "RE has no way," but the effect Dan sees (nothing in the pane lets him
change a status) is accurate. Confirmed by reading
`resource_explorer/web/static/admin-feedback.html` in full: it fetches
`/api/feedback/stats` and `/api/feedback` only (per
`docs/feedback-signals-shared.md:2.1`), with no write call anywhere in the file.

The Admin → Observe → Feedback panel in `index.html` (`loadAdminFeedbackPanel`,
`web/static/index.html:12640-12712` per the companion survey) reads
`GET /api/curate/feedback`, which serves `resource_feedback` (no `triage_status` column at
all, `registry.py:1233-1242`) combined with `feedback` rows tagged `source: "page"`
(`curate.py:79-143`). That combined view also has no write path.

## 1. What can a Workspaces admin actually do?

Two independent admin HTML pages exist and are functionally identical for feedback:
`compose-configs/egeria-quickstart/PyegeriaWebHandler/local-admin.html` and
`.../demo-admin.html` (also duplicated under `egeria-freshstart/`). Both:

- Render a table from `GET /api/demo-feedback` (`local-admin.html:469`,
  `demo-admin.html:599`), gated `_is_admin` (see §5 on that gate).
- Show summary counts from `GET /api/demo-feedback/stats`
  (`demo_feedback_handler.py:243-258`): `total`, `new`, `wants_response`, `avg_rating`.
- Put a `<select>` in the last column of every row
  (`local-admin.html:492-495`, `demo-admin.html:620-623`) populated with exactly
  `['new','triaged','actioned']`, current value pre-selected. `onchange` fires
  `triageFeedback(id, value)` (`local-admin.html:503-511`,
  `demo-admin.html:631-...`), which does:

```js
fetch('/api/demo-feedback/' + id, {
  method: 'PATCH', headers: {...},
  body: JSON.stringify({ triage_status: status }),
});
```

That is the **entire** write surface. Enumerating what the task asked for, against the actual
route (`demo_feedback_handler.py:261-278`):

| Operation | Present? | What it writes | Audited? |
|---|---|---|---|
| Change status | Yes — the only op | `triage_status` column, in place | **No.** No `updated_at`, `updated_by`, or history table. `row.triage_status = body.triage_status; db.commit()` (`:272-273`) is a bare overwrite — the prior status is gone the instant the PATCH lands. |
| Assign (to a person) | No | — | — |
| Annotate (add a note) | No | — | — |
| Resolve (distinct from "actioned") | No — `actioned` is the closest concept, and it's just another `triage_status` value | — | — |
| Delete | No — no `DELETE /api/demo-feedback/{id}` route exists in the file at all | — | — |
| Reply (to the submitter) | No | — | — |

No route, in either handler file, ever touches `message`, `category`, `rating`, `email`, or any
other field the visitor submitted. The *content* of a feedback row is permanently
visitor-authored and admin-immutable in Workspaces today; only `triage_status` is admin-owned.
This is actually a useful property (see §4) — Workspaces never had to solve "how does an editor
avoid destroying the original," because it never allows editing content at all.

Separately, `egeria_feedback_handler.py` (`compose-configs/.../PyegeriaWebHandler/`) proxies
Egeria's *native* likes/ratings/comments feedback (a completely different system — see §3.3).
Its comment `PUT` (`:248-280`) does a `mergeUpdate: True` against Egeria's own
`update_comment`, which is a genuine in-place content edit of a *comment*, not of the
demo-tool `triage_status` workflow. It carries no visible "edited" marker in the UI beyond
whatever Egeria's own `versions` metadata records (`elementHeader.versions`, not surfaced by
this handler's `_comments_list`, `:200-222`, which returns only `createdBy`/`createTime`, no
`updateTime`).

## 2. Status vocabulary and transitions — from the database, not just the docs

**Design doc and code agree**: `demo_feedback_handler.py:67` (`triage_status = Column(...,
default="new")`, comment `# new | triaged | actioned`) and
`design-docs/feedback-analyst-guide.md:36` (`| triage_status | varchar(20) | \`new\` ·
\`triaged\` · \`actioned\` |`) both give the same three-value enum.

**The database does not corroborate `actioned` as a real, used state — and here's the honest
limit on that claim.** Two candidate databases exist:

1. `runtime-volumes/quickstart-demo-data/feedback.db` (SQLite) — the file the task named. Read
   directly:
   ```
   sqlite3 feedback.db ".schema"
   → CREATE TABLE demo_feedback (id, session_id, user_id, section, star_rating, comment,
      contact_email, user_agent, created_at)   -- no triage_status column at all
   ```
   4 rows, last write `2026-06-03 10:38` (file mtime). This table **predates** the
   `triage_status` feature entirely — it's a different, older schema (`demo_feedback` not
   `feedback`; `section`/`star_rating`/`comment` not `page`/`rating`/`message`/`category`) from
   before `demo_feedback_handler.py`'s FB-5 migration to Postgres (the handler's own docstring,
   `:8`: "FB-5 Storage: Postgres instead of SQLite; schema demo.feedback"). This file is stale
   and superseded, not the live store — it tells us the *shape* evolved, but nothing about
   `triage_status` usage, because the column didn't exist yet when this file was last written.
2. The actual live store is Postgres, `demo.feedback` in the `coco_pharma` database at
   `localhost:5442` (per the handler's module docstring and
   `feedback-analyst-guide.md`'s connection string). **This session could not query it** — the
   `psql` command was blocked by the sandbox's permission classifier before execution. So
   whether any row has ever actually reached `triaged` or `actioned`, in Workspaces, is
   **unverified** here.

What *can* be said with confidence: `design-docs/feedback-analyst-guide.md` — a guide written
specifically to give analysts real SQL for this table — mentions `actioned` exactly once, in
the schema reference table (`:36`), and **never again**. Every worked example query in the same
file references only `new` and `triaged` (`:86-138`, including the "bulk-triage" recipe at
`:134-138` which only ever sets `triage_status = 'triaged'`). That is circumstantial but real
evidence that `actioned` is a designed-but-not-yet-operationalized state — the schema and UI
both support it, but the people who use this table daily apparently don't reach for it. Anyone
relying on this doc for a live decision should re-run
`SELECT triage_status, COUNT(*) FROM demo.feedback GROUP BY 1` against the real Postgres
instance before trusting that inference.

**Transitions**: none are enforced. The `<select>` in both admin HTML pages allows any of the
three values from any current value — no state machine, no "can't go from `actioned` back to
`new`" guard. `TriageRequest` (`demo_feedback_handler.py:154-155`) validates only that the
submitted string is one of the three values (`:265-266`); it does not look at the row's current
state at all.

## 3. Reconciling three vocabularies: Workspaces, EA, RE

`docs/feedback-signals-shared.md` (§1.3, §5) already found EA's triage vocabulary is a
**superset** of RE's:

- RE / `feedback_store.py:28`: `{new, triaged, actioned}`
- EA / `advisor/web/static/admin.html:698-704`: `{new, known_issue, actioned, deferred,
  not_an_issue}`

Workspaces' vocabulary (§2 above) is `{new, triaged, actioned}` — **identical to RE's**, which
is not a coincidence: `resource_explorer/feedback_store.py`'s own docstring says it was "Ported
from Egeria Workspaces Portal's `demo_feedback_handler.py`" (`:9-12`), and a byte-for-byte
comparison confirms it — same three states, same default (`"new"`), same column set minus the
Portal-specific `session_id`/`env`/`persona`/JWT fields RE has no equivalent of. So this is not
three independent vocabularies to reconcile; it is **two identical vocabularies (Workspaces,
RE) plus one superset (EA)**.

Concretely, EA distinguishes two things Workspaces/RE's `triaged` collapses into one bucket
(`feedback-signals-shared.md` §1.3):
- `known_issue` — seen, characterized, real, not yet fixed
- `not_an_issue` — seen, and reviewed as *not* a real problem
- `deferred` — seen, real, deliberately not being worked now

versus Workspaces/RE's single `triaged`, which could mean any of those three, or simply
"someone looked at it and hasn't decided yet."

**Egeria's native feedback model does not have a triage vocabulary to align with.**
`pyegeria/feedback_manager.py`'s `FeedbackManager` (checked in
`egeria-workspaces/.venv/lib/python3.13/site-packages/pyegeria/feedback_manager.py:98-780`)
exposes only likes, star ratings, and comments — `add_like_to_element`,
`add_rating_to_element`, `get_attached_likes`, `get_attached_ratings`, and their `remove_*`
counterparts. No status/triage concept anywhere in the class. Correspondingly,
`md_processing/md_commands/feedback_commands.py`'s Dr.Egeria commands are `Add Comment`,
`Journal Entry`, `Upsert Note`, `Attach Note Log`, `Upsert Informal Tag`, `Tag Element` — all
annotation/commentary primitives, none of them a workflow-status field. This confirms
`design-docs/feedback_plan.md`'s own framing (item 2: "Egeria and pyegeria has an internal
feedback API that supports: Likes, Ratings and Comments... This will probably be an iterative
process") — the demo-tool `triage_status` workflow was *designed as a separate concept from*
Egeria's native feedback API, not derived from it. **RE should not try to express
`triage_status` as an Egeria-native concept** (e.g. as a classification or a comment type) —
there is no existing Egeria vocabulary for "an admin's review state of a piece of feedback,"
and inventing one there would be a bigger, out-of-scope change than this task calls for.

### Proposed unified vocabulary

Adopt EA's superset, exactly as `feedback-signals-shared.md` §5 already proposes, with the
values kept intentionally distinct rather than collapsed:

```
new, triaged, known_issue, deferred, not_an_issue, actioned
```

What each source contributes:

| Value | Contributed by | Meaning |
|---|---|---|
| `new` | Workspaces + RE (shared origin) | Untriaged — nobody has looked at it |
| `triaged` | Workspaces + RE (shared origin) | Looked at, not yet further characterized — kept as a real intermediate state, not merged away, since collapsing it into `known_issue` would force every admin to make a characterization decision at triage time instead of two steps |
| `known_issue` | EA | Looked at, confirmed real, not yet actioned |
| `deferred` | EA | Looked at, confirmed real, deliberately not being worked now |
| `not_an_issue` | EA | Looked at, reviewed, and rejected as not a real problem |
| `actioned` | Workspaces + RE (shared origin) | Something was actually done about it |

This is the same list `feedback-signals-shared.md` §5 already names ("The triage vocabulary,
extended to EA's superset: `new, triaged, known_issue, actioned, deferred, not_an_issue`") —
this survey independently arrives at the identical set from the Workspaces side, which is
corroborating evidence rather than a new proposal. Per that doc's own honest-limits section,
whether RE's `triaged` and EA's `known_issue` name the same state is a product call this survey
cannot resolve from code alone; the table above resolves it by treating them as genuinely
different points in a triage lifecycle (seen vs. characterized), consistent with keeping both
as distinct enum values rather than choosing one name over the other.

**What RE should not adopt from Workspaces:** nothing structural — Workspaces' vocabulary is a
strict subset of the proposal above, already covered. The one Workspaces *behavior* RE should
explicitly not copy is the bare unaudited overwrite in `triage_feedback`
(`demo_feedback_handler.py:261-274`) — see §4.

## 4. Editing safety

The task brief states RE's `feedback` table has 9 real rows going back to 2026-08-11,
including Dan's own reports; this survey did not re-query that count (Postgres access was
blocked — see §2's limits note) and takes it as given, consistent with
`feedback-signals-shared.md` §7's same caveat.

Workspaces' own answer to "how do you avoid destroying content" is **it never lets an admin
edit content at all** — only `triage_status` is writable, and even that write is a silent,
unaudited overwrite (§1). That is a real design point worth borrowing (don't let admins touch
`message`/`rating`/`category`/`email` — those are the submitter's record of what happened, not
the admin's to rewrite), but the overwrite-with-no-history part of it is exactly what "editing
safety" should avoid reproducing.

**Proposal for RE:**

1. **Status changes are in-place, but audited**, not append-only. A `triage_status` value is a
   current-state flag, not content — there is no reader-facing "original" to preserve, so
   in-place is correct *for this field specifically*. But unlike Workspaces, every change
   should append a row to a small `feedback_triage_log(feedback_id, from_status, to_status,
   changed_by, changed_at)` table (or equivalent), so "who changed what, when" survives even
   though the current-state column itself is overwritten. This directly fixes the gap this
   survey found in Workspaces (§1: "No `updated_at`, `updated_by`, or history table").
2. **Free-text admin annotation (once RE adds one — it doesn't have one today) must be
   append-only**, not a rewrite of the submitter's `message`. If RE adds an "analyst notes"
   field (the way EA's `analysis_comments` works, per `feedback-signals-shared.md` §1.3), it
   should be a separate column/table from `message`, never a field the admin edit overwrites in
   place — the submitter's original text must remain byte-for-byte recoverable. This is the
   direct application of this codebase's absence-vs-decision rule extended to *content*, not
   just status: an edited message must never look, structurally, like the visitor's original
   message.
3. **A reader must be able to tell edited-by-admin from original-by-visitor** at the data
   level, not just by convention: keep `message` (visitor-authored, immutable after
   submission) and any admin annotation in visibly different columns/fields in every view that
   renders them — never concatenate or overwrite one into the other. This mirrors the envelope
   design `feedback-signals-shared.md` §4 already proposes for cross-store reconciliation
   (`message: str | None` distinct from a store's absence-of-concept), applied here to
   within-store admin edits.
4. **Untriaged is not a decision**, and the vocabulary in §3 keeps it that way: `new` (or
   `NULL`/absent `triage_status`, if RE ever allows a row to exist without one) must render
   distinctly from every reviewed state, including `not_an_issue`. Concretely: a UI that shows
   `triage_status || '—'` for missing status (as `local-admin.html:491` already does — `esc(r.
   triage_status || '—')`) gets this right by accident for the *display* case, but any
   aggregate/count logic downstream must not treat a missing/`new` status as equivalent to
   `not_an_issue` just because both currently render as "nothing has changed yet." This is the
   exact class of bug this codebase already watches for (absence read as a decision) — worth
   stating explicitly here since it's the constraint the task called out by name.

## 5. `_is_admin()`'s permissive default is DELIBERATE, not a bug

> **Corrected 2026-09-01 by Dan, who owns both projects.** This section originally
> reported `_is_admin()` returning `True` when neither `DEMO_MODE` nor
> `SERVER_MANAGED_AUTH` is set as a live fail-open security bug, and recommended
> reporting it upstream. **That is wrong.** The Portal has two modes: a public
> demo requiring an external identity, and a **local mode that relies on Egeria's
> own users** for authentication. Permitting the request in the unconfigured case
> is the local mode working as designed — the authentication happens in Egeria,
> not in the handler.
>
> RE's `admin_auth.py` takes the opposite default because RE has nothing to defer
> to: no multi-user authentication of its own, and no authenticating layer behind
> it. Same reasoning, different surroundings, opposite conclusion. Its docstring
> made the same mischaracterisation and has also been corrected.
>
> Worth keeping rather than deleting, as an instance of a recurring failure: code
> read WITHOUT its deployment context looks like a defect. The observation was
> accurate — the default really is permissive — and the label put on it was
> wrong. The rest of this section is left below for the mechanics; read its
> "bug" framing as withdrawn.

### Original finding (framing withdrawn — mechanics still accurate)

**Confirmed still present**, in both copies of the handler
(`compose-configs/egeria-quickstart/PyegeriaWebHandler/demo_feedback_handler.py:122-125` and
the byte-identical `egeria-freshstart/PyegeriaWebHandler/demo_feedback_handler.py`):

```python
def _is_admin(request: Request) -> bool:
    # Local quickstart has no auth at all — admin page is served without a gate
    if not DEMO_MODE and not SERVER_MANAGED_AUTH:
        return True
    ...
```

`DEMO_MODE` and `SERVER_MANAGED_AUTH` both default to `false`
(`demo_config.py:13,19` — `os.environ.get(..., "false").lower() in ("true","1","yes")`). So in
any deployment where neither env var is explicitly set — the plain "local quickstart" case —
`_is_admin` returns `True` unconditionally for every request, including the
`GET /api/demo-feedback`, `GET /api/demo-feedback/stats`, and
`PATCH /api/demo-feedback/{id}` admin routes. This matches exactly what
`resource_explorer/web/admin_auth.py:8-12`'s docstring already describes as the bug it was
written to invert — that description is accurate and the bug it cites is real and unfixed as
of this reading. This is a live defect in `egeria-workspaces-fs` (the bind-mounted, running
checkout); fixing it is out of scope for this survey and for RE, but it should be reported
upstream.

## 6. Honest limits

- **No live Postgres query was possible.** `psql -h localhost -p 5442 ...` was denied by this
  session's sandbox before it ran. Every claim in §2 about which `triage_status` values have
  actually been *used* in Workspaces' real `demo.feedback` table is inferred from code defaults
  and the analyst guide's example queries, not from row data. This is the single biggest gap in
  this survey relative to what the task asked for ("Its schema and actual row values tell you
  what states and transitions are really used").
- **`runtime-volumes/quickstart-demo-data/feedback.db` is stale** (last write 2026-06-03,
  three months before this survey) and predates the `triage_status` column entirely — it could
  not be used as evidence for §2 beyond showing the schema changed shape since FB-5.
- **The older `egeria-workspaces` clone** was used only for `pyegeria`'s
  `feedback_manager.py`/`feedback_commands.py` (inside its `.venv`, which is generated/vendored
  code, not something either clone's own commits diverge on) — it was not otherwise surveyed for
  divergence from `egeria-workspaces-fs`, since the task's admin-page/handler questions are all
  answered from the live, bind-mounted `egeria-workspaces-fs` checkout.
- **RE's `feedback_store.py:VALID_TRIAGE_STATUSES` was read as ground truth for RE's current
  vocabulary**; RE's live 9-row count from the task brief was not re-verified in this pass
  (consistent with `feedback-signals-shared.md`'s own §7, which explicitly defers that
  verification to before any write-path change lands).
- **Whether Workspaces' comment-edit (`egeria_feedback_handler.py`'s `PUT
  .../comments/{comment_guid}`) actually preserves any recoverable edit history inside Egeria
  itself** (via `elementHeader.versions.updateTime` or similar) was not verified beyond noting
  that this handler's own JSON-shaping code (`_comments_list`, `:200-222`) doesn't surface it —
  Egeria's underlying storage may retain more than this handler exposes; that wasn't traced
  further since it's the native-comments system, not the triage workflow the task centers on.
