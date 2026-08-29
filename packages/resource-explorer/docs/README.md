# Resource Explorer documentation

63 documents, grouped by what they *are* rather than what they are about — the
distinction that matters when deciding whether one is still live.

**Generated from each document's own `**Status:**` line**, not from a
hand-maintained list, because a hand-maintained index goes stale the first time
someone adds a file. Regenerate after adding or reclassifying:

```bash
python scripts/regen_docs_index.py
```

## Open — planned or on hold

Live plans. The work is not done; the doc is the specification.

- **[architecture-recovery-phase0-plan.md](architecture-recovery-phase0-plan.md)** — 2026-08-20  
  plan, ready to execute
- **[architecture-recovery-phase1-findings.md](architecture-recovery-phase1-findings.md)** — 2026-08-22  
  measurement goals MET. Engineering work not started
- **[rag-ingestion-as-analysis-step-plan.md](rag-ingestion-as-analysis-step-plan.md)** — 2026-08-20  
  planned, not started. Written 2026-08-20 for execution in a separate session

## Design and framing

Decisions and models. Cited from source where a comment cannot restate them.

- **[approach-portfolio-model.md](approach-portfolio-model.md)** — 2026-08-22  
  design note, for review
- **[architecture-recovery-design.md](architecture-recovery-design.md)** — 2026-08-24  
  design + plan. Review comments incorporated. All open questions resolved except Q6
- **[architecture-recovery-phase1-plan.md](architecture-recovery-phase1-plan.md)** — 2026-08-20  
  plan, for review
- **[distributed-survey-best-practices.md](distributed-survey-best-practices.md)** — 2026-08-06  
  Architecture Design Note
- **[distributed-survey-orchestration.md](distributed-survey-orchestration.md)** — 2026-08-07  
  Proposal / Design Options
- **[egeria-pyegeria-issues.md](egeria-pyegeria-issues.md)** — 2026-08-27  
  Open, unresolved. No workaround exists in RE — this fails the operation outright; RE catches the
- **[egeria-reset-recovery.md](egeria-reset-recovery.md)** — 2026-08-26  
  written 2026-08-21, from an actual reset rather than from theory. Every
- **[microflow-survey-funnel-model.md](microflow-survey-funnel-model.md)** — 2026-08-16  
  framing doc, capturing a real unification confirmed 2026-08-15 —
- **[survey-activity-design.md](survey-activity-design.md)** — 2026-08-08  
  In revision — second round of comments incorporated

## Findings and audits

Evidence. What was measured, when, and against what.

- **[survey-and-analysis-current-state-2026-08-19.md](survey-and-analysis-current-state-2026-08-19.md)** — 2026-08-20  
  findings document, not a work plan. Everything below is observed in the code as of

## Shipped — kept because the code cites them

The work is done and these are NOT archive candidates: source comments point here for the reasoning behind decisions.

- **[analysis-step-egeria-registration-plan.md](analysis-step-egeria-registration-plan.md)** — 2026-08-13  
  investigation complete, plan drafted, not yet built
- **[assessment-expansion-plan.md](assessment-expansion-plan.md)** — 2026-08-15  
  built. Corrected 2026-08-15 — this header was stale; direct
- **[assessment-sub-resource-cataloging.md](assessment-sub-resource-cataloging.md)** — 2026-08-15  
  built. Corrected 2026-08-15 — this header was stale; the
- **[automate-notification-manager-pyegeria-spec.md](automate-notification-manager-pyegeria-spec.md)** — 2026-08-13  
  specification only, not implemented. Written per explicit direction
- **[confidence-gated-validation-plan.md](confidence-gated-validation-plan.md)** — 2026-08-15  
  framed, not built. Written per direct request (2026-08-14):
