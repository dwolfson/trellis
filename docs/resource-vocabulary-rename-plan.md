# Renaming `project` → `resource`, and `group` → `org`

**Status: plan, not started (2026-08-28).** Sequenced behind in-flight work — see §5.

## 1. The vocabulary, as it now stands

| term | means | today's code |
|---|---|---|
| **Resource** | one thing in the inventory — a repo, a filesystem, a database, and in principle any kind | `Project`, `ProjectRegistry`, `project_slug`, `projects` table |
| **Org** | a group of resources | `group`, `group_create`, `group_assign` |
| **Project** | an **Egeria Project** — nothing else | collides with the above |
| **Investigation** | one body of work; members are resources | already correct |

`docs/investigation-framing-design.md` §7 recorded that "project" meant three different things and
called it half the problem. Those three were separated in the domain; the code kept the old word
for all of them.

**`resource`, not `repo`.** RE ingests repos, filesystems and databases through one
`ResourceTypeAdapter` funnel, and a metadata repository was deliberately absorbed as "just another
resource type" rather than a new concept. `repo` is accurate for most rows today and wrong for
rows that already exist.

## 2. What renames

- `ProjectRegistry` → `ResourceRegistry`; `Project` → `Resource`
- `project_slug` → `resource_slug` throughout (parameters, columns, dict keys)
- `projects` table → `resources`, and every table with a `project_slug` column
- `group_*` CLI commands and their registry methods → `org_*`
- `_CTYPE_LANGUAGE`, route paths (`/api/projects/...`), UI labels, help text

## 3. What does not rename, and why

**Egeria-side names stay.** `entity_egeria_project_context`, `egeria_project_guid`,
`set_investigation_egeria_project` all refer to real Egeria Projects. Those are correct already and
renaming them would recreate the collision from the other direction.

**pgvector collection names — but see §4.** Collections are `f"{project_slug}_{ctype.name}"`
(`ingestion/pipeline.py:134`), so slugs are baked into live vector-store collection names. Renaming
the *identifier* is mechanical; renaming the *data* means migrating every collection.

## 4. The wipe changes the shape of this

A pgvector wipe-and-reingest is wanted eventually — "not urgent but clean". **It should happen
with this rename, not separately.**

Doing them apart means either carrying a legacy `{project_slug}_` wire format indefinitely behind
renamed code, or migrating collection names once and wiping them again later. Doing them together
makes the only genuinely hard part of the rename free: there is no data to migrate if the data is
being rebuilt.

Sequence: export the resource inventory (slugs, URLs, collections, org membership, investigation
membership) → rename the code → wipe pgvector → re-ingest from the export. The export is worth
building regardless; nothing today can reproduce the inventory if the store is lost.

## 5. Sequencing

1. **Admin repair operations land first.** They are in flight and touch `registry.py`,
   `cli/main.py` and the web routes — exactly the rename's surface. Renaming underneath them would
   guarantee conflicts in a checkout several sessions share.
2. **Build the inventory export.** Independently useful, and §4 depends on it.
3. **Rename**, in one pass rather than incrementally. A half-migrated vocabulary is worse than
   either end state: `resource_slug` and `project_slug` coexisting means every reader has to know
   which is which.
4. **Wipe and re-ingest** from the export.

## 6. Guardrails

- A single mechanical pass, reviewed as one diff. No behaviour changes smuggled in.
- The full suite (2680 passed, 10 skipped) is the gate. It exercises the registry heavily, so a
  missed rename in a query string surfaces there rather than in production.
- `tests/test_no_silent_success.py` keys its baseline on `path::function`, so **renaming a function
  makes its baseline entry stale and fails the ratchet.** Expect to rewrite baseline keys; that is
  a rename, not a regression, and the file may still only shrink in count.
- Investigation membership, dispositions and working sets all key on `entity_slug` with an
  `entity_type` of `"repo"`. That literal string is data, not an identifier — decide deliberately
  whether it becomes `"resource"`, and if so migrate the rows.
