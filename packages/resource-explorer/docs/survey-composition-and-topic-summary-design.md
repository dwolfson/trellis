# Chunky surveys, reducer steps, and topic summaries

**Status:** design note, nothing built. Written 2026-08-31 (UTC).
**Worked example:** security, because it is the worst case today — but the shape is general.

## The confusion this note exists to remove

`CLAUDE.md` and `Architecture.md` already name three things and say they are not synonyms:

| Concept | What it is | Where it lives |
|---|---|---|
| **Survey Definition** | A named, ordered graph of steps | Egeria, as a `GovernanceActionProcess` |
| **Step** | One unit of work | `surveyors/sub_surveyors/`, 33 of them |
| **Analysis** | A catalog entry describing a result a person can look at | `configdata/analysis_catalog.yaml` |

The distinction is written down and still collapses in practice, because **almost every analysis maps to exactly one step, and every step is surfaced as its own analysis card.** `AnalysisKind` accepts a *list* of steps and CLAUDE.md says an analysis "occasionally maps to several" — but **0 of 27 currently do.** When a 1:1:1 mapping is the only mapping anyone has seen, the three words start to feel like one thing with three names.

That collapse produced a wrong recommendation on 2026-08-31. Reviewing security, this repo found that `security_scan`'s three checks are each a weaker duplicate of a check another analysis performs, and concluded the *step* should be retired. Wrong layer. The step is cheap (`fast`, `inline`, reads stored data, fetches nothing) and its output is consumed by `foss_scorecard`. What is wrong is that it is *also* a top-level analysis card competing with better answers to the same question. **The duplication was in presentation, not computation** — and the fix for duplicated presentation is composition, not deletion.

### Egeria's names for these, and a collision in ours

RE's local vocabulary is not Egeria's, and since Egeria is the catalog of record it is worth
saying which is which. Egeria models both concepts as specification properties
(`Egeria-specification-properties.http`):

- **`SupportedAnalysisStep`** — `{name, description}`. This is RE's **step**.
- **`ProducedAnnotationType`** — `{name, description, openMetadataTypeName, analysisStepName,
  explanation, expression}`. A named kind of result, tied to the step that produces it, carrying
  its own explanation and a description of any calculation. **This is RE's *analysis*.**

So where this note says "analysis", Egeria says **annotation type**. Egeria has already modelled
step → produced-annotation-type, which is the relationship this whole design leans on; we are not
inventing a structure so much as using one we have not yet mapped onto.

**The collision to be careful about:** RE's Admin → *Annotation Types* page lists something else
entirely — the seven annotation *classes* (`ClassificationAnnotation` →
`ClassificationAnnotationProperties`, `QualityScoreAnnotation` → `QualityAnnotationProperties`,
and so on). Those are Egeria's `openMetadataTypeName`, i.e. **one field of** a
`ProducedAnnotationType`, not the thing itself. Two different concepts are called "annotation
type" in this system today, one of them in a UI label.

A rename is not proposed here — `analysis_catalog.yaml` keys schedules and stored findings, and
this note is not the place to spend that. But new work should say `ProducedAnnotationType` when it
means Egeria's, and anything published to Egeria should populate `analysisStepName` and
`explanation` rather than leaving Egeria to infer them.

## The case: security today

24 of the 49 questions in `docs/dr-egeria/resource_questions.csv` are tagged Security. They are answered by 13 different analyses spread across **five stages**:

    repo_conventions        discovery    4 questions
    chaoss_metrics          assessment   2
    security_scan           assessment   2
    foss_scorecard          assessment   2
    cii_badge               assessment   2
    cve_scan                assessment   1
    ci_quality              assessment   1
    security_features       assessment   1
    license_classification  discovery    1
    interface_surface       discovery    1
    repository_health       scouting     1
    dependency_analysis     analysis     1
    egeria_publish          curate       1

Four more are outright `GAP` — no analysis exists: secret handling, telemetry/phone-home, CLA/DCO provenance, SLA content.

The single biggest answerer, `repo_conventions`, is not in the security family at all.

**The presentation half of the fix already exists.** `SurveyResultDashboard("security_overview")` bundles eight of these and describes itself as *"the full security picture in one place, not five separate cards."* What does not exist is a survey that **runs** them as one unit. The dashboard combines results produced by eight independently-launched analyses, which is why a user still meets them as eight things.

## Proposal

### 1. A Security Survey, in Discovery, of seven steps

    security_scan  security_features  ci_quality  license_classification
    repo_conventions  foss_scorecard  cii_badge

All seven are `run_time: fast` and `availability: inline`. Two (`license_classification`, `repo_conventions`) are already in Discovery, so this pulls five up rather than pushing seven down.

