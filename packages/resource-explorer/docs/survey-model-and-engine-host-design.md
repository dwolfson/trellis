# Survey model: granularity, annotation types, and RE as an engine host

**Status: design note. All three §1 hazards FIXED (2026-08-26). §2–§4 not built.**
**Date:** 2026-08-26
**Supersedes in part:** `analysis-step-egeria-registration-plan.md` (D1/D3 shipped differently; D2 shipped; D4 still open)
**Prompted by:** the question of whether RE should manage two granularities — individual
analyses and survey types — or one.

---

## 0. Summary

RE models the same concept twice. `ANALYSIS_KINDS[k].step_keys` is "a named bundle of steps",
which is definitionally what a Survey Definition is, implemented in a second place with a
second authoring path. 25 of 27 repo analyses are single-step, so that second implementation
is 93% a pass-through.

The resolution is not to pick one. `analysis_id` is doing two jobs — bundling, and naming the
results a step produces — and only the first is duplicated. The second has a first-class home
in Egeria that RE currently fills with redundant data.

Egeria already models everything needed: guards, parameter passing, branching, named
annotation types, and multi-host work distribution with claim-based arbitration. **No extension
to Egeria's type model is justified by anything found here.** The work is removing assumptions
from RE, not adding to Egeria.

Three hazards shipped on 2026-08-26 that make the current state worse than it looks. They come
first because they are live.

---

## 1. Live hazards

All three are in code committed on 2026-08-26. None has fired yet, and each fires the first
time someone does the obvious next thing.

### 1.1 The generator destroys hand-authored definition detail

`scripts/generate_repo_survey_definition.py` ends in `output_path.write_text(markdown)` — a
full overwrite of every Dr.Egeria document it owns.

The generated documents carry exactly three additional properties per step (`executes_at`,
`supported_technology_type`, `re_analysis_step`) and the literal guard `Any` on every edge.
`repo_survey_types.csv` cannot express guards, request parameters, or branching, so any of
those must be hand-authored into the `.md`.

The first hand-authored guard is destroyed by the next generator run. Worse, the resync repair
added the same day (`egeria_resync._do_reauthor_survey_definitions`) *executes* those documents,
so the loss propagates: the guard is removed from the file, and then un-authored from Egeria by
RE's own repair.

**The CSV is a specification of what surveys are needed. The `.md` is the definition.** The
pipeline currently treats the definition as disposable output of the specification, which is
backwards, and which only survives today because nobody has authored a guard yet.

**FIXED 2026-08-26.** The generator now writes a file only when it is absent, byte-identical,
or provably untouched since it was last generated — the last established by a `.generated.json`
sidecar of content hashes. A file that differs from generation *and* from its recorded hash has
been hand-authored, and is reported with the first differing line rather than overwritten;
`--force` discards it deliberately.

The sidecar is what keeps `--force` rare. Without it, every legitimate CSV change would need
`--force` too, people would pass it by reflex, and the hazard would be back.

An earlier draft of this section proposed a second fix — "have the repair refuse to execute a
document that has diverged from the CSV" — and it was wrong twice over. The repair never
replaces documents; it executes them, which for a hand-authored guard is exactly what should
happen. And CSV-divergence is the wrong criterion: divergence is expected once the `.md` carries
detail the CSV cannot hold.

The real interlock is §1.2's hazard, and it shipped alongside: the repair now refuses to run
while any document carries a guard other than `Any`, because the reconciler it must run would
delete the branch. A document it cannot read counts as guarded. That refusal can be removed once
§1.2 is fixed, and not before.

### 1.2 The link reconciler forbids branching

`survey_definition_reconciler.py` identifies a duplicate edge by `(prev, next)` and does not
consider `guard` at all. `compute_expected_edges(survey_group, step_keys)` builds the expected
set as a **linear chain** from the step list.

Both are correct today, because every authored guard is `Any` and every definition is linear.
Neither survives the model in §4:

* `A → B guard=passed` and `A → B guard=failed` are legitimately distinct edges. The reconciler
  deletes one as a duplicate.
* Any genuine branch is absent from the linear expected set, so it is classified stale and
  removed.

This is the same hazard as §1.1 one layer down, and it is reached by the same action: authoring
a real guard. The reconciler is the mandatory post-heal step of the repair, so it runs on every
recovery.

**FIXED 2026-08-26.** `diff_links` is keyed on `(previous, next, guard)`, and
`reconcile_step_links` builds its expected set from the authored document rather than from a
linear chain over the step list. A copy left by a non-idempotent Link command is identical in all
three values, so matching on all three removes exactly what it should and nothing more.

The interlock added earlier the same day — refuse to repair while any document carries a real
guard — is gone with it, because refusing would no longer be honest.

