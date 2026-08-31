# Outbox / retry publishing — design

**Status:** steps 1-4 are BUILT for the **repo** path — which is all Phase 2 needs (§6 step 4's
own scoping). **D1 settled: per element** (Dan, 2026-08-31). Database, filesystem and
investigation publishers still call Egeria directly. Written 2026-08-28 to unblock
`architecture-recovery-design.md`
§8.4, which names this as the sole remaining prerequisite for Phase 2 (Egeria projection of
recovered architecture) and is blunt about why: *"a half-published blueprint is worse than none."*

**Two decisions in §4 need Dan before this is built.** Everything else here is settled by what the
code already does.

---

## 1. What "fire-and-forget" actually means here — measured, not assumed

§8.4 cites the current-state doc §0 for "RE's publishers are fire-and-forget today". That phrase
does not appear in that document; it is the design author's own characterisation. The
characterisation is **correct**, but it was re-derived from the code rather than taken on trust,
because the cited source does not say it.

Dispatch is not the problem. Every publish call is awaited synchronously by its caller — thread
offload via `asyncio.to_thread`, but the HTTP handler, background thread or scheduler tick blocks
on the result. **The problem is entirely in error handling**, at three levels:

**Per element.** `EgeriaPublisher._create_annotations` (`surveyors/egeria_publisher.py:532`) loops
annotations and swallows each failure individually:

```python
try:
    self._discovery.create_annotation(body=body)
except Exception as exc:
    log.warning("Failed to create annotation %d (%s): %s", i, ann.annotation_type.value, exc)
```

A failed annotation does not stop the loop, does not raise, and does not fail `publish()`. **The
SurveyReport is reported published, with a report GUID, even if every annotation under it failed
to write.** The identical pattern is duplicated in the database publisher
(`surveyors/database/egeria_database_surveyor.py:835`) and the filesystem publisher
(`surveyors/filesystem/egeria_filesystem_surveyor.py:567`).

**Per publish.** Every call site catches `Exception`, logs, and records `published: False` with an
error string — leaving whatever was already created in Egeria in place. This is deliberate and
documented at `web/routes/projects.py:712`: *"Publish failure must not turn an otherwise-successful
survey into a reported error."* That intent is right; it is the absence of anything that later
finishes the job that is the gap.

**Per process.** If the process dies mid-publish, `run_reconciler.py:123` marks the orphaned
`activity_log` row `interrupted` and stops there — correctly, per its own docstring: *"We know the
run stopped; we do not know it failed."* Nothing resumes the publish.

`guard_linkage` (`egeria_linkage.py:159`) wraps the sequence but is **not** a transaction — it
reclassifies unknown-GUID errors into a named `StaleEgeriaLinkageError` and performs no
compensating writes.

**Net:** no transaction, no rollback, no resume, no retry, and — for annotations — no idempotency.

## 2. The write surface a retry layer has to cover

Five publisher families, all of which Phase 2 will drive:

| Publisher | Entry points |
|---|---|
| Repo — `surveyors/egeria_publisher.py` | `publish()` `:103`, `publish_sub_resources()` `:556` |
| Database — `surveyors/database/egeria_database_surveyor.py` | `publish_step_annotations()` `:293`, `publish_local_survey()` `:645` |
| Filesystem — `surveyors/filesystem/egeria_filesystem_surveyor.py` | `_create_data_file_asset()` `:525`, `_create_annotations()` `:567` |
| Investigation — `surveyors/egeria_investigation_publisher.py` | `promote()` `:104`, `relink_members()` `:238`, `sync_project_properties()` `:362` |
| RFA → ToDo — `rfa_egeria_sync.py` | `sync_rfa_action()` `:67`, `sync_rfa_note()` `:134` |

A single repo `publish()` performs, in order: find-or-create asset → homepage ExternalReference
(best-effort) → SurveyReport → **N** annotations. A blueprint publish writes far more than that,
which is why §8.4 gates Phase 2 on this.

Consequence for placement: the layer belongs **below** the individual `create_annotation` /
`create_asset` calls, generically — not reimplemented in each of the three publishers that already
carry near-duplicate `_build_annotation_props` and `_create_annotations` methods. The current-state
doc's finding #2 ("there are three publishers, not one") is confirmed still true, and this work is
the natural moment to collapse that duplication rather than triplicate a new mechanism.

## 3. What already exists — and the one working precedent

**There is no general outbox today.** What exists, and why each is not one:

