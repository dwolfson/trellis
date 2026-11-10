# Brief: closed-loop step 2, routing a diagnosis to its consumer

Status: **proposal, awaiting the architect's read-back and the project owner's decisions (§6).**
Design: `docs/feedback-closed-loop-design.md` §3.2 (the routing table) and §6 step 2 ("the gaps and RFA
consumers, then Automate's"). Step 1 (#1019) records a cause on a rated answer and routes nothing.

## 1. Scope

Step 2 routes five of the nine causes. The other four already have a home elsewhere in the phasing, or
need none:

| Cause | Consumer (design §3.2) | In step 2? |
|---|---|---|
| `catalog_gap` | a gap with no analysis, plus an RFA to the catalog owner | yes |
| `missing_evidence` | a gap `ours` on the analysis that had no result | yes |
| `analysis_defect` | a gap `ours` on the analysis, marked as a defect | yes |
| `unclear_question` | an RFA to the catalog owner, with the question as asked | yes |
| `stale` | Automate: propose a schedule for the analysis behind the stale section | yes, last (§4) |
| `wrong_evidence` | chunk scores | no: step 4 (§3.4) |
| `over_compressed` | the compile spec's editing loop | no: needs that loop first (Q6) |
| `reasoning` | a review list | no: the by-cause view already is that list (Q6) |
| `not_an_issue` | nothing | nothing to route |

Answer items only. Page-widget reports carry no cause (design §3.1), so they route nowhere.

## 2. When routing happens

**On Save of a diagnosis**, in the same request as `PATCH /api/feedback/{id}` that records the cause, after
the triage event is written. The design's one-consumer rule (§13's guard) and the append-only triage log
together give the rules:

- **One route per (item, cause).** Saving the same cause again does nothing new: the route table's key
  (§5) is `(item_id, cause)`.
- **A re-diagnosis routes the new cause and leaves the old route alone.** A gap or RFA already raised is
  real work someone may have started. The old route is not withdrawn; the row says the item was
  re-diagnosed (§5). Withdrawing is Q3.
- **A failed route never fails the diagnosis.** The triage event is the record; the route is its
  consequence. A route that cannot be made (no resource, no analysis to charge, a registry error) is
  said on the row with its reason, and the Save still succeeds.
- **No route on a status change alone.** Only a Save that sets or changes `cause` routes.
- **The secondary cause never routes** (design §2.2: measurement only).

## 3. What each consumer writes

The consumers reuse what exists: `registry.upsert_gap` (idempotent on
`(project_slug, analysis_id, gap_kind, check_name)`) and `activity_logger.log_rfa`. The one new table is
the route record (§5).

### Gaps (`missing_evidence`, `analysis_defect`, and `catalog_gap`'s gap half)

- **New `gap_kind`s:** `missing_evidence` and `analysis_defect`, beside today's `not_measurable` and
  `disagreement`. A defect and a missing run have different owners' actions, so they must not share a kind
  (design §3.2: "marked as a defect, not a missing run").
- **Key:** `check_name = question_check_name(question, question_id)`, the same key the checklist's
  disagreement gap uses (`gaps.py`). So several 👎s on one question about one analysis are one gap, and its
  `last_seen_at` moves, which is the count a curator acts on.
- **`evidence`:** `source: person` (SOURCE_PERSON), `cause`, the feedback item id(s), the compile id, the
  analysis's role from the charge set (`absent`, `dropped`, …), and the diagnosing admin. Not the asker's
  id: the gap is visible beyond Admin.
- **Which analysis.** The charge set (`feedback_diagnosis.charge_set`) can name several. The admin picks
  one in the cause menu, defaulting to the first in role order (Q2). One diagnosis makes one gap.
- **`catalog_gap`:** a gap with `analysis_id = ""` (the shape `record_disagreement` already uses for
  "attributed to none"), `gap_kind = "catalog_gap"`.

**A gap needs a resource.** `upsert_gap` refuses an unregistered slug. An answer given with no resource
in scope (a slug-less chat turn) cannot make a gap. For `catalog_gap` the RFA still goes (below); for
`missing_evidence` and `analysis_defect` there is no analysis without a resource, and the row says
"no resource in scope; nothing to route".

**Interaction with the checklist.** A checklist "disagree" already writes a `disagreement` gap through
`record_disagreement`. A diagnosis of that same item writes a second gap of the diagnosed kind, under the
same question key. They are different claims ("a person said it's wrong" vs "an admin found why"), so
both stay. The diagnosed gap's evidence names the disagreement gap's id.

