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
| `rules/` | ast-grep rules — **not yet populated** |

## Status

Built: exclusion, IR, manifest/Dockerfile/compose detectors.
Not built: ast-grep code markers, `imports.py`, `cochange.py`, `score.py`.

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

**8. Scale behaves, so far.** `egeria` yields 231 Gradle modules from `settings.gradle`,
deliberately not expanded into components in this slice (plan §3, T3 — the question is
shape, not leaves). Worth noting the count differs from the 254 `include` lines counted
by grep during planning: 231 is after deduplication and comment-stripping.
