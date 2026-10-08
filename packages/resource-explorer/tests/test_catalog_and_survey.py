"""Registering a database's SERVER with Egeria, optionally (catalog_and_survey.py).

Recording fakes only: a fake Egeria port that records every call and the placeholders it
was given, a scripted engine-action sequence, and a fake read-back. No live Egeria, no live
registry. The rules under test:

* the placeholders are exactly Egeria's, mapped from the stored record, and NO password is in
  anything recorded (requests, logs, activity rows, proof rows);
* every write is followed by a read of that GUID before a pointer is stored;
* adopt by qualifiedName: never a second server for the next database on the same host:port;
* a stale pointer is detected by a read and said plainly; a failed read is not "gone";
* a database never registered is a NEUTRAL state, not an error;
* Egeria's own sentence is shown verbatim, plus one line when it reads as a connection problem.
"""
from __future__ import annotations

import json
import logging

import pytest

from resource_explorer import catalog_and_survey as cas
from resource_explorer import native_survey_run as nsr
from resource_explorer.catalogue_gateway import database_qualified_name, server_qualified_name
from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors import technology_type_processes as ttp
from tests.test_native_survey_run import CATALOG_QN, FakePort

TECH = "PostgreSQL Relational Database"
PASSWORD = "S3cretPW!-do-not-leak"
SERVER_SURVEY_QN = "PostgreSQLSurvey::survey-postgres-server"
SERVER_NAME = "host.docker.internal:5432"
SQN = server_qualified_name(SERVER_NAME)
DQN = database_qualified_name(SERVER_NAME, "adventureworks")
SERVER_GUID = "55555555-0000-0000-0000-000000000001"
DB_GUID = "dddddddd-0000-0000-0000-000000000001"
SURVEY_ACTION = "ffffffff-0000-0000-0000-000000000001"


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.register_database(DatabaseEntity(
        slug="adventureworks", display_name="AdventureWorks", db_type="postgresql",
        host="localhost", port=5432, database_name="adventureworks",
        egeria_host="host.docker.internal", db_user="dwolfson", db_password=PASSWORD))
    reg.register_database(DatabaseEntity(
        slug="sibling", display_name="Sibling", db_type="postgresql",
        host="localhost", port=5432, database_name="sibling",
        egeria_host="host.docker.internal", db_user="dwolfson", db_password=PASSWORD))
    return reg


class RegPort(FakePort):
    """FakePort plus the registration surface. Records every call and every body."""

    def __init__(self):
        super().__init__()
        self.assets = set()
        self.elements: dict[str, str] = {}          # guid -> qualifiedName
        self.created_servers: list[dict] = []
        self.processes: list[tuple[str, dict]] = []
        self.survey_actions: dict[str, list[str]] = {}
        self.create_error: Exception | None = None
        self.process_error: Exception | None = None
        self.read_element_override = "unset"
        self.find_error: Exception | None = None

    def have(self, guid, qn):
        self.elements[guid] = qn
        self.assets.add(guid)

    def find_element(self, qn):
        self.calls.append(("find_element", qn))
        if self.find_error:
            raise self.find_error
        for g, name in self.elements.items():
            if name == qn:
                return cas.ElementBack(g, name)
        return None

    def read_element(self, guid):
        self.calls.append(("read_element", guid))
        if self.read_element_override != "unset":
            return self.read_element_override
        qn = self.elements.get(guid)
        return cas.ElementBack(guid, qn) if qn else None

    def create_server(self, placeholders):
        self.calls.append(("create_server", dict(placeholders)))
        if self.create_error:
            raise self.create_error
        self.created_servers.append(dict(placeholders))
        self.have(SERVER_GUID, SQN)
        return SERVER_GUID

    def initiate_process(self, qn, params):
        self.calls.append(("initiate_process", qn, dict(params)))
        if self.process_error:
            raise self.process_error
        self.processes.append((qn, dict(params)))
        guid = f"99999999-0000-0000-0000-{len(self.processes):012d}"
        self.actions[guid] = ("IN_PROGRESS", "")
        return guid

    def read_process(self, guid):
        self.calls.append(("read_process", guid))
        status, message = self.actions[guid]
        return nsr.ActionRead(status=status, message=message)

    def survey_actions_for(self, guid):
        self.calls.append(("survey_actions_for", guid))
        return list(self.survey_actions.get(guid, []))


