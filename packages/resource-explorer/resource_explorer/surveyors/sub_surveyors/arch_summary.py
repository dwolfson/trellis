"""Sub-surveyor: Architecture Summary — a summarising microflow.

Step key `repo_arch_summary`. **The first step in RE whose input is another
step's output rather than an external resource**, which is why its docstring is
mostly about the model rather than about summarising.

**Why it exists.** Nothing owned summarising up. Every microflow emitted at its
own natural granularity and no step collapsed it to the depth the question
asked for — Milvus yields 154 components after distillation where its own
authors say eight ("five core components and three third-party dependencies"),
and 296 rpcs where the number a reader wants for runtime suitability is
`proxy.proto`'s 18. That is not only a precision failure; it is a missing
summarisation level. A coarse answer often requires a *deeper* analysis that is
then summarised — "REST, ~40 operations, Python and Go bindings" means opening
the document and reporting three facts instead of forty signatures.

**Why it needed no new mechanism, and the mistake that nearly added one.** The
first proposal invented a `requires_results` declaration to sit beside
`requires_resources`, on the claim that nothing declares a data dependency
between steps. That claim is false. Egeria's `0462-Governance-Action-Processes`
gives `GovernanceActionExecutor` `requestParameters`, `requestParameterFilter`,
`requestParameterMap`, `actionTargetFilter` and `actionTargetMap`, and a
completing governance service *"optionally supplies one or more guards and a
list of action targets for the subsequent governance action(s) to process"*.
Step-to-step flow is modelled, **named**, **filterable** and **rebindable**.

So this is an ordinary step whose **action targets are the findings of a prior
step**. `requires_resources` is deliberately empty: it shares no expensive
external resource, needs no zipball and no clone, and is therefore Discovery
tier by rule 17's own test. That is the whole point — a summary should be cheap
enough to recompute whenever its inputs change.

**Depth is a request parameter, not a new concept.** `DEPTH_SUITABILITY` is the
coarse reading this class implements — enough to answer "could we use this?".
Finer depths are where investigation-framing's Purpose selects a summarisation
level rather than only ordering questions (§3 of that design).

**An absent input is not an empty summary.** If the prior step has produced
nothing, this emits `not_established` with the reason rather than a confident
summary of zero components. A summary of nothing looks exactly like a real
answer, which makes the absence-looks-like-zero failure *harder* to see here
than anywhere else it has appeared in this codebase.
"""
from __future__ import annotations

import json
import logging
from collections import Counter

from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.step_outcome import StepOutcome
from resource_explorer.surveyors.result_status import dependency_not_satisfied
from resource_explorer.surveyors.survey_report import Annotation, ResourceMeasureAnnotation

log = logging.getLogger(__name__)

#: The analysis kind this step's action targets come from. Named here rather
#: than passed, until the executor reads `actionTargetMap` from the process
#: graph — at which point this becomes the default, not the only source.
SOURCE_KIND = "architecture_recovery"

#: Where this step's own output lands. It had none until 2026-08-25: the
#: summariser computed a summary, returned it as an annotation, and **persisted
#: nothing**, so nothing could read it back, no results view was possible, and
#: every run recomputed from scratch. Found by the presentation session auditing
#: the end-to-end story, not by me — and it is finding 89's shape ("the
#: capability existed and nothing wired it to storage") in code written the same
#: day as the finding that names it.
KIND = "architecture_summary"

#: Ports and wires persist under their OWN kind, whole-resource scoped — not
#: alongside the component findings. Discovered while wiring this step up: the
#: summary reported no protocols at all while `interfaces.propose()` was
#: returning 31 ports for Milvus, because it was reading only SOURCE_KIND.
#: A summarising step consuming one kind when its subject spans two is the
#: composition-level version of the same mistake, and the symptom — "serves
#: nothing" — is indistinguishable from a component with no interface.
INTERFACE_KIND = "architecture_interfaces"

#: Depths this summariser can produce. Only the first is implemented; the rest
#: are named so their absence reads as scope rather than oversight.
DEPTH_SUITABILITY = "suitability"    # "could we use this?"
DEPTH_INTEGRATION = "integration"    # "how would we call it?"

#: `full` was declared here and is deliberately **gone**, not implemented.
#:
#: It was described as "every component and operation — the raw analysis", and
#: that is precisely the problem: a summariser whose deepest level is *do not
#: summarise* is describing the architecture-recovery results view, which
#: already exists and is already reachable. Implementing it would have produced
#: a second path to the same rows, and a reader choosing between them would be
#: choosing between two spellings of one answer.
#:
#: Recorded rather than quietly dropped, because the reasoning is the reusable
#: part: **a depth is a summarisation level, and "none" is not one.** For the
#: raw component list, read `architecture_recovery`.
DEPTHS = (DEPTH_SUITABILITY, DEPTH_INTEGRATION)

