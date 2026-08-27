import pytest

from resource_explorer.surveyors.survey_definition_reader import (
    SurveyDefinitionReader,
    SurveyDefinitionReaderError,
    UnsupportedSurveyDefinitionError,
)

# Fixtures below match the real GovernanceOfficer.get_governance_action_process_graph
# (renamed from get_governance_process_graph in an upcoming pyegeria release)
# response shape, confirmed against a live qs-view-server for both a single-step
# and a two-step chained Survey Definition (2026-07-07/08): a flat node list
# ("firstProcessStep" + "nextProcessSteps") plus a separate flat edge list
# ("processStepLinks", keyed by GUID via "previousProcessStep"/"nextProcessStep").
# Step properties live under "processStepProperties" (not "properties" — only
# the process element itself uses that).


def _step_element(guid, qualified_name, additional_properties=None, display_name=None):
    return {
        "elementHeader": {"guid": guid},
        "processStepProperties": {
            "qualifiedName": qualified_name,
            "displayName": display_name or qualified_name,
            "additionalProperties": additional_properties or {},
        },
    }


def _link(prev_guid, next_guid, guard=None, mandatory_guard=False):
    link = {
        "previousProcessStep": {"guid": prev_guid},
        "nextProcessStep": {"guid": next_guid},
        "nextProcessStepLinkGUID": "link-guid",
        "mandatoryGuard": mandatory_guard,
    }
    if guard is not None:
        link["guard"] = guard
    return link


def _graph(process_guid, qualified_name, additional_properties=None,
           first_step=None, next_steps=None, links=None):
    graph = {
        "governanceActionProcess": {
            "elementHeader": {"guid": process_guid},
            "properties": {
                "qualifiedName": qualified_name,
                "displayName": qualified_name,
                "additionalProperties": additional_properties or {},
            },
        },
    }
    if first_step is not None:
        graph["firstProcessStep"] = {"element": first_step, "linkGUID": "first-link-guid"}
    if next_steps is not None:
        graph["nextProcessSteps"] = next_steps
    if links is not None:
        graph["processStepLinks"] = links
    return graph


def _reader() -> SurveyDefinitionReader:
    # _parse_graph is side-effect-free and needs no live connection/pyegeria client.
    return SurveyDefinitionReader()


def test_parse_single_step_graph():
    step = _step_element(
        "step-1", "GovActionProcessStep::Survey::SchemaAndStats",
        additional_properties={"executes_at": "resource-explorer", "re_analysis_step": "postgres_schema_and_stats"},
    )
    graph = _graph(
        "proc-1", "GovActionProcess::Survey",
        additional_properties={"supported_technology_type": "PostgreSQL Database"},
        first_step=step,
    )

    survey_def = _reader()._parse_graph(graph)

    assert survey_def.process_guid == "proc-1"
    assert survey_def.supported_technology_type == "PostgreSQL Database"
    assert len(survey_def.steps) == 1
    assert survey_def.steps[0].guid == "step-1"
    assert survey_def.steps[0].executes_at == "resource-explorer"
    assert survey_def.steps[0].re_analysis_step == "postgres_schema_and_stats"
    assert survey_def.survey_kind is None  # not present in additional_properties above


def test_parse_survey_kind_when_present():
    step = _step_element(
        "step-1", "GovActionProcessStep::Survey::Step",
        additional_properties={"executes_at": "resource-explorer"},
    )
    graph = _graph(
        "proc-1", "GovActionProcess::Survey",
        additional_properties={"supported_technology_type": "Git Repository", "survey_kind": "discovery"},
        first_step=step,
    )

    survey_def = _reader()._parse_graph(graph)

    assert survey_def.survey_kind == "discovery"


def test_parse_linear_two_step_graph():
    step1 = _step_element(
        "step-1", "GovActionProcessStep::Survey::SchemaAndStats",
        additional_properties={"executes_at": "resource-explorer", "re_analysis_step": "postgres_schema_and_stats"},
    )
    step2 = _step_element(
        "step-2", "GovActionProcessStep::Survey::RowCountSnapshot",
        additional_properties={"executes_at": "egeria"},
    )
    graph = _graph(
        "proc-1", "GovActionProcess::Survey",
        additional_properties={"supported_technology_type": "PostgreSQL Database"},
        first_step=step1,
        next_steps=[step2],
        links=[_link("step-1", "step-2", mandatory_guard=False)],
    )

    survey_def = _reader()._parse_graph(graph)

    assert [s.guid for s in survey_def.steps] == ["step-1", "step-2"]
    assert survey_def.steps[1].executes_at == "egeria"


