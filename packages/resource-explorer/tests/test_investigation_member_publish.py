"""Publish an investigation's unpublished members (owner, 2026-10-13).

Live on `privacy-proof-2026-10-13`: 14 repositories in scope, Publish, Relink members, still "not linked", and
link-status said why for each ("not in Egeria yet — no asset GUID"). Publish on an investigation publishes its
Project, not its members. Now: the Relink/Publish result says so in words from link-status, each member row says
"not published", and the page offers [Publish the N unpublished members], whose plan and press are one function and
whose members go through RE's existing per-repository publish (`repo_publish.publish_report`).

The only fake is the pyegeria client boundary: `egeria_clients._build` hands back `create_autospec(<real pyegeria
class>, instance=True, spec_set=True)` per identity (the `ZonedEgeria` of the attach-as-owner tests, extended with
the publish clients), so every call binds the real signature and records who sent it and what body. Registry: real,
temp sqlite. Routes: the real FastAPI app. The kept survey is recorded through `survey_snapshot.record_step`.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_private_investigation_attach_as_owner import PLATFORM, PRIVATE, ZonedEgeria  # noqa: E402
from test_zone_access_investigations_worklists import registry, web  # noqa: E402,F401  (shared fixtures)

from resource_explorer.registry import Project  # noqa: E402

ALICE = "alice"
NO_ELEMENTS = "No elements found"


class PublishingEgeria(ZonedEgeria):
    """`ZonedEgeria` plus the clients a repository publish builds: every create body is recorded with its user."""

    def __init__(self):
        super().__init__()
        self.creates: list[tuple[str, dict]] = []          # (user, body) for every create_asset
        self.zoned: list[tuple[str, str, list]] = []        # (user, guid, zones) for every add_zone_membership
        self.reports: dict[str, list[str]] = {}             # asset guid -> report guids
        self.fail_create_for: set[str] = set()              # qualifiedName fragments whose create raises
        self.hide_reports = False                           # the asset read shows no reports (not read back yet)

    def build(self, cls, view_server, platform_url, user_id, password):
        inst = super().build(cls, view_server, platform_url, user_id, password)
        name, user = cls.__name__, user_id
        if name == "AssetMaker":
            inst.find_assets.side_effect = lambda *a, **k: NO_ELEMENTS
            inst.create_asset.side_effect = lambda *a, body=None, **k: self._create_asset(user, body)
            inst.get_asset_by_guid.side_effect = lambda guid, *a, **k: self._asset(user, guid)
            inst.create_software_capability.side_effect = lambda *a, body=None, **k: self._new("s")
            inst.add_capability_asset_use.side_effect = lambda *a, **k: None
        elif name == "AutomatedCuration":
            inst.get_guid_for_name.side_effect = lambda *a, **k: NO_ELEMENTS
        elif name == "ClassificationExplorer":
            real_zone = inst.add_zone_membership.side_effect

            def zone(guid, body, *a, **k):
                self.zoned.append((user, guid, list(body["properties"]["zoneMembership"])))
                return real_zone(guid, body, *a, **k)
            inst.add_zone_membership.side_effect = zone
            inst.add_ownership_to_element.side_effect = lambda *a, **k: None
        return inst

    def _create_asset(self, user, body):
        props = (body or {}).get("properties") or {}
        qn = props.get("qualifiedName") or ""
        if any(f in qn for f in self.fail_create_for):
            raise ConnectionError(f"Egeria went away creating {qn}")
        self.creates.append((user, body))
        guid = self._new("a")
        parent = (body or {}).get("parentGUID") or ""
        # An element created with zones is in them; a report is anchored to its asset until zoned itself.
        self.elements[guid] = {"zones": list(props.get("zoneMembership") or []), "anchor": "", "kinds": []}
        if parent:
            self.reports.setdefault(parent, []).append(guid)
            self.elements[guid]["qn"] = qn
        self.requests.append((user, "create_asset", guid))
        return guid

    def readable_by(self, user: str, guid: str) -> bool:
        """A second user's read, as Egeria's zone check answers it."""
        try:
            self._gate(user, "read", guid)
            return True
        except Exception:  # noqa: BLE001 - the real-shaped 403
            return False

    def _asset(self, user, guid):
        self._gate(user, "get_asset_by_guid", guid)
        if self.hide_reports:
            return {"elementHeader": {"guid": guid}, "reports": []}
        return {"elementHeader": {"guid": guid}, "reports": [
            {"relatedElement": {"elementHeader": {"guid": r, "versions": {"createTime": "2026-10-13T00:00:00"}},
                                "properties": {"qualifiedName": self.elements[r].get("qn", ""),
                                               "additionalProperties": {"annotation_count": "1"}}}}
            for r in self.reports.get(guid, [])]}

    def asset_creates(self) -> list[tuple[str, dict]]:
        return [(u, b) for u, b in self.creates if not b.get("parentGUID")]

    def report_creates(self) -> list[tuple[str, dict]]:
        return [(u, b) for u, b in self.creates if b.get("parentGUID")]


@pytest.fixture
def world(web, registry, monkeypatch):
    """alice signed in; the private zone enforced; pyegeria faked at its construction; three repos, `pub`
    already published (its asset `g-pub`), `new1` and `new2` never published, each with a kept survey."""
    from resource_explorer import config as re_config
    from resource_explorer import egeria_clients
    from resource_explorer import egeria_identity as ident
    from resource_explorer.surveyors import survey_snapshot
    from resource_explorer.surveyors.survey_report import ClassificationAnnotation

    monkeypatch.setattr(re_config.get_config().egeria, "platform_url", PLATFORM)
    monkeypatch.setenv("EXPLORER_EGERIA_PLATFORM_NAME", "Quickstart platform")
    monkeypatch.delenv("EXPLORER_PRIVATE_ZONE", raising=False)
    monkeypatch.delenv("EXPLORER_DRAFT_ZONE", raising=False)
    monkeypatch.setattr(ident, "configured_publish_zones", lambda: [])
    monkeypatch.setattr(ident, "_private_zone_state", {"status": "exists", "enforced": True,
                                                       "zone": PRIVATE, "control_present": True})
    eg = PublishingEgeria()
    monkeypatch.setattr(egeria_clients, "_build", eg.build)
    for slug in ("pub", "new1", "new2"):
        registry.add(Project(slug=slug, display_name=slug.upper(), github_url=f"https://github.com/x/{slug}",
                             description=""))
        survey_snapshot.record_step(registry, slug, "repo_language", "2026-10-13T00:00:00", [
            ClassificationAnnotation(summary="Python", analysis_step="repo_language", check_name="c",
                                     item_key="python")])
    registry.set_egeria_asset_guid("pub", "g-pub")
    eg.elements["g-pub"] = {"zones": [], "anchor": "", "kinds": []}
    client, who = web
    who["user_id"] = ALICE
    return {"client": client, "who": who, "registry": registry, "eg": eg}


def _investigation(world, classification: str = "PersonalProject") -> str:
    c = world["client"]
    r = c.post("/api/investigations/", json={"display_name": "Members", "project_classification": classification})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    for s in ("pub", "new1", "new2"):
        r = c.post(f"/api/investigations/{slug}/members", json={"entity_type": "repo", "entity_slug": s})
        assert r.status_code == 200, r.text
    r = c.post(f"/api/investigations/{slug}/promote")
    assert r.status_code == 200, r.text
    return slug


def _press(world, slug: str):
    """The page's press: read the plan, then send back exactly the slugs it named."""
    c = world["client"]
    plan = c.get(f"/api/investigations/{slug}/publish-members").json()
    return c.post(f"/api/investigations/{slug}/publish-members", json={"slugs": plan["slugs"]})