def register(registry, port, slug="adventureworks"):
    return cas.register_with_egeria(registry, port, "database", slug, technology_type=TECH,
                                    submitted_by="dan")


def pointer(registry, slug="adventureworks"):
    return registry.get_database(slug).egeria_asset_guid


# ── the one function that says whether a kind has a separate server element ──

class TestServerElementDecision:
    def test_postgresql_has_one(self):
        assert ttp.server_has_separate_element("database", TECH) is True

    def test_a_kind_the_config_does_not_cover_is_none_never_a_guess(self):
        assert ttp.server_has_separate_element("filesystem", "File System Directory") is None
        assert ttp.server_has_separate_element("database", "SQLite Embedded") is None

    def test_a_kind_marked_coincident_is_false_and_says_it_is_not_built(self, tmp_path, monkeypatch):
        cfg = tmp_path / "t.yaml"
        cfg.write_text("technology_types:\n  - name: X\n    entity_type: database\n"
                       "    separate_server_element: false\n    processes: []\n")
        wiring = ttp._load_wiring(cfg)
        assert wiring[("database", "X")].separate_server is False
        entity = DatabaseEntity(slug="a", display_name="a", db_type="sqlite", host="h", port=1,
                                database_name="d", db_user="u")
        # a coincident kind says the single-step variant is not built; it never falls into the server path
        monkeypatch.setattr(cas, "server_has_separate_element", lambda *a: False)
        assert cas.wiring_reason("database", "X", entity) == cas.SINGLE_STEP_NOT_BUILT

    def test_the_row_for_an_unwired_kind_says_this_kind_is_not_wired_yet(self, registry, monkeypatch):
        entity = registry.get_database("adventureworks")
        assert "not wired yet" in cas.wiring_reason("database", "SQLite Embedded", entity)

    def test_a_record_missing_what_the_template_needs_names_what(self):
        entity = DatabaseEntity(slug="a", display_name="a", db_type="postgresql", host="", port=5432,
                                database_name="d", db_user="")
        reason = cas.wiring_reason("database", TECH, entity)
        assert "host" in reason and "database user" in reason or "user" in reason


# ── the placeholders ─────────────────────────────────────────────────────────

class TestPlaceholders:
    def test_the_server_placeholders_are_exactly_egeria_server_template_list(self, registry):
        ph = cas.server_placeholders(registry.get_database("adventureworks"))
        # PostgresPlaceholderProperty.getPostgresServerPlaceholderPropertyTypes()
        assert set(ph) == {"hostIdentifier", "portNumber", "serverName", "description",
                           "versionIdentifier", "resourceName", "secretsStorePathName",
                           "secretsCollectionName"}
        assert ph["hostIdentifier"] == "host.docker.internal" and ph["portNumber"] == "5432"
        assert ph["serverName"] == SERVER_NAME == ph["resourceName"]
        assert ph["secretsCollectionName"] == "adventureworks::PostgreSQL Secret"

    def test_the_database_placeholders_are_exactly_egeria_database_template_list(self, registry):
        ph = cas.database_placeholders(registry.get_database("adventureworks"))
        # PostgresPlaceholderProperty.getPostgresDatabasePlaceholderPropertyTypes()
        assert set(ph) == {"hostIdentifier", "portNumber", "serverName", "versionIdentifier",
                           "databaseName", "databaseDescription", "secretsStorePathName",
                           "secretsCollectionName"}
        assert ph["databaseName"] == "adventureworks" and ph["serverName"] == SERVER_NAME

    def test_there_is_no_password_or_user_placeholder(self, registry):
        for ph in (cas.server_placeholders(registry.get_database("adventureworks")),
                   cas.database_placeholders(registry.get_database("adventureworks"))):
            assert PASSWORD not in json.dumps(ph)
            assert not {"databasePassword", "databaseUserId", "clearPassword", "userId"} & set(ph)


