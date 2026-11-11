"""B6: restricted specs per user, "Used by", publish and withdraw as the user, the async admin sync,
the honest catalog, and Route B (saved_query) as a spec choice.

Fakes only: no Egeria, no Dr.Egeria --process. The restricted listing's shape is pyegeria's own
(`list_visible_restricted_specs`, pyegeria tests/micro-tests/test_rs_restricted_specs.py), and the
Dr.Egeria envelope is DrEgeriaActionAgent.execute's.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from advisor import egeria_dashboards as ed
from advisor import egeria_spec_publish as pub
from advisor import egeria_spec_restricted as rs
from advisor import egeria_spec_sync as ess

ERIN = {"user_id": "erinoverview", "password": "", "token": "erin-token-1"}
ERIN_OTHER_SESSION = {"user_id": "erinoverview", "password": "", "token": "erin-token-2"}
PETER = {"user_id": "peterprofile", "password": "", "token": "peter-token"}
ADVISOR = pub.ADVISOR_FOLDER


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    rs._reset_for_tests()
    ess._reset_for_tests()
    monkeypatch.setattr(ed, "_connection", lambda creds: _conn(creds))
    yield
    rs._reset_for_tests()
    ess._reset_for_tests()


def _conn(creds):
    if not creds or not creds.get("token"):
        raise ed.SignInRequired("Sign in to see dashboards: they are read from Egeria as you.")
    return {"user_id": creds["user_id"], "token": creds["token"], "platform_url": "https://egeria.test:9443",
            "view_server": "qs-view-server", "user_pwd": ""}


def _restricted_result(user, specs, status="read", reason=None):
    """pyegeria's list_visible_restricted_specs result shape."""
    return {"format": "pyegeria-restricted-specs/1", "identity": user, "status": status, "reason": reason,
            "specs": specs, "folders": [{"folder": ADVISOR, "result": "ok", "detail": None, "count": len(specs)}],
            "notes": []}


FIN = {"label": "Spec-Fin", "qualified_name": "ReportSpec::Spec-Fin", "guid": "g-fin", "version": 2,
       "zones": ["finance"], "folders": [ADVISOR]}


class Reader:
    """Stands in for pyegeria's reader; what each token sees is decided per token (Egeria's zone check)."""

    def __init__(self, by_token):
        self.by_token, self.calls = by_token, []

    def __call__(self, client, folders=None):
        self.calls.append((client["token"], tuple(folders or ())))
        got = self.by_token[client["token"]]
        if isinstance(got, Exception):
            raise got
        return got


def _use_reader(monkeypatch, reader):
    monkeypatch.setattr(rs, "_restricted_reader", lambda: reader)
    monkeypatch.setattr(ed, "_build_client", lambda conn: dict(conn))


# ── restricted specs, per user ─────────────────────────────────────────────────

