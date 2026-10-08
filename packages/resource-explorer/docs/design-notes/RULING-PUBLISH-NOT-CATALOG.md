# RULING — Publish is the one Egeria verb; what a database publishes is chosen by parts, depth and facets (2026-10-08)

From the designer session, recording the project owner's decision of the
same day. It supersedes the reserved verb **Catalog** in
`REPLY-DESIGNER-SAVE-AND-PUBLISH-VERBS.md` (and its 2026-10-06 spelling
decision) and the "Catalog N schemas" wording in
`REPLY-DESIGNER-CURATE-CATALOGUE-SCOPE-DATABASES.md`,
`REPLY-DESIGNER-STATE-AS-VISUAL-CUE.md` and
`REPLY-DESIGNER-CURATE-SPLIT-BY-JOB.md`. Read against main at 62bcd4ad.

**Decision (project owner, 2026-10-08):** "Catalog" is an overused word.
On a database a person chooses to publish some parts and not others
(schemas but not their tables, the database but no schemas, everything but
the keys), so one word for "send the whole thing to Egeria" doesn't
describe the act. **Publish is the one verb for anything sent to Egeria.**
The button names what goes.

**Decision (project owner, 2026-10-08):** besides depth, a person may
leave out **keys**, **statistics** and **data classes**. Within
statistics, **row counts** are useful to most people and **column
profiles** aren't. Row counts that come only from the database's own
catalog can be out of date with the data, so their source and age must
show. Descriptions (table and column comments) aren't offered as a choice:
they're always published.

## The verbs, now

| Family | Control | Result line |
|---|---|---|
| Saved in RE | **Save**, or the choice's own word | "saved · who · when" |
| Sent to Egeria | **Publish**, always with its object | "published · read back ‹when›"; before that, "sent · waiting for Egeria" |

"Catalog", "cataloged" and "Catalogue" leave every control, tab name,
result line and manifest row. The word survives in one place: **the name
of Egeria's own component**, quoted as Egeria names it in detail lines
("Egeria's PostgreSQL cataloguer refreshed · …"), because that's the name
a steward will search for in Egeria.

## What a database publishes: three choices, one button

The Contents tab (split-by-job reply) holds three choices, top to bottom.

**1. Parts: the scope tree.** Schemas and tables, Include | Leave out,
unchanged from the scope rulings. The column header becomes **"Publish?"**.

**2. Depth: how far down each included part goes.**

> Depth · ○ the database only · ○ schemas · ● tables · ○ tables and columns

This is unchanged, and all four depths are expressible (lever findings §1).

**3. Detail: what's published about each part.** Three toggles under the
depth line, each saying what it governs and what it can't:

| Facet | Default | Governs | The honest limit |
|---|---|---|---|
| **Keys** (primary, foreign) | on | key relationships on published columns | Egeria's cataloguer writes keys with the columns it creates, and no list in its configuration turns that off (lever findings: the lists are names only). Until it can be told, the toggle is shown and explained: "keys: can't be left out yet: Egeria's cataloguer writes them with the columns". It's never silently ignored. Keys appear only at "tables and columns" depth anyway. |
| **Statistics** | row counts **on**, column profiles **off** | the statistics annotations in RE's survey report | **Row counts:** each published count carries its source and as-of in the annotation, and the manifest says so ("row counts · estimates from the database's statistics, last analyzed 10-03"; "measured 10-07" when a scan ran). **Column profiles:** off by default, on for those who want them. **Egeria's own survey** measures what it measures. If the commit runs Egeria's survey, its report carries its own statistics whatever this toggle says, and the manifest says that in its survey row: "Egeria's survey records its own measurements · leave the survey out ›". |
| **Data classes** | on | the data-class findings RE attaches to columns | RE controls these fully: they're RE's annotations. |

Descriptions aren't on the list. A published table without its comment is
a worse table, and no one asked to withhold one.

**The button carries all three choices:**

> **Publish 2 schemas · tables · no column profiles**

Only the choices that differ from the defaults are named, so the common
case stays short ("Publish 2 schemas · tables"). After the press, the
result line on each row reads "published · read back ‹when›", and the
manifest's rows read:

| | what | how many | when |
|---|---|---|---|
| RE publishes | server, database, survey report | 2 elements, 1 report (row counts; no profiles) | now |
| Egeria's cataloguer creates | your included schemas, at table depth | 2 schemas | this refresh |
| Egeria's survey | the same schemas | 2 | after attach |

## How this simplifies, rather than adding controls

The owner's aim is to simplify and modularize, so the three choices must
cost nothing for someone who doesn't need them:

- **Detail is folded by default** into one line under the depth: "Detail ·
  keys, row counts, data classes · change ›". A person who never opens it
  publishes the defaults, and the button stays short. Only a changed
  default is named on the button. Count: one link on the page, not three
  toggles.
- **One verb.** Save for RE, Publish for Egeria. The vocabulary shrinks
  from three reserved words to two.
- **One module, every kind.** "What gets published" is the same component
  with the same three slots on every resource. Only each slot's contents
  change by kind:

  | Slot | Database | Repository | File share (later) |
  |---|---|---|---|
  | Parts | schemas, tables | files, folders (the selection tree) | directories, files |
  | Depth | database … columns | resource … items | share … files |
  | Detail | keys, statistics, data classes | survey report facets | sizes, data classes |

  A person learns it once, and a builder writes it once, with each kind
  supplying its slot contents. That's the split-by-job reply's Contents
  tab, made the same module for every kind.

## Repository, for symmetry

A repository already says "Publish to Egeria →" for the survey report and
"Publish N items" for its parts. Nothing changes there except the
commit-steps heading: "Catalog · commit …" becomes "Publish · commit …"
on every kind.

## What changes in the code (for the wording slice)

- Every control and result string: "Catalog" / "cataloged" / "Catalogue"
  → "Publish" / "published". The `glyphs.js` keys `catalogued` and
  `catalogue_failed` keep their glyphs, with the words "published" and
  "failed".
- The scope tree's column header: "Include in catalog?" → **"Publish?"**.
- The facet toggles as a new scope-record field, saved like depth (signed,
  dated, in the scope record), so a later commit and a reset re-publish
  the same choices.
- The one stored question that keeps "catalogued" as its key (wording
  slice note): unchanged until questions have stable ids, as already
  planned.

Design-note filenames keep their names (`…-CATALOGUE-…`); their prose moves
to "publish" as each is next edited.
