# DESIGN — D1: adopt an existing database element by endpoint, and read Egeria's duplicate links (2026-10-30)

Owner's rulings (coordinator relay, verbatim). On the Coco/RE families: "So these are two distinct database instances
and most likely have different content but the same name … which is why we use qualified names that should providing
uniqueness. Perhaps that isn't the situation here but it sounds like it.." — checked read-only: both families' Endpoints
are jdbc:postgresql://host.docker.internal:5442/coco_pharma, so it is one instance. On the rule: "yes - I agree with
that rule; that said we may still find instances where we have two different qualified names that point to the same
resource - the duplication finder in egeria will most likely find it and will allow them to be linked".

## In one page

When RE publishes a database, it should first ask Egeria whether a database element already exists for the same
endpoint (host, port, database name), and if so use that element and its schema family instead of making a second one.
Two databases with different endpoints stay apart even when their names match. When two elements for one endpoint
already exist, Egeria's duplicate finder links them (PeerDuplicateLink, or a ConsolidatedDuplicate with
ConsolidatedDuplicateLinks), and RE reads those links: anything linked as a duplicate of RE's element counts as RE's for
read-back, the "In Egeria" column and rule publishing, never as absent. For today's coco_pharma pair the choice is the
owner's and Mandy's: leave both, link them by hand, or let the duplicate finder run. No new RE tables are needed.

## 1. Facts this rests on (read 2026-10-30)

- RE's family: `PostgreSQL Relational Database::host.docker.internal:5442::coco_pharma` (RelationalDatabase c990f349),
  Endpoint networkAddress `jdbc:postgresql://host.docker.internal:5442/coco_pharma`, 4 DeployedDatabaseSchema.
- Content-pack family: 22 DeployedDatabaseSchema `PostgreSQL Relational Database Schema::Coco PostgreSQL Server 1::
  coco_pharma.<schema>`, each with an Endpoint `…5442/coco_pharma?currentSchema=<schema>` and a VirtualConnection
  `{databaseName=coco_pharma, databaseSchema=<schema>}`; no RelationalDatabase, SoftwareServer, Connection or Endpoint
  element named "Coco PostgreSQL Server 1" (it is a request parameter of the pack's CreateAsCatalogTarget actions).
- Egeria's duplicate model (OpenMetadataType.java): classification `KnownDuplicate`; relationship `PeerDuplicateLink`
  (two elements that describe one thing, with statusIdentifier/confidence/steward); classification
  `ConsolidatedDuplicate` on a surviving element with `ConsolidatedDuplicateLink` to each contributor. The duplicate
  finder (Egeria's survey/ governance action) proposes PeerDuplicateLinks; a steward confirms.

## 2. (a) Adoption at commit time

Rule: **a database's identity in Egeria is its endpoint — host, port, database name — never its qualified-name prefix
or display name.**

Where: `catalogue_commit.publish_database` (the typed RelationalDatabase read/create) and `catalogue_gateway`.

1. Before creating RE's RelationalDatabase, read candidates by endpoint: `find Endpoint whose networkAddress is
   jdbc:postgresql://<host>:<port>/<db>` (and the `?currentSchema=` variants), then walk ConnectionEndpoint →
   Connection → ConnectionToAsset → the asset, collecting RelationalDatabase and DeployedDatabaseSchema elements.
   Host equivalence is a small, declared table (host.docker.internal ≡ localhost ≡ 127.0.0.1 when RE and Egeria share a
   machine; configured, never guessed), so "laz_local" and "host.docker.internal" compare correctly.
2. Exactly one RelationalDatabase found → **adopt**: record its GUID as the database's `egeria_asset_guid`, and publish
   schemas as members of its family (its QN prefix), attaching to the existing DeployedDatabaseSchema where the schema
   name matches rather than creating a sibling. The proof row says "adopted <guid> · by endpoint".
3. Schemas only, no RelationalDatabase (today's Coco pack shape) → adopt the schema elements by name (aus_inventory →
   b798274a) and create RE's RelationalDatabase if none exists, linking the adopted schemas to it; say so on screen
   ("schema already in Egeria under 'Coco PostgreSQL Server 1' · adopted").
4. More than one RelationalDatabase for one endpoint → do not pick: list them on the Contents page with their QNs and
   the words "two Egeria elements describe this endpoint · Egeria's duplicate finder can link them"; publish to the one
   RE already holds (or the newest if none), and never create a third.
5. Different endpoints, same database name → **separate** by design; the screen may note "another database named
   coco_pharma exists at <endpoint>" with a link to the comparison questions (DESIGN-RESOURCE-COMPARISON-QUESTIONS).

Publish-rules (`not_in_egeria`) and read-back use the same resolver, so a rule's target is "the schema element for this
endpoint and schema name", whichever family holds it.

## 3. (b) Reading Egeria's duplicate links

Wherever RE answers "is this in Egeria?" (read-back after a commit, the IN EGERIA column on Contents, publish-rules'
target check, `reinclude_check`), the set of elements that count as RE's own is:

- RE's own element (by GUID or QN), plus
- every element reachable from it over `PeerDuplicateLink` (either end), plus
- for an element classified `ConsolidatedDuplicate`, every contributor over `ConsolidatedDuplicateLink`, and for a
  contributor, its consolidated survivor.

One relationship read per element (`get_related_metadata_elements(guid, "PeerDuplicateLink")`, then
"ConsolidatedDuplicateLink"), cached per commit-preview. Words: "in Egeria · also described by <other QN> (linked as a
duplicate)". A duplicate link in status proposed (statusIdentifier below confirmed) still counts for reading, with the
word "proposed duplicate"; RE never writes to the other element of a proposed pair. RE never creates PeerDuplicateLinks
itself in this slice; it may offer the pair to Egeria's duplicate finder (a press, a governance action) later.

## 4. (c) Today's coco_pharma second family — for the owner and Mandy

Options, in order of least change:
1. **Leave both** and let adoption (§2) stop any third copy; RE's Contents shows the 22 Coco schemas as "in Egeria
   under 'Coco PostgreSQL Server 1'" once F41/D1 read-back lands.
2. **Run Egeria's duplicate finder** over the two families (Mandy's side; a governance action on the quickstart) and
   confirm the PeerDuplicateLinks as steward; RE then reads them by §3 with no RE change beyond §3.
