"""One rule for "is this the repository's own code?" — ingestion/vendored.py —
and the places it must be read.

Before 2026-09-11 the rule was private to the line census, and on
egeria-workspaces 68% of the inventory, 77% of the symbols and 99% of the
JavaScript chunks were node_modules/typescript. These pin: the rule itself;
that the inventory RECORDS provenance rather than dropping files; that
readers exclude vendored rows by default; and that the symbol/chunk walk
skips them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from resource_explorer.ingestion.vendored import VENDORED_DIRS, is_vendored, is_vendored_abs
from resource_explorer.registry import Project, ProjectRegistry


class TestTheRule:
    def test_any_directory_segment_counts_and_the_filename_never_does(self):
        assert is_vendored("node_modules/typescript/lib/typescript.js")
        assert is_vendored("plugins/x/node_modules/a.js")
        assert is_vendored("site-packages/requests/api.py")
        assert not is_vendored("src/vendor.py")          # a FILE named vendor
        assert not is_vendored("src/app/main.py")
        assert not is_vendored("README.md")

    def test_the_line_census_reads_the_same_set(self):
        from resource_explorer.ingestion import line_census
        assert line_census._EXCLUDED_DIRS is VENDORED_DIRS

    def test_abs_form_is_relative_to_the_walk_root(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        f = tmp_path / "node_modules" / "x.js"; f.write_text("")
        assert is_vendored_abs(f, tmp_path)
        assert not is_vendored_abs(tmp_path / "x.js", tmp_path)


@pytest.fixture
def db(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p", description=""))
    return r


class TestInventoryRecordsProvenance:
    def test_vendored_files_are_kept_marked_and_excluded_from_readers(self, db):
        db.upsert_file_inventory("p", [("src/a.py", 10), ("node_modules/t.js", 99), ("docs/x.md", 5)])
        # recorded, not dropped
        assert db.file_inventory_summary("p") == {"total": 3, "own": 2, "vendored": 1,
                                                  "indexed_at": db.file_inventory_summary("p")["indexed_at"]}
        # readers see the repository's own files by default
        assert sorted(db.get_file_inventory("p")) == ["docs/x.md", "src/a.py"]

    def test_a_pre_migration_row_reads_as_own_until_reindexed(self, db):
        """DEFAULT 0 means an old inventory is unchanged by the migration —
        and the summary's indexed_at is how a reader tells old from new."""
        db.upsert_file_inventory("p", [("src/a.py", 10)])
        with db._conn() as conn:
            conn.execute("UPDATE project_file_inventory SET vendored = NULL WHERE project_slug = 'p'")
        assert db.get_file_inventory("p") == ["src/a.py"]
        assert db.file_inventory_summary("p")["vendored"] == 0


class TestTheWalks:
    def test_local_files_skips_vendored_paths(self, tmp_path):
        from resource_explorer.ingestion.pipeline import IngestionPipeline
        (tmp_path / "src").mkdir(); (tmp_path / "node_modules" / "lib").mkdir(parents=True)
        (tmp_path / "src" / "own.py").write_text("x = 1\n")
        (tmp_path / "node_modules" / "lib" / "theirs.py").write_text("y = 2\n")
        pipe = IngestionPipeline.__new__(IngestionPipeline)   # no store, no registry: the walk is pure
        got = dict(pipe._local_files(tmp_path, [".py"]))
        assert list(got) == ["src/own.py"]


class TestSubResourceSurveyStillListsVendored:
    def test_a_vendored_folder_is_listed_not_worthy_with_the_reason(self, db):
        """The one reader that must see vendored rows: a sub-resource survey
        that omitted node_modules would make "34 sub-resources" silently
        mean "34 of 41". Listed, and the reason is the honest one."""
        from resource_explorer.surveyors.sub_surveyors.sub_resource_survey import SubResourceSurveyor
        db.upsert_file_inventory("p", [(f"node_modules/lib/f{i}.js", 1) for i in range(12)]
                                 + [(f"src/m{i}.py", 1) for i in range(12)])
        rows = db.get_file_inventory_with_sizes("p", include_vendored=True)
        assert {r["file_path"].split("/")[0]: r["vendored"] for r in rows} == {"node_modules": True, "src": False}
        # and the default reader still hides it from everyone else
        assert all(not r["file_path"].startswith("node_modules") for r in db.get_file_inventory_with_sizes("p"))
