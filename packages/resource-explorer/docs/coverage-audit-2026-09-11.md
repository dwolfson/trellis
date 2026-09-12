# Coverage audit — questions ↔ analyses ↔ steps ↔ surveys

Measured 2026-09-11 against the live registry (61 repos) and the committed
catalogs at `004cb66`. Every number came from a query, not a read.

**Two framing decisions from the project owner shape this document, and the
first draft got both wrong.** They are recorded here so the numbers are read
against the right yardstick:

1. **Analyses serve two purposes, not one.** Beyond answering the catalogued
   questions, they exist to make the Chat interface useful for *ad hoc*
   questions — "how many classes, name them, how is this related to that, how
   many files, how big are they" — the shape of question Egeria Advisor showed
   users actually ask. An analysis that answers no catalogued question is not
   an orphan; it may be exactly the data a chat answer needs.
2. **The goal is not to run every survey on every repo.** It is to run the
   *right* surveys to meet the intent of investigating a repo. A repo that
   Scouting shows to be uninteresting is stopped, and no deeper tier is owed
   to it. Coverage is therefore measured against **repos a person chose to
   keep investigating**, not against the estate.

## Inventory

| | count |
|---|---|
| questions (`question_catalog.yaml`) | 52 |
| analyses (`analysis_catalog.yaml`, repo) | 36 |
| steps (`STEP_REGISTRY`) | 40 |
| survey definitions (`repo_survey_types.csv`) | 10 |
| repos in the registry | 61 |
| … with any disposition | 17 |
| … disposition = keep investigating (`investigating`/`tracking`/`using`/`recommended`) | **14** |
| … disposition = stopped (`ignored`/`abandoned`) | 2 |
| … not yet analysed | **44** |

## 1. The wiring is sound

| check | result |
|---|---|
| questions claiming `kind: analysis` with no `analysis_ids` | 0 |
| `analysis_ids` naming an analysis the catalog does not have | 0 |
| analyses cited by a question that own or derive no runnable step | 0 |
| analyses that answer a question and have **never run** | 0 |
| registered steps in no survey definition | 0 |
| survey rows attributing to nothing | 0 |

"Does the chain work" is yes, end to end.

## 2. Questions with no survey or analytic

11 of 52 have no machine answer. They split three ways, and only one way is a
gap:

| kind | n | questions | reading |
|---|---|---|---|
| `human`, Analysis/Enrichment | 5 | monitoring fit, security fit, infrastructure fit, skills, governance fit | **by design** — rule 17: Enrichment is served by `context.py`, not analyses |
| `human`, Analysis | 2 | *do we already support these dependencies?* · *do we know the cost to run it?* | human by nature of the question; a machine could *inform* but not answer |
| `partial`, Analysis | 1 | *what kinds of integrations does it support?* | partially covered; not enumerated here |
| **`gap`, Analysis** | **3** | ***what are similar repos, how does this differ?* · *what is the upgrade process?* · *for AI/ML assets, what licensing or usage constraints apply?*** | **nothing exists** |

So the honest count of questions with no survey or analytic is **three**, with
one more partially covered.

## 3. Coverage per stage

`direct`, `chart` and `mixed` count as machine-answerable alongside `analysis`:

| stage | questions | machine | human/gap | analysis-Qs exercised |
|---|---|---|---|---|
| Analysis | 22 | 16 | 6 | 9 of 9 |
| Discovery | 12 | 12 | 0 | 4 of 4 |
| Assessment | 7 | 7 | 0 | 6 of 6 |
| Scouting | 5 | 5 | 0 | 4 of 4 |
| Analysis/Enrichment | 5 | 0 | 5 | — |
| Automate | 1 | 1 | 0 | — |

Every analysis-backed question has been exercised on at least one repo.

## 4. The actual gap — measured against intent

For the **14 repos a person chose to keep investigating**, how many *cannot*
answer each deeper-tier question because a cited analysis has not run there?
(A derived analysis inherits its source's runs — `architecture_diagram` counts
where `architecture_recovery` ran.)

| kept repos that cannot answer | question | missing |
|---|---|---|
| 13 of 14 | Is IP provenance managed via DCO/CLA? | `contribution_provenance` |
| 13 of 14 | Telemetry / phone-home mechanisms? | `telemetry_scan` |
| 12 of 14 | How are secrets and credentials handled? | `secret_scan` |
| 11 of 14 | What APIs and code symbols does it expose? | `interface_surface`, `api_structure` |
| 9 of 14 | Are there outstanding CVEs? | `cve_scan` |
| 9 of 14 | What dependencies does this require? | `dependency_analysis` |
| 9 of 14 | OpenSSF Scorecard-style score? | `foss_scorecard` |
| 9 of 14 | How concentrated is authorship? | `chaoss_metrics` |
| 9 of 14 | How much code, how complex? | `language_file_classification`, `api_structure` |
| 8 of 14 | Clear process for reporting security issues? | `security_scan`, `repo_conventions` |
| 8 of 14 | OpenSSF Best Practices badge? | `cii_badge` |

