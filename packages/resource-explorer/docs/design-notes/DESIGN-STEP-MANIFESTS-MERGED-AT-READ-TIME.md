# Design: installed step manifests merge into the analysis catalog at read time

Status: built on branch `claude/re-ext-followups-928989`, 2026-10-29. Follows finding F1 of the Architect's
extensibility gate walk (`GATE-RESULT-EXTENSIBILITY-FS-2026-10-28.md`): "adding a step still needs a regeneration
commit in RE." It changes how `analysis_catalog.yaml` is read, which the Architect flagged as a design change, so the
decision is written here.

## 1. What changed

`analysis_catalog_reader._load` still reads `configdata/analysis_catalog.yaml`. It now also reads the installed
`trellis.analytics` step manifests (`survey_step_host.discover_steps`, per resource type) and merges them in, using the
same function that writes the generated block (`survey_step_host.catalog_entry`), so a merged entry and a generated one
cannot differ in shape:

- a manifest whose step has **no committed entry** is appended to its resource type's list;
- a manifest whose step **has a committed generated entry** replaces it in place (same position, same id);
- a manifest that takes the id of a **built-in** (non-`provided_by`) analysis is refused and logged, as `attach` already
  refuses it.

Adding a step is now: install the package, restart RE (or call `survey_step_host.refresh`). No commit in RE. The card,
the run, the declaration, Chat's compile and Curate's publish table all read through `_load()`, so they see it.

## 2. Decision: the committed generated entries stay, as the fallback

The entries already on main between the GENERATED markers are **kept**, and the generator stays. Reasons:

1. **A step whose package is absent still needs an entry.** The catalog is the only record of a step that is not
   installed in this process (the web process may lack a package the Prefect worker has, or the reverse). The "step not
   installed here: 'x' comes from package P v" card, the Run button's disabled reason, and the "N missing: ..." part of
   the start-up line all come from a catalogued entry with no manifest to match. Removing the entries would turn "not
   installed here" into "does not exist", which is absence read as nothing.
2. **Installed wins.** When the package is installed its manifest is the source, so the committed copy can no longer
   drift from it in what RE shows; the staleness test keeps the committed copy honest as a fallback only.
3. **Nothing is lost by keeping them.** A step added later and never regenerated simply has no fallback: it shows as
   absent only if its package is not installed, which is the true state of the world.

So regeneration is now **optional**: run it when you want a package-less environment to know the step exists and say why
it cannot run. Nothing breaks if you do not.

## 3. Open question: a question a step declares

A manifest declares `questions=["Q-0041"]`, by id. That already works for a question the catalogue **holds**: the merged
entry's `provided_by.questions` becomes the declaration's `answers`, and Chat routes by them.

It does **not** make a **new** question available. A question row needs text, a stage, perspectives, purposes, levels and
a rationale, and an id from the append-only sequence (`Q-0107`, `Q-0108` were hand-written configdata rows). A manifest
carries the id only. Merging "a question the step declares" with no configdata row therefore needs a decision this slice
does not make:

- **Who allocates the id?** The catalogue's ids are assigned once and never reused (`reserved_question_ids`); two
  packages declaring `Q-0200` would collide. Options: a package-qualified id (`pkg:Q-1`), or an id RE hands out when the
  package is first seen and records.
- **What does a manifest carry?** At least `question` text and `stage`; perspectives and purposes are suggestive
  elsewhere (warn, never reject), so they could default.
- **Where does the merged row live?** In the same read-time merge as the analyses (`question_catalog_reader._load`), with
  a marker saying the row came from a package and must not be edited in configdata.
- **Retirement.** The catalogue is append-only: a question must outlive an uninstalled package, which argues for RE
  persisting the row once seen (a registry table: DDL, so the coordinator's decision).

Until the project owner decides, a new question still needs a configdata row, and the step's manifest then names its id.
