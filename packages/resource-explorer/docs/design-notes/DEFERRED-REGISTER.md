# The deferred register

**Why this exists:** the project owner observed, 2026-09-18, that the intent
model came up at the start of the project and I deferred it — and that there is
a lot I wanted to ignore, with the time coming soon. Both true. Each deferral
was locally defensible and I never aggregated them, so the accumulation was
visible to the owner and invisible to me. Same failure as the parity inventory:
no register, therefore no shape.

**Assembled from** 33 deferral markers across 20 documents in this folder —
*out of scope*, *a round of its own*, *the owner's call*, *deliberately not
built*, *not worth a round on its own*.

---

## 1 · The finding that only came from aggregating

**Nothing resolves a gap.** `upsert_gap` deliberately never resolves or reopens
(`ITEM-8-FEEDBACK-IMPLEMENTED.md`), the gaps *pane* was scoped out, and
resolving from the UI was scoped out separately. Three defensible deferrals in
one round.

Put together: **the gaps collection has no close path.** I specified it as *"the
number behind the owner's instinct that the analytics need work, accumulated by
the interface rather than asserted in a meeting"* — but a collection that only
grows is not a measure of anything. It is a guilt pile. Its whole value was
being a number that could go down.

That is a defect in my own doctrine, and no single document contains it. It is
visible only here.

---

## 2 · Three kinds, and only one is a problem

### A · Owner decisions, correctly routed

Not mine, and parking them was right. They are listed so they stop being
invisible.

| question | from |
|---|---|
| Is a conversation a Record worth keeping? | `ASSESSMENT-CHAT.md` §4 |
| The exact Egeria type for individual component acceptance | `REPLY-CATALOGUE-IN-LAYERS.md` |
| Do the blueprint clusters have architectural value, or are they filesystem shape? | raised from the live page, 09-17 |
| Do Understanding and Automate want a shared label? | `RULING-NAV-GROUPING.md` §5 |
| Does classic ever gain capability? | **answered** — `RULING-CLASSIC-AND-NEXT.md`: no obligation, honesty only |

### B · Genuinely sequenced — something had to exist first

Defensible, and several are now unblocked because the thing they waited for
shipped.

| deferred | waited on | now |
|---|---|---|
| The gaps pane | gaps landing at all | **unblocked** — `#124`/item 8 |
| Chat's own stage | usage data from item 8's feedback | still waiting, correctly |
| Richer symbol/compare table UI | someone seeing one on screen | **unblocked** — the stream wired it in |
| Membership confirmation tracking | finding the enqueue half exists | **unblocked** — item 3 found it |

### C · Structural questions I deferred because they were hard

**This is the pile.** Local questions produce visible output; structural ones
reorganise the product and produce arguments. I chose the first kind repeatedly.

| question | deferred how many times | state |
|---|---|---|
| **The intent model** — which things are stages at all | since project start | **ruled 09-18**, and only because a peer critique forced it |
| **Nested proposals** — two extractors at different granularities; §4.4's overlap object | twice (`RULING-WHAT-A-VERDICT-IS-ABOUT.md`, `INBOX.md`) | open |
| **Closing a gap** — §1 above | three deferrals in one round | open, and it invalidates the collection's purpose until answered |
| **Confidence as a continuous quantity** — 40% proposals offered at the same weight as 75% | once, deflected as "fix the ranking, not the palette" without specifying the ranking | open, and I owe the ranking |
| **Blueprint clusters as architecture** rather than directory shape | raised, not pursued | open (and an owner call — see A) |
| **`repo_survey_definition_adapter.py:2951`** — primary pick by most-recent rather than best-evidenced | ruled, never built | LOW backlog |

---

## 3 · What I am doing about it

- **This file is the register**, and it is maintained. A deferral that is not
  added here did not happen. The `*-IMPLEMENTED.md` docs are the implementers'
  equivalent and already do this well — several entries above are lifted
  straight from their own "deliberately not built" sections, which is the
  discipline working.
- **Two things I owe, not the owner:** the gap close-path (§1) and the
  confidence ranking. Both are mine, both were deflected, and neither needs a
  decision from anyone to start.
- **Category C is the agenda after the ten items**, not a backlog. It is what
  decides whether the result is useful, which was the stated bar, and the
  reason it never read that way is that it was never in one place.

## 4 · The honest part

Some of category B is real sequencing. Some of category C is not: a structural
question is slower, it produces disagreement rather than a shipped pane, and I
have a bias toward the output that looks like progress. The intent model sat
from project start until someone else raised it. That is the one to learn from,
and the register is the cheapest available guard — it does not make me braver,
but it does make the pile impossible to lose track of.
