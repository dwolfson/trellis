# The decision trace — what was decided, not only what was concluded

**Status:** built 2026-08-30. Records why the survey steps' `notes` are now
persisted, what they are *not* for, and why they are not telemetry.

---

## 1. The gap

Every architecture survey step builds a `notes` list as it works, and each note
is a decision:

```
2 declarations describe one platform (Containerized OMAG Server Platform,
Development OMAG Server Platform) — identical server sets, so they are
deployment styles of 'OMAG Server Platform', not separate platforms

qualified by build module, since a shared name becomes a shared slug and would
collapse them onto one component

test.application.properties is a variant of the `application.properties` beside
it and adds no name or servers — not a separate platform
```

All of it ended here:

```python
for note in notes:
    log.info("ArchDetectSurveyor(%s): %s", self.project.slug, note)
```

`log.info` and nowhere else. So the answer to *"why is this component called
`distro`?"* or *"why is there no `test` platform?"* existed only if somebody
happened to be tailing logs at INFO while that survey ran.

This is the fifth instance of one pattern in this subsystem: a distinction is
computed carefully and dropped at the last hop. `import_cohesion` (computed,
never persisted), ports and wires (discovered, unwired), the doc locator's
outward hop (built, reachable only as a labeller), the `structural` flag
(marked, never read by any consumer), and now these.

## 2. What this is, and what it is not

| | says | lives in |
|---|---|---|
| **Evidence** (§5.4) | *what was concluded, and on what basis* — "X is a Spring application declared in Y" | findings, scope-keyed |
| **StepOutcome** | *did this run succeed, partly, or not at all* | findings + metrics |
| **Decision notes** (this) | *what was decided and what was rejected* | findings, whole-resource |

Evidence justifies a claim that survives. Notes record the claims that **did
not** — the merge that collapsed two declarations, the file that was dropped,
the overlay that had no base. When output looks wrong, the rejected branch is
usually where the answer is, and it was exactly what we were throwing away.

## 3. Design

**Its own kind, `architecture_decisions`.** Not `architecture_recovery`, for
`DIAGRAM_KIND`'s measured reason: a whole-resource row under the recovery kind
makes `context_compile`'s `query_findings(slug, analysis_id)` return exactly one
row and **suppress the results-reader fallback**, replacing an analysis's
evidence with whatever that row happens to be.

**Keyed by `run_label` in the check_name.** `repo_arch_detect` and
`repo_arch_coupling` are independent steps that need not share a `surveyed_at`,
and `query_findings` returns only rows at `MAX(surveyed_at)` per
(slug, kind, scope). A shared check_name at one scope would let whichever step
ran last **hide the other's reasoning entirely** — the same collision
`persist_ir` already solved by prefixing its summary metric with `run_label`.

Read with `query_findings_all_runs(slug, DECISIONS_KIND, "")`, keeping the
newest row per check_name. A plain `query_findings` returns only the
most-recently-run step: a valid but partial view.

**Capped at 200, and the truncation is reported.** A note list is prose for a
human; an unbounded one is a log file in a findings row.

**It cannot fail a survey.** Wrapped, logged on failure — but logged, not
swallowed, since vanishing silently is the failure this change exists to fix.

## 4. First measurement, and what it exposed

| step | notes | shape |
|---|---|---|
| `detect` | 4 | all high-signal — distillation arithmetic, platform consolidation, the variant drop |
| `coupling` | **263** (200 kept, 63 truncated) | **250+ are one templated line**: `.: adopted unproposed subtree X (nothing else claims it)` |

Persisting the trace immediately made a property of it visible that logging
never did: **coupling's reasoning is dominated by a single repetitive message.**
One templated line repeated 250 times is closer to log noise than to a decision
trace, and it crowds out the notes a reader would actually want.

Deliberately **not** changed here — whether those should be summarised into one
note ("adopted 250 unproposed subtrees") or are genuinely per-decision is a
judgement about coupling's own semantics, and the cap already reports the
overflow rather than hiding it. Flagged, not fixed.

## 5. Why this is not MLflow, Phoenix, or OTEL

The question came up directly, and the answer turns on separating two things
that "logging" conflates.

**Decision provenance** — *why did the system conclude X?* — is read months
later, by a person auditing one resource. It must be durable, queryable by
resource, and versioned per run. Telemetry backends are the wrong home: they are
sampled, retention-limited, and keyed by trace id rather than by resource. A
curator asking why a component is named `distro` cannot be asked to find the
matching span.

**Execution telemetry** — how long each step took, what failed, where the hot
path is — *is* spans and metrics, and OTEL is exactly right for it. It is also a
different question, and nothing about it needs the notes.

Concretely, against what RE has today:

- **Phoenix** is wired through `BeeAIInstrumentor` — it instruments the
  **agent/LLM** path. The architecture-recovery steps are deterministic Python
  with no model in them, so there are no LLM spans to hang these on.

  **Correction (Dan, 2026-08-30): that is true of these steps, not of surveys.**
  An earlier draft of this section said "surveying is deterministic Python",
  which overgeneralises from the two steps in front of me — a survey step can
  perform LLM-based analysis, and where it does, Phoenix instrumentation is
  directly relevant to *that* step. It does not change where the decision trace
  belongs (§5's first two paragraphs stand), but it does mean the reasoning
  above is an argument about these steps rather than a property of surveying.
  Revisiting it is a backlog item.
- **MLflow's** `log_query(query, intent, project_slug, response, latency_ms,
  collections_used)` is experiment tracking for **query quality**. A survey is
  not an experiment, and forcing one MLflow run per survey conflates two
  different meanings of "run" behind a UI built for comparing hyperparameters.
- **OTEL generally** would be a reasonable transport for *survey execution*
  spans — per-step and per-detector timings, failure points. That is worth doing
  when there is a performance question to answer; there isn't one yet, and
  `_withdraw_vacated`'s 93ms was measured with `time.perf_counter()` rather than
  needing a collector.

**A further consequence of that correction.** For an LLM-based survey step there
are genuinely two traces to keep apart: the *model interaction* (prompt,
tokens, latency — Phoenix/OTEL's job, and non-deterministic) and the *decision*
it produced (durable, per-resource — this). §16 of
`context-compilation-design.md` already makes the matching argument for the
compiler: agent output must be **written down, versioned and
provenance-stamped before it is packable**, precisely because agents are
non-deterministic. A survey step that calls a model needs the same discipline,
and the decision trace is the natural place for the written-down half.

**Dual-writing was considered and rejected for now.** Emitting notes as span
events *and* findings means two stores that can disagree, and the span copy is
the one that expires. If tracing is added later, the right shape is a span per
survey step carrying the *finding id* — a pointer to the durable record, not a
second copy of it.
