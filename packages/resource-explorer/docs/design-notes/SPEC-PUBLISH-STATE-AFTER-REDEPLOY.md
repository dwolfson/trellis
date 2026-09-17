# Publish state after a redeploy

**Answers:** the open question in `REPLY-RETRACTION-WITHDRAWN.md` §4
**Read against:** `main` at `342e0ca3` (after `#105`) — **verified in the code, by me**
**Date:** 2026-09-17

---

## 1 · The question is answered, and it is the bad branch

I asked whether `/next`'s publish state is read live from Egeria or stored
locally. **It is stored locally, and nothing ever checks it against Egeria.**

Three tables in the project registry carry it:

| table | `registry.py` | what it stores |
|---|---|---|
| `project_egeria_surveys` | ~1015 | `egeria_report_guid`, `published_at`, `annotation_count` |
| `project_published_annotation_types` | ~1052 | `annotation_type`, `published_at`, `egeria_report_guid` |
| `project_published_analyses` | ~1109 | `analysis_id`, `published_at`, `egeria_report_guid` |

`get_last_published_analyses`, `get_last_published_annotation_types`,
`has_published_annotation_types_for_report` and
`get_published_annotation_types_for_report` read them. **There is no function
anywhere that resolves a stored `egeria_report_guid` to check it still exists.**

So after the owner's 2026-09-14 wipe-and-redeploy, every one of those rows names
a GUID that no longer resolves, and the UI reports all of it as published. That
is squarely **a fast path must not lie** — and it is worse than the usual case of
that rule, because the lie is *durable*: nothing in the system will ever
correct it on its own.

## 2 · Which makes this the general case, not the 09-14 case

The instinct is to treat this as cleanup after one wipe. It is not. **This is a
dev environment, so the store will be wiped again** — that is what dev
environments are for, and the 09-14 decision established wipe-and-redeploy as
this project's accepted answer to a bad publish. Every future wipe re-creates
the same false state.

So the fix is not a migration. It is the app knowing **which store it published
into**, so that a different store makes the old rows read as what they are.

## 3 · The fix: publish rows carry the identity of the store they went to

Two ways, and the first is much better if it is available:

**(a) Record the store's own identity.** Read a stable per-deployment
identifier from Egeria once at connect time, cache it, and stamp it on each
publish row. A redeployed store returns a different one, and staleness is
detected with **no operator discipline at all**. This is the version worth
having, because a fix that depends on someone remembering to run something
after a wipe will be wrong the first time someone forgets.

**One question for the project owner, and the only thing here that cannot be
settled from the code: does Egeria expose a stable identifier that changes when a
store is wiped and redeployed** (a platform origin, a metadata collection id, a
cohort or server instance id)? Nothing in `resource_explorer` reads one today —
`config.py` has only `platform_url` and `view_server`, which survive a redeploy
unchanged and so cannot serve. The answer decides between (a) and (b) above.

**(b) If there is no such identifier: an operator-recorded epoch.** One row —
`egeria_store_epoch`, a timestamp — written by whatever redeploys the store.
Publish rows older than it are stale. Cheap and honest, but it can be forgotten,
so it is the fallback rather than the design.

**Not (c): verifying on read.** Resolving each GUID when the page renders puts an
Egeria round trip behind a fast path, and the cost rules say a price like that is
either named or not paid. One cached fact at connect time costs nothing per
render.

## 4 · What it says on screen

Publish state gains a third reading beside the two it has. Not *published* and
not *never published* — **published into a store that no longer holds it**:

> **published** · <span>09-12</span> · <span>14</span> annotations
> ⚠ the store was redeployed on 09-14 — these elements no longer exist ·
> *publish again ›*

Rules, all of them ones this project already applies elsewhere:

- **Flag, do not delete.** The row is evidence that a publish happened and what
  it contained; it stays, the way a withdrawn proposal leaves its verdict
  standing with a flag. Deleting the history to make the screen tidy would
  destroy the only record that the elements ever existed.
- **Name the date, not just the condition.** *The store was redeployed on 09-14*
  is checkable; *may be out of date* is not.
- **The action is `publish again`, and it is honest about being a re-publish**,
  not a repair — it writes new elements with new GUIDs, and the cost ladder
  applies to it exactly as to a first publish.
- **Absence is a state:** a resource with no publish rows at all still reads
  *never published*, which is different from *published, into a store since
  redeployed*, and both are different from *publish failed*.

## 5 · One more thing this exposes, which I am not specifying

`rfa_egeria_sync.py` and `members.py` also hold Egeria GUIDs. I have not traced
whether they have the same problem, and I am not going to guess at it — but if
the answer is that Egeria GUIDs are stored in more places than these three
tables, then **the store-identity fact belongs somewhere central** rather than on
the publish tables, and that changes where (a) lands. Worth one look before
building.
