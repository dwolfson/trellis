"""Annotations produced BY Egeria, brought into RE's own tables.

Every other path in this codebase runs RE -> Egeria. A natively-executing
Survey Definition inverts it, and without this the Results views, trends and
question-answering have nothing to read for those surveys.

No native survey exists yet (measured 2026-08-26: 8 definitions, 71 steps, all
executes_at=resource-explorer), so these tests are what the path is verified by
-- said plainly rather than implying it has been proven against live data.
"""
from __future__ import annotations

import json
import re

import pytest

from resource_explorer.registry import Project
from resource_explorer.surveyors.egeria_annotation_materializer import (
    UNATTRIBUTED_KIND,
    EgeriaAnnotationMaterializer,
    _numeric_values,
)


class _FakeDiscovery:
    def __init__(self, by_guid):
        self._by_guid = by_guid
        self.calls = []

    def get_new_annotations(self, guid, **kw):
        self.calls.append(guid)
        return self._by_guid.get(guid, "No elements found")


class _FakeReader:
    """Stands in for EgeriaReader. Records that fetching goes by RELATIONSHIP."""

    def __init__(self, by_guid, reports=None):
        self._discovery = _FakeDiscovery(by_guid)
        self._reports = reports or []
        self.connected = False

    def connect(self):
        self.connected = True

    def get_survey_reports_from_egeria(self, slug):
        return self._reports


def _ann(guid, atype, summary, *, step="", conf=None, type_name="Annotation",
         json_props=None, subtype=None, explanation=""):
    props = {
        "annotationType": atype, "summary": summary, "analysisStep": step,
        "explanation": explanation,
    }
    if conf is not None:
        props["confidence"] = conf
    if json_props is not None:
        import json as _j
        props["jsonProperties"] = _j.dumps(json_props)
    for k, v in (subtype or {}).items():
        props[k] = v
    return {"elementHeader": {"guid": guid, "type": {"typeName": type_name}}, "properties": props}


@pytest.fixture
def slug(request):
    """One project per test.

    The throwaway schema is session-scoped, so a shared slug would collide on
    the second insert AND let one test read rows another wrote -- which for
    append-only findings tables means a passing assertion about "the latest
    run" that is actually reading someone else's run.
    """
    return "mat_" + re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:48]


@pytest.fixture
def project(pg_registry, slug):
    """The throwaway test schema, never the real catalog.

    This registry is Postgres-backed, so there is no env var that redirects it
    to a temp file -- an earlier version of this fixture assumed there was and
    wrote its rows straight into the real `resource_explorer` schema.
    """
    pg_registry.add(
        Project(slug=slug, display_name=slug, github_url=f"https://github.com/x/{slug}")
    )
    return pg_registry


def test_annotations_are_fetched_by_relationship_not_by_name(project, slug):
    """EgeriaReader.get_annotations() searches `Annotation::{slug}::{ts}::` --
    RE's OWN qualifiedName convention. A natively-produced annotation does not
    carry it, so searching by name would find nothing and report zero as though
    the survey had produced nothing.

    The relationship call is get_new_annotations(report_guid), established by
    probing a real published report: get_annotations_for_element returns "No
    elements found" for both the report and asset GUIDs, while this one returns
    the annotation. The obvious-sounding call was the wrong one.
    """
    reader = _FakeReader({"rep-1": [_ann("a1", "Measurement", "ok")]})
    m = EgeriaAnnotationMaterializer(registry=project, reader=reader)
    out = m.materialize_report(slug, "rep-1")

    assert reader._discovery.calls == ["rep-1"], "must query by the report GUID"
    assert out["annotations"] == 1


def test_findings_land_where_the_results_views_already_read(project, slug):
    reader = _FakeReader({"rep-1": [
        _ann("a1", "SecurityPolicy", "present", step="repo_security", conf=90,
             explanation="SECURITY.md found"),
    ]})
    EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(
        slug, "rep-1", surveyed_at="2026-08-26T10:00:00")

    rows = project.query_findings(slug, "security_scan")
    assert len(rows) == 1
    assert rows[0]["check_name"] == "SecurityPolicy"
    assert rows[0]["label"] == "present"


def test_kind_comes_from_the_analysis_step(project, slug):
    """analysisStep is the only field tying a native annotation back to a step
    RE knows about."""
    reader = _FakeReader({"rep-1": [
        _ann("a1", "X", "s", step="repo_security"),
        _ann("a2", "Y", "s", step="repo_documentation"),
    ]})
    out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(
        slug, "rep-1")
    assert out["kinds"] == ["documentation_coverage", "security_scan"]


