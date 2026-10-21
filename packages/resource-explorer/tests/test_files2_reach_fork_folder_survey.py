"""Files step 2 (2026-10-20): the reachability fork and the folder survey.

The probe records ONE outcome with a date; the outcome decides who leads: Egeria's Folder Survey where Egeria's engine host
can read the canonical mount, Resource Explorer's walk where only it can. Each outcome is read from stored rows. Fakes bind
the real pyegeria signatures (`create_autospec(..., spec_set=True)`); RE's probe, registry, walk, builder, port, view and
routes run for real. Nothing here reaches Egeria, a database or Ollama (the conftest guard refuses the live probe).
"""
from __future__ import annotations

import builtins
import io
import os
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from resource_explorer import file_reach
from resource_explorer import native_survey_run as nsr
from resource_explorer.reachability import ReachabilityResult
from resource_explorer.registry import FileSystemEntity, ProjectRegistry

ASSET = "bbbbbbbb-0000-0000-0000-000000000001"
NOT_VISIBLE = ("OMES-SURVEY-ACTION-0018 ... FileException ... BASIC-FILE-CONNECTOR-404-001 The folder named /Users/x "
               "does not exist")


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "files2.db"))
    return r


def _fs(registry, tmp_path, *, slug="lake", canonical="/deployments/data-lake", guid=ASSET, make_dir=True):
    root = tmp_path / slug
    if make_dir:
        root.mkdir(exist_ok=True)
    registry.register_filesystem(FileSystemEntity(
        slug=slug, display_name=slug.title(), local_mount_point=str(root), canonical_mount_point=canonical,
        egeria_asset_guid=guid))
    return registry.get_filesystem(slug), root


def _egeria_says(outcome, code="", detail=""):
    """A stand-in for Egeria's engine host: records its row the way `check_filesystem_reachability` does."""
    calls = []

    def probe(slug, registry):
        calls.append(slug)
        registry.record_reachability_check(slug, probed_at="2026-10-20T10:00:00+00:00", outcome=outcome,
                                           error_code=code, error_detail=detail)
        return ReachabilityResult(outcome=outcome, error_code=code, error_detail=detail, latency_ms=1,
                                  engine_action_guid="ea-1")
    probe.calls = calls
    return probe


# ── 1. the stored rows decide the state; "not checked yet" is its own state ───────────────────────────────────────

def test_no_row_is_not_checked_yet_and_neither_outcome(registry, tmp_path):
    fs, _ = _fs(registry, tmp_path)
    s = file_reach.fork_for(registry, fs)
    assert s.state == file_reach.NOT_CHECKED and s.sentence == "not checked yet"
    assert s.surveyor == "" and not s.decided


def test_outcome_1_sentence_names_the_container_path_and_the_date(registry, tmp_path):
    fs, _ = _fs(registry, tmp_path)
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="reachable")
    s = file_reach.fork_for(registry, fs)
    assert s.state == file_reach.EGERIA
    assert s.sentence == "Egeria can read /deployments/data-lake · checked 2026-10-20"
    assert s.surveyor == "Egeria's Folder Survey"
    assert s.report_sentence == "surveyed by Egeria's Folder Survey"


def test_outcome_2_sentence_and_the_report_sentence(registry, tmp_path):
    fs, _ = _fs(registry, tmp_path)
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
    s = file_reach.fork_for(registry, fs)
    assert s.state == file_reach.RE_ONLY
    assert s.sentence == "only Resource Explorer can read this path · checked 2026-10-20"
    assert s.surveyor == "Resource Explorer"
    assert s.report_sentence == "surveyed by Resource Explorer · Egeria could not reach the path"


@pytest.mark.parametrize("outcome", ["unknown", "no_connection", "auth_rejected", "unresolvable_secret",
                                     "network_unreachable"])
def test_a_probe_that_could_not_tell_is_neither_outcome(registry, tmp_path, outcome):
    """Egeria timing out, having no connection, or refusing is not "only Resource Explorer can read this path"."""
    fs, _ = _fs(registry, tmp_path)
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome=outcome,
                                       error_detail="Egeria's own words")
    s = file_reach.fork_for(registry, fs)
    assert s.state == file_reach.UNDECIDED and not s.decided
    assert s.surveyor == "" and "Egeria's own words" in s.why
    assert not s.sentence.startswith(("only Resource Explorer", "Egeria can read"))
    assert s.sentence == "could not tell whether Egeria can read this path · checked 2026-10-20"


