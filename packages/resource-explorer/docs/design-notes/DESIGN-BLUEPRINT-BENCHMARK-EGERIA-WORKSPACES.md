# DESIGN — The owner's hand-built blueprints as the bar: what RE derives, what it cannot, what it must be told (2026-10-08)

Design session note at the owner's word. Benchmarks: two Solution
Blueprints he built by hand in Egeria months ago for the same source
egeria_workspaces_git describes: **"Egeria Workspaces Runtimes Solution
Blueprint"** (1d1fa174…: 11 technology services plus one actor role, wires
labelled by what flows, a description, version 6.2-SNAPSHOT, member of the
CollectionFolder "Egeria Solutions", stores drawn as cylinders) and
**"Egeria Workspaces Servers Solution Blueprint"** (572ae03b…: 16
components, Egeria's own servers, four topics, client tools, a notebook
file, plus two actor roles, wires labelled by what flows). PR/CI is dumping
both read-only; this note is written from the owner's screenshots as the
coordinator relayed them and is to be checked row by row against the dump
when it lands (one table per blueprint, appended then). The bar the owner
set: *tailored, not irrelevant*. Ranked by what RE can derive by itself.

## 1. What RE derives by itself after node admission

From compose files, Dockerfiles, CI and environment variables in
egeria_workspaces_git (the Environment Deployment Blueprint's
referenced-only services and the two-ended dependency rows):

| Benchmark component | RE's evidence | Derived? |
|---|---|---|
| Kafka, PostgreSQL, Marquez, Airflow, Superset, OMAG Server Platform, Apache Web Server (nginx or httpd), Open Lineage Proxy, JupyterHub, Pyegeria-Web (Runtimes, 10 of 11) | a compose service each, `image:` naming the project | **yes**, as referenced-only services → Environment Deployment Blueprint nodes with "runs <image>" |
| the store class (cylinder for Kafka, PostgreSQL) | image family (`postgres`, `bitnami/kafka`), a `volumes:` mount, a known port | **yes, by a small map** image family → component type `store` / `service` / `proxy`; the map is reference data a person extends, never a guess beyond it |
| wires between services: "stores data" (service → PostgreSQL), "exchanges notifications" (→ Kafka), "open lineage events" (→ Proxy/Marquez), "accesses content" (→ web) | `depends_on`, environment variables holding host:port or URL (`OPENLINEAGE_URL`, `KAFKA_…`, `POSTGRES_…`), the Egeria server config files the repository holds | **the ends, yes**; **the label, partly**: see §3 |
| Egeria's own servers (Servers: Engine Host, Integration Daemon, View Server, metadata store) | the OMAG server configuration documents in the repository (`compose-configs/…/*.json`, server names and types) | **yes, by a config parser RE lacks today**: a second evidence source, the server configs, which the repository holds as files; a small detector |
| the four topics (Open Governance, Open Metadata, Open Lineage, Audit Log) | topic names in the same server configuration documents (`omrs… topic`, audit log destinations) | **yes, from the same parser**; they are `topic` nodes with Kafka as their store |
| pyegeria, hey_egeria, my_egeria, Dr.Egeria (client tools) | pip requirements of the Jupyter image (`pyegeria` as a build-time dependency), console-script names in pyegeria's own manifest when RE knows that repository | **partly**: pyegeria yes as a dependency; the named tools only when RE has surveyed egeria-python (cross-repository fact) |
| the Jupyter notebook file | the file inventory (`*.ipynb` in the repository) | **yes**, as a chosen file (brief 2a) or a file-type profile row; as a blueprint node only when a person includes it |
| actor roles (Open Metadata User, Python Programmer) | nothing in the repository | **no**: a person adds actors, always |
| description, version, Member Of "Egeria Solutions" | the README's first paragraph for a proposed description; the image tags for a proposed version; nothing for the folder | **proposed** description and version with their source; the folder is a person's choice (an existing CollectionFolder picked from Egeria) |

Ranked for the owner's bar: (1) the services with their class and the
wires' ends are derivable now from compose; (2) Egeria's servers and topics
need one more detector over the server configs the repository already
holds; (3) client tools need the cross-repository fact; (4) actors and the
folder are a person's, and the pane should say so rather than leave a gap.

## 2. What RE cannot derive and must be told

