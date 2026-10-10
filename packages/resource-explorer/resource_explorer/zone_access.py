"""May this person UPDATE an element, as Egeria's zone security would answer? (Brief Z, 2026-10-10)

The owner's rule, verbatim: "rely on Egeria's security model and emulate it - so if zones are used they can
control access - if zones aren't being used then it is open". `workflows/curate.curation_access` owns the
decision (sign-in, the Portal role override, "zones not in use"); this module is only the Egeria half: given
the zones that govern an element, does Egeria's access connector grant this user an update on it?

Mirrored from Egeria's `OpenMetadataAccessSecurityConnector` (egeria-v6/egeria,
open-metadata-implementation/adapters/open-connectors/metadata-security-connectors/
open-metadata-access-security-connector/src/main/java/org/odpi/openmetadata/metadatasecurity/accessconnector/
OpenMetadataAccessSecurityConnector.java at egeria af400039c2, read 2026-10-10):

* `validateUserForElementDetailUpdate` (:1497-1522) checks `validateZoneAccess` with
  `AccessOperation.UPDATE_PROPERTIES`: what a verdict needs. Publish needs more (see the constants below).
* `validateZoneAccess` (:1090-1206) loops the element's `ZoneMembership`:
    - a zone whose name equals the userId grants outright (:1122-1125);
    - a zone with NO associated security list "is not a secured zone and is ignored" (:1130-1134);
    - a secured zone grants when its list holds `allUsers` (:1141-1144), the account type's group
      (:1149-1155), one of the account's security groups (:1157-1166) or roles (:1168-1177), or one of the
      instance groups (:1179-1189);
    - after the loop, any secured zone seen and none granted => denied (:1195-1198); otherwise allowed (:1205).
* `getAssociatedSecurityListForZone` (:911-958) reads the control named after the zone and takes the list for
  the operation's enum NAME, falling back to `DEFAULT`; no control, or neither key => `null` (not secured).
* `getInstanceBasedGroups` (:1218-1248): the userId itself; `instanceOwner` when `isUserAnOwner`
  (:1260-1286: TRUE when the element has no `Ownership`, or its `userIds` holds the user); and
  `existingMaintainer` / `newMaintainer` from the element's maintainers.
* Group names are the connector's defaults (`controls/OpenMetadataSecurityConfigurationProperty.java`
  :46-110): allUsers, instanceOwner, existingMaintainer, newMaintainer, employeeUsers, contractUsers,
  externalUsers, digitalUsers. A deployment that renamed them in the connector's configuration would need
  the same names here (named in the module constants below; RE cannot read the connector's config).

**One deliberate departure: unreadable DENIES.** Egeria's own `getAssociatedSecurityListForZone` logs a
secrets-store failure and returns null (:943-957), i.e. treats the zone as unsecured. RE cannot see that log
and must not open by default when zones might apply (Brief Z rule 5), so any read that fails here raises
`AccessUnreadable` and the caller denies with "could not check access in Egeria (<reason>)".

**The account is read first for any zoned element** (round 2), as Egeria does (:1103): an unknown or
disabled account is refused before any zone is looked at. Only with no zone at all (the owner's "not in use"
rule) is nothing read.

**Every operation the write performs is checked** (round 2): Publish creates (CREATE), updates
(UPDATE_PROPERTIES), attaches (ATTACH, both ends), classifies (CLASSIFY) and rezones (PUBLISH). The daemon does
the write, so RE's check is the only one that sees the person.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger(__name__)

#: `AccessOperation` enum NAMES (frameworks/open-connector-framework/.../users/AccessOperation.java): the keys
#: of a control's `associatedSecurityList` (`getAssociatedSecurityListForZone` reads `operation.name()`, then
#: DEFAULT). Which validator checks which (OpenMetadataAccessSecurityConnector.java):
#:   CREATE             validateUserForElementCreate :1306-1330 (zones the NEW element is created in; the
#:                      creator is passed as its only maintainer)
#:   UPDATE_PROPERTIES  validateUserForElementDetailUpdate :1497-1522
#:   ATTACH             validateUserForElementAttach :1582-1620, on BOTH ends
#:   CLASSIFY           validateUserForElementClassify :1840 (any classification but ZoneMembership)
#:   PUBLISH            validateUserForElementClassify :1816 / Declassify :1911 (a ZoneMembership change)
CREATE_OPERATION = "CREATE"
UPDATE_OPERATION = "UPDATE_PROPERTIES"
ATTACH_OPERATION = "ATTACH"
CLASSIFY_OPERATION = "CLASSIFY"
PUBLISH_OPERATION = "PUBLISH"
DEFAULT_OPERATION = "DEFAULT"

#: The words a refusal uses for each operation.
OPERATION_WORDS = {
    CREATE_OPERATION: "create",
    UPDATE_OPERATION: "update",
    ATTACH_OPERATION: "attach",
    CLASSIFY_OPERATION: "classify",
    PUBLISH_OPERATION: "publish (zone change)",
    # Brief T: a tag link / unlink is feedback (validateUserForElementAddFeedback :1696-1730 and
    # validateUserForElementDeleteFeedback :1748-1770); a membership removal is a DETACH.
    "ADD_FEEDBACK": "tag",
    "DELETE_FEEDBACK": "untag",
    "DETACH": "detach",
}

#: The access connector's default dynamic group names (OpenMetadataSecurityConfigurationProperty.java).
ALL_USERS_GROUP = "allUsers"
INSTANCE_OWNER_GROUP = "instanceOwner"
EXISTING_MAINTAINER_GROUP = "existingMaintainer"
NEW_MAINTAINER_GROUP = "newMaintainer"
ACCOUNT_TYPE_GROUPS = {
    "EMPLOYEE": "employeeUsers",
    "CONTRACTOR": "contractUsers",
    "EXTERNAL": "externalUsers",
    "DIGITAL": "digitalUsers",
}

#: Seconds an access read may take before RE stops waiting and denies ("could not check").
ACCESS_READ_TIMEOUT_SECONDS = 20


class AccessUnreadable(RuntimeError):
    """A zone, control, account or element could not be read: never the same as "no restriction"."""


def security_list_for(control: Optional[dict], operation: str = UPDATE_OPERATION) -> Optional[list[str]]:
    """The security list a control gives `operation`, or None when the zone is not secured for it.

    Mirrors `getAssociatedSecurityListForZone` (:911-958): the operation's own key first, then DEFAULT.
    """
    if not isinstance(control, dict):
        return None
    lists = control.get("associatedSecurityList")
    if not isinstance(lists, dict):
        return None
    for key in (operation, DEFAULT_OPERATION):
        value = lists.get(key)
        if value is not None:
            return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]
    return None


def instance_groups(user_id: str, owners: Optional[list[str]], maintainers: Optional[list[str]]) -> list[str]:
    """`getInstanceBasedGroups` (:1218-1248). `owners` None means the element has no `Ownership` userIds,
    which `isUserAnOwner` (:1260-1286) reads as "the user is an owner"."""
    groups = [user_id]
    if owners is None or user_id in owners:
        groups.append(INSTANCE_OWNER_GROUP)
    if maintainers is not None:
        groups.append(EXISTING_MAINTAINER_GROUP if user_id in maintainers else NEW_MAINTAINER_GROUP)
    return groups


@dataclass
class ZoneVerdict:
    """What `zone_grants` found. `secured` names the zones that restrict the refused operation, `operation` is
    that operation, and `why` says what refused when it was not a zone (an unknown or disabled account)."""

    allowed: bool
    secured: list[str] = field(default_factory=list)
    granted_by: str = ""
    operation: str = ""
    why: str = ""


def _one_operation(user_id: str, zones: list[str], operation: str, account: dict,
                   control_for: Callable[[str], Optional[dict]],
                   owners: Optional[list[str]], maintainers: Optional[list[str]]) -> ZoneVerdict:
    """The zone loop of `validateZoneAccess` (:1117-1198) for one operation; the account is already read."""
    # :1122 — a zone named after the user grants outright. Checked across every zone before any read: any
    # grant returns true in Egeria's loop, so the answer is the same and no control is read for nothing.
    if user_id in zones:
        return ZoneVerdict(True, granted_by=f"zone {user_id}", operation=operation)
    secured: list[tuple[str, list[str]]] = []
    for zone in zones:
        sl = security_list_for(control_for(zone), operation)
        if sl is None:
            continue                      # :1130 not a secured zone: ignored, not "everyone"
        secured.append((zone, sl))
    if not secured:
        return ZoneVerdict(True, operation=operation)               # :1205 no secured zone: access
    names = [z for z, _ in secured]
    type_group = ACCOUNT_TYPE_GROUPS.get(str(account.get("userAccountType") or "").upper())
    groups = [str(g) for g in (account.get("securityGroups") or [])]
    roles = [str(r) for r in (account.get("securityRoles") or [])]
    own = instance_groups(user_id, owners, maintainers)
    for zone, sl in secured:
        if ALL_USERS_GROUP in sl:                                   # :1141
            return ZoneVerdict(True, names, f"zone {zone} · {ALL_USERS_GROUP}", operation)
        if type_group and type_group in sl:                         # :1149-1155
            return ZoneVerdict(True, names, f"zone {zone} · {type_group}", operation)
        hit = next((g for g in [*groups, *roles, *own] if g in sl), None)   # :1157-1189
        if hit:
            return ZoneVerdict(True, names, f"zone {zone} · {hit}", operation)
    return ZoneVerdict(False, names, "", operation)                 # :1195 secured, nothing granted


def zone_grants(user_id: str, zones: Iterable[str], *,
                control_for: Callable[[str], Optional[dict]],
                account_for: Callable[[], Optional[dict]],
                owners: Optional[list[str]] = None,
                maintainers: Optional[list[str]] = None,
                operations: Iterable[str] = (UPDATE_OPERATION,),
                creating: bool = False) -> ZoneVerdict:
    """`validateZoneAccess` (:1090-1206) for `user_id` on an element in `zones`, for EVERY operation in
    `operations` (all must be granted: a write that performs several is checked for each).

    `control_for(zone)` returns the zone's security access control (None: none set up) and RAISES
    `AccessUnreadable` when it cannot tell; `account_for()` likewise returns the caller's user account.
    `creating`: the element does not exist yet, and `validateUserForElementCreate` passes the creator as its
    only maintainer (:1324), so the maintainer group is `existingMaintainer`.

    With no zone at all nothing is read (the owner's "not in use" rule). With any zone the ACCOUNT IS READ
    FIRST, as `validateZoneAccess` does (:1103, `getActiveUserAccount` :244-258): an unknown or disabled
    account is refused whatever the zones would grant. A session minted before the account was disabled, or
    by another app sharing the JWT secret, must not outlive the account.
    """
    zones = [z for z in zones if z]
    ops = list(dict.fromkeys(operations)) or [UPDATE_OPERATION]
    if not zones:
        return ZoneVerdict(True, operation=ops[0])
    account = account_for()
    if not isinstance(account, dict):
        return ZoneVerdict(False, [], "", ops[0], f"Egeria has no account for {user_id}")
    status = str(account.get("userAccountStatus") or "").upper()
    if status != "AVAILABLE":
        return ZoneVerdict(False, [], "", ops[0],
                           f"the Egeria account of {user_id} is {status.lower() or 'not marked available'}")
    if creating:
        maintainers = [user_id]
    last = ZoneVerdict(True, operation=ops[0])
    for op in ops:
        last = _one_operation(user_id, zones, op, account, control_for, owners, maintainers)
        if not last.allowed:
            return last
    return last


# ── reading the element, the controls and the account from Egeria ─────────────────────────────────────

def _string_array(classification: dict, name: str) -> Optional[list[str]]:
    """A string-array property of a raw classification, or None when it is not there."""
    cp = classification.get("classificationProperties") or classification.get("properties") or {}
    arr = (((cp.get("propertyValueMap") or {}).get(name) or {}).get("arrayValues") or {}).get("propertiesAsStrings")
    if isinstance(arr, dict):
        return [str(arr[k]) for k in sorted(arr, key=lambda x: int(x) if str(x).isdigit() else 0)]
    value = cp.get(name)
    if isinstance(value, list):
        return [str(v) for v in value]
    return None


def _classifications(element: dict) -> list[dict]:
    header = element.get("elementHeader") if isinstance(element.get("elementHeader"), dict) else {}
    return [c for c in [*(element.get("classifications") or []), *(header.get("classifications") or [])]
            if isinstance(c, dict)]


def element_facts(element: Any) -> tuple[list[str], Optional[list[str]], Optional[list[str]]]:
    """(zones, owners, maintainers) of a raw metadata element. Raises `AccessUnreadable` when the answer is
    not an element (so "unreadable" is never read as "no zones").

    owners: the `Ownership` classification's `userIds` (what `isUserAnOwner` reads), None when absent.
    maintainers: `versions.maintainedBy` when Egeria returned it, else None (no maintainer groups).
    """
    from resource_explorer.catalogue_gateway import GatewayError, zones_of_element

    try:
        zones = zones_of_element(element)
    except GatewayError as exc:
        raise AccessUnreadable(str(exc)) from exc
    owners: Optional[list[str]] = None
    for c in _classifications(element):
        if c.get("classificationName") == "Ownership":
            owners = _string_array(c, "userIds")
            break
    maintainers = None
    for holder in (element, element.get("elementHeader") or {}):
        versions = holder.get("versions") if isinstance(holder, dict) else None
        if isinstance(versions, dict) and isinstance(versions.get("maintainedBy"), list):
            maintainers = [str(m) for m in versions["maintainedBy"]]
            break
    return zones, owners, maintainers


def _metadata_expert():
    """The read client for an element, as RE's daemon (an access check reads what the caller may not)."""
    from pyegeria.omvs.metadata_expert import MetadataExpert

    from resource_explorer.egeria_clients import Daemon, DaemonReason, egeria_client

    return egeria_client(Daemon(DaemonReason.ACCESS_CHECK), purpose="curation access: element",
                         shared=False).of(MetadataExpert)


def _security_officer():
    """The Security Officer client that reads controls and accounts (the same store the connector reads)."""
    from pyegeria.omvs.security_officer import SecurityOfficer

    from resource_explorer.egeria_clients import Daemon, DaemonReason, egeria_client

    return egeria_client(Daemon(DaemonReason.ACCESS_CHECK), purpose="curation access: controls",
                         shared=False).of(SecurityOfficer)


def _platform() -> tuple[str, Optional[str]]:
    from resource_explorer.egeria_identity import _resolve_platform

    return _resolve_platform()


def _close(client: Any) -> None:
    close = getattr(client, "close_session", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001 - tidy-up, never the answer
            pass


def _bounded(what: str, fn: Callable[[], Any]) -> Any:
    """Run one Egeria read on the shared pool (a client built in the thread that drives it), bounded."""
    from concurrent.futures import TimeoutError as _Timeout

    from resource_explorer.concurrency import run_sync

    try:
        return run_sync(fn, timeout=ACCESS_READ_TIMEOUT_SECONDS)
    except AccessUnreadable:
        raise
    except _Timeout as exc:
        raise AccessUnreadable(f"{what}: no answer within {ACCESS_READ_TIMEOUT_SECONDS}s") from exc
    except Exception as exc:  # noqa: BLE001 - every failure is the one named error, never "no restriction"
        raise AccessUnreadable(f"{what}: {type(exc).__name__}: {exc}"[:300]) from exc


def _catch_wrapped(client: Any, *names: str) -> bool:
    """Whether pyegeria's `dynamic_catch` installed loguru's `logger.catch` on any of these methods of THIS
    client's class. `dynamic_catch` decides at import time (`enable_logger_catch`); the wrapper, when there,
    carries `__wrapped__` (functools.wraps). So this asks the function itself, not today's setting."""
    cls = type(client)
    for name in names:
        fn = getattr(cls, name, None)
        if fn is not None and getattr(fn, "__wrapped__", None) is not None:
            return True
    return False


class EgeriaAccessReader:
    """The three Egeria reads a zone decision needs, cached for one batch of decisions (one press)."""

    def __init__(self) -> None:
        self._controls: dict[str, Optional[dict]] = {}
        self._accounts: dict[str, Optional[dict]] = {}
        self._platform: Optional[tuple[str, Optional[str]]] = None

    def element(self, guid: str) -> tuple[list[str], Optional[list[str]], Optional[list[str]]]:
        # Not cached: a press promotes elements as it goes, so an element's zones can change mid-run and the
        # next check must see the zones Egeria holds then. Controls and accounts are stable within a press.
        def read():
            client = _metadata_expert()
            try:
                return client.get_metadata_element_by_guid(guid)
            finally:
                _close(client)
        return element_facts(_bounded(f"the element {guid[:8]}", read))

    def _resolved_platform(self) -> tuple[str, Optional[str]]:
        if self._platform is None:
            self._platform = _bounded("the platform", _platform)
        return self._platform

    def control(self, zone: str) -> Optional[dict]:
        if zone not in self._controls:
            name, guid = self._resolved_platform()
            kwargs = {"platform_guid": guid} if guid else {}

            def read():
                client = _security_officer()
                try:
                    got = client.get_security_access_control(name, zone, **kwargs)
                    # pyegeria's catch wrapper returns None for a FAILED read: "no control" (= open) and a
                    # failure look the same. With the wrapper installed, None is unreadable, never open.
                    if got is None and _catch_wrapped(client, "get_security_access_control",
                                                      "_async_get_security_access_control"):
                        raise AccessUnreadable(
                            f"the access control for zone {zone}: pyegeria's error catch is installed, so "
                            "'no control' cannot be told from a failed read")
                    return got
                finally:
                    _close(client)
            got = _bounded(f"the access control for zone {zone}", read)
            self._controls[zone] = got if isinstance(got, dict) else None
        return self._controls[zone]

    def account(self, user_id: str) -> Optional[dict]:
        if user_id not in self._accounts:
            name, guid = self._resolved_platform()
            kwargs = {"platform_guid": guid} if guid else {}

            def read():
                client = _security_officer()
                try:
                    return client.get_user_account(name, user_id, **kwargs)
                finally:
                    _close(client)
            got = _bounded(f"the account of {user_id}", read)
            self._accounts[user_id] = got if isinstance(got, dict) else None
        return self._accounts[user_id]
