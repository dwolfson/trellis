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

---

**61. The revised fixture was prose nothing read — and consuming it shows ARI is now the wrong
headline measure.**

`trellis-revised.md` had recorded, over two days, the maintainer's decisions on residue ownership,
three directories of misplaced code, and the component hierarchy. **No tool read any of it.** Same
defect as a guard writing a field no consumer reads: a decision filed is not a decision used.

`score.py` now applies `{target}-revised.md` as a read-time delta over the base fixture — additional
globs for existing components, wholly new components, and parent/child links. The base file is never
mutated, so pre-registration holds. Two parser bugs surfaced doing it: `- **Sub-components:**`
followed by an indented list captured **nothing** (continuation bullets were hardcoded to `files`),
and a prose heading — *"Sub-structure — which components can be nested at all"* — matched the
section rule `"component" in title` and became a phantom component.

**Applying a correction the maintainer endorsed made ARI worse**, and that is the finding:

| | base fixture | revised |
|---|---|---|
| strict exact containment | 10/13 | 10/13 |
| **ARI** | **0.9785** | **0.9259** |

Nothing got worse. The revision assigns `configdata` and `github` to `Core`, and `dashboard` to
`Web backend` — and the detector proposes each of those as a **component in its own right**:

| ground-truth component | detector nodes *inside* it |
|---|---|
| `Core` (37 files) | `configdata`, `github` |
| `Web backend` (26 files) | `dashboard` |

So the corrected fixture is *coarser* exactly where the detector is *finer*. **ARI reads that as
disagreement**, because it compares two flat partitions and has no notion of one refining the other.

**Per §2a that is precisely not an error.** A node inside a matched component is a refinement.
ARI cannot express that, so it now measures the wrong thing — the same way component-set-by-name did
(finding 21), and for the same underlying reason: **a measure that predates a design decision will
quietly contradict it.**

**Consequence: containment becomes the headline, ARI becomes a projected-level diagnostic.** ARI
still means something once both sides are flattened to one declared level, and every historical
number stays comparable there. It should not be quoted as a top-line score on a hierarchy.

**62. A parent defined only by its children has no file set, so file-based scoring cannot see it.**
`Web application` is the maintainer's parent over `Web backend` and `Web front-end`. It owns no
files directly — its extent is the union of its children, 39 files. No detector node matches that
union exactly; the closest is the `web` code-marker node at Jaccard **0.73**.

That is not a scoring bug, it is a modelling consequence: **a component can be real and still have
no files of its own.** Egeria models it fine (`SolutionComposition`, §3.3a), and containment can
score it by unioning children — but any measure that starts from "the files this component owns"
will silently skip it, which is how a genuine component becomes invisible rather than wrong.

**63. Findings 54, 57 and the `web/static` case are one constraint — and co-change already sees
what imports structurally cannot.**

An import edge **cannot cross a language**. `index.html` will never import `projects.py`. So a
component whose parts are in different languages has a seam import cohesion is incapable of seeing,
and adding a JavaScript extractor would not help, because the edge does not exist in either
language's syntax. That is not a gap in tooling; it is what an import is.

Tested on trellis across `web/routes` (Python) ↔ `web/static` (JS/HTML/CSS):

| | pairs |
|---|---|
| within-zone co-change | 9 |
| **cross-language co-change** | **18** |

The invisible seam is **twice as visible** to co-change as the coupling within either side, and the
pairs are meaningful — `projects.py ↔ index.html`, `feedback.py ↔ admin-feedback.html`,
`discovery.py ↔ index.html`. Backend route and the page it serves, changing together. This is
exactly the boundary the maintainer's `web application` parent describes, and it is the boundary
whose loss caused the 10/13 → 9/13 movement.

**We compute co-change and do not use it.** `coupling.propose()` takes `import_edges` only —
co-change is calculated, attached as a supporting metric, and never reaches shape classification.
Blind in precisely the place where it is the only working signal.

Extractor coverage of first-party code files, which decides how much this matters per repo:
`egeria` 99%, `trellis` 96%, **`egeria-workspaces` 65%** (57 `.html`, 28 `.sh`, 7 `.js` unseen). A
single-language repo barely notices; a polyglot one is a third invisible, and polyglot repos are
where components most often span languages.

Written up as design §4.1d. **Not implemented** — `propose()` would need co-change edges weighted
separately from import edges rather than pooled, since pooling lets a noisy non-directional signal
dilute a precise directional one. And the result is n=1 seam: a repo whose commits are "update
everything" would show co-change everywhere and discriminate nothing.

**64. Co-change bridges the seam — and the "regression" it appeared to cause was two measurement
bugs stacked.**

`propose()` now takes co-change edges, weighted **separately** from imports per §4.1d. The design is
narrow on purpose: co-change acts as a **rescue** that fires only when a subtree has *zero* import
signal — the literal "structurally invisible to imports" case, not merely low cohesion — and yields
a new shape `connective-seam` capped at confidence 40, never `connective-library` or
`connective-orchestrator`, because those claims need a direction co-change does not have. It can
find a seam it cannot characterise.

**The success criterion was met**: `web/static` stopped being absorbed as residue. It and
`web/routes` are now sibling nodes under `web` — the maintainer's "web application, two
substitutable sub-components" model, recovered from a signal that crosses languages.

**But the reported headline was 6/11 strict containment, called a real regression. It was not.**
Two separate measurement defects, both found by chasing it:

**(a) A resolution gap — same family as finding 37, different mechanism.** `scripts/arch-spike` is
neither a manifest directory nor a deployment unit, so it was **no source root at all** and *zero*
of its sibling imports resolved, though the files plainly import each other. Downstream that reads
as "no import signal" — indistinguishable from a genuine cross-language seam — so the co-change
rescue fired on it and broke a ground-truth match having nothing to do with language.

Fixed on a principle rather than a special case: **a script directory is its own resolution root; a
package directory is not.** Python puts a script's directory on `sys.path[0]`, so `import sibling`
works between loose scripts; inside a package it does not, since py3 removed implicit relative
imports. `__init__.py` *is* that distinction, so it is what the check tests. Restored 13
intra-directory edges. (Finding 37 was *two roots and the wrong one won*; this is *no root at all*.)

**(b) The headline measure implemented half its own specification.** §2a: a component is matched by
"an exact node, **or** a set of children whose union equals it". `strict_containment_score` checked
only exact single-node equality, so every **refinement** counted as a miss — the exact failure §2a
exists to prevent.

| | containment |
|---|---|
| as reported | 6/11 |
| + script-dir resolution | 6/11 *(cause changed, not outcome)* |
| + §2a's union rule | **8/11** |

**That is the third metric in this project with the same defect** — after component-set-by-name
(finding 21) and ARI (finding 61). Each was a measure that silently contradicted a design decision
it predated, and each time the contradiction presented as a regression in the work rather than a
fault in the measure. Worth stating as a rule: **when a change that should help makes a number
worse, check whether the number still encodes the design.**

---

**65. Use the OWNERS' declared architecture as ground truth — and do not mistake an LLM's
architecture for the owners'.**

The maintainer's proposal, and it is better than deriving fixtures by hand: use the architecture a
project **publishes about itself**. Milvus declares one at `milvus.io/docs/architecture_overview.md`
— four layers (Access, Coordinator, Worker Nodes, Storage) with named components.

**Why this is strictly better than a hand-derived fixture:**

- **Inherently pre-registered.** Written by people who have never heard of Resource Explorer, years
  before our detector existed. The contamination problem this project has been carefully managing —
  fixtures written before runs, provenance marked, T2 caveated — simply does not arise. You cannot
  influence a document that already exists.
- **Authoritative rather than inferred.** A hand-derived fixture is one reader's inference about
  code they do not own. This is the designers' own statement of intent.
- **Declared as *logical*** — the perspective where our detector is weakest and every open question
  lives.
- **Scales past one person's time.** Finding published architecture docs is cheap; deriving them
  per-repo is not.

### The trap, demonstrated

The maintainer also supplied an LLM-generated logical architecture of Milvus, complete with a
component→directory mapping — apparently doing the one piece of remaining work (mapping declared
components to file globs) for free.

**Checked against `milvus-io/milvus` HEAD, five of its thirteen paths do not exist:**

| claimed | reality |
|---|---|
| `proxy`, `coordinator`, `rootcoord`, `datacoord`, `datanode`, `core`, `storage`, `metastore` | exist |
| `querycoord` | is `querycoordv2` |
| `querynode` | is `querynodev2` |
| `indexcoord` | **gone** |
| `indexnode` | **gone** |
| `mq` | **gone** — now `streamingcoord` / `streamingnode` |

It also *omits* `streamingnode`/`streamingcoord`, which the official docs list as "Streaming Node"
and the repo confirms. And the two sources disagree structurally: the official page describes **one**
Coordinator ("single active component, the brain of Milvus"); the LLM describes **four** separate
coords. **The LLM described Milvus 2.2/2.3.** The repo agrees with the official docs, not with it.

**Why this matters beyond one stale answer.** The output is plausible, internally consistent,
well-structured, and wrong in a way no amount of reading it would reveal — only checking it against
the repo did. Had it been adopted as ground truth, our detector would have been scored against a
version of Milvus that no longer exists, and every mismatch would have been recorded as a detector
failure.

**So an LLM is an APPROACH, not a source of truth** — subject to the same outcome record and
retirement rule as coupling or code markers (`approach-portfolio-model.md` §3, §6), and exactly the
"second opinion whose value is disagreeing with the first" that §5a describes. Scoring one model's
inference against another's measures agreement, not correctness, and two models trained on
overlapping data can share both.

**The division of labour this suggests:** the owners' published doc is the ground truth; an LLM is a
useful *candidate mapper* from declared components to directories; and **the mapping must be verified
against the repo**, which is cheap — one directory listing settled it here.

---

**66. The same LLM, re-prompted for "most recent", got it right — which is the argument for
verification, not the argument against the LLM.**

Told the answer was stale, the model produced a second architecture that self-corrects along exactly
the axis finding 65 identified: coordinators consolidated into `MixCoord`, `IndexNode` folded into
`DataNode`, streaming decoupled into `StreamingNode`, Woodpecker as a diskless WAL option.

**Checked against HEAD by two directory listings, it is 9 of 10 correct:**

| claimed | reality |
|---|---|
| `internal/proxy`, `internal/coordinator`, `internal/core`, `internal/datanode`, `internal/querynodev2`, `internal/streamingnode` | exist |
| `internal/distributed/mixcoord`, `internal/distributed/streamingnode` | exist |
| `pkg/streaming` | exists |
| `internal/mq` | **absent — it is `pkg/mq`** |

The negative claims verify too: no `indexnode`, no `indexcoord`, no unversioned `querycoord`. And it
now agrees with the official docs on the structural question — one coordinator, not four.

**Three things follow, all of which sharpen finding 65 rather than reversing it.**

1. **The residual error is a different kind.** Not a hallucinated component but a *misplaced layer*:
   `mq` is real, in `pkg/` not `internal/`. The same table row cites `pkg/streaming` correctly. So
   even a mapping that is right about every component can be wrong about where components live — and
   locating components is precisely what a scope locator does (§6.0). A component-level answer that
   is 100% correct can still yield glob-level ground truth that is not.

2. **The model had the right answer available and produced the stale one by default.** Nothing about
   the first response signalled low confidence. The only thing that changed was the prompt. An LLM
   proposer is therefore *unstable across prompt phrasing* in a way that does not show up in its
   output — which is the whole reason it cannot be the fixed thing others are measured against, and
   is fine as an approach whose output is verified.

3. **Verification is cheap enough that there is no excuse.** Two `contents/` API calls settled both
   rounds. Any pipeline that accepts an LLM component→directory mapping should resolve every path
   against the tree and report unresolvable ones, rather than silently carrying them into a score
   where they present as detector misses.

**Where this method stops.** Structural claims — does this path exist, is this directory still here —
verify for free. Semantic claims — "active-standby", "absorbing the legacy IndexNode role", "stateless"
— do not, and neither the official doc nor the repo listing settles them. The owners' published
architecture is ground truth for *what the components are*; the repo is ground truth for *where they
are*; and the LLM is a fast candidate mapper between the two whose every claim of the second kind
must be resolved before use. Nothing here promotes it past that.

---

**67. Three lessons from the Milvus exercise — and one of them is a new signal, not a new practice.**

The maintainer drew three lessons. They are distinct, and only two are about validation; the third is
a capability. All three are now design doc §5.5a.

**(a) Always look for documentation — including documentation outside the repo.** §5.2 step 0 already
reads in-repo docs, and Milvus shows that is not enough: the authoritative logical architecture lives
at `milvus.io`, not in `milvus-io/milvus`. The repo's own `docs/` holds a README, `design-docs/`,
`agent_guides/` and `archive/` — but not the front-door architecture page. Step 0 needs an outward
hop from README links or manifest homepage.

**(b) The version of the doc and the version of the code both matter — and the correlation is
mechanical.** Verified here: `commits?path={p}&per_page=1` dates any path, and for a deleted path
that date is effectively its removal.

| path cited by the stale description | last commit |
|---|---|
| `internal/indexcoord` | 2023-01-06 |
| `internal/querynode` | 2023-04-11 |
| `internal/mq` | 2024-06-25 |
| `internal/indexnode` | 2025-03-13 |
| *omitted:* `internal/streamingnode` | 2026-08-13 |
| *omitted:* `internal/distributed/mixcoord` | 2026-08-20 |

**Vintage is bounded above by the newest dead path cited; blind spot is bounded below by the churn of
live paths omitted.** That dated the description at ~17 months stale from four API calls, without
reading any Go. It applies to a maintainer's doc, to an LLM's proposal, and to our own recovered
blueprints equally.

**(c) Documentation health is an architectural signal in its own right.** Not what the docs say —
whether they exist, and whether they are kept current. Milvus: `docs/` last touched 2026-08-21,
`internal/` 2026-08-22. A one-day lag, plus a `docs/archive/` that is itself maintained — they retire
stale docs rather than leaving them to mislead, which is a stronger marker than merely having docs.

This is Discovery-tier by rule 17's test (two commit-date lookups, gates the expensive tiers), and it
is the measurable half of the triage judgement finding 58 needed a human for: *is there an
architecture here worth recovering?* It should be reported as dated evidence (§5.4), **not** turned
into a ranking — a maintained doc site can coexist with rotting in-repo docs, and a small stable
library may document lightly on purpose.

---

**68. Scanned twelve repos for architecture docs. The docs are almost never in the repo — and the
naive doc-health metric false-negatives on Kubernetes.**

Finding 67 turned three lessons into design §5.5a. This tested two of them against a real corpus:
`odpi/egeria` (T3), `odpi/egeria-workspaces` (T1), `milvus-io/milvus`, `apache/airflow`,
`kubernetes/kubernetes`, `grafana/grafana`, `prometheus/prometheus`, `apache/kafka`,
`elastic/elasticsearch`, `pola-rs/polars`, `ray-project/ray`, `redis/redis`.

### (a) In-repo architecture docs are the exception, not the rule

| observation | count |
|---|---|
| `ARCHITECTURE.md` (or similar) at repo root | **0 of 12** |
| architecture docs findable in-repo by name | **2 of 12** — `milvus/docs/design-docs`, `prometheus/documentation/internal_architecture.md` |
| declares a `homepage` in GitHub metadata | **11 of 12** |
| README links to an architecture page off-site | 4 of 12 |
| **has a separate, actively-maintained docs repo** | **5 of 5 checked** |

`kubernetes/website`, `odpi/egeria-docs`, `milvus-io/milvus-docs`, `prometheus/docs`,
`redis/redis-doc` all exist; the first four were pushed within the last two days.

**§5.2 step 0, which reads in-repo docs, would find architecture in 2 of 12 cases.** The outward hop
is not an enhancement — without it the best description of the system is missed almost every time.
This is now the primary justification for §5.5a(a), replacing the single Milvus data point.

### (b) The tombstone: doc-lag is confounded by doc *relocation*

The naive metric — compare commit recency of `docs/` against code — scores Kubernetes at **1412 days
of untouched documentation** against code touched 2 days ago. Read at face value that is an
abandoned-documentation signal on one of the best-maintained projects in existence.

The truth is the opposite. `kubernetes/kubernetes/docs/` contains exactly two entries:

```
.gitignore  OWNERS
```

It is a **tombstone**. The docs moved to `kubernetes/website`, pushed today.

**So doc health cannot be measured until you know where the docs live** — §5.5a(a) and §5.5a(c) are
*coupled*, not independent backlog items. Measuring (c) without doing (a) first produces exactly the
wrong answer on exactly the projects that most deserve a good one.

This is the same bug family as findings 30/44/51 in a new costume: **a proxy that quietly stopped
encoding the thing it was a proxy for.** `docs/` mtime proxies for "is the documentation maintained"
only while the documentation is still in `docs/`. Same shape as the name-matching scorer that
predated the identity rules, and caught the same way — by asking whether a surprising number could
possibly be true.

**A tombstone is detectable and is itself a positive signal.** A docs directory holding only
`OWNERS`/`.gitignore`/`README` stubs means deliberate relocation, which is curation — the same class
of marker as Milvus's maintained `docs/archive/` and Egeria's `saved/`. Projects that abandon docs
leave them rotting in place; projects that move them leave a marker.

### (c) The best ground truth is a sibling docs repo, which means it is *in git*

`milvus-io/milvus-docs` carries `site/en/reference/architecture/` — eight pages including
`architecture_overview.md`, `four_layers.md`, `main_components.md`, `streaming_service.md`. Not a
rendered site: **markdown under version control**.

That closes the timestamp-correlation question §5.5a(b) left open. Both sides are git, so a document
can be dated *two independent ways* — by its own commit history, and by the last-commit dates of the
paths it cites — and the two can be cross-checked. No heuristic dating needed.

### (d) Ground-truth candidates, ranked by what the scan actually found

1. **`milvus-io/milvus`** — verified end to end. Eight architecture pages in git, Go/C++ (so coupling
   correctly reports `unverified`), current within a day.
2. **`kubernetes/kubernetes`** — `content/en/docs/concepts/architecture/` in `kubernetes/website`;
   canonical component names (`kube-apiserver`, `kubelet`, `kube-scheduler`) map cleanly onto `cmd/`.
   Large, so also a scale test.
