# Curation lenses — measurement spike

**Run 2026-09-08 against the shared registry (Postgres `egeria_advisor`, schema
`resource_explorer`), read-only.** Answers §8 of `../curation-lenses-design.md`.
Script: `scripts/curation_lenses_spike.py`; raw JSON `curation_lenses_spike.json`
under the run's `--out`.

Headline: **the cut depth is not what controls the decision count, and all four
of §8's "what would change the design" outcomes fired.** kafka's Maintain cut
yields 329 decisions; import cohesion is a classifier, not a ranking; and every
human-accepted node in the corpus sits *below* every cohesion bar.

## 1. Method

Nothing was recomputed. `clustering.propose()` was not re-run.

- **Cluster hierarchy** from `project_analysis_findings`,
  `kind="architecture_blueprints"`, `check_name="candidate_blueprint"` — the rows
  `persist.py::_persist_blueprints` writes (`name`, `perspective`, `signal`,
  `carrier`, `size`, `members`, `children`, `oversized`). Latest run **per
  perspective**: `repo_arch_detect` (physical, deployment) and
  `repo_arch_coupling` (logical) are independent steps with their own
  `surveyed_at`.
- **Component hierarchy** from `kind="architecture_recovery"`,
  `check_name="component"` (latest row per `scope_locator`, as
  `_architecture_recovery_results` does). Its `parent_slug`/`depth` carry the
  deep tree; the stored *cluster* tree is at most two levels, because
  `clustering.rollup` nests one level over a flat leaf list. The two are
  **stitched into one forest** (rollup cluster → leaf cluster → component
  subtree), since §4.2's cut is over both. Depth 0 = a root cluster.
- **Cohesion** from `project_analysis_metrics` (`import_cohesion`,
  `cochange_cohesion`, per component scope), aggregated to a node as the mean
  over its component leaves. **Semantic cohesion**: TF-IDF (log-TF, smoothed IDF, L2-normalised) over
  identifiers and docstrings from `project_code_symbols`, one document per
  component scope (files assigned to their deepest prefix scope); a node's value
  is the mean pairwise cosine among member documents. No sklearn. **Human
  verdicts** come from `architecture_component_verdicts`.

### Parameters — every choice §8 left open

| Parameter | Value | Basis |
|---|---|---|
| `CUT_DEPTH` | deploy 1, learn 2, maintain 4 | **chosen** — numeric reading of §5's "coarse / medium / fine" |
| `LENS_PERSPECTIVES` | deploy `[deployment, physical]`, learn `[logical]`, maintain `[logical, physical]` | §5's table |
| `LENS_DECIDERS` | deploy `import`, learn `semantic`, maintain `import`+`cochange` | §5's "cohesion that decides" column |
| `IMPORT_BAR` | 0.35 | **reused** from `coupling.COHESIVE_BAR`, not redefined |
| `COCHANGE_BAR` | 0.35 | **chosen.** Change coupling has never had a bar here; set equal to the import bar so both read off one number. Measured below to be badly wrong. |
| `SEMANTIC_BAR` | 0.30 | **chosen.** Mean pairwise cosine runs far below an edge-ratio metric; a first guess. |
| `MIN_COVERAGE` | 0.5 | a family abstains unless it has values for ≥50% of a node's leaves; abstention is reported apart from disagreement |
| `DEPLOY_MIN_TOUCHPOINTS` | 2 | §5's "more than one external touchpoint"; touchpoints = ports + wire endpoints from `kind="architecture_interfaces"` |
| `SEMANTIC_MAX_MEMBERS` | 24 | cap on the pairwise cosine; members sampled deterministically |

**Stop rules as implemented.** Deploy: closed when touchpoints < 2. Learn: "open
only if it exposes an interface" — declared ports essentially do not exist for
logical components, so the proxy is *any public symbol under the node*, which is
weak and nearly always true. Maintain: force-open when change coupling is below
the bar; its *"never close a hotspot"* half is **not implemented**, because
`project_commits` stores sha/message/author/date and **no per-file change data**,
so churn per component cannot be derived from the registry.

### What the data does not have — stated, not approximated

**The import graph is not persisted.** Only `import_cohesion` (a ratio) and a
prose excerpt from `coupling.classify_subtree` survive, so boundary fan-in and
fan-out here come from the **only** stored edge set,
`project_code_relationships` with `relationship_type='inherits_from'` (kafka
1459 edges, egeria-python 168, docling 182, after dropping class names defined
in more than one file). That is an inheritance proxy, not the import graph the
cut rules mean; treat every fan number as indicative. Change coupling *is*
stored (`cochange_cohesion`), so no `git log` ran and no clone was touched.
kafka has **zero verdicts**, so step 5 does not exist for it. docling's
`packages` cluster resolves to no logical component and was dropped as empty.

