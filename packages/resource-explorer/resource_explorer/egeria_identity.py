"""Who an Egeria write runs as, and what governance metadata it carries.

`docs/runtime-architecture-plan.md` §4 in one module:

* **Per-request client.** Every pyegeria client RE builds *on behalf of a
  person* is authenticated with that person's Egeria bearer token, so Egeria's
  own provenance records the person rather than `erinoverview`.
  `caller_credentials()` reports which of the two identities is in play, and
  `apply_identity()` is the single place a client is handed a token.
* **Ownership.** Everything RE publishes gets the `Ownership` classification
  (`0445`) with `owner` = the requesting user's id and
  `ownerTypeName = "UserIdentity"`. Ownership is curation by default: the
  owner may accept, reject, promote and delete without any further grant.
* **Draft zone.** One zone per app (owner's decision, 2026-09-04). On publish
  an element joins `resource-explorer-draft`; on curate-accept it is promoted
  into the deployment's publish zones.

The service account is legitimate in exactly one place
---------------------------------------------------
The **worker role's own loops** — bootstrap heal, Egeria resync, the outbox
drain — are the platform's integration identity and *should* be attributed to
it. `service_credentials()` is that identity, named so a reader can tell a
deliberate service-account call from one that merely forgot to pass a token.

**Interim, and deliberate: a queued run does not carry a token.** An Egeria
bearer token lives one hour (measured — `trellis_auth.
EGERIA_TOKEN_TTL_SECONDS_OBSERVED`) and dies whenever the platform restarts,
while a queued survey may sit in the queue longer than that and then run for
sixteen minutes. Storing the token with the row would mean either a credential
at rest in `runs.target` (rejected outright) or an encrypted column and a key
to manage (out of scope for this pass). So the row carries `requested_by` and
nothing else, and the worker publishes **as the service account with
`Ownership` set to `requested_by`**. Egeria's provenance for such a publish
therefore says "the worker did it"; the `Ownership` classification says whose
it is, and that is the attribution the curate authorization actually reads.
Closing the gap needs an encrypted-at-rest credential store or a delegation
token from Egeria, and is named in the plan as follow-on work.
"""
from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional

log = logging.getLogger(__name__)

__all__ = [
    "DRAFT_ZONE",
    "DEFAULT_PUBLISH_ZONES",
    "EgeriaIdentity",
    "apply_identity",
    "caller_credentials",
    "caller_user_id",
    "classification_client",
    "current_identity",
    "current_zones",
    "draft_zone",
    "ensure_draft_zone_exists",
    "ensure_private_zone_exists",
    "private_zone",
    "private_zone_is_enforced",
    "private_zone_status",
    "private_zones",
    "identity_for_user",
    "ownership_body",
    "publish_zones",
    "service_credentials",
    "set_ownership",
    "set_zone_membership",
    "stamp_published",
    "use_identity",
    "zone_membership_body",
]


#: RE's single draft zone. One zone per app, decided 2026-09-04 (project
#: owner): per-user zones multiply fast and per-project zones are a later
#: refinement if visibility must follow *what* is surveyed rather than *who*
#: surveyed it. Overridable so a second RE deployment against one Egeria does
#: not share a draft zone with the first.
DRAFT_ZONE = "resource-explorer-draft"

#: RE's private zone — the one that actually DENIES.
#:
#: Personal and Experiment investigations zone their artifacts as
#: `[PRIVATE_ZONE, "<creator userId>"]`, and both halves are load-bearing for
#: opposite reasons (`OpenMetadataAccessSecurityConnector.validateZoneAccess`):
#:
#: * the **userId entry grants** — the connector returns true outright on
#:   `userId.equals(zoneName)`, so the owner gets in with no configuration;
#: * the **PRIVATE_ZONE entry denies** — for anyone else it is a zone the
#:   platform recognises as secured, which makes `securedZoneCount > 0` and
#:   sends them to `return false`.
#:
#: A userId on its own denies NOBODY: an unrecognised zone name is *ignored*
#: (not treated as restrictive), the count stays zero, and the method falls
#: through to `return true`. Verified live 2026-09-07: a non-owner was denied
#: with both entries present, and the owner still read the element.
PRIVATE_ZONE = "resource-explorer-private"

