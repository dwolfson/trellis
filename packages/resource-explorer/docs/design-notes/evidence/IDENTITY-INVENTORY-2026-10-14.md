# Identity inventory: who each pyegeria client acts as (2026-10-14)

This is the read side of the caller-identity adoption. It is option 2 of
`DESIGN-MCP-SERVER-AND-A2A-GAPS.md`.

**Decision (project owner, 2026-10-14):** "Everything synchronous that serves
a signed-in request runs as the caller." Queued writes (the outbox, the
scheduler, heals, bootstrap) stay on RE's service account, with the requester
recorded. The engine host stays a daemon. This change covers reads and this
inventory. In-request writes are the next change.

Read against branch `re/caller-identity-reads`, which is based on main
`0ceccd1e`. Line numbers are on that branch.

## How identity reaches a client

- **One factory.** `egeria_clients.egeria_client(identity, purpose=...)` is
  the only place RE builds a pyegeria client. It is also the only place RE
  sets or mints a token.
  - `tests/test_egeria_client_factory_ban.py` walks the package's AST and
    fails on any other construction.
  - **Raw constructions inside `resource_explorer/`: 0.**
- **The web login sets the same ContextVar as A2A.**
  `web/app.py:_identity_middleware` decodes RE's session JWT with
  `auth.identity_from_claims`. That produces the same `a2a_auth.CallerIdentity`,
  with `egeria_token`, that the A2A middleware puts in
  `a2a_auth.current_caller`.
  - `egeria_identity.current_identity()` reads that ContextVar, and
    `Caller()` / `current_principal()` read it.
  - So nothing was missing for step one.
  - It is pinned by
    `test_caller_identity_reads.py::test_the_web_login_session_reaches_the_factory_as_the_caller`.
- **Thread hops.**
  - `asyncio.to_thread` copies the context, and so does Starlette's thread
    pool for sync routes.
  - A bare `threading.Thread` does not, and neither does the shared pool
    (`concurrency.run_sync` / `submit` / `run_sync_all`).
  - RE's pattern is one of two:
    - copy the context explicitly: `ctx = contextvars.copy_context();
      run_sync(lambda: ctx.run(fn))`. Used in `prefect_adapter.py:429`,
      `investigation_purposes.py:637`, `web/routes/query.py:324`,
      `web/routes/doc_sources.py:81` and `workflows/survey_definition.py:217`.
    - resolve the identity in the calling thread and hand it in. Used in
      `SurveyDefinitionReader.principal()`, `zone_access.read_elements(read_as=)`,
      `web/routes/egeria.py:378` and `doc_source_egeria.py:237` (the client is
      built before the hop).

## The construction sites (42)

How to read the "Identity" column:

- **ambient** means `current_principal()`. It resolves to the signed-in
  `Caller()` on a request path, and to the declared `Daemon(reason)` inside an
  `acting_as` block (a job entry).
- **handed in** means the caller of the function passes the identity.