**`cve_scan` is deliberately excluded.** It is `run_time: minutes`, `availability: queued`. Discovery's purpose is to be the cheap tier that gates the expensive ones (CLAUDE.md rule 17); a Discovery survey that blocks for minutes destroys the reason Discovery exists. It stays a separate Assessment-tier analysis and its findings remain available to anything that reads stored results.

Surveys being chunkier than analyses is the point. There is no rule that a survey is one step, and several small steps behind one launch is a better unit of *user intent* — "tell me about security here" — than seven cards that each answer a fragment.

### 1b. And a `Security_Assessment` survey, in Assessment

Discovery and Assessment want *different surveys over overlapping steps*, and this is the case
that shows why a survey is not just a bag of steps.

**Discovery's security survey answers "is this worth a closer look?"** — cheap, no fetch beyond
two inline lookups, safe to run across many repos.

**`Security_Assessment` answers "does this meet our bar?"** — it is allowed to be slow, so it can
include what Discovery must exclude:

    everything in the Discovery survey
    + cve_scan                 (run_time: minutes, availability: queued)
    + the four GAP steps, once they exist
      (secret handling, telemetry/phone-home, CLA/DCO provenance, SLA content)

The tier rule (CLAUDE.md 17) is what separates them: Discovery is the cheap tier that gates the
expensive ones, so `cve_scan` cannot be in it. Assessment is where scoring against criteria
belongs, and where minutes are acceptable because a person asked for a verdict on one resource.

Two consequences worth stating, because they are the arguments *for* two surveys rather than one:

- **The same step legitimately appears in both.** `security_scan` runs in Discovery and again in
  Assessment. That is not duplication — findings are append-only and `surveyed_at`-stamped, so the
  second run is a later observation of the same thing, which is what trends are made of.
- **Their summaries should differ in kind, not just in detail.** Discovery's is a triage signal
  ("nothing here blocks a closer look"). Assessment's is a verdict against criteria, and is the one
  that should be publishable to Egeria as a `QualityAnnotation`. A triage signal promoted to a
  verdict is the same overclaim as "Security Scan" meaning three file checks.

### 2. Reducer steps — optional, and not necessarily one

A survey **may** end with a step that reads what the previous steps wrote and emits a summary
annotation for the topic. It may also have none, or several. The survey is a graph of steps
assembled for a purpose; a reducer is just a step whose inputs happen to be other steps' stored
findings, and nothing in the model privileges it.

Where more than one earns its place: a `Security_Assessment` might reduce *artifact hygiene* and
*externally-attested trust* separately, because they fail differently — the first is about what the
project did, the second about what outside parties observed and when they last looked. Averaging
those into one number destroys the distinction that makes either useful. Equally, a survey run for
a purpose that needs no summary should not grow one for symmetry.

The pattern is not speculative:

**`foss_scorecard` is already a reducer step.** Its `run()` does no scanning of its own for several checks — it queries the stored findings of five other kinds:

```python
findings = {
    kind: (self.registry.query_findings(slug, kind) or [])
    for kind in ("ci_quality", "security_scan", "security_features",
                 "cve_scan", "supply_chain")
}
```

So the mechanism works today and is in production. What it lacks is a name, a declared position in a survey graph, and any notion that the steps it reads might disagree.

A reducer is an ordinary step: it produces annotations like any other, it is registered like any other, and it happens to take the whole resource as its scope. Nothing new is required in the step model — which is also why having none, or three, costs nothing structurally.

### 3. Raw annotations are still written, always

Any summary is **in addition to**, never instead of, each step's own annotations.

`project_analysis_findings` is append-only and `surveyed_at`-stamped by design, and trends depend on it — "what changed since last time" is only answerable because nothing overwrites its predecessor. A summary that replaced its inputs would destroy exactly the history the append-only design exists to keep. It would also make the summary unfalsifiable: a reader could not check the reduction against what it reduced.

**Presentation may show only the summary. Storage always keeps everything.** Those are different decisions and should be made separately — collapsing them is how the raw signal gets lost to a UI preference.

## Which moment does a summary describe?

This has to be settled before precedence, because "which step wins" is a different question
depending on whether the inputs are from one moment or many.

**A survey run is an event. A results tab is a state.** The codebase makes the difference
structural, not stylistic:

- **A run** produces one `ActivityEntry` — one `id`, one `ts`, one `operation: 'survey'`, one
  `annotations` list — and `SurveyOrchestrator` stamps every step in that run with a single shared
  `surveyed_at`. Published, it becomes one Egeria `SurveyReport` with its annotations beneath it.
