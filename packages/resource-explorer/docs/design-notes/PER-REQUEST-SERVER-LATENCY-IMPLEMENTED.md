# Per-request server latency — investigated and (mostly) fixed

**Status:** Implemented. Two of the four named suspects were confirmed and fixed, with
real before/after numbers. A third, previously-unnamed contributor was found by profiling
and partially fixed. One gate item (board-summary <200ms on a heavily-surveyed database)
is **not** met yet — see "What is still open" below, reported honestly rather than
claimed.

## The symptom that started this

Live owner gate check, 2026-09-29, on the By-analysis board-summary read-cost branch,
port 8813: a mechanism measured at 8-33ms per operation *called directly* (outside the web
server, against the same registry) took 1.4-3s per HTTP request through the actual running
FastAPI server, with roughly two requests completing at a time rather than in real
parallel. The control measurement that pointed away from "one feature is slow" and toward
"the server itself has a general per-request tax": `GET /api/auth/me` — no board work, no
database read, nothing related to board summaries — took 2.3s at boot on the same server.

## Method

A `_phase_timing_middleware` (`web/app.py`) logs `phase_timing path=... total_ms=...` for
every request. `ProjectRegistry.__init__` (`registry.py`) separately logs `registry_init
path=... ran_schema_init=... elapsed_ms=...` whenever construction takes more than 5ms —
this is the line that actually located the dominant cost (see below); subdividing the
outer request middleware further turned out not to be necessary once that log existed.

**Quiet-registry condition.** Checked directly via `docker exec egeria-shared-postgres
psql ... pg_stat_activity` before and during measurement: 1 active connection (the query
itself), 104-151 idle (accumulated pooled connections from earlier test runs, not activity)
throughout this investigation. No other session's test suite or survey run was active
against the shared registry at measurement time. This is a live spot-check, not a lock —
if another session started a run mid-measurement it would not have been caught — but it is
what was available; I did not coordinate a formal quiet window with the "Resource-explorer
PR/CI merge" session, and note that as a gap rather than asserting more certainty than the
spot-check supports.

**Where measurements ran.** A scratch `resource-explorer web` process on port 8899 (never
8810/8813), `--no-embed-worker`, `TRELLIS_ANONYMOUS_READ=true`, pointed at the same shared
Postgres registry (`localhost:5442`) used by the real deployment. All HTTP timings below
are real requests through this server, not direct function calls, except where explicitly
labeled "direct call".

## What the timing data actually pointed at

### Suspect 2, confirmed and dominant: `ProjectRegistry()` re-verifying its entire schema on every construction

Every route does `registry = ProjectRegistry()` fresh (dozens of call sites; `grep -c
"ProjectRegistry()" resource_explorer/web/routes/*.py` — dozens). `ProjectRegistry.__init__`
called `create_engine(...)` (a brand-new connection pool) and then `_init_schema()` — 58
`CREATE TABLE IF NOT EXISTS`, 46 guarded `ALTER TABLE`, 51 `CREATE INDEX` statements, ~150
round trips to Postgres in total — **unconditionally, every time**, even though the schema
cannot have changed since the last construction in the same process.

Isolated, direct-call measurement (`ProjectRegistry()` in a loop, same process, warm
Postgres):

| call # | before fix | after fix |
|---|---|---|
| 1st | 1517ms (cold) / 305-447ms (warm process) | 305-447ms (unavoidable — first real schema check) |
| 2nd | 305-420ms | **0.0ms** |
| 3rd-5th | 305-420ms each | **0.0ms** each |

**Fix:** `ProjectRegistry` now caches one `Engine` (and its connection pool) and an
"already schema-verified" flag per `database_url` at the class level (`registry.py`,
`ProjectRegistry.__init__`, `_pg_engine_cache`/`_pg_schema_ready`/`_pg_cache_lock`).
Double-checked locking so two racing constructions for the same URL don't both pay full
init (harmless since every statement is idempotent, just pointless). **Scoped to
`postgresql://` URLs only** — SQLite is test/dev-fallback only, and caching those engines
for the process lifetime would hold file descriptors open across hundreds of
`tmp_path`-backed test databases for no benefit; the real problem this fixes is
exclusively the shared Postgres registry. `:memory:` is excluded on principle (two
independent in-memory databases must never share a cached engine/pool).

Real HTTP, sequential, same server, before/after this one fix:

