"""Sub-surveyor: Architecture Doc Lens — label recovered components against the
architecture document (finding 101/102).

Step key `repo_arch_lens`. Runs between `repo_arch_coupling` and
`repo_arch_summary`: it needs components to label, and the summary is worth more
once it can report *documented* components instead of candidates.

**Its own step, not a piece of detect.** Three properties differ from both
neighbours, and the third is the one that decided it:

* **Cost.** `repo_arch_detect` is `fetch_cost: download` (a zipball);
  `repo_arch_summary` is `none`. This is `api` — GitHub calls against a
  *different* repository. Folding it into either would make that step's declared
  cost false, which `48fe0d3` already had to fix once.
* **Cadence.** The document changes independently of the code and often lives in
  another repository. Re-running when the docs move, without re-downloading a
  checkout, is the useful unit.
* **Failure visibility.** Inside detect, a failed document fetch leaves detect
  succeeding with the labels quietly absent. As its own step it carries its own
  reader state — and for the **33 of 46 gate-approved repos with no architecture
  document at all**, "no document located" becomes an explicit, readable answer
  rather than an invisible non-event.

**A lens, never an oracle.** It adds no component, removes none, and assigns no
type. See `github/architecture_doc.py` for why, and for the measured scope: 6 of
15 repos get any match, in-repo documents work (3 of 4) and sibling-repo ones
mostly do not (3 of 9) — which inverted the argument that motivated building it.
"""
from __future__ import annotations

import logging

from resource_explorer.github import architecture_doc as ad
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.result_status import dependency_not_satisfied
from resource_explorer.surveyors.survey_report import (
    Annotation,
    ClassificationAnnotation,
)

log = logging.getLogger(__name__)

#: The kind whose components this labels.
SOURCE_KIND = "architecture_recovery"

#: The kind this WRITES into — deliberately its own, not `SOURCE_KIND`.
#:
#: The first version wrote labels back into `architecture_recovery` on the
#: reasoning that a label belongs beside the component it describes. That is a
#: good instinct and it is wrong here, because of how the store answers a read:
#: `upsert_finding` appends, but `query_findings` returns only the rows at
#: `MAX(surveyed_at)` for a (slug, kind, scope). Writing a label with a NEWER
#: timestamp therefore made that scope's `component` finding **invisible** —
#: measured immediately, Milvus's candidate count fell 218 -> 203, exactly the
#: 15 scopes the lens had labelled, and `client/index` returned `documented_by`
#: and nothing else. The rows were never lost; they stopped being readable.
#:
#: A step that annotates another step's output must therefore write under its
#: own kind, scope-keyed, so annotating can never shadow what it annotates.
#: Same shape as ports living in `architecture_interfaces`.
LENS_KIND = "architecture_doc_lens"

#: Guards this step can produce (0462 `producedGuards`). The lens genuinely has
#: two outcomes worth routing on, which is the first non-hypothetical case for
#: guard-based branching in this chain. Declared so a coordinator knows a guard
#: is expected; nothing routes on them yet, by the 2026-08-21 deferral.
GUARD_CONSULTED = "document-consulted"
GUARD_NO_DOCUMENT = "no-document"
PRODUCED_GUARDS = (GUARD_CONSULTED, GUARD_NO_DOCUMENT)


