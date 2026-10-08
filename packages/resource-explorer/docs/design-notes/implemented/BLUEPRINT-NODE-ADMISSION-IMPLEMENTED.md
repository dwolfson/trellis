# Blueprint node admission: implemented (2026-10-08)

Built from `DESIGN-BLUEPRINT-NODE-ADMISSION.md`, branch `re/blueprint-node-admission`.

- Each component carries an evidence class: built here, shipped here, or referenced only
  (`surveyors/arch_recovery/admission.py`). The class and a short "from <file>" / "image <name>" sentence
  are persisted on the row and shown on the node.
- Referenced-only compose services are not components. They are runtime rows in the dependency table
  (`dependency_table.py`) and are recorded as a whole-resource `architecture_admission` finding with the
  lines of what was found and not admitted.
- A repository with only referenced-only services gets zero components and the sentence pointing at
  Dependencies · runtime. The "Environment Deployment Blueprint" is offered in the selector only then.
- A person may reclassify a node with a reason (`node_admission.py`): one never-updated setting per entry,
  bound to the node's directory, honoured by the next survey.
- Compose services have no files, so their slug is their scope. A name shared by several directories is
  qualified by the whole directory path for every one of them, decided from the full census.
- A compose service merges into a Dockerfile/manifest node only if it builds that directory.

Known heuristic, left as designed: the published-image rule treats a manifest package name equal to an
image's last segment as "shipped here", even when the namespaces differ (package `kafka` makes a
`confluentinc/kafka` service shipped here). It is a proposal a person can reclassify, not a decision.