def test_the_newest_row_decides_and_history_is_kept(registry, tmp_path):
    fs, _ = _fs(registry, tmp_path)
    registry.record_reachability_check("lake", probed_at="2026-10-19T10:00:00+00:00", outcome="reachable")
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
    assert file_reach.fork_for(registry, fs).state == file_reach.RE_ONLY
    assert len(registry.list_reachability_history("lake")) == 2


# ── 2. the probe asks Egeria and never trusts the typed value ─────────────────────────────────────────────────────

def test_a_typed_canonical_mount_is_not_believed_when_egeria_cannot_see_it(registry, tmp_path):
    fs, _ = _fs(registry, tmp_path, canonical="/looks/fine/typed")
    asked = _egeria_says("network_unreachable", file_reach.NOT_VISIBLE_CODE, NOT_VISIBLE)
    state = file_reach.probe_filesystem("lake", registry, egeria_probe=asked)
    assert asked.calls == ["lake"], "Egeria's engine host must be asked, once"
    assert state.state == file_reach.RE_ONLY       # RE read the local mount (it exists), Egeria could not
    rows = registry.list_reachability_history("lake")
    assert [r["outcome"] for r in rows] == ["re_only", "network_unreachable"]
    assert file_reach.NOT_VISIBLE_CODE in rows[0]["error_detail"]


def test_egeria_can_read_it_is_outcome_1_and_records_no_re_only_row(registry, tmp_path):
    _fs(registry, tmp_path)
    state = file_reach.probe_filesystem("lake", registry, egeria_probe=_egeria_says("reachable"))
    assert state.state == file_reach.EGERIA
    assert [r["outcome"] for r in registry.list_reachability_history("lake")] == ["reachable"]


def test_nobody_can_read_it_is_neither_outcome(registry, tmp_path):
    """Egeria cannot see the folder AND this server cannot read it: not "only Resource Explorer can read this path"."""
    _fs(registry, tmp_path, make_dir=False)
    state = file_reach.probe_filesystem(
        "lake", registry, egeria_probe=_egeria_says("network_unreachable", file_reach.NOT_VISIBLE_CODE, NOT_VISIBLE))
    assert state.state == file_reach.UNDECIDED
    assert "re_only" not in [r["outcome"] for r in registry.list_reachability_history("lake")]


def test_an_egeria_failure_that_raises_leaves_the_state_as_the_rows_prove_it(registry, tmp_path):
    _fs(registry, tmp_path)

    def boom(slug, reg):
        raise ConnectionError("egeria down")

    assert file_reach.probe_filesystem("lake", registry, egeria_probe=boom).state == file_reach.NOT_CHECKED


def test_the_real_check_asks_egeria_through_the_pyegeria_signature(registry, tmp_path, monkeypatch):
    """The real `check_filesystem_reachability` end to end with fakes that BIND pyegeria's real signatures."""
    from pyegeria import AutomatedCuration, MetadataExpert

    from resource_explorer import reachability

    _fs(registry, tmp_path)
    ac = create_autospec(AutomatedCuration, instance=True, spec_set=True)
    me = create_autospec(MetadataExpert, instance=True, spec_set=True)
    ac.initiate_gov_action_type.return_value = "ea-guid-1"
    me.get_metadata_element_by_guid.return_value = {"elementProperties": {"propertyValueMap": {
        "activityStatus": {"symbolicName": "FAILED"}, "completionMessage": {"primitiveValue": NOT_VISIBLE}}}}
    monkeypatch.setattr(reachability, "_get_clients", lambda: (ac, me))
    # the conftest guard replaces the probe's one live call; this test puts the REAL call back, over fakes
    monkeypatch.setattr(file_reach, "_default_egeria_probe", reachability.check_filesystem_reachability)
    state = file_reach.probe_filesystem("lake", registry)
    kwargs = ac.initiate_gov_action_type.call_args.kwargs
    assert kwargs["action_type_qualified_name"] == "FileSurvey::survey-folder"
    assert kwargs["action_targets"][0]["actionTargetGUID"] == ASSET
    assert state.state == file_reach.RE_ONLY