class TestRestricted:
    def test_not_signed_in_says_so(self):
        out = rs.restricted_specs(None)
        assert out["state"] == "not_signed_in" and out["specs"] == [] and "Sign in" in out["message"]

    def test_older_pyegeria_says_so(self, monkeypatch):
        monkeypatch.setattr(rs, "_restricted_reader", lambda: None)
        out = rs.restricted_specs(ERIN)
        assert out["state"] == "unsupported" and "6.2.35" in out["message"]

    def test_each_user_sees_their_own(self, monkeypatch):
        reader = Reader({"erin-token-1": _restricted_result("erinoverview", [FIN]),
                         "peter-token": _restricted_result("peterprofile", [],
                                                           reason="the folders were read as peterprofile and hold "
                                                                  "no zone-restricted report spec visible to peterprofile")})
        _use_reader(monkeypatch, reader)
        erin, peter = rs.restricted_specs(ERIN), rs.restricted_specs(PETER)
        assert erin["state"] == "ok" and [s["label"] for s in erin["specs"]] == ["Spec-Fin"]
        assert peter["state"] == "none_visible" and peter["specs"] == [] and "peterprofile" in peter["message"]

    def test_cache_is_per_credential_never_per_user_id(self, monkeypatch):
        """Two sessions of one user id can hold different zone grants: never share their cache."""
        reader = Reader({"erin-token-1": _restricted_result("erinoverview", [FIN]),
                         "erin-token-2": _restricted_result("erinoverview", [])})
        _use_reader(monkeypatch, reader)
        assert rs.restricted_specs(ERIN)["specs"] and rs.restricted_specs(ERIN)["cached"] is True
        other = rs.restricted_specs(ERIN_OTHER_SESSION)
        assert other["cached"] is False and other["specs"] == []
        assert [t for t, _ in reader.calls] == ["erin-token-1", "erin-token-2"]

    def test_a_failed_read_is_stated_and_never_cached(self, monkeypatch):
        reader = Reader({"erin-token-1": RuntimeError("HTTP 500 from the view server")})
        _use_reader(monkeypatch, reader)
        out = rs.restricted_specs(ERIN)
        assert out["state"] == "read_failed" and "HTTP 500" in out["message"]
        rs.restricted_specs(ERIN)
        assert len(reader.calls) == 2

    def test_not_read_folders_are_not_an_empty_answer(self, monkeypatch):
        reader = Reader({"erin-token-1": _restricted_result("erinoverview", [], status="not read",
                                                            reason="no folder could be read: x: folder not found")})
        _use_reader(monkeypatch, reader)
        out = rs.restricted_specs(ERIN)
        assert out["state"] == "read_failed" and "not read" in out["message"]

    def test_a_refused_token_is_sign_in_again(self, monkeypatch):
        from pyegeria.core._exceptions import PyegeriaUnauthorizedException
        exc = PyegeriaUnauthorizedException.__new__(PyegeriaUnauthorizedException)
        Exception.__init__(exc, "401 token expired")
        exc.related_http_code = 401
        _use_reader(monkeypatch, Reader({"erin-token-1": exc}))
        with pytest.raises(ed.TokenRefused):
            rs.restricted_specs(ERIN)

    def test_nothing_restricted_reaches_the_shared_registry(self, monkeypatch):
        from pyegeria.view.base_report_formats import get_report_registry
        _use_reader(monkeypatch, Reader({"erin-token-1": _restricted_result("erinoverview", [FIN])}))
        rs.restricted_specs(ERIN)
        assert get_report_registry().get("Spec-Fin") is None


class TestUsedBy:
    def test_older_pyegeria_says_so(self, monkeypatch):
        import pyegeria.view.egeria_spec_cache as esc
        monkeypatch.delattr(esc, "read_consumer_index", raising=False)
        out = rs.used_by_index()
        assert out["state"] == "unsupported" and out["index"] == {}

    def test_not_read_is_never_used_by_none(self, monkeypatch):
        import pyegeria.view.egeria_spec_cache as esc
        monkeypatch.setattr(esc, "read_consumer_index", lambda **k: {
            "status": "not read", "consumers": [], "index": {}, "reason": "no consumer index yet"}, raising=False)
        out = rs.used_by_index()
        assert out["state"] == "not_read" and "no consumer index yet" in out["message"]

    def test_the_index_is_passed_through(self, monkeypatch):
        import pyegeria.view.egeria_spec_cache as esc
        monkeypatch.setattr(esc, "read_consumer_index", lambda **k: {
            "status": "read", "consumers": [ADVISOR, "ReportSpecFolder::Consumer::Portal"],
            "index": {"Spec-A": [ADVISOR, "ReportSpecFolder::Consumer::Portal"]}}, raising=False)
        out = rs.used_by_index()
        assert out["state"] == "ok" and out["index"]["Spec-A"][1].endswith("Portal") and out["message"] is None


# ── publish and withdraw ───────────────────────────────────────────────────────

