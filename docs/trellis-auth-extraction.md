# Trellis-level login — where it should live, and what it costs

**Status:** design note, 2026-08-29; extracted and adopted by EA. **Revised 2026-09-04** — the
token contract changed (see §6). Prompted by the project owner: *"If RE doesn't have a login,
it should — we could do this at the Trellis level or in each of EA and RE."*

**Recommendation: the Trellis level, as `trellis-auth`, with EA's implementation as the base and RE
adopting it.** Reasoning below, including the part that argues against a shared package.

> **The one thing to read if you read nothing else:** since 2026-09-04 the app JWT carries the
> user's **Egeria bearer token**, never their password, and `exchange_portal_token` validates the
> payload the Portal *actually* issues. §6 records the mismatch that was found and fixed. RE has not
> adopted this package yet, so it inherits the corrected contract with no migration.

---

## 1. Where the two apps actually stand

**Egeria Advisor has a real login.** `advisor/auth.py` (255 lines): HS256 JWT
(`create_access_token` / `decode_token` / `get_current_user` / `require_egeria_user`), Egeria
credentials carried in the token (`get_egeria_credentials`), live credential validation against a
real Egeria server (`validate_egeria_credentials` — attempts `create_egeria_bearer_token`), and
**Portal SSO** via `exchange_portal_token`, which validates a short-lived JWT the Portal issues under
a *shared HS256 secret*.

**Resource Explorer has none.** `/api/egeria/whoami` returns `get_config().egeria.user_id`, and the
comment above it is explicit: *"from config/.env, not a logged-in individual … deliberately NOT a
login mechanism. Real per-user login was raised and explicitly deferred as its own, larger piece of
scope."* The header's "Connected as: erinoverview" is cosmetic — nobody authenticated.

Worse than absent, RE's identity is **inconsistent**. It is read from `os.getenv("EGERIA_USER", …)`
at **26 sites**, each constructing its own pyegeria client, with four different fallbacks:

```
4 × _DEFAULT_USER   (itself "erinoverview", defined separately in four modules)
3 × "steward"
3 × "erinoverview"
1 × ""
```

So which identity an RE operation acts as depends on which module built the client.

## 2. Why Trellis level rather than one each

**Because the expensive half is a contract with an external system, not a login form.**
`exchange_portal_token` implements a shared-secret agreement with the Egeria Portal: a payload shape
(`sub`, `role`, `display_name`, `egeria_token`, `exp` — see §6; until 2026-09-04 this package
believed it was `egeria_user`, `egeria_password`, `iat`, `exp`), an algorithm, a secret, and an
expiry policy. Two
implementations of that contract will drift, and **drift in an auth contract is an auth bug, not a
cosmetic one** — the failure mode is one app accepting a token the other rejects, or worse, the
reverse.

**Because this repo has a documented track record of exactly this divergence**, and it is not
speculative:

| Built twice | What happened |
|---|---|
| Query cache | EA's was named and documented as LRU throughout and was **FIFO** — a hot entry evicted while a colder one survived |
| Annotation properties | The filesystem publisher's copy read an attribute that **exists on no class**, so no filesystem analysis ever reached Egeria; the test suite patched the method out, so nothing caught it |
| Vector store | Structurally similar, behaviourally distinct — extracted as `trellis-vectorstore` |
| Registry connection management | EA's `ConsolidatedDBManager` is a narrower, Postgres-only reinvention of RE's dual-engine abstraction |
| BeeAI agent base | Copy-pasted down to matching inline comments explaining the event-loop workaround |

Five instances. In each, one implementation was materially better and the other quietly wasn't.

**Because this is the cheapest possible moment.** RE has nothing, so it *adopts* rather than
*converges* — there is no second implementation to reconcile, no behaviour to preserve, no migration.
Every other extraction in the table above paid reconciliation costs that this one does not.

**Because the identity is Egeria's, not the app's.** Both apps authenticate the same user against the
same Egeria server for the same purpose. An app-local login would be inventing an identity that then
has to be mapped back to the Egeria one — which is precisely the mapping that `.env` fallbacks do
badly today.

## 3. The argument against, stated fairly

A shared auth package is a shared blast radius: a bug in it is a bug in both apps at once, and auth
bugs are the worst kind to have coupled. Two independent implementations fail independently.

**Why it does not win here:** the alternative is not "two well-tested implementations" but "one
tested implementation and one written later under time pressure to catch up" — which is what the
table in §2 records happening five times. Coupled-and-tested beats independent-and-drifting for a
contract that must agree with a third system anyway.