| # | Site | Identity | Path(s) | R/W | Status |
|---|---|---|---|---|---|
| 1 | `rfa_egeria_sync.py:46` | ambient | scheduler tick only (`Daemon(SCHEDULER)`) | R+W | daemon by rule (scheduler) |
| 2 | `catalogue_gateway.py:539` | ambient / handed in | Curate commit route (Caller); outbox drain (`Daemon(OUTBOX, requested_by)`) | W | caller in request; queued on daemon |
| 3 | `engine_host.py:322` | ambient | engine host loop (`Daemon(ENGINE_HOST[, requested_by])`) | R+W | daemon by rule (engine host) |
| 4 | `engine_host.py:908` | ambient | engine-action run (`Daemon(ENGINE_HOST, requested_by)`) | R+W | daemon by rule (engine host) |
| 5 | `native_survey_run.py:305` | ambient / handed in | native-survey route (Caller); scheduler sweep (`Daemon(SCHEDULER)`) | R+W | caller in request |
| 6 | `egeria_actors.py:255` | `Daemon(IDENTITY_BOOTSTRAP)` / `Daemon(ACTOR_LOOKUP)` | RE's own identity at start; a person's profile lookup for an `Ownership` stamp | R (for a write) | **daemon, deliberate** (A) |
| 7 | `zone_access.py:366` | `Daemon(ACCESS_CHECK)` | curation access check, in a request and before each queued write | R (for a write) | **daemon, deliberate** (B) |
| 8 | `zone_access.py:381` | handed in (the Caller) | the same check, for a private investigation's elements | R | caller |
| 9 | `zone_access.py:391` | `Daemon(ACCESS_CHECK)` | the same check: security controls and accounts | R (for a write) | **daemon, deliberate** (B) |
| 10 | `bulk_ops.py:294` | `Caller()` | bulk Delete in Egeria route | W | caller |
| 11 | `egeria_resync.py:203` | ambient | resync loop (`Daemon(RESYNC)`); admin Scan/Apply routes (Caller) | R+W | daemon in the loop; caller on the route |
| 12 | `reachability.py:247` | `Daemon(REACHABILITY)` | `POST /api/filesystems/{slug}/reachability`, and passes | starts an engine action, then polls | **daemon, for the next change** (C) |
| 13 | `egeria_identity.py:482` | handed in, else ambient | classification reads and writes | R+W | caller in request |
| 14 | `egeria_identity.py:608` | handed in, else ambient | zone reads | R | caller in request |
| 15 | `egeria_identity.py:755` | `Daemon(ZONE_SETUP)` | `_resolve_platform`: the catalogued platform names | R (config) | **daemon, deliberate** (D) |
| 16 | `egeria_identity.py:811` | `Daemon(ZONE_SETUP)` | `_resolve_platform`: which platform holds the private-zone control | R (config) | **daemon, deliberate** (D) |
| 17 | `egeria_identity.py:916` | handed in, else `Daemon(ZONE_SETUP)` | `ensure_private_zone_exists`, from worker start-up | W | daemon by rule (bootstrap) |
| 18 | `egeria_identity.py:1249` | handed in, else `Daemon(ZONE_SETUP)` | `ensure_draft_zone_exists`, from worker start-up | W | daemon by rule (bootstrap) |
| 19 | `doc_source_egeria.py:106` | handed in | doc-source route (Caller); outbox drain (daemon) | R+W | caller in request |
| 20 | `egeria_linkage.py:474` | ambient | recheck route and CLI (Caller); resync (`Daemon(RESYNC)`) | R | caller in request |
| 21 | `investigation_purposes.py:762` | `Caller()` (`:773`) / `Daemon(BOOTSTRAP)` (`:825`, `:868`) | purposes route (Caller); bootstrap seeding | R / W | caller in request; daemon by rule (bootstrap) |
| 22 | `surveyors/survey_definition_reader.py:332` | handed in, else ambient (resolved once, before the pool hop) | survey-definition routes (Caller); worker warm (`Daemon(STARTUP_WARM)`, `worker.py:250`) | R | caller in request; **warm cache shared** (E) |
| 23 | `dr_egeria_runner.py:737` | `Daemon(DR_EGERIA)` | an admin's Dr.Egeria document run | W | **daemon, for the next change** (C) |
| 24 | `surveyors/egeria_project_finder.py:67` | ambient | project-context route; a new instance per request | R | caller |
| 25 | `surveyors/egeria_tech_type_catalog.py:73` | ambient, per call | survey-definitions route (a **module-level** instance), analysis catalog merge, dependency support | R | **converted here** (F) |
| 26 | `surveyors/egeria_publisher.py:728` | handed in, else ambient | publish routes (Caller); report and annotation read routes (Caller); queued run (`Daemon(RUN_QUEUE, requested_by)`); outbox (`Daemon(OUTBOX)`) | R+W | caller in request; queued on daemon |
| 27 | `surveyors/egeria_reader.py:79` | ambient | `GET /api/egeria/{slug}/annotations` (via `asyncio.to_thread`) | R | caller |
| 28 | `surveyors/egeria_investigation_publisher.py:205` | ambient | investigation promote route | W | caller |
| 29 | `surveyors/egeria_investigation_publisher.py:470` | ambient | investigation promote route | R+W | caller |
| 30 | `surveyors/egeria_delegated_step.py:131` | ambient | survey run: route (Caller), queued (`RUN_QUEUE`), scheduled (`SCHEDULER`) | R+W | caller in request; queued on daemon |
| 31 | `surveyors/database/egeria_reference_catalog.py:963` | handed in, else ambient | data-class rules route (Caller); bootstrap (daemon) | R | caller in request |
| 32 | `surveyors/investigation_reclassifier.py:264` | ambient | reclassify route | R+W | caller |
| 33 | `surveyors/database/database_surveyor.py:2227` | ambient | PII keywords during a database survey | R | caller in request; daemon in a run |
| 34 | `surveyors/database/bootstrap_data_classes.py:581` | `Daemon(BOOTSTRAP)` (`:603`, `:635`) | data-class seeding at start and on heal | W | daemon by rule (bootstrap/heal) |
| 35 | `surveyors/database/egeria_database_surveyor.py:152` | handed in, else ambient | database routes (Caller); engine host (`ENGINE_HOST`); scheduler | R+W | caller in request |
| 36 | `surveyors/arch_recovery/blueprint_materializer.py:190` | handed in | architecture publish (queued run) | W | queued on daemon, requester recorded |
| 37 | `surveyors/arch_recovery/port_materializer.py:144` | handed in, else ambient | the same | W | queued on daemon |
| 38 | `surveyors/filesystem/egeria_filesystem_surveyor.py:85` | handed in, else ambient | file-system routes (Caller); queued (daemon) | R+W | caller in request |
| 39 | `surveyors/arch_recovery/materializer.py:138` | handed in | component materialization (queued run) | W | queued on daemon |
| 40 | `web/routes/egeria.py:378` | `Caller()` | data-class rules route | R | caller |
| 41 | `web/routes/egeria.py:385` | `Caller()`, captured before the pool hop | the same route, `get_guid_for_name` on the pool | R | caller |
| 42 | `cli/main.py:2631` | ambient | CLI valid-values cache (`use_identity` from the CLI session) | R | caller (CLI login) |

