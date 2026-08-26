"""The sweep must agree with the publisher about whether an asset exists.

Measured 2026-08-26 against a live, healthy catalog: get_asset_by_guid raised
PyegeriaNotFoundException/400 for GUIDs that plainly existed, so the sweep
declared ALL 23 cached GUIDs stale while find_asset_guid returned those exact
GUIDs for the same repos. `--apply` on that verdict would have cleared every
valid registration in the catalog, along with its survey records and -- once
publish claims were added to the clearing -- its publish history too.

A destructive script whose "is it there?" test disagrees with the one the
publisher uses is worse than having no script.
"""
from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sweep_stale_egeria_guids.py"
PUBLISHER = (Path(__file__).resolve().parents[1] / "resource_explorer" / "surveyors"
             / "egeria_publisher.py")


def test_the_sweep_verifies_the_way_the_publisher_verifies():
    src = SCRIPT.read_text()
    assert "find_software_capabilities" in src, \
        "the sweep no longer uses the publisher's verification"
    assert "find_software_capabilities" in PUBLISHER.read_text()


def test_the_sweep_does_not_decide_staleness_by_asset_guid_lookup():
    """The specific call that produced 23 false positives."""
    # The CALL, not the word -- the comment explaining why it is wrong should
    # survive, and a test that forbids the explanation invites its deletion.
    src = SCRIPT.read_text()
    calls = [ln for ln in src.splitlines()
             if ".get_asset_by_guid(" in ln and not ln.lstrip().startswith("#")]
    assert calls == [], f"staleness still decided by asset-GUID lookup: {calls}"


def test_an_error_is_never_treated_as_stale():
    """"Unreachable" and "not there" must stay distinct, or a network blip
    clears the whole catalog."""
    src = SCRIPT.read_text()
    assert "unknown.append" in src
    # The unknown bucket is reported, and never cleared.
    assert "Projects that could not be determined are never cleared." in src


def test_all_three_kinds_of_cached_guid_are_swept():
    """Asset GUIDs came first; an investigation's Egeria Project and each
    disposition WorkingSet's Collection were added later and were left dangling
    by every sweep before this one."""
    src = SCRIPT.read_text()
    assert "egeria_project_guid" in src
    assert "egeria_collection_guid" in src
    # And they are checked even when no asset GUID is stale -- an early return
    # is why they went unchecked.
    assert src.count("_sweep_investigations(registry, maker") >= 3


def test_clearing_a_registration_also_drops_its_publish_claims():
    """project_published_annotation_types is what the Analyses cards' Published
    badge is derived from. Leaving it would put a Published badge on a repo
    whose catalog entry is gone -- the exact thing the sweep exists to end."""
    registry = (Path(__file__).resolve().parents[1] / "resource_explorer" / "registry.py").read_text()
    fn = registry.split("def clear_egeria_registration(")[1].split("\n    def ")[0]
    assert "project_published_annotation_types" in fn
    assert "published_types_deleted" in fn
