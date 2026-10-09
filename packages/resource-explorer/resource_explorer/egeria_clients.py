"""The one place RE builds a pyegeria client, and decides who it acts as.

Brief I (owner, 2026-10-09): "There should be a common factory routine to generate Egeria Client
objects that is passed around". Every pyegeria client in RE comes from `egeria_client()`; a test
(`tests/test_egeria_client_factory_ban.py`) fails on any other construction or token mint.

The rule (owner, 2026-10-09 scope update): a person's direct actions run as that person;
daemon-like or governance-action work runs under a named RE daemon identity, with the requester
recorded. Who a client acts as is always named, never defaulted:

* `Caller()` — the signed-in person, from `a2a_auth.current_caller`. Their Egeria bearer token
  (from the app JWT) is set on every
  sub-client, so Egeria's own provenance names them. With no caller it raises
  `NoCallerIdentity`; it NEVER falls back to the daemon. A token past its `exp` raises
  `CallerTokenExpired`, which the web app maps to 401 with `EXPIRED_SENTENCE`.
  **No refresh for a caller:** pyegeria's refresh re-mints from a password, and RE holds no
  caller password (the login exchange keeps only the token). Adding one is out of scope.
* `Daemon(reason, requested_by=None)` — RE's daemon identity, for a named job only. `reason` is a
  `DaemonReason`, a closed enum, so a new use is added on purpose. With `requested_by` the
  identity's `user_id` is the requester (what `Ownership` is stamped with) while the client is
  built for the daemon. Refreshable: the factory re-mints from the daemon credential when the
  shared token nears its `exp`. The credential comes from ONE function, `_daemon_credential()`
  (today `config.egeria`; it may move to the secrets store later).

Ambient identity. A web request needs nothing: `current_principal()` is `Caller()`. A daemon job
declares itself once at its entry with `acting_as(Daemon(...))`, and code below it asks
`current_principal()`. A bare `threading.Thread` drops ContextVars, so a thread body
re-declares (or receives) its identity explicitly.

One client per identity per scope. Inside a `client_scope()` (every web request, every
`acting_as` block) `egeria_client()` returns the same `EgeriaClients` for the same identity, so
sub-clients share one token.
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from enum import Enum
from typing import Any, Iterator, Optional

from resource_explorer.egeria_identity import EgeriaIdentity

log = logging.getLogger(__name__)

__all__ = [
    "Caller",
    "CallerTokenExpired",
    "Daemon",
    "DaemonReason",
    "EXPIRED_SENTENCE",
    "EgeriaClients",
    "EgeriaRefused",
    "NoCallerIdentity",
    "PlatformNotAllowed",
    "StoredOrDaemon",
    "acting_as",
    "client_scope",
    "current_principal",
    "egeria_client",
    "last_egeria_identity",
    "refusal",
]

KIND_CALLER = "caller"
KIND_DAEMON = "daemon"
KIND_STORED = "stored"
_KINDS = (KIND_CALLER, KIND_DAEMON, KIND_STORED)

EXPIRED_SENTENCE = "your Egeria sign-in expired; sign in again"
NO_CALLER_SENTENCE = "no one is signed in, so RE will not call Egeria; sign in again"

#: Seconds before a daemon token's `exp` at which the factory re-mints it.
_DAEMON_REFRESH_MARGIN = 120


class NoCallerIdentity(PermissionError):
    """An Egeria call that must run as a person found no signed-in person. Maps to 401."""

    status_code = 401

    def __init__(self, message: str = NO_CALLER_SENTENCE) -> None:
        super().__init__(message)


class CallerTokenExpired(PermissionError):
    """The signed-in person's Egeria token is past its expiry. Maps to 401 with EXPIRED_SENTENCE."""

    status_code = 401

    def __init__(self, message: str = EXPIRED_SENTENCE) -> None:
        super().__init__(message)


class PlatformNotAllowed(PermissionError):
    """A credential would go to an Egeria platform RE is not configured for. Nothing is sent.
    Maps to 403 with the sentence."""

    status_code = 403

    def __init__(self, origin: str) -> None:
        super().__init__(f"this resource names an Egeria platform RE is not configured for: {origin}")
        self.origin = origin


