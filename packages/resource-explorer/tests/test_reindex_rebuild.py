"""R1b of BRIEF-REINDEX-FROM-SCRATCH.md: rebuilding a repository's chat index aside, then swapping, recoverably.

Real SQLite registry; the vector store, analyzer, pipeline and GitHub client are fakes bound to the methods the rebuild
calls. Real Postgres behaviour of the swap itself is R1a's (tests/test_collection_swap_pg.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from resource_explorer import reindex
from resource_explorer.registry import Project, ProjectRegistry, ProjectStatus
from resource_explorer.vector_store_pg import chunk_ids

SLUG = "rr"


class FakeStore:
    """Collections as {name: [(id, text, metadata)]}, with an index flag; swap/insert semantics like the real ones."""

    def __init__(self):
        self.tables: dict[str, list] = {}
        self.indexed: set[str] = set()
        self.fail_swap = False

    def check_names(self, *names):
        return [n for n in names if len(n.encode()) > 63]

    def collection_exists(self, n):
        return n in self.tables

    def drop_collection(self, n):
        self.tables.pop(n, None)
        self.indexed.discard(n)

    def count(self, n):
        return len(self.tables.get(n, []))

    def has_vector_index(self, n):
        return n in self.indexed

    def insert(self, n, texts, metas, *, id_collection=None):
        ids = chunk_ids(id_collection or n, texts, metas)
        self.tables.setdefault(n, []).extend(zip(ids, texts, metas))
        self.indexed.add(n)
        return len(texts)

    def swap_collections(self, renames, **kw):
        if self.fail_swap:
            raise RuntimeError("lock not available")
        for old, new in renames:
            assert old in self.tables and new not in self.tables, (old, new)
            self.tables[new] = self.tables.pop(old)
            if old in self.indexed:
                self.indexed.discard(old)
                self.indexed.add(new)

    def table_bytes(self, n):
        return 1_048_576 * len(self.tables.get(n, []))

    def rows_by_ids(self, n, ids):
        return [{"id": i, "text": t, "metadata": m} for i, t, m in self.tables.get(n, []) if i in ids]

    def all_rows(self, n):
        return [{"id": i, "text": t, "metadata": m} for i, t, m in self.tables.get(n, [])]


@dataclass
class FakePipeline:
    store: FakeStore
    content: dict  # type name -> [(file, text)]
    survey_calls: list = field(default_factory=list)

    _DOC_CTYPES = frozenset({"markdown_docs"})
    extra_seen: list = field(default_factory=list)

    def _ingest_collection(self, repo, slug, name, ct, root, *, id_collection=None, extra_paths=None):
        if extra_paths:
            self.extra_seen.append((ct.name, [p for p, _ in extra_paths]))
        rows = self.content.get(ct.name, [])
        if not rows:
            return 0
        return self.store.insert(name, [t for _, t in rows], [{"file_path": f} for f, _ in rows],
                                 id_collection=id_collection)

    def _count_repo_stats(self, root):
        return 3, 30

    def __getattr__(self, name):
        if name in reindex.SURVEY_WRITERS:
            return lambda *a, **kw: self.survey_calls.append(name)
        raise AttributeError(name)


class FakeCache:
    def __init__(self):
        self.invalidated = 0

    def invalidate_project(self, slug):
        self.invalidated += 1


def ct(name):
    return SimpleNamespace(name=name)


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "reg.db"))
    reg.add(Project(slug=SLUG, display_name="RR", github_url="https://github.com/x/rr",
                    collections=[f"{SLUG}_markdown_docs", f"{SLUG}_java_code", "web_docs_site"]))
    return reg


@pytest.fixture
def store():
    s = FakeStore()
    s.insert(f"{SLUG}_markdown_docs", ["intro", "usage"], [{"file_path": "README.md"}] * 2)
    s.insert(f"{SLUG}_java_code", ["class A"], [{"file_path": "A.java"}])
    s.insert("web_docs_site", ["shared page"], [{"file_path": "https://x"}])
    return s


def deps(registry, store, *, proposed=("markdown_docs", "python_code"), content=None):
    content = content or {"markdown_docs": [("README.md", "new intro"), ("README.md", "intro"),
                                            ("README.md", "usage")],
                          "python_code": [("a.py", "def f(): pass")]}
    client = SimpleNamespace(get_repo=lambda url: SimpleNamespace(), get_latest_commit_sha=lambda repo: "sha1",
                             download_zipball=lambda repo, d, sub=None, ref=None: d)
    return reindex.Deps(registry=registry, store=store, analyzer=SimpleNamespace(
        analyze=lambda url, subpath=None: SimpleNamespace(proposed_collections=[ct(n) for n in proposed])),
        pipeline=FakePipeline(store, content), client=client, query_cache=FakeCache())


def queued(registry, *, held=False):
    out = reindex.queue(registry, SLUG, requested_by="erinoverview", store=FakeStore())
    if not held:
        registry.merge_run_target(out["run_id"], {"held": False})
    return out["run_id"]


def execute(registry, run_id, d):
    """What the run queue does: run the handler, then finish the row with its state."""
    state, error = reindex.run(run_id, d)
    registry.finish_run(run_id, state, error=error)
    return state, error


def target(registry, run_id):
    return registry.merge_run_target(run_id, {})


class TestQueue:
    def test_a_rebuild_needs_a_requester_and_an_index(self, registry):
        with pytest.raises(reindex.ReindexRefused) as e:
            reindex.queue(registry, SLUG, requested_by="", store=FakeStore())
        assert e.value.status == 401
        registry.set_project_collections(SLUG, ["web_docs_site"])
        with pytest.raises(reindex.ReindexRefused, match="first index"):
            reindex.queue(registry, SLUG, requested_by="erin", store=FakeStore())

    def test_one_at_a_time_and_never_twice_for_a_repository(self, registry):
        queued(registry)
        with pytest.raises(reindex.ReindexRefused, match="already has a rebuild"):
            reindex.queue(registry, SLUG, requested_by="erin", store=FakeStore())

    def test_the_first_rebuild_ever_is_held(self, registry):
        out = reindex.queue(registry, SLUG, requested_by="erin", store=FakeStore())
        assert out["held"] is True


class TestRebuild:
    def test_build_aside_check_survey_swap_and_keep_the_previous(self, registry, store):
        d = deps(registry, store)
        run_id = queued(registry)
        assert execute(registry, run_id, d) == ("succeeded", "")
        t = target(registry, run_id)
        assert [o["phase"] for o in t["outcomes"]] == ["building", "built", "surveyed", "list_pruned", "swapped",
                                                       "list_extended", "done"]
        # Re-planned (Q1): java_code dropped, python_code added, markdown_docs rebuilt.
        assert store.count(f"{SLUG}_markdown_docs") == 3 and store.count(f"{SLUG}_python_code") == 1
        assert store.count(f"{SLUG}_markdown_docs__previous") == 2
        assert store.count(f"{SLUG}_java_code__previous") == 1 and not store.collection_exists(f"{SLUG}_java_code")
        assert not any(n.endswith("__rebuild") for n in store.tables)
        assert sorted(registry.get(SLUG).collections) == sorted(
            [f"{SLUG}_markdown_docs", f"{SLUG}_python_code", "web_docs_site"])
        assert t["previous_until"] and "undo available until" in t["outcomes"][-1]["words"]
        assert d.pipeline.survey_calls == list(reindex.SURVEY_WRITERS)
        assert "not reverted by undo" in t["outcomes"][2]["words"]
        assert d.query_cache.invalidated >= 3                        # after each list change, and at the end

    def test_ids_are_minted_under_the_live_name_so_unchanged_chunks_keep_theirs(self, registry, store):
        before = {i for i, _, _ in store.tables[f"{SLUG}_markdown_docs"]}
        content = {"markdown_docs": [("README.md", "intro"), ("README.md", "usage")]}
        reindex.run(queued(registry), deps(registry, store, proposed=("markdown_docs",), content=content))
        assert {i for i, _, _ in store.tables[f"{SLUG}_markdown_docs"]} == before

    def test_no_project_status_is_written(self, registry, store):
        registry.update_status(SLUG, ProjectStatus.ACTIVE)
        d = deps(registry, store)
        d.pipeline.content = {}                                       # every type comes back empty: refused
        execute(registry, queued(registry), d)
        assert registry.get(SLUG).status == ProjectStatus.ACTIVE

    def test_a_type_that_had_chunks_and_now_has_none_is_refused_and_nothing_live_changes(self, registry, store):
        live_before = {k: list(v) for k, v in store.tables.items()}
        d = deps(registry, store, content={"markdown_docs": [], "python_code": [("a.py", "x")]})
        state, error = execute(registry, queued(registry), d)
        assert state == "failed" and "had 2 chunk(s) and now has none" in error
        assert store.tables == live_before and d.pipeline.survey_calls == []

    def test_the_held_first_rebuild_waits_for_accept_then_a_continuation_swaps(self, registry, store):
        run_id = queued(registry, held=True)
        d = deps(registry, store)
        assert execute(registry, run_id, d) == ("succeeded", "")
        assert target(registry, run_id)["phase"] == "awaiting_accept"
        assert store.count(f"{SLUG}_markdown_docs") == 2              # nothing swapped yet
        assert reindex.is_rebuilding(registry, SLUG)
        cont = reindex.accept(registry, run_id, requested_by="erin")["run_id"]
        assert execute(registry, cont, d) == ("succeeded", "")
        assert target(registry, cont)["phase"] == "done" and store.count(f"{SLUG}_markdown_docs") == 3
        with pytest.raises(reindex.ReindexRefused):
            reindex.accept(registry, run_id, requested_by="erin")


class TestRecovery:
    """The architect's recoverability rule: never "pruned but the swap failed", never "swapped but not extended"."""

    def test_a_swap_that_fails_after_the_prune_rolls_the_list_back(self, registry, store):
        store.fail_swap = True
        live_before = {k: list(v) for k, v in store.tables.items()}
        list_before = list(registry.get(SLUG).collections)
        state, _ = execute(registry, queued(registry), deps(registry, store))
        assert state == "failed"
        assert sorted(registry.get(SLUG).collections) == sorted(list_before)
        assert store.tables == live_before                         # the aside tables were dropped

    def test_a_run_that_died_after_the_swap_is_finished_forward(self, registry, store, monkeypatch):
        d = deps(registry, store)
        run_id = queued(registry)
        real = registry.set_project_collections
        calls = {"n": 0}

        def die_on_extend(slug, cols):
            calls["n"] += 1
            if calls["n"] == 2:                                      # the extend, after the swap
                raise SystemExit("process killed")
            real(slug, cols)
        monkeypatch.setattr(registry, "set_project_collections", die_on_extend)
        with pytest.raises(SystemExit):
            execute(registry, run_id, d)
        monkeypatch.setattr(registry, "set_project_collections", real)
        assert target(registry, run_id)["phase"] == "extending"           # the intent was recorded first
        assert f"{SLUG}_python_code" not in registry.get(SLUG).collections   # the half-done state
        assert reindex.recover(registry, registry.get_run(run_id), d) == "finished forward"
        assert f"{SLUG}_python_code" in registry.get(SLUG).collections
        assert target(registry, run_id)["phase"] == "done"

    def test_a_run_that_died_while_building_is_rolled_back(self, registry, store):
        run_id = queued(registry)
        store.insert(f"{SLUG}_markdown_docs__rebuild", ["half"], [{"file_path": "x"}])
        registry.merge_run_target(run_id, {"phase": "building"})
        assert reindex.recover(registry, registry.get_run(run_id), deps(registry, store)) == "rolled back"
        assert not store.collection_exists(f"{SLUG}_markdown_docs__rebuild")

    def test_the_reconciler_recovers_a_dead_rebuild(self, registry, store, monkeypatch):
        from resource_explorer import run_reconciler

        run_id = queued(registry)
        registry.merge_run_target(run_id, {"phase": "building"})
        seen = {}
        monkeypatch.setattr(reindex, "recover", lambda reg, row, deps=None: seen.setdefault("id", row["id"]) or "x")
        monkeypatch.setattr(registry, "list_runs", lambda state=None, kind=None, limit=1000: (
            [{**registry.get_run(run_id), "runner": {"pid": 1}}] if state == "running" else []))
        monkeypatch.setattr(run_reconciler, "_is_alive", lambda owner: False)
        monkeypatch.setattr(registry, "finish_run", lambda *a, **kw: None)
        run_reconciler.reconcile_runs(registry, ignore_heartbeat=True)
        assert seen["id"] == run_id