- **A results tab** does not read runs at all. Each analysis's results come from `query_findings`,
  which takes `MAX(surveyed_at)` **per kind, independently**. It assembles the most recent sighting
  of each analysis, and those sightings can be days apart.

So a security results tab showing seven analyses may be showing seven different moments:
`security_scan` from this morning, `cii_badge` from last week, `foss_scorecard` from a run that
partly failed. It reads as one coherent picture of the repo *now*; it is really **a composite of
the latest sighting of each thing**, and nothing labels it as such. That is usually what a reader
wants — but it is not a run.

### The consequence for reducers

A reducer step has two genuinely different jobs available, and they are not interchangeable:

1. **Summarise this run** — only what the preceding steps just produced. One moment, internally
   coherent, blind to anything this survey did not include.
2. **Summarise current state** — read latest-per-kind as the results tab does, including analyses
   this survey never ran. More useful, and more dangerous: the inputs may be weeks old while the
   summary annotation carries today's `surveyed_at`.

Applied to security, option 2 says "no known vulnerabilities" on the strength of a month-old
`cve_scan`, stamped today. That is precisely the confident-but-stale claim `cii_badge` goes to
lengths to prevent for badge staleness — *"the level alone would carry the badge's authority with
none of its age"* — reproduced one layer up, and about our own data rather than someone else's.

**`foss_scorecard` is already silently option 2.** It reads `query_findings` for five other kinds,
so it mixes whatever was last seen regardless of run. Nobody chose that; it is what the default
read gives you, and it is invisible at the call site.

Neither option is wrong. The requirement is that a summary **states which it is**, and that a
state-summary carries the age of its oldest contributing input rather than the time it was
computed. A reducer that cannot say how old its inputs are should not emit a summary.

### Rename the tab: Results → Dashboard

The two-moments problem above is partly self-inflicted, and the tab label is where it starts. The
stage tabs read **📈 Results**, and the code comment explaining the placement says it sits next to
Survey *"since that's where a run's results naturally get looked for."*

That is the conflation, written down as a design rationale. The tab was positioned to catch people
looking for **a run's** results, and it shows **latest-per-kind across all runs**. A reader who
follows that signposting gets something other than what they came for, and nothing on the page says
so.

**Rename the label to 📈 Dashboard.** It is what the thing already is everywhere else in the code —
`SURVEY_RESULT_DASHBOARDS`, `SurveyResultDashboard`, `get_dashboard_stages`, and the route's own
docstring calling it *"a pure aggregation layer"*. The UI label is the only place it is called
anything else.

Scope is small: **5 label strings**, against 24 internal references (`'results'`, `stage-results`,
`_resultsHost`) that should **not** change — same discipline as leaving `security_scan`'s id alone
while fixing what a user reads. Identifiers key state and routing; labels are the claim.

This frees "results" to mean what a survey run produced, which is what a user reaching for the word
usually means, and leaves "dashboard" meaning the composite view.

## The hard part: precedence between steps that disagree

Two steps in this survey answer the same question at different strengths:

| Step | Says |
|---|---|
| `security_scan` | `SECURITY.md` exists |
| `repo_conventions` | it exists **and contains** a disclosure process — matched on `responsible disclosure`, `report a vulnerability`, `pgp key`, `security@` |

Showing both is what makes the current UI confusing. The second strictly subsumes the first: any repo passing the content check necessarily passes the presence check.

**Rule: strongest evidence wins; the weaker check is retained as corroboration, not deleted.** The summary reports the content-level answer. The presence-level finding stays in storage, stays in the trend, and is available to anything that wants it.

This is genuinely new here. `foss_scorecard` does a primitive version — it takes the *first* match while scanning `("security_scan", "security_features")` in order — and notably it does not know `repo_conventions` has a better answer than either. First-match-by-list-order is precedence by accident of authorship.

### Whose rule is it?

An earlier draft of this note proposed a single global precedence table, declared alongside the
check definitions, on the grounds that "which evidence is stronger" is a property of what the
checks measure rather than of any consumer. **That is wrong, and worth recording as wrong.**

Precedence is the **dashboard author's** call — equally, the reducer author's. It is up to whoever
writes a dashboard or a reducer to decide which annotations to process and how to combine them.
Two consumers can legitimately treat the same pair of findings differently:

- A **triage** view wants the strongest single answer and nothing else — one line, no ambiguity.
- An **assessment** view may want both, precisely *because* they differ: "policy file present but
  no disclosure process in it" is a more actionable finding than either check alone, and collapsing
  it to the stronger one throws away the gap.
- A **trend** view wants neither collapsed — it wants each check's own series over time.

A global table would force all three into one answer and would be wrong for at least two of them.

