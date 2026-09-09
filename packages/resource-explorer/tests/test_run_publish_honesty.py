"""A card must not claim "Never run" and "Published today" at once.

Both halves were wrong, from opposite causes:

* last_run_at read only operation='analysis_run' rows -- written solely by the
  per-analysis "Run" button. The database held 17 of those against 116
  operation='survey' rows, so every analysis on every repo reported never-run
  while its results sat in the findings tables.

* last_published_at joined on annotation_types, which are shared --
  ResourceMeasureAnnotation has 15 producers -- so one analysis publishing
  credited every sibling that declares the same type.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import Project


@pytest.fixture
def slug(request):
    import re as _re
    return "rp_" + _re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:48]


@pytest.fixture
def reg(pg_registry, slug):
    pg_registry.add(Project(slug=slug, display_name=slug,
                            github_url=f"https://github.com/x/{slug}"))
    return pg_registry


def _log_survey(reg, slug, ts, steps, process="RepoCoarseProfile"):
    """One operation='survey' row shaped like the real ones."""
    from resource_explorer.activity_logger import log_survey

    log_survey(reg, "repo", slug, slug, "", "scouting", "ok", "surveyed", json.dumps({
        "source": "survey-definition", "entity_type": "repo", "slug": slug,
        "surveyed_at": ts,
        "steps": [{"step": f"GovActionProcessStep::{process}::{k}", "status": st}
                  for k, st in steps],
    }))


class TestRunAttribution:
    def test_a_survey_run_counts_as_running_its_analyses(self, reg, slug):
        _log_survey(reg, slug, "2026-08-26T10:00:00", [("repo_security", "ok")])
        got = reg.get_analysis_last_run("repo", slug)
        assert "security_scan" in got, "an analysis run by a survey reported never-run"
        assert got["security_scan"]["last_run_via"] == "survey"
        assert got["security_scan"]["last_run_at"] == "2026-08-26T10:00:00"

    def test_step_keys_map_to_exactly_one_analysis(self):
        """The attribution is exact only if the map partitions the keys."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP,
        )
        seen: dict[str, str] = {}
        for analysis_id, keys in REPO_ANALYSIS_STEP_MAP.items():
            for k in keys:
                assert k not in seen, f"step {k} claimed by {seen[k]} and {analysis_id}"
                seen[k] = analysis_id

    def test_the_recovery_keeps_credit_for_its_own_steps(self, reg, slug):
        """The concrete case the partition rule exists for.

        `architecture_diagram` declared `repo_arch_detect`/`repo_arch_coupling`
        as its own until 2026-09-08. `_step_key_to_analysis_id` inverts the map
        with a dict comprehension and the diagram is defined LAST, so both keys
        resolved to it and a survey that ran the recovery credited the picture
        instead of the work. Asserting the survivor by name, not just that the
        map partitions — a future entry could re-take these keys and still
        partition, by removing them from `architecture_recovery`.
        """
        _log_survey(reg, slug, "2026-09-08T10:00:00",
                    [("repo_arch_detect", "ok"), ("repo_arch_coupling", "ok")])
        got = reg.get_analysis_last_run("repo", slug)
        assert "architecture_recovery" in got, (
            "the analysis that owns the recovery steps was not credited with running them")
        assert got["architecture_recovery"]["last_run_at"] == "2026-09-08T10:00:00"
        assert "architecture_diagram" not in got, (
            "a run was attributed to the analysis that only renders its result")

    def test_the_two_attribution_paths_agree(self):
        """There are two of them, and they disagreed on a colliding key.

        `ProjectRegistry._step_key_to_analysis_id` builds a dict, so the LAST
        analysis declaring a key wins. `egeria_annotation_materializer`'s
        `_analysis_for` loops and returns on the FIRST match. On
        `repo_arch_detect` those gave different answers, so a run and the
        annotations produced by that run were filed under different analyses.
        """
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP,
        )
        last_wins = ProjectRegistry._step_key_to_analysis_id()
        first_wins = {}
        for analysis_id, keys in REPO_ANALYSIS_STEP_MAP.items():
            for k in keys:
                first_wins.setdefault(k, analysis_id)
        assert last_wins == first_wins, (
            "the two attribution paths disagree on: "
            f"{ {k: (first_wins[k], last_wins[k]) for k in first_wins if first_wins[k] != last_wins.get(k)} }")