#: Where an accepted element is promoted to.
#:
#: `egeria-runtime` is not a guess: it is what the quickstart deployment
#: actually configures. `egeria-workspaces-fs/compose-configs/egeria-freshstart/
#: secrets/egeria-user-directory.omsecrets` sets `defaultZones: [egeria-runtime]`
#: and `publishZones: [egeria-runtime]` for the platform's own account, and it
#: is the only concrete zone value in the whole compose config. Deliberately
#: NOT `quarantine`, which appears only as filler in pyegeria's own docstring
#: examples and would put every accepted element somewhere the quickstart's
#: view server does not serve.
DEFAULT_PUBLISH_ZONES: tuple[str, ...] = ("egeria-runtime",)

_OWNER_TYPE_NAME = "UserIdentity"

#: `Ownership.ownerPropertyName` — which property of the owning element holds
#: the value in `owner`. For a `UserIdentity` that is `userId`.
_OWNER_PROPERTY_NAME = "userId"


def draft_zone() -> str:
    """RE's draft zone name (`EXPLORER_DRAFT_ZONE` overrides)."""
    return (os.environ.get("EXPLORER_DRAFT_ZONE") or "").strip() or DRAFT_ZONE


def private_zone() -> str:
    """RE's private zone name (`EXPLORER_PRIVATE_ZONE` overrides)."""
    return (os.environ.get("EXPLORER_PRIVATE_ZONE") or "").strip() or PRIVATE_ZONE


def private_zones(owner: str) -> list[str]:
    """The `ZoneMembership` for an element private to `owner`.

    Order is not significant to the connector — it loops the whole list — but
    the secured zone is first so a human reading the classification sees the
    restriction before the exception to it.
    """
    zones = [private_zone()]
    if owner:
        zones.append(owner)
    return zones


def publish_zones() -> list[str]:
    """The zones a curate-accepted element is promoted into.

    `EXPLORER_PUBLISH_ZONES` (comma-separated) wins; then RE's own
    `egeria.default_catalog_zones` if a deployment already set it, since that
    is the same question asked earlier under a different name; then
    `DEFAULT_PUBLISH_ZONES`.
    """
    raw = os.environ.get("EXPLORER_PUBLISH_ZONES", "")
    zones = [z.strip() for z in raw.split(",") if z.strip()]
    if zones:
        return zones
    from resource_explorer.config import get_config

    configured = list(get_config().egeria.default_catalog_zones or [])
    if configured:
        return configured
    return list(DEFAULT_PUBLISH_ZONES)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EgeriaIdentity:
    """How one pyegeria client should authenticate, and as whom.

    Exactly one of `token` / `password` is meaningful:

    * `token` set — a signed-in person. `apply_identity` calls
      `set_bearer_token`, and Egeria's provenance names them.
    * `password` set, `is_service_account` True — the worker role's own
      identity, which is the right attribution for background loops.

    `user_id` is always the name to put in `Ownership.owner`, which is why it
    is set on both: an interim service-account publish still records *whose*
    artifact it is (see the module docstring).
    """

    user_id: str
    token: Optional[str] = None
    password: str = ""
    is_service_account: bool = False

    @property
    def is_person(self) -> bool:
        return bool(self.token) and not self.is_service_account


def current_identity() -> Optional[EgeriaIdentity]:
    """The signed-in caller for this request/thread, or None.

    Reads `a2a_auth.current_caller` — RE's *one* identity ContextVar, set by
    the web `IdentityMiddleware`, by the A2A middleware and by the CLI's
    `use_identity()`. There is deliberately no second mechanism; see
    `resource_explorer/auth.py`.
    """
    from resource_explorer.a2a_auth import caller

    identity = caller()
    if identity is None or identity.auth_source == "anonymous":
        return None
    return EgeriaIdentity(user_id=identity.user_id, token=identity.egeria_token)


def caller_user_id(default: str = "") -> str:
    """The signed-in user's id, or `default` when there is no caller."""
    identity = current_identity()
    return identity.user_id if identity is not None else default


def service_credentials() -> EgeriaIdentity:
    """The worker role's own Egeria identity — the one legitimate service account."""
    from resource_explorer.config import get_config

    egeria = get_config().egeria
    return EgeriaIdentity(
        user_id=egeria.user_id, password=egeria.user_password, is_service_account=True
    )


