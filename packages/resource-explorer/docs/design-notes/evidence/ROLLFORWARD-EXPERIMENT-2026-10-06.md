# Roll-forward experiment on coco_pharma, 2026-10-06 (predictions written BEFORE the commit)

Question: after the ISSUE-117 cascade, does a new commit on the unchanged 8813 build (46aaf5db,
no block) re-catalog onto NEW elements, with nothing undone in Egeria?
Authorised by the project owner (in this session, 2026-10-06, while away; the owner changes the
`us_sales` choice and reviews afterwards). Nothing is detached, archived, restored or deleted by anyone.

## Pre-state (read-only, 2026-10-06)

Registry latest choices for `localhost_docker_coco_pharma`: coco_ods catalogue, coco_sus catalogue,
us_sales **leave_out** (must be set to catalogue before the commit), eu_sales leave_out (never cataloged),
target_sales leave_out (set 14:41; not yet shown to have any element in Egeria, to be read first).
Newest proof row: id 35 `archived` us_sales 87271b37 (16:15).

Egeria, read by GUID: database 17f0a963 Memento, QN `…coco_pharma_archivedOn_Tue Oct 06 16:04:25 GMT 2026`;
schemas 28bbde37 coco_sus, a358abb3 coco_ods, 87271b37 us_sales all Memento; table 9863e995 Memento.
Cataloguer targets as read now: an EMPTY list (not the 3 the architect expected). Empty may mean the
targets were removed, or hidden because their elements are Mementos; NOT yet determined.

## Pre-state refreshed 2026-10-06T16:58Z (minutes before the press)

- Registry: us_sales = catalogue (set 16:57:33 by the owner); coco_sus, coco_ods catalogue; eu_sales and
  target_sales leave_out.
- Egeria lookup by template qualifiedName for eu_sales, target_sales, us_sales: "No elements found" (us_sales
  is a hidden Memento, the other two were never created by RE). Nothing for a leave_out to remove.
- FINDING in its own right: the JDBC cataloguer's catalog-target list reads EMPTY at 16:58Z (read twice,
  16:5x and 16:58). Cause undetermined: removed, or hidden because the elements are Mementos.
- Database 17f0a963, schemas 28bbde37, a358abb3, 87271b37 and table 9863e995 all still Memento.
- Peer round: Portal clear, egeria-python-20 clear, PR/CI not yet answered, architect: owner presses.

## Predictions

1. Publish: the database name no longer resolves, so RE creates a NEW database element with the original
   name. Old 17f0a963, new GUID recorded. The server lookup by name still finds d87059ce.
2. Schemas coco_sus, coco_ods, us_sales: new elements under the new database (DataSetContent), new GUIDs.
3. Attach: IF the 3 old targets are still listed (Mementos, same catalogTargetName) the guard matches by
   name, reports "already attached" and initiates nothing, so the cataloguer never builds tables under the
   new schemas. That is the defect the experiment exists to show (guard must match on element GUID and
   ignore targets whose element is archived). IF the list really is empty, the guard attaches normally and
   this prediction fails; record which.
4. Report: the SurveyReport by name was renamed too, so a new report with 76 annotations.
5. Ownership recorded on the new database.
6. Survey: a new engine action limited to the three schemas.

## Observed (filled in after)

Commit pressed by the owner on 8813 at about 16:59Z. Proof rows 36-47, read back by GUID at 17:35Z.

1. Publish: CONFIRMED. New database `def55997` (RelationalDatabase, not Memento, original QN
   `PostgreSQL Relational Database::host.docker.internal:5442::coco_pharma`). Old 17f0a963 untouched, still Memento.
2. Schemas: CONFIRMED for coco_sus (new 4079a1d5) and coco_ods (new 1f31b602), original names, not Memento.
   us_sales was NOT re-catalogued: RE's own guard held it ("can't be re-included until Egeria restores
   archived elements"); its Memento 87271b37 still holds the original name.
3. Attach: PREDICTION FAILED, in the sense that the defect did not appear. The target list was already EMPTY
   before the press (read 16:58Z), so there were no stale targets to match by name. Two new targets were
   attached (proofs 38-41, attach_requested then target_attached) and the list now holds exactly 2
   (1f31b602 coco_pharma.coco_ods, 4079a1d5 coco_pharma.coco_sus). The name-matching guard defect is NOT
   shown; it remains a risk only if old targets are ever present with archived elements.
4. Report: a SurveyReport exists on the new database (ReportSubject 1) with 56 ResourceMeasureAnnotations,
   not the predicted 76. Not explained yet; the new database's own survey (below) may account for the count.
5. Ownership: owner_result proof 37 on def55997 (the row exists; the Egeria-side ownership was not read back).
6. Survey: new engine action `0d625a7c` COMPLETED in 53 s (requested 1791305953991, completed 1791306006994),
   "postgres-database-survey-service has completed the analysis of asset def55997". Was it limited to the
   three schemas? Not checked.

Unexpected: the new schemas have NO tables or schema type at 17:35Z. Each has 3 related elements only
(CatalogTarget, ActionTarget, DataFlow). The cataloguer's last refresh was 17:04:24Z, after the attach, so
the tables were NOT built by that refresh. Cause unknown (candidates: needs another refresh; the cataloguer
looks up the schema by its own QN form `<DBQN>::<schema>` and RE's template form does not match).
Nothing was detached, archived, restored or deleted by anyone.