def test_an_unattributable_annotation_is_not_filed_under_a_neighbour(project, slug):
    """"Egeria produced this and we cannot say which analysis it belongs to" is
    a different fact from "this is a security_scan finding". Merging them would
    make the second unreliable, so the first gets its own kind."""
    reader = _FakeReader({"rep-1": [
        _ann("a1", "Something", "s", step=""),
        _ann("a2", "Other", "s", step="a_step_re_has_never_heard_of"),
    ]})
    out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(
        slug, "rep-1")
    assert out["kinds"] == [UNATTRIBUTED_KIND]
    assert len(project.query_findings(slug, UNATTRIBUTED_KIND)) == 2


def test_provenance_is_recorded_on_every_row(project, slug):
    """These tables previously only ever held locally-produced findings. Once
    both sources write to them, a row whose origin is ambiguous is exactly the
    confusion this direction of data flow introduces."""
    reader = _FakeReader({"rep-1": [_ann("guid-9", "T", "s", step="repo_security")]})
    EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(
        slug, "rep-1")
    row = project.query_findings(slug, "security_scan")[0]
    detail = json.loads(row["detail_json"])
    assert detail["source"] == "egeria"
    assert detail["egeria_guid"] == "guid-9"


def test_measurements_become_metrics_not_findings(project, slug):
    reader = _FakeReader({"rep-1": [
        _ann("a1", "Size", "measured", step="repo_health",
             type_name="ResourceMeasureAnnotation",
             json_props={"fileCount": 42, "sizeKb": 1024.5}),
    ]})
    out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(
        slug, "rep-1")
    assert out["metrics"] == 2 and out["findings"] == 0
    # query_metrics returns a flat {name: value, ...} with surveyed_at/detail
    # alongside -- not rows.
    metrics = project.query_metrics(slug, "repository_health")
    assert metrics["fileCount"] == 42.0
    assert metrics["sizeKb"] == 1024.5
    # Provenance rides along on the metric side too, not just on findings.
    assert metrics["detail"]["source"] == "egeria"


def test_a_measure_annotation_with_no_numbers_is_kept_as_a_finding(project, slug):
    """Dropping it for failing to be a number would lose a real observation."""
    reader = _FakeReader({"rep-1": [
        _ann("a1", "Size", "nothing measurable", step="repo_health",
             type_name="ResourceMeasureAnnotation", json_props={"note": "n/a"}),
    ]})
    out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(
        slug, "rep-1")
    assert out["metrics"] == 0 and out["findings"] == 1


def test_materializing_twice_does_not_double_the_history(project, slug):
    """These tables are append-only, so a second run would double every count
    read off them -- and counts are what the trend charts plot."""
    reader = _FakeReader({"rep-1": [_ann("a1", "T", "s", step="repo_security")]})
    m = EgeriaAnnotationMaterializer(registry=project, reader=reader)
    first = m.materialize_report(slug, "rep-1")
    second = m.materialize_report(slug, "rep-1")

    assert first["skipped"] is False
    assert second["skipped"] is True
    assert len(project.query_findings(slug, "security_scan")) == 1


def test_an_unreachable_egeria_reports_zero_rather_than_failing(project, slug):
    """Fail-soft, like every other Egeria read in this codebase -- but the
    caller still gets a count, so "nothing there" and "could not look" are
    told apart by the annotations number rather than by an exception."""
    class _Broken(_FakeReader):
        def __init__(self):
            super().__init__({})
            self._discovery = self

        def get_new_annotations(self, guid, **kw):
            raise RuntimeError("connection refused")

    out = EgeriaAnnotationMaterializer(registry=project, reader=_Broken()).materialize_report(
        slug, "rep-1")
    assert out["annotations"] == 0 and out["findings"] == 0


def test_project_level_run_walks_every_report(project, slug):
    reader = _FakeReader(
        {"r1": [_ann("a1", "T", "s", step="repo_security")],
         "r2": [_ann("a2", "T", "s", step="repo_documentation")]},
        reports=[{"guid": "r1", "surveyed_at": "2026-08-26T09:00:00"},
                 {"guid": "r2", "surveyed_at": "2026-08-25T09:00:00"}],
    )
    out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_project(slug)
    assert out["reports_materialized"] == 2
    assert out["kinds"] == ["documentation_coverage", "security_scan"]


