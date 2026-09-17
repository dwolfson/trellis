# The three acts on a report

**Date:** 2026-09-14 · **Against:** `main` at `91d6d93` (after `#82`) — as you
report it; my local checkout stops at `#81`, so C is taken from your note rather
than read
**Drawn at:** `design_handoff_list_answers/ReportActs.dc.html` (new; page one,
below `Report` and `Records`)

You named this as not built, with the correction act. This is the acts; the
correction act is still a gap and I say so at the end rather than folding it in.

The thing to get right: **the three acts on a report are not the three acts on a
list.** A list's selection is live, so an act on it is an act on what is true.
A report's rows are frozen, so an act on it is an act on **what was true** — and
everything below follows from making that visible rather than hiding it.

---

## 1 · The default is the whole report

A list footer defaults to nothing selected. **A report footer defaults to all of
it:**

> **The whole report · 32 rows** · as recorded 2026-09-13
> add to work list · raise RFA · note in journal · *or pick rows to act on some
> of them*

The rows were already chosen once — that is what saving them was. Row-picking
stays available for the person triaging a report they were handed, but it is the
secondary path, not the gate.

## 2 · What each act creates points at the record

This is the whole of it. The rationale and the RFA detail are the provenance
line promotion already composes, **plus the record**:

> 32 of 32 dependencies · from `dependency_analysis`, run 2026-09-13 ·
> **as recorded in "Dependencies to review before 6.2"**

- **add to work list** — *"I will deal with this."* Lands as
  *now in "Dependencies to fix before 6.2"* — the list's **name**, never its
  slug, as promotion learned the hard way.
- **raise RFA** — *"Someone must."* The RFA **points at the record**, so the
  person who receives it opens exactly what the person who raised it was looking
  at. An RFA that re-queried instead would make the record decorative — and the
  record being the thing you hand over is the entire argument for it existing.
- **note in journal** — *"Worth knowing."* The entry opens **seeded with a
  citation, not a sentence**:

  > Per "Dependencies to review before 6.2" (2026-09-13): ▏

  and the cursor after it. This act is what makes real the link I specified when
  I said records live *beside* the journal rather than inside it: a journal entry
  citing a record joins what someone thought to what was true when they thought
  it. Never a canned body — the person writes the thought; the citation is all
  the machine supplies.

**None of the three re-derives the list.** The server acts on the stored
snapshot. The moment one of them re-queries, a report becomes a bookmark.

## 3 · When the report's evidence has moved — carried, not blocked

An out-of-date record already says so on itself:

> ⚠ Out of date — `cve_scan` re-ran on 09-12. No correcting record has been
> written yet.

The acts stay live, and **what they create carries the staleness into itself**:

> … as recorded in "High advisories with a fix", whose evidence has since moved —
> `cve_scan` re-ran 09-12.

Flag, do not invalidate — the same rule the enrichment judgements follow, one
layer out. Someone may have perfectly good reasons to act on last week's list;
what they may not do is act on it without the work item knowing. A disabled
button here would just send them to copy the rows by hand, which loses the
provenance entirely — the worst of the available outcomes.

## 4 · The record learns it was used

> Used · added to work list "Dependencies to fix before 6.2" · 09-14 08:12 ·
> `dwolfson`
> Used · cited in the journal · 09-14 08:20 · `dwolfson`

A record's **uses are a separate append-only list attached to it, not an edit of
it.** The content stays frozen — that is what makes it a record — while what it
caused accumulates beside it. Same relationship the journal has to a resource.

This is also the answer to the fair question of why a record should exist rather
than a download: **it is traceable in both directions.** From a work item you can
reach what was true when it was raised; from the record you can see what it
caused. A CSV in someone's downloads folder does neither.

## 5 · Four things the acts must not do

- **Re-derive the list.** See above.
- **Mutate the record.** Uses attach; content is frozen.
- **Name a slug where a list has a name.**
- **Appear to an anonymous viewer without saying why.**
  *Sign in to act on a report — a work item needs someone who raised it.*
  Gated, not hidden, author server-stamped, as everywhere else.

And the failure state, as `#81` already does it for the depth offer: a failed act
says *not recorded* and leaves the buttons live. It never claims a record it did
not make.

---

## Still a gap: *write a correction*

An out-of-date record says it is out of date and offers no way to say what is
right. That is a dead end, and it is the one thing in the record design that
currently has a sentence and no button. The shape is already settled by
everything above — a correction is a **new record that names what it corrects**,
so the act is *save as report* with the superseded record's id attached, and the
old record gains *Corrected by "…" · 09-14* in the same place its uses appear.

It is a small round. Say the word and it is the next sheet.
