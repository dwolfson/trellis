# For the discussion with the Egeria leads (2026-10-05)

Prepared by the Resource Explorer design session for the project owner, to
take to the Egeria leads. Everything here was read from the Egeria source at
df82f4fe, observed on the dev platform, or measured in the scratch
cataloguer test of 2026-10-04/05 (`evidence/SCRATCH-CATALOGUER-TEST-2026-10-04.md`,
`evidence/CATALOGUE-LEVER-FINDINGS.md`). The full suggestion list with
file:line evidence is `DESIGN-EGERIA-SUGGESTIONS-AND-RE-OWN-CATALOGUING.md`
(S1–S15). This note is the agenda: six topics, what we found, what we ask.

**Version caveat, added the same day.** The owner reports that the Egeria
lead found and fixed bugs on 2026-10-05 that may explain some of these
findings. Everything below was read from the source at df82f4fe
(2026-09-15) and observed on the quickstart image running on the dev
platform, whose build checkout is not established. Before any item is
raised as a defect, it is re-checked against the fixed build: the scratch
test is repeatable (throwaway database, forced refresh, read-back), and
each topic names the observation so the re-check is one comparison. Items
that the fixes resolve move from "defect" to "confirmed fixed in <version>"
here; the design questions (envelope, scope lever, which mechanism,
relationship type) stand either way.

*What the running platform is (established 2026-10-05, read-only):* the
dev platform reports version 6.2-SNAPSHOT; the quickstart image was built
2026-10-03 from a pinned upstream `odpi/egeria-platform:latest` digest, not
from our checkout; its JDBC connector jar contains the 2026-09-22 commit
fcb804149b (new `CatalogTargetKind`, `JDBCDatabaseCatalogTarget`), so the
cataloguer that ran the scratch test is newer than our df82f4fe citations
for it. `JdbcMetadata.java` and `TransferCustomizations.java` are
byte-identical between df82f4fe and upstream main, so topic 3's pattern
and exact-match findings stand on current source. Upstream main is 70
commits ahead at d395c18f; any fix from 2026-10-05 is absent from the
running image, so a re-check needs a new image pin and a platform
restart.

