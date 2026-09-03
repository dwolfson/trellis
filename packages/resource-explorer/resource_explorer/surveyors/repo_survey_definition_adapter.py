"""
Survey Definition adapter for Git repositories, and the repo analysis-kind
registry (STEP_REGISTRY / ANALYSIS_KINDS) — the single source of truth for
"what are the repo survey steps, and what analyses do users actually see/
run/schedule from them."

Analysis-kind extensibility redesign: this used to be four independently-
maintained parallel structures (re_analysis_steps' closures,
_RE_ANALYSIS_STEP_INFO, REPO_ANALYSIS_STEP_MAP, REPO_ANALYSIS_RESULTS_MAP),
each requiring its own hand-edit whenever a step or analysis kind changed —
plus SurveyOrchestrator's own separately-hardcoded surveyor-construction
dict. They're now two registries, everything else is a thin derived view:

  STEP_REGISTRY   — step_key -> StepInfo (surveyor class, description,
                     annotation types, any special constructor kwargs).
                     The 10 granular sub-surveyor units SurveyOrchestrator
                     can run individually via steps=[...].
  ANALYSIS_KINDS  — analysis_catalog id -> AnalysisKind (which step_key(s)
                     it runs, its "family" for grouping related kinds e.g.
                     "security", and — for the 5 kinds shown under
                     Analysis/Assessment — how to read/render its results).

Adding a new plain analysis kind (accepts (project, registry, surveyed_at)
like the existing finding/metric-writing surveyors) needs exactly one new
StepInfo entry and one new AnalysisKind entry — SurveyOrchestrator derives
its surveyor-construction dict from STEP_REGISTRY automatically. See
StepInfo.accepts_surveyed_at / .static_kwargs for the few surveyors that
need something other than the generic (project, registry) construction.

Unlike the database case, repo surveys are already composed of independent
sub-surveyor units — each one is exposed as its own re_analysis_step key,
the most granular and natural fit for Survey Definition steps. Publishing
reuses the existing EgeriaPublisher.publish unmodified — it's already
narrow (no native-survey side effect).
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable

from trellis_microflow import ResourceProvider

from resource_explorer.registry import WITHDRAWN_LABEL
from resource_explorer.step_outcome import PARTIAL, UNVERIFIED
from resource_explorer.surveyors import result_status
from resource_explorer.surveyors.result_status import attach as attach_status
from resource_explorer.surveyors.result_status import status_from_detail as result_status_from_detail
from resource_explorer.surveyors.arch_recovery import projection as arch_projection

from resource_explorer.surveyors.file_classifier.file_classifier_surveyor import FileClassifierSurveyor
from resource_explorer.surveyors.sub_surveyors import (
    ApiStructureSurveyor,
    ArchCouplingSurveyor,
    ArchDetectSurveyor,
    ArchLensSurveyor,
    ArchSummarySurveyor,
    CiQualitySurveyor,
    ChaossMetricsSurveyor,
    CiiBadgeSurveyor,
    CommunitySupportSurveyor,
    ContributionProvenanceSurveyor,
    CveScanSurveyor,
    InterfaceSurfaceSurveyor,
    DataProfilerSurveyor,
    DependencySurveyor,
    DocumentationSurveyor,
    FossScorecardSurveyor,
    SecuritySummarySurveyor,
    RefreshPlanSurveyor,
    FileInventorySurveyor,
    GitStatisticsSurveyor,
    WebsiteIngestionSurveyor,
    FileSizeSurveyor,
    FileStructureSurveyor,
    HealthSurveyor,
    HomepageSurveyor,
    ManifestParseSurveyor,
    LanguageSurveyor,
    LicenseClassifierSurveyor,
    RepoClassificationSurveyor,
    MaturitySurveyor,
    RagIngestionSurveyor,
    RepoConventionsSurveyor,
    SecretScanSurveyor,
    SlaContentSurveyor,
    TelemetryScanSurveyor,
    SecurityFeaturesSurveyor,
    SecurityHygieneSurveyor,
    SubResourceSurveyor,
    SymbolExtractionSurveyor,
)
from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    register_adapter,
)


# qualified_name of the "Repo Coarse Scout" Survey Definition (a
# GovernanceActionProcess authored in Egeria via Dr.Egeria, chaining just
# repo_health + repo_language — both API-only, no clone needed). Referenced
# explicitly by web/routes/projects.py's scouting-scan endpoint rather than
# relying on technology_type auto-resolution, so it stays unambiguous even
# once a second ("deep") repo Survey Definition also exists — see the
# Scouting/Analysis/Assessment boundary plan. Authored once, out-of-band;
# this constant is the single place code and the Egeria-side element must
# agree on the name.
REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN = "GovActionProcess::RepoCoarseScout"


# ── Resource views — the perspective distinction, in the plumbing ────────
#
# design §4.1 names four perspectives as a MODELLING concept. Nothing enforced
# them below the model, and three separate bugs lived in exactly that gap —
# each silent, each invisible to unit tests because the objects were built
# correctly and only the plumbing was wrong:
#
#   * `scope_locator` served both "path prefix" and "identity" -> 58 distinct
#     components collapsed onto 10 keys (spike findings 45-46)
#   * one global import-root order served two copies of one package -> 156 of
#     170 edges resolved into the wrong copy (finding 37)
#   * one directory served both the code view and the change view -> coupling
#     scanned an empty tree and proposed nothing, on every repo (finding 52)
#
# The third is the one this fixes structurally. Two repo resources both yield
# "a directory" and they are not interchangeable:
#
#   SOURCE   files on disk. A zipball extract has them; a --no-checkout clone
#            does not — its root contains only `.git`.
#   HISTORY  git metadata for `git log`. A clone has it; a zipball has no
#            `.git` at all.
#
# A step declares which views it needs per resource; a provider declares which
# it supplies; `validate_resource_views()` compares them at import. A step that
# asks a history-only resource for source files now fails loudly at wiring
# time instead of quietly reporting nothing.
VIEW_SOURCE = "source"
VIEW_HISTORY = "history"


# ── Step-level registry ──────────────────────────────────────────────────

@dataclass
class StepInfo:
    """One SurveyOrchestrator step — a single sub-surveyor unit."""
    step_key: str
    surveyor_cls: type
    description: str
    annotation_types: list[str]
    # Extra kwargs re_analysis_steps' Survey-Definition-triggered runners
    # pass when running this step in isolation (always safe defaults —
    # a single-step run never has real pyegeria_client/force_refresh/
    # data_path context to forward).
    static_kwargs: dict = field(default_factory=dict)
    # Whether this surveyor's constructor accepts surveyed_at (the shared
    # per-orchestrator-run timestamp, Phase B D1) — only the surveyors that
    # persist structured findings/metrics at survey time need this.
    accepts_surveyed_at: bool = False
    # Whether this surveyor's constructor accepts scope_locator (D5/D6 repo
    # scope-narrowing funnel plan) — only the corpus-shaped surveyors
    # (target_shape="corpus" in analysis_catalog.yaml) implement the
    # path-prefix filter; SurveyOrchestrator.run() only forwards
    # scope_locator to steps flagged True here.
    accepts_scope_locator: bool = False
    # Whether this surveyor's constructor accepts fast (the Scouting-tier
    # "skip anything N+1/expensive" flag) — only repo_health today
    # (StatsFetcher's per-commit diff-stats calls, a confirmed real
    # slowness bug for the Coarse Scout survey definition — see
    # HealthSurveyor.__init__'s own docstring). SurveyOrchestrator.run()
    # only forwards fast to steps flagged True here.
    accepts_fast: bool = False
    # D6 (docs/unified-survey-execution-model-plan.md) — shared resources
    # this step needs, as {resource_name: constructor_kwarg_name}. Resolved
    # once per SurveyOrchestrator.run() call, deduped across every step
    # selected in that run, via trellis_microflow.resolve_resources — see
    # RESOURCE_PROVIDERS below for what "zipball_root" actually does.
    #: Preconditions on STORED DATA, checked before dispatch — names from
    #: `step_preconditions.PRECONDITIONS`, mapped to this step's own reason for
    #: needing them. Distinct from `requires_resources` (a zipball, a clone),
    #: which is about runtime inputs: this is "another step's output is absent,
    #: so there is nothing here to work on". Unmet produces a
    #: `skipped_by_design` annotation carrying the reason, never silence — a step
    #: that vanishes from a report is indistinguishable from one that ran and
    #: found nothing.
    requires_context: dict[str, str] = field(default_factory=dict)
    requires_resources: dict[str, str] = field(default_factory=dict)
    # {resource_name: view} — what this step actually READS from that
    # resource. Checked against the provider's `provides` at import by
    # validate_resource_views(). Every entry in requires_resources should have
    # one; test_every_resource_step_declares_its_view enforces that, because a
    # missing declaration is an unchecked assumption and unchecked assumptions
    # are what this mechanism exists to catch.
    requires_views: dict[str, str] = field(default_factory=dict)
    # Step-cost-tiers plan (docs/step-cost-tiers-plan.md, D2) — two
    # independent, deliberately coarse/ordinal axes so a caller (a survey
    # author, the scheduler, or SurveyOrchestrator.run()'s new
    # max_fetch_cost/max_compute_cost filter) can act on network cost and
    # CPU cost separately instead of being forced into one blended score.
    # Do NOT make these numeric — seconds are right for exactly one repo
    # and wrong for every other, which is how `run_time` in
    # analysis_catalog.yaml rotted (see that plan's "Why").
    #   fetch_cost   : "none" | "api" | "api_heavy" | "download"
    #   compute_cost : "low" | "medium" | "high"
    # D3: fetch_cost="none" is invalid for any step declaring
    # requires_resources={"zipball_root": ...} — enforced by
    # test_step_cost_tiers.py, not just by convention.
    fetch_cost: str = "none"
    compute_cost: str = "low"


# ── D6: shared-resource providers ────────────────────────────────────────
# The generic acquire/dedup/cleanup mechanism lives in trellis_microflow
# (packages/trellis-microflow) — this module only supplies the
# repo-specific *instance*: what "zipball_root" actually means and how to
# get one. See that package's README for why the split exists.

@contextmanager
def _acquire_zipball_root(project, registry):
    """Download `project`'s repo zipball into a fresh tempdir and yield the
    extracted root. One real network call + one extraction per invocation —
    trellis_microflow.resolve_resources is what guarantees this only gets
    invoked once per SurveyOrchestrator.run() call no matter how many
    selected steps declare `requires_resources={"zipball_root": ...}`.

    A plain function, not a StepInfo/surveyor. The actual download+tempdir
    logic lives in GitHubClient.zipball_root() (D6.7) — the one
    implementation IngestionPipeline.refresh_profile() also wraps, instead
    of each maintaining its own copy.
    """
    from resource_explorer.github.client import GitHubClient

    client = GitHubClient()
    repo = client.get_repo(project.github_url)
    with client.zipball_root(repo) as root:
        yield root


@contextmanager
def _acquire_git_clone_root(project, registry):
    """Treeless-clone `project`'s repo into a fresh tempdir and yield the
    clone root. Mirrors _acquire_zipball_root exactly — a plain function,
    not a StepInfo/surveyor, resolved once per SurveyOrchestrator.run() no
    matter how many selected steps declare
    `requires_resources={"git_clone_root": ...}`.

    This is design §5.7 gap 2 (architecture-recovery-design.md) and
    architecture-recovery-phase1-plan.md §3's prerequisite: co-change
    coupling needs git history, and a zipball (what `_acquire_zipball_root`
    yields) has no `.git` at all. The actual clone logic lives in
    GitHubClient.git_clone_root() (mirroring zipball_root()'s D6.7 role) —
    one implementation, not a copy per caller. See that method's docstring
    for why the clone is `--filter=blob:none --no-checkout` rather than
    shallow or full, and for the auth path (same GITHUB_TOKEN as the
    zipball download, no second credential mechanism).
    """
    from resource_explorer.github.client import GitHubClient

    client = GitHubClient()
    repo = client.get_repo(project.github_url)
    with client.git_clone_root(repo) as root:
        yield root


def _resource_providers_for(project, registry) -> dict[str, ResourceProvider]:
    """Builds this run's RESOURCE_PROVIDERS, binding `project`/`registry`
    into each provider's zero-argument `acquire` via a closure — see
    ResourceProvider's own docstring for why the binding happens here,
    not by threading project/registry through trellis_microflow itself."""
    return {
        "zipball_root": ResourceProvider(
            name="zipball_root",
            # Files, no history: a zipball has no `.git` at all.
            provides=frozenset({VIEW_SOURCE}),
            acquire=lambda: _acquire_zipball_root(project, registry),
        ),
        "git_clone_root": ResourceProvider(
            name="git_clone_root",
            # History, NO files: `--filter=blob:none --no-checkout` yields a
            # root containing only `.git`. Declaring VIEW_SOURCE here would be
            # a lie, and it is the lie that cost finding 52.
            provides=frozenset({VIEW_HISTORY}),
            acquire=lambda: _acquire_git_clone_root(project, registry),
        ),
    }


STEP_REGISTRY: dict[str, StepInfo] = {
    # Ordered ahead of everything, including repo_file_inventory: eight steps
    # read project_stats and this is the only one that writes it. Same reason
    # file_inventory is early — STEP_REGISTRY order is "Repo Full Survey" order,
    # so a refresh placed after its readers leaves them on the previous run's
    # numbers. API-only, no zipball, so it costs nothing to put first.
    # FIRST, and the position is load-bearing. A planner reads stored state to
    # say what a run needs, which is only useful BEFORE the run does it —
    # placed next to the other reducer it landed at index 34 of 36 in "Repo
    # Full Survey", planning a run that had already happened. Full Survey is
    # generated from the "*" sentinel, so position in this dict IS position in
    # that chain. The mirror of repo_security_summary, which must be last.
    "repo_refresh_plan": StepInfo(
        "repo_refresh_plan", RefreshPlanSurveyor,
        "What a refresh would actually need to do: which targets have never run, "
        "which are stale against the current head commit, and which are current. "
        "One GitHub call, no archive download. ADVISORY — the executor runs every "
        "step regardless, so this records the decision rather than enforcing it.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
    ),
    "repo_git_statistics": StepInfo(
        "repo_git_statistics", GitStatisticsSurveyor,
        "Refreshes project_stats (stars, forks, contributors, commit activity, "
        "releases, security config, deployments) from the GitHub API — the table "
        "eight other steps read. Replaces five independent StatsFetcher calls "
        "that each refreshed it separately in the same run.",
        ["ResourceMeasureAnnotation"],
        accepts_fast=True,
        accepts_surveyed_at=True,
        # Measured 2026-08-19/20: 430s against odpi/egeria at fast=False —
        # fetch_diff_stats is one GitHub API call per commit over a 90-day
        # window. No zipball, so compute itself is cheap; the cost is all
        # network/rate-limit.
        fetch_cost="api_heavy",
        compute_cost="low",
    ),
    # FIRST BY NECESSITY, not by taste. This dict's order is also the order
    # "Repo Full Survey" runs (repo_survey_types.csv uses the "*" sentinel,
    # meaning "every current STEP_REGISTRY step in this order"), and six of the
    # steps below read project_file_inventory. Refreshing the table after its
    # consumers have already read it would leave the run reporting the previous
    # extraction while looking like it had just profiled the repo.
    #
    # Costs no extra network call in any survey that already contains a
    # zipball-using step: resolve_resources (D6) downloads and extracts once per
    # SurveyOrchestrator.run() and shares the root with repo_data_profiling and
    # repo_symbol_extraction.
    "repo_file_inventory": StepInfo(
        "repo_file_inventory", FileInventorySurveyor,
        "Refreshes project_file_inventory from a fresh zipball — the table every "
        "file-shape step reads. Closes the gap where the inventory was written "
        "only by RAG ingestion/refresh_profile and never by a survey step, so a "
        "survey reported whatever an earlier, unrelated run had left behind.",
        ["ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        # One of the 4 zipball steps (D3/D4) — a real download, so "none"
        # is invalid here. Walking the extracted tree is cheap.
        fetch_cost="download",
        compute_cost="low",
    ),
    # Closes the same "table nothing but IngestionPipeline ever writes" gap
    # repo_file_inventory closed for project_file_inventory, this time for
    # three tables at once: project_dependencies (full ingestion only — not
    # even refresh_profile writes it), and project_analysis_findings
    # kind="ci_quality"/"repo_conventions" (full ingestion + refresh_profile,
    # but still never a survey step). Measured 2026-08-22: dependencies
    # present for 3/58 registered resources, ci_quality 4/58, repo_conventions
    # 5/58 — the org-import/discovery path deliberately skips ingestion, so
    # for most resources these three were simply empty, and repo_dependency/
    # repo_ci_quality/repo_conventions (all read-only at survey time) reported
    # a confident nothing forever.
    #
    # Positioned directly after repo_file_inventory and before every reader of
    # what it writes (repo_dependency, repo_ci_quality, repo_conventions) —
    # same ordering rule repo_file_inventory's own comment states: this dict's
    # order is "Repo Full Survey" run order, so a step placed after its
    # readers would refresh the tables only after they had already reported
    # the stale/empty copy. Shares repo_file_inventory's zipball_root
    # extraction — no extra network call.
    "repo_manifest_parse": StepInfo(
        "repo_manifest_parse", ManifestParseSurveyor,
        "Parses dependency manifests, CI workflow content, supply-chain signals "
        "and repo-convention signals from a freshly extracted zipball, refreshing "
        "project_dependencies and project_analysis_findings "
        "(kind=\"ci_quality\"/\"repo_conventions\"/\"supply_chain\") — "
        "the three tables previously written only by full ingestion (and, for the "
        "latter two, refresh_profile), never by a survey step.",
        ["ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        # One of the zipball steps (D3/D4) — a real download, so "none" is
        # invalid here.
        #
        # compute_cost="low", corrected from an initial "medium" guess after
        # measuring it (2026-08-23). The reasoning for "medium" was "three
        # parser passes rather than one walk", which sounds right and is not:
        #   sqlglot   359 files -> 0.0s     (repo_file_inventory: 0.0s)
        #   docling 1,652 files -> 0.2s     (repo_file_inventory: 0.3s)
        #   milvus  5,763 files -> 0.6s     (repo_file_inventory: 0.2s)
        # against downloads of 6.7s/84.1s/31.2s for the same repos. It measures
        # like repo_file_inventory, which is "low", not like repo_data_profiling
        # or repo_symbol_extraction. This is not cosmetic: max_compute_cost="low"
        # filters steps out of a run, so "medium" would have excluded this step
        # from the cheap tier it was added to Coarse Profile to serve. Rule 17's
        # principle applied to the compute axis — where a guess and a
        # measurement disagree, the measurement wins.
        fetch_cost="download",
        compute_cost="low",
    ),
    "repo_file_structure": StepInfo(
        "repo_file_structure", FileStructureSurveyor,
        "File counts, per-language breakdown, and top-level directory structure.",
        ["ResourceMeasureAnnotation"],
        # Reads project_stats + project_code_symbols (no zipball, no API) —
        # D4's "17 zero-fetch steps" default. NOT project_file_inventory,
        # despite what this comment said until 2026-08-22: the surveyor takes
        # its file count from project_stats and both breakdowns from
        # project_code_symbols. The distinction matters for ordering — this
        # step's real prerequisite is repo_symbol_extraction, not
        # repo_file_inventory.
    ),
    "repo_file_size": StepInfo(
        "repo_file_size", FileSizeSurveyor,
        "Per-file sizes, total footprint, size-by-type, top-10 largest files.",
        ["ResourceMeasureAnnotation", "RequestForActionAnnotation"],
        accepts_scope_locator=True,
        # Reads project_file_inventory — no fetch of its own.
    ),
    "repo_language": StepInfo(
        "repo_language", LanguageSurveyor,
        "Primary/secondary language and coarse project-type classification.",
        ["ClassificationAnnotation"],
        # Reads project_stats (not project_file_inventory, despite what this
        # comment said until 2026-08-22 — LanguageSurveyor.run() reads
        # get_latest_project_stats() only). Its real prerequisite is therefore
        # repo_git_statistics. No fetch of its own.
    ),
    "repo_health": StepInfo(
        "repo_health", HealthSurveyor,
        "Activity, community, release-cadence, and freshness scoring from GitHub stats.",
        ["QualityScoreAnnotation"],
        accepts_fast=True,
        # Reads project_stats (already fetched by repo_git_statistics) —
        # no API call of its own, confirmed by HealthSurveyor.run() reading
        # registry.get_latest_project_stats() only.
    ),
    "repo_homepage": StepInfo(
        "repo_homepage", HomepageSurveyor,
        "Finds the project's external website — GitHub's declared homepage first, "
        "falling back to pyproject.toml [project.urls], package.json or the README "
        "when that is empty (measured: 11 of 24 registered repos have no declared "
        "homepage). Surfaced in Scouting as a clickable link and published to "
        "Egeria as an ExternalReference linked to the repo.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # Optional, not required: tier 1 reads project_stats and needs no repo
        # contents at all, so this step still produces an answer when run without
        # a zipball. Declaring it means the fallback tiers work for free whenever
        # another step in the same run has already paid for the download.
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        # Optional zipball (see the constructor comment above) but still
        # one of the 4 steps that declare it — "download", not "none",
        # per D3. Parsing pyproject.toml/package.json/README for a URL is
        # cheap.
        fetch_cost="download",
        compute_cost="low",
    ),
    # Directly after repo_homepage, which is what populates projects.homepage_url
    # — STEP_REGISTRY order is also "Full Survey (all steps)" order, so a site
    # ingested before it has been derived would use the previous run's URL.
    "repo_website_ingestion": StepInfo(
        "repo_website_ingestion", WebsiteIngestionSurveyor,
        "Ingests the project's documentation site into pgvector as web_docs_{host}, "
        "so Chat and Understanding can answer from the project's own documentation "
        "rather than only its source tree. Keyed on the site's host, not the repo "
        "slug — several repos in one project share one site and therefore one "
        "collection. Uses the site repo_homepage derived, collapsing versioned docs "
        "to the current release; skips entirely when the repo builds that site "
        "itself, since the source is already ingested in a better form.",
        ["ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        fetch_cost="download",
        compute_cost="medium",
    ),
    "repo_dependency": StepInfo(
        "repo_dependency", DependencySurveyor,
        "Package dependencies per ecosystem (PyPI/npm/Maven).",
        ["DataClassAnnotation", "ResourceMeasureAnnotation"],
        # Read-only over project_dependencies (populated at ingest time) —
        # no fetch, no re-parsing here.
    ),
    "repo_documentation": StepInfo(
        "repo_documentation", DocumentationSurveyor,
        "Presence of README/CHANGELOG/CONTRIBUTING/SECURITY and overall doc-quality label.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # Reads project_file_inventory — no fetch of its own.
    ),
    "repo_security": StepInfo(
        "repo_security", SecurityHygieneSurveyor,
        "Presence of SECURITY.md, CI config, LICENSE — flags gaps as RFAs.",
        ["ClassificationAnnotation", "RequestForActionAnnotation"],
        accepts_surveyed_at=True,
        # Reads project_file_inventory + project_stats — no fetch of its own.
        # (It genuinely does as of 2026-08-22; until then it read
        # project_code_symbols, which cannot contain SECURITY.md or a CI
        # workflow, so every repo failed those two checks. See the surveyor.)
    ),
    "repo_classification": StepInfo(
        "repo_classification", RepoClassificationSurveyor,
        "What the repo represents (7 roles, ranked, multi-valued), where each "
        "artifact its role implies actually lives, and whether architecture "
        "recovery is worth running at all (design §5.5b).",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # MEASURED, not guessed: the presentation session clocked this at 3 repos
        # in 10 minutes, network-blocked, against 1 second for the other three
        # Discovery steps over 60 repos. It was declaring the dataclass default
        # `fetch_cost="none"` — the defining property of the tier — while making
        # a dozen GitHub calls per repo. Declared honestly now; a
        # `max_fetch_cost="none"` run will correctly exclude it.
        fetch_cost="api_heavy",
        # requires_resources={} — but it DOES reach GitHub directly (repo tree,
        # README, sibling-repo listing). Declared as a rule-17 exception in
        # tests/test_analysis_catalog_reader.py rather than hidden behind an
        # empty resource declaration: the zero-fetch signature is a proxy for
        # "cheap enough to gate the expensive tiers", and this is cheap
        # (a handful of API calls) while genuinely fetching.
    ),
    "repo_license_classification": StepInfo(
        "repo_license_classification", LicenseClassifierSurveyor,
        "Classifies the repo's SPDX license id into a risk tier (permissive/"
        "weak copyleft/strong copyleft/source-available/unknown).",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # Reads project_stats.license_spdx_id — the table-read D4 calls
        # out by name as the reason a single blended score would be wrong
        # for this step.
    ),
    "repo_security_features": StepInfo(
        "repo_security_features", SecurityFeaturesSurveyor,
        "GitHub's native security feature toggles (Dependabot, secret "
        "scanning, etc.) — configuration state, not artifact presence.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # Reads project_stats.security_and_analysis_json (already fetched
        # by StatsFetcher) — no new API call, per this surveyor's own
        # docstring.
    ),
    "repo_ci_quality": StepInfo(
        "repo_ci_quality", CiQualitySurveyor,
        "Whether CI workflows actually run tests/lint/build, via a keyword "
        "scan of workflow content — not just whether a CI config exists.",
        ["ClassificationAnnotation"],
        # Read-only at survey time over already-parsed findings (parsing
        # happens once at ingest, per this surveyor's own docstring) — no
        # fetch, no re-scan here.
    ),
    "repo_interface_surface": StepInfo(
        "repo_interface_surface", InterfaceSurfaceSurveyor,
        "What can be talked to, and whether the contract is written down — "
        "from the file inventory and declared dependencies. A committed "
        "openapi.yaml is 'specified'; a fastapi dependency is only 'implied', "
        "and never counts as a published API.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
    ),
    "repo_chaoss_metrics": StepInfo(
        "repo_chaoss_metrics", ChaossMetricsSurveyor,
        "CHAOSS community-health metrics over recorded commits — chiefly the "
        "elephant factor, the fewest contributors accounting for half the "
        "commits. Contributor COUNT calls deep_causality a five-person project; "
        "the distribution says one person wrote 98% of it.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # Reads project_commits, which the stats fetcher already recorded.
    ),
    "repo_cii_badge": StepInfo(
        "repo_cii_badge", CiiBadgeSurveyor,
        "The real OpenSSF Best Practices (CII) badge, read from "
        "bestpractices.dev rather than estimated. Reports the level with the "
        "age of the self-assessment behind it, and keeps 'no badge' apart from "
        "'could not ask'.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # One GET against a public registry — no repo download.
        fetch_cost="api",
    ),
    "repo_community_support": StepInfo(
        "repo_community_support", CommunitySupportSurveyor,
        "Community support as separate dimensions — attention, participation, "
        "channels — rather than one number. repository_health's community_score "
        "is dominated by stars and forks, and scores a four-contributor project "
        "100/100; this reports the weakest dimension instead of averaging it away.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
    ),
    "repo_cve_scan": StepInfo(
        "repo_cve_scan", CveScanSurveyor,
        "Dependency advisories from OSV.dev, over dependencies the manifest "
        "parser already recorded. Reports coverage with the count: declared "
        "dependencies only, and only those with a pinned, parseable version.",
        ["RequestForActionAnnotation", "ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        # One batched call to a public advisory database — no repo download,
        # and nothing fetched about the repo itself.
        fetch_cost="api",
        # Left at the implicit default `low` after measuring, 2026-09-01.
        # 13 runs give median 0.02s and p90 8.1s — over the 5s ceiling, but
        # only 1.6x, and step_cost_observer's ceilings are "generous on
        # purpose ... to catch order-of-magnitude errors, not to police
        # seconds". A 1.6x p90 on n=13 with a 0.02s median is not that.
        # Raising it would also have taken RepoAssessmentSurvey out of its
        # all-low shape, which is a statement about MEMBERSHIP, not a number
        # to bump — see test_analysis_survey_carries_the_expensive_steps.

        requires_context={
            "has_versioned_dependencies":
                "cve_scan queries OSV by (package, VERSION), so a dependency with "
                "no resolved version cannot be asked about — parsed coordinates "
                "alone are not enough",
        },
    ),
    # ── The four GAP analyses (docs/gap-analyses-design.md) ──────────────
    #
    # Registered 2026-09-01. The modules were built standalone and deliberately
    # left unregistered, because this file was contended across several
    # concurrent sessions and `git add` is per-FILE: two sessions editing one
    # StepInfo block cannot be split by `git add -p`, which happened here once
    # already. Registration was serialised through the coordinating session.
    #
    # **Analysis id vs finding kind is stated on every entry**, per the design's
    # §0. That confusion has produced two real bugs — security_summary (fixed)
    # and foss_scorecard, which read kind `security_scan` (an analysis ID that
    # nothing writes), matched 0 rows across 0 repos, and left all 155
    # security-policy verdicts at `unknown`. The ids and kinds below are
    # visibly non-homographic for that reason.
    #
    # All four declare `has_file_inventory`: they read repository CONTENT, and
    # an inventory-less repo must be SKIPPED_BY_DESIGN with a reason rather than
    # scanned to a confident empty result.
    "repo_secret_scan": StepInfo(
        "repo_secret_scan", SecretScanSurveyor,
        "Committed-credential scan over HEAD content, using a VENDORED gitleaks "
        "ruleset (222 rules, MIT, provenance recorded). Reports what it matched "
        "AND which ruleset version it matched with — never 'no secrets', only "
        "'no matches against this ruleset in HEAD'.",
        ["ClassificationAnnotation", "RequestForActionAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        requires_context={
            "has_file_inventory":
                "the scan reads file content; with no inventory it would report "
                "a clean repo it never opened",
        },
        # Writes finding kind `secret_scan_findings` (NOT the analysis id
        # `secret_scan`). Known-positive is the ruleset's own shipped fixtures,
        # not a scanned-file count — a count cannot tell a working scanner from
        # a neutered one.
        fetch_cost="download",
        # VERIFIED and RAISED, 2026-09-01 — this shipped as `medium` with a
        # VERIFY flag, and the first real run settled it: **277.3s on
        # egeria_git**, the slowest step in that repo by a factor of five,
        # against `medium`'s 60s ceiling. 4.6x over is an order-of-magnitude
        # class error, not the 1.4-1.6x noise that left repo_cve_scan and
        # repo_arch_detect deliberately unchanged earlier today.
        #
        # 222 regex rules over every tracked file is genuinely expensive on a
        # large repository, and `medium` was admitting it to runs that had
        # budgeted a minute. Raised rather than optimised: the cost is real, and
        # declaring it honestly is the fix for the wrong tier. Making the scan
        # faster is a separate question from telling callers what it costs.
        compute_cost="high",
    ),
    "repo_telemetry_scan": StepInfo(
        "repo_telemetry_scan", TelemetryScanSurveyor,
        "Telemetry / phone-home indicators: known SDK imports and literal "
        "outbound endpoints, paired with whether the project discloses them. "
        "Never labels an ordinary API client as telemetry.",
        ["ClassificationAnnotation", "RequestForActionAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        requires_context={
            "has_file_inventory":
                "scans source content; without it, absence of a finding would "
                "mean absence of a scan",
        },
        # Writes `telemetry_scan_findings`. Known-positive is
        # source_files_considered > 0 — stronger than inventory presence alone,
        # since it also catches a data-only repo with nothing to scan.
        fetch_cost="download",
        compute_cost="medium",   # VERIFY
    ),
    "repo_contribution_provenance": StepInfo(
        "repo_contribution_provenance", ContributionProvenanceSurveyor,
        "CLA/DCO provenance, kept as two separate questions: whether sign-off is "
        "STATED, and whether it is ENFORCED. Config presence alone is reported "
        "`partial`, never `pass`.",
        ["ClassificationAnnotation", "RequestForActionAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        requires_context={
            "has_file_inventory":
                "reads CONTRIBUTING and enforcement config; a filename alone is "
                "not evidence of what it says",
        },
        # Writes `contribution_provenance_findings`. NOTE a disclosed design
        # gap: `cla_dco_enforced` cannot currently reach `gap`, because
        # branch-protection data is absent from stats_fetcher/security_features
        # (grepped, zero hits). It reports UNVERIFIED rather than inventing a
        # verdict, and the design's "stated but not enforced -> RFA" path is
        # unreachable until that data is fetched.
        fetch_cost="download",
        compute_cost="low",      # VERIFY
    ),
    "repo_sla_content": StepInfo(
        "repo_sla_content", SlaContentSurveyor,
        "Whether the project publishes support or service-level commitments. "
        "Deliberately NEUTRAL (present/absent, not pass/gap): most repositories "
        "legitimately publish none, and absence alone never raises an action.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        requires_context={
            "has_file_inventory":
                "checks candidate SLA paths before reading them",
        },
        # Writes `sla_content_findings`. Known-positive is the list of candidate
        # paths actually checked — recorded even on the absent branch, so
        # "looked and found none" is distinguishable from "never looked".
        fetch_cost="download",
        compute_cost="low",      # VERIFY
    ),
    "repo_foss_scorecard": StepInfo(
        "repo_foss_scorecard", FossScorecardSurveyor,
        "OpenSSF-Scorecard-shaped checks computed from data already held — an "
        "unevaluable check reports unknown and is excluded from the score, "
        "rather than scored zero as OpenSSF's own tool does.",
        ["QualityScoreAnnotation"],
        accepts_surveyed_at=True,
        # Reads project_stats and other analyses' findings — no fetch of its
        # own, the same relationship repo_ci_quality has with its own data.
        #
        # **This is a REDUCER and was not declared as one.** It consumes five
        # other steps' findings through query_findings(): ci_quality,
        # security_hygiene, security_features, cve_scan, supply_chain.
        # repo_security_summary carries "A reducer: no fetch, and no measurement
        # of its own"; this said only "reads ... other analyses' findings",
        # which describes the same fact without naming the dependency, so
        # nothing recorded that its inputs must run first and no test pinned it.
        #
        # It cost a real bug. The kind list said `security_scan` — the analysis
        # ID from analysis_catalog.yaml — where the finding KIND written by
        # SecurityHygieneSurveyor is `security_hygiene`. Measured 2026-09-01:
        # kind `security_scan` had 0 rows across 0 repos while `security_hygiene`
        # had 252 `security_policy` findings, and every foss_scorecard
        # security-policy verdict on record (155) was `unknown`. The scorecard
        # was reporting a fact about its own lookup as a fact about the project.
        #
        # Ordering is now pinned in tests/test_step_execution_order.py — inputs
        # at positions 3-21, this at 22 — so a reordering cannot silently feed
        # it missing inputs.
    ),
    "repo_maturity": StepInfo(
        "repo_maturity", MaturitySurveyor,
        "Project age/lifecycle stage (nascent/emerging/established/mature), "
        "from repo_created_at — a CHAOSS-informed Discovery-tier signal.",
        ["ClassificationAnnotation"],
        # Reads project_stats.repo_created_at — no fetch of its own.
    ),
    "repo_conventions": StepInfo(
        "repo_conventions", RepoConventionsSurveyor,
        "Discovery-tier repo conventions: security policy content, build "
        "automation, deployment/Docker evidence, catalog self-description "
        "(Backstage-style), documentation breadth.",
        ["ClassificationAnnotation"],
        # Read-only at survey time over already-parsed findings (same
        # ingest-time-parsing relationship as repo_ci_quality) — no fetch
        # here.
    ),
    "repo_api_structure": StepInfo(
        "repo_api_structure", ApiStructureSurveyor,
        "Public API surface (functions/classes/methods) per language.",
        ["SchemaAnalysisAnnotation", "ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        accepts_scope_locator=True,
        # Reads project_code_symbols — doesn't extract itself (that's
        # repo_symbol_extraction's job), per this surveyor's own
        # docstring. No fetch, no re-parsing.
    ),
    "repo_data_profiling": StepInfo(
        "repo_data_profiling", DataProfilerSurveyor,
        "Inventories data files and profiles their schema (rows/columns/dtypes/nulls).",
        ["ResourceMeasureAnnotation", "SchemaAnalysisAnnotation", "RequestForActionAnnotation"],
        static_kwargs={"data_path": None},
        accepts_surveyed_at=True,
        accepts_scope_locator=True,
        # D6's own worked example (docs/unified-survey-execution-model-
        # plan.md) — activates DataProfilerSurveyor's Tier 2 (real
        # per-file column profiling from a real local clone) for the
        # first time via any orchestrator-driven path: previously
        # `local_path` was only ever supplied by an explicit caller
        # override (SurveyOrchestrator(data_path=...), the CLI's
        # `--data-path` flag) and never by anything automatic. A real,
        # flagged behavior change (a real zipball download + real network
        # cost this step didn't previously pay through this path) — not
        # silent.
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        # One of the 4 zipball steps. It declared compute_cost="medium" on the
        # reasoning that Tier 2 profiles every readable data file's rows/columns/
        # dtypes/null-rate with pandas — real per-file work beyond a table read.
        #
        # Measurement disagrees, and the evidence had to be narrowed before it
        # meant anything. Raw, this step shows 0.01s median across 85 runs — a
        # number that cannot distinguish "cheap" from "never reached its input",
        # which is the absence-looks-like-zero shape relocated into the measuring
        # instrument (step_cost_observer.Observation.interpretable exists for
        # exactly this, and names this step in its own comment).
        #
        # Restricted to the 26 INTERPRETABLE observations — non-zero annotation
        # count, no `unverified` outcome, so the run provably had work to do:
        # median 39 annotations, elapsed median 0.10s, p90 0.76s, max 1.41s.
        # Comfortably inside `low`'s 5s ceiling WITH proof it was working, which
        # the raw median could never have supported.
        #
        # Over-declaring is not harmless: it excluded this step from
        # max_compute_cost="low" runs — the cheap tier it is well suited to.
        fetch_cost="download",
        compute_cost="low",
    ),
    "repo_file_classification": StepInfo(
        "repo_file_classification", FileClassifierSurveyor,
        "Classifies every file by type using filename/extension mapping (Egeria-enrichable).",
        ["ClassificationAnnotation", "ResourceMeasureAnnotation"],
        static_kwargs={"pyegeria_client": None, "force_refresh": False},
        accepts_scope_locator=True,
        # Reads project_file_inventory + does filename/extension mapping —
        # no fetch, cheap per-file lookup.
    ),
    "repo_symbol_extraction": StepInfo(
        "repo_symbol_extraction", SymbolExtractionSurveyor,
        "Extracts class/function/method symbols (tree-sitter/ast) for every "
        "supported language, refreshing project_code_symbols/"
        "project_code_relationships — D5's self-contained microflow closing "
        "the bug where those tables were only ever populated by RAG "
        "ingestion, never by a survey step.",
        ["ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        # One of the 4 zipball steps. compute_cost="medium", not "low":
        # unlike repo_api_structure (a read of already-extracted symbols),
        # this step does the tree-sitter/ast extraction itself, across
        # every supported-language file in the zipball.
        fetch_cost="download",
        compute_cost="medium",
    ),
    # Architecture recovery — Phase 1 plan §4.2 (docs/architecture-recovery-
    # phase1-plan.md), ported from scripts/arch-spike (44 findings recorded
    # there). Two steps rather than one because they need different shared
    # resources — repo_arch_detect reads files (a zipball is enough),
    # repo_arch_coupling needs real `git log` history (git_clone_root) for
    # co-change — but grouped into one Survey Definition they still share
    # one checkout per resource kind via `_run_batch`. Both write into the
    # existing `project_analysis_findings`/`project_analysis_metrics`
    # tables under kind="architecture_recovery" (design doc §5.4/§6.0) —
    # no new table.
    "repo_arch_detect": StepInfo(
        "repo_arch_detect", ArchDetectSurveyor,
        "Recovers candidate architecture components from package manifests, "
        "deployment units (Dockerfile/compose), and ast-grep code markers — "
        "the deterministic half of architecture recovery (design doc §5.1).",
        ["ResourceMeasureAnnotation", "RequestForActionAnnotation"],
        accepts_surveyed_at=True,
        accepts_scope_locator=True,
        requires_resources={"zipball_root": "local_path"},
        requires_views={"zipball_root": VIEW_SOURCE},
        # Measured on the arch-spike (docs/architecture-recovery-phase1-
        # findings.md §1): 5.3s per repo for the whole toolchain, so "fast"
        # is honest rather than optimistic.
        fetch_cost="download",
        # Measured 2026-09-01, left at `low`: 147 runs, median 1.3s, p90 7.1s.
        # Over the 5s ceiling by 1.4x, which is inside the noise the ceilings
        # were deliberately made generous to tolerate. Recorded rather than
        # acted on, so the next person does not re-derive it.
        compute_cost="low",
    ),
    "repo_arch_coupling": StepInfo(
        "repo_arch_coupling", ArchCouplingSurveyor,
        "Proposes additional architecture-component boundaries from import "
        "coupling and co-change coupling — the conventional, undeclared "
        "components (Agents, Core, Surveyors, ...) that manifests and code "
        "markers structurally cannot see (design doc §5.5, Phase 1 plan "
        "§4.1). Needs real git history, not just a checkout.",
        ["ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        accepts_scope_locator=True,
        requires_resources={"zipball_root": "source_path",
                            "git_clone_root": "history_path"},
        requires_views={"zipball_root": VIEW_SOURCE,
                        "git_clone_root": VIEW_HISTORY},
        fetch_cost="download",
        # Re-declared 2026-09-01 from 32 measured runs: p90 132s against the
        # 60s `medium` ceiling, median 0 connects. The git-history walk is
        # real compute, and calling it medium admitted it to runs that had
        # budgeted a minute.
        compute_cost="high",
    ),
    "repo_arch_lens": StepInfo(
        "repo_arch_lens", ArchLensSurveyor,
        "Labels recovered components against the project's own architecture "
        "document, wherever it lives — in-repo, a sibling repository, or a "
        "documentation site. A LENS: it adds no component, removes none and "
        "assigns no type. Milvus goes from 206 candidates to 15 the authors "
        "actually name (finding 102).",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # Between coupling and summary: it needs components to label, and the
        # summary is worth more once it can say "documented" instead of
        # "candidate". Registry order generates the chain — the ordering defect
        # caught by the reconciler when repo_arch_summary was first placed
        # before coupling is the reason that is spelled out here.
        requires_resources={},
        # NOT zero-fetch, and that is the third exception in a tier described as
        # zero-fetch by construction (see analysis_catalog.yaml's note on
        # architecture_recovery, and repo_classification's). Up to
        # MAX_DOC_FILES GitHub calls, often against a DIFFERENT repository.
        # Recorded rather than quietly added: three exceptions is where
        # "discovery is zero-fetch" stops being a rule and becomes a slogan.
        fetch_cost="api",
        compute_cost="low",
    ),
    "repo_arch_summary": StepInfo(
        "repo_arch_summary", ArchSummarySurveyor,
        "Collapses architecture-recovery findings to the depth the question "
        "asked for — the summarising half nothing owned. Milvus recovers 218 "
        "candidate components where its own authors describe eight; a "
        "suitability answer is 'serves gRPC (297 operations), 24 runnable "
        "units, 31 third-party'.",
        ["ResourceMeasureAnnotation"],
        # ORDER MATTERS, and registry order is what generates the chain. Placed
        # after repo_arch_coupling deliberately: a summary that runs before a
        # step it summarises silently reports a partial answer. First placed
        # BEFORE coupling, and the reconciler's dry run caught it as a stale
        # detect->coupling edge in RepoFullSurvey — the chain would have been
        # detect -> summary -> coupling, summarising only half the components.
        accepts_surveyed_at=True,
        # The first step whose input is another step's OUTPUT rather than an
        # external resource. Egeria models that as action targets on the
        # GovernanceActionExecutor (0462); `requires_resources` is RE's
        # mechanism for SHARING an expensive external resource across steps in
        # one run and is deliberately empty here — a summary needs no zipball
        # and no clone, which puts it at Discovery tier by rule 17's own test
        # and makes it cheap enough to recompute whenever its inputs change.
        requires_resources={},
        fetch_cost="none",
        compute_cost="low",
    ),
    "repo_sub_resource_survey": StepInfo(
        "repo_sub_resource_survey", SubResourceSurveyor,
        "Surveys file/folder characteristics to recommend which sub-resources "
        "are worthy of cataloging as their own Egeria assets (Assessment "
        "sub-resource cataloging plan) — survey only, does not catalog.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # Not in D4's explicit measurement list — flagged here rather than
        # left at the "none" default, and picked conservatively pending a
        # real measurement. _codeowners_rules() makes one API call, and
        # _attach_tier2_dates() makes one further get_commits() call PER
        # "worthy" finding (Tier 2 dates) — bounded by worthy-entry count
        # rather than total commit count like repo_git_statistics, but the
        # same N+1-shaped sequential-API-calls pattern that made
        # repo_git_statistics expensive. compute_cost stays "low": the
        # cost here is network/rate-limit, not CPU.
        fetch_cost="api_heavy",
        compute_cost="low",
    ),
    # LAST BY NECESSITY, the mirror image of repo_git_statistics/
    # repo_file_inventory being first. Those are first because other steps read
    # what they write; nothing downstream reads what this one writes — pgvector
    # is consumed by Chat and the query router, not by other survey steps — and
    # this is by far the most expensive operation in the set. Since this dict's
    # order is also "Full Survey (all steps)" order (the "*" sentinel in
    # repo_survey_types.csv), putting it anywhere but last would delay every
    # cheap signal a survey exists to produce.
    #
    # No requires_resources on purpose: IncrementalIndexer downloads its own
    # zipball only when there are changed files, so declaring the shared
    # zipball_root would force a download on every run including the common
    # no-op case. The resource-sharing win doesn't apply to a step whose common
    # case is fetching nothing at all.
    # Placed after every security step it reads, and BEFORE
    # repo_rag_ingestion, which has its own invariant: it is the most
    # expensive step and nothing downstream reads it, so it stays last
    # and must not delay the cheap signals a survey exists to produce
    # (test_rag_ingestion_runs_last).
    #
    # Position here is load-bearing: "Repo Full Survey" is generated from
    # the "*" sentinel — every STEP_REGISTRY step in this dict's order —
    # so where this entry sits IS its position in that chain. Written
    # first next to the other security steps, it landed at index 21 of 34,
    # ahead of foss_scorecard and cve_scan, and would have reduced over
    # inputs that had not run yet. Moving it to the very end then
    # displaced rag_ingestion and broke that invariant instead. The
    # requirement is "after its inputs", not "last" — the two only looked
    # the same in the Assessment Survey, where nothing follows it anyway.
    "repo_security_summary": StepInfo(
        "repo_security_summary", SecuritySummarySurveyor,
        "Reduces the security family's stored findings to one topic summary. "
        "Measures nothing itself — it reads what the other security steps wrote, "
        "so it belongs LAST in any survey that runs them. Reports coverage and "
        "the age of its oldest input alongside the verdict, and refuses a verdict "
        "at all below four inputs.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
        # A reducer: no fetch, and no measurement of its own.
    ),
    "repo_rag_ingestion": StepInfo(
        "repo_rag_ingestion", RagIngestionSurveyor,
        "Refreshes the project's pgvector collections via IncrementalIndexer — "
        "the queryable representation Chat, the query router and every "
        "RAG-backed answer read, previously built only at registration, on "
        "webhook or from a bespoke route branch and never by a survey step. "
        "A no-op when the repository's last indexed commit is unchanged.",
        ["ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        # compute_cost="high" (D4 explicit): embeds the repository.
        # fetch_cost="download" records the worst case, not the common
        # one — IncrementalIndexer downloads only when the last-indexed
        # SHA moved (see the "No requires_resources on purpose" comment
        # above), which is exactly the conditionality a coarse ordinal
        # field can't express. Recorded here rather than inventing a
        # fifth fetch_cost value, per D4.
        fetch_cost="download",
        compute_cost="high",
    ),
}


def _run_step(step_key: str, **orchestrator_kwargs):
    def runner(project, registry, fast: bool = False, **_) -> dict:
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        orch = SurveyOrchestrator(registry, **orchestrator_kwargs)
        # fast only actually applies to steps whose StepInfo.accepts_fast is
        # True (repo_health today) — SurveyOrchestrator.run() ignores it for
        # every other step, so forwarding it unconditionally here is safe
        # for any step_key, not just the ones that care.
        result = orch.run(project.slug, steps=[step_key], fast=fast)
        return {"annotations": result.annotations}

    return runner


def _run_batch(project, registry, step_keys: list[str], fast: bool = False, **_) -> dict:
    """D1 (docs/survey-tab-unification-plan.md) — repo's ResourceTypeAdapter.run_batch:
    one SurveyOrchestrator.run() call for a whole group of step_keys instead
    of one call per key. This is what actually lets D6's shared-resource
    dedup (trellis_microflow.resolve_resources) do its job for a multi-step
    Survey Definition — e.g. a 'Coarse Profile' survey whose steps all
    declare requires_resources={"zipball_root": ...} downloads the zipball
    once for the whole group, not once per step, since resolve_resources
    only dedupes *within* a single .run() call."""
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    orch = SurveyOrchestrator(registry)
    result = orch.run(project.slug, steps=step_keys, fast=fast)
    return {"annotations": result.annotations, "errors": result.errors}


def validate_resource_views(registry: dict | None = None,
                            providers: dict | None = None) -> list[str]:
    """Every declared view must be supplied by the named resource.

    Run at import (below). Raises rather than warns: a step wired to a
    resource that cannot give it what it reads does not degrade gracefully —
    it silently produces nothing, which is indistinguishable from "this repo
    has no components" and is exactly how finding 52 survived a full test
    suite and a live run.

    A provider with no declared `provides` is skipped rather than assumed
    empty, so third-party or not-yet-annotated providers do not break the
    build; the exhaustiveness test covers that gap instead.
    """
    registry = STEP_REGISTRY if registry is None else registry
    if providers is None:
        providers = _resource_providers_for(None, None)
    problems: list[str] = []
    for step_key, info in registry.items():
        for resource_name, view in (info.requires_views or {}).items():
            if resource_name not in info.requires_resources:
                problems.append(
                    f"{step_key}: declares view {view!r} for {resource_name!r}, "
                    f"which it does not require")
                continue
            provider = providers.get(resource_name)
            if provider is None or not provider.provides:
                continue
            if view not in provider.provides:
                problems.append(
                    f"{step_key}: reads {view!r} from {resource_name!r}, which "
                    f"provides {sorted(provider.provides)}")
    return problems


_VIEW_PROBLEMS = validate_resource_views()
if _VIEW_PROBLEMS:                       # fail at import, not at survey time
    raise RuntimeError(
        "resource view mismatch in STEP_REGISTRY:\n  " + "\n  ".join(_VIEW_PROBLEMS))


def _build_re_analysis_steps() -> dict:
    """Derived from STEP_REGISTRY — each step key delegates to
    SurveyOrchestrator.run(steps=[key]) rather than instantiating its own
    surveyor closure, so STEP_REGISTRY stays the single source of truth for
    what each key means and how its surveyor is constructed."""
    return {key: _run_step(key, **info.static_kwargs) for key, info in STEP_REGISTRY.items()}


_RE_ANALYSIS_STEP_INFO = {
    key: {"description": info.description, "annotation_types": info.annotation_types}
    for key, info in STEP_REGISTRY.items()
}


# ── Analysis-kind (catalog-id) level registry ────────────────────────────
# analysis_id -> (results_reader, trend_reader). Each results_reader(registry,
# slug) -> dict of latest structured results; each trend_reader(registry,
# slug) -> list[{"surveyed_at": str, "value": number, ...}] for the trend
# chart. Only the 5 analysis-catalog entries actually shown under Analysis/
# Assessment have one — language_file_classification/repository_health are
# scouting-tagged, no results view.

def _file_classification_results(registry, slug: str) -> dict:
    # project_file_type_counts is written by FileClassifierSurveyor
    # (repo_file_classification step) — already has full history/trend
    # support from Phase B (the "Understanding" survey_history chart reads
    # the same table). Surfaced here so the Scouting "Profile" tab's
    # auto-chained refresh->classify has something real to display, closing
    # the gap where classification data was refreshed but never shown.
    rows = registry.query_file_type_counts(slug)
    surveyed_at = rows[0]["surveyed_at"] if rows else ""
    # Code volume, from the census written at ingestion / profile refresh
    # (design doc D1, pipeline.py::_record_line_census).
    #
    # D1 emitted the decomposition as ANNOTATIONS and stopped there — the
    # same mistake D3 made with complexity, made twice in one session.
    # Questions are answered through THIS reader, so "How much code is
    # there?" could not see a single line count no matter how many surveys
    # ran. Verifying the annotation was not verifying the answer.
    #
    # An absent census contributes no keys at all, never zeros: a repo
    # indexed before this existed has not been counted, which is not the
    # same as having no code.
    import json as _json

    volume = registry.query_metrics(slug, "code_volume") or {}
    detail = volume.get("detail")
    if isinstance(detail, str):
        detail = _json.loads(detail or "{}")
    by_language = (detail or {}).get("by_language") or {}
    counted = {k: v for k, v in by_language.items() if not v.get("text_only")}

    volume_fields = {}
    if counted:
        volume_fields = {
            "code_lines": sum(v.get("code", 0) for v in counted.values()),
            "comment_lines": sum(v.get("comment", 0) for v in counted.values()),
            "docstring_lines": sum(v.get("docstring", 0) for v in counted.values()),
            "blank_lines": sum(v.get("blank", 0) for v in counted.values()),
            "source_files": sum(v.get("files", 0) for v in counted.values()),
            "lines_by_language": {
                lang: {"code": v.get("code", 0), "comment": v.get("comment", 0),
                       "docstring": v.get("docstring", 0), "blank": v.get("blank", 0)}
                for lang, v in counted.items()
            },
            "text_only_languages": sorted(
                k for k, v in by_language.items() if v.get("text_only")),
        }

    return {
        "by_type": [{"type_label": r["type_label"], "file_count": r["file_count"]} for r in rows],
        "total_files": sum(r["file_count"] for r in rows),
        **volume_fields,
        "surveyed_at": surveyed_at,
    }


def _file_classification_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["total_files"]}
        for r in registry.query_file_type_history(slug)
    ]


def _dependency_results(registry, slug: str) -> dict:
    deps = registry.query_dependencies(slug)
    by_ecosystem: dict[str, list] = {}
    for d in deps:
        by_ecosystem.setdefault(d["ecosystem"] or "other", []).append(d)
    return {"by_ecosystem": by_ecosystem, "total": len(deps)}


def _dependency_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["total_dependencies"]}
        for r in registry.query_dependencies_history(slug)
    ]


def _data_profile_results(registry, slug: str) -> dict:
    profiles = registry.get_data_profiles(slug)
    metric_detail = (registry.query_metrics(slug, "data_profile") or {}).get("detail") or {}
    # The status rides along from the metric row DataProfilerSurveyor writes on
    # every terminal path, including its zeros. Without it a repo that was
    # scanned and provably has no data files renders identically to one that was
    # never scanned — 36 of them, measured 2026-08-24.
    #
    # `formats` (2026-09-03, Backlog item 3's sweep): the per-format
    # breakdown (count/total_size/directories) is computed over EVERY
    # detected data file, including ones later skipped as too-large-to-
    # profile — those rows never appear in `profiles` (get_data_profiles
    # only returns files that were actually profiled), so `formats` is the
    # only place a too-large-to-profile file is counted by format/location
    # at all. It was persisted and silently unreachable through this reader.
    return attach_status(
        {"profiles": profiles, "total": len(profiles),
         "formats": metric_detail.get("formats", {})},
        metric_detail,
    )


def _data_profile_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "data_profile", "total_files")
    ]


def _security_results(registry, slug: str) -> dict:
    # Generic findings table (analysis-kind extensibility redesign) — same
    # uniform {check_name, label, summary, confidence} shape as
    # _documentation_results below, so the frontend's "findings_list" render
    # mode needs zero per-kind logic (D4). "gap_count" stays as an extra,
    # kind-specific top-level key alongside the generic findings list.
    rows = registry.query_findings(slug, "security_hygiene")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings, "gap_count": sum(1 for f in findings if f["label"] == "gap")}


def _security_trend(registry, slug: str) -> list[dict]:
    # query_findings_history_raw returns raw rows across all runs — this
    # kind's own trend aggregation (gap-count per run) lives here, not as
    # per-kind SQL in the registry layer.
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "security_hygiene"):
        bucket = by_run.setdefault(r["surveyed_at"], {"gap": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] == "gap":
            bucket["gap"] += 1
    return [
        {"surveyed_at": ts, "value": counts["gap"], "total_checks": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _documentation_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results uses — see its comment.
    rows = registry.query_findings(slug, "documentation")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    # The status rides on the quality_score row, which is the one
    # DocumentationSurveyor labels `Unverified` when the file inventory is
    # empty — the case where "Minimal" would be a confident verdict about a
    # repo whose files were never read.
    quality = next((r for r in rows if r["check_name"] == "quality_score"), None)
    return attach_status({"findings": findings},
                         _as_detail(quality.get("detail_json")) if quality else None)


def _gap_analysis_results(registry, slug: str, kind: str) -> dict:
    """Results reader for the four GAP analyses — the uniform `findings_list` shape.

    Added 2026-09-01 because `test_every_findings_producing_analysis_has_a
    _dashboard` failed, and it was RIGHT. Registration originally shipped these
    four with `results=None`, reasoning that a results view was separate work and
    a half-built one would render an absence as an answer.

    That reasoning was backwards. An analysis that WRITES findings and has no
    dashboard does not show a cautious nothing — it shows nothing at all, and the
    findings are write-only: computed, stored, unreachable. That is the same
    defect the annotation-linking audit named as the codebase's strongest
    evidence-loss case, where cve_scan reduced per-CVE detail to bare counts
    before anything could read it.

    `findings_list` needs no new frontend code (D4), so doing this properly cost
    a reader per kind, not a view.

    Status comes from the `scan_summary` row, which each of the four writes and
    which is where the outcome vocabulary lands — SKIPPED_BY_DESIGN with a reason
    when a precondition is unmet, NO_SIGNAL with `known_positive` when the scan
    ran and matched nothing. Reading status from there rather than inferring it
    from an empty list is the point: "no individual findings" and "did not run"
    are different statements.

    `detail` is passed through wholesale (2026-09-03, Backlog item 3's
    31-reader sweep) rather than dropped: secret_scan's per-match `excerpt` —
    the actual matched text a reviewer needs to triage without re-opening
    path:line — was computed, persisted, and unreachable through this reader
    for every one of the four kinds it serves, since it stripped every
    finding down to check_name/label/summary/confidence. Every other
    per-finding `detail` field checked in this sweep (telemetry_scan,
    contribution_provenance, sla_content) was confirmed redundant with what
    `summary`/`label` already say, so passing it through costs nothing for
    those — but a reader deciding in advance what a future writer's `detail`
    will or won't contain is exactly the failure mode this sweep exists to
    close, matching `_refresh_plan_results`/`_security_summary_results`'s
    existing full-passthrough shape rather than re-inventing a narrower one.
    """
    rows = registry.query_findings(slug, kind)
    findings = [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"],
         "detail": _as_detail(r.get("detail_json"))}
        for r in rows
    ]
    summary = next((r for r in rows if r["check_name"] == "scan_summary"), None)
    return attach_status({"findings": findings},
                         _as_detail(summary.get("detail_json")) if summary else None)


def _secret_scan_results(registry, slug: str) -> dict:
    return _gap_analysis_results(registry, slug, "secret_scan_findings")


def _telemetry_scan_results(registry, slug: str) -> dict:
    return _gap_analysis_results(registry, slug, "telemetry_scan_findings")


def _contribution_provenance_results(registry, slug: str) -> dict:
    return _gap_analysis_results(registry, slug, "contribution_provenance_findings")


def _sla_content_results(registry, slug: str) -> dict:
    return _gap_analysis_results(registry, slug, "sla_content_findings")


def _license_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results/_documentation_results
    # use — license classification produces exactly one finding per run, so
    # this is the smallest possible "findings_list" consumer, not a special
    # case. No trend reader: license rarely changes, so a run-over-run chart
    # would be a flat line with almost no analytical value (Assessment
    # expansion plan B1).
    rows = registry.query_findings(slug, "license_classification")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _as_detail(raw) -> dict:
    """A finding's detail blob as a dict, whatever the backend handed back."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def _repo_classification_results(registry, slug: str) -> dict:
    """Same uniform finding shape the license/security readers use, plus
    `detail` — which the other readers drop and this one cannot.

    Everything that makes this analysis legible lives in the detail blob: an
    expected artifact's `evidence` and `date` (a location is only meaningful
    with the thing that proved it), the ranked `roles` list behind the primary
    one, and the gate's `result_status` when it declined to run. Without them
    the card can say "readme: sibling-repo" but not WHICH repo or how recently,
    which is most of the answer. §5.5b's location-not-boolean point only holds
    if the location arrives with its evidence.
    """
    rows = registry.query_findings(slug, "repo_classification")
    findings = [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"],
         # detail_json, not detail: query_findings returns the raw column, and
         # Postgres hands back JSONB as a dict where SQLite hands back a string
         # — the same backend split that has bitten this codebase repeatedly,
         # so it is normalised here rather than in the template.
         "detail": _as_detail(r.get("detail_json"))}
        for r in rows
    ]
    return {"findings": findings}


