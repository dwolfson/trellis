# Slice 17c: generalize the render-bound gate to every level — implemented

**Coordinator brief:** Phase 1b, slice 17 follow-up (`re/coordinator-brief-phase-1b`).
**Replying to:** the same live signed-in gate that reviewed PR #294 (slice 17b),
one screen further on `coco_pharma`.
**PR:** #TBD (`re/slice17c-renderable-answer-gate`).

## What the gate found

Slice 17b bound the sub-resource-level checkmark to whether a known fact
produced a `headline` — the one rung that can carry member-naming prose
past the frontend's `scalarMeasures()` fallback, which skips list/object
fields by design. That fixed "Which schemas carry the data" (a `container`
-level question).

The same live gate, one screen further: **"Is this database a primary or a
replica, and is it replicating to anything?"** — a plain `resource`-level
question, entirely exempt from slice 17b's check — rendered a ✓ with **no
answer text at all**, only the provenance line "db_resilience · run 20h
ago" underneath.

**Diagnosis:** `db_resilience` has no `headline_reader`
(`DATABASE_ANALYSIS_HEADLINE_MAP`), and its value
(`_survey_operations`'s `resilience` key) is four nested dicts —
`replication`, `wal_archiving`, `backup_tool_signals`, `clustering` — with
**no top-level scalar field at all**. `scalarMeasures()` (`app.js`)
explicitly skips every list/object field. So unlike `schema_inventory`
(which at least has scalar fields like `table_count` alongside its list,
and so rendered a thin-but-nonempty rollup), `db_resilience` was
structurally guaranteed to render nothing, on every run, not only the one
the gate happened to catch live.

## The ruling

The design session's call (2026-09-26): generalize rather than patch
`db_resilience` alone — target_shape/headline was never the right axis;
"does the fact render ANY text, at any level" is. A known fact with no
renderable text is not an answer; the checkmark it sits under must be
withheld regardless of whether the question happens to carry a
sub-resource `levels` entry.

## The fix

1. **`FactLayer._renders_text(fact)`** (`facts.py`) — a small, explicit
   mirror of `app.js`'s `readEnvelope` rungs 1–3 (headline, `value.detail`/
   `summary`/`description` prose, or the `scalarMeasures()` fallback: any
   non-null, non-object, ≤60-char field other than `verdict`). Answers one
   narrow question — would rung 3 find anything to say — not a general
   renderer; the two must be kept in step by hand, called out explicitly
   in the docstring since there is no shared source between a Python
   backend and a browser-side formatter.
2. **`FactLayer._check_level`** now runs an unconditional first check —
   does *any* known fact `_renders_text`? — before consulting `levels` at
   all. This fires for `resource`-level questions too, which the old
   version exempted outright. Only if that passes does the existing
   sub-resource / `headline`-specific check from slice 17b run on top,
   preserving its distinct wording (`target_shape`-based: "nothing to
   show" vs. "rows exist, no reader shows them yet").
3. **Three new headline readers** (`survey_definition_adapter.py`,
   registered in `DATABASE_ANALYSIS_HEADLINE_MAP`), mirroring
   `row_count_snapshot`'s pattern — because the honesty floor
   (`_renders_text`) is not the ceiling; "primary; no replicas; WAL
   archiving off; no backup tool detected" is the answer a Data Owner
   actually came for:
   - `_db_resilience_headline` — replication role + replica count, WAL
     archiving mode (+ failure count when archiving), backup-tool
     detection, Citus clustering when present.
   - `_db_activity_signals_headline` — total writes/reads across all
     tables since the last stats reset. Written alongside the other two
     even though this analysis was never silently empty (it does have two
     real scalar fields, `stats_reset`/`table_count`) — "stats reset
     2026-... · table count 56" answers a different question from "is
     anything reading or writing this database."
   - `_db_external_dependencies_headline` — named counts of extensions,
     foreign servers/tables, publications/subscriptions (every one of its
     fields is a list, the identical structural gap `db_resilience` has).

`privilege_audit` (also `_operations_section_reader`-backed, also
all-list fields — `roles`, `table_grants`, presumably a third ACL list)
is **not** given a headline here. Not because it's exempt: `_renders_text`
means it now correctly falls to the honest "ran; no summary reader yet"
state instead of an empty checkmark, which is the safe default the gate
exists to provide. Writing its sentence is separate, deliberately-scoped
follow-up work, not silently dropped.

## Explicitly NOT done here

- **`privilege_audit`'s own headline** — see above; logged, not written.
- **A shared Python/JS implementation of the scalar-fallback rule** —
  `_renders_text` and `scalarMeasures()` are two hand-written
  implementations of the same narrow rule, not one shared source. A
  divergence between them (someone changes one threshold in `app.js`
  without knowing to change `facts.py`, or vice versa) would silently
  reopen exactly this class of bug. Flagged here rather than fixed: unifying
  a Python backend rule with a browser-side JS formatter needs its own
  design pass (a shared JSON schema? A contract test asserting the two stay
  in lockstep?), not a quick patch bolted onto this PR.

## Tests

- `test_slice17c_renderable_answer_gate.py` (new, 26 tests): `_renders_text`
  unit coverage (headline/prose/scalar/all-nested-dict/all-list/empty/
  `verdict`-excluded/overlong-excluded/null-excluded cases, plus the real
  `db_activity_signals` shape rendering via its scalars); the generalized
  gate firing at `resource` level (including a missing-`levels`-key case);
  one renderable fact among several unrenderable ones being enough; the two
  checks composing correctly (renders-something does not by itself satisfy
  a sub-resource question); the three real headline-map entries existing;
  and reader-level tests confirming each new headline's actual sentence
  content (not just non-emptiness).
- `test_slice17_question_level_gate.py` (18 existing, unchanged assertions):
  fixture helper `_measured_envelope` updated to default each fact's
  `value` to a non-empty scalar (`{"measured": True}`), since the
  generalized gate's new first check would otherwise fire on every bare
  fixture — this proxies what a real analysis with even one scalar field
  does, and every test's sub-resource-specific assertion is unaffected.
- Full suite: 6400 passed, 103 skipped, 1 failed — the same pre-existing
  `test_egeria_live_smoke.py` live-Egeria-environment failure noted on
  slices 16, 17, and 17b.

## Live signed-in gate

**Not yet run.** Needs a real signed-in session against `coco_pharma` to
confirm, on screen:

- "Is this database a primary or a replica, and is it replicating to
  anything?" now shows a real sentence (e.g. "Primary; no replicas; WAL
  archiving off; no backup tool detected.") — not an empty ✓, and not the
  no-summary-reader state (a headline now exists for it).
- No ✓ anywhere on the Questions tab has an empty answer line — the
  general claim the ruling asked this slice to close, not just the one
  row that was caught live.
- "Which schemas carry the data" and "How big is this database" still
  behave exactly as slice 17b left them (must not regress).
- Coverage Signals / Subject Signals / Preliminary Fit still show Run
  correctly (must not regress — unrelated to this change, same screen).

Whoever runs this: append the outcome here, one sentence per screen, per
the coordinator brief's own gate convention.
