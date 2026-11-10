"""Rebuild a repository's chat index from scratch, alongside the live one, then swap (BRIEF-REINDEX-FROM-SCRATCH.md, R1b).

The rules, all decided by the project owner or required by the architect's read-backs (2026-11-10):

* **Asked first, admins only, one at a time.** A run-queue row of kind `reindex` with the requester recorded. Refused
  while the repository has a first index or rebuild queued or running, while any other rebuild runs, or while an
  earlier rebuild's previous index is still kept (its names would collide).
* **Build aside.** Each collection type the analyzer proposes TODAY (Q1, re-plan) is ingested into
  `{slug}_{type}__rebuild`, with chunk ids minted under the live name (`vector_store_pg.insert(id_collection=)`), from
  one download at a recorded commit. Chat keeps reading the live index.
* **Check.** Old and new counts per type; a type that had chunks and is still proposed but now has none is refused;
  each built table must own its vector index.
* **The first rebuild ever is held** for an admin to accept (Q7), and timed; later ones go straight on.
* **Survey writes after the check, before the swap** (Q6, the architect's Q6 points): the pipeline's other writers, from
  a download of the same commit. Not undone by an undo. Each is listed in the result.
* **The swap, recoverably** (C3 as accepted): projects.collections is PRUNED of dropped types before the swap, the
  tables and their indexes are swapped in one transaction (`swap_collections`), then the list is EXTENDED with added
  types. A reader never sees a list entry for a missing table. The query cache is invalidated after each list change.
  The phase is written on the run row before and after each step, so `recover` can finish forward or roll back.
* **Votes** are snapshotted before the swap and carried after it (`chunk_votes`); every move is kept for undo.
* **The previous index is kept 7 days** (Q4) under `{name}__previous`; undo restores it (and its votes) in the mirror
  order; a later job drops it (R1c).
* **No project-status writes.** A failed rebuild is recorded on its run row, never as the project's ERROR, since its live
  index still serves.
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from resource_explorer.index_state import has_own_index, own_collections, shared_collections

log = logging.getLogger(__name__)

RUN_KIND = "reindex"
ASIDE, PREVIOUS = "__rebuild", "__previous"
KEEP_PREVIOUS_DAYS = 7
ACTIVE_STATES = ("queued", "claimed", "running")

#: The steps, in order. A run's target carries `phase` (the last step completed) and `outcomes` (each step's words).
PHASES = ("queued", "building", "built", "awaiting_accept", "surveyed", "list_pruned", "swapped", "list_extended",
          "done", "rolled_back", "failed")
#: Phases at which nothing live has changed: a dead run is rolled back by dropping its aside tables.
BEFORE_LIVE = ("queued", "building", "built", "awaiting_accept", "surveyed")

#: The pipeline's other writers a rebuild re-runs (Q6), in the order a first index runs them.
SURVEY_WRITERS = ("_record_line_census", "_store_file_inventory", "_parse_dependencies", "_profile_data_files",
                  "_read_dataset_descriptors", "_parse_ci_workflows", "_parse_supply_chain", "_parse_repo_conventions")

UNDO_NOT_REVERTED = "survey results updated (not reverted by undo)"


class ReindexRefused(Exception):
    """A rebuild, accept or undo that cannot be done, with the sentence to show. `status` is the HTTP status."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def aside(name: str) -> str:
    return name + ASIDE


def previous(name: str) -> str:
    return name + PREVIOUS


def _now() -> datetime:
    return datetime.now(UTC)


def _target(row: dict) -> dict:
    t = row.get("target")
    if isinstance(t, dict):
        return t
    try:
        return json.loads(t or "{}")
    except (TypeError, ValueError):
        return {}


# ── who is doing what ─────────────────────────────────────────────────────────────────────────────────────────────

def active_run_for(registry, slug: str) -> dict | None:
    """The rebuild of `slug` that is queued or running, if any. A held run (awaiting accept) is not active: it has
    finished building and changes nothing until it is accepted."""
    for state in ACTIVE_STATES:
        for r in registry.list_runs(state=state, kind=RUN_KIND, limit=200):
            if _target(r).get("slug") == slug:
                return r
    return None


def any_active(registry) -> dict | None:
    for state in ACTIVE_STATES:
        rows = registry.list_runs(state=state, kind=RUN_KIND, limit=1)
        if rows:
            return rows[0]
    return None