def test_parse_graph_with_no_first_step():
    graph = _graph("proc-empty", "GovActionProcess::Empty")
    survey_def = _reader()._parse_graph(graph)
    assert survey_def.steps == []


def test_a_branching_definition_parses_with_its_guards_intact():
    """This raised UnsupportedSurveyDefinitionError until 2026-08-26.

    Refusing was honest while nothing could run a branch, but it made a
    branching definition unreadable as well as unrunnable — not displayable,
    not diffable against its authored document, not repairable. The plan
    (survey_execution_plan) and the Prefect flow can both express and run one,
    so the reader was the last thing in the way.
    """
    step1 = _step_element("step-1", "Step::First", additional_properties={"executes_at": "resource-explorer"})
    branch_a = _step_element("a", "Step::A", additional_properties={"executes_at": "resource-explorer"})
    branch_b = _step_element("b", "Step::B", additional_properties={"executes_at": "resource-explorer"})
    graph = _graph(
        "proc-branch", "GovActionProcess::Branching",
        first_step=step1,
        next_steps=[branch_a, branch_b],
        links=[_link("step-1", "a", guard="ok"), _link("step-1", "b", guard="not-ok")],
    )

    survey_def = _reader()._parse_graph(graph)

    assert [s.qualified_name for s in survey_def.steps][0] == "Step::First"
    assert {s.qualified_name for s in survey_def.steps} == {"Step::First", "Step::A", "Step::B"}
    # The guards are what make it a branch rather than an ambiguous chain, and
    # they are what the executor routes on.
    assert {(l.guard) for l in survey_def.links} == {"ok", "not-ok"}
    assert survey_def.unreachable_step_guids == []


def test_a_cycle_is_still_rejected():
    """A branch is a shape that can be ordered; a cycle is one that cannot be,
    and any order for it would be a fiction."""
    step1 = _step_element("step-1", "Step::First", additional_properties={"executes_at": "resource-explorer"})
    step2 = _step_element("step-2", "Step::Second", additional_properties={"executes_at": "resource-explorer"})
    graph = _graph(
        "proc-cycle", "GovActionProcess::Cyclic",
        first_step=step1, next_steps=[step2],
        links=[_link("step-1", "step-2"), _link("step-2", "step-1")],
    )

    with pytest.raises(UnsupportedSurveyDefinitionError):
        _reader()._parse_graph(graph)


def test_missing_executes_at_is_rejected():
    step1 = _step_element("step-1", "Step::NoExecutesAt", additional_properties={})
    graph = _graph("proc-missing", "GovActionProcess::Missing", first_step=step1)

    with pytest.raises(SurveyDefinitionReaderError):
        _reader()._parse_graph(graph)


def test_unrecognized_executes_at_value_parses_fine():
    """The reader only rejects unsupported *shapes* (branching, missing keys) —
    an unfamiliar-but-well-formed executes_at value (e.g. a future engine like
    Airflow) is not the reader's job to reject; that's the executor's call."""
    step1 = _step_element(
        "step-1", "Step::Airflow",
        additional_properties={"executes_at": "airflow", "re_analysis_step": "some_dag"},
    )
    graph = _graph("proc-airflow", "GovActionProcess::Airflow", first_step=step1)

    survey_def = _reader()._parse_graph(graph)
    assert survey_def.steps[0].executes_at == "airflow"


def test_cycle_is_rejected():
    step1 = _step_element("step-1", "Step::One", additional_properties={"executes_at": "egeria"})
    step2 = _step_element("step-2", "Step::Two", additional_properties={"executes_at": "egeria"})
    graph = _graph(
        "proc-cycle", "GovActionProcess::Cycle",
        first_step=step1,
        next_steps=[step2],
        links=[_link("step-1", "step-2"), _link("step-2", "step-1")],  # cycle back to step1
    )

    with pytest.raises(UnsupportedSurveyDefinitionError):
        _reader()._parse_graph(graph)


class _FakeGovernanceOfficer:
    def __init__(self, results):
        self._results = results
        self.find_governance_definitions_calls = 0

    def find_governance_definitions(self, **_kwargs):
        self.find_governance_definitions_calls += 1
        return self._results