## 2. Coverage, overlap, stragglers

| Repo | Perspectives stored | Components (logical) | Covered by a cluster | Reachable by >1 cluster | Stragglers |
|---|---|---|---|---|---|
| kafka | deployment, logical, physical | 609 | 418 | **189** | 191 |
| egeria_python_git | logical only | 85 | 67 | 6 | 18 |
| docling | logical, physical | 104 | 77 | 7 | 27 |

Two facts the design should absorb. **The stored cluster set is not a
partition** — kafka has 189 logical components reachable through more than one
leaf cluster (e.g. `.../clients` exists both as a cluster and as a component):
§1's "Overlap", *within one perspective and one extractor*. And **the straggler
queue is already a third of the repo** (191 / 27 / 18) before any lens runs,
because `clustering.propose` drops what no boundary groups.

## 3. Decisions at the cut

`accept` = deciders say cohesive and every family with an opinion agrees;
`contested` = families disagree or the node is `oversized`; `review` = every
family with an opinion agrees the node is *not* cohesive; `no-signal` = the
lens's own decider abstained.

| Repo | Lens / perspective | Decisions | size min/med/max | accept | contested | review | no-signal | stragglers |
|---|---|---|---|---|---|---|---|---|
| kafka | deploy / deployment | 30 | 1/1/1 | 0 | 0 | 0 | 30 | 1 |
| kafka | deploy / physical | 2 | 1/1/1 | 0 | 0 | 0 | 2 | 0 |
| kafka | learn / logical | **347** | 1/1/17 | 1 | 40 | 28 | 278 | 191 |
| kafka | maintain / logical | **329** | 1/1/5 | 4 | 13 | 297 | 15 | 191 |
| kafka | maintain / physical | 2 | 1/1/1 | 0 | 0 | 2 | 0 | 0 |
| egeria_python_git | learn / logical | 29 | 1/1/27 | 0 | 4 | 0 | 25 | 18 |
| egeria_python_git | maintain / logical | 59 | 1/1/1 | 2 | 4 | 51 | 2 | 18 |
| docling | deploy / physical | 1 | 2/2/2 | 0 | 0 | 0 | 1 | 1 |
| docling | learn / logical | 37 | 1/1/32 | 0 | 2 | 0 | 35 | 27 |
| docling | maintain / logical | 72 | 1/1/1 | 2 | 5 | 65 | 0 | 27 |

**Deploy is unavailable where §5 needs it most.** Neither docling nor
egeria-python has a stored *deployment* perspective; egeria-python has no
physical one either. kafka's deployment cut is 30 nodes of size 1 — legible, but
all `no-signal`, because the coupling step writes cohesion for logical scopes
only and never for deployment components. **Median node size is 1 everywhere:**
the cut is producing the straggler queue §6.5 wanted demoted, not components
made of components.

### Cut depth barely moves the number (`CUT_DEPTH` 0…5, all else fixed)

| Repo / lens | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| kafka learn/logical | 156 | 349 | 347 | 326 | 320 | 318 |
| kafka maintain/logical | 163 | 363 | 367 | 340 | 329 | 327 |
| docling learn/logical | 10 | 37 | 37 | 37 | 37 | 37 |
| docling maintain/logical | 19 | 75 | 73 | 72 | 72 | 72 |
| egeria_python learn/logical | 11 | 30 | 29 | 29 | 29 | 29 |
| egeria_python maintain/logical | 10 | 60 | 59 | 59 | 59 | 59 |

Everything happens between depth 0 and 1; after that the tree is exhausted.
**The lens's depth is not the control** — what controls the count is the number
of root clusters, §4.2's always-open rule for `oversized`, and the force-open
stop rules, exactly the three things §4.2 calls "adjustments".

## 4. Family agreement

Nodes at each cut; a family below `MIN_COVERAGE` abstains rather than votes.

| Repo / lens | agree | disagree | <2 opinions |
|---|---|---|---|
| kafka learn/logical | 233 | 40 | 74 |
| kafka maintain/logical | 235 | 13 | 81 |
| egeria_python learn/logical | 9 | 4 | 16 |
| egeria_python maintain/logical | 13 | 4 | 42 |
| docling learn/logical | 29 | 2 | 6 |
| docling maintain/logical | 29 | 5 | 38 |

The agreement is real but nearly vacuous: kafka's largest matrix cell is
`import=false, cochange=false` at 205 of 347 nodes, plus 28 more with
`semantic=false` too. **The families agree because everything is below every
bar.** Semantic cohesion is the only family that says "true" in bulk (26 kafka
nodes where import and co-change both say false).

