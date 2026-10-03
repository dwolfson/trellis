# ASK — Designer: Curate for a database decides what gets catalogued (2026-10-03)

From the design session, for the designer session, at the owner's request.
Reply as `REPLY-DESIGNER-CURATE-CATALOGUE-SCOPE-DATABASES.md` in this folder;
a drawing of the scope tree on a database's Curate under `wireframes/` is
welcome. Follows your `REPLY-DESIGNER-CURATE-AND-UNDERSTANDING-ALL-KINDS.md`
(2026-10-01), whose Curate bands are built and gated; this is the piece
the owner found missing on first use.

## The owner's words

*"One thing I would expect to do in Curate is to decide what should be
catalogued: all tables? all schemas? etc."*

Your reply gave a database's band 2 two sections, glossary terms and
schema match, both waiting on readers. It did not give the database the
thing a repository's band 2 has: the **catalogue commit**, with its plan,
its "N of M sub-resources worth cataloguing" row and its depth offer. For
a database that decision is the one a steward most needs to make, and
today nothing on screen lets them make it.

## What the code says (read against main, 2026-10-03)

- **What RE publishes for a database today:** a PostgreSQL Server asset and
  a PostgreSQL Relational Database asset (from templates, carrying
  Connection, Endpoint and ConnectorType, credentials into a secrets
  collection), one SurveyReport linked by ReportSubject, Annotation
  elements (one SchemaAnalysisAnnotation for the database, one per schema,
  one per table at summary level, none per column, plus statistics, views
  and operations annotations), and LineageMapping relationships for views.
- **What RE does not create:** DatabaseSchema, RelationalTable or
  RelationalColumn elements, anywhere.
- **What Egeria's native database survey creates (read from the Egeria
  source at df82f4fe, 2026-10-03):** also no schema, table or column
  elements. Its only output is annotations on a SurveyReport, as
  ResourceMeasureAnnotations with JSON measurements: one for the database,
  one per schema, one per table, view or materialised view, and one per
  column (from `pg_stats`, so only columns of analysed tables). It has no
  scope or depth control: every non-system schema, table and column is
  surveyed, and each run makes a new report, not a diff. The only
  include/exclude lever on the Egeria side is on the *server* survey, at
  whole-database granularity. So today **nobody** in the RE-plus-Egeria
  path creates schema, table or column elements; Egeria holds the server
  and database assets, the SurveyReport and annotations only.