def _reader_with_fake_results(results) -> SurveyDefinitionReader:
    from resource_explorer.surveyors import survey_definition_reader as sdr

    sdr.clear_caches()  # D3's module-level cache would otherwise leak stale results across tests
    reader = _reader()
    reader._governance_officer = _FakeGovernanceOfficer(results)  # short-circuits connect()
    return reader


def _governance_process_result(qualified_name, technology_type, survey_kind=None, guid="g"):
    additional = {"supported_technology_type": technology_type}
    if survey_kind is not None:
        additional["survey_kind"] = survey_kind
    return {
        "properties": {"qualifiedName": qualified_name, "displayName": qualified_name, "additionalProperties": additional},
        "elementHeader": {"guid": guid},
    }


class TestFindCandidateProcessGuidsSurveyKindFilter:
    """Analysis-step Egeria registration plan D1 (survey_kind filtering) —
    docs/discovery-automate-project-context-plan.md Part 1."""

    def test_no_survey_kind_filter_returns_everything_matching_technology_type(self):
        results = [
            _governance_process_result("GovActionProcess::A", "Git Repository", survey_kind="discovery"),
            _governance_process_result("GovActionProcess::B", "Git Repository", survey_kind="automate_full"),
            _governance_process_result("GovActionProcess::C", "PostgreSQL Database", survey_kind="discovery"),
        ]
        reader = _reader_with_fake_results(results)
        candidates = reader.find_candidate_process_guids("Git Repository")
        assert {c["qualified_name"] for c in candidates} == {"GovActionProcess::A", "GovActionProcess::B"}

    def test_survey_kind_filter_narrows_to_exact_match(self):
        results = [
            _governance_process_result("GovActionProcess::A", "Git Repository", survey_kind="discovery"),
            _governance_process_result("GovActionProcess::B", "Git Repository", survey_kind="automate_full"),
        ]
        reader = _reader_with_fake_results(results)
        candidates = reader.find_candidate_process_guids("Git Repository", survey_kind="discovery")
        assert [c["qualified_name"] for c in candidates] == ["GovActionProcess::A"]

    def test_survey_kind_filter_excludes_definitions_with_no_survey_kind_at_all(self):
        # A Survey Definition authored before this convention existed (no
        # survey_kind key at all) must not leak into a kind-filtered list.
        results = [_governance_process_result("GovActionProcess::Legacy", "Git Repository", survey_kind=None)]
        reader = _reader_with_fake_results(results)
        assert reader.find_candidate_process_guids("Git Repository", survey_kind="discovery") == []
        # ...but shows up fine when no filter is applied (backward compatibility).
        assert len(reader.find_candidate_process_guids("Git Repository")) == 1


class TestFindCandidateProcessGuidsCaching:
    """D3 (docs/survey-question-context-plan.md) — the full search_string="*"
    scan is cached short-TTL, same as D2's scoped path."""

    def test_second_call_with_same_args_does_not_hit_egeria_again(self):
        results = [_governance_process_result("GovActionProcess::A", "Git Repository")]
        reader = _reader_with_fake_results(results)
        reader.find_candidate_process_guids("Git Repository")
        reader.find_candidate_process_guids("Git Repository")
        assert reader._governance_officer.find_governance_definitions_calls == 1

    def test_different_technology_type_is_not_cache_polluted(self):
        results = [
            _governance_process_result("GovActionProcess::A", "Git Repository"),
            _governance_process_result("GovActionProcess::B", "PostgreSQL Database"),
        ]
        reader = _reader_with_fake_results(results)
        repo_candidates = reader.find_candidate_process_guids("Git Repository")
        db_candidates = reader.find_candidate_process_guids("PostgreSQL Database")
        assert [c["qualified_name"] for c in repo_candidates] == ["GovActionProcess::A"]
        assert [c["qualified_name"] for c in db_candidates] == ["GovActionProcess::B"]
        assert reader._governance_officer.find_governance_definitions_calls == 2


class _FakeClassificationExplorer:
    """Fake for ClassificationExplorer — records call counts so tests can
    assert D3's caching actually avoids a second live call."""

    def __init__(self, guid_by_name=None, scoped_elements_by_guid=None):
        self._guid_by_name = guid_by_name or {}
        self._scoped_elements_by_guid = scoped_elements_by_guid or {}
        self.get_guid_for_name_calls = 0
        self.get_scoped_elements_calls = 0

    def create_egeria_bearer_token(self, *_a, **_kw):
        pass

    def get_guid_for_name(self, name, **_kw):
        self.get_guid_for_name_calls += 1
        return self._guid_by_name.get(name)

    def get_scoped_elements(self, scope_guid, **_kw):
        self.get_scoped_elements_calls += 1
        return self._scoped_elements_by_guid.get(scope_guid, [])