## 4. What is shared and what is not

Same split as `trellis-vectorstore` and `trellis-querycache`: the package holds mechanism and never
reads the environment; each app resolves its own config into a frozen dataclass.

**Shared (`trellis-auth`)** — roughly 200 of `auth.py`'s 255 lines:
`create_access_token`, `decode_token`, `get_current_user`, `require_egeria_user`,
`is_authenticated`, `get_egeria_token`, `exchange_portal_token`, `login_with_password`,
`validate_egeria_token`, `validate_egeria_credentials`, `egeria_token_expiry`, `apply_token`.
(`EgeriaCredentials` and `get_egeria_credentials` left the package on 2026-09-04 — see §6.
`get_egeria_credentials` remains as a shim that raises with an explanation rather than a
`{user_id, password}` dict nothing can produce any more.)

**App-specific, and must stay so:**
* **Policy**, not mechanism — EA's `_anonymous_rag_mode` and `_auth_enabled` decide *whether* an app
  demands a login, which is each app's own answer.
* **Config location** — EA reads `advisor/configdata/advisor.yaml` and `mcp_servers.json`; RE has its
  own. Neither belongs in the package.
* **`resolve_egeria_credentials`'s service-account fallback.** Deliberately excluded. Per the SS-4
  decision (2026-08-29), artifact ownership requires an *authenticated* identity with **no config
  fallback**, and a shared package should not ship the fallback that decision exists to remove.

## 5. What this does NOT cost, and what it does

The package is necessary but **not sufficient** for RE, and the estimate should say so:

1. `trellis-auth` extraction — mechanical, EA's code, no behaviour change for EA.
2. **A login UI in RE's SPA** plus token storage and refresh. RE's frontend has never had one.
3. **Collapsing RE's 26 `os.getenv("EGERIA_USER", …)` sites** onto the authenticated identity, and
   removing four inconsistent fallbacks. This is the part most likely to surface behaviour
   differences, because today different code paths genuinely act as different users.
4. A decision RE has not had to make: **what RE does when nobody is logged in.** Its surveys and
   schedulers run unattended, so "require an authenticated identity" cannot mean the same thing it
   means for EA's interactive artifact writes. A scheduled survey has no user — it needs a declared
   service identity, which is a legitimate use of a configured account and is *not* the same as the
   silent fallback SS-4 removes.

Item 4 is the real design question and is worth settling before item 1 is built, because it decides
whether `trellis-auth` needs a first-class notion of a non-interactive principal.

---

## 6. The token contract, and the mismatch that motivated changing it (2026-09-04)

### The finding

`trellis-auth` and the Egeria Portal did not agree, and had never agreed:

| | What `trellis-auth` did (until 2026-09-04) | What the Portal actually does |
|---|---|---|
| App/session JWT payload | `{sub, egeria_user, egeria_password, iat, exp}` — the **raw password signed into an HS256 token** | `{sub, role, display_name, egeria_token, exp}` (`demo_auth_handler.py::_make_jwt`, ~line 202) |
| Per-request Egeria auth | `get_egeria_credentials()` → `{user_id, password}`, then `create_egeria_bearer_token(user_id, password)` on **every** request | `client.set_bearer_token(token)` via a contextvar middleware (`egeria_auth.py::apply_token`) |
| `exchange_portal_token` expects | `{egeria_user, egeria_password, iat, exp}` | — nothing in `egeria-workspaces` has ever produced that shape |

So EA's Portal SSO route, `POST /api/auth/portal`, was wired to a payload the Portal does not send.
It would have accepted a validly-signed token and then minted a session with an empty
`egeria_password`. Nothing failed loudly, because nothing ever exercised the route end-to-end
against the real Portal — the mismatch is only visible by reading both sides, which is what
`docs/runtime-architecture-plan.md` §4 did.

The password-in-the-JWT half is worse than the SSO half. A JWT is signed, not encrypted: anyone
holding the session token — the browser's local storage, a proxy log, an error report — could
base64-decode the user's Egeria password out of it.

### The decision

**The app JWT carries the user's Egeria bearer token, never the password.** One contract serves both
ways into a trellis app, because both must end in the same thing: *a per-request pyegeria client
holding an Egeria bearer token for the actual user.*