class FakeAgent:
    def __init__(self, success=True):
        self.calls, self.success = [], success

    def execute(self, markdown, directive="process", dry_run=False, egeria_credentials=None, service_operation=False):
        self.calls.append({"markdown": markdown, "directive": directive, "creds": egeria_credentials,
                           "service": service_operation})
        return json.dumps({"success": self.success, "output": "", "validation_errors": [], "execution_errors": [],
                           "commands_total": 2, "commands_succeeded": 2 if self.success else 0,
                           "commands_failed": 0 if self.success else 2, "commands_detail": []})


SPEC_MD = """
## Create Report Spec
### Heading
My Glossaries
### Description
Glossaries I care about.
### Action Function
GlossaryManager.find_glossaries
### Required Params
search_string

## Create Column
### Name
Name
### Key
display_name
"""


@pytest.fixture
def my_spec(monkeypatch):
    import pyegeria.view.base_report_formats as brf
    from advisor.report_spec_parser import parse_report_spec_markdown, register_report_spec
    register_report_spec("b6-my-glossaries", parse_report_spec_markdown(SPEC_MD))
    monkeypatch.setattr(rs, "_restricted_reader", lambda: None)  # nothing held, restricted unknown
    yield "b6-my-glossaries"
    brf.unregister_report_spec("b6-my-glossaries")


@pytest.fixture
def sync_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(ess, "start_sync", lambda **k: calls.append(1) or {"message": "Syncing report specs."})
    return calls


class TestPublish:
    def test_preview_is_the_document_and_sends_nothing(self, my_spec):
        agent = FakeAgent()
        out = pub.publish(ERIN, my_spec, step="preview", agent=agent)
        md = out["markdown"]
        assert agent.calls == [] and out["verb"] == "Create" and out["visibility"] == "public"
        assert "## Create Report Spec" in md and "### Display Name\nb6-my-glossaries" in md
        assert "### Qualified Name\nReportSpec::b6-my-glossaries" in md
        assert '"function":"GlossaryManager.find_glossaries"' in md  # the microflow
        assert "Zone Membership" not in md and "Parent ID" not in md
        assert md.count("## Add Member to Collection") == 1 and f"### Collection Id\n{ADVISOR}" in md

    def test_restricted_carries_zones_and_portal_is_optional(self, my_spec):
        out = pub.publish(ERIN, my_spec, step="preview", visibility="restricted", zones=["finance", "hr"],
                          also_portal=True, agent=FakeAgent())
        assert "### Zone Membership\nfinance, hr" in out["markdown"]
        assert out["folders"] == [ADVISOR, pub.PORTAL_FOLDER] and out["markdown"].count("Add Member") == 2

    def test_republish_is_an_update_and_never_a_parent_id(self, my_spec, monkeypatch):
        monkeypatch.setattr(pub, "held_in_egeria", lambda creds, label: {"held": True, "zones": [], "how": "held"})
        md = pub.publish(ERIN, my_spec, step="preview", agent=FakeAgent())["markdown"]
        assert "## Update Report Spec" in md and "Create Report Spec" not in md and "Parent ID" not in md

    def test_restricted_made_public_removes_its_zones(self, my_spec, monkeypatch):
        monkeypatch.setattr(pub, "held_in_egeria", lambda c, l: {"held": True, "zones": ["finance"], "how": "held"})
        out = pub.publish(ERIN, my_spec, step="preview", agent=FakeAgent())
        assert "## Declassify Zone Membership\n### Target Element\nReportSpec::b6-my-glossaries" in out["markdown"]
        assert any("remove its zones (finance)" in s for s in out["steps"])

    def test_validate_runs_as_the_user(self, my_spec):
        agent = FakeAgent()
        out = pub.publish(ERIN, my_spec, step="validate", agent=agent)
        [call] = agent.calls
        assert call["directive"] == "validate" and call["creds"] == ERIN and call["service"] is False
        assert out["result"]["success"] is True

    def test_process_needs_confirm_and_the_previewed_document(self, my_spec, sync_calls):
        agent = FakeAgent()
        digest = pub.publish(ERIN, my_spec, step="preview", agent=agent)["digest"]
        with pytest.raises(pub.PublishRefused, match="Confirm first"):
            pub.publish(ERIN, my_spec, step="process", digest=digest, agent=agent)
        with pytest.raises(pub.PublishRefused, match="changed since you previewed"):
            pub.publish(ERIN, my_spec, step="process", confirmed=True, digest="stale", agent=agent)
        assert agent.calls == [] and sync_calls == []
        out = pub.publish(ERIN, my_spec, step="process", confirmed=True, digest=digest, agent=agent)
        [call] = agent.calls
        assert call["directive"] == "process" and call["creds"] == ERIN
        assert out["after"]["started"] is True and sync_calls == [1]

    def test_a_failed_process_starts_no_sync(self, my_spec, sync_calls):
        agent = FakeAgent(success=False)
        digest = pub.publish(ERIN, my_spec, step="preview", agent=agent)["digest"]
        out = pub.publish(ERIN, my_spec, step="process", confirmed=True, digest=digest, agent=agent)
        assert out["result"]["success"] is False and "after" not in out and sync_calls == []

    @pytest.mark.parametrize("kw, words", [
        ({"visibility": "restricted"}, "at least one zone"),
        ({"visibility": "public", "zones": ["finance"]}, "carries no zones"),
        ({"visibility": "restricted", "zones": ["bad\nzone"]}, "Not a zone name"),
        ({"visibility": "secret"}, "Visibility must be"),
    ])
    def test_bad_visibility_is_refused_with_words(self, my_spec, kw, words):
        with pytest.raises(pub.PublishRefused, match=words):
            pub.publish(ERIN, my_spec, step="preview", agent=FakeAgent(), **kw)

    def test_a_builtin_spec_is_not_published(self):
        with pytest.raises(pub.PublishRefused, match="builtin spec, not one of yours"):
            pub.publish(ERIN, "Collections", step="preview", agent=FakeAgent())

    def test_unknown_spec_is_refused(self):
        with pytest.raises(pub.PublishRefused, match="No report spec named"):
            pub.publish(ERIN, "no-such-spec-b6", step="preview", agent=FakeAgent())


