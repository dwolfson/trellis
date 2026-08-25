"""Investigations — the framing step ahead of Scouting.

`docs/investigation-framing-design.md` §1. These pin the two decisions that make
promotion to Egeria a fill-in rather than a migration, and the one validation
that stops a purpose silently ranking nothing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def made(client):
    created = []

    def _make(**kw):
        body = {"display_name": "Test Investigation", **kw}
        r = client.post("/api/investigations/", json=body)
        assert r.status_code == 200, r.text
        created.append(r.json()["slug"])
        return r.json()

    yield _make
    from resource_explorer.registry import ProjectRegistry
    reg = ProjectRegistry()
    with reg._conn() as conn:
        for slug in created:
            # EVERY collection this investigation owns, not just its folio. An
            # investigation now has a Folio plus one WorkingSet per disposition
            # in use, so a cleanup that hand-lists one leaks the rest into the
            # next test — which is how these passed alone and failed in suite.
            rows = conn.execute(
                "SELECT working_set_slug FROM investigation_resource_lists WHERE investigation_slug = ?",
                (slug,),
            ).fetchall()
            for r in rows:
                ws = r["working_set_slug"]
                conn.execute("DELETE FROM working_set_members WHERE working_set_slug = ?", (ws,))
                conn.execute("DELETE FROM working_sets WHERE slug = ?", (ws,))
            conn.execute("DELETE FROM investigation_resource_lists WHERE investigation_slug = ?", (slug,))
            conn.execute("DELETE FROM investigations WHERE slug = ?", (slug,))


def test_purposes_are_served_not_hardcoded_in_the_spa(client):
    """The UI must not carry its own copy of this vocabulary.

    Purpose is ProjectCharter.purposes (§2), and the same eight values all 41
    catalog questions are tagged with. A second copy in the SPA is exactly the
    frontend/backend mirror that has drifted twice in this codebase already.
    """
    r = client.get("/api/investigations/purposes")
    assert r.status_code == 200
    assert r.json()["purposes"] == [
        "Assess", "Certify", "Deploy", "Explore", "Learn", "Maintain", "Select", "Share",
    ]


def test_an_investigation_starts_local_with_no_egeria_write(made):
    """§1's third starting mode, and the structural decision behind it.

    One local row in all three modes, with a nullable egeria_project_guid, so
    promotion later is a fill-in rather than a migration.
    """
    inv = made(display_name="Local Only", purposes=["Explore"])
    assert inv["egeria_project_guid"] == ""
    assert inv["status"] == "open"
    assert inv["purposes"] == ["Explore"]


def test_an_unknown_purpose_is_rejected_rather_than_stored(client):
    """A purpose outside the vocabulary would rank nothing and look like an
    empty result — indistinguishable from 'nothing matched'."""
    r = client.post("/api/investigations/",
                    json={"display_name": "Bad", "purposes": ["Nonsense"]})
    assert r.status_code == 400
    assert "Nonsense" in r.json()["detail"]


def test_membership_goes_through_a_working_set(client, made):
    """Storage mirrors Egeria's real two-hop shape:

        Project --ResourceList--> WorkingSet --CollectionMembership--> resource

    A flat Project->resource link (which an earlier pass here used, and which
    design §6 itself sketched) has nowhere to put a per-resource rationale and
    makes the working set unnameable. The API stays flat because every caller
    only wants "what is in scope"; the two hops are a storage-fidelity decision
    so promotion to Egeria is a replay rather than a migration.
    """
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Two Hop")
    reg = ProjectRegistry()

    # A brand-new investigation has NO working set — that is what makes the
    # empty sidebar an honest prompt rather than an empty shell.
    assert reg.investigation_working_set_slug(inv["slug"]) == ""

    r = client.post(f"/api/investigations/{inv['slug']}/members", json={
        "entity_type": "repo", "entity_slug": "milvus",
        "membership_rationale": "already adopted; tracking health",
    })
    assert r.status_code == 200
    assert r.json()[0]["membership_rationale"] == "already adopted; tracking health"

    # ...and the working set was created lazily, on first use.
    ws_slug = reg.investigation_working_set_slug(inv["slug"])
    assert ws_slug
    assert reg.get_working_set(ws_slug)["members"][0]["entity_slug"] == "milvus"

    assert client.get(f"/api/investigations/{inv['slug']}").json()["member_count"] == 1

    d = client.delete(f"/api/investigations/{inv['slug']}/members/repo/milvus")
    assert d.status_code == 200 and d.json() == []


def test_members_on_a_missing_investigation_404s(client):
    assert client.get("/api/investigations/nope/members").status_code == 404


class _StubPM:
    def __init__(self, guid="proj-1", fail=False):
        self.guid, self.fail, self.calls = guid, fail, []

    def create_egeria_bearer_token(self):
        pass

    def create_project(self, display_name=None, description=None, body=None, **kw):
        self.calls.append(("create_project", display_name, description, body))
        if self.fail:
            raise RuntimeError("Egeria unreachable")
        return self.guid


class _StubCM:
    def __init__(self):
        self.attached, self.members = [], []

    def create_egeria_bearer_token(self):
        pass

    def create_collection(self, display_name=None, description=None, **kw):
        return "coll-1"

    def attach_collection(self, parent_guid, collection_guid, body=None):
        self.attached.append((parent_guid, collection_guid))

    def add_to_collection(self, collection_guid, element_guid, body=None):
        self.members.append((collection_guid, element_guid))


def test_promotion_replays_the_local_shape_into_egeria(made):
    """Project -> Collection -> ResourceList -> CollectionMembership, in that
    order, from rows that already had that shape."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    inv = made(display_name="Promote Me", purposes=["Certify"])
    reg = ProjectRegistry()
    ws = reg.get_or_create_working_set(inv["slug"])
    reg.add_working_set_member(ws["slug"], "repo", "never-published-repo")

    pm, cm = _StubPM(), _StubCM()
    res = EgeriaInvestigationPublisher(reg, project_manager=pm, collection_manager=cm).promote(inv["slug"])

    assert res.project_guid == "proj-1"
    assert res.collection_guid == "coll-1"
    assert res.resource_list_linked
    # Purposes must survive, and must land in additionalProperties rather than
    # being appended to free text: mission/purposes are ProjectCharter (0442)
    # properties that create_project cannot reach, and Project is a
    # Referenceable, so additionalProperties is the sanctioned carrier.
    props = pm.calls[0][3]["properties"]
    assert "Certify" in props["additionalProperties"]["purposes"]
    assert "Certify" not in (props.get("description") or "")