def caller_credentials(*, required: bool = False) -> EgeriaIdentity:
    """The identity a live Egeria call on this request should use.

    `required=True` raises when nothing is signed in — for a call that must be
    attributed to a person (a publish, a materialization). `required=False`
    falls back to the service account, which is correct only for the worker's
    own loops and for read-only calls; those call sites pass it explicitly so
    the fallback is never something a reader has to infer.
    """
    identity = current_identity()
    if identity is not None:
        return identity
    if required:
        raise PermissionError(
            "This operation writes to Egeria on behalf of a person and no user is "
            "signed in. Sign in (POST /api/auth/login) or run `resource-explorer login`."
        )
    return service_credentials()


def identity_for_user(user_id: str) -> EgeriaIdentity:
    """A service-account identity that *owns* its writes as `user_id`.

    The interim shape for a queued run: no token survives the queue, so the
    worker authenticates as itself and stamps `Ownership` with the person who
    asked. See the module docstring.
    """
    svc = service_credentials()
    return EgeriaIdentity(
        user_id=user_id or svc.user_id,
        password=svc.password,
        is_service_account=True,
    )


def apply_identity(client: Any, identity: Optional[EgeriaIdentity] = None) -> None:
    """Authenticate a freshly-built pyegeria client. The one place this happens.

    A person's token is reused via `set_bearer_token`; a service account mints
    its own. Delegates to `trellis_auth.apply_token`, so RE and the Portal
    build clients the same way.
    """
    from trellis_auth import apply_token

    identity = identity or caller_credentials()
    apply_token(client, identity.token if identity.is_person else None)


@contextmanager
def use_identity(identity: Optional[EgeriaIdentity]) -> Iterator[None]:
    """Run a block as `identity` — the CLI's and the worker's way in.

    Sets the same ContextVar the web and A2A middlewares set, so a CLI command
    and an HTTP request reach identical code with identical results. A None
    identity clears the caller rather than leaving a previous one in place;
    inheriting somebody else's identity is the failure mode this guards.
    """
    from resource_explorer.a2a_auth import CallerIdentity, current_caller

    caller_obj = None
    if identity is not None and identity.is_person:
        caller_obj = CallerIdentity(
            user_id=identity.user_id,
            egeria_token=identity.token,
            auth_source="app-jwt",
        )
    reset = current_caller.set(caller_obj)
    try:
        yield
    finally:
        current_caller.reset(reset)


# ---------------------------------------------------------------------------
# Ownership and zones
# ---------------------------------------------------------------------------

def ownership_body(owner: str, owner_type_name: str = _OWNER_TYPE_NAME) -> dict:
    """The `NewClassificationRequestBody` for `Ownership` (`0445`).

    **`OwnershipProperties`, not `OwnerProperties`.** pyegeria's own
    `add_ownership_to_element` docstring says `OwnerProperties` in its sample
    body, and that is wrong: the method passes `prop=["OwnershipProperties"]`
    to `_async_new_classification_request`, and
    `validate_new_classification_request` rejects anything else with
    `unexpected property class name` before a request is ever made.
    `pyegeria/http clients/Egeria-api-classification-explorer.http` agrees with
    the code. Found by running against the live platform rather than by
    reading — the docstring version fails with a validation error that names
    neither the expected class nor the one supplied. Logged as an issue against
    egeria-python; the value here follows the code, which is what the server
    actually enforces.
    """
    return {
        "class": "NewClassificationRequestBody",
        "properties": {
            "class": "OwnershipProperties",
            "owner": owner,
            "ownerTypeName": owner_type_name,
            "ownerPropertyName": _OWNER_PROPERTY_NAME,
        },
    }


def zone_membership_body(zones: Iterable[str]) -> dict:
    """The `NewClassificationRequestBody` for `ZoneMembership` (`0424`)."""
    return {
        "class": "NewClassificationRequestBody",
        "properties": {
            "class": "ZoneMembershipProperties",
            "zoneMembership": list(zones),
        },
    }


def classification_client(identity: Optional[EgeriaIdentity] = None):
    """A `ClassificationExplorer` authenticated as `identity`.

    Built per call rather than cached on a publisher: the whole point is that
    the client carries *this* caller's credential, and a cached one carries
    whoever built it first.
    """
    from pyegeria import ClassificationExplorer

    from resource_explorer.config import get_config

    egeria = get_config().egeria
    identity = identity or caller_credentials()
    client = ClassificationExplorer(
        egeria.view_server,
        egeria.platform_url,
        identity.user_id if identity.is_person else egeria.user_id,
        identity.password or egeria.user_password,
    )
    apply_identity(client, identity)
    return client


