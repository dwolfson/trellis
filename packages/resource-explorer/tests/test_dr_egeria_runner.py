"""The ad-hoc Dr.Egeria document runner (owner, 2026-10-14: "load Dr.Egeria commands - sometimes adhoc").

The runner reuses the bootstrap's processor (`bootstrap.run_dr_egeria_document`, the `dr_egeria` CLI in a
subprocess), so the process boundary is faked at `bootstrap.subprocess.run` with the summary table the CLI
prints. The pyegeria steps (engine, service, SupportedGovernanceService link) talk to Egeria only through pyegeria:
those clients are `create_autospec(<real class>, spec_set=True)` installed at the one constructor seam
(`egeria_clients._build`). The registry is a real temp SQLite registry.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from resource_explorer.registry import ProjectRegistry

DAEMON = "resourceexplorernpa"
ENGINE_GUID = "0a1b2c3d-0000-4000-8000-00000000e001"
SERVICE_GUID = "0a1b2c3d-0000-4000-8000-00000000f001"
LINK_GUID = "0a1b2c3d-0000-4000-8000-00000000a001"

DOC = """<!-- a test declaration -->

## Create Governance Action Type
### Display Name
Resource Explorer Survey — db_derived

### Qualified Name
ResourceExplorerSurvey::re-db-derived

### Description
Zero-fetch derivation over already-stored rows.

___

## Link Action to Action Executor
### Governance Action Type
ResourceExplorerSurvey::re-db-derived

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-db-derived

