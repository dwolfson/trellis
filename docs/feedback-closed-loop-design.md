# Closing the loop on answer feedback

Status: **proposal, for architect read-back and project-owner decisions (§8).** Nothing here is
built. Written 2026-11-09.

Related:
- [`trellis-feedback-extraction.md`](trellis-feedback-extraction.md) is the shared feedback store
  and triage this builds on. Its §6 step 3 put RE's ratings into it.
- [`context-compilation-design.md`](context-compilation-design.md) §13 names the three feedback
  loops and the double-counting guard. §22 covers editable manifests. This document is the "redesign
  AI-response feedback into a real closed loop" workstream that §13 says it is part of.

## Why this doc exists

**Feedback is now collected well.** Since 2026-11-09 (trellis-feedback adoption, parts A to D) every
chat vote and checklist verdict in RE is kept with:
- its question and the full answer;
- the user;
- the compile id, intent and resource;
- an admin-set status and note, appended as an event.

**Almost nothing reads it.** A 👎 changes no later answer, and nobody can tell whether a fix made
answers better. This document proposes how a rating turns into a change, and how we find out whether
the change worked.

## 1. What exists today

### Loops that act automatically

1. **Chunk re-weighting (RE), but disconnected.**
   - **The design:**
     - `MetricsCollector.record_feedback` adds each vote to `chunk_feedback`: positive, neutral and
       total counts for every chunk the answer retrieved;
     - `vector_store_pg._load_boosts` turns those counts into a score adjustment, `(precision − 0.5)
       × confidence × 0.3`, where neutral counts as half;
     - retrieval adds that adjustment to each chunk's similarity.
   - **Finding, 2026-11-09: the read side is inert on every Postgres deployment.**
     - `record_feedback` writes to `METRICS_DATABASE_URL`, which has been Postgres by default since
       2026-08-23 (`ObservabilityConfig`).
     - `_load_boosts` still opens `observability.metrics_db`, the old SQLite path
       (`data/metrics.db`), with `sqlite3.connect`. That call *creates* an empty file.
     - The query then fails, and the bare `except` returns `{}`.
     - On this development machine `data/metrics.db` is a 0-byte file created that morning. So no
       vote has adjusted any retrieval since the move, and nothing said so.
     - Fixing this is a bug fix, not a design question. It is §6 step 0.
   - **Even when connected, it's blunt.** A 👎 marks down *every* chunk retrieved for that answer.
     That includes the right ones, when the fault was compression or reasoning (§2).
2. **Collection multipliers (EA).**
   - `perspective_routing.get_feedback_adjustments` turns per-collection 👍/👎 counts in
     `query_metrics` into routing multipliers, once a collection has 3 or more votes.
   - That's the "router learns from feedback" consumer §13 warns about. If the compiler also learns
     from the same votes, the signal is counted twice.
3. **Disagreement → gap (RE).**
   - A `disagree` on a resource-scoped answer becomes a gap marked `ours`, charged to the analysis
     the question catalog names (`gaps.record_disagreement`).
   - That works for the Questions checklist, whose questions are catalogued.
   - For free-text chat, the catalog lookup finds no analysis, so the gap is "attributed to none":
     recorded, but not routable.

### Kept, but read by no automated process

- **Answer items** (trellis-feedback, `kind = answer`): vote, question, answer, user, compile id,
  intent, resource and session. Text comes from the stored exchange when there is one.
- **Triage events:** status, note, actor and sequence for every item, including Curate's
  `resource_feedback` rows, which are triaged by reference.
- **Compiles** (`context_compiles`, not pruned): the manifest with each packed section and its rung,
  the gaps, notes and derivation. A vote's compile id therefore leads to exactly the evidence the
  model saw.

## 2. The missing piece is a diagnosis

§13's point, made concrete: **a 👎 is a symptom, and the right fix depends on the cause.**

| Cause | What went wrong | Where the fix lives |
|---|---|---|
| `wrong_evidence` | the compile picked sections or chunks that weren't relevant | retrieval and section weights |
| `missing_evidence` | the analysis that answers it exists but hadn't run, or isn't in the spec | run the analysis, or add it to the spec |
| `over_compressed` | the right section was there, cut to a rung too low to answer from | the compile spec's budget and rungs (§22's "go deeper on that one") |
| `catalog_gap` | nothing we have answers this question | a new analysis or question; a gap or RFA |
| `stale` | the evidence was right but out of date | rescan or reschedule (Automate) |
| `reasoning` | the model had what it needed and answered badly | the prompt, model tier or answer template |
| `not_an_issue` | the answer was right, or the question was unanswerable as asked | nothing; it closes the item |