def test_a_member_with_no_egeria_asset_is_reported_not_invented(made):
    """The honest half. A repo never published to Egeria has no asset GUID; the
    promotion says so per member rather than silently dropping it or fabricating
    a link."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    inv = made(display_name="Partial Promote")
    reg = ProjectRegistry()
    ws = reg.get_or_create_working_set(inv["slug"])
    reg.add_working_set_member(ws["slug"], "repo", "definitely-not-published-xyz")

    cm = _StubCM()
    res = EgeriaInvestigationPublisher(reg, project_manager=_StubPM(), collection_manager=cm).promote(inv["slug"])

    assert res.members_linked == []
    assert len(res.members_unlinkable) == 1
    assert "not published to Egeria yet" in res.members_unlinkable[0]["reason"]
    assert cm.members == []


def test_an_unreachable_egeria_fails_loudly_and_binds_nothing(made):
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    inv = made(display_name="No Egeria")
    reg = ProjectRegistry()
    res = EgeriaInvestigationPublisher(
        reg, project_manager=_StubPM(fail=True), collection_manager=_StubCM()
    ).promote(inv["slug"])

    assert not res.ok
    assert res.project_guid == ""
    assert any("create_project failed" in e for e in res.errors)
    assert reg.get_investigation(inv["slug"])["egeria_project_guid"] == ""


def test_promoting_an_already_bound_investigation_is_refused(made):
    """Two Projects for one body of work is worse than none."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    inv = made(display_name="Already Bound")
    reg = ProjectRegistry()
    reg.set_investigation_egeria_project(inv["slug"], {
        "status": "linked", "egeria_project_guid": "existing-guid",
    })
    res = EgeriaInvestigationPublisher(
        reg, project_manager=_StubPM(), collection_manager=_StubCM()
    ).promote(inv["slug"])
    assert not res.ok
    assert any("already bound" in e for e in res.errors)