# ── the press ────────────────────────────────────────────────────────────────

class TestRegister:
    def test_it_creates_the_server_reads_it_back_and_only_then_stores_the_pointer(self, registry):
        port = RegPort()
        register(registry, port)
        names = [c[0] for c in port.calls]
        assert names.index("create_server") < names.index("read_element")
        assert registry.get_setting(cas.server_pointer_key(SERVER_NAME)) == SERVER_GUID
        created = port.created_servers[0]
        assert created == cas.server_placeholders(registry.get_database("adventureworks"))

    def test_a_server_that_reads_back_wrong_stores_no_pointer(self, registry):
        port = RegPort()
        port.read_element_override = cas.ElementBack(SERVER_GUID, "PostgreSQL Server::someone-else")
        with pytest.raises(nsr.NativeSurveyError, match="not 'PostgreSQL Server::host.docker"):
            register(registry, port)
        assert registry.get_setting(cas.server_pointer_key(SERVER_NAME)) is None
        assert pointer(registry) == ""

    def test_a_server_that_does_not_read_back_stores_no_pointer(self, registry):
        port = RegPort()
        port.read_element_override = None
        with pytest.raises(nsr.NativeSurveyError, match="no server with the GUID"):
            register(registry, port)
        assert registry.get_setting(cas.server_pointer_key(SERVER_NAME)) is None

    def test_the_server_survey_is_submitted_on_the_server_with_the_native_machinery(self, registry):
        port = RegPort()
        register(registry, port)
        init = [c for c in port.calls if c[0] == "initiate"]
        assert init == [("initiate", SERVER_SURVEY_QN, "serverToSurvey", SERVER_GUID)]
        runs = registry.list_native_survey_runs("database", "adventureworks", SERVER_SURVEY_QN)
        assert runs and runs[0]["engine_action_guid"].startswith("eeeeeeee")

    def test_the_database_process_gets_the_database_placeholders_and_is_recorded(self, registry):
        port = RegPort()
        out = register(registry, port)
        (qn, params), = port.processes
        assert qn == CATALOG_QN
        assert params == cas.database_placeholders(registry.get_database("adventureworks"))
        run = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        assert run["engine_action_guid"] == out["database"]["process_instance_guid"]
        assert run["submitted_by"] == "dan"
        # the database is NOT pointed at until Egeria shows it and it is read back
        assert pointer(registry) == ""

    def test_when_egeria_shows_the_database_it_is_read_back_by_guid_before_the_pointer(self, registry):
        port = RegPort()
        register(registry, port)
        run = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        port.have(DB_GUID, DQN)
        port.survey_actions[DB_GUID] = [SURVEY_ACTION]
        port.actions[run["engine_action_guid"]] = ("COMPLETED", "")
        before = len(port.calls)
        state = cas.refresh_registration_run(registry, port, run, entity_type="database",
                                             slug="adventureworks")
        after = [c for c in port.calls[before:]]
        assert [c[0] for c in after].index("read_element") >= 0
        assert pointer(registry) == DB_GUID
        assert state["state"] == cas.REGISTERED
        # the survey Egeria's process started now shows under the ordinary database-survey row
        sruns = registry.list_native_survey_runs("database", "adventureworks", cas.DATABASE_SURVEY_QN)
        assert [r["engine_action_guid"] for r in sruns] == [SURVEY_ACTION]
        # reading again records nothing twice
        cas.refresh_registration_run(registry, port, run, entity_type="database", slug="adventureworks")
        assert len(registry.list_native_survey_runs(
            "database", "adventureworks", cas.DATABASE_SURVEY_QN)) == 1

    def test_a_database_found_by_name_that_does_not_read_back_stores_no_pointer(self, registry):
        port = RegPort()
        register(registry, port)
        run = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        port.have(DB_GUID, DQN)
        port.actions[run["engine_action_guid"]] = ("COMPLETED", "")
        port.read_element_override = None            # found by name, but the GUID read says there is none
        state = cas.refresh_registration_run(registry, port, run, entity_type="database",
                                             slug="adventureworks")
        assert pointer(registry) == "" and state["state"] == cas.AWAITING_REGISTRATION
        row = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        assert "database read failed" in row["engine_action_read_error"]

    def test_ambiguous_survey_actions_are_not_chosen_among(self, registry):
        port = RegPort()
        register(registry, port)
        run = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        port.have(DB_GUID, DQN)
        port.survey_actions[DB_GUID] = [SURVEY_ACTION, "ffffffff-0000-0000-0000-000000000002"]
        port.actions[run["engine_action_guid"]] = ("COMPLETED", "")
        cas.refresh_registration_run(registry, port, run, entity_type="database", slug="adventureworks")
        assert registry.list_native_survey_runs("database", "adventureworks", cas.DATABASE_SURVEY_QN) == []

    def test_a_completed_process_with_no_database_in_egeria_is_awaiting_not_registered(self, registry):
        port = RegPort()
        register(registry, port)
        run = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        port.actions[run["engine_action_guid"]] = ("COMPLETED", "")
        state = cas.refresh_registration_run(registry, port, run, entity_type="database",
                                             slug="adventureworks")
        assert state["state"] == cas.AWAITING_REGISTRATION and pointer(registry) == ""


