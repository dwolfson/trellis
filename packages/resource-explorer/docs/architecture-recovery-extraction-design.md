# Architecture Recovery — Extraction Design

**Status:** design reference. Part of the architecture-recovery design — split out 2026-09-03
from `architecture-recovery.md` (which had grown to 2,720 lines; §5, this document, was 913 of
them) per CLAUDE.md's "Writing project docs" rule.

**Read `architecture-recovery.md` first.** This document covers *how* extraction works —
detectors, distillation, the Architecture IR, evidence and confidence, partition validation,
tooling, and how it wraps as survey steps. `architecture-recovery.md` covers *why* and *what*:
the grounding in Egeria's own types (§3), the architecture model itself (§4), what extraction
feeds into (§6 component-scoped analytics onward), and the plan (§10).

**Numbering is inherited, not restarted.** This document keeps the §5.x numbers it had inside
`architecture-recovery.md` — §5, §5.1–§5.7, with §5.5's five lettered subsections (§5.5a–§5.5f) —
rather than renumbering from 1, so every existing cross-reference to a specific subsection
(elsewhere in this doc, in `architecture-recovery.md`, in `Backlog.md`, and in a few other RE
design docs) still names the same subsection it always did. **Any bare `§N` reference below that
is *not* `§5.x` points back into `architecture-recovery.md`** — §3, §4, §6, §7, §8, §10, §11,
§13, §15 are all sections of that document, referenced here without re-qualifying every mention.

---

## 5. Extraction design

### 5.1 Detectors first, call graphs last

**Deliberate departure from the tool list in the source analysis.** Joern and SCIP are heavy,
language-limited, and answer "what calls what" — which is *not* the boundary question. Component
boundaries and runtime shape are declared in deployment and configuration artifacts, which are cheap,
deterministic, and multi-language for free.

| Signal | Files | Yields |
|---|---|---|
| Container definitions | `Dockerfile*`, `*.containerfile` | `Long Running Daemon` / `Console Command`, entry command, exposed ports |
| Compose / orchestration | `docker-compose*.y*ml`, `k8s/*.y*ml`, Helm charts | component set, inter-service wires, protocols, `Data Storage` components |
| Service units | `*.service`, supervisord, Procfile | `Long Running Daemon` |
| Package entry points | `[project.scripts]`, `setup.py` console_scripts, `package.json` bin/scripts, `Main-Class` | `Console Command` |
| Web framework markers | FastAPI/Flask/Spring/Express route decorators & registrations | `Software Service`, ports with direction `Input-Output` |
| Client libraries | psycopg/SQLAlchemy, kafka clients, boto3, requests to known hosts | wires, `protocol`, `integrationStyle`, direction `Output-Input` |
| Scheduler / worker | Celery, APScheduler, cron, Prefect/Airflow DAGs | `Automated Action`, `Multi-Step Process`, `frequency` |
| Front-end build | `index.html`, SPA bundlers, static handlers | `User Interface` |
| Library shape | published package with no entry point | `Software Library` |
| Monorepo layout | workspace members, `uv`/pnpm/Gradle multi-module | candidate component partition |
| **Variant / near-duplicate** | per-file content hashes across candidate components | variant relationships, accidental-copy RFAs (§8.2a) |

RE already has tree-sitter (`ingestion/ast_chunker.py`) and dependency parsing
(`ingestion/dependency_parser.py`) to build on. Add call-graph tooling **only if** boundary detection
proves insufficient in Phase 1 — do not commit to it up front.

The variant row is cheap — hash every file, then compute directional containment between candidate
components — and it catches something no structural detector can see: two components that look unrelated
by path and manifest while being near-copies of each other. §8.2a has the worked example and the
modelling rules.

**Detection engine: `ast-grep`.** The code-marker rows above (web frameworks, client libraries,
scheduler/worker, entry points) should not be hand-written Python regex. `ast-grep` is a single Rust
binary running tree-sitter across ~20 languages, with rules expressed as YAML structural patterns.
Writing the detector table as ast-grep rule files buys three things: multi-language coverage for free,
detectors that are **data rather than code** (reviewable, extensible, curatable without a release), and
a stable rule id per match that becomes the `detector` field in §5.4's evidence. The file-presence rows
(Dockerfile, compose, k8s, service units) stay as ordinary parsers — use `dockerfile-parse` and PyYAML
rather than regex, and note that Trivy already ships parsers for Dockerfile / compose / k8s / Helm /
Terraform if piggybacking beats writing them.

**Declared architecture outranks inferred architecture.** Before any inference runs, check for sources
where the architecture is *stated* rather than derived:

| Source | Yields | Confidence |
|---|---|---|
| `catalog-info.yaml` (Backstage) — RE's `repo_conventions` step already looks for it | component identity, type, owner, dependencies | highest — human-authored |
| OpenAPI / AsyncAPI specs | ports, directions, protocols, `dataExchanged` | high |
| Compose / k8s service names and labels | component names, wires | high |
| `pyproject.toml` / `package.json` / Gradle workspace members | component partition and **stable identity** (§8.2) | high |

Where these exist they short-circuit distillation entirely — there is nothing to infer and nothing for
the LLM to name. Treat their absence, not their presence, as the interesting case.

### 5.2 Distillation — the noise reducer

Detectors produce candidates; distillation decides the component set. Responsibilities:

0. **Read the repo's own architecture and deployment documentation** (§8.2c). Prose docs stating the
   component set, the deployment tiers, or which divergences are intentional are detector-invisible but
   directly readable here, and they outrank inference. This is not invention — it is reading a human's
   statement about their own architecture, which is the highest-confidence evidence available.
