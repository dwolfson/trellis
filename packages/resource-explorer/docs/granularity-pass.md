# Granularity pass: what actually duplicates, and what to do about it

**Status: design pass complete. Nothing built. Recommends a smaller change than
the one it set out to design.**
**Date:** 2026-08-28
**Follows:** `survey-execution.md` §2, which framed the
question, and `open-stack-checklist.md` §2, which parked it.

---

## 0. The conclusion, first

§2 proposed collapsing `analysis_id`'s **bundling** role into survey types and
turning its **results** role into a declared annotation type. Measuring the
codebase to plan that migration changed the recommendation:

**`analysis_id` is not redundant as a catalog concept. It is redundant as a
schedulable unit.** The duplication is entirely in *"what do I run"*, and not
at all in *"what do I show"*.

So: **do not collapse the analysis catalog.** Re-key the schedulable unit to
survey types, leave the catalog alone, and the thing that actually wanted this
— a survey list in Automate — is unblocked by a change of about six rows.

---

## 1. What the numbers say

### 1.1 The two roles have wildly different weight

| keyed by | tables | rows |
|---|---|---|
| `analysis_id` — the **bundling** role | `resource_schedules`, `notification_subscriptions`, `project_published_analyses` | **6** |
| finding `kind` — the **results** role | `project_analysis_findings`, `project_analysis_metrics` | **74,198** |

The bundling role has six rows in total, and one of those is a *database*
analysis (`index_health`) untouched by any of this. The migration risk the
checklist recorded — "live rows keyed by `analysis_id`" — is essentially nil.

The code, not the data, is the cost: 18 Python files mention `analysis_id`, and
`index.html` references it 99 times.

### 1.2 The results identity is already its own vocabulary

This was the assumption most worth checking, and it did not hold the way §2
implied. Comparing finding `kind` values against analysis ids:

- 15 kinds coincide with an analysis id
- **5 do not** — `supply_chain`, `security_hygiene`, `documentation`,
  `architecture_interfaces`, `repo_sub_resource_survey`
- **12 analyses have no finding kind at all** — their results come from
  elsewhere entirely (`project_dependencies`, `project_stats`, code symbols)

So `kind` is not "the analysis id under another name". It is a producer-level
identity that *coincides* with an analysis id 15 times out of 20. Turning the
results role into an annotation type is therefore not a rename of `analysis_id`
— it is naming something that already exists separately.

**And 12 analyses have no `kind`, so `kind` cannot be the universal results
key.** The real abstraction is the results *reader* on `AnalysisKindResults`,
which already handles all 27 uniformly regardless of where the data lives.

### 1.3 Bundling really is redundant

- 25 of 27 repo analyses are a **single step**
- the 2 genuine bundles — `language_file_classification` (3 steps),
  `architecture_recovery` (2) — are exactly the shape a survey type is
- 4 steps have no analysis at all (`repo_file_inventory`,
  `repo_git_statistics`, `repo_homepage`, `repo_file_size`), so a survey type
  can already express things an analysis cannot

That part of §2's argument stands unchanged.

---

## 2. Why the catalog should stay

An `analysis_id` carries things a Survey Definition has no field for:

| carried by `analysis_id` | in Egeria? |
|---|---|
| `intent` (which of the 8 tabs it belongs to) | no |
| `perspectives` | only indirectly, via the Question → Perspective graph |
| `description` written for a person choosing what to run | step descriptions, not analysis-level |
| `run_time` / `target_shape` | no |
| **results reader, trend reader, headline reader, render mode** | no, and never will — these are UI concerns |

Collapsing the catalog means moving all of that into Egeria or into the CSV.
The results half cannot move at all: a render mode has no business in a
governance catalog.

§2 said the bundling half should collapse and the results half become an
annotation type. The first is right. The second overstated it — the results
half is not a second name for the bundle, it is a separate concept that already
has its own key, and it stays local.

---

## 3. What to change

**One thing: the schedulable unit.**

`resource_schedules` is keyed `(entity_type, entity_slug, analysis_id)`. To
schedule a *survey* — which is what the Automate section needs — it needs to
accept a survey-type reference too.

Recommended shape: keep the table, widen the key's meaning to a `target_kind`
+ `target_ref` pair (`analysis` + id, or `survey` + qualified name), rather
than adding a parallel table. Six existing rows migrate as
`target_kind='analysis'`.

The same applies to `notification_subscriptions` (2 rows), so a subscription
can watch a survey rather than only an analysis.

### 3.1 The offline objection dissolves

The obvious worry: survey types live in Egeria, so keying schedules to them
makes scheduling depend on Egeria being reachable — breaking the local-first
guarantee that `docs/survey-execution.md` §4.6 insists on.

It does not, because of something that landed on 2026-08-27 for a different
reason. `surveyors/survey_definition_docs.py` parses the authored Dr.Egeria
documents **locally** — `documented_definitions()` returns all 8 definitions
and their steps with no Egeria call. It was written so the drift scan and the
link reconciler could share one parser; it also happens to be a complete local
index of what survey types exist and what they run.

So a scheduler can resolve a survey reference to its steps offline, and Egeria
is needed only to *execute* a step that declares `executes_at: egeria`.

---

## 4. What this unblocks

The Automate survey section (`open-stack-checklist.md` §4a). With a survey-typed
schedule target, that section is a UI addition rather than a schema question:

- a third sub-tab beside 🔔 Subscriptions and ⏱ Schedules
- listing survey candidates, selectable, with a schedule action
- and `RepoFullSurvey` can finally move out of the four stage tabs into the one
  place a "run everything" recurring bundle belongs

Both halves in one change — the filter alone loses the feature, as trying it on
2026-08-27 showed.

---

## 5. What NOT to do, and why

- **Do not give every step a single-step survey type.** 37 definitions, each
  needing a CSV row, a generated document and an Egeria re-author, to replace a
  catalog entry that already works. The generator makes it *possible*; that is
  not a reason.
- **Do not move render modes into Egeria.** They are UI concerns and a
  governance catalog is the wrong home.
- **Do not rename finding `kind` to match analysis ids.** They diverge in 5
  cases deliberately, 12 analyses have no kind, and 74k rows carry the current
  values.
- **Do not do this to reduce concept count.** Three concepts is the right
  number — a survey type is what you run, a step is what it runs, an analysis
  is what you look at afterwards. The bug was only that scheduling had to
  borrow the third to express the first.

---

## 6. Open question left for a person

Whether an analysis should remain independently *runnable* once surveys are
schedulable, or become view-only with running always going through a survey
type. Running one analysis is genuinely useful and the per-card "Run →" is
well-liked; but two ways to run the same step is how the original duplication
started. Not decided here.
