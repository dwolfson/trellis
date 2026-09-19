# PLAN — Prefect, or an alternative: an architecture decision for RE's orchestration layer

**Status:** proposal, 2026-09-18. Written against branch `re/plan-execution-modes-and-prefect`
(worktree `wt-orchestration-plan`, branched from `647cd1b4`). Nothing here is built.

Answers the Backlog entry *"TIER 1 — Prefect: what's actually broken, concretely, for the project
owner who wants to use it"*, raised 2026-09-18, and the stated want behind it: orchestration
tooling, integration connectors, and observability.

**Recommendation up front: finish Prefect. It is much closer than the Backlog entry implies —
close enough that the honest phase-1 estimate is under two days — and none of the alternatives wins
by enough to pay for a migration.** The reasoning, the measurements it rests on, and the things
that could still overturn it are below.

---

## 1. What is actually true today, measured rather than recalled

Everything in this section was checked on 2026-09-18 against this worktree and against the running
machine. Where it contradicts the Backlog entry, the measurement is stated and so is the
contradiction.

### 1.1 The leak is fixed, and it is fixed in the right place

The 2026-09-04 revert to off-by-default was caused by Prefect's own client starting an ephemeral
subprocess server it never reaped. `PREFECT_SERVER_EPHEMERAL_ENABLED=false` is now forced at
**package import** (`resource_explorer/__init__.py:6-21`) with a second guard at
`surveyors/prefect_adapter.py:6-33`, and the import-time placement is what makes it cover
`web/routes/prefect_status.py`, which imports `prefect.client.orchestration` independently. The
adapter's fallback branch was also reworked to call `run_surveyor_step_task.fn` — the undecorated
function — rather than the `@flow`, precisely so the fallback needs no Prefect engine and therefore
no server, ephemeral or real (`prefect_adapter.py:202-224`).

**So the reason `enabled` defaults to `False` no longer exists.** The default is a scar, not a
constraint.

### 1.2 The three container gaps: one is already closed, one is a config value, one is real

The Backlog entry lists three gaps in `egeria-workspaces-fs`'s
`compose-configs/optional-associated-runtimes/prefect/docker-compose.yaml`. Checked against the
running machine:

| Gap (as filed) | Measured 2026-09-18 | Verdict |
|---|---|---|
| Work-pool name mismatch: container serves `egeria-pool`, RE defaults to `default-agent-pool` | Real. The compose worker runs `--pool egeria-pool`; `config.py:340` defaults `work_pool` to `default-agent-pool`. But it is `Field(..., alias="PREFECT_WORK_POOL")` — an env var, and `cli/main.py:2316` and `:2333` both read it. | **Config value, not code.** One `.env` line. |
| The worker container has no access to the `resource_explorer` package | Real. Its image installs only `pyegeria`, `rich`, `pandas` (`runtime-volumes/prefect/user_code/requirements.txt`) and bind-mounts only `user_code`. | **Real — and §3 avoids it rather than fixing it.** |
| Unconfirmed whether a `prefect` Postgres database/role is provisioned | **Closed.** `egeria-shared-postgres` has a `prefect` database and a `prefect_user` role. The compose URL's port 5442 matches shared-infra's own `-p 5442`. | **Already done.** |

### 1.3 The container is not hypothetical — it is running right now

The Backlog entry says the container "isn't started". It is:

- `egeria-optional-prefect-server` (`prefecthq/prefect:3-python3.12`) and
  `egeria-optional-prefect-worker` are both **Up**, `restart: always`.
- `GET http://localhost:4200/api/health` returns `true` from the host.
- The work pool `egeria-pool` exists and its `updated` timestamp moves — the worker is
  heartbeating.
- Two deployments exist (`glossary-inspector`, `postgres-inspector`), both from
  `egeria-workspaces-fs`'s own example flows. **RE's `re-survey-step-deployment` is not among
  them** — nobody has ever deployed RE's flow to this server.

RE's own default `PREFECT_API_URL` is `http://localhost:4200/api` (`config.py:317`), which is
exactly where that server answers. **RE is one `.env` edit and one `prefect deploy` away from a
live server.**