1. **Partition** the repo into components (cluster by directory, entry point, and deployment unit —
   the *artifact* sense of deployment unit, per §8.2's floor).
2. **Classify** each into the 13-value `SolutionComponentType` vocabulary.
3. **Name** each in human terms.
4. **Infer ports** and directions from interfaces served vs. consumed.
5. **Infer wires** between components, populating `protocol` / `integrationStyle` / `frequency` /
   `dataExchanged` / `oneWay`.
6. **Emit evidence** for every claim (see §5.4).

**Step 0, added after Phase 0 planning: exclusion.** Before any of the above, filter the file set —
`.gitignore`-aware, plus an explicit vendor denylist (`node_modules`, `.venv`, `site-packages`,
`vendor/`, `target/`, `dist/`, `build/`, `__pycache__`).

This is not tidiness. Vendored dependency trees are **committed to git in real repos** — in
`egeria-workspaces`, 1697 of 1703 tracked `.js` files are `node_modules`, so they are present in every
zipball and clone. Each vendored package carries a manifest declaring a package name, which is
**identity precedence 1 in §8.2**. A detector applying that rule faithfully to an unfiltered tree emits
hundreds of spurious components, each with a real name, a real manifest and real evidence, and every
downstream number is then wrong.

The distinction that matters: this noise is **structural and mechanical**, not low-confidence. No amount
of distillation or LLM adjudication fixes it, because each spurious component looks entirely legitimate
in isolation. It must be excluded *before* detection, never filtered after. The rest of §5.2 assumes
noise means "weak candidates"; this is a different and larger problem.

Heuristics own steps 1, 4, 5; the LLM owns 2 and 3 and adjudicates ambiguous partitions. **Rule: the
LLM never invents a component with no detector evidence behind it.** Its job is naming, classifying,
and merging — not discovery. This keeps hallucinated architecture out of the catalog.

### 5.3 The Architecture IR

A normalised JSON intermediate representation at roughly C4 container/component level, produced and
stored **before** any Egeria write. Everything downstream — projection, curation, drift — reads the IR.

Rationale: the IR is diffable, testable without an Egeria server, and reviewable by a human before it
becomes metadata. It also means re-derivation and re-publication are separable operations.

### 5.4 Evidence and confidence are first-class

Every component, port and wire carries an evidence record justifying each individual claim about it.
A claim is one assertion — "this is a `Software Service`", "this wire uses `HTTPS`" — not a whole
component.

```json
{
  "subject":   {"kind": "component|port|wire", "slug": "resource-explorer.web"},
  "assertion": "solutionComponentType=Software Service",
  "detector":  "ast-grep:fastapi-app-construction",
  "locations": [{"path": "resource_explorer/web/app.py", "line": 42,
                 "excerpt": "app = FastAPI(title=...)"}],
  "confidence": 90,
  "confidenceLevel": "Derived"
}
```

`confidenceLevel` uses Egeria's stock `ConfidenceLevel` values (§3.3b) rather than an RE-local
`derivation` vocabulary — the two were the same axis, so there is one field, and it publishes without
translation.

Curation is impossible without showing *why* a component was proposed, and per the current-state doc,
RE's habit of stuffing untyped detail into `jsonProperties` makes it unqueryable — evidence must not go
the same way.

**Storage — RE-side, in the existing generic findings table.** `project_analysis_findings`
(`registry.py:866`) already carries exactly this shape and needs no schema change:

| Column | Carries |
|---|---|
| `kind` | `architecture_recovery` |
| `check_name` | the assertion |
| `label` | `accept` / `uncertain` / `conflict` |
| `confidence` | INTEGER 0–100 — **the same scale as Egeria's `ConfidenceProperties.confidence`**, so no conversion |
| `scope_locator` | the component's path prefix — the join key to everything else (§6) |
| `detail_json` | the `locations` array, plus `detector` and `confidenceLevel` |

That the fit is exact is not a coincidence: the generic findings table was built for uniformly-shaped
analysis output, and evidence is analysis output. Reusing it also means evidence is immediately visible
to the annotation-Q&A agent (§6.5) with no extra tooling, and lives in the same store as the §7.2
curation overlay — which the overlay needs anyway.

**What reaches Egeria — the reasoning, not the receipts.** Base `AnnotationProperties` already provides
typed fields for the justification:

- `expression` — the detector rule id that fired
- `explanation` — human-readable why
- `analysisStep` — which pass produced it
- `confidence` — the same 0–100 integer

and on the `Confidence` classification itself: `confidenceLevel` (provenance), `source` (the analyzer
id), `steward` (who curated).

Locations and excerpts stay RE-side. A curator or agent that wants the receipts follows `scope_locator`
back into RE. **Nothing goes into `jsonProperties`.** Q4 resolved on this basis (§11).


### 5.5 Validating the partition — three independent signals

Detectors *propose* a partition. Nothing above *checks* it, and a partition nobody checked is exactly
the kind of plausible-looking output that erodes trust. Score every proposed partition against two
signals the detectors structurally cannot see:

1. **Import coupling.** A partition whose components all import each other is wrong regardless of what
   the Dockerfiles say. Build the module import graph and measure cross-boundary edge density.

   **Correction (found while planning Phase 0):** an earlier draft named RE's
   `project_code_relationships` table as the source. It cannot serve — its schema
   (`registry.py:608`) is `relationship_type` / `source_name` / `target_name`, **name-to-name with no
   `file_path`**, and it holds `inherits_from` edges, not imports. Joining it against
   `project_code_symbols` (which does carry `file_path`) recovers path pairs, but yields an
   *inheritance* graph — a much weaker boundary signal than imports.

   **Extract imports with ast-grep instead.** Import statements are among the most trivially matchable
   constructs in any language, and ast-grep is already the detection engine (§5.1), so the marginal
   cost is near zero. Do *not* adopt `grimp`/`import-linter`: grimp resolves modules by importing them,
   so it needs the dependency environment installed rather than just a checkout — real operational cost
   for a graph we can extract statically. Per-language alternatives (`dependency-cruiser`, `jdeps`,
   `go list -deps`) remain available if the ast-grep graph proves too thin.

2. **Co-change coupling.** Files that always change together belong to one component even when the
   directory layout disagrees. It is the signal most likely to *contradict* the detectors usefully —
   directory structure records intent, co-change records reality.

   **Also corrected:** `project_commits` (`registry.py:548`) carries `sha` / `message` / author /
   `committed_at` and **no per-file change data**, so it cannot produce this either. The source is
   `git log --name-only` or `code-maat` over a real clone — which is why `git_clone_root` (§5.7 gap 2)
   is a prerequisite for this signal outside the Phase 0 spike, where local checkouts stand in.

**This gives Phase 0 a sharper exit criterion** than "recognisable to you": run all three — detector
partition, import coupling, co-change coupling — and ask whether they agree with each other and with a
**pre-registered** hand-written partition. See `docs/architecture-recovery.md (§13.1)`, which makes
the criterion falsifiable by requiring the expected answer to be written down before the detectors run. Three independent signals converging is evidence the premise holds. Two agreeing
and one dissenting is a finding. All three disagreeing means §5.1 needs rethinking before anything is
built.

### 5.5a Documentation is a source, a *dated* source, and a signal — three separate uses

The Milvus ground-truth exercise (spike README findings 65–67) produced three lessons about project
documentation. They are not one lesson: each puts docs to a different use, and each lands in a
different part of this design.

**(a) Always look for documentation first — including documentation that is not in the repo.**

§5.2's step 0 already reads in-repo docs. The Milvus case shows that is not sufficient: the
authoritative logical architecture — four layers, named components, explicitly labelled *logical* —
is published at `milvus.io/docs/architecture_overview.md`, **not** in `milvus-io/milvus`. A survey
that only reads the repo would miss the single best description of the system it is trying to
recover. The repo does carry `docs/` (a `README.md`, `design-docs/`, `agent_guides/`, `archive/`),
but the front-door architecture page lives on the project's doc site.

**Measured across twelve repos** (spike finding 68 — `egeria`, `egeria-workspaces`, `milvus`,
`airflow`, `kubernetes`, `grafana`, `prometheus`, `kafka`, `elasticsearch`, `polars`, `ray`, `redis`):
**zero** have an `ARCHITECTURE.md` at root, **two** have architecture docs findable in-repo by name,
**eleven** declare a homepage, and **every one of the five checked has a separate, actively-maintained
docs repo** (`kubernetes/website`, `odpi/egeria-docs`, `milvus-io/milvus-docs`, `prometheus/docs`,
`redis/redis-doc`). Step 0 as written would find architecture in **2 of 12 cases**. The outward hop is
not an enhancement; without it the best available description of the system is missed almost every time.

So step 0 needs an outward hop: resolve the project's documentation site (from `README.md` links,
repository metadata, or the package manifest homepage) and treat the published architecture page as a
first-class input. This is a fetch, and it is the right kind — cheap, once, and it can save every
expensive tier downstream. Consistent with CLAUDE.md rule 17: zero-fetch is a proxy for cheap, and
here the measurement wins.