# ── 3. Egeria leads: the native port, the request parameter, the gate, the read-back ────────────────────────────

def _real_port_with_fake_pyegeria():
    from pyegeria import AutomatedCuration

    port = nsr.PyegeriaSurveyPort(identity=object())
    ac = create_autospec(AutomatedCuration, instance=True, spec_set=True)
    ac.initiate_gov_action_type.return_value = "ea-folder-1"
    port._curation = ac
    return port, ac


def test_the_folder_survey_is_submitted_with_analysis_level_through_the_real_signature():
    port, ac = _real_port_with_fake_pyegeria()
    guid = port.initiate(nsr.FOLDER_SURVEY_QN, "fileToSurvey", ASSET, request_parameters={"analysisLevel": "TOP_LEVEL_ONLY"})
    assert guid == "ea-folder-1"
    kwargs = ac.initiate_gov_action_type.call_args.kwargs
    assert kwargs["request_parameters"] == {"analysisLevel": "TOP_LEVEL_ONLY"}
    assert kwargs["action_type_qualified_name"] == "FileSurvey::survey-folder"


def test_a_survey_that_takes_no_parameters_is_started_exactly_as_before():
    port, ac = _real_port_with_fake_pyegeria()
    port.initiate("PostgreSQLSurvey::survey-postgres-database", "databaseToSurvey", ASSET)
    assert "request_parameters" not in ac.initiate_gov_action_type.call_args.kwargs


class _Port:
    """A scriptable Egeria for the native-survey port, recording what it was asked (the Folder Survey takes a
    `request_parameters` keyword, as the real port does)."""

    def __init__(self):
        self.calls = []
        self.reports = {}
        self.originators = {}
        self.annotations = {}
        self.status = ("REQUESTED", "")

    def asset_exists(self, guid):
        return True

    def initiate(self, qn, target_name, target_guid, request_parameters=None):
        self.calls.append(("initiate", qn, target_name, target_guid, request_parameters))
        return "ea-folder-9"

    def read_action(self, guid):
        return nsr.ActionRead(status=self.status[0], message=self.status[1])

    def report_guid_for_action(self, guid):
        return self.reports.get(guid)

    def read_report(self, report_guid):
        return nsr.ReportRead(guid=report_guid, at="2026-10-20T11:00:00+00:00",
                              originator_guid=self.originators.get(report_guid, ""),
                              annotations=list(self.annotations.get(report_guid, [])))


def _ann(n, name, **detail):
    return {"guid": f"ann-{n}", "annotation_type": name, "analysis_step": "Profiling Associated Resources",
            "summary": name, "explanation": "", "confidence": 0, "detail": detail}


def _submit(registry):
    return nsr.submit_native_survey(registry, _PORT, "filesystem", "lake", nsr.FOLDER_SURVEY_QN,
                                    technology_type="File System Directory", submitted_by="dan")


_PORT = None


def test_egeria_leads_only_where_the_stored_probe_says_it_can_read(registry, tmp_path):
    fs, _ = _fs(registry, tmp_path)
    proc = next(p for p in nsr._processes_for_rows("filesystem", "File System Directory")
                if p.qualified_name == nsr.FOLDER_SURVEY_QN)

    def reason():
        return nsr.cannot_run_reason(proc, registry.get_filesystem("lake"), registry=registry,
                                     technology_type="File System Directory")

    assert reason() == "not checked yet"
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
    assert "only Resource Explorer can read this path" in reason()
    registry.record_reachability_check("lake", probed_at="2026-10-20T11:00:00+00:00", outcome="unknown",
                                       error_detail="timed out")
    assert "could not tell" in reason() and "timed out" in reason()
    registry.record_reachability_check("lake", probed_at="2026-10-20T12:00:00+00:00", outcome="reachable")
    assert reason() == ""


def test_a_press_when_re_leads_is_refused_and_asks_egeria_nothing(registry, tmp_path):
    global _PORT
    _fs(registry, tmp_path)
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
    _PORT = _Port()
    with pytest.raises(nsr.NativeSurveyCannotRun, match="only Resource Explorer can read this path"):
        _submit(registry)
    assert _PORT.calls == []


