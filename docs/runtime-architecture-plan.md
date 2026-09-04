# Runtime architecture plan — threading, containerization, multi-user, LLM backend

**Status: planned, not yet built. Opus-authored design pass, 2026-09-04, grounded by a Sonnet
research pass the same day — see that pass's findings folded in below and in
`project_egeria_resource_explorer_redesign.md` (memory).**

## Context

Triggered by a real stuck-server incident on 2026-09-03/04 (RE's `resolve_question_guid()` hung
15+ seconds inside a `ThreadPoolExecutor` worker calling pyegeria's `get_guid_for_name()` via
`nest_asyncio.run_until_complete`, while a direct curl to the same Egeria platform's own origin
endpoint returned in 18ms — contained with a per-call timeout, root cause deliberately left open
for this pass). The project owner asked for this to be planned together with three other
questions rather than solved piecemeal: containerization, the multi-user transition, and whether
to move to vLLM — and asked whether the effort was worth escalating to Opus-level reasoning given
the stakes. Sonnet did the grounding (current-state facts, live hardware/Docker checks); this
plan is Opus's synthesis of the actual tradeoffs.

## Why this is one plan, not four

Everything today is single-process: RE and EA each run as one `uvicorn` process, no `--workers`,
via `uv run`. That fact is the hinge the other three questions turn on — it's *why* the threading
model is unsafe (shared mutable state, one event loop, ad hoc thread spawns with no registry),
*why* multi-user has nowhere to live (a JWT's `user_id` has no per-request-scoped place to go),
and *why* "containerize" is really "how many processes, and which ones move." Solved in dependency
order — process topology first, because it changes what "the threading fix" and "the multi-user
fix" even mean — not in the order the four questions were originally listed.

---

## 1. Process topology (the load-bearing decision)

**Recommendation: hybrid — containerize the stateless/CPU-bound tier, keep GPU-bound inference
native, and move from "one process, N ad hoc threads" to "N worker processes, no ad hoc threads,"
for both RE and EA.**

Verified live, 2026-09-04: Docker Desktop on the dev machine (Apple M3 Max, 96GB RAM) runs an
ARM64 Linux VM (`linuxkit`) — Metal is not passed through. Current research (not stale training
data) confirms this is a hard platform limit, not a maturity gap: even Docker's own
[Docker Model Runner / vLLM-on-Metal feature](https://www.docker.com/blog/docker-model-runner-vllm-metal-macos/)
works around it by running inference **natively on the host** and exposing it to containers over
the network, not by getting Metal into the container. Independent confirmation the hybrid shape is
the industry's own answer to this exact constraint.

- **Native, unchanged:** Ollama (Metal-accelerated), and an MLX-backed server if one gets built.
- **Containerized, already true today:** Postgres/pgvector, Kroki.
- **Containerized, new:** the FastAPI apps (RE, EA) themselves, Prefect if it's doing real work —
  exactly what `optional-associated-runtimes/` already exists for.
- **Discovery:** containerized app → native Ollama via `host.docker.internal:11434` (Docker
  Desktop resolves this on macOS already); containerized app → Postgres/Kroki via existing
  `egeria_network` container names — inverse of the pattern `shared-infra.yaml`'s own Kroki
  comment already documents for a host process reaching a container.

**Rejected: containerize everything, including Ollama.** Wrong for this machine specifically —
EA's own backlog already flags "Ollama GPU passthrough is Linux-only"; current research confirms
this is a macOS/Docker-Desktop constraint, not Ollama-specific, and applies to vLLM too. Falling
back to CPU inference for a 32B model turns seconds into minutes — not a tradeoff to accept
casually just because the Aug 2026 plan implicitly assumed it by putting RE next to Ollama in
`optional-associated-runtimes`.

**Rejected: stay 100% bare-metal.** Leaves Postgres/Kroki as the only containerized pieces
(status quo, two already-acknowledged-but-unexecuted TODOs), and makes the multi-user and
threading fixes *harder*, not easier — see below.

### Why this interacts with threading and multi-user

Moving from 1 process to N worker processes changes the threading fix from "add a registry and a
shared pool" to "most of the ad hoc-thread problem stops needing a fix":

- RE today: 3 daemon threads (scheduler, bootstrap monitor, cache-warm) + ad hoc per-request
  `threading.Thread`s from `projects.py`/`survey_definitions.py`/`discovery.py`/`query.py` + 6
  independent `ThreadPoolExecutor`s (several `max_workers=1`) bridging pyegeria's sync calls into
  the async loop. None coordinated — no shared pool, no limit, no live registry.
  `run_reconciler.py`'s pid-based ownership check exists specifically because there's no registry
  to ask "is this still running" after a crash.
- **N worker processes turns the 3 daemon threads into a "run in exactly one worker" problem**
  (leader-election via a Postgres advisory lock — `pg_try_advisory_lock` on startup), not a
  "coordinate a pool across all threads in one process" problem. They're global-singleton-shaped
  work (one due-schedule table, one bootstrap state) — 3 workers each running them means firing
  subscriptions 3x.
- **Per-request survey/analysis threads mostly stop being a design problem** — each worker
  process already gives the isolation a thread was faking; the OS process boundary, not a
  hand-rolled registry, is what stops one run from starving other requests. `run_reconciler.py`'s
  pid-ownership pattern is still needed (a worker can still crash mid-run).
- **The actual incident still needs a direct fix, independent of topology.** Multiple worker
  processes reduce blast radius (one hang stalls one worker's queue, not the whole server) but
  don't fix the underlying cross-thread/cross-event-loop asyncio hazard — a hung
  `run_until_complete` call still ties up whatever thread it's on. Fix: **one shared, explicitly
  bounded `ThreadPoolExecutor` per process** (not six scattered `max_workers=1` pools) for all
  sync-pyegeria bridging, keeping the per-call timeout that already contained the incident as
  defense-in-depth. **Research-first, not assumed**: confirm whether pyegeria's sync clients hold
  thread-unsafe global/session state — if so that's a second bug independent of the event-loop
  hazard, worth a deliberate spike reproducing the hang under controlled concurrency.

**Multi-user changes what "the scheduler" means too, not just where credentials live.**
Bootstrap monitor stays global (one shared Egeria platform's health, leader-elected). Scheduler is
mixed: `resource_schedules` will likely want a `user_id` (who scheduled this), but the polling
loop itself stays one global loop attributing fired schedules to their owner — a schema change,
not an architecture change to the thread itself.

---

## 2. Multi-user transition

**Recommendation: adopt `trellis-auth` in RE** (closing the gap open since the package was
extracted 2026-08-29 specifically so RE and EA wouldn't drift), **and implement EA's own
unimplemented `SESSION_AND_INTERACTION_STATE.md` design in EA first — then port the same
two-dimension model (`user_id` persistent / `session_id` ephemeral) to RE rather than inventing a
second one.**

`packages/egeria-advisor/docs/design/SESSION_AND_INTERACTION_STATE.md` is directly reusable:
- Storage renamespacing (`~/egeria-plans/users/{user_id}/...`) generalizes to RE's
  `resource_working_set`/`entity_egeria_project_context` — both already carry comments
  anticipating a `user_id` column (`registry.py:1804`, `registry.py:4831-4835`). Small schema
  migration: add `user_id TEXT NOT NULL DEFAULT ''`, drop the default once cutover completes.
  RE's own `session_id` (conversation memory only, no `user_id` field) has the identical gap the
  EA doc diagnoses for `draft_id`.
- **Session store correction, forced by §1's topology decision**: the doc's in-memory
  `Dict[str, SessionState]` explicitly caveats "if this app ever moves to multi-worker... would
  need Redis or sticky routing." That caveat stops being hypothetical once N-worker topology is
  accepted — a request can land on any worker, so **the session store needs to be Postgres- or
  Redis-backed from the start**, not in-memory with a "revisit later" note. Postgres is the lower-
  effort choice (both apps already share the pgvector instance; session read/write volume is
  trivial next to that; Redis would be new infra to run for a workload that doesn't need its
  speed).

**Flagged, not quietly endorsed: the credential mechanism.** `trellis-auth`'s JWT carries the
user's *actual* Egeria username and password, signed into the token — not a separate credential
store. Confirmed from the README's own usage example. Works today because EA is a trusted
single-tenant deployment behind HTTPS with a short JWT TTL, and its design doc leans into that
trust model explicitly. Adopting the same mechanism in RE, at the same time RE moves toward
containerized/multi-worker deployment (a step toward looking more like production
infrastructure), deserves a deliberate go/no-go conversation: is embedding the raw password still
right once there's a second app and a container boundary, or should the JWT carry a
session-bound credential *reference* instead? **Not resolved here — flagged as its own ~20-minute
decision**, not a paragraph to skim past.

**Scope gap, stated honestly**: EA's own doc already flags `EgeriaContext` and the MCP report
agent as "lower priority — flagged, not solved" even after its own fix lands (still process-wide
singletons on one shared service account). Adopting this doc as RE's model means RE inherits that
same gap — draft/document/working-set scoping is the real win; agent-level per-user isolation is
a legitimate follow-on, not something this pass claims to close.

**Rejected: build RE's own multi-user model independently** — exactly the "converge onto one
common pattern" principle this repo's own conventions already state, with the query-cache/
annotation-properties/vector-store drift history as the standing evidence for why not.

---

## 3. Threading/concurrency model

Substantially covered in §1 (not separable from topology). As a standalone checklist:

1. **Write the model down first**, before any code moves — `docs/Architecture.md`'s one line
   (`scheduler.py # daemon thread`) is not a threading model. Needs: which background loops
   exist, whether each is global-singleton or per-worker, the shared thread-pool bridge shape,
   and the ownership/reconciliation contract `run_reconciler.py` already depends on informally.
2. **Consolidate the sync-bridge pattern** — one shared, explicitly-sized `ThreadPoolExecutor`
   per process, replacing the six scattered ones (`agents/base.py`, `conversation_agent.py`,
   `survey_definition_reader.py` ×2, `prefect_adapter.py`, `tui/app.py`). Keep the per-call
   timeout as defense-in-depth even after consolidation.
3. **Leader-elect the 3 daemon threads** via a Postgres advisory lock.
4. **Verify, don't assume, the pyegeria concurrency hazard** — a dedicated spike reproducing the
   `get_guid_for_name` hang under controlled concurrency, to know whether "one shared pool" alone
   fixes it or whether pyegeria itself needs a fix.

---

## 4. LLM backend and vLLM

**Recommendation: do not move to vLLM now.** Run the ONNX benchmark first (near-zero cost,
already built). Keep Ollama as the default native backend. Treat vLLM as a real, separate
follow-on decision gated on a fact not yet in hand.

**On vLLM specifically** (verified via live research this session, not training-data memory,
since this area moves fast): a community-maintained plugin,
[`vllm-metal`](https://github.com/vllm-project/vllm-metal)
([PyPI](https://pypi.org/project/vllm-metal/)), runs vLLM on Apple Silicon via MLX, with a 0.2.0
release (April 2026) claiming substantial throughput gains over PyTorch MPS. Real, worth knowing
— but this is "Apple Silicon support exists via a young, community-maintained hardware plugin,"
not first-party CUDA-grade maturity. **Not yet verified to the confidence this decision needs** —
production stability, model coverage, maturity vs. Ollama on this exact hardware are all
unconfirmed. Whether `vllm-metal` is worth adopting is a fair question for its own spike, not a
call to make inside this pass.

What's confirmed either way: **containerizing any GPU-bound inference backend on this Mac —
vLLM included — hits the same Metal-passthrough wall Ollama does.** Even if `vllm-metal` proves
excellent, it belongs in the native tier of §1's hybrid topology, not the containerized tier —
that part of the recommendation doesn't move based on which inference engine wins.

**Why not move now, independent of the Apple Silicon question:** RE has a real backend
abstraction (`LLMConfig.backend: ollama | openai | anthropic`) a vLLM backend could slot into; EA
hardcodes `provider: "ollama"` per task-slot with no abstraction at all. Moving either app to
vLLM today means validating `vllm-metal` maturity across all 11 already-pulled Ollama models
*and* building the abstraction EA doesn't have yet — real work chasing an unconfirmed
hardware-support story on the actual deployment target.

**Cheap and worth doing now:** EA's `RUNTIME_AND_HARDWARE.md` §4a — a full ONNX embeddings path
(`embeddings_onnx.py`, exported models, `scripts/benchmark_onnx.py`) is built, switched off
(`backend: pytorch`), and **never benchmarked** despite stated 2x/3x speedup targets. Same-day
task, no architectural risk (accelerator failures already fall back to CPU rather than raising).

**Rejected: adopt vLLM now for either app** — the Apple Silicon story, while real, isn't yet
verified to production confidence, and EA's architecture isn't ready to receive a second backend
without first building the abstraction RE already has.

---

## Sequencing

1. **Now, cheap, no architecture risk:** run EA's existing ONNX benchmark suite, record the
   result. Write RE's threading model into `docs/Architecture.md` (docs only, no code change).
2. **Research-first, before committing to vLLM:** spike `vllm-metal` against RE/EA's actual model
   set, starting with the shared default `llama3.1:8b`.
3. **Structural, sequenced together** (the "solve jointly" core): stand up the
   containerized-app/native-Ollama hybrid topology for RE first (it has the acute incident
   motivating this), moving to N worker processes; land the shared-pool + leader-election
   threading consolidation as part of the same move, not after; do EA next once the pattern is
   proven.
4. **Multi-user, gated on step 3 landing** (the session-store design depends on knowing the
   process topology): implement `SESSION_AND_INTERACTION_STATE.md` in EA with a Postgres-backed
   session store; port the same two-dimension model to RE via `trellis-auth` adoption plus the
   `resource_working_set`/`entity_egeria_project_context` `user_id` migration.
5. **Explicitly out of scope for this pass, flagged rather than papered over:** the
   JWT-carries-raw-password credential posture question (§2); per-user isolation of
   `EgeriaContext`/the MCP report agent (already deferred in EA's own doc); whether `vllm-metal`
   is production-ready enough to adopt. Each is a real follow-on design pass, not a gap in this
   one.

## Critical files

- `packages/resource-explorer/resource_explorer/web/app.py`
- `packages/resource-explorer/resource_explorer/registry.py`
- `packages/resource-explorer/resource_explorer/run_reconciler.py`
- `packages/trellis-auth/README.md`
- `packages/egeria-advisor/docs/design/SESSION_AND_INTERACTION_STATE.md`
- `packages/egeria-advisor/docs/design/RUNTIME_AND_HARDWARE.md`
- `../egeria-workspaces-fs/compose-configs/shared-infra/shared-infra.yaml` (sibling repo)