class TestAdoptByQualifiedName:
    def test_an_existing_server_is_adopted_not_created(self, registry):
        port = RegPort()
        port.have(SERVER_GUID, SQN)
        out = register(registry, port)
        assert out["server"]["how"] == "adopted" and port.created_servers == []

    def test_the_next_database_on_the_same_server_makes_no_second_server(self, registry):
        port = RegPort()
        register(registry, port, "adventureworks")
        register(registry, port, "sibling")
        assert len(port.created_servers) == 1
        assert [n for g, n in port.elements.items() if n.startswith("PostgreSQL Server::")] == [SQN]

    def test_an_existing_database_is_adopted_and_no_process_is_submitted(self, registry):
        port = RegPort()
        port.have(SERVER_GUID, SQN)
        port.have(DB_GUID, DQN)
        out = register(registry, port)
        assert out["database"]["how"] == "adopted" and port.processes == []
        assert pointer(registry) == DB_GUID

    def test_registering_twice_does_not_resubmit_while_in_flight(self, registry):
        port = RegPort()
        register(registry, port)
        with pytest.raises(nsr.NativeSurveyBusy):
            register(registry, port)
        assert len(port.processes) == 1


class TestFailureSaysEgeriasSentence:
    def test_a_refused_process_submission_is_egerias_sentence_and_writes_no_database_pointer(self, registry):
        port = RegPort()
        port.process_error = RuntimeError("OMAG-GOVERNANCE-400-011 The process is not recognized")
        with pytest.raises(nsr.NativeSurveyError) as exc:
            register(registry, port)
        assert "OMAG-GOVERNANCE-400-011 The process is not recognized" in str(exc.value)
        assert pointer(registry) == ""
        run = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        assert run["engine_action_guid"] == "" and "not recognized" in run["submit_error"]
        # what was proven before the failure stays proven: the server was read back and pointed at
        assert registry.get_setting(cas.server_pointer_key(SERVER_NAME)) == SERVER_GUID

    def test_a_failed_server_create_says_egerias_sentence_and_writes_nothing(self, registry):
        port = RegPort()
        port.create_error = RuntimeError("OMAG-REPOSITORY-500 template boom")
        with pytest.raises(nsr.NativeSurveyError, match="template boom"):
            register(registry, port)
        assert registry.get_setting(cas.server_pointer_key(SERVER_NAME)) is None
        assert port.processes == []

    def test_egerias_sentence_is_not_cut(self, registry):
        port = RegPort()
        long = "x" * 900 + " FATAL: role \"surveyor\" does not exist"
        port.process_error = RuntimeError(long)
        with pytest.raises(nsr.NativeSurveyError) as exc:
            register(registry, port)
        assert str(exc.value).endswith('role "surveyor" does not exist')

    def test_a_server_survey_refused_does_not_undo_the_registration(self, registry):
        port = RegPort()
        port.initiate_error = RuntimeError("survey service not recognized")
        out = register(registry, port)
        assert "not recognized" in out["server_survey_error"]
        assert registry.get_setting(cas.server_pointer_key(SERVER_NAME)) == SERVER_GUID


