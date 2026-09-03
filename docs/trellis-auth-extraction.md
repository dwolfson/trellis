# Trellis-level login — where it should live, and what it costs

**Status:** design note, 2026-08-29. Nothing built. Prompted by the project owner: *"If RE doesn't have a login,
it should — we could do this at the Trellis level or in each of EA and RE."*

**Recommendation: the Trellis level, as `trellis-auth`, with EA's implementation as the base and RE
adopting it.** Reasoning below, including the part that argues against a shared package.

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
(`egeria_user`, `egeria_password`, `iat`, `exp`), an algorithm, a secret, and an expiry policy. Two
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
`is_authenticated`, `EgeriaCredentials`, `get_egeria_credentials`, `exchange_portal_token`,
`validate_egeria_credentials`.

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
