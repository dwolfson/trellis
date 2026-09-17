# Inventory: what classic does that `/next` does not

**First pass** · `SPEC-PARITY-INVENTORY-AND-GROUPS.md` §2
**Read against:** `main` at `1b370cbe` · classic `index.html` 18,306 lines;
`next/` 6,861 lines of `app.js` plus `worklist.js`, `feedback.js`, `format.js`
**Date:** 2026-09-17

---

## 0 · What this is, and what it is not

**This is a screen, not an exhaustive read.** I enumerated classic's views by
`id`, its persisted preferences by `localStorage` key, and then compared
occurrence counts per subsystem across *all* of `next/`, spot-verifying each
non-zero result by reading it. That finds whole missing subsystems reliably. It
will miss a behaviour that lives inside a shared function and has no distinct
vocabulary — the group-collapse case would have been missed this way, because it
is three behaviours inside a sidebar renderer that `/next` also has.

**One correction mid-pass, worth recording as method.** My first screen counted
only `next/app.js` and reported feedback as absent. `next/feedback.js` exists.
Counts across an incomplete file set are not evidence; I re-ran against the whole
directory before writing anything below.

**And I cannot finish the classification.** Separating **deferred** (a decision
exists) from **undiscussed** (nobody ruled) requires knowing which decisions were
made, and the design notes only record decisions that came through me. Entries
below are marked **deferred** only where I can cite the decision. Everything else
is **unclassified** — not "undiscussed", because I do not know.

---

## 1 · Absent from `/next` entirely

Each verified by reading, not only by count. Counts are `index.html` →
all of `next/`.

| # | classic behaviour | evidence | screen |
|---|---|---|---|
| 1 | **The whole Admin section** — ten views: discovery sources, Egeria links, feedback review, groups, logs, Prefect, question catalog, repair, resync, outbox | `id="admin-*-view"` ×10 | 338 → 2 |
| 2 | **Repair** | `admin-repair-view` | 120 → 0 |
| 3 | **Egeria outbox** | `admin-outbox-view` | 44 → 1 |
| 4 | **Resync** | `admin-resync-view` | 39 → 0 |
| 5 | **Prefect integration** | `admin-prefect-view` | 38 → 0 |
| 6 | **Discovery sources** | `admin-discovery-sources-view` | 30 → 0 |
| 7 | **Question catalog editing** | `admin-question-catalog-view` | 23 → 0 |
| 8 | **Group administration** — creating groups and assigning resources to them | `admin-groups-view` | — |
| 9 | **Scout source mode**, persisted | `re.scoutSourceMode` | 11 → 0 |
| 10 | **Resizable sidebar**, persisted width | `pe_sidebar_w` | 9 → 0 |

Items 2–8 are all inside item 1, listed separately because they are separate
capabilities, not one screen.

**Admin is the largest single gap and the one least visible from the design
notes**, which contain no mention of it. Whether `/next` needs it at all is a
real question — an admin surface may legitimately stay in classic forever — but
that is a decision nobody has recorded, which is exactly what this inventory is
for.

## 2 · Partly present — the halves that are missing

| # | classic behaviour | what `/next` has | what is missing |
|---|---|---|---|
| 11 | **Collapsible resource groups** | groups render with a count (`next/app.js:1579-1586`, header `:1678`) | the fold itself; persisted collapse state (`_COLLAPSED_GROUPS_KEY`, `index.html:5169`); group-level selection covering a collapsed group's members (`:5473`); **filter force-expands so a match cannot hide in a fold** (`:5748`) |
| 12 | **Feedback** | submission — a floating button and modal with categories (`next/feedback.js`) | the **per-answer** form (`Feedback('${env.query_hash}', -1, …)`) and the **review side** (`admin-feedback-view`; `next/feedback.js` has zero references to admin, review or store) |
| 13 | **Perspectives** | the role row (`renderPerspectiveRow`) | persistence of the active set (`pe_perspectives`), 29 → 10 |
| 14 | **Chat** | `renderChatLog` | 91 → 34; the panel's persisted open state (`pe_chat_panel_open`) among it |
| 15 | **Bulk operations** | some (54 → 17) | unaudited — needs a read, not a count |

## 3 · Deferred, with the decision on record

| # | behaviour | decision |
|---|---|---|
| 16 | **Databases and filesystems** — classic has `db-survey-view` and `filesystem-survey-view` | `/next` answers *"Repos only, in /next"* on three panes, and Disposition says *"no verdict can be recorded for a {db\|filesystem} yet — dispositions exist for repositories only."* Ruled, and the copy states it. |

One entry. That is the point of the exercise: sixteen candidate gaps, and exactly
one of them has a decision anyone can cite.

## 4 · Two findings that are about the design, not about parity

**(a) Classic's per-answer feedback is the machinery I have been designing, and
`/next` replaced it with something weaker.** `Feedback(query_hash, -1, …)`
attaches a rating to **one specific answer**. `/next`'s floating modal attaches a
comment to **the session**. Those are not the same capability: a reader who
disagrees with one claim is producing a finding about that claim, and
`SPEC-ACTIONABLE-AND-HONEST.md` §3's four destinations exist precisely to route
it — a disagreement's destination is **ours**, and the gaps collection is where it
belongs. Classic already had the capture end of that loop, keyed by
`query_hash`, and nothing in my design notes mentions it.

So the destinations work and the feedback subsystem should be one thing. Per-
answer feedback is not a parity item to restore; it is an input the gaps
collection should already be reading.

**(b) Group administration and group display are being tracked as one gap and are
two.** Item 8 (creating groups, assigning resources) is an authoring capability;
item 11 (folding them) is a display one. `/next` can fold groups it cannot
create, and that is a coherent place to stop — the fold is worth building without
waiting on the admin surface.

## 5 · What I could not do, and what would finish this

- **Classify deferred versus undiscussed.** Items 1–15 need someone who knows
  whether a decision exists. That is a half-hour with this table, not a round.
- **Audit the behaviours inside shared renderers**, which this method misses by
  construction. Group collapse was found by the project owner noticing it, not by
  any pass — so the true gap count is a floor, not a total.
- **Item 15** needs reading rather than counting.

**The floor is sixteen candidates, one of them decided.** That is the number
behind *"`/next` is not feature complete"* — and it says the retirement question
cannot be reopened for a while, which is the useful thing to know now.
