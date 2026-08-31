# Publishing a *changed* Survey Definition or Question set

**Status:** written 2026-08-31 from an actual publish, not from theory. Every command and
every trap below was run or hit; where something was inferred rather than observed it says so.

**This is not the reset runbook.** [`egeria-reset-recovery.md`](egeria-reset-recovery.md) covers
recovering after Egeria's database is wiped, where *nothing exists* and the bootstrap heals by
canary. This covers the opposite and more dangerous case: **the elements already exist, and you
are changing them.** The traps are different, and two of them invert between the cases — advice
that is correct there will damage a live platform here.

The short version:

| | wiped platform | live platform, incremental change |
|---|---|---|
| Re-running a whole document | correct, nothing to duplicate | **duplicates every link in it** |
| Run the full questions document | **required** | usually wrong — publish a subset |
| Reconciler after authoring | required | required, but **only after the last document** |

---

## 0. Before you touch anything

```bash
# 1. The reconciler can actually delete. Below 6.0.18.4 its deletes silently no-op AND it
#    reports removals that did not happen (PYEGERIA_ISSUES ISSUE-63) — so a clean-looking
#    run is not evidence of anything.
uv run python -c "import importlib.metadata as m; print(m.version('pyegeria'))"

# 2. A clean baseline. If this is NOT already zero, fix that first — otherwise you cannot
#    tell your damage from someone else's.
uv run python scripts/reconcile_survey_definition_links.py --dry-run

# 3. The pre-state, so you can prove what changed rather than assert it.
uv run python -c "
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader as R, clear_caches
clear_caches(); r=R()
for n in ('RepoAssessmentSurvey','RepoFullSurvey'):
    g=r.find_process_guid_by_name(f'GovActionProcess::{n}'); d=r.fetch(g)
    print(n, len(d.steps), 'steps, last =', [s.re_analysis_step for s in d.steps][-1])"
```

---

## 1. Decide *what* to author: the whole document, or a subset

This is the decision that matters most, and it is not about tidiness.

**Re-running a whole document re-fires every link command in it against elements that are
already linked.** `Link First/Next Process Step`, `Link Perspective to Question` and
`Link Element To Scope` do not dedupe. Measured 2026-08-31 on a single publish of two
survey-definition documents: **40 duplicate edges** (8 on `RepoAssessmentSurvey`, 32 on
`RepoFullSurvey`).

For survey definitions that is recoverable — `reconcile_survey_definition_links.py` exists
precisely for it. **For questions it is not: perspective links have no reconciler.**
`questions/scouting-questions.md` carries 168 `Link Perspective to Question` and 54
`Link Element To Scope` commands. Re-running it whole to add 8 missing terms would have
duplicated 222 links with no cleanup path.

So: **if only some elements are missing or changed, author only those.** Extract the relevant
command blocks into a throwaway document. The blocks are separated by `___`, and each names its
subject in one of `### Display Name`, `### Term Name`, `### Question Name`, `### Target Element`.
`missing-questions-2026-08-31.md` is a worked example — 50 commands kept, 271 dropped.

The reason this is better than "re-run carefully" is that it makes duplication **impossible by
construction** rather than avoided by attention. Nothing existing is touched, so nothing existing
can be duplicated.

> **After a wipe this inverts.** Nothing exists, nothing can duplicate, and a subset would leave
> everything else missing. Run the full document. Delete any subset file once it has served its
> purpose, so nobody runs the wrong one later.

---

## 2. Author in dependency order — and do not reconcile in the middle

`_folder_order.json` encodes the order: **foundations → questions → survey-definitions.** A
definition's `Link Element To Scope` binds to Question terms *by name*; run definitions first and
every command still reports success while creating no ScopedBy links at all.

```bash
cd docs/dr-egeria/survey-definitions
dr_egeria --process --summary-only repo-survey-definition-assessment.md
dr_egeria --process --summary-only repo-survey-definition-full.md
```

**Read the summary table, not the exit line.** A run that ends `COMPLETED WITH ERRORS` still did
most of its work; the failures are individual rows. On 2026-08-31 those rows were eight
`Link Element To Scope` failures — Question elements that did not exist — which is how a separate
"41 of 49 questions are in Egeria" problem was discovered.

