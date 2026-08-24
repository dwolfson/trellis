"""Distillation — the deterministic half of §5.2, ported from `scripts/arch-spike/distill.py`.

The detector's job is recall: propose every candidate that any signal supports.
Measured on the corpus 2026-08-24, that means **202 candidates for Milvus against
a published ground truth of 8** ("five core components and three third-party
dependencies", the Milvus authors' own words) and 311 for `genaicomps`. Recall is
essentially solved; precision is the standing problem, and persisting 25:1
over-proposal is noise at scale rather than coverage.

Each filter is a **claim about what a component is**, not a tuning knob, so it
can be argued with and regression-tested. The spike measured them separately on
a pre-registered corpus (README findings 76-80): Kubernetes 3303 -> 358 while
holding 6/6 ground truth, Milvus 238 at 3/5.

**Nothing is deleted silently.** `distill()` returns what it dropped and why,
and the caller records the counts — an unexplained drop from 202 to 12 is
indistinguishable from a broken detector, which is the failure this codebase
keeps meeting.

**One thing changed in the port, and it is not cosmetic.** The spike ran against
one perspective's candidates at a time; this runs inside a product path that
carries all four perspectives at once (design §4.1). Refinement is therefore
computed **per perspective**. A deployment-perspective candidate must never
suppress a physical-perspective one as its "refinement": §4.2 is explicit that a
Dockerfile-directory component and the compose service it builds are two
readings of one system related by `ImplementedBy`, not a parent and a child.
Distilling across perspectives would silently enforce "merge" where the design
says "map, never merge" — and it would look like a precision win.
"""
from __future__ import annotations

from collections import defaultdict

from .ir import Component

# Directory names that are never a component of the system in their own right.
# A component may CONTAIN tests or docs — Prometheus's `config/` owns
# `config/testdata/` and the ground truth says so — but a candidate whose files
# are *entirely* test or documentation material is describing the project's
# support material, not its architecture.
SUPPORT_SEGMENTS = frozenset({
    "test", "tests", "testdata", "test_data", "fixtures", "e2e",
    "docs", "doc", "documentation", "examples", "example", "samples",
    "hack", "scripts", "tools", "vendor", "third_party", "mocks",
})

DROP_SUPPORT_ONLY = "support-only"
DROP_WHOLE_REPO = "whole-repo-claim"
DROP_REFINEMENT = "refinement-of-classified-parent"


def _roots(comp: Component) -> list[str]:
    return [g.rstrip("/*").rstrip("/") for g in (comp.files or []) if g]


def _is_support_only(comp: Component) -> bool:
    """Every declared root sits under a support directory."""
    roots = _roots(comp)
    if not roots:
        return False
    return all(any(seg in SUPPORT_SEGMENTS for seg in r.split("/")) for r in roots)


def _claims_whole_repo(comp: Component) -> bool:
    """A candidate whose roots include the checkout root claims everything.

    The coupling proposer emits one of these on every target. It is the same
    thing the npm detector calls a workspace root and `go_subsystems` calls a
    module root: **a container, not a component.** Removing it before anything
    else matters because a whole-repo claim makes every real component look
    like its refinement — measured on Kubernetes, where that alone collapsed
    3303 candidates to 4 and took the entire ground truth with it.
    """
    return any(r in ("", ".") for r in _roots(comp))


def _is_refinement(comp: Component, parent_roots: set[str]) -> bool:
    """Every root of this candidate lies strictly inside a CLASSIFIED parent.

    §2a says a refinement is legitimate, not wrong, and the union rule credits a
    set of children covering a parent. But when the parent is also present the
    children add nothing, and they are what turns 6 components into 3270.

    `parent_roots` deliberately contains only candidates that carry a type. An
    untyped blob is not a parent worth deferring to: `pkg` (proposed by
    coupling, type `?`) swallowed `pkg/scheduler`, which is half of Kubernetes'
    `kube-scheduler`. Deferring to a parent claims the parent is the better
    answer, and that is only true when something actually classified it.
    """
    roots = _roots(comp)
    if not roots:
        return False
    for r in roots:
        parts = r.split("/")
        if not any("/".join(parts[:i]) in parent_roots for i in range(1, len(parts))):
            return False
    return True