def _wait(world, slug: str, batch: str) -> dict:
    c = world["client"]
    for _ in range(400):
        r = c.get(f"/api/investigations/{slug}/publish-members/{batch}")
        assert r.status_code == 200, r.text
        if not r.json()["running"]:
            return r.json()
        time.sleep(0.05)
    raise AssertionError("the members publish did not finish")


def _press_and_wait(world, slug: str) -> dict:
    r = _press(world, slug)
    assert r.status_code == 200, r.text
    batch = r.json()["batch_id"]
    assert batch
    return _wait(world, slug, batch)


# ── 1. the e2e: plan, press as the owner, private zones, results, relink ───────────────────────────────

def test_owner_publishes_the_unpublished_members_private_then_relinks_all(world):
    c, eg, reg = world["client"], world["eg"], world["registry"]
    slug = _investigation(world)

    # Before: link-status says why, in words, and marks the two members "not published".
    ls = c.get(f"/api/investigations/{slug}/link-status").json()
    by = {m["entity_slug"]: m for m in ls["members"]}
    assert by["new1"]["not_published"] is True and by["new2"]["not_published"] is True
    assert "not_published" not in by["pub"]
    assert ls["not_published"] == 2
    assert "2 members are not in Egeria yet (not published)" in ls["summary"], ls["summary"]

    # The plan lists exactly the two, from the function the press runs.
    plan = c.get(f"/api/investigations/{slug}/publish-members").json()
    assert [m["entity_slug"] for m in plan["publish"]] == ["new1", "new2"]
    assert plan["count"] == 2 and plan["waiting"] == []
    assert plan["words"] == "will publish 2 repos: new1, new2"
    assert [m["entity_slug"] for m in plan["already_published"]] == ["pub"]

    out = _press_and_wait(world, slug)

    assert {m["entity_slug"]: m["state"] for m in out["members"]} == {"new1": "published", "new2": "published"}
    assert out["words"] == ["2 published"]
    assert out["relink_next"] is True
    # Each was published by the per-repository publish, AS ALICE, and its proof row exists.
    for s in ("new1", "new2"):
        assert reg.get_egeria_asset_guid(s)
        assert any(p["proof"] == "report_published" and p["recorded_by"] == ALICE
                   for p in reg.list_catalogue_commit_proofs(s)), reg.list_catalogue_commit_proofs(s)
    # The assets were created as alice (their zones: see the §3.6 test below).
    assets = eg.asset_creates()
    assert len(assets) == 2 and {u for u, _b in assets} == {ALICE}
    # Each produced SurveyReport ends up zoned [private, alice], as alice.
    for user, body in eg.report_creates():
        assert user == ALICE
    report_guids = [g for guids in eg.reports.values() for g in guids]
    assert len(report_guids) == 2
    for g in report_guids:
        assert (ALICE, g, [PRIVATE, ALICE]) in eg.zoned, eg.zoned
        assert eg.elements[g]["zones"] == [PRIVATE, ALICE]

    # Relink afterwards links all three, as alice, and link-status reads them back as linked.
    r = c.post(f"/api/investigations/{slug}/relink-members")
    assert r.status_code == 200, r.text
    folio = r.json()["collection_guid"]
    assert sorted(eg.members[folio]) == sorted(["g-pub", reg.get_egeria_asset_guid("new1"),
                                                reg.get_egeria_asset_guid("new2")])
    for asset in eg.members[folio]:
        assert (ALICE, "add_to_collection", asset) in eg.requests
    after = r.json()["link_status"]
    assert after["counts"]["linked"] == 3 and after["not_published"] == 0, after
    assert after["summary"] == ["nothing to link"], after["summary"]


