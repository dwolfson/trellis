"""Shared JWT auth + Portal SSO for Trellis apps.

    from trellis_auth import AuthConfig, create_access_token, get_current_user

    config = AuthConfig(jwt_secret="...", jwt_ttl_hours=8, portal_secret="...")
    token = create_access_token("dan", "dan.egeria", "hunter2", config)
    user = get_current_user(request, config)   # None if absent/invalid

Each app wraps this in a thin adapter that supplies its own resolved
`AuthConfig` and layers its own policy (does this endpoint even require
login?) on top — see `advisor/auth.py`.
"""
from trellis_auth.auth import (
    EgeriaCredentials,
    create_access_token,
    decode_token,
    exchange_portal_token,
    get_current_user,
    get_egeria_credentials,
    is_authenticated,
    require_egeria_user,
    validate_egeria_credentials,
)
from trellis_auth.config import AuthConfig

__all__ = [
    "AuthConfig",
    "EgeriaCredentials",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "require_egeria_user",
    "is_authenticated",
    "get_egeria_credentials",
    "exchange_portal_token",
    "validate_egeria_credentials",
]