class TestOwnershipMapIsOnlyUsedForAttribution:
    """The guard whose absence cost three rounds of the same bug.

    Splitting `step_keys` (ownership) from `derives_from` (executability) on
    2026-09-08 meant every existing reader of REPO_ANALYSIS_STEP_MAP had to be
    triaged: does it ask "whose run was that" or "what do I run"? Eight
    consumers, and the second question is the common one. They were found in
    three rounds rather than one, and each miss was silent in its own way —
    a Run button that 400s, a schedule that comes due and does nothing, the
    catalog's most expensive analysis priced as free, a Survey Definition
    quietly losing a ScopedBy link on the next resync, a survey card that stops
    offering a Results view for an analysis its own steps produce.

    None of those fail a test on their own. So this pins the ownership map's
    readers by name: adding one is now a deliberate act with a docstring to
    read, not a plausible-looking autocomplete.
    """

    #: Modules entitled to REPO_ANALYSIS_STEP_MAP, and why.
    ATTRIBUTION_READERS = {
        # Inverts it to answer "which analysis owns this step key" for run
        # attribution (_step_key_to_analysis_id). The partition IS the map.
        "resource_explorer/registry.py",
        # "these step keys ran — which analyses produced these annotations".
        "resource_explorer/surveyors/egeria_annotation_materializer.py",
        # Same question for published elements.
        "resource_explorer/surveyors/egeria_publisher.py",
        # Membership test only ("is this a repo analysis at all"); both maps
        # carry identical KEYS, so this is not a dispatch decision.
        "resource_explorer/web/routes/schedules.py",
        # Defines both maps.
        "resource_explorer/surveyors/repo_survey_definition_adapter.py",
        # Names one analysis explicitly (language_file_classification), which
        # owns its own steps — ownership and source are the same list there.
        "resource_explorer/scheduler.py",
    }

    def test_no_new_module_reads_the_ownership_map(self):
        import re as _re
        from pathlib import Path

        pkg = Path(__file__).resolve().parents[1]
        found = set()
        for path in list((pkg / "resource_explorer").rglob("*.py")) + \
                list((pkg / "scripts").rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Comments and docstrings discuss the map constantly; only a real
            # reference counts — an import, or the name followed by a lookup.
            code = _re.sub(r"^\s*#.*$", "", text, flags=_re.M)
            if _re.search(r"REPO_ANALYSIS_STEP_MAP\s*[\.\[]|^\s+REPO_ANALYSIS_STEP_MAP,\s*$",
                          code, _re.M):
                found.add(str(path.relative_to(pkg)))
        unexpected = found - self.ATTRIBUTION_READERS
        assert not unexpected, (
            f"new reader(s) of the ownership map: {sorted(unexpected)}. If the question "
            "is \"what do I run to refresh this analysis\", use REPO_ANALYSIS_SOURCE_STEPS "
            "— an analysis that owns no steps resolves to [] here and fails silently. "
            "If it really is attribution, add it to ATTRIBUTION_READERS with the reason.")

    def test_the_listed_readers_still_read_it(self):
        """The other direction: a stale entry here reads as coverage of a
        consumer that no longer exists."""
        from pathlib import Path

        pkg = Path(__file__).resolve().parents[1]
        gone = {m for m in self.ATTRIBUTION_READERS
                if "REPO_ANALYSIS_STEP_MAP" not in (pkg / m).read_text(encoding="utf-8")}
        assert not gone, f"ATTRIBUTION_READERS lists modules that no longer read it: {sorted(gone)}"


class TestEveryAnalysisCanActuallyBeRun:
    """Ownership and executability were one field until 2026-09-08, and
    splitting them introduced a way to be silently unrunnable: an analysis with
    `step_keys=[]` and no `derives_from` has nothing to dispatch, so its Run
    button 400s, its cost reads free, and the fact layer tells a user there is
    nothing they can run. Nothing else fails."""

    def test_a_survey_analysis_always_has_something_to_run(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_SOURCE_STEPS,
        )
        runnable = {a["id"] for a in get_analyses("repo", include_egeria_live=False)
                    if a.get("action") == "survey"}
        empty = {a for a in runnable
                 if a in REPO_ANALYSIS_SOURCE_STEPS and not REPO_ANALYSIS_SOURCE_STEPS[a]}
        assert not empty, (
            f"catalogued as runnable with no steps to run: {sorted(empty)}. "
            "Give the AnalysisKind step_keys of its own, or derives_from naming "
            "the steps that produce its data.")

    def test_derives_from_names_steps_that_someone_owns(self):
        """A `derives_from` pointing at a step no analysis owns would name
        something the orchestrator has no owner for — and would leave the
        colliding-key bug's inverse: a step that runs and is credited to
        nobody."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS, REPO_ANALYSIS_STEP_MAP, STEP_REGISTRY,
        )
        owned = {k for keys in REPO_ANALYSIS_STEP_MAP.values() for k in keys}
        for analysis_id, kind in ANALYSIS_KINDS.items():
            for k in kind.derives_from:
                assert k in STEP_REGISTRY, f"{analysis_id} derives from unknown step {k}"
                assert k in owned, (
                    f"{analysis_id} derives from {k}, which no analysis owns — "
                    "a run of it would be credited to nobody")

    def test_a_derived_analysis_does_not_report_itself_free(self):
        """`analysis_cost` reads the steps that RUN. Reading owned steps would
        price architecture_diagram at ("none", "low") — the cheapest tier in
        the catalog for the thing that downloads two artifacts — and
        `recommended_schedule` would invite running it daily."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS, analysis_cost,
        )
        for analysis_id, kind in ANALYSIS_KINDS.items():
            if not kind.derives_from:
                continue
            assert analysis_cost(analysis_id) != ("none", "low"), (
                f"{analysis_id} derives from real steps and is priced as free")

    def test_a_derived_analysis_is_dispatched_by_the_scheduler(self, monkeypatch):
        """A schedule on `architecture_diagram` must actually run the recovery
        steps. Resolved through the ownership map it runs nothing: the schedule
        sits in the list, comes due, and reports an "internal configuration
        gap" nobody reads.

        Driven through `_run_repo_survey` rather than asserted against the
        module's source — what matters is which steps reach the orchestrator.
        """
        from types import SimpleNamespace

        from resource_explorer import scheduler

        ran: list[list[str]] = []

        class _Orch:
            def __init__(self, registry):
                pass

            def run(self, slug, steps=None, **kw):
                ran.append(list(steps or []))
                return SimpleNamespace(errors=[], step_errors={})

        monkeypatch.setattr(
            "resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator", _Orch)

        project = SimpleNamespace(slug="r", display_name="r",
                                  github_url="https://github.com/o/r",
                                  collections=[], subproject_path=None)
        registry = SimpleNamespace(get=lambda slug: project)

        _, _, errors = scheduler._run_repo_survey("r", "architecture_diagram", registry)

        assert not errors, errors
        assert ran == [["repo_arch_detect", "repo_arch_coupling"]], (
            f"the scheduler ran {ran} for architecture_diagram")


    def test_a_partial_run_says_so(self, reg, slug):
        """language_file_classification owns three step keys. A survey running
        one of them did real work -- calling that "never run" is the larger
        error -- but it is not the whole analysis either."""
        _log_survey(reg, slug, "2026-08-26T10:00:00", [("repo_language", "ok")])
        got = reg.get_analysis_last_run("repo", slug)["language_file_classification"]
        assert got["last_run_partial"] is True

        _log_survey(reg, slug, "2026-08-26T11:00:00", [
            ("repo_language", "ok"), ("repo_file_classification", "ok"),
            ("repo_file_structure", "ok"),
        ])
        got = reg.get_analysis_last_run("repo", slug)["language_file_classification"]
        assert got["last_run_partial"] is False

    def test_the_steps_own_status_is_reported_not_the_surveys(self, reg, slug):
        """A survey that failed elsewhere still ran this analysis fine."""
        _log_survey(reg, slug, "2026-08-26T10:00:00",
                    [("repo_security", "ok"), ("repo_documentation", "error")])
        got = reg.get_analysis_last_run("repo", slug)
        assert got["security_scan"]["last_run_status"] == "ok"
        assert got["documentation_coverage"]["last_run_status"] == "error"

    def test_an_unattributable_survey_row_credits_no_analysis(self, reg, slug):
        """Older survey rows carry no step detail. They must not be spread
        across every analysis on the theory that a survey ran something -- they
        are reported once, against a reserved key, as "we cannot say which"."""
        _log_survey(reg, slug, "2026-08-26T10:00:00", [])
        got = reg.get_analysis_last_run("repo", slug)
        assert [k for k in got if not k.startswith("__")] == []
        assert got["__unattributed_surveys__"]["count"] == 1