def _reader_with_fake_classification_explorer(fake) -> SurveyDefinitionReader:
    from resource_explorer.surveyors import survey_definition_reader as sdr

    sdr.clear_caches()
    reader = _reader()
    reader._classification_explorer = fake  # short-circuits _connect_classification_explorer()
    return reader


class TestResolveQuestionGuid:
    """D2 (docs/survey-question-context-plan.md) — Question name -> GUID
    resolution via ClassificationExplorer.get_guid_for_name, long-TTL cached."""

    def test_resolves_known_question(self):
        fake = _FakeClassificationExplorer(guid_by_name={"Is this repository actively maintained?": "q-guid-1"})
        reader = _reader_with_fake_classification_explorer(fake)
        assert reader.resolve_question_guid("Is this repository actively maintained?") == "q-guid-1"

    def test_unknown_question_returns_none_not_raises(self):
        fake = _FakeClassificationExplorer()
        reader = _reader_with_fake_classification_explorer(fake)
        assert reader.resolve_question_guid("Some question never authored in Egeria") is None

    def test_result_is_cached_across_calls(self):
        fake = _FakeClassificationExplorer(guid_by_name={"Q": "guid-1"})
        reader = _reader_with_fake_classification_explorer(fake)
        assert reader.resolve_question_guid("Q") == "guid-1"
        assert reader.resolve_question_guid("Q") == "guid-1"
        assert fake.get_guid_for_name_calls == 1

    def test_lookup_error_returns_none_not_raises(self):
        class _Raising(_FakeClassificationExplorer):
            def get_guid_for_name(self, name, **_kw):
                raise RuntimeError("boom")

        reader = _reader_with_fake_classification_explorer(_Raising())
        assert reader.resolve_question_guid("Q") is None

    def test_pyegeria_not_found_sentence_is_not_treated_as_a_guid(self):
        """Regression: pyegeria signals "no match" by returning the *string*
        "No elements found", not None — a truthy value that passed straight
        through the old `or None` guard and was handed onward as if it were a
        GUID. It then reached get_scoped_elements() as a URL path segment, 404'd,
        and the caller's broad except swallowed it — silently downgrading the
        scoped fast path to the full scan on every call.

        This escaped the suite because the fake above returns None on a miss,
        i.e. it was better behaved than the real library; this test pins the
        real behavior instead."""
        fake = _FakeClassificationExplorer(guid_by_name={"Q": "No elements found"})
        reader = _reader_with_fake_classification_explorer(fake)
        assert reader.resolve_question_guid("Q") is None

    def test_non_string_lookup_result_is_not_treated_as_a_guid(self):
        fake = _FakeClassificationExplorer(guid_by_name={"Q": {"guid": "x"}})
        reader = _reader_with_fake_classification_explorer(fake)
        assert reader.resolve_question_guid("Q") is None