# ── a connection problem: Egeria's sentence verbatim plus one line ───────────

class TestReachNote:
    def _failed(self, message):
        return {"state": nsr.FAILED, "message": message, "error": ""}

    def test_a_refused_connection_gets_the_one_extra_line(self):
        state = self._failed("Connection to host.docker.internal:5432 refused")
        assert cas.reach_note_for(state) == (
            "Egeria connects from its own platform; RE can still survey this database itself")

    def test_a_non_connection_failure_gets_none(self):
        assert cas.reach_note_for(self._failed("The annotation store rejected a duplicate")) == ""

    def test_a_row_carries_egerias_sentence_unchanged_and_the_note(self, registry):
        port = RegPort()
        port.have(SERVER_GUID, SQN)
        register(registry, port)
        sruns = registry.list_native_survey_runs("database", "adventureworks", SERVER_SURVEY_QN)
        guid = sruns[0]["engine_action_guid"]
        sentence = "FATAL: password authentication failed; Connection refused (UnknownHost)"
        port.actions[guid] = ("FAILED", sentence)
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        rows = {r["qualified_name"]: r
                for r in nsr.native_survey_rows(registry, "database", "adventureworks", TECH)}
        row = rows[SERVER_SURVEY_QN]
        assert row["run"]["message"] == sentence
        assert row["reach_note"] == cas.REACH_NOTE
        # RE's own survey is unaffected: the database-survey row is as it was, not run, no note
        assert rows[cas.DATABASE_SURVEY_QN]["reach_note"] == ""
        assert rows[cas.DATABASE_SURVEY_QN]["run"]["state"] == nsr.NOT_RUN


# ── never registered: neutral; stale: said plainly ───────────────────────────