3. **`prometheus/prometheus`** — `documentation/internal_architecture.md` is **in-repo**, and the repo
   is small (281 MB). The cheapest possible first fixture.
4. **`odpi/egeria` (our T3)** — **a negative result worth recording.** Of 15 architecture hits in
   `odpi/egeria-docs`, most are under `saved/` (archived) or are dojo-tutorial SVGs. There is no
   current, authoritative logical-architecture page of the kind Milvus publishes. Our own flagship
   target is the weakest ground-truth source in the corpus — which is worth knowing before anyone
   treats a poor T3 score as a detector failure.

**Recipe, for reuse** (5000 req/hr authenticated, whole scan cost ~60 calls):
`GET /repos/{o}/{r}` for `homepage`; `GET /repos/{o}/{r}/contents/` for root and doc dirs;
`GET /repos/{o}/{r}/readme` for off-site links; `GET /search/code?q=repo:{docs_repo}+architecture+in:path`
for the pages themselves; `GET /repos/{o}/{r}/commits?path={p}&per_page=1` for every date.

---

**69. First score against ground truth we did not write: 0 of 11 on Prometheus. The cross-language
limit is far wider than "coupling reports `unverified`".**

`prometheus.md` was pre-registered from the owners' own `documentation/internal_architecture.md`
(commit `9039f9a`, before any detector ran). Eleven logical components, 1205 of 1668 tracked files.
Then the pipeline ran.

| stage | result |
|---|---|
| detectors | **4 components**, all npm packages under `web/ui/` |
| ast-grep code markers | **0** — *stated here as "rules are Python/Java"; that was wrong, see finding 94: the code-marker rules are **Python only**, and Python/Java/Go describes the separate `rules-imports/` set* |
| imports | **0 edges** — `0 python files, 0 java files` |
| co-change | **18219 pairs over 1030 files** — the only signal that crossed |
| **score** | **0/11**, precision 0.00, recall 0.00, ARI 0.0 |

### The correction

The Backlog predicted Milvus/Prometheus would be fine except that "Go/C++ — coupling correctly
reports `unverified`". **That was wrong, and understated the problem by a lot.** It is not coupling
alone: *three of the four proposers* are Python/Java/npm-only. On a Go repo the component-proposing
stack produces nothing, and co-change — the language-agnostic one — is a *validator*, not a proposer.
The correct outcome label for this run is **`unverified`**, and it should be reached because the
extractor set does not cover Go, not because a threshold was missed.

### Why manifests found nothing, specifically

Prometheus has six `go.mod` files, and **not one corresponds to a ground-truth component**: the root
module covers the entire architecture, and the rest are peripheral (`compliance/`, `internal/tools/`,
`documentation/examples/`, a tooling module nested under `web/ui/`).

**For a single-module Go repo, manifest-based identity is structurally blind — one `go.mod` spans the
whole architecture.** The identity precedence ladder (§8.2) has no rung that fires. Meanwhile the
owners' eleven components map essentially 1:1 onto **Go package directories** (`config/`,
`discovery/`, `scrape/`, `promql/`, `rules/`, `notifier/`, `tsdb/`, `storage/remote/`). The missing
capability is not "a Go rule for ast-grep" — it is *reading Go package structure at all*.

This is the same shape as finding 44's `build.context` lesson from the other direction: there, one
build unit mapped to many components; here, one module maps to **all** components. Manifest → component
is not a function in either direction.

### The near-miss, which the §2a union rule correctly declined

The 4 detected components are not junk. They are real npm packages inside `web/ui/`, and the ground
truth folds all of them into one component, **Web UI and API**. §2a's union rule checks whether
refinements *union to* the ground-truth file set:

- detector's 4 components: **325 files**, every one inside `web/**` — containment holds
- GT `Web UI and API`: **380 files** = `web/ui/` (344) + **`web/*.go` (38)**

The union misses the 38 Go files, so the rule declines and scores 0. **That is correct behaviour**,
and the reason is exact: **the ground-truth component is bilingual, and the detector recovered
precisely the half written in a language it supports.** The API server is Go; the UI is TypeScript;
the owners call them one component. Nothing demonstrates the language seam more cleanly.

### The scoring gap this exposes

Recovering 325 of 380 files of a component scores **identically to recovering nothing**. §2a fixed
"finding more structure must not score worse"; this is its neighbour — *finding most of a component
must not score the same as finding none of it*. The `partial` label already exists in
`step_outcome.py` for exactly this state and the scorer does not emit it. Worth fixing before the
8–10 repo re-check, or that run will report a wall of zeros that hides real near-misses.

### What this exercise bought

The first genuinely external test. Three of the four existing fixtures are ours, and every prior
number was measured against a partition someone here wrote. This one was written by strangers in
2018, and it found a whole-language blind spot that four repos of our own never surfaced — because
all four are Python, Java and JavaScript.

---

**70. Go support: Prometheus goes 0/11 → 11/11. Two of the four changes were in the measuring
instrument, not the detector.**

Finding 69 left two HIGH items. This is the first: read Go package structure.

| change | what |
|---|---|
| `rules-imports/import-go.yml` | matches `import_spec` — one node per import, verified against a real parse tree before use (finding 19 discipline): 6 matches on a file with plain, parenthesised, aliased and blank-identifier forms, where `import_declaration` gave 2 |
| `imports.py` | `go_module_index` / `resolve_go_package` / `_build_go_edges` — Go resolution is the *simplest* of the three languages, because an import path is absolute and module-qualified: no per-file search path (Python), no global type index (Java) |
| `detectors.py` | `go_subsystems()` — the missing **proposer** |
| `score.py` | a name-collision fix, see below |

**Result on Prometheus, against ground truth we did not write:**

| measure | before | after |
|---|---|---|
| strict containment (headline) | **0/11** | **11/11** |
| ARI | 0.0 | **0.9936** |
| NMI | 0.0 | **0.9894** |
| files scanned for imports | 0 | 727 Go files, 6541 imports, 1736 first-party resolved |

Verified independently rather than trusted: **10 exact file-set nodes** (`cmd/prometheus`, `config`,
`discovery`, `scrape`, `storage`, `tsdb`, `promql`, `rules`, `notifier`, `web`) plus **one union of
refinements** (`Remote storage` = `remote` + `prometheusremotewrite` + `azuread` + testdata).

### The proposer rule, and why it is not fitted to Prometheus

**A Go component is the top-level directory of a module**, with two carve-outs: `cmd/` recurses one
level (each `cmd/X` is a separate binary by convention), and files directly at a module root are
skipped (they are the module's own package — the same "workspace root is a container, not a
component" rule the npm detector already applies). Nested modules win over enclosing ones.

That is Go's own layout convention, and crucially **it is what the import graph respects**: a Go
import names a package *by directory path*, so directory boundaries *are* dependency boundaries.
Contrast Python, where a package boundary and a directory boundary are only loosely related.

### Edge weighting: a Go import names a package, not a file

Elsewhere weight means "how many symbols cross this edge". A Go import names a whole package, so each
fanned-out file edge carries `w = 1/len(targets)`. Without it a 40-file package would outweigh a
2-file package twentyfold on file count alone — and since *every* Go import is package-level, the
distortion would be universal rather than occasional. Sanity check: aggregated to top-level
directories the fractions sum back to whole numbers (`tsdb -> model` 136.0, `storage -> tsdb` 36.0),
and the shape is recognisably Prometheus.

### The measuring instrument was wrong twice

**(a) The scorer silently discarded 30 of 173 components.** `score.py` built its file map as
`{c["name"]: c["files"]}`. Names are **not unique** — the Go subsystem proposer and the coupling
subtree proposer both name a component after the directory, so `config` collided with `config`, and
the dict comprehension kept only the last. On Prometheus that dropped 30 components, *including
every Go component whose glob was the correct one*: the ground truth's `Configuration` (224 files)
was being compared against a component named `config` that expanded to **6**.

The failure presented as **three ground-truth components the detector had in fact recovered exactly**
— 8/11 where the truth was 11/11. Slugs are unique by construction (173/173); names are 143/173.
Same family as findings 12/24/51: **one identifier serving two purposes, failing silently as missing
data rather than as an error.**

**(b) `storage/*.go` does not mean what `git ls-files` says it means.** `git ls-files 'storage/*.go'`
returns **65** files — git pathspec `*` crosses `/`. `validate.expand`, using glob semantics, returns
**20**. Twenty is the fixture's intent (files directly in `storage/`, with `storage/remote/` its own
component), so the ground truth is right and an earlier hand-count in the fixture's drafting notes
was wrong. Worth stating because a glob that means two different things depending on who expands it
is precisely the recurring bug this project keeps finding.

### Regression check — the reason to trust the jump

The scorer change touches **every** target, so all three prior fixtures were re-scored under both
keyings:

| target | old key | new key |
|---|---|---|
| `trellis` | 8/11 | **8/11** |
| `egeria-workspaces` (T1) | 18/27 | **18/27** — the pre-registered target still holds |
| `egeria` | 0/0 | 0/0 |

Only `trellis`'s ARI moved (0.4235 → 0.4142), and it moved *because* 3 more files are now assigned
(234 vs 231) — the same collision fix recovering data. A slightly lower ARI over more covered files
is the honest trade, not a regression.

### What this does NOT fix — stated plainly

1. **Precision is bad.** 173 components proposed against 11 declared. Recall is perfect; the
   coupling proposer contributes 146 untyped (`?`) components. §2a says finding more structure must
   not score *worse*, and it does not — but "173 components" is not a usable answer for a human, and
   distillation (§5.2, Phase 5) is now the binding constraint rather than detection.
2. **Type inference is noisy.** `promql`, `util` and `documentation` are typed `Console Command`
   because *some* `main.go` exists beneath them. The `has_main` heuristic is too weak, and its
   confidence is set to 45 for that reason.
3. **Go package-level import cohesion is structurally ~0**, because *files in the same Go package
   never import each other* — an import is only ever cross-package. The small nonzero values
   (`promql` 0.0397) come entirely from external `_test` packages importing their own package.
   `coupling.py`'s `import_cohesion` is therefore not meaningful at Go package granularity and would
   need recursive rollup subtrees to be. Not fixed; the proposer does not depend on it.
4. **None of this is in the package yet.** These changes are in `scripts/arch-spike/` only.
   `resource_explorer/surveyors/arch_recovery/` carries its own copies of `imports.py`,
   `detectors.py` and `coupling.py`, and the ported implementation still has no Go support and still
   has never been scored.

---

**71. Ported into the package, and the ported implementation scored for the first time: also 11/11.**

Finding 70 left Go support in `scripts/arch-spike/` only. It is now in
`resource_explorer/surveyors/arch_recovery/` — `import-go.yml`, the Go block in `imports.py`, and
`go_subsystems()` plus its wiring in `detectors.py`, applied as edits rather than file copies so the
package's own divergence (relative imports, `from . import exclusion`) survived.

**This closes a standing backlog item: "the ported implementation has never been scored."** Running
the package's own `detectors.build_components` + `coupling.propose` against the Prometheus checkout
and scoring the result against the pre-registered fixture:

| | spike | **package** |
|---|---|---|
| components | 173 (23 Go + 146 coupling + 4 manifest) | **173** (identical) |
| strict containment | 11/11 | **11/11** |
| ARI / NMI | 0.9936 / 0.9894 | **0.9936 / 0.9894** |
| Go files / edges / resolved | 727 / 17063 / 1736 | **727 / 17063 / 1736** |

Identical on every measure, which is the result a port should produce and the first time it has been
demonstrated rather than assumed.

**The name-collision bug was scorer-only.** Having found it in `score.py`, the obvious worry was that
the package carried the same latent assumption. It does not — `projection.py` uses
`by_slug = {c.slug: c ...}` and `persist.py` uses `slug_to_scope = {c.slug: ...}`. There is no
name-keyed dict anywhere in `arch_recovery/`. The defect lived only in the measuring instrument,
which is consistent with where it came from: `score.py` is spike-era code that predates slugs being
load-bearing.

**Nine regression tests added** (`tests/test_arch_recovery_detectors.py`), following §4.5's rule that
every finding that was a bug becomes a test — the three `go_subsystems` rules (top-level directories,
`cmd/` recursing one level, module root skipped), nested-module precedence, the no-`go.mod` case, and
five on resolution: package fan-out, **total edge weight of exactly 1.0 per import** however many
files the package holds, stdlib/third-party counted external rather than as edges, and alias/blank
import forms preserved. Full suite: **1678 passed, 10 skipped**.

---

**72. Milvus, the second owner-published fixture: 3/5 exact — and the other two are 575/576 and
259/260, each defeated by a single `OWNERS` file.**

`milvus.md` was pre-registered from Milvus's own docs (commit `97d9194`) before any run. It is a
**deliberately harder shape** than Prometheus: five components mapping **one-to-many** onto scattered
directories (`Coordinator` alone spans six, across `internal/` and `internal/distributed/`), so every
component can only match as a *union of refinements*, never as an exact node.

### First run exposed the hardcoded `cmd/` rule

Finding 70's proposer descended one level past `cmd/` only. Milvus's root module has top-level
`internal/`, `pkg/`, `cmd/`, `client/`, `tests/` — so it emitted **`internal -> internal/**`: one
component containing the entire architecture.** (`pkg/`, `client/` and `tests/` escaped only because
each carries its own `go.mod`.)

**Replaced with Go semantics rather than a convention list:** *a directory is a package only if it
holds `.go` files directly; one holding only subdirectories is a path segment, not a unit of code.*
The component root is the first directory down from the module root that is itself a package.

| directory | direct `.go` | verdict |
|---|---|---|
| `internal/` | 0 | container — descend |
| `internal/distributed/` | 0 | container — descend |
| `internal/proxy/` | 139 | **package — component** |
| `internal/coordinator/` | 9 | **package — component** |
| Prometheus `cmd/` | 0 | container — descend |
| Prometheus `config/` | 6 | **package — component** |

This **subsumes the hardcoded carve-out entirely** — Prometheus's `cmd/prometheus` and `cmd/promtool`
now fall out for free — and it descends *arbitrarily deep*, which Milvus needs:
`internal/distributed/proxy` is two container levels down, and a fixed one-level rule would have
merged every component's distributed wrapper into a single `internal/distributed` blob.

**Prometheus regression: 11/11 and ARI 0.9936, unchanged.** Milvus's ARI moved **0.0 → 0.5273**,
NMI **0.0 → 0.7703**, on the same 3/5 containment.

### The two misses are one metadata file each

| component | ground truth | recovered by union | missing |
|---|---|---|---|
| `Coordinator` | 576 files | **575** | `internal/streamingcoord/OWNERS` |
| `Streaming Node` | 260 files | **259** | `internal/streamingnode/OWNERS` |

Root cause, verified: `internal/streamingcoord` and `internal/streamingnode` hold **0 direct `.go`
files but one `OWNERS` file each**. The proposer correctly descends past them as containers, which
orphans that file. `internal/proxy` and `internal/datanode` *do* hold direct `.go` files, so they are
components and their own `OWNERS`/`README.md` ride along inside `dir/**` — which is why those three
matched exactly.

**Strict containment is behaving correctly and should not be loosened.** 575 ≠ 576, and a measure that
rounds is worse than one that is strict. The defect is that the scorer has **no way to say
"575 of 576"** — it reports the same 0 it would report for recovering nothing.

### `partial` is now doubly evidenced, from two independent repos

Finding 69 raised this on Prometheus (`Web UI and API`: 325 of 380 files, the bilingual component
whose Go half was invisible). Milvus raises it twice more, and far more sharply — **99.83% and 99.62%
recovery scoring identical to zero**. `step_outcome.py` has defined `partial` for exactly this state
since the outcome vocabulary landed, and the scorer has never emitted it.

Two different causes, same missing expression: an unsupported language (Prometheus) and an orphaned
metadata file (Milvus). That is the signature of a **measurement gap rather than a detector gap**, and
it is the same lesson as findings 61 and 71 — the instrument, not the thing being measured.

**Precision remains the real problem**: 608 components proposed against 5 declared, 409 of them
untyped from the coupling proposer. Recall is essentially perfect on both owner-published fixtures.
Distillation (§5.2, Phase 5) is the binding constraint, not detection.

---

**73. Partial coverage is now reported — and on its first run it found a ground-truth component that
is unmatchable by construction.**

Findings 69 and 72 established that the scorer could not say "575 of 576": a component recovered to
99.8% reported the same `0` as one not recovered at all. Implemented, with three deliberate
constraints.

**(a) Reported, never folded into the headline.** `strict containment: 3/5` is unchanged and stays
the number of record. Partial cover prints beneath it, labelled *REPORTED, not counted above*.
575 ≠ 576, and a measure that rounds is worse than one that is strict — the point was never to make
the number go up.

**(b) No threshold.** "Partial" is simply `0 < coverage < 1`. Inventing a cut-off ("≥90% counts")
would repeat the mistake §5.5 avoided when Newman modularity was rejected as a threshold: **a
reported fraction beats an invented cut-off.**

**(c) Overclaim is reported separately**, because two failure modes were previously indistinguishable
— *we found less than the component* versus *we found a blob that merged it with something else*. A
detector node that overlaps a component but spills outside it cannot help cover it, so it is counted
and named rather than silently ignored.

### What it revealed immediately

**Milvus** — headline unchanged at 3/5:

```
partial (REPORTED, not counted above): 2 component(s) covered 834/836 files (99.8%)
  Coordinator:    575/576 (99.8%) from 46 node(s) — missing 1: internal/streamingcoord/OWNERS
  Streaming Node: 259/260 (99.6%) from 47 node(s) — missing 1: internal/streamingnode/OWNERS
```

**Prometheus** — 11/11, no partial line. Nothing to report is itself the right output.

**Trellis — the surprise.** Its three long-standing "misses" were never misses:

| component | actual |
|---|---|
| `Web backend` | **25/26 (96.2%)** — missing exactly `web/app.py` |
| `Web front-end` | **10/13 (76.9%)** — missing three files |
| `Core` | **15/38 (39.5%)** — genuinely partial |

### The finding inside the finding

`Web front-end`'s three missing files are `web/static/vendor/{marked,plotly,svg-pan-zoom}.min.js`.
Confirmed against `exclusion.scan()`: **all three are excluded as vendored, so they are not
first-party and the detector never sees them.**

