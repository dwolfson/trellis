# `/next` — design rules

Rules the experimental UI is built to, each earned by something that went
wrong or by a design round that settled an argument. Short on purpose: a rule
nobody can recall is not a rule.

Sources: the design handoffs in the `claude_design` project
(`Resource Explorer Restyle`, `Next UI Regressions`, `FIX-ROUND`,
`Resource Explorer Matrix Response`), and use of the matrix on real work
lists. Round-by-round narrative lives in
[`next-ui-matrix-round.md`](next-ui-matrix-round.md).

---

## 1. The grid carries state, the popup carries meaning

**The round's central finding**, and what licenses nearly every simplification
in the matrix. A cell can be a single mark because the meaning has somewhere
else to live: click it and you get that question's latest results for that
resource — each contributing analysis, its state, its answer, its own
measurement date, and a re-run.

The corollary is the useful half: **stop trying to make the cell say more than
a glyph can.** Every proposal to encode one more fact into a 26px cell should
first be asked whether it belongs in the thing the cell opens.

It is also what makes the cost work. Reading full facts for one cell is
instant; reading them for 27 × 12 is a minute. You pay for the cell someone is
actually looking at.

## 2. A fast path must not lie

Where a cheap read knows less than the expensive one, the interface **gains a
state** rather than borrowing the nearest confident one.

The matrix's state projection can tell "there is stored output" from "there is
none"; it cannot tell `measured` from `partial`. So those cells render `□ has
results · not read yet` — never `✓`, which would claim a state nobody
established.

Applies at every level, not just cells: the refresh plan reports pairs whose
state is unknown separately, rather than folding them into a confident "never
run".

## 3. There is no per-resource "as of" date

Each analysis ran when it ran — on one row, one measurement from eight hours
ago and another from twenty days. Any single date per resource is wrong
whichever end it takes: the oldest libels the fresh cells, the newest flatters
the stale ones.

**Dates belong to cells.** A row-level age signal is a **count** of stale
cells — a fact about the row — not a date and not a span. A span is two dates
to interpret in a narrow column, where the first reads as "the" date.

## 4. An action must name what it would do, before it does it

Both bulk actions show a plan and queue nothing until confirmed: what is
stale, what is already current and will be skipped, what has never run (left
out by default — a first run is not a refresh), and what is unknown.

`Run across N` and `Bring up to date` share one component deliberately. Both
answer "what am I about to spend", and if they answer it in two shapes people
learn to read one and skim the other.

## 5. Three channels, and they must not collide

- **glyph** — which state
- **hue** — whether a person is needed
- **rule under the glyph** — how old

Age grades rather than flags: nothing under 7 days, a hairline past 7, the
full cell width past 30. Never recolour for age — "this answer is old" and
"this answer is bad" are different claims, and the warn colour is already
spent on the second.

## 6. Scale is a selection problem, not a rendering one

The matrix earns its cost by holding a cohort you can keep in your head, and
nobody holds fifty. So the grid does not grow. Above it, the **column digest**
inverts the view: one line per question showing how its states distribute,
sorted by unresolved, and clicking a line narrows the grid to that question.

Rows are in **triage order** — least resolved first, banded by disposition —
because name order is a filing convention and means nothing here.

## 7. Narrow is a different view, not a smaller one

Below ~720px the matrix **transposes**: one resource, questions down the page,
with a filter row (All / Unresolved / Stale) replacing the scan. Below 780px
both side panes become drawers over a full-width content pane.

A drawer needs its own ground, a narrow shell must not restore a wide shell's
open-rail preference, and the way into a drawer must live somewhere that does
not scroll off a 375px screen. All three were found by looking at it.

## 8. Absence and failure are states, never blanks

- "Could not read" is not "no results" — and it **names its cause** (timed
  out, not in the catalog, unparsable, not permitted, unreachable), with an
  explicit fallback that admits when the cause is not recognised. A confident
  wrong label would defeat the point.
- "Never run" is a claim, and needs evidence; absent evidence the answer is
  "unknown".
- A question with no surveyor is settled, not loading.

## 9. Provenance is not decoration

Two real data defects surfaced only because the matrix tried to show
measurement dates — a word written into a timestamp column that had made an
analysis unreadable on five resources, and two clocks disagreeing about when
something was measured. Both had been in the data for weeks and were invisible
from every other surface.

This extends to **human** judgements: the sequence of dispositions is
provenance too, and is reachable from the matrix rather than only from a
picker on another pane.

## 10. Name things for what they are

The repo-discovery panel is "Find repos", not "Search". Inheriting a wrong
label teaches the wrong noun on first contact, and the current UI's "Search"
is not a search of the selected resource.

---

## Deliberately not built

- **Stage-spanning matrices.** Columns do not survive the crossing, so it
  would be stacked per-stage matrices sharing one frozen resource column — and
  wanting two stages at once is usually a sign a stage boundary is wrong,
  which is worth diagnosing before it is worth rendering.
- **Header group bands.** They need a question topic axis this project
  deliberately deferred; see the deferral's own triggers before adding one.
