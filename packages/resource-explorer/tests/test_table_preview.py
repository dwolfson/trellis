"""Table preview (REPLY-DESIGNER-TABLE-PREVIEW-2026-10-19): the typed query, masking, the session-only credential,
the three refusals, the audit row, and one end-to-end pass through the route with a fake connection that binds the
real signatures. No live database, no Egeria."""
from __future__ import annotations

import contextlib
import logging
import sqlite3
from unittest import mock

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import errors, sql

from resource_explorer import preview_credential_holder as holder
from resource_explorer import table_preview as tp
from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database import connection as conn_mod
from resource_explorer.surveyors.database.connection import (
    EngineCapabilities,
    PostgreSQLConnection,
    PreviewDenied,
    PreviewError,
    PreviewStale,
    PreviewTimedOut,
    PreviewUnsupported,
)

PASSWORD = "pw-not-a-real-secret-93"
VALUE = "ROW-VALUE-SENTINEL-77"
SURVEYED = "2026-10-06T10:00:00"


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────────

def _flat(composed):
    out = []
    for part in getattr(composed, "seq", [composed]):
        out.extend(_flat(part) if isinstance(part, sql.Composed) else [part])
    return out


class FakeCursor:
    def __init__(self, log, rows=None, raises=None):
        self.log, self.rows, self.raises = log, rows or [], raises

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, params=None):
        self.log.append(("execute", q))
        if self.raises is not None and not isinstance(q, str) and "LIMIT" in "".join(
                p.string for p in _flat(q) if isinstance(p, sql.SQL)):
            raise self.raises

    def fetchall(self):
        return self.rows


class FakePgConn:
    def __init__(self, rows=None, raises=None):
        self.log, self.rows, self.raises = [], rows, raises

    def rollback(self):
        self.log.append(("rollback", None))

    def cursor(self):
        return FakeCursor(self.log, self.rows, self.raises)


def _pg(rows=None, raises=None):
    c = PostgreSQLConnection("h", 1, "d", "u", "p")
    c._conn = FakePgConn(rows, raises)
    return c


# ── the typed query ──────────────────────────────────────────────────────────────────────────────────────────

class TestBuildPreviewQuery:
    def test_names_are_identifiers_and_limit_a_literal_int(self):
        q = PostgreSQLConnection.build_preview_query("sales", "orders", ["id", "email"], 20)
        parts = _flat(q)
        assert [p.strings for p in parts if isinstance(p, sql.Identifier)] == [
            ("id",), ("email",), ("sales",), ("orders",)]
        assert [p.wrapped for p in parts if isinstance(p, sql.Literal)] == [20]
        text = "".join(p.string for p in parts if isinstance(p, sql.SQL))
        assert text == "SELECT ,  FROM . LIMIT "

    def test_hostile_names_stay_inside_identifiers(self):
        evil = 'x"; DROP TABLE t; --'
        q = PostgreSQLConnection.build_preview_query(evil, evil, [evil], 100)
        text = "".join(p.string for p in _flat(q) if isinstance(p, sql.SQL))
        assert "DROP" not in text and ";" not in text
        assert all(p.strings == (evil,) for p in _flat(q) if isinstance(p, sql.Identifier))

    @pytest.mark.parametrize("bad", [0, 7, 21, 1000, "20; DROP TABLE t", None, 20.5])
    def test_only_the_two_counts_are_accepted(self, bad):
        with pytest.raises(ValueError):
            PostgreSQLConnection.build_preview_query("s", "t", ["a"], bad)

    def test_no_selectable_column_selects_a_constant_not_a_masked_value(self):
        q = PostgreSQLConnection.build_preview_query("s", "t", [], 20)
        assert "".join(p.string for p in _flat(q) if isinstance(p, sql.SQL)).startswith("SELECT 1 FROM")

    def test_the_only_text_entry_points_take_no_sql(self):
        import inspect
        params = inspect.signature(PostgreSQLConnection.preview_rows).parameters
        assert list(params) == ["self", "schema", "table", "columns", "limit", "timeout_ms"]
        assert not hasattr(PostgreSQLConnection, "preview_sql")