| endpoint | before | after |
|---|---|---|
| `GET /api/activity/?limit=20` | 1040ms | **20ms** |
| `GET /api/databases/` | 6432ms (cold), 8863ms (2nd — see pool note below) | 1015ms (cold), 815ms (2nd) |
| `GET /api/projects/` (68 registered repos) | 5266ms, 5094ms | 1824ms, 1553ms |

(`/api/projects/` and `/api/databases/` don't drop to near-zero like `/api/activity/`
because of the second and third findings below, which the schema-init fix does not touch.)

### Suspect 4-adjacent: the *shared* pool was too small once it was actually shared

Caching the engine (above) means every `ProjectRegistry()` in the process now draws from
**one** pool instead of each getting its own. SQLAlchemy's defaults (`pool_size=5,
max_overflow=10`, 15 total) were fine when each request had its own throwaway pool but
became a real bottleneck once shared: a concurrent burst matching the by-analysis pane's
boot sequence (`auth/me`, `projects`, `activity`, `databases`, 7 board reads — 11 concurrent
DB-touching requests) produced individual request times up to **63.7s**, waiting on a pool
checkout. `SHOW max_connections` on the shared instance returns 1000, so there is no real
ceiling nearby. **Fix:** raised the cached engine's pool to `pool_size=15, max_overflow=25`
(`registry.py`, same `create_engine` call as the caching fix).

### Suspect 3, confirmed via a live thread dump: `list_projects` blocking the event loop directly

`GET /api/projects/` builds one `ProjectSummary` per registered repo (68 on the box this
was measured on) via `_to_summary(p, registry)`, which calls `registry.get_disposition`,
`registry.is_working_set_hidden`, and `registry.egeria_linkage.describe_publish_status` —
all synchronous — **directly inside the `async def list_projects` route handler**, not
wrapped in `asyncio.to_thread` the way the sibling `/survey-results` routes already are.

A `kill -USR1 <pid>` thread dump (this codebase's own SIGUSR1 handler — see
`feedback_sigusr1_kills_cli_processes` for why only `web`/`worker`/`serve` install it)
taken mid-burst caught it directly:

```
Current thread 0x00000001fd7d7f80 (most recent call first):
  .../sqlalchemy/dialects/postgresql/_psycopg_common.py", line 183 in do_ping
  .../sqlalchemy/pool/base.py", line 1309 in _checkout
  .../sqlalchemy/engine/base.py", line 3319 in raw_connection
  .../registry.py", line 1263 in _conn
  .../registry.py", line 7801 in is_working_set_hidden
  .../web/routes/projects.py", line 55 in _to_summary
  .../web/routes/projects.py", line 86 in list_projects
  .../fastapi/routing.py", ... in run_endpoint_function
  ...
  .../uvicorn/server.py", line 67 in run
```

That is the **main/event-loop thread itself** — not a worker thread — parked inside a
Postgres connection-pool checkout, called from `list_projects`. Every other in-flight
coroutine on that event loop, including `/api/auth/me` (zero database work), queues behind
it for as long as the checkout (and then the query) takes. This is the same bug class the
by-analysis-progressive-and-graph slice already found and fixed once, for `/questions`
(BY-ANALYSIS-PROGRESSIVE-AND-GRAPH-IMPLEMENTED.md §2a) — `list_projects` is a second,
previously-unfixed instance of it.

**Fix:** `list_projects`'s body moved into `_list_projects_sync`, called via
`await asyncio.to_thread(_list_projects_sync, ...)` (`web/routes/projects.py`).

**Regression test:** `tests/test_list_projects_off_the_loop.py`, following
`test_ask_route_off_the_loop.py`'s own pattern exactly — monkeypatches
`ProjectRegistry.is_working_set_hidden` to sleep 2s, fires `list_projects` on a background
thread, then asserts `GET /health` (pure liveness, no DB work) still answers in well under
2s. Verified failing without the fix (git-stashed the route change, reran — fails,
`/health` blocks for the full 2s) and passing with it.

### A fourth, previously-unnamed contributor found by profiling: an unbounded historical-blob fetch

Not one of the four suspects named in the brief, but the dominant cost once the above two
were fixed. `cProfile` on a single `GET /api/databases/laz_local_adventureworks/survey-results?board_id=schema_inventory`
(warm process, cached schema/engine):

```
189055 function calls in 1.935 seconds
   ncalls  cumtime  percall  function
        5    1.866  0.373    registry.py:9093(get_database_surveys)
       32    1.850  0.058    {psycopg2 cursor.execute}