def _security_features_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results/_license_results use.
    # Unlike license_classification, this DOES get a trend reader (below) —
    # feature toggles can genuinely change run-to-run (a repo admin flips
    # secret scanning on), unlike a license which almost never changes.
    rows = registry.query_findings(slug, "security_features")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    if findings:
        return {"findings": findings}

    # No findings has two very different causes, and an empty list tells them
    # apart for nobody.
    #
    # GitHub returns `security_and_analysis` ONLY to callers with admin access
    # to the repository. For a third-party repo it comes back empty however many
    # times this runs — the analysis is not failing, it is structurally
    # impossible, which is a fact about GitHub's API and not about the run.
    # Measured 2026-08-25: 2 of 60 repos in this corpus have any findings, and
    # both are the operator's own. The other 58 rendered as an empty card.
    #
    # `skipped_by_design` is the honest state and its reason is required, for
    # exactly this: a skip with no stated reason is indistinguishable from a
    # failure on the screen.
    stats = registry.get_latest_project_stats(slug) or {}
    if not stats:
        # No stats at all: the step this reads from has never run for this repo,
        # which is a third distinct cause and must not be folded into either of
        # the others. Stated rather than left as a bare empty list.
        return {
            "findings": [],
            "_status": {
                "state": result_status.NEVER_RUN,
                "hint": "Repository statistics have not been fetched for this repo yet.",
            },
        }
    raw = stats.get("security_and_analysis_json")
    visible = bool(raw) and raw not in ("{}", "null")
    if not visible:
        return {
            "findings": [],
            "_status": result_status.skipped(
                "GitHub only returns security feature settings to repository "
                "admins, so these are invisible for a repo you do not own. "
                "Not a gap in the repository.",
                gate="github_admin_only",
            ),
        }
    # Visible and genuinely nothing enabled — a real, final answer.
    return {"findings": []}