| Table | What it is | Why it isn't an outbox |
|---|---|---|
| `rfa_actions` (`registry.py:1436`) | `egeria_todo_guid`, `synced_at`, `sync_error`, `egeria_notelog_guid`, … | **The closest thing — and a working one**, but scoped to RFA→ToDo only |
| `egeria_linkage_status` (`registry.py:1425`) | divergence detection — `status`, `stale_guid`, `detected_at` | Records "this GUID is stale", not "this write is pending" |
| `project_published_annotation_types` / `_analyses` (`registry.py:836`) | written *after* the Egeria write, for the "last published" badge | Post-hoc bookkeeping |
| `activity_log` (`registry.py:1281`) | audit trail; `status` ∈ running/ok/error/interrupted | Written during/after the operation; nothing reads it to retry. `get_survey_definition_last_activity` (`:5045`) only *derives* "last published" from history — it creates no state |
| `project_egeria_surveys` (`registry.py:799`) | `(slug, surveyed_at, report_guid, annotation_count)` after the report succeeds | Read-cache for the pull path |

**The precedent to copy is `rfa_actions`.** `reconcile_rfa_actions()` (`rfa_egeria_sync.py:220`),
driven every ~900s by `scheduler.py`'s hand-rolled loop, retries every row where
`sync_error != '' OR egeria_todo_guid == ''`. That is local-authoritative write + best-effort
remote sync + periodic reconcile — exactly the shape this needs, already shipping in this codebase.
Its gaps, which a general version must not inherit: **no backoff, no max-attempts, no dead-letter.**

There is no `tenacity` or `backoff` dependency anywhere, and no Prefect `retries=` configured on
any flow. `AgentsConfig.max_retries = 10` (`config.py:139`) is the BeeAI LLM tool-call loop and is
unrelated.

## 4. Two decisions needed — Dan

### D1. Outbox granularity — SETTLED 2026-08-31: per element

*Per publish* — one row per `publish()` call, retried whole. Simple, few rows, and matches how
callers already think. But retrying the whole call re-creates elements that already succeeded,
which is only safe once **every** write is idempotent (see D2).

*Per element* — one row per element write (asset, report, each annotation, each wire). Many more
rows, but a retry resumes exactly where it stopped, and "no half-published blueprint" is a claim
about elements, not calls. Given `_create_annotations` currently swallows failures per item, the
failure granularity that already exists is per-element.

**Recommendation: per element.** It is the granularity the failure mode already has, and it is the
only one that makes "half-published" observable rather than inferred.

**Volume, measured 2026-08-31 rather than estimated.** Two very different regimes:

| | rows |
|---|---|
| All 68 publishes ever performed, per-element (627 annotations + ~3 structural each) | **831 total** |
| One future blueprint publish on `egeria_git` (13,813 scoped findings — the earlier "945" was wrong and far too low) | **~14,000 per run** |

So per-element is free for everything publishing today and expensive only for the blueprint case
that does not exist yet. Retention policy is therefore not needed on day one for correctness, but
is needed before Phase 2 turns on — and the second column is the number that decides it, not the
first.

### D2. Annotation identity — CORRECTED 2026-08-29, and it is much smaller than this section first said

**What this section originally claimed, and why it was wrong.** It said annotations have no stable
identity at all — the run timestamp defeats convergence, the positional `{i}` is not an identity,
and no substitute exists (134 annotations against 7 distinct annotation types on
`egeria_workspaces_git`). It concluded that D2 was a change to the annotation *model* and blocked
the whole item.

That conflated two different things:

1. **Retrying one publish** — the case an outbox actually serves.
2. **Converging a later survey run onto an earlier one's annotations** — which Egeria's survey model
   does not want and never asked for.

**For (1), the identity is already stable.** `SurveyResult.surveyed_at` is
`field(default_factory=datetime.utcnow)` — stamped when the result is *constructed*, at survey
time, not at publish time. An outbox stores the payload, so a retry replays the same
`surveyed_at` and the same list order, and therefore produces **byte-identical qualifiedNames**.
The timestamp is not a defect here; it is the run's identity, which is exactly what
`Annotation::{slug}::{surveyed_at}::{i}` is for. The positional index is likewise stable within a
stored payload.

**For (2), divergence is correct behaviour, not a bug.** A `SurveyReport` *is* a dated record of one
act of analysis. Each run legitimately mints its own report with its own annotations beneath it —
visible in RE's own bookkeeping, where `deep_causality` carries 10 distinct `egeria_report_guid`
values over three days. Making a later run's annotations converge onto an earlier run's would
*destroy* survey history, which is the opposite of what §7 of the report-then-curate note wants.
The 134-vs-7 collision measurement was real but answered a question that does not need asking.

