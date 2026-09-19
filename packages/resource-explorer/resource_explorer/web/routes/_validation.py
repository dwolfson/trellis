"""Shared request-body validation for resource-registration routes.

Found 2026-09-19: two registered databases (`localhost_docker_coco_ods`,
`localhost_docker_coco_pharma`) had `egeria_user` stored as `"peter profile"`
— a display name typed into the field instead of a technical Egeria login ID.
Nothing caught this at registration time, so it surfaced later as a cryptic
pyegeria `VALIDATION_ERROR_1` deep inside a publish call ("Invalid user_id -
contains a character unsafe for use in a URL path"), rather than an
immediate, actionable error naming the actual field that's wrong.
"""
from __future__ import annotations

from fastapi import HTTPException

#: pyegeria's own client rejects a user_id containing whitespace (it becomes
#: a URL path segment). Checked here too so the error surfaces at
#: registration, not three calls later inside a publish attempt.
_UNSAFE_URL_PATH_CHARS = set(" \t\n\r/?#")


def validate_egeria_user(egeria_user: str, *, field_name: str = "egeria_user") -> None:
    """Raise a 400 if `egeria_user` contains a character unsafe for a URL
    path segment. A no-op for an empty string — that means "use the
    configured default," which is valid and not this check's concern."""
    if not egeria_user:
        return
    bad_chars = sorted(set(egeria_user) & _UNSAFE_URL_PATH_CHARS)
    if bad_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field_name} {egeria_user!r} contains a character unsafe for use "
                f"in a URL path ({bad_chars!r}). This must be a technical Egeria "
                "login ID (e.g. 'erinoverview'), not a display name — leave it "
                "blank to use the configured default instead."
            ),
        )