What survives from the earlier draft is narrower and still worth holding: **whatever precedence a
dashboard applies should be legible in that dashboard, not an accident of list order.**
`foss_scorecard`'s first-match loop is not objectionable because it chose wrongly — it is
objectionable because nobody chose. The rule and the iteration order are the same line of code, so
a reader cannot tell intent from convenience, and a future author reordering the tuple for
tidiness would silently change the result.

This also settles what the *steps* owe: nothing. A step reports what it measured, at the strength
it measured it. It does not know what else ran, does not defer to a stronger check, and does not
suppress itself. Reconciliation is the consumer's job, which is what keeps steps composable across
surveys that combine them differently.

### Absence must survive the reduction

The existing vocabularies are the constraint any reducer has to respect: `measured` / `nothing_found` / `not_established` / `never_run`, and the compile manifest's gaps. **A summary that renders "never ran" and "ran, found nothing" identically is the failure mode this codebase names as its most common bug class**, and a reducer is precisely where two different absences get averaged into one confident sentence.

Concretely: a security summary for a repo where four of seven steps never ran is not a security score. It is a partial answer and must say so.

The `cii_badge` module is the worked example of doing this right — three outcomes (`registered` / `not_registered` / `unreachable`) kept apart on the grounds that a network failure rendered as "no badge" would be a claim about someone's project derived from our own connectivity.

## What is built, and what is not

**Built:**
- Steps, and 33 of them
- `AnalysisKind` accepting multiple steps (unused: 0 of 27)
- Reducer steps reading other steps' stored findings (`foss_scorecard`)
- The security grouping and its combined renderer (`security_overview`)
- Append-only, `surveyed_at`-stamped findings, so trends survive whatever presentation does
- Survey Definitions as ordered step graphs, executed by `survey_definition_executor.py`

**Not built:**
- Any Survey Definition that bundles these steps
- A reducer step declared as such, rather than one that happens to read other kinds
- Explicit, testable precedence between steps answering one question at different strengths
- A topic-summary annotation distinct from a step's own annotations

The gap is smaller than it looks. Most of this is composition of parts that exist.

## Risks

**A summary is easier to read than to justify.** The value of one security sentence is exactly why it will be quoted without its caveats — the `security_scan` misdescription is the same failure at the catalog level, where "Security Scan" was read as real scanning for months. A summary should carry its own provenance: which steps contributed, which did not run.

**Chunkier surveys make partial failure more likely and less visible.** Seven steps means seven ways to be incomplete, and a survey with no reducer pushes that judgement onto the reader instead of removing it. Any reducer must distinguish "the survey ran and this repo is fine" from "the survey ran and most of it did not."

**Precedence rules rot.** A rule saying `repo_conventions` beats `security_scan` on security-policy is correct until someone strengthens `security_scan`. It needs to be data with a test, not a comment.

## Open questions

1. Does the topic summary want a new annotation type, or is `ClassificationAnnotation` with a summary field enough? (Egeria has to be able to receive it either way.)
2. Should a reducer run when some inputs are missing, or refuse? Refusing is honest and unhelpful; running risks the averaged-absence failure above.
3. Is "security" the right topic granularity, or is it two topics — *hygiene/artifacts* and *externally-attested trust* (`cve_scan`, `foss_scorecard`, `cii_badge`)? The latter three answer the same question from outside the repo and have different failure modes.
4. Where do the four `GAP` questions go — do they become steps in this survey later, or a separate one? Secret scanning in particular is what "Security Scan" claimed to do all along.

5. **Do findings need a real run identifier?** `project_analysis_findings` has
   `project_slug, kind, surveyed_at, check_name, label, summary, confidence, detail_json,
   scope_locator` — **no run column**. A run is identifiable only by its shared `surveyed_at`, and
   only by convention: `SurveyOrchestrator` happens to stamp all its steps alike, nothing enforces
   it, and `query_findings` does not use it that way — it takes `MAX(surveyed_at)` per kind
   independently, so the convention is not even relied upon by the main reader.

   Given a finding today you can ask *when was this observed*, but not *which survey produced this*.
   That is exactly the question a run-scoped reducer needs answered, and the question an auditor
   asks of a published summary. A `run_id` column would make "summarise this run" a real query
   rather than a timestamp coincidence, and would let a summary annotation name its inputs.

   Against it: `surveyed_at` already works as a de facto key for the one producer that sets it, the
   table is large and append-only, and `arch_recovery` solved a narrower version of this with
   `run_label` on component rows rather than a schema change — worth reading before adding a column
   (see `persist.py`, and the withdrawal design that depends on it).

   Not decided here. But a reducer built before this is settled will encode whichever answer was
   convenient, and that is how conventions become load-bearing without anyone choosing them.
