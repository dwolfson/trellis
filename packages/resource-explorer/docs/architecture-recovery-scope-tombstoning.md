# Scope Tombstoning — what happens to a component whose identity changed

**Status:** design note. Nothing here is built. It answers a question raised by
the deployment-style consolidation (2026-08-29) and deliberately left open there:
*should an identity change tombstone the scope it vacates?*

**Answer: yes, but "tombstone" is the wrong word for it.** Nothing is deleted.
What is needed is a **withdrawal** — a durable statement that no step proposes
this scope any more — plus one change to the query that has been quietly
publishing vacated scopes as current.

Related: design doc **§4.1c** (`scope_locator` carries two meanings, and
`run_scope`/`partial` were added because of it) and **§6.0** (a component IS a
scope_locator).

---

## 1. The defect, measured

`egeria_git` currently carries **14 `scope_locator`s beginning `spring::`**. That
prefix was removed from `spring_app._slug()` earlier the same day, because it
collapsed every platform into one cluster named after the discoverer. The code
was fixed. The rows were not, and nothing about them says so:

```
spring::Development-OMAG-Server-Platform::view-server
spring::Containerized-OMAG-Server-Platform::integration-daemon
spring::test
...
```

They read as current components, at their original confidence, in every view
that lists components. The deployment-style consolidation will add **12 more**
when egeria is next surveyed — `Development-OMAG-Server-Platform::*` and
`Containerized-OMAG-Server-Platform::*` are merging into
`OMAG-Server-Platform::*`.

**This is not specific to those two changes.** Component identity is *derived*:
a slug is whatever the detector's identity rule produced. Every improvement to
an identity rule renames some components, and every rename orphans the scopes it
left behind. The catalog accumulates a permanent sediment of every identity
scheme the pipeline has ever had, all of it indistinguishable from current.

## 2. Why writing a better row does not fix it

Three facts about the store combine, and only the third is obvious.

**(a) `query_finding_scopes` has no notion of currency.** It is the "list every
component" query for a many-scope kind (§6.0), and it is exactly this:

```sql
SELECT DISTINCT scope_locator FROM project_analysis_findings
WHERE project_slug = ? AND kind = ?
```

No timestamp, no recency, no filter. **A scope, once written, is enumerable
forever.** This is the actual leak, and it is upstream of everything else.

**(b) `query_findings` reads `MAX(surveyed_at)` per scope.** A scope nothing
rewrites keeps its last value, at full confidence, indefinitely. There is no
timestamp comparison a reader can make, because the row *is* the newest row for
that scope — it is just that the scope stopped being written years ago in
survey-time.

**(c) `query_findings_all_runs` accumulates by design.** For
`architecture_recovery` specifically, it deliberately does *not* narrow to the
latest run, because `repo_arch_detect` and `repo_arch_coupling` contribute
evidence for the same component at different times and "latest wins" would
discard whichever ran first. So "supersede by writing later" is not available as
a blanket semantics here — the kind that most needs withdrawal is the one kind
that reads every row.

The consequence: **a withdrawal row alone changes nothing.** Write one and
`query_finding_scopes` still enumerates the scope — now with an extra row on it.
The query has to learn the concept, or the mechanism is decorative.

## 3. What a withdrawal is

> **A withdrawal is a durable, scope-keyed statement that as of time `T`, step
> `S` no longer proposes this scope. It supersedes for reads. It deletes
> nothing.**

Four things follow, and the fourth is the one that keeps this consistent with
the rest of the pipeline.

- It is **scope-keyed** — it lives on the vacated scope, or no query that finds
  the stale rows can find it.
- It is **step-attributed** — see rule R2; unattributed withdrawal is unsafe.
- It **supersedes for `query_findings` and `query_finding_scopes`**, the two
  reads that answer "what is the architecture now".
- It is **invisible to `query_findings_all_runs`**, which keeps answering "who
  proposed what, ever". The provenance view (Phase 1 plan §4.4) must not lose
  history because the current answer changed. Nothing here should quietly remove
  evidence — the same rule `_record_run` states for the doc lens.

