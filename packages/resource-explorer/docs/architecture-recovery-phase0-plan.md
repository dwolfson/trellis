# Architecture Recovery — Phase 0 Spike Plan

**Status:** plan, ready to execute.
**Date:** 2026-08-19
**Parent:** `docs/architecture-recovery-design.md` §10 Phase 0.
**Question Phase 0 answers:** *can deterministic detectors find real component boundaries?*
Nothing else.

---

## 0. Three corrections to the parent design, found while planning this

All three were discovered by checking the code and repos rather than assuming, and all three change the
plan. (a) and (b) change how §5.5's validation signals get computed — **the parent doc's §5.5 is wrong
as written and is corrected**; (c) adds a Phase 1 requirement the parent design does not have.

**(a) `project_code_relationships` cannot produce an import graph.** Its schema (`registry.py:608`) is
`relationship_type` / `source_name` / `target_name` — **name-to-name, with no `file_path`** — and the
default and only observed type is `inherits_from`. Imports are not captured at all. §5.5 claimed this
table as the source for import coupling; it is not.

Two ways forward, and Phase 0 takes the second:

1. Join `project_code_relationships` × `project_code_symbols` on symbol name to recover path pairs
   (`project_code_symbols` *does* carry `file_path`). Free, but yields an **inheritance** coupling
   graph, not an import graph — a much weaker boundary signal.
2. **Extract imports directly with ast-grep during the spike.** Import statements are among the most
   trivially matchable constructs in any language, and ast-grep is being stood up in Phase 0 anyway,
   so the marginal cost is near zero. This also gives the real signal rather than a proxy.

**(b) `project_commits` cannot produce co-change coupling.** Its schema (`registry.py:548`) is
`sha` / `message` / `author_name` / `author_email` / `committed_at` — **no per-file change data**.
Co-change requires `git log --name-only` or PyDriller, both of which need a real clone.

In Phase 0 this costs nothing, because Phase 0 reads **local checkouts already on disk** rather than
downloading anything (§2). It does confirm that the `git_clone_root` provider (Phase 0.5) is a genuine
prerequisite for anything beyond the spike, rather than a convenience.

**(c) Vendored code is tracked in at least one target, and it breaks identity precedence 1.** See §3a
— found while grounding T1, and a Phase 1 requirement rather than a spike detail.

---

## 1. Scope discipline — what Phase 0 runs, and what it does not

Phase 0 answers exactly one question, so it runs **only what informs the partition**:

| In scope | Why |
|---|---|
| **Exclusion pass** — `.gitignore`-aware + vendor denylist | runs *first*; without it T1 is unscoreable (§3a) |
| Package manifests — `pyproject.toml`, `package.json`, `settings.gradle` | identity precedence 1 (§8.2), and the monorepo partition |
| Entry points — `[project.scripts]`, console_scripts, `bin`, `Main-Class` | component existence |
| `Dockerfile*`, compose, k8s | deployment-unit boundaries and wires |
| Web/CLI/worker framework markers via ast-grep | component *type*, and boundaries where no deployment artifact exists |
| Import extraction via ast-grep | validation signal 2 |
| `git log --name-only` over local clones | validation signal 3 |

**Explicitly out of scope**, despite appearing in §5.6: `scc`, `lizard`, `syft`, `trivy`, licence and
SBOM work. These produce **metrics, not boundaries**. None of them would change the partition, and
building them now is how a spike turns into a project. They belong in Phase 1.

Also out of scope: any LLM. The §10 exit criterion is explicitly *detector-only* — introducing
distillation here would make the result unfalsifiable, since a good enough LLM can paper over bad
detectors and we would learn nothing.

---

## 2. Execution shape — throwaway, standalone, local

**No RE integration.** No `StepInfo`, no `analysis_catalog.yaml` entry, no registry writes, no Egeria,
no zipball, no Prefect. A directory of standalone scripts reading local checkout paths and writing JSON
to disk.

This matters for two reasons. It keeps the spike honest — integration work is where spikes quietly
become commitments — and it means a negative result costs nothing to discard, which is the entire point
of running Phase 0 before Phase 1.

