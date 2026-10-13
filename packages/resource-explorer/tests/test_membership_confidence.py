"""A work-list member's confidence reaches Egeria as CollectionMembership `confidence` (2026-10-13).

The bug: RE sent `expectedConfidence`, which is not a field of Egeria 6.2's `CollectionMembershipProperties`
(`membershipRationale`, `membershipType`, `expression`, `confidence` (int, 0-100, default 0),
`membershipStatus`, `userDefinedStatus`, `steward`, `stewardTypeName`, `stewardPropertyName`, `source`,
`notes`). The class is `@JsonIgnoreProperties(ignoreUnknown=true)`, so Egeria dropped the name, answered
success, and the relationship read `confidence: 0`. The outbox row said done.

No Egeria here. `EgeriaCollections` is the only fake: the CollectionManager boundary, every call bound to the
installed pyegeria signature first, and it keeps a relationship property the way Egeria does (known names
only, `confidence` 0 when not sent). Zone access reads are faked at their own client boundary (`zone_fakes`),
with no zone in use.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

from resource_explorer.registry import Project, ProjectRegistry

sys.path.insert(0, str(Path(__file__).parent))

from tests.zone_fakes import permit_publish_routes, signed_in  # noqa: E402

pytestmark = pytest.mark.usefixtures("mock_egeria_client_connections")

USER = "garygeeke"

#: Egeria 6.2 `CollectionMembershipProperties` (+ RelationshipBeanProperties' extendedProperties and
#: RelationshipProperties' effectiveFrom/effectiveTo). Anything else in a body is dropped by Egeria.
EGERIA_MEMBERSHIP_FIELDS = frozenset({
    "membershipRationale", "membershipType", "expression", "confidence", "membershipStatus",
    "userDefinedStatus", "steward", "stewardTypeName", "stewardPropertyName", "source", "notes",
    "extendedProperties", "effectiveFrom", "effectiveTo",
})


def _sig(name: str) -> inspect.Signature:
    from pyegeria.omvs.collection_manager import CollectionManager

    return inspect.signature(getattr(CollectionManager, name))


class EgeriaCollections:
    """The CollectionManager boundary, as Egeria 6.2 behaves for these three calls."""

    def __init__(self, *, keep=EGERIA_MEMBERSHIP_FIELDS, fail_read: bool = False):
        self.keep = keep
        self.fail_read = fail_read
        self.sent: list[dict | None] = []                 # every add_to_collection body, as sent
        self.relationships: dict[tuple[str, str], dict] = {}

    def create_collection(self, *a, **kw):
        _sig("create_collection").bind(self, *a, **kw)
        return "ws-guid"

    def add_to_collection(self, *a, **kw):
        bound = _sig("add_to_collection").bind(self, *a, **kw)
        coll, member = bound.arguments["collection_guid"], bound.arguments["element_guid"]
        body = bound.arguments.get("body")
        self.sent.append(body)
        props = dict((body or {}).get("properties") or {})
        kept = {k: v for k, v in props.items() if k in self.keep}
        # Uni-link: a repeat replaces. The int default comes back on every read.
        self.relationships[(coll, member)] = {"class": "CollectionMembershipProperties",
                                             "typeName": "CollectionMembership", "confidence": 0, **kept}

    def get_collection_members(self, *a, **kw):
        bound = _sig("get_collection_members").bind(self, *a, **kw)
        if self.fail_read:
            raise ConnectionError("platform went away")
        coll = bound.arguments.get("collection_guid")
        return [{"elementHeader": {"guid": m}, "properties": {"qualifiedName": f"Asset::{m}"},
                 "relatedBy": {"relationshipProperties": dict(p)}}
                for (c, m), p in self.relationships.items() if c == coll]


class _Clients:
    def __init__(self, cm):
        self.cm = cm

    def require(self, name):
        assert name == "collection_manager"
        return self.cm


def test_the_fake_rejects_what_real_pyegeria_rejects():
    with pytest.raises(TypeError):
        EgeriaCollections().add_to_collection("c")                       # element_guid is required
    with pytest.raises(TypeError):
        EgeriaCollections().add_to_collection("c", "m", body={}, nonsense=1)


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "memconf.db"))
    assert str(tmp_path) in r.database_url                                # never the shared registry
    for slug in ("p", "q"):
        r.add(Project(slug=slug, display_name=slug.upper(), github_url=f"https://github.com/x/{slug}",
                      description=""))
        r.set_egeria_asset_guid(slug, f"g-{slug}")
    return r


def _queue(registry, **extra) -> int:
    payload = {"collection_guid": "wg", "member_guid": "g-q", "member_entity_type": "repo",
               "member_entity_slug": "q", "by": USER, **extra}
    return registry.enqueue_outbox_element("work_list", "w", "collection_membership",
                                           "CollectionMembership::wg::g-q", payload)


def _drain(registry, cm):
    from resource_explorer.egeria_outbox import OutboxClients, drain_outbox

    return drain_outbox(registry, OutboxClients(collection_manager=cm), lambda qn: "", limit=10)


def _row(registry, slug="w"):
    return registry.list_outbox_elements(entity_slug=slug, limit=10)[0]


# ── the body ──────────────────────────────────────────────────────────────────────────────────────────────

class TestTheBody:
    def test_confidence_is_sent_as_egerias_confidence_never_expected_confidence(self, registry, monkeypatch):
        permit_publish_routes(monkeypatch, USER)
        _queue(registry, membership_rationale="system of record", expected_confidence=80)
        cm = EgeriaCollections()
        _drain(registry, cm)
        props = cm.sent[0]["properties"]
        assert props["class"] == "CollectionMembershipProperties"
        assert props["confidence"] == 80 and "expectedConfidence" not in props
        assert set(props) - {"class"} <= EGERIA_MEMBERSHIP_FIELDS
        assert cm.relationships[("wg", "g-q")]["confidence"] == 80
        assert _row(registry)["status"] == "done"

    def test_no_confidence_recorded_sends_none(self, registry, monkeypatch):
        """Egeria's default is 0, so "not recorded" is NOT sent as 0: the key is simply absent."""
        permit_publish_routes(monkeypatch, USER)
        _queue(registry, membership_rationale="why")
        cm = EgeriaCollections()
        _drain(registry, cm)
        assert "confidence" not in cm.sent[0]["properties"]
        assert cm.sent[0]["properties"]["membershipRationale"] == "why"

    def test_neither_sends_no_body(self, registry, monkeypatch):
        permit_publish_routes(monkeypatch, USER)
        _queue(registry)
        cm = EgeriaCollections()
        _drain(registry, cm)
        assert cm.sent == [None]

    @pytest.mark.parametrize("raw, sent", [(80, 80), ("80", 80), (79.6, 80), (0, 0), (100, 100)])
    def test_a_number_is_coerced_to_an_int(self, registry, monkeypatch, raw, sent):
        permit_publish_routes(monkeypatch, USER)
        _queue(registry, expected_confidence=raw)
        cm = EgeriaCollections()
        _drain(registry, cm)
        assert cm.sent[0]["properties"]["confidence"] == sent
        assert type(cm.sent[0]["properties"]["confidence"]) is int

    @pytest.mark.parametrize("raw", ["high", True, 101, -1, float("nan")])
    def test_a_non_number_or_out_of_range_is_refused_and_nothing_is_sent(self, registry, monkeypatch, raw):
        permit_publish_routes(monkeypatch, USER)
        _queue(registry, expected_confidence=raw)
        cm = EgeriaCollections()
        _drain(registry, cm)
        assert cm.sent == []
        row = _row(registry)
        assert row["status"] in ("failed", "dead") and "confidence" in row["last_error"]

    def test_a_payload_carrying_confidence_by_its_egeria_name_is_read_too(self, registry, monkeypatch):
        permit_publish_routes(monkeypatch, USER)
        _queue(registry, confidence=65)
        cm = EgeriaCollections()
        _drain(registry, cm)
        assert cm.sent[0]["properties"]["confidence"] == 65


