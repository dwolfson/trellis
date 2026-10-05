# ASK — Designer: one verb for "saved in RE", one for "sent to Egeria" (2026-10-05)

From the design session, for the designer session, at the owner's request
after using the Curate page. Reply as `REPLY-DESIGNER-SAVE-AND-PUBLISH-VERBS.md`
in this folder; no drawing needed unless a control changes shape. Two
related points from the same walk are ruled by the design session and are
being built now (below); this ask is the vocabulary.

## What the owner saw

On one Curate page the controls that save a person's input use five
different words with no stated rule: tags **add** (a bare link), ratings
**Submit**, the journal **Write** (the shared component, also on
Disposition), group **change**, and the scope tree **catalogue** / **leave
out** / **confirm**. None of them says whether the action saves into RE's
own record or sends something to Egeria. Everything on the page today is
the former: the Catalogue commit that publishes the scope is the next
slice and is not built.

## The question

One verb for *saved now in RE's own record*, and a different, reserved
word for *anything sent to Egeria*, applied across the Curate bands,
Disposition's journal, Context's rows and the scope tree. The design
session's position for you to confirm or change:

- **Save** for RE's record (tags, ratings, journal entries, group, Context
  judgements and observations, scope choices). Where the control is a
  choice rather than a form, the choice's own word stays on the control
  ("catalogue", "leave out") and the saved state is what carries the rule:
  the row reads "saved · <who> · <when>" after the click.
- **Catalogue** for the commit that sends a database's scope to Egeria, and
  **Publish** for sending a resource or a report to Egeria elsewhere; never
  "submit" or "write" for either.
- The two never share a control, and a control that does both says both,
  in order ("Save, then catalogue").

Does "Save" read right beside the journal's append-only nature (the
designer's earlier ruling: no edit, no delete of signed entries)? Is
"Write" worth keeping there as the one exception, since a journal entry
is written rather than saved?

## Ruled by the design session, being built now (for your information)

- **The scope section says where its state lives.** Every click in "What
  gets catalogued" is already saved immediately as a signed, dated event
  in RE, and nothing goes to Egeria until the commit. The section's header
  gains the line "Saved in Resource Explorer · not yet catalogued in
  Egeria", the same shape as the Egeria facts elsewhere ("local only ·
  resource not published"); when the commit lands, the header carries the
  pending difference between the saved scope and the catalogued one.
- **The scope section collapses.** With 29 schemas it pushes the glossary
  and schema-match sections off screen. Collapsed, it shows its essentials
  on one line ("Your scope: 2 of 29 schemas · declared by <who> <date> ·
  Egeria's latest survey covers 29 schemas, 266 tables"); open by default
  until a scope is declared, collapsed after, remembered per person per
  database. This follows your round-2 "fifth visit" ruling: later visits
  open on what changed, not on the whole tree.