## 4. The rules

### R1 — Only a COMPLETE run may withdraw

A withdrawal is inferred from *absence*: the scopes a step used to write and did
not write this time. **Absence only means something if the run could have seen
everything.**

§4.1c already put the guard in the data. Every row carries `run_scope` and a
`partial` outcome, added precisely because a scoped run's component set is
necessarily incomplete and nothing recorded that. So:

> A run with a non-empty `run_scope`, or whose `StepOutcome` is `PARTIAL`, **may
> not withdraw anything.**

This is the most dangerous failure mode in the whole design — a scoped run
withdrawing the architecture outside its scope — and the field that prevents it
already exists and is already written. That is the strongest argument for
building on §4.1c rather than inventing a completeness flag.

### R2 — A step may only withdraw scopes IT wrote

`repo_arch_detect` and `repo_arch_coupling` write the **same kind**. If detect
withdrew every scope it did not write this run, it would withdraw **all of
coupling's components**, and coupling would return the favour on its next run.
The two steps would erase each other, alternately, forever.

This is not hypothetical — it is the same collision `persist_ir` already
solved once for metrics, and the comment there says why:

> metric_name is prefixed with `run_label` ("detect"/"coupling") rather than
> shared, because [they] are two independent StepInfo entries that are not
> guaranteed to run in the same SurveyOrchestrator batch […] a shared
> metric_name would let one step's count silently overwrite the other's.

**The same reasoning applies to withdrawal, and the same key is the answer.**

**Enabling change:** `run_label` is currently used only in the summary metric
name. It is **not** on the component rows — verified against a stored row, whose
detail keys are `blueprint, confidence_level, depth, files, identity, name,
outcome, outcome_cause, outcome_known_positive, parent_slug, perspective,
proposed_by, run_scope, slug, type`. It must be added. `proposed_by` is a
tempting proxy, and it is the wrong one: it names the *detector*, and a detector
can move between steps without any component changing.

### R3 — Withdrawal records a cause, and the default cause is not "gone"

Two causes look identical from inside the pipeline and mean opposite things to a
reader:

| cause | meaning | what it says about the system |
|---|---|---|
| **superseded** | the component still exists; its slug changed | nothing — our naming moved |
| **removed** | the component is genuinely gone from the repo | real architectural drift |

Conflating them makes "the architecture changed" indistinguishable from "we
improved a detector", which destroys the drift signal the catalog exists to
carry.

**The pipeline usually cannot tell them apart**, and it must not pretend
otherwise. So the default cause is neither:

> **`unclaimed`** — "no step proposes this scope any more". Literally true,
> asserts nothing further.

A detector that *knows* it renamed something may declare a supersession
explicitly and carry the new slug. Absence alone may never be reported as
`removed`. This is §4.1a's discipline in another place: a repository contains a
description of a container, not a container — and a missing row is the absence
of a proposal, not the absence of a component.

### R4 — The query is the choke point, and the mechanism should be generic

`query_finding_scopes` is where the fix belongs: five callers, all of them
architecture readers, one place to change.

But the registry is deliberately **kind-agnostic** — it knows nothing about
components or architecture, and it should stay that way. So the mechanism should
be a reserved **label**, not an architecture-specific `check_name`:

- any kind may withdraw a scope by writing a row with `label = WITHDRAWN`;
- `query_finding_scopes` excludes scopes whose **most recent row** carries it;
- `query_findings` returns it, so a direct reader sees the withdrawal rather
  than an empty result it has to interpret.

"Most recent row wins" gives a property worth having for free: **a step that
still proposes a scope revives it.** If detect withdraws a scope and coupling
writes it again later, the scope is live — correctly, because a scope one step
still proposes is not vacated. The rule needs no special case for this; it falls
out of the ordering.

### R5 — Shadowing is the feature here, and it was the bug there

Worth stating explicitly, because the mechanism is *identical* to one this
codebase already recorded as a defect.

