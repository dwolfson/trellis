"""Every compile has an id, the id is content-addressed, and turns and feedback
can point at it (context-compilation-design.md §9 replayability, §13 feedback).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from resource_explorer.context_compile import compile_context


class _Registry:
    """Deterministic stand-in. A bare MagicMock is NOT one: every analysis
    reader the compiler consults returns a fresh MagicMock whose repr carries
    its memory address, so two "identical" compiles hash differently for a
    reason that has nothing to do with the compiler. Readers here answer None
    ("nothing stored"), which is what a real registry says for an unknown slug.
    """

    def __init__(self, findings_by_kind):
        self._f = findings_by_kind
        self.record_compile = MagicMock(return_value={"created": True})

    def query_findings(self, slug, kind, *a, **k):
        return self._f.get(kind, [])

    def __getattr__(self, name):
        return lambda *a, **k: None


def _registry(findings_by_kind):
    return _Registry(findings_by_kind)


def _finding(check, label="ok", summary="detail here"):
    return {"check_name": check, "label": label, "summary": summary,
            "surveyed_at": "2026-08-28T00:00:00"}


class TestCompileId:
    def test_same_inputs_same_id_and_it_travels_in_the_manifest(self):
        f = {"license_classification": [_finding("license")]}
        a = compile_context(_registry(f), "x", "q", purposes=["Certify"], budget=4000)
        b = compile_context(_registry(f), "x", "q", purposes=["Certify"], budget=4000)
        assert a.compile_id and a.compile_id == b.compile_id
        assert a.manifest["compile_id"] == a.compile_id

    def test_budget_is_identity_bearing(self):
        f = {"license_classification": [_finding("license")]}
        a = compile_context(_registry(f), "x", "q", purposes=["Certify"], budget=4000)
        b = compile_context(_registry(f), "x", "q", purposes=["Certify"], budget=8000)
        assert a.compile_id != b.compile_id

    def test_different_evidence_different_id(self):
        a = compile_context(_registry({"license_classification": [_finding("license", summary="MIT")]}),
                            "x", "q", purposes=["Certify"], budget=4000)
        b = compile_context(_registry({"license_classification": [_finding("license", summary="GPL")]}),
                            "x", "q", purposes=["Certify"], budget=4000)
        assert a.compile_id != b.compile_id

    def test_provenance_timestamp_does_not_change_identity(self):
        """A re-read of the same stored result later is the same compile."""
        f1 = {"license_classification": [dict(_finding("license"), surveyed_at="2026-08-28T00:00:00")]}
        f2 = {"license_classification": [dict(_finding("license"), surveyed_at="2026-09-08T00:00:00")]}
        a = compile_context(_registry(f1), "x", "q", purposes=["Certify"], budget=4000)
        b = compile_context(_registry(f2), "x", "q", purposes=["Certify"], budget=4000)
        assert a.compile_id == b.compile_id

    def test_compile_is_recorded_with_its_session(self):
        r = _registry({"license_classification": [_finding("license")]})
        c = compile_context(r, "x", "q", purposes=["Certify"], budget=4000, session_id="s-1")
        r.record_compile.assert_called_once()
        args, kwargs = r.record_compile.call_args
        assert args[0] == c.compile_id and args[1] == "x" and args[2] == "q"
        assert kwargs["session_id"] == "s-1"

    def test_a_failed_record_does_not_cost_the_compile(self):
        r = _registry({"license_classification": [_finding("license")]})
        r.record_compile.side_effect = RuntimeError("db away")
        c = compile_context(r, "x", "q", purposes=["Certify"], budget=4000)
        assert c.text and c.compile_id
        # ...but the failure is visible in the manifest, not only in a log:
        # a caller (and the feedback that cites this id) can tell a persisted
        # compile from one that was not recorded.
        assert c.manifest["recorded"] is False
        assert any("compile not recorded" in n for n in c.manifest["notes"])

    def test_a_recorded_compile_says_so(self):
        r = _registry({"license_classification": [_finding("license")]})
        c = compile_context(r, "x", "q", purposes=["Certify"], budget=4000)
        assert c.manifest["recorded"] is True


def _sqlite_registry(tmp_path):
    from resource_explorer.registry import ProjectRegistry
    return ProjectRegistry(database_url=f"sqlite:///{tmp_path}/t.db")


class TestRegistryPersistence:
    def test_record_then_repeat_counts_hits(self, tmp_path):
        reg = _sqlite_registry(tmp_path)
        m = {"compile_id": "abc", "spec_id": "adoption-gate:x", "budget": 4000, "used": 3981,
             "packed": [], "dropped": [], "gaps": [], "notes": []}
        first = reg.record_compile("abc", "x", "is it ready?", m, [{"question": "q"}], session_id="s1")
        again = reg.record_compile("abc", "x", "is it ready?", m, [{"question": "q"}], session_id="s2")
        assert first["created"] is True and again["created"] is False
        row = reg.get_compile("abc")
        assert row["hits"] == 2
        assert row["session_id"] == "s1", "the first writer's session stays on the row"
        assert row["manifest"]["used"] == 3981 and row["derivation"] == [{"question": "q"}]
        assert row["budget"] == 4000 and row["used"] == 3981

    def test_unknown_compile_is_none_not_a_row(self, tmp_path):
        assert _sqlite_registry(tmp_path).get_compile("nope") is None

    def test_turns_carry_the_compile_id(self, tmp_path):
        reg = _sqlite_registry(tmp_path)
        reg.append_turn("sess", "user", "why?", "x", compile_id="abc")
        reg.append_turn("sess", "assistant", "because", "x", compile_id="abc")
        reg.append_turn("sess", "user", "and?", "x")  # no compile behind this one
        with reg._conn() as conn:
            rows = conn.execute(
                "SELECT role, compile_id FROM conversation_history WHERE session_id = ? "
                "ORDER BY turn_idx", ("sess",)).fetchall()
        assert [(r["role"], r["compile_id"]) for r in rows] == [
            ("user", "abc"), ("assistant", "abc"), ("user", None)]

    def test_feedback_carries_the_compile_id(self, tmp_path):
        reg = _sqlite_registry(tmp_path)
        entry = reg.add_resource_feedback("repo", "x", 2, "quality", "wrong evidence", compile_id="abc")
        assert entry["compile_id"] == "abc"
        rows = reg.list_resource_feedback("repo", "x")
        assert rows and rows[0].get("compile_id") == "abc"

    def test_rename_moves_compiles_with_the_resource(self, tmp_path):
        reg = _sqlite_registry(tmp_path)
        m = {"spec_id": "s", "budget": 1, "used": 1}
        reg.record_compile("c1", "old-slug", "q", m, [])
        with reg._conn() as conn:
            conn.execute("UPDATE context_compiles SET project_slug = ? WHERE project_slug = ?",
                         ("new-slug", "old-slug"))
        assert reg.get_compile("c1")["project_slug"] == "new-slug"


class TestMetricsFeedback:
    def test_feedback_records_compile_id_on_the_latest_query_row(self, tmp_path, monkeypatch):
        from resource_explorer.observability.metrics_collector import MetricsCollector
        mc = MetricsCollector(database_url=f"sqlite:///{tmp_path}/metrics.db")
        with mc._conn() as conn:
            conn.execute(
                "INSERT INTO query_log (timestamp, query_hash, intent, project_slug, latency_ms, "
                "cache_hit, response_length) VALUES ('t', 'h1', 'i', 'x', 1, 0, 1)")
        mc.record_feedback("h1", -1, compile_id="abc")
        with mc._conn() as conn:
            row = conn.execute("SELECT feedback, compile_id FROM query_log WHERE query_hash = 'h1'").fetchone()
        assert (row[0], row[1]) == (-1, "abc")
        mc.record_feedback("h1", 1)  # a later vote without an id must not erase the link
        with mc._conn() as conn:
            row = conn.execute("SELECT feedback, compile_id FROM query_log WHERE query_hash = 'h1'").fetchone()
        assert (row[0], row[1]) == (1, "abc")
