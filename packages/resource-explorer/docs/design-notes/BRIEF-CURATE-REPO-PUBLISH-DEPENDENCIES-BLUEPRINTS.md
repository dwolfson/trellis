# BRIEF — Curate for repositories: publish from the existing survey, the commit summary, dependency kinds, blueprints, zones, rules wording (2026-10-07)

Design session brief for the coordinator and one builder, on a branch from
main after UI batch B. Source: `DESIGN-CURATE-NESTING-SELECTION-AND-DEPENDENCY-KINDS.md`
(final at 608bd2be) and the owner's words of 2026-10-07 relayed by the
coordinator. Every rule of `BRIEF-PARITY-G1-G3-TO-ALPHA.md`'s preamble applies
(verbs, cue vocabulary, proof rows by GUID after a read, Egeria's full
sentence stored, the ISSUE-117 block on, US spelling, worktree and red runs,
registry guard). The owner gates by use on egeria_git on 8813. Nesting depth
and explicit selection (design §1, §2) are a later brief; nothing here
pre-empts them.

## 1. Publish from the existing survey; re-survey is its own act

**Owner:** "we shouldn't have to survey again before publishing — we are
asking the user to make decisions on what has already been surveyed, not
what the current state is."

What the code does today (read on main 30de07da): the repository publish
(`repo_publish.publish_report`) runs `SurveyOrchestrator.run(slug,
steps=None)`, a full survey, then publishes the result whole; the Curate
Catalog commit (`workflows/curate_commit._resurvey_plan`) re-runs only the
analyses that have run before and are stale, all of them on a first
catalog, none when everything is fresh and the asset exists, then publishes.
Both therefore publish a survey the person has not seen.

Rule: **publish publishes the survey the person decided on.** The report
RE publishes is the latest completed survey already in the registry, with
its age shown. Re-surveying is a separate, explicit control, never a side
effect of a publish or a commit.

- The Publish band shows the survey it would publish before the press:
  "from the survey of <date> · <n> h ago · <m> annotations · <k> steps
  ran". The button reads "Publish to Egeria →" (or "Publish again").
- A separate control beside it: "Re-survey now →" (words per the verbs
  ruling: a local run says Run; "Re-survey" is the existing noun for this
  act and stays), which runs the survey and nothing else; the band then
  shows the new age. Stale steps are named, not auto-run: "3 of 12 steps
  are stale (older than their refresh rule) · re-survey to refresh" with
  the cue ⚠ and the word "stale", one gesture to the list.
- **No survey exists:** the button is disabled with the reason directly
  under it, "no survey to publish yet · run the first survey", and the
  re-survey control is the only enabled one; the first survey is never run
  implicitly by a publish.
- **The Curate Catalog commit** follows the same rule: `_resurvey_plan`'s
  "refresh stale, then publish" becomes two states on the commit's
  manifest: a line "survey of <date> · <n> stale steps" and a checkbox,
  off by default, "re-survey stale steps first (adds minutes)" under the
  Catalog button, the same place the database commit keeps its refresh
  box. Unchecked, the commit publishes from the existing survey and the
  proof row records which survey (`surveyed_at`) it published. On a
  repository with no survey the commit is blocked with the same sentence
  as above. The hint text "refreshing stale surveys only, then publishing"
  goes.
- Proof rows: `report_published` records `surveyed_at` of the survey it
  published and `reused` when the report already existed; the row reads
  "published · from the survey of <date> · read back <when>".
- Tests: a publish never calls the orchestrator; the commit with the box
  unchecked never calls it; with the box checked it runs exactly the stale
  steps; no-survey blocks both with the sentence.

## 2. The commit summary for repositories

**Owner:** "yes, we need the summary for repos."

The database Curate pane has "what this commit does" as a manifest table
with the Catalog button at its top right (the designer's panel C). The
repository gets the same table, before and after a publish or commit.

Before the press, one row per mechanism:

| | what | how many | from |
|---|---|---|---|
| RE publishes | the repository asset and its survey report | 1 report · N annotations | survey of <date> (<age>) |
| Egeria gets | the lines you confirmed under "what it is" | N entities | your confirmations |
| Egeria gets | the folders and files you chose | N files · M folders · K containers | your selection |
| Egeria gets | the file types you chose | N DataSet elements | your selection |
| Blueprints | the blueprints you chose to write | N (kinds named) | your verdicts |
| Left out | nothing in Egeria changes | N proposals not confirmed · M not selected | — |

The button "Publish N items" (or "Catalog" where the commit is the act) at
the table's top right; blockers directly under it (no survey, nothing
selected, no project context with its two choices). The re-survey checkbox
of §1 under the blockers.

After the press, the same table gains a state column derived from proof
rows: ◔ "sent", ✓ "published · read back <when>", ✕ "not published ·
<Egeria's sentence>", with the commit header line "Publish · commit <id> ·
step n of m · running: <label> · k failed" and the numbered steps below
(panel B). Counts in the table are the proof rows' counts, never the
request's.

Tests: the table's numbers equal the selection and the proof rows; a press
with nothing selected is blocked with the sentence and writes nothing.

## 3. Dependencies as one table with a kind column

**Owner:** one table, "more extensible."

- One table on the Analysis pane's dependencies section: columns kind ·
  name · version or target · source · state. Kinds today: `build-time`
  (manifests: pyproject, requirements, package.json, pom, gradle) and
  `runtime` (deployment evidence: compose services, Helm values, Dockerfile
  `FROM` and env, connection strings, ports and wires). A third kind is a
  new value, not a new section.
- Header line with per-kind counts: "12 build-time · 3 runtime"; filter
  chips per kind; sortable by any column; the heading never "dependencies"
  alone, it reads "Dependencies · by kind".
