# Restore plan for the coco_pharma archive cascade, 2026-10-06 (PLAN ONLY, nothing run)

Status: prepared read-only at the project owner's request. No write to Egeria has been made. Every step
below needs the owner's word, a peer round, and the answers from the Egeria lead where marked.

## Before-state (read-only, ~18:30Z)

A name search for `_archivedOn_` with forLineage true found 148 renamed elements, all Memento; plus the
`us_sales` schema 87271b37 (Memento, NOT renamed, found by GUID). 149 in all. Full list with GUIDs:
`RESTORE-BEFORE-STATE-2026-10-06.json` in this folder.

| Group | Count | Note |
|---|---|---|
| database `coco_pharma` 17f0a963 | 1 | renamed |
| its connection graph (VirtualConnection, Endpoint, SecretsStoreConnection, SecretStoreEndpoint) | 4 | renamed |
| schemas coco_sus 28bbde37, coco_ods a358abb3 | 2 | renamed; their schema types and connection graphs are still LIVE |
| schema us_sales 87271b37 | 1 | Memento, not renamed |
| us_sales schema type, table, 11 columns | 13 | renamed several times (one suffix per archive pass) |
| us_sales schema-level connection graph (VirtualConnection, Connection, 2 Endpoints) | 4 | renamed several times |
| SurveyReports of the old database | 4 | renamed |
| ResourceMeasureAnnotations (survey results) | 120 | renamed |

Repeated `_archivedOn_` suffixes show RE's per-element archive calls each re-triggered the whole-tree
walk. Restoring means stripping ALL suffixes from each name.

New elements that now hold the original names: database def55997, its connection graph (d98b8ad5 and
siblings), schemas 4079a1d5 (coco_sus) and 1f31b602 (coco_ods).

## Constraint: names are unique

Putting an original name back fails while another element holds it. So the new elements must be renamed
aside first. A property edit of `qualifiedName` is an in-place update, not an archive or delete, so it is
not expected to cascade. (Not proven; trial first.)

## Approaches

**A. Old wins (closest to undo).** 1) Rename the new elements aside, in place, with a `_rollforward` suffix.
2) For each of the 149 old elements: declassify `Memento` (pyegeria `declassify_metadata_element(guid,
"Memento", body)` with `forLineage: true`, per the owner), then rename back by stripping every
`_archivedOn_...` suffix. Order to be decided by the trial (children first, or anchor first).
3) Re-attach a catalog target for us_sales through RE (its target was detached by RE earlier). coco_sus
and coco_ods still hold CatalogTarget relationships. 4) Retire the new tree by archiving its OWN anchor,
def55997, which walks only the new database's tree (the intended use of archive). 5) Read everything back
through RE.

**B. New wins.** Leave the old tree archived. Free the schema-level names by renaming the old, live
`coco_sus`/`coco_ods` schema types and connection graphs aside, then get a ResourceConnection onto the new
schemas. Unclear how without re-running the template create; weaker.

**Recommendation:** A, after a throwaway trial. B only if Mandy says the restore is unsafe.

## Throwaway trial (before touching coco_pharma)

1. Build a throwaway database with two schemas in Egeria by the same template route RE uses, backed by a
   scratch Postgres database (the existing scratch_cat_test databases may be gone).
2. Archive ONE schema, to reproduce the cascade on purpose. This is itself useful evidence for Mandy.
3. Try approach A on it, step by step, reading back after each: rename-aside edit, declassify with
   forLineage, rename back. Record whether any step cascades or fails (the 500 on reading the database is
   the case to watch).
4. Only if the trial restores a working, readable, cataloguable tree, plan the real run.

## Questions that decide the order (for the Egeria lead)

1. Is declassifying Memento plus renaming back safe, or does Egeria need an internal restore?
2. Does declassify cascade the way archive does (does it walk the anchor tree)?
3. Does the archived database's 500 on read go away once it is declassified?
4. Is there a restore for soft-deleted items yet (the owner says it is on the list)? Not needed for this
   incident, all elements here are archived.

## Not decided

Whether to restore at all or to roll forward. The project owner decides, with the Egeria lead's answers.