def test_relink_with_unpublished_members_says_why_in_words(world):
    c = world["client"]
    slug = _investigation(world)
    r = c.post(f"/api/investigations/{slug}/relink-members")
    assert r.status_code == 200, r.text
    words = r.json()["link_status"]["summary"]
    assert words == ["nothing to link", "2 members are not in Egeria yet (not published)"], words


# ── 2. a non-owner never reaches it ────────────────────────────────────────────────────────────────────

def test_a_non_owner_cannot_plan_or_press(world):
    c, eg = world["client"], world["eg"]
    slug = _investigation(world)
    n = len(eg.requests)
    world["who"]["user_id"] = "mallory"
    assert c.get(f"/api/investigations/{slug}/publish-members").status_code == 404
    assert c.post(f"/api/investigations/{slug}/publish-members", json={"slugs": ["new1", "new2"]}).status_code == 404
    assert eg.requests[n:] == [] and eg.asset_creates() == []
    assert not world["registry"].get_egeria_asset_guid("new1")


def test_the_owner_words_when_the_route_sees_it_but_the_caller_is_not_the_owner(world, monkeypatch):
    """A caller who can SEE the private investigation (e.g. a scoped read that shows it) but is not its owner
    is refused with #640's owner words, before anything is planned."""
    from resource_explorer.registry import ProjectRegistry

    c, eg = world["client"], world["eg"]
    slug = _investigation(world)
    inv = world["registry"].get_investigation(slug)
    monkeypatch.setattr(ProjectRegistry, "get_investigation", lambda self, s, *a, **k: dict(inv))
    world["who"]["user_id"] = "mallory"
    r = c.post(f"/api/investigations/{slug}/publish-members", json={"slugs": ["new1", "new2"]})
    assert r.status_code == 403
    assert r.json()["detail"].startswith(f"waiting for the owner, {ALICE}"), r.json()
    assert eg.asset_creates() == []