class TestPreviewRows:
    def test_read_only_transaction_first_then_timeout_then_the_query_then_rollback(self):
        c = _pg(rows=[(1, "a")])
        out = c.preview_rows("s", "t", ["id", "name"], 20)
        assert out == [{"id": 1, "name": "a"}]
        log = c._conn.log
        assert log[0] == ("rollback", None)
        assert log[1] == ("execute", "SET TRANSACTION READ ONLY")
        timeout = log[2][1]
        assert [p.wrapped for p in _flat(timeout) if isinstance(p, sql.Literal)] == [10000]
        assert "statement_timeout" in "".join(p.string for p in _flat(timeout) if isinstance(p, sql.SQL))
        assert log[-1] == ("rollback", None)

    def test_no_columns_gives_empty_dicts_per_row(self):
        assert _pg(rows=[(1,), (1,)]).preview_rows("s", "t", [], 20) == [{}, {}]

    def test_timeout(self):
        with pytest.raises(PreviewTimedOut) as ei:
            _pg(raises=errors.QueryCanceled("canceling statement due to statement timeout")).preview_rows(
                "s", "t", ["a"], 20)
        assert ei.value.sentence == "no rows shown · the query ran longer than 10 s and was stopped · nothing was read"

    def test_no_read_permission_quotes_the_first_line_only(self):
        exc = errors.InsufficientPrivilege("permission denied for table orders\nDETAIL: more")
        with pytest.raises(PreviewDenied) as ei:
            _pg(raises=exc).preview_rows("s", "orders", ["a"], 20)
        assert ei.value.sentence == "permission denied for table orders"

    def test_stale_catalogue(self):
        with pytest.raises(PreviewStale):
            _pg(raises=errors.UndefinedColumn('column "x" does not exist')).preview_rows("s", "t", ["x"], 20)

    def test_a_data_error_never_echoes_its_message(self):
        exc = errors.InvalidTextRepresentation(f'invalid input syntax for type integer: "{VALUE}"')
        with pytest.raises(PreviewError) as ei:
            _pg(raises=exc).preview_rows("s", "t", ["a"], 20)
        assert VALUE not in ei.value.sentence and VALUE not in str(ei.value)

    def test_base_engine_refuses_with_words(self):
        class Other(conn_mod.DatabaseConnection):
            connect = execute_query = get_schema_info = get_statistics = close = lambda self, *a, **k: None
        with pytest.raises(PreviewUnsupported):
            Other().preview_rows("s", "t", ["a"], 20)
        assert Other().capabilities.row_preview is False
        assert PostgreSQLConnection("h", 1, "d", "u", "p").capabilities.row_preview is True


# ── fixtures: registry + route ───────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "preview.db"))
    r.register_database(DatabaseEntity(
        slug="coco", display_name="Coco", db_type="postgresql", host="h", port=5432, database_name="coco",
        db_user="surveyor", db_password="surveyor-pw"))
    r.write_detail_rows("database_tables", "coco", SURVEYED, rows=[
        {"schema_name": "sales", "table_name": "orders", "table_type": "BASE TABLE", "row_count": 5,
         "size_bytes": 1, "state": "measured"},
        {"schema_name": "sales", "table_name": "v_orders", "table_type": "VIEW", "row_count": None,
         "size_bytes": None, "state": "measured"},
    ])
    cols = [("id", 1), ("email", 2), ("note", 3), ("qty", 4), ("odd", 5)]
    r.write_detail_rows("database_columns", "coco", SURVEYED, rows=[
        {"schema_name": "sales", "table_name": t, "column_name": n, "ordinal_position": i, "data_type": "text",
         "base_type": "text", "is_nullable": 1, "is_primary_key": 0, "foreign_key_json": None, "description": "",
         "state": "measured"}
        for t in ("orders", "v_orders") for n, i in cols])

    def match(col, verdict, pii=0, cls=""):
        return {"schema_name": "sales", "table_name": "orders", "column_name": col, "question": "data_class_match",
                "verdict": verdict, "established": 1, "privacy_relevant": pii, "matched_display_name": cls,
                "state": "measured"}
    r.write_detail_rows("database_column_matches", "coco", SURVEYED, rows=[
        match("id", "no_match"), match("email", "matched", 1, "email"), match("note", "not_sampled"),
        match("odd", "unmatched_patterned"),
    ])                                              # "qty" has no verdict at all
    return r


def _by(decisions):
    return {d["name"]: d for d in decisions}


