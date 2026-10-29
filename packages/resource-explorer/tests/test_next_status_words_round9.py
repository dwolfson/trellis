"""Status words, round 9: a library step's run row names its declared stage, its executor and its duration."""
import json

import pytest

from resource_explorer.activity_logger import log_analysis_run
from resource_explorer.surveyors import analysis_catalog_reader as reader


@pytest.fixture
def fs_activity_ran(tmp_path, monkeypatch):
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors import survey_step_host
    from tests.library_step_install import _entries
    from tests.test_files_derived_steps_host import _register, _tree, _walk

    for entry in reversed(_entries(tmp_path, ("fs_activity",))):
        monkeypatch.syspath_prepend(entry)
    survey_step_host.refresh("filesystem")
    registry = ProjectRegistry(db_path=str(tmp_path / "fs.db"))
    _walk(registry, _register(registry, _tree(tmp_path)))
    yield registry
    monkeypatch.undo()
    survey_step_host.refresh("filesystem")


def test_the_run_row_uses_the_stage_the_catalog_declares(fs_activity_ran):
    registry = fs_activity_ran
    declared = next(a["intent"] for a in reader.get_analyses("filesystem", include_egeria_live=False)
                    if a["id"] == "fs_activity")
    assert declared != "assessment"
    aid = log_analysis_run(registry, "filesystem", "tree", "tree", "running", "x", "fs_activity")
    assert registry.get_activity(aid)["intent"] == declared


def test_the_finished_row_carries_executor_and_duration(fs_activity_ran):
    from resource_explorer.workflows.analysis import execute_and_record_filesystem_analysis

    registry = fs_activity_ran
    aid = log_analysis_run(registry, "filesystem", "tree", "tree", "running", "x", "fs_activity")
    execute_and_record_filesystem_analysis("tree", "fs_activity", aid, registry=registry)
    detail = json.loads(registry.get_activity(aid)["detail"])
    assert detail["executor"] in ("local", "prefect")
    assert isinstance(detail["duration_s"], float)
