# REPLY — Designer: work lists and investigations (2026-09-29)

To ASK-DESIGNER-WORK-LISTS-VS-INVESTIGATIONS.md (#354), read against
main at 8c6f1845. Drawing: `wireframes/WorkListsAndScope.dc.html`, canvas
page 15.

## The answer to the owner, in one sentence

*An investigation says why, and its **scope** says which resources, of
any kind; a **work list** is a bench: one kind of resource, laid out
against one stage's questions, so you can decide which belong in a
scope.*

The confusion doesn't come from two names for one mechanism. It comes from
one name, "work list", used for four things, plus a third name,
"Members", for scope on the investigation page. That sentence should appear
on screen once, on the list of work lists (§1).

## First: the ask's premise doesn't hold

The ask says "one mechanism with two names" and sets the constraint "one
`working_sets` table, an investigation owning one". The code has **two
mechanisms in two modules**:

| | Investigation's scope | Work list |
|---|---|---|
| Tables | `working_sets` + `working_set_members` + `investigation_resource_lists` (registry.py) | `work_lists` + `work_list_members` + `work_list_runs` (work_lists.py) |
| Created by | `get_or_create_working_set(slug)` → `get_or_create_folio` | `WorkLists.create()` |
| Resource types | mixed: repos, databases and filesystems in one scope | exactly one; `work_lists.entity_type`, default `repo` |
| Member reason | `membership_rationale`, which gets **overwritten** on re-add (`ON CONFLICT … DO UPDATE`) | `rationale` + `confidence` |
| Narrowing | by verdict: per-disposition WorkingSets (`get_or_create_disposition_set`) | by a new list: `promote()` records `derived_from` |
| In Egeria | Project → ResourceList → **Folio** Collection | **WorkingSet** Collection, `WorkingSet::resource-explorer::<slug>` |
| Link between them | none | `work_lists.investigation` (TEXT), set on save if an investigation is current; nothing reads it except an unused filter (`list_all(investigation=)`) |

So an investigation does *not* use a work list for its resources. It uses a
Folio, and a work list is a separate row that can be tagged with an
investigation it doesn't feed. Everything below keeps both tables as they
are. The constraint holds for my answers; the few route changes they need
are listed at the end.

### "Work list" names four things

| Where on screen | What it creates today | What it is |
|---|---|---|
| Select bar → **save as work list** (app.js ~2147) | a list of N resources of one type | **a work list** (the bench) |
| Work list pane → **promote N →** | a narrower list with `derived_from` | **a work list** (a shortlist) |
| A report's acts → **add to work list** (app.js ~3664, `projects.py` ~2031, repos and databases alike) | a **new one-resource list on every click**, named after the report; the picked rows survive only as the rationale sentence | "I'll deal with this," beside "raise RFA" (someone must) and "note in journal". **This is the trigger**: on a database's report, the act that reads "work list" is the one a person reaches for to say "this belongs in my investigation." |
| An analysis's member list → **add to work list** (app.js ~5228, `projects.py` ~1714) | the same: one list holding only the repo, with the analysis members (files, components) reduced to prose | the same to-do act |
| Journal → **suggest to…** (`journal.py`, `SUGGESTION_PREFIX`) | one list per audience, `suggested-to-data-expert` | an inbox |

The sidebar's "Work lists · N" shows all of them together, unfiltered
(`listWorkLists()`, app.js ~2450). A steward sees their comparison bench
next to a list with one member that's really a to-do, and a list named
`suggested-to-…` that's really someone's inbox. `work_lists.py`'s own
docstring rules out the second use: activities belong in `WorkItemList`,
*"a list of activities such as ToDos"*, and a work list holds "the
RESOURCES being worked on, not the activities being done to them."

I couldn't read the live counts (the `/api` calls returned 401; the
browser session has expired), so I can't say which of these the owner's
"Work lists · 3" were. The code shows every kind can appear there.

## 1. Vocabulary and the sidebar

**Ruling: (b), except "working set" never appears on screen.** Three words,
one for each thing:

- **investigation**: why. Purposes, charter, verdicts. Egeria: Project.
- **scope**: which resources, of any type. This is already the word on
  screen: the "In scope" chip, "＋ scope / − scope", and the crumb. The one
  holdout is the investigation page's **"Members (N)"** heading, which
  becomes **"Scope · N"**. Egeria: the Folio, reached through ResourceList.