def _security_features_trend(registry, slug: str) -> list[dict]:
    # Enabled-count per run — mirrors _security_trend's gap-count-per-run
    # shape, just counting "pass" (enabled) instead of "gap".
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "security_features"):
        bucket = by_run.setdefault(r["surveyed_at"], {"enabled": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] == "pass":
            bucket["enabled"] += 1
    return [
        {"surveyed_at": ts, "value": counts["enabled"], "total_features": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _ci_quality_results(registry, slug: str) -> dict:
    # Same uniform finding shape as _security_results/_license_results, plus
    # `detail` (2026-09-03, Backlog item 3's sweep): the summary text
    # truncates matched_keywords to the first 3 and never names
    # workflow_files at all, so which config file(s) actually produced a
    # verdict — and any keyword past the third — was unreachable without it.
    rows = registry.query_findings(slug, "ci_quality")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"],
         "confidence": r["confidence"], "detail": _as_detail(r.get("detail_json"))}
        for r in rows
    ]
    return {"findings": findings}


def _interface_surface_results(registry, slug: str) -> dict:
    # `detail` added 2026-09-03 (Backlog item 3's sweep): this module's own
    # docstring says evidence strength is "the entire point of the
    # analysis", yet the summary text truncates `files`/`dependencies` to
    # the first 3 and never states `file_count` — so the exact count and the
    # full list past 3 were unreachable through this reader for every
    # 'specified'/'implied' finding.
    rows = registry.query_findings(slug, "interface_surface")
    return {"findings": [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"],
         "detail": _as_detail(r.get("detail_json"))}
        for r in rows
    ]}