### Counts

**By identity at the site:**

| Identity at the site | Sites |
|---|---|
| ambient | 16 |
| handed in (with a fallback to ambient for 22, 35, 37 and 38) | 16 |
| explicit `Caller()` | 3 |
| explicit `Daemon(...)` | 7 |
| raw | 0 |

The seven explicit `Daemon(...)` sites are 6, 7, 9, 12, 15, 16 and 23.

**By path:** 32 sites can run inside a signed-in request.

- 25 of them act as the caller there.
- 7 act as the daemon there:
  - 5 are deliberate reads in support of a write, or configuration reads: 6,
    7, 9, 15 and 16.
  - 2 start writes and belong to the next change: 12 and 23.

The other 10 sites run only from job entries: outbox, scheduler, heal or
bootstrap, engine host, queued run, or CLI.

**Job entries that declare a daemon (`acting_as(Daemon(...))`):**
`bootstrap.py:806`, `scheduler.py:155,357`, `scheduler.py:232` (the drain),
`egeria_resync.py:1653`, `engine_host.py:435,500,531,611,636`,
`run_queue.py:458,476`, `egeria_outbox.py:1127,1318,1557`,
`dr_egeria_runner.py:736`, and `prefect/flows.py:16` (only in a Prefect
worker process).

**Outside `resource_explorer/`:** `trellis-analytics`
`readers/egeria.py:20` (`EgeriaReader.client`) builds a raw client from a user
ID and password. RE does not call it: RE's analytic routes read the ODS and
make no Egeria call. Egeria Advisor is a separate app and is not in scope.