def set_ownership(
    element_guid: str,
    owner: str,
    *,
    identity: Optional[EgeriaIdentity] = None,
    client: Any = None,
    owner_type_name: str = _OWNER_TYPE_NAME,
) -> bool:
    """Classify `element_guid` as owned by `owner`. True when Egeria accepted it.

    Best-effort by design: a publish that produced real elements must not be
    reported as a failure because one classification call did not land. The
    failure is logged and returned as False so a caller that cares (the tests,
    and the publish response's warning field) can say so.
    """
    if not element_guid or not owner:
        return False
    try:
        client = client or classification_client(identity)
        client.add_ownership_to_element(element_guid, ownership_body(owner, owner_type_name))
        log.info("egeria: Ownership(owner=%s) set on %s", owner, element_guid)
        return True
    except Exception as exc:
        log.warning(
            "egeria: could not set Ownership(owner=%s) on %s — %s: %s",
            owner, element_guid, type(exc).__name__, exc,
        )
        return False


def set_zone_membership(
    element_guid: str,
    zones: Iterable[str],
    *,
    identity: Optional[EgeriaIdentity] = None,
    client: Any = None,
) -> bool:
    """Put `element_guid` in exactly `zones`. True when Egeria accepted it.

    `add_zone_membership` *replaces* the classification's property rather than
    appending, which is what promotion needs: an accepted element leaves the
    draft zone in the same call that puts it in the publish zones, with no
    window in which it is in both.
    """
    zones = list(zones)
    if not element_guid or not zones:
        return False
    try:
        client = client or classification_client(identity)
        client.add_zone_membership(element_guid, zone_membership_body(zones))
        log.info("egeria: ZoneMembership%s set on %s", zones, element_guid)
        return True
    except Exception as exc:
        log.warning(
            "egeria: could not set ZoneMembership%s on %s — %s: %s",
            zones, element_guid, type(exc).__name__, exc,
        )
        return False


def current_zones(element_guid: str, identity: Optional[EgeriaIdentity] = None) -> list[str]:
    """The zones `element_guid` is in right now, or `[]` if we could not tell.

    **`[]` means "we could not tell", and callers must treat it that way.**
    Egeria's security connector rejects a zone change whose before and after
    are equal, so `promote_to_publish_zones` checks this first — and it treats
    an empty answer as "go ahead and try" rather than as "the element is in no
    zones". Read the other way round, an unreachable Egeria would look like an
    element that needs promoting and a genuinely promoted element would be
    re-promoted into a 403.
    """
    if not element_guid:
        return []
    try:
        from pyegeria.omvs.metadata_expert import MetadataExpert

        from resource_explorer.config import get_config

        egeria = get_config().egeria
        identity = identity or caller_credentials()
        client = MetadataExpert(
            egeria.view_server,
            egeria.platform_url,
            identity.user_id if identity.is_person else egeria.user_id,
            identity.password or egeria.user_password,
        )
        apply_identity(client, identity)
        element = client.get_metadata_element_by_guid(element_guid)
        if not isinstance(element, dict):
            return []
        header = element.get("elementHeader", element)
        for classification in header.get("classifications") or []:
            if classification.get("classificationName") != "ZoneMembership":
                continue
            props = classification.get("classificationProperties") or {}
            array = (props.get("propertyValueMap") or {}).get("zoneMembership") or {}
            values = (array.get("arrayValues") or {}).get("propertiesAsStrings") or {}
            return [values[k] for k in sorted(values, key=lambda x: int(x))]
        return []
    except Exception as exc:
        log.debug("egeria: could not read zones of %s — %s", element_guid, exc)
        return []


