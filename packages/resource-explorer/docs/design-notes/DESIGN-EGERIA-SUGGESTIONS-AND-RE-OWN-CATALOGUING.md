# DESIGN — Two doors the owner opened: suggestions to Egeria's surveys and cataloguers, and RE cataloguing on its own (2026-10-04)

**Status: options recorded, decision deferred to after the scratch-database
test.** From the design session with the project owner, 2026-10-04:
*"If we have suggestions for changing some of Egeria's surveys we can offer
them, to provide additional flexibility. Also we can have our own versions
of cataloguing in RE if needed."* Basis: `evidence/CATALOGUE-LEVER-FINDINGS.md`,
the Egeria-side reads of 2026-10-03/04 recorded in
`ASK-DESIGNER-CURATE-CATALOGUE-SCOPE-DATABASES.md`, and the designer's two
Curate scope replies.

## 1. Suggestions to the Egeria leads, from what the reads found

Each is a flexibility RE needs and Egeria's PostgreSQL connectors do not
offer today; each cites where the limit lives. Offered as suggestions, not
requirements; the Egeria leads decide what fits the connectors' design.

| # | suggestion | what the limit is today | where (Egeria df82f4fe) |
|---|---|---|---|
| S1 | **Schema-qualified names in the JDBC cataloguer's include and exclude lists** (`sales.orders`), or a per-schema table list | lists match plain table names, so "orders in sales but not in archive" cannot be said | `TransferCustomizations.java:58-96, :170` |
| S2 | **A depth option** on the JDBC cataloguer (database / schemas / tables / columns) | no depth; "schemas only" or "no columns" needs an impossible name in an include list | `RelationalDatabaseCataloguer.java` (always creates all three levels) |
| S3 | **Escape `_` and `%` when passing real names back to `DatabaseMetaData.getTables` / `getColumns`**, or filter the returned rows by exact name | a schema `a_b` also returns `aXb`'s tables, a table `x_y` also returns `xZy`'s columns, under the wrong parent (source read; live behaviour to be confirmed by the scratch test, the owner believes a guard exists) | `RelationalDatabaseCataloguer.java:335, :353, :670, :946`; `JdbcMetadata.java:101-128` |
| S4 | **Scope on the database survey**: include and exclude schema lists on `survey-postgres-database`, like the server survey's database lists | the survey measures every non-system schema, table and column; a steward who left out 22 schemas sees them measured | `PostgresDatabaseSurveyActionService.java`; `PostgresConfigurationProperty.java:112-126` is server-level only |
| S5 | **Per-target status and last-run time on the CatalogTarget relationship** | only the connector has `lastRefreshTime`; a target's own progress is invisible until its elements appear | `AutomatedCuration` / daemon status |
| S6 | **Arrays accepted where one name is passed today** in `catalog-postgres-database` request parameters | the process passes a single string per list | `RequestTypeDefinition.java:1520-1535` |
| S7 | **Read `includeViewNames` / `excludeViewNames`** or remove them | declared, never read; views follow the table lists | `JDBCConfigurationProperty.java:65-74` |
| S8 | **`deleteMethod` default** stated and `LOOK_FOR_LINEAGE` offered as the archive-by-default choice in the content pack process | null means soft delete, which drops term assignments | catalog target properties |
| S9 | **Default exclusion of system schemas** in the JDBC cataloguer | none excluded by default; every caller must send an include list | `RelationalDatabaseCataloguer.java:128` |
| S10 | **Survey annotations that say what they could not measure** (the honesty envelope the extensibility note asks for) | a column absent from `pg_stats` is simply absent from the report | `PostgresDatabaseStatsExtractor.getAnnotations()` |

Added after the scratch cataloguer test of 2026-10-04/05
(`evidence/SCRATCH-CATALOGUER-TEST-2026-10-04.md`, run live against a
throwaway database; the live behaviour, not only the source):