Maintenance status, since the entry asks: the compose config's last three commits in
`egeria-workspaces-fs` are all dated **2026-07-14**. Untouched for two months, but running
continuously and pinned to a maintained upstream image tag. "Not actively developed" is fair;
"unmaintained" is not, and it is the same repo and the same sole contributor as RE, so the
maintenance question is really "will the project owner keep it", not "will a third party".

### 1.4 The publishing path is more finished than filed

The entry describes `dr_egeria_survey_publisher.py` as an unfinished publishing path. The
**renderer is complete**: `PublishableStep.executes_at` exists (`:57`), it is rendered into the
Dr.Egeria markdown block (`:90`), and `tests/test_dr_egeria_survey_publisher.py` covers it.
`generate_repo_survey_definition.py:196` declares `PREFECT_ROUTED_STEPS = {"repo_arch_coupling"}`
and `:203` sets `executes_at="prefect"` for it.

What has not happened is the **run** — a human-in-the-loop Dr.Egeria execution against a live
Egeria to publish the step with that property, as `Backlog.md:3700-3703` says. That is an
operation, not a code gap, and per the project owner's 2026-09-13 ruling, writing to the dev
platform is an ordinary shared write.

### 1.5 The deployment mechanism constrains where the worker can live

`cli/main.py:2298-2320` deploys via `re_survey_flow.from_source(source=<this checkout's
packages/resource-explorer>, entrypoint=...)`. That is a **local filesystem path**. A worker
running inside a container cannot resolve it unless the checkout is mounted at the identical path
and the package's dependencies are installed in the image. This is not a bug — the comment at
`:2301-2308` explains it was the deliberate right shape for a `process`-type pool on the same
machine — but it is the fact that decides §3's topology.

### 1.6 The gap Prefect does not close, and no orchestrator would

`executes_at: egeria` steps are coordinated by Egeria's own engine host. RE gets an engine-action
GUID and nothing else — no flow run, no local thread, no activity-log progress
(`web/routes/prefect_status.py:1-10` states this scope boundary in the module docstring itself;
`survey_definition_executor.py:473-486` is the code). **No choice of workflow engine changes
this.** It is an Egeria-side async-result problem (`survey-model.md` §D5, still *Proposed*) and it
belongs to `PLAN-EXECUTION-MODES-VERIFICATION.md` §2 Path B, not here. Naming it matters because
"adopt an orchestrator and get observability" is only true for the steps RE runs.

---

## 2. What closing the remaining gaps actually takes

Given §1, the list is short:

| Work | Effort |
|---|---|
| `.env`: `PREFECT_ENABLED=true`, `PREFECT_API_URL=http://localhost:4200/api`, `PREFECT_WORK_POOL=<pool>` | minutes |
| Create a `resource-explorer-pool` (process type) on the running server and start a **host** worker for it via `make prefect-up`, reduced to the worker+deployment steps | ~0.5 d |
| `resource-explorer prefect deploy` against the container server; confirm `re-survey-step-deployment` appears | minutes |
| One real end-to-end run of `repo_arch_coupling` through Prefect; confirm the result comes back through `state.result()` and is **not** silently re-run locally (the 2026-08-26 failure mode — `prefect_adapter.py:119-129`) | ~0.5 d |
| Publish the `executes_at: prefect` step to dev Egeria via the Dr.Egeria run (§1.4); coordinate the shared write first | ~0.5 d |
| Decide and document `PREFECT_ROUTE_LOCAL_STEPS` (see §5 phase 3) | ~0.5 d |

**~2 days to a working, observable, non-default-on Prefect integration.** Compare with the
Backlog entry's framing — three container gaps, an unfinished publisher, an undecided default —
which reads like a multi-week commitment. It is not, because two of the three gaps were already
closed by other work and nobody had re-measured.

**What is not in that estimate, and should be named:** making the *containerized* worker able to run
RE steps (gap 2 in §1.2). §3 recommends not doing that yet.

---

## 3. Recommended topology: container server, host worker

Not the obvious "containerize everything", and the reason is `from_source` (§1.5).

- **Prefect server: the existing container.** Already running, `restart: always`, backed by the
  shared Postgres, survives reboots. This retires the "nothing auto-starts these after a reboot"
  objection in `scripts/prefect_up.sh`'s closing comment without Trellis having to containerize
  anything.