**That component cannot be matched by any detector, ever.** The ground truth claims files that
`exclusion.py` removes before detection begins — a fixture/exclusion contradiction that was
completely invisible while the result was a bare "miss", and that has been sitting in `trellis.md`
since the fixture was written.

> **CORRECTED by finding 74 — read that before acting on this.** The conclusion above is wrong.
> `trellis.md` was *not* contradictory: it already carried an
> `## Excluded — not first-party` section naming `web/static/vendor/**` exactly. The fixture was
> right; the **scorer** never read that section. No fixture note was needed.

Two of the three are also arguably *detector* findings worth chasing: one file (`web/app.py`) and one
vendor-rule disagreement are very different from "the detector failed on Web front-end", which is all
anyone could previously have said.

---

**74. The fixture was right and the scorer was wrong — again. `trellis` 8/11 → 9/11.**

Finding 73 concluded that `trellis.md`'s `Web front-end` was unmatchable by construction, because its
glob `web/static/**` claims three vendored `.min.js` files that `exclusion.py` removes before
detection. The recommendation was to record the contradiction in a revision file.

**There was no contradiction.** `trellis.md` has carried this since it was written:

```
## Excluded — not first-party
- `packages/resource-explorer/resource_explorer/web/static/vendor/**`
```

The maintainer excluded the vendor tree from the start and said so in the fixture's own vocabulary.
`validate.py` has always parsed the section — it is in the parse dict and reported in the summary
line ("3 excluded" on `milvus.md`). **`score.py` never referenced it once.**

So the two sides were expanded against **different file universes**: ground truth over every tracked
file, the detector over first-party files only, since `exclusion.py` runs before detection. A
ground-truth component spanning an excluded subdirectory could therefore never be matched by
anything.

**Fix:** apply the fixture's `Excluded` globs to `tracked`, immediately after the `Scope:` narrowing
and for the same reason — both are scope declarations by the fixture author, and both must narrow
*both* sides. One place, four lines.

| target | before | after |
|---|---|---|
| **`trellis`** | 8/11 | **9/11** — `Web front-end` matches exactly |
| `prometheus` | 11/11 | 11/11 |
| `milvus` | 3/5 | 3/5 |
| `egeria-workspaces` | 18/27 | 18/27 |

**Three things worth keeping.**

1. **This is the third time a "detector failure" has turned out to live in the measuring
   instrument** — after ARI silently contradicting §2a (finding 61), and the name-keyed component
   dict discarding 30 of 173 components (finding 70). The pattern is specific enough to act on:
   *when the detector looks wrong on a component, check what universe each side was expanded over
   before believing it.*

2. **Partial reporting is what made it findable at all.** As a bare "miss", `Web front-end` was
   indistinguishable from a component the detector had no idea about, and it sat that way for weeks.
   As "10 of 13, missing these three files", the cause was obvious in one line. A measure that can
   only say pass/fail cannot be debugged.

3. **A fixture that records a decision the tooling ignores is worse than no decision**, because it
   reads as agreement. The maintainer did the right thing, in the right place, in the right
   vocabulary — and it was silently discarded, with the cost landing on the detector's reputation
   rather than the scorer's.

---

**75. Kubernetes, the third owner-published fixture: 6/6, ARI 0.906 — after one fix the fixture
itself provoked.**

`kubernetes.md` was pre-registered from `kubernetes/website` (commit `2d305c3`). It is the **first
fixture whose ground truth lives in a different repository from the code** — the concrete case behind
§5.5a(a), since `kubernetes/kubernetes/docs/` is a tombstone holding only `.gitignore` and `OWNERS`.

Six components — `kube-apiserver`, `kube-scheduler`, `kube-controller-manager`,
`cloud-controller-manager`, `kubelet`, `kube-proxy` — over 2132 of **31300** tracked files.

### The shape is harder than either predecessor

Prometheus's components were single directories. Milvus's spanned several directories under one
tree. Kubernetes's span **two different top-level trees** — `cmd/kube-scheduler` *and*
`pkg/scheduler` — so the union has to reach across `cmd/` and `pkg/`, which no containment rule
alone can do.

### First run: 5/6, with the sixth at 107/119

`cloud-controller-manager` missed exactly 12 files, all at
`staging/src/k8s.io/cloud-provider/` root: `LICENSE`, `OWNERS`, `README.md`, `go.mod`, `cloud.go`,
`doc.go`, `plugins.go`, `ports.go` and siblings.

**Different cause from Milvus's `OWNERS` misses, despite looking identical.** That directory has
**4 direct `.go` files** — it is a package. What it also has is its own **`go.mod`**, and finding
70's rule skips files directly at a module root as "the module is the whole repo".

That rule is right for the **outermost** module and wrong for a **nested** one. Prometheus has
`rules.go` at its repo root; treating that root as a component would emit one `**` component
claiming the entire repository. But `staging/src/k8s.io/cloud-provider` is a *distinct published
library* — being a module is precisely what makes it a unit, not what disqualifies it.

**Fix:** skip the module root's own files only when the module is the outermost one. Nested module
roots become components in their own right.

| target | before | after |
|---|---|---|
| **`kubernetes`** | 5/6 | **6/6** |
| `prometheus` | 11/11 | 11/11 |
| `milvus` | 3/5 | 3/5 |
| `trellis` | 9/11 | 9/11 |
| `egeria-workspaces` | 18/27 | 18/27 |

Two regression tests added (nested root becomes a component; outermost root still skipped). Suite: 36 passed.

### Two things worth recording beyond the score

**Name-based component-set recall hit 1.00 — the first time that metric has ever worked.** It has
been useless on every prior target (0/13 on trellis, 0/11 on Prometheus) because detector names are
directory names and ground-truth names are prose. Kubernetes is the exception *because its component
names are its binary names* and the repo follows `cmd/<binary>` exactly. That is a property of this
repo's conventions, not evidence the metric has become sound — strict containment remains the
headline.

**Scale is not the problem.** 31300 files, 13415 Go files, 93046 import statements, 57438 resolved
first-party imports: imports ~12s, detection ~4s. The Analysis-tier cost concern (§5.6) does not
bite here.

**Precision is, catastrophically.** **3270 components proposed against 6 declared**, 2482 of them
untyped from the coupling proposer. Recall across the three owner-published fixtures is now
11/11, 3/5 (+2 at 99.8%) and 6/6 — essentially solved. Nothing about "3270 components" is usable by
a human, and distillation (§5.2, Phase 5) is now unambiguously the only thing standing between this
work and an answer.

---

**76. Can precision be fixed by dropping the noisiest proposer? Measured: no.**

The coupling proposer accounts for almost all the over-proposal — 146 of 173 on Prometheus, 409 of
608 on Milvus, 2482 of 3270 on Kubernetes, all untyped (`?`). The obvious cheap fix is to stop
emitting it. Tested by re-scoring each target with coupling-proposed components removed:

| target | with coupling | without | components |
|---|---|---|---|
| `prometheus` | **11/11** | 9/11 | 212 → 62 |
| `milvus` | 3/5 | 3/5 | 609 → 162 |
| `kubernetes` | **6/6** | 5/6 | 3303 → 795 |

**Coupling is not noise-only: it earns 3 of the 20 matches across the three fixtures**, and they are
matches nothing else produces. Deleting it trades real recall for precision, which is the wrong
trade when recall is the thing that has been hard to get.

**And removing it does not solve precision anyway.** 795 components for 6 declared on Kubernetes,
62 for 11 on Prometheus — the `go_subsystems` proposer over-proposes *on its own*, because it emits
every package tree in the module and a repo has far more packages than components.

Two conclusions, both of which shape Phase 5:

1. **This is a distillation problem, not a proposer-selection problem.** No subset of the current
   proposers is both high-recall and low-count. §5.2's division of labour — heuristics partition, the
   LLM classifies, names and adjudicates, and *never invents a component with no detector evidence* —
   is the right shape, and the measurements say the adjudication half is now the load-bearing half.
2. **The candidate set is the right input to it.** 3270 candidates with evidence, containing a 6/6
   recall, is a *better* starting point for adjudication than a smaller set that has already thrown
   away a third of the answer. Over-proposal is the correct failure direction for a funnel — provided
   something downstream actually narrows it, which is exactly what does not exist yet.

---

**77. Candidate ranking: how many candidates must a distiller see? Hundreds, not thousands — and
confidence is the worst signal we have.**

Finding 76 showed no proposer subset is both high-recall and low-count. So the Phase 5 question is
how far down a *ranked* list the right answers sit. `rank.py` measures **recall@N** — the same
strict-containment rule `score.py` applies (§2a: exact node, or union of contained refinements),
computed over only the top N candidates. It reproduces `score.py` exactly at N=ALL rather than
approximating it.

**Not tuned.** Weights fitted on these three fixtures would contaminate the only pre-registered,
owner-published ground truth this project has. Each strategy is motivated separately, stated up
front, and the sweep was run once.

| strategy | motivation |
|---|---|
| `confidence` | the null hypothesis — the number the detectors already emit, used as-is (§3.3b) |
| `agreement` | independent agreement first (Phase 1 §4.4, portfolio §3), then confidence |
| `shallow` | §6.0 — a component is a *scope locator*, and the locators humans name are coarse |
| `typed` | classifiable into the 13 values before `?`, then agreement, depth, confidence |
| `rollup` | not-a-refinement-of-another-candidate first, then typed/depth/confidence |

### Results

```
prometheus  (212 cand, 11 declared)   N=10   N=25   N=50  N=100  N=212
  confidence                          1/11   1/11   2/11   7/11  11/11
  agreement                           3/11   6/11   8/11   9/11  11/11
  shallow                             2/11   7/11  10/11  10/11  11/11
  typed                               6/11   9/11   9/11  10/11  11/11
  rollup                              6/11   9/11  10/11  10/11  11/11

milvus      (578 cand, 5 declared)    N=50  N=100  N=250  N=500  N=578
  confidence                           0/5    1/5    3/5    3/5    3/5
  typed / rollup                       0/5    3/5    3/5    3/5    3/5

kubernetes  (3303 cand, 6 declared)   N=50  N=100  N=250  N=500  N=3303
  confidence                           0/6    0/6    0/6    2/6     6/6
  agreement                            0/6    0/6    4/6    5/6     6/6
  typed / rollup                       3/6    4/6    5/6    5/6     6/6
```

**Confidence alone is the worst strategy at every N on every target** — 1/11 at N=25 on Prometheus
where `typed` gets 9/11. The confidence the detectors emit is a claim about *how the identity was
established* (§8.2's precedence rungs), not about *how likely this is to be a component*, and it
does not transfer. Another instance of the recurring lesson: a number that does not encode the
question being asked of it.

**`rollup` ties `typed` and does not beat it — a negative result, recorded as one.** The hypothesis
was that preferring nodes not contained in another candidate would surface the handful that matter.
It buys nothing `typed` did not already capture, so the extra machinery is not justified by this
evidence.

### Why recall@N is harsher than "is the answer in the list"

Measuring the **minimal** cover per declared component — maximal contained nodes only — gives the
real shape:

| component | candidates *contained* | **minimal cover** |
|---|---|---|
| `kube-controller-manager` | 140 | **2** — `cmd/kube-controller-manager` + `pkg/controller` |
| `kubelet` | 103 | **2** |
| `kube-scheduler` | 53 | **2** |
| `kube-apiserver` | 27 | **3** |
| Milvus `Proxy` | 15 | **2** |

**A component needs *every* member of its cover inside the window.** Prometheus survives truncation
because 10 of its 11 components are *exact single nodes*; Kubernetes and Milvus need both halves
(`cmd/X` **and** `pkg/X`) in the top N simultaneously. So recall@N degrades much faster than a
"is the right answer somewhere in the list" measure would suggest — and reporting the latter would
have flattered the result substantially.

### The practical answer for Phase 5

**An adjudicator needs on the order of hundreds of candidates, not thousands** — roughly N≈25
(Prometheus), N≈100 (Milvus), N≈250 (Kubernetes) under `typed`. That is about an order of magnitude
off 3303, not two, and 250 evidence-carrying candidates is a tractable LLM input where 3303 is not.

Ranking is therefore **worth doing and not sufficient on its own**. The remaining gap is structural:
until something merges `cmd/X` with `pkg/X` into one candidate — which is what the ground truth
actually declares — every union-matched component costs two or three slots in the window instead of
one.

---

**78. The `cmd/X` + `pkg/X` merge: one real fix, and a clean negative result.**

Finding 77 left this as the next concrete work — merge the two arms of a union so a component costs
one slot in the ranking window instead of two or three. Attempted, and it does not work by import
evidence. Recorded in full, because the reason is more useful than the attempt.

### The real fix found along the way: entry points are `package main`, not `main.go`

Measuring which packages `cmd/*` imports produced nonsense at first — `pkg/scheduler`'s top importer
was `integration` (a *test* binary), and `cmd/kube-scheduler` did not appear in the entry-point set
at all. Cause: `has_main` tested `basename(f) == "main.go"`. **Kubernetes's entry points are
`cmd/kube-scheduler/scheduler.go`, `cmd/kubelet/kubelet.go`, `cmd/kube-proxy/proxy.go`** — the
filename test missed every one of the six components that matter.

Two corrections, both Go semantics rather than convention — the same lesson as finding 72's container
rule:

* detect `^package main` in the file's own text, not a filename;
* scan only files **directly in the component root**, since scanning the subtree typed
  `pkg/controlplane` as an executable because a nested test helper declares `package main`.

**This closes finding 70's known type-inference weakness.** Prometheus no longer mistypes `promql`,
`util` and `documentation` as `Console Command`; its 7 executables are now `cmd/prometheus`,
`cmd/promtool` and five genuine example/generator mains. Kubernetes resolves 60 real `cmd/*`
binaries. No score changed: 11/11, 3/5, 6/6. Three regression tests added; suite 39 passed.

### With correct entry points, the dominance signal is excellent

Import weight from entry point to package, restricted to non-entry targets:

| ground-truth partner | dominant importer | share |
|---|---|---|
| `pkg/scheduler` | `kube-scheduler` | **1.00** |
| `pkg/controlplane`, `pkg/kubeapiserver` | `kube-apiserver` | **1.00** |
| `pkg/controller` | `kube-controller-manager` | **0.97** |
| `pkg/proxy` | `kube-proxy` | **0.97** |
| `pkg/kubelet` | `kubelet` | **0.83** |
| `staging/src/k8s.io/cloud-provider` | — | 0.50, correctly no majority |

Six of seven partners are found by a **strict majority** rule, which is threshold-free.

### And it still fails — because the graph does not encode the distinction

Merging every strict-majority-dominated package into its entry point captures the right partner every
time (`missing=[]` for five of six) **and over-reaches every time**:

| entry point | packages merged | extras pulled in |
|---|---|---|
| `kube-proxy` | 3 | `pkg/util/iptables`, … |
| `kube-scheduler` | 6 | `staging/.../component-base/config`, … |
| `kubelet` | 15 | `pkg/credentialprovider`, `pkg/util/flock`, … |
| `kube-controller-manager` | 44 | `pkg/apis/apps`, `pkg/apis/autoscaling`, … |

**Not one merged set equals the ground truth.** The distinction the maintainers draw — `pkg/proxy` is
kube-proxy's *implementation*, `pkg/util/iptables` is a *utility it uses* — **is not in the import
graph.** Both are imports, both are dominated by exactly one binary, and `pkg/util/iptables` is
legitimately used only by `kube-proxy`. Dominance cannot separate "is" from "uses".

### Why the fitted alternative was not shipped

The pairing *is* recoverable by name — `kube-scheduler`↔`scheduler`, `kube-proxy`↔`proxy`,
`kubelet`↔`kubelet`, `kube-apiserver`↔`kubeapiserver` after stripping the `kube-` prefix; and Milvus's
`Proxy` is `internal/proxy` + `internal/distributed/proxy`, the same basename in two trees.

**That is fitting a rule to the two repos we have measured**, which is precisely the contamination
this project's pre-registration discipline exists to prevent. A `kube-` prefix rule is a Kubernetes
rule. It should be proposed against a repo nobody here has looked at before it is believed — the same
standard finding 65 applied to an LLM's output.

**No behaviour change from the merge attempt.** The union path already recovers these components
(6/6 on Kubernetes); merging would have added noise without producing an exact match, and the
ranking-window cost that motivated it remains open.

---

**79. Distillation, deterministic half: 3303 → 358 candidates on Kubernetes with recall intact.**

§5.2 divides the work — *"Heuristics own steps 1, 4, 5; the LLM owns 2 and 3 and adjudicates
ambiguous partitions."* `distill.py` answers how far the heuristic half gets **before an LLM is
involved at all**, which matters because every candidate removed deterministically is one an
adjudicator never sees, and a deterministic rule can be regression-tested against the pre-registered
corpus where a prompt cannot.

Three filters, each a claim about what a component *is*:

1. **support-only** — a candidate whose roots are *entirely* under `test/`, `testdata/`, `docs/`,
   `examples/`, `hack/`, `vendor/`, `mocks/`… A component may *contain* tests (Prometheus's
   `config/` owns `config/testdata/` and the ground truth says so); one that is *only* tests is
   support material, not architecture.
2. **whole-repo claims** — the coupling proposer emits one per target (`.`, globbing `cmd/**`,
   `staging/**`, …). Same thing the npm detector calls a workspace root and `go_subsystems` calls a
   module root: **a container, not a component.**
3. **refinements** — a candidate every root of which lies strictly inside a *classified* parent.

| target | before | after | recall |
|---|---|---|---|
| `kubernetes` | 3303 | **358** | **6/6** — unchanged |
| `milvus` | 609 | **238** | 3/5 — unchanged |
| `prometheus` | 212 | **95** | 11/11 → **10/11** |

**A 9× reduction on Kubernetes at no cost to recall**, and better than ranking alone achieved
(finding 77: `typed` needed N≈250 for 5/6; this keeps 6/6 in 358 unranked).

### Two failures worth keeping

**The whole-repo guard was not in the first version, and its absence was catastrophic in a way that
looked like success.** Without it, Kubernetes distilled to **4 components** — a 99.9% reduction, and
a total loss of ground truth. The coupling proposer's `.` candidate claims `cmd/**` and `staging/**`,
so every real component was "a refinement of" it. A filter that removes everything reports as the
best filter, which is why the count was scored rather than admired.

**Sparing typed refinements is a measured, rejected improvement.** "A classified child is a component
in its own right, so don't drop it because a classified parent exists" sounds obviously right. It is
strictly worse on every axis: Kubernetes 358 @ 6/6 → **762 @ 5/6**, Milvus 238 → 276 at the same 3/5,
and Prometheus did not recover the component the change was meant to save. Left in the code as a
comment rather than silently reverted, because the intuition is appealing enough to be retried.

### The known cost, stated plainly

Prometheus loses **`Remote storage`**. Its ground truth splits `storage/remote/**` out of what the
detector proposes as one `storage` roll-up, so it was only ever matched as a *union of refinements* —
exactly what filter 3 removes. This is the §2a granularity tension in its sharpest form: the same
refinements that let a coarse detector match a fine ground truth are the ones that turn 6 components
into 3303. **Dropping them trades recall for count, and the trade is repo-dependent** — free on
Kubernetes and Milvus, one component on Prometheus.

### What this leaves for the LLM

358 evidence-carrying candidates for 6 declared components is a tractable adjudication input where
3303 was not. §5.2's rule still stands and is now enforceable: **the LLM never invents a component
with no detector evidence behind it** — it names, classifies and merges what survives. Distillation
has moved the problem from "unusable" to "expensive", which is the right shape of remaining work.

---

**80. LLM adjudicator: the guardrail holds, the plumbing works, and a local 32B is worse than the
deterministic distiller on everything but names.**

`adjudicate.py` implements §5.2 steps 2 (classify) and 3 (name) plus merge, over finding 79's
distilled candidates. First measured run, `qwen2.5-coder:32b` via local Ollama, Prometheus:

| measure | deterministic (finding 79) | + adjudicator |
|---|---|---|
| components | 95 | **56** |
| strict containment | **10/11** | **9/11** |
| types assigned | — | **53 of 56 are `Software Library`** |

**Lost `Fanout storage` *and* `Remote storage`** — deterministic distillation lost only the second.

### Read it by §5.2's own three jobs, because they came out differently

- **Step 3, name — good.** "Prometheus Command Line Interface", "Configuration Module", "Discovery
  Module". Human-readable, accurate, and exactly the thing no heuristic produces. This is the part
  worth keeping.
- **Step 2, classify — poor.** 53 of 56 components typed `Software Library`. A classifier that
  answers the same way 95% of the time carries almost no information, whatever the accuracy of any
  single answer.
- **Merge — weak.** 95 → 56 is 1.7×, where the target is closer to 95 → 11. It paired a few things
  and left the rest alone.

### The genuinely good news: **zero guardrail drops**

Every one of the 56 outputs referenced real candidate slugs, used a valid type, and claimed only
files its candidates claimed. All 95 inputs were referenced; none was silently discarded. §5.2's rule
— *the LLM never invents a component with no detector evidence* — **held without a single
intervention.**

Worth being careful about what that shows. It is evidence the *mechanism* is sound; it is not
evidence a stronger model would stay grounded, since a weaker model that mostly renames what it is
given has little opportunity to invent. The guardrail's value is untested until something tries to
cross it.

### What this does and does not measure

**It does not measure whether LLM adjudication works.** A local 32B is not what would ship, and the
failure modes seen — under-merging, monotone typing — are exactly what a small model does. The
result establishes that the pipeline runs end to end, is scoreable, caches, and is grounded by
construction.

**Do not read 9/11 as a verdict on the approach.** Read it as: *this configuration is worse than
doing nothing, and the next measurement needs a representative model.* Recorded now precisely so the
comparison exists before a better model makes it look easy.

### The `storage` split, for the third time

`Fanout storage` (`storage/*.go`) and `Remote storage` (`storage/remote/**`) have now been lost by
distillation (one of them) and adjudication (both). Prometheus's ground truth splits what every
detector proposes as one `storage` roll-up. This is the §2a granularity tension in its most
persistent form, and it is now the single most repeated failure in the corpus — worth attacking
directly rather than hoping a better model resolves it.

---

**81. Coder vs instruct, one variable: instruct wins by two components. Monotone typing is neither
model's fault.**

Finding 80 measured `qwen2.5-coder:32b`. The obvious objection: a **code-completion-tuned** model was
asked to do classification, naming and merge judgement with structured JSON output — not code
generation. Tested properly, with the prompt **frozen** so the model is the only variable.

**A confound was caught first.** The prompt had been revised between runs (`adjudicate.py` mtime
16:56, after finding 80's 17:03 output). Running the new model against the new prompt would have
changed two variables and answered nothing. A frozen copy was taken and both models run against it.

### Result (Prometheus, DEV fixture — development signal, not a measurement)

| config | components | strict containment | type distribution |
|---|---|---|---|
| deterministic only (finding 79) | 95 | **10/11** | — |
| original prompt + coder | 56 | 9/11 | 53/56 one type |
| frozen prompt + **coder** | **16** | 6/11 | 14/16 one type |
| frozen prompt + **instruct** | **16** | **8/11** | 15/16 one type |

**Three findings, and the second is the useful one.**

1. **Instruct beats coder, 6/11 → 8/11**, at an identical component count and identical prompt. The
   hypothesis was right: coder-tuning was costing real accuracy on a task that is judgement, not code.
2. **Monotone typing is NOT a coder-tuning artefact.** The instruct model is *worse* — 15 of 16 one
   value against the coder's 14 of 16. Two differently-tuned models of the same size, same family,
   same prompt, both collapse the 13-value vocabulary to essentially one. That points at the **task
   framing**, not the model: the prompt asks for a type without giving the model what
   `SolutionComponentType` actually distinguishes (§3.1: *"how and where is it run"*). This is now the
   most promising thing to fix, and it is fixable in the prompt.
3. **Merge count is prompt-driven, not model-driven.** Both models produced *exactly* 16. The merge
   instruction dominates; the model contributes accuracy within it.

### The tradeoff that matters, stated plainly

**Deterministic distillation alone still has the best recall: 10/11.** Every LLM configuration is
worse on that measure. But it leaves 95 components, and the adjudicator gets to **16 at 8/11**.

For the actual goal — *an answer a human reads* — 16 components at 8/11 is plausibly more useful than
95 at 10/11. That is a judgement call and should be made explicitly rather than by whichever number
is quoted. Both are recorded so it can be.

### A methodological cost, recorded rather than hidden

The adjudicator session ran `milvus` and `kubernetes` — both **held out** — with the *coder* model
before this comparison existed. Their timestamps confirm one settled prompt was used for both
(`adjudicate.py` unchanged since 16:56), so those runs are internally valid. But they measure a
configuration now known to be inferior, and re-running them under instruct would be **a second use of
a held-out fixture**, which is what the holdout rule exists to prevent.

**`trellis` and `egeria-workspaces` have not been touched by any adjudicator run.** They are the
clean holdout for whatever configuration is finally settled — and, being maintainer-written rather
than doc-derived, the only fixtures where a doc-fed adjudicator could ever be measured honestly.

---

**82. The guardrail proves groundedness, not correctness — and Kubernetes shows the difference costs
everything.**

Held-out runs, settled v3 prompt, `qwen2.5-coder:32b`, one pass each:

| target | candidates | components | strict containment | baseline | guardrail drops |
|---|---|---|---|---|---|
| `milvus` | 238 | 89 | 3/5 | 3/5 — **matched** | **10** |
| `kubernetes` | 358 | 70 | **0/6** | 6/6 — **destroyed** | 0 |

### What the guardrail caught — real hallucination, on first exposure

On `milvus` the model **invented candidate slugs**: `coupling::internal::json`,
`coupling::internal::registry`, `coupling::internal::util::nullutil`. It pattern-matched the
`coupling::x::y` naming convention it saw on *other* real candidates and applied it to directories
where no candidate was ever proposed — the real slug was `go::internal-json`. All were dropped by the
unknown-slug check.

**This retroactively corrects finding 80.** Zero drops on Prometheus was not validation, it was lack
of opportunity — exactly as suspected there. Given a target with more candidates, the model
hallucinated immediately, and §5.2's rule caught it. The mechanism works.

### What the guardrail did NOT catch — and this is the finding

On `kubernetes` the model merged **24 independent `cmd/*` binaries** — `kube-apiserver`, `kubelet`,
`kube-scheduler`, `kube-proxy`, `kube-controller-manager`, `cloud-controller-manager` and 18 others —
into a single component named **"CLI Commands"**.

Verified directly: 24 globs on one component, `cmd/cloud-controller-manager/**` among them. Every
slug real. Every glob grounded in a candidate. Type valid. **It passes the hard rule perfectly, and
it destroys all six ground-truth components in one move.**

> **Groundedness is not architectural correctness, and no amount of grounding checking will make it
> so.** §5.2's rule prevents invention. It says nothing about whether the merge is *right*.

### Finding 73 is what makes the failure legible

The score is 0/6 — and partial cover reports **2002 of 2132 files, 93.9%**, across six components
all sitting under one overclaiming node.

Without partial reporting this reads as total failure. With it, the diagnosis is exact: **the right
files were found and grouped wrongly.** That is a completely different defect from "found nothing",
and it is the difference between "the detector is broken" and "the merge grain is wrong".

### Prompt iteration did not transfer, which is the holdout rule's whole point

Three dev-fixture iterations: v1 under-merged (95→56), v2 collapsed totally (95→4, **0/11**), v3
settled (95→16). v3's fix was learned against Prometheus's *fan-out utility packages*. On Kubernetes
the over-merge reappeared in a **structurally different shape** — sibling CLI binaries — and v3 had
nothing to say about it.

Tuning suppressed the failure mode *visible on the dev fixture* and left the general defect intact.
Had the prompt been iterated against Kubernetes directly, 6/6 would have been recoverable and
meaningless.

### The concrete fix this points to, and we already have the signal

**A merged component should not span multiple entry points.** Finding 78 built exactly that signal —
`package main` detection, per component root. Twenty-four `cmd/*` binaries are twenty-four
independent deployables, and any merge unioning more than one of them is almost certainly wrong.

That is a **partition-level post-check** to sit beside the groundedness check: not "did you invent
this?" but "does this grouping contradict evidence we already hold?". It is principled rather than a
tuned threshold, it uses a signal already extracted, and it would have caught this exact failure.

### One drop that was arguably wrong

On `milvus` the model identified third-party compose services (etcd, pulsar, minio, jaeger) as a
deployment-perspective component, grounded in real slugs — and the guardrail dropped it because those
candidates are legitimately **fileless**, and the grounding rule requires non-empty `files`.
`egeria-workspaces.md` records exactly this case: *"deployment components frequently own no
first-party files at all."* The rule is too strict for the deployment perspective.

### Cost

10 LLM calls, **$0** (the Anthropic key has no credit; everything ran locally), **~133 minutes** of
wall time — 11.5s for a one-candidate chunk to 31.6 min for a 177-candidate one. Chunking grouped by
shallowest shared path prefix so no component's candidates split across a boundary.

---

**83. A partition-level check beside the groundedness check: Kubernetes 0/6 → 6/6.**

Finding 82's conclusion was that `validate_and_ground` proves the model didn't *invent* anything and
says nothing about whether its merge is *right*. The fix it pointed to needed no new signal: finding
78 already detects entry points properly (a package declaring `package main` in its own root), and
`go_subsystems` types those `Console Command`.

**Rule: a merge spanning more than one entry point is rejected.** Twenty-four binaries are
twenty-four independently deployable things. On rejection the constituents are **passed through
unmerged** rather than discarded — losing the model's grouping is a cost, losing the candidates would
be a regression.

| target | deterministic | adjudicator (v3) | **+ entry-point check** |
|---|---|---|---|
| `prometheus` | 95 @ 10/11 | 16 @ 6/11 | **17 @ 7/11** |
| `milvus` | 238 @ 3/5 | 89 @ 3/5 | 89 @ 3/5 |
| `kubernetes` | 358 @ 6/6 | 70 @ **0/6** | **93 @ 6/6** |

**It fires on exactly the right things.** Kubernetes: *"'CLI Commands' — merge spans 24 entry
points"*. Prometheus: *"'Prometheus Command Line Interface' — merge spans 2 entry points"* —
`cmd-prometheus` and `cmd-promtool`, genuinely two binaries, an over-merge nobody had noticed. Milvus:
no merge rejected, no change. No false positives across three targets.

**And it is the first configuration where adjudication beats distillation on Kubernetes.**
93 components at 6/6 against 358 at 6/6 — a 3.8× reduction at *identical* recall. That is what the
whole exercise was for: fewer components, same answer.

Prometheus still favours the deterministic result on recall (10/11 vs 7/11) while the adjudicator
gives 5.6× fewer components. The tradeoff from finding 81 stands, now with a better exchange rate.

### Bookkeeping: Kubernetes moves to DEV

This check was **derived from the Kubernetes failure**, so measuring it on Kubernetes is a
development signal, not an independent result — the same reasoning that made Prometheus a dev fixture
when its prompt was iterated. Recorded in the fixtures README rather than quietly reused.

**`trellis` and `egeria-workspaces` remain the only untouched fixtures.** They are now the entire
clean holdout for this work, and should be spent once, on a settled configuration — not on the next
increment.

### The general shape, which is the durable part

Two checks, answering different questions:

| check | question | catches |
|---|---|---|
| `validate_and_ground` | did you invent this? | hallucinated slugs (finding 82, Milvus) |
| `split_multi_entrypoint` | does this contradict evidence we hold? | semantically catastrophic merges |

The second is a *category*, not a single rule. Other evidence we already hold could ground further
partition checks in the same way — a merge spanning two deployment units, or two modules, or both
sides of a language boundary. **The pattern is: use detector evidence to falsify the model's
grouping, not just to license it.**

**84. Typing was a prompt-framing problem: 3 distinct types → 6, and recall 6/11 → 9/11.**

Finding 81 showed two differently-tuned models collapsing the 13-value vocabulary to essentially one
value, and concluded the fault was framing rather than capability. Confirmed: the prompt listed the
13 values and **never said what they distinguish.** §3.1 states the axis outright — *"how and where
is it run"* — and none of it reached the model. Given only a list, `Software Library` looks safest for
almost anything.

Added an ordered decision guide (third-party product → own entry point, split by terminal /
continuous / scheduled → serves network requests → renders for a human → persists data → moves data →
emits outputs → inference → workflow → human steps), named `Software Library` as **the fall-through,
not the default**, quoted the actual failure back (*"a previous run typed 53 of 56 components
`Software Library`"*), and pointed at the evidence that already decides it: `detector-proposed type:
Console Command` means an entry point was genuinely detected (§78's `package main` check), not a hint.

| | v3 prompt | **+ typing guide** |
|---|---|---|
| components | 16 | 27 |
| distinct types used | 3 | **6** |
| share on one value | 87.5% | **59%** |
| strict containment | 6/11 | **9/11** |

**Recall improved, which was not predicted.** The guide was aimed at typing; file sets do not change
when a type changes. It moved 6/11 → 9/11 because the same instruction reduced over-merging — 16 → 27
components. The clause forcing a distinction between "runs continuously" and "is imported" is also a
clause about what makes two things different, and the model merged less as a result. **Typing and
merging were not independent problems.**

Best adjudicated Prometheus result so far: **27 components at 9/11**, against deterministic
distillation's 95 at 10/11 — 3.5× fewer components for one component of recall.

### What the types actually got right, and wrong

Right, and unambiguously: `cmd/prometheus` → `Long Running Daemon`, `cmd/promtool` → `Console
Command`, `tsdb/**` → `Data Storage`, `web/**` → `User Interface`. All four match the ground truth
exactly, and all four are the cases where direct evidence existed.

Wrong, and instructively:

- **`promql/**` → `Long Running Daemon`.** The ground truth says `Software Library`, and Prometheus's
  own document says the engine *"does not run as its own actor goroutine, but is used as a library."*
  The model had no access to that sentence — we deliberately do not feed the architecture doc (§5.2
  step 0 says prose outranks inference, but doing so here would be circular against a fixture
  transcribed from it). This is the clearest single illustration of both the doc's value and why it
  cannot be used on these three fixtures.
- **`scrape/**`, `rules/**` → `Long Running Daemon`** where ground truth says `Automated Action`;
  **`notifier/**` → `Long Running Daemon`** where it says `Publishing`. In-process managers are being
  read as daemons.
- **`model/exemplar/**` → `Insight Model`.** A keyword false positive: `model/` is a *data model*
  package, nothing to do with inference.

**So the guide fixed diversity, not accuracy.** One over-used value (`Software Library`, 87.5%) was
replaced by two (`Software Library` 59%, `Long Running Daemon` 22%). That is a real improvement and a
partial one, and the remaining error has a clear shape: **the model cannot tell "runs as its own
process" from "runs inside one"**, which is exactly the distinction `Automated Action` and
`Long Running Daemon` turn on. Evidence we already hold could settle it — a component with no entry
point of its own is not a daemon — which is another instance of finding 83's pattern: use detector
evidence to falsify a claim, not merely to license it.

**85. Falsifying a type with evidence: 4/9 → 5/9 type agreement, and an honest ceiling.**

Finding 84 left the model unable to tell *"runs as its own process"* from *"runs inside one"*. We can
tell: **a component with no entry point among its constituents is not a daemon and not a console
command.** Those two types assert a mode of execution the absence of an entry point refutes — a
falsification, not a preference.

It fired on exactly the five in-process managers finding 84 named: `Notification System`, `PromQL
Engine`, `Rule Management`, `Scrape Manager`, `Template Management` — all `Long Running Daemon`, none
with an entry point.

**Type agreement against ground truth, measured directly for the first time** (over the 9 components
whose file sets match exactly):

| | agreement | recall |
|---|---|---|
| typing guide (finding 84) | 4/9 | 9/11 |
| **+ entry-point falsification** | **5/9** | 9/11 — unchanged |

Recall is untouched, as expected: this is post-processing over a cached response, and a type change
cannot move a file set. (Finding 84's recall gain came from re-prompting, which also changed merging.
This one genuinely isolates typing.)

### The honest ceiling, and why the remaining four are different

`PromQL engine` is now correct — and it is the one Prometheus's own doc settles: *"does not run as
its own actor goroutine, but is used as a library."* We reached the right answer without the doc.

The other four are **not fixed, only made less wrong**:

| component | ground truth | now | was |
|---|---|---|---|
| `Scrape manager` | `Automated Action` | `Software Library` | `Long Running Daemon` |
| `Rule manager` | `Automated Action` | `Software Library` | `Long Running Daemon` |
| `Notifier` | `Publishing` | `Software Library` | `Long Running Daemon` |
| `Service discovery` | `Automated Action` | `Software Library` | (unchanged) |

**A false claim was replaced by a weaker one, not a true one**, and that should be stated plainly
rather than counted as a win. The falsification can prove *"not a separate process"*; it cannot
distinguish *"runs on a schedule or trigger"* (`Automated Action`) or *"emits outputs to consumers"*
(`Publishing`) from a plain library — those turn on **behaviour inside the process**, which no
artifact we currently extract observes.

That is a real ceiling on evidence-based typing, and it is worth naming: **three of the 13 values —
`Automated Action`, `Publishing`, `Data Distribution` — describe what a component *does at runtime*,
and every signal we collect is static.** Ports and wires (§5.5f) are the nearest thing we have to
runtime evidence, and they are not wired into the IR yet. That is the next place this could improve,
rather than a better prompt.

### The pattern, now three instances deep

| check | question | outcome |
|---|---|---|
| `validate_and_ground` | did you invent this? | caught hallucinated slugs (finding 82) |
| `split_multi_entrypoint` | does this grouping contradict evidence? | Kubernetes 0/6 → 6/6 (finding 83) |
| `falsify_types` | does this *claim* contradict evidence? | type agreement 4/9 → 5/9 |

Each is cheap, deterministic, regression-testable, and derived from evidence already extracted.
Cumulatively they have been worth far more than either the model choice (finding 81, +2 components)
or three rounds of prompt iteration (finding 82, which ended at 0/6 on a held-out target).
**Constraining the model with evidence has outperformed instructing it, every time.**

**86. Finding 81 does not generalise: the better model depends on the prompt.**

Finding 81 measured `qwen2.5:32b` (instruct) beating `qwen2.5-coder:32b` 8/11 to 6/11 on the v3
prompt, and concluded coder-tuning was costing accuracy. Before spending a held-out fixture, the
settled configuration — typing guide (finding 84) plus both evidence checks (findings 83, 85) — was
re-confirmed on the dev fixture with **both** models.

**The ordering reverses.**

| configuration (Prometheus, DEV) | components | recall | distinct types |
|---|---|---|---|
| v3 prompt + coder | 16 | 6/11 | 3 |
| v3 prompt + **instruct** | 16 | **8/11** | 2 |
| typing guide + checks + **coder** | 27 | **9/11** | **6** |
| typing guide + checks + instruct | 23 | 8/11 | 3 |

With the v3 prompt, instruct wins by two. With the typing guide, **coder wins by one and gives twice
the type diversity** — and instruct collapses to a *different* over-used value, `Multi-Step Process`
(7 of 23), rather than `Software Library`.

**So "which model is better" was never a property of the models.** It is a property of the
model-and-prompt pair, and the better prompt helped the coder model more. A model comparison measured
on one prompt does not transfer to another, and finding 81 should be read as *"instruct beat coder on
the v3 prompt"* — not as a general claim. Corrected here rather than left to be quoted.

**It also nearly cost the holdout.** The `egeria-workspaces` run had been queued with the instruct
model on the strength of finding 81, and would have spent the fixture measuring a configuration the
dev fixture says is inferior. Stopped before it wrote output — the fixture was not spent. **The
dev-confirm step existed precisely so a settled configuration is settled by measurement rather than
by the most recent conclusion**, and this is the first time it paid for itself.

---

**87. The held-out run: 18/27 → 0/27. Every adjudicator rule was derived from code-tree repos and
none of them is valid for the deployment perspective.**

`egeria-workspaces` was spent as the clean holdout for the settled configuration (coder + typing
guide + both evidence checks), after finding 86's dev-confirm chose the model.

| stage | components | component-set agreement |
|---|---|---|
| raw IR | 164 | **18/27** |
| + deterministic distillation | 141 | **18/27** — no loss |
| + adjudication | **8** | **0/27** |

**Deterministic distillation transfers to a new perspective without loss. Adjudication destroys it.**

### Three failures, all the same root cause

**1. The grounding rule dropped 15 components for having no files.** `egeria-workspaces.md` states
the case in its own text: *"deployment components frequently own no first-party files at all —
`kafka`, `postgres` and `kroki` are third-party images."* Finding 82 already flagged this rule as
"conservative-but-arguably-too-strict" when it dropped one legitimate component on Milvus. It is not
arguable any more: on a deployment-perspective target it removes the components wholesale.

**2. `falsify_types` fired on seven real daemons and was wrong every time** — `Egeria Freshstart`,
`Egeria Quickstart`, `DuckDB Server`, `Unity Catalog Server`, `Autoheal`, `User Code Server`,
`Airflow Marquez`. All were correctly typed `Long Running Daemon` and all were demoted to
`Software Library` because no constituent declares `package main`.

**A container running a third-party image is a long-running daemon that has no first-party entry
point by definition.** Finding 85 called this rule "a falsification, not a preference". It is a
falsification *in the logical perspective, over first-party code*. Outside that scope the premise
fails, and the rule confidently produces the opposite of the truth.

**3. Merging collapsed 141 candidates to 8.** With the files-grounding drops and the type demotions
compounding, what survived was 7 `Software Library` and 1 `Third Party Process` — a description of a
25-compose-file estate as eight libraries.

### What this actually establishes

Every rule built in findings 79–86 was derived from Prometheus, Milvus and Kubernetes: **three
code-tree repos, all logical perspective, all Go.** Each rule was principled *within that scope* and
each was measured. None was tested outside it until now.

> **A rule derived from one perspective is not a rule. It is a rule about that perspective.**

The same lesson as finding 78's `kube-` prefix pairing, which was refused for being fitted to the
repos already measured — but this time the fitting was to a *perspective* rather than to a repo, and
it was invisible because every fixture in play shared it.

### The cost, stated plainly

**`egeria-workspaces` is now spent, and it was the only deployment-perspective fixture.** Any fix to
deployment handling — perspective-gating the grounding rule, scoping `falsify_types` to first-party
code, or refusing to adjudicate a deployment IR at all — **has no clean fixture left to be validated
against.** `trellis` remains clean but is logical perspective, so it cannot test this.

That is the honest position: the defect is identified and evidenced, the fix is obvious, and **there
is currently no way to measure whether the fix works.** A new pre-registered deployment-perspective
fixture is the prerequisite, not the follow-up.

### And the deterministic half is the quiet result

18/27 preserved through distillation on a target and a perspective it was never designed for. The
filters — support-only, whole-repo claims, refinements of a classified parent — are stated as claims
about what a component *is*, and they held. **Cheap, deterministic, perspective-independent, and the
only part of this pipeline that transferred.**

**88. Perspective-gating the two rules was necessary and not sufficient: the adjudicator has to run
*within* a perspective.**

Finding 87's fix looked obvious — gate the files-grounding rule and `falsify_types` on perspective.
Both were applied:

- **files-grounding**: a component whose candidates are all `deployment` may legitimately own no
  files. Groundedness there is the *slug*, which is what §5.2's rule actually asks for.
- **cross-perspective merges rejected**: §4.2 says perspectives are *"map, never merge"*. A merge
  spanning them is a category error, and mixed merges were silently defaulting to
  `perspective="logical"`, which is why the deployment gate never engaged.

**Survival improved substantially and the score did not move at all.**

| | components | deployment components | agreement |
|---|---|---|---|
| distilled | 141 | **59** | **18/27** |
| adjudicated (finding 87) | 8 | — | 0/27 |
| + files gate | 14 | — | 0/27 |
| + cross-perspective rejection | **30** | **15** | **0/27** |

### The real defect, which the gates could only expose

**Adjudication runs over the whole candidate set at once, regardless of perspective.** The distilled
IR carries 59 deployment candidates; adjudication leaves 15. Forty-four were absorbed into merges
with logical candidates — and `egeria-workspaces.md` is a *deployment* ground truth, so those 59 are
exactly what the match needs.

Gating the rules stopped them producing *wrong answers* about deployment components. It could not
stop the merge step from *consuming* those components before the rules ever saw them.

> **The fix is structural: partition candidates by perspective and adjudicate each separately.**
> One prompt per perspective, never a merge across them — which is what §4.2 has said all along.

### Why this is recorded rather than built

Three reasons, and the third is the binding one:

1. Each perspective is a separate LLM pass; on this hardware that is roughly an hour of wall time for
   a target of this size.
2. Per-perspective prompts would need per-perspective *guidance* — the type decision guide (finding
   84) is written for logical components and its ordered list barely applies to a compose service.
3. **There is no clean fixture to validate it against.** `egeria-workspaces` is spent (finding 87)
   and was the only deployment-perspective ground truth. `trellis` is clean but logical. Building a
   structural fix with no way to measure whether it worked is how the last five findings' worth of
   discipline gets thrown away in one step.

**A new pre-registered deployment-perspective fixture is the prerequisite.** Until then the honest
position is: the defect is diagnosed and evidenced, the fix is known, and it is unbuildable *as a
measured change*.

### What stands

The two gates are correct on their own terms and are kept — they remove rules that were producing
confidently wrong answers outside their scope, which is worth doing whether or not the score moves.
And the headline from finding 87 is unchanged: **deterministic distillation preserved 18/27 on a
perspective it was never designed for; adjudication has yet to beat it there.**

**89. "Wired into the IR" was wired into the *spike*. The product computed ports by nobody and
stored them nowhere.**

Finding 86's commit said *"Wire ports and wires into the IR"* and *"closes gap-list item 3"*. Both
claims were wrong in the same way, and I repeated them to the presentation session as fact.

Three checks, run to verify their report rather than accept it:

| claim | verified |
|---|---|
| the only caller of `interfaces.propose()` is `scripts/arch-spike/detect.py:124` | **yes** — the throwaway harness |
| `arch_recovery_detect.py` never imports `interfaces` | **yes** — zero matches; the survey step never computed them |
| `persist_ir()` takes no ports/wires | **yes** — `components` and `evidence` only |

So the 68 ports and 38 wires were real and stable *inside a spike run*. In the product: **computed by
nobody, stored nowhere, readable by nothing.**

### The failure mode, which is the point

The capability existed, was regression-tested, and was not connected to storage — and **an empty
result renders identically to a real zero.** Prometheus legitimately yielding one port and zero wires
is exactly the case that would have hidden this: a topology view built against it would have shown
nothing, and nobody could have told "nothing to show" from "nothing arrives".

The presentation session named three prior instances of the same shape in this codebase this week —
`project_dependencies` written only by the ingestion pipeline, `ci_quality` findings likewise,
`project_analysis_findings` never cleaned by `remove()`. That makes this a **pattern, not an
incident**: a capability lands, its call site does not, and the gap is invisible because absence and
zero look alike.

It is also the same family as findings 12/24/51/70 — something silently producing nothing rather than
failing — one level up. There the defect was inside a function; here it is *between* a function and
its caller.

### Fixed

- `arch_recovery_detect.py` now calls `interfaces.propose()` and passes the result to `persist_ir`.
  Deployment artifacts only, so no source parsing and no change to the step's cost tier.
- `persist_ir()` takes `ports`/`wires` and writes an `architecture_interfaces` finding kind.

**Ports** key on the owning component's `scope_locator`, like every other component-scoped finding.
**Wires are edges**, which that shape does not fit — so rather than invent an edge table for a view
nobody has built yet, each wire is attributed to its **source** component, with the target in
`detail`. That is not an arbitrary tie-break: a compose `depends_on` is *declared by* the depending
service, so the source is where the evidence actually lives. An edge list is recoverable without
having committed to a schema before anyone knows what reads it.

Full suite 1877 passed.

### The lesson worth keeping

**"Committed and regression-tested" is not "reachable".** A test that calls a function proves the
function works; it proves nothing about whether anything calls it in production. Neither does a green
suite. The check that would have caught this is the one the presentation session actually ran: *who
calls this, outside its own tests?*

---

**90. The immich holdout: 0/4 by the measure, 4/4 by identity. The instrument failed, not the
detector — and it was pre-registered.**

`immich.md` was created and pre-registered specifically to measure finding 88's per-perspective fix,
after `egeria-workspaces` was spent. Four owner-declared deployment components. Spent once.

### The per-perspective fix works

Four dev iterations on the already-spent `egeria-workspaces`, each exposing the same shape — **a rule
correct in the perspective it came from, applied where its premise fails**:

| iteration | broke | fix |
|---|---|---|
| 1 | `SolutionComponentType` applied to containers | 17-value `SoftwareCapability` vocabulary |
| 2 | *"typically 5-25 components"* merged 59 → 15 | a compose service **is** a component; merge only exact duplicates |
| 3 | model emitted `Third Party Process` (60 drops) | third-party-ness is a **property, not a type** |
| 4 | renamed `quickstart-egeria-main` → "Egeria Quickstart" | in deployment a name is a **fact**, not a description |

Result: `egeria-workspaces` **0/27 → 18/27**, parity with deterministic distillation, *plus* correct
types the deterministic path cannot produce. Prometheus re-confirmed at **9/11** afterwards — no
regression to the logical path across all four.

### The held-out run

| | components | component-set |
|---|---|---|
| deterministic distillation | 30 | **0/4** |
| adjudicated | 30 | **0/4** |

And yet:

```
GT (owners' doc): immich-server   immich-machine-learning   postgres          redis
detected        : immich_server   immich_machine_learning   immich_postgres   immich_redis
```

**All four were found.** Typed `SoftwareService`, `SoftwareService`, `DatabaseManager`,
`DatabaseManager`. The score is 0/4 because component-set matching is **exact string**, and the
differences are a hyphen against an underscore and a `container_name` prefix.

**This was pre-registered**, in `immich.md`, before the run:

> *"the owners' `postgres` and `redis` correspond to compose services named `database` and `redis`,
> whose `container_name` values are `immich_postgres` and `immich_redis`. A detector naming these
> `database`/`immich_postgres` rather than `postgres` is describing the same component; scoring
> should treat that as a naming difference, not a miss."*

Which is the entire value of pre-registration. Said afterwards this is an excuse; said before the run
it is a prediction that came true, and the fixture is the evidence.

### So the instrument is the problem, for the third time

Findings 61, 70 and 74 each found the measure wrong rather than the detector. This is the fourth, and
the sharpest: **for the deployment perspective, component-set-by-exact-name is the *only* applicable
measure** (plan §5a — file-partition scoring cannot apply where components own no files). A broken
sole measure is worse than a broken one among several.

`egeria-workspaces` scored 18/27 only because its ground truth was written *from* `container_name`
values, so the strings happened to align. `immich.md`'s came from the owners' prose, where they
naturally write `postgres`, not `immich_postgres`. **The measure was never testing identity; it was
testing whether the fixture author had read the compose file.**

### What this actually establishes

- **Detection on a deployment target from owner-published prose: 4/4.** Including both
  pre-registered traps — `immich-microservices` correctly absent, and the observability containers
  found but correctly outside the declared set.
- **One real typing disagreement**: `redis` is typed `DatabaseManager` where the ground truth says
  `EventBroker`. The owners describe it purely as *"queue management for background jobs"*, so the
  ground truth is right and the model reached for the more common role of Redis. That is a genuine
  miss, and the only one.
- **The measure needs fixing before any further deployment-perspective work**, and it is a
  measurement change, not a detector change: identity-aware matching that normalises separators and
  `container_name` prefixes, or matching on the compose service a component was derived from rather
  than on its display name.

**91. Identity-aware matching: immich 0/4 → 4/4, and the over-match trap held.**

Finding 90 established the detector found all four immich components and scored 0/4 on exact-string
matching. The fix is in `score.py`, not the detector, and honours a caveat **pre-registered in
`immich.md` before the run** — which is the only thing separating it from tuning on a holdout.

Two normalisations, both cosmetic, neither able to merge distinct things:

- **separators** — `-` and `_` are interchangeable in Compose naming and carry no meaning;
- **the project prefix** — Compose derives `container_name` as `<project>_<service>` with the project
  defaulting to the directory name, so stripping it recovers the service.

**The prefix is taken from the fixture name, not inferred from the data**, so it cannot be tuned.
(First attempt passed the *target*, which carries run suffixes — `immich-adjudicated` — and scored
2/4. The two that still missed were exactly the two needing the prefix.)

| | before | after |
|---|---|---|
| `immich` adjudicated | 0/4 | **4/4**, recall 1.00 |
| `immich` deterministic | 0/4 | **4/4** |
| `egeria-workspaces` | 18/27 | **18/27** — unchanged |

**The over-match trap held**, and it was the real risk: `immich-e2e-postgres` normalises to
`immich_e2e_postgres` and strips to `e2e_postgres`, which is correctly **not** `postgres`. It stays
in the spurious list. A substring rule — which is what a careless "fuzzy match" would have been —
would have matched it and manufactured a false positive while appearing to improve the score.

### What it does and does not establish

**Detection on a deployment target from owner-published prose is genuinely 4/4**, now measurable.
Adjudication and deterministic distillation **tie** — as they did on `egeria-workspaces` — so
per-perspective adjudication has reached parity on this perspective without yet beating it.

**Precision remains poor: 0.18, 18 spurious.** Those are e2e test containers, hardware-acceleration
profiles (`cuda`, `openvino`, `armnn`, `rknn`, `nvenc`) and the observability pair the fixture
explicitly excludes. The hwaccel entries are real compose services that are not backend components —
the same over-proposal problem as everywhere else, in a new costume.

### The measurement lesson, fourth instance

`egeria-workspaces` scored 18/27 for two years' worth of confidence only because its ground truth was
written *from* `container_name` values. `immich.md` was written from the owners' prose. **The measure
had never been tested against a fixture whose author had not read the compose file**, and it failed
the first time one existed. That is what a genuinely independent fixture buys, and it is the argument
for choosing the next one on a dimension nothing in the corpus currently varies.

**92. Why every owner-published fixture is Go: in the JVM world the published architecture and the
code structure are different decompositions.**

The corpus has a blind spot exactly parallel to the perspective one finding 87 exposed: **all three
owner-published logical fixtures are Go** (Prometheus, Kubernetes, Milvus), and every rule built from
them is Go-shaped — `go_subsystems`, the container-directory rule, `package main` entry-point
detection, entry-point type falsification. So a Java fixture was sought. Three candidates checked,
all rejected, and the reason is the same each time.

| project | what the docs publish | maps to code? |
|---|---|---|
| `apache/kafka` | Motivation, Persistence, The Producer, The Consumer, Replication — **protocol concepts** | no; 2 path mentions in the whole design doc |
| `apache/flink` | JobManager, TaskManager, Dispatcher — **runtime processes** | no; all three live inside `flink-runtime`, and there is no `flink-jobmanager` module |
| `apache/pulsar` | architecture docs are in a separate site repo | not checked further |

**The generalisation, which is the useful part.** For the Go projects, the runtime process and the
code directory *coincide*: `cmd/kubelet` is both a directory and the kubelet binary, and Prometheus's
`cmd/prometheus` is the server. Owner-published architecture maps onto directories because in Go it
already is a directory layout.

**In the JVM world it does not.** One `flink-dist` jar runs as a JobManager or a TaskManager
depending on how you start it. The published architecture is a description of **processes**; the repo
is organised by **build module**; and those are two different decompositions of the same system —
which is §4.1's perspective distinction showing up as an ecosystem property rather than a modelling
choice.

**Consequences for fixture selection:**

1. **A JVM project's published architecture is deployment-perspective evidence, not logical.** If a
   Java fixture is built from published docs, it should be scored as deployment — where processes do
   map — not as logical.
2. **A Java *logical* fixture has to be maintainer-written** at module level, like `trellis.md` and
   `egeria-workspaces.md`, because no owner publishes the module decomposition as prose.
3. **The Go corpus was unusually easy, and that has flattered every measurement in it.** Prometheus
   at 11/11 and Kubernetes at 6/6 are real, but they were scored on the ecosystem where published
   architecture and directory structure are the same thing. Nothing yet tells us whether the rules
   survive an ecosystem where they are not.

That third point is the one to carry: **the corpus does not yet contain a case where the published
architecture and the code layout disagree**, and finding 87 is the precedent for what happens when a
whole class of case is absent — every rule looks principled until the first fixture that does not
share the hidden assumption.

**93. Kafka diagnostic: Java is not blind like Go was — but the Gradle parser sees 1 module of 64.**

Run without ground truth (finding 92 established Kafka cannot provide usable owner-published GT), to
answer one question: **how large is the Java hole?**

**My prediction was wrong, and informatively.** I expected the Go situation — most proposers blind.

| signal | result |
|---|---|
| Java imports | **6172 files, 46669 resolved imports, 42822 edges** — works well |
| coupling proposer | **494 logical components** — consumes the import graph fine |
| deployment (compose/Dockerfile) | 31 components, 23 ports, 36 wires |
| code markers | **0** — ast-grep available (imports used it for 93922 matches) but no Java rule matched |
| **Gradle module identity** | **1 module parsed. Kafka declares 64.** |

So Java's problem is **not** the Go problem. Go had three of four proposers producing nothing.
Java's import graph is excellent and the coupling proposer works — 528 components total, which is
over-proposal, the same failure everywhere else, not blindness.

### The real defect: a line-wise parser on a multi-line construct

`gradle_modules()` reads `settings.gradle` line by line. Kafka declares its modules as **one
`include` statement spanning 64 lines**:

```gradle
include 'clients',
    'clients:clients-integration-tests',
    'connect:api',
    ...
```

We parse `'clients'` and stop. **One module of sixty-four**, and the note that follows —
*"1 Gradle modules — not expanded into components in this slice"* — reads like a deliberate scoping
decision when it is actually a parse failure. The scoping decision was real, but it is hiding a bug
underneath it.

**This is finding 5 exactly, in a new file.** There, a line-wise compose reader accumulated three
silent failure modes on the stated assumption that a real parser would reject real-world files;
PyYAML parsed all 25 without complaint. Here a line-wise Gradle reader silently loses 98% of the
modules. The lesson recorded then — *the cheap-parser instinct cost more than it saved, and each
failure was silent rather than loud* — applies unchanged, and I did not recognise it while writing
the diagnostic.

### What this makes the Java work

Much smaller than Go support was, and differently shaped:

1. **Fix the Gradle parse** — handle multi-line/comma-continued `include`, and `includeBuild`. Cheap,
   and it is a bug rather than a feature.
2. **Expand modules into components** — the direct analogue of `go_subsystems`, and the Gradle module
   list is a *better* identity source than Go's directory convention because it is declared rather
   than inferred.
3. **Java code markers matched nothing** on 6172 Java files, which is worth its own look: the rules
   exist, ast-grep ran, and zero matched. Per the standing rule from finding 19 — **a zero is a
   finding, not a pass** — that is a third thing to check, not something to accept.

The import graph, the expensive part, already works.

**94. The code-marker proposer is Python-only, and I said otherwise twice.**

Finding 93 ended with *"Java code markers matched nothing across 6172 Java files, which is worth its
own look: the rules exist, ast-grep ran, and zero matched."* Checked, and **the rules do not exist.**

| rule set | count | languages |
|---|---|---|
| `rules/` — **code markers** | 8 | **Python only** |
| `rules-imports/` — import extraction | 3 | Go, Java, Python |

`code_markers.marker_languages()` returns `{'python'}`. I had conflated the two rule directories:
Python/Java/Go is the *import* set, and I attributed its coverage to the marker set — in **finding 69**
(*"rules are Python/Java"*, now corrected in place) and again in finding 93.

### What it actually means

The code-marker pass is §5.1's "code half" — the proposer meant to find logical components that
manifests and deployment artifacts structurally cannot see. **It has never run on anything but
Python:**

| target | components | code-marker |
|---|---|---|
| `trellis` (Python) | 66 | **5** |
| `prometheus` (Go) | 212 | 0 |
| `milvus` (Go) | 609 | 0 |
| `kafka` (Java) | 595 | 0 |
| `egeria-workspaces` | 164 | 0 |

So every non-Python target has been running **three proposers, not four**, and every measurement in
the corpus was taken that way. Prometheus at 11/11 and Kubernetes at 6/6 were achieved without the
code-marker proposer contributing anything at all.

### Two corrections that matter more than the gap

**Finding 69's diagnosis was right for the wrong reason.** It concluded Go support was missing
because "three of the four proposers are Python/Java/npm-only". The conclusion held and the fix
worked — but one of those three was blind on Go not because Go lacked *rules of its kind*, but
because that proposer has rules for exactly one language. Adding Go marker rules was never on the
list, because I believed Java ones existed and Go was the exception.

**And this is the same shape as finding 92, one layer in.** There, every fixture shared a hidden
property (Go, where process and directory coincide). Here, every *proposer* claim I made shared a
hidden property: I had checked `rules-imports/` and assumed `rules/` matched. **A capability
described from an adjacent directory listing is not a checked capability** — the same class as
finding 89's "committed and regression-tested is not reachable".

The gap itself is smaller than it looks: the marker proposer contributes 5 of 66 components on the
one target where it runs. It is worth knowing precisely because it has been silently absent, not
because it was carrying the result.

**95. Go and Java marker rules — and `$$$` does not match Go call arguments.**

Finding 94 found the code-marker proposer Python-only. Seven rules added: `go-http-server`,
`go-grpc-server`, `go-cli-construction`, `go-client-sql`, `java-spring-service`,
`java-main-method`, `java-scheduled`.

### Every rule verified before use, and the first four were wrong

Finding 19's discipline earned its keep immediately. The natural patterns —
`http.ListenAndServe($$$A)`, `grpc.NewServer($$$A)` — returned **zero on files that plainly contain
those calls**:

| pattern | on a file containing `http.ListenAndServe(":1234", nil)` |
|---|---|
| `http.ListenAndServe($$$A)` | **0** |
| `http.ListenAndServe($A, $B)` | 1 |

**ast-grep's Go support does not match `$$$` against a call's argument list** — not even when
arguments are present. Arity-specific patterns would then silently miss every other call shape. The
working form is structural: `kind: call_expression` with a `regex` on the `function` field, which
matched `grpc.NewServer` 16× in Milvus and `ListenAndServe` 2× in Prometheus, exactly the grep count.

Had these shipped unverified they would have been **eight more silent zeros** — the same failure
finding 94 was about.

Two rules matched nothing in any real repo (`go-client-sql`, `java-scheduled`), so they were given
synthetic known-positives rather than shipped untested: a rule that has never fired is
indistinguishable from a broken one.

### A second silent discard, upstream of the rules

With the rules in place Prometheus still reported **"0 logical components from 8 matches"** — the
markers matched and were then dropped. Cause: `package_roots` was derived from **Python and Node
manifests only**. Prometheus has `web/ui/package.json`, so every root sat under `web/ui/`, and all
eight Go matches fell outside them. Go module roots, Gradle module dirs, and the repo root are now
package roots too.

### Result

| target | code-marker components | note |
|---|---|---|
| `prometheus` | **5 from 8 matches** | 4 merged with `go-subsystem` — *"proposed independently by code, go — confidence raised to 90"* |
| `kafka` | **12** | first Java markers ever produced |
| `trellis` | 5 | unchanged |

Scores unchanged: Prometheus 11/11, trellis 8/11. **The markers' value here is corroboration, not new
components** — independent agreement between two proposers is what the design calls its strongest
signal, and it is now available outside Python.

### The test that caught the change

`test_marker_languages_is_read_from_the_rule_files` asserted `{"python"}`, with a comment saying it
*"breaks (correctly) the day a non-Python rule lands rather than silently staying right by
coincidence."* It did. Updated to `{"go", "java", "python"}` — **not loosened to "any language
present"**, which would have stopped it catching the next silent change.

### Known limitation, recorded not fixed

Java marker components are named `src` (12 of them on Kafka), because attribution walks to a subtree
level that lands on `src` in `module/src/main/java/...`. The Maven/Gradle layout puts real depth
between the module root and the code, and the subtree rule was written for Python and Go layouts
where it does not. The components are real and correctly typed; their names are useless.

---

**96. Disposition: the first output that is advice, and the vocabulary had to shrink to hold the
no-score line.**

§5.5d listed six dispositions, derived from why a user looks at a repo: adopt, avoid, monitor,
upgrade, compare, expand. Building it, only three survived contact with the evidence, plus one the
list didn't have.

- **monitor / investigate / nothing-to-do** follow from role + expectations + the gate.
- **insufficient-evidence** had to be added. Without it, "we could not determine what this is"
  collapses into "there is nothing to do" — the single substitution that would actively mislead,
  because one invites a human to look and the other tells them not to bother.
- **adopt / avoid** need the user's *motivation*. "Should we adopt this" is a different question
  from "what is this", and no amount of repo evidence closes the gap.
- **upgrade / replace** need a second corpus that **does not live in the repo being surveyed** —
  which version we run, which APIs we call, how deeply it is embedded. This is the sharpest of the
  four: the evidence isn't scarce, it's *elsewhere*, and no better surveying of the target repo
  will ever produce it.
- **compare** needs a second resource.

Each undeliverable one is named in `NOT_DERIVABLE` with what it would need. Naming beats omitting:
an absent entry reads as an oversight and gets filled in later from the same evidence by someone
who didn't know it had been considered.

**The failure mode this whole feature invites.** Everything before this was description — here is
what the repo is, here is where its docs are. A disposition is *advice*, and advice attracts
ranking: "which repos should we adopt first" is a maturity score wearing a verb. The defence is the
same one that has worked since §5.5a(c) — separately-named lists, no tally, evidence attached to
each item. `investigate` names the missing artifacts and never counts them, because "3 of 5
present" is the score with a hat on. A test asserts no field name contains score/grade/rating/
count/percentage, copied rather than imported from `tests/test_result_status.py` so weakening one
doesn't weaken the other.

**A recommendation with no target cannot be acted on.** `monitor`'s next step is an Automate
subscription — a mechanism that already exists, not a badge. But a subscription only fires if
there is an active schedule for the *same* `analysis_id`, so one created without a target silently
never fires, and never-firing is indistinguishable from nothing-changed. This is the same family as
findings 63 and 90: an absence that renders identically to a real zero. Hence `next_step_target`,
pinned by test to a real `ANALYSIS_KINDS` key, with a second test asserting
`bool(next_step) == bool(next_step_target)` across every branch. The peer session raised this; it
was not visible from inside the module, because from in here the subscription is just a string.

Commit `2fb02d3`. See also §5.5d-i — the Egeria vocabulary check that came back negative.

---

**97. Measuring the gate's 87% pass-through: my hypothesis was wrong, and the real defect was one
signal being produced by the documentation tooling itself.**

The corpus run (finding in `Backlog.md`, 2026-08-24) showed the recovery gate letting 47 of 54
classified repos through and flagged the ratio for whoever owns it. I predicted `package-manifest`
was the culprit — near-universal, therefore unable to discriminate. **Measured, that is false.**
Every gate decision persists its own reason string with the signals named, so this needed no re-run:

```
carry a non-architectural role   32 of 54     of those: run 25 · skip 7
signals firing across the 25 overrides    package-manifest 19 · deployment-artifacts 15 · entry-points 13
DECISIVE ALONE                            deployment-artifacts 3 · package-manifest 3 · entry-points 1
counterfactual, drop package-manifest     7 skip -> 10 skip   (87% -> 81%)
```

`package-manifest` appears in 19 of 25 but is the sole reason in 3. **The 87% is mostly real
structural evidence and the ratio is approximately right** — the gate was built with containment
semantics precisely so a samples repo with compose files still runs, and on a corpus that is mostly
real software that is what happens. The prediction was a plausible mechanism reasoned from the
aggregate; the aggregate did not contain it.

**But n=3 was worth reading by name, and one of them was wrong.** `OpenLineage/openlineage-site`:
71% doc-shaped files, `docusaurus.config.js` at root, `absence-as-evidence: no Dockerfile/compose/
charts` — and a `package.json`, because **Docusaurus is a Node program**. The gate took that one
manifest as "there is an architecture here" and overrode a skip that the rest of the same
classification argued for. Worse, the discriminator against `opea-project.github.io`, which
skipped, is nothing principled: that one was classified by repo-name convention and never acquired
a `library` role. **Run versus skip came down to Docusaurus rather than Jekyll.**

So the defect is not that `package-manifest` is weak. It is that **`package-manifest` is the only
structural signal the documentation machinery can produce by itself.** A docs site has no
Dockerfile and no entry point of its own; it always has a manifest if its generator is a Node
program. Fix: the site-generator config gets its own signal (`doc-site-generator`) instead of being
prose inside `documentation-dominance`, and the gate discounts `package-manifest` when it is
present. Narrow on purpose — no generator, no discount, which keeps the three real samples+library
repos running.

**A second defect, measured and deliberately not fixed.** `kubernetes/website` — cited in
`recovery_gate`'s own docstring as a repo the gate skips — **runs, and always did.** It carries a
root `Dockerfile` plus nine under `content/*/examples/`, which are documentation *content*: sample
manifests shown to readers. The signal cannot tell an artifact that deploys the repo from one the
repo is teaching about. Tempting to fix with a path-prefix rule; measured first, and across the 15
corpus repos overridden by deployment artifacts, exactly **2** have all of theirs under doc paths
(`docling-serve`, `langchain-opea`) — and both run anyway on entry points and a package manifest.
**Zero gate outcomes change.** A path-prefix heuristic tuned on n=2 with no measured effect is the
"rule derived from one context" trap in finding 94's family, so it is recorded here and in the
docstring, not implemented. The stale docstring claim is corrected, because a rationale that names
a repo it gets wrong is worse than one that names none.

**The transferable part.** Three times now the aggregate has been read correctly and the mechanism
guessed wrongly (findings 73, 79, and this one). What worked again was reading the small-n cases by
name: 25 overrides is a number, but `openlineage-site` is a Docusaurus site, and only the second
one tells you what to change.

---

**98. The gate fix was correct, tested, merged, pushed — and unreachable from the UI. Third
instance of finding 89's rule.**

Finding 97's fix landed and `openlineage_site` re-classified to `skip` on real data, persisted with
`result_status: skipped_by_design` and the full reason as its hint. Correct end to end. Dan then
tried to re-run the classification **from the UI** and nothing happened, which is how the next
defect surfaced.

`repo_classification` has `intent: discovery` in the analysis catalog. The per-card **Run** button
comes from `_loadAnalysisCatalogPanel`, and that function is called at exactly two sites:

```
analysis      8  card + Run
assessment    4  card + Run
discovery     5  NO CARD ANYWHERE   repo_classification, architecture_recovery,
                                    license_classification, maturity, repo_conventions
