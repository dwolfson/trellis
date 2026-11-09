"""The feedback store: items plus an append-only triage log, on Postgres or SQLite.

Design: docs/trellis-feedback-extraction.md §4. One store instance belongs to one app, which is
stamped on everything it writes. On Postgres each app keeps its tables in its own schema (the
`trellis-vectorstore` arrangement); SQLite (tests, a from-scratch box) has no schemas.

Nothing here updates a row in place. An item is written once; its status is the latest of its
triage events, ordered by a monotonic sequence id. That removes both ways EA's file-based triage
could go wrong (§1): a position that drifts from the record, and a whole-file rewrite.
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    func,
    insert,
    literal,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from trellis_feedback.models import (
    ITEM_SOURCE,
    KINDS,
    PRODUCT_CATEGORIES,
    STATUSES,
    FeedbackError,
    FeedbackItem,
    TriageEvent,
    TriageState,
)

ITEMS_TABLE = "trellis_feedback_items"
EVENTS_TABLE = "trellis_feedback_events"

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SOURCE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

#: Columns copied between FeedbackItem and the items table, other than id/created_at/extra.
_ITEM_FIELDS = (
    "app", "kind", "user_id", "session_id",
    "vote", "query_text", "response_text", "intent_label", "perspective", "routing_agent",
    "compile_id", "entity_type", "slug",
    "category", "page", "element_guid", "rating", "email", "wants_response",
    "consent_to_contact", "build_version", "user_agent", "viewport", "locale",
    "message",
)


class NotFound(FeedbackError):
    """The item or subject named does not exist in this store."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _build_tables(schema: str | None) -> tuple[MetaData, Table, Table]:
    md = MetaData(schema=schema)
    items = Table(
        ITEMS_TABLE, md,
        Column("id", String(36), primary_key=True),
        Column("app", String(64), nullable=False),
        Column("kind", String(16), nullable=False),
        Column("idempotency_key", String(128), nullable=True),
        Column("user_id", Text, nullable=False, default=""),
        Column("session_id", Text, nullable=False, default=""),
        Column("vote", Integer, nullable=True),
        Column("query_text", Text, nullable=False, default=""),
        Column("response_text", Text, nullable=False, default=""),
        Column("intent_label", Text, nullable=False, default=""),
        Column("perspective", Text, nullable=False, default=""),
        Column("routing_agent", Text, nullable=False, default=""),
        Column("compile_id", Text, nullable=False, default=""),
        Column("entity_type", Text, nullable=False, default=""),
        Column("slug", Text, nullable=False, default=""),
        Column("category", Text, nullable=False, default=""),
        Column("page", Text, nullable=False, default=""),
        Column("element_guid", Text, nullable=False, default=""),
        Column("rating", Integer, nullable=True),
        Column("email", Text, nullable=False, default=""),
        Column("wants_response", Boolean, nullable=False, default=False),
        Column("consent_to_contact", Boolean, nullable=False, default=False),
        Column("build_version", Text, nullable=False, default=""),
        Column("user_agent", Text, nullable=False, default=""),
        Column("viewport", Text, nullable=False, default=""),
        Column("locale", Text, nullable=False, default=""),
        Column("message", Text, nullable=False, default=""),
        Column("extra", Text, nullable=False, default="{}"),
        Column("created_at", String(40), nullable=False),
        # A retried submit carries the same key and finds the first one, rather than duplicating it.
        # Scoped to the submitting user: a key is only ever matched against that user's own items, so
        # sending someone else's key cannot return their item (0.1 read-back P2). NULL keys never
        # collide, so a client that sends none is not deduplicated (stated, not hidden).
        UniqueConstraint("app", "user_id", "idempotency_key", name="uq_trellis_feedback_idempotency"),
    )
    Index("ix_trellis_feedback_items_created", items.c.app, items.c.created_at)
    events = Table(
        EVENTS_TABLE, md,
        # BIGSERIAL on Postgres; on SQLite an AUTOINCREMENT rowid, which never reuses a number --
        # without AUTOINCREMENT SQLite may hand the highest deleted seq out again.
        Column("seq", BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True),
        Column("app", String(64), nullable=False),
        Column("source", String(64), nullable=False),
        Column("ref_id", String(128), nullable=False),
        Column("status", String(32), nullable=False),
        Column("note", Text, nullable=False, default=""),
        Column("actor", Text, nullable=False, default=""),
        Column("created_at", String(40), nullable=False),
        sqlite_autoincrement=True,
    )
    Index("ix_trellis_feedback_events_subject", events.c.app, events.c.source, events.c.ref_id, events.c.seq)
    return md, items, events