class EgeriaRefused(PermissionError):
    """Egeria's security refused the identity that made the call. A route raises it (from the
    pyegeria error) so the page shows "refused by Egeria" with Egeria's sentence; it is never
    retried as anyone else. Maps to 403."""

    status_code = 403


def refusal(exc: BaseException) -> Optional["EgeriaRefused"]:
    """`EgeriaRefused` carrying Egeria's sentence when `exc` is an Egeria security refusal, else None."""
    from resource_explorer.egeria_outbox import _refusal_sentence, is_security_refusal

    if isinstance(exc, Exception) and is_security_refusal(exc):
        return EgeriaRefused(_refusal_sentence(exc))
    return None


class DaemonReason(str, Enum):
    """The closed list of jobs that may act as RE's daemon identity. Add a member on purpose."""

    BOOTSTRAP = "bootstrap"            # bootstrap heal, its canary reads and post-heal checks
    RESYNC = "egeria_resync"           # the Egeria resync loop and its heals
    SCHEDULER = "scheduler"            # scheduled surveys, the native-survey sweep, RFA reconcile
    OUTBOX = "outbox_drain"            # the outbox drain
    RUN_QUEUE = "run_queue"            # queued surveys and analyses (requester recorded)
    REACHABILITY = "reachability"      # file-system reachability checks
    ZONE_SETUP = "zone_setup"          # draft/private zone and security-officer bootstrap
    STARTUP_WARM = "startup_warm"      # the worker's one-shot cache warm at start
    PREFECT_FLOW = "prefect_flow"      # a survey flow run in a Prefect worker process (no caller there)


# ---------------------------------------------------------------------------
# The identities
# ---------------------------------------------------------------------------

def _token_expiry(token: str) -> Optional[int]:
    from trellis_auth.auth import egeria_token_expiry

    return egeria_token_expiry(token)


def Caller() -> EgeriaIdentity:  # noqa: N802 - named as the brief names it
    """The signed-in person. Raises `NoCallerIdentity` / `CallerTokenExpired`; never the daemon."""
    from resource_explorer.egeria_identity import current_identity

    identity = current_identity()
    if identity is None or not identity.token:
        raise NoCallerIdentity()
    exp = _token_expiry(identity.token)
    if exp is not None and exp <= time.time():
        raise CallerTokenExpired()
    return replace(identity, kind=KIND_CALLER, is_service_account=False)


def _daemon_credential() -> tuple[str, str]:
    """THE one place RE's daemon credential is loaded. Today: the configured service account
    (`config.egeria`, unchanged). Kept a single small function so the loading can move (e.g. to
    the secrets store) without touching any caller.

    The daemon exists in Egeria as userId `resourceexplorernpa` (ITProfile
    `ITProfile::ResourceExplorer`); deployments set EGERIA_USER_ID to it.

    TODO(Brief I, follow-up after merge): Egeria daemons hold their identity in an omsecrets
    `tokenAPI` collection, here named "Resource Explorer" (with a space) —
    `secretsCollections: {"Resource Explorer": {tokenAPI: {httpRequestType:
    POST, url: <platform>/api/token, requestBody: {userId, password}}}}` — read through
    `omsecrets_store._load`. Switch this function to that when the owner decides; nothing else."""
    from resource_explorer.config import get_config

    egeria = get_config().egeria
    return egeria.user_id, egeria.user_password


def Daemon(reason: DaemonReason, requested_by: Optional[str] = None) -> EgeriaIdentity:  # noqa: N802
    """RE's daemon identity for one named job; `requested_by` recorded as the Ownership owner.

    A reason outside `DaemonReason` is refused. This is also the seam where a later decision
    about queued work plugs in (encrypted credential, longer token, Egeria delegation).
    """
    if not isinstance(reason, DaemonReason):
        raise ValueError(
            f"Daemon identity refused: {reason!r} is not a DaemonReason. A new daemon use is "
            "added to DaemonReason on purpose, never passed as a free string.")
    user, password = _daemon_credential()
    requester = (requested_by or "").strip()
    return EgeriaIdentity(user_id=requester or user, password=password, is_service_account=True,
                          kind=KIND_DAEMON, reason=reason.value, client_user=user,
                          requested_by=requester)