def stamp_published(
    element_guid: str,
    owner: str,
    *,
    identity: Optional[EgeriaIdentity] = None,
    client: Any = None,
    zones: Optional[Iterable[str]] = None,
) -> dict:
    """`Ownership` + draft-zone `ZoneMembership` on one just-published element.

    The pair is applied together because they are one decision — "this is
    yours, and it is not visible outside the draft zone yet" — and a publish
    that set one without the other would be either an unowned draft or an
    owned element already in the catalogue's normal zones.

    One client is built and reused across both calls: two classifications on
    one element should cost one authentication, not two.
    """
    zones = list(zones) if zones is not None else [draft_zone()]
    client = client or classification_client(identity)
    return {
        "ownership": set_ownership(element_guid, owner, client=client),
        "zone_membership": set_zone_membership(element_guid, zones, client=client),
        "owner": owner,
        "zones": zones,
    }


# ---------------------------------------------------------------------------
# The zone itself
# ---------------------------------------------------------------------------

#: Qualified name of RE's draft zone element.
def _zone_qualified_name(zone: str) -> str:
    return f"GovernanceZone::{zone}"


#: How long after WRITING the control before the enforcing connector has it.
#:
#: Measured 2026-09-07 against the quickstart platform: a control written at
#: 02:53:11 was still not enforced 6 minutes later and WAS enforced at 7:03.
#: The deployment's secrets collection declares `refreshTimeInterval: 10`,
#: which `SecretsStoreConnector` multiplies by `60 * 1000` — minutes. The
#: connector reloads on its own timer, so the wait from any given write is
#: anywhere from ~0 to the full interval.
#:
#: Default is deliberately longer than the interval. Being late costs a few
#: minutes of refused private publishing; being early publishes private work
#: into a zone that is not yet enforced, which cannot be undone.
PRIVATE_ZONE_SETTLE_SECONDS = int(os.environ.get("EXPLORER_PRIVATE_ZONE_SETTLE", "720"))

#: Cached result of the last `ensure_private_zone_exists()`. `None` means "not
#: yet asked", which is deliberately NOT the same as "not enforced" — see
#: `private_zone_is_enforced`.
_private_zone_state: Optional[dict] = None


def _platform_name() -> str:
    """The catalogued OMAG Server Platform the Security Officer API addresses.

    `EXPLORER_EGERIA_PLATFORM_NAME` wins. Otherwise the single catalogued
    `SoftwareServerPlatform`, ignoring the archive's `~{placeholder}~` template
    entries — a real deployment has one, and if it somehow has several we
    cannot pick for the operator, so we say so rather than guess.
    """
    configured = (os.environ.get("EXPLORER_EGERIA_PLATFORM_NAME") or "").strip()
    if configured:
        return configured
    from pyegeria import EgeriaTech

    from resource_explorer.config import get_config

    egeria = get_config().egeria
    tech = EgeriaTech(egeria.view_server, egeria.platform_url,
                      egeria.user_id, egeria.user_password)
    tech.create_egeria_bearer_token()
    names = []
    for el in tech.get_elements("SoftwareServerPlatform", output_format="JSON") or []:
        name = ((el.get("properties") or {}).get("displayName") or "").strip()
        if name and not name.startswith("~"):
            names.append(name)
    if len(names) == 1:
        return names[0]
    if not names:
        raise RuntimeError(
            "could not identify the platform to configure: no catalogued "
            "SoftwareServerPlatform found. Set EXPLORER_EGERIA_PLATFORM_NAME."
        )

    # Several platforms are catalogued. Before refusing, ask which of them
    # already holds OUR control — that is a fact, not a guess, and it is the
    # common case on a deployment that has been running: the control was
    # created on one specific platform and we only need to find it again.
    #
    # This path became real on 2026-09-08: a redeploy catalogued a second
    # platform ("Local OMAG Server Platform" beside "Quickstart OMAG Server
    # Platform"), and the refusal below started firing on a deployment whose
    # private zone was demonstrably still enforcing. Refusing there is the safe
    # direction but it disables a working feature, which is its own kind of
    # wrong answer.
    zone = private_zone()
    try:
        from pyegeria.omvs.security_officer import SecurityOfficer

        probe = SecurityOfficer(egeria.view_server, egeria.platform_url,
                                egeria.user_id, egeria.user_password)
        probe.create_egeria_bearer_token()
        holders = []
        for name in names:
            try:
                got = probe.get_security_access_control(name, zone)
            except Exception:
                continue
            if got and (got.get("associatedSecurityList") or {}):
                holders.append(name)
        if len(holders) == 1:
            log.info("egeria: several platforms catalogued %s; using %r, which holds "
                     "the %r control", names, holders[0], zone)
            return holders[0]
        if len(holders) > 1:
            raise RuntimeError(
                f"the {zone!r} control exists on more than one catalogued platform "
                f"({holders}), so which one governs this deployment is ambiguous. "
                "Set EXPLORER_EGERIA_PLATFORM_NAME."
            )
    except RuntimeError:
        raise
    except Exception as exc:
        log.debug("could not probe platforms for the %r control: %s", zone, exc)

    # None of them holds it, so this would be a CREATE and there is no evidence
    # for where it belongs. Refusing beats writing security configuration to an
    # arbitrary platform.
    raise RuntimeError(
        f"could not identify the platform to configure: found {names}, and none "
        f"holds the {zone!r} control. Set EXPLORER_EGERIA_PLATFORM_NAME to say "
        "which platform governs this deployment."
    )