```
scripts/arch-spike/           # throwaway; not part of the package
  detect.py                   # → ir/{target}.json
  imports.py                  # → signals/{target}-imports.json
  cochange.py                 # → signals/{target}-cochange.json
  score.py                    # ground truth × 3 signals → report
  rules/*.yml                 # ast-grep rules

tests/fixtures/architecture-ground-truth/   # NOT throwaway
  README.md                   # the three pre-registration rules
  _TEMPLATE.md
  {target}.md                 # hand-written, committed first — see §4
  validate.py                 # parses + checks types, globs, blueprint refs
```

**Ground truth deliberately lives outside the spike directory.** The scripts are throwaway; the
partitions are not. Once Phase 1 has real detectors, these become regression fixtures, so they should
survive the spike being deleted.

Local checkouts, all present under `/Users/dwolfson/localGit/egeria-v6/`.

---

## 3. Targets — chosen to test different things, not to be representative

Grounding each target changed the set substantially from the parent doc's "RE and `egeria-workspaces`".

**First, a checkout correction.** `egeria-workspaces` and `egeria-workspaces-fs` are **the same repo**
(`dwolfson/egeria-workspaces`), not two targets. `egeria-workspaces` is ~6 months stale (last commit
2026-02-05); `egeria-workspaces-fs` is current and is the bind-mounted one. **Use `-fs`.** Running both
would double the work and score a stale snapshot as if it were an independent target.

### T1 — `egeria-workspaces` (via the `-fs` checkout) — **the richest target, and the noise test**

An earlier draft of this plan characterised T1 as "compose-rich, almost no application code, a positive
control only". **That was wrong**, and the correction matters — it is the most demanding target of the
three, and it covers the blind spot the earlier draft named as missing.

What it actually contains:

| | |
|---|---|
| Deployment artifacts | 6 Dockerfiles, ~10 compose files; `shared-infra.yaml` declares `proxy`, `kafka`, `postgres`, `kroki`, `kroki-mermaid` |
| Deployment **tiers** | 2 solution deployments + **11 optional runtime add-ons** + 3 flag-selected runtime modes (parent doc §8.2b) |
| Self-documentation | `ENVIRONMENT_DIVERGENCE.md` states the runtime-mode table and which divergences are intentional (§8.2c) |
| Application code | ~1200 Python files under `compose-configs/`, overwhelmingly `PyegeriaWebHandler` — which carries **its own `Dockerfile-fast-api`** |
| Polyglot | Python, JavaScript, 165 HTML (the SPAs), 63 notebooks, Java, SQL |
| Duplication | `PyegeriaWebHandler` exists under **both** `egeria-quickstart` and `egeria-freshstart` |

Four distinct things this tests, which is why it leads:

1. **Declaration-only components (the control).** `shared-infra.yaml`'s services are third-party
   processes with no first-party code — pure `Data Storage` / `Third Party Process` classification from
   YAML alone. If this fails, the harness is broken. It is a control, so **a green result here is not
   evidence the premise holds** — do not report it as such.

2. **Code-versus-deployment reconciliation.** The application lives *inside* `compose-configs/`. The
   directory says "deployment config", the compose file says "services", the code says "a FastAPI
   application". This is precisely the case the earlier draft said no target covered, and detectors have
   to reconcile three disagreeing structural stories.

3. **Identity under duplication (Q3) — answered, and it changed the design.** Ground truth: **two
   components**, one per deployment (QuickStart = pre-configured, FreshStart = unconfigured), with
   slightly different admin requirements. Package-name-first would have merged them, so **deployment
   unit is now identity precedence 1** (§8.2, §8.2a in the parent doc). This target therefore ships with
   a known-correct answer, which makes it a regression test for the precedence chain rather than an open
   question.

   Measured overlap, for scoring against: quickstart 138 first-party tracked files, freshstart 94, 90
   shared paths (**60 byte-identical, 30 divergent**), 48 quickstart-only, **4 freshstart-only**. The
   right primary measure is **directional containment** — 96% of freshstart is inside quickstart —
   because symmetric Jaccard (0.63 by path, 0.42 by content) reads as "moderately similar" and badly
   understates near-containment. Any variant detector must report containment first.