class TestWithdraw:
    def test_removes_membership_from_each_folder_only(self, sync_calls):
        agent = FakeAgent()
        prev = pub.withdraw(ERIN, "Spec-Fin", folders=[ADVISOR, pub.PORTAL_FOLDER], agent=agent)
        md = prev["markdown"]
        assert md.count("## Remove Member from Collection") == 2 and "Delete" not in md and agent.calls == []
        out = pub.withdraw(ERIN, "Spec-Fin", step="process", folders=[ADVISOR, pub.PORTAL_FOLDER],
                           confirmed=True, digest=prev["digest"], agent=agent)
        assert agent.calls[0]["creds"] == ERIN and out["after"]["started"] and sync_calls == [1]

    def test_only_consumer_folders(self):
        with pytest.raises(pub.PublishRefused, match="consumer folders only"):
            pub.withdraw(ERIN, "Spec-Fin", folders=["ReportSpecFolder::scratch"], agent=FakeAgent())


# ── the async admin sync (G2) ──────────────────────────────────────────────────

class TestAsyncSync:
    def test_start_returns_at_once_and_one_at_a_time(self, monkeypatch):
        gate, done = threading.Event(), threading.Event()

        def slow_sync(**kw):
            gate.wait(5)
            with ess._lock:
                ess._state.update(state="ok", finished_at=ess._now(), report={"skipped": []}, identity="svc")
            done.set()
            return ess.egeria_held_status()

        monkeypatch.setattr(ess, "sync_now", slow_sync)
        st = ess.start_sync()
        assert st["running"] is True and "Syncing report specs" in st["message"]
        with pytest.raises(ess.SyncBusy, match="already running"):
            ess.start_sync()
        from advisor.web.reports import start_spec_sync
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            asyncio.run(start_spec_sync())
        assert ei.value.status_code == 409
        gate.set()
        assert done.wait(5)
        assert ess.sync_status()["running"] is False

    def test_admin_action_starts_it_in_the_background(self, monkeypatch):
        monkeypatch.setattr(ess, "start_sync", lambda: {"message": "Syncing report specs from Egeria (started x).",
                                                        "running": True})
        from advisor.web.admin import maintenance_action
        out = asyncio.run(maintenance_action("sync_specs"))
        assert out["status"] == "ok" and out["status_url"] == "/api/admin/specs/sync" and out["sync"]["running"]


