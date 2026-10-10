"""Brief Z (2026-10-10): curation rights follow Egeria's zones, not RE's own "last decided_by owns it".

The project owner: "rely on Egeria's security model and emulate it - so if zones are used they can control
access - if zones aren't being used then it is open". What broke: the egeria_git Publish plan mixed decisions
by erinoverview and peterprofile, and Publish refused BOTH with a whole-press 403 (each was "not the owner" of
the other's items), and neither could re-decide the other's items either.

No Egeria anywhere: the zone reads are faked at the client-construction boundary (`zone_access._metadata_expert`,
`_security_officer`, `_platform`), and a fake that is reached when no read should happen fails the test.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer import architecture_publish as ap
from resource_explorer.registry import Project, ProjectRegistry

pytestmark = pytest.mark.usefixtures("mock_egeria_client_connections")

# The deployment's two people (the egeria_git case was erinoverview and peterprofile; erinoverview is RE's own
# service account in a default checkout, which the web refuses to sign in, so a second person stands in for it).
ERIN, PETER = "garygeeke", "peterprofile"
SECURED = "sales-zone"


# ── a fake Egeria at the client boundary ──────────────────────────────────────────────────────────────

def _element(guid: str, zones=(), owners=None) -> dict:
    classes = []
    if zones:
        classes.append({"classificationName": "ZoneMembership", "classificationProperties": {"propertyValueMap": {
            "zoneMembership": {"arrayValues": {"propertiesAsStrings": {str(i): z for i, z in enumerate(zones)}}}}}})
    if owners is not None:
        classes.append({"classificationName": "Ownership", "classificationProperties": {"propertyValueMap": {
            "userIds": {"arrayValues": {"propertiesAsStrings": {str(i): o for i, o in enumerate(owners)}}}}}})
    return {"elementGUID": guid, "classifications": classes}


class FakeEgeria:
    """The two pyegeria clients an access check builds, in one recording fake."""

    def __init__(self):
        self.elements: dict[str, dict] = {}
        self.controls: dict[str, dict] = {}
        self.accounts: dict[str, dict] = {}
        self.fail_control = ""
        self.fail_element = ""
        self.calls: list[tuple] = []

    def get_metadata_element_by_guid(self, guid, **kw):
        self.calls.append(("element", guid))
        if guid == self.fail_element:
            raise ConnectionError("platform unreachable")
        return self.elements.get(guid) or _element(guid)

    def get_security_access_control(self, platform, zone, **kw):
        self.calls.append(("control", zone))
        if zone == self.fail_control:
            raise ConnectionError("secrets store unreadable")
        return self.controls.get(zone)

    def get_user_account(self, platform, user_id, **kw):
        self.calls.append(("account", user_id))
        return self.accounts.get(user_id)


@pytest.fixture
def egeria(monkeypatch):
    fake = FakeEgeria()
    monkeypatch.setattr("resource_explorer.zone_access._metadata_expert", lambda: fake)
    monkeypatch.setattr("resource_explorer.zone_access._security_officer", lambda: fake)
    monkeypatch.setattr("resource_explorer.zone_access._platform", lambda: ("Quickstart platform", "plat-guid"))
    monkeypatch.delenv("EXPLORER_DRAFT_ZONE", raising=False)
    monkeypatch.setattr("resource_explorer.egeria_identity.configured_publish_zones", lambda: [])
    return fake


@pytest.fixture
def no_egeria_reads(monkeypatch):
    """With zones not in use and nothing in Egeria, NO read may happen."""
    def boom(*a, **k):
        raise AssertionError("an Egeria access read was made where none was needed")
    monkeypatch.setattr("resource_explorer.zone_access._metadata_expert", boom)
    monkeypatch.setattr("resource_explorer.zone_access._security_officer", boom)
    monkeypatch.setattr("resource_explorer.zone_access._platform", boom)
    monkeypatch.delenv("EXPLORER_DRAFT_ZONE", raising=False)
    monkeypatch.setattr("resource_explorer.egeria_identity.configured_publish_zones", lambda: [])


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p", description=""))
    return r


def _as(user_id, role="user", source="app-jwt"):
    from resource_explorer.a2a_auth import CallerIdentity, current_caller

    return current_caller.set(CallerIdentity(user_id=user_id, egeria_token="t", auth_source=source, role=role))


@pytest.fixture
def as_erin():
    from resource_explorer.a2a_auth import current_caller

    reset = _as(ERIN)
    yield ERIN
    current_caller.reset(reset)


# ── 1. the emulation itself (OpenMetadataAccessSecurityConnector.validateZoneAccess) ──────────────────

class TestZoneGrants:
    @staticmethod
    def _grants(zones, controls, account=None, owners=None):
        from resource_explorer.zone_access import zone_grants

        return zone_grants(ERIN, zones, control_for=controls.get, account_for=lambda: account, owners=owners)

    def test_a_zone_named_after_the_user_grants(self):
        assert self._grants(["resource-explorer-private", ERIN], {}).allowed is True

    def test_a_zone_with_no_control_is_ignored_not_restrictive(self):
        assert self._grants(["decorative"], {}).allowed is True

    def test_a_secured_zone_without_the_user_denies_and_names_the_zone(self):
        v = self._grants([SECURED], {SECURED: {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}},
                         account={"userAccountStatus": "AVAILABLE", "securityGroups": ["hr"]}, owners=[PETER])
        assert v.allowed is False and v.secured == [SECURED]

    def test_a_group_or_role_on_the_account_grants(self):
        controls = {SECURED: {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}}
        assert self._grants([SECURED], controls, {"securityGroups": ["salesTeam"]}, owners=[PETER]).allowed
        assert self._grants([SECURED], controls, {"securityRoles": ["salesTeam"]}, owners=[PETER]).allowed

    def test_the_operation_key_wins_over_default(self):
        controls = {SECURED: {"associatedSecurityList": {"UPDATE_PROPERTIES": ["editors"], "DEFAULT": ["allUsers"]}}}
        assert self._grants([SECURED], controls, {"securityGroups": []}, owners=[PETER]).allowed is False

    def test_all_users_and_account_type_groups_grant(self):
        assert self._grants([SECURED], {SECURED: {"associatedSecurityList": {"DEFAULT": ["allUsers"]}}}).allowed
        assert self._grants([SECURED], {SECURED: {"associatedSecurityList": {"DEFAULT": ["employeeUsers"]}}},
                            {"userAccountType": "EMPLOYEE"}, owners=[PETER]).allowed

    def test_instance_owner_holds_when_there_is_no_ownership_userids(self):
        """isUserAnOwner (:1260-1286) is TRUE when the element carries no Ownership userIds at all."""
        controls = {SECURED: {"associatedSecurityList": {"DEFAULT": ["instanceOwner"]}}}
        assert self._grants([SECURED], controls, owners=None).allowed is True
        assert self._grants([SECURED], controls, {"securityGroups": []}, owners=[PETER]).allowed is False

    def test_a_disabled_or_missing_account_denies_a_secured_zone(self):
        controls = {SECURED: {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}}
        assert self._grants([SECURED], controls, None, owners=[PETER]).allowed is False
        assert self._grants([SECURED], controls, {"userAccountStatus": "DISABLED", "securityGroups": ["salesTeam"]},
                            owners=[PETER]).allowed is False


# ── 2. the decision (workflows/curate.curation_access) ────────────────────────────────────────────────

class TestCurationAccess:
    def test_anonymous_is_denied(self, registry, no_egeria_reads):
        from resource_explorer.workflows.curate import BASIS_ANONYMOUS, curation_access

        d = curation_access(registry, "repo", "p", "src/a")
        assert (d.allowed, d.basis) == (False, BASIS_ANONYMOUS) and "sign in" in d.reason

    def test_the_egeria_git_case_mixed_decided_by_no_zones_is_open_to_either(self, registry, no_egeria_reads):
        from resource_explorer.a2a_auth import current_caller
        from resource_explorer.workflows.curate import BASIS_NO_ZONES, curation_access, last_decided_by

        registry.record_component_verdict("repo", "p", "src/a", "accepted", "", "", decided_by=ERIN)
        registry.record_component_verdict("repo", "p", "src/b", "accepted", "", "", decided_by=PETER)
        for who in (ERIN, PETER):
            reset = _as(who)
            try:
                for scope in ("src/a", "src/b"):
                    d = curation_access(registry, "repo", "p", scope)
                    assert (d.allowed, d.reason, d.basis) == (True, "", BASIS_NO_ZONES), (who, scope)
            finally:
                current_caller.reset(reset)
        assert last_decided_by(registry, "repo", "p", "src/b") == PETER      # attribution kept, not a gate

    def test_an_element_in_egeria_with_no_zone_is_open(self, registry, egeria, as_erin):
        from resource_explorer.workflows.curate import BASIS_NO_ZONES, curation_access

        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        d = curation_access(registry, "repo", "p", "src/a")
        assert (d.allowed, d.basis) == (True, BASIS_NO_ZONES)
        assert egeria.calls == [("element", "g-a")]

    def test_a_zoned_element_granted_to_the_caller_is_allowed(self, registry, egeria, as_erin):
        from resource_explorer.workflows.curate import BASIS_ZONE_GRANTED, curation_access

        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        egeria.elements["g-a"] = _element("g-a", [SECURED], owners=[PETER])
        egeria.controls[SECURED] = {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}
        egeria.accounts[ERIN] = {"userAccountStatus": "AVAILABLE", "securityGroups": ["salesTeam"]}
        d = curation_access(registry, "repo", "p", "src/a")
        assert (d.allowed, d.reason, d.basis) == (True, "", BASIS_ZONE_GRANTED)

    def test_a_zoned_element_not_granted_is_not_permitted_with_the_zone_named(self, registry, egeria, as_erin):
        from resource_explorer.workflows.curate import BASIS_ZONE_REFUSED, curation_access

        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        egeria.elements["g-a"] = _element("g-a", [SECURED], owners=[PETER])
        egeria.controls[SECURED] = {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}
        egeria.accounts[ERIN] = {"userAccountStatus": "AVAILABLE", "securityGroups": ["hr"]}
        d = curation_access(registry, "repo", "p", "src/a")
        assert (d.allowed, d.basis) == (False, BASIS_ZONE_REFUSED)
        assert d.reason == f"zone {SECURED} does not grant {ERIN} update in Egeria"

    def test_an_unreadable_control_denies_with_the_reason(self, registry, egeria, as_erin):
        from resource_explorer.workflows.curate import BASIS_UNREADABLE, curation_access

        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        egeria.elements["g-a"] = _element("g-a", [SECURED])
        egeria.fail_control = SECURED
        d = curation_access(registry, "repo", "p", "src/a")
        assert (d.allowed, d.basis) == (False, BASIS_UNREADABLE)
        assert d.reason.startswith("could not check access in Egeria (") and "secrets store unreadable" in d.reason

    def test_no_control_is_not_trusted_when_pyegeria_swallows_errors(self, registry, egeria, as_erin, monkeypatch):
        """With PYEGERIA_ENABLE_LOGGER_CATCH on, a failed control read returns None, which would read as "not
        secured" and open the element. It denies instead."""
        from resource_explorer.workflows.curate import BASIS_UNREADABLE, curation_access

        monkeypatch.setattr("resource_explorer.zone_access._pyegeria_swallows_errors", lambda: True)
        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        egeria.elements["g-a"] = _element("g-a", [SECURED])
        d = curation_access(registry, "repo", "p", "src/a")
        assert (d.allowed, d.basis) == (False, BASIS_UNREADABLE) and "PYEGERIA_ENABLE_LOGGER_CATCH" in d.reason

    def test_an_unreadable_element_denies_rather_than_reading_as_no_zones(self, registry, egeria, as_erin):
        from resource_explorer.workflows.curate import BASIS_UNREADABLE, curation_access

        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        egeria.fail_element = "g-a"
        d = curation_access(registry, "repo", "p", "src/a")
        assert (d.allowed, d.basis) == (False, BASIS_UNREADABLE) and "platform unreachable" in d.reason

    def test_configured_publish_zones_apply_to_an_element_not_yet_in_egeria(self, registry, egeria, as_erin,
                                                                           monkeypatch):
        from resource_explorer.workflows.curate import BASIS_ZONE_REFUSED, curation_access

        monkeypatch.setattr("resource_explorer.egeria_identity.configured_publish_zones", lambda: [SECURED])
        egeria.controls[SECURED] = {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}
        egeria.accounts[ERIN] = {"userAccountStatus": "AVAILABLE", "securityGroups": []}
        d = curation_access(registry, "repo", "p", "src/new")
        assert (d.allowed, d.basis) == (False, BASIS_ZONE_REFUSED)
        assert ("element", "src/new") not in egeria.calls

    def test_a_portal_curator_is_allowed_without_reading_egeria(self, registry, no_egeria_reads):
        from resource_explorer.a2a_auth import current_caller
        from resource_explorer.workflows.curate import BASIS_PORTAL_ROLE, curation_access

        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        for role in ("curator", "admin", "CURATOR"):
            reset = _as(ERIN, role=role)
            try:
                d = curation_access(registry, "repo", "p", "src/a")
                assert (d.allowed, d.basis) == (True, BASIS_PORTAL_ROLE), role
            finally:
                current_caller.reset(reset)

    def test_the_a2a_caller_is_the_one_checked(self, registry, egeria):
        """A2A's middleware publishes its caller (auth_source egeria-token) on the same ContextVar."""
        from resource_explorer.a2a_auth import current_caller
        from resource_explorer.workflows.curate import curation_access

        registry.record_materialized_component("repo", "p", "src/a", "qn", "g-a")
        egeria.elements["g-a"] = _element("g-a", [SECURED, PETER])
        egeria.controls[SECURED] = {"associatedSecurityList": {"DEFAULT": ["nobody"]}}
        egeria.accounts[ERIN] = {"securityGroups": []}
        for who, allowed in ((PETER, True), (ERIN, False)):
            reset = _as(who, source="egeria-token")
            try:
                assert curation_access(registry, "repo", "p", "src/a").allowed is allowed, who
            finally:
                current_caller.reset(reset)


