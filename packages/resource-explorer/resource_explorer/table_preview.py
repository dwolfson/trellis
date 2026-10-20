"""Table preview: the first n rows of one table, as the person's own database credential sees them.

Design: docs/design-notes/REPLY-DESIGNER-TABLE-PREVIEW-2026-10-19.md (and its ASK, which holds the owner's rulings).
Everything the route does that is not HTTP lives here, so the tests can reach it without a server.

**A preview is an act, not a view.** Nothing here runs until a person presses; then one typed query runs on the live
database with THEIR credential (`preview_credential_holder`, session-only), and the rows go back to the browser and
nowhere else:

* no row value is written to the registry, an activity row, a log line, an exception message or a trace attribute;
* the query is RE-built from catalogue names (`PostgreSQLConnection.build_preview_query`, `sql.Identifier` quoting),
  never SQL text from the caller; a table or column that is not in the stored catalogue cannot be asked for;
* a masked column is NOT SELECTED, so its values never leave the database unless the person reveals that column.

**Masking is per column and on by default** (owner, 2026-10-19). A column is shown only if RE profiled it and the
profile matched no PII data class, and no Confidentiality classification says otherwise. "Unknown" is never "safe":
a column the profile never read is masked, and one it read but could not decide is masked too.

**Audit, RE side.** Each preview and each reveal writes one `activity_log` row (who, the database user, which table,
when, how many rows, which columns were masked and revealed: column NAMES, never values) through the existing
activity write path, BEFORE the rows are returned, and the "recorded" the header shows is read back from that row. If
RE cannot record it, the rows are not shown. Egeria's record is not built (an open question for the architect, Mandy
note Q5): `record_in_egeria` is the named seam, and the header says so as a plain state.
"""
from __future__ import annotations

import datetime as _dt
import decimal
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass

from resource_explorer import preview_credential_holder as holder
from resource_explorer.surveyors.database import connection as db_connection
from resource_explorer.surveyors.database.column_matching import (
    MATCH_MATCHED,
    MATCH_NO_MATCH,
    MATCH_NOT_APPLICABLE,
    MATCH_NOT_SAMPLED,
    MATCH_PARTIAL,
)
from resource_explorer.surveyors.database.connection import (
    PREVIEW_LIMITS,
    PREVIEW_TIMEOUT_MS,
    PreviewDenied,
    PreviewError,
    PreviewStale,
    PreviewTimedOut,
)

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5
#: A request may reveal at most this many columns beyond those this preview's last audit row already revealed.
MAX_NEW_REVEALS = 1
#: A text cell longer than this is cut, and says so: a preview reads what a column holds, not whole documents.
MAX_CELL_CHARS = 500

# Masking reasons: the three the design names, plus one it did not foresee (see `_evidence`).
REASON_PII = "pii"
REASON_CONFIDENTIAL = "confidential"
REASON_NOT_PROFILED = "not_profiled"
REASON_UNDECIDED = "undecided"

#: Confidentiality levels at which a classification masks (curate_plan.CONFIDENTIALITY_LEVELS: public 0, internal 1,
#: confidential 2, restricted 4).
CONFIDENTIAL_FROM_LEVEL = 2
_LEVELS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 4}

#: The verdict names are `column_matching`'s own constants, so they cannot drift from the producer.
#: The ONLY verdict that unmasks: the values were read, candidates existed, and nothing conformed.
_VERDICT_NO_MATCH = MATCH_NO_MATCH
#: Verdicts that name a class the values conform to (fully or partly): masked as PII with the class name. Note that
#: `ColumnMatch.privacy_relevant` is NOT set on these (it belongs to the value patterns of an unmatched column), so
#: it can never be the test (finding 1).
_VERDICTS_MATCHED = (MATCH_MATCHED, MATCH_PARTIAL)
#: Nothing was read for this column.
_VERDICTS_NOT_READ = (MATCH_NOT_SAMPLED, MATCH_NOT_APPLICABLE)
# Every other verdict, and any string a later version of the producer invents, is masked as "undecided": the
# allowlist is `_VERDICT_NO_MATCH`, not a list of the dangerous ones.