# ── the catalog says what it left out (A-P hand-off) ───────────────────────────

class TestCatalogStatus:
    def test_unrunnable_specs_are_listed_with_their_reason(self, monkeypatch):
        from advisor.web import shared
        real = shared._registry_status()
        name = next(n for n, r in real.items() if r.get("runnable"))
        fake = dict(real)
        fake[name] = {"name": name, "runnable": False, "unrunnable_reason": "its find method is gone"}
        monkeypatch.setattr(shared, "_registry_status", lambda: fake)
        catalog, st = shared._load_report_catalog_with_status(include_dre=True)
        assert name not in {n for v in catalog.values() for n in v}
        assert {"name": name, "reason": "its find method is gone"} in st["unrunnable"] and st["message"]

    def test_format_only_specs_are_counted_not_called_unrunnable(self):
        from advisor.web import shared
        _, st = shared._load_report_catalog_with_status(include_dre=True)
        assert st["format_only"] > 0
        assert not any("no action" in (u["reason"] or "") for u in st["unrunnable"])

    def test_registry_unavailable_falls_back_and_says_so(self, monkeypatch, tmp_path):
        from advisor.web import shared

        def boom():
            raise RuntimeError("registry exploded")

        f = tmp_path / "specs.json"
        f.write_text(json.dumps({"Bundled-Only-Spec": {}}))
        monkeypatch.setattr(shared, "_registry_status", boom)
        monkeypatch.setattr(shared, "_SPEC_FILES", [f])
        catalog, st = shared._load_report_catalog_with_status()
        assert st["registry"] == "unavailable" and st["bundled_only"] == ["Bundled-Only-Spec"]
        assert "registry exploded" in st["message"] and "bundled" in st["message"]
        assert "Bundled-Only-Spec" in {n for v in catalog.values() for n in v}


# ── Route B: saved_query as a spec choice ──────────────────────────────────────

class TestSavedQuery:
    def test_shape_is_checked_with_words(self):
        from advisor.spec_saved_query import check_saved_query
        with pytest.raises(ValueError, match="qualifiedName"):
            check_saved_query({"mode": "cached"})
        with pytest.raises(ValueError, match="mode must be"):
            check_saved_query({"name": "q", "mode": "sometimes"})
        with pytest.raises(ValueError, match="output must be"):
            check_saved_query({"name": "q", "output": "chart"})
        with pytest.raises(ValueError, match="a value is a string"):
            check_saved_query({"name": "q", "params": {"x": {"nested": 1}}})
        assert check_saved_query({"name": " q "}) == {"name": "q", "mode": "cached", "output": "count", "params": {}}

    def test_builder_spec_round_trips_to_an_analytic_saved_query(self):
        from advisor.agents.report_spec_elicitor import get_report_spec_elicitor
        from advisor.report_spec_parser import parse_report_spec_markdown
        from advisor.spec_saved_query import check_saved_query
        sq = check_saved_query({"name": "SavedQuery::open-projects", "mode": "live", "output": "list",
                                "params": {"status": "ACTIVE", "tags": ["a", "b"]}})
        md = get_report_spec_elicitor()._generate_report_spec_md(
            {"answers": {"Heading": "Open projects"}, "columns": [], "saved_query": sq,
             "action_function": "GlossaryManager.find_glossaries"})
        assert "### Action Function" not in md  # the saved query replaces the find method
        fs = parse_report_spec_markdown(md)
        assert fs.action.analytic_function == "saved_query" and not fs.action.function
        assert fs.action.analytic_spec_params == {"name": "SavedQuery::open-projects", "mode": "live",
                                                  "output": "list", "params": {"status": "ACTIVE", "tags": ["a", "b"]}}

    def test_spec_params_keep_an_apostrophe_and_a_json_object(self):
        from advisor.report_spec_parser import _parse_spec_params
        got = _parse_spec_params("search_string=Dan's\npage_size=100\nparams={\"y\": \"a,b\"}\nzones=['a', 'b']")
        assert got == {"search_string": "Dan's", "page_size": 100, "params": {"y": "a,b"}, "zones": ["a", "b"]}


