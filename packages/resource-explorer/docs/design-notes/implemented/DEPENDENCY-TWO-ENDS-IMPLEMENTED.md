# Dependency two ends — implemented (2026-10-08)

Built from `DESIGN-DEPENDENCY-ROW-TWO-ENDS.md` on `re/dependency-two-ends` (stacked on node admission).
A dependency row has two ends and a kind: dependent, relation, typed target, kind, evidence, state. Runtime
and data rows are read from the recovery IR's wires, so the table and the blueprint diagram share one record
(`dependency_table.py`; `mermaid.render(edge_ports=...)`). A confirmed row publishes one
`ResourceMeasureAnnotation` whose qualifiedName is built from the dependent (name and locator), the relation
and the target, never a GUID. The table header states what it does not read.

## Departures from the design note (accepted by the architect)

| | Departure | Reason | Follow-up |
|---|---|---|---|
| a | The annotation attaches to the repository's survey report, with the dependent named inside it (locator, plus the component's GUID once accepted). | There is no general annotation-on-element path yet. The locator is in the qualifiedName so a re-homing is a move, not a rewrite. | Attach to the accepted SolutionComponent's asset once Enrichment-publishing P1 gives that path; a migration re-homes rows by dependent GUID. |
| b | Wires are derived as a `drawn` class only; nothing is written to Egeria. | The materialiser deferred `SolutionLinkingWire` because wires are multi-link and not idempotent. | Write wires with the idempotency key (two ends plus relation as qualifiedName); the same problem the materialiser deferred. |
| c | Evidence is file-only for manifest rows and referenced-only rows. | The stored rows name the file, not the line; no line is invented. | Record the line in the dependency surveyor and the admission finding. |
| d | No reads/writes, endpoint, host:port or module-to-module rows. | Nothing in a compose file says read or write; wire findings carry service names only; stored build rows have no inter-module marker. | After P1: module-to-module `requires` from Gradle project dependencies (derivable). |
| e | `not established` is used only for an ambiguous name (several nodes) or a referenced-only service naming no image. | A name RE does not know is still a real, typed service named in the artifact; calling it unestablished would hide proposable rows. | Revisit when targets can be typed more strictly. |

## Known gaps

- The Environment Deployment Blueprint route returns `wires` (the rows whose two ends are both referenced-only
  services) but no UI draws them yet.
- `build_table` reads the architecture recovery results once more than before; the cost is unmeasured.