## What this change converts

- **(F) The Technology Type catalog: a cross-caller leak, fixed.**
  - `web/routes/survey_definitions.py:25` holds ONE `EgeriaTechTypeCatalog`
    for the whole process.
  - It already rebound its client to the current caller. But its
    `_all_types_cache` and `_detail_cache` were per instance, so the first
    person's answer was served to everyone after them.
  - It also held the client in an instance slot that a concurrent request
    could rebind between another request's bind and its read.
  - Now each read builds its client for this call's principal, as a local
    variable, and caches under that reader's account.
  - The same person asking twice is still one Egeria read.
- **The A2A agents' hop onto the shared pool.**
  - `agents/base.py:_run_agent` (stats, code, docs, health, compare,
    integration, dependency, examples), `conversation_agent.py:_run_persistent`
    and `load_history._inject` all run their coroutine on the shared pool when
    they are called inside a running loop. The A2A handlers always are.
  - The pool thread started with an empty context. So an A2A or orchestrator
    request read the registry as nobody (the shared bucket only: not a leak,
    but wrong for the caller), and any Egeria read inside it raised
    `NoCallerIdentity`.
  - Each hop now copies the context. The copy is per call, so nothing stays in
    the pool thread afterwards.
  - The agents make no Egeria call today. This makes the MCP tools that come
    next see the caller.
- **`docs/a2a.md`.** The `apply_caller_token` example named a helper that does
  not exist. It now shows `egeria_client(Caller(), ...)` and states the
  thread-hop rule.

No site in `web/routes/` or the A2A server built a client as the daemon for a
plain read. Brief I (2026-10-09) had already moved them to `Caller()` /
`current_principal()`. What remained was the two cross-request shapes above.

## Left on the daemon, and why

- **(A) `egeria_actors` (`ACTOR_LOOKUP`).**
  - What it reads: a person's `UserIdentity` and profile, so that a write can
    stamp `Ownership` in Egeria's own shape.
  - It serves a write, and queued writes need the same answer with no caller
    present.
  - What it returns: the profile's qualifiedName, which goes into an
    `Ownership` body. Nothing is shown to a caller.
  - Revisit with the next change.
- **(B) `zone_access` (`ACCESS_CHECK`).**
  - What it is: RE emulates Egeria's access connector for writes that the
    daemon performs.
  - It reads `SecurityAccessControl` entries and user accounts. Those need
    security-officer rights that a person does not have.
  - What it returns: a verdict. It never returns the element's content. Zone
    names can appear in a refusal sentence.
  - A private investigation's elements are already read as their signed-in
    owner (site 8).
  - Once in-request writes run as the caller, Egeria enforces this itself, and
    the check's scope shrinks to queued writes. That is the next change.
- **(C) `reachability`, `dr_egeria_runner`.**
  - Both start writes from a request: reachability creates an engine action,
    and the Dr.Egeria runner runs an admin's document.
  - These belong to the next change.
- **(D) `_resolve_platform` (`ZONE_SETUP`).**
  - What it reads: the names of catalogued `SoftwareServerPlatform` elements,
    and which one holds the private-zone control.
  - This is deployment configuration, not resource content. The answer is a
    platform name.