**What is actually missing, and it is a publisher-layer fix.** `_create_annotations` calls
`create_annotation` blind — no lookup first — whereas `_find_or_create_asset` searches by
qualifiedName before creating (`egeria_publisher.py:277`) and `publish_sub_resources` does the same
via `_find_element_guid`. So the failure mode is narrow and concrete: **a crash after Egeria wrote
the annotation but before the outbox recorded the success**. Replaying that row creates a second
annotation with the same qualifiedName.

**Settled by Dan, 2026-08-29 — search by qualifiedName; do not rely on a uniqueness error.**
Egeria identifies an element primarily by **GUID**; qualifiedName should also be unique, and the
supported way to avoid re-creating something is to **search by qualifiedName first and see whether
it already exists**. So the apply step needs no live-server experiment on rejection behaviour, and
must not be built on one — depending on a duplicate-create failing would rest on an error path
rather than the documented mechanism, and would misread any *other* failure as "already applied".

That leaves exactly one change: **generalise lookup-then-create to annotations** — step 2 of §6
anyway, the same helper the three duplicated `_create_annotations` implementations should share, and
precisely what `_find_or_create_asset` and `publish_sub_resources` already do.

Once a row records the GUID it resolved to (`egeria_guid` in the §5 sketch), later retries of that
row need no search at all: the GUID is the primary identity, and the qualifiedName search is only
how a row that never recorded one finds out whether it nonetheless landed.

**Net effect on this item: D2 no longer blocks it.** It is a publisher-layer change of the same size
as the deduplication already planned, not a redesign of the annotation model.

## 5. Sketch, assuming D1 = per element

```
egeria_outbox
  id, entity_type, entity_slug, run_id
  element_kind        -- asset | report | annotation | relationship | ...
  qualified_name      -- the idempotency key; NOT NULL
  payload_json        -- the body the pyegeria call needs
  depends_on_id       -- ordering: annotations after their report
  status              -- pending | in_flight | done | failed | dead
  attempts, next_attempt_at, last_error, created_at, completed_at
  egeria_guid         -- filled on success
```

* **Write-then-publish.** The publisher enqueues rows inside the same local transaction that
  records the survey, then drains. A crash between the two is then impossible, which is what
  closes the §2 "per process" hole.
* **Drain** on the `scheduler.py` loop that already drives `reconcile_rfa_actions()` — no new
  runtime, and it already runs everywhere publishes originate.
* **Ordering** via `depends_on_id`: a row is eligible only when its dependency is `done`. This is
  what makes "no half-published blueprint" enforceable rather than aspirational.
* **Backoff and dead-letter**, both of which the `rfa_actions` precedent lacks: exponential
  `next_attempt_at`, a max-attempt count, then `dead` — surfaced as an RFA so a stuck publish is
  visible to a human instead of retrying silently forever.
* **Idempotent apply**: look up `qualified_name` before create; adopt the existing GUID if found.
  This is `_find_or_create_asset`'s behaviour generalised — the same change D2 now reduces to.

## 5a. What report-then-curate changes here

`architecture-recovery-report-then-curate.md` (2026-08-29) replaces Phase 2's structural projection
with publishing a **proposal** as annotations, materialised into real blueprints and components only
when a curator accepts. That does **not** relax this item — it tightens it. Annotations are Egeria
writes too, and under that model they are the *only* carrier — so a proposal that publishes half
its annotations misrepresents the analysis, and the atomicity this item provides is what stops that.

**Note the correction in D2:** a proposal republished on every re-derivation is *not* an identity
problem. Each re-derivation is a new survey run, so it legitimately mints a new `SurveyReport` with
its own annotations; that is what a survey report is. Only a *retry of one publish* has to converge,
and there the stored payload replays an identical qualifiedName.

## 6. Sequencing

1. ~~**Generalise lookup-then-create to annotations** (D2, settled)~~ — **DONE**, `c7e99f6`.
   `surveyors/annotation_props.py`'s `publish_annotations()` looks up `find_element_guid(qn)`
   before creating and skips on a hit.
2. ~~Generalise into one helper the three publishers share, collapsing the duplicated
   `_create_annotations`~~ — **DONE**, same commit. All three publishers' `_create_annotations`
   are now thin wrappers that build their own qualifiedName prefix and delegate; each is kept as
   a method only because tests reach for it by name.

   **Still open from §2, deliberately:** `publish_annotations` retains the per-element swallow —
   a failed annotation is logged and the loop continues. That is the hole the outbox closes, and
   it was left alone rather than changed to raise, because raising without a retry layer would
   turn a partial publish into a failed survey.