class TestNumericExtraction:
    def test_a_numeric_looking_string_is_not_coerced(self):
        """Coercing it would invent a measurement Egeria did not make."""
        assert _numeric_values({"json_properties": {"n": "42"}}) == {}

    def test_booleans_are_not_measurements(self):
        """Python calls bools ints; a True stored as 1.0 is a fabricated number."""
        assert _numeric_values({"json_properties": {"ok": True}}) == {}

    def test_subtype_scores_are_read_including_when_json_encoded(self):
        got = _numeric_values({
            "json_properties": {},
            "subtype_data": {"qualityScores": '{"completeness": 0.75}'},
        })
        assert got == {"completeness": 0.75}


def test_a_failed_read_is_not_recorded_as_a_completed_materialization(project, slug):
    """"Egeria was unreachable" must not be stored as "this report held nothing".

    Marking it would make the report permanently un-retryable, and its zero
    indistinguishable from a real one -- while these tables are append-only, so
    nothing would ever correct it.
    """
    class _Broken(_FakeReader):
        def __init__(self):
            super().__init__({})
            self._discovery = self

        def get_new_annotations(self, guid, **kw):
            raise RuntimeError("connection refused")

    m = EgeriaAnnotationMaterializer(registry=project, reader=_Broken())
    out = m.materialize_report(slug, "rep-1")
    assert out.get("error")
    # Still retryable: a later, working read must be able to do the real work.
    working = _FakeReader({"rep-1": [_ann("a1", "T", "s", step="repo_security")]})
    again = EgeriaAnnotationMaterializer(registry=project, reader=working).materialize_report(
        slug, "rep-1")
    assert again["skipped"] is False and again["findings"] == 1


def test_an_empty_report_is_marked_because_it_was_actually_read(project, slug):
    """The other half of the distinction above: a successful read of a report
    holding nothing is a real answer, and re-reading it forever would be
    pointless work."""
    m = EgeriaAnnotationMaterializer(registry=project, reader=_FakeReader({}))
    assert m.materialize_report(slug, "rep-empty")["skipped"] is False
    assert m.materialize_report(slug, "rep-empty")["skipped"] is True


def test_a_sweep_tells_all_empty_apart_from_all_failed(project, slug):
    """Both produce zero findings; only one means the data is not there."""
    class _Broken(_FakeReader):
        def __init__(self, reports):
            super().__init__({}, reports=reports)
            self._discovery = self

        def get_new_annotations(self, guid, **kw):
            raise RuntimeError("boom")

    reports = [{"guid": "r1", "surveyed_at": "2026-08-26T09:00:00"}]
    failed = EgeriaAnnotationMaterializer(
        registry=project, reader=_Broken(reports)).materialize_project(slug)
    assert failed["reports_failed"] == 1 and failed["reports_materialized"] == 0

    empty = EgeriaAnnotationMaterializer(
        registry=project, reader=_FakeReader({}, reports=reports)).materialize_project(slug)
    assert empty["reports_failed"] == 0 and empty["reports_materialized"] == 1