scouting      3  no card, but the Scouting scan button reaches 2 of them
```

All five discovery-intent analyses are catalogued, step-mapped in `REPO_ANALYSIS_STEP_MAP`, and
runnable through `POST /{slug}/analyses/{id}/run` — that exact orchestrator path worked first time
from a script. Nothing in the UI calls it for them. The Discovery pane renders Survey Definitions /
Questions / Disposition instead, and the only repo Survey Definition that exists, `RepoCoarseScout`,
chains `repo_health` + `repo_language`, so it does not reach them either.

**`architecture_recovery` is one of the five.** The subsystem this entire spike exists to build has
no way to be run from the product's interface.

**Why it stayed invisible.** The pane loads, throws nothing, and renders successfully — it just
renders something else. "I clicked and nothing ran" is indistinguishable from "there was nothing to
run", which is the absence-looks-like-zero shape (findings 63, 90, 97) relocated into the UI.
Scouting is the near-miss that makes it easy to skip past: its analyses are also card-less, but the
scan button covers them, so the pattern looks handled from one sample.

**Third instance of the rule.** Finding 86 claimed ports/wires were wired into the IR when only the
spike had them. Finding 89 generalised it: *committed and regression-tested is not reachable*. This
is the same rule one layer further out — merged, pushed, live-verified against a real repo, and
still not reachable by the person the feature is for. Unit tests, integration through the
orchestrator, and a green suite all pass without any of them touching a call site.

The check that would have caught it is mechanical and cheap: **for every entry in the analysis
catalog, assert some UI call site reaches it.** That is a test over a static map and a set of call
sites, not a browser test. Not written here — `web/` belongs to the presentation session and the
fix is theirs — but recorded so the next person asking "why did nothing happen" starts from the
catalog rather than from the surveyor.

---

**99. The distiller ported cleanly and does not transfer. 3303→358 in the spike; 216→154 on
Milvus, 311→311 on genaicomps.**

Finding 97's pilot established that precision, not coverage, is what blocks architecture recovery:
Milvus proposes ~216 candidates against a published ground truth of 8. The distiller
(`scripts/arch-spike/distill.py`, findings 76–80) measured 3303 → 358 on Kubernetes while holding
6/6 ground truth, so porting it into the product path was the obvious move. Ported, measured
in-process:

```
repo                    in  support  whole  refine   kept   cut   ground truth
milvus                 216       19      0      43    154   29%   8
docling_java             8        1      0       0      7   12%
egeria_workspaces_git   74        0      0       3     71    4%   27
docling_parse            1        0      1       0      0  100%
genaicomps             311        0      0       0    311    0%
```

**Milvus is still 19× its ground truth after distillation, and `genaicomps` is untouched.** The
port is faithful — the filters are the spike's, regression-tested against the same claims — so this
is not a porting bug. The rules do not generalise off the corpus they were built on.

**Why, and it is visible in the by-perspective split.** `genaicomps` keeps **289 deployment**
candidates out of 311; Milvus keeps **120 logical**. The three filters all reason about *path
containment*: support directories, whole-repo roots, and children of classified parents. That is a
good model for logical/physical candidates derived from a directory tree. **Deployment candidates
are compose services** — they are siblings by construction, none contains another, and none lives
under `tests/`. Every filter abstains, and abstaining reads as "nothing to remove". The spike's
corpus was Go and Python monorepos where the logical perspective dominated; `genaicomps` is 289
compose services, a shape the spike never measured.

**A precision rule that can empty the set is a recall bug wearing a precision rule's clothes.**
`docling-parse` yields exactly one candidate, covering the whole repo. `_claims_whole_repo` dropped
it and left **zero components** — a correct single-component answer turned into an empty result.
In the spike this branch never misfired because a whole-repo claim always sat among thousands of
siblings, so there was always something else to keep. Fixed by applying the filter only when
something survives it, and the sole-candidate case is now recorded in the stats rather than
silently spared. Two tests pin it, including the general invariant.

**What this says about the next step.** Deterministic filtering is not going to close a 19× gap on
its own, and the honest reading of the spike's own numbers agrees: Kubernetes went 3303 → 358
deterministically, then **358 → 93 only with the LLM adjudicator**, which is where 6/6 was held.
Distillation was never the whole answer there either; it was the cheap tier that made adjudication
affordable. Porting it was still right — it removes 29% of Milvus's candidates for no marginal cost
and it is regression-testable where a prompt is not — but the entry claiming precision is now
solved would be false. **The adjudicator is the unported half, and it is the half that produced the
result.**

Recorded so the next person does not re-port the distiller expecting the spike's numbers, or
conclude from `genaicomps`' 0% that the port is broken.

---

**100. Milvus is gRPC-first and we could not see it. `.proto`/GraphQL/Thrift recognition, and
counting without listing.**

Dan's framing (2026-08-24) corrected a model I had wrong: *"if we want to see if a repo is
something we can use during runtime, we need to know how to interface to it — what kind of API it
has, maybe language bindings, the number of commands. We don't need the names of every request and
their payloads/signatures — until we want to actually try to use it."*

**A coarse answer often requires a deeper analysis that is then summarised.** I had been treating
finding 99's 154-components-for-Milvus as a precision failure. It is better read as a missing
*summarisation level*: the detail may be needed to compute the answer; it should not *be* the
answer.

`interfaces.propose()` matched OpenAPI by **filename** from a six-entry tuple and never opened the
document, and recognised no IDL at all. Measured on Milvus before the change: exposed ports
recorded, **interface entirely invisible**. After:

```
milvus   31 ports   gRPC 10 documents   18 services   296 rpcs
         proxy.proto 18 · root_coord 76 · data_coord 87 · query_coord 74 · streaming 14 · ...