def test_egeria_led_run_sends_analysis_level_and_the_row_names_its_surveyor(registry, tmp_path):
    global _PORT
    _fs(registry, tmp_path)
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="reachable")
    _PORT = _Port()
    _submit(registry)
    (call,) = _PORT.calls
    assert call == ("initiate", "FileSurvey::survey-folder", "fileToSurvey", ASSET, {"analysisLevel": "TOP_LEVEL_ONLY"})
    rows = nsr.native_survey_rows(registry, "filesystem", "lake", "File System Directory")
    folder = next(r for r in rows if r["qualified_name"] == nsr.FOLDER_SURVEY_QN)
    assert folder["surveyor"] == "Egeria's Folder Survey" and folder["runnable"] is True


def test_the_file_names_log_is_never_read_stored_or_shown(registry, tmp_path):
    """Egeria writes "Profile File Names to External Log" on every folder survey (no request parameter turns it off);
    Resource Explorer's half of "stays off" is that it never reads it."""
    global _PORT
    _fs(registry, tmp_path)
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="reachable")
    _PORT = _Port()
    _submit(registry)
    _PORT.status = ("COMPLETED", "done")
    _PORT.reports["ea-folder-9"] = "report-9"
    _PORT.originators["report-9"] = "ea-folder-9"
    _PORT.annotations["report-9"] = [
        _ann(1, "Capture File Counts", resource_properties={
            "Number of files": "120", "Total file size": "1.2345678E7", "Number of subdirectories (folders)": "9",
            "Number of inaccessible files": "2", "Last file modification time": "2026-10-19"}),
        _ann(2, "Profile File Types", value_count={"CSV Data File": 7, "Markdown": 3}),
        _ann(3, "Inaccessible files"),
        _ann(4, "Profile File Names to External Log", resource_properties={"logFile": "/surveys/names.csv"}),
    ]
    run = registry.list_native_survey_runs("filesystem", "lake", nsr.FOLDER_SURVEY_QN)[0]
    nsr.refresh_run(registry, _PORT, run, entity_type="filesystem", slug="lake")
    run = registry.list_native_survey_runs("filesystem", "lake", nsr.FOLDER_SURVEY_QN)[0]
    types = {a["annotation_type"] for a in registry.query_native_survey_annotations(run["survey_report_guid"])}
    assert "Profile File Names to External Log" not in types
    assert types == {"Capture File Counts", "Profile File Types", "Inaccessible files"}


def test_the_view_reads_an_egeria_led_report_back_into_counts_types_and_inaccessible(registry, tmp_path):
    from resource_explorer.folder_survey_view import folder_survey_view

    global _PORT
    _fs(registry, tmp_path)
    assert folder_survey_view(registry, "lake")["state"] == "none"
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="reachable")
    _PORT = _Port()
    _submit(registry)
    _PORT.status = ("COMPLETED", "done")
    _PORT.reports["ea-folder-9"] = "report-9"
    _PORT.originators["report-9"] = "ea-folder-9"
    _PORT.annotations["report-9"] = [
        _ann(1, "Capture File Counts", resource_properties={
            "Number of files": "120", "Total file size": "1.2345678E7", "Number of subdirectories (folders)": "9",
            "Number of inaccessible files": "2", "Number of unclassified files": "5"}),
        _ann(2, "Profile File Types", value_count={"CSV Data File": 7, "Markdown": 3}),
        _ann(3, "Inaccessible files"),
    ]
    run = registry.list_native_survey_runs("filesystem", "lake", nsr.FOLDER_SURVEY_QN)[0]
    nsr.refresh_run(registry, _PORT, run, entity_type="filesystem", slug="lake")
    v = folder_survey_view(registry, "lake")
    assert v["state"] == "measured" and v["surveyor"] == "Egeria's Folder Survey"
    assert v["report_sentence"] == "surveyed by Egeria's Folder Survey" and v["published"] is True
    c = v["results"]["counts"]
    assert (c["files"], c["subdirectories"], c["total_size_bytes"], c["unclassified"], c["inaccessible"]) == (120, 9, 12345678, 5, 2)
    assert v["results"]["file_types"] == [{"name": "CSV Data File", "count": 7}, {"name": "Markdown", "count": 3}]
    # Egeria keeps the inaccessible NAMES in a CSV asset, not in the annotation: the count and the request are read.
    assert v["results"]["inaccessible"] == {"count": 2, "listed": None, "requested": True}
    assert v["limits"] is None