# ── 3. one failure is reported in its words; the other still publishes ───────────────────────────────

def test_one_member_failing_does_not_stop_the_other(world):
    eg, reg = world["eg"], world["registry"]
    slug = _investigation(world)
    eg.fail_create_for.add("github.com/x/new1")

    out = _press_and_wait(world, slug)

    by = {m["entity_slug"]: m for m in out["members"]}
    assert by["new1"]["state"] == "failed"
    assert "Egeria went away creating GitHubRepository::https://github.com/x/new1" in by["new1"]["words"]
    assert by["new2"]["state"] == "published"
    assert reg.get_egeria_asset_guid("new2") and not reg.get_egeria_asset_guid("new1")
    assert out["words"] == ["1 published", "1 failed"]


def test_a_member_with_no_kept_survey_is_not_published_with_the_sentence(world):
    reg = world["registry"]
    reg.add(Project(slug="bare", display_name="BARE", github_url="https://github.com/x/bare", description=""))
    slug = _investigation(world)
    world["client"].post(f"/api/investigations/{slug}/members", json={"entity_type": "repo", "entity_slug": "bare"})

    out = _press_and_wait(world, slug)

    by = {m["entity_slug"]: m for m in out["members"]}
    assert by["bare"]["state"] == "not_published" and by["bare"]["words"], by["bare"]
    assert by["new1"]["state"] == "published" and by["new2"]["state"] == "published"


# ── 4. a shared investigation's members publish with normal zones ────────────────────────────────────

def test_a_shared_investigations_members_publish_with_normal_zones(world):
    eg = world["eg"]
    slug = _investigation(world, "StudyProject")

    out = _press_and_wait(world, slug)

    assert {m["state"] for m in out["members"]} == {"published"}
    for user, body in eg.asset_creates():
        assert user == ALICE
        assert PRIVATE not in (body["properties"].get("zoneMembership") or [])
    assert not any(PRIVATE in zones for _u, _g, zones in eg.zoned), eg.zoned


# ── 5. the cap ────────────────────────────────────────────────────────────────────────────────────────

def test_the_plan_caps_a_press_and_names_the_rest(world):
    from resource_explorer import investigation_member_publish as imp

    slug = _investigation(world)
    plan = imp.member_publish_plan(world["registry"], slug, cap=1)
    assert [m["entity_slug"] for m in plan["publish"]] == ["new1"]
    assert [m["entity_slug"] for m in plan["waiting"]] == ["new2"]
    assert plan["words"] == "will publish 1 repo: new1 · 1 more waits for the next press (at most 1 a press)"
    assert imp.MEMBER_PUBLISH_CAP == 50