```

Three facts computed by opening ten documents and discarding them. No signature is retained, and a
test asserts it — an operation name leaking into a port would mean stage-two work done at
stage-one cost.

**The vocabulary check came back positive, and my first reading of it was wrong.** I recorded
0735's `SolutionPort` as having no home for a count — it carries exactly one attribute,
`direction` — and called that a second negative result after `ResourceUse`. Dan pointed out the
obvious: `SolutionPort` is a `Referenceable` (§3.3b, settled by `Confidence` being defined against
`Referenceable` and applying to `SolutionPort` directly), so it carries `additionalProperties` as
`map<string,string>` — which §6.4 *already* names "the documented extension point ... the interim
carrier for anything not yet typed". The count rides there as `operationCount`, stringified because
the map is string-valued, and promoting it to a real attribute later is an upstream type change
rather than a migration of ours. **Reading a type's own attribute list and stopping is the same
mistake as reading `ResourceUse`'s names instead of its descriptions** — the answer was one
inheritance edge away.

Deliberately not `SolutionPortDelegation`, which maps a parent component's ports to its decomposed
children's. That models operations-as-child-ports well and is very likely right for **stage two**;
here it would create one entity per operation, which is the listing the coarse question excludes.

**A test caught a limitation the corpus would have hidden.** The rpc regex was line-anchored, so
`service S { rpc A (Q) returns (R); }` on one line reported 1 service and **0 rpcs** — "an
interface with no operations", indistinguishable from a real zero. Milvus's files are all
multi-line, so a corpus run would have looked perfect. De-anchored to word boundaries.

**Honest limitation, recorded not fixed:** the 296 conflates the public API with internal
coordinator RPCs. For runtime suitability the number a reader wants is `proxy.proto`'s 18. Nothing
currently distinguishes a client-facing interface from an internal one, and inferring it from a
filename would be exactly the convention-as-evidence failure §5.5a(b) forbids.

---

**101. Documentation is the lens, and architecture recovery has never looked through it.**

Dan, closing finding 100: *"you need to look at code through the lens of the documentation — and
good documentation will guide you towards what code to look at for which purpose. Just looking at
the code doesn't provide enough context to easily distinguish between internal and external
communications."*

The Milvus limitation I had recorded as unfixable is the proof. We now report **296 rpcs across 18
services**; the number a reader wants for runtime suitability is `proxy.proto`'s **18**, because
`proxy` is the client-facing service and `root_coord`/`data_coord`/`query_coord` are internal.
Nothing in the code says so. Inferring it from a filename would be convention-as-evidence
(§5.5a(b), finding 66). **Milvus's own documentation says so plainly**, and the same document is
the source of the ground truth this spike scores against — "five core components and three
third-party dependencies", the authors' own words, which is how `milvus.md` was written *by hand*.

**So the system has never done automatically what we did manually to build every fixture.**

And the capability is already here, in the same package:

```
github/doc_locations.py   find_artifact(owner_repo, "architecture") -> in-repo | sibling-repo | doc-site | not-found
                          _ARTIFACT_PATTERNS["architecture"] = [architecture, design-docs, design_docs, solution-blueprint]
