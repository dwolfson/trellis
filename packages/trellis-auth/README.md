# trellis-auth

Shared JWT auth + Portal SSO token exchange for Trellis apps.

## Why this package exists

Egeria Advisor has a real login (`advisor/auth.py`): HS256 JWTs carrying the
signed-in user's Egeria bearer token, plus Portal SSO (`exchange_portal_token`)
via a shared HS256 secret agreed with the Portal. Resource Explorer has none —
its "Connected as: erinoverview" header reads a `.env` value, not a logged-in
identity.

`exchange_portal_token` is a *contract with an external system*: a payload
shape, an algorithm, a secret, an expiry policy. Two independent
implementations of that contract will drift, and this repo has a documented
track record of exactly that happening when the same mechanism is built
twice (query cache, annotation properties, vector store, ...). See
`docs/trellis-auth-extraction.md` for the full reasoning.

## The contract: one token, two ways in

**The app JWT carries the user's Egeria *bearer token*, never their password**
(changed 2026-09-04 — see "The password contract that never matched" below).
Both ways into a Trellis app end in the same thing: a per-request pyegeria
client holding an Egeria bearer token for the actual user.

```
{sub, user_id, role, display_name, egeria_token, iat, exp}
```

That is the Portal's own payload shape, so one contract serves the direct
login and the SSO handoff alike.

## Usage

```python
from trellis_auth import (
    AuthConfig, apply_token, create_access_token, exchange_portal_token,
    get_current_user, get_egeria_token, login_with_password, validate_egeria_token,
)

config = AuthConfig(
    jwt_secret="...",
    jwt_ttl_hours=8,
    portal_secret="...",             # empty string disables Portal SSO
    egeria_view_server="qs-view-server",
    egeria_platform_url="https://localhost:9443",
)

# --- Direct login: the password is used once, here, and never stored. --------
egeria_token = login_with_password("dan.egeria", "hunter2", config)   # None on failure
token = create_access_token("dan", egeria_token, config)

# --- Portal SSO: the Portal already holds an Egeria token; re-sign it. -------
payload = exchange_portal_token(portal_token, config)   # {sub, role, display_name, egeria_token, exp}
validate_egeria_token(payload["egeria_token"], config)  # optional cheap liveness check
token = create_access_token(
    payload["sub"], payload["egeria_token"], config,
    role=payload["role"], display_name=payload["display_name"],
)

# --- Per request ------------------------------------------------------------
user = get_current_user(request, config)          # None if absent/invalid, never raises
egeria_token = get_egeria_token(request, config)  # the user's bearer token, or None

client = EgeriaTech(view_server=..., platform_url=..., user_id=...)
apply_token(client, egeria_token)   # set_bearer_token(), so Egeria records the person
```

`apply_token` mirrors the Portal's own `egeria_auth.apply_token`: with a token
it calls `set_bearer_token()`, without one it falls back to the client's own
configured credentials — which is how the legitimately service-account-backed
paths (bootstrap, outbox drain, background workers) already authenticate.

## Session expiry is bounded by Egeria's

**Egeria bearer tokens last one hour.** Measured 2026-09-04 against the running
quickstart deployment (`qs-view-server` at `https://localhost:9443`) by minting
one with pyegeria's `create_egeria_bearer_token()` and decoding it: an RS256 JWT
with `{"iss": "self", "sub": ..., "iat": ..., "exp": ...}` where `exp - iat` is
3600.

So `create_access_token` sets the app JWT's `exp` to
`min(now + jwt_ttl_hours, the Egeria token's own exp)`. A session that outlives
its Egeria token looks signed in and cannot make a single Egeria call. The cap
is a `min()`, not an assignment — a long-lived Egeria token must not extend the
session past the configured TTL. Refresh is a re-login, as it is in the Portal.

`egeria_token_expiry()` reads that `exp` **without verifying the signature**,
deliberately: the RS256 key belongs to the view server. This is not an
authentication decision, only a bound on how long the session claims to be
usable — Egeria enforces the token's real validity on every call. An opaque
(non-JWT) Egeria token simply falls back to the app TTL.

## The password contract that never matched

Until 2026-09-04 `create_access_token` signed the **raw Egeria password** into
the HS256 app JWT (a JWT is signed, not encrypted — anyone holding the session
token could base64-decode the password out of it), and `exchange_portal_token`
expected a Portal payload of `{egeria_user, egeria_password, iat, exp}`.

The Portal never issued that. `demo_auth_handler.py::_make_jwt` issues
`{sub, role, display_name, egeria_token, exp}`, where `egeria_token` is a real
Egeria bearer token, applied per request with `set_bearer_token()`. Nothing in
`egeria-workspaces` produced the password shape, so EA's
`POST /api/auth/portal` was wired to a payload that does not exist.

Both halves are fixed. A Portal token in the old shape is now rejected with a
400 that names the change, rather than a generic 401 —
`get_egeria_credentials` likewise raises a `RuntimeError` pointing at
`get_egeria_token`. Full write-up: `docs/trellis-auth-extraction.md` §6.

Apps do not use this module directly — each keeps a thin adapter over it
that supplies its own resolved `AuthConfig` and layers its own policy on
top, the same shape `trellis-querycache`/`trellis-vectorstore` use. See
`advisor/auth.py`.

## What is NOT here (deliberately)

* **Whether an app requires login at all.** EA's `_auth_enabled` /
  `_anonymous_rag_mode` decide *whether* an endpoint demands a signed-in
  user; that's each app's own answer, not this package's.
* **Config file locations.** EA reads `advisor/configdata/advisor.yaml` and
  `mcp_servers.json`; this package never reads a file or the environment —
  every function takes an `AuthConfig` the caller already resolved.
* **`resolve_egeria_credentials`'s service-account fallback.** Per the
  2026-08-29 decision, artifact ownership requires an authenticated identity
  with *no* config fallback — a shared package must not ship the fallback
  that decision exists to remove.

## Design notes

**No dependencies beyond `pyjwt` and `starlette`.** No pydantic (config is a
frozen dataclass), no loguru (stdlib `logging`). `starlette` rather than
`fastapi`: the only things needed are `Request` and `HTTPException`, both
starlette types that `fastapi`'s own re-exports subclass — a FastAPI app's
default exception handler for the starlette `HTTPException` already catches
what this package raises, so depending on `fastapi` itself would only add
its dependency surface (pydantic, etc.) for nothing this package uses.

**`pyegeria` is an optional extra (`trellis-auth[egeria]`)**, imported
lazily inside `login_with_password`, `validate_egeria_token` and
`validate_egeria_credentials`. A missing install is caught by the same broad
`except Exception` that already handles "Egeria is unreachable", so a consumer
that never calls those doesn't pay for the install. `apply_token` needs no
import at all — it only calls methods on a client the caller built.

**`validate_egeria_credentials`'s service-account fallback is not the
excluded one.** When `AuthConfig.egeria_view_server`/`egeria_platform_url`
aren't set, it compares against `egeria_service_account_user/password`
instead of attempting a live call — that's a sanity check for a
misconfigured deployment's login form, not the per-request credential
*resolution* fallback `resolve_egeria_credentials` uses, which stays out of
this package entirely.