def _interface_surface_headline(registry, slug: str) -> dict | None:
    """Specified interfaces, and whether a contract is published.

    An implied interface never reaches the headline on its own: "depends on
    fastapi" is not an API this project offers, and a headline is exactly where
    that distinction gets lost.
    """
    rows = _interface_surface_results(registry, slug)["findings"]
    if not rows:
        return None
    specified = [r["check_name"] for r in rows if r["label"] == "specified"]
    published = next((r["label"] for r in rows
                      if r["check_name"] == "published_spec"), "")
    if specified:
        return {"label": f"{', '.join(specified)} (specified)", "tone": "good"}
    implied = [r["check_name"] for r in rows if r["label"] == "implied"]
    if implied:
        return {"label": f"{', '.join(implied[:3])} implied, no published contract",
                "tone": "warn"}
    return {"label": "no interface signals found",
            "tone": "warn" if published == "no" else ""}


def _chaoss_metrics_results(registry, slug: str) -> dict:
    rows = registry.query_findings(slug, "chaoss_metrics")
    return {"findings": [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]}


def _chaoss_metrics_trend(registry, slug: str) -> list[dict]:
    return registry.query_metrics_history(slug, "chaoss_metrics", "elephant_factor")


def _chaoss_metrics_headline(registry, slug: str) -> dict | None:
    """Authorship concentration, never an average of the metrics.

    Averaging is exactly what let a project one person wrote 98% of score
    100/100 on repository_health's community_score.
    """
    rows = _chaoss_metrics_results(registry, slug)["findings"]
    if not rows:
        return None
    ef = next((r for r in rows if r["check_name"] == "elephant_factor"), None)
    if not ef or ef["label"] == "not_established":
        return {"label": "authorship concentration unknown", "tone": "neutral"}
    tone = {"sole": "warn", "narrow": "warn"}.get(ef["label"], "ok")
    # The CHAOSS term stays, after the plain reading rather than instead of
    # it: "elephant factor: sole" led with jargon and left a reader to look
    # it up before knowing whether it was good news.
    plain = {
        "sole": "one contributor writes most of the code",
        "narrow": "a handful of contributors write most of the code",
        "broad": "authorship is spread across many contributors",
    }.get(ef["label"], f"authorship concentration: {ef['label']}")
    return {"label": f"{plain} (CHAOSS elephant factor: {ef['label']})", "tone": tone}


def _cii_badge_results(registry, slug: str) -> dict:
    # `detail` added 2026-09-03 (Backlog item 3's sweep): the summary text
    # for `badge_level` never states `url`/`project_id` — the only way to
    # click through and verify the actual badge record, exactly the
    # "location without evidence" failure this module's own sibling readers
    # warn against — and `criteria_coverage`'s summary states only the
    # *count* of unmet criteria, never `unmet_criteria` itself (which ones).
    rows = registry.query_findings(slug, "cii_badge")
    return {"findings": [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"],
         "detail": _as_detail(r.get("detail_json"))}
        for r in rows
    ]}


def _cii_badge_headline(registry, slug: str) -> dict | None:
    """Three outcomes, never two.

    "not registered" is an answer about the project; "could not be looked up"
    is an answer about us, and rendering the second as the first would be a
    claim about someone's project derived from our own connectivity.
    """
    rows = _cii_badge_results(registry, slug)["findings"]
    if not rows:
        return None
    level = next((r for r in rows if r["check_name"] == "badge_level"), None)
    if not level or level["label"] == "not_established":
        return {"label": "badge could not be looked up", "tone": "neutral"}
    if level["label"] == "not_registered":
        return {"label": "no OpenSSF badge", "tone": "warn"}
    stale = any(r["check_name"] == "badge_freshness" and r["label"] == "stale"
                for r in rows)
    return {"label": f"OpenSSF badge: {level['label']}"
                     + (" (stale)" if stale else ""),
            "tone": "warn" if stale else "ok"}


def _community_support_results(registry, slug: str) -> dict:
    rows = registry.query_findings(slug, "community_support")
    return {"findings": [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]}


def _community_support_headline(registry, slug: str) -> dict | None:
    """The WEAKEST dimension, never an average.

    Averaging is what let 683 stars mask four contributors in
    repository_health's community_score. A reader deciding whether to depend on
    something needs the weakest link named, not smoothed out.
    """
    rows = _community_support_results(registry, slug)["findings"]
    if not rows:
        return None
    by_name = {r["check_name"]: r["label"] for r in rows}
    if by_name.get("attention_exceeds_participation") == "yes":
        return {"label": "widely used, narrowly maintained", "tone": "warn"}
    participation = by_name.get("participation") or ""
    plain = {
        "sole_maintainer": "maintained by one person",
        "small_team": "maintained by a small team",
        "team": "maintained by a team",
        "broad": "maintained by a broad community",
    }
    if participation in ("sole_maintainer", "small_team"):
        return {"label": plain[participation], "tone": "warn"}
    if participation:
        return {"label": plain.get(participation, f"{participation} participation"),
                "tone": "good"}
    return {"label": "participation not established", "tone": "warn"}


def _cve_scan_results(registry, slug: str) -> dict:
    """Findings plus coverage, and coverage is not optional here.

    A clean CVE result means "none of the dependencies we could check had an
    advisory". Without `checked`/`unqueryable`/`ecosystems_seen` beside it, that
    is indistinguishable from "this repo has no vulnerable dependencies" — a
    claim this analysis cannot make, since it sees declared dependencies only.
    """
    rows = registry.query_findings(slug, "cve_scan")
    findings = [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    metrics = registry.query_metrics(slug, "cve_scan") or {}
    out = {"findings": findings}
    for key in ("advisories", "packages_affected", "checked", "unqueryable"):
        if key in metrics:
            out[key] = metrics[key]
    detail = metrics.get("detail") or {}
    if isinstance(detail, dict):
        for key in ("ecosystems_seen", "recorded", "scanned", "excludes_transitive"):
            if key in detail:
                out[key] = detail[key]
    return out


def _cve_scan_trend(registry, slug: str) -> list[dict]:
    return registry.query_metrics_history(slug, "cve_scan", "advisories")


def _cve_scan_headline(registry, slug: str) -> dict | None:
    data = _cve_scan_results(registry, slug)
    if not data.get("scanned"):
        return None
    advisories = int(data.get("advisories") or 0)
    checked = int(data.get("checked") or 0)
    recorded = int(data.get("recorded") or checked)
    if advisories:
        return {"label": f"{advisories} advisor{'y' if advisories == 1 else 'ies'} "
                         f"across {int(data.get('packages_affected') or 0)} "
                         f"{_plural('package', int(data.get('packages_affected') or 0))}",
                "tone": "bad"}
    # A clean result never states itself without its coverage.
    return {"label": f"none in {checked} of {recorded} declared dependenc(ies)",
            "tone": "good" if checked == recorded else "warn"}


def _refresh_plan_results(registry, slug: str) -> dict:
    rows = registry.query_findings(slug, "refresh_plan")
    return {"findings": [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"],
         "confidence": r["confidence"], "detail": _json_or_empty(r.get("detail_json")),
         "surveyed_at": r["surveyed_at"]}
        for r in rows
    ]}


def _refresh_plan_headline(registry, slug: str) -> dict | None:
    """States that it is advisory, because a plan read as an action is the whole
    risk here — "nothing to refresh" must not be mistaken for "nothing ran"."""
    rows = _refresh_plan_results(registry, slug)["findings"]
    if not rows:
        return None
    overall = next((r for r in rows if r["check_name"] == "refresh_needed"), None)
    if not overall:
        return None
    if overall["label"] == "unknown":
        return {"label": "refresh need unknown — head commit unreadable", "tone": "neutral"}
    d = overall["detail"]
    if overall["label"] == "no":
        return {"label": f"nothing stale ({d.get('total')} targets current)", "tone": "good"}
    return {"label": f"{d.get('needed')} of {d.get('total')} targets need refreshing",
            "tone": "warn"}


def _security_summary_results(registry, slug: str) -> dict:
    """The reduced topic summary. Findings only — the interesting values
    (coverage, oldest input) already ride in each finding's detail, and
    duplicating them at the top would give two places to disagree."""
    rows = registry.query_findings(slug, "security_summary")
    return {"findings": [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"],
         "confidence": r["confidence"], "detail": _json_or_empty(r.get("detail_json")),
         "surveyed_at": r["surveyed_at"]}
        for r in rows
    ]}


def _security_summary_headline(registry, slug: str) -> dict | None:
    """Coverage and staleness are part of the headline, not a detail below it.

    A one-word verdict is the whole risk of a topic summary: "clean" over four
    of eight inputs, resting on month-old evidence, reads identically to "clean"
    over all eight measured this morning. If the tile has room for one line, that
    line has to carry both.
    """
    rows = _security_summary_results(registry, slug)["findings"]
    if not rows:
        return None
    posture = next((r for r in rows if r["check_name"] == "security_posture"), None)
    coverage = next((r for r in rows if r["check_name"] == "input_coverage"), None)
    fresh = next((r for r in rows if r["check_name"] == "summary_freshness"), None)
    if not posture or not posture["detail"].get("known"):
        return {"label": "not enough inputs to summarise", "tone": "neutral"}

    cov = coverage["detail"] if coverage else {}
    bits = [f"security: {posture['label']}"]
    if cov.get("total"):
        bits.append(f"{cov.get('covered')}/{cov.get('total')} inputs")
    if fresh and fresh["label"] == "stale":
        bits.append("evidence is stale")
    tone = ("bad" if posture["label"] == "concerns"
            else "warn" if (fresh and fresh["label"] == "stale") or cov.get("missing")
            else "good")
    return {"label": " · ".join(bits), "tone": tone}


def _foss_scorecard_results(registry, slug: str) -> dict:
    """Findings plus the aggregate, which is the point of a scorecard.

    `checks_evaluated`/`checks_unknown` travel WITH the score. A scorecard
    number without its coverage is what this analysis exists to avoid: 8.0
    over five checks and 8.0 over twelve are different claims.

    That claim was being violated by this function itself until the
    silent-field-allowlist sweep (docs/Backlog.md item 3, following the
    pattern finding 118 named): `score()` (foss_scorecard.py) computes and
    persists `checks_total` and `comparable_to_openssf` in `detail` alongside
    the three metric keys below, but only the three were ever read back —
    `checks_total`, the denominator this docstring's own example depends on,
    was silently dropped, and `_foss_scorecard_headline` rendered "8.0/10
    over 5 checks" with no way to say whether that was 5 of 5 or 5 of 12.
    Mirrors `_cve_scan_results`'s existing two-loop shape (metrics, then
    detail) rather than inventing a new one.
    """
    rows = registry.query_findings(slug, "foss_scorecard")
    findings = [
        {"check_name": r["check_name"], "label": r["label"],
         "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    metrics = registry.query_metrics(slug, "foss_scorecard") or {}
    out = {"findings": findings}
    for key in ("score", "checks_evaluated", "checks_unknown"):
        if key in metrics:
            out[key] = metrics[key]
    detail = metrics.get("detail") or {}
    if isinstance(detail, dict):
        for key in ("checks_total", "comparable_to_openssf"):
            if key in detail:
                out[key] = detail[key]
    return out


def _foss_scorecard_trend(registry, slug: str) -> list[dict]:
    return registry.query_metrics_history(slug, "foss_scorecard", "score")


def _foss_scorecard_headline(registry, slug: str) -> dict | None:
    data = _foss_scorecard_results(registry, slug)
    if not data.get("findings"):
        return None
    score = data.get("score")
    if score is None:
        return {"label": "no check could be evaluated", "tone": "warn"}
    evaluated = int(data.get("checks_evaluated") or 0)
    unknown = int(data.get("checks_unknown") or 0)
    total = data.get("checks_total")
    # "8.0/10 over 5 checks" doesn't say whether that's 5 of 5 or 5 of 12 —
    # exactly the ambiguity this analysis's own docstring exists to avoid.
    # Only spell out the denominator when it differs; "5 of 5 checks" reads
    # as noise where "5 checks" already said everything.
    count_phrase = (f"{evaluated} of {int(total)} {_plural('check', int(total))}"
                     if total is not None and int(total) != evaluated
                     else f"{evaluated} {_plural('check', evaluated)}")
    return {
        "label": f"{score}/10 over {count_phrase}"
                 + (f", {unknown} not evaluable" if unknown else ""),
        "tone": "good" if score >= 7 else "warn" if score >= 4 else "bad",
    }


def _ci_quality_trend(registry, slug: str) -> list[dict]:
    # Pass-count per run — mirrors _security_features_trend's shape.
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "ci_quality"):
        bucket = by_run.setdefault(r["surveyed_at"], {"passing": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] == "pass":
            bucket["passing"] += 1
    return [
        {"surveyed_at": ts, "value": counts["passing"], "total_checks": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _maturity_results(registry, slug: str) -> dict:
    # Same uniform finding shape as _license_results — single
    # current-state classification, no trend (see maturity.py's docstring).
    rows = registry.query_findings(slug, "maturity")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _repo_conventions_results(registry, slug: str) -> dict:
    # `detail` added 2026-09-03 (Backlog item 3's sweep): `security_policy_
    # content`'s summary names only the file's basename, not its directory
    # (root vs .github/ vs docs/ — a real distinction, since e.g. GitHub only
    # recognises .github/SECURITY.md as the canonical location), and
    # truncates matched keywords to the first 2; `automated_build`/
    # `deployment_docker`'s summaries truncate their file lists to the
    # first 3. Every one of those is a genuine information loss, not
    # redundant scaffolding — the full data existed only in `detail`.
    rows = registry.query_findings(slug, "repo_conventions")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"],
         "confidence": r["confidence"], "detail": _as_detail(r.get("detail_json"))}
        for r in rows
    ]
    return {"findings": findings}


def _repo_conventions_trend(registry, slug: str) -> list[dict]:
    # Pass-count per run — mirrors _ci_quality_trend/_security_features_trend.
    # "present"/"pass" both count as a positive signal (catalog_info uses
    # "present"/"absent" rather than "pass"/"gap" — see
    # RepoConventionsParser._catalog_info's docstring for why).
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "repo_conventions"):
        bucket = by_run.setdefault(r["surveyed_at"], {"positive": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] in ("pass", "present"):
            bucket["positive"] += 1
    return [
        {"surveyed_at": ts, "value": counts["positive"], "total_checks": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _sub_resource_survey_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results/_documentation_results
    # use ("worthy"/"not_worthy" are this kind's own label vocabulary) —
    # plus path/kind/owners/dates parsed out of detail_json, since the
    # repo scope-narrowing funnel's selection UI (D3) needs those as real
    # sortable/filterable columns and needs `kind` to build a correct
    # catalog request, not just a display string.
    rows = registry.query_findings(slug, "repo_sub_resource_survey")
    findings = []
    for r in rows:
        detail = {}
        if r.get("detail_json"):
            try:
                detail = json.loads(r["detail_json"])
            except (TypeError, ValueError):
                detail = {}
        findings.append({
            "check_name": r["check_name"], "label": r["label"],
            "summary": r["summary"], "confidence": r["confidence"],
            "path": detail.get("path", ""), "kind": detail.get("kind", "file"),
            "owners": detail.get("owners", []),
            "last_updated_at": detail.get("last_updated_at", ""),
            "first_added_at": detail.get("first_added_at", ""),
        })
    metrics = registry.query_metrics(slug, "repo_sub_resource_survey")
    return {"findings": findings, "metrics": metrics}


def _sub_resource_survey_trend(registry, slug: str) -> list[dict]:
    # Growth over time (D11) — total_size_bytes is the headline trend
    # value; file_count is included per-point for context.
    size_history = {
        r["surveyed_at"]: r["metric_value"]
        for r in registry.query_metrics_history(slug, "repo_sub_resource_survey", "total_size_bytes")
    }
    count_history = {
        r["surveyed_at"]: r["metric_value"]
        for r in registry.query_metrics_history(slug, "repo_sub_resource_survey", "file_count")
    }
    return [
        {"surveyed_at": ts, "value": value, "file_count": count_history.get(ts)}
        for ts, value in sorted(size_history.items())
    ]


_DOC_QUALITY_RANK = {"Minimal": 1, "Partial": 2, "Comprehensive": 3}


def _documentation_trend(registry, slug: str) -> list[dict]:
    quality_rows = [
        r for r in registry.query_findings_history_raw(slug, "documentation")
        if r["check_name"] == "quality_score"
    ]
    return [
        {"surveyed_at": r["surveyed_at"], "value": _DOC_QUALITY_RANK.get(r["label"], 0), "label": r["label"]}
        for r in quality_rows
    ]


def _api_structure_results(registry, slug: str) -> dict:
    # Always-current live read (project_code_symbols/project_code_relationships
    # are repopulated at ingestion, not survey time) — no "latest results"
    # snapshot needed for this one, unlike the others above.
    with registry._conn() as conn:
        rows = conn.execute(
            "SELECT language, kind, COUNT(*) as c FROM project_code_symbols "
            "WHERE project_slug = ? GROUP BY language, kind",
            (slug,),
        ).fetchall()
    by_language: dict[str, dict[str, int]] = {}
    for r in rows:
        by_language.setdefault(r["language"], {})[r["kind"]] = r["c"]
    relationships = registry.get_code_relationships(slug)

    # Complexity, live from the same table (design doc D3).
    #
    # It was persisted into the api_structure METRIC and stopped there: the
    # fact layer answers questions through THIS reader, so "How complex?"
    # rendered `relationship_count: 437` — the one scalar that happened to be
    # here — while the complexity summary sat in a metric nobody on this path
    # reads. Verifying the metric is not verifying the answer.
    #
    # Same language guard as the surveyor: go and javascript store 0 for
    # every symbol because their extractors never compute it, so an average
    # spanning them is dragged toward zero (0.32 vs 2.69 on milvus).
    from resource_explorer.surveyors.sub_surveyors.api_structure import (
        _COMPLEXITY_CAPABLE_LANGUAGES)

    with registry._conn() as conn:
        crows = conn.execute(
            "SELECT language, COUNT(*) AS n, MAX(complexity) AS mx, "
            "AVG(complexity) AS av FROM project_code_symbols "
            "WHERE project_slug = ? AND kind IN ('function', 'method') "
            "GROUP BY language",
            (slug,),
        ).fetchall()
    complexity = {
        r["language"]: {
            "max": int(r["mx"] or 0),
            "avg": round(float(r["av"] or 0), 1),
            "measured_over": int(r["n"] or 0),
        }
        for r in crows
        if r["language"] in _COMPLEXITY_CAPABLE_LANGUAGES and (r["n"] or 0)
    }
    not_measured = sorted(
        {r["language"] for r in crows} - set(complexity)
    )

    symbol_count = sum(sum(k.values()) for k in by_language.values())
    return {
        "symbol_count": symbol_count,
        "by_language": by_language,
        "relationship_count": len(relationships),
        "complexity_by_language": complexity,
        "complexity_languages_not_measured": not_measured,
    }


def _api_structure_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "api_structure", "symbol_count")
    ]


def _symbol_extraction_results(registry, slug: str) -> dict:
    # D5's own worked example — separate "symbol_extraction" metric kind
    # (SymbolExtractionSurveyor writes it) from ApiStructureSurveyor's
    # "api_structure" kind, so this step's independent run history stays
    # its own trend, not conflated with the reporting step it feeds.
    m = registry.query_metrics(slug, "symbol_extraction")
    return {
        "symbol_count": m.get("symbol_count", 0),
        "relationship_count": m.get("relationship_count", 0),
        "by_language": (m.get("detail") or {}).get("by_language", {}),
        "surveyed_at": m.get("surveyed_at", ""),
    }


def _symbol_extraction_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "symbol_extraction", "symbol_count")
    ]