# ── 4. Resource Explorer leads: the same annotation types, under its own report ─────────────────────────────────────

EGERIA_NAMES = {"Capture File Counts", "Profile File Extensions", "Profile File Types", "Profile Asset Types",
                "Profile Deployed Implementation Types", "Missing File Reference Data", "Inaccessible files"}


def _tree(tmp_path):
    root = tmp_path / "walkme"
    (root / "data" / "deep" / "deeper").mkdir(parents=True)
    (root / "data" / "a.csv").write_text("a,b\n1,2\n")
    (root / "data" / "deep" / "b.json").write_text("{}")
    (root / "data" / "deep" / "deeper" / "c.xyz123").write_text("mystery")
    (root / "README.md").write_text("# hi\n")
    (root / ".hidden").write_text("h")
    return root


def _walk(registry, root, **limits):
    from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import LocalFileSystemSurveyor

    registry.register_filesystem(FileSystemEntity(slug="walkme", display_name="W", local_mount_point=str(root),
                                                  canonical_mount_point="/x/walkme", egeria_asset_guid=ASSET))
    return LocalFileSystemSurveyor(registry.get_filesystem("walkme"), registry, **limits).run(profile_contents=False)


def test_the_walk_publishes_egerias_annotation_types_and_never_the_names_log(registry, tmp_path):
    from resource_explorer.surveyors.filesystem.folder_survey_annotations import folder_specs, to_annotations

    sd = _walk(registry, _tree(tmp_path))
    specs = folder_specs(sd, directory_name="/x/walkme")
    names = {s["annotation_type_name"] for s in specs}
    assert names <= EGERIA_NAMES and "Profile File Names to External Log" not in names
    assert {"Capture File Counts", "Profile File Extensions", "Profile File Types"} <= names
    measure = next(s for s in specs if s["annotation_type_name"] == "Capture File Counts")
    # FileDirectoryMetric display names, verbatim (read from Egeria's source, FileDirectoryMetric.java)
    assert measure["resource_properties"]["Number of files"] == "5"
    assert measure["resource_properties"]["Number of subdirectories (folders)"] == "3"
    assert measure["resource_properties"]["Hidden File Count"] == "1"
    assert {"fileCount", "subDirectoryCount", "directoryName"} <= set(measure["json_properties"])
    assert all(isinstance(v, str) for v in measure["resource_properties"].values())
    kinds = {a.annotation_type.value for a in to_annotations(specs)}
    assert kinds <= {"ResourceMeasureAnnotation", "ResourceProfileAnnotation", "RequestForActionAnnotation"}


def test_re_and_egeria_results_read_the_same_way(registry, tmp_path):
    """Understanding reads one shape: the view of RE's specs and of Egeria's stored annotations have the same keys."""
    from resource_explorer.surveyors.filesystem.folder_survey_annotations import folder_specs, read_folder_survey

    sd = _walk(registry, _tree(tmp_path))
    re_view = read_folder_survey(folder_specs(sd))
    egeria_view = read_folder_survey([
        {"annotation_type": "Capture File Counts", "detail": {"resource_properties": {"Number of files": "5"}}}])
    assert set(re_view) == set(egeria_view)
    assert set(re_view["counts"]) == set(egeria_view["counts"])
    assert re_view["counts"]["files"] == 5 and egeria_view["counts"]["files"] == 5
    # a number the survey did not carry is None (not measured), never 0
    assert egeria_view["counts"]["hidden"] is None and egeria_view["counts"]["unclassified"] is None


