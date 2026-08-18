# Repo survey catalog completion — microflow reuse, CSV-driven authoring, EA integration

**Status: design pass complete (2026-08-17), not yet built.**

## Context

Follow-on from the RE-as-engine-host work (now on hold, `docs/re-as-engine-host-plan.md`, pending Egeria `PYEGERIA_ISSUES.md` ISSUE-51). Confirmed all-local (case 3) surveying works cleanly end to end today — a live run against a real repo produced 3 annotations, 0 errors. Per direct decision, repo gets finished properly before database/filesystem get the same treatment.

**Repo's actual current state** (pulled from `analysis_catalog.yaml`/`STEP_REGISTRY`, not assumed): 17 real surveyor steps, all working. 3 named Survey Types authored via Dr.Egeria (`Repo Coarse Scout` — 2 steps, `Repo Discovery Survey` — 3 steps, `Repo Full Survey` — 16 of 17 steps, missing `repo_symbol_extraction` which postdates it). 15 `analysis_catalog.yaml` menu entries (2 steps — `repo_sub_resource_survey`, `repo_symbol_extraction` — have no catalog entry, reachable only via `steps=[...]`, not as standalone UI items).

**Operational note, not a bug**: the quickstart Egeria platform doesn't persist custom-authored elements across a redeploy/restart (confirmed live — all 3 Survey Definitions and the `Question` elements they scope-link to were gone after a routine dev-environment Postgres recreate). This is exactly why Dr.Egeria markdown docs are generated as reproducible artifacts in the first place — `scripts/generate_repo_survey_definition.py` regenerates them from `STEP_REGISTRY`, and re-running them restores the elements. Confirmed working today (re-ran `repo-survey-definition-scouting.md`, `Repo Coarse Scout` process + steps + chain restored correctly; only the `Link Element To Scope` calls failed, since the `Question` elements they reference were also wiped and haven't been re-authored yet). **No new work needed here** — the recovery model is correct as designed; just a note that a full re-authoring pass (all 3 survey docs + the Question docs) is worth doing once, after this plan's changes land, rather than twice.

## D1 — Recovery model: confirmed correct as-is, no changes

Covered above. Not revisited further in this doc.

## D2 — Microflow/step reuse

Two distinct meanings, both real:

**(b) Cross-survey step reuse — already fully supported, confirmed by inspection.** Any `step_key` in `STEP_REGISTRY` is independently addressable and can appear in any number of named Survey Types' `Link First/Next Process Step` chains (e.g. `repo_health` is already in both `Repo Coarse Scout` and `Repo Full Survey`). No code change needed — this is a property of the existing design, worth documenting explicitly so it's not re-litigated later.

**(c) Within-surveyor primitive duplication — real findings, worth consolidating.** Grepped all 16 `sub_surveyors/*.py` files for direct `self.registry._conn()` use (bypassing named registry accessor methods): **5 files** do this — `api_structure.py`, `file_structure.py`, `health.py`, `language.py`, `security_hygiene.py`. Concretely:
- `health.py` and `security_hygiene.py` **both** hand-write their own raw `SELECT ... FROM project_stats` query with overlapping-but-different column sets, instead of using the registry's own existing `get_latest_project_stats()` (already used correctly by 3 *other* call sites) — a direct, unambiguous duplication.
- `file_structure.py`, `api_structure.py`, `security_hygiene.py` each hand-write their own file-inventory/code-symbol queries (`project_file_inventory`-shaped stats, `project_code_symbols` distinct-file-path lookups) rather than going through a shared, named, tested registry method.

**This is NOT `trellis_microflow`-package territory** — that package is specifically for the acquire/dedupe/cleanup pattern around *shared external resources* (zipball downloads, DB connections), already working correctly (confirmed: only `data_profiler.py`/`symbol_extraction.py` declare `requires_resources={"zipball_root": ...}`, and `resolve_resources` already dedupes that download once per orchestrator run regardless of how many steps need it). The D2(c) duplication found here is a simpler, different problem — ad hoc SQL vs. named `registry.py` accessor methods — and the fix is correspondingly simpler: promote each duplicated query pattern into a proper, tested `ProjectRegistry` method, and have every surveyor that needs it call that method instead of writing its own SQL.