# ── 3. the routes: verdicts and Publish ───────────────────────────────────────────────────────────────

from tests.test_architecture_publish_e2e import _seed as _seed_e2e  # noqa: E402
from tests.test_architecture_publish_e2e import world  # noqa: E402,F401 - the fixture

BP = "deployment::a grouping of services"


def _seed(reg, decided=(PETER, PETER, PETER, PETER)):
    """Components A, B (members of blueprint BP) and C (no blueprint), all accepted; `decided` = who decided
    a, b, c and the blueprint (attribution only)."""
    _seed_e2e(reg, "a grouping of services")
    reg.upsert_finding("p", "architecture_recovery", [{
        "check_name": "component", "label": "x",
        "detail": {"name": "C", "slug": "c", "type": "Software Service", "admission": "built"}}],
        surveyed_at="2026-10-09T00:00:00", scope_locator="src/c")
    for scope, who in zip(("src/a", "src/b", "src/c"), decided):
        reg.record_component_verdict("repo", "p", scope, "accepted", "", "", decided_by=who)
    reg.record_component_verdict("repo", "p", BP, "accepted", "", "", verdict_target="blueprint", decided_by=decided[3])


def _zone_the_blueprint(reg, egeria):
    """A and B already in Egeria, and BP too (members still to attach) in a zone that grants ERIN nothing."""
    reg.record_materialized_component("repo", "p", "src/a", "SolutionComponent::repo::p::src/a", "g-a")
    reg.record_materialized_component("repo", "p", "src/b", "SolutionComponent::repo::p::src/b", "g-b")
    reg.record_materialized_blueprint("repo", "p", "deployment", "a grouping of services", "qn-bp", "g-bp")
    egeria.elements["g-bp"] = _element("g-bp", [SECURED], owners=[PETER])
    egeria.controls[SECURED] = {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}
    egeria.accounts[ERIN] = {"securityGroups": []}
    plan = ap.publish_plan(reg, "p")
    assert [c["path"] for c in plan["components"]["to_write"]] == ["src/c"]
    assert [b["key"] for b in plan["blueprints"]["to_write"]] == [BP], "the blueprint still has members to attach"