3. ~~`egeria_outbox` table + drain on the existing scheduler loop, with backoff and
   dead-lettering.~~ — **DONE**. `registry.py` owns the rows (`enqueue_outbox_element`,
   `claim_due_outbox_elements`, `mark_outbox_done`/`_failed`, `list_dead_outbox_elements`,
   `outbox_counts`, `purge_outbox_completed`); `egeria_outbox.py` owns the apply side and the
   drain; `scheduler.py`'s existing loop drives it alongside `reconcile_rfa_actions()`.

   Behaviour worth knowing before step 4 builds on it:

   - **Ordering is enforced, not advisory.** A row with `depends_on_id` is not returned by
     `claim_due_outbox_elements` until its dependency is `done` — a *failed* dependency keeps
     blocking. A partial drain therefore leaves a coherent prefix, never an annotation whose
     report was never written.
   - **Backoff** is exponential from 60s, capped at a day; **dead-letter** at 8 attempts.
   - **An unreachable platform is not a failed write.** The drain leaves every row untouched and
     reports `skipped` rather than burning an attempt, so an outage cannot dead-letter a
     perfectly good write.
   - **An unregistered `element_kind` raises** rather than quietly succeeding. Only `annotation`
     has a creator today; asset/report/relationship are registered as step 4 needs them.

   **Logging is not a surface here — measured 2026-08-31.** Nothing in this package configures
   logging, and `uvicorn.run()` (`cli/main.py:327`) is called without a `log_config`, so uvicorn
   configures only its own `uvicorn.*` loggers. Application records fall through to Python's
   `lastResort` handler: WARNING and ERROR reach the server's **stderr** with no timestamp and no
   logger name, and **INFO is discarded outright** — which silently included the drain summary
   line as first written. So `drain_outbox` now calls `record_drain_outcome`, writing failures and
   dead-letters to the **activity log**, which the Activity tab already reads. A clean pass writes
   nothing: an entry every quarter-hour saying nothing was wrong is how a log stops being read.

   **Not done, and deliberately:** a dead row is surfaced through `list_dead_outbox_elements()`,
   an error log and now an activity entry, but not yet as an RFA. `rfa_actions` rows hang off an `activity_log` entry
   (`entry_id`, `annotation_index`), so raising one from a dead outbox row is its own small
   integration rather than a line of code.
4. **Repo publisher migrated — DONE.** `EgeriaPublisher._create_annotations` now enqueues one
   outbox row per annotation and drains inline, instead of calling `publish_annotations`
   directly.

   **The asset and the SurveyReport stay synchronous, deliberately.** `publish()` returns the
   report GUID and callers record it, so those two cannot become deferred work without breaking
   that contract — and they do not need to. They are single elements whose failure aborts the
   publish outright; annotations are the plural part, the part that swallowed failures per
   element, and therefore the part where "half-published" actually happened.

   **The happy path is byte-for-byte unchanged.** Rows are enqueued and drained within the same
   call, so a successful publish still writes everything before returning. What changed is the
   unhappy path: a failed annotation is now a durable row the scheduler retries with backoff,
   rather than a warning in a log nobody reads. `_create_annotations` still does not raise —
   `publish()`'s contract that a publish problem must not turn a successful survey into a
   reported error is unchanged. The difference is that the work is no longer *lost* when it is
   swallowed.

   **The inline drain is scoped by `run_id`.** An unscoped claim takes the oldest due rows in
   the table, which could be an entirely different resource's backlog — the publisher would then
   return believing it had published while having drained someone else's queue. Found while
   writing this, not in production; `TestRunScoping` pins it.

   Falls back to the direct path when the publisher has no registry, since there is then nowhere
   to record a row and silently skipping the annotations would be worse.

   **Remaining:** database, filesystem and investigation publishers. Each needs its own
   `element_kind` creators registered (`asset`, `report`, `relationship`) and is where
   `depends_on_id` starts earning its place — those paths queue the report itself, so ordering
   stops being trivially satisfied.
5. Only then Phase 2 (§10 of the recovery design).

**Note for step 4:** the two survey-launch paths still diverge on five axes (current-state doc
§1.2, confirmed still true), so a retry layer must sit under *both* — putting it under the
publishers rather than under either launcher is what makes that automatic.
