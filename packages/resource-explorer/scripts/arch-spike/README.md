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
```

## Files

| File | Role |
|---|---|
| `exclusion.py` | first-party filter — runs before everything (plan §3a) |
| `ir.py` | the Architecture IR (design §5.3) + evidence records (§5.4) |
| `detectors.py` | manifest, deployment-unit, and compose detectors (§5.1) |
| `detect.py` | CLI: exclusion → detect → IR |
| `score.py` | detector IR × ground truth → component-set + file-partition scores (plan §5, §5a) |
| `rules/` | ast-grep rules — **not yet populated** |

## Status

Built: exclusion, IR, manifest/Dockerfile/compose detectors, scoring.
Not built: ast-grep code markers, `imports.py`, `cochange.py`.

## Running the scorer

```bash
python3 score.py trellis                # logical GT — diagnostic only, see finding 13
python3 score.py egeria-workspaces      # deployment GT — the scoreable T1 result
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