4. **Variant detection.** Do the detectors notice that two structurally-unrelated-looking components
   are near-copies? Nothing in the path or manifest signals it. And do the **30 divergent files** surface
   as an RFA — *"declared variants, but a third of the co-located files differ; intentional?"* — rather
   than being silently averaged away? Parent doc §8.2a covers the modelling, including why
   `KnownDuplicate`/`PeerDuplicateLink` are the **wrong** types here.

5. **Deployment-tier discrimination — the hardest judgement in the target.** Three structurally
   different things are all called "deployments" here, and only one mints blueprints (parent §8.2b).
   The failure modes are symmetric and both bad: **over-splitting** (13+ blueprints, one per compose
   file, most holding a single third-party component) or **under-splitting** (one blueprint, losing the
   QuickStart/FreshStart distinction entirely). The 11 add-ons are also the cleanest available test of
   shared Collection membership — 11 optional component sets across 2 solutions.

   The runtime-mode tier is the specific trap: `demo-quickstart` / `local-quickstart` / `freshstart`
   share code *and* directory, differing only by flags in `demo_config.py`. A detector that splits them
   has over-applied the deployment-unit rule.

6. **Prose-declared architecture (§8.2c).** `ENVIRONMENT_DIVERGENCE.md` states much of the answer in
   English. Phase 0 is detector-only and **will not read it** — which is the point: it establishes the
   baseline against which Phase 5's LLM distillation can be measured. Record what the detectors miss
   that the doc states plainly; that delta is the value case for distillation, quantified rather than
   asserted.

7. **Vendored-dependency noise — see §3a. The most valuable test in the plan.**

### T2 — `trellis` / `resource-explorer` — **the no-declarations case**

**trellis contains no Dockerfiles, no compose files, and no `catalog-info.yaml` at all.** The richest
rows of §5.1's detector table yield *nothing* here.

That makes it the hard case. RE genuinely has multiple components — FastAPI web service, Typer CLI,
Textual TUI, AgentStack A2A server, surveyors, ingestion pipeline, agents, vector store — and **not one
is declared in a deployment artifact.** The only structural declarations are the four `packages/*`
workspace members and two `[project.scripts]` blocks.

So T2 asks the question §5.1 is actually betting on: *when nothing is declared, can code-level markers
alone recover the boundaries?* A weak result here is the single most informative outcome available,
because most repos in the estate will look like this.

T2 is also the **clean** target — no vendored code, no build artifacts — which makes it the right place
to judge detector quality without noise as a confound.

### T3 — `egeria` — **scale and the monorepo partition**

254 `include` entries in `settings.gradle`, no Dockerfiles. Tests whether the partition degrades
gracefully at two orders of magnitude more modules than T2, and whether "one blueprint per repo with
nested components" (§3.3a) is tolerable or absurd at this size.

**Scope the ground truth**: hand-partition only the top level of `open-metadata-implementation`, not all
254 modules. The question is whether the shape is right, not whether every leaf is placed.

---

## 3a. Vendored-dependency noise — a first-class objective

Discovered while grounding T1, and severe enough to be an objective rather than a caveat. **There are
two kinds, with different implications, and the difference is the point.**

**(a) Committed vendor code — a production problem.** `node_modules` in `egeria-workspaces` is **not
gitignored and is tracked**: 1697 of 1703 tracked `.js` files are vendored dependencies. Being in git,
it is in every zipball and every clone. This is not an artifact of anything.

Why it is dangerous rather than merely untidy: **it attacks §8.2's identity rule head-on.** Identity
precedence 1 is *declared package name*, and every vendored package carries a `package.json` declaring
one. A detector applying §8.2 faithfully emits **hundreds of spurious components**, each with a real
name, a real manifest, and real evidence behind it. Every downstream number — component count, scale
metrics, coupling, co-change — is then wrong, and the blueprint is unusable.

**(b) Untracked local build artifacts — a spike problem.** `.venv` / `site-packages` are **not** tracked
(1053 local-only Python files under `PyegeriaWebHandler`). Production paths never see these, because a
zipball contains only tracked files. But **Phase 0 reads local checkouts** (§2), so the spike sees them
and T1's results are garbage unless they are excluded.

**Consequences for this plan:**

- **An exclusion pass runs before any detector**, and it is `.gitignore`-aware plus an explicit vendor
  denylist (`node_modules`, `.venv`, `site-packages`, `vendor/`, `target/`, `dist/`, `build/`,
  `__pycache__`). Not a filter applied afterwards — vendored manifests must never reach the identity
  logic in the first place.