Both sides were needed. Keyed on the guard but still diffing against a linear chain, every branch
edge would have been stale instead of duplicate: deleted either way. There is one document parser
for this (`surveyors/survey_definition_docs.py`), shared with the §1.3 scan, because two parsers
of one format is how they drift apart.

Verified against live Egeria before and after: all eight definitions reconcile to a no-op, with
kept counts equal to `steps − 1`. The change rewrites nothing on real data.

**What is deliberately NOT fixed: RE still cannot RUN a branching definition.**
`SurveyDefinitionReader._parse_graph` walks a single chain and raises
`UnsupportedSurveyDefinitionError` on a second outgoing edge. That is a loud, safe failure rather
than silent destruction, and it should stay one: evaluating guards to choose a branch is
implementing a workflow engine inside RE, which is exactly what §4 argues Egeria should own. The
hazard was never that RE refuses to run a branch — it was that RE destroyed one.

Note the irony worth recording: `NextGovernanceActionProcessStep` is MULTI_LINK, which is why
Dr.Egeria's link command duplicates rather than upserts — the problem that took definitions out
of service earlier the same day. The multi-link property is not a quirk. **It is the branching
mechanism.** RE's reconciler currently exists to suppress it.

### 1.3 The drift scan conflates two different checks

`egeria_resync._scan_definition_drift` compares Egeria's authored definitions against the CSV
and reports Egeria as "behind". That is one useful check, but it silently assumes the CSV is
authoritative and that every definition should have a CSV row.

There are two distinct questions, and only one of them is this:

| check | compares | means | tolerates |
|---|---|---|---|
| **recovery** | docs ↔ Egeria | Egeria has lost or drifted from the authored definitions | nothing |
| **specification coverage** | CSV ↔ docs | we said we needed a survey and never authored one | extra definitions |

The second must tolerate definitions with no CSV row at all — Egeria-native surveys, and
anything authored directly. The old scan would have reported those as drift, and did not only
because none exist yet.

**FIXED 2026-08-26.** Split into `definition_drift` (recovery: documents ↔ Egeria, drives the
repair, tolerates nothing) and `specification_gap` (coverage: CSV ↔ documents, tolerates extra
definitions, no repair button — closing a gap edits the source tree, and this panel repairs the
catalog, not the repository).

Two things fell out of doing it properly:

* **Order is now compared, not just membership.** Run order is load-bearing —
  `repo_foss_scorecard` reads what `repo_cve_scan` writes, and ran before it until earlier the
  same day. Verified first that document order matches live Egeria exactly across all eight
  definitions, so ordered comparison does not generate false drift.
* **Descriptions are compared too.** Comparing only step keys is what let Egeria sit on a
  `repo_manifest_parse` description the documents had already moved past — invisible to a scan
  whose entire job is to notice that. The split scan found it in three definitions immediately;
  they have since been re-authored and Egeria now matches.

Coverage remains membership-only, deliberately: the CSV's full-survey row is the sentinel `*`,
which has no order to compare, and its rows are not stored sorted. Order is authoritative in the
documents.

---

## 2. The granularity question

### 2.1 Evidence

Measured 2026-08-26 against `ANALYSIS_KINDS` / `STEP_REGISTRY` / `analysis_catalog.yaml`:

| fact | value |
|---|---|
| repo analyses | 27 (29 catalog entries; `egeria_publish` and `repo_profile_refresh` are actions, not analyses) |
| registered steps | 34 |
| analyses that are exactly one step | **25 of 27** |
| analyses that are real bundles | 2 — `language_file_classification` (3), `architecture_recovery` (2) |
| steps with no `analysis_id` at all | 4 — `repo_file_inventory`, `repo_git_statistics`, `repo_homepage`, `repo_file_size` |
| analyses carrying a results/render payload | 27 of 27 |
| distinct `annotation_types` across 29 analyses | **7** |
| analyses sharing `ClassificationAnnotation` | **14** |

Two readings follow directly.

The **bundling** role of `analysis_id` is duplicated. A bundle of ordered steps is what a Survey
Definition is, and the only two real bundles are exactly that shape. The four steps with no
`analysis_id` are the prerequisite refresh steps — expressible in a survey type, not as an
analysis — which shows the survey type is the *more* expressive of the two, not the coarser.

The **results** role is not duplicated, and `annotation_types` is not it either: 7 values across
29 analyses, one of which covers 14. Those are Python base classes describing the *shape* of a
result. The per-analysis result identity in RE today is the finding **kind** —
`chaoss_metrics`, `supply_chain`, `foss_scorecard` — a 1:1-with-step untyped string passed to
`upsert_finding`, with no registry behind it, which every results reader already keys on.