### RFAs (`catalog_gap`, `unclear_question`)

- **Through `log_rfa`**, so they reach the RFA drawer. Summary: the cause and the question as asked.
  Detail: the rule, the compile id, and for `unclear_question` the admin's note.
- **`items`:** `{"kind": "feedback", "id": <item id>}` and, for `catalog_gap`, the gap id, so the RFA
  points at both.
- **Raised against the resource** when there is one, as the gap→RFA route already does
  (`projects.py`, "no 'analysis' RFA entity type exists yet"). With no resource: Q4.
- **One RFA per question**, keyed in the RFA's items. A second 👎 on the same question finds the open RFA
  and adds the item to it instead of raising another.
- **"The catalog owner"** has no representation in RE today: no person or role is named as owning the
  question catalog. The RFA lands in the drawer unassigned (Q5).

## 4. Automate (`stale`), last

There is no "proposed schedule" anywhere in RE: `resource_schedules` has a schedule and `enabled`,
nothing more. Two ways to propose:

- **(a) An RFA that offers the schedule.** "Section X was as of <date> when this answer was given;
  schedule <analysis> on <resource>?" It carries the analysis and resource in `items`, and the drawer
  action opens the existing per-card "⏱ Schedule" control. No schema change.
- **(b) A disabled schedule row** marked proposed. This needs a new column and a new state on the
  Schedules overview.

**Recommended: (a).** It reuses the drawer, which is where Automate already delivers its notifications,
and a proposal stays a request to a person, not a half-made schedule. If the analysis is already
scheduled, the RFA says so and suggests a shorter cadence instead (the section was stale anyway).

## 5. What the admin sees

On the answer's row, after Save: **"Routed: gap #12 on `repo_profile` (missing evidence)"**, or **"RFA
raised: …"**, or **"Not routed: no resource in scope"**. A re-diagnosed item lists each route with its
cause.

**The route record is an RE table, `feedback_routes`:** `(item_id, cause)` primary key, `consumer`
(`gap` / `rfa` / `automate` / `none`), `target` (the gap id or RFA activity id), `reason` (why nothing was
routed, when nothing was), `routed_at`, `routed_by`. It is RE's, not trellis-feedback's: trellis-feedback's
`TriageEvent` has no free field, and the consumers (gaps, RFAs, schedules) are RE's. The key is what
makes Save idempotent. Admin → Feedback reads it beside each item's triage history. EA adopting the loop
later would keep its own.

## 6. Questions for the project owner

1. **Route on Save, automatically** (recommended), or only on an explicit "Route" button after Save?
2. **Several analyses charged:** the admin picks one, defaulting to the first in role order
   (recommended), or one gap per absent analysis?
3. **Re-diagnosis:** leave the earlier route standing and say so on the row (recommended), or withdraw
   it (resolve the gap, close the RFA)?
4. **A slug-less `catalog_gap` / `unclear_question`:** RFAs need an entity. Raise them against a fixed
   "question catalog" entity (recommended: `entity_type = "catalog"`, slug `questions`, a small
   addition to the drawer), or record them only on the feedback item?
5. **The catalog owner:** leave the RFA unassigned in the drawer (recommended for now), or name an owner
   (a person or a role in config) that it is assigned to?
6. **Out of step 2:** confirm `over_compressed` waits for the spec-editing loop, and that `reasoning`'s
   "review list" is the by-cause view step 1 already shipped, not a new surface.
7. **Automate:** propose with an RFA (a, recommended) or a disabled schedule row (b)?

## 7. Phasing inside step 2

Each its own PR, with tests and a read-back:

- **2a.** Routing core: the route-on-Save hook, idempotency, the gap consumers, the result on the row.
- **2b.** The RFA consumers, including the slug-less entity if Q4 says so.
- **2c.** Automate's proposal.

## 8. Tests

- Each cause routes to its consumer and to no other; `wrong_evidence`, `over_compressed`, `reasoning`,
  `not_an_issue` and every secondary cause route nothing.
- Saving the same cause twice makes one gap and one RFA.
- A re-diagnosis routes the new cause and leaves the old gap and RFA as they were.
- A route that fails (unregistered slug, registry error) leaves the diagnosis saved and says why.
- Two items on one question and analysis make one gap, whose evidence lists both items.
- The gap's evidence carries no asker id.