class TestMasking:
    def test_each_reason_and_the_one_shown_column(self, registry):
        d = _by(tp.masking_decisions(registry, "coco", "sales", "orders", ["id", "email", "note", "qty", "odd"]))
        assert d["id"]["masked"] is False and d["id"]["reason"] is None
        assert (d["email"]["reason"], d["email"]["tag"]) == (tp.REASON_PII, "masked · email")
        assert "PII class email" in d["email"]["hover"] and "run 10-06" in d["email"]["hover"]
        assert (d["note"]["reason"], d["note"]["tag"]) == (tp.REASON_NOT_PROFILED, "masked · not profiled")
        assert "can't say it's safe" in d["note"]["hover"]
        assert d["qty"]["reason"] == tp.REASON_NOT_PROFILED       # never profiled at all
        assert d["odd"]["reason"] == tp.REASON_UNDECIDED          # read, could not decide: not "not profiled"

    def test_a_confidential_classification_masks_a_shown_column(self, registry):
        registry.save_context("database", "coco", {"enrichment": {
            "sensitivity": {"value": "confidential", "author": "dwolfson", "set_at": "2026-10-12T09:00:00"}}})
        d = _by(tp.masking_decisions(registry, "coco", "sales", "orders", ["id", "email"]))
        assert d["id"]["reason"] == tp.REASON_CONFIDENTIAL and d["id"]["tag"] == "masked · confidential"
        assert d["id"]["hover"] == "Confidentiality classification · set by dwolfson 10-12 in Enrichment"
        assert d["email"]["reason"] == tp.REASON_PII                # a finding outranks the classification

    @pytest.mark.parametrize("level", ["public", "internal", "unknown", ""])
    def test_a_low_classification_does_not_mask(self, registry, level):
        registry.save_context("database", "coco", {"enrichment": {"sensitivity": {"value": level}}})
        assert tp.masking_decisions(registry, "coco", "sales", "orders", ["id"])[0]["masked"] is False

    def test_a_table_with_no_stored_profile_masks_everything(self, registry):
        d = tp.masking_decisions(registry, "coco", "sales", "v_orders", ["id", "email"])
        assert all(x["masked"] and x["reason"] == tp.REASON_NOT_PROFILED for x in d)

    def test_counts_count_each_column_once(self, registry):
        c = tp.masking_counts(tp.masking_decisions(registry, "coco", "sales", "orders",
                                                   ["id", "email", "note", "qty", "odd"]))
        assert c == {"total": 5, "masked": 4, "pii": 1, "confidential": 0, "not_profiled": 2, "undecided": 1}


class TestCredentialHolder:
    def test_per_person_and_database_and_never_in_text(self):
        holder.clear_all()
        holder.put("dan", "coco", "dan_ro", PASSWORD)
        assert holder.held_user("dan", "coco") == "dan_ro"
        assert holder.held_user("mandy", "coco") is None and holder.held_user("dan", "other") is None
        cred = holder.take("dan", "coco")
        assert PASSWORD not in repr(cred) and PASSWORD not in str(cred)
        assert PASSWORD not in repr(holder._HOLDER)
        holder.clear_user("dan")
        assert holder.take("dan", "coco") is None

    def test_expires_at_the_session_end_and_the_ttl(self):
        holder.clear_all()
        now = [1000.0]
        h = holder._Holder(clock=lambda: now[0])
        h.put("dan", "coco", "u", PASSWORD, not_after=1100.0)
        now[0] = 1099.0
        assert h.take("dan", "coco")
        now[0] = 1100.0
        assert h.take("dan", "coco") is None
        h.put("dan", "coco", "u", PASSWORD, ttl=5)
        now[0] = 1106.0
        assert h.take("dan", "coco") is None

    def test_only_table_preview_reads_the_holder(self):
        import pathlib
        root = pathlib.Path(tp.__file__).parent
        users = sorted(str(p.relative_to(root)) for p in root.rglob("*.py")
                       if "preview_credential_holder" in p.read_text() and p.name != "preview_credential_holder.py")
        assert users == ["table_preview.py", "web/routes/auth.py", "web/routes/table_preview.py"]


# ── the route, end to end ────────────────────────────────────────────────────────────────────────────────────

class Spy:
    """A fake connection that binds the REAL signatures (autospec of PostgreSQLConnection and of
    database_connection), recording what it was asked and never touching a database."""

    def __init__(self, rows=None, raises=None):
        self.asked, self.opened = [], []
        self.rows, self.raises = rows, raises
        self.conn = mock.create_autospec(PostgreSQLConnection, instance=True, spec_set=True)
        self.conn.capabilities = EngineCapabilities(row_preview=True)
        self.conn.preview_rows.side_effect = self._preview
        self.opener = mock.create_autospec(conn_mod.database_connection, side_effect=self._open)

    def _open(self, db_entity, credentials, connect_timeout=None):
        self.opened.append((db_entity.slug, credentials["user"], connect_timeout))
        return contextlib.nullcontext(self.conn)

    def _preview(self, schema, table, columns, limit, *, timeout_ms=10000):
        self.asked.append((schema, table, list(columns), limit))
        if self.raises:
            raise self.raises
        return [{c: f"{VALUE}-{c}" if c != "id" else 1 for c in columns} for _ in range(self.rows or 3)]


