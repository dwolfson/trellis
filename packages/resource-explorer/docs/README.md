# Resource Explorer documentation

60 documents, grouped by what they *are* rather than what they are about — the
distinction that matters when deciding whether one is still live.

**Generated from each document's own `**Status:**` line**, not from a
hand-maintained list, because a hand-maintained index goes stale the first time
someone adds a file. Regenerate after adding or reclassifying:

```bash
python scripts/regen_docs_index.py
```

## Open — planned or on hold

Live plans. The work is not done; the doc is the specification.

- **[consolidation-2026-08-24.md](consolidation-2026-08-24.md)** — 2026-09-03  
  DATED SNAPSHOT — 2026-08-24. Superseded; do not act on it. It planned the work ahead of a PR tha

## Design and framing

Decisions and models. Cited from source where a comment cannot restate them.

- **[a2a.md](a2a.md)** — 2026-10-14  
  live. The A2A server surface (one service, routed by path)
- **[admin-guide.md](admin-guide.md)** — 2026-10-14  
  live. Operator guide; the best-maintained user-facing document
- **[architecture-recovery-extraction-design.md](architecture-recovery-extraction-design.md)** — 2026-09-03  
  design reference. Part of the architecture-recovery design — split out 2026-09-03
- **[architecture-recovery-in-practice.md](architecture-recovery-in-practice.md)** — 2026-09-02  
  reference, current as of 2026-09-02
- **[Architecture.md](Architecture.md)** — 2026-10-14  
  live. Module map, flows and key decisions; the zone passage was corrected 2026-10-14
- **[Backlog.md](Backlog.md)** — 2026-10-07  
  design question first (generalized discovery across resource kinds), then slice. Not scheduled
- **[BUILDER-BRIEF-CHECKLIST.md](BUILDER-BRIEF-CHECKLIST.md)** — 2026-10-14  
  live. Short checklist for every builder brief
- **[ddl-step-annotations.md](ddl-step-annotations.md)** — 2026-10-14  
  live. Deployment record for the step_annotations table (2026-10-13)
- **[dr-egeria-engine-host-gaps.md](dr-egeria-engine-host-gaps.md)** — 2026-10-14  
  live. Request to the egeria-python maintainers (2026-10-14); open until they respond
- **[egeria-integration.md](egeria-integration.md)** — 2026-09-03  
  consolidated design. Current as of 2026-09-02
- **[egeria-operations.md](egeria-operations.md)** — 2026-10-03  
  consolidated runbook. Current as of 2026-09-02
- **[egeria-support-for-multi-resource.md](egeria-support-for-multi-resource.md)** — 2026-10-14  
  validation and planning input, 2026-09-20. Expands §12 of
- **[egeria.md](egeria.md)** — 2026-09-02  
  hand-authored reference outline. Sparse by nature — the headings are
- **[end-to-end-gap-audit-2026-08-25.md](end-to-end-gap-audit-2026-08-25.md)** — 2026-09-02  
  DATED SNAPSHOT — 2026-08-25. Do not act on it directly. Several gaps it records have since been 
- **[extending-resource-explorer.md](extending-resource-explorer.md)** — 2026-10-14  
  live. How to add a question, analysis step, annotation type or survey type
- **[feedback-and-curation.md](feedback-and-curation.md)** — 2026-09-03  
  consolidated design. Current as of 2026-09-02
- **[filesystem-and-database-surveying.md](filesystem-and-database-surveying.md)** — 2026-09-25  
  consolidated design and reference. Current as of 2026-09-02
- **[funnel-cost-measured.md](funnel-cost-measured.md)** — 2026-10-14  
  live. Measured funnel cost (2026-09-12/13); re-derivable from the committed resolver
- **[gap-analyses-design.md](gap-analyses-design.md)** — 2026-10-14  
  live. Design for four gap analyses; code and tests cite it
- **[kroki-diagram-rendering.md](kroki-diagram-rendering.md)** — 2026-10-14  
  live. How server-side mermaid rendering works
- **[multi-resource-questions-design.md](multi-resource-questions-design.md)** — 2026-10-01  
  design and planning input. First draft 2026-09-20; revised the same
- **[next-ui-matrix-round.md](next-ui-matrix-round.md)** — 2026-09-10  
  live and in real use on a twelve-repo work list
- **[next-ui-side-by-side.md](next-ui-side-by-side.md)** — 2026-10-14  
  superseded. Walk written when / was Classic; Next is now the default (2026-10-07). Kept as a rec
- **[open-stack-checklist.md](open-stack-checklist.md)** — 2026-10-14  
  live, partly dated. Outstanding-work checklist, last updated 2026-08-31; entries are deleted whe
- **[process-model.md](process-model.md)** — 2026-10-14  
  live. Process roles, leader locks and loop inventory
- **[project-review-2026-07-14.md](project-review-2026-07-14.md)** — 2026-09-02  
  DATED SNAPSHOT — 2026-07-14, the oldest document here. Predates the migration into the Trellis m
- **[question-answering-and-context.md](question-answering-and-context.md)** — 2026-09-03  
  consolidated design. Current as of 2026-09-02
- **[repo-analysis-funnel.md](repo-analysis-funnel.md)** — 2026-09-02  
  consolidated design. Current as of 2026-09-02
- **[security-model.md](security-model.md)** — 2026-10-11  
  consolidated model, current as of 2026-09-25. This is the single