- **Worker: a host process in the Trellis checkout**, on its own pool (`resource-explorer-pool`,
  not `egeria-pool` — RE's flows and egeria-workspaces' example flows should not share a pool and
  cannot share an image). The host worker already has the `resource_explorer` package importable
  via `uv run --package resource-explorer`, which is precisely what gap 2 is about. Gap 2 is
  therefore **avoided, not fixed** — an honest deferral, recorded here so it is not rediscovered.
- **Revisit when Trellis containerizes.** At that point the worker moves into a Trellis-built image
  and the deployment moves from `from_source(local path)` to a Docker or git source. That is the
  right time to fix gap 2 properly, and it is a consequence of the containerization decision rather
  than a blocker for it.

---

## 4. Alternatives, and why they lose

Three were considered seriously. This is not a shortlist assembled to justify a conclusion — the
third one nearly wins, and the reason it does not is worth stating.

### 4.1 No workflow engine — structured logging plus a lighter task queue

**The strongest challenger.** RE's actual scale is a single-operator tool: one web process, a
900-second scheduler loop (`scheduler.py`), surveys measured in seconds to a couple of minutes,
and a fallback path that runs every step perfectly well in-process. Nothing here needs distributed
scheduling. The `activity_log` already records every operation by design rule 16, and steps already
report `ok`/`error`/`cancelled`/`skipped_by_design` per `result_status.py`.

**Why it still loses:** it is not free, it is *deferred cost*. Retries, per-task logs, cancellation
of a running step, and a UI showing what is in flight are exactly what the project owner asked for,
and each one is real work to build and own. The Cancel button in the Admin "⚡ Prefect" panel was
verified live to actually stop a running step (`Backlog.md:3706-3712`) — reimplementing that over
threads is not a small afternoon. Choosing this option means choosing to build a small orchestrator
badly. It would be the right call if Prefect's integration were weeks away; §2 says it is ~2 days.

### 4.2 Dagster

Already running on this machine (`egeria-optional-dagster-webserver`/`-daemon`), with a `dagster`
database on the shared Postgres — so "is it available here" is not the discriminator.

**Why it loses:** Dagster's model is software-defined *assets*, and RE's unit of work is a *step in
a governance-action-process graph defined in Egeria*, not a materialised table. Egeria is already
the asset model; adding a second, competing asset model is the wrong kind of duplication. It would
also throw away every piece of working Prefect integration for a model that fits worse.

*(Web-sourced and unverified here: Prefect announced an acquisition of Dagster Labs in July 2026,
with both products continuing under their own names. If accurate it weakens Dagster as the
"different vendor" hedge, but it should not carry weight in this decision until confirmed.)*

### 4.3 Temporal