**(b) A prose architecture describes a *version*, and the version is recoverable from the repo.**

Documentation and code drift, and prose rarely carries a version stamp. But **every path a document
cites is dateable**: `GET /repos/{o}/{r}/commits?path={p}&per_page=1` returns the last commit that
touched it, and for a path that no longer exists that is effectively its deletion date.

Two bounds follow, each one cheap call per path:

- **Upper bound on vintage** — the newest of the now-dead paths a document cites. A description
  naming `internal/indexcoord` (last touched 2023-01), `internal/querynode` (2023-04),
  `internal/mq` (2024-06) and `internal/indexnode` (2025-03) cannot be describing anything after
  ~March 2025.
- **Lower bound on blind spot** — the churn of live paths it omits. The same description omitted
  `internal/streamingnode` and `internal/distributed/mixcoord`, both committed to within the last
  fortnight.

Together those dated the document as roughly seventeen months stale, from four API calls and without
reading a line of Go.

Because the published docs usually live in a **sibling git repo** rather than a rendered site
(finding 68 — `milvus-io/milvus-docs` carries `site/en/reference/architecture/`, eight markdown pages
under version control), a document can be dated **two independent ways**: by its own commit history,
and by the last-commit dates of the paths it cites. The two cross-check each other, and no heuristic
dating is needed.

This applies symmetrically. It is a check on a maintainer's doc, on an LLM's proposal, **and on our
own output** — a recovered blueprint that cites paths deleted two years ago is stale in exactly the
same measurable way, and §5.4's evidence records are the natural place to carry the dates.

**(c) Documentation health is itself an architectural signal — arguably a strong one.**

Whether a project documents its architecture, and whether that documentation is *current*, is
evidence about the project independent of anything the docs say. The gradient is roughly:

| observation | reading |
|---|---|
| architecture documented, docs churn tracks code churn | mature and maintained — the strongest state |
| documented, docs lag code by a long interval | back-level docs; the project has moved and the description has not |
| documented once, no longer touched | abandoned documentation — a health signal about the project, not just the doc |
| stale docs *archived* rather than left in place | deliberate curation; strictly stronger than simply having docs |
| no architecture documentation at all | either immature, or small enough not to need one — needs the maturity signals to disambiguate |

Milvus sits at the top of that table: `docs/` last touched 2026-08-21 against `internal/` at
2026-08-22 — a one-day lag — and a `docs/archive/` that is itself actively maintained.

Three consequences for this design:

1. **This is a Discovery-tier signal, not an Analysis one.** It reads commit dates over two path
   sets. It costs nothing and it gates the expensive tiers, which is exactly rule 17's test.
2. **It feeds triage, which we already know we need.** Spike finding 58's false positives were
   settled by a human reading a README that said the repo's intent was a tutorial. Doc health is the
   measurable half of the same judgement: *is there an architecture here worth recovering, and does
   the project believe there is?*
3. **It cannot be measured until (a) is done — the two are coupled, not independent.** The naive
   metric (commit recency of `docs/` against code) scores **Kubernetes at 1412 days of untouched
   documentation** against code touched two days ago. `kubernetes/kubernetes/docs/` in fact holds
   exactly two entries, `.gitignore` and `OWNERS`: it is a **tombstone**, and the real docs moved to
   `kubernetes/website`, pushed today. Measuring doc health without first resolving where the docs
   live returns the *opposite* of the truth on precisely the projects that most deserve a good answer.

   This is a proxy that quietly stopped encoding the thing it proxied for — the same failure shape as
   the name-matching scorer that outlived the identity rules. `docs/` mtime means "documentation is
   maintained" only while the documentation is still in `docs/`.

   **The tombstone is itself detectable, and is a positive signal.** A docs directory holding only
   `OWNERS`/`.gitignore`/README stubs indicates deliberate relocation — the same class of curation
   marker as Milvus's maintained `docs/archive/` or Egeria's `saved/`. Projects that abandon
   documentation leave it rotting in place; projects that move it leave a marker.

4. **Do not turn it into a score.** A marketing-maintained doc site can coexist with rotting
   in-repo docs, and a small, stable, mature library may document lightly on purpose. Report the
   observation and its dates as evidence (§5.4); let the confidence axes (§3.3c) and a human carry
   the interpretation. Recording "docs lag code by N days" is defensible; ranking projects by it is
   not.

**(d) The outward hop was built, and it measured near-zero on the case that motivated it.**
Added 2026-08-29. `doc_locations.py` resolves sibling repos and doc sites as (a) asks, and it works
— 13 of 46 gate-approved repos get a document located. But the lens built on top of it named **1 of
Egeria's 999 logical components**, from `odpi/egeria-docs`, and that one match is a directory called
`egeria` matching the term `egeria`. The document names `Common Services`, `OMAS`, `OMVS`; the
pipeline proposed Java package paths. Nothing joins, and better matching cannot make it join.

The diagnosis is a §4.1 violation this document did not anticipate: `coupling.propose()` asserts
`perspective="logical"` beside `identity.method="module-path"`, so a directory path and `OMAS` are
filed under the same word and the lens joins on it. The only genuinely logical source in the
pipeline is the one input forbidden from proposing anything.

Decision (project owner, 2026-08-29): **a documentation-derived component may exist without a
`scope_locator`** — docs become a source, bridged to code by `ImplementedBy` (§3.6, §4.1). The
consequences, the gate this needs (the existing `undetected_is_meaningful` licenses *reading*, not
*proposing*, and its denominator is circular), and why §5.5a(b)'s dating becomes a precondition
rather than an enhancement are in **`architecture-recovery.md (§15)`**.

### 5.5b What the repo *is* — classification before analysis

**Maintainer direction, 2026-08-22.** Before asking *what is the architecture of this repo*, ask
**what does this repo represent**: a library, an application, middleware, a tutorial, a set of
samples, documentation, a tooling repo — or a *family* of repos playing different roles.