@pytest.fixture
def web(registry, monkeypatch):
    """The real app with the real curation check; only who is signed in is set."""
    who = {"user_id": ERIN}
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setattr("resource_explorer.auth.get_current_user",
                        lambda request: {"user_id": who["user_id"], "egeria_token": f"tok-{who['user_id']}"})
    from resource_explorer.web.app import app
    return TestClient(app), who


class TestRoutes:
    def test_either_user_may_re_decide_the_others_item_with_no_zones(self, web, registry, no_egeria_reads):
        client, who = web
        _seed(registry, decided=(ERIN, PETER, ERIN, PETER))
        who["user_id"] = ERIN
        r = client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["src/b"], "verdict": "accepted"})
        assert r.status_code == 200, r.text
        who["user_id"] = PETER
        r = client.post("/api/curate/component-verdicts/repo/p", json={"scope_locator": "src/a", "verdict": "accepted"})
        assert r.status_code == 200, r.text
        r = client.post("/api/curate/blueprint-verdicts/repo/p", json={
            "perspective": "deployment", "cluster_name": "a grouping of services", "verdict": "accepted"})
        assert r.status_code == 200, r.text

    def test_the_egeria_git_publish_is_not_refused_for_either_user(self, web, registry, no_egeria_reads):
        client, who = web
        _seed(registry, decided=(ERIN, PETER, ERIN, PETER))
        who["user_id"] = PETER
        r = client.post("/api/projects/p/architecture/publish")
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["queued"] == 4 and out["refused"] == []

    def test_a_refused_verdict_says_why_and_records_nothing(self, web, registry, egeria):
        client, who = web
        _seed(registry)
        _zone_the_blueprint(registry, egeria)
        egeria.elements["g-a"] = _element("g-a", [SECURED], owners=[PETER])
        before = registry.list_component_verdict_history("repo", "p", "src/c")
        r = client.post("/api/projects/p/components/verdicts",
                        json={"scope_locators": ["src/c", "src/a"], "verdict": "rejected"})
        assert r.status_code == 403
        assert r.json()["detail"] == f"zone {SECURED} does not grant {ERIN} update in Egeria"
        assert registry.list_component_verdict_history("repo", "p", "src/c") == before   # nothing half-recorded

    def test_publish_skips_the_item_not_permitted_and_queues_the_rest(self, web, registry, egeria):
        import json as _json

        client, who = web
        _seed(registry)
        _zone_the_blueprint(registry, egeria)
        r = client.post("/api/projects/p/architecture/publish")
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["queued"] == 1
        assert [(x["kind"], x["key"]) for x in out["refused"]] == [("blueprint", BP)]
        target = _json.loads(registry.get_run(out["run_id"])["target"])
        assert target["paths"] == ["src/c"] and target["blueprints"] == []
        assert target["not_permitted"][0]["words"] == f"zone {SECURED} does not grant {ERIN} update in Egeria"

    def test_publish_is_refused_whole_only_when_nothing_is_permitted(self, web, registry, egeria):
        client, who = web
        _seed(registry)
        _zone_the_blueprint(registry, egeria)
        registry.record_materialized_component("repo", "p", "src/c", "SolutionComponent::repo::p::src/c", "g-c")
        r = client.post("/api/projects/p/architecture/publish")
        assert r.status_code == 403
        assert r.json()["detail"] == f"zone {SECURED} does not grant {ERIN} update in Egeria"


