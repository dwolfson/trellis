"""A synchronous survey or analysis does NOT wait for its publish (project owner, 2026-10-14).

* `RUNS_PUBLISH_INLINE` defaults to enqueue-only; `RUNS_PUBLISH_INLINE=true` keeps the old wait.
* A run's publish state is one of three words, derived from the run's own outbox rows (the proof rows),
  never from which code branch ran (designer, REPLY-COST-LADDER-AND-PUBLISH-STATE.md §2):
    - "queued for publish": an outbox row of the run exists and is not done (a write, or its read-back);
    - "published · read back": the run's `publish_read_back` row is done — Egeria answered the report's
      annotations by relationship and every annotation the run wrote is among them;
    - "publish failed": a row of the run is dead, with Egeria's words.
  A run whose writes are all done but whose read-back has not succeeded is NOT published.

End to end through `run_analysis` -> `EgeriaPublisher.publish()` -> the real outbox and a real temp-SQLite
registry -> `drain_outbox` as the service account. Only the pyegeria boundary is faked, with
`create_autospec(cls, spec_set=True)` doubles of the real classes (the store in
test_publisher_private_zones_e2e.py), answering the live shapes: `get_new_annotations` answers a list of
`{"elementHeader": {"guid"}, "properties"}` or the string "No elements found" (measured against a real report,
egeria_annotation_materializer.py's docstring). The survey itself (SurveyOrchestrator) is upstream of the write
path and returns a real SurveyResult.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from tests.test_publisher_private_zones_e2e import Denied, Store

SLUG = "r"


class ReadBackStore(Store):
    """The private-zones store (which answers the read-back call, `get_new_annotations`), for a shared resource."""

    def __init__(self):
        super().__init__(private_zone="re-private-zone-not-used")


@pytest.fixture
def world(tmp_path, monkeypatch):
    from resource_explorer.egeria_clients import _client_user
    from tests.zone_fakes import open_access

    monkeypatch.delenv("RUNS_PUBLISH_INLINE", raising=False)
    monkeypatch.delenv("EXPLORER_DRAFT_ZONE", raising=False)
    open_access(monkeypatch)
    store = ReadBackStore()
    monkeypatch.setattr("resource_explorer.egeria_clients.egeria_client",
                        lambda identity, *, purpose, **kw: store.clients_for(_client_user(identity)))
    reg = ProjectRegistry(db_path=str(tmp_path / "reg.db"))
    reg.add(Project(slug=SLUG, display_name="R", github_url="https://github.com/o/r", description=""))
    reg.set_project_context("repo", SLUG, status="linked", egeria_project_guid="proj-1")
    # The default comes from the environment, so a fresh config reads it (no cached RunsConfig from another test).
    from resource_explorer import config as cfg

    monkeypatch.setattr(cfg, "_config", None, raising=False)
    return store, reg


def _result():
    from resource_explorer.surveyors.survey_report import Annotation, AnnotationType, SurveyResult

    result = SurveyResult(resource_slug=SLUG, project_display_name="R", github_url="https://github.com/o/r")
    for i in range(2):
        result.add(Annotation(annotation_type=AnnotationType.CLASSIFICATION, summary=f"finding {i}",
                              analysis_step="repo_language"))
    return result


def _run(reg, monkeypatch, publish=None):
    """One analysis run the way the run queue records it: a running activity row, then the real workflow."""
    from resource_explorer.activity_logger import log_analysis_run
    from resource_explorer.workflows.analysis import execute_and_record_analysis
    from tests.test_publisher_private_zones_e2e import _signed_in

    activity_id = log_analysis_run(reg, "repo", SLUG, "R", "running", "Running…", "fake_analysis")
    monkeypatch.setattr("resource_explorer.workflows.analysis.resolve_analysis_plan",
                        lambda analysis_id, entity_type="repo": (False, ["repo_language"]))
    with patch("resource_explorer.registry.ProjectRegistry", return_value=reg), \
            patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as orch, \
            _signed_in("alice"):
        orch.return_value.run.return_value = _result()
        out = execute_and_record_analysis(SLUG, "fake_analysis", activity_id, registry=reg, publish=publish)
    return out, reg.get_activity(activity_id)


def _drain(reg):
    """The background drain: the service account (Daemon OUTBOX), as the scheduler runs it."""
    from resource_explorer.egeria_clients import Daemon, DaemonReason
    from resource_explorer.egeria_outbox import drain_outbox

    return drain_outbox(reg, identity=Daemon(DaemonReason.OUTBOX))


def _annotations(store):
    return [g for g, e in store.elements.items() if e["kind"] == "Annotation"]


def _screen_text(entry) -> str:
    """Everything a person can read about this run: its summary, its publish word, and its detail's message."""
    detail = json.loads(entry.get("detail") or "{}")
    proof = entry.get("publish_proof") or {}
    return " ".join(str(x) for x in (entry.get("summary"), detail.get("message"), proof.get("word"),
                                     proof.get("words")))


