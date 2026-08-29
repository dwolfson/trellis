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
from resource_explorer.step_outcome import UNVERIFIED, StepOutcome, no_signal
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
            from resource_explorer.surveyors.arch_recovery import exclusion, imports
            from resource_explorer.surveyors.arch_recovery import code_markers
            from resource_explorer.surveyors.arch_recovery.detectors import (
                build_components,
                deployment_units,
                gradle_modules,
                node_manifests,
                python_manifests,
            )
            from resource_explorer.surveyors.arch_recovery.persist import persist_ir

            root = str(self.local_path)
            census = exclusion.scan(root)
            first_party = census.first_party
            if self._scope_locator:
                first_party = [f for f in first_party if path_matches_scope(f, self._scope_locator)]

            components, evidence, notes = build_components(root, first_party)

            # Unlike coupling, detect has three independent ways to find a
            # component — package manifests, Dockerfile/compose deployment
            # units, and ast-grep code markers — and only the last needs
            # source-language extraction at all (module docstring). So a zero
            # here is only ambiguous if NONE of the three had anything to work
            # with: no recognized manifest ecosystem, no deployment unit, and
            # no first-party file in a language the code-marker rules cover.
            # If any of those existed, this run had a real chance to find
            # something and zero is a trustworthy answer, not a blind spot.
            if not components:
                has_manifest = bool(
                    python_manifests(root, first_party)
                    or node_manifests(root, first_party)
                    or gradle_modules(root, first_party)
                )
                has_deployment_unit = any(u != "." for u in deployment_units(root, first_party))
                present_langs = imports.languages_present(first_party)
                has_marker_language = bool(set(present_langs) & code_markers.marker_languages())
                if has_manifest or has_deployment_unit or has_marker_language:
                    detect_outcome: StepOutcome | None = no_signal(
                        "no_components_detected", known_positive=True,
                        has_manifest=has_manifest, has_deployment_unit=has_deployment_unit,
                    )
                else:
                    detect_outcome = StepOutcome(
                        UNVERIFIED, cause="no_supported_source",
                        detail={
                            "languages_present": present_langs,
                            "marker_languages": sorted(code_markers.marker_languages()),
                        },
                    )
            else:
                detect_outcome = None  # persist_ir's ordinary scoped/recovered default

            # Distillation (design §5.2 step 1, spike findings 76-80). The
            # detector optimises recall and over-proposes heavily: measured on
            # the corpus 2026-08-24, Milvus yields 202 candidates against a
            # published ground truth of 8, `genaicomps` 311. Persisting that is
            # noise at scale, not coverage.
            #
            # Runs AFTER the zero-check above deliberately. "Nothing was
            # detected" and "things were detected and every one was support
            # material or a whole-repo claim" are different statements about the
            # repo, and collapsing them would lose the more informative one.
            distill_stats: dict = {}
            if components:
                from resource_explorer.surveyors.arch_recovery import distill as _distill
                kept, dropped, distill_stats = _distill.distill(components)
                notes.append(f"distillation: {_distill.summarise(distill_stats)}")
                if not kept:
                    # Every candidate was filtered. Not `no_signal` — detection
                    # worked and found things; the filters rejected all of them,
                    # which is a claim about this repo (all support material, or
                    # only whole-repo claims) and is worth saying out loud.
                    notes.append(
                        "every candidate was filtered — the repo proposed only "
                        "support-material or whole-repo candidates, which is a "
                        "statement about the repo, not a failed detection"
                    )
                    detect_outcome = no_signal(
                        "all_candidates_distilled", known_positive=True,
                        input_candidates=distill_stats.get("input", 0),
                    )
                components = kept

            # Ports and wires (design §5.5f). This was committed and
            # regression-tested against `interfaces.propose()` but its only
            # caller was the throwaway spike harness, so in the product they
            # were computed by nobody and stored nowhere — the capability
            # existed and nothing wired it to storage. Caught by the
            # presentation session before a view was built against an
            #empty reader; recorded as spike finding 89.
            #
            # Deployment artifacts only: no source parsing, no clone, so this
            # does not move the step's cost tier.
            try:
                from resource_explorer.surveyors.arch_recovery import interfaces
                ports, wires, iface_ev, iface_notes = interfaces.propose(
                    root, first_party, components)
                evidence.extend(iface_ev)
                notes.extend(iface_notes)
            except Exception:
                log.exception("%s: interface extraction failed", self.project.slug)
                ports, wires = [], []

            # Spring applications declare their own deployment architecture:
            # the process, its port, the sub-components it hosts, and the
            # endpoints it reaches. For Egeria that is the difference between
            # 235 module-path components with no wires and one platform with
            # five servers, three internal REST edges and a Postgres
            # dependency — the same repo read in the deployment-specification
            # perspective rather than the physical one (design §4.1).
            try:
                from resource_explorer.surveyors.arch_recovery import spring_app
                spring = spring_app.discover(root)
                sp_components, sp_ports, sp_wires, sp_ev = spring_app.to_ir(spring)
                if sp_components:
                    components.extend(sp_components)
                    evidence.extend(sp_ev)
                    ports.extend(sp_ports)
                    wires.extend(sp_wires)
                    notes.extend(spring["notes"])
            except Exception:
                # Recorded, not swallowed: a failure here means the deployment
                # perspective is missing entirely, which looks identical to a
                # repo that declares no Spring application.
                log.exception("%s: spring application discovery failed", self.project.slug)
                notes.append("spring application discovery failed — deployment-perspective "
                             "components not proposed for this run")

            persist_ir(
                self.registry, self.project.slug, components, evidence,
                self._surveyed_at, run_label="detect",
                run_scope=self._scope_locator, outcome=detect_outcome,
                ports=ports, wires=wires,
            )

            by_type: dict[str, int] = {}
            for c in components:
                by_type[c.type or "Unclassified"] = by_type.get(c.type or "Unclassified", 0) + 1
            if components:
                summary = (
                    f"{len(components)} candidate component(s) detected "
                    f"({', '.join(f'{n} {t}' for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]))})"
                )
            elif detect_outcome is not None and detect_outcome.outcome == UNVERIFIED:
                langs = ", ".join(sorted(imports.languages_present(first_party))) or "none recognized"
                summary = (
                    "Unverified — no recognized manifest, deployment unit, or "
                    f"code-marker-supported language found; this repo's first-party "
                    f"files are {langs}"
                )
            else:
                summary = "No components detected from manifests, deployment units, or code markers"
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