def ensure_private_zone_exists(identity: Optional[EgeriaIdentity] = None) -> dict:
    """Create the `SecurityAccessControl` that makes `private_zone()` ENFORCED.

    This is the half that actually denies, and it is a different mechanism from
    `ensure_draft_zone_exists`. That one creates a `GovernanceZone` *metadata
    element*, which is documentation: the security connector never reads it. The
    thing the connector reads is the platform's secrets store, reached through
    the Security Officer OMVS —

        SecurityOfficer.set_security_access_control
          -> OpenMetadataPlatformSecurityVerifier.setSecurityAccessControl
          -> userSecurityConnector.setSecurityAccessControl

    and `getAssociatedSecurityListForZone` reads that same store. A zone element
    without a control is **decorative**: the connector does not recognise the
    zone, so it *ignores* it rather than treating it as restrictive, and
    everything in it is world-readable while looking private.

    **A read-back is not proof of enforcement, and this is the subtle part.**
    The store and the connector that reads it are not the same thing: the
    connector reloads on `refreshTimeInterval`. Measured live — a control
    written at 02:53:11 read back from the store immediately, and a
    privately-zoned element was still readable by a non-owner **six minutes
    later**, then denied at seven. So a freshly created control reports
    `enforced: False` until `PRIVATE_ZONE_SETTLE_SECONDS` has passed. A control
    that was already there when we first looked predates this process and is
    treated as settled.

    The security list names a group that nobody holds. That is the whole point:
    the list must never admit anyone, because access for the owner comes from
    the `userId`-as-zone-name shortcut instead. Two groups are deliberately NOT
    used — `openMetadataMember` (effectively everyone) and `instanceOwnersGroup`
    (whose `isUserAnOwner` returns **true when an element carries no `Ownership`
    classification at all**, so one unstamped element would be readable by
    anybody).

    Requires platform-operator rights (`validateUserAsOperatorForPlatform`, whose
    base implementation only throws — there is no permissive fallback). On the
    Coco-Pharma-seeded quickstart, RE's own account has them. On a stock
    freshstart NO human account does, so this returns `not_authorized` with the
    groups that would grant it, and the caller must treat private publishing as
    unavailable rather than proceeding. Never raises.
    """
    global _private_zone_state
    import time as _time

    zone = private_zone()
    try:
        from pyegeria.omvs.security_officer import SecurityOfficer

        from resource_explorer.config import get_config

        egeria = get_config().egeria
        identity = identity or service_credentials()
        client = SecurityOfficer(egeria.view_server, egeria.platform_url,
                                 egeria.user_id, egeria.user_password)
        apply_identity(client, identity)
        platform = _platform_name()

        existing = client.get_security_access_control(platform, zone)
        if existing and (existing.get("associatedSecurityList") or {}):
            # Already there when we first looked, so it predates this process
            # and the connector has had at least as long as we have been up.
            _private_zone_state = {
                "status": "exists", "zone": zone, "platform": platform,
                "control_present": True, "enforced": True,
                "basis": "control was already present when this process first looked",
            }
            return _private_zone_state

        client.set_security_access_control(platform, {
            "class": "SecurityAccessControlRequestBody",
            "securityAccessControl": {
                "controlName": zone,
                "controlDisplayName": "Resource Explorer — private",
                "controlTypeName": "GovernanceZone",
                "description": (
                    "Elements belonging to a Personal or Experiment investigation "
                    "in Resource Explorer. Readable only by their creator, whose "
                    "userId is carried as a second zone on each element. The "
                    "security list below names a group nobody holds, on purpose: "
                    "it exists to make this a SECURED zone so that everyone else "
                    "is denied, not to admit anybody."
                ),
                "associatedSecurityList": {"DEFAULT": ["resourceExplorerPrivateNobody"]},
                "otherProperties": {
                    "criteria": "Published by resource-explorer from a private investigation.",
                    "createdBy": "resource-explorer",
                },
            },
        })

        # Read back. A write that returned without raising is not evidence the
        # control exists — the same lesson as the classification read-back in
        # `egeria_investigation_publisher`.
        back = client.get_security_access_control(platform, zone)
        if not (back and (back.get("associatedSecurityList") or {})):
            log.error(
                "egeria: wrote SecurityAccessControl %r but it did not read back with "
                "a security list — the zone would be IGNORED by the security "
                "connector, so private publishing stays disabled.", zone)
            _private_zone_state = {
                "status": "unconfirmed", "zone": zone, "platform": platform,
                "control_present": False, "enforced": False,
                "detail": "the control did not read back with a security list",
            }
            return _private_zone_state

        settle_at = _time.time() + PRIVATE_ZONE_SETTLE_SECONDS
        log.info("egeria: created SecurityAccessControl %r on %r; enforcement expected "
                 "within %ss once the security connector reloads its secrets store",
                 zone, platform, PRIVATE_ZONE_SETTLE_SECONDS)
        _private_zone_state = {
            "status": "created", "zone": zone, "platform": platform,
            "control_present": True, "enforced": False,
            "settle_after": settle_at,
            "detail": (
                f"just created; the security connector reloads on its own timer, so "
                f"enforcement is not assumed for {PRIVATE_ZONE_SETTLE_SECONDS}s. "
                "Private publishing is refused until then."
            ),
        }
        return private_zone_status()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        unauthorized = "UserNotAuthorized" in detail or "not authorized" in detail.lower()
        log.warning(
            "egeria: could not ensure the private zone %r is enforced — %s. "
            "Private investigations will NOT publish until this is fixed.", zone, detail)
        _private_zone_state = {
            "status": "not_authorized" if unauthorized else "error",
            "zone": zone, "control_present": False, "enforced": False,
            "detail": detail,
            "remedy": (
                "Writing a security access control needs platform-operator rights. "
                "Grant RE's Egeria account one of: serverOperator, infrastructureTeam, "
                "devOpsTeam, dataManagementTeam, securityTeam, serverAdministrator, "
                "runtimeManager, metadataArchitect, platform — or have an operator "
                f"create the {zone!r} GovernanceZone security access control."
            ),
        }
        return _private_zone_state


