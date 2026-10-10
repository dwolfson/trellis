"""A fake Egeria at the curation-access client boundary (Brief Z), shared by the tests that reach the check.

`zone_access` builds its two pyegeria clients through `_metadata_expert()` and `_security_officer()` and
resolves the platform through `_platform()`; these fakes replace exactly those, so everything of RE's own
(the decision, the emulated zone loop, the publish workflow) runs for real.
"""
from __future__ import annotations

AVAILABLE = {"userAccountStatus": "AVAILABLE", "userAccountType": "EMPLOYEE", "securityGroups": [], "securityRoles": []}


def element(guid: str, zones=(), owners=None) -> dict:
    """A raw metadata element in the live shape, with Egeria's array encoding for zones and owners."""
    classes = []
    if zones:
        classes.append({"classificationName": "ZoneMembership", "classificationProperties": {"propertyValueMap": {
            "zoneMembership": {"arrayValues": {"propertiesAsStrings": {str(i): z for i, z in enumerate(zones)}}}}}})
    if owners is not None:
        classes.append({"classificationName": "Ownership", "classificationProperties": {"propertyValueMap": {
            "userIds": {"arrayValues": {"propertiesAsStrings": {str(i): o for i, o in enumerate(owners)}}}}}})
    return {"elementGUID": guid, "classifications": classes}


class FakeEgeria:
    """The two pyegeria clients an access check builds, in one recording fake. Every account is AVAILABLE
    with no groups unless `accounts` says otherwise (None = Egeria has no such account)."""

    def __init__(self):
        self.elements: dict[str, dict] = {}
        self.controls: dict[str, dict] = {}
        self.accounts: dict[str, dict | None] = {}
        self.fail_control = ""
        self.fail_element = ""
        self.calls: list[tuple] = []

    def get_metadata_element_by_guid(self, guid, **kw):
        self.calls.append(("element", guid))
        if guid == self.fail_element:
            raise ConnectionError("platform unreachable")
        return self.elements.get(guid) or element(guid)

    def get_security_access_control(self, platform, zone, **kw):
        self.calls.append(("control", zone))
        if zone == self.fail_control:
            raise ConnectionError("secrets store unreadable")
        return self.controls.get(zone)

    def get_user_account(self, platform, user_id, **kw):
        self.calls.append(("account", user_id))
        return self.accounts.get(user_id, AVAILABLE)


def install(monkeypatch, *, zones=()) -> FakeEgeria:
    """Fake the client boundary; `zones` are the publish zones RE is configured with (default none)."""
    fake = FakeEgeria()
    monkeypatch.setattr("resource_explorer.zone_access._metadata_expert", lambda: fake)
    monkeypatch.setattr("resource_explorer.zone_access._security_officer", lambda: fake)
    monkeypatch.setattr("resource_explorer.zone_access._platform", lambda: ("Quickstart platform", "plat-guid"))
    monkeypatch.delenv("EXPLORER_DRAFT_ZONE", raising=False)
    monkeypatch.setattr("resource_explorer.egeria_identity.configured_publish_zones", lambda: list(zones))
    return fake


def signed_in(user_id: str, role: str = "user", source: str = "app-jwt"):
    """Set the caller ContextVar; returns the reset token."""
    from resource_explorer.a2a_auth import CallerIdentity, current_caller

    return current_caller.set(CallerIdentity(user_id=user_id, egeria_token="t", auth_source=source, role=role))


def permit_publish_routes(monkeypatch, user_id: str = "publisher") -> FakeEgeria:
    """For tests of a publish route that are about something else: no zone in use (every element answers with
    no ZoneMembership) and a signed-in caller as the curation check sees it (`workflows.curate._caller_identity`
    only; the route's own sign-in handling is untouched)."""
    from resource_explorer.a2a_auth import CallerIdentity

    fake = install(monkeypatch)
    monkeypatch.setattr("resource_explorer.workflows.curate._caller_identity",
                        lambda: CallerIdentity(user_id=user_id, egeria_token="t", auth_source="app-jwt"))
    return fake