The reason is not taxonomy for its own sake. **The classification determines which analyses are
relevant and which questions are worth asking.** Recovering a solution blueprint from a tutorial
repository is not a weak result; it is the wrong question. A samples repo has no architecture to
recover, and reporting one is a false positive no confidence score can rescue. Middleware and an
application have different port/wire expectations. A documentation repo should be answering "is it
current, and does it match the code it documents" (§5.5a) rather than "what are its components".

This generalises three things already established rather than adding a new idea:

- **Spike finding 58/60** — the `workshops` false positives were settled by a human reading a README
  that said the repo's *intent* was a tutorial. That is exactly this classification, applied by hand,
  once.
- **§5.5a(c) doc health** — already framed as "the measurable half of the triage judgement finding 58
  needed a human for". Repo classification is the other half of the same triage.
- **Rule 17's funnel** — Discovery exists to decide whether the expensive tiers are worth paying for.
  Classification is the cheapest possible gate: it can rule out whole *categories* of analysis, not
  just individual steps.

Signals already in hand, none of which need new collection: the README's own statement of intent
(finding 60), published architecture documentation and whether any exists (§5.5a), manifest
`packages`/`bin`/`scripts` declarations, presence or absence of deployment artifacts (a repo with no
Dockerfile and no compose file is not an application — `trellis.md` records exactly that), the ratio
of test/example/notebook files to source, and dependency direction (a library is depended upon; an
application depends).

#### It is a gate, not a weighting — and the outcome vocabulary has no word for it

**Maintainer, same session:** *"If we classify a repo as being a tutorial there is no point trying to
discover an architecture."*

That is stronger than down-weighting a result, and the design should say so plainly: on a repo
classified as a tutorial (or samples, or documentation), **architecture recovery does not run.** Not
"runs and scores low", not "runs and is reported with low confidence" — does not run. The cost saved
is the whole tier, which is what makes this the cheapest gate in the funnel rather than one more
filter applied after the expensive work has already happened.

**This exposes a gap in the five-label outcome vocabulary** (`resource_explorer/step_outcome.py`), and
it is not ours to fix unilaterally — that module is owned elsewhere and the labels were agreed jointly:

| label | why it does not fit a deliberate skip |
|---|---|
| `recovered` / `partial` | nothing ran |
| `no_signal` | "genuinely nothing to find — **and provably so**"; its constructor requires `known_positive=True`, i.e. evidence the detector works. We did not run, so we can prove nothing |
| `unverified` | "could not run, or ran with nothing to validate against" — closest, but wrong in the part that matters: we **could** have run and **chose not to**, which is a success of the funnel, not a failure of it |
| `regression` | unrelated |

A skip-because-irrelevant is a *good* outcome and currently reads as a degraded one. Whatever the
label ends up being — `not_applicable`, or `no_signal` with the `known_positive` requirement relaxed
for classification-gated skips — **the distinction that must survive is "we didn't run because it
would have been the wrong question" versus "we ran and found nothing".** Conflating them would make
the funnel's biggest win indistinguishable from its most common failure. Raise with the owner of
`step_outcome.py` rather than adding a sixth label here.

#### Two questions, not one: repo **role** and project **topology**

**Maintainer, same session.** Classification has a second axis. Beyond *what is this repo*, there is
*how does this project distribute its concerns across repos* — and that is a question of **style and
trend**, not correctness. Some projects keep a clean set of purpose-built repos; others jumble
tutorials, docs and code together. Both are legitimate, and the difference changes **where to look
for what**.

This is why RE has a project structure above repos at all: `projects.parent_slug`,
`projects.group_slug`, `projects.homepage_url` and `projects.docs_url` already exist in the registry.
The topology question has a home in the data model; nothing has been asking it.

**We already have five measured topologies**, gathered for the ground-truth work (finding 68) before
this framing existed:

| project | code | documentation | architecture published? |
|---|---|---|---|
| `milvus` | `milvus-io/milvus` | **sibling repo** `milvus-io/milvus-docs` | yes, versioned by branch |
| `kubernetes` | `kubernetes/kubernetes` | **sibling repo** `kubernetes/website`; in-repo `docs/` is a **tombstone** | yes |
| `prometheus` | `prometheus/prometheus` | **both** — in-repo `documentation/` *and* `prometheus/docs` | yes, in-repo, five years stale |
| `egeria` | `odpi/egeria` | **sibling repo** `odpi/egeria-docs` | no — mostly archived under `saved/` |
| `egeria-workspaces` | one repo | **in-repo**, mixed with code and tutorials | no |

Four of five separate documentation into its own repo. That is the trend, and a heuristic that
assumes otherwise will be wrong most of the time.

#### The expectation set — and reporting *where*, not *whether*

The maintainer's proposal, which is the actionable half:

1. **Classify the kind of thing** from the project's documentation and web site.
2. **Derive what a mature project of that kind should have**, then go looking for it.
3. **The result is itself part of the classification**, and it tells you where to look for everything else.

The design decision that makes this work: **the output for each expected artifact is a *location*,
not a boolean.** Four outcomes — `in-repo`, `in a sibling repo`, `on the doc site`, `not found` — and
only the fourth is an absence.

**Finding 68 is the cautionary tale for exactly this heuristic.** "Where is the documentation?"
answered naively against `kubernetes/kubernetes` returns *nothing, and stale for 1400 days*. The
correct answer is "in `kubernetes/website`, updated today". A boolean checklist would have marked
Kubernetes as undocumented. The location-valued answer is what makes the heuristic safe, and it
**requires the outward hop of §5.5a(a) as a hard prerequisite**, not an enhancement.

Indicative expectation sets — to be validated, not adopted as written:

| role | expected | notably *not* expected |
|---|---|---|
| application | deployment artifacts, install/quickstart, configuration reference, architecture doc, release notes | published package manifests |
| library | API reference, usage examples, versioning/changelog, published package | deployment artifacts — `trellis.md` records exactly this: "no Dockerfiles, no compose files … it has no deployment perspective at all" |
| middleware | deployment artifacts, configuration reference, integration/connector docs, compatibility matrix | end-user UI docs |
| tutorial / samples | stated intent, step-by-step content, sample data, environment setup | architecture, deployment topology |

**Absence is evidence in two directions, and they must not be conflated.** No deployment artifacts in
something classified as an application is a *maturity* finding. No deployment artifacts in something
classified as a library is *confirmation* of the classification. The same observation means opposite
things depending on the declared role — which is precisely why role must be established first.

**The failure mode to design against** is the one §5.5a(c) already names: an expectation checklist
turns into a maturity score, and a maturity score punishes deliberate choices. A small stable library
documents lightly on purpose; a project may deliberately keep tutorials in-tree. **Report the
findings and their locations as dated evidence; do not rank projects on the count.**

#### Offer to widen the scope — never widen it silently