class TestPublishAttribution:
    """Which analysis a publish covered is RECORDED, not inferred.

    It used to be worked out backwards: join a publish's annotation types
    against each analysis's declared ones, and treat a uniquely-owned type as
    proof. That held only while every type had one producer. It stopped being
    true the moment a second analysis produced a QualityScoreAnnotation —
    after which NO analysis could earn an attributable publish and every card
    showed the hedged "Repo published". The inference was always going to break
    that way; nothing prevented a second producer.

    SurveyOrchestrator knows exactly which steps ran, so the publish records
    the analyses outright (project_published_analyses).
    """

    def test_the_orchestrator_records_what_actually_ran(self):
        """`steps_run` must reflect the post-cost-filter set: attributing an
        analysis a cost ceiling excluded would be the same false claim in a
        new place."""
        import inspect

        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        src = inspect.getsource(SurveyOrchestrator.run)
        assert "result.steps_run" in src
        assert src.index("result.steps_run") > src.index("max_compute_cost is not None"), \
            "steps_run recorded before the cost filter narrowed the set"

    def test_steps_map_to_the_analyses_that_own_them(self):
        from resource_explorer.surveyors.egeria_publisher import _analyses_for_steps

        assert _analyses_for_steps(["repo_health"]) == {"repository_health"}
        assert _analyses_for_steps([]) == set()

    def test_a_partial_run_still_attributes_its_analysis(self):
        """language_file_classification owns three steps. One of them running
        published real findings under its name, and reporting nothing would
        lose them."""
        from resource_explorer.surveyors.egeria_publisher import _analyses_for_steps

        assert _analyses_for_steps(["repo_language"]) == {"language_file_classification"}

    def test_recorded_attribution_round_trips(self, pg_registry):
        reg = pg_registry
        reg.record_published_analyses("attr-demo", ["repository_health", "security_scan"],
                                      "guid-1", published_at="2026-08-27T00:00:00")
        got = reg.get_last_published_analyses("attr-demo")
        assert got["repository_health"] == "2026-08-27T00:00:00"
        assert got["security_scan"] == "2026-08-27T00:00:00"

    def test_recording_nothing_is_not_an_error(self, pg_registry):
        pg_registry.record_published_analyses("attr-none", [])
        assert pg_registry.get_last_published_analyses("attr-none") == {}

    def test_the_route_prefers_the_record_over_the_inference(self):
        import inspect

        from resource_explorer.web.routes import projects

        src = inspect.getsource(projects.get_analyses_last_activity)
        assert "published_by_analysis" in src
        # The dead inference helper is gone, not left to rot beside its
        # replacement.
        assert not hasattr(projects, "_sole_producer")