def _manifest_parse_results(registry, slug: str) -> dict:
    """Combines the three sub-parse snapshots ManifestParseSurveyor records
    (its own "manifest_parse_*" metric kinds, not the tables it writes into
    directly) into one results shape — mirrors _symbol_extraction_results'
    own reasoning for keeping a step's run-history separate from the table(s)
    it feeds."""
    deps = registry.query_metrics(slug, "manifest_parse_dependencies")
    ci = registry.query_metrics(slug, "manifest_parse_ci_quality")
    conventions = registry.query_metrics(slug, "manifest_parse_conventions")

    # Three sub-parses, three independent answers — so three statuses, not one.
    # A single card-level status would have to pick a winner, and "dependencies
    # unverified, CI recovered, conventions recovered" (egeria_git, whose
    # build.gradle the parser cannot read) has no honest single summary.
    def _sub(metrics: dict, count_key: str) -> dict:
        out = {"count": int(metrics.get("count", 0) or 0)}
        detail = metrics.get("detail") or {}
        st = result_status_from_detail(detail)
        if st:
            out["status"] = st
        # `manifests`/`error` (2026-09-03, Backlog item 3's sweep): manifest_
        # parse.py nests its per-sub-parse detail under StepOutcome.as_row()'s
        # own "outcome_detail" key — result_status_from_detail only reads the
        # flat outcome/outcome_cause/outcome_known_positive fields alongside
        # it, never opens outcome_detail, so the manifest basenames a "no
        # dependencies parsed despite N manifest(s) present" summary already
        # names, and the raw exception text on a parse failure, were
        # persisted and unreachable through this reader.
        outcome_detail = detail.get("outcome_detail")
        if isinstance(outcome_detail, dict):
            if "manifests" in outcome_detail:
                out["manifests"] = outcome_detail["manifests"]
            if "error" in outcome_detail:
                out["error"] = outcome_detail["error"]
        return out

    return {
        "dependencies": _sub(deps, "dependency_count"),
        "ci_quality": _sub(ci, "ci_quality_count"),
        "conventions": _sub(conventions, "conventions_count"),
        # Flat keys kept: they are what the trend reader and any existing
        # consumer read, and removing them to tidy the shape would be a
        # breaking change for a cosmetic gain.
        "dependency_count": deps.get("count", 0),
        "dependency_outcome": (deps.get("detail") or {}).get("outcome", ""),
        "ci_quality_count": ci.get("count", 0),
        "ci_quality_outcome": (ci.get("detail") or {}).get("outcome", ""),
        "conventions_count": conventions.get("count", 0),
        "conventions_outcome": (conventions.get("detail") or {}).get("outcome", ""),
        "surveyed_at": deps.get("surveyed_at") or ci.get("surveyed_at")
                       or conventions.get("surveyed_at", ""),
    }


def _manifest_parse_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "manifest_parse_dependencies", "count")
    ]


def _rag_ingestion_results(registry, slug: str) -> dict:
    """Live-ish snapshot of what is in pgvector for this project, as recorded
    by the last repo_rag_ingestion run. Reads the persisted metric rather than
    counting the vector store again here: the results route runs per page load,
    and RagIngestionSurveyor already reads the store's live counts at survey
    time — the number a user wants is "what does my chat index contain as of
    the last time anything checked", not a per-request count query."""
    m = registry.query_metrics(slug, "rag_ingestion")
    if not m:
        # Same false zero the website_ingestion reader had: with nothing
        # persisted this returned total_chunks=0 and collections=0, which the
        # "metrics" mode renders as measured values — "your chat index is
        # empty", when the truth is that nothing has ever looked.
        return {"_status": {"state": result_status.NEVER_RUN,
                            "hint": "This analysis has not run for this repo yet."}}
    return {
        "total_chunks": m.get("total_chunks", 0),
        "collections": m.get("collections", 0),
        "by_collection": (m.get("detail") or {}).get("by_collection", {}),
        "surveyed_at": m.get("surveyed_at", ""),
    }


def _rag_ingestion_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "rag_ingestion", "total_chunks")
    ]


def _website_ingestion_results(registry, slug: str) -> dict:
    """What the last repo_website_ingestion run put into pgvector for this
    project's documentation site.

    `reason` is carried through deliberately: three of this step's outcomes are
    legitimate zeros — no homepage derived yet, the repo publishes its own site
    (so the source is already ingested in a better form), or discovery found
    nothing — and without the reason they render identically to a failure. The
    card reads the reason, not just the count.
    """
    m = registry.query_metrics(slug, "website_ingestion")
    if not m:
        # NEVER RUN is not the same as ran-and-found-nothing, and this reader
        # used to erase the difference: with no persisted run it still returned
        # chunks/pages_fetched/pages_found/pages_failed as 0, which the "metrics"
        # mode lays out as four rows of zeros — indistinguishable from a site
        # that was scanned and had nothing. Measured 2026-08-25: this step has
        # never run on ANY of the 60 repos, so every card in the corpus was
        # showing that false zero.
        #
        # Returning nothing lets _renderEmptyResultState say "No results yet —
        # click Run to scan", which result_status documents as exactly the
        # never_run message.
        return {"_status": {"state": result_status.NEVER_RUN,
                            "hint": "This analysis has not run for this repo yet."}}
    detail = m.get("detail") or {}
    out = {
        # int(): metric_value is a float column, and "0.0 chunk(s)" on a card
        # reads as a broken number rather than a count.
        "chunks": int(m.get("chunks", 0) or 0),
        "pages_fetched": int(m.get("pages_fetched", 0) or 0),
        "pages_found": detail.get("pages_found", 0),
        "pages_failed": detail.get("pages_failed", 0),
        "url": detail.get("url", ""),
        "collection": detail.get("collection", ""),
        "reason": detail.get("reason", ""),
        "discovery": detail.get("discovery", ""),
        # ingested_by/ingested_at (2026-09-03, Backlog item 3's sweep): the
        # already-ingested explanation text names who ingested it and when
        # ("...was ingested as {collection} by '{owner}' at {when}") — the
        # writer treats that as part of the answer, not incidental, and this
        # reader dropped both a second time even though the exact same field
        # (ingested_by) had already been the subject of one silent-drop fix
        # at the writer's own _note() allowlist (website_ingestion.py's
        # _DETAIL_FIELDS). error is the literal exception text on a
        # discovery failure — only the generic outcome_cause category
        # otherwise survives via attach_status below.
        "ingested_by": detail.get("ingested_by", ""),
        "ingested_at": detail.get("ingested_at", ""),
        "error": detail.get("error", ""),
        "surveyed_at": m.get("surveyed_at", ""),
    }
    # The "metrics" render mode lays every key out as a labelled row, so an
    # empty descriptive field shows as a label with nothing beside it — which
    # reads as a failed lookup rather than as "not applicable". The counts stay
    # even at zero: there, zero is the answer.
    return attach_status(
        {k: v for k, v in out.items()
         if v != "" or k in ("chunks", "pages_fetched", "pages_found", "pages_failed")},
        detail,
    )


def _website_ingestion_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "website_ingestion", "chunks")
    ]


def _deployment_name(path: str) -> str:
    """A readable name for the deployment an interface fact came from.

    The parent directory, not the filename: `compose-configs/egeria-quickstart/
    egeria-quickstart.yaml` is "egeria-quickstart", and a bare
    `docker-compose.yml` under `optional-associated-runtimes/milvus/` is
    "milvus" rather than a name shared with six other stacks.
    """
    parts = (path or "").replace("\\", "/").split("/")
    if len(parts) >= 2:
        return parts[-2]
    return parts[-1] if parts else "(unknown)"


def _architecture_interfaces_results(registry, slug: str) -> dict:
    """Ports and wires, grouped by the deployment that declared them.

    Grouped rather than flat because mixing deployments is meaningless:
    egeria-workspaces declares a quickstart topology AND a freshstart one AND
    a dozen optional runtimes, in 26 separate compose files. A single graph
    over all of them would draw a system nobody ever runs.

    Two things this shape is careful about, both from §5.5f:

      * A wire is a compose `depends_on` — **startup ordering, not traffic**.
        `oneWay` is always true and `frequency`/`dataExchanged` are
        deliberately empty rather than invented, so `integration_style` is
        carried through to be stated on the view. An arrow here means "A
        declares it depends on B" and nothing about data.
      * Coverage is partial by construction: these come only from Dockerfile
        EXPOSE, compose ports/expose/depends_on and OpenAPI documents.
        `artifact_count` is carried so the view can say so — absence of wires
        means no deployment artifact declared any, NOT that no dependencies
        exist. Prometheus yields one port and zero wires and must not read as
        "simple architecture".

    Protocol is left exactly as found, usually empty: the detector does not
    infer HTTP from port 8080, because convention dressed as evidence is how an
    unverifiable claim enters the catalog at the confidence of a measured one.
    Blank means "nothing said so", and the view must render it as blank rather
    than as a gap.
    """
    rows = registry.query_findings(slug, "architecture_interfaces")
    deployments: dict[str, dict] = {}
    for r in rows:
        d = _as_detail(r.get("detail_json"))
        path = (d.get("evidence") or {}).get("path", "")
        name = _deployment_name(path)
        dep = deployments.setdefault(name, {"name": name, "artifacts": set(),
                                            "components": {}, "wires": []})
        dep["artifacts"].add(path)
        if d.get("kind") == "port":
            comp = d.get("component", "")
            dep["components"].setdefault(comp, {"name": comp, "ports": []})
            # operation_count (2026-09-03, Backlog item 3's sweep):
            # persist.py's own neighboring comment names this exact class of
            # bug ("exactly what happened to operationCount between finding
            # 100 and this line") — it recurred one layer up. Computed per
            # port, actively used elsewhere (arch_summary.py's "N
            # operation(s)" line, mermaid.py's diagram annotations), but
            # never surfaced here, so this Interfaces card could show a port
            # with no indication of its declared operation count even
            # though the same number appears elsewhere in the UI.
            dep["components"][comp]["ports"].append({
                "port": d.get("port", ""), "direction": d.get("direction", ""),
                "protocol": d.get("protocol", ""), "summary": r.get("summary", ""),
                "path": path, "line": (d.get("evidence") or {}).get("line"),
                "operation_count": (d.get("additionalProperties") or {}).get("operationCount"),
            })
        elif d.get("kind") == "wire":
            src, tgt = d.get("source", ""), d.get("target", "")
            for c in (src, tgt):
                if c:
                    dep["components"].setdefault(c, {"name": c, "ports": []})
            dep["wires"].append({
                "source": src, "target": tgt,
                "integration_style": d.get("integrationStyle", ""),
                "protocol": d.get("protocol", ""),
                "path": path, "line": (d.get("evidence") or {}).get("line"),
            })
    out = []
    for dep in deployments.values():
        out.append({
            "name": dep["name"],
            "artifact_count": len(dep["artifacts"]),
            "components": sorted(dep["components"].values(), key=lambda c: c["name"]),
            "wires": dep["wires"],
        })
    out.sort(key=lambda d: (-(len(d["components"]) + len(d["wires"])), d["name"]))
    return {"deployments": out}