@pytest.fixture
def env(registry, monkeypatch, caplog):
    holder.clear_all()
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setattr("resource_explorer.auth.get_current_user",
                        lambda request: {"user_id": "dan", "exp": 4102444800})
    # the credential check connects: stand in for it with a signature-bound fake
    from resource_explorer import credential_check
    checks = mock.create_autospec(credential_check.check_database_credential, side_effect=lambda db, u, p: None)
    monkeypatch.setattr(credential_check, "check_database_credential", checks)
    spy = Spy()
    monkeypatch.setattr(conn_mod, "database_connection", spy.opener)
    # nothing may write a credential anywhere
    monkeypatch.setattr(ProjectRegistry, "update_database_credentials",
                        lambda *a, **k: pytest.fail("credential written to the registry"))
    monkeypatch.setattr("resource_explorer.omsecrets_store.write_credential",
                        lambda *a, **k: pytest.fail("credential written to the secrets store"))
    caplog.set_level(logging.DEBUG)
    from resource_explorer.web.app import app
    return type("Env", (), {"client": TestClient(app), "spy": spy, "registry": registry, "checks": checks})


def _hold(env, user="dan_ro"):
    r = env.client.put("/api/databases/coco/preview/credential", json={"user": user, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r


def _preview(env, **body):
    return env.client.post("/api/databases/coco/preview", json={"schema": "sales", "table": "orders", **body})


def _everything_stored(registry, tmp_path):
    return "\n".join(sqlite3.connect(str(tmp_path / "preview.db")).iterdump())


class TestRoute:
    def test_signed_out_is_401(self, env, monkeypatch):
        monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: None)
        assert env.client.get("/api/databases/coco/preview/credential").status_code == 401
        assert _preview(env).status_code == 401

    def test_no_credential_held_is_409_and_runs_nothing(self, env):
        r = _preview(env)
        assert r.status_code == 409 and "no credential of yours" in r.json()["detail"]
        assert env.spy.opened == []

    def test_holding_tests_first_names_the_user_never_the_password(self, env):
        r = _hold(env)
        assert r.json() == {"held": True, "user": "dan_ro"}
        env.checks.assert_called_once()
        g = env.client.get("/api/databases/coco/preview/credential").json()
        assert g["held"] and g["user"] == "dan_ro" and PASSWORD not in str(g)

    def test_a_refused_credential_holds_nothing(self, env):
        from resource_explorer.credential_check import CredentialCheckError
        env.checks.side_effect = CredentialCheckError("credential", "Credential not saved: the server refused it")
        r = env.client.put("/api/databases/coco/preview/credential", json={"user": "x", "password": PASSWORD})
        assert r.status_code == 400 and "not kept" in r.json()["detail"] and PASSWORD not in r.text
        assert env.client.get("/api/databases/coco/preview/credential").json()["held"] is False

    def test_forget_and_sign_out_drop_it(self, env):
        _hold(env)
        env.client.delete("/api/databases/coco/preview/credential")
        assert env.client.get("/api/databases/coco/preview/credential").json()["held"] is False
        _hold(env)
        env.client.post("/api/auth/logout")
        assert holder.held_user("dan", "coco") is None

    def test_preview_rows_masks_by_default_and_never_selects_a_masked_column(self, env, tmp_path):
        _hold(env)
        r = _preview(env, limit=20)
        assert r.status_code == 200
        out = r.json()
        assert out["outcome"] == "rows" and out["row_count"] == 3 and out["as_user"] == "dan_ro"
        assert env.spy.asked == [("sales", "orders", ["id"], 20)]            # only the unmasked column was read
        assert env.spy.opened == [("coco", "dan_ro", 5)]
        assert list(out["rows"][0]) == ["id"] and VALUE not in str(out["columns"])
        assert [c["tag"] for c in out["columns"] if c["masked"]] == [
            "masked · email", "masked · not profiled", "masked · not profiled", "masked · undecided"]
        assert out["counts"]["masked"] == 4 and out["kind"] == "table"
        assert out["egeria"] == {"state": "not_built"}

    def test_audit_row_is_written_before_the_rows_and_read_back(self, env):
        _hold(env)
        out = _preview(env).json()
        rec = out["recorded"]
        row = env.registry.get_activity(rec["id"])
        assert row["operation"] == "preview" and rec["at"] == row["ts"] and rec["state"] == "recorded"
        import json
        d = json.loads(row["detail"])
        assert d["who"] == "dan" and d["db_user"] == "dan_ro" and d["table"] == "orders" and d["rows"] == 3
        assert d["masked"] == ["email", "note", "qty", "odd"] and d["revealed"] == []

    def test_reveal_one_column_selects_it_and_records_its_own_row(self, env):
        _hold(env)
        out = _preview(env, reveal=["email"]).json()
        assert env.spy.asked[-1][2] == ["id", "email"]
        assert next(c for c in out["columns"] if c["name"] == "email")["revealed"] is True
        assert out["rows"][0]["email"].startswith(VALUE)
        import json
        d = json.loads(env.registry.get_activity(out["recorded"]["id"])["detail"])
        assert d["action"] == "reveal" and d["revealed"] == ["email"]
        assert len(env.registry.list_activity(operation="preview")) == 1        # a reveal is one row, not two

    def test_a_revealed_column_is_not_remembered_by_the_next_preview(self, env):
        _hold(env)
        _preview(env, reveal=["email"])
        out = _preview(env).json()
        assert env.spy.asked[-1][2] == ["id"] and not any(c["revealed"] for c in out["columns"])

    def test_unknown_reveal_limit_and_table_are_refused_before_any_query(self, env):
        _hold(env)
        assert _preview(env, reveal=["nope"]).status_code == 422
        assert _preview(env, limit=21).status_code == 422
        assert env.client.post("/api/databases/coco/preview",
                               json={"schema": "sales", "table": "x; DROP"}).status_code == 404
        assert env.spy.asked == []

    @pytest.mark.parametrize("exc,outcome", [
        (PreviewDenied("permission denied for table orders"), "no_read"),
        (PreviewTimedOut("no rows shown · the query ran longer than 10 s and was stopped · nothing was read"),
         "timeout"),
    ])
    def test_refusals_keep_their_words_and_are_recorded_as_errors(self, env, exc, outcome):
        _hold(env)
        env.spy.raises = exc
        out = _preview(env).json()
        assert out["outcome"] == outcome and out["sentence"] == exc.sentence and "rows" not in out
        assert env.registry.get_activity(out["recorded"]["id"])["status"] == "error"

    def test_an_empty_table_is_its_own_outcome(self, env):
        _hold(env)
        env.spy.rows = 0
        env.spy.rows = None
        env.spy._preview = None
        env.spy.conn.preview_rows.side_effect = lambda *a, **k: []
        out = _preview(env).json()
        assert out["outcome"] == "empty" and out["row_count"] == 0

    def test_a_view_is_previewable_and_says_what_it_is(self, env):
        _hold(env)
        out = env.client.post("/api/databases/coco/preview", json={"schema": "sales", "table": "v_orders"}).json()
        assert out["kind"] == "view" and out["outcome"] == "rows"

    def test_another_engine_refuses_with_words(self, env, registry):
        registry.register_database(DatabaseEntity(slug="my", display_name="My", db_type="mysql", host="h",
                                                  port=3306, database_name="m"))
        g = env.client.get("/api/databases/my/preview/credential").json()
        assert g["engine_supported"] is False and "PostgreSQL only" in g["unsupported"]
        assert env.client.put("/api/databases/my/preview/credential",
                              json={"user": "u", "password": PASSWORD}).status_code == 409

    def test_if_re_cannot_record_the_rows_are_not_shown(self, env, monkeypatch):
        _hold(env)
        monkeypatch.setattr(ProjectRegistry, "write_activity", lambda self, e: (_ for _ in ()).throw(OSError("disk")))
        r = _preview(env)
        assert r.status_code == 503 and VALUE not in r.text

    def test_a_connect_failure_is_an_outcome_with_the_password_scrubbed(self, env):
        _hold(env)
        env.spy.opener.side_effect = psycopg2.OperationalError(f'FATAL: password authentication failed {PASSWORD}')
        out = _preview(env).json()
        assert out["outcome"] == "credential_refused" and PASSWORD not in str(out)


class TestNothingLeaks:
    def test_credential_and_row_values_reach_no_row_no_log_no_trace(self, env, caplog, tmp_path):
        _hold(env)
        _preview(env, reveal=["email"])
        _preview(env)
        env.client.delete("/api/databases/coco/preview/credential")
        stored = _everything_stored(env.registry, tmp_path)
        assert PASSWORD not in stored and VALUE not in stored
        assert PASSWORD not in caplog.text and VALUE not in caplog.text

    def test_a_validation_error_does_not_echo_the_password(self, env):
        r = env.client.put("/api/databases/coco/preview/credential", json={"user": ["bad"], "password": PASSWORD})
        assert r.status_code == 422 and PASSWORD not in r.text
