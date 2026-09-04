"""Shared JWT auth + Portal SSO for Trellis apps.

    from trellis_auth import AuthConfig, create_access_token, get_current_user

    config = AuthConfig(jwt_secret="...", jwt_ttl_hours=8, portal_secret="...")
    egeria_token = login_with_password("dan.egeria", "hunter2", config)
    token = create_access_token("dan", egeria_token, config)
    user = get_current_user(request, config)   # None if absent/invalid

The app JWT carries the user's Egeria *bearer token*, never a password
(contract change 2026-09-04 — see `auth.py`'s module docstring and
`docs/runtime-architecture-plan.md` §4).

Each app wraps this in a thin adapter that supplies its own resolved
`AuthConfig` and layers its own policy (does this endpoint even require
login?) on top — see `advisor/auth.py`.
"""
from trellis_auth.auth import (
    EGERIA_TOKEN_TTL_SECONDS_OBSERVED,
    apply_token,
    create_access_token,
    decode_token,
    egeria_token_expiry,
    exchange_portal_token,
    get_current_user,
    get_egeria_credentials,
    get_egeria_token,
    is_authenticated,
    login_with_password,
    require_egeria_user,
    validate_egeria_credentials,
    validate_egeria_token,
)
from trellis_auth.config import AuthConfig

__all__ = [
    "AuthConfig",
    "EGERIA_TOKEN_TTL_SECONDS_OBSERVED",
    "apply_token",
    "create_access_token",
    "decode_token",
    "egeria_token_expiry",
    "exchange_portal_token",
    "get_current_user",
    "get_egeria_credentials",
    "get_egeria_token",
    "is_authenticated",
    "login_with_password",
    "require_egeria_user",
    "validate_egeria_credentials",
    "validate_egeria_token",
]