`arch_lens` originally wrote labels into `architecture_recovery`. Because
`query_findings` returns only rows at `MAX(surveyed_at)`, that made the labelled
components **invisible** — Milvus's candidate count fell 218 → 203, exactly the
15 scopes the lens had labelled. The rows were never lost; they stopped being
readable.

Withdrawal uses the same mechanism deliberately. **The difference is intent, and
it is a real distinction rather than a rationalisation:** a step that *annotates*
another step's output must never shadow it, and a step that *supersedes* its own
earlier output must. The test is whose rows are being shadowed — your own, or
someone else's. R2's step-attribution is what makes that question answerable at
all, which is a second reason it is not optional.

## 5. Metrics need no change, and here is why

`query_metrics` has the same `MAX(surveyed_at)`-per-scope shape, so a withdrawn
scope's metrics linger identically. But there is **no `query_metric_scopes`** —
verified — so metrics are only ever read for a scope some *finding* query
already surfaced. Fix the finding-scope enumeration and metric rows for
withdrawn scopes become unreachable rather than wrong.

Recorded rather than assumed: if a metric-scope enumeration is ever added, it
inherits this defect on day one and this section stops being true.

## 6. The backfill is a separate act, and must be labelled as one

The orphans that exist today — **14 now, and 26 once egeria's next survey adds
the 12 the consolidation renames** — predate the mechanism. No run will withdraw
them, because no run can prove it wrote them — old rows carry no `run_label` (R2), so
the attribution withdrawal depends on does not exist for exactly the rows that
need it.

They therefore need a one-off sweep, and that sweep is **weaker evidence than a
withdrawal from a real run**: it is a human asserting that a scope is vacated,
not a step observing it. It must say so — `cause: unclaimed`, and a detail
recording that it came from a backfill on a stated date rather than from a
survey. A backfill that writes rows indistinguishable from earned ones would
launder an assertion into an observation.

## 7. What this must not become

- **Not deletion.** No `DELETE` anywhere in this design. `query_findings_all_runs`
  must keep returning withdrawn rows, or the "which approach proposed this"
  view (Phase 1 §4.4) loses exactly the history it exists to show.
- **Not a drift detector.** A withdrawal is a bookkeeping fact about our
  proposals. Real drift is R3's `removed`, which absence alone can never
  establish.
- **Not automatic in a partial run.** R1 is a hard gate, not a heuristic.
- **Not silent.** A run that withdraws N scopes should say so in its
  `StepOutcome` and its summary row. A cleanup that leaves no trace is
  indistinguishable from data loss when someone comes looking in six months.

## 8. Honest limits

- **The revive rule is untested at scale.** "Most recent row wins" is right for
  detect/coupling, the only two-writer kind today. A third writer with a
  different cadence could produce withdrawal/revival churn, and nothing here
  measures that.
- **No cross-kind story.** `architecture_interfaces`, `architecture_diagram` and
  `architecture_doc_lens` are separately scope-keyed and will orphan the same
  way. The generic label mechanism covers them; nothing in this note has checked
  whether their readers behave sensibly when a scope disappears.
- **It does not make identity stable.** It makes identity *changes* legible.
  Those are different, and the second is the achievable one.

## 9. Staging

1. **Add `run_label` to component rows** (R2's enabler). Additive, no reader
   changes, no behaviour change — and it is a precondition for everything else.
2. **Add the reserved label and teach `query_finding_scopes`.** Five callers,
   all architecture readers. Measure the enumerated-scope count for
   `egeria_git` before and after, which should not move at all until step 4.
3. **Withdraw on complete runs only** (R1 + R3's `unclaimed` default). At this
   point egeria's next survey stops adding new orphans.
4. **Backfill whatever orphans remain**, labelled as a backfill (§6). Note the
   count is a moving target — 14 today, 26 after the next egeria survey — and
   step 3 stops it growing, which is why the backfill goes last.

Steps 1 and 2 are safe and independently useful; 3 is the behaviour change worth
reviewing carefully; 4 is the one that touches data already published, and it
should be last precisely because it is the one that cannot be undone by
re-running a survey.