def is_rebuilding(registry, slug: str) -> bool:
    """True while `slug` has a rebuild queued or running, or one held for accept. Refresh, first index and the
    scheduler's survey steps for `slug` are refused while it is (the architect's Q6 point 4)."""
    return active_run_for(registry, slug) is not None or held_run_for(registry, slug) is not None


def held_run_for(registry, slug: str) -> dict | None:
    for r in registry.list_runs(kind=RUN_KIND, limit=200):
        t = _target(r)
        if t.get("slug") == slug and t.get("phase") == "awaiting_accept" and not t.get("accepted"):
            return r
    return None


def latest_done(registry, slug: str) -> dict | None:
    """The last finished rebuild of `slug` whose previous index is still kept (undo window open, not undone)."""
    for r in registry.list_runs(kind=RUN_KIND, limit=200):
        t = _target(r)
        if t.get("slug") == slug and t.get("phase") == "done" and not t.get("undone") and not t.get("discarded"):
            return r
    return None


def ever_completed(registry) -> bool:
    return any(_target(r).get("phase") == "done" for r in registry.list_runs(kind=RUN_KIND, limit=500))


# ── queue ────────────────────────────────────────────────────────────────────────────────────────────────────────

def queue(registry, slug: str, *, requested_by: str, store=None) -> dict:
    """Queue one admin's yes to rebuild `slug`. Returns {run_id, held}; raises ReindexRefused otherwise."""
    if not (requested_by or "").strip():
        raise ReindexRefused("A rebuild needs a signed-in admin's yes; none is recorded for this request.", 401)
    p = registry.get(slug)
    if p is None:
        raise ReindexRefused(f"Project '{slug}' not found.", 404)
    name = p.display_name or slug
    if not has_own_index(p.slug, p.collections):
        raise ReindexRefused(f"{name} has no index of its own to rebuild; give it a first index instead.")
    if active_run_for(registry, slug) or held_run_for(registry, slug):
        raise ReindexRefused(f"{name} already has a rebuild queued, running, or waiting to be accepted.")
    other = any_active(registry)
    if other is not None:
        raise ReindexRefused(f"Another rebuild ({_target(other).get('slug', '?')}) is running; one at a time.")
    from resource_explorer.first_index import active_run_for as first_index_active
    if first_index_active(registry, slug) is not None:
        raise ReindexRefused(f"{name} is waiting for, or being given, a first index.")
    kept = latest_done(registry, slug)
    if kept is not None:
        until = _target(kept).get("previous_until", "")
        raise ReindexRefused(f"{name}'s previous index from its last rebuild is kept until {until[:10]} for undo; "
                             "undo it or discard it before rebuilding again.")
    store = store or _store()
    problems = store.check_names(*[n for c in own_collections(slug, p.collections) for n in (aside(c), previous(c))])
    if problems:
        raise ReindexRefused("; ".join(problems), 400)
    held = not ever_completed(registry)
    from resource_explorer.activity_logger import log_reindex

    activity_id = log_reindex(registry, slug, name, "running", f"Rebuild of {name}'s chat index: queued by "
                              f"{requested_by}" + (" (the first rebuild: held for accept before it swaps)." if held
                                                   else "."))
    target = {"slug": slug, "phase": "queued", "held": held, "asked_by": requested_by, "outcomes": []}
    run_id = registry.enqueue_run(RUN_KIND, target, requested_by=requested_by, result_ref=activity_id)
    return {"run_id": run_id, "held": held}


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Deps:
    """The collaborators, so a test can hand in fakes bound to the real signatures."""
    registry: Any
    store: Any = None
    analyzer: Any = None
    pipeline: Any = None
    client: Any = None
    query_cache: Any = None

    def __post_init__(self):
        if self.store is None:
            self.store = _store()
        if self.analyzer is None:
            from resource_explorer.github.analyzer import RepoAnalyzer
            self.analyzer = RepoAnalyzer()
        if self.pipeline is None:
            from resource_explorer.ingestion.pipeline import IngestionPipeline
            self.pipeline = IngestionPipeline()
        if self.client is None:
            from resource_explorer.github.client import GitHubClient
            self.client = GitHubClient()
        if self.query_cache is None:
            from resource_explorer.query_cache import QueryCache
            self.query_cache = QueryCache()


