# Databases, filesystems, open data and models — representation brief for the designer

**Round 1: a review reply, not drawings.** Read against `main` after `#177`.
**Nothing is blocking this**, and nothing you decide here blocks the plumbing
that is being built in parallel — except one thing, called out in §3, where
your answer changes a table shape before it is committed.

Written 2026-09-20 by the design session; the project owner has ruled on the
decisions listed in §1. Round 2, with drawings, comes after the first native
survey has been read back into rows, so that you design against real
annotations rather than against the guesses in `docs/multi-resource-questions-design.md §1.4`.

---

## 0 · What this is about, in one paragraph

Resource Explorer's question model — funnel stages, twelve Perspectives,
Purposes, the `FactLayer` envelope that says *measured / nothing found / not
established / partial* — is being extended from repositories to databases,
filesystems and files, open datasets on portals, and AI models. Databases and
filesystems first. The full design is `docs/multi-resource-questions-design.md`;
§11 there is the section this brief expands. The question is not "what does
a database page look like" but **which representation actually answers each
question family**, given that the same question ("what do the columns
contain?") is asked of a Postgres column and of a column in a CSV file, and
that every answer has an honesty state that must be visible.

---

## 1 · Fixed — do not redesign

Project owner, 2026-09-20:

- **DB and FS do not go into `/next`** until repositories are complete. They
  live in the classic UI (`index.html`), which already has a database report
  (`renderDatabaseSurveyReport`, ~`:13121`) and a filesystem report
  (`renderFilesystemSurveyReport`, ~`:14744`). Your work here is what those
  should become, and what carries into `/next` later.
- **Automate is not a stage.** Schedule, subscribe and history are
  affordances on every analysis, not a place. The `automate` tab remains
  where schedules and subscriptions are *managed*.
- **The sub-resource rule.** Server → database → schema → table → column, and
  filesystem → folder → file, are one navigation pattern: sub-resource by
  default, first-class on direct registration.
- **Every result has a local snapshot history**, whoever ran the survey
  (Egeria's engine or RE). So every visual is per snapshot, and "vs. last
  time" is always available.
- **Measured is not declared.** A survey *measures* (dates x..y seen, a
  column matches a Data Class at 0.98 of sampled values); a curator
  *declares* (scope is x..current; this column *is* an email). The Curate
  surface prefills the declaration from the measurement; nothing writes a
  declaration unattended.
- **Notifications go to actors** — a person, a team, or an automated process —
  with a configurable grain. Perspectives are lenses, not actors; they carry
  preset comparator sets offered at subscribe time.
- **Twelve Perspectives stay twelve.**

---

## 2 · The question families and the representation proposed for each

This is the table you are reviewing. Each row: what the user is asking, the
proposed representation, and why. Push on any of them.

| Family | Question in the user's words | Proposed | Why this and not a list |
|---|---|---|---|
| **Inventory** (Scouting, all types) | what is here, how big, how old | **Treemap** by schema → table (area = rows or bytes) or folder → file; colour = kind (data / document / code / binary) or age band | one picture answers size, structure and staleness at once; the classic FS report is a flat list that answers none of them at a glance |
| **Data model** | do the tables relate, or is it a bag of tables | **ER graph** (Kroki Mermaid, already used for the DB ER view) with FK edges; hub tables emphasised by in-degree; orphans greyed; each table labelled with its measured *grain* ("one row per order line") | the FK graph *is* the answer; grain on the label is the single most useful thing a consumer learns from a table |
| **Column contents** (DB column *and* data-file column) | what is actually in it | **One profile card**: null bar, cardinality, top values as a mini bar, min–max or date range, width; badges for Data Class match and reference-set match, each with confidence and *measured / declared* state | same card for both resource types; the card is where a curator accepts a measured match as a declaration |
| **Sensitive-data exposure** (Assessment) | who can read the sensitive columns | **Heatmap** sensitive columns × roles; cell = readable / not; row header carries the Data Class badge | the composite is a join of two findings, and a join reads best as a grid |
| **Change over time** (Understanding) | how is it changing | **Small multiples** per table of insert / update / delete rates; a **schema-diff timeline** with add / drop / retype markers; for FS, bytes and file-count series | the trend is per object, and twenty tiny charts beat one busy one |
| **Lineage** | how do the views depend on tables | **Graph** views → tables → columns (SQLGlot output), expandable into Egeria lineage | the classic "Views & Lineage" tab has the data as text |
| **Sovereignty and scope** | where is the data, under which jurisdiction, what period does it cover | **Map** with the measured bounding box and the declared one; **timeline strip** for collection / validity / coverage; jurisdiction and controller as text | space and time are the two axes of Egeria's `DataScope`; the measured-vs-declared pair is what the curator adjusts |
| **Resilience** (Admin, Data Owner) | is it replicated, archived, backed up, restore-tested | **Status strip**, each cell with its source visible: *from the catalog* / *a person said so* / *not established* | half of these can only come from a person; the honesty state matters more than the graphic |
| **Conformance proposals** (Curate) | the survey thinks this column is an email; this column's values look like a reference set | **Review queue**: proposal, evidence (sample values, confidence), one-click *declare* / *dismiss* / *refine* | proposals accumulate; the RFA drawer is the wrong shape for a queue of dozens |
| **Data-product readiness and demand** (Assessment) | is it ready, and does anyone want it | **Two-sided checklist**: supply checks left (owner, description, licence or agreement, schema, freshness, scope), demand signals right (subscriptions, requests, existing use, feedback, similar-search hits, open RFAs); composite verdict with its state | two questions, not one; a single score would hide which side is weak |
| **Cards** (datasets, models) | what does the publisher say about it | **Rendered card** with inline check badges per section: present / thin / missing / contradicted by measurement | the card is the resource's own description; do not re-summarise it, annotate it |
| **Reachability and cost** (survey launcher) | can Egeria reach it, and which run is cheaper | **A sentence**: "Egeria can reach this (checked 2 min ago). Local run ≈ 4 s, native ≈ 40 s." with the choice | the decision needs three facts and a button, not a panel |

---

## 3 · Where your answer changes a table before it is committed

The structured tables that back all of this are being designed now
(`COORDINATOR-BRIEF-MULTI-RESOURCE.md`, stream 3). Two representation
choices change their shape, so these are the questions to answer first:

1. **The column profile card.** If one card serves DB columns and data-file
   columns, then `database_column_profiles` and the FS equivalent should share
   a column set (null fraction, distinct count, top values with frequencies,
   min, max, width, sample strategy, class matches, set matches). If you
   think the two cards should differ, say how, and the tables will differ.
2. **Snapshot granularity in the change views.** Small multiples per table
   need per-table tuple counters per snapshot (`database_table_activity`).
   If you would rather show change at schema level with drill-down, the
   table can be coarser. Per-table is the proposal.

Everything else in §2 can be redrawn without a schema change.

---

## 4 · Cross-cutting requirements

- **The envelope state is drawn, never omitted.** Unmeasured, measured-empty,
  partial and not-established look different in every visual — the treemap
  has a hatched region for "could not read", the heatmap has a third cell
  state for "not established", the card has a "no statistics collected, run
  ANALYZE" state distinct from "no nulls".
- **Per snapshot, with a picker**, and a "vs." affordance on every visual
  that has a previous snapshot.
- **One navigation control** for the sub-resource chain, both families.
- **Questions are the entry point.** A stage's page is its questions with
  their answers rendered; every visual is reached from a question. Do not
  design a menu of charts.
- **Measured / declared is a visible pair** wherever both exist: the card's
  badge, the map's two boxes, the scope timeline's two bars.
- **Absence has a reason.** A missing schema in a native Postgres survey
  means the survey user lacked permission; an empty question list for a
  type means no questions were authored; an empty profile means statistics
  were never collected. Each says so.

---

## 5 · What I would like back in round 1

A reply document in this folder, `REVIEW-MULTI-RESOURCE-REPRESENTATIONS.md`,
answering:

1. §3's two questions, first — they are the only ones with a deadline.
2. For each §2 row: keep, change (to what), or drop — with the reason, and
   with a citation to the classic UI code where the current rendering is
   the thing you are changing.
3. Which of these should be built once and shared with repositories now
   (the profile card already exists in spirit as `data_file_profiling`'s
   output; the treemap would serve repos too).
4. Anything in §1 that you think is wrong. You cannot change it, but the
   owner can, and a reasoned objection is worth more than compliance.

Not wanted in round 1: drawings, `/next` work, new intents, new
Perspectives, a scoring layer.

---

## 6 · Round 2

Triggered when stream 6/7 in the coordinator brief lands: `coco_ods`
re-catalogued, the native Postgres survey read back into rows, and RE's own
schema-and-stats step extended to `pg_stats`. At that point real column
profiles, real tuple counters and real annotation types exist. Round 2 asks
for drawings of the profile card, the treemap and the exposure heatmap
against that data, on the canvas, in the usual way.
