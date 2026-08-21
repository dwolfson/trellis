"""CSV batch import/export — inventory in, scorecard out.

The design rule under test is that **import reads intent and never state**.
Every observed column is prefixed `status_` and ignored on the way back in.

Without that rule the format is ambiguous in a way nothing can resolve later: is
`status_last_surveyed_at=2026-08-01` a record of something that happened, or an
instruction to make it so? And an export taken on Tuesday still claims
`status_cataloged=yes` on Friday after Egeria was reset — a file that reads as a
record while being wrong. Letting import act on those columns would write that
fiction into the registry.

So the round-trip test here is not a convenience check. It is the one that keeps
a scorecard from becoming an instruction sheet.
"""
from __future__ import annotations

import csv

import pytest

from resource_explorer.batch_io import (
    ALL_COLUMNS,
    STATUS_COLUMNS,
    export_rows,
    parse_csv,
    plan_import,
    resource_key,
    write_csv,
)
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="sqlglot", display_name="sqlglot",
                    github_url="https://github.com/tobymao/sqlglot",
                    description="", collections=["sqlglot_docs"]))
    return reg


def _write(tmp_path, text):
    p = tmp_path / "in.csv"
    p.write_text(text, encoding="utf-8")
    return p


class TestIdentity:
    """RE's slug is derived, so the interchange format keys on the address the
    user actually knows — and matches it the way the registry does."""

    @pytest.mark.parametrize("addr", [
        "https://github.com/tobymao/sqlglot",
        "https://github.com/tobymao/sqlglot.git",
        "https://github.com/tobymao/sqlglot/",
        "HTTPS://GitHub.com/tobymao/sqlglot",
    ])
    def test_repo_urls_normalize_to_one_key(self, addr):
        assert resource_key("repo", addr) == resource_key(
            "repo", "https://github.com/tobymao/sqlglot")

    def test_different_repos_do_not_collide(self):
        assert resource_key("repo", "https://github.com/a/x") != resource_key(
            "repo", "https://github.com/b/x")


class TestAlreadyLoadedDetection:

    def test_a_registered_repo_is_recognised_however_it_is_written(self, registry, tmp_path):
        p = _write(tmp_path, "resource_type,address\n"
                             "repo,https://github.com/tobymao/sqlglot.git\n")
        plan = plan_import(registry, parse_csv(p))
        assert len(plan.already_registered) == 1
        assert not plan.to_register

    def test_a_new_repo_is_queued(self, registry, tmp_path):
        p = _write(tmp_path, "resource_type,address\nrepo,https://github.com/apache/airflow\n")
        plan = plan_import(registry, parse_csv(p))
        assert [r.address for r in plan.to_register] == ["https://github.com/apache/airflow"]

    def test_the_same_repo_twice_in_one_file_is_caught(self, registry, tmp_path):
        """Dedup has to happen within the file too, not just against the
        registry — otherwise the second row fails at import time with a
        confusing "already registered" for something registered seconds ago."""
        p = _write(tmp_path, "resource_type,address\n"
                             "repo,https://github.com/apache/airflow\n"
                             "repo,https://github.com/apache/airflow/\n")
        plan = plan_import(registry, parse_csv(p))
        assert len(plan.to_register) == 1
        assert len(plan.duplicate_in_file) == 1