# ── review of bca5be94 ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason=(
    "egeria_publisher zones the shared repo ASSET private (create body) and the report only after create; "
    "fixed on re/publisher-zone-what-it-produced (design §3.6). Remove this xfail when this branch rebases onto it."))
def test_a_private_member_publish_zones_what_it_produced_not_the_shared_asset(world):
    """§3.6: an investigation zones what it PRODUCED (the report, its annotations by anchor), never what it
    REFERENCES. The member's repo asset is one per repository and stays readable to a second user; the report is
    born [private, owner]."""
    eg = world["eg"]
    slug = _investigation(world)

    out = _press_and_wait(world, slug)

    assert {m["state"] for m in out["members"]} == {"published"}
    for user, body in eg.asset_creates():
        assert PRIVATE not in (body["properties"].get("zoneMembership") or []), body["properties"]
    for s in ("new1", "new2"):
        asset = world["registry"].get_egeria_asset_guid(s)
        assert eg.readable_by("bob", asset), f"a second user cannot read the shared asset of {s}"
    reports = eg.report_creates()
    assert len(reports) == 2
    for user, body in reports:
        assert user == ALICE
        assert body["properties"].get("zoneMembership") == [PRIVATE, ALICE], body["properties"]
        assert not eg.readable_by("bob", next(g for g, el in eg.elements.items()
                                              if el.get("qn") == body["properties"]["qualifiedName"]))


def _fake_publish_report(registry, results: dict):
    """A stand-in for `repo_publish.publish_report` that writes the proof row the real one would (by kind), so the
    batch's result mapping is tested against rows, not against what the function returned."""
    from resource_explorer import repo_publish as rp

    def fake(reg, slug, author, **kw):
        kind, words = results[slug]
        if kind == "read_failed":
            reg.append_catalogue_commit_proof(slug, proof="read_failed", node_kind=rp.NODE_REPORT, recorded_by=author,
                                              detail={"error": words, "stage": "publish"})
            return {"ok": False, "stage": "publish", "report_guid": ""}
        reg.set_egeria_asset_guid(slug, f"g-{slug}")
        reg.append_catalogue_commit_proof(slug, proof=kind, node_kind=rp.NODE_REPORT, recorded_by=author,
                                          element_guid=f"r-{slug}", detail={})
        return {"ok": True, "report_guid": f"r-{slug}"}
    return fake


def test_a_private_report_whose_zones_were_not_confirmed_is_failed_not_published(world, monkeypatch):
    """After the publisher fix a private publish whose report zones cannot be confirmed fails closed with a
    `read_failed` proof row: that reads FAILED, with its words, never "published"."""
    from resource_explorer import repo_publish as rp

    slug = _investigation(world)
    words = "the report's zones [resource-explorer-private, alice] could not be confirmed; it was not published"
    monkeypatch.setattr(rp, "publish_report", _fake_publish_report(world["registry"], {
        "new1": ("read_failed", words), "new2": ("report_published", "")}))

    out = _press_and_wait(world, slug)

    by = {m["entity_slug"]: m for m in out["members"]}
    assert by["new1"]["state"] == "failed" and by["new1"]["words"] == words
    assert by["new2"]["state"] == "published"
    assert out["words"] == ["1 published", "1 failed"]


def test_sent_is_its_own_state(world):
    world["eg"].hide_reports = True                  # the create answered; the read-back does not show it yet
    slug = _investigation(world)
    out = _press_and_wait(world, slug)
    assert {m["state"] for m in out["members"]} == {"sent"}, out
    assert out["words"] == ["2 sent · waiting for Egeria"]