Discovery- and Scouting-tier questions are answerable on most kept repos; the
gap is concentrated in Assessment and Analysis — the tiers a "keep
investigating" decision is supposed to unlock.

**This is the finding.** Not "the estate is uncovered" — 44 repos simply
have not been analysed yet, which says nothing about whether they are
interesting (project owner, 2026-09-11: "I haven't spent the time to analyze
all of the repos yet — that doesn't mean they aren't interesting, just not
done") — but *"for the repos already decided worth it, the deeper questions
mostly cannot be answered"*. Fourteen repos, ten questions, a handful of
analyses. The 44 will each produce their own version of this gap as they are
reached.

### The funnel is respecting its stops

Deeper-tier analyses that ran on repos later marked `ignored`/`abandoned`: **9
runs, all on `amundsen`**, on 2 stopped repos. Effectively no work is being
spent past a stop decision.

### Related: the funnel-cost spec's §2 said "not narrowing"

That measurement (2026-09-10) found 100% discovery→analysis retention on the
26 *attributable* repos. Read against this document's yardstick, the two are
compatible: the funnel narrows by **disposition** (14 kept, 2 stopped, 44
not yet reached), and the deeper tiers are applied — thinly — to the kept
ones. What §2 could not see, because it read only the activity log, is that
most repos have not entered the funnel yet.

## 5. Analyses answering no catalogued question — read against purpose 1

| analysis | intent | ran on | reading |
|---|---|---|---|
| `manifest_parse` | analysis | 16 | writes `project_dependencies`; feeds `dependency_analysis` *and* chat ("what does this depend on") |
| `code_symbol_extraction` | analysis | 8 | writes `project_code_symbols`; feeds `interface_surface`/`api_structure` *and* chat ("how many classes, name them") |
| `sub_resource_survey` | analysis | 8 | infrastructure |
| `refresh_plan` | analysis | 6 | infrastructure |
| `security_summary` | assessment | 3 | no catalogued question and no evident chat role — **worth a decision**, not a deletion |
| `repo_profile_refresh` | scouting | 0 | owns no steps, never ran — **dead entry** |

The first draft called the first two "orphans". Under purpose 1 they are
among the most load-bearing analyses in the catalog. The catalog has no field
that says so, which is why they *look* orphaned to any tool that only joins
against `question_catalog.yaml`.

## 6. Steps owned by no analysis — same reading

`repo_file_inventory`, `repo_file_size`, `repo_git_statistics`,
`repo_homepage` run in surveys with no owning analysis. Under purpose 1 they
are plausibly the chat data for "how many files, what files, how big" — but a
survey definition built from them alone would attribute to `unknown-analysis`,
and their cost is invisible to `get_analysis_last_run`. Giving them an owner
costs nothing and makes them visible; it does not change what they do.

## 7. Concentration

`repo_conventions` answers **7 of 23** analysis-backed questions — 30% — and
is a zero-fetch Discovery analysis. One analysis's correctness carries nearly a
third of the machine-answerable catalogued surface.

## What to improve, in order

1. **Close the deeper-tier gap on the 14 kept repos.** This is bounded work:
   `RepoAssessmentSurvey` (10 steps) and `RepoComplianceSurvey` (14) on
   fourteen repos, not sixty-one. The freshness gate declines what is already
   current. Whether that is a one-off or a rule — "a `keep investigating`
   disposition schedules the deeper surveys" — is a product decision, and the
   second is the one that keeps this from recurring.
2. **The 44 not-yet-analysed repos are pending, not out of scope.** Each will
   need Scouting, then a disposition, then — if kept — the deeper surveys.
   Item 1's "a `keep investigating` disposition schedules the deeper surveys"
   rule is what stops the gap in §4 reappearing for every one of them as it
   is reached.
3. **Give the catalog a way to say "this exists for chat."** A `serves:`
   field (`questions` / `chat` / `feeder` / `infrastructure`) on
   `AnalysisCatalogEntry` would stop `manifest_parse` and
   `code_symbol_extraction` reading as orphans to every future audit, and make
   `security_summary`'s status a stated decision rather than an omission.
4. **Own the four unowned steps** under a Scouting-tier profile analysis so
   their runs attribute.
5. **Retire `repo_profile_refresh`** (dead) and **decide `security_summary`**.
6. **Only then consider new analyses**, and only for the three `gap`
   questions. *Upgrade process* and *AI/ML licensing* are plausibly derivable
   from data already collected (release notes; license and model-card files).
   *Similar repos* is a different kind of problem and should not be built on
   the strength of one question.
7. **Look at `repo_conventions`' seven checks** for independence — not to
   split it, but to know whether one broken check takes seven answers with it.

## What this audit could not see

- **Answer quality.** "Ran on N repos" is presence, not correctness; a run
  that produced `unverified` for every check counts here as coverage.
- **Chat coverage itself.** Purpose 1 is real and is not measured here — there
  is no catalogue of ad-hoc chat questions to audit against. If one existed
  (even a sample of what people actually asked), the "orphan" analyses could
  be scored the same way as the catalogued questions.
- **Egeria-side analyses.** `include_egeria_live=False` throughout.
- **Database and filesystem resources.** Repos only.
