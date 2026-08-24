# Consolidation: what is actually open, and in what order

**Written 2026-08-24, at the point where `re/deferred-cleanup-followups` is 190 commits
ahead of `main`.** Purpose: decide what has to happen before a PR, what can run in parallel
after it, and which backlog entries are stale rather than open. Put in the repo rather than
said in a session, because two cross-session messages were lost to session turnover today and
the durable record is what reached people.

---

## 1. Where we are

| | |
|---|---|
| `origin/main` | `4ff3cdd`, last touched 2026-08-18 |
| `origin/re/deferred-cleanup-followups` | **190 commits ahead of main** |
| `origin/re/results-presentation` | identical to it (worktree at `../trellis-presentation`) |
| Test suite | 1948 passed, 10 skipped |
| CI | green, ~4.5 min, runs on `main` and `re/**`, with a real Postgres tier |
| Sessions | ~11 live; at least 4 have committed to the shared branch today |

**190 commits is the headline problem.** Everything below is downstream of it: a branch that
far from `main` cannot be reviewed as one PR in any meaningful sense, and every day it grows.

---

## 2. Before a PR — in this order, and only these

These are sequential. Each blocks the next.

1. **Stop the multi-writer churn.** Today four sessions committed to one branch through one
   shared checkout. Twice, two of us coordinated carefully and were surprised by a third who
   was not in the conversation (`852955f`, `c370fa8` and `6c0cb2a` all reached the branch
   without review by the people merging). Until writers are reduced to one, "consolidate" has
   no fixed point — the branch moves while you describe it. **This is the actual precondition,
   not a nicety.**

2. **~~Reconcile `.../trellis`~~ — done, and it exposed the real problem.** `6c0cb2a` (54 EA
   Curation templates) is now on origin: Dan instructed a merge that left the commit alone,
   and it rode along. **Its author still has not chosen to publish it, and it is published.**
   That is the second commit from the same writer to reach the remote by someone else's push
   (`c370fa8` was the first).

   **Nobody knows who that writer is, and one confident guess was already wrong.** It was
   attributed to `egeria-advisor-7a` — including in the first version of this document —
   because the commit touches `packages/egeria-advisor/`. They checked and it is not theirs.
   Every session commits under Dan's identity and signs with his key, so **nothing in commit
   metadata distinguishes sessions**, and topic-to-session mapping is a guess wearing the
   clothes of identification. The reflog narrows it only to "an EA-template writer committing
   directly into the shared checkout at 13:50:32 and 13:55:31" — concurrent and active, not a
   leftover.

   The sharpened version of §2.1: the sessions in worktrees caused each other no trouble all
   afternoon. **The one writer working directly in the shared checkout is the one whose
   commits keep being published by other people, and the one nobody can name.** That is the
   setup to change.

3. **Prune the backlog.** 33 entries read as open; several were closed by today's work and
   never marked (see §4). A reviewer cannot tell a live item from a finished one, and neither
   can we — which is the "lots of almost-closed issues" feeling.

4. **Decide the PR's shape.** 190 commits spanning the pgvector migration, the Egeria survey
   definitions, architecture recovery, the presentation layer and CI is not one reviewable
   change. Options, in increasing order of effort: one squash per theme; several stacked PRs
   off `main`; or merge as-is with the history intact and accept it is an integration branch,
   not a reviewed change. **This is a judgement call for Dan, not for a session.**

---

## 3. Outstanding threads, and how they may run

### Can run in parallel — independent, different files

- **Presentation** (`web/`, readers, `result_status.py`). Remaining: render
  `suggested_action` as an input to the Disposition sub-tab rather than a second badge; the
  schedule check before offering a `monitor` subscription (a subscription with no active
  schedule for its `analysis_id` silently never fires).
- **Architecture recovery** (`github/`, `arch_recovery/`, spike). Owned elsewhere. Live
  threads: the LLM adjudicator at 0/27 on the deployment perspective; `misgrouped` has no
  emitter; `investigate` unexercised against real data.