def private_zone_is_enforced() -> bool:
    """Whether the private zone is KNOWN to deny. Defaults to False.

    Four states collapse to False here, and only one of them is "we checked and
    it does not": never asked, could not ask, confirmed absent, and **present
    but not yet loaded by the enforcing connector**. That last one is the case a
    store read-back cannot see, and it is real — measured at seven minutes.

    The asymmetry is deliberate. Guessing True when the control is missing or
    not yet live means publishing somebody's private work into a zone the
    connector ignores — world-readable, while every RE screen says private.
    Guessing False only means private publishing is refused until somebody
    looks, which is recoverable and visible.
    """
    return bool(private_zone_status().get("enforced"))


def private_zone_status() -> dict:
    """What we currently know, for the admin surface.

    `status: "unknown"` when nothing has asked yet — not a synonym for "not
    enforced", though both refuse a private publish. Resolves `settle_after`
    into the live `enforced` answer so callers never have to do clock
    arithmetic to find out whether they may publish.
    """
    import time as _time

    if _private_zone_state is None:
        return {"status": "unknown", "zone": private_zone(), "control_present": False,
                "enforced": False, "detail": "not checked yet this process"}
    state = dict(_private_zone_state)
    settle_after = state.pop("settle_after", None)
    if settle_after is not None:
        remaining = max(0, int(settle_after - _time.time()))
        state["enforced"] = state.get("control_present", False) and remaining == 0
        state["settling_seconds_remaining"] = remaining
        if remaining:
            state["status"] = "settling"
    return state


