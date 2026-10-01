# ASK — Designer: work lists and investigations, one thing or two? (2026-09-29)

From the design session, for the designer session, at the owner's request.
Reply as `REPLY-DESIGNER-WORK-LISTS-VS-INVESTIGATIONS.md` in this folder; a
drawing of the sidebar and of one investigation page under `wireframes/`
is welcome.

## The prompt, verbatim from the owner

*"What is the difference, really, between a work list and an investigation?
Should an investigation use a work list for its resources?"*

Trigger: adding a database to an investigation from the sidebar uses
work-list naming, and the sidebar shows "Work lists · 3" as a section
beside the investigation selector, as if they were two kinds of thing.

## What the code says

They are one mechanism with two names.

- The registry has `working_sets` and `working_set_members`. An
  investigation owns exactly one working set
  (`investigation_working_set_slug`, `get_or_create_working_set`); adding a
  resource to an investigation goes through `add_working_set_member`
  (`web/routes/investigations.py` ~223–238). A sidebar "work list" is a
  working set with no investigation attached.
- `app.js` already states the intended distinction in a comment at ~872:
  *"Investigation is why a body of work exists, a work list is which
  resources it covers."* Nothing on screen says this.
- In Egeria, an investigation maps to a `Project` with a `ProjectCharter`
  (its purposes) and its working set to a `ResourceList`
  (`investigation-framing-design.md`; `EgeriaInvestigationPublisher.ensure_working_set`).
  That mapping is exactly the why/which split: the charter is why, the
  resource list is which.
- What a work list can do today that an investigation's set cannot, as a
  first-class thing: be compared as rows × questions in the Scouting
  grid, run a survey definition across all rows, and be saved from a
  multi-select. What an investigation has that a work list lacks: a
  purpose (from `VALID_PURPOSES`), a scope crumb that every stage page
  follows, verdicts per resource, and a published Egeria project.

So the owner's second question already has its answer in the data model:
an investigation *does* use a work list for its resources. The open
question is the first one, as a person experiences it.

## The questions for you

1. **Vocabulary and the sidebar.** Two names for one mechanism cost the
   owner a question in his first week. Options to react to: (a) one word,
   "work list", everywhere, and an investigation is "a work list with a
   purpose"; (b) "working set" as the neutral name for the mechanism,
   "work list" for a standalone one, and an investigation's resources
   shown *as* its working set under the investigation, not in the sidebar
   section; (c) drop the standalone kind from the sidebar and make every
   list start as an investigation with purpose "explore". Which reads best
   to a steward, a data owner and an app builder, given the perspectives
   chips above?
2. **The two missing actions.** "Start an investigation from this work
   list" (the list becomes its scope; it disappears from the standalone
   section) and "add this work list's members to investigation X". Where
   do they live, and what does the list show afterwards?
3. **The comparison grid.** Today it belongs to work lists (rows ×
   questions, batch runs). Should an investigation's page carry the same
   grid for its scope, so the two experiences converge, or is the grid the
   *only* thing a standalone list is for?
4. **Adding from the sidebar.** The trigger: on a database's row, the add
   action says "work list" while the person thinks "investigation". What
   should the row's add action read, and what happens when an investigation
   is selected versus none?
5. **A stage click while a work list is open.** Found 2026-09-30 fixing an
   unrelated routing bug: a work list replaces the main pane for whatever
   stage is current, and clicking a different top-nav stage (including
   Investigation, Understanding or Automate) does not close the work list —
   it keeps showing, under the new stage's nav highlight. Is that the right
   behavior (a work list is its own view, independent of stage, until the
   person explicitly exits it), or should navigating to a stage — especially
   a frame stage like Investigation — close an open work list first?

## Constraints

The data model does not change for this: one `working_sets` table, an
investigation owning one. Honesty rules hold: a list's row shows the same
state marks as everywhere else (`glyphs.js`). The Enrichment sub-tab ask
(#350) is separate; do not fold the two.

## What we do with the reply

One UI slice: sidebar and add-action wording, the two actions, and whatever
you decide about the grid; gate is task-based (a person adds a database to
an investigation from the sidebar without meeting the word "work list"
unless the designer keeps it, and can turn a saved list into an
investigation in two clicks). Until then nothing changes on screen.