def StoredOrDaemon(entity: Any, reason: DaemonReason) -> EgeriaIdentity:  # noqa: N802
    """KEPT, pending the owner's decision (Brief I: "ask before removing"): the Egeria user and
    password a database server / database / file system row carries (`egeria_user`,
    `egeria_password`, typed into the registration dialogs; plaintext, unlike `db_password`).

    Used only where those credentials were used before this change AND no person is behind the
    call: the outbox drain's doc-source and catalogue-schema rows. Interactive routes use
    `Caller()` and ignore them. An entity without both falls back to `Daemon(reason)` — named,
    not silent: the drain is a daemon job either way.
    """
    if not isinstance(reason, DaemonReason):
        raise ValueError(f"StoredOrDaemon refused: {reason!r} is not a DaemonReason")
    user = (getattr(entity, "egeria_user", "") or "").strip()
    password = getattr(entity, "egeria_password", "") or ""
    if not (user and password):
        return Daemon(reason)
    # A stored credential is bound to its OWN entity's platform (the configured one when the
    # entity names none); the factory refuses to send it anywhere else, or to a platform that is
    # not allowed at all.
    bound = origin_of(getattr(entity, "egeria_url", "") or _configured_platform())
    return EgeriaIdentity(user_id=user, password=password, is_service_account=True,
                          kind=KIND_STORED, reason=reason.value, client_user=user,
                          bound_platform=bound)


# ---------------------------------------------------------------------------
# Where a credential may go
# ---------------------------------------------------------------------------

def origin_of(url: str) -> str:
    """`scheme://host:port`, lower-cased, with the scheme's default port made explicit."""
    from urllib.parse import urlsplit

    u = urlsplit((url or "").strip())
    scheme = (u.scheme or "").lower()
    host = (u.hostname or "").lower()
    if not scheme or not host:
        return (url or "").strip().lower()
    port = u.port or {"https": 443, "http": 80}.get(scheme, 0)
    return f"{scheme}://{host}:{port}"


def _configured_platform() -> str:
    from resource_explorer.config import get_config

    return get_config().egeria.platform_url


def allowed_platforms() -> frozenset[str]:
    """The origins a Caller, Daemon or stored credential may be sent to: the configured
    `EGERIA_PLATFORM_URL`, plus any in `EGERIA_ALLOWED_PLATFORM_URLS` (comma separated)."""
    from resource_explorer.config import get_config

    egeria = get_config().egeria
    configured = getattr(egeria, "platform_url", "")
    listed = getattr(egeria, "allowed_platform_urls", "")
    extra = [u for u in (listed.split(",") if isinstance(listed, str) else []) if u.strip()]
    return frozenset(origin_of(u) for u in [configured, *extra] if isinstance(u, str) and u.strip())


def _check_platform(identity: EgeriaIdentity, platform_url: str) -> None:
    origin = origin_of(platform_url)
    if origin not in allowed_platforms():
        raise PlatformNotAllowed(origin)
    if identity.kind == KIND_STORED and identity.bound_platform and origin != identity.bound_platform:
        raise PlatformNotAllowed(origin)


def _client_user(identity: EgeriaIdentity) -> str:
    """The Egeria user a client is built for: the person, or the daemon it mints as."""
    return identity.client_user or identity.user_id


# ---------------------------------------------------------------------------
# Ambient identity and the per-scope client cache
# ---------------------------------------------------------------------------

_acting: contextvars.ContextVar[Optional[EgeriaIdentity]] = contextvars.ContextVar(
    "re_egeria_acting_as", default=None)
_scope: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "re_egeria_client_scope", default=None)
_scope_lock = threading.Lock()


@contextmanager
def client_scope() -> Iterator[None]:
    """One `EgeriaClients` per identity inside this block (a request, a job pass)."""
    reset = _scope.set({})
    try:
        yield
    finally:
        _scope.reset(reset)


@contextmanager
def acting_as(identity: EgeriaIdentity) -> Iterator[EgeriaIdentity]:
    """Declare who the code in this block acts as — a system job's or a queued run's entry point.

    Only a Daemon is accepted: a person is published by the web/A2A middleware or
    the CLI's `use_identity`, never declared here. Opens its own client scope.
    """
    if identity is None or identity.kind != KIND_DAEMON:
        raise ValueError("acting_as takes Daemon(reason, requested_by=None)")
    reset = _acting.set(identity)
    try:
        with client_scope():
            yield identity
    finally:
        _acting.reset(reset)


