"""The CLI's side of the cached login.

`egeria-advisor login` exchanges an Egeria password for a bearer token once,
wraps it in this app's own session JWT and caches that under
`$XDG_CONFIG_HOME/trellis/egeria-advisor/session.json` (mode 0600). Every later
command reads it back, so the CLI runs as the signed-in person rather than as
the `.env` service account — which is what makes Egeria's own provenance record
who did it (`docs/runtime-architecture-plan.md` §4, "Attribution").

The file format, the location and the expiry check all live in
`trellis_auth.session_file`, shared verbatim with Resource Explorer. What is
EA-specific and therefore here: the app name, minting the app JWT from EA's own
`AuthConfig`, and the two ways a command can ask for the session —

  * `resolve_identity(explicit_user)` — best effort. Returns whoever we can
    name, for namespacing drafts and documents. A question answered out of the
    local corpus needs no Egeria and must not be blocked by a lapsed session.
  * `require_egeria_credentials()` — hard requirement. Prints exactly one line
    and exits 2 when there is no live session, for commands that will make a
    live Egeria call and would otherwise fail deep inside pyegeria with a
    stack trace that names none of this.

Exit code 2 rather than 1, deliberately: 1 is "the command ran and failed", 2
is "you are not signed in", and a script wrapping the CLI can tell them apart
without parsing the message.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional, Tuple

from trellis_auth import session_file
from trellis_auth.session_file import SessionRecord

#: The directory name under `$XDG_CONFIG_HOME/trellis/`. Matches the console
#: script name, so `ls ~/.config/trellis` reads as a list of commands.
APP_NAME = "egeria-advisor"

LOGIN_COMMAND = "egeria-advisor login"

#: Exit status for "no live session" — see the module docstring.
EXIT_NOT_SIGNED_IN = 2

__all__ = [
    "APP_NAME",
    "LOGIN_COMMAND",
    "EXIT_NOT_SIGNED_IN",
    "load_session",
    "save_login",
    "clear_session",
    "resolve_identity",
    "require_egeria_credentials",
    "session_status_line",
]


def load_session() -> Optional[SessionRecord]:
    """The cached session, expired or not (check `.is_expired`)."""
    return session_file.load_session(APP_NAME)


def clear_session() -> bool:
    """Forget the cached session. True if there was one."""
    return session_file.clear_session(APP_NAME)


def save_login(user_id: str, egeria_token: str) -> SessionRecord:
    """Mint EA's session JWT around `egeria_token` and cache it.

    The Egeria token is wrapped rather than stored bare so the cached artifact
    is exactly what the web app's `Authorization: Bearer` header carries — one
    format, one expiry, and a CLI session that can be handed to the local
    server (which is how the live check in this change's own verification
    works).
    """
    from advisor.auth import create_access_token

    app_jwt = create_access_token(user_id=user_id, egeria_token=egeria_token)
    return session_file.save_session(APP_NAME, user_id, app_jwt)


def _live_session() -> Optional[SessionRecord]:
    record = load_session()
    if record is None or record.is_expired:
        return None
    return record


def _credentials_from(record: SessionRecord) -> Dict[str, Any]:
    """An `advisor.auth.EgeriaCredentials` dict for a live cached session.

    `password` is empty and `token` is set — the same shape a signed-in web
    request produces, so every `egeria_credentials=` call site behaves
    identically whether it was reached from the browser or from here. The
    Egeria bearer token is read back out of the app JWT rather than stored
    separately; `decode_token` verifies our own signature on the way.
    """
    from advisor.auth import decode_token

    claims = decode_token(record.token)
    return {
        "user_id": claims.get("user_id") or claims.get("sub") or record.user_id,
        "password": "",
        "token": claims.get("egeria_token", ""),
    }


def resolve_identity(explicit_user: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """`(user_id, egeria_credentials)` for this invocation — never fails.

    `--user` still wins for the *namespace*, because it always could and
    scripts depend on it; it does not conjure credentials, so a `--user` that
    disagrees with the cached login gets that user's namespace and the cached
    user's Egeria token. That combination is legitimate (curating someone
    else's drafts) and Egeria still records who really made the call.

    Returns `(None, None)` when nothing is signed in, which is the pre-existing
    anonymous behaviour: shared namespace, service-account fallback for any
    live call. A lapsed session is reported by the caller that actually needs
    one, not here.
    """
    record = _live_session()
    if record is None:
        return explicit_user, None
    creds = _credentials_from(record)
    return explicit_user or creds["user_id"], creds


def require_egeria_credentials(console=None) -> Dict[str, Any]:
    """Credentials for a command that must talk to Egeria, or exit 2.

    Prints **exactly one line** — no traceback, no banner, no second "try
    again" sentence. The line always names the command that fixes it.
    """
    record = load_session()
    if record is not None and not record.is_expired:
        return _credentials_from(record)
    message = session_file.expired_message(record, LOGIN_COMMAND)
    if console is not None:
        console.print(f"[red]{message}[/red]")
    else:  # pragma: no cover - every CLI caller passes a console
        print(message, file=sys.stderr)
    sys.exit(EXIT_NOT_SIGNED_IN)


def session_status_line() -> str:
    """One line describing the cached session, for `login`/`logout` output."""
    record = load_session()
    if record is None:
        return f"not signed in — run `{LOGIN_COMMAND}`"
    if record.is_expired:
        return session_file.expired_message(record, LOGIN_COMMAND)
    if record.expires_at_local is None:
        return f"signed in as {record.user_id}"
    return f"signed in as {record.user_id} until {record.expires_at_local:%H:%M}"