**Maintainer, same session.** When the expected artifacts for a project's role are not in the repo
the user named, **ask whether to include other repos of the project**.

The location-valued lookup makes this nearly free: resolving where documentation lives *already*
produces the candidate list. Having found `kubernetes/website`, the remaining question is not
"which repo?" but simply "shall I include it?".

Four constraints, each with a reason:

1. **Ask; do not auto-add.** Silent scope expansion is the failure mode. It causes fetches the user
   did not ask for, and it produces results that cannot be compared with the previous run of the same
   analysis. There is precedent for this interaction: the maintainer's earlier answer on ambiguous
   partitions — *"if we are truly unsure we can present the user with a file tree with checkboxes"*.
2. **Record the scope with the result.** Adding a repo changes the denominator of every coverage and
   score. `trellis.md`'s `Scope:` line exists precisely because a wrong denominator makes a number
   meaningless (whole-repo coverage reads 15% where in-scope coverage is 48%). §6.2 already argues
   that a metric moving between two runs is ambiguous without `analyzerVersion`; **the set of repos in
   scope is the same kind of provenance and must travel with the result.**
3. **Classification must come first.** What is "missing" is only defined relative to the role.
   Asking "where are the deployment artifacts?" for a library is noise, not a gap — a library is
   *expected* not to have them (§5.5b, and `trellis.md` records exactly this).
4. **Use the mechanisms that exist.** RFA is already the carrier for "the system needs something from
   a human", and the registry already models repo families (`projects.parent_slug`,
   `projects.group_slug`) with an Admin Groups UI on top. This is a new *question*, not new
   plumbing.

**Why this is good funnel behaviour rather than a nag.** The ask is cheap, it happens before the
expensive tiers, and the alternative is worse than a prompt: analysing a code repo whose architecture
documentation lives in a sibling repo produces a confident, wrong "no architecture documented"
finding. That is the Kubernetes tombstone case (finding 68) reaching the user as a conclusion instead
of a question.

#### The gate must NOT trigger on the primary role alone

Found while building the classifier, and it corrects the "gate" subsection above.

`odpi/egeria-workspaces` classifies as **`tutorial`, `application`, `library`** — all three correct.
Its README says it is *"a fully pre-configured, Docker Compose-based platform for **learning**,
experimenting with, and operating Egeria"* and *"designed for learning and small-team use"*, and it
carries 37 Jupyter notebooks in `workbooks/` and `coco-workbooks/`. `tutorial` ranks **primary**.

**And it is target T1, from which architecture recovery scored 18/27.** A gate keyed on the primary
role would skip the repo whose deployment architecture we have most successfully recovered.

So primacy is the wrong trigger. The gate's real question is not *"what is this repo mostly?"* but
*"is there an architecture here worth recovering?"* — and that is answered by the **presence of
structural evidence**, not by which role sorted first:

> **Skip architecture recovery when a tutorial/samples/documentation role is present AND no
> deployment or structural artifacts were found. Never on the primary role alone.**

Under that rule `egeria-workspaces` runs (25 compose files), a pure notebook workshop does not, and
`kubernetes/website` does not. The primary role still drives the **expectation set** — what a mature
project of this kind should have — which is what it is good for.

**Why the distinction was invisible until now.** Single-role classification conflates "what it mostly
is" with "what it contains". The multi-valued decision separates them, and the gate must key on
*containment* while the expectation set keys on *primacy*. Two different questions, two different
readings of the same classification.

#### Vocabulary check against Egeria — done, and nothing existing fits

§3.1's lesson was that `SolutionComponentType` **already existed** rather than needing invention, so
the same check was run before defining a role vocabulary. Searched
`frameworks/open-metadata-framework/.../refdata/` (the same directory
`SolutionComponentType.java` lives in) at `egeria-v6`:

| candidate | what it actually encodes | verdict |
|---|---|---|
| `DeployedImplementationType` (~120 values) | *deployed runtime artifacts* — `SOFTWARE_SERVER`, `DOCKER_CONTAINER`, `REST_API`, `SOURCE_CODE_FILE`, connectors, file types | **wrong axis.** Describes what a thing IS at runtime, not what a body of work represents. No `library`, `tutorial`, `samples`, `documentation` |
| `ResourceUse` (29 values) | how a resource is *used in a governance flow* — `SURVEY_RESOURCE`, `CATALOG_RESOURCE`, `INFORM_STEWARD` | wrong axis |
| `Category` (7 values) | metadata namespaces — `OPEN_METADATA_TYPES`, `SUSTAINABILITY`, `CLINICAL_TRIALS` | unrelated |
| `ProjectStatus`, `ProjectPhase`, `ProjectHealth` | lifecycle state of a *project*, not its kind | unrelated |

**There is no existing Egeria vocabulary for what a repository represents.** The check was still worth
running: it rules out a wrong reuse, and it found the adjacent slot is already occupied.

**The adjacent slot, and why role must not go in it.** `egeria_publisher.py:295` already writes
`"deployedImplementationType": "GitHub Repository"` for every catalogued repo. That is the *hosting
technology*, not the role — and "GitHub Repository" is not one of the enum's ~120 values, which
confirms the property is free text backed by an extensible valid value set. Overloading it with
`library` / `tutorial` would collide two orthogonal facts in one property, the §4.1c mistake
(`scope_locator` meaning two things) in a new place.