class TestNotEstablished:
    """"Never run" and "we cannot say" are different claims.

    Older survey rows carry no step detail. Their analyses cannot be credited
    with a run -- but the repo WAS surveyed, so calling them never-run beside a
    publish we can attribute reproduces the original contradiction with extra
    steps.
    """

    def test_an_undetailed_survey_yields_not_established_not_never_run(self, reg, slug):
        _log_survey(reg, slug, "2026-08-26T10:00:00", [])
        got = reg.get_analysis_last_run("repo", slug)
        assert got["__unattributed_surveys__"]["count"] == 1

    def test_a_repo_with_no_surveys_at_all_is_never_run(self, reg, slug):
        """The third state must not swallow the second: a genuinely unsurveyed
        repo has to keep saying so, or "never run" stops meaning anything."""
        assert reg.get_analysis_last_run("repo", slug) == {}

    def test_an_attributed_run_is_not_downgraded_by_an_undetailed_one(self, reg, slug):
        _log_survey(reg, slug, "2026-08-26T09:00:00", [])
        _log_survey(reg, slug, "2026-08-26T10:00:00", [("repo_security", "ok")])
        got = reg.get_analysis_last_run("repo", slug)
        assert got["security_scan"]["last_run_at"] == "2026-08-26T10:00:00"
        assert got["__unattributed_surveys__"]["count"] == 1

    def test_the_ui_renders_all_three_states(self):
        html = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "resource_explorer" / "web" / "static" / "index.html"
        ).read_text()
        assert "📅 Last run not established" in html
        assert "📅 Never run" in html
        assert "la.last_run_basis === 'not_established'" in html


class TestProposedPerspectives:
    """The eight analyses that carried no lens at all now carry one.

    Not asserted individually -- the specific choices are a judgement the user
    can revise. What must hold is that none is untagged, and every tag is a
    real Egeria Perspective.
    """

    def test_no_analysis_is_left_without_a_perspective(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

        untagged = [
            f"{rt}:{a['id']}"
            for rt in ("repo", "database", "filesystem")
            for a in get_analyses(rt, include_egeria_live=False)
            if not [p for p in (a.get("perspectives") or []) if p != "all"]
        ]
        assert untagged == [], f"analyses with no lens: {untagged}"

    def test_every_tag_is_a_real_egeria_perspective(self):
        from resource_explorer.surveyors.analysis_catalog_reader import (
            EGERIA_PERSPECTIVES, get_analyses,
        )
        for rt in ("repo", "database", "filesystem"):
            for a in get_analyses(rt, include_egeria_live=False):
                for p in (a.get("perspectives") or []):
                    assert p == "all" or p in EGERIA_PERSPECTIVES, f"{a['id']}: {p}"
