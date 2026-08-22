# arch-spike — Phase 0 detector spike

Throwaway scripts for `docs/architecture-recovery-phase0-plan.md`. **Not part of the
package**: no RE integration, no registry writes, no Egeria, no Prefect, no network.
Reads a local checkout, writes JSON. A negative Phase 0 result must cost nothing to
discard (plan §2).

Ground truth lives elsewhere, deliberately —
`tests/fixtures/architecture-ground-truth/` — because the partitions outlive the spike
as regression fixtures while these scripts do not.

## Running

```bash
python3 detect.py /path/to/checkout --target NAME      # → ir/NAME.json
python3 exclusion.py /path/to/checkout --json          # census only
python3 imports.py /path/to/checkout --target NAME     # → signals/NAME-imports.json
python3 cochange.py /path/to/checkout --target NAME    # → signals/NAME-cochange.json
python3 coupling.py NAME                                # boundary_stats + candidate_boundaries (needs ir/ + signals/)
```

## Files

| File | Role |
|---|---|
| `exclusion.py` | first-party filter — runs before everything (plan §3a) |
| `ir.py` | the Architecture IR (design §5.3) + evidence records (§5.4) |
| `detectors.py` | manifest, deployment-unit, and compose detectors (§5.1) |
| `code_markers.py` | ast-grep web/CLI/TUI/scheduler markers — logical-perspective components (§5.1 code half) |
| `detect.py` | CLI: exclusion → detect → IR |
| `imports.py` | ast-grep Python import extraction → module import graph (design §5.5 signal 1, plan §0a) |
| `cochange.py` | `git log --name-only` → co-change coupling graph (design §5.5 signal 2, plan §0b) |
| `score.py` | detector IR × ground truth → component-set + file-partition scores (plan §5, §5a) |
| `coupling.py` | Task 3 — cross-boundary edge ratio for a given partition, and candidate boundaries neither the detector nor the ground truth proposed |
| `rules/` | ast-grep rules for `code_markers.py` |
| `rules-imports/` | ast-grep rule for `imports.py` — separate directory so `code_markers.py`'s `rules/*.yml` scan never sees it |

## Status

Built: exclusion, IR, manifest/Dockerfile/compose detectors, ast-grep code markers, scoring,
`imports.py`, `cochange.py`, `coupling.py`.
Not built, and deliberately out of scope for this spike: JS/TS import extraction (finding 23 —
measured, not assumed, to be under 2% of first-party files on both targets); general-purpose
graph clustering (Louvain etc. — finding 28 explains why `coupling.py` reuses the code-marker
subtree rule instead).

## Running the scorer

```bash
python3 score.py trellis                # logical GT — diagnostic only, see finding 13
python3 score.py egeria-workspaces      # deployment GT — the scoreable T1 result
python3 coupling.py trellis
python3 coupling.py egeria-workspaces
```

## Findings so far

Recorded here as they arise; they belong in the Phase 0 write-up (plan §7.4).

**1. §3a confirmed, and it is not marginal.** `egeria-workspaces` is **29% first-party**
— 4428 of 6239 tracked files are `node_modules`. `trellis` is 99.8% (3 vendored JS
libraries under `web/static/vendor/`), `egeria` is 100%. Without the exclusion pass the
largest target is three-quarters noise, and every vendored `package.json` would have
declared a component.

**2. Using `git ls-files` beats reimplementing `.gitignore`.** Tracked-only is exactly
the right filter for noise kind (b) — `.venv` and `site-packages` disappear without a
single gitignore rule being parsed, because git already knows. The vendor denylist then
only has to handle kind (a), committed vendor code.

**3. Compose files cannot be identified by filename.** The first version matched
`*compose*.y*ml` and silently missed **every solution deployment** in
`egeria-workspaces`, whose compose files are named after the solution
(`egeria-quickstart-local.yaml`, `egeria-freshstart.yaml`) with no "compose" substring
anywhere. It found only the optional add-ons — i.e. it reported the least important
tier and missed the most important. Detection is now by content (a top-level
`services:` key). Any detector keying on compose filenames will under-report exactly
the components that matter most.

**4. Dockerfile-without-manifest was the worst miss.** `PyegeriaWebHandler` — the most
substantial component in `egeria-workspaces` — went entirely unreported in the first
version because it ships no `pyproject.toml`. This is identity precedence **rung 1**
(§8.2), the strongest claim available, and it was not firing at all. A deployment unit
with a Dockerfile and first-party code is now a component; a directory of nothing but
Dockerfiles is reported as a build context instead.

**5. The pre-registered identity case initially failed, in the predicted way.** With
rung 1 firing, both `PyegeriaWebHandler` copies were found but collapsed into one
component by an unqualified slug. §8.2's rule that a deployment context *qualifies* the
slug had been implemented for manifests and not for deployment units. Now correct:
`egeria-quickstart::PyegeriaWebHandler` and `egeria-freshstart::PyegeriaWebHandler`,
matching the form §8.2 proposes and the answer pre-registered in the fixture.

**6. Manifest-only detection recovers the workspace partition and nothing below it.**
On `trellis` it finds exactly the 4 workspace members plus a frontend `package.json` —
5 components. RE's real internal structure (web service, CLI, TUI, A2A server,
surveyors, ingestion, agents) is entirely invisible, collapsed into one
`resource-explorer / Console Command`. This is the **qualified pass** outcome the plan
predicted (§6): boundaries recovered only where a manifest declares them. It is early
evidence, not a verdict — the code-marker detectors are the half that would change it,
and they are not written yet.

**7. Manifests cannot distinguish a service from a CLI.** `classify()` can only separate
"has an entry point" (`Console Command`) from "does not" (`Software Library`). RE is a
FastAPI service *and* a CLI *and* a TUI; its manifest says only that it has a script.
Confidence is set to reflect that ceiling rather than overstating it, and every IR
carries a note saying so.

**8. Scale behaves, so far.** `egeria` yields 231 Gradle modules from `settings.gradle`,
deliberately not expanded into components in this slice (plan §3, T3 — the question is
shape, not leaves). Worth noting the count differs from the 254 `include` lines counted
by grep during planning: 231 is after deduplication and comment-stripping.

**9. `container_name` is the component's name, and it is declared.** Every runtime component
the maintainer named by hand in the `egeria-workspaces` ground truth is a `container_name:`
in a compose file. Reading the service key instead — an internal handle like `apache-web`
or `kafka` — matched **2 of 16**; preferring `container_name` matches **16 of 16**. The key
is a handle; container_name is what shows up in `docker ps` and what people call the thing.
Design consequence: where a deployment declares a container name, that IS the component's
name (§8.2 says which identity *rung* to use, but not which *name*, and a unit can have
three — service key, container name, directory name).

**10. The cheap-parser instinct cost more than it saved.** `compose_services` began as a
line-wise reader, justified in its own docstring on the assumption that real compose files
carry anchors, merge keys and templating a strict parser would reject. **The assumption was
never tested and is false** — PyYAML parses all 25 compose files in `egeria-workspaces`
without error. Before that was checked, the shallow reader had accumulated three separate
failure modes, each silent: filename detection missed every solution deployment (finding 3),
first-wins missed layered base/override files, and a **column-0 comment inside the services
block** truncated the parse after 4 of 7 services. Now a real YAML parse with a targeted
re-scan for line numbers. The generalisable lesson for Phase 1: prefer the real parser, and
test the excuse for not using one before writing the excuse into a docstring.

**11. Layered compose is the norm.** These deployments split across a base file and several
overrides (`egeria-quickstart.yaml` + `-local` + `-ssl` + `-demo` + …), and the human-facing
`container_name` often lives in a different file from the service declaration. Any per-file
pass under-reports; services must be merged across every file in a deployment unit.


**12. `score.py` reuses `validate.py`'s parser rather than writing a second one, and had
to extend it slightly.** The original `parse()` only captured `type`/`files`/`identity`/
`notes` off a component's bullets; `Provenance:` (needed for the maintainer/all tier
split, README.md "Provenance") and per-component `Perspective:` were silently dropped.
Changed to capture any bullet label generically into the component dict rather than
whitelisting a fourth and fifth name — `validate.py`'s own type/files checks are
unaffected, and any future field (e.g. a Q11 sibling-annotation-style tag) is captured
for free. Re-ran `validate.py` against all three fixtures after the change; same
component/blueprint counts, same coverage percentages. `score.py` needed no ground-truth
edits to run, honours `Scope:` on both sides (same `tracked_files()`/`expand()` as
`validate.py`), and refuses to roll T2 into a pass/fail verdict — labelling it
`DIAGNOSTIC ONLY` because a `logical` ground truth cannot be scored against detectors
that read only manifests and deployment artifacts (plan §5a).

**13. First real scores — and the headline is a *granularity* mismatch, not a detection
failure.**

| | component-set | file-partition |
|---|---|---|
| **T1** `egeria-workspaces` (deployment) | 21/27 matched, recall **0.78**, precision **0.31** | N/A — 25 of 27 components own no first-party files |
| **T2** `trellis` (logical) | 2/13 all-tier, 0/11 maintainer-tier | ARI 0.08 / NMI 0.30 over 192 files — **DIAGNOSTIC ONLY**, plan §5a |

