# SS-4 — per-user artifact namespacing

**Status:** design, not built. Written 2026-08-29 after Dan settled the two questions that had this
paused. One question remains open (§5).

## 1. The problem

Six process-wide singleton managers write to fixed roots with **no ownership metadata at all**:

| Manager | Root |
|---|---|
| `DraftManager`, `DocumentManager`, `PlanTemplateManager`, `SessionLogger` | `~/egeria-plans/` |
| `ReportDraftManager`, `ReportSpecDocumentManager` | `~/egeria-reports/` |

`grep created_by|user_id|owner` returns **nothing** in any of the five artifact managers. The only
creator record anywhere is the `**Created by:**` line in a plan document's markdown header, and
`_compose_document` fills that from `$USER` — the *server process's OS user*, not the logged-in web
user. A live outbox plan reads `**Created by:** dwolfson`.

Consequences today: any client that knows or guesses a `draft_id` can act on another user's draft;
`GET /api/plans`, `/api/drafts`, `/api/reports` list every user's documents unfiltered; and
`/api/plans` has no auth check at all.

The *other* half of multi-user safety was fixed 2026-07-11 — per-user Egeria credentials
(`auth.get_egeria_credentials` / `resolve_egeria_credentials`, threaded through `rag_system.py` →
`report_pipeline.py` / `dr_egeria_agent.py` / `governance_plan_agent.py` / `egeria_context.py`) and
hard-required login on the live-Egeria endpoints. That fix does not touch storage layout. This is
the remaining half.

## 2. Settled — the namespace key

**Dan, 2026-08-29: "There is one namespace — which is the one we use to connect to Egeria."**

So the namespace is **the Egeria user the app connects as**, not an app-local user id invented for
the purpose. That already exists and is already per-request:

```
get_egeria_credentials(request)  ->  {"user_id": <from the JWT>, "password": ...}
resolve_egeria_credentials(creds) ->  falls back to settings.egeria_user
```

This is a better key than an app-local one for the reason Dan gives: artifacts are *about* Egeria
work, so the identity that scopes them should be the identity that performs it. It also means the
namespace and the credentials cannot drift apart — a user cannot end up writing artifacts under one
identity while acting in Egeria as another.

Layout: `~/egeria-plans/{egeria_user}/drafts/`, `~/egeria-reports/{egeria_user}/inbox/`, etc.

## 3. Settled — the migration

**Dan, 2026-08-29: a one-time migration assigning existing artifacts to `peterprofile` (the Egeria
user we are logged in as).**

That resolves what previously had no answer: the 49 existing artifacts (5 plan drafts, 24 session
logs, 11 report drafts, plus inbox/outbox/template files) carry no owner, so nothing could derive
one. A one-time assignment is the honest move — it states a decision rather than inferring one from
`$USER`, which would be wrong for the reason in §1.

The migration is a directory move per manager root, run once, idempotent (skip anything already
under a namespace directory), and reversible while nothing else has written.

## 4. Settled — an authenticated identity is required, with no config fallback

**Dan, 2026-08-29: "require an authenticated identity, no config fallback."**

This resolves the prerequisite found while designing this note, and resolves it by removing the
unreliable path rather than repairing it.

**What the problem was.** `settings.egeria_user` resolves differently depending on where the process
was started: `config.py:247` declares `env_file=".env"` — a *relative* path resolved against the
process CWD — so from `packages/egeria-advisor/` it reads `EGERIA_USER=peterprofile`, and from the
repo root, where no `.env` exists, it silently falls back to the `garygeeke` default at
`config.py:271`. As a namespace key that would scatter artifacts across two directories depending on
how the server happened to be started, with neither looking wrong to the code.

**The decision removes it as a key entirely.** The namespace is the **authenticated** Egeria user
from the request's JWT (`auth.get_egeria_credentials`). `resolve_egeria_credentials`'s fallback to
the `.env` service account is *not* used for artifact scoping. Where there is no authenticated
identity, the app **refuses to write or read artifacts** rather than choosing one.

That is stricter than today's behaviour and deliberately so: a silent scatter becomes an explicit
failure, and every artifact on disk is then attributable to a real user by construction rather than
by convention. `.env` remains what it is — a default for *connecting*, per app, not an identity that
owns anything.

**Consequence, stated because it follows rather than being separately decided: `/api/plans` gains an
auth check.** It has none today (§1). If artifact access requires an identity, an endpoint that
lists artifacts cannot be anonymous. This closes §5's open question in the same stroke — the
storage-layout half and the auth half are no longer separable, because the layout *is* the identity.

## 5. Resource Explorer will need this too, and it is a much larger piece

**Dan: "both EA and RE will need (ultimately) to support multi-user."**

EA can do this now because it already has real per-user login. **RE cannot**, and the gap is bigger
than a refactor:

* RE has **no login mechanism at all.** `/api/egeria/whoami` — the source of the header's
  "Connected as: erinoverview" — returns `get_config().egeria.user_id`, and the comment above it
  says so plainly: *"from config/.env, not a logged-in individual … deliberately NOT a login
  mechanism. Real per-user login was raised and explicitly deferred as its own, larger piece of
  scope."* The badge is cosmetic; nobody has authenticated.
* There is **no shared connection object** carrying an identity. Identity is read from
  `os.getenv("EGERIA_USER", …)` at **26 separate sites**, each constructing its own pyegeria client.
* The fallbacks are **not even consistent**: 4 × `_DEFAULT_USER` (itself `"erinoverview"` in four
  modules), 3 × `"steward"`, 3 × `"erinoverview"`, 1 × `""`. So which identity an RE operation acts
  as depends on which module built the client — a stronger version of the CWD problem, varying by
  code path rather than by working directory.

So RE's multi-user work is: build a login, establish one identity source, and collapse 26 sites onto
it. It is a separate item from this one and should not be folded in.

## 6. Shape of the work

1. ~~Settle the namespace key, the migration, the env fallback, and the auth question~~ — all
   settled (§2, §3, §4).
2. A single `artifact_root(egeria_user)` helper — one place that maps identity to directory, rather
   than six managers each deriving it.
3. Thread the identity to the managers. **This is the large part:** the six singleton factories are
   called from **115 sites** (`get_doc_manager` 37, `get_draft_manager` 28,
   `get_report_spec_doc_manager` 19, `get_report_draft_manager` 18, `get_session_logger` 7,
   `get_template_manager` 6), none of which take a user today. Per-user instances keyed by identity
   are preferable to threading a parameter through every method.
4. Ownership check on every `draft_id`/`doc_id` access, not only on listing — the guessing hole is
   the one that matters.
5. The one-time migration (§3).
6. Overlaps **TC-5** (`web/app.py` router split). Both touch the same ~50 endpoints; doing them in
   either order is fine, doing them simultaneously is not.