- **The third mechanism exists and is deployed (read from the Egeria
  source, 2026-10-03):** Egeria's PostgreSQL cataloguing is two connectors
  in sequence. The *server cataloguer* creates one RelationalDatabase per
  database on a server attached to it as a catalog target, with
  `includeDatabaseList` / `excludeDatabaseList` at whole-database
  granularity, and registers each database as a target of the second. The
  generic *JDBC cataloguer* then creates DeployedDatabaseSchema,
  RelationalTable (views as RelationalTable with a CalculatedValue
  classification) and RelationalColumn elements, with include and exclude
  lists for schema, table, view and column names. Re-runs upsert by a
  deterministic qualified name and **delete elements that have gone stale**,
  so a table left out on a later refresh is removed from Egeria. The
  quickstart loads and hosts both in its integration daemon at boot.
  Nothing in RE sets any of those lists or attaches a server as a target.
  **Runtime, checked 2026-10-03 against the dev platform with a demo
  login:** both integration groups (PostgreSQL, Database) are RUNNING in
  `qs-integration-daemon`, both cataloguers are WAITING with **zero catalog
  targets**, and the repository holds RelationalDatabase elements for
  coco_pharma and adventureworks (RE's template publish) but no
  DeployedDatabaseSchema, RelationalTable or RelationalColumn for any of
  our databases; the only such elements are templates and one content-pack
  sample. So the cataloguer has never run for us, and the premise below is
  established at runtime, not only from source.
  Three constraints come with it: the name filters match **plain names,
  not schema-qualified ones**, so "table X in schema A but not in B" cannot
  be expressed; the filters cover names only, with no row, size or depth
  option; and whether the cataloguer adopts the server and database assets
  RE already creates from templates, or makes its own by name, was not
  checked.

So the premise is: a database is catalogued whole or not at all today, and
the lever a steward's choice would pull already exists on the Egeria side,
unused: attach the server as a catalog target, and compile the confirmed
scope into the cataloguer's include and exclude lists. Per-node states then
come from reading the created elements back by qualified name. What the
lever cannot express (a per-schema table choice, a depth below "columns
on or off") the screen has to say rather than pretend.

## The questions for you

1. **The scope decision.** A tree of schemas and tables with what is known
   about each (table count, row count or "not established", data classes
   found, last activity, PII marks), and a choice per node: catalogue,
   leave out, undecided. Depth as a separate choice: the database only;
   schemas; tables; columns. Where does this sit in band 2, relative to
   glossary terms and schema match, and does the depth offer come before
   the tree or after it, as it does for repositories?
2. **What may be proposed.** A measured fact may propose inclusion or
   exclusion: a schema with zero tables, a table with no writes since 2019
   (an archive finding), a table carrying PII data classes. By the standing
   rule a proposal comes from a measurement, never a judgement, and a
   person confirms. How is a proposed scope drawn against a confirmed one,
   and what does the row say when the measurement behind a proposal
   changes after confirmation? The four observation states are the model;
   say if they fit or need a fifth here.
3. **Commit and its proof.** "Catalogue" for a database publishes the
   chosen scope at the chosen depth. Each schema and table then has a state
   with proof: catalogued (its element GUID read back), not catalogued, in
   progress (an outbox row), failed (Egeria's word). How is that drawn on
   the tree after commit, and on re-commit when the scope changes? What
   does a steward see for a table that was catalogued and later left out?
4. **Three mechanisms, one commit.** RE's publish (assets, report and
   annotations), Egeria's native survey (measurements per schema, table and
   column, no scope control) and Egeria's cataloguer (the element creator,
   with name filters). The commit's job is to set the cataloguer's lists
   from the confirmed scope and attach the target; the native survey and
   RE's publish add measurements. Should the screen name all three as what
   will happen, and how does a node show which mechanism produced its
   state: an element read back, a measurement only, or RE's annotation
   only? And two consequences of the lever need a drawing: a selection the
   plain-name filter cannot express ("orders" in sales but not in archive)
   must say so on the tree before commit, not fail after; and leaving a
   catalogued table out deletes its element on Egeria's next refresh, so
   the tree must say "will be removed from Egeria", with whatever hangs off
   that element named, before the person confirms.

5. **Ties to Find and the investigation.** A database in an investigation's
   scope with a verdict of recommended or using is the one a steward
   catalogues. Should the Curate scope tree be reachable from the
   investigation's scope grid, and should a verdict propose a scope
   ("recommended: catalogue all non-archive tables")?
6. **Governance zones and ownership at commit.** Classic's publish offers
   governance zones; the owner judgement and the licence observation
   exist on Context. Which of these does the commit carry, and does it ask
   for any that are missing before it runs, or publish and say what was
   missing?

## Constraints

Honesty rules hold: every per-table state derives from a proof row (a
GUID read back, an outbox row, Egeria's status), never from the branch the
code took; a count on the tree opens what it counted; the accent colour is
for controls only; no new glyph. The publish stays one-way and idempotent
(owner, 2026-10-01). File systems are the same shape (directories as
schemas, files as tables) and may be answered by analogy or deferred; say
which.

## What we do with the reply

One slice: the scope tree, proposals from measured facts, the commit with
per-node proof, and the depth offer, for databases. Gate on 8813 by the
owner: on coco_pharma, leave one schema out, catalogue the rest at table
depth, and see each table's state with its proof; change the scope and
re-commit; the proposal for an archive table reads as proposed until
confirmed.