Today none of these causes is recorded. The status (`known_issue`, `actioned`, …) says *whether*
something was done, not *what kind* of problem it was. Without the cause, nothing can be routed and
nothing can be counted by cause.

**Some causes can be pre-filled from the manifest:**
- a compile whose manifest lists a gap for the asked section suggests `missing_evidence`;
- a packed section at its lowest rung suggests `over_compressed`;
- no compile at all (unscoped RAG) suggests `wrong_evidence` or `catalog_gap`.

The admin confirms or changes the suggestion. A suggestion is never recorded as a diagnosis by
itself.

## 3. Proposal

### 3.1 Diagnose at triage

- **Data:** a `cause` field on the triage event, from the vocabulary above. Like the status, the
  library checks it, and it is append-only: a re-diagnosis is a new event.
- **UI:** Admin → Feedback gains, for an answer item:
  - the compile's evidence beside the answer (its sections, rungs and gaps, read from the manifest);
  - the suggested cause;
  - a cause menu next to the status menu that part C built.
- **Product items:** page-widget reports keep status only. Their cause is a UI or product
  question, outside this loop.

### 3.2 Route each cause to one consumer

One consumer per signal (§13's guard), named here so there's no second, silent one.

| Cause | Consumer | What it does |
|---|---|---|
| `missing_evidence` | the gaps loop | a gap `ours` on the analysis from the manifest, so a chat 👎 becomes routable where today it's "attributed to none" |
| `catalog_gap` | the gaps loop / RFA | a gap with no analysis, plus an RFA to the catalog owner when the question has no home |
| `stale` | Automate | proposes a schedule for the analysis behind the stale section |
| `over_compressed` | the compile spec | an entry in the spec-editing loop (§13 loop 2), naming the section and the rung that wasn't enough |
| `wrong_evidence` | retrieval weights | **only these** votes feed chunk scores (§3.4) |
| `reasoning` | a prompt/model review list | read by a person, not by a weight |

### 3.3 Turn a fixed failure into a regression case

The step that makes the loop closed, not just routed.

- **The case:** when an admin marks a diagnosed 👎 `actioned`, it becomes a replay case:
  - the question and the resource (or none);
  - the perspective and the as-of time;
  - the original answer;
  - the cause;
  - the admin's note on what a right answer must contain: a short list of facts or "must not"
    statements, not a reference answer.
- **The replay:** runs the cases against the current build and checks each one. Two kinds of check:
  - **deterministic:** the compile includes the section that was missing, or a section is packed
    above the rung that failed;
  - **judged:** the answer contains the must-have facts. That is an LLM judge, scoped to those
    statements and nothing broader.
- **The result:** an Admin view of each case's state: fixed, still failing, or regressed (it passed
  before and fails now).
- **Placement:** a regressed case reopens its item with an event (`new`, actor `replay`), so a
  regression lands in the same queue as a fresh report.
- **Starting small:** the cases are few at first, and the replay is cheap: one compile and one answer
  per case. A nightly run is enough. It can be attached to the scheduler RE already has.

### 3.4 Chunk scores from diagnosed votes only

- After step 0 reconnects it, chunk scoring keeps taking raw votes **only until** diagnoses exist.
- From then on, the input changes:
  - a 👎 diagnosed `wrong_evidence` marks down the chunks that compile used;
  - a 👎 with any other cause leaves chunk scores alone;
  - a 👍 still counts.
- That stops a reasoning failure from punishing the evidence that was right.
- **The scope rule (EA):** EA's collection multipliers and RE's chunk scores read *different* votes
  (EA's and RE's answers). That's no double count *today*. The shared store could make it one, so
  the rule is written down here: each app's retrieval learns only from its own app's votes.

### 3.5 Measure

A small set of numbers, computed from the store, shown in Admin and logged to MLflow, where §12 says
tuning reports:

- **Helpful rate** (👍 / all, with 😐 at half credit, as everywhere else), by intent, perspective,
  resource type and analysis, weekly.
- **Cause mix** of diagnosed 👎, weekly. A falling share for one cause after its fix is the evidence
  the fix worked.
- **Time to diagnose** and **time to actioned**.
- **Replay pass rate**, and regressions found.

One caveat belongs on the page, not in a footnote: vote counts will be small for a long time, so most
of these are a direction, not a measurement.