* **Direct login.** The app's login form takes an Egeria user id and password, calls
  `login_with_password()` → pyegeria's `create_egeria_bearer_token()` **once**, and issues an app
  JWT around the returned token. The password exists only for that instant.
* **Portal SSO.** The Portal already logged the user into Egeria. `exchange_portal_token()`
  validates its real payload under the shared secret (`ADVISOR_PORTAL_SECRET` ↔ the Portal's
  `JWT_SECRET`, configured together at `egeria-quickstart.yaml:248`) and the app re-signs it as its
  own session, with **no Egeria round-trip** beyond an optional cheap liveness check
  (`validate_egeria_token()`, one `get_my_profile()` call).

### The new payload

```
{sub, user_id, role, display_name, egeria_token, iat, exp}
```

`sub` and `user_id` are the same value — `sub` is what the Portal uses, `user_id` is what the rest
of trellis calls it. There is no password field under any name, and a test asserts on the raw token
bytes so one cannot creep back under a different key.

### Egeria's token TTL, and why `exp` is capped

**Egeria bearer tokens last one hour.** Measured live on 2026-09-04 against the running quickstart
deployment (`qs-view-server` at `https://localhost:9443`) by minting one with pyegeria's
`create_egeria_bearer_token()` and base64-decoding the payload:

```json
{"iss": "self", "sub": "peterprofile", "iat": 1788540043, "exp": 1788543643,
 "displayName": "Peter Profile"}
```

`exp - iat = 3600`. It is an RS256 JWT signed by the view server, and it *does* carry an `exp`
claim — so the cap is real rather than a guess. `create_access_token` therefore sets the app JWT's
`exp` to `min(now + jwt_ttl_hours, the Egeria token's own exp)`. With EA's 8-hour default the Egeria
expiry always wins, which makes the Egeria token's lifetime the session bound, and **refresh is a
re-login** — the same policy the Portal has.

Two details the implementation gets right and a reimplementation might not:

* The cap is a `min()`, not an assignment. A long-lived Egeria token must not *extend* an app
  session past its configured TTL.
* `egeria_token_expiry()` decodes the Egeria token **without verifying its signature**, deliberately:
  the RS256 key is the view server's and we do not hold it. This is not an authentication decision —
  it only bounds how long our session claims to be usable, and the token's real validity is enforced
  by Egeria on every call it is presented to. A deployment whose Egeria issues an opaque token
  simply falls back to the app TTL rather than refusing to issue a session.

### What changed in the API

| Before | After |
|---|---|
| `create_access_token(user_id, egeria_user, egeria_password, config)` | `create_access_token(user_id, egeria_token, config, role="user", display_name=None)` |
| `get_egeria_credentials(request, config) -> {user_id, password}` | `get_egeria_token(request, config) -> str \| None`; the old name raises a `RuntimeError` naming the replacement |
| — | `login_with_password(user_id, password, config) -> str \| None` |
| — | `validate_egeria_token(token, config) -> bool` |
| — | `apply_token(client, token)` — mirrors the Portal's `egeria_auth.apply_token`, so both sides build clients identically |
| — | `egeria_token_expiry(token) -> int \| None` |

`validate_egeria_credentials` stays for callers that only want a yes/no, but now delegates to
`login_with_password` — validating and then minting a session used to cost two Egeria round-trips.

**EA-side.** `advisor.auth.get_egeria_credentials(request)` keeps its name and call shape, because
about fifteen route handlers pass its result on as `egeria_credentials=`; what it returns is now
`{user_id, password: "", token}`. `password` is always empty for a signed-in user. The
service-account fallback in `resolve_egeria_credentials` is unchanged in spirit and now yields the
reverse — `password` set, `token` empty — which gives call sites a way to tell "this is the service
account" from "this is a signed-in person", a distinction the old dict could not express. The
2026-08-29 SS-4 decision (§4) is untouched: the fallback still fires only for a request with no
signed-in user at all.

### Still to do

`advisor/report_pipeline.py` (`_read_pyegeria_connection` → the `EgeriaTech` build around line 462)
and `advisor/web/app.py`'s report-preview client (~line 1318) still authenticate from
`conn["user_pwd"]`, which is now empty for a signed-in user. Each needs the same two-line change
`advisor/egeria_context.py::_make_client` already has: carry `creds["token"]` alongside the conn
dict and call `apply_token(client, token)` instead of
`create_egeria_bearer_token(user_id, user_pwd)`. Until then those two paths fall back to the
client's own configured (service-account) credentials rather than acting as the signed-in user.