**The disagreeing nodes**, largest first — the expected human questions:

- kafka `clients/src/main/java/org/apache/kafka/clients` (size 9, and again at
  size 8 as the overlapping cluster/component pair): import 0.009, co-change
  0.130, **semantic 0.337**. `coordinator-common/src` (3): 0.002 / 0.194 / 0.375.
  `group-coordinator/.../group/modern` (3): 0.004 / 0.023 / **0.483**, and its
  `src/test` twin (3): 0.0 / 0.019 / 0.374. `.../oauthbearer/internals/secured`
  (2) and its test twin (2): semantic 0.333 / 0.329 against near-zero import.
  `docker` (1): **import 0.875**, co-change 0.34 — the one place import cohesion
  is high and change coupling is not.
- egeria-python `my_egeria/my_egeria/DemoCode` (5): import 0.113, **co-change
  0.411**, semantic 0.502 — and this node is human-**accepted**. `pyegeria/omvs`
  (1): 0.054 / 0.414; `examples/surveys` (1): 0.286 / 0.471; `tests/micro-tests`
  (2): 0.0 / 0.028 / semantic 0.342.
- docling `docling/models/inference_engines` (4): import 0.382, co-change 0.083,
  semantic 0.361; `docling/backend/docx/latex` (1): **import 0.966**, co-change
  0.190; the four `inference_engines/*` children all sit at import ≈0.35–0.41
  against co-change ≈0.07–0.11.

The pattern is consistent and is the informative part: **import cohesion and
change coupling disagree about test trees and about `inference_engines`-style
plugin families, and semantic cohesion sides with change coupling.**

### The bars are wrong, measurably

Distribution of the two stored families, all scopes, latest values:

| Repo | metric | n | =0 | 0–0.1 | 0.1–0.3 | 0.3–0.5 | 0.5–0.9 | 0.9–1 |
|---|---|---|---|---|---|---|---|---|
| kafka | import | 494 | 397 | 79 | 10 | 0 | 4 | 4 |
| kafka | co-change | 510 | 149 | 265 | 78 | 16 | 1 | 1 |
| egeria_python | import | 39 | 20 | 9 | 8 | 0 | 2 | 0 |
| egeria_python | co-change | 72 | 11 | 42 | 13 | 2 | 3 | 1 |
| docling | import | 46 | 25 | 9 | 4 | 7 | 1 | 0 |
| docling | co-change | 106 | 13 | 65 | 21 | 3 | 4 | 0 |

kafka's import cohesion is **96% below 0.1** with *nothing* between 0.3 and 0.5
— `clustering.py`'s 2026-08-29 measurement reproduces exactly. Co-change is
graded but low: 17 of 510 kafka values reach 0.3, so `COCHANGE_BAR = 0.35`
force-opens almost every node, which is why Maintain shows 297 of 329 nodes as
`review`. **That bar must be set from the distribution (a percentile), not
borrowed from the import bar.**

## 5. Agreement with human verdicts

Sample sizes, all **anecdotal** by §8's own rule (<20 per repo):

| Repo | verdict rows | distinct component scopes | accepted | rejected |
|---|---|---|---|---|
| kafka | 0 | 0 | — | — |
| egeria_python_git | 4 | 4 | 4 | 0 |
| docling | 19 | 9 | 5 | 4 |

Several docling rows are the same scope re-clicked seconds apart (`docs` five
times) and one carries the note "test note" — UI-exercise data, not a curation
session. Worse: docling's verdicts are on *physical* scopes (`packages/docling`,
`perfs`, `.actor`) while Learn and Maintain cut the *logical* tree, so only
`docs` and the two `.agents/skills` scopes intersect at all.

MoJo (Tzerpos & Holt, IWPC 1999; MoJoFM per Wen & Tzerpos 2004) between each cut
and the partition the accepted scopes imply, over objects the human ruled on:

| Repo | Lens / perspective | n objects | human groups | cut groups | MoJo | MoJoFM |
|---|---|---|---|---|---|---|
| egeria_python_git | learn / logical | 27 | 4 | 18 | 14 | 39.1% |
| egeria_python_git | maintain / logical | 27 | 4 | 22 | 18 | 21.7% |
| docling | learn / logical | 11 | 5 | 5 | 4 | 33.3% |
| docling | maintain / logical | 11 | 5 | 7 | 4 | 33.3% |
| docling | deploy / physical | 5 | 5 | 1 | 1 | 0.0% |
| docling | maintain / physical | 5 | 5 | 2 | 0 | 100.0% |