# ── schema discovery says which of its causes it hit (A-P P2 hand-off) ─────────

class TestSchemaDiscovery:
    DRAFT = {"draft_id": "d1", "columns": [], "answers": {"Heading": "H"}, "action_function": "X.find_x"}
    CONN = {"view_server": "v", "platform_url": "https://p:9443", "user_id": "erinoverview", "user_pwd": "",
            "token": "erin-token-1"}

    @pytest.fixture
    def env(self, monkeypatch):
        import types
        import advisor.report_draft as rd
        import advisor.report_spec_parser as rsp
        import advisor.agents.report_spec_elicitor as rse
        import advisor.report_pipeline as rp
        import pyegeria.egeria_tech_client as etc
        from advisor.web import reports
        reports._SCHEMA_CACHE.clear()
        state = {"draft": dict(self.DRAFT), "conn": dict(self.CONN), "schema": [{"attribute_path": "displayName"}],
                 "parse": lambda md: object(), "conn_error": None, "client_error": None}
        monkeypatch.setattr(rd, "resolve_report_draft", lambda *a, **k: ("ns", state["draft"]) if state["draft"] else None)
        monkeypatch.setattr(rse, "get_report_spec_elicitor",
                            lambda: types.SimpleNamespace(_generate_report_spec_md=lambda d: "md"))
        monkeypatch.setattr(rsp, "parse_report_spec_markdown", lambda md: state["parse"](md))
        monkeypatch.setattr(rsp, "register_report_spec", lambda *a, **k: None)

        def read_conn(egeria_credentials=None):
            if state["conn_error"]:
                raise state["conn_error"]
            return dict(state["conn"])
        monkeypatch.setattr(rp, "get_report_pipeline", lambda: types.SimpleNamespace(_read_pyegeria_connection=read_conn))

        class Client:
            def __init__(self, **kw):
                if state["client_error"]:
                    raise state["client_error"]

            def set_bearer_token(self, t):
                pass

            def get_report_spec_schema(self, **kw):
                return state["schema"]
        monkeypatch.setattr(etc, "EgeriaTech", Client)
        return reports, state

    def _ask(self, reports):
        return asyncio.run(reports.discover_draft_schema_with_status("d1", egeria_credentials=ERIN))

    def test_ok(self, env):
        reports, _ = env
        out = self._ask(reports)
        assert out == {"state": "ok", "attributes": [{"attribute_path": "displayName"}], "message": None}

    @pytest.mark.parametrize("setup, state, words", [
        (lambda s: s.update(draft=None), "draft_not_found", "was not found"),
        (lambda s: s.update(parse=lambda md: (_ for _ in ()).throw(ValueError("no heading"))), "spec_invalid", "no heading"),
        (lambda s: s.update(conn_error=OSError("mcp_servers.json unreadable")), "connection_unreadable", "unreadable"),
        (lambda s: s["conn"].update(view_server=""), "connection_incomplete", "not configured"),
        (lambda s: s.update(client_error=ConnectionError("refused")), "discovery_failed", "refused"),
        (lambda s: s.update(schema=[{"attribute_path": "Error", "data_type": "HTTP 500"}]), "discovery_failed", "HTTP 500"),
        (lambda s: s.update(schema=[{"attribute_path": "Info", "data_type": "no data"}]), "empty", "no sample elements"),
        (lambda s: s.update(schema=[]), "empty", "no sample elements"),
    ], ids=["draft", "spec", "conn-unreadable", "conn-incomplete", "egeria-error", "egeria-error-row",
            "info-row", "nothing"])
    def test_each_cause_has_its_sentence_not_an_empty_list(self, env, setup, state, words):
        reports, st = env
        setup(st)
        out = self._ask(reports)
        assert out["state"] == state and out["attributes"] == [] and words in out["message"]

    def test_the_route_hands_the_sentence_to_the_canvas(self, env, monkeypatch):
        reports, st = env
        st.update(draft=None)
        monkeypatch.setattr("advisor.auth.require_egeria_user", lambda request: {"user_id": "erinoverview"})
        monkeypatch.setattr("advisor.auth.get_egeria_credentials", lambda request: ERIN)
        [row] = asyncio.run(reports.get_report_draft_schema(object(), "d1"))
        assert row["attribute_path"] == "Error" and "was not found" in row["data_type"]


