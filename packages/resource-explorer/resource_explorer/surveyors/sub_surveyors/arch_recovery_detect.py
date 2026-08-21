"""Sub-surveyor: Architecture Detect -> ResourceMeasureAnnotation +
RequestForActionAnnotation.

Phase 1 plan §4.2, step key `repo_arch_detect`. Wraps
resource_explorer.surveyors.arch_recovery's ported exclusion/detectors/
code_markers modules (scripts/arch-spike, findings 1-22) over a real
checkout: package manifests, deployment units (Dockerfile/compose), and
ast-grep code markers -> the Architecture IR's `Component`/`Evidence`
records. `target_shape: corpus` (analysis_catalog.yaml) — `scope_locator`
narrows which part of the repo gets analyzed, same as every other
corpus-shaped surveyor (repo_file_size, repo_api_structure, ...).

Needs a real checkout (manifests/Dockerfiles/compose files must be read),
so `requires_resources = {"zipball_root": "local_path"}` — a zipball is
sufficient here because this step reads files, not git history (that is
repo_arch_coupling's job, which needs a real clone instead).
"""
from __future__ import annotations

import logging
from datetime import datetime

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.scoping import path_matches_scope
from resource_explorer.surveyors.survey_report import (
    Annotation,
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
)

log = logging.getLogger(__name__)

STEP = "ArchitectureDetect"


class ArchDetectSurveyor(BaseSurveyor):
    def __init__(
        self,
        project: Project,
        registry: ProjectRegistry,
        local_path: str | None = None,
        scope_locator: str = "",
        surveyed_at: str | None = None,
    ) -> None:
        super().__init__(project, registry)
        self.local_path = local_path
        self._scope_locator = scope_locator
        self._surveyed_at = surveyed_at or datetime.utcnow().isoformat()

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        if not self.local_path:
            self._warn(results, "No local checkout available — zipball_root resource was not resolved")
            return results

        try:
            from resource_explorer.surveyors.arch_recovery import exclusion
            from resource_explorer.surveyors.arch_recovery.detectors import build_components
            from resource_explorer.surveyors.arch_recovery.persist import persist_ir

            root = str(self.local_path)
            census = exclusion.scan(root)
            first_party = census.first_party
            if self._scope_locator:
                first_party = [f for f in first_party if path_matches_scope(f, self._scope_locator)]

            components, evidence, notes = build_components(root, first_party)
            persist_ir(
                self.registry, self.project.slug, components, evidence,
                self._surveyed_at, run_label="detect",
                run_scope=self._scope_locator,
            )

            by_type: dict[str, int] = {}
            for c in components:
                by_type[c.type or "Unclassified"] = by_type.get(c.type or "Unclassified", 0) + 1
            summary = (
                f"{len(components)} candidate component(s) detected "
                f"({', '.join(f'{n} {t}' for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]))})"
                if components else "No components detected from manifests, deployment units, or code markers"
            )
            results.append(ResourceMeasureAnnotation(
                summary=summary, analysis_step=STEP,
                resource_properties={
                    "component_count": len(components),
                    "evidence_count": len(evidence),
                    "first_party_files": len(first_party),
                    "first_party_ratio": round(census.first_party_ratio, 4),
                },
                confidence=80,
            ))

            if census.total and census.first_party_ratio < 0.5:
                # arch-spike README finding 1 — make a shrunken first-party
                # corpus loud rather than letting it pass silently: most of
                # what build_components() saw may be vendor noise.
                results.append(RequestForActionAnnotation(
                    summary="Most tracked files were excluded as non-first-party",
                    analysis_step=STEP,
                    action_requested="Review vendor-exclusion rules for this repo",
                    action_target_name=self.project.slug,
                    explanation=(
                        f"Only {100 * census.first_party_ratio:.1f}% of tracked files were "
                        f"treated as first-party; architecture detection only sees "
                        f"first-party files."
                    ),
                    confidence=60,
                ))

            for note in notes:
                log.info("ArchDetectSurveyor(%s): %s", self.project.slug, note)

        except Exception as exc:
            log.exception("ArchDetectSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
