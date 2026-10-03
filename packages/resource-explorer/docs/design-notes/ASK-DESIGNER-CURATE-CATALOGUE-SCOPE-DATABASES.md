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
  RelationalColumn elements, anywhere. The only path that would is Egeria's
  own native survey service, which RE can start ("Catalog and Survey" in
  Egeria's own surveys, today locked for want of template parameters); what
  that survey creates, and whether its depth is configurable, was not read
  and is a question for the Egeria side.
- **Depth control: none.** The publish takes whatever the latest measured
  schema set holds, every schema and every table. The request carries only
  connection and credential fields; there is no include or exclude list.
- **The repository counterpart** is repo-only by construction: the curation
  plan, the SubResource row, locator selection, `publish_sub_resources`,
  and the depth offer all read the repository table; no database or file
  system path exists.
- **Proof rows a database has:** `published_at` and the report GUID on the
  survey row, an `egeria_publish` step run on the Survey Definition path,
  the asset GUID, and a catalogue log row naming the server and database.
  Nothing per schema or table.

So the premise is: a database is catalogued whole or not at all, with
nothing between, and nothing a steward chooses.

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
4. **RE's publish versus Egeria's native survey.** Two mechanisms can put a
   database into Egeria: RE's publish (assets and annotations, no schema
   elements) and Egeria's own survey service (which may create schema
   elements). Should the commit choose between them, run RE's then offer
   Egeria's, or should the screen name both as what will happen? The
   steward should never have to know the mechanism, but they must be able
   to see which one produced what.
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