class TestVotesAndUndo:
    def _vote(self, ref):
        from resource_explorer.vector_store_pg import _metrics_collector
        m = _metrics_collector()
        with m._conn() as conn:
            conn.execute("INSERT INTO chunk_feedback (chunk_ref, positive_count, neutral_count, total_count, "
                         "last_updated) VALUES (?, 1, 0, 1, 'now')", (ref,))
        return m

    def test_a_moved_chunk_keeps_its_vote_and_undo_moves_it_back(self, registry, store):
        col = f"{SLUG}_markdown_docs"
        usage_id = next(i for i, t, _ in store.tables[col] if t == "usage")
        m = self._vote(f"{col}:{usage_id}")
        d = deps(registry, store)
        run_id = queued(registry)
        execute(registry, run_id, d)
        new_id = next(i for i, t, _ in store.tables[col] if t == "usage")
        assert new_id != usage_id                                   # "new intro" was added before it: it moved
        assert m.chunk_vote_refs(col) == [f"{col}:{new_id}"]
        out = reindex.undo(registry, SLUG, requested_by="erin", deps=d)
        assert out["votes_moved_back"] == 1 and m.chunk_vote_refs(col) == [f"{col}:{usage_id}"]

    def test_undo_restores_the_previous_index_and_removes_an_added_type(self, registry, store):
        d = deps(registry, store)
        execute(registry, queued(registry), d)
        reindex.undo(registry, SLUG, requested_by="erin", deps=d)
        assert store.count(f"{SLUG}_markdown_docs") == 2 and store.count(f"{SLUG}_java_code") == 1
        assert not store.collection_exists(f"{SLUG}_python_code")    # the type the rebuild added
        assert sorted(registry.get(SLUG).collections) == sorted(
            [f"{SLUG}_markdown_docs", f"{SLUG}_java_code", "web_docs_site"])
        with pytest.raises(reindex.ReindexRefused):
            reindex.undo(registry, SLUG, requested_by="erin", deps=d)

    def test_a_kept_previous_index_blocks_the_next_rebuild_until_undone(self, registry, store):
        execute(registry, queued(registry), deps(registry, store))
        with pytest.raises(reindex.ReindexRefused, match="kept until"):
            reindex.queue(registry, SLUG, requested_by="erin", store=FakeStore())