class FeedbackStore:
    """Feedback for one app.

    `external_sources` is the closed list of the app's own tables whose rows may be triaged by
    reference (RE: ``("resource_feedback",)``) -- §4 item 3 and Q2. A source not declared here is
    refused, so a typo cannot quietly start a second, unread triage history.
    """

    def __init__(
        self,
        url: str,
        app: str,
        *,
        schema: str | None = None,
        external_sources: Iterable[str] = (),
        engine: Engine | None = None,
    ) -> None:
        if not app:
            raise FeedbackError("app is required")
        self.app = app
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        if schema is not None and not _SCHEMA_NAME.match(schema):
            raise FeedbackError(f"schema name {schema!r} is not a plain lower-case identifier")
        # SQLite has no schemas; a schema there would be read as an ATTACHed database name.
        self.schema = None if self.is_sqlite else schema
        self.external_sources = frozenset(external_sources)
        for s in self.external_sources:
            if s == ITEM_SOURCE or not _SOURCE_NAME.match(s):
                raise FeedbackError(f"external source {s!r} is reserved or not a plain identifier")
        if engine is None:
            kwargs: dict[str, Any] = {"future": True}
            if self.is_sqlite:
                # Threads share the engine; a writer waits for a lock instead of failing at once.
                kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            engine = create_engine(url, **kwargs)
        self.engine = engine
        self._md, self.items, self.events = _build_tables(self.schema)
        self._init_schema()

    # ── schema ──────────────────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self.engine.begin() as conn:
            if self.schema:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"'))
        self._md.create_all(self.engine)

    # ── items ───────────────────────────────────────────────────────────────────────────────

    def submit(self, item: FeedbackItem, *, idempotency_key: str | None = None) -> tuple[FeedbackItem, bool]:
        """Store `item`. Returns `(stored item, created)`.

        With an `idempotency_key` this same user has already used, nothing is written and that
        first item is returned with `created=False`: a retried submission is the same submission.
        The match is per user (`item.user_id`), never across users. Anonymous submissions all share
        the user "", so a caller exposing submit to anonymous users should not echo a replayed
        item's content back -- the router returns only its id.
        """
        item.app = self.app
        item.user_id = item.user_id or ""
        item.validate()
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()[:128] or None
            if idempotency_key:
                existing = self._by_key(item.user_id, idempotency_key)
                if existing is not None:
                    return existing, False
        item.id = uuid.uuid4().hex
        item.created_at = _now()
        row = {f: getattr(item, f) for f in _ITEM_FIELDS}
        row.update(id=item.id, created_at=item.created_at, idempotency_key=idempotency_key,
                   extra=json.dumps(item.extra or {}, sort_keys=True))
        for k, v in row.items():          # NOT NULL text columns: a None from a caller is ""
            if v is None and k not in ("vote", "rating", "idempotency_key"):
                row[k] = ""
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(self.items).values(**row))
        except IntegrityError:
            # Two submissions with one key raced past the lookup above; the other one won.
            if idempotency_key:
                existing = self._by_key(item.user_id, idempotency_key)
                if existing is not None:
                    return existing, False
            raise
        return item, True

    def _by_key(self, user_id: str, key: str) -> FeedbackItem | None:
        i = self.items
        with self.engine.connect() as conn:
            row = conn.execute(
                select(i).where(and_(i.c.app == self.app, i.c.user_id == user_id, i.c.idempotency_key == key))
            ).mappings().first()
        return self._item_from_row(row) if row else None

    def get(self, item_id: str) -> FeedbackItem | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.items).where(and_(self.items.c.app == self.app, self.items.c.id == item_id))
            ).mappings().first()
        return self._item_from_row(row) if row else None

    @staticmethod
    def _item_from_row(row: Any) -> FeedbackItem:
        data = dict(row)
        data.pop("idempotency_key", None)
        try:
            data["extra"] = json.loads(data.get("extra") or "{}")
        except ValueError:
            data["extra"] = {"_unreadable": data.get("extra")}
        data["wants_response"] = bool(data.get("wants_response"))
        data["consent_to_contact"] = bool(data.get("consent_to_contact"))
        return FeedbackItem(**data)

    def list(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        category: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Items, newest first, each with its current `triage` state.

        Every row carries the item's own `id`, and that id is the only handle triage takes -- there
        is no position for a client to get wrong (§6 step 2, EA's live bug).
        """
        q = self._filtered(kind=kind, status=status, category=category, since=since, until=until)
        i = self.items
        q = q.order_by(i.c.created_at.desc(), i.c.id).limit(max(1, min(int(limit), 1000))).offset(max(0, int(offset)))
        out = []
        with self.engine.connect() as conn:
            for row in conn.execute(q).mappings():
                data = dict(row)
                state = TriageState(
                    status=data.pop("t_status") or "new", note=data.pop("t_note") or "",
                    actor=data.pop("t_actor") or "", updated_at=data.pop("t_at") or "",
                    events=int(data.pop("t_events") or 0),
                )
                item = self._item_from_row(data).to_dict()
                item["triage"] = state.to_dict()
                out.append(item)
        return out

    def count_matching(self, *, kind: str | None = None, status: str | None = None,
                       category: str | None = None, since: str | None = None, until: str | None = None) -> int:
        """How many items `list` would return with these filters and no limit."""
        q = self._filtered(kind=kind, status=status, category=category, since=since, until=until)
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(q.subquery())).scalar_one())

    def _filtered(self, *, kind, status, category, since, until):
        """This app's items joined to their latest event, with the filters applied; no order/limit."""
        if kind is not None and kind not in KINDS:
            raise FeedbackError(f"kind must be one of {list(KINDS)}, got {kind!r}")
        if status is not None and status not in STATUSES:
            raise FeedbackError(f"status must be one of {list(STATUSES)}, got {status!r}")
        if category is not None and category not in PRODUCT_CATEGORIES:
            raise FeedbackError(f"category must be one of {list(PRODUCT_CATEGORIES)}, got {category!r}")
        latest = self._latest_events_subquery(ITEM_SOURCE)
        i = self.items
        q = (
            select(i, latest.c.status.label("t_status"), latest.c.note.label("t_note"),
                   latest.c.actor.label("t_actor"), latest.c.created_at.label("t_at"),
                   latest.c.n.label("t_events"))
            .select_from(i.outerjoin(latest, latest.c.ref_id == i.c.id))
            .where(i.c.app == self.app)
        )
        if kind:
            q = q.where(i.c.kind == kind)
        if category:
            q = q.where(i.c.category == category)
        if since:
            q = q.where(i.c.created_at >= since)
        if until:
            q = q.where(i.c.created_at < until)
        if status:
            q = q.where(func.coalesce(latest.c.status, "new") == status)
        return q

    def count(self, *, kind: str | None = None) -> int:
        q = select(func.count()).select_from(self.items).where(self.items.c.app == self.app)
        if kind:
            q = q.where(self.items.c.kind == kind)
        with self.engine.connect() as conn:
            return int(conn.execute(q).scalar_one())

    def delete_item(self, item_id: str) -> bool:
        """Delete an item AND its triage events, in one transaction (Q6: deleting removes the item,
        its text and its triage history). Returns False when there was no such item."""
        with self.engine.begin() as conn:
            gone = conn.execute(
                delete(self.items).where(and_(self.items.c.app == self.app, self.items.c.id == item_id))
            ).rowcount
            if not gone:
                return False
            conn.execute(delete(self.events).where(and_(
                self.events.c.app == self.app, self.events.c.source == ITEM_SOURCE,
                self.events.c.ref_id == item_id)))
        return True

    # ── triage ──────────────────────────────────────────────────────────────────────────────

    def _check_source(self, source: str) -> None:
        if source != ITEM_SOURCE and source not in self.external_sources:
            raise FeedbackError(
                f"source {source!r} is not '{ITEM_SOURCE}' or one of this app's declared external "
                f"sources {sorted(self.external_sources)}")

    def triage(self, ref_id: str, status: str, *, source: str = ITEM_SOURCE, note: str = "",
               actor: str = "") -> TriageEvent:
        """Record a status change. Appends; never updates.

        A library item must exist. An external row cannot be checked from here -- it is the app's
        own table -- so the app's route checks it before calling (the router factory does, through
        the app's lookup).
        """
        if status not in STATUSES:
            raise FeedbackError(f"status must be one of {list(STATUSES)}, got {status!r}")
        self._check_source(source)
        ref_id = str(ref_id or "").strip()
        if not ref_id:
            raise FeedbackError("ref_id is required")
        row = {"app": self.app, "source": source, "ref_id": ref_id, "status": status, "note": note or "",
               "actor": actor or "", "created_at": _now()}
        e = self.events
        with self.engine.begin() as conn:
            if source != ITEM_SOURCE:
                seq = conn.execute(insert(e).values(**row)).inserted_primary_key[0]
            else:
                # The check that the item exists and the insert are ONE statement (INSERT ... SELECT
                # FROM the item row), so a delete_item cannot land between them and leave an orphan
                # event (0.1 read-back P3). On Postgres the item row is also held FOR KEY SHARE until
                # this commits, so a concurrent delete_item waits and then removes this event with
                # the item; without the lock, its event delete could run before this insert commits.
                # SQLite serialises writers, so the single statement is enough there.
                i = self.items
                cols = ["app", "source", "ref_id", "status", "note", "actor", "created_at"]
                src = (
                    select(*[literal(row[c], type_=Text()).label(c) for c in cols])
                    .select_from(i)
                    .where(and_(i.c.app == self.app, i.c.id == ref_id))
                )
                if not self.is_sqlite:
                    src = src.with_for_update(read=True, key_share=True)
                seq = conn.execute(insert(e).from_select(cols, src).returning(e.c.seq)).scalar()
                if seq is None:
                    raise NotFound(f"no feedback item {ref_id!r}")
        return TriageEvent(seq=int(seq), **row)

    def history(self, ref_id: str, *, source: str = ITEM_SOURCE) -> list[TriageEvent]:
        self._check_source(source)
        e = self.events
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(e).where(and_(e.c.app == self.app, e.c.source == source, e.c.ref_id == str(ref_id)))
                .order_by(e.c.seq)
            ).mappings().all()
        return [TriageEvent(**dict(r)) for r in rows]

    def states(self, ref_ids: Iterable[str], *, source: str = ITEM_SOURCE) -> dict[str, TriageState]:
        """Current state for each id asked about; an id with no events is `new`."""
        self._check_source(source)
        ids = [str(r) for r in ref_ids]
        out = {r: TriageState.untouched() for r in ids}
        if not ids:
            return out
        latest = self._latest_events_subquery(source)
        with self.engine.connect() as conn:
            for row in conn.execute(select(latest).where(latest.c.ref_id.in_(ids))).mappings():
                out[row["ref_id"]] = TriageState(status=row["status"], note=row["note"], actor=row["actor"],
                                                 updated_at=row["created_at"], events=int(row["n"]))
        return out

    def state(self, ref_id: str, *, source: str = ITEM_SOURCE) -> TriageState:
        return self.states([ref_id], source=source)[str(ref_id)]

    def referenced(self, source: str) -> list[str]:
        """Every id in `source` that has triage events. For an external source, the app compares
        this with the rows it still has: one missing is shown as "item gone (source, id)" and keeps
        its events until an admin deletes them (Q7)."""
        self._check_source(source)
        e = self.events
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(e.c.ref_id).where(and_(e.c.app == self.app, e.c.source == source)).distinct()
                .order_by(e.c.ref_id)
            ).all()
        return [r[0] for r in rows]

    def gone(self, source: str, exists: Callable[[list[str]], Iterable[str]]) -> list[str]:
        """Referenced ids in an external `source` whose row the app no longer has. `exists` takes a
        list of ids and returns those still present."""
        if source == ITEM_SOURCE:
            raise FeedbackError("library items are deleted with their events; only external sources can be gone")
        refs = self.referenced(source)
        if not refs:
            return []
        present = {str(x) for x in exists(refs)}
        return [r for r in refs if r not in present]

    def delete_events(self, ref_id: str, *, source: str) -> int:
        """Delete every triage event of an external subject (an admin clearing an "item gone"
        row). Library items are deleted with `delete_item`, which takes their events with it."""
        if source == ITEM_SOURCE:
            raise FeedbackError("delete a library item with delete_item; its events go with it")
        self._check_source(source)
        e = self.events
        with self.engine.begin() as conn:
            return int(conn.execute(delete(e).where(and_(
                e.c.app == self.app, e.c.source == source, e.c.ref_id == str(ref_id)))).rowcount or 0)

    # ── internals ───────────────────────────────────────────────────────────────────────────

    def _latest_events_subquery(self, source: str):
        """One row per subject in `source`: its highest-seq event, plus how many events it has."""
        e = self.events
        agg = (
            select(e.c.ref_id.label("ref_id"), func.max(e.c.seq).label("mx"), func.count().label("n"))
            .where(and_(e.c.app == self.app, e.c.source == source))
            .group_by(e.c.ref_id)
            .subquery("agg")
        )
        return (
            select(e.c.ref_id, e.c.status, e.c.note, e.c.actor, e.c.created_at, agg.c.n)
            .select_from(e.join(agg, e.c.seq == agg.c.mx))
            .subquery("latest")
        )