3. **Consolidate**: pick one survivor (RE's RelationalDatabase, since the pack has none) and mark the pack's schema
   elements ConsolidatedDuplicate contributors; the heaviest change, and it touches the content pack's elements.
Recommendation: 1 now, 2 when the duplicate finder is available on the quickstart; 3 only if the pack is re-loaded.

## 5. Slices, gate, DDL

- **D1-a resolver + read-back** (RE): endpoint resolver with the host-equivalence table; duplicate-link reading in
  read-back, IN EGERIA, publish-rules, reinclude_check. Gate: on coco_pharma, read-back shows the 4 RE schemas and the
  22 Coco schemas as in Egeria (with "under 'Coco PostgreSQL Server 1'"), publish-rules stops saying aus_inventory is
  not in Egeria; on a throwaway with a unique endpoint nothing changes. Unit test with a fake gateway that returns a
  PeerDuplicateLink pair.
- **D1-b adoption at commit** (RE, Egeria write): the five cases of §2 as tests over a fake gateway; the live proof on a
  throwaway database first published under one host alias, then re-registered under another alias of the same endpoint:
  the second publish adopts (one RelationalDatabase, proof row "adopted · by endpoint"). Needs the owner's word
  (shared Egeria write) and a peer round.
- **D1-c** (Egeria, Mandy): run or schedule the duplicate finder; confirm links; RE reads them (D1-a). Not RE work.
- **DDL: none.** `egeria_asset_guid` and the proof rows exist; the host-equivalence table is configuration
  (`EGERIA_HOST_ALIASES`, declared and read — a configured-but-never-read check in the gate). If a builder finds the
  adoption needs a per-schema adopted-GUID column that today's proof rows cannot carry, stop and flag it.

## 6. Open for the owner and Mandy

1. §4: leave / link / consolidate for today's pair.
2. The host-equivalence list for this machine (host.docker.internal, localhost, 127.0.0.1, laz?).
3. Whether a *proposed* (unconfirmed) PeerDuplicateLink should count for the IN EGERIA column, or only confirmed ones.