class TestNeutralAndStale:
    def test_a_never_registered_database_is_neutral_not_an_error(self, registry):
        rows = {r["qualified_name"]: r
                for r in nsr.native_survey_rows(registry, "database", "adventureworks", TECH)}
        survey = rows[cas.DATABASE_SURVEY_QN]
        assert survey["neutral"] is True and survey["stale"] is False
        assert survey["cannot_run_reason"] == cas.NOT_REGISTERED_WORDS
        assert "optional" in survey["cannot_run_reason"]
        assert survey["run"]["state"] == nsr.NOT_RUN and survey["run"]["error"] == ""
        assert survey["register"]["available"] is False       # the one control is on the catalog row
        catalog = rows[CATALOG_QN]
        assert catalog["run"]["state"] == cas.NOT_REGISTERED
        assert catalog["register"]["available"] is True
        assert not catalog["in_flight"]
        server = rows[SERVER_SURVEY_QN]
        assert server["neutral"] and server["cannot_run_reason"] == cas.SERVER_NOT_REGISTERED_WORDS

    def test_a_pointer_egeria_says_is_gone_is_stale_and_offers_the_control(self, registry):
        registry.set_database_egeria_guid("adventureworks", DB_GUID)
        port = RegPort()
        pointers = cas.check_pointers(registry, port, "database", "adventureworks")
        assert pointers["database"] == "gone"
        rows = {r["qualified_name"]: r for r in nsr.native_survey_rows(
            registry, "database", "adventureworks", TECH, pointers=pointers)}
        survey = rows[cas.DATABASE_SURVEY_QN]
        assert survey["stale"] is True and survey["neutral"] is False
        assert survey["cannot_run_reason"] == cas.STALE_WORDS == (
            "the Egeria asset RE had stored no longer exists")
        assert survey["register"]["available"] and survey["register"]["label"] == cas.REGISTER_LABEL
        assert rows[CATALOG_QN]["stale"] is True and rows[CATALOG_QN]["run"]["state"] == cas.NOT_REGISTERED

    def test_a_failed_read_is_unreadable_never_gone(self, registry):
        registry.set_database_egeria_guid("adventureworks", DB_GUID)
        port = RegPort()

        def boom(guid):
            raise RuntimeError("Egeria is unreachable")
        port.asset_exists = boom
        pointers = cas.check_pointers(registry, port, "database", "adventureworks")
        assert pointers["database"] == "unreadable" and "unreachable" in pointers["error"]
        rows = {r["qualified_name"]: r for r in nsr.native_survey_rows(
            registry, "database", "adventureworks", TECH, pointers=pointers)}
        assert rows[cas.DATABASE_SURVEY_QN]["stale"] is False

    def test_a_pointer_that_resolves_is_not_stale(self, registry):
        registry.set_database_egeria_guid("adventureworks", DB_GUID)
        port = RegPort()
        port.assets.add(DB_GUID)
        assert cas.check_pointers(registry, port, "database", "adventureworks")["database"] == "resolves"

    def test_running_a_survey_on_a_gone_asset_is_the_stale_error_and_submits_nothing(self, registry):
        registry.set_database_egeria_guid("adventureworks", DB_GUID)
        port = RegPort()
        with pytest.raises(nsr.NativeSurveyStale, match="no longer exists"):
            nsr.submit_native_survey(registry, port, "database", "adventureworks",
                                     cas.DATABASE_SURVEY_QN, technology_type=TECH)
        assert not [c for c in port.calls if c[0] == "initiate"]

    def test_the_old_sentence_and_the_old_locked_wording_are_gone_from_the_source(self):
        import pathlib
        root = pathlib.Path(nsr.__file__).parent
        text = "".join(p.read_text() for p in (root / "native_survey_run.py", root / "catalog_and_survey.py",
                                                root / "web/routes/native_surveys.py"))
        text += (root / "configdata/technology_type_processes.yaml").read_text()
        assert "Publish the resource to Egeria again" not in text
        assert "does not collect those template" not in text
        assert "RE cannot run this one" not in text


# ── credentials never travel ─────────────────────────────────────────────────

class TestNoPasswordAnywhere:
    def test_the_password_is_in_no_request_no_log_no_proof_row(self, registry, caplog):
        caplog.set_level(logging.DEBUG)
        port = RegPort()
        port.process_error = RuntimeError(f"jdbc failed for password {PASSWORD}")
        with pytest.raises(nsr.NativeSurveyError):
            register(registry, port)
        recorded = json.dumps(port.calls, default=str)
        assert PASSWORD not in recorded
        assert PASSWORD not in caplog.text
        with registry._conn() as conn:
            dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM step_runs").fetchall()],
                              default=str)
            settings = json.dumps([dict(r) for r in conn.execute("SELECT * FROM app_settings").fetchall()],
                                  default=str)
        assert PASSWORD not in dump and PASSWORD not in settings

    def test_an_absent_collection_with_a_writable_path_is_filled_by_the_existing_projection(
            self, registry, tmp_path, monkeypatch):
        path = str(tmp_path / "s.omsecrets")
        monkeypatch.setattr("resource_explorer.omsecrets_store.local_path", lambda: path)
        port = RegPort()
        register(registry, port)
        from resource_explorer import omsecrets_store
        assert omsecrets_store.has_collection("adventureworks::PostgreSQL Secret", path=path)
        assert PASSWORD not in json.dumps(port.calls, default=str)

    def test_an_absent_collection_that_cannot_be_filled_refuses_with_the_exact_reason(
            self, registry, tmp_path, monkeypatch):
        path = str(tmp_path / "s.omsecrets")
        monkeypatch.setattr("resource_explorer.omsecrets_store.local_path", lambda: path)
        monkeypatch.setattr("resource_explorer.omsecrets_reproject.reproject", lambda *a, **k: [])
        port = RegPort()
        with pytest.raises(cas.RegistrationRefused, match="no credentials for this database"):
            register(registry, port)
        assert port.calls == []