def _store():
    from resource_explorer.vector_store_pg import MultiCollectionStore
    return MultiCollectionStore()


class _Run:
    """One rebuild's state, written to its run row as it moves."""

    def __init__(self, run_id: str, deps: Deps):
        self.id, self.d = run_id, deps
        self.t = deps.registry.merge_run_target(run_id, {})

    def step(self, phase: str, words: str = "", **data) -> None:
        patch = {"phase": phase, **data}
        if words:
            patch["outcomes"] = list(self.t.get("outcomes") or []) + [{"phase": phase, "words": words,
                                                                        "at": _now().isoformat()}]
        self.t = self.d.registry.merge_run_target(self.id, patch)


def run(run_id: str, deps: Deps) -> tuple[str, str]:
    """Execute a `reindex` run: build, check, and either hold (the first ever) or go on to survey and swap. Returns
    (state, error) for the run queue. Never writes the project's status."""
    r = _Run(run_id, deps)
    slug = r.t["slug"]
    if r.t.get("continue_of"):
        return _continue_accepted(r)
    try:
        _build(r)
    except Exception as exc:  # the run row says what failed; the live index is untouched
        log.exception("rebuild of %s failed while building", slug)
        _drop_aside(r)
        r.step("failed", f"the build failed, and the live index is unchanged: {exc}")
        return "failed", str(exc)[:500]
    if r.t.get("refused"):
        _drop_aside(r)
        r.step("failed", f"the check refused the swap: {r.t['refused']}")
        return "failed", r.t["refused"]
    if r.t.get("held"):
        r.step("awaiting_accept", "held for an admin to accept: the first rebuild is checked by a person before it "
                                  "swaps")
        return "succeeded", ""
    return _finish(r)


def _build(r: _Run) -> None:
    d, slug = r.d, r.t["slug"]
    p = d.registry.get(slug)
    started = time.monotonic()
    r.step("building", "building aside from a fresh download; chat keeps the live index")
    plan = d.analyzer.analyze(p.github_url, subpath=p.subproject_path or None)
    live = own_collections(slug, p.collections)
    proposed = {f"{slug}_{ct.name}": ct for ct in plan.proposed_collections}
    problems = d.store.check_names(*[n for c in set(live) | set(proposed) for n in (aside(c), previous(c), c)])
    if problems:
        raise ValueError("; ".join(problems))
    repo = d.client.get_repo(p.github_url)
    sha = d.client.get_latest_commit_sha(repo)
    counts: dict[str, dict] = {}
    extra_docs = list(p.extra_docs_paths or [])
    doc_types = getattr(d.pipeline, "_DOC_CTYPES", frozenset())
    with tempfile.TemporaryDirectory() as tmp:
        extra: list[tuple[str, Path]] = []
        if p.subproject_path and extra_docs:
            # As a first index and a refresh do: the whole repository, so the extra docs paths outside the subproject
            # are ingested into the doc collections too.
            full = d.client.download_zipball(repo, Path(tmp), None, ref=sha)
            root = full / p.subproject_path
            extra = [(path, full / path) for path in extra_docs]
        else:
            root = d.client.download_zipball(repo, Path(tmp), p.subproject_path or None, ref=sha)
        for name, ct in proposed.items():
            if d.store.collection_exists(aside(name)):
                d.store.drop_collection(aside(name))
            kw = {"extra_paths": extra} if extra and ct.name in doc_types else {}
            new = d.pipeline._ingest_collection(repo, slug, aside(name), ct,
                                                root if ct.name != "release_notes" else None, id_collection=name,
                                                **kw)
            old = d.store.count(name) if name in live and d.store.collection_exists(name) else 0
            counts[name] = {"old": old, "new": int(new or 0)}
    for name in live:
        if name not in proposed:
            counts[name] = {"old": d.store.count(name) if d.store.collection_exists(name) else 0, "new": None}
    refused = [f"{n} had {c['old']} chunk(s) and now has none" for n, c in counts.items()
               if c["new"] == 0 and c["old"] > 0]
    unindexed = [n for n, c in counts.items() if c["new"] and not d.store.has_vector_index(aside(n))]
    if unindexed:
        refused.append("these rebuilt tables have no vector index: " + ", ".join(unindexed))
    added = sorted(n for n, c in counts.items() if c["new"] and n not in live)
    dropped = sorted(n for n in live if n not in proposed)
    kept = sorted(n for n, c in counts.items() if c["new"] and n in live)
    words = "; ".join(f"{n}: {c['old']} → {c['new'] if c['new'] is not None else 'dropped'}"
                      for n, c in sorted(counts.items()))
    r.step("built", f"built: {words}", sha=sha, counts=counts, added=added, dropped=dropped, kept=kept,
           built_seconds=round(time.monotonic() - started, 1), refused="; ".join(refused))