class PreviewRefusal(Exception):
    """A request RE refuses before any query runs. `status` is the HTTP status the route answers with."""

    def __init__(self, status: int, sentence: str, code: str = "") -> None:
        super().__init__(sentence)
        self.status = status
        self.sentence = sentence
        self.code = code


class NotRecorded(Exception):
    """RE could not record the preview, so the rows were not shown."""


# ── the engine seam ──────────────────────────────────────────────────────────────────────────────────────────────

def engine_supported(db_type: str | None) -> bool:
    """Postgres only, today. The seam a later adapter fills is `DatabaseConnection.preview_rows` +
    `EngineCapabilities.row_preview`; this is the cheap check before a credential is even used."""
    return (db_type or "").strip().lower() == "postgresql"


def unsupported_sentence(db_type: str | None) -> str:
    return (f"Row preview is built for PostgreSQL only; this database is {db_type or 'of an unknown engine'}, "
            "which has no adapter for it yet.")


# ── the catalogue side: which table, which columns ──────────────────────────────────────────────────────────────

def catalogue_table(registry, slug: str, schema: str, table: str) -> dict | None:
    """The stored catalogue's node for `schema.table` (`{name, table_type, columns:[{name,...}]}`), or None.

    The same resolved node set the Schema Inventory reads, so a person can preview exactly what the tab lists, and
    nothing it does not: an unlisted name is refused rather than quoted into a query."""
    from resource_explorer.catalogue_scope import resolve_node_set

    for s in resolve_node_set(registry, slug).get("schemas", []):
        if s.get("schema") != schema:
            continue
        for t in s.get("tables", []) or []:
            if t.get("name") == table:
                return t
    return None


def table_kind(table_type: str | None) -> str:
    """'view' for a plain view (it runs its query on every read); everything else, a materialized view included
    (it stores its rows), previews like a table."""
    return "view" if (table_type or "").strip().upper() == "VIEW" else "table"


# ── masking ────────────────────────────────────────────────────────────────────────────────────────────────────

def column_classifications(registry, slug: str, schema: str, table: str) -> dict[str, dict]:
    """Per-column Confidentiality classifications `{column: {"level", "by", "at"}}`.

    Empty on this build, honestly: Curate records Confidentiality on the RESOURCE (the Enrichment `sensitivity` fact),
    and no column-level store exists yet. The seam is here so the day one does, a column can be masked for it.
    """
    return {}


def resource_confidentiality(registry, slug: str) -> dict | None:
    """The database's own Confidentiality judgement when it is `confidential` or above, else None."""
    ctx = registry.get_context("database", slug) or {}
    fact = (ctx.get("enrichment") or {}).get("sensitivity") or {}
    value = str(fact.get("value") or "").strip().lower()
    if _LEVELS.get(value, -1) < CONFIDENTIAL_FROM_LEVEL:
        return None
    return {"level": value, "by": fact.get("author") or "", "at": fact.get("set_at") or ""}


def _short_date(ts: str) -> str:
    """`2026-10-06T...` -> `10-06`, the date form the design's hover text uses."""
    return ts[5:10] if len(ts) >= 10 and ts[4] == "-" else ""


def _evidence(registry, slug: str, schema: str, table: str) -> dict[str, dict]:
    """The latest stored `data_class_match` verdict per column of this table: `{column: row}`."""
    rows = registry.query_detail_rows("database_column_matches", slug)
    return {r["column_name"]: r for r in rows
            if r.get("schema_name") == schema and r.get("table_name") == table
            and r.get("question") == "data_class_match"}