surveyors/arch_recovery/  grep for doc_locations / find_artifact  ->  NO MATCHES
```

Architecture recovery reads manifests, deployment artifacts, code markers, imports and co-change.
It does not read the architecture document, on any of the 46 repos the gate approves. Measured
corpus context makes that worse rather than better: **31% of located artifacts are not in the repo
at all** (43 of 140 across 25 of 60 repos), so a code-only reader is structurally blind to a third
of what exists, and `doc_locations` is the thing that already solves that.

**Why this outranks the remaining precision work.** The unported adjudicator buys precision by
asking a model to judge candidates. The documentation states the answer. Finding 92 recorded that
every owner-published fixture is Go because in the JVM world the published architecture and the
code diverge — but where a doc exists and is current (findings 65-68's version-correlation
discipline applies), it is the highest-provenance evidence available and it is free. `provenance:
owner-published` already exists as a class in the fixture format; nothing in the running system
can produce it.

**The shape of the work, not yet built:** resolve `architecture` via `find_artifact` during
recovery, and use it as a *lens* rather than as an oracle — to rank and label what the detectors
already propose (which of these 216 candidates does the document name? which interface does it call
the client API?), never to replace them. A document that disagrees with the code is a finding in
its own right (findings 65-67: correlate doc version against code version), not a silent override.

Recorded here rather than built: it is a design change to the detect step's inputs and it needs its
own entry, cost estimate, and a decision about staleness handling.

**MEASURED 2026-08-24, after the presentation session objected that "documentation states the
answer" was n=1 — and the objection was right.** Milvus is the only repo this was argued from, and
worse, its ground-truth fixture was transcribed *from that same document*, so the doc agreeing with
the fixture is not independent confirmation. Measured across all 46 gate-approved repos, using the
architecture-artifact resolution already persisted by `repo_classification`:

```
gate=run repos                             46
  architecture doc located                 13     in-repo 4 · sibling-repo 9
  not-found                                 2
  never looked — not in the role's set     31