def accept(registry, run_id: str, *, requested_by: str) -> dict:
    """An admin accepts a held first rebuild: a continuation run does the survey writes and the swap."""
    row = registry.get_run(run_id)
    if row is None or row.get("kind") != RUN_KIND:
        raise ReindexRefused(f"No rebuild {run_id!r}.", 404)
    t = _target(row)
    if t.get("phase") != "awaiting_accept" or t.get("accepted"):
        raise ReindexRefused("That rebuild is not waiting to be accepted.")
    if not (requested_by or "").strip():
        raise ReindexRefused("Accepting needs a signed-in admin.", 401)
    registry.merge_run_target(run_id, {"accepted": requested_by, "accepted_at": _now().isoformat()})
    cont = {**{k: t[k] for k in ("slug", "sha", "counts", "added", "dropped", "kept") if k in t},
            "phase": "built", "held": False, "continue_of": run_id, "asked_by": requested_by, "outcomes": []}
    from resource_explorer.activity_logger import log_reindex

    slug = t.get("slug", "")
    activity_id = log_reindex(registry, slug, slug, "running",
                              f"Rebuild of {slug}'s chat index: accepted by {requested_by}; survey writes and swap "
                              "queued.")
    new_id = registry.enqueue_run(RUN_KIND, cont, requested_by=requested_by, result_ref=activity_id)
    return {"run_id": new_id}


def _continue_accepted(r: _Run) -> tuple[str, str]:
    return _finish(r)


def _finish(r: _Run) -> tuple[str, str]:
    """Survey writes, then the recoverable swap. Each step is recorded before the next starts."""
    try:
        _survey(r)
    except Exception as exc:  # nothing live changed yet
        log.exception("rebuild of %s failed in its survey writes", r.t["slug"])
        _drop_aside(r)
        r.step("failed", f"the survey writes failed before the swap, so nothing was swapped: {exc}")
        return "failed", str(exc)[:500]
    try:
        _swap(r)
    except Exception as exc:  # recover() decides by the phase reached
        log.exception("rebuild of %s failed during the swap", r.t["slug"])
        result = recover_target(r)
        return "failed", f"{exc} ({result})"[:500]
    return "succeeded", ""


def _survey(r: _Run) -> None:
    d, slug = r.d, r.t["slug"]
    p = d.registry.get(slug)
    repo = d.client.get_repo(p.github_url)
    done: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = d.client.download_zipball(repo, Path(tmp), p.subproject_path or None, ref=r.t.get("sha"))
        file_count, loc = d.pipeline._count_repo_stats(root)
        for writer in SURVEY_WRITERS:
            fn = getattr(d.pipeline, writer, None)
            if fn is None:
                continue
            try:
                fn(slug, root, repo=repo) if writer == "_store_file_inventory" else fn(slug, root)
                done.append({"writer": writer.lstrip("_"), "state": "done"})
            except Exception as exc:  # noqa: BLE001 -- listed, not fatal: the index is the rebuild's purpose
                done.append({"writer": writer.lstrip("_"), "state": "failed", "error": str(exc)[:200]})
    failed = [w["writer"] for w in done if w["state"] == "failed"]
    words = f"{UNDO_NOT_REVERTED}: " + ", ".join(w["writer"] for w in done if w["state"] == "done")
    if failed:
        words += f"; failed: {', '.join(failed)}"
    r.step("surveyed", words, survey=done, file_count=file_count, loc=loc)


def _set_list(r: _Run, collections: list[str]) -> None:
    d, slug = r.d, r.t["slug"]
    d.registry.set_project_collections(slug, collections)
    d.query_cache.invalidate_project(slug)