def _architecture_summary_results(registry, slug: str) -> dict:
    """The architecture summary, read back.

    The step persisted nothing until 2026-08-25 — it computed a summary,
    returned it as an annotation and wrote no row, so there was nothing for a
    results view to read and every run recomputed from scratch. Found by the
    end-to-end audit rather than by the step failing, because it never failed.
    """
    rows = registry.query_findings(slug, "architecture_summary") or []
    if not rows:
        return {"state": result_status.NEVER_RUN,
                "message": "No architecture summary yet — run the analysis."}
    row = rows[-1]
    detail = row.get("detail_json") or row.get("detail") or {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except Exception:  # noqa: BLE001
            detail = {}
    return {"summary": row.get("summary", ""), "depth": row.get("label", ""),
            "surveyed_at": row.get("surveyed_at", ""), **detail}


def _architecture_doc_lens_results(registry, slug: str) -> dict:
    """Which components the project's own documentation names, and from where.

    `evidence_kind` is carried per component and MUST NOT be flattened by a
    renderer — and this docstring asserted that before the persistence provided
    it, which is how a promise in prose outran the data. 212 rows carried none.
    `tests/test_persisted_detail_contracts.py` now asserts it against real rows
    rather than against this sentence: emphasis in a source document is a stronger claim than a mention
    in an ingested site's text, and a reader who cannot tell them apart will
    over-trust the weaker one. Group or mark them structurally rather than
    styling them, which the presentation session's own argument settles — a
    style difference assumes the reader is looking for one.
    """
    # `query_findings` returns the latest row PER SCOPE, and a lens run is a
    # whole-resource event — so a scope that was documented in an earlier run
    # and is not documented now keeps its old row forever, and reads as current.
    # Measured 2026-08-25: three such rows survived a full corpus refresh, on
    # `docling_eval` and `docling_java`, because those scopes stopped matching
    # and nothing removes a finding that is no longer produced.
    #
    # So take the newest timestamp across the whole kind and report only rows
    # from that run. The stale rows stay in the table — this is a read-side
    # correction, not a deletion — but they stop being presented as the current
    # answer, which is the part that misleads.
    # The run marker is the authority on what "current" means: a run that
    # documents nothing writes only this, so without it the newest rows are
    # whatever the last successful run left behind.
    latest = ""
    for row in registry.query_findings(slug, "architecture_doc_lens") or []:
        if (row.get("check_name") or "") == "lens_run":
            latest = max(latest, str(row.get("surveyed_at") or ""))

    rows_by_scope = {}
    for scope in registry.query_finding_scopes(slug, "architecture_doc_lens") or []:
        rows = [f for f in (registry.query_findings(slug, "architecture_doc_lens", scope) or [])
                if (f.get("check_name") or "") == "documented_by"]
        if not rows:
            continue
        rows_by_scope[scope] = rows
        if not latest:                     # no marker yet (rows predate it)
            latest = max(latest, max(str(f.get("surveyed_at") or "") for f in rows))

    findings = []
    for scope, rows in rows_by_scope.items():
        for f in rows:
            if str(f.get("surveyed_at") or "") != latest:
                continue
            detail = f.get("detail_json") or f.get("detail") or {}
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except Exception:  # noqa: BLE001
                    detail = {}
            findings.append({
                "component": scope, "label": f.get("label", ""),
                "summary": f.get("summary", ""),
                "term": detail.get("term", ""), "evidence": detail.get("evidence", ""),
                "date": detail.get("date", ""),
                "evidence_kind": detail.get("evidence_kind", ""),
            })
    if not findings:
        # The run marker is what separates these. "Nobody has run the lens here"
        # and "the lens ran and the documentation named nothing we recovered"
        # are different facts about the repository, and the second is a real
        # answer — the same distinction `never_run` vs `nothing_found` exists to
        # make, which this reader collapsed until the marker existed to tell
        # them apart.
        if latest:
            return {"state": result_status.NOTHING_FOUND,
                    "message": "The architecture documentation was consulted and named "
                               "none of the components recovered here. That is an answer "
                               "about this project's documentation, not a missing run."}
        return {"state": result_status.NEVER_RUN,
                "message": "The architecture document has not been consulted for this "
                           "resource yet."}
    return {"findings": findings, "count": len(findings)}


def _architecture_summary_headline(registry, slug: str) -> dict | None:
    r = _architecture_summary_results(registry, slug)
    if r.get("state"):
        return None                      # never run — the card's own empty state
    n, doc = r.get("components", 0), r.get("documented", 0)
    if not r.get("complete", True):
        # A summary that lost half its input still reads as a confident answer,
        # which is why partial-ness has to survive into the one line every
        # caller sees.
        return {"label": f"Summary incomplete — {n} {_plural('candidate', n)}, some unread",
                "status": "warn"}
    return {"label": (f"{doc} documented of {n} candidate {_plural('component', n)}" if doc
                      else f"{n} candidate {_plural('component', n)}, none documented"),
            "status": "info" if doc else "warn"}


def _architecture_doc_lens_headline(registry, slug: str) -> dict | None:
    r = _architecture_doc_lens_results(registry, slug)
    if r.get("state"):
        return None
    n = r.get("count", 0)
    return {"label": f"{n} {_plural('component', n)} named by the project's own documentation",
            "status": "info"}


def _doc_ingestion_state(registry, slug: str) -> dict:
    """`{state, detail}` for this repo's documentation site, for rendering.

    Isolated so a failure to read it cannot take out the architecture card it
    decorates — an unreadable ingestion status is a missing offer, not a missing
    result.
    """
    try:
        from resource_explorer.surveyors.sub_surveyors.arch_lens import ingestion_status

        from resource_explorer.surveyors.sub_surveyors.arch_lens import ING_UNKNOWN

        state, detail = ingestion_status(registry, slug)
        # `unknown` is now a state of its own (2026-08-25). Until it was, this
        # told "nobody has read the site" from "we could not tell" by matching
        # ingestion_status's DETAIL STRING — this module depending on another's
        # wording, with nothing to notice a reword. It is exactly what happened:
        # the detail gained an exception suffix and the exact match stopped
        # firing. The state is the contract; the prose beside it is not.
        if state == ING_UNKNOWN:
            return {"state": "", "detail": ""}
        return {"state": state, "detail": detail}
    except Exception:  # noqa: BLE001
        # No logging call here on purpose: this module defines no logger, and an
        # earlier version referenced one — so the handler raised NameError and
        # the guard against a failure taking out the card became the thing that
        # took out the card. An error handler that can itself error is not a
        # guard. The empty state is the signal; the renderer shows nothing.
        return {"state": "", "detail": ""}


def _verdict_view(row: dict | None) -> dict | None:
    """The subset of an architecture_component_verdicts row a component card
    needs — None when no curator has ruled on this component yet, so a
    reader can tell "no verdict" from "verdict happens to be falsy" without
    inspecting field values."""
    if not row:
        return None
    return {
        "verdict": row["verdict"],
        "retyped_to": row.get("retyped_to", ""),
        "note": row.get("note", ""),
        "decided_at": row.get("created_at", ""),
    }


def _materialized_view(row: dict | None) -> dict | None:
    """The subset of an architecture_materialized_components row a component
    card needs — None when nothing has been materialized yet. Kept as its
    own function alongside _verdict_view rather than folded in: a component
    can carry a verdict with no materialization (e.g. 'rejected', or an
    'accepted' whose materialize call failed — see curate.py's
    _materialize_if_accepted) and the UI needs to tell those apart on a
    page reload, not just in the transient POST response."""
    if not row:
        return None
    return {"guid": row["guid"], "qualified_name": row["qualified_name"],
            "materialized_at": row.get("materialized_at", "")}


def _architecture_recovery_results(
    registry, slug: str, max_depth: int | None = arch_projection.DEFAULT_PROJECTION_DEPTH,
) -> dict:
    """Phase 1 plan §4.4 — the results view. Reads back what
    repo_arch_detect/repo_arch_coupling wrote into the generic findings/
    metrics tables (kind="architecture_recovery") and reassembles it into
    one component list, each with its evidence and **which approach
    proposed it** (manifest / deployment / code marker / coupling, and for
    coupling its shape) — this is the "portfolio legible" requirement, and
    it falls out of grouping by scope_locator rather than needing an
    explicit cross-step merge (see persist.py's module docstring).

    Uses query_finding_scopes/query_findings_all_runs (registry.py) rather
    than the single-scope query_findings, because repo_arch_detect and
    repo_arch_coupling are independent steps that may run at different
    times — a component both propose needs evidence from both runs, not
    just whichever ran most recently.

    **Projected to `max_depth` by default** (approach-portfolio-model.md
    §2a / projection.py) — the generator now stores the whole candidate
    hierarchy rather than choosing a level (item 2/3 of that redesign), and
    a UI rendering a few thousand raw candidates flat (the `egeria` case
    this exists for) is unusable. Nothing is discarded server-side: pass
    `max_depth=None` for the full, unprojected hierarchy (e.g. component-
    scoped analytics, design §6, which wants the fine-grained partition).
    """
    scopes = registry.query_finding_scopes(slug, "architecture_recovery", check_name="component")
    components = []
    slug_to_path: dict[str, str] = {}
    # A curator's accept/reject/retype call (docs/Backlog.md "take
    # architecture results into Curate") — kept in its own table, not folded
    # into this kind's findings, per that entry's own constraint: "a
    # curator's verdict is evidence of a different kind, not a rewrite of
    # what the detectors said." One query for the whole resource, same
    # reasoning as everything else here that avoids a per-scope round trip.
    verdicts = registry.get_component_verdicts("repo", slug)
    materialized = registry.get_materialized_components("repo", slug)
    for scope in scopes:
        rows = registry.query_findings_all_runs(slug, "architecture_recovery", scope)
        comp_rows = [r for r in rows if r["check_name"] == "component"]
        evidence_rows = [r for r in rows if r["check_name"] != "component"]
        if not comp_rows:
            continue
        # Latest "component" row per run wins for name/type/confidence —
        # earlier runs at the same scope_locator are superseded facts about
        # the SAME component, unlike evidence, which accumulates.
        latest = max(comp_rows, key=lambda r: r["surveyed_at"])
        detail = _json_or_empty(latest.get("detail_json"))
        # A WITHDRAWAL is not an approach. Its rows are `check_name !=
        # "component"`, so they land in `evidence_rows` and their label
        # ("withdrawn") was being rendered as though a detector by that name had
        # proposed the component: measured in the browser, egeria's withdrawn
        # rows showed `spring, withdrawn` on their provenance line.
        approaches = sorted({r["label"] for r in evidence_rows
                             if r["label"] and r["label"] != WITHDRAWN_LABEL})
        metrics = registry.query_metrics(slug, "architecture_recovery", scope)
        if detail.get("slug"):
            slug_to_path[detail["slug"]] = scope
        components.append({
            "path": scope,
            "name": detail.get("name", scope),
            "type": detail.get("type"),
            "confidence": latest.get("confidence", 0),
            "perspective": detail.get("perspective", "physical"),
            "outcome": detail.get("outcome", ""),
            "run_scope": detail.get("run_scope", ""),
            "proposed_by": approaches or (detail.get("proposed_by") or []),
            "surveyed_at": latest.get("surveyed_at", ""),
            # Granularity is not precision (§2a) — depth/parent are the
            # stored hierarchy, kept even after projection collapses which
            # rows get SHOWN (below), so nothing computed is lost, only
            # summarised. `parent_slug` is detector-namespaced (§8.2's
            # `code::`/`coupling::` prefixes), so it only resolves to a
            # `parent_path` when that ancestor was ALSO persisted this run;
            # otherwise it stays "" and this node is its branch's coarsest
            # available reading, same as a root-attached node.
            "depth": detail.get("depth", 0),
            "parent_slug": detail.get("parent_slug", ""),
            # identity/blueprint (2026-09-03, Backlog item 3's sweep), both
            # persisted by persist.py and never read back anywhere before
            # this fix (confirmed by grep):
            #  - identity: which rung of §8.2's precedence chain identified
            #    this component (deployment-unit/package-name/module-path) —
            #    ir.py's own docstring calls this "materially" different
            #    from the numeric confidence, a claim-strength qualifier
            #    with nowhere to surface.
            #  - blueprint: which candidate cluster this component was
            #    assigned to. persist.py deliberately runs clustering BEFORE
            #    writing component rows specifically so this could be
            #    attached — and it's the only surviving path to blueprint
            #    membership here, since the sibling "architecture_blueprints"
            #    finding kind (the full cluster definitions) has no reader
            #    anywhere in this file.
            "identity": detail.get("identity"),
            "blueprint": detail.get("blueprint"),
            "verdict": _verdict_view(verdicts.get(scope)),
            "materialized": _materialized_view(materialized.get(scope)),
            "evidence": [
                {
                    "assertion": r["check_name"], "approach": r["label"],
                    "summary": r["summary"], "confidence": r["confidence"],
                    "surveyed_at": r["surveyed_at"],
                }
                for r in evidence_rows
            ],
            "metrics": {k: v for k, v in metrics.items() if k not in ("surveyed_at", "detail")},
        })
    # Structural nodes (persist.py) — ancestors referenced by a component's
    # parent_slug that were never emitted as components. They exist so
    # parent_path resolves and projection has a tree to collapse; without them
    # every node reads as root-attached and project_rows is an identity
    # function (measured 2026-08-24: milvus 204 components at every depth).
    #
    # They carry no type and no confidence by design — they have no evidence of
    # their own — so they are marked `structural` and a consumer can render
    # them as grouping rather than as a recovered component.
    for scope in registry.query_finding_scopes(
            slug, "architecture_recovery", check_name="structural_node"):
        rows = [r for r in registry.query_findings_all_runs(slug, "architecture_recovery", scope)
                if r["check_name"] == "structural_node"]
        if not rows:
            continue
        latest = max(rows, key=lambda r: r["surveyed_at"])
        detail = latest.get("detail_json") or {}
        if isinstance(detail, str):
            import json as _json
            detail = _json.loads(detail or "{}")
        node_slug = detail.get("slug", "")
        if not node_slug or node_slug in slug_to_path:
            continue
        node_path = detail.get("path", scope)
        slug_to_path[node_slug] = node_path
        components.append({
            "name": detail.get("name", node_path), "path": node_path,
            "slug": node_slug, "type": "", "confidence": 0,
            "structural": True,
            "perspective": "", "proposed_by": [], "run_scope": detail.get("run_scope", ""),
            "outcome": "", "evidence": [], "metrics": {},
            "depth": detail.get("depth", 0),
            "parent_slug": detail.get("parent_slug", ""),
            "surveyed_at": latest.get("surveyed_at", ""),
        })

    for c in components:
        c["parent_path"] = slug_to_path.get(c["parent_slug"], "")
    components.sort(key=lambda c: c["path"])
    # `scoped`/`partial`/`surveyed_at` below must see every persisted
    # component, not just the ones a coarse projection chooses to SHOW — a
    # projected-away node's own run_scope/outcome would otherwise silently
    # stop being able to mark the whole result partial/scoped.
    all_components = components
    displayed = (arch_projection.project_rows(components, max_depth)
                if max_depth is not None else components)

    # Per-run outcome, read from the run-summary metric row persist_ir
    # writes unconditionally (scope_locator="", metric_name=
    # "{detect,coupling}_component_count") — the ONE row a component-less
    # run still produces, since every other row above is written per
    # component and a zero-component run has none of those (README finding
    # 57; see persist.py's run-summary comment for why this is where it
    # lives). Read per run_label rather than via query_metrics(scope_locator
    # ="") because repo_arch_detect/repo_arch_coupling are independent
    # StepInfo entries that are not guaranteed to share one surveyed_at —
    # the same reason _architecture_recovery_trend below reads them apart.
    run_outcomes: dict[str, dict] = {}
    for run_label in ("detect", "coupling"):
        history = registry.query_metrics_history_raw(
            slug, "architecture_recovery", f"{run_label}_component_count", scope_locator="",
        )
        if not history:
            continue
        latest = history[-1]  # ASC-ordered; last is most recent
        detail = _json_or_empty(latest.get("detail_json"))
        run_outcomes[run_label] = {
            "component_count": int(latest.get("metric_value", 0) or 0),
            "outcome": detail.get("outcome", ""),
            "outcome_cause": detail.get("outcome_cause", ""),
            "outcome_detail": detail.get("outcome_detail", {}),
            "run_scope": detail.get("run_scope", ""),
            "surveyed_at": latest.get("surveyed_at", ""),
        }

    # Surface the outcome at the top level, not only per component.
    #
    # design §4.1c added run_scope/outcome to every persisted row precisely so a
    # SCOPED run — whose component set is incomplete by construction — could not
    # be mistaken for a complete one. That guard wrote the data and stopped:
    # this reader pulled name/type/confidence/perspective/proposed_by and never
    # looked at it, so the signal died one layer below where the design doc
    # checked, and a scoped run still presented as complete to the caller.
    #
    # Writing a field nobody reads is the same failure as not writing it. The
    # top-level flag is what a caller can act on without inspecting every
    # component.
    #
    # run_outcomes covers what the per-component loop above cannot: a run
    # that persisted zero "component" finding rows still ran, and — since
    # README finding 57 — still records why via its run-summary row. `scoped`/
    # `partial` stay sourced from components (a component's own run_scope is
    # more specific than the run-summary's, which is only ever the CURRENT
    # scope_locator this surveyor instance was given), but `unverified` can
    # only ever be seen here, because an unverified run is definitionally one
    # that produced no components to carry it.
    scoped = sorted({c["run_scope"] for c in all_components if c.get("run_scope")}
                     | {o["run_scope"] for o in run_outcomes.values() if o.get("run_scope")})
    partial = (any(c.get("outcome") == PARTIAL for c in all_components)
               or any(o.get("outcome") == PARTIAL for o in run_outcomes.values()))
    unverified = sorted(
        run_label for run_label, o in run_outcomes.items() if o.get("outcome") == UNVERIFIED
    )
    surveyed_at = max(
        [c["surveyed_at"] for c in all_components] + [o["surveyed_at"] for o in run_outcomes.values()],
        default="",
    )
    return {
        # Carried so the renderer can call the curator-verdict endpoints
        # (/api/curate/component-verdicts/repo/{slug}) without a second
        # parameter threaded through _renderCustomAnalysisResults' generic
        # `(data) => html` registry contract — every other entry there stays
        # untouched.
        "slug": slug,
        "components": displayed,
        # Ports and wires live under the same analysis because they are the same
        # recovery run's output, but in their own key rather than folded into
        # `components`: they are grouped BY DEPLOYMENT, and a component means
        # something different in each (egeria-workspaces declares 18 separate
        # topologies). Flattening them into the component list would merge
        # stacks nobody runs together.
        "interfaces": _architecture_interfaces_results(registry, slug)["deployments"],
        "component_count": len(displayed),
        # The full, unprojected count — so a caller/UI can say "13 shown
        # (of 42 total)" rather than a projected view silently looking like
        # the whole answer (§2a: coarsening a view must never look like
        # discarding the data behind it).
        # Structural nodes are grouping, not recoveries — counting them here
        # would inflate "N recovered" with rows that carry no evidence.
        # The documentation-site ingestion state, carried on THIS card because
        # this is where the absence is: a repo whose only architecture sources
        # are unreadable sites has nothing to show here, and a concrete,
        # answerable offer belongs in that space rather than a blank.
        #
        # Four states, not a flag (sub_surveyors/arch_lens.py) — `declined` is
        # why: the ingestion step refuses ON PURPOSE for a self-published site,
        # since the repo builds it and its source is already ingested in better
        # form. Offering there would re-open a decision the system made
        # correctly.
        "documentation": _doc_ingestion_state(registry, slug),
        # Phase C (blueprint-materialization-plan.md) — candidate blueprints
        # proposed by clustering.py, each with its own accept/reject verdict
        # and materialization state. Read once here so the frontend's Curate
        # tab doesn't need a second route; Analysis's read-only rendering of
        # this same payload simply doesn't render this key.
        "blueprints": _candidate_blueprints_results(registry, slug),
        "raw_component_count": sum(1 for c in all_components if not c.get("structural")),
        "structural_node_count": sum(1 for c in all_components if c.get("structural")),
        "run_outcomes": run_outcomes,
        "partial": partial,
        "unverified": unverified,
        "scoped_to": scoped,
        "unverified_note": (
            f"{', '.join(unverified)} could not verify this repo — "
            f"{'; '.join(o['outcome_cause'] for rl, o in run_outcomes.items() if rl in unverified)}"
            if unverified else ""
        ),
        "completeness_note": (
            f"Partial result — this analysis was scoped to {', '.join(scoped)}, so components "
            f"outside that scope were never looked for."
            if partial and scoped else ""
        ),
        "surveyed_at": surveyed_at,
    }


def _json_or_empty(raw) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _candidate_blueprints_results(registry, slug: str) -> list[dict]:
    """The `data.blueprints` key for `_architecture_recovery_results` —
    Phase C's frontend-facing read of clustering.py's proposals (Backlog.md
    item 1 / blueprint-materialization-plan.md), so Curate can offer an
    accept/reject control on a candidate blueprint the same way component
    verdicts already work.

    Deliberately its own reader rather than folded into the component loop
    above: candidate_blueprint findings share scope_locator="" (persist.py's
    `_persist_blueprints`) and are disambiguated by (perspective, label)
    within that one scope, not by scope_locator the way components are — a
    genuinely different join key, so merging the two loops would mean
    threading a second identity scheme through code that already has one.

    One row per (perspective, cluster_name), latest survey wins — same
    "latest row for this identity" rule every other reader here uses.
    Verdict/materialized state merged on via curate.py's own key shape
    (`f"{perspective}::{cluster_name}"`) so the frontend never has to
    recompute that join.
    """
    from resource_explorer.surveyors.arch_recovery.persist import BLUEPRINT_KIND

    rows = [r for r in registry.query_findings(slug, BLUEPRINT_KIND, "")
            if r["check_name"] == "candidate_blueprint"]
    by_key: dict[tuple[str, str], dict] = {}
    for r in rows:
        detail = _json_or_empty(r.get("detail_json"))
        perspective = detail.get("perspective", "")
        name = detail.get("name", "")
        if not perspective or not name:
            continue
        key = (perspective, name)
        existing = by_key.get(key)
        if existing is None or r["surveyed_at"] >= existing["row"]["surveyed_at"]:
            by_key[key] = {"row": r, "detail": detail}

    verdicts = registry.get_component_verdicts("repo", slug)
    materialized = registry.get_materialized_blueprints("repo", slug)

    blueprints = []
    for (perspective, name), entry in sorted(by_key.items()):
        r, detail = entry["row"], entry["detail"]
        vkey = f"{perspective}::{name}"
        blueprints.append({
            "perspective": perspective,
            "cluster_name": name,
            "summary": r.get("summary", ""),
            "signal": detail.get("signal"),
            "carrier": detail.get("carrier"),
            "composed_into": detail.get("composed_into"),
            "size": detail.get("size", 0),
            "members": detail.get("members") or [],
            "children": detail.get("children") or [],
            "parent": detail.get("parent", ""),
            "oversized": bool(detail.get("oversized")),
            "target_size": detail.get("target_size"),
            "run_scope": detail.get("run_scope", ""),
            "surveyed_at": r.get("surveyed_at", ""),
            "verdict": _verdict_view(verdicts.get(vkey)),
            "materialized": _materialized_view(materialized.get(vkey)),
        })
    return blueprints



def _architecture_recovery_trend(registry, slug: str) -> list[dict]:
    # Two independent counters (detect/coupling never share a metric_name —
    # see persist.py's run-summary comment) merged by surveyed_at into one
    # "total proposed this run" trend point.
    by_run: dict[str, float] = {}
    for name in ("detect_component_count", "coupling_component_count"):
        for r in registry.query_metrics_history(slug, "architecture_recovery", name):
            by_run[r["surveyed_at"]] = by_run.get(r["surveyed_at"], 0) + r["metric_value"]
    return [{"surveyed_at": ts, "value": v} for ts, v in sorted(by_run.items())]


def _architecture_recovery_headline(registry, slug: str) -> dict | None:
    result = _architecture_recovery_results(registry, slug)
    if not result.get("surveyed_at"):
        return None
    if result.get("unverified"):
        # An unverified run and a genuine zero look identical as a bare
        # count (README finding 57) — the headline is the one place every
        # caller sees, so this is where that distinction has to survive or
        # it is lost the same way it was before this outcome was wired up.
        return {"label": f"Unverified — {', '.join(result['unverified'])} could not read this repo",
                "status": "warn"}
    n = result["component_count"]
    return {"label": f"{n} {_plural('component', n)} recovered", "status": "info" if n else "warn"}


def _website_ingestion_headline(registry, slug: str) -> dict | None:
    """Survey Results dashboard headline. A skip is reported as its own status
    rather than as zero-with-a-warning — "this repo publishes its own site" is a
    correct, final answer, and flagging it as a shortfall would push someone to
    "fix" a duplicate ingest we deliberately avoid.

    Signature is `(registry, slug)` like every other headline reader. It took
    `(results)` until 2026-08-25, so the uniform call site
    (`web/routes/projects.py`) raised TypeError on every invocation — 0 of 60
    repos — and the caller's bare `except Exception: headline = None` swallowed
    it. The tile never rendered for anyone and nothing was logged.
    """
    results = _website_ingestion_results(registry, slug)
    if not results.get("surveyed_at"):
        return None
    reason = results.get("reason", "")
    if reason == "self_published":
        return {"label": "Site ingested as repo source", "status": "ok"}
    if reason == "code_host":
        return {"label": "No docs site (homepage is the repo)", "status": "unknown"}
    if reason in ("no_homepage", "no_collection_type"):
        return {"label": "No site to ingest", "status": "unknown"}
    chunks = results.get("chunks", 0)
    if not chunks:
        # An unreachable host and a reachable-but-empty site are both zero, and
        # they call for opposite responses — fix the recorded URL, or look at
        # why extraction found nothing. Measured: docs.unitycatalog.com no
        # longer resolves, while sqlglot.com was reachable and yielded nothing
        # until meta-refresh handling landed.
        if results.get("pages_failed") and not results.get("pages_fetched"):
            return {"label": "Documentation site unreachable", "status": "warn"}
        return {"label": "Nothing ingested from site", "status": "warn"}
    return {"label": f"{chunks} {_plural('chunk', chunks)} from {results.get('pages_fetched', 0)} {_plural('page', results.get('pages_fetched', 0))}",
            "status": "ok"}


#: Finding labels whose polarity _generic_findings_headline can rely on.
#: Anything outside both sets leaves polarity unknown, and the headline then
#: reports a count rather than a verdict — see that function for what
#: guessing cost.
_NEGATIVE_LABELS = frozenset({"gap", "absent", "fail", "missing", "no"})
_POSITIVE_LABELS = frozenset({"pass", "present", "ok", "yes", "found"})


def _plural(noun: str, n: int) -> str:
    """"1 check", "3 checks" — not "3 check(s)".

    The parenthetical plural read as machine output in every headline that
    used it, which undercut the one line meant to read like an answer.
    """
    if n == 1:
        return noun
    return noun + ("es" if noun.endswith(("s", "x", "ch", "sh")) else "s")


def _generic_findings_headline(results: dict, *, noun: str = "check") -> dict | None:
    """Survey Results dashboard, Tier 1 (docs/survey-results-dashboard-plan.md
    D5) — generic headline compression for any findings_list-shaped results
    dict (the uniform {check_name, label, summary, confidence} shape most
    kinds already use). Not a new data source, just a summary of the same
    list already shown in full on the kind's own Analysis/Assessment card.
    Returns None when there's no data yet (survey never run for this repo)."""
    findings = results.get("findings")
    if not findings:
        return None

    negatives = [f for f in findings if f.get("label") in _NEGATIVE_LABELS]
    positives = [f for f in findings if f.get("label") in _POSITIVE_LABELS]
    n = len(findings)

    if negatives:
        if len(negatives) < n:
            return {"label": f"{len(negatives)} of {n} {_plural(noun, n)} need attention",
                    "status": "warn"}
        return {"label": f"all {n} {_plural(noun, n)} need attention", "status": "gap"}

    if positives and len(positives) == n:
        return {"label": f"all {n} {_plural(noun, n)} pass", "status": "ok"}

    # Neither vocabulary matched, so polarity is UNKNOWN — state the count and
    # nothing more.
    #
    # This branch used to say "N {noun}(s) passing" for anything it did not
    # recognise as a negative, which produced "7 secret match(s) passing" for
    # a repo with seven committed-secret matches. secret_scan labels its
    # findings by RULE NAME (generic-api-key, jwt, hashicorp-tf-password), so
    # none matched the negative set and every one of them counted as a pass.
    # For that noun more is worse, and this helper cannot know that — so it
    # must not assert a verdict it has no basis for. Counting is honest;
    # "passing" was not.
    return {"label": f"{n} {_plural(noun, n)}", "status": "info"}


def _security_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(_security_results(registry, slug))


def _documentation_headline(registry, slug: str) -> dict | None:
    results = _documentation_results(registry, slug)
    findings = results.get("findings") or []
    # Lead with the two things a reader asked about — the overall label the
    # surveyor assigned, and how much of the API carries a docstring — rather
    # than a count of heterogeneous "signals", which told them nothing about
    # documentation at all.
    quality = next((f for f in findings if f.get("check_name") == "quality_score"), None)
    coverage = next((f for f in findings
                     if f.get("check_name") == "api_docstring_coverage"), None)
    if not quality and not coverage:
        return _generic_findings_headline(results, noun="doc signal")
    parts = []
    if quality:
        parts.append(f"{quality.get('label')} documentation artifacts")
    if coverage:
        parts.append(f"{coverage.get('label')} of the public API documented")
    return {"label": ", ".join(parts), "status": "info"}


# The four GAP analyses. `noun` is chosen so the headline reads honestly when the
# count is ZERO, which for these is the common and CORRECT case: "0 secret
# matches" is a real result, whereas a noun like "issue" would make an absence
# sound like a clean bill of health it is not entitled to give. The status the
# reader attaches — from each scan's `scan_summary` row — is what distinguishes
# "scanned and matched nothing" from "never scanned".
def _secret_scan_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(_secret_scan_results(registry, slug), noun="secret match")


def _telemetry_scan_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(_telemetry_scan_results(registry, slug), noun="telemetry signal")


def _contribution_provenance_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(
        _contribution_provenance_results(registry, slug), noun="provenance check")


def _sla_content_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(_sla_content_results(registry, slug), noun="support signal")


def _security_features_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(_security_features_results(registry, slug), noun="feature")


def _ci_quality_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(_ci_quality_results(registry, slug), noun="CI check")


def _repo_conventions_headline(registry, slug: str) -> dict | None:
    return _generic_findings_headline(_repo_conventions_results(registry, slug), noun="convention")


def _repo_classification_headline(registry, slug: str) -> dict | None:
    """The role and the gate decision — the two things a reader wants at a
    glance. Deliberately NOT a count of located-vs-missing artifacts: §5.5b
    forbids reducing this to a number, because a checklist becomes a maturity
    score and a score punishes deliberate choices."""
    findings = _repo_classification_results(registry, slug).get("findings") or []
    if not findings:
        return None
    by_check = {f.get("check_name"): f for f in findings}
    if "classification_error" in by_check:
        return {"label": by_check["classification_error"].get("summary", "Classification failed"),
                "status": "error"}
    role = by_check.get("repo_role")
    gate = by_check.get("architecture_recovery_gate")
    if not role:
        return None
    label = role.get("label", "unclassified")
    if gate:
        label = f"{label} · architecture recovery: {gate.get('label')}"
    return {"label": label, "status": "info"}


def _license_headline(registry, slug: str) -> dict | None:
    # Single current-state classification, not a pass/gap checklist — surface
    # its own summary text directly rather than forcing it through the
    # generic gap-counter (see _license_results' own docstring).
    findings = _license_results(registry, slug).get("findings") or []
    if not findings:
        return None
    f = findings[0]
    return {"label": f.get("summary") or f.get("check_name", "License classified"), "status": "info"}


def _maturity_headline(registry, slug: str) -> dict | None:
    findings = _maturity_results(registry, slug).get("findings") or []
    if not findings:
        return None
    f = findings[0]
    return {"label": f.get("summary") or f.get("check_name", "Maturity classified"), "status": "info"}


def _dependency_headline(registry, slug: str) -> dict | None:
    result = _dependency_results(registry, slug)
    if not result.get("total"):
        return None
    return {"label": f"{result['total']} dependenc{'y' if result['total'] == 1 else 'ies'}", "status": "info"}


def _data_profile_headline(registry, slug: str) -> dict | None:
    result = _data_profile_results(registry, slug)
    if not result.get("total"):
        return None
    n = int(result["total"])
    return {"label": f"{n:,} data {_plural('file', n)} profiled", "status": "info"}


def _health_results(registry, slug: str) -> dict:
    """Latest health scores. HealthSurveyor writes these as metrics under the
    "repository_health" kind; before it did, this analysis had no reader at all,
    so its Survey Results card could never populate however often the survey
    ran — the scores existed only as in-memory annotations on their way to
    Egeria."""
    m = registry.query_metrics(slug, "repository_health")
    detail = m.get("detail") or {}
    scores = {k: m.get(k) for k in ("overall", "activity", "community",
                                    "release_cadence", "freshness")
              if m.get(k) is not None}
    if not scores:
        return {"detail": {}, "surveyed_at": ""}
    # Scores go at the TOP LEVEL, not under a "metrics" key. The "metrics"
    # render mode (_renderMetricsResults in index.html) iterates the payload's
    # own entries, filtering out only `detail`/`surveyed_at`/`_status` — so a
    # nested envelope renders as a single row literally named "metrics" whose
    # value is an object. The other two metrics-mode readers
    # (_rag_ingestion_results, _website_ingestion_results) already return flat.
    return {**scores, "detail": detail, "surveyed_at": m.get("surveyed_at", "")}


def _health_trend(registry, slug: str) -> list[dict]:
    """Overall score over time — the one number worth a line chart; the four
    component scores are visible on the card itself."""
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "repository_health", "overall")
    ]