| # | suggestion | what the test showed |
|---|---|---|
| S11 | **Accept several names in a CatalogTarget's include/exclude lists**: honour arrays, or split a delimited string | a JSON array read back as a flattened `ArrayTypePropertyValue{…}` string and no schema was processed; comma and JSON-array *strings* were stored as plain strings and treated as one name (`TransferCustomizations.processCustomization`: a String is one name, only `List<String>` gives several, and the relationship stores configurationProperties as strings), so a database-kind target can name exactly one schema |
| S12 | **The "schema defaults to `public`" rule should apply only to tables in `public`**: no database-level pass over other schemas' tables | the docs (egeria-solutions/leveraging-postgres/overview) say a resource name is `serverName.databaseName.schemaName.tableName.columnName` "with the database schema defaulting to `public` if none is specified"; the test showed tables of five non-public schemas (a_b 1, aXb 1, s_x 2, pct 1, plain 2 of 7 built) created directly under the database as `<dbQN>::<table>`, none under a schema element, when the schema pass did not run; the throwaway had no table in `public`, so how `public` itself is treated is still to be read |
| S13 | **Delete or archive dependents with a stale schema** (schema type, tables, columns) | a soft-deleted schema left its `_schemaType` and its table ACTIVE and orphaned |
| S14 | **Exclude system schemas from pattern matches on real names** (with S3) | a table named `p%t` received about 65 `pg_catalog` columns alongside its own two |
| S16 | **Re-including a schema that was once excluded must succeed**: the stale delete must remove the `_schemaType` (and other dependents) or the re-create must adopt it | after a schema was soft-deleted as stale, its schema type kept the unique qualifiedName; re-including the schema failed with OMAG-COMMON-409-001 on `<dbQN>::<schema>_schemaType` |
| S17 | **A detached catalog target must stop being refreshed**: the connector should re-read its target list on each refresh (or on detach), or a detach should reach the running connector | after all three CatalogTarget relationships were removed (read-back: none), two forced refreshes still refreshed all three targets (OIF-CONNECTOR-0008/0009, 13 tables re-transferred); the connector keeps its list cached; whether the natural cycle, a config refresh or only a connector restart clears it was established 2026-10-05: a platform restart cleared it (the new connector's first refresh touched zero targets); whether the natural cycle re-reads the list was not observed, since the rebuild came first; a connector-only restart was not tried |
| S18 | **Cascade delete by an ordinary user should either succeed over cataloguer-created children or say which it cannot delete** | a cascade delete of a database element as a demo user removed most children, then returned AUTHORIZATION_ERROR_401 and left the seven elements the cataloguer's own user had created; deleting those individually, leaf first, succeeded |
| S15 | **Resolve or drop unused template placeholders** on template-created elements | RE's template publish left `description` and `versionIdentifier` as literal `~{…}~` strings (RE's side to supply, Egeria's side to refuse or blank) |

**Two names, side by side, so neither is "fixed" into the other:** the
stored identities the cataloguer writes are `<dbQN>::<schema>`,
`<parentQN>::<table>`, `<tableQN>::<column>` and `<schemaQN>_schemaType`
(observed 2026-10-05), where the database's qualified name comes from RE's
template, `PostgreSQL Relational Database::<host>:<port>::<database>`; the
docs' dotted four-level name is the resource's display hierarchy, not its
qualified name.

Also observed, for the record: a forced refresh is synchronous (about 16 s)
through the daemon's refresh call; the natural interval was about 34
minutes, not the configured 60; refreshes are idempotent; and the
SecretsStoreCataloguer catalogues any `.omsecrets` file it can see,
including a throwaway one.

## 2. The second door: RE catalogues on its own

RE already creates elements for repositories (`publish_sub_resources`,
`curate_commit.py`: components, blueprints, members). The same shape for
databases would have RE create DeployedDatabaseSchema, RelationalTable and
RelationalColumn elements itself for the confirmed scope, as the Catalogue
commit's own step, instead of attaching Egeria's cataloguer.

| | attach Egeria's JDBC cataloguer | RE creates the elements |
|---|---|---|
| scope fidelity | plain names only (S1); depth by impossible-name trick (S2) | exact: per-schema table choices, any depth, rules compiled to the exact set |
| timing | elements arrive on the daemon's next refresh; "attached · waiting" state | synchronous at commit; per-node proof by read-back at once |
| ongoing sync | the cataloguer re-runs every cycle: new tables appear, stale ones archived, without RE | RE must re-run on its own survey cadence (it already surveys; the publish becomes incremental, like the repo path) |
| the `_`/`%` hazard (S3) | present if real | absent: RE names elements, it never lists by pattern |
| owner and zone | zone copied from the database element; owner never set | RE sets both at creation, from Context |
| element identity | the cataloguer's deterministic qualifiedNames (`parent::name`) | RE must use the **same** qualifiedName scheme, so that attaching the cataloguer later adopts RE's elements instead of duplicating them, and so Egeria's own tools read them as the same thing |
| what Egeria's survey does | unchanged either way: it measures everything (S4) | unchanged |
| cost to build | small: attach, lists, read-back | medium: a sub-resource publisher for databases mirroring the repo one, plus archive-on-leave-out |

Neither excludes the other: RE could create the elements at commit for
exact scope and immediate proof, and attach the cataloguer afterwards for
ongoing sync, provided the qualifiedNames agree. That agreement is the one
thing to verify before choosing: that the JDBC cataloguer, attached to a
database whose schema elements RE already created under the same names,
updates them rather than creating a second set. The scratch test can
answer it with one extra step.

## 3. Decision rule and timing

Decide after the scratch test, on three facts it will establish: whether
the cataloguer mis-parents on colliding names (S3), whether it adopts
pre-existing elements by qualifiedName, and the actual refresh interval.

*Status after the first run (2026-10-05, stopped at step 5, state left for
the owner):* S3 confirmed for tables and columns; adoption not established
because the schema pass never ran (the array lists were not honoured, S11),
and the pre-made schema was soft-deleted as stale with its dependents
orphaned (S13); interval about 34 minutes, forced refresh 16 seconds. Two
string forms of the include list were tried on 2026-10-05: neither works
(S11). **A third door was found in the running build's newer code and
tested: SCHEMA-kind catalog targets.** RE creates a DeployedDatabaseSchema
from the template of technology type "PostgreSQL Relational Database
Schema" (qualifiedName `PostgreSQL Relational Database Schema::<server>::<db>.<schema>`),
attaches it to the JDBC cataloguer with no configuration, and one refresh
creates exactly that schema's tables and columns under it and nothing
else: no other schema's tables, no database-level leak from that target.
The `_`/`%` hazard survives inside it (a SCHEMA target for `a_b` also
pulled in `aXb`'s table), so RE's inventory check stays. Not yet tested:
detaching a SCHEMA target and what happens to its elements; whether the
database-level pass exists when no database-kind target is attached; and
all of it on the rebuilt platform with the 2026-10-05 fixes.

**Decision (project owner, 2026-10-05):** "Go with the schema-kind door."
It may be revisited as Egeria is enhanced and changed; the lever it rests
on (SCHEMA-kind catalog targets) and the alternatives above stay recorded
for that. As confirmed, slice B takes the third door: one SCHEMA-kind target per chosen schema, created
and attached by RE's commit, no include lists; depth below "tables and
columns" is not offered until S2 exists; leave-out detaches the schema
target and archives (behaviour to be read back); re-inclusion handles S16
by adopting or clearing the orphaned schema type; RE's manifest flags
`_`/`%` collisions across all schema and table names before attaching.

- If adoption works and the hazard is guarded: attach the cataloguer, as
  the designer's reply assumes; RE's own creation stays the fallback.
- If adoption fails or the hazard is real: RE creates the elements itself
  for exact scope and offers the cataloguer attachment as a later, optional
  "keep in sync with Egeria's cataloguer" choice once S1 to S3 land.
- Either way, S1 to S10 go to the Egeria leads as a list, with this note as
  the evidence, so the flexibility arrives at the source over time.

**Decision (project owner, 2026-10-04):** both doors are open; which one
slice B walks through is decided on the scratch test's evidence, with the
owner.