**If you are authoring more than one document, run them all before reconciling.** The reconciler
is **delete-only**: it removes duplicate and stale edges and never adds one. Mid-sequence, an edge
that the *new* chain replaces reads as stale while its replacement does not exist yet, so
reconciling between documents severs the chain. Observed 2026-08-31: after the first of two
documents, the dry-run wanted to delete `repo_sub_resource_survey -> repo_rag_ingestion` from
`RepoFullSurvey`, whose replacement (`… -> repo_security_summary -> repo_rag_ingestion`) only
existed after the second document ran.

---

## 3. Reconcile, then prove the deletes happened

```bash
uv run python scripts/reconcile_survey_definition_links.py
uv run python scripts/reconcile_survey_definition_links.py --dry-run   # must say "nothing to do"
```

The second command is the point. The reconciler's own output says "removed", and on pyegeria
below 6.0.18.4 that sentence is printed for deletes that silently did not happen. **Re-running the
dry-run is the only cheap evidence available.**

---

## 4. Verify against the definitions, not the output

```bash
# chains load, and a reducer step still runs after its inputs
uv run python -c "
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader as R, clear_caches
clear_caches(); r=R()
for n in ('RepoAssessmentSurvey','RepoFullSurvey'):
    g=r.find_process_guid_by_name(f'GovActionProcess::{n}'); d=r.fetch(g)
    s=[x.re_analysis_step for x in d.steps]; print(n, len(s), 'steps, last =', s[-1])"

# every catalog question resolves — this is what ScopedBy links bind to
uv run python -c "
import csv
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader as R, clear_caches
clear_caches(); r=R()
qs=[x['Question'] for x in csv.DictReader(open('docs/dr-egeria/resource_questions.csv'))]
m=[q for q in qs if not r.resolve_question_guid(q)]
print(f'{len(qs)-len(m)}/{len(qs)} resolve'); [print('  MISSING:', q[:70]) for q in m]"

uv run pytest tests/test_egeria_live_smoke.py tests/test_survey_definition_graph_walk.py -q
```

`clear_caches()` is not optional in any of these. `SurveyDefinitionReader` caches candidates for
300s and question GUIDs for an hour, so a read straight after a publish can return the pre-publish
answer and look like the publish failed.

---

## 5. Traps that cost time on 2026-08-31

**A step's position in `STEP_REGISTRY` is its position in Full Survey's chain.** "Repo Full
Survey" is generated from the `*` sentinel, meaning *every STEP_REGISTRY step in that dict's own
order*. A new step added next to related ones lands wherever they are — a reducer written beside
the other security steps landed at index 21 of 34, ahead of two of its own inputs. **Read the
generated chain before publishing it**; the authored document is where this is visible, and it is
cheap to check.

**"Runs last" and "runs after its inputs" are different requirements.** Moving that reducer to the
end of the registry fixed Full Survey and broke `test_rag_ingestion_runs_last` — `repo_rag_ingestion`
is the most expensive step and nothing reads it, so it stays terminal. Two steps wanted the same
slot; only one needed it. Assert the property you actually need.

**Authored is not published.** Regenerating a document changes only the file. Both problems that
cost time this day were the same state: a Survey Definition regenerated but never run, and a
questions document regenerated months earlier and never re-run, leaving 8 of 49 terms absent.
`test_egeria_live_smoke.py` catches the first. Nothing catches the second — the questions batch's
canary proves the batch *ran*, not that every element in it exists.

**Egeria writes may be blocked by the permission classifier.** If `dr_egeria --process` is refused,
do not work around it — the operation makes permanent changes to someone's platform. Hand the
command over, and verify the outcome yourself afterwards.

---

## Related

- [`egeria-reset-recovery.md`](egeria-reset-recovery.md) — the wiped-platform case, and where the
  bootstrap self-heal is described
- `docs/dr-egeria/survey-definitions/_batch.json` — the non-idempotency record, including both
  prior incidents (2026-08-13, and 22 duplicate edges on 2026-08-19)
- `docs/open-stack-checklist.md` §7 — what a redeploy destroys and the order to bring it back