def test_promote_route_does_not_call_pyegeria_on_the_event_loop(client, made, monkeypatch):
    """Regression for a bug a CLI test structurally cannot catch.

    pyegeria's synchronous methods drive their own event loop internally. Called
    inline from an async FastAPI route they raise "this event loop is already
    running" — but exercised from a script, where no loop is running, they work
    perfectly. So the promoter passed every test and failed the moment a human
    clicked the button.

    This asserts the work happens off the loop: the stub raises if it finds a
    running loop, exactly as pyegeria effectively does.
    """
    import asyncio

    from resource_explorer.surveyors import egeria_investigation_publisher as mod

    inv = made(display_name="Loop Check")

    class _LoopSensitivePublisher:
        def __init__(self, registry, **kw):
            pass

        def promote(self, slug):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                from resource_explorer.surveyors.egeria_investigation_publisher import (
                    PromotionResult,
                )
                return PromotionResult(project_guid="off-loop-ok")
            raise RuntimeError("this event loop is already running")

    monkeypatch.setattr(mod, "EgeriaInvestigationPublisher", _LoopSensitivePublisher)
    r = client.post(f"/api/investigations/{inv['slug']}/promote")
    assert r.status_code == 200, r.text
    assert r.json()["project_guid"] == "off-loop-ok", (
        "promote ran on the event loop — pyegeria's sync wrappers cannot be "
        "called inline from an async route"
    )


def test_a_qualified_name_collision_is_explained_not_dumped(made):
    """Egeria signals "this qualifiedName is taken" as a 409 inside a large Java
    error payload. Raw, it tells a user nothing and fills the toast with a stack
    trace. It is also the single most likely real failure here — it happens
    whenever a promotion succeeded and the local binding was later cleared,
    which orphans the Project.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    inv = made(display_name="Collision")

    class _CollidingPM(_StubPM):
        def create_project(self, display_name=None, description=None, body=None, **kw):
            raise RuntimeError(
                "PyegeriaAPIException: OMAG-COMMON-409-001 ... qualifiedName is defined "
                "as a unique property and value Project::Investigation::collision is not "
                "available for use"
            )

    res = EgeriaInvestigationPublisher(
        ProjectRegistry(), project_manager=_CollidingPM(), collection_manager=_StubCM()
    ).promote(inv["slug"])

    assert not res.ok
    joined = " ".join(res.errors)
    assert "already" in joined and "Bind to the existing" in joined
    assert "OMAG-COMMON" not in joined, "raw Egeria payload leaked to the user"


def test_binding_an_existing_project_also_gets_a_working_set(made, monkeypatch):
    """Both routes to a Project need the same next thing.

    Promotion created a Project AND a Collection, so it worked by accident.
    Binding to an existing Project recorded the GUID and stopped, leaving the
    investigation with nowhere in Egeria for its membership to live — the gap
    only existed because one path happened to do both.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors import egeria_investigation_publisher as mod

    inv = made(display_name="Bind And Set")
    reg = ProjectRegistry()
    cm = _StubCM()

    real_managers = mod.EgeriaInvestigationPublisher._managers
    monkeypatch.setattr(mod.EgeriaInvestigationPublisher, "_managers",
                        lambda self: (_StubPM(), cm))

    res = mod.EgeriaInvestigationPublisher(reg).ensure_working_set(inv["slug"])
    assert not res.ok  # unbound: refuses rather than inventing a Project
    assert any("not bound" in e for e in res.errors)

    reg.set_investigation_egeria_project(inv["slug"], {
        "status": "linked", "egeria_project_guid": "existing-proj",
    })
    res = mod.EgeriaInvestigationPublisher(reg).ensure_working_set(inv["slug"])
    assert res.collection_guid == "coll-1"
    assert res.resource_list_linked
    assert cm.attached == [("existing-proj", "coll-1")]

    # Idempotent: a second call must not create a second Collection.
    res2 = mod.EgeriaInvestigationPublisher(reg).ensure_working_set(inv["slug"])
    assert res2.collection_guid == "coll-1"
    assert cm.attached == [("existing-proj", "coll-1")], "created a duplicate Collection"
    monkeypatch.setattr(mod.EgeriaInvestigationPublisher, "_managers", real_managers)


