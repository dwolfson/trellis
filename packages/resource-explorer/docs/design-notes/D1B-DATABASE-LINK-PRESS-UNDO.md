# D1-b: the database-level press, and how to undo it (2026-10-31)

Design: `DESIGN-ADOPT-BY-ENDPOINT-D1-2026-10-30.md` §10 and §12. The owner, 2026-10-31 (coordinator relay): "yes,
database level is what I meant - go".

## What the press does

`POST /api/catalogue-scope/{slug}/reanchor` (the button "Add the pack's N schemas to this database" on the plan's
database row in Contents; signed in, with the same publish check the commit uses) adds ONE `DataSetContent`
relationship between RE's database element and each schema another family holds at the same endpoint that is not yet
its member. For coco_pharma: c990f349 and the content pack's 22 schemas, 26 members after.

- The relationship type and which end the schema takes are read off the links RE's database already has to its own
  schemas (live 2026-10-31: `DataSetContent`, the schema at end 1, the database at end 2). The call is pyegeria's
  `AssetMaker.link_data_set_content(<schema GUID>, <database GUID>)`.
- The endpoint and the database's links are read again immediately before writing; a schema already linked is
  skipped, so a second press or a retry adds nothing. One press per database runs at a time.
- pyegeria's wrapper returns no relationship GUID, so the press reads the database's links back after writing and
  records each new relationship's GUID from that read. A link that was sent but is not on the read-back is said as
  "sent but not seen on the read-back", never as added.
- One proof row, `reanchor_database_link` (node `database`), lists every relationship added: schema GUID, schema
  name, relationship GUID; the schemas Egeria refused, with its words; and the undo below. The log carries one
  `reanchor_press ... added relationship=<guid> ... undo: ...` line per link.

Nothing of the pack's is changed: its elements keep every property; the press only adds relationships.

## How to undo

Every relationship the press added is listed, by its own GUID, in the press's proof row (`detail_json.added[*].
relationship_guid`) and in the log. Remove each one ALONE by that GUID:

```python
from pyegeria import AssetMaker
am = AssetMaker(view_server, platform_url, user_id, user_pwd)   # signed in as a steward of the database
am.create_egeria_bearer_token()
for guid in relationship_guids:          # from the proof row's `added` list, never searched for
    am.detach_data_set_content_relationship(guid)
```

`detach_data_set_content_relationship` addresses one relationship by its GUID (DataSetContent is multi-link, so the
two-element `detach_data_set_content(<data set>, <content>)` form could remove a link the cataloguer made). Never
detach a relationship that is not in the proof row: RE's own 4 schema links were made by Egeria's cataloguer.

After an undo, press "Read Egeria again" on Contents: the plan's database row shows the members Egeria holds again.