def _says_published(text: str) -> bool:
    """'published' as a claim. 'queued for publish' and 'not published' are not the claim."""
    import re

    return bool(re.search(r"(?<!not )\bpublished\b", text, re.IGNORECASE))


# ── the default ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_default_is_enqueue_only(monkeypatch):
    from resource_explorer.config import RunsConfig

    monkeypatch.delenv("RUNS_PUBLISH_INLINE", raising=False)
    assert RunsConfig(_env_file=None).publish_inline is False


def test_inline_stays_available_behind_the_explicit_setting(monkeypatch):
    from resource_explorer.config import RunsConfig

    monkeypatch.setenv("RUNS_PUBLISH_INLINE", "true")
    assert RunsConfig(_env_file=None).publish_inline is True


# ── end to end: queued, then read back ──────────────────────────────────────────────────────────────────────

def test_a_run_queues_its_publish_and_does_not_publish_inline(world, monkeypatch):
    store, reg = world
    out, entry = _run(reg, monkeypatch)

    assert out.status == "ok"
    assert out.published == "queued" and out.publish_mode == "enqueued"
    assert _annotations(store) == [], "an annotation was written to Egeria before the run returned"
    rows = reg.list_outbox_elements(entity_slug=SLUG)
    assert rows and all(r["status"] == "pending" for r in rows)
    assert any(r["element_kind"] == "publish_read_back" for r in rows), "no read-back is queued for the drain"
    proof = entry["publish_proof"]
    assert proof["state"] == "queued" and proof["word"] == "queued for publish"
    assert not _says_published(_screen_text(entry)), _screen_text(entry)


def test_queued_until_the_read_back_then_published_read_back(world, monkeypatch):
    store, reg = world
    _out, entry = _run(reg, monkeypatch)
    activity_id = entry["id"]

    _drain(reg)

    assert len(_annotations(store)) == 2, "the drain did not write the run's annotations"
    after = reg.get_activity(activity_id)
    proof = after["publish_proof"]
    assert proof["state"] == "read_back", proof
    assert proof["word"] == "published · read back"
    assert proof["at"], "a read-back carries when it was read"
    read_back = [r for r in reg.list_outbox_elements(entity_slug=SLUG) if r["element_kind"] == "publish_read_back"]
    assert [r["status"] for r in read_back] == ["done"]
    assert json.loads(after["detail"])["published"] is True
    # The badge rows are written by the transition, not at enqueue time.
    assert reg.get_last_published_annotation_types(SLUG), "the Published badge rows were not written on read-back"


def test_writes_done_without_a_read_back_are_not_published(world, monkeypatch):
    """Egeria took every write but does not answer one of them under the report: not published, still queued."""
    store, reg = world
    _out, entry = _run(reg, monkeypatch)

    real_new = store._new

    def _new(user, kind, qn, *a, **k):
        guid = real_new(user, kind, qn, *a, **k)
        if kind == "Annotation" and not store.hidden:
            store.hidden.add(guid)
        return guid

    store._new = _new
    _drain(reg)

    writes = [r for r in reg.list_outbox_elements(entity_slug=SLUG) if r["element_kind"] == "annotation"]
    assert writes and all(r["status"] == "done" for r in writes)
    after = reg.get_activity(entry["id"])
    assert after["publish_proof"]["state"] == "queued", after["publish_proof"]
    assert not _says_published(_screen_text(after)), _screen_text(after)
    assert json.loads(after["detail"])["published"] == "queued"
    assert not reg.get_last_published_annotation_types(SLUG)


