"""Feedback Store — RE's page-level product feedback, kept in the shared `trellis-feedback` library.

Since 2026-11-09 (docs/trellis-feedback-extraction.md §6 step 3) the rows live in the library's
`trellis_feedback_items` table and their status in its append-only `trellis_feedback_events` log,
the same store Egeria Advisor will use. This module is RE's facade over it: the routes and
curate.py's combined Admin listing keep calling `add`/`list`/`stats`/`update_triage_status`.

The tables are created on the URL's own search_path (the `resource_explorer` schema by default),
where the legacy `feedback` table already is, so a test's throwaway schema isolates both.

**Migration.** The first time a process opens a URL, any rows of the legacy `feedback` table that
the library does not hold yet are copied in with their own id and created_at
(`FeedbackStore.import_item`), and a legacy `triage_status` other than `new` becomes one triage
event, written in the same transaction as its item. Rows already copied are skipped, so running it
again, or from two processes at once, writes nothing twice. The legacy table is left in place and
nothing writes to it any more: a change made to it by hand after the copy is not carried over.
The copy runs at web startup (web/app.py), not inside the first request that needs the store.

See resource_explorer/web/admin_auth.py for the admin gating the triage endpoints require.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from trellis_feedback import (
    PRODUCT_CATEGORIES,
    STATUSES,
    FeedbackError,
    FeedbackItem,
    NotFound,
)
from trellis_feedback import FeedbackStore as _LibraryStore

logger = logging.getLogger(__name__)

APP = "resource-explorer"
#: RE's own tables whose rows Admin may triage by reference (Q2): Curate's per-resource feedback.
EXTERNAL_SOURCES = ("resource_feedback",)
LEGACY_TABLE = "feedback"
MIGRATION_ACTOR = "migration"

#: Q1: the library's six statuses. RE's old three (new, triaged, actioned) are among them.
VALID_TRIAGE_STATUSES = set(STATUSES)
VALID_CATEGORIES = set(PRODUCT_CATEGORIES)

#: Fields a page submission carries, copied between FeedbackEntry and the library item.
_ENTRY_FIELDS = (
    "session_id", "page", "element_guid", "rating", "category", "message", "email",
    "wants_response", "consent_to_contact", "build_version", "user_agent", "viewport", "locale",
)


@dataclass
class FeedbackEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    page: str = ""
    element_guid: str = ""
    rating: int | None = None
    category: str = ""  # bug | confusing | suggestion | praise
    message: str = ""
    email: str = ""
    wants_response: bool = False
    consent_to_contact: bool = False
    build_version: str = ""
    user_agent: str = ""
    viewport: str = ""
    locale: str = ""
    triage_status: str = "new"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


# One library store per URL per process: building one creates an engine and checks the schema,
# which a request should not pay for, and the legacy copy must run once, not per request.
_stores: dict[str, _LibraryStore] = {}
_stores_lock = threading.Lock()


def _library_store(url: str) -> _LibraryStore:
    with _stores_lock:
        store = _stores.get(url)
        if store is None:
            store = _LibraryStore(url, APP, external_sources=EXTERNAL_SOURCES)
            migrate_legacy_feedback(store)
            _stores[url] = store
        return store


def _as_utc(created_at: str) -> str:
    """Legacy rows were stamped with naive `datetime.utcnow()`; say so, as the library's own do."""
    value = (created_at or "").strip()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def migrate_legacy_feedback(store: _LibraryStore) -> dict[str, int]:
    """Copy the legacy `feedback` table's rows into the library. Safe to run any number of times.

    Returns counts: `legacy` rows seen, `imported` now, `skipped` (already there), `events`
    written, `refused` (a row the library would not take, logged and left behind).
    """
    counts = {"legacy": 0, "imported": 0, "skipped": 0, "events": 0, "refused": 0}
    if not inspect(store.engine).has_table(LEGACY_TABLE):
        return counts
    with store.engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(f"SELECT * FROM {LEGACY_TABLE}")).mappings()]
    for row in rows:
        counts["legacy"] += 1
        item = FeedbackItem(
            app=APP, kind="product", id=str(row.get("id") or ""),
            created_at=_as_utc(str(row.get("created_at") or "")),
            **{f: row.get(f) for f in _ENTRY_FIELDS},
        )
        item.wants_response = bool(item.wants_response)
        item.consent_to_contact = bool(item.consent_to_contact)
        status = (row.get("triage_status") or "new").strip()
        try:
            # The status goes in with the item, in one transaction: a crash between the two cannot
            # leave a copied row reading `new` that every later run then skips.
            imported = store.import_item(
                item, status=status if status in STATUSES else None, actor=MIGRATION_ACTOR,
                note=(f"status carried over from RE's legacy {LEGACY_TABLE} table, "
                      "which kept no time for the change"))
        except FeedbackError as exc:
            counts["refused"] += 1
            logger.warning("feedback migration: legacy row %r not copied: %s", row.get("id"), exc)
            continue
        if not imported:
            counts["skipped"] += 1
            continue
        counts["imported"] += 1
        if status in STATUSES and status != "new":
            counts["events"] += 1
    if counts["imported"] or counts["refused"]:
        logger.info("feedback migration from legacy %s table: %s", LEGACY_TABLE, counts)
    return counts