def ensure_draft_zone_exists(identity: Optional[EgeriaIdentity] = None) -> dict:
    """Create RE's draft `GovernanceZone` if Egeria does not have one. Idempotent.

    Called once from the worker's leader-elected startup, so N processes
    create at most one zone and a fresh Egeria gets one without an operator
    step.

    **pyegeria has no GovernanceZone create or lookup** — searched 2026-09-04
    across `pyegeria/omvs/`: `governance_officer.py` creates
    `GovernanceDefinition`s (a different type family — `GovernanceZone` is
    `0424`, not `0401`), and every other `governance_zone` hit is a
    *filter* parameter on a find. Logged as an issue against egeria-python;
    until it has a first-class call this goes through
    `MetadataExpert.create_metadata_element`, the generic element create, with
    `get_metadata_element_by_unique_name` as the idempotency check.

    Never raises. A deployment whose Egeria is down at worker start must still
    start; the zone is created on the next attempt, and until then a publish
    still names the zone in its `ZoneMembership` — a zone classification does
    not require the zone element to exist, it just cannot be navigated to.
    """
    zone = draft_zone()
    qualified_name = _zone_qualified_name(zone)
    try:
        from pyegeria.omvs.metadata_expert import MetadataExpert

        from resource_explorer.config import get_config

        egeria = get_config().egeria
        identity = identity or service_credentials()
        client = MetadataExpert(
            egeria.view_server, egeria.platform_url, egeria.user_id, egeria.user_password
        )
        apply_identity(client, identity)

        existing = _existing_guid(client, qualified_name)
        if existing:
            return {"status": "exists", "zone": zone, "guid": existing}

        guid = client.create_metadata_element({
            "class": "NewOpenMetadataElementRequestBody",
            "typeName": "GovernanceZone",
            "isOwnAnchor": True,
            "properties": {
                "class": "ElementProperties",
                "propertyValueMap": {
                    "qualifiedName": _string_property(qualified_name),
                    "displayName": _string_property(zone),
                    "description": _string_property(
                        "Elements published by Resource Explorer that are awaiting "
                        "curation. Visible to the publishing user and to curators; "
                        "promoted into the deployment's publish zones on accept."
                    ),
                    "criteria": _string_property(
                        "Published by resource-explorer and not yet accepted."
                    ),
                },
            },
        })
        log.info("egeria: created GovernanceZone %r (%s)", zone, guid)
        return {"status": "created", "zone": zone, "guid": guid}
    except Exception as exc:
        log.warning(
            "egeria: could not ensure GovernanceZone %r exists — %s: %s. Publishes "
            "still carry the zone in their ZoneMembership classification.",
            zone, type(exc).__name__, exc,
        )
        return {"status": "error", "zone": zone, "error": str(exc)}


#: A GUID and nothing else. `get_metadata_element_by_unique_name` returns a
#: *sentence* when it finds nothing, and there is no documented list of which
#: sentence — so the only reliable test is whether what came back is shaped like
#: an identifier.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _existing_guid(client: Any, qualified_name: str) -> str:
    """The GUID of an element with this qualified name, or `""`.

    **Match the GUID shape, never the error text.** `get_metadata_element_by_
    unique_name` signals "nothing here" by returning a human sentence, and the
    first version of this function tested for the literal `"No element found"`
    from pyegeria's own docstring. The platform actually says **"No elements
    found"** — plural — so the test passed on a miss, the caller reported
    `{"status": "exists", "guid": "No elements found"}`, and the zone was never
    created while the result said it already existed. Caught by running it
    against the live platform; nothing about the return value looked wrong from
    inside the process.

    Testing the shape of what we want, rather than the wording of what we don't,
    cannot go stale when the message changes. Same reasoning, and the same
    regex, as `EgeriaPublisher._find_element_guid`.
    """
    try:
        found = client.get_metadata_element_by_unique_name(qualified_name)
    except Exception as exc:
        log.debug("egeria: lookup of %r failed — %s", qualified_name, exc)
        return ""
    if isinstance(found, dict):
        candidate = (
            found.get("elementGUID")
            or (found.get("elementHeader") or {}).get("guid")
            or found.get("guid")
            or ""
        )
    elif isinstance(found, str):
        candidate = found
    else:
        return ""
    return candidate if _UUID_RE.match(candidate.strip()) else ""


def _string_property(value: str) -> dict:
    return {
        "class": "PrimitiveTypePropertyValue",
        "typeName": "string",
        "primitiveValue": value,
    }