- **[discovery-automate-project-context-plan.md](discovery-automate-project-context-plan.md)** — 2026-08-15  
  all 5 parts built and live-verified (2026-08-13). Part 1 (Discovery
- **[egeria-collaboration-and-survey-model.md](egeria-collaboration-and-survey-model.md)** — 2026-08-06  
  Discussion captured; §6.6 (RE's local Survey Definition executor) is implemented, unit-tested, a
- **[filesystem-survey-analytics-plan.md](filesystem-survey-analytics-plan.md)** — 2026-08-06  
  Design agreed (2026-07-13). §4 items 1-3, 5, 6 implemented (2026-07-13) — Technology Type string
- **[funnel-stage-data-needs-review.md](funnel-stage-data-needs-review.md)** — 2026-08-15  
  draft, first pass — for discussion, not yet decided or implemented
- **[granularity-pass.md](granularity-pass.md)** — 2026-08-28  
  design pass complete. Nothing built. Recommends a smaller change than
- **[investigation-framing-design.md](investigation-framing-design.md)** — 2026-08-24  
  design; two pieces have since been built (2026-08-24). All 41 questions are tagged with Purpose 
- **[microflow-embedded-process-plan.md](microflow-embedded-process-plan.md)** — 2026-08-17  
  design pass complete (2026-08-16), not yet built. Four independent, loosely-coupled threads — se
- **[re-as-engine-host-plan.md](re-as-engine-host-plan.md)** — 2026-08-17  
  ON HOLD (2026-08-17). Design complete; case 4 built and live-verified at the code/routing level 
- **[repo-scope-narrowing-funnel.md](repo-scope-narrowing-funnel.md)** — 2026-08-11  
  Phase 1 AND Phase 2 both implemented, tested (916 tests total), and live-verified
- **[repo-survey-catalog-completion-plan.md](repo-survey-catalog-completion-plan.md)** — 2026-08-17  
  design pass complete (2026-08-17), not yet built
- **[rfa-egeria-todo-followup.md](rfa-egeria-todo-followup.md)** — 2026-08-16  
  (2026-08-16): implemented, unit-tested (44 tests), AND live-verified
- **[step-cost-tiers-plan.md](step-cost-tiers-plan.md)** — 2026-08-20  
  implemented 2026-08-20
- **[survey-definitions.md](survey-definitions.md)** — 2026-08-06  
  Implemented and validated end-to-end against a live Egeria server (2026-07-07/08) — both a singl
- **[survey-model-and-engine-host-design.md](survey-model-and-engine-host-design.md)** — 2026-08-27  
  design note. §1 hazards, §3 and §4.5 (Prefect) all done 2026-08-26
- **[survey-question-context-plan.md](survey-question-context-plan.md)** — 2026-08-15  
  D1/D2/D3 built, unit-tested (2026-08-13, 1100 tests green), and
- **[survey-results-dashboard-plan.md](survey-results-dashboard-plan.md)** — 2026-08-17  
  planned, not yet built
- **[survey-tab-unification-plan.md](survey-tab-unification-plan.md)** — 2026-08-18  
  implemented, tested, and live-verified this session (D1-D5 all shipped). Not yet committed
- **[unified-survey-execution-model-plan.md](unified-survey-execution-model-plan.md)** — 2026-08-16  
  planned, not yet built, except D7a's first slice (shipped

## Guides, references and unmarked

Includes the user-facing guides. Anything here without a Status line is a candidate for gaining one.

- **[admin-guide.md](admin-guide.md)** — 2026-08-21
- **[architecture-recovery-phase0-findings.md](architecture-recovery-phase0-findings.md)** — 2026-08-20
- **[architecture-recovery-scenarios-and-gaps.md](architecture-recovery-scenarios-and-gaps.md)** — 2026-08-23
- **[Architecture.md](Architecture.md)** — 2026-08-07
- **[Backlog.md](Backlog.md)** — 2026-08-28
- **[code-intelligence-approach.md](code-intelligence-approach.md)** — 2026-08-07
- **[comparison-integration-approach.md](comparison-integration-approach.md)** — 2026-08-07
- **[consolidation-2026-08-24.md](consolidation-2026-08-24.md)** — 2026-08-24
- **[curate-followups.md](curate-followups.md)** — 2026-08-07
- **[database-surveyor-design.md](database-surveyor-design.md)** — 2026-08-06
- **[database-surveyor-quickstart.md](database-surveyor-quickstart.md)** — 2026-08-28
- **[egeria-database-survey-definition.md](egeria-database-survey-definition.md)** — 2026-08-06
- **[egeria-lineage-invocation.md](egeria-lineage-invocation.md)** — 2026-08-06
- **[egeria-postgresql-exploration.md](egeria-postgresql-exploration.md)** — 2026-08-06
- **[egeria.md](egeria.md)** — 2026-08-20
- **[end-to-end-gap-audit-2026-08-25.md](end-to-end-gap-audit-2026-08-25.md)** — 2026-08-25
- **[kroki-diagram-rendering.md](kroki-diagram-rendering.md)** — 2026-08-15
- **[open-stack-checklist.md](open-stack-checklist.md)** — 2026-08-28
- **[project-review-2026-07-14.md](project-review-2026-07-14.md)** — 2026-08-06
- **[repair-operations-design.md](repair-operations-design.md)** — 2026-08-28
- **[repo-phase-visibility-model.md](repo-phase-visibility-model.md)** — 2026-08-26
- **[surveyor-reference.md](surveyor-reference.md)** — 2026-08-07
- **[trellis.md](trellis.md)** — 2026-08-20
- **[tutorial.md](tutorial.md)** — 2026-08-06
- **[user-guide.md](user-guide.md)** — 2026-08-21
- **[using-the-intent-shell.md](using-the-intent-shell.md)** — 2026-08-08
- **[workspaces.md](workspaces.md)** — 2026-08-20