def test_publish_is_refused_unless_the_probe_proves_egeria_could_not_reach_the_path(registry, tmp_path):
    from resource_explorer.surveyors.filesystem import survey_definition_adapter as ad
    from resource_explorer.surveyors.survey_definition_executor import NothingToPublish

    root = _tree(tmp_path)
    sd = _walk(registry, root)
    fs = registry.get_filesystem("walkme")
    for outcome in ("reachable", "unknown"):
        registry.record_reachability_check("walkme", probed_at="2026-10-20T10:00:00+00:00", outcome=outcome)
        with pytest.raises(NothingToPublish):
            ad._publish(fs, [{"survey_data": sd}], sd["surveyed_at"], registry)
    with pytest.raises(NothingToPublish, match="Egeria's Folder Survey leads"):
        ad._publish(fs, [{"survey_data": None}], "t", registry)


def test_the_published_report_names_resource_explorer_and_says_when_capped(registry, tmp_path):
    from pyegeria import AssetMaker

    from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyor

    sd = _walk(registry, _tree(tmp_path), max_entries=3)
    assert sd["walk_limits"]["capped"] is True
    registry.record_reachability_check("walkme", probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
    fs = registry.get_filesystem("walkme")
    sd["surveyed_by"] = {"surveyor": file_reach.SURVEYOR_RE, "reach": file_reach.fork_for(registry, fs).as_dict()}
    maker = create_autospec(AssetMaker, instance=True, spec_set=True)
    maker.create_asset.return_value = "report-guid-7"
    s = EgeriaFileSystemSurveyor()
    s.connect = lambda: None
    s._asset_maker = maker
    made = []
    s._create_annotations = lambda anns, guid, slug, at: made.extend(anns) or [g.annotation_type for g in anns]
    out = s.publish_step_annotations(fs, sd, registry)
    assert out["report_guid"] == "report-guid-7"
    props = maker.create_asset.call_args.kwargs["body"]["properties"]
    assert "surveyed by Resource Explorer · Egeria could not reach the path" in props["description"]
    assert "capped" in props["description"] and "not the whole tree" in props["description"]
    assert props["additionalProperties"]["walkCapped"] == "true"
    assert props["additionalProperties"]["surveyor"] == "Resource Explorer"
    assert {a.annotation_type_name for a in made} <= EGERIA_NAMES
    assert "Profile File Names to External Log" not in {a.annotation_type_name for a in made}


# ── 5. the three cautions ────────────────────────────────────────────────────────────────────────────────────────

def test_caution_1_the_walk_opens_no_file_contents(registry, tmp_path, monkeypatch):
    root = _tree(tmp_path)
    opened = []
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def watch(path):
        try:
            p = os.fspath(path)
        except TypeError:
            return
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        if isinstance(p, str) and p.startswith(str(root)):
            opened.append(p)

    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (watch(f), real_open(f, *a, **k))[1])
    monkeypatch.setattr(io, "open", lambda f, *a, **k: (watch(f), real_io_open(f, *a, **k))[1])
    monkeypatch.setattr(os, "open", lambda f, *a, **k: (watch(f), real_os_open(f, *a, **k))[1])
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: (watch(self), real_open(self, *a, **k))[1])
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (watch(self), "")[1])
    monkeypatch.setattr(Path, "read_bytes", lambda self, *a, **k: (watch(self), b"")[1])
    sd = _walk(registry, root)
    assert opened == [], f"the walk opened file contents: {opened}"
    assert sd["total_files"] == 5 and sd["profiling_errors"] == []
    assert not any("row_count" in f for f in sd["inventory"]), "no file was profiled"


def test_caution_2_the_walk_writes_nothing_into_the_path(registry, tmp_path):
    root = _tree(tmp_path)

    def snapshot():
        out = {}
        for dirpath, dirnames, filenames in os.walk(root):
            for n in dirnames + filenames:
                p = Path(dirpath) / n
                st = p.stat()
                out[str(p)] = (st.st_size, st.st_mtime_ns)
        out[str(root)] = (0, root.stat().st_mtime_ns)
        return out

    before = snapshot()
    _walk(registry, root)
    assert snapshot() == before