def test_a_failed_adoption_check_is_reported_because_that_is_when_duplicates_happen(made, monkeypatch):
    """Caught by the no-silent-success ratchet, on my own code.

    ensure_working_set asks Egeria what is already attached before creating
    anything. If that lookup fails it still proceeds — a missing working set
    should not be blocked by an unreadable list — but failing to look is
    precisely the moment a duplicate Collection gets made, so it cannot be
    swallowed into a debug log.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors import egeria_investigation_publisher as mod

    inv = made(display_name="Blind Adoption")
    reg = ProjectRegistry()
    reg.set_investigation_egeria_project(inv["slug"], {
        "status": "linked", "egeria_project_guid": "proj-x",
    })

    class _BlindCM(_StubCM):
        def get_attached_collections(self, parent_guid, **kw):
            raise RuntimeError("listing unavailable")

    monkeypatch.setattr(mod.EgeriaInvestigationPublisher, "_managers",
                        lambda self: (_StubPM(), _BlindCM()))
    res = mod.EgeriaInvestigationPublisher(reg).ensure_working_set(inv["slug"])

    assert res.collection_guid == "coll-1", "should still create the missing working set"
    assert any("may have created a second" in e for e in res.errors), (
        "a failed adoption check was not surfaced — that is when duplicates happen"
    )


def test_a_repo_inherits_its_project_binding_from_the_investigation(made):
    """Membership answers the publish gate's question.

    An investigation IS the context everything else runs inside, so when a repo
    sits in the working set of one bound to an Egeria Project, that binding
    already says which Project it belongs to. Asking again per resource asks a
    question that has been answered — which is what left 17 repos unpublishable
    after an Egeria reseed.
    """
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Inheriting")
    reg = ProjectRegistry()
    reg.set_investigation_egeria_project(inv["slug"], {
        "status": "linked", "egeria_project_guid": "proj-inherit",
        "egeria_project_qualified_name": "Project::Inherit",
    })
    ws = reg.get_or_create_working_set(inv["slug"])

    # Not a member yet: nothing to inherit, so the gate must still prompt.
    assert reg.inherited_egeria_project_context("repo", "some-unrelated-repo") is None

    reg.add_working_set_member(ws["slug"], "repo", "some-unrelated-repo")
    got = reg.inherited_egeria_project_context("repo", "some-unrelated-repo")
    assert got and got["egeria_project_guid"] == "proj-inherit"
    assert got["_inherited_from"] == inv["slug"]


def test_only_a_linked_investigation_supplies_a_binding(made):
    """personal / declined / deferred are deliberate answers about the
    INVESTIGATION; none of them names a Project a member could inherit. Treating
    them as inheritable would publish a repo into a Project nobody chose."""
    from resource_explorer.registry import ProjectRegistry

    reg = ProjectRegistry()
    for status in ("personal", "declined", "deferred", "unset"):
        inv = made(display_name=f"Not Linked {status}")
        reg.set_investigation_egeria_project(inv["slug"], {
            "status": status, "egeria_project_guid": "",
        })
        ws = reg.get_or_create_working_set(inv["slug"])
        reg.add_working_set_member(ws["slug"], "repo", f"probe-{status}")
        assert reg.inherited_egeria_project_context("repo", f"probe-{status}") is None, (
            f"'{status}' must not supply a Project binding"
        )


def test_an_excluded_member_does_not_inherit(made):
    """§7's excluded state means "considered and ruled out" — it must not carry
    the investigation's Project binding with it."""
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Excluding")
    reg = ProjectRegistry()
    reg.set_investigation_egeria_project(inv["slug"], {
        "status": "linked", "egeria_project_guid": "proj-x",
    })
    ws = reg.get_or_create_working_set(inv["slug"])
    reg.add_working_set_member(ws["slug"], "repo", "ruled-out-repo", state="excluded")
    assert reg.inherited_egeria_project_context("repo", "ruled-out-repo") is None