___
"""

STEPS = {
    "steps": [
        {"command": "Create Survey Action Engine", "qualified_name": "ResourceExplorerSurvey",
         "display_name": "Resource Explorer Survey Engine", "description": "Hosted by RE's worker."},
        {"command": "Create Survey Action Service",
         "qualified_name": "SurveyActionService::ResourceExplorerSurvey::db_derived",
         "display_name": "Resource Explorer Survey — db_derived", "description": "db_derived"},
        {"command": "Link Supported Governance Service", "governance_engine": "ResourceExplorerSurvey",
         "governance_service": "SurveyActionService::ResourceExplorerSurvey::db_derived",
         "request_type": "re-db-derived", "service_request_type": "re-db-derived"},
    ]
}


def _summary(rows: list[tuple[str, str, str, str, str]], errors: dict[str, list[str]] | None = None) -> str:
    """What `dr_egeria --process --summary-only` prints: the errors section, then the summary table, rendered
    with rich exactly as md_processing.dr_egeria.process_md_file_v2 builds it (same box, same columns)."""
    from rich.box import Box
    from rich.console import Console
    from rich.table import Table

    dotted = Box("┏━┳┓\n┃ ┃┃\n┡━╇┩\n│ ││\n├·┼┤\n├─┼┤\n│ ││\n└─┴┘\n")
    buf = io.StringIO()
    console = Console(width=int(os.environ.get("EGERIA_WIDTH", "4000")), file=buf)
    if errors:
        console.print("[bold red]Processing Errors:[/bold red]\n")
        for header, lines in errors.items():
            console.print(f"[red]-- {header} --[/red]")
            for e in lines:
                console.print(f"   [red]- {e}[/red]")
        console.print("\n")
    table = Table(title="Dr. Egeria v2 Processing Summary", show_header=True, show_lines=True, box=dotted)
    for col in ("Markdown Command", "Canonical Command", "Status", "Found", "Display Name / End 1",
                "Qualified Name / End2", "Message"):
        table.add_column(col, overflow="fold")
    for command, status, name, qn, message in rows:
        table.add_row(command, command, status, "No", name, qn, message)
    console.print(table)
    return buf.getvalue()


OK_OUTPUT_ROWS = [
    ("Create Governance Action Type", "SUCCESS", "Resource Explorer Survey — db_derived",
     "ResourceExplorerSurvey::re-db-derived", "Created Governance Action Type"),
    ("Link Action to Action Executor", "SUCCESS", "", "", "Linked Action to Action Executor"),
]


@pytest.fixture
def root(tmp_path, monkeypatch):
    docs = tmp_path / "dr-egeria"
    (docs / "engine-host").mkdir(parents=True)
    (docs / "engine-host" / "decl.md").write_text(DOC)
    (docs / "engine-host" / "decl.pyegeria-steps.json").write_text(json.dumps(STEPS))
    (docs / "plain").mkdir()
    (docs / "plain" / "only.md").write_text(DOC)
    monkeypatch.setenv("RE_DR_EGERIA_DOCS_DIR", str(docs))
    monkeypatch.setenv("EGERIA_USER_ID", DAEMON)
    monkeypatch.setenv("EGERIA_USER_PASSWORD", "daemon-secret")
    monkeypatch.setenv("EGERIA_USER", "someone-else")          # what an inherited env would have run as
    return docs


@pytest.fixture
def reg(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "runner.db"))


class Fakes:
    """The pyegeria boundary plus the dr_egeria process boundary, recording one ordered call log."""

    def __init__(self, monkeypatch, *, output: str | None = None, engine_exists=False, service_exists=False,
                 link_exists=False):
        from pyegeria import AssetMaker, MetadataExpert

        from resource_explorer import bootstrap, egeria_clients

        self.calls: list[str] = []
        self.built: list[tuple[str, str]] = []
        self.subprocess_envs: list[dict] = []
        self.output = output if output is not None else _summary(OK_OUTPUT_ROWS)
        self.expert = create_autospec(MetadataExpert, spec_set=True, instance=True)
        self.maker = create_autospec(AssetMaker, spec_set=True, instance=True)
        known = {}
        if engine_exists:
            known["ResourceExplorerSurvey"] = ENGINE_GUID
        if service_exists:
            known["SurveyActionService::ResourceExplorerSurvey::db_derived"] = SERVICE_GUID
        self.known = known

        def by_name(name=None, property_name="qualifiedName", as_of_time=None, body=None, **kwargs):
            self.calls.append(f"find {name}")
            return self.known.get(name, "No element found")

        def create_capability(body=None):
            self.calls.append("create engine")
            self.known[body["properties"]["qualifiedName"]] = ENGINE_GUID
            return ENGINE_GUID

        def create_asset(asset_type=None, body=None):
            self.calls.append("create service")
            self.known[body["properties"]["qualifiedName"]] = SERVICE_GUID
            return SERVICE_GUID

        def related(guid, relationship_type, body, for_lineage=None, for_duplicate_processing=None,
                    starting_at_end=0, start_from=0, page_size=500, timeout=30, mermaid_only=False, **kwargs):
            self.calls.append(f"related {relationship_type}")
            if link_exists and (body or {}).get("startFrom", 0) == 0:
                return {"elementList": [{
                    "type": {"typeName": "SupportedGovernanceService"},
                    "element": {"elementGUID": SERVICE_GUID},
                    "relationshipProperties": {"propertyValueMap": {
                        "requestType": {"primitiveValue": "re-db-derived"}}}}]}
            return "No elements found"

        def link(governance_engine_guid, governance_service_guid, body=None):
            self.calls.append("link supported service")
            self.link_body = body
            return LINK_GUID

        self.expert.get_metadata_guid_by_unique_name.side_effect = by_name
        self.expert.get_related_metadata_elements.side_effect = related
        self.maker.create_software_capability.side_effect = create_capability
        self.maker.create_asset.side_effect = create_asset
        self.maker.link_supported_governance_service.side_effect = link
        self.expert.create_egeria_bearer_token.return_value = "tok"
        self.maker.create_egeria_bearer_token.return_value = "tok"
        by_cls = {MetadataExpert: self.expert, AssetMaker: self.maker}

        def build(cls, view_server, platform_url, user_id, password):
            self.built.append((cls.__name__, user_id))
            return by_cls[cls]

        monkeypatch.setattr(egeria_clients, "_build", build)

        real_run = bootstrap.subprocess.run      # the stdlib module: `ps` (process_identity) must still work

        def fake_run(argv, **kwargs):
            if argv[0] != "/venv/bin/dr_egeria":
                return real_run(argv, **kwargs)
            self.calls.append("dr_egeria " + " ".join(a for a in argv[1:] if not a.startswith("/")))
            self.subprocess_envs.append(dict(kwargs.get("env") or {}))
            return SimpleNamespace(returncode=0, stdout=self.output, stderr="")

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
        monkeypatch.setattr(bootstrap, "_resolve_dr_egeria_executable", lambda: "/venv/bin/dr_egeria")

    def writes(self) -> list[str]:
        return [c for c in self.calls if not c.startswith(("find ", "related "))]


def _rows(reg) -> list[dict]:
    return reg.list_activity(operation="dr_egeria")


# ── dry run ─────────────────────────────────────────────────────────────────

def test_dry_run_builds_no_client_runs_nothing_and_writes_no_row(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch)
    out = runner.run_document("engine-host/decl.md", dry_run=True, registry=reg)

    assert fakes.calls == [] and fakes.built == [], "a dry run makes no Egeria call and starts no dr_egeria"
    assert _rows(reg) == []
    assert out["status"] == "planned" and out["dry_run"] is True
    assert [c["command"] for c in out["commands"]] == [
        "Create Survey Action Engine", "Create Survey Action Service", "Link Supported Governance Service",
        "Create Governance Action Type", "Link Action to Action Executor"]
    assert out["not_safe_to_repeat"] == ["Link Action to Action Executor"]
    assert all(c["status"] == "planned" for c in out["commands"])


def test_dry_run_reports_an_unknown_command_as_invalid(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    (root / "plain" / "bad.md").write_text("## Create Frobnicator Thing\n### Display Name\nx\n")
    Fakes(monkeypatch)
    out = runner.run_document("plain/bad.md", dry_run=True, registry=reg)
    assert out["valid"] is False and any("Frobnicator" in e for e in out["errors"])
    with pytest.raises(runner.DocumentRefused):
        runner.run_document("plain/bad.md", registry=reg)
    assert _rows(reg) == []


def test_a_destructive_command_is_refused(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    (root / "plain" / "del.md").write_text("## Delete Glossary Term\n### Qualified Name\nx\n")
    fakes = Fakes(monkeypatch)
    with pytest.raises(runner.DocumentRefused, match="owner"):
        runner.run_document("plain/del.md", registry=reg)
    assert fakes.calls == []


# ── logging ─────────────────────────────────────────────────────────────────

def test_a_run_writes_the_running_row_first_then_a_terminal_row_with_per_command_results(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner
    from resource_explorer.run_reconciler import process_identity

    fakes = Fakes(monkeypatch)
    written = []
    real_write = reg.write_activity

    def spy(entry):
        written.append((entry.status, json.loads(entry.detail or "{}"), list(entry.items), list(fakes.calls)))
        return real_write(entry)

    monkeypatch.setattr(reg, "write_activity", spy)
    out = runner.run_document("engine-host/decl.md", registry=reg)

    first_status, first_detail, _items, calls_before = written[0]
    assert first_status == "running" and calls_before == [], "the running row is written before any work"
    assert first_detail["_runner"]["pid"] == process_identity()["pid"]
    assert first_detail["sha256"] and first_detail["document"] == "engine-host/decl.md"

    row = _rows(reg)[0]
    assert row["status"] == "ok" and row["id"] == out["activity_id"]
    assert "_runner" not in json.loads(row["detail"])
    items = row["items"]
    assert [(i["command"], i["status"]) for i in items] == [
        ("Create Survey Action Engine", "ok"), ("Create Survey Action Service", "ok"),
        ("Link Supported Governance Service", "ok"), ("Create Governance Action Type", "ok"),
        ("Link Action to Action Executor", "ok")]
    assert items[0]["element"] == "ResourceExplorerSurvey" and items[0]["outcome"] == "created"
    assert items[3]["element"] == "ResourceExplorerSurvey::re-db-derived"
    # Status words come from the persisted row.
    assert out["status"] == row["status"] and out["commands"] == items


def test_a_failing_command_is_recorded_with_its_error_words(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    output = _summary(
        [OK_OUTPUT_ROWS[0],
         ("Link Action to Action Executor", "FAILURE", "", "", "Execution failed: engine not found")],
        errors={"Link Action to Action Executor ()": ["Governance Engine ResourceExplorerSurvey not found"]})
    Fakes(monkeypatch, output=output)
    out = runner.run_document("plain/only.md", registry=reg)

    row = _rows(reg)[0]
    assert row["status"] == "error" and out["status"] == "error"
    last = row["items"][-1]
    assert last["command"] == "Link Action to Action Executor" and last["status"] == "error"
    assert "engine not found" in last["error"]
    assert "ResourceExplorerSurvey not found" in last["error"]


def test_output_that_cannot_be_read_is_unknown_never_ok(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    Fakes(monkeypatch, output="Traceback (most recent call last):\n  boom\n")
    out = runner.run_document("plain/only.md", registry=reg)
    row = _rows(reg)[0]
    assert row["status"] == "error" and out["status"] == "error"
    assert {i["status"] for i in row["items"]} == {"unknown"}



def test_a_summary_that_does_not_line_up_with_the_commands_is_unknown(root, reg, monkeypatch):
    """One SUCCESS row for a two-command document: which command it belongs to is not known, so neither is ok."""
    from resource_explorer import dr_egeria_runner as runner

    Fakes(monkeypatch, output=_summary(OK_OUTPUT_ROWS[:1]))
    runner.run_document("plain/only.md", registry=reg)
    row = _rows(reg)[0]
    assert row["status"] == "error"
    assert [i["status"] for i in row["items"]] == ["unknown", "unknown"]
    assert "1 row(s) for 2 command(s)" in row["items"][0]["error"]

def test_a_failed_pyegeria_step_stops_the_run_before_dr_egeria(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch)
    fakes.maker.create_asset.side_effect = RuntimeError("Egeria said no")
    runner.run_document("engine-host/decl.md", registry=reg)
    row = _rows(reg)[0]
    assert row["status"] == "error"
    statuses = [(i["command"], i["status"]) for i in row["items"]]
    assert statuses[1] == ("Create Survey Action Service", "error")
    assert "Egeria said no" in row["items"][1]["error"]
    assert [s for _c, s in statuses[2:]] == ["not_run"] * 3
    assert not any(c.startswith("dr_egeria") for c in fakes.calls)


# ── repeats ─────────────────────────────────────────────────────────────────

def test_a_second_run_of_the_same_document_is_refused_without_force(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch)
    first = runner.run_document("engine-host/decl.md", registry=reg)
    n = len(fakes.calls)
    with pytest.raises(runner.RepeatRefused) as refused:
        runner.run_document("engine-host/decl.md", registry=reg)
    assert first["activity_id"] in str(refused.value)
    assert "Link Action to Action Executor" in str(refused.value)
    assert len(fakes.calls) == n and len(_rows(reg)) == 1, "a refused repeat touches nothing"

    again = runner.run_document("engine-host/decl.md", force=True, registry=reg)
    assert again["status"] == "ok" and len(_rows(reg)) == 2


def test_a_changed_document_is_a_new_document(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    Fakes(monkeypatch)
    runner.run_document("plain/only.md", registry=reg)
    (root / "plain" / "only.md").write_text(DOC.replace("Zero-fetch", "Zero fetch"))
    assert runner.run_document("plain/only.md", registry=reg)["status"] == "ok"


def test_an_interrupted_run_still_counts_as_applied(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    Fakes(monkeypatch)
    out = runner.run_document("plain/only.md", registry=reg)
    reg.update_activity_status(out["activity_id"], "interrupted")
    with pytest.raises(runner.RepeatRefused):
        runner.run_document("plain/only.md", registry=reg)


# ── path ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.md", "engine-host/../../outside.md",
                                 "engine-host/decl.pyegeria-steps.json", "missing.md", "link.md"])
def test_only_markdown_under_the_docs_directory_is_accepted(root, reg, monkeypatch, bad):
    from resource_explorer import dr_egeria_runner as runner

    (root.parent / "outside.md").write_text(DOC)
    (root / "link.md").symlink_to(root.parent / "outside.md")
    fakes = Fakes(monkeypatch)
    with pytest.raises(runner.DocumentRefused):
        runner.run_document(bad, registry=reg)
    with pytest.raises(runner.DocumentRefused):
        runner.run_document(bad, dry_run=True, registry=reg)
    assert fakes.calls == [] and _rows(reg) == []


def test_the_default_root_is_the_repo_docs_dr_egeria(monkeypatch):
    from resource_explorer import bootstrap, dr_egeria_runner as runner

    monkeypatch.delenv("RE_DR_EGERIA_DOCS_DIR", raising=False)
    assert runner.docs_root() == bootstrap.DOCS_DIR.resolve()
    assert runner.resolve_document("engine-host/resource-explorer-survey-engine.md").is_file()


# ── pyegeria steps ──────────────────────────────────────────────────────────

def test_find_or_create_never_creates_what_already_exists(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch, engine_exists=True, service_exists=True, link_exists=True)
    runner.run_document("engine-host/decl.md", registry=reg)
    fakes.maker.create_software_capability.assert_not_called()
    fakes.maker.create_asset.assert_not_called()
    fakes.maker.link_supported_governance_service.assert_not_called()
    items = _rows(reg)[0]["items"]
    assert [i["outcome"] for i in items[:3]] == ["found", "found", "found"]


def test_an_engine_that_exists_is_found_and_only_the_missing_parts_are_created(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch, engine_exists=True)
    runner.run_document("engine-host/decl.md", registry=reg)
    fakes.maker.create_software_capability.assert_not_called()
    fakes.maker.create_asset.assert_called_once()
    fakes.maker.link_supported_governance_service.assert_called_once()
    assert fakes.link_body["properties"]["requestType"] == "re-db-derived"
    assert fakes.link_body["properties"]["serviceRequestType"] == "re-db-derived"


def test_a_lookup_that_cannot_answer_creates_nothing(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch)
    fakes.expert.get_metadata_guid_by_unique_name.side_effect = lambda *a, **k: None
    runner.run_document("engine-host/decl.md", registry=reg)
    fakes.maker.create_software_capability.assert_not_called()
    assert _rows(reg)[0]["items"][0]["status"] == "error"


def test_engine_then_service_then_link_then_the_action_type(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch)
    runner.run_document("engine-host/decl.md", registry=reg)
    assert fakes.writes() == ["create engine", "create service", "link supported service",
                              "dr_egeria --process --summary-only decl.md"]


def test_a_steps_file_out_of_order_is_refused(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    steps = {"steps": [STEPS["steps"][2], STEPS["steps"][0], STEPS["steps"][1]]}
    (root / "engine-host" / "decl.pyegeria-steps.json").write_text(json.dumps(steps))
    fakes = Fakes(monkeypatch)
    with pytest.raises(runner.DocumentRefused, match="order"):
        runner.run_document("engine-host/decl.md", registry=reg)
    assert fakes.calls == []


# ── identity ────────────────────────────────────────────────────────────────

def test_every_client_is_built_for_the_daemon_user(root, reg, monkeypatch):
    from resource_explorer import dr_egeria_runner as runner

    fakes = Fakes(monkeypatch)
    runner.run_document("engine-host/decl.md", registry=reg)
    assert fakes.built and {u for _c, u in fakes.built} == {DAEMON}
    env = fakes.subprocess_envs[0]
    assert env["EGERIA_USER"] == DAEMON, "dr_egeria runs as the daemon, not the inherited EGERIA_USER"
    assert env["EGERIA_USER_PASSWORD"] == "daemon-secret"
    assert env["EGERIA_VIEW_SERVER_URL"] == env["EGERIA_PLATFORM_URL"] == "https://localhost:9443"


def test_the_runner_has_its_own_daemon_reason():
    from resource_explorer.egeria_clients import DaemonReason

    assert DaemonReason.DR_EGERIA.value == "dr_egeria"


# ── CLI and route ───────────────────────────────────────────────────────────

def test_the_cli_and_the_route_call_the_same_function(root, monkeypatch):
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from resource_explorer import dr_egeria_runner as runner
    from resource_explorer.cli.main import app as cli_app
    from resource_explorer.web.app import app as web_app

    seen = []

    def fake_run(path, *, dry_run=False, force=False, requested_by="", registry=None):
        seen.append((str(path), dry_run, force))
        return {"status": "planned", "document": str(path), "dry_run": dry_run, "commands": [],
                "not_safe_to_repeat": [], "errors": [], "summary": "", "valid": True}

    monkeypatch.setattr(runner, "run_document", fake_run)
    res = CliRunner().invoke(cli_app, ["dr-egeria", "run", "engine-host/decl.md", "--dry-run"])
    assert res.exit_code == 0, res.output

    monkeypatch.setattr("resource_explorer.web.admin_auth.is_admin_request", lambda *a, **k: True)
    monkeypatch.setattr("resource_explorer.web.admin_auth.admin_configured", lambda *a, **k: True)
    monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda *a, **k: {"sub": "dan"})
    r = TestClient(web_app).post("/api/bootstrap/dr-egeria/run",
                                 json={"path": "engine-host/decl.md", "dry_run": True})
    assert r.status_code == 200, r.text
    assert seen == [("engine-host/decl.md", True, False), ("engine-host/decl.md", True, False)]


def test_the_route_is_admin_only(root, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer import dr_egeria_runner as runner
    from resource_explorer.web.app import app as web_app

    monkeypatch.setattr(runner, "run_document", lambda *a, **k: pytest.fail("a refused caller runs nothing"))
    monkeypatch.setattr("resource_explorer.web.admin_auth.is_admin_request", lambda *a, **k: False)
    monkeypatch.setattr("resource_explorer.web.admin_auth.admin_configured", lambda *a, **k: True)
    monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda *a, **k: {"sub": "peter"})
    client = TestClient(web_app)
    for body in ({"path": "engine-host/decl.md"}, {"path": "engine-host/decl.md", "dry_run": True}):
        assert client.post("/api/bootstrap/dr-egeria/run", json=body).status_code == 403
    monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda *a, **k: None)
    assert client.post("/api/bootstrap/dr-egeria/run", json={"path": "x.md"}).status_code == 403


def test_the_route_maps_refusals(root, reg, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer import dr_egeria_runner as runner
    from resource_explorer.web.app import app as web_app

    monkeypatch.setattr("resource_explorer.web.admin_auth.is_admin_request", lambda *a, **k: True)
    monkeypatch.setattr("resource_explorer.web.admin_auth.admin_configured", lambda *a, **k: True)
    monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda *a, **k: {"sub": "dan"})
    real = runner.run_document
    monkeypatch.setattr(runner, "run_document", lambda path, **k: real(path, **{**k, "registry": reg}))
    Fakes(monkeypatch)
    client = TestClient(web_app)
    assert client.post("/api/bootstrap/dr-egeria/run", json={"path": "/etc/passwd"}).status_code == 400
    assert client.post("/api/bootstrap/dr-egeria/run", json={"path": "plain/only.md"}).status_code == 200
    again = client.post("/api/bootstrap/dr-egeria/run", json={"path": "plain/only.md"})
    assert again.status_code == 409 and "--force" not in again.json()["detail"]
    assert client.post("/api/bootstrap/dr-egeria/run",
                       json={"path": "plain/only.md", "force": True}).status_code == 200


def test_the_cli_refuses_a_repeat_with_exit_1(root, reg, monkeypatch):
    from typer.testing import CliRunner

    from resource_explorer import dr_egeria_runner as runner
    from resource_explorer.cli.main import app as cli_app

    real = runner.run_document
    monkeypatch.setattr(runner, "run_document", lambda path, **k: real(path, **{**k, "registry": reg}))
    Fakes(monkeypatch)
    first = CliRunner().invoke(cli_app, ["dr-egeria", "run", "plain/only.md"])
    assert first.exit_code == 0, first.output
    assert "not safe to repeat" in first.output and "Link Action to Action Executor" in first.output
    second = CliRunner().invoke(cli_app, ["dr-egeria", "run", "plain/only.md"])
    assert second.exit_code == 1 and "--force" in second.output