def test_the_press_must_name_what_was_confirmed(world):
    c, eg = world["client"], world["eg"]
    slug = _investigation(world)
    plan = c.get(f"/api/investigations/{slug}/publish-members").json()
    assert plan["slugs"] == ["new1", "new2"]
    # The scope changed after the confirmation: a third unpublished repo.
    world["registry"].add(Project(slug="new3", display_name="NEW3", github_url="https://github.com/x/new3",
                                  description=""))
    c.post(f"/api/investigations/{slug}/members", json={"entity_type": "repo", "entity_slug": "new3"})

    r = c.post(f"/api/investigations/{slug}/publish-members", json={"slugs": plan["slugs"]})
    assert r.status_code == 409 and r.json()["detail"] == "the list changed, confirm again", r.text
    r = c.post(f"/api/investigations/{slug}/publish-members")            # no list at all
    assert r.status_code == 409 and r.json()["detail"] == "the list changed, confirm again", r.text
    assert eg.asset_creates() == []
    assert world["registry"].list_activity(entity_type="investigation", entity_slug=slug, operation="publish") == [] \
        or not any("member_publish" in (a.get("detail") or "")
                   for a in world["registry"].list_activity(entity_type="investigation", entity_slug=slug))


def test_a_lost_sign_in_stops_the_batch_and_says_sign_in_again(world, monkeypatch):
    from resource_explorer import egeria_clients
    from resource_explorer import investigation_member_publish as imp

    reg = world["registry"]
    slug = _investigation(world)
    expired = {"now": False}
    real_caller, real_record = egeria_clients.Caller, imp._record

    def caller():
        # Only the batch's own threads see the expiry: the page's progress reads are fresh requests.
        import threading as _t
        if expired["now"] and _t.current_thread().name.startswith("member-publish"):
            raise egeria_clients.CallerTokenExpired()
        return real_caller()

    def record(*a, **k):
        real_record(*a, **k)
        expired["now"] = True                        # the token runs out after the first member's result

    monkeypatch.setattr(egeria_clients, "Caller", caller)
    monkeypatch.setattr(imp, "_record", record)

    out = _press_and_wait(world, slug)

    by = {m["entity_slug"]: m for m in out["members"]}
    assert by["new1"]["state"] == "published"
    assert by["new2"]["state"] == "not_reached" and by["new2"]["words"].startswith("sign in again"), by["new2"]
    assert not reg.get_egeria_asset_guid("new2")
    batch = next(a for a in reg.list_activity(entity_type="investigation", entity_slug=slug, operation="publish")
                 if a["id"] == out["batch_id"])
    assert batch["summary"].startswith("finished: 1 of 2 tried · stopped: sign in again"), batch["summary"]
    assert batch["status"] == "error"


def test_a_second_press_while_one_runs_is_409(world, monkeypatch):
    from resource_explorer import investigation_member_publish as imp

    slug = _investigation(world)
    monkeypatch.setitem(imp._running, slug, "mp-already")
    r = _press(world, slug)
    assert r.status_code == 409 and "already running" in r.json()["detail"], r.text
    assert world["eg"].asset_creates() == []


def test_a_press_after_a_crashed_batch_works(world):
    """A batch whose process went away left its row 'running' and no lock (the lock is in memory): its members read
    "not reached", and a new press runs."""
    from resource_explorer import investigation_member_publish as imp

    reg = world["registry"]
    slug = _investigation(world)
    inv = reg.get_investigation(slug)
    imp._write_row(reg, "mp-crashed", inv, "running", "will publish 1 repo: new1",
                   {imp.BATCH_KEY: "mp-crashed", "members": [{"entity_type": "repo", "entity_slug": "new1"}],
                    "waiting": [], "by": ALICE, "finished": False})
    old = world["client"].get(f"/api/investigations/{slug}/publish-members/mp-crashed").json()
    assert [(m["state"], m["words"]) for m in old["members"]] == [("not_reached", "the batch stopped before this member")]

    out = _press_and_wait(world, slug)
    assert {m["state"] for m in out["members"]} == {"published"}


