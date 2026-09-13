"""Sub-surveyor: which curated technologies does this repo's dependency list
indicate, and does Egeria already hold a type for each → ClassificationAnnotation.

Zero-fetch: reads `project_dependencies` (written by repo_manifest_parse) and
the curated mapping, and asks Egeria's technology-type catalog once. Discovery
tier under CLAUDE.md rule 17 — it reasons over what an earlier step collected
and fetches nothing from the repository. The Egeria call is catalog
consultation, not acquisition.

A **starting point for people**, per the project owner (2026-09-11): a match
means "this repo indicates technology X", not "we support X". The per-repo
result persists the matched technologies and one coverage row; the unmatched
names are re-derived at read time so the cross-repo ranked "nobody has
classified this yet" list — the actual human corroboration queue — needs no
table of its own. See `surveyors/dependency_support.py`.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from resource_explorer.step_outcome import StepOutcome
from resource_explorer.surveyors import dependency_support as ds
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "DependencySupportAssessment"
KIND = "dependency_support"


class DependencySupportSurveyor(BaseSurveyor):
    """One ClassificationAnnotation per matched technology, plus a coverage
    annotation that says how much of the dependency list the mapping covered
    and whether Egeria could be consulted."""

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        slug = self.project.slug
        try:
            deps = self.registry.query_dependencies(slug) or []
            if not deps:
                # Nothing to assess is a real, reportable state — not a zero
                # technologies matched. Either manifest parsing has not run, or
                # the repo declares no dependencies; both are `unverified` here
                # because this step cannot tell which from its own inputs.
                outcome = StepOutcome("unverified", cause="no project_dependencies rows",
                                      detail={"hint": "run repo_manifest_parse first"})
                results.append(ClassificationAnnotation(
                    summary="No dependency rows held for this repository — nothing to assess "
                            "(manifest parsing may not have run)",
                    # Not "coverage": that name belongs to the normal path's
                    # annotation below, and two annotations sharing a check_name
                    # with no item key publish the same qualifiedName if both
                    # ever run in one survey (test_annotation_check_names). This
                    # branch says "nothing to assess", which is a different
                    # statement from "here is how much was covered".
                    analysis_step=STEP, check_name="nothing_to_assess",
                    candidate_classifications=[], confidence=0,
                    json_properties={"total_dependencies": 0, **outcome.as_row()},
                ))
                self.registry.upsert_finding(slug, KIND, [{
                    "check_name": "coverage", "label": "no-dependencies",
                    "summary": "No dependency rows held — nothing to assess", "confidence": 0,
                    "detail": {"total_dependencies": 0, "egeria_check": "skipped",
                               "egeria_check_detail": "no dependencies to assess"},
                }], surveyed_at=datetime.now(UTC).isoformat())
                return results

            techs = ds.load_mapping()
            linked = sorted({t.egeria_technology_type for t in techs if t.egeria_technology_type})
            present, check, detail = ds.egeria_technology_types_present(linked)
            assessment = ds.assess(deps, technologies=techs, egeria_types=present,
                                   egeria_check=check, egeria_check_detail=detail)

            for m in assessment.matches:
                results.append(ClassificationAnnotation(
                    summary=f"{m.technology.name} — indicated by {', '.join(sorted(m.dependencies)[:6])}",
                    analysis_step=STEP, check_name="technology",
                    # One annotation per matched technology makes this check
                    # list-shaped, and the publisher builds each qualifiedName
                    # from (slug, run, check_name, item_key). Without the key,
                    # any repo with two matched technologies collided and EVERY
                    # publish of it — Curate, ☁ Publish, resync — was refused
                    # before writing. Found on the first live press, not by the
                    # static check-name guard, which sees sites and not loops.
                    item_key=m.technology.name,
                    candidate_classifications=[m.technology.name],
                    confidence=85 if m.egeria_state == "present" else 70,
                    json_properties={
                        "technology": m.technology.name,
                        "dependencies": sorted(m.dependencies),
                        "egeria_technology_type": m.technology.egeria_technology_type,
                        "egeria_state": m.egeria_state,
                        **StepOutcome("recovered").as_row(),
                    },
                ))

            # The coverage annotation carries the Egeria check state at the
            # top: `unreachable` is "could not check", and a reader must be
            # able to see that without inferring it from per-match states.
            cov_outcome = (StepOutcome("recovered") if check == "checked"
                           else StepOutcome("partial", cause=f"Egeria technology catalog {check}",
                                            detail={"egeria_check_detail": detail}))
            results.append(ClassificationAnnotation(
                summary=assessment.as_findings()[-1]["summary"],
                analysis_step=STEP, check_name="coverage",
                candidate_classifications=[],
                confidence=100 if check == "checked" else 50,
                json_properties={
                    "total_dependencies": assessment.total_dependencies,
                    "matched_dependencies": assessment.matched_dependency_count,
                    "unmatched_dependencies": len(assessment.unmatched),
                    "technologies": len(assessment.matches),
                    "egeria_check": check,
                    **cov_outcome.as_row(),
                },
            ))

            self.registry.upsert_finding(slug, KIND, assessment.as_findings(),
                                         surveyed_at=datetime.now(UTC).isoformat())
        except Exception as exc:
            log.exception("DependencySupportSurveyor failed for %s", slug)
            self._warn(results, str(exc))
        return results
