"""Configuration for the shared auth package.

A plain frozen dataclass, deliberately: this package never reads the
environment or any config file. Each app resolves its own settings (EA's
`advisor/configdata/advisor.yaml` + `ADVISOR_JWT_SECRET`/`ADVISOR_PORTAL_SECRET`
env vars, RE's own config) into one of these and hands it over — the same
split `trellis-querycache` and `trellis-vectorstore` use for their configs.

Deliberately NOT here: whether an app requires login at all, and where its
config files live. Those are policy/location decisions each app makes for
itself (see `docs/trellis-auth-extraction.md` §4) — this dataclass only
carries the mechanism's inputs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthConfig:
    """How JWTs are signed/verified, and how Egeria credentials are checked.

    `jwt_secret` and `portal_secret` are independent: `jwt_secret` signs the
    tokens this app issues to its own users, `portal_secret` verifies
    short-lived tokens a Portal issues under a *shared* secret agreed with
    that Portal. Leave `portal_secret` empty if this app doesn't accept
    Portal SSO — `exchange_portal_token` reports that as 503, not a crash.

    The `egeria_*` fields are only needed by `validate_egeria_credentials`;
    leave them empty if a consumer never calls that function.
    """

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_ttl_hours: int = 8
    portal_secret: str = ""

    egeria_view_server: str = ""
    egeria_platform_url: str = ""
    # Service-account credentials used ONLY as a sanity check inside
    # validate_egeria_credentials() when the Egeria connection itself isn't
    # configured (see that function's docstring). This is NOT the
    # resolve_egeria_credentials() service-account fallback that
    # docs/trellis-auth-extraction.md §4 deliberately excludes from this
    # package — that fallback resolves *which identity a live call runs as*
    # and stays app-specific; these two fields only let a misconfigured
    # deployment's login form be checked against something.
    egeria_service_account_user: str = ""
    egeria_service_account_password: str = ""

    def __post_init__(self) -> None:
        if not self.jwt_secret:
            raise ValueError("jwt_secret must be non-empty")
        if self.jwt_ttl_hours <= 0:
            raise ValueError(f"jwt_ttl_hours must be > 0, got {self.jwt_ttl_hours}")