def test_a_hung_member_times_out_and_the_batch_goes_on(world, monkeypatch):
    import threading as _t

    from resource_explorer import investigation_member_publish as imp
    from resource_explorer import repo_publish as rp

    slug = _investigation(world)
    release = _t.Event()
    real = _fake_publish_report(world["registry"], {"new1": ("report_published", ""),
                                                    "new2": ("report_published", "")})

    def maybe_hang(reg, s, author, **kw):
        if s == "new1":
            release.wait(5)
        return real(reg, s, author, **kw)

    monkeypatch.setattr(imp, "MEMBER_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(rp, "publish_report", maybe_hang)
    try:
        out = _press_and_wait(world, slug)
    finally:
        release.set()
    by = {m["entity_slug"]: m for m in out["members"]}
    assert by["new1"]["state"] == "failed"
    assert by["new1"]["words"].startswith("timed out after 0.3s · it may still finish in Egeria"), by["new1"]
    assert by["new2"]["state"] == "published"
    assert imp._running.get(slug) is None                        # the lock is released


def test_a_finished_batch_with_a_lost_result_row_reads_could_not_tell(world):
    from resource_explorer import investigation_member_publish as imp

    reg = world["registry"]
    slug = _investigation(world)
    inv = reg.get_investigation(slug)
    members = [{"entity_type": "repo", "entity_slug": "new1"}, {"entity_type": "repo", "entity_slug": "new2"}]
    imp._write_row(reg, "mp-lost", inv, "ok", "finished: 2 of 2 tried",
                   {imp.BATCH_KEY: "mp-lost", "members": members, "waiting": [], "by": ALICE, "finished": True})
    # new2's row claims "published" with a proof row that does not exist.
    imp._record(reg, inv, "mp-lost", members[1], {"outcome": "published", "words": "", "proof_id": 987654})

    out = imp.progress_of(reg, slug, "mp-lost")

    assert [(m["entity_slug"], m["state"], m["words"]) for m in out["members"]] == [
        ("new1", "could_not_tell", "no result was recorded for this member"),
        ("new2", "could_not_tell", "no proof row for this publish")]
    assert out["words"] == ["2 could not tell"]


def test_the_close_row_says_how_many_were_tried_and_its_status_follows_the_outcomes(world):
    reg = world["registry"]
    world["eg"].fail_create_for.add("github.com/x/new1")
    slug = _investigation(world)
    out = _press_and_wait(world, slug)
    batch = next(a for a in reg.list_activity(entity_type="investigation", entity_slug=slug, operation="publish")
                 if a["id"] == out["batch_id"])
    assert batch["summary"] == "finished: 2 of 2 tried" and batch["status"] == "error"


def test_a_press_with_a_cap_of_one_publishes_one_and_names_the_rest(world, monkeypatch):
    from resource_explorer import investigation_member_publish as imp

    reg = world["registry"]
    monkeypatch.setattr(imp, "MEMBER_PUBLISH_CAP", 1)
    slug = _investigation(world)

    out = _press_and_wait(world, slug)

    assert [(m["entity_slug"], m["state"]) for m in out["members"]] == [("new1", "published")]
    assert [m["entity_slug"] for m in out["waiting_next_press"]] == ["new2"]
    assert reg.get_egeria_asset_guid("new1") and not reg.get_egeria_asset_guid("new2")
    plan = world["client"].get(f"/api/investigations/{slug}/publish-members").json()
    assert plan["slugs"] == ["new2"] and plan["words"] == "will publish 1 repo: new2"


def test_relink_says_a_database_member_is_not_linked_from_here_not_unpublished(world):
    c = world["client"]
    slug = _investigation(world)
    reg = world["registry"]
    ws = reg.get_or_create_working_set(slug)
    reg.add_working_set_member(ws["slug"], "database", "some_db")
    r = c.post(f"/api/investigations/{slug}/relink-members")
    assert r.status_code == 200, r.text
    db = next(m for m in r.json()["members_unlinkable"] if m["entity_slug"] == "some_db")
    assert db["reason"] == "only repositories are linked from an investigation today"