```

`get_database_surveys(slug)` runs `SELECT ... survey_data ... FROM database_surveys WHERE
database_slug=? ORDER BY surveyed_at DESC` — **no `LIMIT`**, fetching every historical
survey's full `survey_data` JSON blob. `laz_local_adventureworks` has accumulated 57 survey
rows totalling **61MB**:

```sql
select count(*), sum(length(survey_data)), max(length(survey_data))
from database_surveys where database_slug='laz_local_adventureworks';
--  57 | 60974646 | 1811863
```

`_credential_capability_results` (`surveyors/database/survey_definition_adapter.py`)
deliberately searches every stored survey newest-first for one that carries a
`credential_capability` key — its own docstring explains why (fixed live 2026-09-26 for a
real correctness bug: the latest survey doesn't always carry the probe). One board read
called this 5 times, each paying the full 57-row/61MB fetch. Direct psycopg2 comparison:

| query | time |
|---|---|
| unbounded (`ORDER BY surveyed_at DESC`, no LIMIT) | 688-905ms |
| `LIMIT 1` | 14-34ms |

**Fixes applied (both real, both tested against real Postgres):**

1. `get_latest_database_survey` — used by callers that only ever want the newest row — got
   its own `ORDER BY surveyed_at DESC LIMIT 1` query instead of delegating to
   `get_database_surveys(...)[0]`. `get_database_surveys` itself is untouched: several real
   callers (survey-history views, trend stats) genuinely want every row, so this is a second,
   narrower query for the one caller pattern that only wanted the first.
2. `get_database_surveys` gained a per-`ProjectRegistry`-**instance** cache
   (`self._database_surveys_cache`), so the 5 identical calls within one board read become 1
   real fetch. Instance-scoped, not class/process-scoped, deliberately: a `ProjectRegistry`
   is normally constructed fresh per request (the same pattern the engine/schema cache
   exists to make cheap), so the cache dies with the request and can never serve a stale
   answer to an unrelated caller. `record_database_survey` clears the slug's cache entry on
   write, so a longer-lived instance (a worker loop reusing one `ProjectRegistry`) never
   reads its own write as stale.

Direct-call (`build_survey_results`, same board, same process) before/after all three
registry-layer fixes:

| | before any fix | after schema/pool fix only | after survey-cache fix too |
|---|---|---|---|
| 1st call (fresh instance, cold cache) | 2.4-2.7s | 2.0-2.7s | **666ms** |
| repeat calls (same instance, cache warm) | 2.0-2.7s | 2.0-2.7s | **48-74ms** |

## Gate results

1. **`/api/auth/me` under 100ms.** **PASS.** 0.2-17ms warm; measured across every burst run
   in this investigation, including the one that caught `list_projects` blocking the loop
   — after the `to_thread` fix, `/api/auth/me` stayed at 0.2-2.7ms even under an 11-way
   concurrent burst that included 7 board reads.

2. **A board-summary request under 200ms, in-server.** **NOT MET**, on
   `laz_local_adventureworks` specifically. Warm, sequential, single-request: 0.92-2.05s —
   down from ~2-3s before any fix (and down from what would have been ~5x that before the
   survey-cache dedup), but still 4-10x over budget. Root cause is the unbounded-fetch
   query above: even a single, un-duplicated 57-row/61MB fetch costs ~700-900ms on its own,
   and `_credential_capability_results`'s per-board search still pays it once per board
   read (my fix removed the *redundant* 4 extra fetches within one read, not the one real
   fetch itself). A further fix — pushing the "does this survey carry
   `credential_capability`" check into the query itself (e.g. `survey_data::jsonb ?
   'credential_capability'`, measured directly at ~300ms server-side vs ~700-900ms
   client-side, or a proper `jsonb` column with an index) — would close most of the
   remaining gap, but touches a correctness-sensitive code path (the exact search this was
   built to get right, 2026-09-26) and needs its own casting-safety and correctness pass
   against malformed historical rows; I chose not to ship it under this slice's time
   budget rather than land something under-tested on a query this history-sensitive.
   **This is the one gate item not met — flagged, not claimed.**

3. **Cold-load headline-visible timing on the By-analysis pane under 2s.** **NOT MET**, for
   the same root cause as #2 (the pane's board reads are gated behind the same unbounded
   fetch), compounded by a second, separate finding: `list_projects` itself (part of the
   pane's boot sequence) still takes 1.5-2.8s end to end even after the `to_thread` fix —
   the fix stops it from blocking *other* requests, but does not make the ~204 round trips
   (68 projects × 3 registry calls each: `get_disposition` → `get_by_github_url`,
   `is_working_set_hidden`, `describe_publish_status`) any faster. This is a genuine N+1
   query pattern, found by profiling (`cProfile` on `_list_projects_sync`: 422 raw
   `cursor.execute()` calls, 1.04s), but it is a **fifth**, newly-found contributor outside
   the four named suspects and outside this slice's board-summary-focused gate — flagged
   here as a follow-up (batch-fetch dispositions/working-set-hidden for all slugs in one or
   two queries instead of one round trip per project per field) rather than fixed, to keep
   this slice's fix scoped to what the gate actually measures.

## The coordinator's backfill-regression question

Added mid-task: the owner observed the board-summary-read-cost branch's *first-visit
backfill* (every board recomputes and persists, since no `board_summary` rows exist yet)
taking over 4 minutes on `coco_pharma`, versus 1:20 on the pre-board-summary-read-cost
build (plain per-board reads, no persistence). Asked specifically whether the write path
serializes the 7 board writes under a lock/shared connection, as opposed to the read path's
`BY_ANALYSIS_MAX_CONCURRENT_READS`-bounded real parallelism.

**Important scope note:** the `board_summary`/backfill mechanism does not exist on
`origin/main` — it lives only on the separate, not-yet-merged `re/board-summary-read-cost`
branch. This task's branch (`re/per-request-server-latency`) was set up off `origin/main`
per its own instructions, so none of the fixes above are present there, and I did not edit
that branch (out of scope — a different PR/session owns it). The answer below is a **code
read**, not a measurement on that branch, and I want to be explicit about that distinction.

**No lock or single-shared-connection artifact found.** `_refresh_board_summaries_after_run`
(`workflows/analysis.py`, that branch) is a plain, unconcurrent Python `for` loop:

```python
for board_id in board_ids:
    build_survey_results(registry, entity_type, slug, stage="", include_empty=True, board_id=board_id)