def _swap(r: _Run) -> None:
    from resource_explorer import chunk_votes

    d, slug = r.d, r.t["slug"]
    p = d.registry.get(slug)
    shared = shared_collections(slug, p.collections)
    live = own_collections(slug, p.collections)
    dropped, added, kept = r.t.get("dropped") or [], r.t.get("added") or [], r.t.get("kept") or []
    snaps = {n: chunk_votes.snapshot(d.store, n) for n in live if d.store.collection_exists(n)}
    # 1. prune: the dropped types leave the list while their tables still exist, so no reader names a missing one.
    pruned = [c for c in live if c not in dropped] + [c for c in shared if c not in live]
    _set_list(r, pruned)
    r.step("list_pruned", f"dropped from the list: {', '.join(dropped) or 'none'}", list_before=live + [
        c for c in shared if c not in live])
    # 2. swap, one transaction: live -> previous for every live table rebuilt or dropped; aside -> live for the built.
    renames = [(n, previous(n)) for n in kept + dropped if d.store.collection_exists(n)]
    renames += [(aside(n), n) for n in kept + added]
    d.store.swap_collections(renames)
    r.step("swapped", f"swapped {len(kept) + len(added)} collection(s); the previous index is kept",
           renames=renames)
    # 3. votes, now that the new rows are live.
    moved: dict[str, str] = {}
    vote_words: list[str] = []
    for n, snap in snaps.items():
        if not snap or n in dropped:
            continue
        rows = [(n, row["id"], row.get("text") or "", str((row.get("metadata") or {}).get("file_path") or
                 (row.get("metadata") or {}).get("source_url") or ""))
                for row in d.store.all_rows(n)]
        report = chunk_votes.carry(snap, rows)
        moved.update(report.moved)
        vote_words.append(f"{n}: {report.words()}")
    # 4. extend: the added types join the list now that their tables exist.
    final = kept + added + [c for c in shared if c not in kept + added]
    _set_list(r, final)
    r.step("list_extended", f"added to the list: {', '.join(added) or 'none'}" +
           (f"; {'; '.join(vote_words)}" if vote_words else ""), vote_moves=moved)
    _complete(r, final)


def _complete(r: _Run, final: list[str]) -> None:
    d, slug = r.d, r.t["slug"]
    d.registry.update_indexed_at(slug, final)
    if r.t.get("sha"):
        d.registry.update_commit_sha(slug, r.t["sha"])
    if r.t.get("file_count") is not None:
        d.registry.update_ingestion_stats(slug, int(r.t.get("file_count") or 0), int(r.t.get("loc") or 0))
    mine = own_collections(slug, final)
    counts = {c: d.store.count(c) for c in mine}
    d.registry.upsert_metric(slug, "rag_ingestion", {"total_chunks": sum(counts.values()), "collections": len(mine)},
                             detail={"by_collection": counts, "rebuild": True})
    d.query_cache.invalidate_project(slug)
    until = (_now() + timedelta(days=KEEP_PREVIOUS_DAYS)).isoformat()
    r.step("done", f"rebuilt; undo available until {until[:10]}", previous_until=until)


def _drop_aside(r: _Run) -> None:
    d, slug = r.d, r.t["slug"]
    p = d.registry.get(slug)
    names = set(own_collections(slug, p.collections if p else [])) | set((r.t.get("counts") or {}).keys())
    for n in names:
        try:
            if d.store.collection_exists(aside(n)):
                d.store.drop_collection(aside(n))
        except Exception as exc:  # noqa: BLE001 -- best effort; the name stays visible as __rebuild
            log.warning("could not drop %s: %s", aside(n), exc)


# ── recovery ─────────────────────────────────────────────────────────────────────────────────────────────────────

