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

## Added after the project owner's message (2026-10-06)

- **Possible regression.** The project owner says some of this is a regression in Egeria's behaviour that the
  Egeria lead will look at tomorrow. Consistent with the source: a comment above the anchor check says
  archiving is supported only on the anchor entity, yet the check cannot fire. Whether it ever worked, and
  since which build, is for her to say. Rehearsal 2's clean archive is a data point (cause not established).
  If it is a regression, the restore plan may be superseded by a fixed build, so nothing here should run
  before her answer.
- **Nested anchors for cataloguing (each layer an anchor).** Under consideration; pros and cons as seen from
  RE's side, not decided:
  - Pro: an archive or delete of a schema, table or column would walk only its own subtree, which removes
    the cross-schema cascade that caused this incident.
  - Pro: a schema could be retired on its own without hiding the database.
  - Con: RE's live-proven shapes (all elements anchored to the DATABASE) and its leave-out order, proofs and
    read-back all assume that; each would need rework and re-proof.
  - Con: existing elements are anchored to the database already; changing anchors probably means
    re-creating them, which is the same name-collision problem as this restore.
  - Con: anchors also decide visibility and delete cascade for everything under them, so a table anchored
    on its own schema changes what a database-level delete reaches. Behaviour of the template create and
    the JDBC cataloguer with nested anchors is not known; they would need a throwaway trial.

## Review additions (architect, 2026-10-06; items marked CHECK were not verified by me)

**Approach A needs these steps added:**
1. Detach the NEW schemas' catalog targets (by relationship GUID, read first) before retiring the new tree.
   Otherwise the connector keeps two targets per name, one on an archived element, and the restored
   coco_sus/coco_ods targets compete with them. The daemon already shows this state for scratch_cat_test6.
2. Move RE's registry with Egeria. The database record's Egeria element pointer (CHECK the exact field
   name, the architect calls it egeria_asset_guid) and the roll-forward commit's proof rows point at
   def55997. After a restore, write a proof row "restored · 17f0a963 · from def55997 · <when> · by <who>" and
   set the pointer back; otherwise every status on the page derives from rows naming the wrong element. If
   B is chosen, write "rolled forward · def55997 · previous 17f0a963 archived".
3. Rename-aside must cover every new element that took an old element's name: the two schemas, the
   database and its four connection elements, and any new SurveyReport or annotation sharing a deterministic
   name with an old one. 56 of 76 annotations suggests about twenty collided; read before the trial.
4. The old coco_sus schema type and schema-level connection are LIVE with original names and relationships
   intact (read 17:5xZ); the old coco_ods schema type is live too (its schema-level connection was NOT read:
   CHECK). After declassify and rename-back they should rejoin without work. This is why A restores a
   cataloguable tree and B does not.
5. Order: anchor first (the database), then children, because a read of a child can return 500 while its
   anchor is Memento (the symptom seen). The trial confirms.

**Trial additions.** After the deliberate cascade, read the database by GUID and expect the 500; declassify
the database alone and read again before touching any child. That answers question 3 with one call. The
trial database needs two schemas and a table with a term assignment, so the cascade and the surviving
relationships both reproduce.

**Why A is consistent with roll-forward.** The archive was not an intended state change but a defective
write; Egeria keeps the versions either way; the correction is recorded as a forward event (the
"restored" proof row). If the Egeria lead's fix lands first, B becomes a re-run on the fixed build rather than
a plan.

**Nested anchors, what the first cons missed.**
- The anchor is Egeria's choice (template and cataloguer), not RE's: RE can only follow. The real question
  for the Egeria lead is whether her cataloguer and template will change.
- A transition leaves mixed trees (old elements anchored to the database, new ones to the schema), so RE's
  leave-out preview must read each element's Anchors classification and not assume the shape. That is right
  regardless.
- Visibility and zones are evaluated through the anchor, so nesting changes which element's zone governs a table.
- Pro: schema-kind targets already make the schema the unit of cataloguing; nested anchors would make it
  the unit of archive too.
- The anchor check that cannot fire is a bug whatever the anchoring. Nested anchors shrink the blast radius
  without fixing it. Keep the fix and the redesign apart.