*A lever we had not read, from that newer code:* a catalog target can
now be of kind SCHEMA ("one schema of a database, and nothing else in that
database"), handed a DeployedDatabaseSchema by the
`catalog-<vendor>-schema` processes, as well as kind DATABASE ("every
schema in it"). A per-schema scope without include lists is a candidate
third door for topic 4: RE creates the DeployedDatabaseSchema for each
chosen schema and attaches each as a SCHEMA target, and the cataloguer does
tables and columns. Tested on the scratch state on 2026-10-05: it works
(one refresh created exactly that schema's tables and columns under it,
nothing else), and the owner chose it for RE's commit.

*After the 2026-10-05 rebuild from today's upstream image:* the JDBC
cataloguer jar is byte-identical to the 2026-10-03 one, so topics 3 and 4's
cataloguer findings stand; what landed is scope on the database survey
(`includeSchemaNames` / `excludeSchemaNames`, ebafb08fdc), which closes
topic 2's survey item once a run confirms it, and a platform restart was
observed to clear the cataloguer's cached target list (a detached target
kept being refreshed until then).

## 1. The annotation vocabulary and an honesty envelope

**What RE needs.** Every analytic result, Egeria's surveys and RE's own
steps alike, carries a small required envelope: *measured*, *not
established* with a reason, or *not applicable*, plus the run that produced
it. RE's whole user interface derives its state words from that
distinction, and a result that renders "nothing" where it never looked is
the defect we keep paying for.

**Where Egeria is today.** The PostgreSQL database survey emits
ResourceMeasureAnnotations with JSON measurements at database, schema,
table and column level, and says nothing about what it could not measure:
a column absent from `pg_stats` is simply absent from the report (S10).

**To discuss.** The extension of the annotation types that you and Mandy
are already working on: can the envelope be part of it, as a small set of
required attributes on every annotation type, so RE's readers become
generic over annotation type rather than per analysis
(`DESIGN-ANALYTIC-EXTENSIBILITY-WORKING-ASSUMPTIONS.md` A2, R5).

## 2. Scope: what a steward chooses gets catalogued, nothing more

**What RE needs.** A steward's confirmed choice of schemas, tables and
depth, stored and signed in RE, compiled into whatever Egeria needs so that
a republish or a reset keeps it (the designer's Curate scope reply). The
Coco case: coco_pharma grew from 7 to 29 schemas when the scenarios were
extended; without a stored scope, whatever is added is catalogued silently.

**Where Egeria is today.** The JDBC cataloguer's include and exclude lists
are the only lever, and in the test a JSON array in the catalog target's
`configurationProperties` was **not honoured** (read back as a flattened
string; no schema processed) (S11); the `catalog-postgres-database` process
passes one string per list (S6); names match plain, exact, case-sensitive
strings, so "orders in sales but not in archive" cannot be said (S1); there
is no depth option (S2); the database survey has no scope at all, it
measures every non-system schema, table and column (S4). String forms of
the lists are being tried today.

**To discuss.** Schema-qualified names or per-schema lists; a depth option;
arrays or a documented string form; and scope on the database survey, so
that a steward who left out 22 schemas does not see them measured anyway.

## 3. Correctness of the cataloguer on real names

**What we found.** The cataloguer passes real schema and table names back
to `DatabaseMetaData.getTables` / `getColumns` as LIKE patterns: in the
test, table `x_y` received `xZy`'s columns, and `p%t` received about 65
`pg_catalog` columns (S3, S14). A database-level pass catalogued the tables
of five non-public schemas directly under the database when the schema pass
did not run, which the docs' "schema defaults to `public`" rule does not
explain (S12). A soft-deleted schema left its schema type and table active
and orphaned (S13).

**To discuss.** Escaping `_` and `%` or filtering returned rows by exact
name; restricting the public default to `public`; deleting or archiving
dependents with a stale parent. The owner believes guards exist; the
evidence says where to look.

## 4. Mechanisms, and which one RE should drive

**What we found.** Three separate mechanisms put a database into Egeria:
RE's publish (assets, report, annotations, no schema elements); the native
survey (annotations only); the two-stage cataloguer (the only element
creator), reached by attaching a catalog target, with elements arriving on
the daemon's cycle (about 34 minutes in practice, 60 configured; a forced
refresh is synchronous, 16 seconds). No Egeria process combines cataloguing
with surveying; "Catalog and Survey" is RE's own name for its own method.

**To discuss.** Whether RE should attach Egeria's cataloguer (ongoing sync
for free, scope limited by the lists above) or create the schema, table and
column elements itself for the exact scope and attach the cataloguer later
for sync (the second door). The condition for both is that the two agree on
qualified names (`<dbQN>::<schema>`, `<parentQN>::<table>`,
`<tableQN>::<column>`), which the test could not yet establish because the
schema pass never ran. Also: the docs' dotted four-level name versus the
stored `::` identities, recorded side by side.

## 5. Relationships RE will propose: repository informs database

**What RE needs.** When a repository defines, loads, reads or governs a
database (the Coco data lives in egeria-workspaces and loaded coco_pharma),
RE measures the mechanism and proposes the relation; a person confirms; RE
publishes it. The owner's ruling: it is **not lineage**, which implies
information flow; it is closer to a dependency.

**To discuss.** Which relationship type carries it, and whether, once
published, Egeria's own watchers (governance actions, Notification Manager)
can raise a change at one end against the other, so RE is not the only
detector (`DESIGN-FIND-AND-INTEGRATE-PURPOSES-AND-THE-DATA-LENS.md` §13).

## 6. Smaller items with evidence

- Per-target status and last-run time on the CatalogTarget relationship,
  which today has neither; only the connector reports a time (S5).
- `includeViewNames` / `excludeViewNames` declared and never read (S7).
- `deleteMethod` default (null = soft delete, drops term assignments) and
  `LOOK_FOR_LINEAGE` as the archive-by-default choice (S8).
- No system schemas excluded by default in the JDBC cataloguer (S9).
- Template-created elements keep `~{…}~` placeholders in description and
  version when a caller leaves them unset (S15).
- The SecretsStoreCataloguer catalogues any `.omsecrets` file it can see,
  including throwaways.
- pyegeria: `AssetMaker.get_catalog_targets` sends a relationship type as
  the element type and always fails (egeria-python ISSUE-122, with the
  working body).

## What RE will do regardless

Store the scope in RE and compile it on every commit; derive every state
word from a read-back; keep the plain-name and `_`/`%` checks in its
manifest until the cataloguer no longer needs them; publish one-way and
idempotently; propose relations and never judge them. The discussion
decides how much of that Egeria makes unnecessary.