```

Three things fall out, and they pull in different directions:

- **The claim is not universal.** At most 13 of 46 today. "Documentation states the answer" is a
  premise that holds for a minority of the corpus, and designing as though it held generally would
  be the same error as assuming Perspective could drive dispatch.
- **But 9 of the 13 are `sibling-repo`** — the architecture document lives in a *different
  repository* from the code. A code-only reader cannot reach those by any amount of better parsing;
  it is not a precision problem, it is a wrong-corpus problem. This is the strongest form of the
  argument and it does not depend on Milvus at all.
- **The 31 are "never looked", not "no doc".** `EXPECTED` lists `architecture` only for
  `application` and `middleware`; `library`, `tool`, `samples`, `tutorial` and `documentation` do
  not ask for it. That is defensible for the *expectation report* — a library is not deficient for
  lacking an architecture doc — but it means the 31 are an unmeasured population, not a measured
  absence. Reusing an expectation set built to judge completeness as if it were a survey of
  availability is the one-identifier-two-purposes shape again.

So the honest scope: documentation-as-lens is worth building for the ~13 repos where a document is
already located, the sibling-repo majority is the case that justifies it, and the 31 need a
separate cheap probe before anyone claims a corpus-wide number.

---

**102. The documentation lens works — and the sibling-repo case I argued was its strongest
justification is where it performs worst.**

Finding 101 established that architecture recovery never reads the architecture document, and
argued the sibling-repo majority (9 of 13 located docs live in a *different* repository) was "the
strongest form of the argument" because no amount of better parsing reaches them. Built it,
measured it across every gate-approved repo with both a located document and recovered components:

```
repo                    doc location   comps  documented
milvus                  in-repo          206          15
egeria_workspaces_git   in-repo           73          12
amundsen                in-repo           43           4
docling_java            sibling-repo       8           2
genaicomps              sibling-repo     312           2
docling_eval            sibling-repo      34           1
ryoma                   in-repo           31           0
marquez / openlineage / workshops / trellis / egeria_python_git / docling_parse
                        sibling-repo   11-124           0
sqlglot / unitycatalog  doc-site       11, 16           0   (located, not readable)

at least one match: 6 of 15
```

**in-repo: 3 of 4 work, and work well. sibling-repo: 3 of 9, all weakly. My reasoning was
backwards.** A sibling *documentation repository* is a whole website; `doc_locations` legitimately
resolves it to a generic pointer at the repo rather than to an architecture page, so what gets read
is navigation and prose. `openlineage` yielded 2 candidate terms, `marquez` 5, `trellis` 0. The
in-repo case wins because the located artifact is an actual design-docs directory.

**Where it works, it is the best result this project has produced.** Milvus: 206 candidates → **15
documented**, and the 15 are the architecture — `proxy`, `rootcoord`, `datacoord`, `querycoord`,
`indexcoord`, `datanode`, `querynode`, `indexnode`, plus `pulsar` and the shared infrastructure
(`msgstream`, `tso`, `flowgraph`, `storage`). Against the authors' own "five core components and
three third-party dependencies", the lens recovered the real partition out of 206 by reading what
they wrote. Distillation managed 216 → 154 on the same repo; the summariser reported 24 runnable
units. **The document did in one pass what two deterministic tiers could not.**

**It stays a lens.** It adds no component, removes none, assigns no type, and carries no score — a
test asserts `DocLens` has no field whose name contains type/confidence/score/rank/grade. A name
the document uses that nothing proposed is reported as `undetected`, a disagreement, never adopted.

**Three restraints that cost real work and are worth keeping:**

* **Bounded reads, reported.** Milvus's `docs/design-docs` holds 78 markdown files one level down,
  each an API call. `MAX_DOC_FILES = 25`, overview-shaped filenames first, and the note says what
  was dropped — because an unread document is not a silent document.
* **Located ≠ consulted.** `doc-site` outcomes are located and unreadable from here; `consulted` is
  a separate property from having an outcome. Collapsing them would report "the docs say nothing"
  for a repo whose docs were never opened.
* **The date travels.** `OpenLineage`'s architecture document is dated **2023-11-03** — measured.
  Findings 65-68's version-correlation discipline is not hypothetical here.

**A bug the tests caught that the corpus would have hidden:** `_STOPWORDS` compared raw strings
against normalised terms, so every multi-word entry in it ("table of contents", "getting started",
"see also") silently did nothing. The list looked right and half of it was inert.

**`undetected` is not yet usable as a finding.** On Milvus it is 506 terms — section headings from
25 design documents, not component names. It is meaningful only when the located artifact is an
architecture *overview* rather than a corpus of design docs, and nothing currently distinguishes
those. Reported with that caveat rather than presented as a list of things we failed to detect.

---

**103. Wiring the lens found a storage trap: annotating another step's findings under the same kind
makes them invisible.**

`repo_arch_lens` is now a step, between `repo_arch_coupling` and `repo_arch_summary`. Its own step
rather than part of detect, for three reasons — its cost is `api` where detect is `download` and
summary is `none`; the document changes on its own cadence and often lives in another repository;
and, decisively, **a failed document fetch inside detect would leave detect succeeding with the
labels quietly absent**, whereas as a step it carries its own reader state and the 33 of 46
gate-approved repos with no architecture document get an explicit answer instead of a non-event.

**The trap.** The first version wrote its labels back into `architecture_recovery`, on the
reasonable instinct that a label belongs beside the component it describes. Then:

```
before wiring   milvus: 218 candidate components, 31 third-party
after wiring    milvus: 203 candidate components, 22 third-party
                        ...exactly the 15 scopes the lens had just labelled
```

`upsert_finding` **appends**, but `query_findings` returns only the rows at `MAX(surveyed_at)` for a
`(slug, kind, scope)`. Writing a label with a newer timestamp therefore made that scope's
`component` finding unreadable — `client/index` returned `documented_by` and nothing else. **No row
was lost; they stopped being visible.** A backup would not have shown a problem, and a reader would
simply have seen a smaller architecture.

So a step that annotates another step's output must write under **its own kind**, scope-keyed —
`architecture_doc_lens`. The same shape as ports living in `architecture_interfaces`, which the
summariser had already tripped over from the other direction (finding 100: reading one kind when
the subject spans two). **Append-only storage with latest-run reads has both failure modes, and
neither raises.**

Caught only because the numbers moved by exactly the number of labels written. That is worth
naming: the check that found it was not a test but a **conservation expectation** — annotating
should not change a count it does not own.

**Three smaller things the wiring surfaced, all the same family:**

* `_STOPWORDS` compared raw strings to normalised terms, so every multi-word entry ("table of
  contents", "getting started") was inert. The list looked correct and half of it did nothing.
* A test fake used `terms or ["proxy"]`, turning an explicit `terms=[]` back into a populated list —
  so the doc-site case silently asserted the opposite of what it claimed. Empty-versus-absent, in
  four characters of test helper.
* A test patched `AL.ad.apply` by bare assignment rather than `monkeypatch`, and leaked into the
  next test. Same shared-state shape as the conftest schema collision, one layer up.

**Recorded, not resolved:** `repo_arch_lens` is the **third** exception to "discovery is the
zero-fetch derivation tier", after `architecture_recovery` and `repo_classification`. Three
exceptions is where that description stops being a rule and becomes an intention. Flagged in
`analysis_catalog.yaml`, in the registry entry, and in the test that enumerates the exceptions —
the next addition should be a decision about the rule, not a fourth entry.

---

**104. The lens across the corpus: 1108 candidates → 36 documented, and where a document lives
predicts almost everything.**

`repo_arch_lens` run as a registered step over every repo with recovered components (16), labels
persisted:

```
repo                     comps  labelled  doc location
milvus                     206        15  in-repo
egeria_workspaces_git       73        12  in-repo
amundsen                    43         4  in-repo
docling_java                 8         2  sibling-repo
genaicomps                 312         2  sibling-repo
docling_eval                34         1  sibling-repo
marquez / monocle / openlineage / workshops / trellis / ryoma /
egeria_python_git / docling_parse / sqlglot / unitycatalog
                        1-124         0  sibling-repo, doc-site, or none