# ── the databases a server survey found ──────────────────────────────────────

class TestDiscoveredDatabases:
    def _complete_server_survey(self, registry, port):
        port.have(SERVER_GUID, SQN)
        register(registry, port)
        guid = registry.list_native_survey_runs("database", "adventureworks", SERVER_SURVEY_QN)[0][
            "engine_action_guid"]

        def ann(i, name, type_="Capture Database Measurements"):
            return {"guid": f"a{i}", "annotation_type": type_, "summary": "s",
                    "detail": {"qualified_name": f"Annotation::{type_}::{name}::"
                               "11111111-2222-3333-4444-555555555555",
                               "resource_properties": {"Database Name": name} if i != 3 else {}}}
        port.finish(guid, report="rep-s", annotations=[
            ann(1, "adventureworks"), ann(2, "sibling"), ann(3, "unknown_db"),
            {"guid": "a9", "annotation_type": "Capture Database Table Measurements", "summary": "t",
             "detail": {"qualified_name": "Annotation::T::notadb::11111111-2222-3333-4444-555555555555"}}])
        nsr.refresh_resource(registry, port, "database", "adventureworks")

    def test_names_are_exactly_what_egeria_reported_and_only_from_database_annotations(self, registry):
        port = RegPort()
        self._complete_server_survey(registry, port)
        rows = {r["qualified_name"]: r
                for r in nsr.native_survey_rows(registry, "database", "adventureworks", TECH)}
        found = {d["name"]: d for d in rows[SERVER_SURVEY_QN]["discovered"]}
        assert set(found) == {"adventureworks", "sibling", "unknown_db"}      # not "notadb"
        # one RE has registered and Egeria has no asset for: found, not yet cataloged, with the control
        assert found["sibling"]["state"] == "found" and found["sibling"]["re_slug"] == "sibling"
        assert found["sibling"]["control"] == cas.REGISTER_LABEL
        # one RE does not have: reported, no control (the slice does not widen into registering it)
        assert found["unknown_db"]["re_slug"] == "" and found["unknown_db"]["control"] == ""

    def test_a_database_with_an_egeria_pointer_is_cataloged(self, registry):
        port = RegPort()
        registry.set_database_egeria_guid("sibling", DB_GUID)
        self._complete_server_survey(registry, port)
        rows = {r["qualified_name"]: r
                for r in nsr.native_survey_rows(registry, "database", "adventureworks", TECH)}
        found = {d["name"]: d for d in rows[SERVER_SURVEY_QN]["discovered"]}
        assert found["sibling"]["state"] == "cataloged" and found["sibling"]["control"] == ""

    def test_before_a_complete_server_survey_nothing_is_listed_as_found(self, registry):
        rows = {r["qualified_name"]: r
                for r in nsr.native_survey_rows(registry, "database", "adventureworks", TECH)}
        assert rows[SERVER_SURVEY_QN]["discovered"] == []


# ── the sweep and the poll leave a finished registration alone ───────────────

class TestSweep:
    def test_a_registered_database_costs_no_egeria_call_on_a_sweep(self, registry):
        port = RegPort()
        register(registry, port)
        run = registry.list_native_survey_runs("database", "adventureworks", CATALOG_QN)[0]
        port.have(DB_GUID, DQN)
        port.actions[run["engine_action_guid"]] = ("COMPLETED", "")
        nsr.refresh_run(registry, port, run, entity_type="database", slug="adventureworks")
        port.calls.clear()
        # the server survey is still in flight; the registration is finished and is not re-read
        nsr.sweep_in_flight(registry, port)
        assert not [c for c in port.calls if c[0] == "read_process"]