def _flatten(row: dict[str, Any]) -> dict[str, Any]:
    """A library list row, with the legacy `triage_status` key the Admin page still reads."""
    row["triage_status"] = (row.get("triage") or {}).get("status", "new")
    return row


class FeedbackStore:
    def __init__(self, db_path: str = "data/feedback.db") -> None:
        self.db_path = db_path
        if db_path == "data/feedback.db":
            try:
                from resource_explorer.config import get_config
                config = get_config()
                self.database_url = config.feedback.database_url
            except Exception:  # noqa: BLE001 -- no usable config: fall back to the env var, as before
                import os
                self.database_url = os.environ.get("FEEDBACK_DATABASE_URL", f"sqlite:///{db_path}")
        else:
            self.database_url = f"sqlite:///{db_path}"

        if self.database_url.startswith("sqlite:///"):
            path_str = self.database_url[len("sqlite:///"):]
            if path_str and path_str != ":memory:":
                Path(path_str).parent.mkdir(parents=True, exist_ok=True)

        self.store = _library_store(self.database_url)
        self.engine = self.store.engine

    def add(self, entry: FeedbackEntry) -> FeedbackEntry:
        item = FeedbackItem(app=APP, kind="product", **{f: getattr(entry, f) for f in _ENTRY_FIELDS})
        stored, _ = self.store.submit(item)
        entry.id, entry.created_at = stored.id, stored.created_at
        return entry

    def list(
        self,
        triage_status: str | None = None,
        category: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        # An unknown category matches nothing, as the old SQL filter did; the library refuses it, and
        # curate.py's combined listing passes whatever the Admin filter holds.
        if category and category not in VALID_CATEGORIES:
            return []
        rows = self.store.list(kind="product", status=triage_status or None,
                               category=category or None, limit=limit)
        return [_flatten(r) for r in rows]

    def get(self, feedback_id: str) -> dict[str, Any] | None:
        item = self.store.get(feedback_id)
        if item is None:
            return None
        row = item.to_dict()
        row["triage"] = self.store.state(feedback_id).to_dict()
        row["history"] = [e.to_dict() for e in self.store.history(feedback_id)]
        return _flatten(row)

    def stats(self) -> dict[str, Any]:
        i = self.store.items
        mine = (i.c.app == APP) & (i.c.kind == "product")
        with self.engine.connect() as conn:
            wants_response = conn.execute(
                select(func.count()).select_from(i).where(mine & i.c.wants_response.is_(True))
            ).scalar_one()
            avg_rating = conn.execute(
                select(func.avg(i.c.rating)).where(mine & i.c.rating.is_not(None))
            ).scalar_one()
        return {
            "total": self.store.count(kind="product"),
            "new": self.store.count_matching(kind="product", status="new"),
            "wants_response": int(wants_response),
            # float(): Postgres AVG() returns Decimal where SQLite returns a float, and plain
            # json.dumps() refuses a Decimal (found on the 2026-08-23 move to Postgres).
            "avg_rating": round(float(avg_rating), 2) if avg_rating is not None else None,
        }

    def update_triage_status(
        self, feedback_id: str, triage_status: str, *, note: str = "", actor: str = ""
    ) -> dict[str, Any] | None:
        """Append a triage event. Returns the item with its new state, or None if there is no such item."""
        if triage_status not in VALID_TRIAGE_STATUSES:
            raise ValueError(f"Invalid triage_status: {triage_status!r}")
        try:
            self.store.triage(feedback_id, triage_status, note=note, actor=actor)
        except NotFound:
            return None
        return self.get(feedback_id)