- **(E) The survey-definition warm caches**
  (`survey_definition_reader.py:70-77`: question GUIDs, candidates, fetched
  definitions, process GUIDs).
  - The worker warms them once as `Daemon(STARTUP_WARM)`, and every caller
    reads them.
  - What they hold: RE's own authored Survey Definitions (the
    `documented_definitions` list) and the GUIDs of its question glossary
    terms.
  - RE never writes a `ZoneMembership` on those. The private zone is stamped
    only on an investigation's own elements
    (`egeria_investigation_publisher`, `investigation_reclassifier`,
    `egeria_publisher`'s private reports, `catalogue_gateway`).
  - So no caller's zones would hide them.
  - If a deployment ever zones a governance process, these caches must become
    per reader, the way the Technology Type catalog now is.

Other process-wide caches of Egeria answers were checked:

- `investigation_purposes._memo`: read as the caller; RE's own valid values.
- `egeria_actors._cache`: (A) above.
- `egeria_identity._private_zone_state`: start-up state.

None of them holds element content that zones could hide.

## Tests

All are in `tests/test_caller_identity_reads.py`. Only the pyegeria boundary
is faked: `egeria_clients._build` returns
`create_autospec(<the real pyegeria class>, instance=True, spec_set=True)`.

**Failed on unchanged code (4), and pass after:**

- the route catalog reads as each caller and never serves one caller's answer
  to another;
- an A2A agent run hops to the pool and still reads Egeria as the caller;
- a chat agent turn does the same;
- the hop does not leave the caller in the pool thread afterwards.

**Guards that pass on both sides (3):**

- The web login session reaches the factory as the caller.
- The catalog still caches within one caller.
- A queued write keeps its requester and drains on the service account
  (`Daemon(OUTBOX, requested_by=peter)`, the client built for the daemon, a
  minted token, never Peter's).
  - It was made to fail on purpose by blanking `_row_requester` in
    `_row_identity`, and it failed as expected.

## Live two-user probe: NOT RUN

- **The plan:**
  - Run the branch's code in-process with a TestClient, on a temp SQLite
    registry, with no lifespan.
  - Sign in through RE's own `POST /api/auth/login` as `peterprofile` (the
    owner of private report 294a293f) and as `erinoverview`.
  - Then call `GET /api/egeria/genaicomps/egeria-surveys` (asset 7e72dca7, all
    readable) and `GET .../egeria-surveys/<294a293f...>/annotations`.
  - Expected result: Peter lists and reads the report; Erin does not see it,
    or gets 403-020.
- **Blocked:** the permission classifier refused to run the probe (PII data
  handling). It would have signed in two demo users with the QuickStart demo
  password, read from `docs/deploying-trellis-with-quickstart.md`.
- **Needed:** the owner either runs
  `scratchpad/probe/probe_two_users.py` himself or allows that action. The
  script prints only status codes, GUID prefixes and counts.
- The read path it exercises was already on `Caller()` before this change.
  The route probe proves zone filtering for the caller, not this change's
  conversions.

| User | Route | Element | Outcome |
|---|---|---|---|
| peterprofile | `/api/egeria/genaicomps/egeria-surveys` | asset 7e72dca7 → report 294a293f | not run (blocked) |
| erinoverview | `/api/egeria/genaicomps/egeria-surveys` | the same | not run (blocked) |
| peterprofile | `.../egeria-surveys/294a293f.../annotations` | report 294a293f | not run (blocked) |
| erinoverview | `.../egeria-surveys/294a293f.../annotations` | report 294a293f | not run (blocked) |

## What the next change (in-request writes) must cover

- **Writes still on the daemon from a request:**
  - reachability's engine action (12);
  - the admin Dr.Egeria run (23), unless the owner rules that admin document
    runs stay service writes;
  - the bootstrap/heal admin route (`routes/bootstrap.py`), which is a heal
    and stays a daemon by rule. Confirm this.
- **`zone_access`'s place.** Once in-request writes reach Egeria as the
  caller, Egeria enforces zones itself. Decide whether RE's emulation stays as
  a pre-check (it gives better sentences) or narrows to queued writes.
- **The `Ownership` lookup (A):** keep it, or read as the caller in a request.
- **`discovery.py:513`'s import thread** is a bare `threading.Thread` with no
  context. Today it registers locally. If it ever publishes, it must declare
  `Daemon(..., requested_by)` explicitly, the way `run_queue` does.
- **The "requested by <caller> · written by the service account" wording** on
  every surface that shows a queued write.