def distill(
    components: list[Component],
    *,
    drop_support: bool = True,
    drop_refinements: bool = True,
) -> tuple[list[Component], list[tuple[Component, str]], dict]:
    """Return `(kept, dropped, stats)`.

    `dropped` pairs each removed candidate with the rule that removed it, so a
    caller can report *what* was dropped rather than only how many. Order within
    `kept` is preserved.

    MEASURED ALTERNATIVE, REJECTED: sparing refinements that carry a type ("a
    classified child is a component in its own right") sounds obviously right and
    is strictly worse on every axis — Kubernetes 358 candidates at 6/6 became 762
    at 5/6, Milvus 238 became 276 at the same 3/5, and Prometheus did not recover
    the component it was meant to save. Recorded rather than silently reverted:
    the intuition is appealing enough that someone will try it again.
    """
    dropped: list[tuple[Component, str]] = []
    stats: dict = {"input": len(components)}
    kept = list(components)

    if drop_support:
        survivors = []
        for c in kept:
            (dropped.append((c, DROP_SUPPORT_ONLY)) if _is_support_only(c)
             else survivors.append(c))
        kept = survivors
    stats[f"dropped_{DROP_SUPPORT_ONLY}"] = sum(
        1 for _, r in dropped if r == DROP_SUPPORT_ONLY)

    # A whole-repo claim is a container rather than a component — but only when
    # the things it contains are ALSO proposed. Measured on `docling-parse`,
    # which yields exactly one candidate covering the whole repo: dropping it
    # left nothing at all, turning a correct single-component answer into an
    # empty result. In the spike this branch never fired that way because a
    # whole-repo claim always sat among thousands of siblings.
    #
    # So: the filter applies only if something survives it. A precision rule
    # that can empty the set is a recall bug wearing a precision rule's clothes.
    survivors, whole_repo = [], []
    for c in kept:
        (whole_repo if _claims_whole_repo(c) else survivors).append(c)
    if survivors:
        dropped.extend((c, DROP_WHOLE_REPO) for c in whole_repo)
        kept = survivors
    elif whole_repo:
        stats["whole_repo_claims_kept_as_sole_candidates"] = len(whole_repo)
    stats[f"dropped_{DROP_WHOLE_REPO}"] = sum(
        1 for _, r in dropped if r == DROP_WHOLE_REPO)

    if drop_refinements:
        # Per perspective — see the module docstring. Crossing perspectives here
        # would enforce "merge" where §4.2 says "map, never merge".
        by_perspective: dict[str, list[Component]] = defaultdict(list)
        for c in kept:
            by_perspective[c.perspective or ""].append(c)

        survivors_set: set[int] = set()
        for _persp, group in by_perspective.items():
            parent_roots = {r for c in group if c.type for r in _roots(c)}
            for c in group:
                if _is_refinement(c, parent_roots):
                    dropped.append((c, DROP_REFINEMENT))
                else:
                    survivors_set.add(id(c))
        kept = [c for c in kept if id(c) in survivors_set]
    stats[f"dropped_{DROP_REFINEMENT}"] = sum(
        1 for _, r in dropped if r == DROP_REFINEMENT)

    stats["output"] = len(kept)
    stats["by_perspective"] = {
        p: sum(1 for c in kept if (c.perspective or "") == p)
        for p in sorted({(c.perspective or "") for c in kept})
    }
    return kept, dropped, stats


def summarise(stats: dict) -> str:
    """One line for the run notes. Never a bare output count — a drop from 202
    to 12 with no reason attached reads as a broken detector."""
    parts = [f"{stats.get('input', 0)} candidates"]
    for rule in (DROP_SUPPORT_ONLY, DROP_WHOLE_REPO, DROP_REFINEMENT):
        n = stats.get(f"dropped_{rule}", 0)
        if n:
            parts.append(f"-{n} {rule}")
    parts.append(f"= {stats.get('output', 0)} kept")
    return " ".join(parts)