class ArchLensSurveyor(BaseSurveyor):
    """Resolve the architecture document and label components it names."""

    requires_resources: dict = {}

    def __init__(self, project, registry, surveyed_at: str = "") -> None:
        super().__init__(project, registry)
        self._surveyed_at = surveyed_at

    @property
    def step_name(self) -> str:
        return "ArchLensSurveyor"

    def _owner_repo(self) -> str:
        url = (getattr(self.project, "github_url", "") or "").rstrip("/")
        url = url.removesuffix(".git")
        parts = url.split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 else ""

    def run(self) -> list[Annotation]:
        slug = self.project.slug
        owner_repo = self._owner_repo()
        if not owner_repo:
            return [self._nothing(
                "no GitHub URL for this resource, so no document to resolve",
                guard=GUARD_NO_DOCUMENT)]

        try:
            scopes = self.registry.query_finding_scopes(slug, SOURCE_KIND) or []
        except Exception:
            log.exception("%s: could not read %s scopes", slug, SOURCE_KIND)
            return [self._nothing(
                f"{SOURCE_KIND} findings could not be read",
                guard=GUARD_NO_DOCUMENT)]

        if not scopes:
            # Nothing to label. Distinct from "no document": the document may
            # exist and be perfectly good, and the missing half is ours.
            return [self._nothing(
                f"no {SOURCE_KIND} components to label — the lens ran, the step "
                f"it annotates has not", guard=GUARD_NO_DOCUMENT)]

        components = [_ScopedComponent(s) for s in scopes]
        lens = ad.apply(owner_repo, components)

        if not lens.consulted:
            reason = lens.notes[0] if lens.notes else "document not consulted"
            return [self._nothing(reason, guard=GUARD_NO_DOCUMENT,
                                  outcome=lens.outcome, evidence=lens.evidence)]

        self._persist(slug, components, lens)

        return [ClassificationAnnotation(
            summary=(f"{len(lens.documented)} of {len(components)} component(s) named "
                     f"by the architecture document ({lens.outcome})"),
            analysis_step=self.step_name,
            confidence=90,
            explanation=(
                f"Read from {lens.evidence} (last change {lens.date or 'unknown'}). "
                f"A LENS, not an oracle: no component was added, removed or "
                f"retyped. Terms the document uses that nothing proposed are "
                f"recorded as disagreements, not adopted."
            ),
            candidate_classifications=sorted(lens.documented),
            json_properties={
                "doc_outcome": lens.outcome,
                "doc_evidence": lens.evidence,
                "doc_date": lens.date,
                "terms_extracted": len(lens.terms),
                "documented": lens.documented,
                "undetected_count": len(lens.undetected),
                # Deliberately a COUNT, not the list: on Milvus this is 506
                # section headings from 25 design documents, not component
                # names. Publishing it as findings would dress prose as a gap.
                "undetected_note": (
                    "terms the document emphasises that nothing proposed — only "
                    "meaningful when the located artifact is an architecture "
                    "overview rather than a corpus of design documents"),
                "notes": lens.notes,
                "produced_guard": GUARD_CONSULTED,
            },
        )]

    def _persist(self, slug: str, components: list, lens) -> None:
        """One finding per documented component, on that component's own scope.

        Written under `LENS_KIND`, scope-keyed — see that constant for why
        writing into `SOURCE_KIND` silently hid the components being labelled.
        """
        by_slug = {c.slug: c for c in components}
        for comp_slug, term in lens.documented.items():
            comp = by_slug.get(comp_slug)
            if comp is None:
                continue
            try:
                self.registry.upsert_finding(
                    slug, LENS_KIND,
                    [{
                        "check_name": "documented_by",
                        "label": lens.outcome,
                        "summary": f"named '{term}' in the architecture document",
                        "confidence": 90,
                        "detail": {"term": term, "evidence": lens.evidence,
                                   "date": lens.date, "kind": "doc-lens"},
                    }],
                    surveyed_at=self._surveyed_at, scope_locator=comp.scope,
                )
            except Exception:
                log.exception("%s: could not persist doc label for %s", slug, comp_slug)

    def _nothing(self, reason: str, *, guard: str, outcome: str = "",
                 evidence: str = "") -> Annotation:
        return ClassificationAnnotation(
            summary=f"Architecture document not consulted — {reason}",
            analysis_step=self.step_name,
            confidence=100,
            explanation=reason,
            json_properties={
                "doc_outcome": outcome, "doc_evidence": evidence,
                "produced_guard": guard,
                "result_status": dependency_not_satisfied(reason,
                                                          depends_on=SOURCE_KIND),
            },
        )


class _ScopedComponent:
    """The minimum a lens needs: something with `slug`/`name`, remembering the
    scope it came from so a label can be written back to the right place."""

    __slots__ = ("scope", "slug", "name")

    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.slug = scope.split("::")[-1].split("/")[-1]
        self.name = self.slug