- **work list**: the bench. One resource type, compared as rows ×
  questions, narrowed by shortlisting. Egeria: WorkingSet, whose own
  definition, "a list of elements that are being worked on", fits. The name
  stays, and from now on it means only this.

"Working set" is the code's word and Egeria's type name. It appears where
provenance goes: in the publish evidence ("published as a WorkingSet
collection"), never as a label.

Why not the other two options:

- **(a) "an investigation is a work list with a purpose"** reverses the
  relationship. An investigation *has* a scope and may keep several lists
  beside it: shortlists, per-disposition sets, and the bench it started
  from. Under (a), the suggestion inbox would also be "a work list with a
  purpose."
- **(c) every list starts as an investigation, purpose Explore.** Explore
  is a real purpose, not a default. `egeria_binding` defaults to `egeria`,
  so every scratch comparison would become a Project candidate. It also
  loses the order of work: people compare *before* they know why, and the
  bench is where they find out.

How the three words read by perspective. A **steward** reads "scope" as a
boundary they can govern. A **data owner** sees their database as "in scope
for Customer 360", which answers the question they actually have (who is
looking at my thing, and why). An **app builder** uses the bench and
rarely needs the investigation at all. Nobody has to learn "working set".

**The sidebar** (drawing, panel A), top to bottom:

1. Investigation selector, unchanged.
2. When one is current, two lines directly under it:
   - **Scope · 7**, which opens the "In scope" chip. A count opens what it
     counted.
   - **Work lists for Customer 360 · 2**, using the `list_all(investigation=)`
     filter that already exists.
3. **Other work lists · 3**, folded to that one line while an investigation
   is current. With none current, the section reads **Work lists · N** and
   lists them all, as today.
4. **Suggestions · N** (the `suggested-to-*` inboxes), on their own line,
   not among work lists. They stay present and explained, not hidden.

The list of work lists (the ▦ front door) gets the one-sentence definition
as its opening line, not just in the empty state.

## 2. The two missing actions

Both go on the **work list pane's action row**, beside "publish to Egeria",
and on each row of the list of work lists. They don't go on the sidebar
row: one click there opens a list, as it does now.

**"Add these 9 to Customer 360"** (the button names the current
investigation, never "scope" alone). With rows ticked, it reads
**"Add 3 selected to Customer 360"**. With no investigation current,
it reads **"Add to an investigation…"** and opens a picker listing the open
investigations plus "start a new one". Each member's `rationale` goes in as
`membership_rationale`, so the reason carries over; a member with no rationale gets "from work list *Sales databases*". A member already in
scope is **skipped, not re-added**: re-adding overwrites that member's
existing reason. The note says "2 were already in scope; their reasons were
kept."

**"Start an investigation from this list…"** In two clicks: this button,
then **Start** in a dialog prefilled with name = list name, description =
list description, the purpose chips unselected (purposes are optional in
`InvestigationCreate`), and the **binding shown and chosen** (local or Egeria;
default Egeria, per the model). "Start" creates the investigation, adds the
members as above, tags the list with the investigation, and makes it
current.

**Afterwards, the list stays.** It doesn't disappear, as the ask proposed.
It moves to "Work lists for Customer 360" in the sidebar. The list is the
record of how the scope was chosen: its `derived_from` trail and its grid
of answers are the evidence behind the decision. Deleting the bench would
delete that evidence.

What the list shows once linked (panel B):

- A header line, **"7 of 9 in scope for Customer 360 · 2 not added"**,
  computed live against `list_investigation_members` and never stored. The
  two tables are separate, so this is a copy, not a share. If someone later
  removes a member from scope, the line becomes "6 of 9". Drift shows up; it
  doesn't hide.
- A scope column on each row with the words **in scope** / **not in scope**,
  in ink. No new glyph and no accent color: it's a state, and `glyphs.js`
  doesn't need a sixth table.

## 3. The comparison grid

**Yes: the investigation page carries the grid for its scope.** The page's
Scope section *becomes* the grid, and the members table merges into it
rather than sitting beside it (panel C).