class TestValidation:

    def test_a_row_without_an_address_is_invalid_not_skipped(self, registry, tmp_path):
        """Silently dropping a row from a 500-row file is how you end up with
        497 repos and no idea which three are missing."""
        p = _write(tmp_path, "resource_type,address\nrepo,\n")
        plan = plan_import(registry, parse_csv(p))
        assert len(plan.invalid) == 1 and "no address" in plan.invalid[0].errors[0]

    def test_an_unknown_disposition_is_rejected(self, registry, tmp_path):
        p = _write(tmp_path, "resource_type,address,disposition\n"
                             "repo,https://github.com/a/b,definitely-maybe\n")
        assert len(plan_import(registry, parse_csv(p)).invalid) == 1

    def test_unsupported_types_say_why_rather_than_disappearing(self, registry, tmp_path):
        p = _write(tmp_path, "resource_type,address\nfilesystem,/mnt/data\n")
        plan = plan_import(registry, parse_csv(p))
        assert len(plan.unsupported_type) == 1
        assert "credentials" in plan.unsupported_type[0].errors[0]

    def test_a_file_with_no_address_column_fails_loudly(self, tmp_path):
        p = _write(tmp_path, "name,url\nfoo,bar\n")
        with pytest.raises(ValueError, match="address"):
            parse_csv(p)

    def test_resource_type_defaults_to_repo(self, tmp_path):
        """The common case is a list of repos; requiring the column on every row
        of a hand-written file earns nothing."""
        p = _write(tmp_path, "address\nhttps://github.com/a/b\n")
        assert parse_csv(p)[0].resource_type == "repo"


class TestImportReadsIntentNeverState:
    """The rule the whole format rests on."""

    def test_status_columns_are_ignored_on_import(self, registry, tmp_path):
        """A row asserting it is registered, cataloged and surveyed must still be
        classified from the registry alone."""
        p = _write(
            tmp_path,
            "resource_type,address," + ",".join(STATUS_COLUMNS) + "\n"
            "repo,https://github.com/apache/airflow,yes,airflow,yes,ok,2026-01-01,2026-01-01,active,yes\n")
        plan = plan_import(registry, parse_csv(p))
        # It claims to be registered. It is not, so it is queued for registration.
        assert len(plan.to_register) == 1
        assert not plan.already_registered

    def test_an_exported_file_reimports_as_a_complete_no_op(self, registry, tmp_path):
        """The round-trip. Everything already exists, so nothing is queued —
        and the status_ columns the export wrote did not confuse the classifier."""
        out = tmp_path / "inv.csv"
        write_csv(export_rows(registry), out)

        plan = plan_import(registry, parse_csv(out))
        assert plan.to_register == []
        assert len(plan.already_registered) == 1
        assert plan.invalid == [] and plan.duplicate_in_file == []

    def test_intent_columns_do_survive_the_round_trip(self, registry, tmp_path):
        """The other half: what a human set must come back, or the file is not
        an inventory, only a report."""
        registry.set_disposition("https://github.com/tobymao/sqlglot", "tracking",
                                 reason="core dependency")
        out = tmp_path / "inv.csv"
        write_csv(export_rows(registry), out)

        row = parse_csv(out)[0]
        assert row.disposition == "tracking"
        assert row.disposition_reason == "core dependency"


class TestExport:

    def test_every_column_is_written_every_time(self, registry, tmp_path):
        """Columns that vary with content cannot be diffed against last week's,
        which is most of what a running scorecard is for."""
        out = tmp_path / "inv.csv"
        write_csv(export_rows(registry), out)
        with out.open(newline="") as fh:
            assert csv.DictReader(fh).fieldnames == list(ALL_COLUMNS)

    def test_observed_state_reflects_the_registry(self, registry, tmp_path):
        rows = {r["status_slug"]: r for r in export_rows(registry)}
        assert rows["sqlglot"]["status_cataloged"] == "no"      # no GUID set
        assert rows["sqlglot"]["status_indexed"] == "yes"       # has collections

        registry.set_egeria_asset_guid("sqlglot", "guid-1")
        rows = {r["status_slug"]: r for r in export_rows(registry)}
        assert rows["sqlglot"]["status_cataloged"] == "yes"

    def test_a_stale_egeria_link_is_visible_in_the_scorecard(self, registry):
        """The condition most worth seeing across a whole corpus at once."""
        registry.mark_egeria_linkage_stale("repo", "sqlglot", "guid-1", "gone")
        rows = {r["status_slug"]: r for r in export_rows(registry)}
        assert rows["sqlglot"]["status_egeria_link"] == "stale"


