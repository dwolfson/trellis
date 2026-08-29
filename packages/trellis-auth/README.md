# trellis-auth

Shared JWT auth + Portal SSO token exchange for Trellis apps.

## Why this package exists

Egeria Advisor has a real login (`advisor/auth.py`): HS256 JWTs carrying the
signed-in user's Egeria credentials, plus Portal SSO (`exchange_portal_token`)
via a shared HS256 secret agreed with the Portal. Resource Explorer has none —
its "Connected as: erinoverview" header reads a `.env` value, not a logged-in
identity.

`exchange_portal_token` is a *contract with an external system*: a payload
shape, an algorithm, a secret, an expiry policy. Two independent
implementations of that contract will drift, and this repo has a documented
track record of exactly that happening when the same mechanism is built
twice (query cache, annotation properties, vector store, ...). See
`docs/trellis-auth-extraction.md` for the full reasoning.

## Usage

```python
from trellis_auth import AuthConfig, create_access_token, get_current_user

config = AuthConfig(
    jwt_secret="...",
    jwt_ttl_hours=8,
    portal_secret="...",             # empty string disables Portal SSO
    egeria_view_server="qs-view-server",
    egeria_platform_url="https://localhost:9443",
)

token = create_access_token("dan", "dan.egeria", "hunter2", config)
user = get_current_user(request, config)   # None if absent/invalid, never raises
creds = get_egeria_credentials(request, config)  # {"user_id", "password"} or None
```

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
lazily inside `validate_egeria_credentials`. A missing install is caught by
the same broad `except Exception` that already handles "Egeria is
unreachable", so a consumer that never calls that function doesn't pay for
the install.

**`validate_egeria_credentials`'s service-account fallback is not the
excluded one.** When `AuthConfig.egeria_view_server`/`egeria_platform_url`
aren't set, it compares against `egeria_service_account_user/password`
instead of attempting a live call — that's a sanity check for a
misconfigured deployment's login form, not the per-request credential
*resolution* fallback `resolve_egeria_credentials` uses, which stays out of
this package entirely.