def _health_headline(registry, slug: str) -> dict | None:
    result = _health_results(registry, slug)
    overall = result.get("overall")
    if overall is None:
        return None
    # Bands match how the scores are built (0-100, four equally weighted
    # components) rather than being tuned separately here.
    status = "ok" if overall >= 70 else "warn" if overall >= 40 else "gap"
    return {"label": f"Health {overall:.0f}/100", "status": status}


def _api_structure_headline(registry, slug: str) -> dict | None:
    result = _api_structure_results(registry, slug)
    symbol_count = sum(sum(kinds.values()) for kinds in result.get("by_language", {}).values())
    if not symbol_count:
        return None
    return {"label": f"{symbol_count:,} {_plural('symbol', symbol_count)} across "
            f"{len(result.get('by_language', {}))} {_plural('language', len(result.get('by_language', {})))}", "status": "info"}


def _symbol_extraction_headline(registry, slug: str) -> dict | None:
    result = _symbol_extraction_results(registry, slug)
    if not result.get("symbol_count"):
        return None
    n = int(result["symbol_count"])
    return {"label": f"{n:,} {_plural('symbol', n)} extracted from the code",
            "status": "info"}


def _manifest_parse_headline(registry, slug: str) -> dict | None:
    result = _manifest_parse_results(registry, slug)
    if not result.get("surveyed_at"):
        return None
    deps = int(result["dependency_count"])
    ci = int(result["ci_quality_count"])
    conv = int(result["conventions_count"])
    # Named parts rather than one summed total across three unlike things:
    # "40 finding(s)/dependency(s) across 3 tables" told a reader neither what
    # was found nor of what.
    return {"label": f"{deps:,} {_plural('dependency', deps).replace('dependencys', 'dependencies')}, "
                     f"{ci} CI {_plural('check', ci)}, {conv} {_plural('convention', conv)}",
            "status": "info"}


def _rag_ingestion_headline(registry, slug: str) -> dict | None:
    result = _rag_ingestion_results(registry, slug)
    total = result.get("total_chunks") or 0
    if not total:
        # "gap", not None: unlike the other kinds, an empty result here is a
        # real finding — nothing is indexed, so Chat has nothing to answer from.
        return {"label": "Nothing indexed for chat", "status": "gap"}
    return {
        "label": f"{int(total):,} indexed {_plural('chunk', int(total))} across "
                 f"{int(result.get('collections') or 0)} "
                 f"{_plural('collection', int(result.get('collections') or 0))}",
        "status": "ok",
    }


def _file_classification_headline(registry, slug: str) -> dict | None:
    result = _file_classification_results(registry, slug)
    if not result.get("total_files"):
        return None
    total = result["total_files"]
    code = result.get("code_lines")
    if code:
        src = result.get("source_files", 0)
        return {"label": f"{code:,} lines of code across {src:,} source "
                         f"{_plural('file', src)}, {total:,} "
                         f"{_plural('file', total)} in total",
                "status": "info"}
    return {"label": f"{total:,} {_plural('file', total)} classified", "status": "info"}


def _sub_resource_survey_headline(registry, slug: str) -> dict | None:
    result = _sub_resource_survey_results(registry, slug)
    findings = result.get("findings") or []
    if not findings:
        return None
    worthy = sum(1 for f in findings if f.get("label") == "worthy")
    n = len(findings)
    return {"label": f"{worthy} of {n} {_plural('sub-resource', n)} worth cataloging",
            "status": "info"}


@dataclass
class AnalysisKindResults:
    results_reader: Callable    # (registry, slug) -> dict
    trend_reader: Callable | None
    # A small fixed render-mode tag the frontend switches on generically —
    # "findings_list" and "metrics" need zero new frontend code for a new
    # kind; "custom" is the escape hatch for shapes that don't fit either
    # (dependency-by-ecosystem, data-profile summary, API structure).
    render: str
    # Survey Results dashboard Tier 1 (D5) — compressed {label, status} stat
    # tile for a phase's "is it worth proceeding" summary row. Optional:
    # None for kinds with no results view at all (repository_health).
    headline_reader: Callable | None = None
    #: True when the results reader does NOT depend on a survey step having
    #: run — it reads a table populated elsewhere (ingestion) and is current
    #: by construction.
    #:
    #: Without this, FactLayer.fact() gates on "was this analysis among the
    #: recorded steps of a survey run", which for a live-read analysis asks
    #: the wrong question. Measured 2026-09-02: api_structure reported
    #: `not_established` ("cannot be determined") for egeria_python_git while
    #: its reader returned 8,654 symbols from project_code_symbols — data
    #: that was current, sitting in the table, and reported as unknowable.
    live_read: bool = False


@dataclass
class AnalysisKind:
    """One analysis_catalog.yaml entry — what a user actually sees, runs,
    and schedules. May span more than one STEP_REGISTRY step_key (e.g.
    language_file_classification bundles three)."""
    id: str
    step_keys: list[str]
    family: str = ""             # e.g. "security" — groups related kinds on
                                  # the generic findings/metrics tables' `kind`
                                  # column, so future security-family members
                                  # (secret scanning, CVE checks, SAST,
                                  # branch-protection audit) share one query
                                  # surface without a UNION across tables.
    results: AnalysisKindResults | None = None   # None for kinds with no results view (repository_health)


# "language_file_classification" is the one genuinely ambiguous entry — its
# catalog description ("file types, languages, and project structure") and
# annotation_types span what three separate sub-surveyors emit, so all three
# are bundled here rather than guessing at just one. repo_file_size has no
# catalog entry at all (never independently schedulable/runnable today) so
# it isn't listed — it stays bundled only in a full, steps=None survey.
# egeria_publish is intentionally absent — it's an explicit write action,
# not a survey step; both scheduler.py and the analysis-run route special-
# case entries with action=="publish" before ever consulting this registry.
ANALYSIS_KINDS: dict[str, AnalysisKind] = {
    # Gained a results view when Scouting's "Profile" tab was built — that
    # tab's "Refresh profile" auto-chains this survey against the freshly
    # refreshed file inventory and displays project_file_type_counts, closing
    # the gap where classification data was refreshed but never shown
    # anywhere. repository_health (below) still has no results view; it's
    # covered by the Scouting overview's own stat cards instead.
    "language_file_classification": AnalysisKind(
        "language_file_classification",
        ["repo_language", "repo_file_classification", "repo_file_structure"],
        results=AnalysisKindResults(
            _file_classification_results, _file_classification_trend, "custom",
            headline_reader=_file_classification_headline,
        ),
    ),
    # The four GAP analyses. No `results=` yet: each is registered so it can be
    # RUN and scheduled, but none has a results view — that is a separate,
    # deliberate piece of work, and a half-built view would render an absence as
    # an answer, which is the failure this whole family of analyses exists to
    # avoid. `family="security"` groups the three that belong to it, per the
    # convention reserved for exactly this when the analysis-kind registry was
    # designed.
    #
    # The finding kinds they write are `<id>_findings` in every case — stated on
    # each StepInfo above, and non-homographic with the id on purpose.
    "secret_scan": AnalysisKind(
        "secret_scan", ["repo_secret_scan"], family="security",
        results=AnalysisKindResults(
            _secret_scan_results, None, "findings_list",
            headline_reader=_secret_scan_headline,
        ),
    ),
    "telemetry_scan": AnalysisKind(
        "telemetry_scan", ["repo_telemetry_scan"], family="security",
        results=AnalysisKindResults(
            _telemetry_scan_results, None, "findings_list",
            headline_reader=_telemetry_scan_headline,
        ),
    ),
    "contribution_provenance": AnalysisKind(
        "contribution_provenance", ["repo_contribution_provenance"], family="security",
        results=AnalysisKindResults(
            _contribution_provenance_results, None, "findings_list",
            headline_reader=_contribution_provenance_headline,
        ),
    ),
    # NOT family="security": publishing a support commitment is a governance and
    # transparency property, not a security control, and filing it under security
    # would make `WHERE family='security'` overstate what has been assessed.
    "sla_content": AnalysisKind(
        "sla_content", ["repo_sla_content"],
        results=AnalysisKindResults(
            _sla_content_results, None, "findings_list",
            headline_reader=_sla_content_headline,
        ),
    ),
    "repository_health": AnalysisKind(
        "repository_health", ["repo_health"],
        results=AnalysisKindResults(
            _health_results, _health_trend, "metrics", headline_reader=_health_headline,
        ),
    ),
    "dependency_analysis": AnalysisKind(
        "dependency_analysis", ["repo_dependency"],
        results=AnalysisKindResults(
            _dependency_results, _dependency_trend, "custom", headline_reader=_dependency_headline,
        ),
    ),
    "security_scan": AnalysisKind(
        "security_scan", ["repo_security"], family="security",
        results=AnalysisKindResults(
            _security_results, _security_trend, "findings_list", headline_reader=_security_headline,
        ),
    ),
    "documentation_coverage": AnalysisKind(
        "documentation_coverage", ["repo_documentation"],
        results=AnalysisKindResults(
            _documentation_results, _documentation_trend, "findings_list",
            headline_reader=_documentation_headline,
        ),
    ),
    "data_file_profiling": AnalysisKind(
        "data_file_profiling", ["repo_data_profiling"],
        results=AnalysisKindResults(
            _data_profile_results, _data_profile_trend, "custom", headline_reader=_data_profile_headline,
        ),
    ),
    # D5 note: deliberately NOT bundled with repo_symbol_extraction the way
    # language_file_classification bundles its three step_keys — this kind
    # is also selectable *scoped* (target_shape: corpus,
    # sub-resource-narrowed runs, see the repo scope-narrowing funnel plan),
    # and repo_symbol_extraction can't honor scope_locator (extraction reads
    # the whole zipball, there's no sub-resource-only extraction) — bundling
    # would silently force a full, unscoped, real zipball-download
    # extraction into every scoped "API Structure" request. Symbol
    # Extraction stays its own AnalysisKind (below) instead — independently
    # run/scheduled, and included automatically in any full (steps=None)
    # survey since it's a plain STEP_REGISTRY member either way.
    "api_structure": AnalysisKind(
        "api_structure", ["repo_api_structure"],
        results=AnalysisKindResults(
            _api_structure_results, _api_structure_trend, "custom",
            headline_reader=_api_structure_headline,
            # project_code_symbols is repopulated at INGESTION, not survey
            # time — this reader's own comment says so. Gating it on "was
            # this step among a recorded survey run" asks the wrong question.
            live_read=True,
        ),
    ),
    "sub_resource_survey": AnalysisKind(
        "sub_resource_survey", ["repo_sub_resource_survey"],
        results=AnalysisKindResults(
            _sub_resource_survey_results, _sub_resource_survey_trend, "custom",
            headline_reader=_sub_resource_survey_headline,
        ),
    ),
    "repo_classification": AnalysisKind(
        "repo_classification", ["repo_classification"],
        results=AnalysisKindResults(_repo_classification_results, None, "custom",
                                    headline_reader=_repo_classification_headline),
    ),
    "license_classification": AnalysisKind(
        "license_classification", ["repo_license_classification"],
        results=AnalysisKindResults(_license_results, None, "findings_list", headline_reader=_license_headline),
    ),
    "security_features": AnalysisKind(
        "security_features", ["repo_security_features"], family="security",
        results=AnalysisKindResults(
            _security_features_results, _security_features_trend, "findings_list",
            headline_reader=_security_features_headline,
        ),
    ),
    "ci_quality": AnalysisKind(
        "ci_quality", ["repo_ci_quality"],
        results=AnalysisKindResults(
            _ci_quality_results, _ci_quality_trend, "findings_list", headline_reader=_ci_quality_headline,
        ),
    ),
    "interface_surface": AnalysisKind(
        "interface_surface", ["repo_interface_surface"],
        results=AnalysisKindResults(
            _interface_surface_results, None, "findings_list",
            headline_reader=_interface_surface_headline,
        ),
    ),
    "chaoss_metrics": AnalysisKind(
        "chaoss_metrics", ["repo_chaoss_metrics"],
        results=AnalysisKindResults(
            _chaoss_metrics_results, _chaoss_metrics_trend, "findings_list",
            headline_reader=_chaoss_metrics_headline,
        ),
    ),
    "cii_badge": AnalysisKind(
        "cii_badge", ["repo_cii_badge"],
        family="security",
        results=AnalysisKindResults(
            _cii_badge_results, None, "findings_list",
            headline_reader=_cii_badge_headline,
        ),
    ),
    "community_support": AnalysisKind(
        "community_support", ["repo_community_support"],
        results=AnalysisKindResults(
            _community_support_results, None, "findings_list",
            headline_reader=_community_support_headline,
        ),
    ),
    "cve_scan": AnalysisKind(
        "cve_scan", ["repo_cve_scan"],
        family="security",
        results=AnalysisKindResults(
            _cve_scan_results, _cve_scan_trend, "findings_list",
            headline_reader=_cve_scan_headline,
        ),
    ),
    "foss_scorecard": AnalysisKind(
        "foss_scorecard", ["repo_foss_scorecard"],
        family="security",
        results=AnalysisKindResults(
            _foss_scorecard_results, _foss_scorecard_trend, "findings_list",
            headline_reader=_foss_scorecard_headline,
        ),
    ),
    "refresh_plan": AnalysisKind(
        "refresh_plan", ["repo_refresh_plan"],
        results=AnalysisKindResults(
            _refresh_plan_results, None, "findings_list",
            headline_reader=_refresh_plan_headline,
        ),
    ),
    "security_summary": AnalysisKind(
        "security_summary", ["repo_security_summary"],
        family="security",
        results=AnalysisKindResults(
            _security_summary_results, None, "findings_list",
            headline_reader=_security_summary_headline,
        ),
    ),
    "maturity": AnalysisKind(
        "maturity", ["repo_maturity"],
        results=AnalysisKindResults(_maturity_results, None, "findings_list", headline_reader=_maturity_headline),
    ),
    "repo_conventions": AnalysisKind(
        "repo_conventions", ["repo_conventions"],
        results=AnalysisKindResults(
            _repo_conventions_results, _repo_conventions_trend, "findings_list",
            headline_reader=_repo_conventions_headline,
        ),
    ),
    # D5 — independently runnable/schedulable refresh of project_code_symbols
    # (see repo_symbol_extraction's StepInfo docstring for the bug this
    # closes). Kept separate from "api_structure" rather than bundled into
    # it — see that AnalysisKind's own comment for why.
    # The fourth instance of the "a table everything reads that nothing writes"
    # pattern, and the largest. Note D5: this does NOT replace the
    # action=="ingest" branches in scheduler.py and web/routes/projects.py —
    # existing schedules reference rag_ingestion by analysis id and the Analysis
    # card's Run button uses that route, so both keep working unchanged. This
    # adds the survey-step path and the results view; retiring the branches is a
    # separate follow-up.
    "rag_ingestion": AnalysisKind(
        "rag_ingestion", ["repo_rag_ingestion"],
        results=AnalysisKindResults(
            _rag_ingestion_results, _rag_ingestion_trend, "metrics",
            headline_reader=_rag_ingestion_headline,
        ),
    ),
    "website_ingestion": AnalysisKind(
        "website_ingestion", ["repo_website_ingestion"],
        results=AnalysisKindResults(
            _website_ingestion_results, _website_ingestion_trend, "custom",
            headline_reader=_website_ingestion_headline,
        ),
    ),
    "code_symbol_extraction": AnalysisKind(
        "code_symbol_extraction", ["repo_symbol_extraction"],
        results=AnalysisKindResults(
            _symbol_extraction_results, _symbol_extraction_trend, "custom",
            headline_reader=_symbol_extraction_headline,
        ),
    ),
    # Independently runnable/schedulable refresh of project_dependencies +
    # project_analysis_findings (kind="ci_quality"/"repo_conventions") — the
    # fifth instance of "a table everything reads that nothing writes"
    # (project_stats, project_file_inventory, project_code_symbols were the
    # first three; this closes it for three tables at once). Kept as its own
    # card rather than folded into dependency_analysis/ci_quality/
    # repo_conventions for the same reason code_symbol_extraction stays
    # separate from api_structure: this step is a real zipball download and
    # those three are read-only, so bundling would force an unwanted download
    # into every "just show me what's already there" card click. Included
    # automatically in any full (steps=None) survey since it's a plain
    # STEP_REGISTRY member either way — this card exists so it is also
    # reachable and independently schedulable on its own, same as
    # code_symbol_extraction.
    "manifest_parse": AnalysisKind(
        "manifest_parse", ["repo_manifest_parse"],
        results=AnalysisKindResults(
            _manifest_parse_results, _manifest_parse_trend, "custom",
            headline_reader=_manifest_parse_headline,
        ),
    ),
    # Phase 1 plan §4.2/§4.4 — bundles both architecture-recovery steps the
    # way language_file_classification bundles three: one card, one Results
    # view, over both repo_arch_detect's and repo_arch_coupling's combined
    # output (grouped by scope_locator, not by which step wrote it — see
    # _architecture_recovery_results' docstring).
    "architecture_doc_lens": AnalysisKind(
        "architecture_doc_lens", ["repo_arch_lens"],
        results=AnalysisKindResults(_architecture_doc_lens_results, None, "findings_list",
                                    headline_reader=_architecture_doc_lens_headline),
    ),
    "architecture_summary": AnalysisKind(
        "architecture_summary", ["repo_arch_summary"],
        results=AnalysisKindResults(_architecture_summary_results, None, "metrics",
                                    headline_reader=_architecture_summary_headline),
    ),
    "architecture_recovery": AnalysisKind(
        "architecture_recovery", ["repo_arch_detect", "repo_arch_coupling"],
        results=AnalysisKindResults(
            _architecture_recovery_results, _architecture_recovery_trend, "custom",
            headline_reader=_architecture_recovery_headline,
        ),
    ),
}

# ── cost tiers: ordering and per-analysis rollup ─────────────────────────
# The ordinal scales StepInfo.fetch_cost/compute_cost draw from. Defined here,
# beside the dataclass that declares those fields, and imported by
# survey_orchestrator.py rather than duplicated there — two private copies of
# an ordinal scale drift silently, and a wrong index means a cost filter that
# quietly admits a step it was meant to exclude.
FETCH_COST_ORDER = ["none", "api", "api_heavy", "download"]
COMPUTE_COST_ORDER = ["low", "medium", "high"]