class TestFindCandidateProcessGuidsByQuestions:
    """D2 — scoped candidate lookup via ClassificationExplorer.get_scoped_elements,
    replacing the search_string="*" full scan for a phase/perspective-narrowed
    query. D3 — short-TTL cached."""

    def _survey_definition_element(self, qualified_name, technology_type, survey_kind=None, guid="sd-guid"):
        additional = {"supported_technology_type": technology_type}
        if survey_kind is not None:
            additional["survey_kind"] = survey_kind
        return {
            "properties": {"qualifiedName": qualified_name, "displayName": qualified_name, "additionalProperties": additional},
            "elementHeader": {"guid": guid},
        }

    def test_no_resolvable_question_returns_empty(self):
        fake = _FakeClassificationExplorer()
        reader = _reader_with_fake_classification_explorer(fake)
        assert reader.find_candidate_process_guids_by_questions(["Unknown question"], "Git Repository") == []
        # Never even attempts a scoped-elements call with no resolvable guid.
        assert fake.get_scoped_elements_calls == 0

    def test_returns_scoped_survey_definitions_matching_technology_type(self):
        fake = _FakeClassificationExplorer(
            guid_by_name={"Q1": "q1-guid"},
            scoped_elements_by_guid={
                "q1-guid": [
                    self._survey_definition_element("GovActionProcess::A", "Git Repository"),
                    self._survey_definition_element("GovActionProcess::B", "PostgreSQL Database", guid="sd-guid-2"),
                ]
            },
        )
        reader = _reader_with_fake_classification_explorer(fake)
        candidates = reader.find_candidate_process_guids_by_questions(["Q1"], "Git Repository")
        assert [c["qualified_name"] for c in candidates] == ["GovActionProcess::A"]

    def test_survey_kind_filter_applied(self):
        fake = _FakeClassificationExplorer(
            guid_by_name={"Q1": "q1-guid"},
            scoped_elements_by_guid={
                "q1-guid": [
                    self._survey_definition_element("GovActionProcess::A", "Git Repository", survey_kind="discovery"),
                    self._survey_definition_element("GovActionProcess::B", "Git Repository", survey_kind="automate_full", guid="g2"),
                ]
            },
        )
        reader = _reader_with_fake_classification_explorer(fake)
        candidates = reader.find_candidate_process_guids_by_questions(["Q1"], "Git Repository", survey_kind="discovery")
        assert [c["qualified_name"] for c in candidates] == ["GovActionProcess::A"]

    def test_dedupes_survey_definition_scoped_by_multiple_questions(self):
        fake = _FakeClassificationExplorer(
            guid_by_name={"Q1": "q1-guid", "Q2": "q2-guid"},
            scoped_elements_by_guid={
                "q1-guid": [self._survey_definition_element("GovActionProcess::A", "Git Repository")],
                "q2-guid": [self._survey_definition_element("GovActionProcess::A", "Git Repository")],
            },
        )
        reader = _reader_with_fake_classification_explorer(fake)
        candidates = reader.find_candidate_process_guids_by_questions(["Q1", "Q2"], "Git Repository")
        assert len(candidates) == 1

    def test_result_is_cached_across_calls(self):
        fake = _FakeClassificationExplorer(
            guid_by_name={"Q1": "q1-guid"},
            scoped_elements_by_guid={"q1-guid": [self._survey_definition_element("GovActionProcess::A", "Git Repository")]},
        )
        reader = _reader_with_fake_classification_explorer(fake)
        reader.find_candidate_process_guids_by_questions(["Q1"], "Git Repository")
        reader.find_candidate_process_guids_by_questions(["Q1"], "Git Repository")
        assert fake.get_scoped_elements_calls == 1

    def test_string_response_treated_as_no_elements_found(self):
        # pyegeria returns a bare string (e.g. "No elements found") instead
        # of a list when a query has no results — must not crash iterating it.
        fake = _FakeClassificationExplorer(
            guid_by_name={"Q1": "q1-guid"},
            scoped_elements_by_guid={},
        )
        fake.get_scoped_elements = lambda scope_guid, **_kw: "No elements found"
        reader = _reader_with_fake_classification_explorer(fake)
        assert reader.find_candidate_process_guids_by_questions(["Q1"], "Git Repository") == []


def test_missing_node_for_linked_guid_is_rejected():
    """A link pointing at a guid with no corresponding node (malformed/partial
    graph) should fail loudly, not silently stop the chain early."""
    step1 = _step_element("step-1", "Step::One", additional_properties={"executes_at": "egeria"})
    graph = _graph(
        "proc-dangling", "GovActionProcess::Dangling",
        first_step=step1,
        next_steps=[],  # step "step-2" is linked but never listed as a node
        links=[_link("step-1", "step-2")],
    )

    with pytest.raises(SurveyDefinitionReaderError):
        _reader()._parse_graph(graph)


class _FakeGovernanceOfficerGraph:
    """Fake returning a raw graph (for reconcile_step_links, which reads
    processStepLinks directly rather than going through _parse_graph)."""

    def __init__(self, links):
        self._links = links
        self.get_governance_action_process_graph_calls = 0

    def get_governance_action_process_graph(self, **_kwargs):
        self.get_governance_action_process_graph_calls += 1
        return {"elementGraph": {"processStepLinks": self._links}}


