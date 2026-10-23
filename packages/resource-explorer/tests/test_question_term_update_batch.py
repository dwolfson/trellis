"""scripts/question_term_update_batch.py: the Egeria update for the 2026-10-22 questions edit (#842).

The fixture (tests/fixtures/question_term_batch/) is a ten-row CSV pair and an inventory covering the join paths
(question_id, pre-edit-name fallback, not found), an id-less term, an existing link that must not be re-added, a
merge whose ReplacementTerm already exists, a merge into a NEW term, and a stray term the CSV does not name. The
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
    assert c["command_kind"] == {"classify": 1, "create": 1, "deprecate": 4, "link_perspective": 2,
                                 "link_replacement": 2, "link_stage": 2, "update": 4}
    assert c["commands_total"] == 16
    assert c["unplaceable"] == 0
    assert c["unknown_terms"] == 1  # the stray "Scouting" term: listed, left alone


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
    assert update.fields["Qualified Name"] == "Org::Term::Is-B?::1.0"
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
    # survivor is new: named by its display name, created earlier in the same document
    (rep8,) = [c for c in _row(plan, "Q-0008").commands if c.kind == "link_replacement"]
    assert rep8.fields["Term 2"] == "I new?"
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


def test_term_not_found_by_either_path_is_unplaceable(after, before, inventory):
    inventory["terms"] = [t for t in inventory["terms"] if t["guid"] != "term-06"]
    plan = qtb.build_plan(after, before, inventory)
    assert [(r.question_id, r.join_path) for r in plan.unplaceable] == [("Q-0006", "not_found")]


def test_inventory_with_read_errors_is_refused(after, before, inventory):
    inventory["read_errors"] = [{"guid": "term-01", "error": "timeout"}]
    with pytest.raises(qtb.PlanInputError, match="read error"):
        qtb.build_plan(after, before, inventory)


def test_cli_exits_nonzero_and_writes_nothing_when_unplaceable(tmp_path, inventory):
    inventory["terms"] = [t for t in inventory["terms"] if t["guid"] != "term-06"]
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


def _apply(inventory: dict, text: str) -> dict:
    """What a fully successful PROCESS of the document leaves in Egeria, as the next inventory would show it."""
    inv = copy.deepcopy(inventory)
    terms = inv["terms"]

    def find(ref):
        hits = [t for t in terms if ref in (t["qualified_name"], t["display_name"])]
        assert len(hits) == 1, ref
        return hits[0]

    def qid_of(table):
        m = re.search(r"\|\s*question_id\s*\|\s*(Q-\d{4})\s*\|", table or "")
        return m.group(1) if m else None

    for n, c in enumerate(_extract(text)):
        a, name = c.attributes, f"{c.verb} {c.object_type}"
        if name == "Create Glossary Term":
            terms.append({"guid": f"new-{n}", "qualified_name": f"Org::Term::{a['Display Name']}::1.0",
                          "display_name": a["Display Name"], "description": a.get("Description", ""),
                          "summary": a.get("Summary", ""), "usage": a.get("Usage", ""), "content_status": "ACTIVE",
                          "element_status": "ACTIVE", "question_id": qid_of(a.get("Additional Properties")),
                          "classifications": ["Anchors"], "links": []})
        elif name == "Classify Term as Question":
            find(a["Term Name"])["classifications"].append("Question")
        elif name == "Update Glossary Term":
            t = find(a["Qualified Name"])
            t["display_name"] = a["Display Name"]
            for label, key in (("Description", "description"), ("Summary", "summary"), ("Usage", "usage")):
                if label in a:
                    t[key] = a[label]
            if "Status" in a:
                t["content_status"] = a["Status"]
            if qid_of(a.get("Additional Properties")):
                t["question_id"] = qid_of(a["Additional Properties"])
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


def _term_element(guid, name, glossary, qid=None):
    props = {"qualifiedName": f"QN::{name}", "displayName": name, "description": "d", "summary": "s",
             "usage": "u", "contentStatus": "ACTIVE"}
    if qid:
        props["additionalProperties"] = {"question_id": qid}
    return {"elementHeader": {"guid": guid, "status": "ACTIVE",
                              "anchor": {"classificationName": "Anchors",
                                         "classificationProperties": {"anchorScopeGUID": glossary}}},
            "properties": props}


def test_inventory_reads_only_and_records_links(monkeypatch):
    from pyegeria.omvs.glossary_manager import GlossaryManager
    from pyegeria.omvs.metadata_expert import MetadataExpert

    gm, me = _read_only_fake(GlossaryManager), _read_only_fake(MetadataExpert)
    gm.get_glossaries_by_name.return_value = [
        {"elementHeader": {"guid": "g-uq"}, "properties": {"displayName": "User Questions"}},
        {"elementHeader": {"guid": "g-other"}, "properties": {"displayName": "User Questions (old)"}}]
    page1 = [_term_element("t1", "Q one?", "g-uq", "Q-0001"), _term_element("t2", "Q two?", "g-uq"),
             _term_element("x1", "Elsewhere", "g-other")]
    gm.find_glossary_terms.side_effect = lambda *a, start_from=0, **k: page1 if start_from == 0 else "No elements found"

    def related(guid, **kw):
        if kw.get("start_from"):
            return "No elements found"
        if guid == "t2":
            return "No elements found"
        return {"elementList": [
            {"type": {"typeName": "ScopedBy"}, "elementAtEnd1": False, "relationshipGUID": "r1",
             "element": {"elementGUID": "p1", "type": {"typeName": "Perspective"},
                         "elementProperties": {"propertiesAsStrings": {"qualifiedName": "Perspective::Steward",
                                                                       "displayName": "Steward"}}}},
            {"type": {"typeName": "ReplacementTerm"}, "elementAtEnd1": False, "relationshipGUID": "r2",
             "element": {"elementGUID": "t9", "type": {"typeName": "GlossaryTerm"},
                         "elementProperties": {"propertiesAsStrings": {"qualifiedName": "QN::nine"}}}},
            {"type": {"typeName": "CollectionMembership"}, "elementAtEnd1": True, "relationshipGUID": "r3",
             "element": {"elementGUID": "g-uq"}}]}
    me.get_all_related_elements.side_effect = related

    inv = qtb.read_inventory(gm, me, "User Questions", page_size=3, now="T")
    assert inv["schema"] == qtb.INVENTORY_SCHEMA and inv["read_errors"] == []
    assert [(t["guid"], t["question_id"]) for t in inv["terms"]] == [("t1", "Q-0001"), ("t2", None)]
    assert [l["relationship"] for l in inv["terms"][0]["links"]] == ["ScopedBy", "ReplacementTerm"]
    assert inv["terms"][1]["links"] == []
    called = {c[0].split(".")[0] for m in (gm, me) for c in m.mock_calls if c[0]}
    assert called <= set(qtb.INVENTORY_READ_METHODS)


def test_inventory_records_a_failed_link_read_and_the_plan_refuses_it():
    from pyegeria.omvs.glossary_manager import GlossaryManager
    from pyegeria.omvs.metadata_expert import MetadataExpert

    gm, me = _read_only_fake(GlossaryManager), _read_only_fake(MetadataExpert)
    gm.get_glossaries_by_name.return_value = [{"elementHeader": {"guid": "g"}, "properties": {"displayName": "UQ"}}]
    gm.find_glossary_terms.return_value = [_term_element("t1", "Q?", "g", "Q-0001")]
    me.get_all_related_elements.return_value = None  # pyegeria's dynamic_catch on a failure: not "no links"
    inv = qtb.read_inventory(gm, me, "UQ", now="T")
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
    with pytest.raises(qtb.InventoryReadError, match="none anchored"):
        qtb.read_inventory(gm, me, "UQ")
