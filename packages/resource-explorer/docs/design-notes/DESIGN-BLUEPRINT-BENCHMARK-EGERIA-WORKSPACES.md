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

## 0. The bar is metadata, not drawing (owner, 2026-10-08)

*"Egeria constructs the blueprint diagram from its metadata as part of its
query response. All the rules for creating the mermaid diagram are
embedded in Egeria. There is nothing special we need to do: we just create
components, wires, ports, etc. and Egeria creates the blueprint; that is
true for all mermaid diagrams in Egeria."*

So the bar this note measures against is **metadata completeness**, and
nothing in RE draws a blueprint for Egeria. What Egeria needs written, as
the dump shows the owner's own blueprints carry it:

- `SolutionBlueprint` with `description`, `versionIdentifier`, member of a
  `CollectionFolder` by `CollectionMembership`;
- `SolutionComponent` members with `solutionComponentType` (Egeria's own
  value set) and `plannedDeployedImplementationType`, `description`,
  `versionIdentifier`, `url`; content-pack components adopted by their
  qualifiedName, never duplicated;
- `SolutionLinkingWire` between components with `label`, `description`,
  `oneWay`, and `iscQualifiedNames` where an information supply chain
  applies, written with an idempotency key;
- `SolutionActorRole` members and `SolutionComponentActor` links with
  `role` and `description`;
- `SolutionComposition` where one component is composed of others (25 in
  the dump), which is how Egeria draws nesting: a **relationship**, not
  membership, and the right form for "this platform hosts these servers"
  if the owner ever wants it drawn inside the blueprint rather than as
  `deployed_by` rows.