class _FakeMetadataExpert:
    """delete_related_elements() is called directly again (pyegeria's
    ISSUE-63 fixed upstream — the method now routes through
    DeleteRelationshipRequestBody, which does declare deleteMethod, instead
    of the old OpenMetadataDeleteRequestBody that silently dropped it)."""

    def __init__(self):
        self.deleted_guids = []
        self.delete_bodies = []

    def delete_related_elements(self, relationship_guid, body=None):
        self.deleted_guids.append(relationship_guid)
        self.delete_bodies.append(body)


def _unique_name_link(prev_qn, next_qn, link_guid):
    return {
        "previousProcessStep": {"uniqueName": prev_qn},
        "nextProcessStep": {"uniqueName": next_qn},
        "nextProcessStepLinkGUID": link_guid,
    }


class TestReconcileStepLinks:
    """D1 follow-up (docs/survey-question-context-plan.md) — the live
    incident where Dr.Egeria's non-idempotent Link Next Process Step
    duplicated every edge on re-run, plus one genuinely stale edge."""

    def _reader_with_fakes(self, links):
        from resource_explorer.surveyors import survey_definition_reader as sdr

        reader = _reader()
        gov = _FakeGovernanceOfficerGraph(links)
        reader._governance_officer = gov
        meta = _FakeMetadataExpert()
        reader._metadata_expert = meta
        sdr._fetch_cache.clear()
        return reader, gov, meta

    def test_clean_chain_deletes_nothing(self):
        links = [
            _unique_name_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l1"),
        ]
        reader, gov, meta = self._reader_with_fakes(links)
        result = reader.reconcile_step_links("proc-guid", "X", ["a", "b"])
        assert result.kept == 1
        assert result.removed_total == 0
        assert meta.deleted_guids == []

    def test_duplicate_edge_deletes_the_extra_one(self):
        links = [
            _unique_name_link("GovActionProcessStep::RepoCoarseScout::repo_health", "GovActionProcessStep::RepoCoarseScout::repo_language", "l1"),
            _unique_name_link("GovActionProcessStep::RepoCoarseScout::repo_health", "GovActionProcessStep::RepoCoarseScout::repo_language", "l2"),
        ]
        reader, gov, meta = self._reader_with_fakes(links)
        result = reader.reconcile_step_links("proc-guid", "RepoCoarseScout", ["repo_health", "repo_language"])
        assert result.removed_duplicate == 1
        assert meta.deleted_guids == ["l2"]

    def test_dry_run_reports_but_does_not_delete(self):
        links = [
            _unique_name_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l1"),
            _unique_name_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l2"),
        ]
        reader, gov, meta = self._reader_with_fakes(links)
        result = reader.reconcile_step_links("proc-guid", "X", ["a", "b"], dry_run=True)
        assert result.removed_duplicate == 1
        assert meta.deleted_guids == []

    def test_busts_fetch_cache_after_deleting(self):
        from resource_explorer.surveyors import survey_definition_reader as sdr

        links = [
            _unique_name_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l1"),
            _unique_name_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l2"),
        ]
        reader, gov, meta = self._reader_with_fakes(links)
        sdr._fetch_cache["proc-guid"] = (0.0, "stale-cached-survey-def")
        reader.reconcile_step_links("proc-guid", "X", ["a", "b"])
        assert "proc-guid" not in sdr._fetch_cache

    def test_no_changes_does_not_touch_fetch_cache(self):
        from resource_explorer.surveyors import survey_definition_reader as sdr

        links = [_unique_name_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l1")]
        reader, gov, meta = self._reader_with_fakes(links)
        sdr._fetch_cache["proc-guid"] = (1e18, "still-fresh")  # far-future timestamp, not stale
        reader.reconcile_step_links("proc-guid", "X", ["a", "b"])
        assert sdr._fetch_cache.get("proc-guid") == (1e18, "still-fresh")

    def test_fetch_error_returns_error_result_not_raises(self):
        reader = _reader()

        class _Raising:
            def get_governance_action_process_graph(self, **_kwargs):
                raise RuntimeError("boom")

        reader._governance_officer = _Raising()
        result = reader.reconcile_step_links("proc-guid", "X", ["a", "b"])
        assert result.error
        assert "boom" in result.error

    def test_idempotent_second_call_is_a_no_op(self):
        links = [_unique_name_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l1")]
        reader, gov, meta = self._reader_with_fakes(links)
        reader.reconcile_step_links("proc-guid", "X", ["a", "b"])
        reader.reconcile_step_links("proc-guid", "X", ["a", "b"])
        assert meta.deleted_guids == []