#: What `integration` still cannot say without a stage-two read, named so its
#: absence is a scoped decision rather than an oversight. Operation NAMES and
#: request/response shapes are deliberately not extracted (finding 100: a count
#: is a summary, a listing is not), so "how do we call it" is answered down to
#: *what it serves, how much of it, and what it depends on* — not down to a
#: signature. That last step needs the documents opened again at a different
#: cost tier, and the driving question explicitly excluded it.
INTEGRATION_NOT_ANSWERED = (
    "operation names and signatures", "request/response schemas",
    "authentication requirements", "client library versions",
)

#: `SolutionComponentType` values that mean "something that runs" — the ones a
#: suitability answer is actually about. `Software Library` is excluded on
#: purpose: it is by far the most-proposed type (163 of 218 on Milvus) and it is
#: the least informative about whether a system can be used at runtime.
_RUNNABLE_TYPES = frozenset({"Software Service", "Long Running Daemon", "Console Command"})

#: Not ours. Counting these separately answers "how much of this repo is
#: somebody else's", which is a suitability question in its own right.
_THIRD_PARTY_TYPES = frozenset({"Third Party Process"})


class ArchSummarySurveyor(BaseSurveyor):
    """Collapse architecture-recovery findings to the depth the question asked."""

    requires_resources: dict = {}

    def __init__(self, project, registry, surveyed_at: str = "",
                 depth: str = DEPTH_SUITABILITY) -> None:
        super().__init__(project, registry)
        self._surveyed_at = surveyed_at
        self._depth = depth if depth in DEPTHS else DEPTH_SUITABILITY

    @property
    def step_name(self) -> str:
        return "ArchSummarySurveyor"

    def run(self) -> list[Annotation]:
        slug = self.project.slug
        try:
            scopes = self.registry.query_finding_scopes(slug, SOURCE_KIND) or []
        except Exception:
            log.exception("%s: could not read %s findings", slug, SOURCE_KIND)
            scopes = None

        if scopes is None:
            return [self._nothing_to_summarise(
                "architecture-recovery findings could not be read")]
        if not scopes:
            # NOT an empty summary. The distinction is the whole reason this
            # branch is separate: "recovery has not run here" and "recovery ran
            # and found one component" are different statements about the repo,
            # and a summary saying "0 components" would collapse them.
            return [self._nothing_to_summarise(
                f"no {SOURCE_KIND} findings for this resource — the summarising "
                f"step ran, its input step has not")]

        types, protocols, operations, third_party = Counter(), Counter(), 0, 0
        # Components the architecture document names (repo_arch_lens, finding
        # 102). Counted, never used to FILTER: the undocumented ones are still
        # recovered evidence, and dropping them would turn a lens into an
        # oracle in the one place a reader would not see it happen.
        documented = 0
        # `integration` needs to know WHICH component serves WHAT, not just how
        # many ports exist — the difference between "there are 10 gRPC ports"
        # and "proxy serves gRPC".
        serving: dict = {}
        wire_targets: list = []
        # Every partial read is counted, because a summary that quietly lost
        # half its input still reads as a confident answer. `unread_scopes` and
        # `interfaces_unread` go into the annotation so a reader can tell a
        # complete summary from a degraded one.
        unread_scopes, interfaces_unread = 0, False
        for scope in scopes:
            try:
                findings = self.registry.query_findings(slug, SOURCE_KIND, scope) or []
            except Exception:
                log.exception("%s: could not read scope %r", slug, scope)
                unread_scopes += 1
                continue
            for f in findings:
                check = (f.get("check_name") or "")
                label = (f.get("label") or "")
                # On a `component` finding the LABEL is the solutionComponentType.
                # The separate `solutionComponentType = X` rows are evidence, and
                # the first version of this counted those instead — which reported
                # proposers ("go-subsystem", "code marker") as if they were types.
                if check == "component":
                    types[label or "Unclassified"] += 1
                    if label in _THIRD_PARTY_TYPES:
                        third_party += 1
                elif check.startswith("wire:"):
                    target = check.split(":", 1)[1]
                    if target:
                        wire_targets.append(target)
                elif check.startswith("port:"):
                    # A port finding's LABEL is its direction; the protocol and
                    # the operation count live in `detail`. Reading `label` here
                    # would have reported "Input-Output" as a protocol.
                    detail = f.get("detail_json") or f.get("detail")
                    if isinstance(detail, str):
                        try:
                            detail = json.loads(detail)
                        except Exception:
                            detail = {}
                    detail = detail if isinstance(detail, dict) else {}
                    proto = detail.get("protocol") or ""
                    if proto:
                        protocols[proto] += 1
                        if detail.get("direction") == "Input-Output":
                            serving.setdefault(proto, set()).add(
                                detail.get("component") or scope)
                    try:
                        operations += int(
                            (detail.get("additionalProperties") or {}).get("operationCount", 0))
                    except (TypeError, ValueError):
                        pass

        # Doc-lens labels live under their own kind, scope-keyed, so that
        # annotating a component can never hide it — see arch_lens.LENS_KIND.
        try:
            from resource_explorer.surveyors.sub_surveyors.arch_lens import LENS_KIND
            for scope in scopes:
                for f in self.registry.query_findings(slug, LENS_KIND, scope) or []:
                    if (f.get("check_name") or "") == "documented_by":
                        documented += 1
        except Exception:
            log.exception("%s: could not read doc-lens labels", slug)
            interfaces_unread = True

        # Ports live under their own kind at whole-resource scope.
        try:
            for f in self.registry.query_findings(slug, INTERFACE_KIND) or []:
                if not (f.get("check_name") or "").startswith("port:"):
                    continue
                detail = f.get("detail_json") or f.get("detail")
                if isinstance(detail, str):
                    try:
                        detail = json.loads(detail)
                    except Exception:
                        detail = {}
                detail = detail if isinstance(detail, dict) else {}
                proto = detail.get("protocol") or ""
                if proto:
                    protocols[proto] += 1
                    if detail.get("direction") == "Input-Output":
                        # The PORT name, not the owning component. An IDL port is
                        # named for the interface it defines (`proxy.proto`), and
                        # the component that owns it is whatever subtree the file
                        # sits in — `pkg` on Milvus, which tells a caller
                        # nothing. What you call is the interface.
                        serving.setdefault(proto, set()).add(
                            detail.get("port") or detail.get("component") or "")
                if (f.get("check_name") or "").startswith("wire:"):
                    wire_targets.append((f.get("check_name") or "").split(":", 1)[1])
                try:
                    operations += int(
                        (detail.get("additionalProperties") or {}).get("operationCount", 0))
                except (TypeError, ValueError):
                    pass
        except Exception:
            log.exception("%s: could not read %s findings", slug, INTERFACE_KIND)
            interfaces_unread = True

        if self._depth == DEPTH_INTEGRATION:
            summary = self._render_integration(serving, wire_targets, operations)
        else:
            summary = self._render(types, protocols, operations, third_party,
                                   documented)
        props = {
            "depth": self._depth,
            "source_kind": SOURCE_KIND,
            "component_scopes": len(scopes),
            "components": sum(types.values()),
            "component_types": dict(types),
            "third_party": third_party,
            "documented": documented,
            "protocols": dict(protocols),
            "operations": operations,
            "unread_scopes": unread_scopes,
            "interfaces_unread": interfaces_unread,
            "complete": unread_scopes == 0 and not interfaces_unread,
        }
        self._persist(slug, summary, props)
        if unread_scopes or interfaces_unread:
            missing = []
            if unread_scopes:
                missing.append(f"{unread_scopes} component scope(s)")
            if interfaces_unread:
                missing.append("the interface findings")
            summary += f" — INCOMPLETE, could not read {' and '.join(missing)}"
        return [ResourceMeasureAnnotation(
            summary=summary,
            analysis_step=self.step_name,
            explanation=(
                f"Summarised from {len(scopes)} {SOURCE_KIND} component scope(s) at "
                f"depth '{self._depth}'. A count, not a listing — the underlying "
                f"per-component findings are unchanged and remain the detail view."
            ),
            json_properties={
                "depth": self._depth,
                "source_kind": SOURCE_KIND,
                "component_scopes": len(scopes),
                "components": sum(types.values()),
                "component_types": dict(types),
                "third_party": third_party,
                "documented": documented,
                "protocols": dict(protocols),
                "operations": operations,
                # Observable degradation, not a silent partial result.
                "unread_scopes": unread_scopes,
                "interfaces_unread": interfaces_unread,
                # And now labelled: this step already tracked its own
                # incompleteness and said so in the summary ("INCOMPLETE, could
                # not read ..."). `partial` is the word for exactly that —
                # produced something, knowingly incomplete — so the label now
                # agrees with the prose instead of leaving a reader to notice.
                **(StepOutcome("partial",
                               cause="some component scopes or interface findings "
                                     "could not be read",
                               detail={"unread_scopes": unread_scopes,
                                       "interfaces_unread": interfaces_unread})
                   if (unread_scopes or interfaces_unread) else
                   StepOutcome("recovered",
                               detail={"components": sum(types.values())})).as_row(),
                "complete": unread_scopes == 0 and not interfaces_unread,
            },
        )]

    def _persist(self, slug: str, summary: str, props: dict) -> None:
        """Write the summary where something can read it back.

        Whole-resource scope: a summary is by definition about the resource, not
        about one component — and writing it under a component's scope would
        shadow that component's own findings, which is the trap finding 103
        records.
        """
        try:
            self.registry.upsert_finding(
                slug, KIND,
                [{
                    "check_name": "architecture_summary",
                    "label": self._depth,
                    "summary": summary,
                    "confidence": 90,
                    "detail": props,
                }],
                surveyed_at=self._surveyed_at,
            )
        except Exception:
            log.exception("%s: could not persist the architecture summary", slug)
        try:
            self.registry.upsert_metric(
                slug, KIND,
                {"components": float(props.get("components", 0)),
                 "documented": float(props.get("documented", 0)),
                 "third_party": float(props.get("third_party", 0)),
                 "operations": float(props.get("operations", 0))},
                surveyed_at=self._surveyed_at,
            )
        except Exception:
            log.exception("%s: could not persist architecture summary metrics", slug)

    def _render_integration(self, serving: dict, wires: list, operations: int) -> str:
        """"How would we call it?" — from data already persisted.

        My own earlier note said this depth needed stage-two interface reads.
        That was only true of operation *names*: which components serve an
        interface, over what protocol, how many operations, and what they call
        out to are all in `architecture_interfaces` already. The correction
        matters because it is the difference between a depth that is unbuildable
        and one that is a different reading of what we hold — which is the whole
        premise of depth as a summarisation level.
        """
        if not serving:
            return ("Nothing here serves an interface we can see — no port with a "
                    "protocol was recovered, so there is no call surface to describe")
        parts = []
        for proto, ifaces in sorted(serving.items(), key=lambda kv: -len(kv[1])):
            named = ", ".join(sorted(ifaces)[:3])
            more = f" (+{len(ifaces) - 3} more)" if len(ifaces) > 3 else ""
            parts.append(f"{proto}: {named}{more}")
        line = "; ".join(parts)
        if operations:
            line += f"; {operations} operation(s) across them"
        if wires:
            targets = sorted({w for w in wires})[:4]
            line += f"; calls out to {', '.join(targets)}"
        # The honest caveat, and it is the point of finding 101 restated where a
        # reader meets it. Milvus declares 297 rpcs across ten .proto files;
        # `proxy` is the client-facing one and the coord services are internal,
        # and NOTHING IN THE CODE SAYS SO. Reporting the largest surface would
        # name `root_coord` (76 rpcs) over `proxy` (18) and be exactly backwards.
        if len(serving) or operations:
            line += (" — public and internal interfaces are not distinguished; "
                     "the project's own documentation is what separates them")
        return line

    def _render(self, types: Counter, protocols: Counter,
                operations: int, third_party: int, documented: int = 0) -> str:
        """One line a person can act on at `suitability` depth.

        **Deliberately does not lead with the component count.** "204
        components" is the raw analysis restated, which is summarising nothing —
        and it is the number that made this step necessary. What "could we use
        this?" actually turns on is: what does it serve, how big is that
        surface, and how much of what is here is somebody else's.

        The count is still reported, last and qualified, because dropping it
        entirely would hide the disagreement between 204 and the eight Milvus's
        authors describe — and that disagreement is a finding, not noise.
        """
        if not types:
            return "Architecture recovered, but no component findings to summarise"

        parts = []
        if protocols:
            iface = ", ".join(f"{p}" for p, _ in protocols.most_common(3) if p)
            if iface:
                parts.append(f"serves {iface}"
                             + (f" ({operations} operations)" if operations else ""))
        # Documented components lead when they exist: the project's own authors
        # naming a component is stronger evidence than any type we derived, and
        # on Milvus it is 15 against 206 candidates. It never REPLACES the
        # candidate count below — a lens that silently shrank the answer would
        # be indistinguishable from a detector that missed things.
        if documented:
            parts.append(f"{documented} documented component(s)")
        runnable = sum(n for t, n in types.items() if t in _RUNNABLE_TYPES)
        if runnable:
            parts.append(f"{runnable} runnable unit(s)")
        if third_party:
            parts.append(f"{third_party} third-party")
        parts.append(f"from {sum(types.values())} candidate component(s)")
        return "; ".join(parts)

    def _nothing_to_summarise(self, reason: str) -> Annotation:
        return ResourceMeasureAnnotation(
            summary=f"No architecture summary — {reason}",
            analysis_step=self.step_name,
            explanation=reason,
            json_properties={"depth": self._depth, "source_kind": SOURCE_KIND,
                             "result_status": dependency_not_satisfied(reason, depends_on=SOURCE_KIND),
                             # Both vocabularies, and they say different things:
                             # the READER is told a dependency has not run, the
                             # RUN reports it could establish nothing. A summary
                             # of nothing is never a provable zero — the absence
                             # is upstream, not in the repo.
                             **StepOutcome("unverified",
                                           cause=f"{SOURCE_KIND} has not run").as_row()},
        )