class TestAttribution:
    """Which analysis a native annotation belongs to.

    Grounded in a real published annotation (2f1f804a, egeria_git): it carries
    analysisStep="HealthAssessment" -- the surveyor's own step name, NOT the
    "repo_health" key -- and annotationType="QualityScoreAnnotation". Matching
    only on analysisStep would leave every real annotation unattributed.
    """

    def test_the_step_key_wins_when_present(self, project, slug):
        reader = _FakeReader({"r": [_ann("a", "Whatever", "s", step="repo_security")]})
        out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(slug, "r")
        assert out["kinds"] == ["security_scan"]

    def test_an_unambiguous_annotation_type_attributes_it(self, project, slug):
        """DataClassAnnotation is declared by exactly one step (repo_dependency),
        so it attributes even though its analysisStep means nothing here.

        This used to use QualityScoreAnnotation, which was unique to repo_health
        until foss_scorecard began producing one too on 2026-08-26 -- correctly,
        it really does compute a quality score. Attribution by annotation type
        is inherently fragile in exactly this way: it holds only while no second
        analysis produces the same type, and nothing prevents one.
        """
        reader = _FakeReader({"r": [
            _ann("a", "DataClassAnnotation", "dependencies", step="SomethingNative"),
        ]})
        out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(slug, "r")
        assert out["kinds"] == ["dependency_analysis"]

    def test_a_type_that_gains_a_second_producer_stops_attributing(self, project, slug):
        """The fragility, pinned rather than left to be rediscovered.

        QualityScoreAnnotation attributed to repository_health until a second
        analysis declared it. Now it cannot, and lands unattributed -- which is
        the honest outcome, but it means adding an analysis silently reduces
        attribution precision for every analysis sharing its types.
        """
        reader = _FakeReader({"r": [
            _ann("a", "QualityScoreAnnotation", "score", step="HealthAssessment"),
        ]})
        out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(slug, "r")
        assert out["kinds"] == [UNATTRIBUTED_KIND]

    def test_an_ambiguous_annotation_type_is_never_guessed(self, project, slug):
        """ResourceMeasureAnnotation has 15 producers. Picking one would file a
        finding under an analysis that did not produce it -- making that
        analysis's results WRONG, rather than merely incomplete."""
        reader = _FakeReader({"r": [
            _ann("a", "ResourceMeasureAnnotation", "s", step="SomethingNative"),
        ]})
        out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(slug, "r")
        assert out["kinds"] == [UNATTRIBUTED_KIND]

    def test_sole_producer_lookup_is_strict(self):
        from resource_explorer.surveyors.egeria_annotation_materializer import _sole_producer_of

        assert _sole_producer_of("DataClassAnnotation") == "repo_dependency"
        # Shared since foss_scorecard also produces one -- see
        # test_a_type_that_gains_a_second_producer_stops_attributing.
        assert _sole_producer_of("QualityScoreAnnotation") == ""
        assert _sole_producer_of("ResourceMeasureAnnotation") == ""   # 15 owners
        assert _sole_producer_of("ClassificationAnnotation") == ""    # 13 owners
        assert _sole_producer_of("NoSuchAnnotation") == ""
        assert _sole_producer_of("") == ""

    def test_measure_detection_reads_annotation_type_too(self, project, slug):
        """Egeria's typeName and annotationType differ -- the real annotation is
        typeName=QualityAnnotation, annotationType=QualityScoreAnnotation. A
        check on typeName alone would file every measurement as a finding."""
        reader = _FakeReader({"r": [
            _ann("a", "QualityScoreAnnotation", "scored", step="repo_health",
                 type_name="QualityAnnotation", json_props={"score": 83}),
        ]})
        out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_report(slug, "r")
        assert out["metrics"] == 1 and out["findings"] == 0
        assert project.query_metrics(slug, "repository_health")["score"] == 83.0


class TestOwnReportsAreNotReimported:
    """RE's own published reports must not come back in as external data.

    Found on real data: egeria_git's only SurveyReport was published BY RE from
    a local run. Materializing it wrote a second copy of that run's numbers at
    the REPORT's timestamp (...442655) while the original sat at the RUN's
    (...448468) -- 6ms apart, same kind. query_metrics' "latest run" then picks
    between two copies of one run by millisecond ordering.
    """

    def test_a_report_re_published_is_skipped(self, project, slug):
        from resource_explorer.surveyors.egeria_annotation_materializer import _is_own_report

        assert _is_own_report(f"SurveyReport::GitHubRepo::{slug}::2026-08-25T12:54:25", slug)
        reader = _FakeReader(
            {"r1": [_ann("a1", "T", "s", step="repo_security")]},
            reports=[{"guid": "r1", "surveyed_at": "2026-08-25T12:54:25",
                      "qualified_name": f"SurveyReport::GitHubRepo::{slug}::2026-08-25T12:54:25"}],
        )
        out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_project(slug)

        assert out["reports_skipped_own"] == 1
        assert out["reports_materialized"] == 0
        assert project.query_findings(slug, "security_scan") == []

    def test_a_natively_created_report_is_imported(self, project, slug):
        """The whole point: a report Egeria made itself has no RE naming, and
        is the case this feature exists for."""
        reader = _FakeReader(
            {"r1": [_ann("a1", "T", "s", step="repo_security")]},
            reports=[{"guid": "r1", "surveyed_at": "2026-08-26T09:00:00",
                      "qualified_name": "SurveyReport:egeria-native-engine:0e12"}],
        )
        out = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_project(slug)
        assert out["reports_skipped_own"] == 0
        assert out["reports_materialized"] == 1
        assert len(project.query_findings(slug, "security_scan")) == 1

    def test_skipped_own_is_reported_separately_from_found_nothing(self, project, slug):
        """"Nothing new in Egeria" and "everything there came from us" are
        different answers; only the second means the round trip is closed."""
        reader = _FakeReader({}, reports=[])
        empty = EgeriaAnnotationMaterializer(registry=project, reader=reader).materialize_project(slug)
        assert empty["reports_seen"] == 0 and empty["reports_skipped_own"] == 0