**Scope for this pass**: consolidate the confirmed duplicate (`health.py`/`security_hygiene.py`'s stats query → both use `get_latest_project_stats()`), then audit the remaining 3 files' raw queries one at a time to decide, per query, whether it's genuinely one-off (leave it) or a second instance of an existing pattern (extract). Not a big-bang rewrite — a few small, independently-verifiable PRs.

## D3 — CSV-driven Survey Type generation

**Primary authoring mechanism, per direct decision.** `scripts/generate_repo_survey_definition.py` already derives per-step detail (description, additional properties, Question scope-links) from `STEP_REGISTRY` + `question_catalog.yaml` — the one piece that's still hardcoded is `SPECS: list[SurveyDefSpec]`, a Python literal naming the 3 survey bundles and their step-key lists in file. That's exactly the piece to move to a CSV, matching the precedent already established by `docs/dr-egeria/resource_questions.csv` (source of truth for `question_catalog.yaml`, regenerated via `scripts/csv_to_question_catalog_yaml.py`).

**Design**: new `docs/dr-egeria/repo_survey_types.csv`, one row per (survey, step) pair — mirrors how a spreadsheet-native author would naturally lay this out (a survey's step list as a contiguous block of rows, in chain order):

```csv
survey_kind,survey_group,survey_display_name,description,step_key,step_order
scouting,RepoCoarseScout,Repo Coarse Scout,"Fast, GitHub-API-only pass...",repo_health,1
scouting,RepoCoarseScout,Repo Coarse Scout,"Fast, GitHub-API-only pass...",repo_language,2
discovery,RepoDiscoverySurvey,Repo Discovery Survey,"...",repo_license_classification,1
...
```

`generate_repo_survey_definition.py` changes from defining `SPECS` as a literal to parsing it from this CSV (group by `survey_kind`+`survey_group`, sort by `step_order`, build the same `SurveyDefSpec` objects it already builds today — the dataclass and everything downstream of `SPECS` stays unchanged). A `step_key` value not present in `STEP_REGISTRY` should fail generation loudly (typo guard), not silently produce a broken Survey Definition.

**Validation guard, learned from this session's own mistakes**: cross-check every `step_key` in the CSV against `STEP_REGISTRY.keys()` and every `step_key` *in* `STEP_REGISTRY` against at least one CSV row, at generation time — flag (don't silently ignore) any `STEP_REGISTRY` step with zero CSV rows (exactly how `repo_symbol_extraction` quietly fell out of `Repo Full Survey` last time — a step shipped in code but never added to the authoring spec).

## D4 — Ad hoc Survey Type authoring via Egeria Advisor

**Per direct decision**: the CSV is the primary path, but sometimes a user wants to add or organize Survey Types differently outside it. For that case: the user authors a new Survey Type **in Egeria Advisor**, from a template file RE provides, not in RE itself. This makes sense given EA already owns the Dr.Egeria-authoring UX (LGCI plan documents, the Plan Editor, template save/load via `PlanTemplateManager`) — RE doesn't need to duplicate that.

**Two real open questions, not resolved here:**
1. **What does "a template file RE provides" concretely look like?** Candidates: (a) a `.md` template matching the existing Dr.Egeria markdown shape (`Create Governance Action Process`/`...Step`/`Link First/Next Process Step`) with placeholder step-key slots the author fills in and orders — closest to EA's existing template mechanism (`{{placeholder}}` substitution); (b) a lighter-weight spec (CSV-row-shaped, or a small YAML) that a **new** EA-side generator turns into the same Dr.Egeria markdown `generate_repo_survey_definition.py` already produces — more consistent with D3's model, but means teaching EA about RE's `STEP_REGISTRY` shape, a cross-app coupling that doesn't exist today.
2. **Where does the author see the registry of available steps to choose from?** Named as open — "could be a number of different tools." Real candidates: RE's existing `GET /api/analyses/repo` catalog endpoint (already serves exactly this list to RE's own UI — EA could just call it, zero new RE-side work); a static generated file (JSON/YAML snapshot of `STEP_REGISTRY`, committed alongside the CSV, browsable without a live RE instance); or a live query once/if steps become directly Egeria-native metadata (not the case today — `additionalProperties.executes_at`/`re_analysis_step` is RE's own convention, not a real Egeria type).

**Not decided, needs another round with the user before building**: which template shape, and which step-registry-visibility mechanism. Flagged here so the destination is on record.

## D5 — New step/analysis creation: developer-only, explicit non-goal for now

**Per direct decision**: creating a genuinely new step (a new `StepInfo` + surveyor class) is closer to a developer task than something to build no-code tooling for. No UI/authoring-template work planned for this — adding a new analysis stays "write a new `sub_surveyors/*.py` file + register it in `STEP_REGISTRY`," same as today. Noted explicitly so it doesn't get silently folded into D3/D4's scope later.

## Sequencing

1. **D2(c) consolidation** — smallest, safest, no design risk, do first. `health.py`/`security_hygiene.py` → `get_latest_project_stats()`; audit the other 3 files' raw queries one at a time.
2. **D3 CSV-driven generation** — real, scoped, buildable now: the CSV schema, the parser, the validation guard, regenerating all 3 existing survey docs from it (should byte-for-byte reproduce what exists today, a regression guard), then adding `repo_symbol_extraction` to `Repo Full Survey` (the concrete, known-missing step) as the first real proof the new mechanism works, not just reproduces the status quo.
3. **Re-run all survey-definition + Question docs against Egeria** once D3 lands, closing out the "full re-authoring, once, not twice" note from D1.
4. **D4 (EA integration)** — needs another design round on the two open questions above before any code.
5. **D5** — no action, revisit only if the developer-only assumption stops holding.

## Verification

- D2(c): unit tests already covering `health.py`/`security_hygiene.py`'s existing behavior must still pass unchanged after the `get_latest_project_stats()` swap (regression guard — same data, different code path).
- D3: a new test asserts the CSV-driven `SPECS` matches today's hardcoded literal exactly (before `repo_symbol_extraction` is added) — proves the migration is behavior-preserving; a second test asserts the validation guard actually fires on a deliberately-mismatched CSV/`STEP_REGISTRY` pair.
- D3 live: regenerate all 3 docs from the CSV, run them through Dr.Egeria against the real platform, confirm `Repo Full Survey` now has all 17 steps (via `reconcile_survey_definition_links.py --dry-run` reporting clean).
- Full RE test suite green throughout.