- **Actor roles** and their wires ("interacts with", "writes python code
  for", "work with markdown"): a person adds an actor from Egeria's
  `SolutionActorRole`s and draws its wire; RE proposes nothing here and
  says "actors: add one" on the blueprint.
- **Membership in a CollectionFolder**: a choice from Egeria's folders.
- **Meaning that is not in any file**: that pyegeria-web is where a user
  "accesses content" rather than a service among services is a judgement;
  RE proposes "service" and the person reclassifies.

## 3. Wire labels: derived vocabulary and told labels

RE's relation vocabulary (`runs`, `connects_to`, `reads`, `writes`,
`deployed_by`) names the mechanism; the owner's labels name **what flows**.
The bridge is a **label map keyed by (relation, target class, evidence
family)**, reference data a person extends:

| Derived (relation, target class, evidence) | Default label | Owner's label |
|---|---|---|
| `connects_to`, store `postgres`, env `POSTGRES_*`/connection string | "stores data" | stores data ✓ |
| `connects_to`, store `kafka`, env `KAFKA_*`/topic names | "exchanges notifications" | exchanges notifications ✓ |
| `connects_to`, service, env `OPENLINEAGE_URL`/`MARQUEZ_*` | "open lineage events" | open lineage events ✓ |
| `connects_to`, proxy or web, port 80/443 | "accesses content" | accesses content ✓ |
| `connects_to`, Egeria platform, env `EGERIA_*`/view server URL | "access metadata" | access metadata ✓ |
| topic → server from the server config (OMRS topic, audit log destination) | "metadata change notifications" / "audit log notifications" | ✓ both, once the config parser exists |
| anything with no map entry | the relation word itself, "connects to" | — |

So every label in the Runtimes blueprint and most in Servers are
**derivable with the map**, and the map is where "RE must be told" lives:
a label a person changes on one wire becomes a proposal to the map
("use this label for all `connects_to` → kafka?"), never a silent global
change. Labels for actor wires are told, always.

## 4. What the Environment Deployment Blueprint needs to be written like the owner's

| The owner's blueprint has | RE writes today | Needed |
|---|---|---|
| `SolutionBlueprint` with description and version | `SolutionBlueprint`, Draft, no description or version | description proposed from the README, version from image tags or the repository's tag, both editable before the write |
| member of a CollectionFolder | nothing | a folder picker from Egeria's `CollectionFolder`s; `CollectionMembership` to it (one additive write) |
| components with a type (store, service, actor) drawn differently | `SolutionComponent` with `solutionComponentType` from recovery | the class map of §1 fills `solutionComponentType` (`Data Store`, `Software Service`, `Proxy`, `Topic`); actors are `SolutionActorRole`s a person links |
| wires with labels | **no wires** (deferred: multi-link, not idempotent) | `SolutionLinkingWire` with `label` from §3 and an idempotency key `Wire::<blueprint>::<from>::<to>::<relation>` as its qualifiedName, read-before-write by that key; this is the wires follow-up already named in the two-ends rulings, and it is what makes the diagram the owner's |
| actor roles | nothing | add-from-Egeria on the pane; `SolutionComponentActor` link with a role label |
| a confirmed dependency's annotation on the component | on the repository's report (departure 1 of the two-ends rulings) | re-homed onto the component's asset once P1 exists (the annotation follow-up) |

## 5. Blueprint kinds, mapped to the owner's two

- **Runtimes** ≈ the **Environment Deployment Blueprint** of the
  node-admission note: the technology services a workspace runs, from
  compose. Derivable to the owner's bar with the class map and the label
  map, minus the actor.
- **Servers** ≈ a **Logical/Deployment blueprint of Egeria's own servers**:
  the OMAG servers, their topics and the client tools. Derivable once the
  server-config detector exists; its wires come from the configs (topics
  and connectors), its client tools from the cross-repository fact, its
  actors from a person. It belongs to egeria_workspaces_git as the
  repository that configures those servers, and the same blueprint drawn
  for egeria_git would be a Build/Logical one of the platform's code,
  which is a different kind and a different repository.

## 6. Order, on the owner's go

1. Class map and label map as reference data (two small YAML files with
   tests), the Environment Deployment Blueprint drawn with classes and
   labels from compose, description and version proposed: the Runtimes
   blueprint minus the actor and the folder.
2. `SolutionLinkingWire` with the idempotency key; folder picker; actor
   add-from-Egeria: the Runtimes blueprint written to the owner's bar.
3. The server-config detector: Egeria's servers and topics; the Servers
   blueprint minus client tools and actors.
4. Client tools from the egeria-python cross-repository fact.

## 7. Compare against the dump

When PR/CI's read-only dump of the two blueprints lands, append two
tables here: per component, found by RE / needs the config detector /
needs the cross-repository fact / a person's; per wire, label derived by
the map / told. The count of the first column over the total is the
number the owner's bar is measured by, and it is recorded in the evidence
with the dump's path.