def test_a_folio_holds_scope_and_working_sets_hold_dispositions(made):
    """The correction that prompted this: a WorkingSet carries a SINGLE
    Disposition, so one per investigation cannot be the membership list.

    Folio = everything in scope. WorkingSet = the resources carrying one
    disposition. A resource's disposition within an investigation IS which
    WorkingSet it sits in, so nothing stores it twice.
    """
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Folio Model")
    reg = ProjectRegistry()

    folio = reg.get_or_create_folio(inv["slug"])
    assert folio["collection_kind"] == "folio"
    assert folio["disposition"] == ""

    reg.set_investigation_disposition(inv["slug"], "repo", "alpha", "tracking")
    reg.set_investigation_disposition(inv["slug"], "repo", "beta", "using")

    by_disp = reg.investigation_dispositions(inv["slug"])
    assert sorted(by_disp) == ["tracking", "using"]
    # in scope regardless of judgement
    assert {m["entity_slug"] for m in reg.list_investigation_members(inv["slug"])} == {"alpha", "beta"}


def test_changing_a_disposition_moves_rather_than_adds(made):
    """A WorkingSet carries one disposition, so membership of two would assert
    two contradictory judgements about the same resource at once."""
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Moving")
    reg = ProjectRegistry()
    reg.set_investigation_disposition(inv["slug"], "repo", "gamma", "investigating")
    reg.set_investigation_disposition(inv["slug"], "repo", "gamma", "abandoned")

    by_disp = reg.investigation_dispositions(inv["slug"])
    holding = [d for d, ms in by_disp.items() if any(m["entity_slug"] == "gamma" for m in ms)]
    assert holding == ["abandoned"], f"in {len(holding)} sets at once: {holding}"
    assert reg.disposition_of(inv["slug"], "repo", "gamma") == "abandoned"


def test_clearing_a_disposition_leaves_it_in_scope(made):
    """In scope but unjudged is the normal state straight after scouting, and
    must be expressible — otherwise clearing a decision would silently remove
    the resource from the investigation."""
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Unjudged")
    reg = ProjectRegistry()
    reg.set_investigation_disposition(inv["slug"], "repo", "delta", "tracking")
    reg.set_investigation_disposition(inv["slug"], "repo", "delta", "")

    assert reg.disposition_of(inv["slug"], "repo", "delta") == ""
    assert any(m["entity_slug"] == "delta" for m in reg.list_investigation_members(inv["slug"]))


def test_undecided_is_not_a_working_set(made):
    """"Nobody has judged this" is the ABSENCE of a WorkingSet. Creating one for
    it would make an unjudged resource indistinguishable from one deliberately
    marked undecided."""
    from resource_explorer.registry import ProjectRegistry
    import pytest as _pytest

    reg = ProjectRegistry()
    assert "undecided" not in reg.WORKING_SET_DISPOSITIONS
    inv = made(display_name="No Undecided Set")
    with _pytest.raises(ValueError):
        reg.get_or_create_disposition_set(inv["slug"], "undecided")


def test_dispositions_route_returns_what_the_filter_needs(client, made):
    """The left-column chips read this directly, so its shape is a contract."""
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Chips")
    reg = ProjectRegistry()
    reg.set_investigation_disposition(inv["slug"], "repo", "one", "tracking")
    reg.set_investigation_disposition(inv["slug"], "repo", "two", "using")

    r = client.get(f"/api/investigations/{inv['slug']}/dispositions")
    assert r.status_code == 200
    body = r.json()
    assert sorted(body) == ["tracking", "using"]
    assert body["tracking"][0]["entity_slug"] == "one"