**Do not read these percentages.** MoJoFM's denominator (n − |B|) is 1 for the
docling physical rows, so 0% and 100% are the same non-measurement. Only
egeria-python has content: the Learn cut needs 14 move/join operations to reach
a 4-group human answer over 27 objects and Maintain needs 18 — **the cut is much
finer than the curator's answer**, consistent with §3's median size of 1.

**Are accepted nodes the ones where the families agree?** Every accepted node:

| Repo | accepted scope | size | families holding | agree | cohesive under bars |
|---|---|---|---|---|---|
| egeria_python | `my_egeria/my_egeria` | 12 | 2 | yes | **no** |
| egeria_python | `my_egeria/my_egeria/DemoCode` | 5 | 3 | **no** | **no** |
| egeria_python | `md_processing` | 6 | 3 | yes | **no** |
| egeria_python | `pyegeria` | 4 | 3 | yes | **no** |
| docling | `docs` | 4 | 3 | yes | **no** |
| docling | `.agents/skills/dignified-python` | 4 | 1 | — | **no** |
| docling | `.agents/skills/building-pydantic-ai-agents/references` | 1 | 1 | — | **no** |

Families agree on 4 of the 5 accepted nodes where two or more had an opinion —
but they agree *below* the bar. **Not one human-accepted component is cohesive
under any of the three bars.** "The families agree" does not discriminate
accepted from rejected here, because they agree almost everywhere; what the
curator accepted are top-level named packages (`pyegeria`, `md_processing`,
`docs`, a skill directory) — a **naming and packaging** signal none of the three
families measures.

## 6. Cost

Wall clock for steps 1–4, one process, warm Postgres, M3 Max: kafka 1.11 s (of
which 0.74 s is the step-1 load), egeria_python_git 0.13 s (0.12 s), docling
0.11 s (0.10 s). **Re-cutting interactively is not a performance problem** — the
cost is the one-time load, and a re-cut over trees already in memory is
milliseconds.

## 7. Recommendations — one per lens

- **Deploy: cut as proposed (depth 1), but the lens is untested.** 30 legible
  nodes on kafka is the right order of magnitude and depth beyond 1 changes
  nothing — but two of three repos have no deployment perspective, and every
  kafka deployment node is `no-signal` because no cohesion metric is written for
  deployment scopes. Either the coupling step must produce something for them,
  or the lens must declare that it decides on ports and wires alone.
- **Learn: shallower.** Depth 2 gives 347 decisions on kafka at median size 1;
  depth 0 gives 156 — still too many, but the curve says the useful cut is at or
  above the roots. The lens's own decider (semantic cohesion) abstained on 278
  of 347 kafka nodes and 35 of 37 docling nodes, so as specified it has no
  opinion at all.
- **Maintain: shallower, and re-bar first.** Depth 4 gives 329 on kafka, depth 0
  gives 163; neither is workable, and the force-open rule at
  `COCHANGE_BAR = 0.35` is what produces them — 297 of 329 nodes opened by a bar
  only 3% of measured values clear. Set the bar from the distribution and
  re-measure before touching the depth.

## 8. Which of §8's four outcomes occurred

1. **"Maintain on kafka still yields several hundred decisions" — YES, 329.**
   §4.2's stop rules are not enough. The stored cluster tree is only two levels
   deep, so there is nowhere for a cut to land between "29 roots" and "the
   component tree"; another roll-up level is a prerequisite for the interface.
2. **"The families agree almost everywhere" — YES, but uninformatively.**
   kafka: 233 agree / 40 disagree at the Learn cut, agreeing that nothing is
   cohesive. One score would suffice today and the contested queue is small
   (40, 13, 4, 5, 2), so the DSM view does *not* earn its place early.
3. **"Accepted nodes are not the ones where signals agree" — YES.** Every
   accepted node is below every bar. On this anecdotal sample (n=9 distinct
   scopes) curators appear to be trusting **top-level package naming and
   directory identity** — `pyegeria`, `md_processing`, `docs`,
   `packages/docling` — which none of the three families measures. §6's routing
   rule should not be built on cohesion until that is measured against a real
   curation session.
4. **"Import cohesion stays as bimodal as `clustering.py` measured" — YES.**
   kafka: 397 of 494 exactly zero, 96% under 0.1, nothing between 0.3 and 0.5.
   A classifier, not a ranking. Change coupling and semantic cohesion must carry
   the ordering, and change coupling needs a bar from its own distribution.

Outcome 2 is the only one arguing *for* simplifying the design; 1, 3 and 4 all
say the interface should not be designed on the current signal set.