def test_caution_3_limits_are_declared_and_a_capped_walk_says_it_was_capped(registry, tmp_path):
    root = _tree(tmp_path)
    whole = _walk(registry, root)
    lim = whole["walk_limits"]
    assert lim["capped"] is False and lim["capped_reasons"] == []
    assert lim["max_depth"] == 20 and lim["max_entries"] == 100_000
    assert "node_modules" in lim["not_walked_directory_names"]

    registry.remove_filesystem("walkme")
    by_entries = _walk(registry, root, max_entries=3)
    assert by_entries["walk_limits"]["capped"] is True and "entry cap" in by_entries["walk_limits"]["capped_reasons"]
    assert by_entries["total_files"] < whole["total_files"]

    registry.remove_filesystem("walkme")
    by_depth = _walk(registry, root, max_depth=1)
    assert by_depth["walk_limits"]["capped"] is True and "depth cap" in by_depth["walk_limits"]["capped_reasons"]


def test_noise_and_linked_folders_are_skipped_and_counted(registry, tmp_path):
    root = _tree(tmp_path)
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("x")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.txt").write_text("not ours")
    os.symlink(outside, root / "link_out")
    sd = _walk(registry, root)
    lim = sd["walk_limits"]
    assert lim["not_walked_directories"] == 1 and lim["symlinked_directories_not_followed"] == 1
    assert not any("secret.txt" in f["file_path"] or "junk.js" in f["file_path"] for f in sd["inventory"])
    assert lim["capped"] is False


# ── 6. the step: the probe runs first, and an Egeria-led survey measures nothing of Egeria's ─────────────────────

def test_the_inventory_step_probes_first_and_stands_aside_when_egeria_leads(registry, tmp_path, monkeypatch):
    from resource_explorer.surveyors.filesystem import survey_definition_adapter as ad

    _fs(registry, tmp_path)
    seen = []

    def probe(slug, reg, **kw):
        seen.append(slug)
        reg.record_reachability_check(slug, probed_at="2026-10-20T10:00:00+00:00", outcome="reachable")
        return file_reach.fork_for(reg, reg.get_filesystem(slug))

    monkeypatch.setattr(file_reach, "probe_filesystem", probe)
    out = ad._run_filesystem_inventory(registry.get_filesystem("lake"), registry)
    assert seen == ["lake"]
    assert out["led_by"] == "egeria" and out["survey_data"] is None
    assert registry.list_filesystem_surveys("lake") == [], "Resource Explorer re-measured what Egeria's survey owns"


def test_the_inventory_step_walks_and_stores_when_only_re_can_read(registry, tmp_path, monkeypatch):
    from resource_explorer.folder_survey_view import folder_survey_view
    from resource_explorer.surveyors.filesystem import survey_definition_adapter as ad

    root = _tree(tmp_path)
    registry.register_filesystem(FileSystemEntity(slug="walkme", display_name="W", local_mount_point=str(root),
                                                  canonical_mount_point="/x/walkme", egeria_asset_guid=ASSET))

    def probe(slug, reg, **kw):
        reg.record_reachability_check(slug, probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
        return file_reach.fork_for(reg, reg.get_filesystem(slug))

    monkeypatch.setattr(file_reach, "probe_filesystem", probe)
    out = ad._run_filesystem_inventory(registry.get_filesystem("walkme"), registry)
    assert out["led_by"] == "re_only" and out["persisted"] is True
    v = folder_survey_view(registry, "walkme")
    assert v["state"] == "measured" and v["surveyor"] == "Resource Explorer"
    assert v["report_sentence"] == "surveyed by Resource Explorer · Egeria could not reach the path"
    assert v["published"] is False                      # kept here, not claimed as published
    assert v["limits"]["capped"] is False
    assert v["results"]["counts"]["files"] == 5
    assert v["reach"]["state"] == "re_only"


# ── 7. routes ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def api(registry, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer.auth import create_access_token
    from resource_explorer.web.app import app

    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **k: setattr(self, "__dict__", registry.__dict__) or None)
    from tests.zone_fakes import open_access

    open_access(monkeypatch, caller_if_none="files2-tester")
    headers = {"Authorization": "Bearer " + create_access_token(user_id="files2-tester", egeria_token="tok")}
    return TestClient(app), headers