**Why it loses:** Temporal is built for durable, long-running, exactly-once business workflows with
compensation — crash-safe state machines. RE's surveys are short, idempotent, and safe to re-run;
its actual durability problem is elsewhere (the outbox drain that does not serialise,
`Backlog.md`'s own entry). Temporal's operational footprint is the largest of the three, its Python
authoring model is the furthest from RE's `@task`-wrapped functions, and its integration-connector
story is the weakest of the candidates — which is one of the three things the project owner
explicitly asked for.

### 4.4 Airflow — not seriously considered, and why

An `airflow` database and an `airflow-marquez` compose config exist in the same optional-runtimes
directory, so it is technically at hand. It is the heaviest of the four, its DAG model is the least
compatible with a step graph that is *read from Egeria at runtime*, and `docs/survey-execution.md`
§3 already compared and rejected it in 2026-07. Nothing has changed to reopen that.

---

## 5. Recommendation and phased path

**Finish Prefect.** It is ~2 days of work (§2) against a server that is already running (§1.3), the
leak that caused the revert is fixed at the right layer (§1.1), the routing honours `executes_at`
rather than overriding it (`survey_definition_executor.py:317-332`), and the three candidates that
could displace it either fit RE's model worse or cost more than the work remaining.

| Phase | What | Effort | Gate |
|---|---|---|---|
| **1** | Topology per §3: `resource-explorer-pool` on the container server, host worker, `prefect deploy`, `.env`. Prefect **stays off by default**; this only makes "on" real. | ~1 d | — |
| **2** | One real end-to-end `repo_arch_coupling` run through Prefect, plus the dev-Egeria Dr.Egeria publish of the `executes_at: prefect` step (§1.4). Coordinate the shared write first. | ~1 d | 1 |
| **3** | Decide `PREFECT_ENABLED`'s default. Recommendation: **on** once phase 2 passes, because `enabled` alone no longer reroutes anything that did not ask for Prefect. `PREFECT_ROUTE_LOCAL_STEPS` stays **off** — the per-step overhead is real and unmeasured. | ~0.5 d | 2 |
| **4** | Measure, then decide. Instrument per-step overhead of the Prefect route against the in-process route on the same step, and record the number in `Backlog.md`. Everything said about `route_local_steps` today is an estimate. | ~1 d | 3 |
| **5** | Widen `PREFECT_ROUTED_STEPS` beyond `repo_arch_coupling` only if phase 4's number justifies it. | ~0.5 d/step | 4 |
| **6** | Revisit on containerization: worker into a Trellis image, deployment off `from_source(local path)`, gap 2 fixed properly (§3). | — | Trellis containerization |

**Decisions needed (project owner):** ~~(a) accept the container-server/host-worker split, or hold
out for a fully containerized worker~~; (b) `PREFECT_ENABLED` default after phase 2; (c) whether
phase 5 is wanted at all, or `executes_at: prefect` stays a narrow opt-in for genuinely
long-running steps.

**Decision (project owner, 2026-09-19):** keep the container-server/host-worker split (option 1),
including for development machines, not only demo ones. Raised while exploring why Trellis isn't
fully containerized — that question is really two independent problems, and this decision answers
only the Prefect-specific one:

- **GPU passthrough (Ollama/embedding inference) is the reason full containerization is deferred
  generally**, and does not apply here — `repo_arch_coupling` and RE's other survey steps do no
  GPU work; the constraint that drove the dev/demo profile split
  ([[trellis-target-environments]]) is irrelevant to this worker specifically.
- **The actual blocker for a containerized worker is packaging**, not performance: the existing
  container image (`egeria-workspaces-fs`'s, not RE's own) only installs `pyegeria`/`rich`/`pandas`.
  Bind-mounting RE's checkout into it was considered and rejected — it would still require
  installing RE's full dependency stack inside that container (drifts from what `uv sync`
  maintains on the host) and couples two repos' compose configs awkwardly (a dependency change in
  RE would require touching a container `egeria-workspaces-fs` owns).
- **On a Mac dev machine specifically, a bind-mount would also be slower**, not just more work:
  Docker Desktop for Mac's bind-mount filesystem (gRPC-FUSE/VirtioFS) has real I/O overhead, and
  `repo_arch_coupling`'s git-history walk is exactly the kind of workload that pays for it.
- The properly-fixed version (a Trellis-owned worker image with dependencies baked in at *build*
  time) remains phase 6's answer, gated on Trellis containerizing more broadly for its own
  reasons — not something a bind-mount shortcuts around.

---

## 5a. Phases 1 and 2 — done, 2026-09-19

