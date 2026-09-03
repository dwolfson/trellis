"""Phase A.5 of docs/blueprint-materialization-plan.md — live measurement,
not assumption: does a second, identical `link_solution_linking_wire()` call
between the same two SolutionComponents create a duplicate relationship, or
upsert onto the existing one?

pyegeria's own docstring for SolutionLinkingWire says "allows more than one
wire between the same pair of components" (multi-link) — this script
confirms it empirically rather than trusting the docstring, following this
codebase's own established discipline (docs/reference_egeria_dedup_and_link_patterns
memory: "if attach returns an identifier it is multi-link; if it returns
nothing it is uni-link" — measured directly for ResourceList/CollectionMembership
on 2026-08-25; SolutionLinkingWire was never measured).

One-off, throwaway: creates two disposable SolutionComponents, links them
twice, reads back, deletes both components (which removes their
relationships too — NOT a by-ends detach, which the same reference note
warns removes every matching relationship for a multi-link type, silently
destroying the evidence this script exists to capture).

Coordinated with all 8 live peer sessions before running (2026-09-03) —
see the session transcript. Confirmed before running: the platform is
healthy and settled (not mid-restart), and the earlier republish batch's
outbox is fully drained (0 'running' rows) so this write cannot collide
with it.

Run once, capture output to a file, inspect the file — never pipe this
invocation into grep/tail/wc (a non-idempotent write inside a pipeline
runs again for each stage that reads it, per this session's own
coordinate-shared-writes convention).
"""
from __future__ import annotations

import sys
import time

from pyegeria.omvs.solution_architect import SolutionArchitect

PLATFORM_URL = "https://localhost:9443"
VIEW_SERVER = "qs-view-server"
USER = "erinoverview"
PASSWORD = "secret"

_TAG = f"wire-multi-link-probe-{int(time.time())}"


def _component_body(name: str) -> dict:
    return {
        "class": "NewElementRequestBody",
        "isOwnAnchor": True,
        "properties": {
            "class": "SolutionComponentProperties",
            "qualifiedName": f"SolutionComponent::probe::{_TAG}::{name}",
            "displayName": f"{_TAG}-{name}",
            "additionalProperties": {"purpose": "throwaway-probe, safe to delete"},
        },
    }


def main() -> int:
    print(f"[probe] tag = {_TAG}")
    sa = SolutionArchitect(VIEW_SERVER, PLATFORM_URL, USER, PASSWORD)
    sa.create_egeria_bearer_token(USER, PASSWORD)

    comp_a_guid = comp_b_guid = None
    try:
        print("[probe] creating component A...")
        comp_a_guid = sa.create_solution_component(_component_body("A"))
        print(f"[probe] component A guid = {comp_a_guid}")

        print("[probe] creating component B...")
        comp_b_guid = sa.create_solution_component(_component_body("B"))
        print(f"[probe] component B guid = {comp_b_guid}")

        wire_body = {
            "class": "NewRelationshipRequestBody",
            "properties": {
                "class": "SolutionLinkingWireProperties",
                "label": "probe-wire",
                "description": "Phase A.5 multi-link measurement — throwaway.",
            },
        }

        print("[probe] first link_solution_linking_wire() call...")
        first_return = sa.link_solution_linking_wire(comp_a_guid, comp_b_guid, wire_body)
        print(f"[probe] first call returned: {first_return!r}")

        print("[probe] second link_solution_linking_wire() call, identical args...")
        second_return = sa.link_solution_linking_wire(comp_a_guid, comp_b_guid, wire_body)
        print(f"[probe] second call returned: {second_return!r}")

        # The definitive signal (memory note: "the return value IS the
        # test"). A None return would be uni-link (attach-as-upsert,
        # contradicting the docstring); a non-None identifier is multi-link.
        return_value_verdict = (
            "MULTI-LINK (both calls returned an identifier)"
            if first_return and second_return
            else "UNI-LINK (at least one call returned None)"
            if (first_return is None or second_return is None)
            else "INCONCLUSIVE (unexpected return shape)"
        )
        same_identifier = first_return == second_return
        print(f"[probe] return-value verdict: {return_value_verdict}")
        print(f"[probe] first_return == second_return: {same_identifier}")

        # Confirmatory read-back — counting DISTINCT RELATIONSHIP GUIDS
        # between the two components, not just "does a wire exist" (which
        # reads identically for one wire and for two — the exact query-side
        # version of the collision-key trap this session's own
        # reference-note already documents for annotation qualifiedNames).
        print("[probe] reading back component A's related elements...")
        related_a = sa.get_component_related_elements(comp_a_guid)
        print(f"[probe] raw related-elements response for A:\n{related_a!r}")

        wire_relationship_guids: set[str] = set()
        if isinstance(related_a, dict):
            for key in ("elements", "elementList", "relatedElements"):
                items = related_a.get(key)
                if isinstance(items, list):
                    for item in items:
                        rel = item.get("relationshipHeader") or item.get("relationship") or {}
                        guid = (rel.get("elementHeader") or {}).get("guid") or rel.get("guid")
                        if guid:
                            wire_relationship_guids.add(guid)
        print(f"[probe] distinct relationship GUIDs found in read-back: "
              f"{len(wire_relationship_guids)} -> {sorted(wire_relationship_guids)}")

        print()
        print("=" * 70)
        print("RESULT")
        print(f"  first call return value:  {first_return!r}")
        print(f"  second call return value: {second_return!r}")
        print(f"  same identifier both times: {same_identifier}")
        print(f"  return-value verdict: {return_value_verdict}")
        print(f"  distinct relationship GUIDs via read-back: {len(wire_relationship_guids)}")
        print("=" * 70)
        return 0

    finally:
        # Delete the COMPONENTS, not a by-ends detach — cascade_delete=True
        # so any relationships (one or two wires) go with them. This is the
        # safe cleanup path per the coordinating peers' shared warning:
        # detach_solution_linking_wire(component1_guid, component2_guid, ...)
        # removes EVERY matching relationship for a multi-link type in one
        # call, which would corrupt the evidence if done before the
        # read-back above. Cleanup only runs after read-back either way,
        # via this try/finally, even if something above raised.
        for label, guid in (("A", comp_a_guid), ("B", comp_b_guid)):
            if not guid:
                continue
            try:
                sa.delete_solution_component(guid, cascade_delete=True)
                print(f"[probe] deleted throwaway component {label} ({guid})")
            except Exception as exc:
                print(f"[probe] WARNING: failed to delete component {label} ({guid}): {exc}",
                      file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
