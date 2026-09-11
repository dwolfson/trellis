"""Work lists — a named set of resources you are working through, and the
batch runs launched across one.

This is the storage and Egeria half of the `/next` Scouting slice: search →
select → **save as a work list** → **run one survey across the whole set,
concurrently** → compare → disposition in bulk → promote the survivors.

Self-contained on purpose. Everything the feature needs is here — its two
tables, its Egeria publish, its batch enqueue — so that if the `/next`
experiment is dropped, this module and its route file go with it and nothing
else has to be unpicked. It reaches into the registry for a connection and
for the run queue rather than growing a second one of either.

Egeria
------
**The type is `WorkingSet`, not `WorkList`.** The design asked for a
"`WorkList`-classified collection"; `WorkList` does not exist in Egeria — it
appears nowhere in the type archive or the framework's `OpenMetadataType`.
`WorkingSet` does, and its own description is exactly this feature:

    "Defines a list of elements that are being worked on by a process or by
     a group of people."  — OpenMetadataType.WORKING_SET_COLLECTION

It is a Collection SUBTYPE, not a classification, so it goes through
`typeName` (see `egeria_investigation_publisher._create_typed_collection`,
which this reuses rather than re-deriving).

`WorkItemList` is the other candidate and is the wrong one here — *"Defines a
list of activities such as ToDos, Tasks, etc..."*. A work list holds the
RESOURCES being worked on, not the activities being done to them. If the runs
launched across a set ever want cataloguing in their own right, that is what
`WorkItemList` would be for, and it would be a second collection beside this
one rather than a change to it.

RE already creates `WorkingSet` collections for an investigation's
per-disposition membership (`registry.get_or_create_disposition_set`), so this
is a second producer of the same subtype. They are told apart by
qualifiedName: work lists are namespaced `WorkingSet::resource-explorer::<slug>`.

`CollectionMembership` genuinely does carry `membershipRationale` — it is a
real `OpenMetadataProperty` — and pyegeria's `add_to_collection` takes an
optional relationship body, so a member's reason travels with it rather than
being local-only.

**Publishing is explicit, never automatic.** Creating a work list writes
locally and nothing else. `publish_work_list()` is what enqueues the Egeria
writes, and even then they are queued in the outbox and applied by whichever
worker drains it — which is the pattern every other Egeria write here uses,
and is what keeps a half-finished publish from being invisible.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

log = logging.getLogger(__name__)

#: The Egeria Collection subtype. See the module docstring for why this is not
#: `WorkList`.
EGERIA_TYPE_NAME = "WorkingSet"

#: The states a run can END in.
#:
#: MEASURED, not guessed. The first version of this invented `done` and left
#: out `claimed`, so a set whose runs had all SUCCEEDED reported
#: `finished 0/2, complete false` — forever. The UI polls on `complete`, so a
#: finished batch would have polled until the tab closed and the grid would
#: never have refreshed. Nothing errored; the numbers were simply always
#: wrong, which is the shape this project keeps finding.
#:
#: `ProjectRegistry.RUN_STATES` is the authority. This is kept as an explicit
#: subset rather than "everything that is not active", so that a NEW state
#: added upstream shows up here as unrecognised instead of being silently
#: counted as finished.
TERMINAL_RUN_STATES = ("succeeded", "failed", "cancelled")

#: What a run is doing while it is not finished. `claimed` is a real state —
#: a worker has taken the row but not started it — and omitting it is how a
#: run in flight gets counted as neither running nor done.
ACTIVE_RUN_STATES = ("queued", "claimed", "running")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(conn) -> None:
    """Create this feature's tables if they are not there.

    `CREATE TABLE IF NOT EXISTS` and nothing else — no `ALTER` to a table
    another session's code also writes. Several Claude sessions and two apps
    share this database; a purely additive schema cannot break any of them,
    and that property is worth more here than tidiness.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_lists (
            slug            TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            entity_type     TEXT NOT NULL DEFAULT 'repo',
            investigation   TEXT NOT NULL DEFAULT '',
            created_by      TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL,
            derived_from    TEXT NOT NULL DEFAULT '',
            egeria_guid     TEXT NOT NULL DEFAULT '',
            published_at    TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_list_members (
            work_list_slug  TEXT NOT NULL,
            entity_slug     TEXT NOT NULL,
            rationale       TEXT NOT NULL DEFAULT '',
            confidence      INTEGER,
            added_at        TEXT NOT NULL,
            PRIMARY KEY (work_list_slug, entity_slug)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_list_runs (
            set_id          TEXT NOT NULL,
            run_id          TEXT NOT NULL,
            work_list_slug  TEXT NOT NULL DEFAULT '',
            entity_slug     TEXT NOT NULL,
            analysis_id     TEXT NOT NULL,
            enqueued_at     TEXT NOT NULL,
            PRIMARY KEY (set_id, run_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_list_runs_set ON work_list_runs(set_id)")


class WorkLists:
    """Work-list storage, over the shared registry's connection."""

    def __init__(self, registry=None):
        from resource_explorer.registry import ProjectRegistry

        self.registry = registry or ProjectRegistry()

    def _conn(self):
        return self.registry._conn()

    # ── Work lists ──────────────────────────────────────────────────────

    def create(self, display_name: str, entity_slugs: Iterable[str], *,
               description: str = "", entity_type: str = "repo",
               investigation: str = "", created_by: str = "",
               derived_from: str = "", rationale: str = "",
               slug: str = "") -> dict:
        """Create a work list. LOCAL ONLY — nothing reaches Egeria here."""
        slug = slug or f"wl-{uuid.uuid4().hex[:10]}"
        # Materialise ONCE: `entity_slugs` may be a generator, and the old
        # shape consumed it in `dict.fromkeys` then counted it again, which
        # logs "0 members" for a list that has members.
        slugs = list(dict.fromkeys(entity_slugs))
        now = _now()
        with self._conn() as conn:
            _ensure_schema(conn)
            conn.execute(
                "INSERT INTO work_lists (slug, display_name, description, entity_type,"
                " investigation, created_by, created_at, derived_from)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, display_name, description, entity_type, investigation,
                 created_by, now, derived_from),
            )
            for entity_slug in slugs:
                conn.execute(
                    "INSERT INTO work_list_members (work_list_slug, entity_slug,"
                    " rationale, confidence, added_at) VALUES (?, ?, ?, ?, ?)",
                    (slug, entity_slug, rationale, None, now),
                )
        log.info("work list %s created with %d member(s)", slug, len(slugs))
        return self.get(slug)

    def get(self, slug: str) -> dict | None:
        with self._conn() as conn:
            _ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM work_lists WHERE slug = ?", (slug,)).fetchone()
            if not row:
                return None
            members = conn.execute(
                "SELECT entity_slug, rationale, confidence, added_at"
                " FROM work_list_members WHERE work_list_slug = ? ORDER BY added_at, entity_slug",
                (slug,)).fetchall()
        out = dict(row)
        out["members"] = [dict(m) for m in members]
        self._attach_dispositions(out["members"])
        return out

    def _attach_dispositions(self, members: list[dict]) -> None:
        """Add each member's current disposition, for grouping in the matrix.

        Dispositions are keyed by github_url, not by slug, so this is a
        two-step lookup per member. It is best-effort by design: a work list
        whose disposition store is unreachable must still open, with rows
        that say `undecided` rather than no rows at all. The matrix groups on
        this and a missing value is a legitimate group.
        """
        try:
            from resource_explorer.registry import ProjectRegistry
            registry = ProjectRegistry()
        except Exception:                                   # pragma: no cover
            return
        for m in members:
            m.setdefault("disposition", "")
            m.setdefault("github_url", "")
            try:
                # registry.get() returns a Project DATACLASS, not a dict —
                # a .get() call on it raises rather than returning None, and
                # the broad except below would have swallowed that into a
                # silent empty disposition for every row.
                project = registry.get(m["entity_slug"])
                url = getattr(project, "github_url", "") or ""
                if not url:
                    continue
                # The URL travels with the member too: dispositions and their
                # history are keyed on it, so a client that has only the slug
                # cannot ask for the verdict trail.
                m["github_url"] = url
                held = registry.get_disposition(url) or {}
                m["disposition"] = held.get("disposition") or ""
            except Exception:                               # pragma: no cover
                continue

    def list_all(self, *, investigation: str = "") -> list[dict]:
        with self._conn() as conn:
            _ensure_schema(conn)
            if investigation:
                rows = conn.execute(
                    "SELECT * FROM work_lists WHERE investigation = ?"
                    " ORDER BY created_at DESC", (investigation,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM work_lists ORDER BY created_at DESC").fetchall()
            out = []
            for row in rows:
                d = dict(row)
                d["member_count"] = conn.execute(
                    "SELECT COUNT(*) AS n FROM work_list_members WHERE work_list_slug = ?",
                    (d["slug"],)).fetchone()["n"]
                out.append(d)
        return out

    def set_member(self, slug: str, entity_slug: str, *,
                   rationale: str = "", confidence: int | None = None) -> None:
        """Add a member, or update the reason it is there."""
        with self._conn() as conn:
            _ensure_schema(conn)
            existing = conn.execute(
                "SELECT 1 FROM work_list_members WHERE work_list_slug = ? AND entity_slug = ?",
                (slug, entity_slug)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE work_list_members SET rationale = ?, confidence = ?"
                    " WHERE work_list_slug = ? AND entity_slug = ?",
                    (rationale, confidence, slug, entity_slug))
            else:
                conn.execute(
                    "INSERT INTO work_list_members (work_list_slug, entity_slug,"
                    " rationale, confidence, added_at) VALUES (?, ?, ?, ?, ?)",
                    (slug, entity_slug, rationale, confidence, _now()))

    def remove_member(self, slug: str, entity_slug: str) -> None:
        with self._conn() as conn:
            _ensure_schema(conn)
            conn.execute(
                "DELETE FROM work_list_members WHERE work_list_slug = ? AND entity_slug = ?",
                (slug, entity_slug))

    def delete(self, slug: str) -> None:
        """Remove the work list locally.

        Does NOT delete the Egeria Collection. Removing a published element
        is a catalog decision with its own consequences, and doing it as a
        side effect of tidying a local list is how a catalog loses history
        nobody meant to spend.
        """
        with self._conn() as conn:
            _ensure_schema(conn)
            conn.execute("DELETE FROM work_list_members WHERE work_list_slug = ?", (slug,))
            conn.execute("DELETE FROM work_lists WHERE slug = ?", (slug,))

    # ── Promotion ───────────────────────────────────────────────────────

    def promote(self, slug: str, survivors: Iterable[str], *,
                display_name: str = "", rationale: str = "",
                created_by: str = "") -> dict:
        """The survivors of one work list become a new, narrower one.

        The new list records `derived_from`, so the funnel keeps its own
        trail: a shortlist that cannot say what it was shortlisted FROM is a
        list of names, not a decision.
        """
        parent = self.get(slug)
        if not parent:
            raise KeyError(slug)
        keep = [s for s in survivors if any(m["entity_slug"] == s for m in parent["members"])]
        return self.create(
            display_name or f"{parent['display_name']} — shortlist",
            keep,
            description=f"Survivors of {parent['display_name']}",
            entity_type=parent["entity_type"],
            investigation=parent["investigation"],
            created_by=created_by,
            derived_from=slug,
            rationale=rationale,
        )

    # ── Batch runs ──────────────────────────────────────────────────────

    def enqueue_batch(self, analysis_id: str, entity_slugs: Iterable[str], *,
                      work_list_slug: str = "", requested_by: str = "") -> dict:
        """Enqueue one analysis across a SET of resources, and return a set id.

        The queue already does the hard half of this — `SKIP LOCKED` claims
        mean each extra worker is extra throughput, per-user fairness is live,
        and a dead worker is reconciled. What was missing was a caller that
        enqueues a set and a way to watch the set finish, which is all this is.

        One row per resource, so a single failure is one row's failure and the
        rest still run. The set id is ours, not the queue's: the queue has no
        concept of a set and does not need one.
        """
        slugs = list(dict.fromkeys(entity_slugs))
        if not slugs:
            raise ValueError("a batch needs at least one resource")
        set_id = f"set-{uuid.uuid4().hex[:12]}"
        now = _now()
        enqueued: list[dict] = []
        for entity_slug in slugs:
            run_id = self.registry.enqueue_run(
                "analysis_run",
                {"slug": entity_slug, "analysis_id": analysis_id},
                requested_by=requested_by,
            )
            enqueued.append({"run_id": run_id, "entity_slug": entity_slug})
        with self._conn() as conn:
            _ensure_schema(conn)
            for row in enqueued:
                conn.execute(
                    "INSERT INTO work_list_runs (set_id, run_id, work_list_slug,"
                    " entity_slug, analysis_id, enqueued_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (set_id, row["run_id"], work_list_slug, row["entity_slug"],
                     analysis_id, now))
        log.info("batch %s: enqueued %s across %d resource(s)", set_id, analysis_id, len(slugs))
        return {"set_id": set_id, "analysis_id": analysis_id,
                "work_list_slug": work_list_slug, "runs": enqueued}

    def batch_progress(self, set_id: str) -> dict | None:
        """What every run in this set is doing right now.

        Derived from the `runs` rows every time. Nothing about a set's
        progress is stored, so a worker that updates a run without knowing
        about sets cannot leave a stale summary behind — which is the failure
        a cached count would guarantee.
        """
        with self._conn() as conn:
            _ensure_schema(conn)
            rows = conn.execute(
                "SELECT wr.run_id, wr.entity_slug, wr.analysis_id, wr.enqueued_at,"
                "       r.state, r.error, r.result_ref, r.started_at, r.finished_at"
                "  FROM work_list_runs wr LEFT JOIN runs r ON r.id = wr.run_id"
                " WHERE wr.set_id = ? ORDER BY wr.entity_slug", (set_id,)).fetchall()
        if not rows:
            return None
        runs = []
        counts: dict[str, int] = {}
        for row in rows:
            d = dict(row)
            # A run row that has vanished is NOT a finished run. Saying
            # "unknown" keeps it out of the done count, where it would read as
            # a success nobody observed.
            state = (d.get("state") or "unknown")
            d["state"] = state
            counts[state] = counts.get(state, 0) + 1
            runs.append(d)
        terminal = set(TERMINAL_RUN_STATES)
        unrecognised = sorted(
            {r["state"] for r in runs}
            - set(TERMINAL_RUN_STATES) - set(ACTIVE_RUN_STATES) - {"unknown"})
        if unrecognised:
            # Neither finished nor in flight by this module's reckoning. Said
            # out loud rather than bucketed, because guessing is what produced
            # the `done` bug.
            log.warning("run set %s has unrecognised state(s): %s", set_id, unrecognised)
        return {
            "set_id": set_id,
            "total": len(runs),
            "counts": counts,
            "finished": sum(n for s, n in counts.items() if s in terminal),
            "complete": all(r["state"] in terminal for r in runs),
            "unrecognised_states": unrecognised,
            "runs": runs,
        }

    # ── Egeria ──────────────────────────────────────────────────────────

    def publish(self, slug: str, *, run_id: str = "") -> dict:
        """Publish a work list to Egeria as a `WorkingSet` Collection.

        Two halves, deliberately different:

        * the Collection is created SYNCHRONOUSLY, because its GUID is needed
          to attach anything to it and a caller that cannot record the GUID
          has published nothing it can find again. Same reasoning as the
          investigation publisher, which is where `_create_typed_collection`
          comes from.
        * the memberships are ENQUEUED to the outbox and applied by whichever
          worker drains it, each carrying its `membershipRationale`.

        A member whose resource was never published to Egeria has no GUID to
        attach and is REPORTED, not retried — that is a fact about the
        resource, not a failed write.
        """
        wl = self.get(slug)
        if not wl:
            raise KeyError(slug)

        from resource_explorer.egeria_outbox import _default_clients
        from resource_explorer.surveyors.egeria_investigation_publisher import (
            _create_typed_collection,
        )

        # `_default_clients()` returns a TUPLE — (clients, find_element_guid) —
        # not an `OutboxClients`. Unpacking it wrong gets you
        # `'tuple' object has no attribute 'require'` at publish time, which
        # is only reachable with a live platform and so is exactly the kind of
        # line a stub test does not exercise.
        clients, _find_element_guid = _default_clients()
        cm = clients.require("collection_manager")

        guid = (wl.get("egeria_guid") or "").strip()
        if not guid:
            guid = _create_typed_collection(
                cm, EGERIA_TYPE_NAME, wl["display_name"],
                wl.get("description") or f"Work list {slug}",
                qualified_name=f"{EGERIA_TYPE_NAME}::resource-explorer::{slug}",
            )
            if not guid:
                raise RuntimeError("Egeria returned no GUID for the collection")
            with self._conn() as conn:
                conn.execute(
                    "UPDATE work_lists SET egeria_guid = ?, published_at = ?"
                    " WHERE slug = ?", (guid, _now(), slug))

        attachable, unpublished = [], []
        for m in wl["members"]:
            project = self.registry.get(m["entity_slug"])
            member_guid = (getattr(project, "egeria_asset_guid", "") or "") if project else ""
            if member_guid:
                attachable.append({
                    "member_guid": member_guid,
                    "entity_type": wl["entity_type"],
                    "entity_slug": m["entity_slug"],
                    "rationale": m.get("rationale") or "",
                    "confidence": m.get("confidence"),
                })
            else:
                unpublished.append(m["entity_slug"])

        row_ids = enqueue_work_list_members(
            self.registry, slug, guid, attachable, run_id=run_id)

        return {
            "slug": slug,
            "egeria_guid": guid,
            "type_name": EGERIA_TYPE_NAME,
            "queued_members": len(row_ids),
            "outbox_row_ids": row_ids,
            # Named, not counted: "3 could not be attached" is not actionable
            # and "3 could not be attached: a, b, c" is.
            "members_without_an_egeria_asset": unpublished,
        }


def enqueue_work_list_members(registry, work_list_slug: str, collection_guid: str,
                              members: list[dict], *, run_id: str = "") -> list[int]:
    """Queue one `collection_membership` write per member, WITH its rationale.

    Deliberately not `egeria_outbox.enqueue_collection_members`: that one is
    the investigation path and carries no rationale, and widening it would
    change what every existing queued row means. This adds two optional keys
    the shared creator passes through only when they are present.
    """
    row_ids: list[int] = []
    for m in members:
        payload: dict[str, Any] = {
            "collection_guid": collection_guid,
            "member_guid": m["member_guid"],
            "member_entity_type": m.get("entity_type", ""),
            "member_entity_slug": m.get("entity_slug", ""),
        }
        if m.get("rationale"):
            payload["membership_rationale"] = m["rationale"]
        if m.get("confidence") is not None:
            payload["expected_confidence"] = m["confidence"]
        row_ids.append(registry.enqueue_outbox_element(
            "work_list", work_list_slug, "collection_membership",
            f"CollectionMembership::{collection_guid}::{m['member_guid']}",
            payload, run_id=run_id,
        ))
    return row_ids