Recall 0.78 with precision 0.31 is one finding, not two: the detector emits **67**
components where ground truth has 27, and almost every extra is a *sub-service of an
optional add-on* — `airflow-apiserver`, `airflow-scheduler`, `dl-hive-metastore`,
`dl-minio`, and so on. The maintainer named each add-on as **one** component
(`airflow-marquez`); the detector enumerated its individual compose services. The six
"missed" add-ons (`dagster`, `milvus`, `mlflow`, `prefect`, `superset-compose`,
`deltalake-spark`) are the same effect from the other side: found, but only under their
service names, because (root cause, from reading `build_components()`) a directory-level
component only fires when the directory *itself* contains a Dockerfile — true for
`airflow-marquez`, `duckdb`, `unity-catalog`, false for the other six, which declare
their containers entirely inside nested compose files. So detector and human agree on
*what exists* and disagree on *how far down to go* — design doc §4.3's "how far down"
question arriving as a measurement rather than a discussion, and biting specifically at
the **add-on tier** (§8.2b), not the solution tier, which matched cleanly. Not fixed
here — a real Phase 1 gap in the deployment-unit detector, for the write-up (plan §7.4)
rather than a quiet patch to a throwaway spike.

Separately: most of the 46 "spurious" names are not really false positives so much as a
**ground-truth granularity gap** — `egeria-workspaces.md`'s own add-on section says
container names there are "not yet enumerated," so precision computed against it is not
a meaningful number until the fixture is extended to per-container detail. That would be
a fixture change (README.md rule 3: a new `egeria-workspaces-revised.md`, never an edit
to the pre-registered file), not a `score.py` change — noted so 0.31 isn't misread as a
detector defect on its own.

**14. Inside that 46, one pair is a real detector bug, not a granularity gap: the same
component is emitted twice, under two names — a reconciliation-test failure.**
`PyegeriaWebHandler` (from the Dockerfile-directory detector: has files, no container
name) and `quickstart-pyegeria-web` (from the compose detector: has the container name,
no files) are the same thing. Two detectors found it from two angles and nothing
reconciled them, so it scores as one spurious component **and** one missed one
simultaneously. **The join key is declared and unread**: the compose service carries
`build.context: ./PyegeriaWebHandler`. Merging on `build.context` would remove the
duplicate and give the compose-named component its files — making T1 **partially
file-scoreable** for the first time — and is exactly the code-versus-deployment
reconciliation plan §3 T1 item 2 exists to test. Currently that test fails.

**15. The first proposed fix for finding 14 (merge on `build.context`) was wrong, and the
regression it caused is what proved it.** Implemented as a straight merge — join, rename
to `container_name`, drop the duplicate — it dropped T1 recall from 0.78 to **0.48**
(13/27), not an improvement. Root cause: the join assumed one build context maps to one
deployed component. It does not, and not marginally — `compose-configs/egeria-quickstart`
is the build context for **7** services, `airflow-marquez`'s compose file backs **9**
containers from one image family. Even narrowing the join key to `(context, dockerfile)`
— there are 5 different Dockerfiles under the quickstart context — leaves 3 of 14 keys
still colliding: `Dockerfile-apache-web` and `Dockerfile-jupyter` are each shared by
**FreshStart reusing QuickStart's build context** (a real, previously undocumented
cross-solution build-sharing fact, not a detector artifact), and one airflow key backs
all 8 airflow containers. **No join key makes this 1:1** — build unit → deployed
component is one-to-many, the norm in compose rather than an edge case, and a
merge-based fix would have papered over real architecture instead of modelling it.
Reverted rather than patched with a same-context-collision guard, since a guard that
skips colliding joins just declines to model the common case.

**16. The actual correction: finding 14's "duplicate" was a perspective conflation, not a
bug.** `PyegeriaWebHandler` (a source directory with a Dockerfile) and
`quickstart-pyegeria-web` (a running container) are not the same component counted
twice — they are the **physical** and **deployment** perspectives (design §4.1) on the
same system, related one-to-many by `ImplementedBy` (§3.6), and §4.2 says explicitly to
**map, never merge** across perspectives. The fix that holds: tag every `Component` with
its perspective (`ir.py`, defaults `physical`; compose-service-derived components are
tagged `deployment`) and have `score.py` compare only same-perspective components against
a ground truth's declared `Perspective:` — the same rule already applied at file level
(finding 12's `Scope:` handling), now applied per component. The `logical`-perspective
(T2, diagnostic-only) comparison deliberately keeps comparing across all perspectives,
since plan §5a wants that cross-perspective number computed as a distillation baseline,
not scored.

**17. Perspective filtering's effect on T1 was bigger than expected, and the extra
recall drop is a genuine finding, not a bug to chase back to 21/27.** Precision holds
essentially flat (0.313 → 0.310), but recall drops further than the PyegeriaWebHandler
fix alone predicts — **0.78 → 0.67** (21/27 → 18/27), because `airflow-marquez`,
`duckdb` and `unity-catalog` were *also* cross-perspective coincidences: each is a
Dockerfile-derived (`physical`) component whose name happens to equal the ground
truth's deployment-perspective name for that whole add-on **bundle** — nothing in the
compose layer emits a service or container literally called `airflow-marquez`. Correctly
excluding them from the deployment comparison is the same rule, just less visible than
PyegeriaWebHandler because the name coincidence hid it.

**Resolved, not dual-tagged.** The instinct to give the add-on Dockerfile a second
`deployment` tag was checked and rejected: doing so would recover 21/27, which is exactly
why not to do it — it fits the model to the score rather than fixing the actual cause.
The real cause is a **granularity inconsistency inside the pre-registered ground truth
itself**: `egeria-workspaces.md` names `airflow-marquez` (a bundle of 9 containers) as
one component in the same document where `quickstart-egeria-main` (one container) is
also one component — two different levels of the same vocabulary in one fixture. That is
a `-revised.md` question (README.md rule 3), never something to paper over with a second
tag on the detector side. **18/27 is the honest number**; the write-up should say
deployment-perspective recall is depressed by an add-on-tier granularity gap in the
fixture, not by a detector or tagging defect.

**18. The "deployment" perspective is a *specification* perspective, not a claim about a
running system — a second correction of the same shape as finding 16, both times from
refusing to collapse things that look alike.** A repo contains no deployed container; it
contains a *description* of one — a compose service definition plus a Dockerfile — and
the compose file that would start it. Nothing is running, so writing an Area 0
`SoftwareServer` / `DeployedSoftwareComponent` / `DeployedOn` from static analysis would
assert infrastructure that was never observed running; `ContentStatus = Draft` does not
repair that, since Draft means *incomplete*, not *may not correspond to anything real*.
Area 0's `ITInfrastructure` is explicitly "hardware and base software that supports an IT
system" — actual infrastructure, evidenced by a live connector, not a checkout.

Egeria already has the right property for this distinction: `plannedDeployedImplementationType`
(`OpenMetadataProperty.java:2504`) on `SolutionComponent`, documented as *"the type of
software component that is **likely** to serve as an implementation for this solution
component"* — note "likely". So a compose service yields an Area 7 `SolutionComponent`
carrying `plannedDeployedImplementationType` for the technology, not an Area 0
infrastructure element. The compose file and Dockerfile themselves are real and are
properly Area 0 0280 assets (`YAMLFile`, `BuildInstructionFile`) — it's the *inferred
running instance* that is out of scope for this feature, not the artifacts that describe
it. Design doc §4.1a now records this as "deployment specification"; the IR/fixture token
stays `deployment` unchanged (churning it to match the prose would mean editing a
pre-registered fixture), and `validate.py`'s deployment vocabulary (`Application`,
`EventBroker`, …) is unaffected for the spike — its content survives long-term as the
technology-type string in `plannedDeployedImplementationType` rather than as an entity
type.

**19. Every ast-grep rule was verified against real parse trees, and two of the eight were
wrong — in opposite directions.** The drafts had never been run (no binary). Counts against
`resource_explorer`:

| rule | draft | verified | |
|---|---|---|---|
| `fastapi-route` | **620** | **149** | draft matched `dict.get(k, default)` |
| `scheduler-worker` | **0** | **4** | draft missed Prefect entirely |
| `cli-entry` | 6 | 6 | ok |
| `client-postgres` | 3 | 3 | ok |
| `fastapi-app` | 1 | 1 | ok |
| `textual-app` | 1 | 1 | ok |
| `client-boto3` | 0 | 0 | **correct** zero — repo has no boto3 |
| `client-kafka` | 0 | 0 | **correct** zero — repo has no kafka |

`fastapi-route` matched the *call* form `$APP.get($PATH, $$$ARGS)`. Its own comment predicted
over-matching and judged it acceptable — "e.g. a dict named `router` with a `.get` method".
Measured, that understated the damage by an order of magnitude: it matched **every two-argument
`.get()` call in Python**, one of the language's commonest idioms. The top-matching file was
`cli/main.py` (38 hits), which registers no routes at all. Routes are **decorators**; matching
`@$APP.get($$$ARGS)` finds 149 real registrations and no dict lookups.

`scheduler-worker` scored zero, which reads as "this repo has no scheduler" and is false — RE
orchestrates through Prefect (`resource_explorer/prefect/flows.py`). The draft only looked for
APScheduler *class construction*, and Prefect declares work with *decorators*. This was the rule
the earlier session deliberately omitted rather than guess at decorator syntax unverified; that
was the right call, since guessing would have produced another silent zero.