- **One grid per resource type.** A scope is mixed and each type has its
  own question catalog (`listAnalyses(entity_type, { intent: stage })`).
  Tabs: **Repos 4 · Databases 2 · Filesystems 0**. The zero tab stays,
  muted, with the line "nothing of this kind in scope".
- The members table's columns (disposition, reason, remove) become the
  grid's left columns: one table instead of two.
- The section's heading line links the work lists tagged to this
  investigation ("work lists: Sales databases, Candidate repos"), so the
  bench is one click from the scope it fed.
- The questions come from one stage at a time, with a stage row above the
  grid, defaulting to the last stage the person was on. That's how the work
  list pane already works.
- Batch runs need no new table: `enqueue_batch(work_list_slug="")` already
  runs without a list.

**The grid isn't the only thing a list is for.** A work list still has
things a scope can't have: it's one type throughout, it has no purpose (you
can compare before you know why), it narrows by shortlist with a
`derived_from` trail, and it can be published on its own. The two narrow
differently, and that difference is worth keeping: **a list narrows by
making a new list; a scope narrows by verdict** (disposition). The
investigation grid's narrowing control is "mark as…", not "promote".

If the slice has to be small, ship §1, §2 and §4 first. The gate doesn't
depend on the grid.

## 4. Adding from the sidebar, and from a finding

**The select bar.** With an investigation current: **"＋ add to Customer
360"** and **"− remove from Customer 360"**. Long names truncate at 24ch,
with the full name in the title. **"save as work list…"** comes after them.
With none current: **"＋ add to an investigation…"** is *enabled* and opens
the same picker as in §2. After adding, that investigation becomes current,
and the note says so: "Added 3 to Customer 360, now your current
investigation." "− remove" stays visible but disabled, with the reason as
visible text in the bar ("no investigation selected"), not only in a
tooltip. Today both buttons are dashed and disabled, and only the tooltip
explains why.

**The report and member-list acts (the actual trigger).** "add to work
list" becomes **"add to Customer 360"**. It puts the resource in scope,
with the act's provenance line (already computed as `line`) as
`membership_rationale`, and the record learns it was used (`add_use`,
act `scope`). With none current, it reads **"add to an investigation…"**. If
the resource is already in scope, the act reads **"already in Customer
360's scope"** as text. It doesn't re-add, because re-adding overwrites the
existing reason. "Note in journal" remains the way to record the finding
against it.

This means these acts stop minting one-resource work lists. The "I'll deal
with it" to-do they were standing in for belongs in `WorkItemList`, as the
module's own docstring says. That's a separate ask, and I haven't folded it
in here.

The gate as stated then passes. A person adds a database to an
investigation from the sidebar, or from its report, without seeing the words
"work list". They can turn a saved list into an investigation in two clicks.

## What the slice changes

| Change | Kind |
|---|---|
| "Members (N)" → "Scope · N"; select-bar, report-act and member-act labels as above | wording |
| Sidebar: scope line, lists for this investigation, other lists folded, suggestions separated | UI; `list_all(investigation=)` exists; the suggestion split is a prefix filter |
| `RecordAct` and the member-promote body accept `action: "scope"` + `investigation` | route |
| Set `investigation` on an existing work list (the column exists; there's no route to set it) | route |
| "7 of 9 in scope" | computed client-side from two existing reads |
| Investigation grid | UI; reuses worklist.js's renderer with a scope source |

No schema change.

## Left open, for the architect

1. When an investigation is promoted to Egeria and a work list linked to it
   is published, both collections exist, but nothing relates the WorkingSet
   to the Project. `investigation_resource_lists` keys on `working_sets`,
   not `work_lists`, so relating them isn't possible without a model change.
   Is that link wanted?
2. The one-resource lists and `suggested-to-*` inboxes already created:
   leave them (they show under "Other work lists" and "Suggestions"), or
   migrate them once the to-do ask lands?
3. Adding from the sidebar with no investigation current makes the chosen
   one current. I think that's right, because the crumb and every stage page
   follow the current investigation. The owner should confirm.

Not folded: `stages/investigation.js` has its own emoji `DISPOSITION_GLYPH`
table (👁🔬👍✅🪦🚫), another glyph map outside `glyphs.js`. I'm noting it for
the glyph consolidation, not for this slice.
