"""scripts/question_term_update_batch.py: the Egeria update for the 2026-10-22 questions edit (#842).

The fixture (tests/fixtures/question_term_batch/) is a ten-row CSV pair and an inventory covering the join paths
(question_id, pre-edit-name fallback, not found), an id-less term, an existing link that must not be re-added, a
merge whose ReplacementTerm already exists, a merge into a NEW term, and a leftover term no CSV row names. The
failure cases (duplicate id, survivor missing, term not found, read errors) mutate it. The end-to-end test parses
the RENDERED document with Dr.Egeria's own extractor, applies it to the inventory, and plans again: empty.
"""
from __future__ import annotations

import copy
import csv
import glob
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import create_autospec

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "question_term_update_batch.py"
FIXTURES = ROOT / "tests" / "fixtures" / "question_term_batch"


def _load():
    spec = importlib.util.spec_from_file_location("question_term_update_batch", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


qtb = _load()


def _rows(name: str) -> list[dict]:
    with open(FIXTURES / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def after():
    return _rows("after.csv")


@pytest.fixture
def before():
    return _rows("before.csv")


@pytest.fixture
def inventory():
    return json.loads((FIXTURES / "inventory.json").read_text(encoding="utf-8"))


def _row(plan, qid):
    return next(r for r in plan.rows if r.question_id == qid)


# ---------------------------------------------------------------------------
# the plan on the fixture
# ---------------------------------------------------------------------------

def test_fixture_counts_by_join_path_and_action(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    c = plan.counts()
    assert c["join_path"] == {"not_found": 1, "old_name": 3, "question_id": 6}
    assert c["action"] == {"create": 1, "deprecate_merged": 3, "deprecate_retired": 1, "unchanged": 1, "update": 4}
    assert c["command_kind"] == {"classify": 1, "create": 1, "deprecate": 4, "deprecate_leftover": 1,
                                 "link_perspective": 2, "link_replacement": 2, "link_stage": 2, "update": 4}
    assert c["commands_total"] == 17
    assert c["unplaceable"] == 0
    assert c["unknown_terms"] == 0  # the stray "Scouting" term no row names is now a leftover, deprecated
    assert c["proof"] == {"found by name": 3, "by id": 6, "id set on": 3, "created: missing in Egeria": 0,
                          "deprecated: leftovers": 1}


def test_each_join_path(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    assert _row(plan, "Q-0001").join_path == "question_id"
    # No question_id on the term: joined by the pre-edit name, even though the question was reworded.
    q3 = _row(plan, "Q-0003")
    assert q3.join_path == "old_name" and q3.term["display_name"] == "C?"
    assert "question_id" in q3.changed_fields and "Display Name" in q3.changed_fields
    assert _row(plan, "Q-0009").join_path == "not_found" and _row(plan, "Q-0009").action == "create"


def test_missing_id_is_set_in_the_same_update(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    q2 = _row(plan, "Q-0002")
    assert q2.changed_fields == ["question_id"]  # text unchanged: an RE-only column changed
    (update,) = q2.commands
    assert update.command == "Update Glossary Term"
    assert (update.fields["GUID"], update.fields["Qualified Name"]) == ("term-02", "Org::Term::Is-B?::1.0")
    assert "| question_id | Q-0002 |" in update.fields["Additional Properties"]


def test_existing_links_are_not_re_added(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    q5 = _row(plan, "Q-0005")  # Discovery -> Discovery/Enrichment; Consumer perspective already linked
    links = [c for c in q5.commands if c.kind.startswith("link")]
    assert [(c.kind, c.fields) for c in links] == [
        ("link_stage", {"Target Element": "Org::Term::E?::1.0", "Scope Reference": "Enrichment"})]
    assert _row(plan, "Q-0004").action == "unchanged" and _row(plan, "Q-0004").commands == []


def test_deprecations_keep_links_and_prefix_the_description(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    q6 = _row(plan, "Q-0006")
    assert q6.action == "deprecate_retired"
    assert [c.kind for c in q6.commands] == ["deprecate"]  # no replacement, no unlink
    f = q6.commands[0].fields
    assert f["Status"] == "DEPRECATED"
    assert f["Description"] == "retired 2026-10-22: launcher affordance (review §1.4) — R6"
    assert not any(c.command.startswith(("Unlink", "Detach", "Remove", "Delete")) for c in plan.commands())


def test_merges_link_absorbed_to_survivor_and_omit_an_existing_replacement(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    (rep7,) = [c for c in _row(plan, "Q-0007").commands if c.kind == "link_replacement"]
    assert rep7.fields == {"Term 1": "Org::Term::G?::1.0", "Term 2": "Org::Term::What-is-A?::1.0",
                           "Relationship Type": "ReplacementTerm"}
    # survivor is new: named by the qualifiedName its Create (earlier in the same document) carries
    (rep8,) = [c for c in _row(plan, "Q-0008").commands if c.kind == "link_replacement"]
    assert rep8.fields["Term 2"] == "Org::Term::I-new?::1.0" == _row(plan, "Q-0009").commands[0].fields["Qualified Name"]
    kinds = [c.kind for c in plan.commands()]
    assert kinds.index("create") < kinds.index("link_replacement")
    # Q-0010's ReplacementTerm to Q-0001 is already in the inventory: only the status update remains
    assert [c.kind for c in _row(plan, "Q-0010").commands] == ["deprecate"]


# ---------------------------------------------------------------------------
# rows the plan cannot place
# ---------------------------------------------------------------------------

def test_duplicate_question_id_is_unplaceable(after, before, inventory):
    dup = copy.deepcopy(next(t for t in inventory["terms"] if t["question_id"] == "Q-0004"))
    dup["guid"] = "term-04-copy"
    inventory["terms"].append(dup)
    plan = qtb.build_plan(after, before, inventory)
    assert [r.question_id for r in plan.unplaceable] == ["Q-0004"]
    assert "2 terms carry question_id Q-0004" in plan.unplaceable[0].reason


def test_survivor_missing_is_unplaceable(after, before, inventory):
    next(r for r in after if r["Question ID"] == "Q-0007")["Status"] = "merged into Q-0099 2026-10-22"
    plan = qtb.build_plan(after, before, inventory)
    assert [r.question_id for r in plan.unplaceable] == ["Q-0007"]
    assert _row(plan, "Q-0007").commands == []


def test_retired_row_with_no_term_is_reported_not_failed(after, before, inventory):
    """Ruling 2026-10-23: nothing to deprecate is fine; reported as "deprecate: no term", never unplaceable."""
    inventory["terms"] = [t for t in inventory["terms"] if t["guid"] != "term-06"]
    plan = qtb.build_plan(after, before, inventory)
    assert plan.unplaceable == []
    q6 = _row(plan, "Q-0006")
    assert (q6.join_path, q6.action, q6.commands) == ("not_found", "no_term", [])
    assert plan.counts()["deprecate_no_term"] == ["Q-0006"]
    assert "deprecate: no term 1 (Q-0006)" in qtb.format_counts(plan)


def test_inventory_with_read_errors_is_refused(after, before, inventory):
    inventory["read_errors"] = [{"guid": "term-01", "error": "timeout"}]
    with pytest.raises(qtb.PlanInputError, match="read error"):
        qtb.build_plan(after, before, inventory)


def test_cli_exits_nonzero_and_writes_nothing_when_unplaceable(tmp_path, inventory):
    dup = copy.deepcopy(next(t for t in inventory["terms"] if t["question_id"] == "Q-0004"))
    dup["guid"] = "term-04-copy"
    inventory["terms"].append(dup)
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps(inventory))
    out = tmp_path / "out.md"
    rc = qtb.main(["plan", "--inventory", str(inv), "--out", str(out), "--csv", str(FIXTURES / "after.csv"),
                   "--old-csv", str(FIXTURES / "before.csv")])
    assert rc == 1 and not out.exists()


# ---------------------------------------------------------------------------
# the rendered document: counts, labels, end to end
# ---------------------------------------------------------------------------

def _extract(text: str):
    from md_processing.v2.extraction import UniversalExtractor
    return [c for c in UniversalExtractor(text).extract_commands() if c.is_command]


def test_plan_counts_equal_the_rendered_documents_commands(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    cmds = _extract(qtb.render_document(plan))
    rendered: dict = {}
    for c in cmds:
        name = f"{c.verb} {c.object_type}"
        rendered[name] = rendered.get(name, 0) + 1
    assert rendered == plan.counts()["command"]
    assert len(cmds) == plan.counts()["commands_total"]
    # each block's attributes survive Dr.Egeria's own parse unchanged
    for parsed, planned in zip(cmds, plan.commands()):
        assert {k: v.strip() for k, v in planned.fields.items()} == parsed.attributes


def _compact_specs():
    import md_processing
    attrs, bundles, commands = {}, {}, {}
    for f in glob.glob(str(Path(md_processing.__file__).parent / "data" / "compact_commands" / "*.json")):
        j = json.loads(Path(f).read_text())
        attrs.update(j["attribute_definitions"]), bundles.update(j["bundles"]), commands.update(j["commands"])
    return attrs, bundles, commands


def test_every_rendered_label_is_an_attribute_of_its_command(after, before, inventory):
    """The installed pyegeria's compact specs: an unknown label is silently dropped by Dr.Egeria."""
    attrs, bundles, commands = _compact_specs()

    def expand(name):
        b = bundles[name]
        inh = b.get("inherits") or []
        out = [a for p in (inh if isinstance(inh, list) else [inh]) for a in expand(p)]
        return out + list(b.get("own_attributes") or [])

    plan = qtb.build_plan(after, before, inventory)
    for cmd in plan.commands():
        # an Update runs through its upsert Create command's spec (Create Glossary Term is upsert: true)
        spec = commands.get(cmd.command) or commands[cmd.command.replace("Update ", "Create ", 1)]
        known = set(expand(spec["bundle"])) | set(spec.get("custom_attributes") or [])
        labels = set(known)
        for a in known:
            labels |= {x.strip().strip('"') for x in (attrs.get(a, {}).get("attr_labels") or "").split(";") if x.strip()}
        assert set(cmd.fields) <= labels, (cmd.command, set(cmd.fields) - labels)
    assert "ReplacementTerm" in attrs["Relationship Type"]["valid_values"]
    assert attrs["Status"]["inUpdate"] and attrs["Additional Properties"]["inUpdate"]


def _apply(inventory: dict, text: str, limit: Optional[int] = None) -> dict:
    """What a successful PROCESS of the document leaves in Egeria, as the next inventory would show it. With
    `limit`, only the document's first `limit` commands were processed (a partial apply)."""
    inv = copy.deepcopy(inventory)
    terms = inv["terms"]

    def find(ref):
        """Links, classifications and Term 1/2 name a term by qualifiedName (the inventory's, or the one a
        Create in the same document carries); nothing is found by display name."""
        hits = [t for t in terms if ref == t["qualified_name"]]
        assert len(hits) == 1, ref
        return hits[0]

    def props(table):
        return dict(re.findall(r"^\|(?!\s*(?:Parameter Name|-))\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|$", table or "", re.M))

    for n, c in enumerate(_extract(text)[:limit]):
        a, name = c.attributes, f"{c.verb} {c.object_type}"
        if name == "Create Glossary Term":
            assert a["Qualified Name"] not in {t["qualified_name"] for t in terms}
            p = props(a.get("Additional Properties"))
            terms.append({"guid": f"new-{n}", "qualified_name": a["Qualified Name"],
                          "display_name": a["Display Name"], "description": a.get("Description", ""),
                          "summary": a.get("Summary", ""), "usage": a.get("Usage", ""), "content_status": "ACTIVE",
                          "element_status": "ACTIVE", "question_id": p.get("question_id"),
                          "additional_properties": p, "classifications": ["Anchors"], "links": []})
            inv.setdefault("all_terms", []).append({"guid": f"new-{n}", "qualified_name": a["Qualified Name"],
                                                    "display_name": a["Display Name"]})
        elif name == "Classify Term as Question":
            find(a["Term Name"])["classifications"].append("Question")
        elif name == "Update Glossary Term":
            # located by GUID, which must name the same term as the qualifiedName it also carries
            (t,) = [x for x in terms if x["guid"] == a["GUID"]]
            assert t["qualified_name"] == a["Qualified Name"]
            t["display_name"] = a["Display Name"]
            for label, key in (("Description", "description"), ("Summary", "summary"), ("Usage", "usage")):
                if label in a:
                    t[key] = a[label]
            if "Status" in a:
                t["content_status"] = a["Status"]
            if "Additional Properties" in a:
                t["additional_properties"] = props(a["Additional Properties"])  # the map sent replaces the map
                t["question_id"] = t["additional_properties"].get("question_id")
        elif name == "Link Perspective to Question":
            col = a["Perspective Name"].split("::", 1)[1]
            find(a["Question Name"])["links"].append({
                "relationship": "ScopedBy", "relationship_guid": f"r{n}", "other_at_end1": False,
                "guid": f"persp-{col}", "type": "Perspective", "qualified_name": a["Perspective Name"],
                "display_name": col})
        elif name == "Link Element To Scope":
            find(a["Target Element"])["links"].append({
                "relationship": "ScopedBy", "relationship_guid": f"r{n}", "other_at_end1": False,
                "guid": f"stage-{a['Scope Reference']}", "type": "GlossaryTerm",
                "qualified_name": f"Org::Term::{a['Scope Reference']}::1.0", "display_name": a["Scope Reference"]})
        elif name == "Link Term-Term Relationship":
            survivor = find(a["Term 2"])
            find(a["Term 1"])["links"].append({
                "relationship": a["Relationship Type"], "relationship_guid": f"r{n}", "other_at_end1": False,
                "guid": survivor["guid"], "type": "GlossaryTerm", "qualified_name": survivor["qualified_name"],
                "display_name": survivor["display_name"]})
        else:
            raise AssertionError(f"unexpected command {name}")
    inv["taken_at"] = "after-apply"
    return inv


def test_end_to_end_plan_after_a_successful_apply_is_empty(after, before, inventory):
    first = qtb.build_plan(after, before, inventory)
    applied = _apply(inventory, qtb.render_document(first))
    second = qtb.build_plan(after, before, applied)
    assert second.commands() == [] and second.unplaceable == []
    assert all(r.join_path == "question_id" for r in second.rows)  # every term now carries its id
    assert _extract(qtb.render_document(second)) == []


# ---------------------------------------------------------------------------
# inventory: read-only
# ---------------------------------------------------------------------------

def _read_only_fake(cls):
    """An autospec of the real pyegeria class whose every public or _async_ method except the three reads raises."""
    fake = create_autospec(cls, spec_set=True, instance=True)
    for name, _ in inspect.getmembers(cls, callable):
        if name.startswith("__") or name in qtb.INVENTORY_READ_METHODS:
            continue
        try:
            getattr(fake, name).side_effect = AssertionError(f"inventory called {name}")
        except AttributeError:
            pass
    return fake


LIVE_SAMPLE = FIXTURES / "live_term_sample_Q-0001.json"
LIVE_GLOSSARY_GUID = "22dc03e9-a981-41c2-814e-bacbdad9fa9f"
LIVE_GLOSSARY_QN = "Coco Pharmaceuticals::Glossary::User-Questions::1.0"


def _live_term() -> dict:
    """The live Egeria answer for Q-0001 (pyegeria 6.2.9 find_glossary_terms, JSON), verbatim."""
    return json.loads(LIVE_SAMPLE.read_text(encoding="utf-8"))


def _live_glossary() -> dict:
    """The glossary entry get_glossaries_by_name answers with, taken from the sample's own membership."""
    related = _live_term()["memberOfCollections"][0]["relatedElement"]
    return {"elementHeader": related["elementHeader"], "properties": related["properties"]}


LIVE_RELATED = FIXTURES / "live_related_sample_Q-0001.json"


def _live_related() -> dict:
    """The live get_all_related_elements answer for Q-0001's term (pyegeria 6.2.9), verbatim: six ScopedBy with
    a survey process at end 1, the Scouting stage and three perspectives at end 2, and the CollectionMembership."""
    return json.loads(LIVE_RELATED.read_text(encoding="utf-8"))


def _replacement_item(guid: str, qualified_name: str, display_name: str) -> dict:
    """A ReplacementTerm item built from the live sample's own GlossaryTerm item (the Scouting stage): only the
    relationship type and GUID and the other element's GUID and names changed; the survivor at end 2."""
    item = copy.deepcopy(next(e for e in _live_related()["elementList"]
                              if e["element"]["type"]["typeName"] == "GlossaryTerm"))
    item["type"]["typeName"] = "ReplacementTerm"
    item["relationshipGUID"] = f"rt-{guid}"
    item["elementAtEnd1"] = False
    item["element"]["elementGUID"] = guid
    pvm = item["element"]["elementProperties"]["propertyValueMap"]
    pvm["qualifiedName"]["primitiveValue"] = qualified_name
    pvm["displayName"]["primitiveValue"] = display_name
    return item


def _term_element(guid, name, glossary=LIVE_GLOSSARY_GUID, qid=None, *, scopes=True):
    """A variant of the LIVE sample: its guid, names and membership target changed, nothing invented."""
    t = _live_term()
    t["elementHeader"]["guid"] = guid
    t["properties"].update(qualifiedName=f"QN::{name}", displayName=name)
    if qid:
        t["properties"]["additionalProperties"] = {"question_id": qid}
    t["memberOfCollections"][0]["relatedElement"]["elementHeader"]["guid"] = glossary
    if glossary != LIVE_GLOSSARY_GUID:
        t["memberOfCollections"][0]["relatedElement"]["properties"]["qualifiedName"] = f"QN::{glossary}"
    if not scopes:
        t["relevantToScopes"] = []
    return t


def _old_shape_only(element: dict, glossary_guid: str) -> dict:
    """The shape the first builder read: an Anchors classification naming the glossary, no membership."""
    e = copy.deepcopy(element)
    e.pop("memberOfCollections", None)
    e["elementHeader"]["classifications"] = [{"classificationName": "Anchors",
                                              "classificationProperties": {"anchorScopeGUID": glossary_guid}}]
    return e


def _fakes():
    from pyegeria.omvs.glossary_manager import GlossaryManager
    from pyegeria.omvs.metadata_expert import MetadataExpert
    return _read_only_fake(GlossaryManager), _read_only_fake(MetadataExpert)


def test_inventory_reads_only_and_records_links(monkeypatch):
    from pyegeria.omvs.glossary_manager import GlossaryManager
    from pyegeria.omvs.metadata_expert import MetadataExpert

    gm, me = _read_only_fake(GlossaryManager), _read_only_fake(MetadataExpert)
    gm.get_glossaries_by_name.return_value = [
        _live_glossary(),
        {"elementHeader": {"guid": "g-other"}, "properties": {"displayName": "User Questions (old)"}}]
    page1 = [_term_element("t1", "Q one?", qid="Q-0001", scopes=False), _term_element("t2", "Q two?", scopes=False),
             _term_element("x1", "Elsewhere", "g-other")]
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: page1 if start_from == 0 else "No elements found"

    def related(guid, **kw):
        if kw.get("start_from"):
            return "No elements found"
        if guid == "t2":
            return "No elements found"
        answer = _live_related()  # the LIVE get_all_related_elements answer, plus one ReplacementTerm of its shape
        answer["elementList"].append(_replacement_item("t9", "QN::nine", "nine"))
        return answer
    me.get_all_related_elements.side_effect = related

    inv = qtb.read_inventory(gm, me, "User Questions", page_size=3, now="T")
    assert inv["schema"] == qtb.INVENTORY_SCHEMA and inv["read_errors"] == []
    assert [(t["guid"], t["question_id"]) for t in inv["terms"]] == [("t1", "Q-0001"), ("t2", None)]
    assert [l["relationship"] for l in inv["terms"][0]["links"]] == ["ScopedBy"] * 4 + ["ReplacementTerm"]
    assert inv["terms"][0]["additional_properties"] == {"question_id": "Q-0001"}
    assert inv["terms"][1]["links"] == [] and inv["terms"][1]["additional_properties"] == {}
    # every term read is kept, the one in another glossary too
    assert [(t["guid"], t["display_name"]) for t in inv["all_terms"]] == [
        ("x1", "Elsewhere"), ("t1", "Q one?"), ("t2", "Q two?")]
    called = {c[0].split(".")[0] for m in (gm, me) for c in m.mock_calls if c[0]}
    assert called <= set(qtb.INVENTORY_READ_METHODS)


def test_inventory_records_a_failed_link_read_and_the_plan_refuses_it():
    from pyegeria.omvs.glossary_manager import GlossaryManager
    from pyegeria.omvs.metadata_expert import MetadataExpert

    gm, me = _read_only_fake(GlossaryManager), _read_only_fake(MetadataExpert)
    gm.get_glossaries_by_name.return_value = [_live_glossary()]
    gm.find_glossary_terms.return_value = [_term_element("t1", "Q?", qid="Q-0001")]
    me.get_all_related_elements.return_value = None  # pyegeria's dynamic_catch on a failure: not "no links"
    inv = qtb.read_inventory(gm, me, "User Questions", now="T")
    assert [e["guid"] for e in inv["read_errors"]] == ["t1"]
    with pytest.raises(qtb.PlanInputError):
        qtb.build_plan([], [], inv)


def test_inventory_refuses_an_answer_it_cannot_read():
    from pyegeria.omvs.glossary_manager import GlossaryManager
    from pyegeria.omvs.metadata_expert import MetadataExpert

    gm, me = _read_only_fake(GlossaryManager), _read_only_fake(MetadataExpert)
    gm.get_glossaries_by_name.return_value = None
    with pytest.raises(qtb.InventoryReadError):
        qtb.read_inventory(gm, me, "User Questions")
    gm.get_glossaries_by_name.return_value = [{"elementHeader": {"guid": "g"}, "properties": {"displayName": "UQ"}}]
    gm.find_glossary_terms.return_value = [{"elementHeader": {"guid": "t"}, "properties": {"displayName": "x"}}]
    with pytest.raises(qtb.InventoryReadError, match="none a member of"):
        qtb.read_inventory(gm, me, "UQ")


# ---------------------------------------------------------------------------
# inventory: the live term shape (tests/fixtures/question_term_batch/live_term_sample_Q-0001.json)
# ---------------------------------------------------------------------------

def test_live_shape_is_read_membership_scopes_and_classifications():
    gm, me = _fakes()
    gm.get_glossaries_by_name.return_value = [_live_glossary()]
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: [_live_term()] if start_from == 0 else []
    me.get_all_related_elements.return_value = "No elements found"
    inv = qtb.read_inventory(gm, me, "User Questions", now="T")
    assert inv["read_errors"] == [] and inv["glossary"]["qualified_name"] == LIVE_GLOSSARY_QN
    (t,) = inv["terms"]
    assert t["guid"] == "318f1291-a825-4f67-81b1-f9fd1d18e6e3"
    assert t["display_name"] == "Is this repository actively maintained?"
    assert t["question_id"] is None and t["content_status"] == "ACTIVE"   # no additionalProperties on live terms
    assert "Question" in t["classifications"]
    assert qtb._term_perspectives(t) == {"Perspective::Data Expert", "Perspective::Consumer", "Perspective::Steward"}
    assert qtb._term_stages(t) == {"Scouting"}
    # scopedElements (the term as the scope of survey processes) are not the term's own scopes
    assert all(l["type"] != "GovernanceActionProcess" for l in t["links"])


def test_the_old_anchors_shape_alone_is_refused():
    gm, me = _fakes()
    gm.get_glossaries_by_name.return_value = [_live_glossary()]
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: (
        [_old_shape_only(_live_term(), LIVE_GLOSSARY_GUID)] if start_from == 0 else [])
    with pytest.raises(qtb.InventoryReadError, match="1 terms read, none a member of 'User Questions'"):
        qtb.read_inventory(gm, me, "User Questions", now="T")


def test_membership_falls_back_to_qualified_name_never_display_name():
    gm, me = _fakes()
    gm.get_glossaries_by_name.return_value = [_live_glossary()]
    by_qn = _term_element("t-qn", "by qn")
    del by_qn["memberOfCollections"][0]["relatedElement"]["elementHeader"]["guid"]
    by_dn = _term_element("t-dn", "by display name only")
    rel = by_dn["memberOfCollections"][0]["relatedElement"]
    del rel["elementHeader"]["guid"]
    rel["properties"]["qualifiedName"] = "Other::Glossary::User-Questions::1.0"  # displayName still "User Questions"
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: [by_qn, by_dn] if start_from == 0 else []
    me.get_all_related_elements.return_value = "No elements found"
    inv = qtb.read_inventory(gm, me, "User Questions", now="T")
    assert [t["guid"] for t in inv["terms"]] == ["t-qn"]


def test_a_link_in_both_reads_is_recorded_once():
    gm, me = _fakes()
    gm.get_glossaries_by_name.return_value = [_live_glossary()]
    live = _live_term()
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: [live] if start_from == 0 else []
    scope = live["relevantToScopes"][0]
    me.get_all_related_elements.side_effect = lambda guid, start_from=0, **kw: "No elements found" if start_from else {
        "elementList": [{"type": {"typeName": "ScopedBy"}, "elementAtEnd1": False,
                         "relationshipGUID": scope["relationshipHeader"]["guid"],
                         "element": {"elementGUID": scope["relatedElement"]["elementHeader"]["guid"],
                                     "type": {"typeName": "GlossaryTerm"},
                                     "elementProperties": {"propertiesAsStrings": {
                                         "qualifiedName": "Coco Pharmaceuticals::Term::Scouting::1.0",
                                         "displayName": "Scouting"}}}}]}
    (t,) = qtb.read_inventory(gm, me, "User Questions", now="T")["terms"]
    assert len(t["links"]) == len(live["relevantToScopes"]) == 4


def _live_rows():
    """The real CSV's Q-0001 row, before and after #842 (the question was not reworded)."""
    rows = qtb.read_csv_rows(qtb.CSV_PATH.read_text(encoding="utf-8"))
    return [r for r in rows if r["Question ID"] == "Q-0001"]


def test_live_term_plans_by_old_name_sets_question_id_adds_no_link_and_replans_empty():
    gm, me = _fakes()
    gm.get_glossaries_by_name.return_value = [_live_glossary()]
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: [_live_term()] if start_from == 0 else []
    me.get_all_related_elements.return_value = "No elements found"
    inventory = qtb.read_inventory(gm, me, "User Questions", now="T")
    rows = _live_rows()
    plan = qtb.build_plan(rows, rows, inventory)
    (rp,) = plan.rows
    assert rp.join_path == "old_name" and rp.action == "update" and "question_id" in rp.changed_fields
    assert [c.kind for c in rp.commands] == ["update"]  # perspectives and the Scouting stage are already linked
    assert rp.commands[0].fields["Qualified Name"] == "Coco Pharmaceuticals::Term::Is-this-repository-actively-maintained?::1.0"
    applied = _apply(inventory, qtb.render_document(plan))
    second = qtb.build_plan(rows, rows, applied)
    assert second.commands() == [] and [r.join_path for r in second.rows] == ["question_id"]


# ---------------------------------------------------------------------------
# fix round 2 (architect rulings 2026-10-23): missing terms and leftover terms
# ---------------------------------------------------------------------------

def test_active_row_missing_in_egeria_is_created_and_counted_apart(after, before, inventory):
    # Q-0005: active, pre-edit row; gone from the glossary AND from every term read
    inventory["terms"] = [t for t in inventory["terms"] if t["guid"] != "term-05"]
    inventory["all_terms"] = [t for t in inventory["all_terms"] if t["guid"] != "term-05"]
    plan = qtb.build_plan(after, before, inventory)
    assert plan.unplaceable == []
    q5 = _row(plan, "Q-0005")
    assert (q5.join_path, q5.action, q5.missing_in_egeria) == ("not_found", "create", True)
    assert [c.kind for c in q5.commands][:2] == ["create", "classify"]
    assert "| question_id | Q-0005 |" in q5.commands[0].fields["Additional Properties"]
    assert {c.kind for c in q5.commands[2:]} <= {"link_perspective", "link_stage"} and q5.commands[2:]
    assert _row(plan, "Q-0009").missing_in_egeria is False  # a row new in the edit is not "missing"
    assert plan.proof()["created: missing in Egeria"] == 1
    assert plan.counts()["created_missing_in_egeria"] == ["Q-0005"]
    assert "created: missing in Egeria 1 (Q-0005)" in qtb.format_counts(plan)


def _leftover(guid, name, description="old text"):
    return {"guid": guid, "qualified_name": f"Org::Term::{name}::1.0", "display_name": name,
            "description": description, "summary": "", "usage": "", "content_status": "ACTIVE",
            "element_status": "ACTIVE", "question_id": None, "additional_properties": {},
            "classifications": ["Anchors", "Question"],
            "links": [{"relationship": "ScopedBy", "relationship_guid": "r-lo", "other_at_end1": False,
                       "guid": "persp-Steward", "type": "Perspective", "qualified_name": "Perspective::Steward",
                       "display_name": "Steward"}]}


def test_leftover_in_the_map_is_deprecated_with_a_replacement_to_its_survivor(after, before, inventory, monkeypatch):
    monkeypatch.setattr(qtb, "LEFTOVER_SURVIVORS", {"Old cost?": ("bbbab254", "Q-0001")})
    inventory["terms"].append(_leftover("bbbab254-0000", "Old cost?"))
    plan = qtb.build_plan(after, before, inventory)
    (lo,) = [r for r in plan.leftovers if r.term["guid"] == "bbbab254-0000"]
    assert (lo.action, lo.survivor_id, lo.question_id) == ("deprecate_leftover", "Q-0001", "")
    dep, rep = lo.commands
    assert dep.fields == {"GUID": "bbbab254-0000", "Qualified Name": "Org::Term::Old cost?::1.0",
                          "Display Name": "Old cost?",
                          "Description": "retired before 2026-10-22: no longer in the question list — old text",
                          "Status": "DEPRECATED"}  # no Additional Properties: ids are never invented
    assert rep.fields == {"Term 1": "Org::Term::Old cost?::1.0", "Term 2": "Org::Term::What-is-A?::1.0",
                          "Relationship Type": "ReplacementTerm"}
    assert not any(c.command.startswith(("Unlink", "Detach", "Remove", "Delete")) for c in plan.commands())
    assert plan.proof()["deprecated: leftovers"] == 2  # this one and the fixture's "Scouting"
    assert "Leftover terms no question row names" in qtb.render_document(plan)


def test_leftover_not_in_the_map_is_deprecated_without_a_replacement_and_listed(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    (lo,) = plan.leftovers
    assert lo.term["guid"] == "term-stage-scouting" and lo.survivor_id is None
    assert [c.kind for c in lo.commands] == ["deprecate_leftover"]
    assert plan.counts()["leftovers"] == [{"guid": "term-stage-scouting", "display_name": "Scouting",
                                           "action": "deprecate_leftover", "survivor": None}]
    assert "leftover term-stage-scouting 'Scouting': deprecate_leftover, no replacement" in qtb.format_counts(plan)


def test_mapped_leftover_name_on_another_guid_is_unplaceable(after, before, inventory, monkeypatch):
    monkeypatch.setattr(qtb, "LEFTOVER_SURVIVORS", {"Old cost?": ("bbbab254", "Q-0001")})
    inventory["terms"].append(_leftover("99999999-0000", "Old cost?"))
    plan = qtb.build_plan(after, before, inventory)
    (bad,) = plan.unplaceable
    assert bad.term["guid"] == "99999999-0000" and "bbbab254" in bad.reason and bad.commands == []


def test_a_term_a_row_still_names_is_not_a_leftover(after, before, inventory):
    """Two terms named like Q-0004's row: Q-0004 joins by id; the other is named by a row, so left alone."""
    inventory["terms"].append(_leftover("term-d-copy", "D?"))
    plan = qtb.build_plan(after, before, inventory)
    assert [t["guid"] for t in plan.unknown_terms] == ["term-d-copy"]
    assert "term-d-copy" not in {r.term["guid"] for r in plan.leftovers}


def test_end_to_end_with_leftovers_replans_empty(after, before, inventory, monkeypatch):
    monkeypatch.setattr(qtb, "LEFTOVER_SURVIVORS", {"Old cost?": ("bbbab254", "Q-0009")})  # survivor created here
    inventory["terms"].append(_leftover("bbbab254-0000", "Old cost?", description=""))
    first = qtb.build_plan(after, before, inventory)
    (rep,) = [c for r in first.leftovers for c in r.commands if c.kind == "link_replacement"]
    assert rep.fields["Term 2"] == "Org::Term::I-new?::1.0"
    applied = _apply(inventory, qtb.render_document(first))
    lo = next(t for t in applied["terms"] if t["guid"] == "bbbab254-0000")
    assert lo["content_status"] == "DEPRECATED" and lo["question_id"] is None
    assert lo["description"] == qtb.LEFTOVER_PREFIX and len(lo["links"]) == 2  # Steward kept + ReplacementTerm
    second = qtb.build_plan(after, before, applied)
    assert second.commands() == [] and second.unplaceable == []
    assert {r.action for r in second.leftovers} == {"unchanged"}


# the real inventory the coordinator took 2026-10-23T02:04Z (read-only), and the CSVs it was planned against
LIVE_INVENTORY = FIXTURES / "live_inventory_2026-10-23.json"
LIVE_CSV_BEFORE = FIXTURES / "live_csv_before_d7a395a4.csv"
LIVE_CSV_AFTER = FIXTURES / "live_csv_after_24da909b.csv"


def _live_plan_inputs():
    return (_rows(LIVE_CSV_AFTER.name), _rows(LIVE_CSV_BEFORE.name),
            json.loads(LIVE_INVENTORY.read_text(encoding="utf-8")))


def test_real_inventory_plans_these_counts_and_writes_nothing_from_a_schema_1_inventory(tmp_path, capsys):
    """The 2026-10-23T02:04Z inventory is schema /1: no all-terms list, no additionalProperties map. The plan is
    counted and printed with both gaps named, and no document is written: the coordinator re-takes it."""
    out = tmp_path / "batch.md"
    rc = qtb.main(["plan", "--inventory", str(LIVE_INVENTORY), "--out", str(out), "--csv", str(LIVE_CSV_AFTER),
                   "--old-csv", str(LIVE_CSV_BEFORE)])
    captured = capsys.readouterr()
    printed = captured.out
    assert rc == 1 and not out.exists()
    assert "NOT ESTABLISHED: no all-terms list: a create was checked against the 98 glossary terms only, not every " \
           "term read (991)" in printed
    assert "NOT ESTABLISHED: no additionalProperties map" in printed
    assert "Take a fresh inventory with this version" in captured.err
    assert ("found by name 94, by id 2, id set on 94, created: missing in Egeria 1 (Q-0073), "
            "deprecated: leftovers 2") in printed
    plan = qtb.build_plan(*_live_plan_inputs())
    c = plan.counts()
    assert c["rows"] == 105 and c["unplaceable"] == 0 and c["unknown_terms"] == 0
    assert c["join_path"] == {"not_found": 9, "old_name": 94, "question_id": 2}
    assert c["action"] == {"create": 9, "deprecate_merged": 9, "deprecate_retired": 2, "unchanged": 2, "update": 83}
    assert c["command_kind"] == {"classify": 9, "create": 9, "deprecate": 11, "deprecate_leftover": 2,
                                 "link_perspective": 31, "link_replacement": 11, "link_stage": 14, "update": 83}
    assert c["commands_total"] == 170
    assert c["created_missing_in_egeria"] == ["Q-0073"] and c["deprecate_no_term"] == []
    survivors = {lo["guid"][:8]: lo["survivor"] for lo in c["leftovers"]}
    assert survivors == {"bbbab254": "Q-0016", "ccc5d55b": "Q-0044"}
    for lo in plan.leftovers:
        (rep,) = [x for x in lo.commands if x.kind == "link_replacement"]
        assert rep.fields["Term 2"] == _row(plan, lo.survivor_id).term["qualified_name"]
        assert "Additional Properties" not in lo.commands[0].fields


def test_real_inventory_replans_empty_after_apply():
    after_rows, before_rows, inventory = _live_plan_inputs()
    first = qtb.build_plan(after_rows, before_rows, inventory)
    applied = _apply(inventory, qtb.render_document(first))
    second = qtb.build_plan(after_rows, before_rows, applied)
    assert second.commands() == [] and second.unplaceable == []
    assert {r.join_path for r in second.rows if r.term is not None} == {"question_id"}
    assert [(r.term["content_status"], r.action) for r in second.leftovers] == [("DEPRECATED", "unchanged")] * 2
    assert second.proof()["deprecated: leftovers"] == 0 and second.proof()["created: missing in Egeria"] == 0


# ---------------------------------------------------------------------------
# fix round 3 (Opus review 2026-10-23)
# ---------------------------------------------------------------------------

def _updates(plan):
    return [c for c in plan.commands() if c.command == "Update Glossary Term"]


def test_every_update_and_deprecation_carries_the_guid_and_its_qualified_name(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    term_of = {id(c): r.term for r in plan.rows + plan.leftovers for c in r.commands}
    updates = _updates(plan)
    assert {c.kind for c in updates} == {"update", "deprecate", "deprecate_leftover"}
    for c in updates:
        assert (c.fields["GUID"], c.fields["Qualified Name"]) == (term_of[id(c)]["guid"],
                                                                  term_of[id(c)]["qualified_name"])
    doc = qtb.render_document(plan)
    assert doc.count("### GUID\n") == len(updates)
    assert "VALIDATE must show no \"Rewriting ... to 'Create'\"; if it does, STOP" in doc


def test_the_installed_dr_egeria_honours_an_explicit_guid_before_any_name():
    """processors.py fetch_as_is: '### GUID' is fetched first, so an Update is not rewritten to a Create when
    its qualifiedName lookup fails. A pyegeria that dropped this would make the GUID decoration."""
    from md_processing.v2.processors import AsyncBaseCommandProcessor
    source = inspect.getsource(AsyncBaseCommandProcessor.fetch_as_is)
    guid_at = source.index('explicit_guid = self.parsed_output.get("attributes", {}).get("GUID", {}).get("value")')
    assert guid_at < source.index('qn = self.parsed_output.get("qualified_name")')


def test_real_inventory_every_update_carries_a_guid():
    plan = qtb.build_plan(*_live_plan_inputs())
    updates = _updates(plan)
    assert len(updates) == 83 + 11 + 2 and all(c.fields["GUID"] for c in updates)
    assert qtb.render_document(plan).count("### GUID\n") == 96


def test_updates_send_only_what_changed_plus_the_locator(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    (q2,) = _row(plan, "Q-0002").commands  # only question_id changed
    assert list(q2.fields) == ["GUID", "Qualified Name", "Display Name", "Additional Properties"]
    assert q2.fields["Display Name"] == "Is B?"  # the term's own: Display Name is required, not a change
    q3 = _row(plan, "Q-0003").commands[0]  # reworded: the new name rides in Display Name
    assert q3.fields["Display Name"] == _row(plan, "Q-0003").question != "C?"
    assert set(q3.fields) - {"GUID", "Qualified Name", "Display Name", "Additional Properties"} == {
        label for label in _row(plan, "Q-0003").changed_fields if label != "Display Name" and label != "question_id"}


def test_question_id_is_merged_into_the_whole_additional_properties_map(after, before, inventory):
    t2 = next(t for t in inventory["terms"] if t["guid"] == "term-02")
    t2["additional_properties"] = {"source": "scouting-questions.md", "owner": "stewards"}
    plan = qtb.build_plan(after, before, inventory)
    table = _row(plan, "Q-0002").commands[0].fields["Additional Properties"]
    assert table.splitlines()[2:] == ["| source | scouting-questions.md |", "| owner | stewards |",
                                      "| question_id | Q-0002 |"]
    applied = _apply(inventory, qtb.render_document(plan))
    assert next(t for t in applied["terms"] if t["guid"] == "term-02")["additional_properties"] == {
        "source": "scouting-questions.md", "owner": "stewards", "question_id": "Q-0002"}
    assert qtb.build_plan(after, before, applied).commands() == []


def test_a_map_that_cannot_be_written_back_unchanged_is_unplaceable(after, before, inventory):
    next(t for t in inventory["terms"] if t["guid"] == "term-02")["additional_properties"] = {"note": "a | b"}
    plan = qtb.build_plan(after, before, inventory)
    assert [r.question_id for r in plan.unplaceable] == ["Q-0002"] and _row(plan, "Q-0002").commands == []


def test_an_active_term_without_the_question_classification_is_classified(after, before, inventory):
    next(t for t in inventory["terms"] if t["guid"] == "term-04")["classifications"] = ["Anchors"]  # like bbbab254
    plan = qtb.build_plan(after, before, inventory)
    q4 = _row(plan, "Q-0004")
    assert q4.action == "links_only"
    assert [(c.command, c.fields) for c in q4.commands] == [
        ("Classify Term as Question", {"Term Name": "Org::Term::D?::1.0"})]
    applied = _apply(inventory, qtb.render_document(plan))
    assert "Question" in next(t for t in applied["terms"] if t["guid"] == "term-04")["classifications"]
    assert qtb.build_plan(after, before, applied).commands() == []


def test_live_related_sample_is_read_scopes_only_at_end_2():
    links = qtb.links_from_related(_live_related(), "live")
    assert [(l["type"], l["qualified_name"]) for l in links] == [
        ("GlossaryTerm", "Coco Pharmaceuticals::Term::Scouting::1.0"), ("Perspective", "Perspective::Data Expert"),
        ("Perspective", "Perspective::Consumer"), ("Perspective", "Perspective::Steward")]
    assert all(l["relationship"] == "ScopedBy" and not l["other_at_end1"] for l in links)
    term = {"links": links}
    assert qtb._term_stages(term) == {"Scouting"}
    assert qtb._term_perspectives(term) == {"Perspective::Data Expert", "Perspective::Consumer",
                                            "Perspective::Steward"}


def test_a_replacement_term_in_the_live_item_shape_is_not_planned_again():
    """Q-0001's live term is the survivor; a second term (old name 'Old dup?') merged into it already has the
    ReplacementTerm, read from an item of the live related-elements shape: the re-plan only deprecates."""
    gm, me = _fakes()
    gm.get_glossaries_by_name.return_value = [_live_glossary()]
    survivor = _live_term()
    absorbed = _term_element("b0b0b0b0-0000-0000-0000-000000000001", "Old dup?", scopes=False)
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: [survivor, absorbed] if start_from == 0 else []
    survivor_qn = survivor["properties"]["qualifiedName"]

    def related(guid, start_from=0, **kw):
        if start_from:
            return "No elements found"
        if guid == absorbed["elementHeader"]["guid"]:
            return {"elementList": [_replacement_item(survivor["elementHeader"]["guid"], survivor_qn,
                                                      survivor["properties"]["displayName"])]}
        return _live_related()
    me.get_all_related_elements.side_effect = related
    inventory = qtb.read_inventory(gm, me, "User Questions", now="T")
    (q1,) = _live_rows()
    dup = dict(q1, **{"Question ID": "Q-0999", "Question": "Old dup?", "Status": "merged into Q-0001 2026-10-22"})
    plan = qtb.build_plan([q1, dup], [q1, dup], inventory)
    q999 = _row(plan, "Q-0999")
    assert q999.action == "deprecate_merged" and [c.kind for c in q999.commands] == ["deprecate"]
    assert not [c for c in plan.commands() if c.kind == "link_replacement"]


def test_a_create_that_collides_with_any_term_read_is_unplaceable(after, before, inventory):
    # a term in another glossary under Q-0009's name: never seen by the glossary read, seen in all_terms
    inventory["all_terms"].append({"guid": "elsewhere-1", "qualified_name": "Other::Term::I-new?::1.0",
                                   "display_name": "I new?"})
    plan = qtb.build_plan(after, before, inventory)
    q9 = _row(plan, "Q-0009")
    assert q9.action == "unplaceable" and "elsewhere-1" in q9.reason and q9.commands == []
    assert "Q-0008" in [r.question_id for r in plan.unplaceable]  # its survivor is not placed


def test_a_create_whose_derived_qualified_name_is_taken_is_unplaceable(after, before, inventory):
    inventory["all_terms"].append({"guid": "qn-1", "qualified_name": "Org::Term::I-new?::1.0",
                                   "display_name": "Something else"})
    q9 = _row(qtb.build_plan(after, before, inventory), "Q-0009")
    assert q9.action == "unplaceable" and "'Org::Term::I-new?::1.0'" in q9.reason and "qn-1" in q9.reason


def test_a_create_is_refused_when_a_term_with_another_id_has_the_rows_name(after, before, inventory):
    """Item 5: the name check counts terms WITH a question_id too (the join only looks at id-less ones)."""
    other = copy.deepcopy(next(t for t in inventory["terms"] if t["guid"] == "term-04"))
    other.update(guid="term-x", qualified_name="Org::Term::I-new-x?::1.0", display_name="I new?",
                 question_id="Q-0777", additional_properties={"question_id": "Q-0777"})
    inventory["terms"].append(other)
    q9 = _row(qtb.build_plan(after, before, inventory), "Q-0009")
    assert q9.action == "unplaceable" and "term-x" in q9.reason


def test_created_terms_are_named_by_their_derived_qualified_name(after, before, inventory):
    plan = qtb.build_plan(after, before, inventory)
    q9 = _row(plan, "Q-0009")
    create, classify, *links = q9.commands
    assert create.fields["Qualified Name"] == q9.created_qn == "Org::Term::I-new?::1.0"
    assert classify.fields == {"Term Name": q9.created_qn}
    assert links and all(q9.created_qn in (c.fields.get("Question Name"), c.fields.get("Target Element"))
                         for c in links)


def test_a_schema_1_inventory_names_its_gaps_and_a_schema_2_one_has_none(after, before, inventory, tmp_path):
    assert qtb.build_plan(after, before, inventory).input_gaps == []
    legacy = copy.deepcopy(inventory)
    legacy["schema"] = qtb.LEGACY_INVENTORY_SCHEMA
    del legacy["all_terms"]
    for t in legacy["terms"]:
        del t["additional_properties"]
    assert len(qtb.build_plan(after, before, legacy).input_gaps) == 2
    for inv, rc_expected in ((inventory, 0), (legacy, 1)):
        src, out = tmp_path / f"inv-{rc_expected}.json", tmp_path / f"out-{rc_expected}.md"
        src.write_text(json.dumps(inv))
        rc = qtb.main(["plan", "--inventory", str(src), "--out", str(out), "--csv", str(FIXTURES / "after.csv"),
                       "--old-csv", str(FIXTURES / "before.csv")])
        assert (rc, out.exists()) == (rc_expected, rc_expected == 0)


def _no_duplicates(inventory: dict) -> None:
    qns = [t["qualified_name"] for t in inventory["terms"]]
    assert len(qns) == len(set(qns)), "a term was created twice"
    for t in inventory["terms"]:
        keys = [(l["relationship"], l["qualified_name"]) for l in t["links"]]
        assert len(keys) == len(set(keys)), (t["qualified_name"], "a link was added twice")
        assert t["classifications"].count("Question") <= 1


@pytest.mark.parametrize("which", ["fixture", "live"])
def test_a_partial_apply_replans_the_remainder_without_repeating_anything(which, after, before, inventory):
    """Item 9: PROCESS stops after N commands; a fresh inventory and plan finishes the job, repeating no create,
    link or classification, for every N (the live inventory at a spread of N)."""
    args = (after, before, inventory) if which == "fixture" else _live_plan_inputs()
    first = qtb.build_plan(*args)
    doc, total = qtb.render_document(first), len(first.commands())
    steps = range(total + 1) if which == "fixture" else sorted({0, 1, 2, 9, 10, 18, 40, 83, 120, 169, total})
    for n in steps:
        partial = _apply(args[2], doc, limit=n)
        second = qtb.build_plan(args[0], args[1], partial)
        assert second.unplaceable == [], n
        created = {c.question_id for c in first.commands()[:n] if c.kind == "create"}
        assert not [c for c in second.commands() if c.kind == "create" and c.question_id in created], n
        done = _apply(partial, qtb.render_document(second))
        _no_duplicates(done)
        assert qtb.build_plan(args[0], args[1], done).commands() == [], n