```

— one shared `registry` instance, called sequentially, 7 times (once per board_id derived
from the just-completed `analysis_id`). No `threading.Lock`, no `asyncio.Lock`, nothing
narrowing to one connection beyond what one `ProjectRegistry` instance already implies.
This IS a real, distinct inefficiency — unlike the read path's bounded-3-concurrent queue,
this can never benefit from real parallelism — but it is an *absence of concurrency*, not a
lock.

**The dominant explanation is very likely the same root cause fixed above.** That branch
predates both the registry engine/schema caching and the `get_database_surveys` unbounded-
fetch fix. `_credential_capability_results`'s "search every stored survey" pattern (up to 5
calls per board, each an unbounded fetch on a heavily-surveyed database) running
**sequentially across 7 boards, with no caching at all**, is exactly the shape that turns a
compute that should take single-digit seconds into minutes — and it gets *worse* the more
survey rows a database accumulates, which plausibly explains why this regression showed up
during live testing on `coco_pharma` rather than being visible from day one: the database's
survey history had grown by the time this was observed.

**I could not measure this directly** — triggering a genuine first-visit backfill against
the shared registry is a non-idempotent, side-effectful write, and doing it without
coordinating with whoever is actively driving `re/board-summary-read-cost` would risk
exactly the kind of concurrent-write collision this project's coordinate-shared-writes
convention exists to prevent. Flagging as an open item rather than guessing a number.

**Recommendation for that branch's owner:** port the three registry-layer fixes above
(engine/schema caching, `get_latest_database_survey` LIMIT-1, `get_database_surveys`
instance cache) and re-measure the real first-visit-backfill timing; separately, consider
bounding `_refresh_board_summaries_after_run`'s loop to run boards with real concurrency
(matching the read path's own `BY_ANALYSIS_MAX_CONCURRENT_READS` pattern) as an independent
second improvement.

## Full suite

`uv run pytest tests/ -q -rf`, against the same quiet shared Postgres registry checked
above: **6828 passed, 103 skipped, 0 failed** (15m37s). Skips are the usual optional-service
integration tiers (Ollama/Phoenix/MLflow/etc. not running in this environment), not new.
