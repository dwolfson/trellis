"""A queued run publishes AS the person who pressed it (architect ruling, option a, 2026-10-21).

The evidence: a synchronous press wrote to Egeria as the person (`createdBy = peterprofile`), but the same press
queued (`run_queue` -> the survey definition executor's auto-publish) wrote the SurveyReport and its annotations as the
service account (`createdBy = resourceexplorernpa`). That breaks the owner rule "run as the initiating user; service
account only when automated with no known user".

What this module holds
----------------------
The presser's own Egeria bearer token, **in this process's memory only**, keyed by the run's id, from the press until
the run ends. It is the same posture as `preview_credential_holder` (a per-sign-in secret kept in memory, nowhere
else): nothing here is written to the registry, a run row, the activity log, a log line, an exception message or
Egeria. `HeldSession.__repr__` hides the token and the holder has no listing and no iteration. The one reader is
`publishing_as_presser`, below.

* **Where held:** `hold()` is called by the press route (`web/routes/survey_definitions.py`) with the token the request
  carries, BEFORE the run row is enqueued (the run id is made first), so a worker in the same process can never claim
  a row whose token is not there yet.
* **Lifetime:** released when the run ends (`execute_run`'s `finally`), at the token's own `exp`, or at the cap
  (`RE_PRESSER_HOLD_TTL_SECONDS`, default 2 hours, never unbounded), whichever is first; and at process exit.
* **Cross-process:** a run claimed by another process (a separate worker, a restart) finds nothing held. That is the
  safe direction to fail in: the run ends "published: no · your sign-in expired · press Publish on the card" and
  writes nothing as the service account.

What it changes
---------------
Only the run's **publish** (`publishing_as_presser`, wrapped around the executor's `publish_fn` call). The run's
measuring, reads and step execution stay `Daemon(RUN_QUEUE, requested_by)`: a token that ages out mid-run must not
turn a measurement into a failure, and reading as the service account is not the attribution the owner asked about.
A run is "pressed" only when its params say so (`publish_as_presser`, set by the press route). A scheduled run, an
Egeria-dispatched one or a batch with no person is not, and keeps the service account.
"""
from __future__ import annotations

import atexit
import math
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator

DEFAULT_TTL_SECONDS = 2 * 3600
TTL_ENV = "RE_PRESSER_HOLD_TTL_SECONDS"

#: The run's publish word when the presser's session is not there to publish with. Fixed vocabulary: it starts
#: "published: no", which the card draws as a warning with these words, never as a published run.
SIGN_IN_EXPIRED_WORDS = "published: no · your sign-in expired · press Publish on the card"


class PresserSignInExpired(Exception):
    """The pressed run reached its publish and the presser's Egeria session is gone (expired, never held in this
    process, or released). Nothing was written. `str(exc)` is the run's publish word."""

    def __init__(self, words: str = SIGN_IN_EXPIRED_WORDS) -> None:
        super().__init__(words)


def configured_ttl() -> float:
    raw = (os.environ.get(TTL_ENV) or "").strip()
    if not raw:
        return float(DEFAULT_TTL_SECONDS)
    try:
        value = float(raw)
    except ValueError:
        return float(DEFAULT_TTL_SECONDS)
    if not math.isfinite(value) or value <= 0:
        return float(DEFAULT_TTL_SECONDS)
    return value


@dataclass(frozen=True)
class HeldSession:
    """One held session. `token` is excluded from every generated text form."""

    person: str
    token: str = field(repr=False)
    expires_at: float = 0.0

    def __repr__(self) -> str:                  # never the token, in any spelling
        return f"HeldSession(person={self.person!r}, token=<hidden>)"

    __str__ = __repr__