**The generalisable lessons, both cheap and both only visible by running the rules:**

- **A zero is a finding, not a pass.** It means either the technology is genuinely absent
  (boto3, kafka — correct here) or the pattern is broken (`scheduler-worker`). The two are
  *indistinguishable* without a known-positive file to check against, so every rule needs one.
- **"Over-matching is acceptable" is a claim to measure, never to assume.** A code marker must
  match the syntactic form the framework actually uses. Matching a superficially similar form
  produced a 4x-inflated count dominated entirely by false positives.

Worth noting `ast-grep` resolved from `.venv/bin/` and **not** from PATH despite a `brew install`
— which is the argument for the pip dependency (finding: commit 60a6d5f) landing in practice
rather than in principle.

---

## Phase 0 verdict: QUALIFIED PASS

**20. T2 scored, and the answer is the middle outcome plan §6 pre-defined.**

`trellis`, logical perspective, code-marker detectors wired (`code_markers.py`):

| measure | value | reading |
|---|---|---|
| file-partition **ARI** | **0.56** | good agreement on boundaries |
| file-partition **NMI** | **0.77** | good agreement on boundaries |
| files scored | **38** of 182 GT-assigned | **coverage is the problem** |
| components proposed | **4** of 11 | `web`, `cli`, `tui`, `prefect` |
| component-set F1 | 0.00 | see below — a measurement artifact |

**Where the detectors fire, they get the boundary right. They fire on 4 of 11 components.**
ARI 0.56 / NMI 0.77 is not a weak result — on the subtrees it proposes, the partition
substantially agrees with the maintainer's. But it proposes only the four subtrees that
happen to use a *framework*: FastAPI (`web`), Typer (`cli`), Textual (`tui`), Prefect
(`prefect`). `Agents`, `Core`, `RAG ingestion`, `Observability`, `Surveyors` and
`Utility scripts` have no framework marker of any kind, so no code-marker rule can see
them, and no rule that could be written would — there is nothing distinctive to match.

That is **exactly** the qualified pass described in plan §6: *"boundaries recovered only
where a manifest declares them... does not kill the feature, but changes it"*. Refined by
measurement: boundaries are recovered where a manifest declares them **or a framework
marker fires**, and the union still leaves the majority of a code-first repo invisible.

**Consequences, per plan §6's own instruction that a qualified pass changes the estimate:**

- LLM distillation (§5.2, Phase 5) is **not optional polish**. It is the only mechanism
  that can propose `Agents` or `Core`, because those boundaries are conventional rather
  than declared. Phase 5 should move earlier.
- The §5.5 validation signals (import coupling, co-change) matter more than assumed —
  they are the only *detector-side* signals that could propose an undeclared boundary.
- The Phase 1 rule-writing estimate should not rise much. More rules would not have
  helped here; the missing components have nothing to match on. Effort belongs in
  distillation and coupling, not in more markers.

**21. Component-set F1 of 0.00 is a measurement artifact, not a detection failure.**
The detector emits `web`, `cli`, `tui`, `prefect` — directory basenames. The ground truth
says `Web backend`, `CLI`, `Textual TUI`, `Prefect orchestration`. The *boundaries* agree
(ARI 0.56); only the *names* differ.

This is by design and should not be scored as error: §5.2 assigns naming to the LLM
precisely because detectors cannot produce human names. So **component-set agreement is
the wrong measure for the logical perspective** — it is the right measure for deployment,
where names are declared (`container_name`, finding 9) and it scored 16/16. Different
perspectives need different measures, which is plan §5a's rule arriving one level deeper
than it was written.

**22. `diagnostic_only` is now derived rather than hardcoded.** It was `perspective ==
"logical"`, correct while nothing emitted logical components. Once `code_markers.py` did,
the hardcode would have gone on labelling a real comparison DIAGNOSTIC ONLY forever. Now:
a comparison is a diagnostic only when no detected component carries the ground truth's
perspective. The earlier session was right to defer this until there was something to test
it against — the same judgement that made it revert the `build.context` merge.

---

## §5.5 validation signals — the two signals findings 20's Consequences section
called "more important than assumed"

**23. Python-only import extraction, and the scope decision is measured, not assumed.**
Before writing `imports.py`, both targets' `exclusion.py` census was checked by extension:
trellis is 472 first-party `.py` against 7 `.js`; `egeria-workspaces-fs` is 167 `.py`
against 6 `.js` + 1 `.ts`. Real JS/TS import syntax (`require`, dynamic `import()`,
bundler path aliases) is a materially different extraction problem for under 2% of either
target's first-party files, so it is out of scope for this slice — stated here as a finding
rather than silently narrowed. `imports.py` extracts with ast-grep (`rules-imports/
import-python.yml`, one rule matching all three Python import-statement node kinds — plan
§0(a): not `project_code_relationships` × `project_code_symbols`, which yields
`inherits_from` pairs; not grimp, which needs the dependency environment installed), then
re-parses each *matched snippet* with Python's own `ast` module rather than a hand-rolled
regex over import syntax — ast-grep does the finding, `ast` does the parsing, so relative
dots, parenthesised multi-imports, and `as` aliases are never hand-modelled. Resolution
uses source roots (every `pyproject.toml` dir, every deployment-unit dir, and the checkout
root) for absolute imports and pure dot-counting for relative ones — a documented, honest
approximation, not full Python import-system semantics.

`rules-imports/` is a **separate directory** from `rules/`, not a stylistic choice —
`code_markers.py`'s scan iterates every `.yml` in `rules/` and logs a "no MARKER_ROLES
entry" note for anything it does not recognise. Putting the import rule there would have
made every `code_markers.py` run silently slower and noisier for no reason.

**24. First run's numbers, both targets — non-zero, and cross-checked as real rather than
broken (README finding 19's rule: a zero is a finding, not a pass, and the same applies to
a suspiciously clean *non*-zero).**

| | python files | import statements matched | resolved edges | external/unresolved |
|---|---|---|---|---|
| trellis | 472 | 4045 | 1157 (2221 individual imports) | 2877 |
| egeria-workspaces | 167 | 1674 | 306 (548 individual imports) | 1933 |

Zero `ast.parse` failures on either target. The known-positive check: `imports.py` run
against `egeria-workspaces-fs` resolves every `PyegeriaWebHandler` file's internal imports
strictly *within its own copy* — not one edge crosses from `compose-configs/
egeria-quickstart/PyegeriaWebHandler/` to the `egeria-freshstart` copy or vice versa. That
is independent confirmation, from a signal that has never seen the ground truth, of finding
5/15's identity answer (two components, not one) — exactly the kind of cross-check finding
19 asks every zero (and here, every suspicious non-zero) to have.

**25. `cochange.py` — window, large-commit cap, and normalisation, all as stated, unadjusted
flags.** `--months 24` (default), `--max-files 50` applied to the **raw** `--name-only`
count before first-party filtering (so a vendor-drop or bulk-reformat commit is excluded
before it can contribute a single pair, not filtered down to a smaller "innocent" commit
first), `--no-merges` on by default. Strength is `count(a,b) / sqrt(count(a)*count(b))` —
cosine-style, not raw count, so two files each touched in half the repo's commits don't
read as "coupled" purely from churn. First run: trellis — 164 commits in the window, 120
considered (3 skipped as too large, 41 as touching <2 first-party files), 5236 pairs over
398 files. egeria-workspaces — ~950 commits in the window (moves slightly run to run as
`--since` is relative to now), ~586 considered (49 skipped as too large, ~310 as <2
first-party files), 10869 pairs over 710 files. Both non-zero, both with a plausible large-
commit-exclusion rate (2–5% of considered commits), neither run tuned after the fact.

