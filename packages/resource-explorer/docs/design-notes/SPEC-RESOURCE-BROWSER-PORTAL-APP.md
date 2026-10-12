# SPEC — Resource browser: a shop-for-data app on Egeria alone (2026-10-12)

For the Claude session working on egeria-workspaces (the Egeria Portal),
from the design session, at the project owner's request. Companion to
`DESIGN-AMUNDSEN-MIGRATION-ASSESSMENT.md`, which carries the reasoning;
this note carries what to build. The owner decides and walks the gates.

## 1. What it is, in one paragraph

A single-page app, beside the Portal's existing apps and in the same
no-build React stack served by `PyegeriaWebHandler`, for anyone looking
for data: an analyst, a casual browser, a person who does not curate.
It reads Egeria only. It never reads Resource Explorer's registry or any
other store, so it runs wherever Egeria runs. It writes back only what
Egeria already models: descriptions, tags, ratings, likes, comments and
collection membership. It replaces what an Amundsen user opens daily:
home, search ranked by use, one page per resource, browse.

## 2. Hard constraints

- **Egeria only.** Every read and write goes through pyegeria's clients
  (or the Portal's existing FastAPI endpoints that wrap them). No new
  database, no index of its own, no file on disk beyond static assets.
  If something a page needs is not in Egeria, the page says so
  ("usage not recorded for this resource") and the gap is logged in the
  spec's open list; it is never fetched from elsewhere.
- **Egeria's own types and feedback.** `Rating`, `Like`, `Comment`,
  `InformalTag`, `Collection` with members, `Ownership`, the governance
  classifications, `SurveyReport` annotations, lineage relationships.
  No parallel notion of a tag or a bookmark.
- **Honesty.** A number is labelled with what it counts and when it was
  measured. "Never measured" and "measured, found nothing" are shown
  differently, always (the `find-absence-as-answer` rule). A count that
  came from a sample says so. Nothing is shown as zero because a query
  returned nothing.
- **No steward controls.** No publish, no survey, no curation verdicts,
  no archive or delete. A person who needs those is sent to RE or the
  Portal's steward apps by a link that names them.
- **Sign-in is the Portal's.** The signed-in user is the author of every
  write; nothing writes as a service account.
- **The three flavours are a facet and a badge, never three apps.**

## 3. The three flavours, and how the app tells them apart

| Flavour | Meaning | How the app recognises it | Badge and next action |
|---|---|---|---|
| (a) Known | An asset Egeria knows about, curated or not | Any asset without (b) or (c) below | "Known" · next: ask about it (the owner, comments, a Data Sharing Request to the party that holds it) |
| (b) Data product | Curated and prepared to be subscribed to | Membership of, or being, a digital product: Egeria's `DigitalProduct` (model 0710) or its product collection, with a subscription available | "Product" · next: subscribe (the product's subscription path) |
| (c) Hub asset | Added to a data sharing hub as authoritative, actively maintained data available for sharing | `CollectionMembership` in a collection of type `DataSharingHub` (model 0705, a subtype of Collection; [concept page](https://egeria-project.org/concepts/data-sharing-hub)) | "Hub" · next: use now, under the hub's access conditions, or raise a Data Sharing Request (Egeria's to-do type) where access is not yet granted |

Precedence when more than one applies: (c), then (b), then (a); the badge
shows the highest and the page lists the others. The recognition rules
are one function with one committed test per flavour and one for the
precedence, so a change in Egeria's model changes one place.

## 4. Pages

### Home
- Popular: the top resources by use, from the usage measure Egeria holds
  once the nanny usage work is reinstated; until then the tile says
  "popularity not available yet" and shows recently changed instead.
  Never a fake ranking.
- Bookmarked: the signed-in user's `Like`s, newest first.
- Recently changed: assets by update time, with what changed if Egeria's
  history gives it in one call, else the time only.
- My lists: the collections the user owns or is a member of (see §5).

### Search
- One box. Full text over names, qualified names, descriptions, tags,
  column names, owners. Results ranked by use when the usage measure
  exists, by text relevance otherwise, and the page says which.
- Facets: flavour; resource type (database, schema, table, file, report,
  topic, process); tag; badge (governance classification); owner;
  source system; collection; scope and granularity (a table versus its
  schema versus its database: the user picks the level they want results
  at, and children roll up to it).
- Each result: name, type icon, flavour badge, one-line description with
  its author and date, owner, tags, the usage figure with its as-of date,
  the rating summary, "in N of your lists".

### Resource
One component, reused by the answering app later, so it is built as a
standalone element with the resource GUID as its only input.
- Header: name, type, flavour badge, what you can do next (one primary
  action by flavour), owner, rating summary, like, add to list.
- Description: editable in place by anyone signed in. Each save is an
  Egeria update under the signed-in user; the page shows "described by
  <user> · <date>" from Egeria's element header. No second store of
  authorship.
- Columns (for tables and schemas): name, type, description editable in
  place, data class if present, key marks, statistics from the latest
  survey annotation with the survey date, "no survey yet" when none.
- Statistics: row count and size with their as-of date and source
  (database catalog estimate versus measured), distinct values and
  profiles where annotations exist.
- Lineage: upstream and downstream from Egeria's lineage relationships,
  one level by default, expandable; "no lineage recorded" when none.
- Where it is used: processes and reports that read it, from the same
  relationships; usage by user where the usage measure records it.
- People: owner, stewards, people who rated or commented.
- Feedback: comments (threaded as Egeria stores them), ratings, likes.
- Tags: add and remove `InformalTag`s under the signed-in user.
- Preview: reuse the Portal's existing data preview component unchanged.

### Browse
- By tag, by badge, by owner, by source system, by collection, by
  flavour. Each a list page with the same result row as Search.

## 5. Work lists

- A work list is an Egeria `Collection` with members. Personal lists are
  owned by the user; team lists are owned by a team (ActorProfile) the
  user belongs to. Create, rename, add, remove, share with a team.
- Because RE's own work lists are Egeria collections too, a list made
  here is visible to a steward in RE and a steward's shortlist is
  visible here. The app does nothing special for that; it is the same
  collection.
- "Hand to a steward": adds a comment on the collection naming the
  request. No new type.

## 6. Backend

- FastAPI endpoints in pyegeria's web handler, one per page need, each a
  thin wrapper over existing pyegeria clients. Follow the pattern the
  `pyegeria-spa-add-tab` skill describes for the other Portal apps.
- Search uses Egeria's find with property and classification conditions;
  no Elasticsearch, no local index.
- Caching only in memory per process with a visible age on the page.
- Every endpoint returns, beside its data, the as-of time and the source
  (which Egeria call), so the page can label what it shows.

## 7. What is explicitly not in scope

- Anything that needs RE's registry (RE's analyses, investigations,
  proof rows). The answering app may use those later; this app does not.
- Ingestion of any kind. The browser shows what Egeria has.
- Popularity when Egeria has no usage measure: show the honest absence.
- Standing needs and notifications: the answering app's job.
- Product and hub management: their own tools.

## 8. Gate, by use

The owner walks these on a Portal build against the dev platform:

1. From Home, find coco_pharma's most-used table without typing, when
   the usage measure exists; otherwise see the honest absence and the
   recently-changed list.
2. Search "sales", filter to tables and the (a) flavour, open a result,
   read its columns and statistics with dates, improve one column's
   description, see it attributed to the signed-in user with the time.
3. Rate it, like it, add it to a new personal list, share the list with
   a team, and see the list in RE's work lists under the same name.
4. Open a data product and a hub asset (once one exists), see the right
   badge and the right next action.
5. Open a resource with no survey and no lineage, and see "no survey
   yet" and "no lineage recorded", never empty tables.

## 9. Open items before build

- [x] The type that marks a hub asset (c): `DataSharingHub` (0705), a
      Collection subtype; membership by `CollectionMembership` (owner,
      2026-10-12). A hub also carries a data dictionary of its members'
      fields, which the Resource page can show when present.
- [ ] Where the reinstated usage measure lives and its shape, so Home and
      Search can read it; until then, the fallbacks above.
- [ ] Whether the Portal's existing resource view can become the shared
      resource component, or the new one replaces it.
- [ ] Portal app or trellis app: the owner's call; this spec assumes the
      Portal.
