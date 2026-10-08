# ASK — Designer: splitting Curate by the job a person is doing (proposal, not a decision) (2026-10-08)

From the design session, for the designer session, at the owner's request.
Reply as `REPLY-DESIGNER-CURATE-SPLIT-BY-JOB.md` in this folder; a drawing
of the stage strip and of each tab on a repository and on a database under
`wireframes/` is the most useful form. **This is a proposal for your
reaction, not a decision.** It waits behind the current work (the Egeria
reset and the slices in flight) by the owner's order.

## The owner's words

> We have now made the curation step so complicated with so many parts and
> options that only an expert can navigate it. I think that we might need
> to consider splitting it into 2 or 3 tabs, and we may even choose to hide
> some with a mode like basic use vs advanced use; this is perhaps a
> stepping stone to what we discussed earlier about having a separate,
> simpler tool for non-experts. For instance, in the case of repos, there
> might be a simple curation step that includes information from enrichment
> and basic information about the repo, while in an intermediate step we
> might curate information about modules and blueprints, and in advanced we
> might include everything else.

## What Curate holds today (read on main, 2026-10-08)

On a repository, one pane carries: the "what it is" lines to confirm; the
"what's in it" selection tree (Include | Leave out per file and folder,
proposals, containers, the manifest and "Publish N items"); "what it's made
of" (component tree with verdicts, the blueprint selector, the container
shape); "how it relates" (the two-ended dependency table by kind, with
confirmation); the Publish band (publish the survey report whole, the
Egeria reports list, forget links, project-context choices); the generic
controls (tags, rating and category, notes via the journal, group); the
glossary and data-class block; the By-analysis tab; the commit steps list.
On a database: the scope tree (schemas and tables with the selector), the
manifest and Catalog button, the steps list, the term and logical-schema
proposals, the data-class rules block, the generic controls, By analysis.
The design session has not counted the controls; a count per kind is the
first thing the reply could ask the coordinator for.

## The proposal: split by job, not by expertise

The design session's reading of the owner's three levels is that they are
three **jobs**, and a split by job keeps one source of truth per count,
whereas a basic/advanced mode would hide counts a person then contradicts
elsewhere (the status-words rule).

| Tab | The question it answers | Repository | Database | Who presses it |
|---|---|---|---|---|
| **1. Describe and publish** | what do we say about this resource, and is it in Egeria | confirmed Enrichment facts (licence, owner, sensitivity…), tags, rating, notes, group; "Publish to Egeria →" of the survey report; the Egeria reports list; forget links; project context | the same | anyone; this is also the whole of what the non-expert tool would do |
| **2. Catalog the contents** | which parts become Egeria assets | the selection tree, proposals (worthiness), containers, the manifest, "Publish N items", the scope record | the schema and table scope tree, the manifest, "Catalog N schemas", the commit steps | a steward deciding scope |
| **3. Architecture and relations** | what RE proposes about structure, and what a person confirms | components and verdicts, the blueprint selector and shape, the dependency table with confirmations, term and data-class confirmations, data-class rules | term and logical-schema proposals, data-class rules, dependencies when they exist | an architect or data steward |
| **By analysis** (existing) | what has been done with all of the above | the curation-record analyses | the same | anyone |

Rules the proposal keeps: tabs never disappear (your ruling), so tabs 2
and 3 stay in the strip with their counts, "Catalog contents · 3 chosen ·
26 undecided", "Architecture · 12 proposals awaiting you"; tab 1 is the
default landing; every count derives from the same record as the tab it
names; the cue vocabulary applies unchanged inside each tab.

## The questions for you

1. **Is the split by job right, or would you cut it differently?** Two
   tabs (describe-and-publish versus everything that catalogs or
   confirms), three as above, or four with "relations" its own.
2. **Modes.** The owner floated basic versus advanced. The design session's
   position is a saved preference that collapses tabs 2 and 3 by default
   rather than a mode that hides them, for the status-words reason. Do you
   see a mode that is honest, and what would it hide?
3. **The commit steps list and the manifest** belong to the press that
   starts them (tab 2 for a catalog, tab 1 for a publish). Does a running
   commit show on every tab, or only where it was pressed?
4. **The stepping stone.** Tab 1 as drawn is the non-expert surface. Is
   that the right seed for the separate chat-first application, and is
   there anything in tab 1 that an expert needs and a non-expert must not
   see?
5. **Per kind.** A file system's Curate, when it exists, would take the
   same three tabs; does anything in the split assume a repository?
6. **What to measure first.** The control count per kind, and which
   controls the owner pressed in two days of gate walks; would you want
   those numbers before drawing?

## The same shape for Understanding (owner, the same day)

> The other thing I'd point out is that we might want to structure the
> Understanding stage similarly.

Understanding today, on a repository, lists every chart kind (stars,
commits, languages, health, file types, weekly commits, top committers,
survey history) and the changes-since-last-run banner; on a database, the
three charts, the trend, the survey-history table with invalid rows, the
three-number line, the ranked tables, the Views section, the changes
banner. It has the same shape of problem: one long pane, every kind of
reader at once. The same split by job would read:

| Tab | The question | Repository | Database |
|---|---|---|---|
| **1. At a glance** | what is this and how is it doing | the overview tiles, health, the changes-since-last-run banner, the survey-history trend | the three-number line, the changes banner, the trend |
| **2. Inside it** | what does it contain, and how is that distributed | file types, languages, top committers, weekly commits | schemas, tables and column-type charts, the ranked tables, the Views section |
| **3. Over time and in detail** | how has it changed, and what exactly ran | survey history with invalid rows, per-run detail, the runs dialog | the survey-history table with invalid rows, per-table growth, per-run detail |

The same rules: tabs never disappear, counts on the tab names, the first
tab the landing, the cue vocabulary inside. Two questions in addition to
the six above: (7) does one split serve both stages, so a person learns
it once, or do Curate's jobs (decide, confirm, publish) and
Understanding's (look, compare, trace) want different tab names with the
same three-level shape? (8) The context-as-product note's "on a screen"
form is Understanding's tab 1 plus Curate's tab 1 seen by a non-expert;
is that the surface the chat-first application renders, and does it
change what belongs on either tab 1?

## Constraints

Status words derive from proof rows; tabs never disappear; the accent is
for controls, never states; no new glyph; the cue vocabulary of your
2026-10-06 reply applies inside each tab unchanged. Nothing in this ask
changes what RE writes to Egeria; it changes only where a person finds the
control.

## What we do with the reply

Nothing until the owner decides; if he adopts the split, one slice per kind
that moves existing sections under the tabs without changing them, gated
by use: the owner describes and publishes a resource from tab 1 alone
without opening the others.