# ── the read-back ─────────────────────────────────────────────────────────────────────────────────────────

class TestTheReadBack:
    def test_a_property_egeria_did_not_keep_is_named_on_the_row(self, registry, monkeypatch):
        """The shape of the original bug, against a correct name: Egeria answers success and keeps nothing."""
        permit_publish_routes(monkeypatch, USER)
        _queue(registry, membership_rationale="why", expected_confidence=80)
        cm = EgeriaCollections(keep=frozenset({"membershipRationale"}))
        _drain(registry, cm)
        row = _row(registry)
        assert row["status"] in ("failed", "dead")
        assert "did not keep: confidence (sent 80, read back 0)" in row["last_error"]
        assert "membershipRationale" not in row["last_error"]

    def test_a_failed_read_leaves_the_write_done(self, registry, monkeypatch):
        permit_publish_routes(monkeypatch, USER)
        _queue(registry, expected_confidence=80)
        cm = EgeriaCollections(fail_read=True)
        _drain(registry, cm)
        assert _row(registry)["status"] == "done"
        assert cm.relationships[("wg", "g-q")]["confidence"] == 80


# ── end to end: set a member's confidence, publish, drain ─────────────────────────────────────────────────

def test_work_list_publish_lands_the_members_confidence_on_the_relationship(registry, monkeypatch):
    from resource_explorer.work_lists import WorkLists

    permit_publish_routes(monkeypatch, USER)
    cm = EgeriaCollections()
    monkeypatch.setattr("resource_explorer.egeria_outbox._default_clients", lambda who=None: (_Clients(cm), None))
    wls = WorkLists(registry)
    slug = wls.create("W", ["p", "q"], entity_type="repo", created_by=USER)["slug"]
    wls.set_member(slug, "q", rationale="the system of record", confidence=80)
    wls.set_member(slug, "p", rationale="a candidate")            # no confidence recorded

    token = signed_in(USER)
    try:
        out = wls.publish(slug)
    finally:
        from resource_explorer.a2a_auth import current_caller

        current_caller.reset(token)
    assert out["egeria_guid"] == "ws-guid" and out["queued_members"] == 2
    queued = {json.loads(r["payload_json"])["member_guid"]: json.loads(r["payload_json"])
              for r in registry.list_outbox_elements(entity_slug=slug, limit=10)}
    assert queued["g-q"]["expected_confidence"] == 80 and "expected_confidence" not in queued["g-p"]

    summary = _drain(registry, cm)
    assert summary["done"] == 2, summary
    assert cm.relationships[("ws-guid", "g-q")] == {
        "class": "CollectionMembershipProperties", "typeName": "CollectionMembership",
        "confidence": 80, "membershipRationale": "the system of record"}
    assert cm.relationships[("ws-guid", "g-p")]["confidence"] == 0              # Egeria's default, not RE's
    assert all("expectedConfidence" not in (b or {}).get("properties", {}) for b in cm.sent)


def test_the_route_refuses_a_confidence_egeria_cannot_hold(registry, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer.work_lists import WorkLists

    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setattr("resource_explorer.auth.get_current_user",
                        lambda request: {"user_id": USER, "egeria_token": "t", "role": "user"})
    from resource_explorer.web.app import app

    slug = WorkLists(registry).create("W", ["q"], entity_type="repo", created_by=USER)["slug"]
    client = TestClient(app)
    assert client.post(f"/api/work-lists/{slug}/members",
                       json={"entity_slug": "q", "confidence": 150}).status_code == 422
    r = client.post(f"/api/work-lists/{slug}/members", json={"entity_slug": "q", "confidence": 70})
    assert r.status_code == 200, r.text