def recover_target(r: _Run) -> str:
    """Finish forward or roll back by the phase reached. Never leaves "swapped but the list not extended" (an added type
    never queried) or "pruned but the swap failed" (a dropped type gone from chat while its old index still serves)."""
    phase = r.t.get("phase")
    d, slug = r.d, r.t["slug"]
    if phase in BEFORE_LIVE:
        _drop_aside(r)
        r.step("rolled_back", f"rolled back at {phase}: nothing live had changed; the aside tables were dropped")
        return "rolled back"
    if phase == "list_pruned":
        before = r.t.get("list_before") or []
        _set_list(r, before)
        _drop_aside(r)
        r.step("rolled_back", "rolled back after the list was pruned and before the swap: the list is restored and "
                              "the live index was never changed")
        return "rolled back"
    if phase in ("swapped", "list_extended"):
        kept, added = r.t.get("kept") or [], r.t.get("added") or []
        p = d.registry.get(slug)
        shared = shared_collections(slug, p.collections if p else [])
        final = kept + added + [c for c in shared if c not in kept + added]
        if phase == "swapped":
            _set_list(r, final)
            r.step("list_extended", "finished forward after the swap: the added types joined the list")
        _complete(r, final)
        return "finished forward"
    return f"nothing to recover at {phase}"


def recover(registry, row: dict, deps: Deps | None = None) -> str:
    """Called for a `reindex` run whose process died (run_reconciler)."""
    deps = deps or Deps(registry=registry)
    return recover_target(_Run(row["id"], deps))


# ── undo ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def undo(registry, slug: str, *, requested_by: str, deps: Deps | None = None) -> dict:
    """Restore the previous index of `slug`'s last rebuild, within its 7 days, in the mirror order: types the rebuild
    ADDED leave the list first, the swap is reversed (an added type's table is set aside as `__rebuild`), then the
    types it DROPPED rejoin the list. Votes moved by the rebuild are moved back. Survey writes are not reverted."""
    if not (requested_by or "").strip():
        raise ReindexRefused("Undo needs a signed-in admin.", 401)
    row = latest_done(registry, slug)
    if row is None:
        raise ReindexRefused(f"{slug} has no rebuild whose previous index is still kept.", 404)
    deps = deps or Deps(registry=registry)
    r = _Run(row["id"], deps)
    if r.t.get("previous_until", "") < _now().isoformat():
        raise ReindexRefused(f"The undo window for {slug} closed on {r.t.get('previous_until', '')[:10]}.")
    if is_rebuilding(registry, slug):
        raise ReindexRefused(f"{slug} has another rebuild in progress.")
    d = deps
    kept, added, dropped = r.t.get("kept") or [], r.t.get("added") or [], r.t.get("dropped") or []
    p = d.registry.get(slug)
    shared = shared_collections(slug, p.collections)
    _set_list(r, kept + [c for c in shared if c not in kept])
    renames = [(n, aside(n)) for n in kept + added] + [(previous(n), n) for n in kept + dropped]
    d.store.swap_collections(renames)
    restored = kept + dropped
    _set_list(r, restored + [c for c in shared if c not in restored])
    metrics = _metrics()
    back = 0
    for old, new in (r.t.get("vote_moves") or {}).items():
        if metrics.move_chunk_votes(new, old):
            back += 1
    for n in kept + added:
        if d.store.collection_exists(aside(n)):
            d.store.drop_collection(aside(n))
    d.query_cache.invalidate_project(slug)
    words = (f"undone by {requested_by}: the previous index is live again; {back} vote(s) moved back; "
             f"{UNDO_NOT_REVERTED} stay as the rebuild left them")
    r.step("done", words, undone=requested_by, undone_at=_now().isoformat())
    from resource_explorer.activity_logger import log_reindex

    log_reindex(registry, slug, p.display_name or slug, "ok", f"Rebuild of {slug}'s chat index {words}.")
    return {"run_id": row["id"], "votes_moved_back": back}


def _metrics():
    from resource_explorer.vector_store_pg import _metrics_collector
    return _metrics_collector()


# ── what the page reads ──────────────────────────────────────────────────────────────────────────────────────────

def progress(registry, slug: str) -> dict:
    """The latest rebuild of `slug`: its phase, each step's words, and when the undo window closes."""
    for r in registry.list_runs(kind=RUN_KIND, limit=200):
        t = _target(r)
        if t.get("slug") == slug:
            return {"run_id": r["id"], "state": r.get("state"), "phase": t.get("phase"), "held": t.get("held"),
                    "outcomes": t.get("outcomes") or [], "counts": t.get("counts") or {},
                    "survey": t.get("survey") or [], "previous_until": t.get("previous_until", ""),
                    "undone": bool(t.get("undone")), "error": r.get("error", "")}
    return {"run_id": None}