def masking_decisions(registry, slug: str, schema: str, table: str, column_names: list[str]) -> list[dict]:
    """One decision per column, in catalogue order: `{name, masked, reason, tag, hover}`.

    Masked when (first reason wins):
      1. `pii` -- the column profile matched a data class (`matched` or `partial_match`; the matched class is the
         reason, whatever `privacy_relevant` says: Egeria Data Classes are what RE has for "PII");
      2. `confidential` -- a Confidentiality classification of `confidential` or above (the database's, or a
         column's once a store exists);
      3. `not_profiled` -- no stored verdict, or the profile never read the column ("unknown is not safe");
      4. `undecided` -- the profile read it and could not decide (a pattern with no known class, too few distinct
         values). Not in the design's table: calling it "not profiled" would be a wrong label on a right decision,
         so it has its own muted tag.
    Shown ONLY when the profile's verdict is `no_match` (read, candidates existed, nothing conformed) and nothing
    classifies it confidential. Every other verdict, an unknown string included, stays masked.
    """
    evidence = _evidence(registry, slug, schema, table)
    col_class = column_classifications(registry, slug, schema, table)
    resource_class = resource_confidentiality(registry, slug)
    out = []
    for name in column_names:
        ev = evidence.get(name)
        run = _short_date((ev or {}).get("surveyed_at") or "")
        verdict = (ev or {}).get("verdict") or ""
        decision = {"name": name, "masked": True, "reason": None, "tag": "", "hover": ""}
        if ev and verdict in _VERDICTS_MATCHED:
            cls = ev.get("matched_display_name") or "a PII class"
            decision.update(reason=REASON_PII, tag=f"masked · {cls}",
                            hover=f"column profile matched the PII class {cls}" + (f" · run {run}" if run else ""))
        elif name in col_class or resource_class:
            c = col_class.get(name) or resource_class
            when = _short_date(c.get("at") or "")
            who = (f"set by {c['by']}{' ' + when if when else ''} in Enrichment" if c.get("by")
                   else "set in Enrichment")
            decision.update(reason=REASON_CONFIDENTIAL, tag="masked · confidential",
                            hover=f"Confidentiality classification · {who}")
        elif ev is None or verdict in _VERDICTS_NOT_READ or not verdict:
            decision.update(reason=REASON_NOT_PROFILED, tag="masked · not profiled",
                            hover="no column profile has read this column, so RE can't say it's safe")
        elif verdict == _VERDICT_NO_MATCH:       # profiled, candidates existed, nothing conformed: the one unmask
            decision.update(masked=False)
        else:                                    # unmatched_patterned, inconclusive, no_candidates, anything unknown
            decision.update(reason=REASON_UNDECIDED, tag="masked · undecided",
                            hover="the column profile read this column but could not decide whether it is "
                                  "sensitive, so RE can't say it's safe" + (f" · run {run}" if run else ""))
        out.append(decision)
    return out


def masking_counts(decisions: list[dict]) -> dict:
    """The count line's numbers. Each masked column counts once, under its (first) reason."""
    c = {REASON_PII: 0, REASON_CONFIDENTIAL: 0, REASON_NOT_PROFILED: 0, REASON_UNDECIDED: 0}
    for d in decisions:
        if d["masked"] and d["reason"] in c:
            c[d["reason"]] += 1
    return {"total": len(decisions), "masked": sum(1 for d in decisions if d["masked"]), **c}