- **[survey-execution.md](survey-execution.md)** — 2026-09-04  
  consolidated design. Current as of 2026-09-02
- **[survey-model.md](survey-model.md)** — 2026-10-01  
  consolidated design and reference. Current as of 2026-09-02
- **[surveyor-reference.md](surveyor-reference.md)** — 2026-10-14  
  stale. Oldest unrevised reference (2026-08-07); predates the database surveyors and Prefect. Che
- **[trellis.md](trellis.md)** — 2026-09-02  
  hand-authored reference outline describing runtime and deployment
- **[user-guide.md](user-guide.md)** — 2026-10-14  
  live. Investigations, work lists, private work, Curate and Publish are current; more sections fo
- **[work-timeline-2026-08-31-to-09-02.md](work-timeline-2026-08-31-to-09-02.md)** — 2026-09-03  
  source material, not a design document. A commit-derived narrative of one work window, kept as r
- **[workspaces.md](workspaces.md)** — 2026-09-02  
  hand-authored reference outline describing runtime and deployment

## Findings and audits

Evidence. What was measured, when, and against what.

- **[architecture-recovery.md](architecture-recovery.md)** — 2026-09-03  
  consolidated design and reference. Phase 0 and Phase 1 measurement complete; the
- **[coverage-audit-2026-09-11.md](coverage-audit-2026-09-11.md)** — 2026-10-14  
  historical findings. Dated audit (2026-09-11); numbers are as of that date

## Shipped — kept because the code cites them

The work is done and these are NOT archive candidates: source comments point here for the reasoning behind decisions.

- **[admin-surface-options.md](admin-surface-options.md)** — 2026-10-14  
  implemented. Options survey from 2026-09-03; the admin surface it proposed has been built
- **[annotation-identity-check.md](annotation-identity-check.md)** — 2026-10-14  
  implemented. Answered 2026-09-11 from the schema and live registry; the answer is applied in cod
- **[automate-notification-manager-pyegeria-spec.md](automate-notification-manager-pyegeria-spec.md)** — 2026-08-13  
  specification only, not implemented. Written per explicit direction
- **[blueprint-materialization-plan.md](blueprint-materialization-plan.md)** — 2026-09-03  
  planned, not yet built. Written 2026-09-03 (Opus-model plan pass), scoping
- **[curate-evidence-based-decisions-plan.md](curate-evidence-based-decisions-plan.md)** — 2026-09-03  
  design pass, not yet built. Companion to `docs/blueprint-materialization-plan.md` (the
- **[curated-architecture-answers-design.md](curated-architecture-answers-design.md)** — 2026-10-14  
  implemented in part (code cites §6 items 1-4). Originally a design pass, not yet built. Opened 2
- **[curation-lenses-design.md](curation-lenses-design.md)** — 2026-10-14  
  design, unmeasured (2026-09-08). Nothing here is built. §8 defines the spike that
- **[discovery-automate-project-context-plan.md](discovery-automate-project-context-plan.md)** — 2026-08-15  
  all 5 parts built and live-verified (2026-08-13). Part 1 (Discovery
- **[investigation-classification-and-zoning-design.md](investigation-classification-and-zoning-design.md)** — 2026-10-14  
  BUILT. All six phases are implemented and live-verified (2026-09-07/08). Extends
- **[investigation-framing-design.md](investigation-framing-design.md)** — 2026-10-13  
  design; two pieces have since been built (2026-08-24). All 41 questions are tagged with Purpose 
- **[next-ui-corrections-implemented.md](next-ui-corrections-implemented.md)** — 2026-10-14  
  implemented. Next UI corrections round, 2026-09-10; kept as a record
- **[next-ui-design-rules.md](next-ui-design-rules.md)** — 2026-10-14  
  live. Design rules the Next UI is built to
- **[next-ui-experiment.md](next-ui-experiment.md)** — 2026-10-14  
  implemented. Narrative of the /next experiment; Next has since become the default UI (2026-10-07
- **[next-ui-legibility-and-charts.md](next-ui-legibility-and-charts.md)** — 2026-10-14  
  implemented. Legibility and charts round, 2026-09-10; kept as a record
- **[next-ui-matrix-response-implemented.md](next-ui-matrix-response-implemented.md)** — 2026-10-14  
  implemented. Matrix response round, 2026-09-10; kept as a record
- **[next-ui-survey-dashboard-implemented.md](next-ui-survey-dashboard-implemented.md)** — 2026-10-14  
  implemented. Survey and dashboard pass, 2026-09-10; kept as a record
- **[repair-operations-design.md](repair-operations-design.md)** — 2026-10-14  
  implemented. Four repo-repair operations (2026-08-28), built
- **[rfa-dismissals.md](rfa-dismissals.md)** — 2026-10-14  
  implemented. Not applicable and won't do dismissals for RFAs, built
- **[survey-definitions.md](survey-definitions.md)** — 2026-09-02  
  Implemented and validated end-to-end against a live Egeria server (2026-07-07/08) — both a singl
- **[tutorial.md](tutorial.md)** — 2026-10-14  
  historical. Narrates how the predecessor Project Explorer was built; do not follow as instructio
- **[vendored-guard.md](vendored-guard.md)** — 2026-10-14  
  implemented. The vendored-walk guard and the record of it failing (2026-09-12)