def test_only_dispositions_in_use_are_returned(client, made):
    """An investigation where nothing is abandoned must not offer an 'abandoned'
    chip that always matches nothing — an always-empty filter reads as broken
    rather than as an empty category."""
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Sparse")
    reg = ProjectRegistry()
    reg.set_investigation_disposition(inv["slug"], "repo", "solo", "tracking")

    body = client.get(f"/api/investigations/{inv['slug']}/dispositions").json()
    assert list(body) == ["tracking"]
    assert len(body) < len(reg.WORKING_SET_DISPOSITIONS)


def test_an_unknown_disposition_is_rejected(client, made):
    inv = made(display_name="Bad Disposition")
    r = client.post(f"/api/investigations/{inv['slug']}/dispositions/repo/x?disposition=nonsense")
    assert r.status_code == 400
    assert "nonsense" in r.json()["detail"]


def test_a_disposition_member_is_always_in_the_folio(made):
    """Why the disposition filter can compose with the working-set filter.

    set_investigation_disposition adds to the Folio BEFORE assigning, so a
    disposition member is in scope by construction. That is what makes
    "working set AND disposition" safe to combine — the intersection can never
    be spuriously empty, so the UI must not widen the base filter to compensate
    for a problem that cannot occur.

    It also matters for intent: disposition exists so an investigation can focus
    on what matters within it. Widening to every registered repo would discard
    that focus at the moment the user asked for it.
    """
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Composes")
    reg = ProjectRegistry()
    reg.set_investigation_disposition(inv["slug"], "repo", "never-added-first", "tracking")

    in_scope = {(m["entity_type"], m["entity_slug"])
                for m in reg.list_investigation_members(inv["slug"])}
    for disposition, members in reg.investigation_dispositions(inv["slug"]).items():
        for m in members:
            assert (m["entity_type"], m["entity_slug"]) in in_scope, (
                f"{m['entity_slug']} is '{disposition}' but not in the Folio — "
                "the two filters would then disagree"
            )


def test_next_steps_retire_as_the_gaps_close(client, made):
    """Offers, not a checklist to fill in.

    The creation form asks only what §1 says an investigation IS — a name, why
    it exists, and what kind of work it is. Everything else surfaces here, where
    the absence already is, and disappears when it stops being true. A step that
    lingered after being satisfied would train people to ignore the list.
    """
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Retiring", purposes=["Select"])
    reg = ProjectRegistry()
    slug = inv["slug"]

    def ids():
        return [s["id"] for s in client.get(f"/api/investigations/{slug}/next-steps").json()["steps"]]

    assert ids() == ["add_resources", "bind_egeria"]

    ws = reg.get_or_create_folio(slug)
    reg.add_working_set_member(ws["slug"], "repo", "some-repo")
    assert ids() == ["set_dispositions", "bind_egeria"], "scope offer should retire once scoped"

    reg.set_investigation_disposition(slug, "repo", "some-repo", "investigating")
    assert ids() == ["bind_egeria"], "judgement offer should retire once judged"

    reg.set_investigation_egeria_project(slug, {
        "status": "linked", "egeria_project_guid": "g",
    })
    body = client.get(f"/api/investigations/{slug}/next-steps").json()
    assert body["steps"] == [] and body["complete"] is True


def test_a_purposeless_investigation_is_told_so(client, made):
    """Purpose is the one field that does real work — it ranks what gets
    proposed — so its absence is worth surfacing rather than defaulting."""
    inv = made(display_name="No Purpose", purposes=[])
    ids = [s["id"] for s in client.get(f"/api/investigations/{inv['slug']}/next-steps").json()["steps"]]
    assert "declare_purpose" in ids


def test_classification_is_recorded_and_validated(client, made):
    """§1 mode 2 carries a classification. Kept even for a local-only
    investigation, so promoting later does not re-ask something already decided."""
    inv = made(display_name="Kinded", project_classification="Campaign")
    assert inv["project_classification"] == "Campaign"
    bad = client.post("/api/investigations/", json={"display_name": "Bad Kind",
                                                    "project_classification": "Nonsense"})
    assert bad.status_code == 400