### 2.2 Three concepts, named

| concept | Egeria | RE today | status |
|---|---|---|---|
| workflow definition | `GovernanceActionProcess` | Survey Definition | ✓ |
| named microflow | `GovernanceActionProcessStep`, `analysisStep` | step key | ✓ |
| **result definition** | `AnnotationProperties.annotation_type` (free string) | finding `kind` | **not published** |
| result *shape* | annotation entity subtype | `ANNOTATION_TYPES_REGISTRY` (7) | ✓ |

`analysis_id` sits across rows 1 and 3 and belongs in neither. Its bundling half should collapse
into the survey type — including single-step survey types, which are a legitimate degenerate
case and not a workaround. Its results half should become a declared annotation type.

---

## 3. The annotation-type defect

`annotation_props.py` builds every annotation body as:

```python
"class":          "ClassificationAnnotationProperties",   # the shape
"annotationType": "ClassificationAnnotation",             # the shape again
"analysisStep":   ann.analysis_step,
```

`annotationType` is filled with the entity subtype name, duplicating `class`. Egeria's
`AnnotationProperties.annotation_type` is a free string intended to name *which* result this is.
The names RE actually has — `chaoss_metrics`, `supply_chain`, `foss_scorecard`, `cve_scan` —
never reach the catalog.

**This has already generated a workaround.** Commit `e915b1c` (2026-08-26) added the
`project_published_analyses` table because publish attribution keyed on annotation types could
not tell which analysis a publish covered — 14 analyses share `ClassificationAnnotation`, so the
question is unanswerable from that field. A local side-table was built rather than the wasted
slot being noticed. If `annotationType` carried the finding kind, that attribution would come
from the catalog for free, and the table would not exist.

This is the cheapest correction in this document: it is a string, RE already has the value, and
`AnnotationProperties` already has the field.

### 3.1 The one open modelling question

For steps with `executes_at: resource-explorer` there is no Egeria SurveyActionService provider
to *declare* which annotation types a step produces — RE's steps are not Egeria services, so
nothing declares them. Two options need no extension:

* `additionalProperties` on the process step (already carries `executes_at`, `re_analysis_step`)
* a `ValidValueSet` for the vocabulary

**The test for whether an extension is justified: do you need to query or navigate it?**
"Which steps produce `chaoss_metrics`?", or linking an annotation type to a Perspective the way
`Survey → Question → Perspective` already works — a string map answers neither. If that is the
intent, a real element and relationship is warranted. If it is only ever read once you already
hold the step, `additionalProperties` is sufficient and free.

Recommendation: do not extend until one concrete query motivates it. The symmetry argument
("what would this survey tell me?" mirrors the Question graph) is suggestive but is not yet a
use.

---

## 4. Target model: RE as an engine host

### 4.1 The mechanism exists

Confirmed in pyegeria on 2026-08-26. Nothing below requires a Java engine host or a change to
Egeria.

**Registration** — `AssetMaker.link_supported_governance_service()` writes
`SupportedGovernanceServiceProperties` with `requestType`, `serviceRequestType` and
`requestParameters`. MULTI_LINK: one engine, many request types. This is where `re_analysis_step`
becomes a real request type instead of an `additionalProperties` string.

**Finding work** — `AutomatedCuration.get_active_engine_actions()`, `find_engine_actions()`,
`get_engine_actions_by_name()`, and `GET /governance-engines/{guid}/engine-actions/active-claimed`
for one engine.

**Lifecycle** — `claim_engine_action()`, `update_engine_action_status()`,
`cancel_engine_action()`, over
`REQUESTED → APPROVED → WAITING → ACTIVATING → IN_PROGRESS → COMPLETED | FAILED | CANCELLED | ABANDONED`
(`pyegeria/core/_globals.py:ACTIVITY_STATUS`).

**Sequencing** — already modelled and already unused by RE:

| capability | Egeria | RE today |
|---|---|---|
| guards | `NextGovernanceActionProcessStepProperties.guard`, `mandatory_guard` | writes literal `Any` |
| branching / parallelism | multiple guarded next-steps (MULTI_LINK) | reconciler deletes them (§1.2) |
| parameter passing | `GovernanceActionExecutorProperties.request_parameters`, `request_parameter_map`, `action_target_map` | writes none |
| first-step parameters | `GovernanceActionProcessFlowProperties.request_parameters` | writes none |

Four capabilities, all present, none used.

### 4.2 Kafka is an optimization, not the mechanism

pyegeria has **no Kafka client** — no consumer, no producer. `egeria_kafka_endpoint` is a config
value (default `localhost:9192`) and `create_kafka_server_element_from_template()` catalogs a
Kafka server as an asset; neither consumes Egeria's own out topic. Consuming it means a direct
Kafka dependency in RE, outside pyegeria.