- **Report first-party versus total file counts per target.** A detector that silently includes vendor
  code will look productive while being wrong; the ratio makes it visible.
- **The two noise kinds must be reported separately**, because (a) is a Phase 1 requirement and (b) is
  a property of the spike's local-path shortcut that disappears in production. Conflating them either
  invents work or hides it.

**This is a finding for Phase 1 regardless of how Phase 0 turns out**: §5.2's "distillation — the noise
reducer" is written as though noise means *low-confidence candidates*. The larger noise problem is
structural and mechanical, needs no distillation, and must be handled before detection rather than
after.

## 4. Pre-registration — write the answer down before running

**This is the step that makes Phase 0 an experiment rather than a demo.**

The parent doc's exit criterion — *"the partition is recognisable to you as the real architecture"* — is
unfalsifiable if the partition is read first. Anyone shown a plausible clustering will find it
recognisable. So:

**Before running any detector**, hand-write `tests/fixtures/architecture-ground-truth/{target}.md` for
each target: the component
list, each one's type from the 13-value vocabulary (§3.1), and the file globs belonging to it. T1 and T2
are the ones that matter and the ones you know best — T1 because it is the richest, T2 because it is the
premise test.

T1's ground truth is the harder of the two to write and the more valuable. The `PyegeriaWebHandler`
question is **already answered** (two components — §3 T1 item 3), so pre-register that answer as given;
what remains is the rest of the partition, and excluding vendored code by hand — itself a check on
whether §3a's denylist matches human judgement.

T1's ground truth needs **two blueprints, not one** — QuickStart and FreshStart — sharing the
`shared-infra.yaml` components (parent doc Q8, revised). A single flat component list cannot express the
sharing relationship and so cannot score it.

It also needs the **11 optional add-ons recorded as optional component sets rather than blueprints**
(§8.2b), with a note of which solution(s) each attaches to. This is the part most likely to be
tedious to write and most likely to catch an over-splitting detector, so it earns its place.

Since much of this is already stated in `ENVIRONMENT_DIVERGENCE.md`, writing T1's ground truth is
partly transcription rather than recall — which lowers the cost of the pre-registration step and raises
its reliability.

Rules: written by you, not by the detectors; committed before `detect.py` is first run against that
target; and **not edited afterwards** — if the detectors reveal that the ground truth was wrong, that is
a finding to record, not a file to quietly fix.

Expect ground truth to be *partial*. Docs, configs, CI and test files often belong to no component.
Scoring only covers files both sides assign (§5).

---

## 5. Scoring — how "do they agree?" becomes a number

Three partitions of the same file set: **ground truth**, **detector output**, **import coupling**,
**co-change coupling**. (The latter two are derived clusterings, not opinions — cluster the graph, then
compare.)

**The number:** Adjusted Rand Index and Normalized Mutual Information over file→component assignments,
pairwise between all four. Both are a few lines to compute, both handle differing cluster counts, and
both are chance-corrected — which matters, because a "partition" that dumps 90% of files into one
component scores well on naive agreement measures.

**The decision:** not the number. Report, per target, a human-legible confusion view — which files the
detectors merged that ground truth splits, and which they split that ground truth merges. **Disagreement
is the output of this phase.** A boundary that all three signals place differently from you is worth more
than any aggregate score, because it is either a detector bug or a genuine fact about the code that
directory structure hides.

Score only files assigned by both sides of a given comparison; report coverage (what fraction of files
each partition placed) separately, because a detector that confidently partitions 20% of the repo is a
different failure from one that partitions all of it badly.

**Compute coverage against first-party files only, and report the first-party/total ratio alongside it**
(§3a). On T1 the two differ by an order of magnitude, and a coverage figure computed over the full tree
would be meaningless.

---

## 6. Exit criteria — falsifiable, decided in advance

**Pass.** On T2, detector output agrees substantially with pre-registered ground truth at the component
level, and the disagreements are explicable — a merge you consider defensible, a split you had not
thought of. The premise holds; proceed to Phase 1 as written.

