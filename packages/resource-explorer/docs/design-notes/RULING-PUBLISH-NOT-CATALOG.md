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

## What we say about it: Enrichment facts, optionally published

**Decision (project owner, 2026-10-08):** a database's Enrichment data is
published too, optionally, by the same press. The repository commit
already copies its judgements (`curate_plan.py`'s "what gets written":
sensitivity → Confidentiality, criticality → Criticality, retention →
Retention, plus owner and licence). The database commit does the same,
under the same rules.

**It's the module's fourth slot**, and the first one a person meets. The
three slots above describe the resource's *contents*. This one describes
*the resource as a whole*, so it lives on Curate's first tab ("What we
say about it", split-by-job reply §1), not on Contents.

| Context fact | Goes to Egeria as | Default |
|---|---|---|
| sensitivity, criticality, retention | the governance classification of that name, with author and date in its notes (as the repository commit does) | **publish**, when signed and confirmed |
| licence | the licence (observation, with its state) | **publish**, when signed and confirmed |
| owner | the owner (see the open point below) | **publish**, when signed and confirmed, once the owner mapping is ruled; kept in RE until then |
| documentation sources | external references (they already carry a GUID field) | **publish** |
| answers to the human questions | no Egeria home yet | shown with "no Egeria home yet": present and explained, never silently dropped |

**Rules, the same as everywhere else:**

- **Each fact row gets the same two-part selector**, "Publish? [ Publish |
  Keep in RE ]", beside its value. Facts are *edited* on Context. Whether
  each one *travels* is a curation choice, made here and saved like any
  other choice (signed, dated).
- **Only testimony that can be questioned travels.** An unsigned fact
  can't be published: its selector is disabled with "no author: sign it
  on Context first". An **interim** fact, or one marked **review**
  (evidence moved), defaults to **Keep in RE**, with its reason. A person
  can still choose Publish, and the row then says so.
- **One press carries it.** On a database, the Publish commit on Contents
  takes the chosen facts, and its manifest gains a row: "What we say · 4
  facts · owner, licence, confidentiality, retention · 1 kept in RE
  (criticality, interim)". On a repository, the commit that publishes the
  asset carries them, as it does today.
- **After publishing**, each fact row reads "published · read back
  ‹when›". A fact changed on Context afterward reads **"changed since
  published"**, and the tab 1 line counts them ("2 facts changed since
  the last publish · Publish again"). The fact is never re-sent silently.

**Folded like Detail:** "What we say · 4 of 5 facts will be published ·
change ›" is the whole line until it's opened. So the module stays one
line per slot for someone who takes the defaults.

**Open, for the architect: two "owners" in one classification.** RE
already writes Egeria's `Ownership` classification on everything it
publishes, set to the *requesting user*, because the curate authorization
reads it (`egeria_identity.py`). The Context **owner** is a different fact:
who is accountable for the database. Egeria gives an element one
`Ownership`. Publishing the Context owner there would overwrite what the
authorization depends on. Keeping RE's would make Egeria name the wrong
owner. Which one gets the classification, and where the other goes, is
the architecture session's call. Until it's ruled, the owner row's
selector is disabled with "kept in RE until the owner mapping is decided",
and the manifest row says the same. Once it's ruled, the selector turns
on and the manifest names where the owner goes.

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
  with the same four slots on every resource (What we say, Parts, Depth,
  Detail). Only each slot's contents
  change by kind:

  | Slot | Database | Repository | File share (later) |
  |---|---|---|---|
  | What we say | Context facts | Context facts | Context facts |
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