That matters less than it appears. Polling `active-claimed` has identical semantics to consuming
the topic. **Correctness rests on `claim`, not on delivery** — every host may see an action, one
claim wins. So the polling implementation can be built first and the topic added later purely to
cut latency and poll load, with no redesign.

### 4.3 What is not confirmed

**That `claim_engine_action` fails against an already-claimed action** rather than silently
succeeding. The entire model rests on server-enforced arbitration. It is strongly implied by
`ACTIVATING` existing as a distinct state between `WAITING` and `IN_PROGRESS`, but this was read
from the client side only. **Test against a live platform before designing on it** — two
concurrent claims on one action, expect exactly one success.

### 4.4 What it changes

`executes_at` collapses. Today `{resource-explorer, prefect, egeria}` is RE's own configuration
describing who runs a step. Under this model it is catalog data — which governance engine holds
a `SupportedGovernanceService` for that request type — and RE stops being a special case
alongside Egeria's native surveys.

It also answers §2 from a third direction: **the step is the unit of coordination and the survey
type is the process that sequences it.** Guards, branching and parameter passing stop being
things RE must express, because Egeria's process engine walks the graph and RE executes leaves.

And it raises the stakes on §3: RE's annotations would be consumed by things that are not RE, so
`annotationType` carrying the real finding kind stops being tidiness and becomes the interface.

### 4.5 What it costs

**Inversion of control.** `SurveyOrchestrator.run(slug, steps=…)` owns the loop today. For
Egeria-coordinated runs it would not. RE must keep the local path indefinitely — the argument
that made Automate local-first (`docs/automate-notification-manager-pyegeria-spec.md`) applies
unchanged whenever Egeria is unreachable. This is two execution paths for the same steps, for a
long time, and that is the real price.

**Recovery still runs on the local copy.** If Egeria becomes the runtime authority, a wipe means
rebuilding from RE's own copy — which must therefore be the *authored Dr.Egeria documents*, not
a projection of Egeria's graph. A projection preserves only what the reader models, and the
reader models neither request parameters nor branching, so round-tripping through it would
flatten exactly the detail §1.1 is about. This is why the documents are the durable artifact and
why the generator must not own them.

---

## 5. Sequencing

Ordered by dependency, not by value.

1. ~~**§1.1 generator seed-only.**~~ **Done 2026-08-26**, with the §1.2 interlock alongside it.
   Hand-authoring a guard is now safe from the generator, and refused by the repair rather than
   silently flattened.
2. **§3 publish the real `annotationType`.** One string, already held. Independently useful,
   and it retires the `project_published_analyses` workaround.
3. ~~**§1.3 split the drift scan**~~ **Done 2026-08-26**, with order and description
   comparison added — the latter caught real stale content on its first run.
4. ~~**§1.2 reconciler keyed on `(prev, next, guard)`**~~ **Done 2026-08-26**, with the expected
   set built from the authored document. Authoring a guard is now safe end to end; running one
   is still refused, deliberately.
5. **Confirm §4.3** against a live platform. Gates everything below.
6. **Collapse `analysis_id`'s bundling role into survey types.** Migration with real blast
   radius: `resource_schedules` has live rows keyed by `analysis_id` and 27 render payloads to
   repoint. Own design pass.
7. **Engine-host participation**, polling first.

Steps 1–4 are corrections to shipped code and were worth doing whether or not §4 is ever built.
All four are done. Everything from 5 onward depends on the engine-host decision.

---

## 6. Open questions

* **Where is the source of truth?** This note assumes CSV → `.md` (definition) → Egeria
  (runtime authority) → local docs (recovery). An alternative is Egeria-as-truth with the local
  copy purely a cache — but §4.5 shows the cache cannot be a projection, so the two converge on
  the documents being durable regardless. Worth stating explicitly rather than leaving implied.
* **Who authors?** `repo_survey_types.csv` and its generator live in RE, which sits awkwardly
  with "EA is the authoring environment for Dr.Egeria documents, RE is not." Making survey types
  the sole granularity puts ~30 definitions on that path and forces the question. Unresolved;
  `analysis-step-egeria-registration-plan.md` D4 deferred it and it is still deferred.
* **Do single-step survey types need Egeria to exist to be schedulable?** Under §4 yes, which is
  a new hard dependency for something RE does locally today.
* **Is `analysisStep` the step key or the display name?** RE writes `ann.analysis_step`, which is
  the surveyor's `STEP` constant (`ChaossMetrics`), not the registry key (`repo_chaoss_metrics`).
  Harmless today; ambiguous the moment anything joins on it.
