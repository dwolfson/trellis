# Confidence-gated validation — Analysis-first, Enrichment-fallback

**Status: framed, not built.** Written per direct request (2026-08-14):
"we will need it pretty quickly so we should at least frame it in... Especially
in terms of recording and making use of confidence." This is the *frame* —
concrete enough to build from, deliberately not fully speced (D4/D5 below
stay open) since the request was to get the shape down, not finish it.

## Context

Working through `docs/dr-egeria/resource_questions.csv`'s Funnel Stage
column, two questions ("Does it fit into our monitoring infrastructure?",
"...security infrastructure?") got tagged `Analysis/Enrichment` — a
combined stage. Asked what that meant: **"see if we can run an analysis
step that produces a high confidence answer and if not then we need to
validate/update from user input."** I.e. not "answered by two stages
equally" — a real *pattern*: try the automated Analysis path first, and
only fall through to a human (Enrichment) when the automated answer isn't
trustworthy enough. Then, weighing whether this is "an extension to
Analysis" or "more work in Enrichment": **both, but they're different-sized
— extending Analysis (confidence-gate + reuse the existing RFA delivery)
is the cheap, mostly-already-there part; a dedicated Enrichment
validate/correct UI is a real, separate, bigger piece, deferred here.**

## What's already real (confirmed by reading the code, not assumed)

- **`confidence` is already a genuine, widely-used per-Annotation field**
  (`survey_report.py`, `0-100`, default `100`) — not just a default nobody
  sets. Real, *dynamic* examples exist today:
  - `license_classifier.py`: `confidence = 100 if tier in (known tiers) else 60`
    — genuinely computed from classification certainty.
  - `maturity.py` computes its own `confidence` variable similarly.
  - Most other surveyors set a fixed-but-differentiated constant per
    finding type (95 for a direct field read, 70-80 for a heuristic,
    60 for LanguageSurveyor's weakest signal) — a real, if coarse,
    uncertainty signal, not a placeholder.
- **`confidence` is already persisted** — `project_analysis_findings`/
  `project_documentation_findings` (the generic findings tables from the
  Analysis-kind extensibility redesign) have a real `confidence INTEGER
  DEFAULT 100` column, threaded through `upsert_finding()`.
- **`RequestForActionAnnotation` + the RFA drawer already exist** as a
  real delivery mechanism — `SecurityHygieneSurveyor`/`DataProfilerSurveyor`/
  `FileSizeSurveyor` already emit RFAs for gaps they find, and
  `base_surveyor.py`'s `_warn()` already emits one (`confidence=0`) on a
  hard survey error.

## What's actually missing

**Nothing consumes confidence.** No code anywhere reads a *successful*
finding's confidence score and decides "this is too low, escalate for
human validation." The only current RFA-on-confidence case is the
degenerate one (`confidence=0` on a hard error) — a normal finding that
completed with `confidence=60` today is silently treated exactly the same
as one that completed with `confidence=100`. That gap is the actual thing
to frame.

## Decisions (framed, not fully specified)

**D1 — A confidence threshold is a policy value, not a magic number
scattered per-surveyor.** Add a `confidence_threshold` (default e.g. 70,
tunable) to `analysis_catalog.yaml` per analysis kind, with a global
fallback default — so "how sure is sure enough" is an editable config
value, not buried in code. Exact default number is a first-guess, not
citing any standard — worth revisiting once real data exists on how
findings' confidence actually distributes.

**D2 — Gate at the point findings are persisted, not inside each
surveyor.** `registry.upsert_finding()` (or a thin wrapper called right
after it, in `SurveyOrchestrator.run()`) is the single choke point every
finding already passes through — checking `finding.confidence <
threshold` there means every current and future surveyor gets the gate
for free, no per-surveyor code changes needed. When a finding's confidence
is below threshold, emit a `RequestForActionAnnotation` (reusing the
exact existing mechanism, not a new one) with `action_requested=
"Validate or correct this finding"`, referencing the low-confidence
finding's `check_name`/`label`/`summary` so the RFA is concrete, not generic.

**D3 — Recording needs one new thing: don't re-raise the same RFA every
run.** Findings already append-not-overwrite (one row per `surveyed_at`),
so re-running a schedule would re-trigger D2's gate every time unless
something tracks "this specific low-confidence finding was already
escalated." New table: `finding_validation_state(project_slug, kind,
check_name, last_confidence, last_surveyed_at, escalated_at,
human_validated_at, human_override_value)` — one row per (project, kind,
check_name), updated each time a finding for that key is written. RFA
only re-fires if confidence is *still* below threshold AND
`human_validated_at` is null or older than the current `surveyed_at`
(i.e. a human validated a *previous* run's answer, not this one — matches
how disposition/context data doesn't silently stay valid forever either).
This table is also where a human's override value would live once D5
(below) builds the actual correction UI — recording the override now,
even before there's a UI to produce one via anything other than direct
registry access, keeps the schema stable for that later work.

**D4 — Delivery stays the RFA drawer for now, not a new Enrichment
surface.** Matches "Extension to Analysis" being the cheap path — the
human sees "low-confidence finding, please validate" in the same drawer
that already exists, with a defer/reassign/complete lifecycle already
built. No new UI needed to ship D1-D3.

**D5 — A real Enrichment-side validate/correct UI is a separate, bigger,
explicitly deferred piece.** Today's Context form only does blank-field
prompting (a field with no computed counterpart at all). Seeding a form
field from a specific low-confidence Annotation and letting a human
accept/correct it — rather than just completing the generic RFA action —
is a real, different capability (the Annotation needs to be resolvable
from the Enrichment side, the correction needs to feed back into
`finding_validation_state.human_override_value`, and downstream readers
of that finding need to prefer the override when present). Not scoped
here — flagged as the natural next step once D1-D4 are live and there's
real data on how often this actually fires.

## Verification (once built)

- Unit tests: threshold check fires an RFA exactly once per (project,
  kind, check_name) at first-crossing, not every subsequent run at the
  same or lower confidence; a human `human_validated_at` newer than the
  latest `surveyed_at` suppresses re-firing; a *later* run whose
  confidence recovers above threshold doesn't leave a stale open RFA
  (needs its own resolution path — TBD alongside D5, not solved here).
- Live: run `license_classifier` against a repo with an unrecognized SPDX
  id (the real `confidence=60` case already in the code) with the
  threshold at 70, confirm exactly one RFA appears; re-run the same
  survey, confirm no duplicate RFA.
