"""Sub-surveyor: Architecture Coupling -> ResourceMeasureAnnotation.

Phase 1 plan §4.2, step key `repo_arch_coupling`. Wraps
resource_explorer.surveyors.arch_recovery's ported imports/cochange/
coupling modules (scripts/arch-spike, findings 23-44): import-graph +
co-change coupling as a boundary PROPOSER (§4.1), not the Phase 0 scorer.

Needs real git history, which a zipball does not have — this is the reason
`git_clone_root` exists at all (design §5.7 gap 2,
repo_survey_definition_adapter.py's `_acquire_git_clone_root`), so
`requires_resources = {"git_clone_root": "local_path"}`, deliberately
different from repo_arch_detect's zipball_root. That is also why this is a
second StepInfo rather than folded into repo_arch_detect: the two steps
need different resources, even though grouping them into one Survey
Definition still shares one checkout per resource kind via `_run_batch`.

Co-change is computed and attached as a *supporting* metric
(`cochange_cohesion`) alongside each proposed component, but — matching
arch_recovery.coupling.propose()'s own documented behaviour — it does NOT
feed the shape classification itself; only import edges are directional
enough for the fan-in/fan-out dispersion rule (finding 34).
"""
from __future__ import annotations

import logging
from datetime import datetime

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.scoping import path_matches_scope
from resource_explorer.surveyors.survey_report import (
    Annotation,
    ResourceMeasureAnnotation,
)

log = logging.getLogger(__name__)

STEP = "ArchitectureCoupling"

# arch-spike cochange.py defaults (findings 25) — read as-is, not tuned.
_COCHANGE_MONTHS = 24
_COCHANGE_MAX_FILES = 50


class ArchCouplingSurveyor(BaseSurveyor):
    def __init__(
        self,
        project: Project,
        registry: ProjectRegistry,
        source_path: str | None = None,
        history_path: str | None = None,
        scope_locator: str = "",
        surveyed_at: str | None = None,
    ) -> None:
        super().__init__(project, registry)
        # TWO resources, because coupling draws on two different views of the
        # same repo and one artifact cannot serve both:
        #
        #   source_path  (zipball_root)    — the CODE view. Import extraction
        #                                    needs files on disk.
        #   history_path (git_clone_root)  — the CHANGE view. Co-change needs
        #                                    git history and no file contents.
        #
        # An earlier version passed `git_clone_root` as a single `local_path`
        # and read both from it. That clone is `--filter=blob:none
        # --no-checkout`, so its root contains **only `.git`** — verified: zero
        # .py files. Co-change worked; import extraction silently scanned an
        # empty tree, produced zero edges, and coupling proposed zero
        # components on every real repo. The first live run against
        # egeria-python returned 9 components, all from manifests and code
        # markers, and none from coupling.
        #
        # `--no-checkout` is correct for the history view — without it a
        # treeless clone fetches every blob in HEAD, defeating the filter. It
        # became a bug only when a second consumer with a different view was
        # pointed at the same root. Naming the two resources by the view each
        # serves is what stops that recurring.
        self.source_path = source_path
        self.history_path = history_path
        self._scope_locator = scope_locator
        self._surveyed_at = surveyed_at or datetime.utcnow().isoformat()

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        if not self.source_path:
            self._warn(results, "No source tree available — zipball_root resource was not resolved; "
                                "import coupling needs files on disk")
            return results
        if not self.history_path:
            self._warn(results, "No git history available — git_clone_root resource was not resolved; "
                                "co-change needs git log")
            return results

        try:
            from resource_explorer.surveyors.arch_recovery import (
                cochange,
                coupling,
                detectors,
                exclusion,
                imports,
            )
            from resource_explorer.surveyors.arch_recovery.persist import (
                persist_ir,
                scope_locator_for,
            )

            root = str(self.source_path)
            history_root = str(self.history_path)
            census = exclusion.scan(root)

            first_party = census.first_party
            if self._scope_locator:
                first_party = [f for f in first_party if path_matches_scope(f, self._scope_locator)]

            graph = imports.build_graph(root, first_party)              # code view
            cochange_result = cochange.build_cochange(                   # change view
                history_root, first_party, _COCHANGE_MONTHS, _COCHANGE_MAX_FILES, True,
            )

            package_roots = sorted({m["dir"] for m in detectors.python_manifests(root, first_party)}) or ["."]
            components, evidence, notes = coupling.propose(set(first_party), package_roots, graph["edges"])

            # Supporting co-change cohesion per proposed subtree — computed,
            # attached as evidence, and deliberately NOT part of the shape
            # decision above (see module docstring).
            file_subtree = coupling.candidate_subtrees(sorted(first_party), package_roots)
            coc_table = coupling.cohesion_table(file_subtree, cochange_result["pairs"], "a", "b", "cochange_count")
            extra_metrics: dict[str, dict[str, float]] = {}
            for c in components:
                sub = c.identity.value   # module-path identity == the subtree
                coc = coc_table.get(sub)
                if coc and coc.get("total_weight"):
                    extra_metrics[scope_locator_for(c)] = {"cochange_cohesion": coc["cohesion"]}

            persist_ir(
                self.registry, self.project.slug, components, evidence,
                self._surveyed_at, run_label="coupling",
                run_scope=self._scope_locator, extra_metrics=extra_metrics,
            )

            shape_counts: dict[str, int] = {}
            for e in evidence:
                if e.detector.startswith("coupling:"):
                    shape_counts[e.detector.split(":", 1)[1]] = shape_counts.get(e.detector.split(":", 1)[1], 0) + 1

            results.append(ResourceMeasureAnnotation(
                summary=(
                    f"{len(components)} boundary(ies) proposed from import/co-change coupling "
                    f"({', '.join(f'{n} {s}' for s, n in sorted(shape_counts.items(), key=lambda kv: -kv[1]))})"
                    if components else
                    "No coupling-proposed boundaries — repo may be too flat/small for a "
                    "subtree partition, or import extraction found no first-party Python"
                ),
                analysis_step=STEP,
                resource_properties={
                    "component_count": len(components),
                    "import_edges": graph["edge_count"],
                    "cochange_pairs": cochange_result["pair_count"],
                    "commits_considered": cochange_result["commits_considered"],
                },
                confidence=70,
            ))

            for note in notes:
                log.info("ArchCouplingSurveyor(%s): %s", self.project.slug, note)

        except Exception as exc:
            log.exception("ArchCouplingSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
