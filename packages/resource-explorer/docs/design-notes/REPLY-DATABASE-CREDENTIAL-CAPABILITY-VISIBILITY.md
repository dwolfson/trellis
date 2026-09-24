# Reply: database credentials and access — the model is Egeria's, the probe is RE's

**Replying to:** `ASK-DATABASE-CREDENTIAL-CAPABILITY-VISIBILITY.md` (#251).
**From:** the design session, 2026-09-24, at the project owner's request.
**Read against:** `main` at `00f3b615`; Egeria Java source at
`/Users/dwolfson/localGit/egeria-v6/egeria` (matches the running platform
version, per `PROBES-2026-09-21.md`).
**Status:** an opinion for the project owner to turn into a ruling. Piece 1
of the ask (the visibility probe and banner) does not wait on any of it.

---

## 0 · What the source says, that the ask could not see

Four facts, each with a location, that decide most of the three questions:

1. **An asset can carry any number of Connections.** The `ResourceConnection`
   relationship is *at most one* asset per connection and *any number* of
   connections per asset (`OpenMetadataTypesArchive.java` ~`:279-302`, ends
   `connectedResources` / `resourceConnections`). "Several credential sets
   for one database" is therefore several `Connection` elements on the same
   asset, each wrapping its own embedded `SecretsStoreConnection` with its
   own `secretsCollectionName`. Nothing needs inventing on the Egeria side.
2. **The role of a credential set has a native slot.** `ResourceConnectionProperties
   extends LabeledRelationshipProperties` (`:32`): the *link* between the
   asset and each connection carries `label` and `description`. "surveyor",
   "reader", "admin" belong there — on the relationship, not on the
   connection and not in a new RE table.
3. **Egeria picks the connection by metadata security, not by capability.**
   `ConnectionHandler.getConnectionForAsset` (`generichandlers/ConnectionHandler.java:95-155`)
   fetches every connection on the asset, most recent first, then delegates
   to `securityVerifier.selectConnection(userId, asset, connections, …)`.
   The default security connector
   (`OpenMetadataAccessSecurityConnector.java:2628-2674`) keeps the
   connections the *requesting user may read* — zones and security tags on
   the `Connection` element — and returns one. **There is no capability or
   scope vocabulary on a Connection anywhere in the type model.** Which
   credential a native survey runs with is a function of who the engine
   host's user is and which Connection elements that user can see.
4. **Two defects in that selection.** Same method: when exactly one
   connection is visible it returns `connectionEntities.get(0)` — the first
   of the *unfiltered* list — instead of `visibleConnections.get(0)`
   (`:2666-2669`). An asset with an admin connection first and a surveyor
   connection second, seen by a user allowed only the second, gets the
   admin one. And when several are visible it picks one **at random**
   (`:2670-2674`, the comment says so). Neither affects RE-local surveys,
   where RE chooses; both affect every native survey.

Also confirmed from the incident itself: Postgres system catalogs
(`pg_namespace`, `pg_class`, `pg_attribute`) are readable by any role
regardless of `USAGE`/`SELECT` grants; only `information_schema` and
`pg_stats` are privilege-filtered. So a credential can always see *that* a
table exists even when it cannot read it. **The blind spot has a known
denominator**, which is what makes piece 1 exact rather than a warning.

---

## 1 · Q1 — where the model lives: Egeria, using what exists; RE keeps an index

**Recommendation.** One `Connection` per credential set on the database
asset; each with its own secrets collection in RE's own client-side store
(#185, one collection per *(resource, role)* rather than per resource);
the role on the `ResourceConnection` link's `label`; and each Connection
zoned or security-tagged so the security connector decides who may use it.
That is the whole model, and it is Egeria's.

RE's registry gains **`database_credentials` as a cache and index, not a
source of truth**: `(slug, connection_guid, role, secrets_collection_name,
last_probe_at, capability jsonb)`. Its job is to let the launcher list
choices and show the last probe without a round trip. The `DatabaseEntity`
keeps a *default* connection reference, which is what today's single
`db_user`/`db_password` pair becomes.

**Retire `databases.db_password`.** It is a clear-text `TEXT` column
(`registry.py:2185`) holding a value the secrets store already holds since
#185. The migration is: write the existing value into the resource's
collection if none exists, then drop the column. `db_user` can stay as a
display field.

**Do not build an RE-owned multi-credential store.** It would duplicate
three things Egeria already does — multiple connections, secrets
collections, access control on who sees which — and the native survey path
would ignore it anyway (fact 3).

---

## 2 · Q2 — enumeration and choice: different answers for the two routes

| Route | Who chooses | How |
|---|---|---|
| **RE-local survey** (rule B local, `executes_at: resource-explorer`) | RE, for the signed-in user | list the asset's connections through pyegeria (the security connector filters by user); read each link's `label`; pick the **least-privileged connection whose probed capability satisfies the step's requirement** (§3); let the user override from that list |
| **Egeria-native survey** (`executes_at: egeria`) | the security connector, for the engine host's user | RE cannot pass a connection; the action target is the asset. **Operational rule:** the survey engine's user must be able to see exactly one connection per asset — the surveyor one — via zones or security tags, because the default picks at random among several and, with one visible, may return the wrong one (fact 4). Until the upstream fixes land, this rule is what makes native surveys deterministic |

"Elevate the credential" stays out of scope for RE, as the project owner
said. RE's part is the **RFA to the database owner**, raised by the probe:
"connected as `egeria_user`: SELECT on 3 of 26 tables; grant SELECT on
`coco_ods.*` or register a broader connection on this asset." The RFA
carries the exact object list, which the probe has.

**pyegeria to verify (one probe):** which call lists an asset's
connections with their `ResourceConnection` relationship properties, so the
label is readable. `ClassificationExplorer.get_relationships` on the asset
filtered to `ResourceConnection` is the likely answer; confirm it returns
the relationship's `label` and not only the far-end element.

---

## 3 · Q3 — declare the requirement per step; derive the capability by probing, never by declaring

**Per step, not per analysis.** Steps open connections; analyses are
presentation. `requires_capability` goes on `StepInfo` next to
`fetch_cost`/`compute_cost`; the analysis catalog inherits the strongest
requirement among its steps for display, the same way it already presents
cost.

**Coarse vocabulary, four values:**

| Value | Means | Postgres check |
|---|---|---|
| `catalog` | system-catalog reads only | always true for a connected role |
| `read` | SELECT on the target tables | `has_table_privilege(role, t, 'SELECT')` per table; `has_schema_privilege(role, s, 'USAGE')` per schema |
| `stats` | the monitoring and statistics views (`pg_stat_*`, `pg_stats` beyond one's own tables) | `pg_has_role(role, 'pg_monitor', 'member')` or `pg_read_all_stats` |
| `write` | never for a survey; only for a future repair step | `has_table_privilege(…, 'INSERT')` — probed, never exercised |

Finer vocabularies (per-schema, per-table) are **results of the probe**,
not values of the requirement: a step requires `read`; the probe says
`read` holds on 3 of 26 tables; the gate reports the fraction.

**The probe is a Scouting-tier step, `credential_capability`**, rule C,
`fetch_cost: api`, `compute_cost: low`, one connection, catalog reads only,
no trial writes. Output, stored on `database_credentials.capability` and
published as a `ResourceMeasureAnnotation` on the survey report:

```
connected_as: egeria_user
schemas: visible 6 of 8   (pg_namespace vs has_schema_privilege USAGE)
tables:  select 3 of 26   (pg_class vs has_table_privilege SELECT), by schema
stats:   false            (not pg_monitor)
write:   false
probed_at: …
```

**The gate mirrors cost-tier gating.** A step whose requirement the
connected credential does not fully meet is never run silently. The
launcher labels it — "needs `read`; this credential has `read` on 3 of 26
tables" — with three choices: run partially and say so; pick another
visible connection; raise the RFA. This is the same shape as the
prerequisite proposal in design §17.1 and should share its rendering.

---

## 4 · The third completeness state

Every envelope for a database fact gains one more state alongside
*measured* and *not established*: **measured within credential scope**,
with the fraction attached. "How big is this database" on `coco_pharma`
renders "3 tables, 32 columns — as `egeria_user`, which can read 3 of 26
tables in 6 of 8 schemas" and never again "3 tables". The credential
identity is recorded on every survey row (`source` already distinguishes
who ran it; add `surveyed_as`) and on the report, which is also what
Egeria's own Postgres survey annotations say in their explanation text
("missing schemas indicate the survey userId lacks permission").

This is the `find-absence-as-answer` shape the ask named, with the
denominator supplied by the system catalog.

---

## 5 · What to file upstream

| Target | Item | Evidence |
|---|---|---|
| Egeria server | `selectConnection` returns `connectionEntities.get(0)` when exactly one connection is visible; should be `visibleConnections.get(0)` | `OpenMetadataAccessSecurityConnector.java:2666-2669` |
| Egeria server | random selection among several visible connections; propose deterministic order (most recent, or a `ResourceConnection.label` match against a request parameter such as `connectionRole`) so a survey can ask for the surveyor connection | `:2670-2674` |
| pyegeria | confirm or add a read of an asset's connections *with* the `ResourceConnection` relationship properties (label) | probe in §2 |

Neither server item blocks piece 1. Both should be fixed before the
operational rule in §2 is relied on in a multi-connection deployment.

---

## 6 · Sequence

1. **Now, no ruling needed:** `credential_capability` probe; banner and the
   third envelope state; `surveyed_as` on survey rows; the RFA. (Piece 1
   of the ask.)
2. **On the ruling for §1:** one Connection per credential set with a
   labelled link and a per-role secrets collection; `database_credentials`
   index; retire `db_password`; migrate `coco_ods`/`coco_pharma`, which
   need delete-and-recreate anyway (`PROBES-2026-09-21.md`).
3. **Then:** `requires_capability` on `StepInfo` for the database steps
   that exist (`postgres_schema_and_stats` → `catalog`; column profile and
   data-class matching → `read`; `postgres_operations` → `stats`); the
   launcher gate; connection choice for local runs.
4. **Alongside:** file the two Egeria issues; verify the pyegeria read.