class _Holder:
    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, HeldSession] = {}

    def __repr__(self) -> str:
        with self._lock:
            return f"<presser hold: {len(self._entries)} held>"

    def put(self, run_id: str, person: str, token: str, *, not_after: float | None = None,
            ttl: float | None = None) -> None:
        expires = self._clock() + (configured_ttl() if ttl is None else ttl)
        if not_after is not None:
            expires = min(expires, float(not_after))
        with self._lock:
            now = self._clock()
            for key in [k for k, v in self._entries.items() if v.expires_at <= now]:
                del self._entries[key]
            self._entries[run_id] = HeldSession(person=person, token=token, expires_at=expires)

    def take(self, run_id: str) -> HeldSession | None:
        """The held session, or None. An entry past its expiry is dropped here and never returned."""
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                return None
            if entry.expires_at <= self._clock():
                del self._entries[run_id]
                return None
            return entry

    def release(self, run_id: str) -> None:
        with self._lock:
            self._entries.pop(run_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._entries.clear()


_HOLDER = _Holder()
atexit.register(_HOLDER.clear_all)

take = _HOLDER.take
release = _HOLDER.release
clear_all = _HOLDER.clear_all


def hold(run_id: str, person: str, token: str | None) -> bool:
    """Keep the presser's session for `run_id`. False (nothing held) when there is no run id, person or token.

    The hold ends at the token's own expiry when it states one, so a held session is never offered past it."""
    if not (run_id and person and token):
        return False
    not_after = None
    try:
        from trellis_auth.auth import egeria_token_expiry

        exp = egeria_token_expiry(token)
        not_after = float(exp) if exp is not None else None
    except Exception:  # noqa: BLE001 - an unreadable expiry is simply not a tighter bound
        not_after = None
    _HOLDER.put(run_id, person, token, not_after=not_after)
    return True


#: (run id, person) of the pressed run this context is executing; None everywhere else.
_PRESSED: ContextVar["tuple[str, str] | None"] = ContextVar("re_pressed_run", default=None)


@contextmanager
def pressed_run(run_id: str, person: str) -> Iterator[None]:
    """Mark the code in this block as executing the run `run_id` that `person` pressed."""
    reset = _PRESSED.set((run_id, person))
    try:
        yield
    finally:
        _PRESSED.reset(reset)


def is_pressed() -> bool:
    return _PRESSED.get() is not None


@contextmanager
def publishing_as_presser() -> Iterator[None]:
    """Wrap a pressed run's Egeria WRITE: inside, `current_principal()` is the presser (their held token).

    Outside a pressed run it does nothing, so every other run keeps the identity it had. In a pressed run with no
    usable held session it raises `PresserSignInExpired` BEFORE the block runs: nothing is written, and never as the
    service account."""
    pressed = _PRESSED.get()
    if pressed is None:
        yield
        return
    run_id, person = pressed
    held = take(run_id)
    if held is None or held.person != person or not _token_alive(held.token):
        raise PresserSignInExpired()
    from resource_explorer.egeria_clients import acting_as_held_caller

    with acting_as_held_caller(held.person, held.token):
        yield


def _token_alive(token: str) -> bool:
    try:
        from trellis_auth.auth import egeria_token_expiry

        exp = egeria_token_expiry(token)
    except Exception:  # noqa: BLE001 - unreadable: let Egeria answer; it refuses an expired token itself
        return True
    return exp is None or exp > time.time()


# ---------------------------------------------------------------------------
# Proof on screen: who the report says created it
# ---------------------------------------------------------------------------

def created_by_of(report: object) -> str:
    """`versions.createdBy` from an Egeria element read (on `elementHeader`, else the element); '' when it states none.

    Pure. '' is "Egeria stated no creator in what was read", never a guess."""
    if not isinstance(report, dict):
        return ""
    header = report.get("elementHeader") if isinstance(report.get("elementHeader"), dict) else {}
    for versions in ((header or {}).get("versions"), report.get("versions")):
        if isinstance(versions, dict) and versions.get("createdBy"):
            return str(versions["createdBy"])
    return ""


def read_published_by(report_guid: str) -> str:
    """Who Egeria says created the SurveyReport `report_guid`: ONE read by GUID, as whoever the run is acting as.

    The run's "published as <identity>" comes from this read and from nothing the code path believes about itself, so a
    regression to the service account shows on the card. '' when the read could not be made or Egeria stated no
    creator: the caller says nothing, which is "could not tell", not "as nobody"."""
    if not report_guid:
        return ""
    try:
        from pyegeria import AssetMaker

        from resource_explorer.config import egeria_platform_url, egeria_view_server
        from resource_explorer.egeria_clients import current_principal, egeria_client

        maker = egeria_client(current_principal(), purpose="publish read-back",
                              view_server=egeria_view_server(), platform_url=egeria_platform_url()).of(AssetMaker)
        result = maker.get_asset_by_guid(
            report_guid, body={"class": "GetRequestBody", "graphQueryDepth": 0}, output_format="JSON")
    except Exception:  # noqa: BLE001 - unread is "could not tell"; the message may carry a token, so it is not kept
        return ""
    return created_by_of(result)