class TestOthersWaitForARebuild:
    def test_refresh_returns_rebuilding(self, registry):
        from resource_explorer.ingestion.incremental import IncrementalIndexer, RefreshResult

        queued(registry)
        indexer = IncrementalIndexer.__new__(IncrementalIndexer)
        indexer.registry = registry
        assert indexer.refresh(registry.get(SLUG)) is RefreshResult.REBUILDING

    def test_a_first_index_is_refused(self, registry):
        from resource_explorer import first_index

        queued(registry)
        registry.set_project_collections(SLUG, ["web_docs_site"])
        with pytest.raises(first_index.FirstIndexRefused, match="rebuild in progress"):
            first_index.queue(registry, SLUG, requested_by="erin")

    def test_the_scheduler_leaves_the_repository_s_schedules_due(self, registry):
        from resource_explorer.scheduler import _defer_while_rebuilding

        queued(registry)
        due = [{"entity_type": "repo", "entity_slug": SLUG, "analysis_id": "a"},
               {"entity_type": "repo", "entity_slug": "other", "analysis_id": "b"}]
        assert [s["entity_slug"] for s in _defer_while_rebuilding(due, registry)] == ["other"]


class TestRoutes:
    def test_the_routes_are_admin_only(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from resource_explorer.web.app import app

        monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite:///{tmp_path}/r.db")
        import resource_explorer.config as cfg
        cfg._config = None
        client = TestClient(app)
        assert client.post("/api/reindex/queue", json={"slug": SLUG}).status_code in (401, 403)
        assert client.get(f"/api/reindex/progress?slug={SLUG}").status_code in (401, 403)
        assert client.post(f"/api/reindex/{SLUG}/undo").status_code in (401, 403)


class TestActivity:
    """Design rule 16: every operation writes an activity entry."""

    def test_a_rebuild_and_an_undo_each_write_one(self, registry, store):
        run_id = queued(registry)
        assert registry.get_run(run_id)["result_ref"]
        execute(registry, run_id, deps(registry, store))
        reindex.undo(registry, SLUG, requested_by="erin", deps=deps(registry, store))
        rows = [a for a in registry.list_activity(entity_slug=SLUG, limit=50) if a.get("operation") == "reindex"]
        assert len(rows) == 2 and any("undone by erin" in a["summary"] for a in rows)


def test_extra_docs_paths_of_a_subproject_are_rebuilt_too(registry, store, tmp_path):
    with registry._conn() as conn:
        conn.execute("UPDATE projects SET subproject_path = ?, extra_docs_paths = ? WHERE slug = ?",
                     ("sub", '["docs/guide.md"]', SLUG))
    d = deps(registry, store)
    execute(registry, queued(registry), d)
    assert d.pipeline.extra_seen == [("markdown_docs", ["docs/guide.md"])]


class TestRecoveryReadsTheTables:
    """The architect's B1-B3 on a6ef63b1: intent before effect, and recovery decides from the tables."""

    def _kill_after(self, monkeypatch, obj, name):
        real = getattr(obj, name)

        def wrapped(*a, **kw):
            real(*a, **kw)
            raise SystemExit(f"killed after {name}")
        monkeypatch.setattr(obj, name, wrapped)
        return real

    def test_killed_after_the_prune_took_effect_but_before_it_was_recorded(self, registry, store, monkeypatch):
        list_before = sorted(registry.get(SLUG).collections)
        d = deps(registry, store)
        run_id = queued(registry)
        real = self._kill_after(monkeypatch, registry, "set_project_collections")
        with pytest.raises(SystemExit):
            reindex.run(run_id, d)
        monkeypatch.setattr(registry, "set_project_collections", real)
        assert target(registry, run_id)["phase"] == "pruning"
        assert f"{SLUG}_java_code" not in registry.get(SLUG).collections          # the prune happened
        assert reindex.recover(registry, registry.get_run(run_id), d) == "rolled back"
        assert sorted(registry.get(SLUG).collections) == list_before
        assert not any(n.endswith("__rebuild") for n in store.tables)

    def test_killed_after_the_swap_committed_but_before_it_was_recorded(self, registry, store, monkeypatch):
        d = deps(registry, store)
        run_id = queued(registry)
        real = self._kill_after(monkeypatch, store, "swap_collections")
        with pytest.raises(SystemExit):
            reindex.run(run_id, d)
        monkeypatch.setattr(store, "swap_collections", real)
        assert target(registry, run_id)["phase"] == "swapping"
        assert reindex.recover(registry, registry.get_run(run_id), d) == "finished forward"
        t = target(registry, run_id)
        assert t["phase"] == "done" and t["previous_until"]
        assert f"{SLUG}_python_code" in registry.get(SLUG).collections
        registry.finish_run(run_id, "failed", error="killed")
        assert reindex.undo(registry, SLUG, requested_by="erin", deps=d)       # undo is available

    def test_a_swap_that_commits_and_then_raises_is_finished_forward(self, registry, store, monkeypatch):
        real = store.swap_collections

        def commit_then_raise(renames, **kw):
            real(renames, **kw)
            raise RuntimeError("connection lost after commit")
        monkeypatch.setattr(store, "swap_collections", commit_then_raise)
        assert execute(registry, queued(registry), deps(registry, store)) == ("succeeded", "")
        assert store.count(f"{SLUG}_markdown_docs") == 3

    def test_votes_are_recorded_per_collection_and_forward_recovery_carries_only_the_rest(self, registry, store,
                                                                                          monkeypatch):
        from resource_explorer.vector_store_pg import _metrics_collector
        col = f"{SLUG}_markdown_docs"
        usage_id = next(i for i, t, _ in store.tables[col] if t == "usage")
        m = _metrics_collector()
        with m._conn() as conn:
            conn.execute("INSERT INTO chunk_feedback (chunk_ref, positive_count, neutral_count, total_count, "
                         "last_updated) VALUES (?, 1, 0, 1, 'now')", (f"{col}:{usage_id}",))
        d = deps(registry, store)
        run_id = queued(registry)
        real = self._kill_after(monkeypatch, store, "swap_collections")
        with pytest.raises(SystemExit):
            reindex.run(run_id, d)
        monkeypatch.setattr(store, "swap_collections", real)
        reindex.recover(registry, registry.get_run(run_id), d)               # carries from the __previous table
        new_id = next(i for i, t, _ in store.tables[col] if t == "usage")
        assert m.chunk_vote_refs(col) == [f"{col}:{new_id}"]
        assert target(registry, run_id)["vote_moves"] == {f"{col}:{usage_id}": f"{col}:{new_id}"}


class TestUndoIsRecoverable:
    def _rebuilt(self, registry, store):
        d = deps(registry, store)
        execute(registry, queued(registry), d)
        return d

    def test_an_undo_killed_after_its_swap_committed_is_finished(self, registry, store, monkeypatch):
        d = self._rebuilt(registry, store)
        real = store.swap_collections

        def die_after(renames, **kw):
            real(renames, **kw)
            raise SystemExit("killed")
        monkeypatch.setattr(store, "swap_collections", die_after)
        with pytest.raises(SystemExit):
            reindex.undo(registry, SLUG, requested_by="erin", deps=d)
        monkeypatch.setattr(store, "swap_collections", real)
        out = reindex.recover_undos(registry, deps=d)
        assert out and "undo finished forward" in out[0]
        assert store.count(f"{SLUG}_java_code") == 1 and not store.collection_exists(f"{SLUG}_python_code")
        assert sorted(registry.get(SLUG).collections) == sorted(
            [f"{SLUG}_markdown_docs", f"{SLUG}_java_code", "web_docs_site"])

    def test_an_undo_killed_before_its_swap_is_reversed_and_undo_stays_available(self, registry, store):
        d = self._rebuilt(registry, store)
        store.fail_swap = True
        with pytest.raises(RuntimeError):
            reindex.undo(registry, SLUG, requested_by="erin", deps=d)
        store.fail_swap = False
        out = reindex.recover_undos(registry, deps=d)
        assert out and "undo reversed" in out[0]
        assert f"{SLUG}_python_code" in registry.get(SLUG).collections        # the rebuilt index is still live
        assert reindex.undo(registry, SLUG, requested_by="erin", deps=d)

    def test_a_live_undo_s_claim_keeps_recovery_away(self, registry, store):
        d = self._rebuilt(registry, store)
        row = reindex.latest_done(registry, SLUG)
        registry.merge_run_target(row["id"], {"phase": "undo_swapping"})
        registry.take_claim(reindex._claim_key(SLUG), "a live undo")
        assert reindex.recover_undos(registry, deps=d) == []


class TestTheRestOfTheReadBack:
    def test_a_second_rebuild_is_refused_when_claimed(self, registry, store, monkeypatch):
        run_id = queued(registry)
        real = registry.list_runs
        monkeypatch.setattr(registry, "list_runs", lambda state=None, kind=None, limit=50: (
            [{"id": "other", "target": {"slug": "elsewhere"}}] if state == "running"
            else real(state=state, kind=kind, limit=limit)))
        state, error = reindex.run(run_id, deps(registry, store))
        assert state == "failed" and "one at a time" in error

    def test_disk_full_is_named_and_the_aside_tables_dropped(self, registry, store, monkeypatch):
        class DiskFull(Exception):
            pgcode = "53100"
        d = deps(registry, store)

        def fill(*a, **kw):
            store.insert(f"{SLUG}_markdown_docs__rebuild", ["half"], [{"file_path": "x"}])
            raise DiskFull("could not extend file")
        monkeypatch.setattr(d.pipeline, "_ingest_collection", fill)
        state, error = reindex.run(queued(registry), d)
        assert state == "failed" and "ran out of disk" in error
        assert not store.collection_exists(f"{SLUG}_markdown_docs__rebuild")

    def test_the_ask_states_the_measured_space_a_rebuild_needs(self, registry, store):
        out = reindex.queue(registry, SLUG, requested_by="erin", store=store)
        assert out["needs_bytes"] == 3 * 1_048_576                           # the repo's own tables, not web_docs
        assert "needs about 3 MB more" in out["needs_words"]