# ── 4. end to end: the press, the run, the next read ──────────────────────────────────────────────────

class TestPressToNextRead:
    """Drives enqueue_publish -> run_publish -> publish_plan/last_results with only Egeria's clients faked."""

    def _press_as(self, reg, user):
        import json as _json

        from resource_explorer.a2a_auth import current_caller
        from resource_explorer.workflows.curate import require_curation_rights

        reset = _as(user)
        try:
            out = ap.enqueue_publish(reg, reg.get("p"), ap.publish_plan(reg, "p"), requested_by=user,
                                     authorize=lambda s: require_curation_rights(reg, "repo", "p", s))
        finally:
            current_caller.reset(reset)
        target = _json.loads(reg.get_run(out["run_id"])["target"])
        return out, ap.run_publish(reg, "p", target, out["activity_id"])

    def test_mixed_decided_by_no_zones_one_press_by_either_settles_the_plan(self, world, no_egeria_reads, as_daemon):
        reg, fake, outbox = world
        _seed(reg, decided=(ERIN, PETER, ERIN, PETER))
        out, res = self._press_as(reg, ERIN)
        assert out["refused"] == []
        assert sorted(r["status"] for r in res) == ["done"] * 4
        assert ap.publish_plan(reg, "p")["nothing"] is True

    def test_a_refused_item_is_its_own_result_row_and_the_rest_are_written(self, world, egeria, as_daemon):
        reg, fake, outbox = world
        _seed(reg)
        _zone_the_blueprint(reg, egeria)
        out, res = self._press_as(reg, ERIN)
        by = {r["key"]: r for r in res}
        assert by[BP]["status"] == ap.NOT_PERMITTED
        assert by[BP]["words"] == f"not permitted · zone {SECURED} does not grant {ERIN} update in Egeria"
        assert by["src/c"]["status"] == "done"
        assert outbox == [], "nothing was attached to the refused blueprint"
        last = ap.last_results(reg, "p")
        assert {i["key"]: i["status"] for i in last["items"]} == {BP: "not_permitted", "src/c": "done"}
        # The next read: C is in Egeria; the refused blueprint still waits for someone permitted to publish it.
        plan = ap.publish_plan(reg, "p")
        assert plan["components"]["to_write"] == []
        assert [b["key"] for b in plan["blueprints"]["to_write"]] == [BP]


# ── 5. the CLI uses the same function ─────────────────────────────────────────────────────────────────

def test_the_cli_publish_asks_curation_access(registry, monkeypatch):
    import typer

    from resource_explorer.cli import runs_commands as rc
    from resource_explorer.workflows import curate as wc

    _seed(registry)
    monkeypatch.setattr(rc, "_registry", lambda: registry)
    monkeypatch.setattr("resource_explorer.cli.session.require_and_activate", lambda console=None: None)
    monkeypatch.setattr("resource_explorer.run_queue.requested_by", lambda: ERIN)
    asked = []

    def spy(reg, entity_type, slug, scope, **kw):
        asked.append((entity_type, slug, scope))
        return wc.AccessDecision(False, f"zone {SECURED} does not grant {ERIN} update in Egeria",
                                 wc.BASIS_ZONE_REFUSED)
    monkeypatch.setattr(wc, "curation_access", spy)
    with pytest.raises(typer.Exit) as exc:
        rc.curate_materialize("p", "src/a", entity_type="repo")
    assert exc.value.exit_code == 3
    assert asked == [("repo", "p", "src/a")]