- State words per row: build-time "measured · from <manifest>"; runtime
  "proposed · from <artifact>" (a proposal in the E3 states until a person
  confirms it under "how it relates"), or "no deployment artifact found" /
  "runtime not surveyed" for the section as a whole.
- Publishing: build-time as today (annotations per ecosystem); runtime
  confirmed rows publish as **annotations only**, because Egeria's planned
  "deployed by" relationship types are not yet available; no word on
  screen says "lineage" (owner, 2026-10-05: a dependency, not lineage).
- Tests: a fixture with both sources yields the two kinds with correct
  counts; a repository with manifests and no artifacts shows the runtime
  state sentence, never an empty section.

## 4. Blueprints: the kind in the name, and the selector

- Rename the existing recovered diagram **"Egeria Deployment Blueprint"**
  for egeria_git (the kind in `displayName` and in the `<perspective>` slot
  of the `SolutionBlueprint` qualifiedName); generic form "<repository>
  Deployment Blueprint".
- A blueprint selector at the top of "what it's made of": one row per
  kind RE can offer, with source and state: "Egeria Deployment Blueprint ·
  recovered from <n> artifacts · <m> units · proposed"; "Egeria Build
  Blueprint · from build.gradle · <m> modules · not yet drawn"; "Egeria
  Logical Blueprint · needs your confirmation of <k> components · not yet
  drawn". A person selects which to view; "write to Egeria" is per
  blueprint and only for one with accepted nodes. Verdicts are per
  blueprint. The Build and Logical blueprints themselves are later slices;
  this slice draws the Deployment one and lists the other two honestly.
- Writing: unchanged mechanism (`SolutionBlueprint` Draft, `SolutionComponent`,
  `CollectionMembership`), the kind in the name; proof rows by GUID.

## 5. Promotion adopts the configured-only zone rule

**Owner:** "configured-only, no default zone."

- `workflows/curate.promote_to_publish_zones` uses
  `egeria_identity.configured_publish_zones()`; with nothing configured it
  writes no `ZoneMembership` and the verdict row reads "accepted · zones
  left to Egeria · everyone visible"; with a configured zone, "accepted ·
  zone <name>". `publish_zones()`'s fallback to `DEFAULT_PUBLISH_ZONES`
  must no longer be reachable from any write path; if nothing else calls
  it, remove the fallback and the constant's "where an accepted element is
  promoted to" comment.
- **Read first:** whether materialisation puts the Draft `SolutionBlueprint`
  or `SolutionComponent` into `PRIVATE_ZONE`. If it does, accept must clear
  that zone when nothing is configured (one `add_zone_membership` with an
  empty set or the documented clear call, verified on a throwaway element),
  or the element stays private; if it does not, accept is the content-status
  change alone. Record which in the implemented note.
- Tests: no zone configured → accepted blueprint and component carry no
  `ZoneMembership` and are readable by the service identity (a fake that
  records the calls); configured → exactly that zone; the old default never
  appears in any body.
- Backlog line (owner): zone configuration in the Admin panel with
  deployment-set defaults, replacing the environment variable.

## 6. "Rules" wording

**Owner:** the block must say these are DATA CLASS rules; "there are many
kinds of rules."

- `curate-bands.js` `rulesBlockShellHtml`: the label "Rules Egeria applies"
  becomes **"Data-class rules Egeria applies"**; the loading line "Reading
  the data-class rules…" stays; the no-reader sentences already say
  "data-class rules" and stay; the disclosure "RE's built-in keyword list,
  not read from Egeria (N)" becomes "RE's built-in data-class keyword list,
  not read from Egeria (N)".
- Other places the word appears on screen and could confuse, each
  qualified: the Curate scope tree's suggested rule sentence ("The lens
  names <term>: N table names contain it · make that a rule?") becomes
  "make that a scope rule?" (it is an inclusion rule for the catalog scope,
  not a data class); the stale-step sentence of §1 says "refresh rule";
  the Automate pane's schedule words do not use "rule" and stay. Grep the
  Next scripts for the word before closing; every remaining "rule" on
  screen carries its kind.
- Tests: the label strings, asserted.

## 7. Backlog, and one design question for the owner

- **RAG ingestion of code.** The ingestion step produced 51,729 chunks from
  egeria_git's code. Backlog line recorded by the coordinator. My read: it
  deserves a short design note, not only a line, because two decisions sit
  under it: whether code is ingested at all by default (the owner's
  "optional" is the minimum: a per-resource switch, off for repositories
  whose purpose is not code understanding, with the count shown before
  ingestion, "would ingest N files · M chunks estimated"), and what the
  ingestion rules are when it is on (file types, size caps, generated and
  vendored exclusions reusing the sub-resource survey's worthiness rules, a
  chunk budget per resource with the honest sentence when it is hit). The
  note is short and can wait for the demo; the switch alone is a slice of
  its own if the owner wants the count down sooner.

## Gate (egeria_git, by use)

1. The Publish band shows the survey's age before the press; "Publish to
   Egeria →" publishes without running a survey (the activity log shows no
   survey run); the proof row names `surveyed_at`; "Re-survey now →" runs
   one and the age changes.
2. The manifest table's counts match the selection; after the press the
   state column fills from proof rows; a repository with no survey is
   blocked with the sentence.
3. Dependencies read as one table with kinds and counts; the runtime rows
   say "proposed · from <artifact>" or the section says why there are none.
4. "what it's made of" shows the selector with the Deployment Blueprint
   named and the other two listed as not yet drawn.
5. Accept one component with no zone configured: the verdict row reads
   "accepted · zones left to Egeria · everyone visible" and a read-only
   lookup shows no `ZoneMembership`.
6. The Curate rules block reads "Data-class rules Egeria applies".