**Ports.** The dump holds **no `SolutionPort` element at all**: every one
of the 208 `SolutionLinkingWire`s attaches component to component. So RE's
compose-declared ports (the `ports:` mapping the recovery reads as "ports
and wires") are not blueprint elements; they are **evidence** for a wire's
existence and for a component's `url`, and nothing more. The recovery's
own "port" vocabulary stays internal to the IR and never reaches Egeria as
an element. If a later blueprint needs Egeria's `SolutionPort`s, that is a
distinct design; nothing here.

**Consequences for RE's own drawing.** RE's mermaid diagram in Curate
(`surveyors/arch_recovery/mermaid.py` through Kroki,
`renderComponentDiagram`) is a **review preview** of the metadata RE would
write, nothing else. The "Environment Deployment Blueprint has no diagram"
remark in the node-admission note is not a gap to build: once the wires
exist in Egeria, Egeria Explorer and the Portal draw it. The preview a
person needs before writing is the smallest that lets them confirm the
wires: **the two-ends dependency table itself**, with a "will become a
wire" mark on rows whose both ends are members and the label the map
proposes, is enough; a drawn preview stays as it is today and is not
extended (the dependency slice's edge-port drawing is preview-only and
must not grow). The screenshot of RE's "OMAG-Server-Platform" blueprint,
seven stacked boxes with no wires and no actor, is therefore purely missing
metadata: no wires, no actor roles, no composition written, and the
self-membership of §6a.

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

## 4. What the Environment Deployment Blueprint needs written, so Egeria draws it like the owner's

| The owner's blueprint has | RE writes today | Needed |
|---|---|---|
| `SolutionBlueprint` with description and version | `SolutionBlueprint`, Draft, no description or version | description proposed from the README, version from image tags or the repository's tag, both editable before the write |
| member of a CollectionFolder | nothing | a folder picker from Egeria's `CollectionFolder`s; `CollectionMembership` to it (one additive write) |
| components with a type (store, service, actor) drawn differently | `SolutionComponent` with `solutionComponentType` from recovery | the class map of §1 fills `solutionComponentType` (`Data Store`, `Software Service`, `Proxy`, `Topic`); actors are `SolutionActorRole`s a person links |
| wires with labels | **no wires** (deferred: multi-link, not idempotent) | `SolutionLinkingWire` with `label` from §3, `description`, `oneWay=false`, `iscQualifiedNames` when told, and an idempotency key `Wire::<blueprint>::<from>::<to>::<relation>` as its qualifiedName, read-before-write by that key; this is the wires follow-up already named in the two-ends rulings, and it is what makes Egeria's diagram the owner's |
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

## 6a. "An OMAG Server Platform does not contain an OMAG Server Platform" (owner, 2026-10-08)

The blueprint RE wrote earlier for egeria_git (`SolutionBlueprint`
254dbbe6, displayName "OMAG-Server-Platform", deployment perspective) has
seven members: a component also named "OMAG Server Platform" and six
others (active-metadata-store, engine-host, integration-daemon,
nanny-daemon, simple-metadata-store, view-server). The owner is right that
it is wrong, in two ways.

**Cause.** The recovery's clustering names a cluster after its root
component, and the materialiser writes the cluster as a blueprint
*containing* its root and its children. So the blueprint and its root
component share a name, and the platform appears as a member of itself.
The six others are not parts of the platform either: they are **OMAG
servers hosted on** the platform, runtime instances the compose and
server configuration files declare. The owner's own blueprints show the
right shape: in "Runtimes" the platform is one component among peers
(Kafka, PostgreSQL, Marquez …), and in "Servers" there is no platform
component at all; the servers, topics and tools are the peers.

**Rule.**

1. A blueprint's name never equals a member's name. The name is the kind
   and the repository, per brief 1 ("Egeria Deployment Blueprint"), never
   the root cluster's name.
2. A root component is a member like any other; a cluster's root carries
   no special place in the blueprint.
3. "Hosted on" / "runs on" is a **relation between nodes**, from the
   dependency vocabulary (`deployed_by` / `runs`), never a membership. A
   server hosted on the platform is a node with a wire to the platform
   node labelled "hosted on"; it is not a child of the platform in the
   blueprint's membership.

**How the deployment blueprint shows platform and servers.** Two readings,
both supported by the owner's examples, chosen by the blueprint's kind:

- In the **Environment Deployment Blueprint** (≈ his Runtimes), the
  platform is one node among the technology services; the servers hosted
  on it are **not** drawn as separate nodes, because at that level the
  platform is the deployment unit. His Runtimes blueprint has exactly
  this: "OMAG Server Platform" beside Kafka and PostgreSQL, no servers.
- In the **Servers blueprint** (≈ his Servers, a Logical/Deployment
  blueprint of Egeria's own servers), the servers are the nodes, with
  their topics and tools, and the platform is not a node at all; if a
  person wants the hosting shown, the platform appears as an edge port
  with "hosted on" wires, never as a container of the servers. His
  Servers blueprint has no platform node, which is the stronger
  precedent: at that level the platform is the environment, not a peer.

So RE draws the platform **or** the servers in one blueprint, never both
as container and contents; which one is the blueprint's kind. The
recovery's cluster is still useful: it tells RE that these six are hosted
on that one, which becomes six `deployed_by` rows and, in the Servers
blueprint, the optional edge port.

**What to do about 254dbbe6.** Egeria rolls forward, never undoes, and no
rename call exists in RE today for a blueprint. Options, with the exact
writes, for the owner's decision:

| Option | Writes | Effect | Leaves behind |
|---|---|---|---|
| **(a) leave it** | none | the next accepted verdict on egeria_git, on the fixed build, creates "Egeria Deployment Blueprint" with the platform as one member and the six servers as `deployed_by` rows; 254dbbe6 stays as it is | a second blueprint for the same repository, the old one wrongly named and wrongly shaped, visible in Egeria Explorer beside the right one until a steward retires it there |
| **(b) rename-forward only** | one merge update of 254dbbe6's `displayName` (and `qualifiedName`'s perspective slot) to "Egeria Deployment Blueprint", the same mechanism as the file-type rename-forward: a property update, no delete, no membership change | the name stops lying; the shape still does (seven members including the platform) | the self-membership and the six wrong memberships, which no RE call removes; a steward may detach the six `CollectionMembership` links in Egeria by hand |
| **(c) both: rename-forward, then re-materialise under the rule** | the rename of (b), then on the next accepted verdict RE finds the blueprint by its new qualifiedName (adoption by name), keeps the platform component as a member, and writes six `deployed_by` annotations (the two-ends form) instead of memberships; the six existing memberships are **not** removed by RE | one blueprint, rightly named, with the right new facts beside the old wrong memberships, which Egeria Explorer still draws as members | the six old membership links, until a steward detaches them in Egeria; the same-named component stays as the platform node, correctly a member |

**Recommendation: (c)**, with the detachment of the six old memberships
done by the owner in Egeria Explorer (a stewardship act, six detaches, no
RE code), because it yields one blueprint and keeps every RE write
additive. (a) is cleaner for RE and worse for a person looking at Egeria,
who sees two blueprints for one repository. (b) alone fixes the word and
not the shape. Whichever he chooses, the fix to the materialiser (name
from kind and repository; root as an ordinary member; hosting as
`deployed_by` rows) ships regardless, since it is what prevents the next
one.

**Exact write for (b)/(c)'s rename**, for the record: `update_element`
(merge) on 254dbbe6 with `displayName="Egeria Deployment Blueprint"` and
`qualifiedName="SolutionBlueprint::repo::egeria_git::deployment::Egeria
Deployment Blueprint"`, read back by GUID, recorded as an activity row
"blueprint renamed forward · 254dbbe6 · OMAG-Server-Platform → Egeria
Deployment Blueprint · owner-directed <UTC>"; nothing else touched.

## 7. Compared against the dump (2026-10-08)

Dump by PR/CI, read-only: `benchmark-blueprints.json` (summary),
`blueprints-raw.json`, `blueprint-components-raw.json` in PR/CI's scratchpad
(2 blueprint reads at depth 3, 24 member reads, 0 errors, no credentials).
Facts from it that correct or sharpen §1–§4: the blueprint's qualifiedName
is `SolutionBlueprint::<IDENTIFIER>::<displayName>` (identifiers
`EGERIA-WORKSPACES-RUNTIMES`, `-SERVERS`) with `versionIdentifier`
6.2-SNAPSHOT and a description, Member Of the CollectionFolder "Egeria
Solutions" by `CollectionMembership`, **self-anchored, no ZoneMembership
and no Ownership on the blueprint or any member** (the configured-only
rule RE adopted matches the owner's own practice); members are
`SolutionComponent` or `SolutionActorRole`, self-anchored, with
`identifier`, `description`, `versionIdentifier`,
`solutionComponentType` (Software Service · Data Storage · Data
Distribution · User Interface · Software Library · Console Command · one
"PYEGERIA"), `plannedDeployedImplementationType` (SoftwareServer, or a
specific type: Marquez Server, Engine Host, View Server, Topic, Jupyter
Notebook File, pyegeria) and usually `url`; two qualifiedName forms, RE's
own `SolutionComponent::<IDENTIFIER>::<name>` and the content-pack form
`Egeria:ValidMetadataValue:<Type>:deployedImplementationType-(<type>)::<name>`
for components Egeria's content packs already define (the platform,
Marquez, Airflow, Superset, the four Egeria servers, pyegeria, the notebook
file). Wires: `SolutionLinkingWire` with `label`, `description`,
`oneWay=false`, optional `iscQualifiedNames` naming an
InformationSupplyChain; actor links `SolutionComponentActor` with `role`
and `description`, no label.

So the class map of §1 is Egeria's own `solutionComponentType` value set,
and where a component is one Egeria's content packs define, RE should
**adopt the content-pack element by its qualifiedName** rather than create
a second component (the platform, the servers, Marquez, Airflow, Superset,
pyegeria): the same adoption-by-name rule as everywhere else, and it is
why the owner's two blueprints share members.

### Per component

| Component (type · planned impl.) | Runtimes | Servers | RE finds it by | Class |
|---|---|---|---|---|
| OMAG Server Platform (Software Service · OMAG Server Platform) | ✓ | — | compose service `image: odpi/egeria-platform`; content-pack element adopted by name | derivable now |
| Egeria Workspaces PostgreSQL Server (Data Storage · SoftwareServer) | ✓ | — | compose service, image family `postgres`, volume | derivable now |
| Apache Kafka (Data Distribution · SoftwareServer) | ✓ | — | compose service, image family `kafka` | derivable now |
| Marquez Server (Data Storage · Marquez Server) | ✓ | — | compose service; content-pack element | derivable now |
| Apache Airflow Server (Data Distribution · Apache Airflow Server) | ✓ | ✓ | compose service; content-pack element | derivable now |
| Apache Superset (User Interface · Apache Superset) | ✓ | — | compose service; content-pack element | derivable now |
| Apache Web Server (Software Service · SoftwareServer) | ✓ | — | compose service, image family `nginx`/`httpd` | derivable now |
| Open Lineage Proxy (Software Service · SoftwareServer) | ✓ | ✓ | compose service | derivable now |
| JupyterHub (Software Service · SoftwareServer) | ✓ | — | compose service | derivable now |
| Pyegeria-Web (Software Service · SoftwareServer) | ✓ | — | compose service with a `build:` context in the repository → **built here**, a component of this repository as well as a runtime | derivable now |
| Engine Host, Integration Daemon, View Server (Software Service · their types) | — | ✓ | the OMAG server configuration documents in the repository; content-pack elements | needs the server-config detector |
| Open Governance / Open Metadata / Open Lineage / Audit Log Topic (Data Distribution · Topic) | — | ✓ | topic names in the same configuration documents | needs the server-config detector |
| pyegeria (PYEGERIA · pyegeria) | — | ✓ | the Jupyter image's pip requirements → build-time dependency; content-pack element | derivable now as a dependency; as a blueprint member once the cross-repository fact exists |
| hey_egeria (Console Command), my_egeria (User Interface), Dr.Egeria (Software Library) | — | ✓ | console-script and package names in egeria-python's manifest | needs the cross-repository fact |
| Jupyter Notebook File (Data Storage · Jupyter Notebook File) | — | ✓ | the file inventory (`*.ipynb`) | derivable now; a member only when a person includes it (brief 2a) |
| Open Metadata User (actor) | ✓ | ✓ | nothing in the repository | a person's |
| Python Programmer (actor) | — | ✓ | nothing in the repository | a person's |

**Counts.** Runtimes: 10 of 11 members derivable now from compose (the
actor is a person's). Servers: 1 of 16 derivable now as a member (the
notebook file, by inclusion), 7 more with the server-config detector (3
servers, 4 topics), 2 more as the Airflow and Proxy services already
found, 4 with the cross-repository fact (pyegeria and the three tools), 2
actors a person's. So the Runtimes blueprint meets the owner's bar at
step 1 of §6; the Servers blueprint reaches 10 of 16 at step 3 and 14 of
16 at step 4, the two actors always told.

### Per wire (internal links only, as the dump counts them)

| Wire (end1 → end2) | Label | Derivation |
|---|---|---|
| Superset, OMAG Platform, Airflow, Marquez → PostgreSQL | "stores data" | `connects_to` + store class `postgres` + env family → map ✓ |
| OMAG Platform → Kafka | "exchanges notifications" | `connects_to` + store class `kafka` → map ✓ |
| Open Lineage Proxy → Kafka; Airflow → Open Lineage Proxy | "open lineage events" (ISC) | `connects_to` + env `OPENLINEAGE_*` → map ✓; the InformationSupplyChain name is told (a person's, or the map's when one ISC is configured) |
| Open Metadata User → Apache Web Server | "accesses content" | actor link: a person's |
| pyegeria, hey_egeria, Dr.Egeria, my_egeria → View Server | "access metadata" | `connects_to` + Egeria view-server URL → map ✓ once the clients are members |
| Jupyter Notebook File → pyegeria | (none) | file imports pyegeria: the file inventory plus the notebook's imports, derivable |
| Engine Host, Integration Daemon → Audit Log Topic | "audit log notifications" | server config (audit log destinations) → map ✓ with the detector |
| Open Governance Topic → Integration Daemon, Engine Host | "configuration change…" | server config → map ✓ with the detector |
| Open Metadata Topic → Integration Daemon, Engine Host | "metadata change notifications" | server config (OMRS topic) → map ✓ with the detector |
| Airflow → Proxy, Proxy → Open Lineage Topic, Open Lineage Topic → Integration Daemon | "open lineage events" (ISC) | compose env and server config → map ✓; ISC told |
| actor → component links with a role | role words | a person's |

**Counts.** Runtimes: 7 of 8 internal links derivable with the map (the
actor's is told). Servers: 17 of 19 derivable with the map once the
server-config detector and the client members exist (the two actor links
are told); the notebook → pyegeria wire is derivable from imports with no
label to invent.

**What the dump adds to §4.** Three things RE did not have in its plan:
`versionIdentifier` and `description` on **components** as well as the
blueprint (proposed from the image tag and the compose service's
`container_name`/labels, editable); `url` on most components (derivable
from the compose port mapping and the host RE serves from, proposed); and
`iscQualifiedNames` on lineage wires, which names an InformationSupplyChain
a person chooses from Egeria. And one correction: RE's class map is not
RE's; it is Egeria's `solutionComponentType` value set, read from Egeria
as valid values, with RE's image-family → type mapping as the only thing RE
owns.