#: Set in a Prefect WORKER's flow-run process (Prefect's process worker exports it for every
#: flow run it starts); never set by RE's own in-process flows, which run in RE's context.
PREFECT_WORKER_MARKER = "PREFECT__FLOW_RUN_ID"


def in_prefect_worker_process() -> bool:
    import os

    return bool((os.environ.get(PREFECT_WORKER_MARKER) or "").strip())


def daemon_entry(reason: DaemonReason):
    """Decorator for a Prefect flow entry point. In a Prefect WORKER process (the explicit marker,
    `PREFECT__FLOW_RUN_ID`) there is no person, and the flow is declared `Daemon(reason)`.
    Anywhere else the call keeps whatever identity it carries — and with none, the first Egeria
    call raises `NoCallerIdentity`. A missing caller is never turned into the daemon."""
    import functools

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            from resource_explorer.egeria_identity import current_identity

            if in_prefect_worker_process() and _acting.get() is None and current_identity() is None:
                with acting_as(Daemon(reason)):
                    return fn(*args, **kwargs)
            return fn(*args, **kwargs)
        return inner
    return wrap


def current_principal() -> EgeriaIdentity:
    """Who an Egeria call here acts as: the declared Daemon job, else the signed-in Caller.

    Raises `NoCallerIdentity` when neither is present — never the service account by default.
    """
    declared = _acting.get()
    if declared is not None:
        return declared
    return Caller()


# ---------------------------------------------------------------------------
# What the last call used (the connection popover's recorded value)
# ---------------------------------------------------------------------------

_last_lock = threading.Lock()
_last_by_user: dict[str, dict] = {}


def _person_in_request() -> str:
    from resource_explorer.egeria_identity import current_identity

    person = current_identity()
    return person.user_id if person is not None and person.token else ""