# ── cells ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _cell(value):
    """A database value as something JSON can carry. Long text is cut; binary is described, not sent."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_CELL_CHARS else value[:MAX_CELL_CHARS] + "…"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, (decimal.Decimal, uuid.UUID, _dt.date, _dt.time, _dt.timedelta)):
        return str(value)
    text = str(value)
    return text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS] + "…"


# ── the audit row ───────────────────────────────────────────────────────────────────────────────────────────────

def record_in_egeria(entry: dict) -> dict:
    """THE SEAM for Egeria's central record of a preview or reveal.

    NOT BUILT: which element or relationship carries "who previewed which table, when, how many rows, which columns
    were revealed" is an open question for the architect (ASK-DESIGNER-TABLE-PREVIEW-2026-10-19, "For the
    architect"; Mandy note Q5). The owner ruled that a preview runs whether or not Egeria can take its record, so
    when this is built it must queue through the outbox and never block the rows. `entry` is the RE activity row
    (no values). Returns the state the header shows.
    """
    return {"state": "not_built"}


def _record_in_re(registry, *, slug, db_name, location, person, db_user, schema, table, action, limit, outcome,
                  row_count, masked, revealed) -> dict:
    """Write the one activity row, then read it back: the header's "recorded" comes from what was read back."""
    from resource_explorer.activity_logger import log_preview

    try:
        entry_id = log_preview(
            registry, slug=slug, name=db_name, location=location, who=person, db_user=db_user, schema=schema,
            table=table, action=action, limit=limit, outcome=outcome, rows=row_count, masked=masked,
            revealed=revealed)
        row = registry.get_activity(entry_id)
    except Exception as exc:                     # noqa: BLE001 - reported below; the type only, nothing it carried
        log.error("table preview: the RE audit row could not be written (%s)", type(exc).__name__)
        raise NotRecorded("RE could not record this preview, so no rows are shown") from None
    if not row:
        raise NotRecorded("RE could not read back the record of this preview, so no rows are shown")
    return {"state": "recorded", "by": "RE", "at": row["ts"], "id": entry_id}


# ── the preview ──────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PreviewRequest:
    slug: str
    schema: str
    table: str
    limit: int = 20
    reveal: tuple[str, ...] = ()


def _header(db, req: PreviewRequest, kind: str, as_user: str) -> dict:
    return {"database": db.slug, "schema": req.schema, "table": req.table, "kind": kind, "limit": req.limit,
            "as_user": as_user}


def _last_revealed(registry, db, person: str, schema: str, table: str) -> set[str]:
    """The columns this person's most recent preview of this table (the audit row of it) had revealed.

    The baseline for "one new reveal per request" (finding 11): the server reads it from the RE audit rows rather
    than trusting what the browser says it already revealed. A fresh preview records none, so it starts masked."""
    try:
        rows = registry.list_activity(entity_type="database", entity_slug=db.slug, operation="preview", limit=100)
    except Exception:                            # noqa: BLE001 - unknown baseline: the strictest one, nothing revealed
        return set()
    for row in rows:                             # newest first
        try:
            d = json.loads(row.get("detail") or "{}")
        except ValueError:
            continue
        if d.get("action") in ("preview", "reveal") and d.get("who") == person \
                and d.get("schema") == schema and d.get("table") == table:
            return set(d.get("revealed") or [])
    return set()