# ── the docs list says why it is empty, and which documents cannot run ─────────

class TestDocsList:
    @pytest.fixture
    def docs(self, monkeypatch, tmp_path):
        import types
        import advisor.report_spec_docs as rsd
        import advisor.report_draft as rd
        good, bad = tmp_path / "b6-good-doc.md", tmp_path / "b6-bad-doc.md"
        good.write_text(SPEC_MD)
        bad.write_text("not a report spec at all")
        st = {"inbox": [{"doc_id": "b6-good-doc", "path": str(good)}, {"doc_id": "b6-bad-doc", "path": str(bad)}],
              "outbox": [], "trash_error": PermissionError("trash folder not readable")}

        def trash(**k):
            raise st["trash_error"]
        dm = types.SimpleNamespace(list_inbox=lambda **k: [dict(e) for e in st["inbox"]],
                                   list_outbox=lambda **k: list(st["outbox"]), list_trash=trash)
        monkeypatch.setattr(rsd, "get_report_spec_doc_manager", lambda: dm)
        monkeypatch.setattr(rd, "list_visible_report_drafts", lambda **k: [])
        monkeypatch.setattr("advisor.auth.get_current_user", lambda request: None)
        yield st
        import pyegeria.view.base_report_formats as brf
        brf.unregister_report_spec("b6-good-doc")
        brf.unregister_report_spec("b6-bad-doc")

    def test_empty_unreadable_and_unrunnable_are_said(self, docs, monkeypatch):
        from advisor.web.reports import list_report_docs
        import advisor.report_spec_parser as rsp

        real = rsp.parse_report_spec_markdown

        def parse(md):
            if md.startswith("not a report spec"):
                raise ValueError("no Create Report Spec command")
            return real(md)
        monkeypatch.setattr(rsp, "parse_report_spec_markdown", parse)
        out = asyncio.run(list_report_docs(object()))
        assert "No executed reports here yet" in out["messages"]["outbox"] and "sign in" in out["messages"]["outbox"]
        assert "trash could not be read" in out["messages"]["trash"] and out["trash"] == []
        rows = {e["doc_id"]: e for e in out["inbox"]}
        assert rows["b6-good-doc"]["registered"] is True
        assert rows["b6-bad-doc"]["registered"] is False
        assert "no Create Report Spec command" in rows["b6-bad-doc"]["not_runnable_reason"]