TOTAL                     1108        36        labelled: 6 of 16
```

**Every in-repo document fired, and fired well: 3 for 3, 31 of the 36 labels.** Every sibling-repo
document that fired did so weakly (2, 2, 1) and six produced nothing. Doc-site produced nothing by
construction — located, unreadable from here.

This confirms finding 102's correction at corpus scale, and the corrected version is worth stating
plainly because the original claim is the intuitive one: **a document in a sibling repository is
easy to *locate* and hard to *use*.** `doc_locations` resolves a sibling documentation repo to a
pointer at the repo, because that is the honest answer to "where are the docs" — but a whole
documentation website is not an architecture description, so what gets read is navigation. The
in-repo case wins because `docs/design-docs` is the thing itself.

**The ceiling is recovery coverage, not the lens.** 16 repos have components at all, against 46 the
gate approves. The lens cannot label what was never recovered, so its reach is bounded by a
different subsystem's coverage — the honest reading of "1108 → 36" is that it is a strong result on
a third of the corpus, not a corpus-wide one.

**What would raise it, in order of expected value:**

1. **Resolve to an architecture *page* inside a sibling docs repo**, not to the repo. Nine of
   thirteen located documents are sibling-repo and six of those yielded nothing; this is where the
   unclaimed value is, and it is a `doc_locations` change rather than a lens change.
2. **Run detect on the 30 gate-approved repos that have no components yet** — bounded and known at
   roughly 28s each, no clone.
3. Doc-site fetching. Last: it needs an HTTP fetcher for arbitrary sites, a new cost tier, and
   `doc_locations` already warns that a homepage field is not proof of a page.

---

**105. Three wrong published numbers from the same query mistake, the third while checking the
second.**

`query_findings(slug, kind)` defaults to `scope_locator=""` — whole-resource — and a step may
persist **metrics rather than findings**. So a bare findings query answers *"nothing at
whole-resource scope in the findings table"*. It does not answer *"this never ran"*, and reading it
as though it did has now produced three wrong numbers in two days:

```
architecture recovery   published "3 of 46"    actually 16   (scope-keyed; finding 97's entry)
website_ingestion       published "0 of 60"    actually  6   (writes metrics, not findings)
architecture_doc_lens   reported  "0"          actually 36   (scope-keyed)
```

The third is the instructive one. It came from the verification script written to check the
second — after the presentation session correctly pointed out that a findings-only query cannot
establish absence. The correction was understood, and the very next query repeated the other half
of the same mistake.

**A count is not an absence unless the query covers every shape the answer could take.** Findings
and metrics are two tables; whole-resource and scope-keyed are two addresses. Four combinations, and
a default query reaches one of them.

**The `website_ingestion` defect underneath was larger than the miscount**, and belongs to the
presentation session: its reader returned `chunks/pages_fetched/pages_found/pages_failed` as 0 when
nothing was persisted, and `metrics` render mode lays every key out as a labelled row — so 54 cards
read "we scanned the site and found nothing" about a site nobody had looked at. `NEVER_RUN` already
described the right behaviour and nothing emitted it. They wrote the guard for the *class* rather
than the instance and it immediately found a second case in `rag_ingestion`.

Their framing is worth keeping: this is the exact twin of the render-mode fix made the same morning,
where a card said "no results" while holding real data. **Same seam, opposite directions, one day
apart — so the reader/render boundary is where this class lives, not any individual analysis.**

---

**106. Documentation is plural, and one location was the wrong model. 36 → 49 documented, and the
repo that motivated the work went 0 → 5.**

Dan, on being told the plan was "resolve sibling-repo to a page": *"there is an assumption that may
be worth considering — you are assuming that there can only be a single doc page. In practice that
may not be true... perhaps record doc sites as we find them rather than assume there can only be
one?"* And then: *"consider not just repos that call themselves documentation but also tutorials
etc"*, and *"they may not be repos — often just web sites."*

All three were right, and the data was already there. `DocLocations` has always been *"a bag of
findings, not a verdict"* (§5.5a(c) point 4) — it holds in-repo dirs, a homepage, sibling repos AND
README links. **`find_artifact` was the thing collapsing it to one**, first match wins.

```
                        sources found        before -> after
OpenLineage/OpenLineage   1  ->   6     labelled  0 -> 5
milvus-io/milvus          1  ->  12     labelled 15 -> 22
monocle                                 labelled  0 -> 1

corpus                                  36 -> 49 documented, 6 -> 8 repos of 16
```

Three changes, each traceable to one of Dan's points:

* **`find_artifacts` (plural)** returns every location, ordered as before, so
  `find_artifacts(...)[0]` is exactly what `find_artifact` returned and no caller changed. The lens
  now reads *every readable source* rather than the first — "most specific by resolution order"
  says nothing about which document describes the architecture, and OpenLineage's first sibling of
  five yielded nothing while its siblings collectively yielded 5.
* **Sibling repos are searched properly.** The old code tried `sibling_repos[0]` only, and only its
  ROOT — which is why every sibling answer in the corpus was a bare pointer at a repo. A
  documentation website keeps pages under `docs/` or `content/`, so the one place we looked was the
  one place they are not. Now: every sibling, root then its own doc dirs.
* **Tutorials and workshops count.** `_SIBLING_NAME_PATTERNS` went from 6 entries to 19, adding
  tutorial/workshop/examples/learn shapes. It immediately found `OpenLineage/workshops`,
  `milvus-io/milvus-tutorials` and `milvus-io/milvus-workshop`. A name that holds nothing costs one
  shallow search; a name never tried costs the document.

**And a documentation site is now a first-class source rather than a fallback.** A `doc-site` result
— a declared homepage, or an off-site link the README itself offers, like Milvus's
`milvus.io/docs/tutorials-overview.md` — is recorded in `DocLens.sources` even though it cannot be
read from here. That is the difference between "no documentation" and "documentation we have not
ingested", and it is precisely what the doc-site ingestion recommendation attaches to.

`sources` and `read_sources` are kept separate for the same reason `consulted` exists: **located and
consulted are different states**, and now that there are a dozen locations the distinction carries
more weight, not less.

**What did not move, and is the honest remainder.** `marquez`, `trellis`, `workshops`,
`ryoma`, `egeria_python_git`, `docling_parse` still yield nothing, and `sqlglot`/`unitycatalog`
remain site-only. Reading more sources raised the ceiling; it did not change that a documentation
website read as markdown is mostly navigation. The next real gain is ingesting sites, not resolving
harder.

---

**107. The ingest offer needs four states, not a boolean — and two of them are the system being
right already.**

`repo_arch_lens` now emits a `RequestForActionAnnotation` when it locates documentation sites it
cannot read: *"ingesting would make them answerable"*, pointing at `repo_website_ingestion`. It is
the most actionable negative result the chain produces — we know a document exists, we know its
address, and we know we cannot read it from here.

**The naive version would have been wrong on a third of the cases it fires for.** "Has this site
been ingested?" is not a yes/no:

```
ingested        2 of 60    sqlglot's site is 97 chunks in web_docs_sqlglot_com
declined        4 of 60    self_published (3) / code_host (1)
not-attempted  54 of 60
attempted       0          ran and got nothing — real, just unobserved so far
```

`declined` is the state worth naming. `repo_website_ingestion` refuses on purpose when a site is
`self_published` — the repo *builds* it, so its source is already ingested in a better form — and
when the "site" is only a `code_host` URL. Offering to ingest either would be **re-opening a
decision the system already made correctly**, which is worse than staying quiet: it teaches a reader
that the recommendations have not been thought through.

And `ingested` would have been the embarrassing one. `sqlglot` is one of only two repos in the
corpus whose architecture sources are *all* unreadable sites — precisely the case the offer is for
— and its site was ingested days ago. The naive rule would have fired hardest exactly where it was
most wrong.

**Read from metrics, not findings**, and a test asserts `ingestion_status` never calls
`query_findings`. `repo_website_ingestion` writes metrics and no findings at all, so a findings
query reports nothing for a step that has run six times. That is finding 105 applied rather than
re-learned — the presentation session caught my "0 of 60" claim, and this is the first code written
after it that had to get the same distinction right.

**It is an offer, not a finding, and the prose says so:** *"nothing is wrong with the repository."*
A project that publishes its documentation on a website has done nothing wrong, and an RFA that
reads as a defect would make the funnel's most useful signal feel like criticism.

Verified live: `unitycatalog` gets the offer, `sqlglot` gets none.

**What this does not do, deliberately.** It does not ask. An interactive session may *render* it as
a question at the point the absence appears — the presentation session's better formulation is to
put the ask where the absence already is, in the empty state, rather than in a prompt. A scheduled
survey has nobody to ask and must not block. Both read the same annotation; only the rendering
differs. That constraint is in the Backlog under "Doc-site located but unreadable" and applies to
every future step that would benefit from a human answer.

---

**108. Acting on the recommendation ingested three junk sites, including 3096 chunks of another
project's documentation.**

The offer from finding 107 said "ingest this project's documentation site". Acting on it, on a
deliberate mix of three real documentation sites and three URLs that looked wrong, **all six were
ingested**:

```
GOOD  kafka           1169→ no: 1 chunk / 1 page   kafka.apache.org
GOOD  polaris         1169 chunks / 16 pages       polaris.apache.org
GOOD  deep_causality    28 chunks / 1 page         deepcausality.com
JUNK  docling_mcp        1 chunk                   static.pepy.tech/badge/docling-mcp/month
JUNK  docling_serve      3 chunks                  quay.io/repository/...
JUNK  docling_nlp     3096 chunks / 46 pages       docs.astral.sh/uv/        <- the uv package manager's docs
```

`repo_website_ingestion` had exactly one guard, `is_code_host`, for a homepage pointing back at the
forge. Nothing else. And `repo_homepage` falls back to manifest and README URLs when GitHub declares
no homepage — **a README's first link is very often a badge** — so these are not exotic inputs, they
are what the corpus contains. Of 54 eligible repos, the sample of six contained three bad ones.

**The `docling_nlp` case is the one that matters and no host list catches it.** `docs.astral.sh/uv/`
is a perfectly good documentation site. It is simply not *this project's*, and 3096 chunks of it
went into a collection a reader would reach when asking about docling. A blocklist answers "is this
a documentation host"; the actual question is **"is this documentation site this project's"**, which
needs a relatedness check: a shared token between the site host and the owner/repo name, with the
parts every host has (`docs`, `io`, `com`, `github`, `readthedocs`) removed so they cannot carry the
match. `kafka`/`kafka.apache.org`, `deep_causality`/`deepcausality.com` and
`docling`/`docling-project.github.io` all pass; `docling-nlp`/`docs.astral.sh` does not.

**Two things that only came out of running it rather than reasoning about it:**

* **The host-keyed collection naming contained the damage.** Junk landed in
  `web_docs_static_pepy_tech` and `web_docs_docs_astral_sh`, not inside a docling collection — so it
  is identifiable and separable. That naming decision was made for an unrelated reason (several
  repos in one project share one site) and paid off here.
* **An existing test caught an ordering bug in my fix.** I put the relatedness check before the
  self-published check, and `test_repo_that_publishes_its_own_site_records_the_skip` failed:
  a marker in the repo's own file inventory is **direct evidence** that this project publishes this
  site, and it must outrank a name heuristic. A project whose site is named nothing like its repo
  would otherwise be refused as somebody else's while we hold proof that it is theirs. Final order:
  `no_homepage → code_host → non_doc_host → self_published → unrelated_host`, pinned by a test that
  reads the run method — the first version read the whole class and matched `self_published` in its
  docstring, which sits above every guard and made the assertion meaningless.

**Refusals are stated, never silent.** `unrelated_host` says which URL and which repo, and that if
the project really does publish there it is worth correcting. A refusal that looked like an absence
would be this codebase's oldest failure wearing new clothes.

**Left as it is, deliberately:** three junk collections exist in the store from this pilot. They are
small, host-keyed and obviously named, and deleting from a live store is not something to do without
asking.

---

**109. Closing the loop: the lens can now read what ingestion stored. 49 → 60 documented, and the
two site-only repos stopped being permanent zeros.**

Ingestion existed so *Chat and Understanding* could answer from a project's documentation. It made
that documentation available to everything **except the step that most needed it**: `sqlglot`'s site
was 97 chunks in `web_docs_sqlglot_com` while `repo_arch_lens` reported *"located, not readable"*.

Bulk-ingested the 38 repos whose homepage passes the finding-108 guards, then taught the lens to
read a collection when a located site is unreadable:

```
ingested                25 of 60      refused: self_published 13 · non_doc_host 2
                                               unrelated_host 1 · code_host 1
web_docs collections    20

lens, corpus            49 -> 60 documented       11 of 17 repos (was 8)
   sqlglot               0 -> 6      <- was a permanent zero: site-only, unreadable
   openmetadata          0 -> 4
   unitycatalog          0 -> 1
```

**Ingested text needs a weaker test, and saying so is the point.** Rendered HTML converted to text
has no markdown emphasis, so `extract_terms` — which keys on headings, bold and code spans — found
twelve terms in sqlglot's ingested site and every one was a code fragment. The question has to
change from *"what does this document emphasise"* to *"does this document mention this component"*,
which needs no markup: word-boundary matched, four characters minimum, generic names excluded (a
component called `index` is not evidenced by a site containing the word "index").

That is genuinely weaker evidence and is labelled as such — `EVIDENCE_MENTIONED` versus
`EVIDENCE_EMPHASISED`, carried per component. Collapsing them would let a reader over-trust the
weaker one, and the whole value of this chain is that its claims can be checked.

**A property keyed on the wrong thing, found by running it.** `DocLens.consulted` returned
`bool(terms)`. The moment ingested sites became readable that was wrong: `unitycatalog` read 26
chunks and reported *"document not consulted"*, because HTML text yields no markdown terms.
**Extracting nothing from a document is not the same as never opening one** — the same distinction
`consulted` was written to make, broken by the arrival of a source it did not anticipate. Now keys
on `read_sources`.

**Two ingestion defects found and left recorded, not fixed:**

* **`milvus`: 400 pages fetched, 0 chunks stored, `ingested: True`, after 685 seconds.** A
  contradiction on its face, and the repo whose lens result would most benefit. `ingested: True`
  with `chunks: 0` is absence-versus-zero at the ingestion layer.
* **`egeria-project.org` was ingested three times in one run** — once each for `egeria_git`,
  `egeria_python_git`, `egeria_workspaces_git`, 6018 chunks and 187 pages every time, ~175 seconds
  total. Collections are host-keyed precisely so sibling repos share one, but the *work* is not
  deduplicated across repos within a run.

**And one guard limitation worth knowing before trusting it:** `trellis` → `egeria-project.org` is
refused as `unrelated_host`, and it probably should not be — trellis *is* an Egeria project. The
relatedness check compares names and knows nothing about project families. It fails safe (a stated
refusal, not a silent skip) but it is a real false-positive class.

---

**110. A site is now ingested once, not once per sibling repo — and the first version of the fix
re-ingested anyway.**

`site_collection_name`'s own docstring said a site should be *"ingested once and every repo pointing
at it"* shares the copy. The **naming** did that; nothing enforced it. Measured:
`egeria-project.org` fetched and embedded **three times in one batch** — 187 pages and 6018 chunks
each, ~175 seconds — because host-keying dedupes the *destination* and not the *fetch*.

**Keyed on the collection's state, not on a within-run memo**, and that choice matters:
`SurveyOrchestrator.run()` is per project, so there is no "run" spanning sibling repos to memoise
against. A state-keyed check also holds when the repos are surveyed days apart, by the scheduler, or
one at a time from the UI.

```
before   egeria_git 79s · egeria_python_git 46s · egeria_workspaces_git 49s
after    0.4s · 0.2s · 0.2s
```

**The first version excluded the repo itself, and re-ingested in front of me.** Two siblings skipped
in under a second; the third then spent **103 seconds re-fetching the site its own record said was
current**. Skipping writes a zero-chunk record over whatever that repo held, so after two skips only
the third still carried the evidence — and run last, it found nobody else and started fetching. The
question is *"has this collection been ingested recently"*, not *"did somebody else do it"*.

Worth noting what caught it: not a test, but **running the exact three-repo case that motivated the
work**. A unit test with two repos would have passed.

**Two conditions the check deliberately does not treat as "done":**

* **A run that stored nothing.** `milvus` recorded a completed ingest with **zero chunks after 400
  failed fetches**; treating that as already-done would make a bad run permanent.
* **A stale one.** 24 hours, stated as a constant with its reasoning — a documentation site does not
  change hourly, and a daily scheduled survey should re-ingest once a day rather than once per repo.

**Skipping the fetch must not skip the wiring.** The query router searches a repo's *own* collection
list, so the skip still registers the collection on this repo — otherwise the saving costs the
thing the ingest was for. A test pins it.

**And a third instance of one shape, in one day.** `_note` filters its props through a fixed
allowlist, so `ingested_by` was **dropped silently** and the attribution came back empty. That is
`operationCount` in `arch_recovery/persist.py` this morning, and the port/wire `detail` before it:
**a curated field list that discards anything added upstream, without saying so.** The list stays
explicit — an unbounded passthrough would let anything into the record — but the hazard is now named
at the point it bit.

---

**111. Look before you crawl: 685 seconds becomes 1.7, and the first version of the check would
have refused a site that works.**

Dan asked what ingestion assumes, and whether content should be staged and profiled before deciding
how to ingest it. The honest answer was that ingestion **fetched, chunked and embedded in one pass
with no decision point** — so `milvus` spent **685 seconds finding 400 pages by sitemap and failing
all 400 fetches**, and nothing could notice until it was over.

`ingestion/site_profile.py` is the cheap tier that gates the expensive one — the shape architecture
recovery already uses, and the one thing ingestion had no version of. Two questions, because they
are the two answerable from **one or two fetches**:

```
milvus.io              1.7s   unreachable            (was 685s)
sqlglot.com            0.4s   ok, 34659 chars
polaris.apache.org     0.2s   ok
docs.unitycatalog.com  0.1s   unreachable
```

**The first version refused `sqlglot`, which ingests 97 chunks perfectly well.** Its landing page is
a 138-byte `meta-refresh` stub, `discover_pages` follows it, and my profiler did not — so the
profile said "no readable text" about a site whose text is one hop away. `follow_meta_refresh`
already existed for exactly this reason and I did not use it.

**The rule that generalises, and it is not a detail: a profile must model what the crawl actually
does.** Profiling with a *more* capable fetcher clears sites the crawl then fails on. Profiling with
a *less* capable one refuses sites the crawl would have managed. Both are worse than not profiling,
because both are **confident**. The fetcher is passed in by the caller for that reason, and a test
asserts it.

**What caught it was checking against reality rather than against invented cases.** I profiled every
site that had actually ingested content — 18 of them — and asked whether any would now be refused.
The answer after the fix is **zero**; before it, `sqlglot` was one. A unit test written from
imagination would have used a normal HTML page and passed.

**Two questions, not five.** Reachability and text yield are answerable from one page. What *kind*
of documentation it is (which should select a chunking profile), how much is boilerplate, and
whether it duplicates something already held are real and remain in the Backlog — each needs several
pages and a judgement. Building the cheap half first is the entire point of a cheap tier.

**Reached-and-empty stays distinct from never-reached**, which is what `no_pages_fetched` was split
out for one finding ago: `no_extractable_text` is a `no_signal` with `known_positive=True` because
we reached the site and it told us; `unreachable` is `unverified` because we never got to look.