@pytest.mark.usefixtures("signed_in_caller")
def test_routes_read_the_stored_state_and_refuse_a_press_nobody_can_lead(api, registry, tmp_path):
    client, headers = api
    _fs(registry, tmp_path)
    reach = client.get("/api/filesystems/lake/reach", headers=headers).json()
    assert reach["state"] == "not_checked" and reach["sentence"] == "not checked yet"
    view = client.get("/api/filesystems/lake/folder-survey", headers=headers).json()
    assert view["state"] == "none" and view["results"] is None
    registry.record_reachability_check("lake", probed_at="2026-10-20T10:00:00+00:00", outcome="unknown",
                                       error_detail="timed out")
    # the press probes first; the conftest guard makes the live probe "could not tell", so nobody leads
    refused = client.post("/api/filesystems/lake/folder-survey", json={}, headers=headers)
    assert refused.status_code == 409 and "could not tell" in refused.json()["detail"]
    assert registry.list_filesystem_surveys("lake") == []


@pytest.mark.usefixtures("signed_in_caller")
def test_the_press_walks_when_only_re_can_read_and_keeps_it_unpublished_until_asked(api, registry, tmp_path, monkeypatch):
    client, headers = api
    root = _tree(tmp_path)
    registry.register_filesystem(FileSystemEntity(slug="walkme", display_name="W", local_mount_point=str(root),
                                                  canonical_mount_point="/x/walkme", egeria_asset_guid=ASSET))

    def probe(slug, reg, **kw):
        reg.record_reachability_check(slug, probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
        return file_reach.fork_for(reg, reg.get_filesystem(slug))

    monkeypatch.setattr(file_reach, "probe_filesystem", probe)
    r = client.post("/api/filesystems/walkme/folder-survey", json={}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["led_by"] == "resource_explorer" and body["surveyor"] == "Resource Explorer"
    assert body["published"] is False and body["capped"] is False and body["total_files"] == 5
    view = client.get("/api/filesystems/walkme/folder-survey", headers=headers).json()
    assert view["surveyor"] == "Resource Explorer" and view["published"] is False
    assert view["reach"]["sentence"] == "only Resource Explorer can read this path · checked 2026-10-20"


# ── 8. the screens and the routes agree on names ────────────────────────────────────────────────────────────────────

def test_the_view_has_exactly_the_keys_the_screens_read(registry, tmp_path):
    """fs-survey.js reads these names; a renamed key would draw dashes (not measured) where numbers exist."""
    from resource_explorer.folder_survey_view import folder_survey_view

    root = _tree(tmp_path)
    registry.register_filesystem(FileSystemEntity(slug="walkme", display_name="W", local_mount_point=str(root),
                                                  canonical_mount_point="/x/walkme", egeria_asset_guid=ASSET))
    sd = _walk_existing(registry, root)
    registry.record_reachability_check("walkme", probed_at="2026-10-20T10:00:00+00:00", outcome="re_only")
    sd["surveyed_by"] = {"surveyor": file_reach.SURVEYOR_RE, "reach": {}}
    registry.add_filesystem_survey("walkme", sd["surveyed_at"], sd, source="survey-definition")
    v = folder_survey_view(registry, "walkme")
    assert {"state", "surveyor", "surveyed_at", "report_guid", "published", "report_sentence", "results", "limits",
            "reach", "leads"} <= set(v)
    assert {"counts", "times", "file_types", "extensions", "asset_types", "deployed_types", "inaccessible"} <= set(v["results"])
    assert {"files", "total_size_bytes", "subdirectories", "file_types", "unclassified", "inaccessible"} <= set(v["results"]["counts"])
    assert {"max_depth", "max_entries", "capped", "capped_reasons", "entries_examined", "deepest_level_reached",
            "not_walked_directory_names", "not_walked_directories", "symlinked_directories_not_followed"} <= set(v["limits"])
    assert {"state", "sentence", "surveyor", "why", "decided"} <= set(v["reach"])


def _walk_existing(registry, root):
    from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import LocalFileSystemSurveyor

    return LocalFileSystemSurveyor(registry.get_filesystem("walkme"), registry).run(profile_contents=False)


def test_the_folder_survey_request_model_is_what_the_screen_posts():
    from resource_explorer.web.routes.filesystems import FolderSurveyRequest

    assert set(FolderSurveyRequest.model_fields) == {"publish"}      # fs-survey.js posts { publish: false }