**Phase 1.** `resource-explorer-pool` (process type) created on the running container server —
kept separate from `egeria-workspaces-fs`'s own `egeria-pool`, per §3. `RE Survey Flow/re-survey-
step-deployment` deployed against it. A host worker is running (`uv run --package
resource-explorer`, so `resource_explorer` is importable — gap 2 from §1.2 avoided as planned, not
fixed) and confirmed `ONLINE` and heartbeating via the API. `.env`'s `PREFECT_WORK_POOL` now points
at it; `PREFECT_ENABLED` stays `false`, as this phase only makes "on" real. One thing worth naming
now rather than waiting for phase 4: the worker logged a real version-mismatch warning (server
3.7.8, client recommends 3.8.1+) — the §6 risk was not hypothetical, though phase 2 found no actual
problem from it.

Also done as part of this phase: the Egeria-side publish from §1.4/§2 phase 2, coordinated as a
shared write with all three live peers first. Ran only the single `Create Governance Action
Process Step` block for `repo_arch_coupling` (no link commands — zero duplication risk) via
Dr.Egeria; it resolved as an **update** to an already-existing element (GUID
`6406cf97-b46d-4c6d-b373-2970f74043ee`), confirming the outbox/`check_and_heal` mechanism had
already published this document at least once before this session. Verified independently via
`SurveyDefinitionReader.find_process_guid_by_name()` resolving the same GUID through a separate
code path. `reconcile_survey_definition_links.py --dry-run` confirms all 10 Survey Definitions
clean (42/42 edges correct on `RepoFullSurvey`) — nothing to reconcile.

**Phase 2's live run — the plan's own named highest-risk item — passed cleanly.** Dispatched
`run_prefect_step("repo", "egeria_python_git", "repo_arch_coupling", {})` with `PREFECT_ENABLED`
scoped to that one process only (never written to `.env`, the shared live web server untouched).
Result: a real flow run (`571cfe66-e636-4caf-ac92-acab06f075d5`) completed in ~25.6s, tagged
correctly, `state.result()` returned the step's real annotation — no `Prefect API dispatch failed`
fallback warning. **The crux check — no silent duplicate local execution — passed**: the worker's
own log shows it executed the task, and the registry's `coupling_component_count` metric gained
exactly one new row timestamped inside the flow run's execution window, not duplicated.

**Phase 3 (`PREFECT_ENABLED`'s default) is now unblocked** — its gate ("once phase 2 passes") is
satisfied. That decision, and the container-server/host-worker topology it depends on, still need
the project owner's sign-off per the decisions list above.

---

## 6. Risks and unknowns — what could not be verified from the code

Listed plainly, because each one could change the recommendation.

- **RE's flow has never actually run on this server.** §1.3 confirms the server, the pool and the
  worker heartbeat; it does not confirm that `re-survey-step-deployment` deploys cleanly against
  *this* server or that a run completes. Phase 1 is where that becomes known, and it is the most
  likely place for an unpleasant surprise.
- **Prefect's running cost at RE's scale is unmeasured.** The claim that routing every local step
  through Prefect "multiplies overhead" appears repeatedly in `Backlog.md` and is, as far as this
  pass could tell, an estimate rather than a measurement. Phase 4 exists to fix that. If per-step
  overhead turns out to be small, §4.1's challenger weakens further; if large, `route_local_steps`
  should probably be deleted rather than left as a tempting switch.
- **Server maintenance is a single-contributor question.** The compose config has not been touched
  since 2026-07-14 (§1.3). It is the project owner's own repo, so this is a question about
  attention, not abandonment — but RE would be taking a dependency on a component in another repo
  that nothing in Trellis's CI exercises.
- **The container server is shared.** It already hosts `egeria-workspaces-fs`'s own deployments. A
  separate pool keeps execution separate; it does not keep the *server* separate. A Prefect server
  restart or a database problem affects both. Not a reason to avoid it — a reason to not treat it
  as RE-owned infrastructure.
- **Prefect's integration-connector story was not evaluated against a concrete RE need.** The
  project owner named "integration connectors" as a reason to want Prefect. This pass found no RE
  code that consumes any Prefect integration library; the value is prospective. If there is a
  specific connector in mind, it should be named — it could change the comparison in §4 more than
  anything else in this document.
- **Version drift.** `prefect_adapter.py:119-129` documents an API that changed underneath this
  integration once already (`resolve_value` → `State.result()`), found only because a live run was
  attempted. The container is pinned to a moving `3-python3.12` tag while the host venv has its own
  pinned version. A version mismatch between the two is a real, unchecked hazard — phase 1 should
  compare them.

---

## 7. Where this document disagrees with the Backlog entry

Recorded explicitly so the Backlog can be corrected rather than silently diverging.

1. **"A container already exists... and isn't started"** — it is running, healthy, and reachable at
   the exact URL RE defaults to (§1.3).
2. **Gap 3 (Postgres database/role) is "unconfirmed"** — confirmed present (§1.2).
3. **Gap 1 (work-pool mismatch)** is real but is an env var, not a code change (§1.2).
4. **"unfinished `dr_egeria_survey_publisher.py` publishing path"** — the renderer is complete and
   tested; what is outstanding is a human-in-the-loop run (§1.4).
5. **The `_use_prefect` global-override concern** (`Backlog.md:3661`) was fixed; `executes_at` is
   honoured and rerouting needs `route_local_steps` (§1, and
   `PLAN-EXECUTION-MODES-VERIFICATION.md` §0).

The entry's central judgement — that this was never scoped into a real plan and that "off by
default" had become an unexamined steady state — was correct, and is what this document responds
to.