def _record(identity: EgeriaIdentity, purpose: str) -> None:
    if identity.kind == KIND_CALLER:
        key, as_words = identity.user_id, "you"
    elif identity.kind == KIND_DAEMON and identity.requested_by:
        # Queued work for a person (owner's wording, 2026-10-09).
        key, as_words = identity.requested_by, "service account (Resource Explorer) on your behalf"
    elif identity.kind == KIND_DAEMON and _person_in_request():
        # A daemon call made inside a person's request (e.g. reachability): theirs to see.
        key, as_words = _person_in_request(), "service account (background)"
    elif identity.kind == KIND_STORED:
        key, as_words = "", "stored resource credential"
    else:
        key, as_words = "", "service account (daemon)"
    entry = {"as": as_words, "kind": identity.kind, "purpose": purpose,
             "reason": identity.reason if identity.kind != KIND_CALLER else "",
             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with _last_lock:
        _last_by_user[key] = entry


def last_egeria_identity(user_id: str) -> Optional[dict]:
    """What this process recorded for `user_id`'s most recent Egeria client, or None (not recorded)."""
    if not user_id:
        return None
    with _last_lock:
        entry = _last_by_user.get(user_id)
        return dict(entry) if entry else None


# ---------------------------------------------------------------------------
# The clients
# ---------------------------------------------------------------------------

def _build(cls: Any, view_server: str, platform_url: str, user_id: str, password: str) -> Any:
    """The one constructor call. (Tests guard it so no real client can reach a platform.)"""
    return cls(view_server, platform_url, user_id, password)


class EgeriaClients:
    """pyegeria sub-clients for ONE identity, created lazily, sharing one token (EgeriaTech's shape).

    `of(cls)` returns the sub-client of pyegeria class `cls`, built and authenticated here and
    nowhere else. `server` overrides the view server (the catalogue gateway's ServerOps talks to
    the integration daemon).
    """

    def __init__(self, identity: EgeriaIdentity, *, purpose: str,
                 view_server: Optional[str] = None, platform_url: Optional[str] = None) -> None:
        from resource_explorer.config import get_config

        egeria = get_config().egeria
        self.identity = identity
        self.purpose = purpose
        self.view_server = view_server or egeria.view_server
        self.platform_url = platform_url or egeria.platform_url
        # Before anything is built or sent: a credential goes only to an allowed platform.
        _check_platform(identity, self.platform_url)
        self.user_id = _client_user(identity)
        self._clients: dict[tuple, Any] = {}
        self._token: Optional[str] = identity.token if identity.is_person else None
        self._lock = threading.Lock()

    @property
    def acting_as(self) -> str:
        return self.user_id

    def _password(self) -> str:
        return "" if self.identity.is_person else (self.identity.password or "")

    def _mint(self, client: Any) -> None:
        """Daemon/stored only: mint (or reuse) the shared token for `client`."""
        if self._token and not self._daemon_token_due():
            client.set_bearer_token(self._token)
            return
        token = client.create_egeria_bearer_token()
        if isinstance(token, str) and token and token != "FAILED":
            self._token = token
            for other in self._clients.values():
                if other is not client:
                    other.set_bearer_token(token)

    def _daemon_token_due(self) -> bool:
        if not self._token:
            return True
        exp = _token_expiry(self._token)
        return exp is not None and exp - _DAEMON_REFRESH_MARGIN <= time.time()

    def of(self, cls: Any, *, server: Optional[str] = None) -> Any:
        """The sub-client of pyegeria class `cls` for this identity."""
        key = (cls, server or self.view_server)
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                if self.identity.is_person:
                    exp = _token_expiry(self._token or "")
                    if exp is not None and exp <= time.time():
                        raise CallerTokenExpired()
                client = _build(cls, server or self.view_server, self.platform_url, self.user_id,
                                self._password())
                self._clients[key] = client
                if self.identity.is_person:
                    client.set_bearer_token(self._token)
                else:
                    self._mint(client)
            elif not self.identity.is_person and self._daemon_token_due():
                self.refresh()
        _record(self.identity, self.purpose)
        return client

    def refresh(self) -> None:
        """Re-mint the daemon token on every sub-client. A Caller cannot refresh (no password held)."""
        if self.identity.is_person:
            raise CallerTokenExpired()
        clients = list(self._clients.values())
        if not clients:
            return
        token = clients[0].create_egeria_bearer_token()
        if isinstance(token, str) and token and token != "FAILED":
            self._token = token
            for other in clients[1:]:
                other.set_bearer_token(token)


def identity_key(identity: EgeriaIdentity) -> tuple:
    """A hashable key for `identity` that holds no credential (the token is hashed)."""
    return _scope_key(identity, None, None)


def _scope_key(identity: EgeriaIdentity, view_server: Optional[str], platform_url: Optional[str]) -> tuple:
    import hashlib

    token_key = hashlib.sha256(identity.token.encode()).hexdigest() if identity.token else ""
    # A stored credential: the password's hash too, so an edited credential is a new client.
    pw_key = (hashlib.sha256(identity.password.encode()).hexdigest()
              if identity.kind == KIND_STORED and identity.password else "")
    return (identity.kind, identity.user_id, identity.reason, token_key, pw_key,
            identity.bound_platform, view_server, platform_url)


def egeria_client(identity: EgeriaIdentity, *, purpose: str,
                  view_server: Optional[str] = None, platform_url: Optional[str] = None,
                  shared: bool = True) -> EgeriaClients:
    """THE factory. `identity` is `Caller()`, `Daemon(reason, requested_by)` or
    `current_principal()` — never omitted. `purpose` names the use (recorded, logged).
    `shared=False` skips the scope cache: a client one pool thread owns (pyegeria ISSUE-96 binds
    a client's HTTP pool to the event loop of the thread that first drives it)."""
    if not isinstance(identity, EgeriaIdentity) or identity.kind not in _KINDS:
        raise ValueError("egeria_client needs Caller() or Daemon(reason, requested_by=None)")
    if identity.kind == KIND_CALLER and not identity.token:
        raise NoCallerIdentity()
    if identity.kind in (KIND_DAEMON, KIND_STORED) and identity.reason not in {r.value for r in DaemonReason}:
        raise ValueError(f"Daemon identity with an unknown reason {identity.reason!r}")
    cache = _scope.get() if shared else None
    if cache is None:
        return EgeriaClients(identity, purpose=purpose, view_server=view_server, platform_url=platform_url)
    key = _scope_key(identity, view_server, platform_url)
    with _scope_lock:
        clients = cache.get(key)
        if clients is None:
            clients = EgeriaClients(identity, purpose=purpose, view_server=view_server,
                                    platform_url=platform_url)
            cache[key] = clients
        else:
            clients.purpose = purpose
    return clients