**Qualified pass.** T2 partitions correctly only where a package manifest declares the boundary, and
code-level markers add little. This is the outcome I consider most likely. It does **not** kill the
feature, but it changes it: identity precedence 1 (declared package name) is doing all the work,
`ast-grep` marker rules need substantially more investment than §5.1 assumes, and the estimate for
Phase 1 should rise accordingly. Record it as such rather than rounding it up to a pass.

**Fail.** T2 boundaries do not correspond to anything you recognise, *and* import and co-change coupling
do not agree with the detectors either. §5.1's premise — that boundaries are declared in deployment and
configuration artifacts — is then false for code-first repos, and §5 needs rethinking before anything is
built. Call-graph tooling comes back onto the table, via SCIP's protobuf index rather than framework
adoption (§5.6).

**T1-specific criteria, orthogonal to the T2 pass/fail call:**

- **Noise handling (§3a).** Does the exclusion pass produce a first-party file set matching the
  hand-excluded ground truth? Any vendored `package.json` reaching the identity logic is a **fail on
  this criterion regardless of how well the rest partitions** — it is the failure that makes output
  unusable rather than merely imperfect.
- **Reconciliation.** Where directory layout, compose services and code markers disagree about
  `PyegeriaWebHandler`, does the detector pick a defensible answer, and is its evidence trail good
  enough to see *why*? This is the §5.4 evidence model's first real test.
- **Identity under duplication — now a regression test, not an open question.** The answer is two
  components, split by deployment unit. Anything else — one merged component, or one promoted and the
  other absorbed into a parent — means the revised precedence chain (§8.2) is not implemented correctly.
- **Variant detection and divergence.** Does the detector report directional containment between the two,
  and raise the 30 divergent files for review? Missing the variant relationship entirely is a partial
  fail: the partition would be right while the most actionable finding in the target went unreported.
  **Caveat on the RFA half:** `ENVIRONMENT_DIVERGENCE.md` documents much of this divergence as
  intentional, so an RFA asking "is this intentional?" is noise for anyone who has read it (§8.2c).
  Phase 0 records that the detector *found* the divergence; whether it should be raised as an RFA is a
  Phase 3 question and depends on distillation having read the doc.
- **Deployment-tier discrimination.** Two blueprints, 11 add-ons as shared component sets, runtime modes
  not split. Over-splitting into 13+ blueprints and under-splitting into 1 are both fails, and both are
  more likely than getting it right.

**Independent of pass/fail — the secondary measurement.** Time `scc` and `lizard` on T2 and T3 to test
§5.6's Discovery-tier cost claim. If they do not come in around a minute on T3, the funnel placement in
§5.6 is wrong and the tiering changes. Timing runs only; no integration.

---

## 7. Deliverables

1. `scripts/arch-spike/` — throwaway scripts and ast-grep rules.
2. `tests/fixtures/architecture-ground-truth/{target}.md` × 3, committed **before** the corresponding
   detector run, each passing `validate.py`.
3. `ir/{target}.json` — the Architecture IR draft (§5.3), which doubles as a test of whether the IR
   shape is expressive enough. A second finding source: if the IR cannot represent what the detectors
   found, §5.3 needs revision before Phase 1.
4. **A findings write-up** recording the pass/qualified/fail call against §6, the per-target
   disagreement analysis, the cost measurements, and any corrections to the parent design — of which
   §0 above already contains two, before a line of spike code has been written.

## 8. Effort and sequencing

Roughly a week, dominated by the ast-grep rule set. Order matters: **ground truth first** (§4), then
detectors, then the two validation signals, then scoring.

Sequencing: **T2 first**, not T1. T2 is the clean target — no vendored code, no build artifacts — so
detector quality can be judged without noise as a confound, and it is the premise test. Move to T1 once
T2's detectors are trustworthy, so that a bad T1 result is attributable to noise handling or
reconciliation rather than to detectors that were never right. T3 last, and only for shape.

Budget the exclusion pass (§3a) as real work rather than a helper function — `.gitignore` semantics are
fiddlier than they look, and on T1 everything downstream depends on it.

## 9. What Phase 0 explicitly defers

Egeria writes, qualified names, `ContentStatus`, `Confidence`, the curation overlay, versioning, RE
integration, Prefect, the `git_clone_root` provider, binary provisioning, metrics extraction, and the
LLM. Each belongs to a later phase and none is needed to answer Phase 0's single question.