def run_preview(registry, db, person: str, session: str, req: PreviewRequest) -> dict:
    """Run one preview (or reveal) for `person`'s sign-in `session` and answer with everything the pane draws.

    Raises `PreviewRefusal` for a request refused before any query (bad limit, unknown table, no stored credential,
    unsupported engine, more than one new reveal) and `NotRecorded` when the audit row could not be written. Every
    other outcome, a refusal by the database included, is an ANSWER with an `outcome` word the pane has a state
    for, and EVERY outcome that reached the database (a failed connect included) has its audit row first.
    """
    if req.limit not in PREVIEW_LIMITS:
        raise PreviewRefusal(422, f"limit must be one of {', '.join(str(n) for n in PREVIEW_LIMITS)}", "bad_limit")
    if not engine_supported(db.db_type):
        raise PreviewRefusal(409, unsupported_sentence(db.db_type), "unsupported")
    node = catalogue_table(registry, db.slug, req.schema, req.table)
    if node is None:
        raise PreviewRefusal(404, f"{req.schema}.{req.table} is not in the stored catalogue for {db.slug}; "
                                  "survey the database first", "not_in_catalogue")
    cols = [c for c in (node.get("columns") or []) if c.get("name")]
    names = [c["name"] for c in cols]
    if not names:
        raise PreviewRefusal(409, f"the stored catalogue holds no columns for {req.schema}.{req.table}, so there is "
                                  "nothing to select; survey the database again", "no_columns")
    types = {c["name"]: (c.get("type") or c.get("base_type") or c.get("data_type") or "") for c in cols}
    cred = holder.take(person, session, db.slug)
    if cred is None:
        raise PreviewRefusal(409, f"no credential of yours is held for {db.slug}; enter it first", "no_credential")

    decisions = masking_decisions(registry, db.slug, req.schema, req.table, names)
    by_name = {d["name"]: d for d in decisions}
    unknown = [n for n in req.reveal if n not in by_name]
    if unknown:
        raise PreviewRefusal(422, "cannot reveal a column the catalogue does not list for this table", "bad_reveal")
    revealed = [n for n in names if n in set(req.reveal) and by_name[n]["masked"]]
    if len(set(revealed) - _last_revealed(registry, db, person, req.schema, req.table)) > MAX_NEW_REVEALS:
        raise PreviewRefusal(422, "reveal one column at a time: this request asks for more than one new column",
                             "bad_reveal")
    selected = [n for n in names if (not by_name[n]["masked"]) or n in revealed]
    kind = table_kind(node.get("table_type"))
    header = _header(db, req, kind, cred.user)
    masked_names = [d["name"] for d in decisions if d["masked"]]
    action = "reveal" if revealed else "preview"

    def record(outcome: str, row_count: int) -> dict:
        return _record_in_re(
            registry, slug=db.slug, db_name=db.display_name or db.slug, location=f"{db.host}:{db.port}",
            person=person, db_user=cred.user, schema=req.schema, table=req.table, action=action, limit=req.limit,
            outcome=outcome, row_count=row_count, masked=masked_names, revealed=revealed)

    connected = False
    rows: list[dict] = []
    error: PreviewError | None = None
    try:
        with db_connection.database_connection(
                db, {"user": cred.user, "password": cred.password}, connect_timeout=CONNECT_TIMEOUT_SECONDS) as conn:
            connected = True
            if not conn.capabilities.row_preview:
                raise PreviewRefusal(409, unsupported_sentence(db.db_type), "unsupported")
            try:
                rows = conn.preview_rows(req.schema, req.table, selected, req.limit, timeout_ms=PREVIEW_TIMEOUT_MS,
                                         column_types={n: types[n] for n in selected})
            except PreviewError as exc:
                rows, error = [], exc
    except PreviewRefusal:
        raise
    except Exception as exc:                     # noqa: BLE001
        if connected:
            # Past the connect step: the text of this exception is never sent (it can quote a value), and it is
            # not a connect failure, so it is not labelled one (finding 6).
            error = PreviewError("the database answer could not be read")
            log.error("table preview: an unexpected %s after connecting", type(exc).__name__)
        else:
            failure = _connect_failure(db, cred, exc)
            recorded = record(failure["outcome"], 0)                # fail closed, like every other path (finding 5)
            return {**header, **failure, "recorded": recorded, "egeria": record_in_egeria(recorded)}

    if error is not None:
        recorded = record(error.kind, 0)
        return {**header, "outcome": error.kind, "sentence": error.sentence, "recorded": recorded,
                "egeria": record_in_egeria(recorded)}

    recorded = record("rows" if rows else "empty", len(rows))
    columns = [{**d, "revealed": d["name"] in revealed} for d in decisions]
    shown = [{n: _cell(r.get(n)) for n in selected} for r in rows]
    return {**header, "outcome": "rows" if rows else "empty", "row_count": len(rows), "columns": columns,
            "rows": shown, "counts": masking_counts(decisions), "recorded": recorded,
            "egeria": record_in_egeria(recorded)}


def _connect_failure(db, cred, exc: Exception) -> dict:
    """A failed connect as an outcome. The password is scrubbed from the text, and only the first line is kept."""
    from resource_explorer.credential_check import scrub

    msg = " ".join(scrub(str(exc), cred.password).split())[:300]
    where = f"{db.host}:{db.port}"
    if "FATAL" in msg or "authentication" in msg.lower():
        return {"outcome": "credential_refused",
                "sentence": f"the server at {where} refused your credential ({msg})"}
    return {"outcome": "unreachable", "sentence": f"could not reach {where} ({msg})"}