def analysis_cost(analysis_id: str) -> tuple[str, str]:
    """This analysis's (fetch_cost, compute_cost), as the max over its steps.

    Max rather than sum, because these are ordinal labels and not quantities —
    adding "download" to "api" has no meaning. What a caller wants to know is
    "how expensive is the worst thing this will do", which is what governs
    whether it is safe to run hourly. An analysis with no mapped steps is
    ("none", "low"): it costs nothing here because it does nothing here (the
    Survey-Definition and publish dispatch paths run elsewhere).
    """
    steps = [STEP_REGISTRY[k] for k in REPO_ANALYSIS_STEP_MAP.get(analysis_id, [])
             if k in STEP_REGISTRY]
    if not steps:
        return ("none", "low")
    return (max((s.fetch_cost for s in steps), key=FETCH_COST_ORDER.index),
            max((s.compute_cost for s in steps), key=COMPUTE_COST_ORDER.index))


# ── "cheap often, expensive rarely", in the scheduler's own vocabulary ────
# Cadences are picked from {manual, daily, weekly, monthly} — there is no
# hour-level control anywhere in this system — so the recommendation is a
# cadence name, not an interval in hours. An hours-based floor would imply a
# precision the scheduler cannot express and nothing could act on, which is
# exactly how `run_time` in analysis_catalog.yaml rotted (docs/step-cost-tiers-
# plan.md, "Why").
#
# Ordered most- to least-frequent, so "more frequent than recommended" is an
# index comparison rather than a pile of special cases.
SCHEDULE_FREQUENCY_ORDER = ["daily", "weekly", "monthly", "manual"]


def recommended_schedule(analysis_id: str) -> str:
    """The most frequent cadence worth using for this analysis.

    Keyed on fetch cost first: a download is what a schedule actually spends on
    someone else's infrastructure, so it dominates. High compute pushes one step
    further out — that cost is local, but it is the one that makes a run take
    long enough to collide with the next.

    Advisory, never enforced. The legitimate reasons to run an expensive
    analysis more often than this — actively working on it, a repo that really
    does change that fast — are invisible from inside the scheduler. What this
    addresses is choosing a cadence without knowing what it costs.

    Known limitation, stated rather than special-cased: fetch_cost records the
    worst case, so a step that usually skips its fetch is rated as if it always
    paid it. rag_ingestion is the live instance — IncrementalIndexer downloads
    only when the last-indexed SHA moved, so daily is defensible for it despite
    the "monthly" this returns. Encoding that would mean a conditional-cost
    axis, which is a real design question and not one worth answering to
    improve one recommendation the user can already override.
    """
    fetch, compute = analysis_cost(analysis_id)
    if fetch == "download" and compute == "high":
        return "monthly"
    if fetch in ("download", "api_heavy") or compute == "high":
        return "weekly"
    return "daily"


def schedule_is_more_frequent_than_recommended(analysis_id: str, schedule: str) -> bool:
    """True when `schedule` runs this analysis more often than its cost warrants.

    "manual" is never too frequent — it does not recur at all.
    """
    if schedule not in SCHEDULE_FREQUENCY_ORDER or schedule == "manual":
        return False
    rec = recommended_schedule(analysis_id)
    return SCHEDULE_FREQUENCY_ORDER.index(schedule) < SCHEDULE_FREQUENCY_ORDER.index(rec)


# Derived views — kept as the same names/shapes scheduler.py and
# web/routes/projects.py already import, so this consolidation doesn't
# force churn in every caller; only ANALYSIS_KINDS is hand-maintained now.
REPO_ANALYSIS_STEP_MAP: dict[str, list[str]] = {k: v.step_keys for k, v in ANALYSIS_KINDS.items()}
REPO_ANALYSIS_RESULTS_MAP: dict[str, tuple] = {
    k: (v.results.results_reader, v.results.trend_reader)
    for k, v in ANALYSIS_KINDS.items() if v.results
}
REPO_ANALYSIS_HEADLINE_MAP: dict[str, Callable] = {
    k: v.results.headline_reader
    for k, v in ANALYSIS_KINDS.items() if v.results and v.results.headline_reader
}


# ── Survey Results dashboard registry (docs/survey-results-dashboard-plan.md) ──
# Tier 2 — repo-wide, cross-stage dashboards. Each groups one or more
# ANALYSIS_KINDS ids into one view composition; no new persistence, this is
# purely a read/aggregation layer over the existing results_reader machinery.

@dataclass
class SurveyResultDashboard:
    id: str
    title: str
    description: str
    analysis_ids: list[str]        # which ANALYSIS_KINDS entries this pulls from
    render: str = "grouped_cards"  # "grouped_cards" (stack each id's existing
                                    # findings_list/metrics/custom renderer under
                                    # one heading) | "custom" (a genuinely
                                    # composite widget spanning >1 analysis_id)
    custom_renderer: str | None = None   # JS function name, when render="custom"


SURVEY_RESULT_DASHBOARDS: dict[str, SurveyResultDashboard] = {
    # cve_scan/foss_scorecard/cii_badge added 2026-08-31 (docs/Backlog.md
    # "Survey Results dashboards cover 14 of 29 analyses", remaining-8 list) —
    # all three are the same "is this trustworthy" question security_overview
    # already asks, just from OSV.dev/OpenSSF-Scorecard-shape/bestpractices.dev
    # rather than repo-local signals. renderSecurityOverviewDashboard's own
    # scorecard tiles are NOT updated for these three (that's index.html, a
    # separate change) — they still render, via _renderGroupedCardsDashboard's
    # generic fallback the custom renderer already appends its scorecard to,
    # just without a dedicated tile yet. Not silently dropped, just not
    # polished — noted rather than left for someone to discover.
    "security_overview": SurveyResultDashboard(
        "security_overview", "Security Overview",
        "Artifact presence (SECURITY.md/CI/LICENSE), GitHub's native security feature "
        "toggles, CI quality, license risk tier, and security-policy content — the full "
        "security picture in one place, not five separate cards. Also gathers the three "
        "externally-sourced trust signals (CVE advisories, OpenSSF Scorecard, OpenSSF Best "
        "Practices badge) that ask the same question from outside the repo.",
        # security_summary FIRST: it is the reduction of the other eight, and a
        # reader who stops after one card should get the one that names its own
        # coverage and staleness rather than an arbitrary input.
        ["security_summary",
         "security_scan", "security_features", "ci_quality", "license_classification",
         "repo_conventions", "cve_scan", "foss_scorecard", "cii_badge",
         # The four GAP analyses (2026-09-01). Three genuinely belong to this
         # "is this trustworthy" question; sla_content is here because it has
         # nowhere better and NOT because it is a security signal — it reports a
         # governance/transparency property, and its AnalysisKind deliberately
         # carries no family="security" for that reason. Worth revisiting if a
         # governance dashboard ever exists; parked rather than mis-filed
         # silently.
         "secret_scan", "telemetry_scan", "contribution_provenance", "sla_content"],
        render="custom", custom_renderer="renderSecurityOverviewDashboard",
    ),
    # community_support/chaoss_metrics added 2026-08-31, same Backlog entry —
    # both are community/activity signal, same topic repository_health
    # already reports a cruder version of (stars/forks dominate its score;
    # these two report attention/participation/channels as separate
    # dimensions instead of averaging them away — see community_support's
    # own description).
    "health_maturity": SurveyResultDashboard(
        "health_maturity", "Health & Maturity",
        "Activity/community signal from GitHub stats, alongside lifecycle-stage "
        "classification and the community-health metrics that report attention, "
        "participation and channels as separate dimensions rather than one averaged score.",
        ["repository_health", "maturity", "community_support", "chaoss_metrics"],
    ),
    "documentation_conventions": SurveyResultDashboard(
        "documentation_conventions", "Documentation & Conventions",
        "README/CHANGELOG/CONTRIBUTING coverage and doc-quality, plus repo-convention "
        "signals (build automation, deployment evidence, catalog self-description).",
        ["documentation_coverage", "repo_conventions"],
    ),
    # Opened 2026-08-31 (docs/Backlog.md "Survey Results dashboards cover 14 of
    # 29 analyses"): all three architecture analyses were homeless in this
    # registry — architecture_recovery has its own bespoke card elsewhere in
    # the UI, but nothing gathered its own summary (architecture_summary) and
    # its doc-consistency lens (architecture_doc_lens) alongside it, even
    # though a single authored question ("What is its internal architecture —
    # what components exist and how do they relate?") already names all
    # three together. render="grouped_cards" reuses each id's existing
    # renderer as-is (architecture_recovery keeps its own perspective-tabbed
    # custom view via _renderCustomAnalysisResults' dispatch) — no new
    # frontend code needed, same pattern documentation_conventions above
    # already proves out.
    "architecture_overview": SurveyResultDashboard(
        "architecture_overview", "Architecture Overview",
        "Recovered architecture components, the depth-collapsed summary a question actually "
        "asked for, and whether the project's own architecture document agrees with what was "
        "recovered — three analyses of the same question, previously shown nowhere together.",
        ["architecture_recovery", "architecture_summary", "architecture_doc_lens"],
    ),
    "dependencies": SurveyResultDashboard(
        "dependencies", "Dependencies",
        "Package dependencies per ecosystem.",
        ["dependency_analysis"],
    ),
    # interface_surface added 2026-08-31, same Backlog entry — "what can be
    # talked to, and whether the contract is written down" is the same
    # surface api_structure already reports on, just from declared
    # dependencies/file inventory rather than parsed source.
    "code_structure": SurveyResultDashboard(
        "code_structure", "Code Structure",
        "File/language classification, public API surface, extracted code symbols, and "
        "what interfaces the project exposes and whether they're documented.",
        ["language_file_classification", "api_structure", "code_symbol_extraction",
         "interface_surface"],
    ),
    "data_profile": SurveyResultDashboard(
        "data_profile", "Data Profile",
        "Data-file inventory/schema profiling and sub-resource cataloging candidates.",
        ["data_file_profiling", "sub_resource_survey"],
    ),
    # repo_classification and manifest_parse, added 2026-08-31, close out the
    # remaining-8 list — neither fits an existing theme (classification is its
    # own question; manifest_parse is a refresh operation, not a topic), so
    # each gets a single-item dashboard rather than being forced into one that
    # doesn't fit. `dependencies` above is the existing precedent for a
    # single-item dashboard being an accepted shape, not a special case.
    "repo_classification": SurveyResultDashboard(
        "repo_classification", "Repo Classification",
        "What the repo represents (library/application/tool/documentation/etc.), where its "
        "expected artifacts live, and whether architecture recovery is worth running.",
        ["repo_classification"],
    ),
    "manifest_refresh": SurveyResultDashboard(
        "manifest_refresh", "Refresh",
        "Whether this repo's derived data is current, and the last refresh of it. The plan comes "
        "first: which targets are stale, which never ran, and which are already current — judged "
        "per target, since a target that never ran needs work whatever the commit says. Then the "
        "manifest refresh itself. Not a fourth view of dependency_analysis/ci_quality/"
        "repo_conventions' own data (those are the dashboards for that); this reports the refresh.",
        # refresh_plan first: it is the one card that says whether anything here
        # needed doing, which is the question a reader arrives with.
        ["refresh_plan", "manifest_parse"],
    ),
}


def get_dashboard_stages(analysis_ids: list[str]) -> list[str]:
    """Which funnel stage(s) a Survey Results card belongs to — derived, never
    hand-authored, for the same reason perspectives are (see below): a card's
    stage is a consequence of what it reports on, so deriving it means the two
    cannot drift apart.

    Source is analysis_catalog.yaml's per-analysis `intent`, deliberately rather
    than the Funnel Stage column in the questions CSV. Both describe "stage", but
    the catalog's is the canonical vocabulary (CLAUDE.md rule 17 — lowercase
    scouting/discovery/assessment/analysis/enrichment/understanding/curate/
    automate), it is complete (every analysis has one, whereas only analyses
    referenced by a Question get a funnel stage — which would leave the
    code_structure and data_profile cards with no stage at all and therefore
    invisible everywhere), and it is already what the Assessment/Analysis panels
    route by, so Results now agrees with the tabs it sits beside.

    A card spanning stages is expected and fine — health_maturity reports both
    repository_health (scouting) and maturity (assessment), so it appears under
    both. Returned in canonical order rather than discovery order so the UI is
    stable across runs.
    """
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    _CANONICAL = [
        "scouting", "discovery", "assessment", "analysis",
        "enrichment", "understanding", "curate", "automate",
    ]
    wanted = set(analysis_ids)
    by_id = {a["id"]: (a.get("intent") or "").strip().lower()
             for a in get_analyses("repo")}
    found = {by_id[a] for a in wanted if by_id.get(a)}
    # An analysis_id absent from the catalog (e.g. sub_resource_survey) simply
    # contributes no stage rather than breaking the card — the card still shows
    # wherever its other analyses place it.
    return [s for s in _CANONICAL if s in found]


def get_dashboard_perspectives(analysis_ids: list[str]) -> list[str]:
    """D4 — a dashboard's Perspective tags are derived, not hand-authored:
    the union of Perspectives linked to any Question whose
    answering.analysis_ids intersects this dashboard's analysis_ids.
    question_catalog.yaml's analysis_ids already use the same vocabulary as
    ANALYSIS_KINDS' keys (both trace back to analysis_catalog.yaml ids), so
    this is a direct intersection — no REPO_ANALYSIS_STEP_MAP indirection
    needed. repo-only (question_catalog_reader has no db/filesystem entries
    today — same graceful-degrade as the Survey panel's own Perspective row)."""
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    wanted = set(analysis_ids)
    perspectives: list[str] = []
    for entry in get_questions(resource_type="repo"):
        if wanted.intersection(entry["answering"]["analysis_ids"]):
            for p in entry["perspectives"]:
                if p not in perspectives:
                    perspectives.append(p)
    return perspectives


def get_dashboard_annotation_types(analysis_ids: list[str]) -> list[str]:
    """Union of analysis_catalog.yaml's `annotation_types` across a
    dashboard's analysis_ids — the join key back to real Egeria publish
    history (registry.get_last_published_annotation_types(), 2026-08-24:
    "we should already have all of that information if it's been published
    to Egeria" — this is what makes that true: EgeriaPublisher already knows
    which annotation_types went into a publish, this just says which
    analysis_ids/dashboards those types belong to). Same derived-not-hand-
    authored pattern as get_dashboard_stages/get_dashboard_perspectives
    above — an analysis_id absent from the catalog, or with no declared
    annotation_types, simply contributes nothing rather than breaking the
    card."""
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    wanted = set(analysis_ids)
    types: list[str] = []
    for a in get_analyses("repo"):
        if a["id"] not in wanted:
            continue
        for t in a.get("annotation_types") or []:
            if t not in types:
                types.append(t)
    return types


_RUN_TIME_RANK = {"fast": 0, "minutes": 1, "async": 2}


def get_survey_definition_speed_tag(steps: list[dict]) -> str:
    """Derived 'fast'/'minutes'/'async' tag for a Survey Definition
    candidate, matching the local Analyses catalog's own run_time field
    (2026-08-24 — direct feedback: the speed tag existed on Analyses cards
    but not Survey Definition cards, one more field the two card families
    didn't share). No such field exists on a Survey Definition itself, so
    this is inferred, not read: each step with a `re_analysis_step` is
    looked up against REPO_ANALYSIS_STEP_MAP's *analysis_id* (via the
    reverse step_key -> analysis_id lookup below) to find its catalog
    run_time; a step with no re_analysis_step (Egeria-native or another
    engine — no local run_time to consult) is conservatively treated as
    'minutes', never assumed 'fast'. The candidate's tag is the slowest
    (highest-rank) tier among all its steps — one slow step makes the
    whole bundle not-fast, same logic a human would apply. Falls back to
    'minutes' for a candidate with no steps at all (nothing to be fast
    about, but nothing confirming speed either)."""
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    step_key_to_run_time = {}
    for a in get_analyses("repo"):
        for step_key in REPO_ANALYSIS_STEP_MAP.get(a["id"], []):
            step_key_to_run_time[step_key] = a.get("run_time", "minutes")

    if not steps:
        return "minutes"
    worst = "fast"
    for s in steps:
        step_key = s.get("re_analysis_step")
        tier = step_key_to_run_time.get(step_key, "minutes") if step_key else "minutes"
        if _RUN_TIME_RANK.get(tier, 1) > _RUN_TIME_RANK.get(worst, 0):
            worst = tier
    return worst


def _get_project_entity(registry, slug: str):
    return registry.get(slug)


def _publish(project, step_outputs: list, surveyed_at: str, registry) -> str:
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
    from resource_explorer.surveyors.survey_report import SurveyResult

    result = SurveyResult(
        resource_slug=project.slug,
        project_display_name=project.display_name,
        github_url=project.github_url,
    )
    for output in step_outputs:
        for ann in output.get("annotations", []):
            result.add(ann)

    publisher = EgeriaPublisher(registry=registry)
    return publisher.publish(result)


_ADAPTER = ResourceTypeAdapter(
    entity_type="repo",
    technology_type="Git Repository",
    re_analysis_steps=_build_re_analysis_steps(),
    get_entity=_get_project_entity,
    publish=_publish,
    re_analysis_step_info=_RE_ANALYSIS_STEP_INFO,
    run_batch=_run_batch,
)

register_adapter(_ADAPTER)


# ── annotation type names ───────────────────────────────────────────────────
#
# Egeria's AnnotationProperties.annotation_type is a free string naming WHICH
# result an annotation is. RE filled it with the entity subtype name
# ("ClassificationAnnotation"), duplicating the `class` field beside it and
# telling a reader nothing: 14 repo analyses share that subtype. The names RE
# actually has — chaoss_metrics, supply_chain, cve_scan — never reached the
# catalog at all.
#
# The map is DERIVED from STEP_REGISTRY and ANALYSIS_KINDS rather than written
# out, because a hand-maintained second list of the same facts is what this
# module spent its history collapsing. Nothing here is guessed from string
# shape either: `CiQualityCheck` -> `ci_quality` and `ApiStructureAnalysis` ->
# `api_structure` are not derivable by any snake_case rule, and a rule that
# looked right for most of them would quietly mislabel the rest.

_ANNOTATION_TYPE_NAMES: dict | None = None


def _step_constant(surveyor_cls) -> str:
    """The value a surveyor puts in Annotation.analysis_step, or "".

    Three conventions exist in the tree, all read here, none required: a
    module-level STEP constant (most), a class-level STEP attribute
    (FileClassifierSurveyor), and a `step_name` property returning a literal
    (the architecture surveyors). Reading all three is cheaper than making
    thirty surveyors agree on one, and a convention this file does not know
    about simply goes unmapped rather than being mislabelled.
    """
    import importlib

    try:
        step = getattr(importlib.import_module(surveyor_cls.__module__), "STEP", None)
    except ImportError as exc:
        log.warning("cannot read STEP for %s — module import failed: %s",
                    surveyor_cls.__name__, exc)
        return ""
    if isinstance(step, str) and step:
        return step

    own = getattr(surveyor_cls, "STEP", None)
    if isinstance(own, str) and own:
        return own

    prop = getattr(surveyor_cls, "step_name", None)
    getter = getattr(prop, "fget", None)
    if getter is None:
        log.warning("%s declares no STEP constant and no step_name property — its "
                    "annotations will fall back to naming their entity subtype",
                    surveyor_cls.__name__)
        return ""
    try:
        # Safe for a property whose body is `return "SomeName"`. One that
        # touches self raises exactly these, and is left unmapped.
        value = getter(None)
    except (AttributeError, TypeError) as exc:
        log.warning("%s.step_name could not be read without an instance (%s) — its "
                    "annotations will fall back to naming their entity subtype",
                    surveyor_cls.__name__, exc)
        return ""
    return value if isinstance(value, str) else ""


def annotation_type_names() -> dict:
    """{analysis_step value: annotation type name}.

    The name is the analysis id where the step belongs to one, and the step key
    otherwise. The four prerequisite refresh steps (repo_file_inventory,
    repo_git_statistics, repo_homepage, repo_file_size) have no analysis by
    design — they are expressible in a survey type, not as an analysis — so
    their own key is the most specific true name they have.
    """
    global _ANNOTATION_TYPE_NAMES
    if _ANNOTATION_TYPE_NAMES is not None:
        return _ANNOTATION_TYPE_NAMES

    step_to_analysis = {sk: aid for aid, kind in ANALYSIS_KINDS.items()
                        for sk in kind.step_keys}
    out: dict = {}
    for step_key, info in STEP_REGISTRY.items():
        constant = _step_constant(info.surveyor_cls)
        if constant:
            out[constant] = step_to_analysis.get(step_key, step_key)
    _ANNOTATION_TYPE_NAMES = out
    return out


def resolve_annotation_type(analysis_step: str) -> str:
    """The annotation type name for an analysis_step, or "" when unknown.

    Returns "" rather than a guess. Callers fall back to the entity subtype
    name, which is what was always written — wrong, but no more wrong than
    before, and a fabricated name would be worse than a vague one.
    """
    return annotation_type_names().get((analysis_step or "").strip(), "")
