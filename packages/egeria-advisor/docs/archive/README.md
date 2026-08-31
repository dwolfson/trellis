# Archived documents

Kept, not deleted. Each of these described work that finished, or a road not taken — the code
is now the truth, and these record how it was reasoned about at the time.

Same convention as `packages/resource-explorer/docs/archive/`, and the same test.

## The test

**"Nothing points at it"**, not "the work is done." A design doc whose decisions are still cited
by source comments is load-bearing documentation whatever its status line says. Reference count
is the measurement that tells them apart, and every file here was checked that way first.

**Unreferenced is necessary but not sufficient.** Measured 2026-08-30: 24 of `docs/design/`'s 49
files had zero inbound references, and eight of those described *live behaviour* — ONNX
embeddings, incremental indexing, scoped and exhaustive queries, metadata filtering. Those are
under-linked documentation, not dead documentation, and archiving them would have buried the
only written explanation of code that runs. They stayed in `docs/design/` and are now indexed
from the package README. Only docs describing something finished or abandoned moved here.

## What is here (2026-08-30)

**Completion and status reports (9).** `FINAL_IMPLEMENTATION_SUMMARY`,
`IMPLEMENTATION_COMPLETE_SUMMARY`, `PHASE2_COLLECTION_PARAMETERS_IMPLEMENTATION`,
`PHASE3_COMPLETION_REPORT`, `INTERACTIVE_ROUTING_IMPLEMENTATION_STATUS`,
`DASHBOARD_INTEGRATION_STATUS`, `DASHBOARD_UPDATES_SUMMARY`, `PYEGERIA_AGENT_IMPLEMENTATION`,
`GPU_DETECTION_ENHANCEMENT`. Snapshots of a moment, mostly dated March 2026. The features they
report on are live; how they were built is what these preserve.

**Plans that have been executed (2).** `implementation-roadmap` — the original build plan for
the whole advisor — and `IMPLEMENTATION_ORDER`, its sequencing. Both are history now.

**Designs for work never built (3).** `AIRFLOW_INTEGRATION_DESIGN` and `AIRFLOW_V3_OPENLINEAGE`
describe automating maintenance with Airflow DAGs; there is no Airflow dependency and no Airflow
code anywhere in the package. `DYNAMIC_SCHEMA_DISCOVERY_DESIGN` has no corresponding
implementation either. Roads not taken, kept because the reasoning may be wanted if the question
returns.

**A decision record (1).** `BEEAI_ARCHITECTURE_EVALUATION` — the evaluation that led to adopting
the BeeAI framework, which the package still uses. The decision is now embedded in the code; the
argument for it is here.

**A superseded strategy (1).** `MODEL_SELECTION_STRATEGY` says "`llama3.1:8b` for everything",
which stopped being true when the Literate Governance planner moved to `qwen2.5-coder:32b`. This
one was archived for being *wrong* rather than merely unreferenced — a stale document that reads
as current is worse than one nobody links.

**A one-off fix note (1).** `VSCODE_FILE_WATCHING_FIX` — an editor configuration workaround, not
a property of this software.

## What is deliberately NOT here

The eight unreferenced docs describing live behaviour, listed under "The test" above. If you are
looking for how scoped queries, exhaustive queries, incremental indexing, metadata filtering or
the ONNX embedding path work, they are still in `docs/design/` and linked from the package
README — being unreferenced was the bug, and linking them was the fix.