# ── the person's credential ─────────────────────────────────────────────────────────────────────────────────────

#: Five refused credentials for one (person, database) in ten minutes lock that pair out for ten minutes. In memory
#: and per process, like the credential itself: a restart forgets it, which is the lenient direction, so the audit
#: rows (every attempt, kept) are the durable record.
THROTTLE_FAILURES = 5
THROTTLE_WINDOW_SECONDS = 600.0
THROTTLE_LOCKOUT_SECONDS = 600.0
#: The one sentence for a wrong password AND an unknown user: the answer must not tell a guesser which it was.
REFUSED_SENTENCE = "Credential not kept: the database refused that user and password."
THROTTLED_SENTENCE = "Credential not tested: too many refused credentials for this database; try again in 10 minutes."


class _Throttle:
    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._locked_until: dict[tuple[str, str], float] = {}

    def locked(self, person: str, slug: str) -> bool:
        with self._lock:
            until = self._locked_until.get((person, slug))
            if until is None:
                return False
            if until <= self._clock():
                del self._locked_until[(person, slug)]
                return False
            return True

    def failed(self, person: str, slug: str) -> None:
        with self._lock:
            now = self._clock()
            recent = [t for t in self._failures.get((person, slug), []) if now - t < THROTTLE_WINDOW_SECONDS]
            recent.append(now)
            if len(recent) >= THROTTLE_FAILURES:
                self._locked_until[(person, slug)] = now + THROTTLE_LOCKOUT_SECONDS
                recent = []
            self._failures[(person, slug)] = recent

    def succeeded(self, person: str, slug: str) -> None:
        with self._lock:
            self._failures.pop((person, slug), None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


_THROTTLE = _Throttle()
throttle_reset = _THROTTLE.reset


def _record_credential_attempt(registry, db, person: str, user: str, outcome: str) -> None:
    from resource_explorer.activity_logger import log_preview_credential

    try:
        log_preview_credential(registry, slug=db.slug, name=db.display_name or db.slug,
                               location=f"{db.host}:{db.port}", who=person, db_user=user, outcome=outcome)
    except Exception as exc:                     # noqa: BLE001 - type only
        log.error("table preview: the credential attempt could not be recorded (%s)", type(exc).__name__)
        raise NotRecorded("RE could not record this credential attempt, so nothing was kept") from None


def hold_credential(registry, db, person: str, session: str, user: str, password: str, *,
                    not_after: float | None = None) -> str:
    """Test (connect with) the credential, then hold it for this person's sign-in. Returns the database user.

    EVERY attempt writes an RE activity row first (who, database user, outcome; never the password), and nothing is
    held if that row cannot be written. A wrong password and an unknown user get the same sentence, and five refusals
    in ten minutes lock the pair out for ten minutes. Raises `PreviewRefusal` (400 refused/unreachable, 429
    throttled) or `NotRecorded`. Blocking: call off the event loop."""
    from resource_explorer.credential_check import CredentialCheckError, check_database_credential

    if _THROTTLE.locked(person, db.slug):
        _record_credential_attempt(registry, db, person, user, "throttled")
        raise PreviewRefusal(429, THROTTLED_SENTENCE, "throttled")
    try:
        check_database_credential(db, user, password)
    except CredentialCheckError as exc:
        if exc.kind == "credential":
            _THROTTLE.failed(person, db.slug)
            _record_credential_attempt(registry, db, person, user, "refused")
            raise PreviewRefusal(400, REFUSED_SENTENCE, "refused") from None
        _record_credential_attempt(registry, db, person, user, "unreachable")
        raise PreviewRefusal(400, str(exc).replace("Credential not saved", "Credential not kept"),
                             "unreachable") from None
    _record_credential_attempt(registry, db, person, user, "held")
    _THROTTLE.succeeded(person, db.slug)
    holder.put(person, session, db.slug, user, password, not_after=not_after)
    return user