def test_an_unreadable_read_back_is_not_published(world, monkeypatch):
    store, reg = world
    _out, entry = _run(reg, monkeypatch)
    store.read_back_error = ConnectionError("platform unreachable")
    _drain(reg)
    after = reg.get_activity(entry["id"])
    assert after["publish_proof"]["state"] == "queued"
    assert not _says_published(_screen_text(after))


def test_a_failed_drain_says_publish_failed_with_egerias_words(world, monkeypatch):
    store, reg = world
    _out, entry = _run(reg, monkeypatch)

    def _refuse(user, kind, qn, *a, **k):
        raise Denied("403 OPEN-METADATA-SECURITY-403-001 erinoverview may not create beneath the report")

    store._new = _refuse
    _drain(reg)

    after = reg.get_activity(entry["id"])
    proof = after["publish_proof"]
    assert proof["state"] == "failed" and proof["word"] == "publish failed"
    assert "OPEN-METADATA-SECURITY-403" in proof["words"], proof
    assert not _says_published(proof["word"])
    assert json.loads(after["detail"])["published"] is False


def test_inline_on_request_waits_and_reads_back_before_returning(world, monkeypatch):
    """`RUNS_PUBLISH_INLINE=true` (or the per-run "wait"): the old wait, and the word still comes from the proof."""
    store, reg = world
    monkeypatch.setenv("RUNS_PUBLISH_INLINE", "true")
    from resource_explorer import config as cfg

    monkeypatch.setattr(cfg, "_config", None, raising=False)
    out, entry = _run(reg, monkeypatch)
    assert out.published is True and out.publish_mode == "inline"
    assert len(_annotations(store)) == 2
    assert entry["publish_proof"]["state"] == "read_back"


def test_the_runs_list_reader_carries_the_same_proof(world, monkeypatch):
    """list_activity (the Activity panel and the Runs dialog) and get_activity derive the same word."""
    _store, reg = world
    _out, entry = _run(reg, monkeypatch)
    [listed] = [e for e in reg.list_activity(entity_slug=SLUG, limit=20) if e["id"] == entry["id"]]
    assert listed["publish_proof"] == entry["publish_proof"]


def test_a_run_with_no_outbox_rows_carries_no_publish_word(world):
    """No proof rows, no word: an entry that never published is not "queued", and not "published"."""
    _store, reg = world
    from resource_explorer.activity_logger import log_analysis_run

    aid = log_analysis_run(reg, "repo", SLUG, "R", "ok", "done", "fake_analysis")
    assert reg.get_activity(aid).get("publish_proof") in (None, {})


# ── the engine host still waits ─────────────────────────────────────────────────────────────────────────────

def test_the_engine_host_publisher_takes_no_defer_choice():
    """The engine host completes an engine action with its report GUID, so its publish must finish in its own
    handler. Its publisher takes four positional arguments and no `defer_drain`, which is exactly what makes the
    executor call it synchronously whatever RUNS_PUBLISH_INLINE says (survey_definition_executor: publish_kwargs
    is only filled when the publish function accepts `defer_drain`)."""
    import inspect

    import resource_explorer.engine_host as eh

    src = inspect.getsource(eh._run_and_publish) if hasattr(eh, "_run_and_publish") else inspect.getsource(eh)
    assert "def publisher(entity, step_outputs, surveyed_at, _registry):" in src


def test_the_analysis_row_carries_the_last_runs_publish_word(world, monkeypatch):
    """The Analyses rows (get_analysis_last_run -> stage page / last-activity) show the same proof-derived word."""
    _store, reg = world
    _run(reg, monkeypatch)
    assert reg.get_analysis_last_run("repo", SLUG)["fake_analysis"]["last_publish_proof"]["state"] == "queued"
    _drain(reg)
    assert reg.get_analysis_last_run("repo", SLUG)["fake_analysis"]["last_publish_proof"]["state"] == "read_back"


def test_a_queued_catalog_entry_is_not_a_repo_wide_publish(world, monkeypatch):
    """The publisher's own catalog entry names the run; until the run is read back it is not a publish for the
    Survey Definition cards' repo-wide fallback either."""
    _store, reg = world
    _run(reg, monkeypatch)
    catalog = [e for e in reg.list_activity(entity_slug=SLUG, operation="catalog", limit=5)]
    assert catalog and catalog[0]["publish_proof"]["state"] == "queued"
    assert catalog[0]["summary"].startswith("Queued for publish to Egeria")