**26. `coupling.py`'s first version had a real bug, caught only by cross-checking against a
known fact from finding 5 — reusing IR `name` as a dict key instead of `slug`.** Both
`PyegeriaWebHandler` components (quickstart and freshstart) share the *name*
`"PyegeriaWebHandler"` and differ only in `slug` (`egeria-quickstart::PyegeriaWebHandler` /
`egeria-freshstart::PyegeriaWebHandler` — finding 5's own fix). Building
`{c["name"]: c["files"] for c in components}` silently drops one of the two entries via
dict-key collision; its files then fell through to whichever *broader* directory component
(`egeria-freshstart`, the whole compose deployment) claimed them first, merging what should
have been two boundaries into one and corrupting the co-change cross-boundary count (306
fewer internal pairs before the fix). Found by comparing `coupling.py`'s own file→component
map against ground truth's for the 230 files both sides assign and seeing 93 freshstart-side
files land on the container component instead of their own. Fixed by keying on `slug`.
Generalisable lesson, same shape as finding 14: **IR `name` is a display field, not an
identity — anything doing set/dict operations across components must use `slug`.**

**27. Cross-boundary edge ratio is granularity-sensitive, and the raw numbers say so before
any interpretation is applied — reported as measured, including the part that looks like a
paradox.** trellis: the detector's own (coarse, 5-component) partition scores a
cross-boundary ratio of **0.0049** on imports and **0.0076** on co-change — near-zero. The
pre-registered ground truth's (11-component) partition, on the *same* edges, scores **0.55**
on imports and **0.64** on co-change. Read naively this looks like "the detector's partition
is what the signals agree with" — backwards. A 5-bucket partition where 4 buckets are entire
top-level packages has almost no boundaries *to* cross by construction; a near-zero ratio
here is a property of coarseness, not of correctness, and is not evidence for the coarse
partition over the fine one. This is stated as a finding rather than being fixed by
normalising for granularity, because normalising it away is exactly the kind of "make the
number look better" the task rules forbid — the raw, mildly counterintuitive number is the
honest one to report.

**28. The headline answer to Task 3's actual question — does either signal suggest a
boundary neither the detectors nor the ground truth proposed — is: at a stated,
unadjusted 0.5 cohesion bar, no; at 0.3, yes, cleanly, for exactly the components README
finding 20 named as the qualified pass's gap.**

Candidate boundaries use the *same* structural rule `code_markers.py` already uses to
attribute a marker (top-level subpackage beneath the nearest manifest root,
`code_markers._subtree_for`) — not general clustering — so a candidate here is directly
comparable to what a code marker could have proposed, never an apples-to-oranges cut.

At `--min-cohesion 0.5` (the stated default — "most of this subtree's weighted traffic
with the rest of the repo stays inside it"): **0 signal-only, 0 novel**, on both targets.
That is a real negative at that bar, reported as one rather than quietly lowered until it
wasn't.

At `--min-cohesion 0.3` on trellis — run afterward purely to see the shape, not to search
for a bar that passes, and reported alongside the 0.5 result rather than instead of it:

| subtree | import cohesion | cochange cohesion | ground truth | detector |
|---|---|---|---|---|
| `resource_explorer/surveyors` | 0.40 | 0.12 | **Surveyors** | *(none)* |
| `resource_explorer/agents` | 0.33 | 0.03 | **Agents** | *(none)* |
| `resource_explorer/ingestion` | 0.33 | 0.03 | **RAG ingestion** | *(none)* |
| `scripts/arch-spike` | — | 0.31 | **Utility scripts** | *(none)* |

Four of the six conventional, marker-less components finding 20 named
(`Agents`, `RAG ingestion`, `Surveyors`, `Utility scripts`) are exactly the subtrees import
coupling or co-change independently cluster most tightly — cohesion computed with **zero
knowledge of the ground-truth file lists**, cross-referenced against them only afterward for
labelling. `Core` and `Observability` do not appear at this bar (`Core`'s own candidate
subtree — the top-level loose `.py` files, correctly bucketed by `_subtree_for` as a distinct
group from any subpackage — measured 0.06 import cohesion, because it is a shared hub every
other subtree imports *from*, which is a plausible, not a failure, cause: a hub's own
internal cohesion is not what makes it a hub). `trellis_microflow` appears "novel" at 0.3,
which on inspection is a measurement artifact rather than a real undocumented boundary: its
own tests live in a sibling subtree bucket the GT glob (`packages/trellis-microflow/**`)
spans but the candidate-subtree rule splits, dropping the Jaccard match just under 0.5 —
noted rather than patched by lowering the match threshold, which would be tuning the number.

egeria-workspaces at 0.5 surfaces four **novel** (nobody proposed, including ground truth)
cochange-only clusters — `design-docs/`, `docs/images/`, `runtime-volumes/unity-coco/`,
one `coco-workbooks/` subdirectory — all documentation/data directories with no import
signal at all (`import_cohesion: None`, honestly reported rather than defaulted to 0), so
architecturally low-value: they say "these docs get edited together," not "this is a
component." The one genuinely load-bearing egeria-workspaces recovery is a re-confirmation,
not new news: `compose-configs/egeria-quickstart` matches ground truth's
`quickstart-pyegeria-web` at Jaccard ≥0.5 on both signals — the same fact finding 24's
known-positive check already established from the import side alone.

**Reading for the Phase 1 write-up:** this is not "import coupling and co-change solve the
qualified-pass gap" — 2 of 6 conventional components (`Core`, `Observability`) did not clear
even the lowered bar, and the 0.5 default cleared none. It is real, first evidence, at a
lower confidence than the framework markers' 0.56/0.77 ARI/NMI, that these two signals point
at the *same* conventional boundaries a maintainer named by hand and no marker rule could
ever see — which is the specific, falsifiable claim finding 20's "Phase 1 rule-writing
estimate" consequence needed and did not yet have.

---

## Review of findings 23-28 (Opus, post-verification)

**29. The headline result is stronger than it was reported, after one bug fix: 5 signal-only
boundaries, 0 novel — every boundary the coupling signals proposed is a real component.**

`coupling.py trellis --min-cohesion 0.3`, computed with **no knowledge of the ground truth**:

| candidate subtree | ground truth | detector |
|---|---|---|
| `resource_explorer/surveyors` | **Surveyors** | none |
| `resource_explorer/agents` | **Agents** | none |
| `resource_explorer/ingestion` | **RAG ingestion** | none |
| `scripts/arch-spike` | **Utility scripts** | none |
| `packages/trellis-microflow/trellis_microflow` | **trellis-microflow** | none |

Five of the six components that code markers **structurally could not see** (finding 20) are
exactly the subtrees import and co-change cohesion cluster most tightly. Precision is 5/5 —
nothing flagged that is not a real component. Only `Core` and `Observability` stay missed, and
`Core` for a structural reason worth keeping: it is a shared import *hub*, and hubs suppress
their own internal cohesion by construction.

**This changes the Phase 1 plan.** §5.5 framed these as *validation* signals — a way to score a
partition someone else proposed. They are demonstrably **proposal** signals, and they cover
precisely the gap the qualified pass identified. Promote them accordingly: they are cheaper than
LLM distillation and they got 5 of 6 without it.

**Honest caveat, and it is a real one.** At the default `min_cohesion=0.5` the result is zero;
0.3 was chosen after seeing the data. Threshold calibration is therefore an open Phase 1
question and this must not be reported as a tuned-in success. What was *not* fitted is the
identity of the recoveries: the ground-truth names were matched blind, and 5/5 precision with
zero false positives is not the shape threshold-fishing noise takes.

**30. `which_gt_component` used Jaccard, and mislabelled a correct match as novel.** A candidate
subtree is normally a *subset* of the component that owns it — `trellis-microflow/
trellis_microflow` (2 files) inside GT's `packages/trellis-microflow/**` (5 files). Jaccard
scores that 0.4, below the 0.5 bar, so it was reported as a **novel** boundary rather than a
recovered one.

This is design §8.2a's rule — *"measure containment, not similarity"* — written for the
PyegeriaWebHandler variant analysis and applying verbatim here. Symmetric measures penalise the
subset relationship that is the normal shape of this comparison, and they do it **silently, by
inflating the novel count with things that are not novel**. Switched to directional containment
(|A n B| / |A|); the novel count went 1 -> 0 and the recovery count 4 -> 5. Worth noting the
design doc already contained the fix and the code did not follow it — the same error twice, in
two places, is a signal to look for it in a third.

**31. The cross-boundary ratio is degenerate as a partition-quality metric — do not use it to
rank partitions.** Finding 26 reported the inversion honestly (detector's coarse partition
0.005, ground truth's finer partition 0.55-0.64) and declined to normalise it away, which was
the right call. But it is not merely counterintuitive: **a metric that counts the fraction of
edges crossing a boundary is minimised by having no boundaries.** A one-component partition
scores exactly 0. The detector's partition does not win on cohesion; it wins on coarseness, and
it would win by more if it were coarser still.

So the number is meaningful *within* a fixed granularity and meaningless *across* granularities,
which is the comparison it was built to make. The standard correction is a **null model** —
Newman modularity Q compares observed intra-cluster edges against those expected at random given
the degree distribution, and exists precisely to stop "one big cluster" winning. Phase 1 should
use modularity, or state the granularity constraint every time the raw ratio is quoted.

**32. The import graph independently confirms the pre-registered identity answer.** `imports.py`
finds **zero** import edges crossing between the `quickstart` and `freshstart` copies of
PyegeriaWebHandler. That is finding 5's two-components answer — the one that reordered §8.2's
identity precedence — arrived at from a signal that never saw the ground truth, the compose
files, or the container names. Independent corroboration of a design decision is rare enough to
record.

---

## Phase 1 §4.1 — coupling as proposer

**33. Newman modularity does not give a usable threshold. The Phase 1 plan said it would; the
data says otherwise.** Per-subtree contribution `Q_c = e_c/m - (deg_c/2m)^2` is **positive for 15
of 16 candidates** on trellis — in a sparse import graph almost any subtree beats chance, so
`Q > 0` admits nearly everything. Q survives as a *ranking* (it puts surveyors, ingestion and
agents on top) but not as a bar.

Recorded as a plan-level miss rather than quietly substituted: §4.1 proposed modularity
specifically to remove the hand-set cohesion bar, and it does not. The fallback the same plan
named — **relative ranking rather than an absolute threshold** — is what the data supports.

**34. What discriminates is *directional dispersion*, and it explains the Phase 0 misses.** A raw
cohesion bar rejects any component that is structurally *connective*. `Core` has 27 internal
import edges against **238 fan-in**: cohesion 0.09, obviously a real component, unreachable by any
cohesion threshold. But its fan-in is spread evenly across 14 others, and that is measurable as
normalised entropy.

Three shapes, of which only the third is genuinely not a component:

| shape | signature | example |
|---|---|---|
| **cohesive** | high internal ratio | `surveyors` (0.42) |
| **connective — library** | low cohesion, fan-**in** dispersed | `Core` (d=0.73), `Observability` (0.96) |
| **connective — orchestrator** | low cohesion, fan-**out** dispersed | `cli` (0.82), `web`, `tui` |
| **merge-candidate** | low cohesion, externals **concentrated** on one neighbour | `trellis-microflow/tests` |

Admitting on *either* direction is deliberate. An earlier cut required fan-in to exceed fan-out
and misclassified `agents`, which is dispersed both ways but slightly more outbound.

**35. Coverage 4 -> 11 of 13, which clears Phase 1's target; precision falls, which the plan
predicted.**

| | Phase 0 | §4.1 |
|---|---|---|
| GT components covered | 4 of 11 scored | **11 of 13** |
| subtrees proposed | 4 | 16 |
| rough precision | — | **~0.69** |

The five unmatched proposals are `configdata` (data, not code), `dashboard`, `github`, and two
`tests` trees. Several are defensible as components and simply are not in the ground truth;
`tests` is explicitly `unassigned_ok`. **This is exactly the precision-for-coverage trade the
Phase 1 plan named as its first risk**, now measured rather than anticipated, and the ARI floor
in §5 of that plan exists to bound it.

Two honest limits on the numbers above:

- **`Web front-end` is unreachable by this signal.** It is `web/static/**` — JavaScript SPAs —
  and `imports.py` is Python-only. Correct behaviour, not a miss to fix here.
- **The coverage figure was measured with a crude prefix match**, not `score.py`. The subtree
  `resource_explorer/` prefix-matches every nested file, so `Core` was attributed to `Surveyors`
  by majority vote and shows as missed when its subtree was in fact proposed. Real coverage is
  probably 12 of 13. **Do not quote 11/13 as final** — proper scoring runs through `score.py`
  against the pre-registered fixture, and that is the next step.

**36. The proposer produces ZERO candidates on the second target — the subtree rule assumes a
layout the estate does not always have.** `coupling.classify_subtree` was validated on trellis
(11 of 13). Run against `egeria-workspaces`, which has 306 resolved import edges and is not short
of signal, it proposes **nothing**.

Diagnosed rather than assumed (finding 19's rule): `PyegeriaWebHandler` is a **flat** module
directory — every `.py` file sits directly in it, with only `tests/` beneath. `_subtree_for`
requires at least two path parts under a package root, so a flat application has no subpackages to
partition by and the candidate set is empty. The zero is real, not an invocation error.

This is the generalisation risk the Phase 1 plan named as its second, arriving sooner than
expected and for a different reason than predicted. It is **not** a language problem — both
targets are Python. It is a *layout* problem: the boundary rule inherits directory structure from
the manifest, and a repo with no internal directory structure offers it nothing.

Two consequences for Phase 1:

- **The ≥9-components target is currently met on one repo out of two**, and single-app repos are
  common. Discovery-sufficiency cannot be claimed on trellis alone.
- **A flat repo needs a boundary source that is not the directory tree** — co-change clusters over
  individual files, or naming, or distillation. That is a different mechanism, not a tuning
  change, and it should be decided before the port rather than discovered after it.

Separately: the Java adversarial target is blocked. `egeria` has **zero** tracked `.py` files and
`imports.py` extracts Python only, so the "does this generalise beyond a well-factored Python
monorepo?" question cannot be answered with the current extractor at all.

---

**37. CORRECTION — finding 32 was wrong, and finding 36's diagnosis was wrong. Both were
artifacts of one import-resolution bug.**

`imports.py` resolved every absolute import against a single **global** source-root list, tried in
the same order regardless of which file the import appeared in. `egeria-workspaces` ships
`PyegeriaWebHandler` twice — once under `egeria-quickstart`, once under `egeria-freshstart` — and
both are source roots, both containing a file called `common_serialize.py`. So a flat sibling
import in a *quickstart* handler resolved into the *freshstart* copy.

Measured before the fix:

| | before | after |
|---|---|---|
| quickstart → quickstart | **14** | **170** |
| quickstart → freshstart | **156** | **0** |
| freshstart → freshstart | 134 | 136 |

**Finding 32 is retracted.** It claimed `imports.py` found *zero* import edges crossing between
the two copies, and offered that as independent corroboration of the pre-registered
two-components identity answer. In fact **156 edges crossed**, every one of them misresolved. The
identity answer stands on its own evidence; this particular corroboration was spurious and should
not be cited.

**Finding 36's conclusion is withdrawn.** It read the zero-candidates result as a *layout*
problem — "the subtree rule assumes a structure flat repos do not have" — and generalised that
into a design gap. The real cause was that the import graph for that repo was **89% missing**. A
flat application is not structureless; the measurement was.

**The fix**: resolve against the importing file's own nearest enclosing source root first
(`roots_for_file`). An import resolves within its own copy — that is what "sibling" means. Trellis
is essentially unaffected (1165 → 1185 edges) because it has no duplicated copies, which is also
why the bug hid: it is invisible on a repo with one copy of everything.

**38. With the graph corrected, the flat app does have internal structure — and it is the shape
the classifier is built for.** Re-running community detection on quickstart's
`PyegeriaWebHandler`:

- **75 files, 170 internal edges** (was 15 files, 14 edges)
- **4 communities, modularity Q = 0.427** — meaningful structure, not noise
- fan-in leaders: `common_serialize.py` (64), `egeria_auth.py` (42), `demo_config.py` (37),
  `demo_db.py` (25) — textbook **connective-library** signatures (finding 34)

So the genuine remaining gap is narrower than finding 36 claimed, and now has evidence behind it:
**the candidate *generator* is directory-based, and a flat directory generates no candidates even
when the graph plainly contains communities.** `_subtree_for` needs a companion that clusters the
file-level graph directly where directory structure is absent. That is a real design item — but it
is now motivated by Q = 0.427 and four visible communities, rather than by a bug.

**39. Three "design problems" this session turned out to be measurement bugs.** The
`build.context` merge regression (finding 15), the Jaccard novel-boundary mislabel (finding 30),
and now this. Each initially presented as a property of the domain and each was a defect in how
the domain was being measured. The pattern is worth carrying into Phase 1: **when a signal says
something surprising about the code, suspect the measurement before revising the model** — all
three were caught by checking a number against something already known to be true, and none by
reasoning about the design.

---

## Phase 1 §4.1 scored — targets met

**40. With coupling wired in as a proposer and agreeing proposals merged, trellis scores 12 of 13
components and ARI 0.965.**

| Phase 1 §5 target | Phase 0 | now | |
|---|---|---|---|
| components (T2) | 4 of 11 | **12 of 13** | met |
| file coverage, in scope | 21% | **87%** (165 of 190 GT-assigned) | met |
| partition accuracy, ARI | 0.56 | **0.965** (NMI 0.973) | met, floor held |

**Ten of the twelve are exact file-set matches** — `CLI`, `Textual TUI`, `RAG ingestion`,
`Agents`, `Observability`, `Prefect orchestration`, `Surveyors`, `Core`, `trellis-microflow`,
`trellis-vectorstore` all at F1 1.0. `Web backend` 0.84, `Web front-end` 0.63.

`Core` at F1 1.0 is the one worth pausing on: it was unrecoverable in Phase 0 by any mechanism
tried, and it is recovered exactly by the connective-library rule (finding 34).

The single miss is `Utility scripts` at F1 0.42, and the cause is mundane — the proposer emits
`scripts/*` where the ground truth says `scripts/**`. A non-recursive glob against a recursive
one, not a boundary disagreement.

**41. Agreement between approaches was surfacing as a duplicate instead of as confidence.** Two
approaches proposing the same file set produced two IR components and double-counted in every
score. They are now merged: type comes from whichever approach can supply one (a code marker knows
a subtree serves HTTP; coupling knows only *where* a boundary is), confidence rises with agreement
capped at 95, and every contributing approach is kept in `proposed_by` so the portfolio stays
legible (Phase 1 §4.4).

Coupling-only components deliberately keep `type = None`. Coupling locates boundaries; it does not
classify them, and inventing a type from the shape would be exactly the over-claiming §5.2 assigns
to distillation instead. 17 of 27 components currently have no type — that is honest, and it is
the concrete size of the naming-and-classification job distillation inherits.

**42. Component-set F1 remains 0.00, and it is still the wrong measure** (finding 21). The
detector emits `agents`, `surveyors`, `cli`; the ground truth says `Agents`, `Surveyors`, `CLI`.
The boundaries are identical — ARI 0.965 — and only the names differ, several of them by
capitalisation alone. **Do not read 0.00 as a failure**; read the file-partition numbers, which is
what §5a of the plan says to do for the logical perspective.

**43. Two measurement scripts in a row collided on non-unique component names.** A components-by-
name dict silently dropped one of two `PyegeriaWebHandler` entries in `coupling.py`, and while
scoring this result the same mistake reproduced in a throwaway matcher, where two components named
`cli` (one in resource-explorer, one in egeria-advisor) overwrote each other and made `CLI` look
like a 0.02 miss. **Component names are not unique; slugs are.** Key by slug, always — the design
says as much in §8.2 and it has now cost two debugging detours.

**44. The `scripts` glob was not a glob bug — it was the residue rule, and fixing it properly is a
trade rather than a clean win.**

`_subtree_glob` emits `X/*` for a one-segment bucket because files under `X/Y` belong to the
separate bucket `X/Y`. That is correct while `X/Y` is itself proposed, and it is exactly why
`Core` got `resource_explorer/*` and matched exactly — `agents/`, `cli/` and the rest really are
their own components.

It breaks when the nested bucket is **not** proposed. `scripts/arch-spike` is a 20-file bucket no
signal proposes (the spike's modules barely import one another), so `scripts/*` claimed 7 files
and 20 were owned by nobody. The rule that fixes it is the residue rule stated properly: **a
component owns everything beneath it that nothing else claims.**

| | before | after |
|---|---|---|
| components matched (F1≥0.5) | 12 of 13 | **13 of 13** |
| file coverage in scope | 87% | **97%** (184 of 190) |
| ARI / NMI | 0.965 / 0.973 | **0.969 / 0.977** |
| `Utility scripts` | 0.42 | **exact** |
| `Core` | **exact** | **0.51** |

**`Core` got worse, and that is the interesting part.** Adoption gives `resource_explorer` the
unproposed `github/`, `configdata/` and `dashboard/` buckets — but the ground truth's `Core` is
explicitly *"the 19 top-level modules"*, so those do not belong to it.

The two ground-truth components genuinely disagree about residue ownership, and both readings are
deliberate: `Utility scripts` is written `scripts/**` (a bag of scripts, and arch-spike is more
scripts), while `Core` is written `resource_explorer/*.py` (top-level modules, and `github/` is a
distinct concern). **No single mechanical rule reproduces both**, because the difference is a
human judgement about what a component is *for*, not about where its files sit.

Kept the adoption rule and recorded the cost rather than special-casing it. Special-casing would
be tuning to the fixture, which is the one thing the ground truth exists to prevent. Two things
follow for Phase 1:

- **Residue ownership is a disambiguation worth asking a human** (portfolio note §5a) — it is
  cheap to answer, impossible to derive, and it changes the partition.
- The orphan buckets adoption surfaced — `github/`, `configdata/`, `dashboard/` — are files the
  ground truth never assigned to anything. Whether they are unowned or belong somewhere is a real
  open question about the fixture, and belongs in a `-revised.md` rather than being decided by a
  detector.

## Phase 1 §4.6 — the PORTED pipeline scored (docs/Backlog.md, "never been scored")

**45. The port reproduces the spike exactly on the trellis target — component set, counts, and
file-partition all match.** Ran `ArchDetectSurveyor`/`ArchCouplingSurveyor` (`resource_explorer/
surveyors/sub_surveyors/arch_recovery_{detect,coupling}.py`, commit `45b8be3`) directly against
`/Users/dwolfson/localGit/egeria-v6/trellis` with an isolated throwaway SQLite registry, read the
result back out of `project_analysis_findings`/`project_analysis_metrics` (the real
`persist_ir()`/registry path, not a re-implementation), and fed it into `score.py` via a small
loader shim (`load_ir` monkeypatch — no changes to `score.py` itself).

| | spike (`ir/trellis.json`) | port |
|---|---|---|
| components (raw) | 27 (22 logical, 5 physical) | 27 (22 logical, 5 physical) |
| component-set (logical, exact-name) | 0/11 matched, F1 0.00 | 0/11 matched, F1 0.00 |
| file-partition ARI / NMI (maintainer) | 0.9778 / 0.978 | 0.9778 / 0.978 |
| file-partition ARI / NMI (all) | 0.9784 / 0.9804 | 0.9784 / 0.9804 |

Bit-for-bit identical. (Component-set F1 0.00 is not a regression — finding 42 already
established this is a naming-case artifact of `score.py`'s exact-string match against
`Agents`/`agents` etc.; read the file-partition row instead, per plan §5a.) The two components
that land on the same `scope_locator` in the port (`web`, `tui` — one proposal from the code-marker
pass, one from coupling, same file glob both times) confirm the documented known difference
behaves exactly as described: the port discovers the agreement at read time instead of an
IR-level merge, does **not** apply the spike's +10-confidence-per-agreement boost, but also does
**not** lose or corrupt either proposal. Harmless here.

**46. The port has a severe, previously-unknown regression on the deployment perspective —
T1 recall drops from 18/27 (67%) to 2/27 (7%) — and it is NOT the known merge difference.**
Same method against `/Users/dwolfson/localGit/egeria-v6/egeria-workspaces-fs`:

| | spike (`ir/egeria-workspaces.json`) | port |
|---|---|---|
| components (raw, all perspectives) | 70 (58 deployment, 10 physical, 2 logical) | 70 (58 deployment, 10 physical, 2 logical) |
| T1 component-set (deployment), matched | **18/27** (recall 0.67, target ≥18/27) | **2/27** (recall 0.07) |
| detected_count after scoping | 58 | **10** |

The **detectors themselves are faithful** — raw output is 70 components in both, same
perspective breakdown, same per-container `Component` records (`detectors.py`'s compose-service
loop still emits one `Component` per `container_name`, exactly as its own comment describes:
*"egeria-workspaces ships PyegeriaWebHandler twice... collapsing them is the failure the revised
precedence chain exists to prevent"*). The regression is introduced one layer downstream, in
`persist.py`'s `scope_locator_for()`:

```python
ctx = component.identity.deployment_context
if ctx:
    return ctx
return component.identity.value or component.slug
```

For a compose-service component, `identity = Identity("deployment-unit", name, unit)` —
`value` is the container name (unique per container, exactly what `detectors.py` computed it
to be), but `deployment_context` (`ctx`) is the **compose file's directory** (`unit`), shared by
every container declared in that compose file. Because fileless components have no `files[0]` to
fall back on first, `scope_locator_for` returns `ctx`, not `value` — so all 9 containers under
`compose-configs/egeria-quickstart` (and all 9 under `airflow-marquez`, all 6 under
`deltalake-spark`, etc.) get **the same `scope_locator`**. Confirmed directly against the
registry (not inferred): 58 raw `component` finding rows collapse onto only **10** distinct
`scope_locator`s (one per compose unit directory) — e.g.
`compose-configs/optional-associated-runtimes/apache-atlas` carries 6 different container names
(`zookeeper`, `hadoop-namenode`, `hadoop-datanode`, `atlas-hive-metastore`, `hive-server`,
`apache-atlas`) under one scope. Every reader of this table — including
`_architecture_recovery_results()`, the results view's own reader — then does `max(comp_rows,
key=surveyed_at)` to pick "the" component per scope; since all rows from one run share a
`surveyed_at`, `max` keeps whichever was inserted first and **silently discards the other 5-8
container identities and their evidence** at that scope. This is a real defect in the shipped
code (`resource_explorer/surveyors/arch_recovery/persist.py`), not an artifact of how this
scoring session read the data back — any consumer of `project_analysis_findings` for
`kind="architecture_recovery"` on a compose-heavy repo sees the same collapse.

This is a different bug from the one the backlog item named as "known" (finding-41-style
IR-level merge/confidence-boost, confirmed harmless in finding 45 above). The known difference
costs nothing; this one costs the entire deployment-perspective result. `persist.py`'s own
docstring for `scope_locator_for` states the intent correctly ("Preferred source is the
component's own `files` glob... Only a files-less component... falls back to its declared
deployment context") but the fallback chosen for the files-less case (`deployment_context`
before `value`) is backwards for exactly the shape `detectors.py` was written to produce:
many same-context, differently-identified fileless components. Swapping the fallback order
(`value` before `deployment_context`, or qualifying `deployment_context` with `value` the way
`detectors.py`'s own `_slug()` already does for the Dockerfile-unit case at line ~354) would fix
it, but per the task's ground rules this write-up does not modify `arch_recovery/` — it only
scores and reports.

**Route taken:** the ported `ArchDetectSurveyor`/`ArchCouplingSurveyor` classes were called
directly (real `persist_ir()`/registry write-and-read-back path) against local checkouts, not
through the full `SurveyOrchestrator`/Survey Definition/Egeria plumbing (registry/project setup
for that was judged disproportionate to a scoring task — no Egeria writes, no network, per the
task's hard rules). This is a weaker claim than "the deployed survey steps agree" but a stronger
one than "the modules agree in isolation," since it exercises the actual registry schema and the
actual read-back grouping logic where the finding-46 defect lives.

**47. The residue rule surfaced misplaced code, not just unassigned files — and the dependency
data overturned the maintainer's first read of it.**

Finding 44's orphans (`github/`, `configdata/`, `dashboard/`) were put to the maintainer. The
answer was not "here is the component that owns them" but **"the code is in the wrong place"** —
`github/` described as *"utilities to fetch git data and statistics, so they are effectively used
by surveyors — you could move that folder"*, `dashboard/` as *"might not be properly organized"*.

That is the feature doing the job it exists for: not describing the architecture, but finding
where the code disagrees with the intended one.

**Then the measurement contradicted the instinct.** `resource_explorer.github` is imported by
**six** subsystems — `web/routes` (2 files), `surveyors/sub_surveyors` (2), `ingestion` (2), `cli`
(2), `surveyors` (1), `agents` (1). Surveyors are 3 of 11 importers, not the owner. Moving
`github/` under `surveyors/` would create upward dependencies from `web/`, `ingestion/`, `cli/`
and `agents/` **into** `surveyors/` — worse coupling, not better.

It matches its measured signature precisely: fan-in 22, dispersion 0.90 — the
**connective-library** shape (finding 34). A utility imported evenly by many components is not
misplaced; it is a library.

**Both halves are the point.** A human knows things no detector does (that `configdata` is package
config, that `dashboard` is presentation support). A detector knows things no human recalls (that
six subsystems import `github`, not one). The check ran in both directions and changed the answer
in one of them, which is the strongest argument yet for
`approach-portfolio-model.md` §5a's bidirectional channel over a one-way RFA.

Recorded in `tests/fixtures/architecture-ground-truth/trellis-revised.md`, with the residue rule
decided: **adopt by default, ask when not obvious** — the asking surface being a file tree with
checkboxes, since the answer is naturally a selection rather than a boolean.

---

## Phase 1 §4.6 — portfolio backfill (approach-portfolio-model.md §8)

**48. Findings 1-47 backfilled into `project_analysis_findings` as 21 `kind='approach_run'` rows
(4 approaches x 3 targets, several targets carrying more than one row where an approach was tried,
regressed, and fixed) plus 15 `kind='repo_characteristics'` rows, in a throwaway local SQLite
registry** (no shared Postgres, no Egeria, no network — `ProjectRegistry(db_path=...)` pointed at
a scratch file, per the same pattern finding 45 used for scoring the port). Every row's
`detail_json` carries a `source` key citing the finding number(s) it comes from, so the backfill
is traceable back to this document rather than being a second, independent record of the same
facts. No new table — both kinds reuse `project_analysis_findings` exactly as portfolio note §3
specifies.

**One gotcha worth recording on its own: `ProjectRegistry._normalize_slug()` replaces `-` with
`_`.** `egeria-workspaces` is stored (and must be queried back) as `egeria_workspaces`. Trivial
once known, silent if not — a query for the literal target name returns nothing and looks like
missing data rather than a slug mismatch. Filed here because it is exactly finding 43's shape
(non-unique/non-normalized keys costing a debugging detour) arriving a third time, this time in
`registry.py` itself rather than the spike.

**49. Portfolio note §3's `unverified`-vs-`no_signal` rule was not a hypothetical — the backfill
data needed it for real, more than once.** Two clean cases:

- `coupling` on `egeria`: cannot run at all (zero tracked `.py` files, `imports.py` is
  Python-only, finding 36). No known-positive file can exist, so this is `unverified`, not
  `no_signal` — a zero here would be indistinguishable from "the tool is broken."
- `coupling` on `egeria-workspaces`, inside `PyegeriaWebHandler`: the candidate *generator*
  proposes zero boundaries even on the corrected graph, but the corrected graph has a known
  positive right next to the zero — Q=0.427, four visible communities (finding 38). That
  known-positive is exactly what makes this a meaningful `no_signal` (a real capability gap in the
  directory-based candidate rule) rather than an unverified zero. Without finding 38's measurement,
  this cell would have had to be recorded as `unverified` too.

Both `manifest` and `code_markers` on `egeria` are `unverified` for the same structural reason as
`coupling`: `code_markers` targets Python-framework syntax egeria has none of, and `manifest` (231
Gradle modules) was never scored against anything, because T3's ground truth deliberately stayed
at shape level. `deployment` on `egeria` is `unverified` for a different, more mundane reason — it
was simply never run in the spike; no finding claims otherwise.

**50. The 4x3 grid is qualitatively full (12 of 12 cells have at least one row) but only half is a
scored outcome — 6 of 12 cells are `unverified`, all six of them on `egeria` or half of
`egeria-workspaces`.** Laid out (best non-regression label and confidence per cell):

| target | manifest | deployment | code_markers | coupling |
|---|---|---|---|---|
| `trellis` | partial (40) | no_signal (90) | partial (75) | recovered (95) |
| `egeria-workspaces` | unverified (20) | partial (65) | unverified (15) | no_signal (70) |
| `egeria` | unverified (30) | unverified (10) | unverified (5) | unverified (0) |

`egeria`'s entire row is `unverified` — not because every approach failed, but because none of the
four was ever scored against anything on that target (T3's ground truth stayed at shape level by
design, and two of the four approaches structurally cannot run there at all). That is a very
different thing from "the portfolio doesn't work on Java repos," and the table as recorded cannot
be misread that way, which is the entire point of keeping `unverified` distinct from `no_signal`.

**51. Checking portfolio note §4's selection-rule shape against this data: it does not fall out,
and the one place it looks like it does is the weakest evidence in the table, not the strongest.**

§4 gives two worked examples:

> *"No deployment artifacts, >80% Python, single package -> markers recover ~35% of components,
> coupling ~80%. Run coupling first."*

`trellis` matches two of those three characteristics (no deployment artifacts: confirmed by direct
search this session; 99.8% Python) but not the third — it is a 4-package uv workspace, not a
single package. On the two-of-three match: `code_markers` recovers 4 of 11 GT components = **36%**,
strikingly close to the quoted "~35%". `coupling`'s *final* number is 13/13 = 100%, but that figure
is the merged detectors-plus-coupling result (finding 41), not coupling in isolation — coupling's
own unique, marker-blind contribution is roughly 8 of 13 (~62%), not the ~80% quoted. So half of
this example lines up and half does not, on the only repo that even partially matches its
precondition — and the half that lines up is worth real suspicion: `approach-portfolio-model.md`
is dated 2026-08-20, *after* Phase 0's findings existed, so a design note quoting "~35%" for
"markers recover" on a profile trellis matches may simply be restating Phase 0's own trellis
number back at itself rather than an independent prediction the backfill then confirmed. That is
not evidence for the rule; it is circularity risk stated plainly.

> *"Compose-rich, low first-party ratio -> deployment detectors recover ~100% of declared
> containers. Markers add nothing; skip them."*

`egeria-workspaces` matches this profile exactly — 25 compose files, 29% first-party. Measured
`deployment` recall against it is **18/27 = 67%**, not "~100%". This is not a near-miss shaded by
methodology; it is the T1 exit-criteria number Phase 1 explicitly held as a floor, arrived at after
three rounds of detector fixes (findings 9-17) and one real regression along the way (finding 15).
The one target that matches this rule's precondition **disconfirms its prediction outright.**

`egeria` cannot test either rule. It matches neither example's precondition (100% Java, not
Python; deployment artifacts unmeasured), and two of the four approaches cannot even execute on
it. It is not silent evidence for or against §4 — it is a target the modest lookup, as specified,
was never going to have anything to say about, which is itself informative: §4's two example
profiles are both implicitly Python-flavoured, and the estate's most language-diverse target falls
through both of them.

**Verdict: at n=3 targets, §4's selection rules do not fall out of this data, and the one example
that looks confirmed is the one built on the smallest, most circular evidence in the set — the
other is actively contradicted by the one repo positioned to test it.** This is the honest reading
plan §4.6 and portfolio note §8 asked for, not a reluctant one: three repos is not a sample a
lookup table can be built from, and pretending otherwise here would be exactly the "prove the
model prematurely" failure §8 warns against. What would change this verdict is not more analysis
of these three repos — the four approaches are now about as well-characterised on `trellis` and
`egeria-workspaces` as 47+ findings can make them — but **more repos**, each contributing one more
data point per cell, ideally covering the profile combinations §4's own examples describe
(single-package Python, compose-heavy-non-Python, and everything unlike both). `Backlog.md`'s
standing 8-10-repo re-run item is already the right-sized next step; nothing about this backfill
argues for a different one.

**Do not build the portfolio manager, selection lookup, or retirement rule yet.** Portfolio note §6
already names the risk this avoids — an evaluation harness that outgrows the results it ranks —
and at n=3, with two of three targets' grids half `unverified`, there is nothing yet to rank.

---

**53. Java extraction works, and the adversarial target is scoreable for the first time.** `egeria`
— 231 Gradle modules, 4,515 tracked `.java` files, **zero** `.py` — previously could not be run at
all, which was recorded as `unverified` rather than `no_signal` precisely because a zero from an
extractor that cannot read the language is not evidence about the repo.

Verified independently: 30,552 import statements → **48,894 distinct edges**, with a known-positive
checked first (`ProfileReportResponse.java` visibly imports
`OpenMetadataConformanceProfileResults`; the edge appears). Per finding 19, that check is what makes
the aggregate trustworthy rather than a possible silent zero.

Resolution mirrors finding 37's fix: a duplicate fully-qualified name across two Gradle modules
resolves within the importing file's own module first.

**54. Two-thirds of Java edges are wildcard imports, and a wildcard edge means "might use", not
"does use".** Measured: 32,480 of 48,894 edges (66%) come from `import a.b.*;`, with single files
fanning out to hundreds of targets — `OpenMetadataPropertyConverterBase.java` reaches **704**,
`OpenMetadataType.java` 674.

This is a real over-approximation specific to Java, and it plausibly explains the shape of the
result: of 321 classified subtrees only **4** came out `cohesive` against **156** `connective`.
Heavy dispersed fan-in and fan-out from wildcard imports into shared framework packages is exactly
what the dispersion signal reads as "connective", whether or not the code genuinely is.

**So Java coupling numbers carry a caveat Python's do not.** Python edges are exact per-symbol;
Java's are two-thirds "might". Worth tagging `kind: wildcard` on the edge (done) so a consumer can
down-weight or exclude them, and worth deciding deliberately before Java results are compared with
Python ones.

**55. The Gradle granularity collapse and the flat-repo zero are the SAME bug, from opposite
directions.** On `egeria`, coupling proposed roughly one component per Gradle module's `src/main`
and `src/test` — it never drills into the `org/odpi/openmetadata/...` hierarchy inside a module.

`_subtree_for` is a **fixed-depth directory rule**: the top-level subpackage two levels below a
package root. That is tuned to Python's conventional layout, and it degenerates whenever a repo's
structure differs:

| repo shape | package root | what the rule yields |
|---|---|---|
| flat app (`PyegeriaWebHandler`) | the app dir | **nothing** — no subdirectories to find (finding 36/37) |
| Gradle (`egeria`) | each of 231 modules | **`src/main` / `src/test`** — never the package tree below |
| Python monorepo (`trellis`) | each workspace member | the right answer, which is why it looked correct |

Both failures were previously read as separate problems — one a "flat repo" limitation, one a
"Java scale" observation. They are one cause: **the candidate generator assumes a directory depth
rather than deriving one.** That reframes the flat-repo work from a special case into the general
fix, and gives it a second target to be validated against instead of one.

**56. A single depth rule does not fit the three repo shapes — measured, not assumed. The answer is
a hierarchy, which the target model already has.**

Finding 55 established that `_subtree_for`'s fixed depth is one bug with two faces. The obvious fix
— generate candidates at *every* depth, then prune parent/child pairs by a relative test — was
tried and **does not work**. Candidates at all depths (directories holding ≥2 source files):

| target | all depths | after a parent-vs-children prune | verdict |
|---|---|---|---|
| `trellis` | 35 | **4** | far too aggressive — the shipped fixed-depth rule gets 13/13 here |
| `egeria-workspaces` | 6 | **3** | non-zero at last (the flat case yields candidates), but thin |
| `egeria` | 2,434 | **619** | still unusable at 231 Gradle modules |

The prune kept a parent when its own edges — those not internal to any single child — matched or
beat its largest child's. That is a defensible test and it fails in *both* directions at once: too
coarse on a Python monorepo, nowhere near coarse enough on Gradle. Trying a different constant
would move the failure, not remove it, which is the same trap modularity set in finding 33.

**Why no single depth can work.** The three shapes disagree about what a component *is*, and each
is right about itself: a Python workspace member is a component, a flat app is one component, and a
Gradle module contains a package tree several levels deep. A rule that outputs one depth must be
wrong for at least two of them.

**The answer already exists in the target model.** Design §3.3a: components nest via
`SolutionComposition`, and Egeria models that natively — a `SolutionComponent` can contain
`SolutionComponent`s. So the generator should stop choosing a depth and **emit the hierarchy**,
tagged with depth and parent, letting the consumer take the level it needs.

That also lines up with `approach-portfolio-model.md` §2's sufficiency reframe, which is the
stronger argument: **Discovery wants coarse and Analysis wants fine**, so "which depth?" was never a
question with one answer. It is a question about what the stage will do with the partition.

**Not implemented.** It changes the scoring model too — the pre-registered ground truth is flat, so
a hierarchical proposal cannot be scored against it without deciding how a nested proposal counts
against a flat expectation. That decision should be made deliberately, not slipped in. Recorded here
so the next attempt starts from the hierarchy rather than re-running the depth experiment.

**What was salvaged.** The flat case is no longer structurally invisible: at multiple depths
`egeria-workspaces` yields 6 candidates where the fixed rule yielded zero. That half of finding 55
has a working mechanism whenever the hierarchy question is settled.

---

## Six new repo shapes — three findings, two of them defects

Dan added ~20 repos. Six were run through the shipped steps, chosen to include cases that *should*
fail rather than only ones that should work.

| repo | shape | components | depth profile |
|---|---|---|---|
| `sqlglot` | single Python package | 11 | `{0:5, 1:6}` |
| `openlineage` | multi-language | 34 | `{0:18, 1:7, 2:4, 3:4, 4:1}` |
| `unitycatalog` | Java/Scala multi-module | 16 | `{0:4, 1:1, 2:10, 3:1}` |
| `unitycatalog_rs` | **Rust** | **0** | — |
| `ryoma` | Python app | 31 | `{0:1, 1:5, 2:4, 3:21}` |
| `workshops` | **non-code materials** | **45** | `{0:43, 1:2}` |

**57. `unverified` is not wired, so an unsupported language is a silent zero — the exact failure the
label exists to prevent.** `unitycatalog_rs` is Rust. There is no Rust extractor, so coupling cannot
see anything; `imports.py` handles Python and Java only. It returned **0 components and recorded no
outcome at all** — verified, zero component scopes persisted.

That is indistinguishable from *"this repo genuinely has no components"*, which is precisely the
distinction `step_outcome.py` was built for: **a zero from an extractor that cannot read the
language is not evidence about the repo.** The vocabulary exists, the constructor enforces the rule,
and the detect/coupling steps never emit `unverified` for an unreadable language. First real test
outside the cases it was designed against, and it failed.

Fix is small — the steps should emit `StepOutcome(UNVERIFIED, cause="no_supported_source")` when the
first-party set contains no extractable language — but it needs doing before any corpus sweep, or
every Rust, Go and C# repo will read as architecture-free.

**58. A repo with no architecture got 45 components, 44 of them from deployment artifacts.**
`workshops` is OpenLineage's tutorial materials. It proposed `e3-airflow`, `airflow-scheduler`,
`airflow-worker`, `flower` and 41 more — because workshop examples *contain compose files*, and the
deployment detector treats every service in every compose file as a component.

The detector cannot tell **"this repo deploys Airflow"** from **"this repo contains a tutorial that
shows you how to deploy Airflow."** Both are compose services declaring container names. Precision
on a non-software repo is near zero, and nothing in the output signals low confidence — the
components look exactly like real ones.

This is the mirror of finding 57: one repo returns nothing when it should say "cannot tell", the
other returns 45 things when it should say "nothing here". Neither failure is visible from the
output alone.

**59. Depth profiles do not cluster, which settles finding 56's open question in favour of the
hierarchy.** Across six repos the distributions share no shape: `sqlglot` is flat
(`{0:5, 1:6}`), `ryoma` is depth-3-heavy (21 of 31), `unitycatalog` is depth-2-heavy (10 of 16),
`workshops` is depth-0 (43 of 45), `openlineage` spreads across five levels.

Finding 56 left two candidate answers: **detect the repo's shape and pick a depth rule**, or **emit
the hierarchy and let the consumer choose a level**. If shapes clustered into a few families the
first would be tractable. They do not — six repos gave six profiles. That is evidence for the
hierarchy, and it is now grounded in more than the three repos finding 56 had.

**On the sample.** These six can settle shape questions because those need variety, not ground
truth. They **cannot** advance `Backlog.md`'s measurement re-check, which needs *pre-registered*
ground truth per target — and writing that is the actual cost. Two or three of these with genuinely
different shapes would be worth more than all twenty.

**60. Finding 58's answer is to read the repo's README — the signal exists, is already in hand, and
is not a path heuristic.**

The maintainer's observation: *"the README says the intent is for a tutorial, which means it is not
an architecture worth surveying."* That is the disambiguation, and it settles the design.

**The signal needs no new resource.** `repo_arch_detect` already holds `zipball_root` — the source
view — so the README is on disk while the step runs. Nothing needs fetching; it needs reading.

**This is §5.2 step 0 and §8.2c, not a new mechanism.** The design already says distillation should
read the repo's own architecture and deployment documentation before proposing boundaries, because
prose is detector-invisible and LLM-readable. `ENVIRONMENT_DIVERGENCE.md` was the first instance
(§8.2c); a README declaring "this is a workshop" is the same shape, and it answers a question no
structural signal can: **is this repo software, or materials *about* software?**

**Why the cheap alternatives are worse:**

- **Path heuristics misfire in both directions.** `examples/`, `tutorial/`, `workshops/` — a real
  product can live under any of them, and tutorial material frequently does not. It would trade a
  false-positive problem for a differently-shaped one.
- **Keyword-matching the README misfires too.** "Workshop" and "example" appear in the READMEs of
  real software. The judgement is about *intent*, which is what distillation is for.

**A deterministic signal worth pairing with it**, since it needs no LLM and no README: `workshops`
produced 45 components of which **44 came from deployment artifacts and essentially none from
source**. A repo whose entire proposed architecture comes from compose files, with no first-party
code behind any of it, is structurally suspicious — a real deployment usually ships alongside the
thing being deployed. That is measurable now and would flag the case cheaply even where no README
states intent.

**And the human stays in it.** Per the maintainer: *"might require a human to triage."* Agreed, and
the portfolio note §5a's rules apply — non-blocking, skippable, with the consequence stated. The
right shape is: read the README, propose an answer with confidence, and ask only when unsure. The
question *"is this repo software, or a tutorial about software?"* takes a human two seconds and no
detector can answer it.

**Not implemented.** It depends on distillation, which is not built, and finding 58's cost is
precision on non-software repos rather than a broken result on real ones. Recorded so the next
attempt starts from the README rather than from a path list.