**Recommended shape: a new Egeria valid value set, not a Python enum.** Valid value sets are the
framework's native extension mechanism — `ConfidenceLevel` is one, and the maintainer has already
confirmed they can be extended ("confidence level is defined in valid values — we can extend it if we
want"). A valid value set is catalogable, queryable, and extensible without a code change, where a
hardcoded Python enum is none of those and would have to be migrated the first time the list is wrong.

**Open, deliberately.** The vocabulary is not chosen yet, and the temptation to invent a closed enum
should be resisted until it is checked against Egeria's existing types — `SoftwareCapability`
subtypes and `plannedDeployedImplementationType` may already carry part of this, the same way §3.1's
13-value `SolutionComponentType` turned out to exist rather than needing invention. Whether one repo
gets one classification, or a monorepo gets one per workspace member, is also open — `trellis` alone
contains an application, two libraries and a spike.

**A companion question — capturing the user's intent — was raised at the same time and deliberately
deferred to a separate discussion.** What the repo *is* and what the user *wants from it* are two
different filters on which analyses matter, and conflating them would be a mistake.

### 5.5c Learning from user feedback — and the two things that look alike

**Maintainer direction, 2026-08-22:** *"we need to continuously get feedback from the user to allow
us to continue to refine our weights, scoring and algorithms — perhaps some of them dynamically."*

Right, and necessary: every table in §5.5b is provisional, the role vocabulary is a first guess, and
the expectation sets were written from five projects. Nothing here improves without correction from
people who know the repos.

But two mechanisms hide under "learn from feedback", and conflating them would dismantle the only
uncontaminated measurement this project has.

#### (a) Feedback as **labelled examples** — safe, and the high-value half

A user saying *"this is a tutorial, not an application"* is a **data point**: a labelled example with
an author, a date, and a repo. Stored that way it is durable, auditable, and reusable for purposes
not yet imagined. This is the half to build first, and RE already has the plumbing — `curate.py`'s
`resource_feedback` / `resource_curator_notes`, the RFA lifecycle, and the activity log. **Capturing
feedback is not new infrastructure; it is a new question asked through existing surfaces.**

#### (b) Feedback as **weight adjustment** — where the danger is

Three rules this project has already paid for, each of which auto-tuning would violate by default:

1. **Never tune on the pre-registered fixtures.** `README.md` rule 3 forbids editing them *because a
   partition inferred from the code and then compared against that code measures nothing*. A weight
   fitted to make `prometheus.md` score 11/11 makes that 11/11 meaningless. Feedback-derived examples
   must form a **separate, growing corpus**, and the fixtures must never enter it.
2. **A rule fitted to the repos you have measured is not a rule** (findings 65, 78). The `kube-`
   prefix pairing was not shipped for exactly this reason. Feedback arrives from repos the user
   happens to care about, which is a biased sample by construction — the correction is a **frozen
   holdout**, not more data.
3. **A moving weight is a moving denominator.** §6.2 already argues that a metric which changes
   between two runs is ambiguous without `analyzerVersion` — did the code change, or the detector?
   Silently-adjusting weights make *every* number incomparable across runs. So any weight set must be
   **versioned and recorded with the result**, exactly like `analyzerVersion` and the in-scope repo
   set (§5.5b).

#### The ordering constraint

**You cannot safely auto-tune without a way to detect that tuning made things worse.** That detector
is the pre-registered corpus scored by strict containment (§2a, finding 61) — currently Prometheus
11/11, Kubernetes 6/6, Milvus 3/5, trellis 9/11, egeria-workspaces 18/27. It works *only* while it
stays out of the training loop.

So the sequence is: **capture labelled feedback → make weights explicit, versioned and stated with
every result → require a holdout run before any weight change → only then consider anything
dynamic.** Static-but-versioned is not a lesser version of dynamic; it is the thing that makes
dynamic detectable.

#### The failure mode to name out loud

A system that tunes on recent feedback gets better at **agreeing with recent users** rather than at
being right, and it degrades invisibly, because the same feedback that shifts the weights also shapes
what anyone thinks to check. §5.5a(c)'s guardrail — report the observations, do not rank them — is
the same instinct one layer up: **prefer a system that shows its evidence and is corrected, over one
that quietly converges on approval.**

### 5.5d User motivation → disposition → next steps

**Maintainer, 2026-08-23.** Step back from the repos and ask why anyone is looking at one at all.
Motivation drives **disposition** and **next steps**, and therefore which questions — and hence which
survey types — are relevant.

The motivations, as given:

| # | motivation |
|---|---|
| 1 | gain general understanding |
| 2 | assess potential competition |
| 3 | prospect for components, runtimes or tools that might be useful |
| 4 | the components/runtimes/tools are **already in use**: (a) learn to use them, (b) evaluate robustness/security/viability, (c) decide whether to upgrade, (d) compare with alternatives, (e) investigate expanding their use |
| 5 | the repo is **data** — analogous questions, different kinds: quality, currency, documentation |

Possibly several at once, as with roles.

#### The structural line inside the list

**1–3 are about resources you do not use; 4 is about resources you do.** That is not a label, it
changes what evidence *exists*. For an in-use resource there is a second corpus — which version you
are on, which APIs you actually call, how deeply it is embedded, who owns the integration — and
**none of it lives in the repo being surveyed.** RE has no such corpus today. Every motivation under
4 is partly unanswerable from the repo alone, and pretending otherwise would produce confident
answers to the wrong question. Worth naming before anything is built: *4 needs an input we do not
have*.

#### 5 is not a sixth motivation

It is the observation that the **question set is resource-type-specific while the motivation set is
not**. "Is it current?", "is it documented?", "can I depend on it?" are the same motivations aimed at
a different kind of thing. That is good news: motivation **composes with** resource type rather than
multiplying against it, so a data resource does not need its own motivation taxonomy.

#### Disposition is the new idea, and it is the missing top layer

RE produces annotations and findings — *evidence*. A **disposition** is an answer: adopt, avoid,
monitor, upgrade, replace, ignore, investigate further. That is what a decision-maker actually wants,
and nothing in the system currently produces it.

**And Egeria may already have the vocabulary.** §5.5b's check found `ResourceUse` and set it aside as
the wrong axis *for role* — which it is. But for disposition and next steps it looks close to right:
`CERTIFY_RESOURCE`, `CATALOG_RESOURCE`, `UNCATALOG_RESOURCE`, `PROVISION_RESOURCE`, `CHOOSE_PATH`,
`WATCH_DOG`, `CREATE_SUBSCRIPTION`, `IMPROVE_METADATA`, `INFORM_STEWARD`, `GENERATE_INSIGHT`. Those
are *governance actions on a resource* — which is what a next step is. **Check this properly before
inventing a disposition vocabulary**, exactly as §3.1's `SolutionComponentType` turned out to exist.

Note `WATCH_DOG` and `CREATE_SUBSCRIPTION` in particular: motivation 4c (*do we need to upgrade?*) is
inherently **recurring**, not a one-shot survey. It is the Automate intent by another name, which
suggests some motivations imply a *schedule* rather than a run.

#### Four axes now exist — keep them apart

| axis | question | vocabulary |
|---|---|---|
| **role** (§5.5b) | what *is* this resource? | 7 values, provisional |
| **motivation** (here) | why am I looking at it? | this list, provisional |
| **perspective** | who am I? | dba / data_scientist / steward / security |
| **intent** (the 8 UI tabs) | how am I working right now? | Scouting … Automate |

These are genuinely different, and merging any two would repeat the §4.1c mistake — one field, two
meanings — which this project has now hit three times. In particular **motivation is not the eight UI
intents**: those are *modes of working*, this is *why*. "Evaluate robustness" (motivation) is pursued
*through* Assessment (mode).

**The combinatorial risk is real and has an answer.** Four axes multiply if each independently
filters. They do not have to: questions in `docs/dr-egeria/resource_questions.csv` already carry
funnel stage and perspective, so **motivation selects question sets** and the existing facets do the
rest. One mapping, not a cross-product.

#### The discipline that keeps this from becoming a taxonomy nothing uses

**Every motivation must change something concrete** — which questions are asked, which survey types
run, or which disposition is offered. **If two motivations produce identical behaviour, they are one
motivation.** That is a falsifiable test, and it should be applied to this list before it is adopted:
on current evidence 4b (*evaluate robustness/security/viability*) and 3 (*is this worth using?*) may
well collapse, and 1 (*general understanding*) may turn out to be the absence of a motivation rather
than one of them.

### 5.5d-i Disposition — the vocabulary check came back negative, for the first time

§5.5d named **disposition** as the missing top layer: the system produces *evidence*, and a decision
maker wants an *answer*. It also flagged `ResourceUse` as a strong candidate, on the strength of
value names like `CERTIFY_RESOURCE`, `WATCH_DOG`, `CHOOSE_PATH` and `UNCATALOG_RESOURCE`.

**Checked, and it is the wrong axis.** Reading the descriptions rather than the names:

| value | Egeria's own description |
|---|---|
| `CATALOG_RESOURCE` | *"Extract metadata from the real-world resource and add it to the open metadata repositories"* |
| `WATCH_DOG` | *"Monitor for changes to a **metadata element** and its related elements"* |
| `INFORM_STEWARD` | *"Send notification to a steward"* |
| `UNCATALOG_RESOURCE` | *"Remove asset and associated metadata … from the open metadata repositories"* |

These are **governance operations on metadata**, not judgements about a resource. `UNCATALOG_RESOURCE`
means "stop cataloguing this", not "don't adopt this". Same mistake as reading it as a role vocabulary
in §5.5b — the names suggest a decision and the semantics are an operation.

**This is the first negative result from that check**, after `SolutionComponentType` (§3.1),
`SolutionPortDirection` (§3.2), `SolutionLinkingWire` (§3.3) and the Area 0 `SoftwareCapability`
subtypes all turned out to exist and be reusable. It was still worth running: it rules out a wrong
reuse that the value names actively invite, and it located the adjacent concept.

#### What Egeria models is the ACTION, not the RECOMMENDATION

`ToDo`, `Certification` / `CertificationType`, `GovernanceAction`, `ActionTarget` — all real, all
downstream. A disposition is upstream of every one of them: *"this looks like it should be upgraded"*
precedes the ToDo that upgrades it.

So disposition is a **small new vocabulary**, and its value is that its consequences map onto
mechanisms that already exist:

| disposition | what it leads to, all of which exist |
|---|---|
| adopt / approve | `Certification` against a `CertificationType` |
| monitor | an Automate subscription (`notification_subscriptions`), delivered as an RFA |
| act (upgrade, replace, investigate) | an RFA today, an Egeria `ToDo` when that integration lands |
| nothing to do | no action — and this must read as a *complete answer*, not an empty one |

#### Three constraints, carried from the rest of §5.5

1. **A recommendation, not a verdict.** It carries the evidence that produced it, and it must never
   imply the system decided. Same reason §5.5a(c) forbids scoring: a confident-looking output
   punishes deliberate choices the system cannot see.
2. **No score, and no ranking of resources by disposition.** "Three repos need attention" is a
   count of findings; "these repos scored worst" is not something this can support.
3. **"Nothing to do" is an answer.** For a repo the gate skipped, the disposition is
   *nothing-to-do*, and it should render like `SKIPPED_BY_DESIGN` does — neutral and complete —
   rather than as an absence. Reuse that reader-state vocabulary rather than inventing a parallel one.

### 5.5e Black box / white box — a lens derived from motivation, not a fifth axis

**Maintainer, 2026-08-23.** Some questions are answerable from the outside — *how do I operate this,
does it fit my infrastructure* — and some require looking inside — *how do I tune it, is it secure,
is it well built*.

**This is not another axis to keep apart from the other four.** It is largely *determined* by
motivation (§5.5d), so it should be **derived and shown, never selected**. Making it a user choice
would add the fifth independent filter §5.5d just warned about; deriving it costs nothing and
explains the resulting question set to the user.

| motivation | lens |
|---|---|
| 4a learn to use it | black box |
| 3 prospect — would this be useful? | black box |
| 4e expand its use | black box (mostly — fit and limits) |
| 4b evaluate robustness / security / viability | **white box** |
| 2 assess competition | **white box** (what have they actually built) |
| 4c upgrade? | **both** — compatibility is black box, breaking changes and risk are white box |
| 1 general understanding | undetermined — further evidence that 1 may be the *absence* of a motivation |

#### Why it is worth naming: we have already built one of each

- **Black box** — role classification, doc-location resolution, expectation sets (§5.5b). These read
  only what a project *exposes*: README, published docs, manifests, deployment artifacts.
- **White box** — architecture recovery. It reads source, import graphs and co-change history.

Naming the split describes structure that already exists rather than inventing any.

#### And it is approximately the funnel boundary we already have

Black-box evidence is cheap and largely already collected — GitHub API, manifests, docs. White-box
evidence needs a fetch and a parse — zipball, clone, ast-grep, import resolution. So the lens tracks
**Discovery vs Analysis/Assessment** (CLAUDE.md rule 17) closely enough to be useful as an
explanation of it.

It also explains the one case that never fit: `architecture_recovery` is **white box yet cheap**
(~5s/repo), which is exactly why it needed a named rule-17 exception. The tier is defined by *cost*,
the lens by *where the evidence lives*, and they usually but not always agree.

#### Deferred, deliberately: how the resource is exposed and consumed

The larger question the maintainer raised alongside this — *is it a library you import, a service you
call, a container you run, a dataset you read?* — is **its own thread and is not recorded here.** It
is close to role (§5.5b) without being it: a thing can be a library *and* expose a REST API. It
determines what "using it" even means, and therefore what a black-box question can be. Picking it up
should start there rather than by extending any table above.

### 5.5f The external interface is the biggest gap, and it is cheap

**Maintainer, 2026-08-23:** the external interfaces a resource exposes, and their characteristics,
are an under-analyzed aspect. Checked rather than assumed, and it is stronger than "under-analyzed":

| specified | built |
|---|---|
| `IR.ports` | **empty** — `# not in this slice`, and **nothing anywhere populates it** |
| `IR.wires` | **empty** — same |
| §5.2 step 4, "infer ports and directions from interfaces served vs. consumed" | not built |
| §5.2 step 5, "infer wires ... `protocol` / `integrationStyle` / `frequency` / `dataExchanged` / `oneWay`" | not built |
| §3.2 `SolutionPortDirection`, a 5-value enum | never written |

`ApiStructureSurveyor` does not close this — it counts symbols and module structure, which is
internal shape, not exposed surface.

#### Why this matters more than it looks: it undercuts the black-box half

§5.5e says black-box questions are *how do I operate this, does it fit my infrastructure*. But
everything black-box we have built reads **metadata *about* the resource** — README, published docs,
manifests, deployment artifacts — and **not the interface *of* the resource.**

So today the system can say *"this is an application with deployment artifacts and a current
architecture doc"* and cannot say *"it serves these three REST endpoints, consumes this Kafka topic,
and needs these two ports open."* The second is what "does it fit our infrastructure" actually means.
**The black-box half is weaker than §5.5e implies, and this is the gap.**

#### The vocabulary already exists — for the third time

`SolutionPortDirection` (§3.2) and `SolutionLinkingWire`'s properties are already in Egeria and
already in this design; nothing populates them. That is the same pattern as `SolutionComponentType`
(existed, §3.1) and the `ResourceUse` candidate for disposition (§5.5d): **check before inventing.**

#### And it is cheap — unusually so for the biggest gap

Interface evidence is disproportionately **black-box observable**, much of it in artifacts already
fetched:

- OpenAPI / Swagger documents, `.proto` files, GraphQL schemas
- compose `ports:` / `expose:`, `EXPOSE` in a Dockerfile, Kubernetes `Service` manifests
- declared entry points and console scripts (already read by `go_subsystems` and the manifest detectors)
- event topics and queue names in configuration

Most needs no source parsing at all, which puts it at **Discovery tier by rule 17's own test** —
cheap, and it gates the expensive tiers. That is an unusual combination: the largest missing piece is
also among the least expensive to start.

#### Its relationship to the deferred thread

This is the concrete, buildable half of the exposure/consumption question §5.5e deferred. **A port is
how a resource is exposed**; the deferred thread is the broader model of what kind of thing is being
exposed (library to import, service to call, container to run, dataset to read). Ports and wires can
be populated without settling that model, and doing so would give it evidence to be designed against
rather than reasoned about.

### 5.6 Tooling — what to adopt, and what it costs

Everything below is either a subprocess emitting JSON or a plain Python library. No daemons, no
servers, no persistent state — which is what makes them all trivially wrappable as microflow steps
(§5.7). Cost tier maps onto the funnel: cheap enough to run on everything that passes Scouting, versus
expensive enough to spend only on resources that earned it.

| Tool | Role | Shape | Cost | Tier |
|---|---|---|---|---|
| `scc` | file/line/comment counts, per-language, **per directory** | Go binary, JSON | ~1s on a large repo | **Discovery** |
| `ast-grep` | the §5.1 code-marker detectors, as YAML rules | Rust binary, JSON | seconds | **Discovery** |
| `dockerfile-parse` + PyYAML | container / compose / k8s / service-unit parsing | pure Python | milliseconds | **Discovery** |
| `lizard` | cyclomatic complexity, max nesting, function counts, **~15 languages** | Python lib | seconds–1 min, scales with code volume | **Discovery** |
| `syft` | SBOM across ~20 ecosystems, with package→file mapping | Go binary, CycloneDX/SPDX | tens of seconds | **Analysis** |
| `trivy` | SBOM + vulnerabilities + IaC misconfig + secrets; also ships compose/k8s/Helm/Terraform parsers | Go binary, JSON | first run pulls a large vuln DB, then seconds | **Analysis** (cache the DB) |
| `PyDriller` | per-path churn, contributors, ownership, code age — the Q11 sibling annotation | Python lib | **minutes**; needs git history | **Analysis** |
| `code-maat` | co-change coupling (§5.5) | JVM jar over `git log` output | cheap *given* the log | **Analysis** |
| Structurizr | **export target**, not extraction — validates the IR maps onto C4 | schema / DSL | n/a | optional |

**The whole detector layer is Discovery-tier.** `scc` + `ast-grep` + config parsing + `lizard` together
run in about a minute on a large repo with no network beyond the zipball. That means the component
partition — the thing everything else depends on — is affordable at estate scale and can run on every
repo that clears Scouting. This is the single most important cost fact in the design.

**Two things are genuinely expensive, and the funnel should gate them:**

- **Git history.** A full clone is the largest cost in this feature. Mitigate with `--filter=blob:none`
  (treeless — metadata without file contents, a large win) and a bounded window: bus-factor and churn
  questions almost always concern recent history, so cap at N months rather than mining the full log.
- **LLM distillation (§5.2).** Cost scales with component count and evidence volume. Gate it: invoke
  the LLM **only** for components where detector confidence falls below threshold, and **only** for
  naming, classification, and merge adjudication — small prompts over distilled evidence, never
  whole-repo reading. A repo whose architecture is fully declared (§5.1) should invoke it zero times.

Deliberately not adopted: `radon` (Python-only; `lizard` supersedes it), `grimp` (§5.5),
`scancode-toolkit` (heavy; RE's existing `repo_license_classification` is sufficient), Joern / SCIP /
stack-graphs (§10 Deferred — but note SCIP indexers emit a specified protobuf, so if symbol-granularity
`ImplementedBy` is ever needed, you consume an index rather than adopt a framework; that is the
cheapest re-entry point).

### 5.7 Wrapping as survey steps

The extension point already exists and needs no redesign: one `StepInfo` in `STEP_REGISTRY` plus one
`AnalysisKind` in `analysis_catalog.yaml`, per
`surveyors/repo_survey_definition_adapter.py`. `SurveyOrchestrator` derives its surveyor-construction
dict from `STEP_REGISTRY` automatically, and `prefect_adapter.py` dispatches by `step_name` +
`runner_kwargs` — so a new step is **Prefect-dispatchable with zero Prefect-specific work**.

Proposed steps:

| Step key | Wraps | `target_shape` | `accepts_scope_locator` | `requires_resources` |
|---|---|---|---|---|
| `repo_arch_detect` | ast-grep rules + config parsers → the IR | `corpus` | yes | `zipball_root` |
| `repo_code_metrics` | `scc` + `lizard` → §6.2 attributes | `corpus` | yes | `zipball_root` |
| `repo_sbom` | `syft` | `corpus` | yes | `zipball_root` |
| `repo_history_metrics` | `PyDriller` + `code-maat` → Q11 sibling annotation | `corpus` | yes | **`git_clone_root`** |

Three infrastructure notes, two of which are real gaps:

1. **Zipball sharing already works.** All of these need a real checkout, and `_acquire_zipball_root` +
   `trellis_microflow.resolve_resources` already dedupe it. Critically, dedup only happens *within* a
   single `SurveyOrchestrator.run()` call — which is what `_run_batch` provides. So these belong as
   **steps of one Survey Definition**, not four independent analyses: one download for the whole group.
   This is the strongest argument for the survey-path unification work.

2. **Gap: git history.** A zipball has no `.git`. `PyDriller` and co-change coupling need one. That is a
   **new `ResourceProvider` — `git_clone_root`** — alongside `_acquire_zipball_root`, doing a treeless
   clone. Q11's sibling annotation type currently has no data source without it; this is a
   prerequisite, not a detail.

3. **Gap: binary provisioning.** `scc`, `ast-grep`, `syft`, `trivy` are Go/Rust binaries, not pip
   installs. Bake pinned versions into the RE image and expose a version probe — which is precisely
   what §6.2's `analyzerVersion` is for. The network-dependent steps (`syft`, `trivy` DB pulls) want
   Prefect task-level retries; the rest are pure functions of a checkout and need none.
