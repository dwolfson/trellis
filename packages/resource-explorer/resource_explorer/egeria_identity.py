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