- **Question catalog / check registry** (`configdata/`, `question_catalog*`). A session exists
  and has committed; it is in a worktree and has caused no trouble. Not in any coordination
  conversation so far, so its plans are unknown rather than conflicting.
- **Dependency parsing** — `DependencyParser` covers Python/Node/Go/Maven; Gradle and Cargo
  are missing, so `egeria_git` reports zero dependencies while shipping a `build.gradle`. The
  arch session has an independently-tested Gradle `include` parser (~30 lines) offered for
  reuse.

### Must be sequential

- **`repo_data_profiling` cost tier.** Declared `compute_cost="medium"`, measures 0.0s median
  across 21 repos. **Not yet a finding**: needs a timing on a repo that HAS data files, or it
  is an absence being read as a measurement. Blocks nothing; do not log until measured.
- **Corpus growth.** Several open items ("grow the corpus as a bug-finding strategy",
  "re-check Phase 1 once there are more samples") depend on more repos, and more repos make
  every survey run longer. Sequence it after the PR, not before.

### Genuinely blocked

- **Anything downstream of adjudication.** 0/27 on the deployment perspective; the owning
  session has asked that nothing be built against those numbers yet.

---

## 4. Backlog entries that are stale, not open

Checked against today's work. These read as open and are not:

- **`HIGH — populate IR.ports and IR.wires (§5.5f)`** — done. Persistence wired
  (`architecture_interfaces` findings), reader and deployment-topology view built, verified on
  egeria-workspaces (68 ports, 38 wires across 18 topologies).
- **`Repo classification — what the repo represents`** — done. Step, catalog entry, Egeria
  survey definitions, and the card.
- **`(original entry) the scorer cannot express a partial component match`** — superseded by
  finding 73, which is marked DONE two entries above it. Three entries describe one item.
- **`repo_classification declares fetch_cost="none"`** — fixed (`api_heavy`, plus the
  org-listing and 5x-resolution optimisations: ~10 min/repo → ~25s median).

The pattern: entries are appended when found and rarely struck when closed, so the file grows
monotonically and its length stops meaning anything. This document is subject to the same
failure — its own §2.2 was wrong within an hour of being written. Worth a pass that marks closures in place
— the file already does this well where it has been done (`~~struck~~` with the resolving
commit named).

---

## 5. What was built today, for the PR description

Presentation layer:

- `result_status.py` — six reader states (`measured` / `nothing_found` / `not_established` /
  `never_run` / `skipped_by_design` / `misgrouped`), deliberately separate from
  `step_outcome.py` because a run asks "is my zero provable?" and a reader asks "what should I
  do about it?"
- Empty states that name which kind of empty they are. Previously one string —
  *"No results yet — click Run to scan"* — served three situations and asserted the one that
  was usually false; measured wrong for 51 persisted outcomes.
- The `repo_classification` card (roles ranked, gate with reason, artifacts grouped by
  **where they are**, not whether they exist).
- The deployment topology view (per-deployment, "declared startup dependencies, not data
  flow" stated on the view).
- `manifest_parse` had a render mode declared and no renderer, showing "No results view for
  this analysis" while holding 61 dependencies.

Instrumentation and infrastructure:

- `step_cost_observer.py` — observed vs declared cost per step; reports, never corrects.
- **First CI in this repository**, with `RE_REQUIRE_POSTGRES=1` so a misconfigured service
  fails the job instead of silently skipping the integration tier.
- All three production stores moved off SQLite; `remove()` had been raising
  `ForeignKeyViolation` on Postgres for every surveyed project.

---

## 6. The one thing worth carrying forward

Nearly every defect found today was the same shape: **something produced a result nobody could
distinguish from nothing.** A chart reading a deleted SQLite file; a security check searching a
table that could not contain its answer; ports computed and never stored; a step declared
zero-fetch that blocked on the network; and — twice — the *measuring instrument* having the
bug. The cheap check that kept working was asking **"who calls this, outside its own tests?"**
and **"what would this look like if it were broken?"**
