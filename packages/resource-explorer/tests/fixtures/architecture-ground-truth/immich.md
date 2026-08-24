# Ground-truth partition — immich-app/immich

> **PRE-REGISTERED, `owner-published` provenance.** The component set below is transcribed from
> Immich's own developer documentation, `docs/docs/developer/architecture.mdx`, §"Server":
> *"The Immich backend is divided into several services, which are run as individual docker
> containers."* No detector has been run against this target. This file is committed first; the
> commit timestamp is the evidence (`README.md` rule 2).

**Target:** `immich-app/immich`
**Checkout:** clean clone of `main`
**Perspective:** deployment
**Vocabulary:** SoftwareCapability subtypes (Area 0) — *not* SolutionComponentType (design §4.2)
**Written by:** transcribed by assistant from the owners' published architecture — see Provenance
**Written at:** 2026-08-23

**Source document:** `docs/docs/developer/architecture.mdx` (in-repo)
**Source last modified:** 2026-02-26 — about six months old

---

## Why this fixture exists

`egeria-workspaces.md` was the **only** deployment-perspective ground truth, and finding 87 spent it
on a held-out run. Finding 88 then identified a structural defect — the adjudicator merges across
perspectives and consumes deployment components before the perspective-gated rules ever see them —
and concluded the fix was unbuildable *as a measured change* with no clean deployment fixture left.
**This is that fixture.** It exists to be spent once, on the per-perspective adjudication fix.

It is deliberately a different shape from `egeria-workspaces`: four components rather than
twenty-seven, one product rather than an estate of optional runtimes, and a component list the owners
publish in prose rather than one a maintainer derived.

---

## Provenance

| element | author |
|---|---|
| component set | **the Immich authors** — the numbered list in `architecture.mdx` §Server |
| descriptions | **the Immich authors** — their own one-line role for each |
| `Type:` assignments | **assistant** — the owners do not use Egeria's vocabulary |

No globs are declared. §4.2 and `README.md`: deployment components frequently own no first-party
files at all, globs are optional in this perspective, and **file-partition scoring does not apply —
component-set agreement is the only applicable measure** (plan §5a).

---

## Known doc/code drift, recorded BEFORE any run

The same document says, in its High Level Diagram section, that *"the server is split into two
separate containers `immich-server` and `immich-microservices`."* **`immich-microservices` does not
exist** in any compose file at `main` — `docker/docker-compose.yml` declares exactly
`immich-server`, `immich-machine-learning`, `redis`, `database`. The container was consolidated away
and this sentence was not updated.

Recorded here, before running anything, so that a detector NOT finding `immich-microservices` is
scored as correct rather than as a miss. This is §5.5a(b)'s vintage problem inside a single document —
the numbered list is current, the prose above it is not — and it is why the numbered list is taken as
authoritative.

**A second observation, also pre-registered:** the owners' `postgres` and `redis` correspond to
compose services named **`database`** and **`redis`**, whose `container_name` values are
`immich_postgres` and `immich_redis`. A detector naming these `database`/`immich_postgres` rather
than `postgres` is describing the same component; scoring should treat that as a naming difference,
not a miss.

---

## Components

### immich-server

- **Type:** Application
- **Notes:** Owners' description: *"Handle and respond to REST API requests, execute background jobs (thumbnail generation, metadata extraction, transcoding, etc.)"* — a TypeScript/Nest.js service. Compose service `immich-server`, container `immich_server`.
- **Provenance:** owner-published (type assigned by assistant)

### immich-machine-learning

- **Type:** Application
- **Notes:** Owners' description: *"Execute machine learning models"* — Python/FastAPI, deliberately a separate container so it can run on separate hardware or be disabled entirely. Compose service `immich-machine-learning`.
- **Provenance:** owner-published (type assigned by assistant)

### postgres

- **Type:** DatabaseManager
- **Notes:** Owners' description: *"Persistent data storage"*. Compose service `database`, container `immich_postgres`, image `ghcr.io/immich-app/postgres` (a pgvector-bearing build). Third-party runtime — owns no first-party files.
- **Provenance:** owner-published (type assigned by assistant)

### redis

- **Type:** EventBroker
- **Notes:** Owners' description: *"Queue management for background jobs"* — used via BullMQ. Compose service `redis`, container `immich_redis`, image `valkey`. `EventBroker` follows `egeria-workspaces.md`'s use of that type for queue/broker runtimes; `DatabaseManager` would be defensible for a Redis used as a store, but the owners describe it purely as a queue.
- **Provenance:** owner-published (type assigned by assistant)

---

## Excluded — not first-party deployment components

- **`immich-prometheus`, `immich-grafana`** — present in `docker-compose.prod.yml` only, as optional observability. The architecture document does not list them among the backend services, so they are out of the declared set. A detector reporting them is **not** producing false positives (§2a).
- **Mobile app, Web app, CLI** — the document's three clients. They are clients of this deployment, not containers within it.

---

## Known gaps in this ground truth

- The document lists four containers; the repository additionally ships `docker-compose.dev.yml` and `docker-compose.rootless.yml` deployment variants that the architecture page does not describe.
- **`docker-compose.dev.yml` uses the Compose `!reset` YAML tag, which `yaml.safe_load` cannot parse.** Our compose reader will return nothing for that file (gracefully). Discovered while selecting this target, recorded here because it is a detector limitation, not a repository defect.
