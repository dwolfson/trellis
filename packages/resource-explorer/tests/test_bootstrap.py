"""Tests for the Dr.Egeria bootstrap (resource_explorer/bootstrap.py).

Weighted toward the failure modes actually hit live on 2026-08-19 rather than
the happy path: a present batch must never be re-run (re-running the survey
definitions duplicated 22 step links and took them out of service), an
unreachable Egeria must not look like a reset, and a canary that can never
resolve must not drive an infinite heal loop.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer import bootstrap as bs


def _write_batch(root, name, *, canary=None, files=("a.md",), extra=None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"display_name": name.title(), "files": list(files)}
    if canary is not None:
        manifest["canary"] = canary
    manifest.update(extra or {})
    (d / bs.BATCH_MANIFEST_FILE).write_text(json.dumps(manifest))
    for f in files:
        (d / f).write_text(f"# {f}\n")
    return d


@pytest.fixture(autouse=True)
def _clear_state():
    with bs._status_lock:
        bs._status.clear()
    yield
    with bs._status_lock:
        bs._status.clear()


class TestDiscovery:
    def test_folder_order_drives_execution_order(self, tmp_path):
        for n in ("charlie", "alpha", "bravo"):
            _write_batch(tmp_path, n, canary={"qualified_name": f"Q::{n}"})
        (tmp_path / bs.FOLDER_ORDER_FILE).write_text(json.dumps({"folders": ["charlie", "alpha"]}))
        assert [b.batch_id for b in bs.discover_batches(tmp_path)] == ["charlie", "alpha", "bravo"]

    def test_bare_array_folder_order_also_parses(self, tmp_path):
        """The Portal's _folder_order.json is a bare array; RE's is an object so
        it can carry comments. Both must work so a Portal-style file drops in."""
        for n in ("alpha", "bravo"):
            _write_batch(tmp_path, n, canary={"qualified_name": f"Q::{n}"})
        (tmp_path / bs.FOLDER_ORDER_FILE).write_text(json.dumps(["bravo", "alpha"]))
        assert [b.batch_id for b in bs.discover_batches(tmp_path)] == ["bravo", "alpha"]

    def test_folder_without_manifest_is_not_a_batch(self, tmp_path):
        """Dropping a directory into docs/dr-egeria/ must not silently make it
        execute against Egeria."""
        _write_batch(tmp_path, "real", canary={"qualified_name": "Q::real"})
        (tmp_path / "notabatch").mkdir()
        (tmp_path / "notabatch" / "stray.md").write_text("# stray")
        assert [b.batch_id for b in bs.discover_batches(tmp_path)] == ["real"]

    def test_unlisted_files_run_after_declared_ones(self, tmp_path):
        d = _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"}, files=("second.md", "first.md"))
        (d / "zz_extra.md").write_text("# extra")
        batch = bs.discover_batches(tmp_path)[0]
        assert batch.files == ["second.md", "first.md", "zz_extra.md"]

    def test_declared_file_that_does_not_exist_is_dropped(self, tmp_path):
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"},
                     files=("real.md",), extra={"files": ["ghost.md", "real.md"]})
        (tmp_path / "b" / "real.md").write_text("# real")
        assert bs.discover_batches(tmp_path)[0].files == ["real.md"]

    def test_unreadable_manifest_skips_batch_without_raising(self, tmp_path):
        _write_batch(tmp_path, "good", canary={"qualified_name": "Q::good"})
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / bs.BATCH_MANIFEST_FILE).write_text("{not json")
        assert [b.batch_id for b in bs.discover_batches(tmp_path)] == ["good"]


class _FakeClient:
    """Mimics ClassificationExplorer.get_guid_for_name, including pyegeria's
    habit of returning a human sentence rather than None when nothing matches."""

    def __init__(self, present=(), raises=False):
        self._present = set(present)
        self._raises = raises
        self.calls = []

    def get_guid_for_name(self, name, **kw):
        self.calls.append((name, kw))
        if self._raises:
            raise RuntimeError("egeria unreachable")
        if name in self._present:
            return "6a3014a3-de4d-4909-8dd0-511dae0e08b2"
        return "No elements found"


class TestCanary:
    def test_present_canary_detected(self, tmp_path):
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        batch = bs.discover_batches(tmp_path)[0]
        assert bs.canary_present(batch, _FakeClient(present=["Q::b"])) is True

    def test_missing_canary_detected(self, tmp_path):
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        batch = bs.discover_batches(tmp_path)[0]
        assert bs.canary_present(batch, _FakeClient()) is False

    def test_sentinel_string_is_not_mistaken_for_a_guid(self, tmp_path):
        """pyegeria returns "No elements found" — truthy. If that were taken as
        a GUID the batch would read as present and never heal."""
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        batch = bs.discover_batches(tmp_path)[0]
        assert bs.canary_present(batch, _FakeClient(present=[])) is False

    def test_lookup_error_fails_open(self, tmp_path):
        """An unreachable Egeria is not evidence of a reset. Healing on that
        basis would re-run every batch against a server that is merely down."""
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        batch = bs.discover_batches(tmp_path)[0]
        assert bs.canary_present(batch, _FakeClient(raises=True)) is True

    def test_no_canary_means_never_auto_healed(self, tmp_path):
        _write_batch(tmp_path, "b", canary=None)
        batch = bs.discover_batches(tmp_path)[0]
        assert batch.has_canary is False
        assert bs.canary_present(batch, _FakeClient()) is True

    def test_type_is_omitted_from_lookup_when_not_declared(self, tmp_path):
        """A wrong type_name silently returns nothing, which reads as 'missing'
        and triggers a heal — so type must not be invented when absent."""
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        client = _FakeClient(present=["Q::b"])
        bs.canary_present(bs.discover_batches(tmp_path)[0], client)
        assert "type_name" not in client.calls[0][1]

    def test_declared_type_is_passed_through(self, tmp_path):
        _write_batch(tmp_path, "b", canary={"type": "Perspective", "qualified_name": "Q::b"})
        client = _FakeClient(present=["Q::b"])
        bs.canary_present(bs.discover_batches(tmp_path)[0], client)
        assert client.calls[0][1]["type_name"] == "Perspective"

    def test_display_name_canary_uses_display_name_property(self, tmp_path):
        """Glossary-term qualified names are generated with a deployment-specific
        org prefix and version, so those batches key on display name instead."""
        _write_batch(tmp_path, "b", canary={"display_name": "Some Question?"})
        client = _FakeClient(present=["Some Question?"])
        assert bs.canary_present(bs.discover_batches(tmp_path)[0], client) is True
        assert client.calls[0][1]["property_name"] == ["displayName"]


class TestCheckAndHeal:
    def test_present_batch_is_never_re_run(self, tmp_path, monkeypatch):
        """THE critical guarantee. Re-running an already-present survey-definition
        batch duplicates every step link and takes it out of service."""
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        monkeypatch.setattr(bs, "canary_present", lambda b, client=None: True)
        called = []
        monkeypatch.setattr(bs, "heal_batch", lambda b: called.append(b) or (True, "ok"))

        res = bs.check_and_heal(tmp_path)
        assert called == []
        assert res["batches"]["b"]["action"] == "ok"

    def test_missing_batch_is_healed(self, tmp_path, monkeypatch):
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        monkeypatch.setattr(bs, "canary_present", lambda b, client=None: False)
        called = []
        monkeypatch.setattr(bs, "heal_batch", lambda b: called.append(b.batch_id) or (True, "ok"))

        res = bs.check_and_heal(tmp_path)
        assert called == ["b"]
        assert res["batches"]["b"]["action"] == "healed"

    def test_heals_in_declared_order(self, tmp_path, monkeypatch):
        """Order is load-bearing: a survey definition processed before the
        Question terms exist silently creates no ScopedBy links."""
        for n in ("foundations", "questions", "survey-definitions"):
            _write_batch(tmp_path, n, canary={"qualified_name": f"Q::{n}"})
        (tmp_path / bs.FOLDER_ORDER_FILE).write_text(
            json.dumps({"folders": ["foundations", "questions", "survey-definitions"]}))
        monkeypatch.setattr(bs, "canary_present", lambda b, client=None: False)
        order = []
        monkeypatch.setattr(bs, "heal_batch", lambda b: order.append(b.batch_id) or (True, "ok"))

        bs.check_and_heal(tmp_path)
        assert order == ["foundations", "questions", "survey-definitions"]

    def test_repeated_failures_stop_retrying(self, tmp_path, monkeypatch):
        """A canary that can never resolve would otherwise re-heal forever. Two
        real Question terms behave exactly this way, so the guard is not
        hypothetical."""
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::never"})
        monkeypatch.setattr(bs, "canary_present", lambda b, client=None: False)
        attempts = []
        monkeypatch.setattr(bs, "heal_batch", lambda b: attempts.append(1) or (False, "boom"))

        for _ in range(bs.MAX_CONSECUTIVE_FAILURES + 3):
            bs.check_and_heal(tmp_path)
        assert len(attempts) == bs.MAX_CONSECUTIVE_FAILURES

    def test_force_reruns_even_when_present(self, tmp_path, monkeypatch):
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"})
        monkeypatch.setattr(bs, "canary_present", lambda b, client=None: True)
        called = []
        monkeypatch.setattr(bs, "heal_batch", lambda b: called.append(b.batch_id) or (True, "ok"))

        bs.check_and_heal(tmp_path, force=True)
        assert called == ["b"]


class TestHealBatch:
    def test_stops_at_first_failing_document(self, tmp_path, monkeypatch):
        """Within a batch, file order encodes dependency order — continuing past
        a failure runs commands whose prerequisites are missing."""
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"}, files=("one.md", "two.md", "three.md"))
        batch = bs.discover_batches(tmp_path)[0]
        seen = []

        def fake(doc):
            seen.append(doc.name)
            return (False, "bad") if doc.name == "two.md" else (True, "ok")

        monkeypatch.setattr(bs, "_run_dr_egeria", fake)
        ok, detail = bs.heal_batch(batch)
        assert ok is False
        assert seen == ["one.md", "two.md"]
        assert "two.md" in detail

    def test_post_heal_runs_after_documents(self, tmp_path, monkeypatch):
        """Survey definitions need the reconciler after a heal: a legitimate
        heal still duplicates step links."""
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"},
                     extra={"post_heal": {"script": "scripts/reconcile.py"}})
        batch = bs.discover_batches(tmp_path)[0]
        monkeypatch.setattr(bs, "_run_dr_egeria", lambda doc: (True, "ok"))
        ran = []
        monkeypatch.setattr(bs, "_run_post_heal", lambda b: ran.append(b.batch_id) or (True, "post_heal ok"))
        ok, _ = bs.heal_batch(batch)
        assert ok is True and ran == ["b"]

    def test_post_heal_failure_fails_the_batch(self, tmp_path, monkeypatch):
        _write_batch(tmp_path, "b", canary={"qualified_name": "Q::b"},
                     extra={"post_heal": {"script": "scripts/reconcile.py"}})
        batch = bs.discover_batches(tmp_path)[0]
        monkeypatch.setattr(bs, "_run_dr_egeria", lambda doc: (True, "ok"))
        monkeypatch.setattr(bs, "_run_post_heal", lambda b: (False, "reconciler exploded"))
        ok, detail = bs.heal_batch(batch)
        assert ok is False and "reconciler" in detail


class TestRealManifests:
    """The shipped docs/dr-egeria manifests must stay parseable and coherent —
    a broken manifest here disables healing silently."""

    def test_real_manifests_discover_in_dependency_order(self):
        batches = bs.discover_batches(bs.DOCS_DIR)
        ids = [b.batch_id for b in batches]
        assert ids[:3] == ["foundations", "questions", "survey-definitions"]

    def test_every_real_batch_has_a_usable_canary_and_files(self):
        for b in bs.discover_batches(bs.DOCS_DIR):
            assert b.has_canary, f"{b.batch_id} has no canary — would never self-heal"
            assert b.files, f"{b.batch_id} has no documents"

    def test_survey_definitions_declares_non_idempotent_and_post_heal(self):
        sd = {b.batch_id: b for b in bs.discover_batches(bs.DOCS_DIR)}["survey-definitions"]
        assert sd.idempotent is False
        assert (sd.post_heal or {}).get("script")