## 4. What changes, by component

| Component | Change |
|---|---|
| `trellis-feedback` (0.3) | `cause` on triage events, with its vocabulary; `TriageState` carries the latest cause; list and count filter by cause |
| RE `vector_store_pg` | step 0: read chunk scores from the metrics URL the collector writes, and stop creating `data/metrics.db` |
| RE `metrics_collector` | chunk scores from diagnosed votes (§3.4) once causes exist |
| RE Admin → Feedback | the evidence panel from the manifest, the suggested cause and the cause menu |
| RE gaps / RFA / Automate | consumers for `missing_evidence`, `catalog_gap` and `stale` (§3.2) |
| RE replay | the case store (library items with `extra.replay`, or a small table; §8 Q4), the nightly run and its Admin view |
| EA | none until EA adopts the library (trellis-feedback doc §6 step 4); then the same causes and replay |

## 5. What it costs

- **Admin time is the real cost.** Each diagnosis is a person reading an answer and its evidence.
  The suggested cause and the evidence panel are there to make that a minute, not ten. Volume
  decides whether that's sustainable, and we don't yet know the volume (§8 Q6).
- **A judge model for replay**, scoped to the stated must-haves. It's cheap per case and nightly;
  it's the one place an LLM grades an LLM, which is why the deterministic checks come first.
- **Privacy:** replay cases keep questions and answers, already kept and admin-only (feedback doc
  Q3–Q5). Replay runs as the service identity, so the original user's id must not travel into the
  replay's own logs.

## 6. Phasing

Each step is its own PR, with tests and an architect read-back.

0. **Reconnect chunk scoring.** Read from the metrics URL. Add a test that a recorded 👎 changes the
   next retrieval's scores on Postgres and on SQLite. Remove the `sqlite3.connect` that creates an
   empty file. A bug fix: it needs no decision, and it's the only step here that changes answers
   by itself.
1. **Cause on triage:** trellis-feedback 0.3, then RE's cause menu and evidence panel. No consumers
   yet; it starts collecting diagnoses.
2. **Routing:** the gaps and RFA consumers, then Automate's.
3. **Replay:** the cases, the nightly run, the Admin view, and reopening on regression.
4. **Diagnosed chunk scoring** (§3.4), once enough diagnosed `wrong_evidence` votes exist to matter.
5. **Measurement views.** These can run alongside 1 to 4; their numbers mean little until there are
   diagnoses.

## 7. Not in scope

- **Fine-tuning a model on feedback.** The volume is nowhere near it, and the causes say most fixes
  are in evidence and specs, not weights.
- **Automatic diagnosis without a person.** The suggestion is a starting point. Recording it
  unconfirmed would make every downstream number depend on a heuristic we haven't measured.
- **§22's editable manifest.** It's a better label than a rating, as §22 says, and it would arrive
  already diagnosed. It's a separate, larger piece of work. This design leaves room for it: an
  accepted manifest edit could later be recorded as a diagnosed item with cause `over_compressed`
  or `wrong_evidence`.

## 8. Open questions for the project owner

1. **The cause vocabulary.** The seven in §2, or fewer to start? Recommendation: all seven. Each has
   a different fix, and merging two makes one of them unroutable.
2. **Who diagnoses?** Admins only, the same as triage (feedback doc Q3)? Or may an analysis's owner
   diagnose the items charged to their analysis? Recommendation: admins for now.
3. **What "must contain" looks like for a replay case.** A short list of fact statements, written by
   the admin who marks the item actioned? Or optional, with replay checking only the deterministic
   compile properties when it's missing? Recommendation: optional; the deterministic check alone
   already catches the commonest regressions.
4. **Where replay cases live.** As library items (`extra.replay`), which keeps them beside their
   history, or in their own small table, which keeps the feedback store to feedback?
   Recommendation: their own table in trellis-feedback, keyed to the item, so EA gets it too.
5. **Should a regression reopen the item, or open a new one** linked to it? Recommendation: reopen
   (`new`, actor `replay`), since it is the same failure come back.
6. **Volume.** How many chat votes a week do we expect on the production instance? It decides
   whether diagnosis is a minute a day or a job. Step 0 and step 1 can go ahead regardless.
7. **EA's collection multipliers.** Leave them as they are (they read EA's own votes, §3.4), or move
   them onto diagnosed votes too when EA adopts the library? Recommendation: decide at EA adoption,
   not now.