class TestParseText:
    """Both shapes people actually arrive with: a spreadsheet export, and a list
    pasted out of a wiki. Rejecting the second would push them back to
    registering one at a time, which is the thing this exists to stop."""

    def test_a_plain_url_list_is_accepted(self):
        from resource_explorer.batch_io import parse_csv_text

        rows = parse_csv_text("https://github.com/a/b\nhttps://github.com/c/d\n")
        assert [r.address for r in rows] == ["https://github.com/a/b", "https://github.com/c/d"]
        assert all(r.resource_type == "repo" for r in rows)

    def test_comments_and_blank_lines_are_skipped(self):
        from resource_explorer.batch_io import parse_csv_text

        rows = parse_csv_text("# batch 1\n\nhttps://github.com/a/b\n\n# end\n")
        assert [r.address for r in rows] == ["https://github.com/a/b"]

    def test_original_line_numbers_survive_filtering(self):
        """Error messages have to point at the file the user is looking at, not
        at the filtered subset."""
        from resource_explorer.batch_io import parse_csv_text

        rows = parse_csv_text("# header\n\nhttps://github.com/a/b\n")
        assert rows[0].line == 3

    def test_csv_text_keeps_its_columns(self):
        from resource_explorer.batch_io import parse_csv_text

        rows = parse_csv_text("resource_type,address,group\nrepo,https://github.com/a/b,asf\n")
        assert rows[0].group == "asf"

    def test_prose_is_flagged_rather_than_treated_as_a_url(self):
        from resource_explorer.batch_io import parse_csv_text

        rows = parse_csv_text("just some prose here\n")
        assert rows[0].errors


class TestFromListRoute:
    """The uploaded list lands in the same review table as a search — the point
    being that nothing is registered until a human selects rows."""

    @pytest.fixture
    def client(self, registry, monkeypatch):
        from fastapi.testclient import TestClient

        from resource_explorer.web.app import app

        # The route imports ProjectRegistry inside the function, so it must be
        # patched where it is defined rather than on the route module.
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry",
                            lambda *a, **kw: registry)

        async def fake_list_urls(urls, reg):
            return [{"full_name": u.rsplit("/", 2)[-2] + "/" + u.rsplit("/", 1)[-1],
                     "html_url": u, "description": "", "stars": 1, "language": "Python",
                     "license": "", "forks": 0, "archived": False, "fork": False,
                     "updated_at": ""} for u in urls]

        monkeypatch.setattr("resource_explorer.web.routes.discovery._run_list_urls",
                            fake_list_urls)
        return TestClient(app)

    def test_a_registered_repo_comes_back_marked(self, client):
        r = client.post("/api/discovery/from-list",
                        json={"text": "https://github.com/tobymao/sqlglot\n"})
        assert r.status_code == 200
        assert r.json()[0]["already_registered"] is True

    def test_a_new_repo_is_not_marked(self, client):
        r = client.post("/api/discovery/from-list",
                        json={"text": "https://github.com/apache/airflow\n"})
        assert r.json()[0]["already_registered"] is False

    def test_the_route_registers_nothing(self, client, registry):
        before = len(registry.list_all())
        client.post("/api/discovery/from-list",
                    json={"text": "https://github.com/apache/airflow\n"})
        assert len(registry.list_all()) == before

    def test_unusable_input_explains_itself(self, client):
        r = client.post("/api/discovery/from-list", json={"text": "not a url at all\n"})
        assert r.status_code == 400
        assert "address" in r.json()["detail"] or "URL" in r.json()["detail"]

    def test_an_exported_scorecard_can_be_fed_straight_back(self, client, registry):
        """The status_ columns must not confuse the parser — same round-trip
        guarantee as the CLI path."""
        from resource_explorer.batch_io import export_rows, write_csv

        import io as _io
        rows = export_rows(registry)
        buf = _io.StringIO()
        import csv as _csv

        from resource_explorer.batch_io import ALL_COLUMNS
        w = _csv.DictWriter(buf, fieldnames=list(ALL_COLUMNS))
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in ALL_COLUMNS})

        resp = client.post("/api/discovery/from-list", json={"text": buf.getvalue()})
        assert resp.status_code == 200
        assert all(x["already_registered"] for x in resp.json())
