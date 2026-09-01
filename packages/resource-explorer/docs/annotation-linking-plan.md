# Annotation-to-annotation linking — plan

Builds on `docs/annotation-linking-audit.md` (WHERE). This is HOW, phased
smallest-useful-first. No production code changed by this document.

Every claim below was re-verified against source during this pass, not
carried over from the audit unchecked — citations follow each one. Two of
the audit's "what I could not determine" items turned out to have concrete
answers; one turned out harder than the audit's framing suggested. Both are
called out where they matter, and again in "Where this is harder than the
audit implied."

## Discovery findings

### 1. Does `create_annotation` return the GUID?

**Yes, already.** `DataDiscovery.create_annotation` →
`_async_create_annotation` → `ServerClient._async_create_element_body_request`
(`pyegeria/core/_server_client.py:7198-7205`):

```python
response = await self._async_make_request("POST", url, json_body, is_json=True)
return response.json().get("guid")
```

The docstring on `_async_create_annotation` (`pyegeria/omvs/data_discovery.py:105-141`)
confirms the contract: returns "the unique identifier of the newly created
annotation." So the audit's "what I could not determine" item #1 has an
answer: nothing needs to be added to pyegeria to get a GUID back. The gap is
entirely on RE's side — it calls the method and drops the return value.

Two call sites, two different states today:

- `annotation_props.py:261` (`publish_annotations`, the direct/no-registry
  path): `discovery.create_annotation(body=body)` — return value discarded,
  confirmed unchanged.
- `egeria_outbox.py:128` (`_create_annotation`, the outbox path used whenever
  a registry is present — i.e. the normal path per `egeria_publisher.py:566`):
  `_guid_of(clients.require("discovery").create_annotation(body=payload))`
  — **this one already captures the GUID** and returns it up to
  `drain_outbox`, which passes it to `registry.mark_outbox_done(row["id"], guid)`
  (`egeria_outbox.py:229`). The GUID is captured and persisted — but only into
  the outbox row, not into `project_analysis_findings`, and outbox rows are
  not a general-purpose "GUID by finding" index (see Phase 1 below).

**Failure distinguishability.** `_async_make_request`
(`pyegeria/core/_base_server_client.py:471-519`) raises `PyegeriaAPIException` /
`PyegeriaUnauthorizedException` / `PyegeriaConnectionException` /
`PyegeriaInvalidParameterException` for anything Egeria or the transport
reports as an error — including Egeria errors wrapped in an HTTP 200 body.
So a real failure surfaces as an exception, not a silent empty return.
What is *not* distinguishable: a 200 response whose JSON body has no `"guid"`
key returns `None` with no exception (`.get("guid")` on a dict that lacks the
key). No code path in pyegeria's create-element helper was found that
produces this today, but nothing prevents a future server response shape
from doing so silently. Treat "created but empty GUID" as a state the
consuming code must check for explicitly (`if not guid: ...`), not assume
impossible.

### 2. What creates a relationship between two existing elements?

**A generic primitive exists, but not on the client RE already uses.**

`DataDiscovery` (the OMVS client `egeria_publisher.py` already connects,
`egeria_publisher.py:241,248-250`) has **no create/attach endpoint for
`AnnotationExtension` or `AnnotationReview`** at all — server or client side.
Verified two ways:

- pyegeria (`omvs/data_discovery.py`): grepped every `def ` — attach/detach
  wrappers exist only for `SurveyReportAnnotationRelationship`,
  `AnnotationDescribedElementRelationship`, `AnnotationPredecessorRelationship`,
  `ResourceProfileDataRelationship`, `AnnotationMatchRelationship`, and
  `RequestForActionTarget` (lines 359, 459, 532, 632, 732, 1790).
  `get_annotation_extensions` (line 1278) and the underlying
  `_async_get_annotation_extensions` (line 1242) are **read-only** — they GET
  the annotations that already extend a given one; there is no matching
  create/attach.
- The Java REST controller behind that client,
  `open-metadata-implementation/view-services/data-discovery/data-discovery-spring/.../DataDiscoveryResource.java`,
  confirms the same gap at the server: the six `@PostMapping(.../attach)`
  endpoints (lines 146, 215, 277, 339, 401, 463) cover exactly the six
  relationship types pyegeria wraps above. The `@PostMapping` at line 699
  for `/annotations/{annotationGUID}/annotation-extensions` is
  `getAnnotationExtensions` — a POST-with-body *query*, not a create — and
  there is no `AnnotationReview` handling anywhere in this file. **This is a
  genuine Data Discovery view service gap, not a pyegeria omission** — even
  a hand-rolled REST call against this view service has no endpoint to hit.

**The fallback that does exist:** a second, generic view service —
`metadata-expert` — exposes `POST /related-elements`
(`MetadataExpertResource.java:376-384`,
`createRelatedElementsInStore(serverName, urlMarker, NewRelatedElementsRequestBody)`),
which creates a relationship of **any** named type between two GUIDs
(`typeName`, `metadataElement1GUID`, `metadataElement2GUID`, `properties`).
pyegeria wraps it: `MetadataExpert.create_related_elements(body)` →
`_async_create_related_elements` (`omvs/metadata_expert.py:622-670`), whose
own docstring says this is the same generic mechanism Dr.Egeria's
`AsyncBaseCommandProcessor._sync_parent_relationship()` already uses in
production for exactly this "attach two existing elements by type name"
shape (`md_processing/v2/processors.py`, cited in the docstring, not
independently re-verified here). It returns the new relationship's own GUID.

So the audit's characterization ("no primitive exists anywhere in this
codebase or, so far as I could find, pyegeria") undersells what pyegeria
has and oversells how directly usable it is: the primitive **exists and is
exercised in production by another part of this stack**, but through a
*different OMVS client* (`MetadataExpert`, not `DataDiscovery`) that RE has
never connected. Adding it is the same four-line pattern
`_connect()` already uses for `AssetMaker`/`AutomatedCuration`/
`ExternalReferences` (`egeria_publisher.py:240-263`): construct with
`(view_server, platform_url, user_id, user_password)`, call
`create_egeria_bearer_token`.

`get_metadata_guid_by_unique_name(name, property_name="qualifiedName")`
also lives on `MetadataExpert` (`omvs/metadata_expert.py:865-957`) — same
client, no extra connection needed once it exists. Relevant to Q3 below.

### 3. The cross-run case

**Reconstructing a past annotation's GUID from a local finding row is
possible today only under a fragile assumption, not reliably.** This is
where discovery came out harder than the audit's framing implied — the
audit flagged this as unresolved; having chased it, "unresolved" undersells
it: the mechanism that *looks* like an answer does not actually hold up.

What exists: annotations get a deterministic qualifiedName —
`f"Annotation::{result.resource_slug}::{result.surveyed_at.isoformat()}::{i}"`
(`egeria_publisher.py:566`, consumed by `publish_annotations`,
`annotation_props.py:205-266`) — and `MetadataExpert.get_metadata_guid_by_unique_name`
can resolve any qualifiedName to a GUID (or the sentinel string
`"No element found"`, `omvs/metadata_expert.py:957` — not an exception, not
`None`; callers must check for that literal string). In principle: know the
resource slug, the run's `surveyed_at`, and the index `i`, and you can
recompute the qualifiedName without ever having stored a GUID.

**Why that does not actually work for the cross-run case:** `i` is a bare
`enumerate()` position in whatever order a sub-surveyor's `run()` happened
to `.append()` its annotations that run (verified in `data_profiler.py`:
the summary `ResourceMeasureAnnotation` is appended at line 307, ahead of
per-file `SchemaAnalysisAnnotation`s appended later in `_tier2_stored`/
`_tier2_local`; nothing in `Annotation` — `survey_report.py:26-41` — records
this position, it is purely accidental append order). A local finding row
in `project_analysis_findings` carries `check_name`, not an index, and
there is no stated mapping from `check_name` to `i`. Reconstructing
`i` from a finding row would mean re-deriving the exact append order a
past version of the sub-surveyor's code used, for a run that may predate
today's code — silently wrong the moment the surveyor's internal order
changes, with no error, just a link to the wrong annotation. This fails the
same test flagged in `feedback_checks_weaker_than_they_look.md`: a lookup
that resolves to *some* GUID looks like it worked.

**What would actually work:** persist the real qualifiedName (or the GUID
directly) at the moment of creation, not recompute it later. That requires
the schema change in Phase 1 regardless of same-run vs. cross-run — the
cross-run case additionally requires that column to be *back-filled at
publish time*, which is a second write RE does not do today (`upsert_finding`,
`registry.py:3098-3145`, is insert-only; no update-by-id exists yet).

**Coverage gap, stated plainly:** `security_summary.py`'s 8 `INPUT_KINDS`
are read via `registry.query_findings(slug, kind)` at "latest per kind"
(confirmed `registry.py:3149-3167`, `MAX(surveyed_at)` independently per
kind) — i.e., genuinely different runs, different `SurveyReport`s, for
different kinds. Even after Phase 1 adds a GUID column, this reducer's
cross-run resolution works **only for finding rows written after Phase 1's
back-fill lands** — every finding row already in the ~68,000-row table
before that point has no GUID and no reconstructable one. This is a hole in
history, not just a hole in code, and nothing in this plan closes it
retroactively (see Phase 3).

### 4. Idempotency for relationships

**No protection exists today, and the shape it needs is not the shape RE
already has for annotations.** Verified against `annotation_props.py`'s
existing guard (`publish_annotations`, lines 205-266): it dedupes by
`find_element_guid(qualified_name)` before create — but that mechanism only
works because an `Annotation` *element* has a qualifiedName to search for.
A **relationship** does not. `egeria_outbox.py`'s own comment on this exact
distinction (`_create_collection_membership`, lines 132-149):

> "Idempotency here is NOT lookup-then-create: a CollectionMembership has no
> qualifiedName of its own to search for... `CollectionMembership` was
> measured live (2026-08-25) as uni-link, so `add_to_collection` returns
> None and adding the same element twice leaves one member."

That is the memory file `reference_egeria_dedup_and_link_patterns.md`'s
point exactly, and it is the load-bearing fact for this phase:
**idempotency for a relationship type depends on whether Egeria's own
repository treats it as UNI_LINK (one instance per ordered pair — a second
create upserts or is a no-op) or MULTI_LINK (any number of instances
allowed — a second create duplicates)**, and that is a property of the
relationship type definition, not something inferable from the Java model
file this task cites. It has to be *measured live*, the same way
`CollectionMembership`/`ResourceList` were on 2026-08-25 — create the same
relationship twice against a real server and read back the count. This plan
does not assume an answer for `AnnotationExtension` or `AnnotationReview`
in either direction, and the task brief's framing ("Egeria's link commands
elsewhere in this stack do NOT dedupe... assume relationships duplicate
unless you prove otherwise") is the right default until that measurement
exists. `pyegeria`'s own `_async_new_relationship_request` docstring
(`core/_server_client.py:7252-7266`) independently corroborates the risk in
general terms — it explains *why* a relationship GUID matters most for
MULTI_LINK types, because "there can be more than one relationship of the
same type between the same pair of elements."

**What a workable guard looks like, once measured:**
- If UNI_LINK: create-blind is safe (matches `CollectionMembership`'s
  precedent exactly) — no guard code needed beyond what Phase 2 already
  writes.
- If MULTI_LINK: a pre-check via `MetadataExpert.get_all_related_elements`
  (`omvs/metadata_expert.py:2508-2585`, filtered client-side by relationship
  type name and the target GUID) is required before every create, and its
  own docstring flags the return shape trap explicitly: `{"elementList": [...]}`
  — a dict, not a list — with per-entry fields (`type.typeName`,
  `relationshipGUID`, `element.elementGUID`) that do not match the shape of
  any domain-specific "get related X" call already in this codebase. A guard
  written against the wrong shape here fails exactly the way
  `feedback_checks_weaker_than_they_look.md` describes: it "passes" by
  raising `KeyError` on malformed input in test but silently returning
  "nothing found" (empty list from a `.get()` miss) against a real payload,
  which looks identical to "no existing link" and creates a duplicate anyway.
  Any implementation of this guard needs a known-negative test that asserts
  it detects an existing link given a real (or realistically shaped)
  `elementList` response, not just that it returns something.
- `detach_related_elements_in_store` (`omvs/metadata_expert.py:836-885`)
  exists as a repair tool either way — deletes *all* relationships of a
  given type between a specific pair, useful for cleaning up duplicates a
  MULTI_LINK type produced before the guard above existed. Not proposed for
  use in the normal publish path.

### 5. Failure isolation

**Today: nothing tracks link failures, because nothing creates links.**
Going forward, the existing outbox model (`egeria_outbox.py`) is the right
place, and it already solves the adjacent problem the audit's framing
worries about ("a summary created, evidence links partially failing,
silently"): `apply_element` (lines 77-119) is lookup-then-create per row,
`drain_outbox` (lines 189-249) treats each row independently — one row's
failure (`registry.mark_outbox_failed`, backoff/dead-letter per row) does
not block or roll back any other row, and `record_drain_outcome`
(referenced at line 245, defined further in the same file) is the existing
surface for "N rows dead-lettered, needs a human"
(`registry.list_dead_outbox_elements()`, cited in `drain_outbox`'s own log
line, line 246-247).

The gap is that `_CREATORS` (lines 176-180) has no `element_kind` for a
relationship yet — `"annotation"`, `"collection_membership"`,
`"resource_list"` only — and no relationship-shaped row has a qualifiedName
to key idempotency off (point 4 above), so `apply_element`'s
lookup-then-create step (which is qualifiedName-keyed at its core,
`row["qualified_name"]`, line 90) cannot be reused unmodified. Phase 2 below
is scoped around exactly this: a new `element_kind` whose lookup step is
"does this specific relationship already exist between these two GUIDs"
instead of "does an element with this qualifiedName exist."

**What a reader sees on partial failure, once this ships:** the summary
annotation itself was already created and durable (unaffected by any link
failure, since links are enqueued and drained *after* both ends exist) —
satisfies the "must remain independently readable" constraint on its own,
independent of this phase entirely. A reader who *does* follow links sees
however many of the N evidence links succeeded; the missing ones are
visible as dead-lettered/pending rows to an operator via
`list_dead_outbox_elements()`, not visible at all to an external Egeria
consumer just walking the graph — a real limit, not new to this plan
(the same is already true for a failed annotation create today).

## Constraint: summaries stay independently readable

Every summary in Tier 1/2 already carries its verdict fields directly in
`json_properties`, and this plan does not touch that. Confirmed again
per-file:

- `security_summary.py`: `known`, `missing`, `oldest_input_age_days` are
  fields on the summarise() output, unconditionally included regardless of
  whether any link is later added (audit's characterization confirmed by
  re-reading — not re-quoted here to avoid duplicating the audit).
- `cve_scan.py`: `no_signal` / `known_positive` in `coverage`, same
  guarantee.

Nothing in Phases 1-3 below removes or gates these fields behind a
successful link. Any future PR that proposes shrinking a summary's own
`json_properties` "because the links cover it now" is out of scope for this
plan and should be rejected on sight per the task's own constraint.

## Phasing

### Phase 0 — Measurement spike (no schema change, no new code path)

Before any of Phases 1-2 are trustworthy, two live facts must be confirmed
against a real server, not assumed:

1. Is `AnnotationExtension` UNI_LINK or MULTI_LINK? (point 4). Create the
   same `AnnotationExtension` between two real annotations twice via
   `MetadataExpert.create_related_elements`, then read back with
   `get_annotation_extensions` and count. Same for `AnnotationReview` if
   Phase 3 (out of scope here) is ever picked up.
2. Confirm `MetadataExpert.create_related_elements` actually succeeds
   against this stack's server version for `typeName: "AnnotationExtension"`
   specifically — the generic endpoint existing in Java does not guarantee
   every relationship type is accepted by it (some relationship types carry
   server-side validation, e.g. end-type restrictions, that only a live call
   surfaces).

**Rollback:** none needed — nothing is written except two throwaway test
annotations and one throwaway relationship, cleaned up manually after.
**Verification:** a short script, run once, output captured in this repo's
`docs/` as a dated note (not proposed as a file here — a follow-up, not part
of this plan's deliverable).

This phase is a hard prerequisite for Phase 2's guard design (point 4) —
Phase 1 does not depend on its outcome and can proceed in parallel.

#### Measured 2026-09-01 — RESULT: `AnnotationExtension` is UNI_LINK

Both open questions above are answered. Peer sessions checked first (via
`ListAgents`/session listing — none live/running at measurement time) per
`coordinate-shared-writes`; the write below ran once, its own output captured
to a file rather than the script being re-run to "check" it.

**What was created**, against the live `qs-view-server` platform
(`https://localhost:9443`):
- Two throwaway `Annotation` elements, qualifiedName-tagged
  `PHASE0-MEASURE-2026-09-01::annotation-A` /`::annotation-B` — GUIDs
  `f1475b36-dfcc-461b-a247-f05525c3c75a` (A) and
  `063593ea-21e6-42e1-8a2e-c2a18ace55d3` (B).
- One `AnnotationExtension` relationship, `metadataElement1GUID=A`,
  `metadataElement2GUID=B`, via `MetadataExpert.create_related_elements` —
  returned relationship GUID `d97faaf5-9d14-46f2-8f59-e0a7ecf9fc23`.
- The **identical** call, same body, same two GUIDs, made a second time
  immediately after.

**Result: the second create returned the exact same relationship GUID as the
first** (`d97faaf5-9d14-46f2-8f59-e0a7ecf9fc23`, byte-identical) — it did not
raise, and did not mint a new GUID. Read back two ways, independently of the
write itself:
- `DataDiscovery.get_annotation_extensions(guid_a)` — the real, existing
  read-only call the audit already confirmed exists — returned exactly **one**
  extension (annotation B), not two.
- `MetadataExpert.get_all_related_elements(guid_a)` — a second, independent
  read via a different client/endpoint — also returned exactly **one**
  relationship in its `elementList`, matching `relationshipGUID`
  `d97faaf5-...`.

Both reads agreeing, from two different endpoints, on "one relationship, same
GUID as both create calls" is conclusive: **`AnnotationExtension` is
UNI_LINK** (one instance per ordered pair; a second create upserts/returns
the existing instance rather than duplicating). This matches the precedent
already measured for `CollectionMembership`/`ResourceList` on 2026-08-25 — the
task brief's "assume relationships duplicate unless proven otherwise" default
is now overridden by an actual measurement for this specific type, the same
way it was for those two.

**Also answered — point 2 (does the generic endpoint accept this type at
all):** yes, without qualification. `create_related_elements` with
`typeName: "AnnotationExtension"` between two `Annotation` elements succeeded
on the first call with no end-type rejection; nothing in the "Honest-limits"
bullet about server-side end-type validation applies to this type. Phase 2 is
NOT blocked on this point.

**Also answered — direction (Honest-limits section, "direction of
`AnnotationExtension`'s two ends"):** `metadataElement1GUID` is end 1,
`metadataElement2GUID` is end 2, in the straightforward order — no reversal.
Confirmed two ways: `get_annotation_extensions(A)`'s response nests B under
A with `relatedElementAtEnd1: true` (i.e., A — the call's own subject — is at
end 1), and `get_all_related_elements(A)`'s response returns B with
`elementAtEnd1: false` (B is end 2, consistent). Both API surfaces and both
generated mermaid graphs render the arrow the same way: A —AnnotationExtension→ B.
Phase 2's own open question ("evidence GUID to summary GUID, or the reverse")
is therefore just a choice of which element is passed as
`metadataElement1GUID` at call time — nothing about the type itself forces a
direction.

**What this means for Phase 2's idempotency guard, plainly:** the MULTI_LINK
branch of point 4's design (the `get_all_related_elements`-based pre-check
before every create) is **not needed** for `AnnotationExtension`. Phase 2 can
follow the UNI_LINK branch instead — the same one `CollectionMembership`/
`ResourceList` already use in `egeria_outbox.py::_create_collection_membership`/
`_create_resource_list`: create-blind, no pre-check, replay-safe by the
relationship's own semantics, because the server itself will not accumulate
duplicates. This removes a real chunk of Phase 2's design complexity (the
`{"elementList": [...]}` shape-trap guard, and its own required known-negative
test) — worth restating explicitly since it is the answer the whole plan
hinges on. (This measurement covers `AnnotationExtension` only —
`AnnotationReview`, relevant only if Phase 3 is ever picked up, was not
measured and should not be assumed to share this answer without its own
measurement, per point 1 above.)

**Cleanup:** confirmed complete. `MetadataExpert.detach_related_elements_in_store`
removed the relationship, then `DataDiscovery.delete_annotation` (cascaded)
removed both throwaway annotations. Verified independently (a third read, not
a re-run of the write): a subsequent `get_all_related_elements(A)` raised
`PyegeriaNotFoundException` — `OMRS-REPOSITORY-404-013 ... is soft-deleted in
the open metadata repository` — confirming A no longer resolves. No test
elements, and no `AnnotationExtension` relationships, remain from this
measurement.

### Phase 1 — GUID capture + schema (same-run only, no relationships yet)

**What changes:**
- `annotation_props.py:261`: capture `discovery.create_annotation(body=body)`'s
  return value in `publish_annotations` (currently discarded — the direct/
  no-registry path only; the outbox path already captures it per Q1).
- `Annotation` (`survey_report.py:26-41`): add one field,
  `evidence_of: int | None = None` — the index, within the same `run()`'s
  returned list, of the annotation this one is evidence *for*. `None` means
  "not evidence of anything in this run" (every existing annotation,
  unchanged). Chosen over a GUID-based field because the GUID does not exist
  until after publish — the sub-surveyor only ever knows relative position
  within its own list, which is exactly what `data_profiler.py`/
  `dependency.py` already produce for free via append order (Q3's finding
  about *not* trusting append order applies to reconstructing it blind
  *later*, cross-run — it is fine as an explicit, intentional signal set by
  the surveyor itself, in the same run, checked into the data it hands the
  publisher).
- `project_analysis_findings`: add `egeria_annotation_guid TEXT DEFAULT ''`
  via the existing pattern (`registry.py:965-970`'s
  `scope_locator` migration is the template — check
  `_get_table_columns`, `ALTER TABLE ... ADD COLUMN ... DEFAULT ''` if
  absent). Existing ~68,000 rows get `''`, meaning "no known GUID" —
  indistinguishable from "not yet published," which is honest: that is
  genuinely all that can be said about them (Q3).
- `registry.py`: one new method, `mark_finding_guid(finding_id: int, guid: str) -> None`
  — a plain `UPDATE project_analysis_findings SET egeria_annotation_guid = ? WHERE id = ?`.
  `upsert_finding` stays insert-only; this is a separate, narrow write used
  only after a successful publish.

**What it enables:** nothing user-visible by itself. It is the prerequisite
Q1-Q3 above establish is required before Phase 2 can create a single real
link. Also closes the direct-path GUID-discard gap regardless of whether
Phase 2 ever ships.

**Verification:** run `data_profiler.py` against a project with data files
end to end; assert the summary annotation's `evidence_of` field is unset,
every per-file annotation's `evidence_of == 0`, and (once wired) that
`egeria_annotation_guid` lands non-empty in `project_analysis_findings` for
the reducer kinds that call `upsert_finding` after a successful publish.
Known-negative: assert the column stays `''` when `create_annotation`
raises — the guard against "recorded a GUID from a create that actually
failed."

**Rollback:** the new column is additive and unread by every existing query
(`query_findings`, `query_findings_history_raw` already `SELECT` named
columns, not `SELECT *` — confirmed `registry.py:3167,3192,3385` — so they
are unaffected by the new column without a code change). Dropping the
`evidence_of` field from `Annotation` reverts to current behavior; no data
migration needed either direction since it is never null-checked in a way
that changes existing control flow (`None` is the default and is
indistinguishable from "field doesn't exist" for every reader that predates
this change).

### Phase 2 — Tier 1 same-run linking (data_profiler.py, dependency.py)

**What changes:**
- `egeria_publisher.py`: connect a `MetadataExpert` client alongside
  `DataDiscovery`/`AutomatedCuration`/`ExternalReferences` in `_connect()`
  (`egeria_publisher.py:240-263`), same four-line pattern.
- `annotation_props.py` / `publish_annotations`: after all annotations in
  one `run()`'s list are created (Phase 1 now has every one's real GUID in
  hand, in-memory, keyed by list index — no lookup needed, this is the
  same-run case specifically because both ends were just created together),
  a second pass creates one `AnnotationExtension` relationship per
  annotation whose `evidence_of` is set, from evidence GUID to summary GUID
  (or the reverse — direction is Phase 0's open question below, not decided
  here).
- `egeria_outbox.py`: new `element_kind = "annotation_link"`. Its creator
  calls `MetadataExpert.create_related_elements`. Its idempotency step is
  **not** the existing qualifiedName lookup (point 5) — it is whatever
  Phase 0 determines: skip entirely if UNI_LINK, or the
  `get_all_related_elements`-based pre-check if MULTI_LINK. The row's
  payload carries both GUIDs plus the relationship typeName, not a
  qualifiedName (relationships have none, confirmed point 4) — `apply_element`
  needs a conditional branch keyed on `element_kind` for which idempotency
  strategy applies, since `"annotation"`/`"collection_membership"`/
  `"resource_list"` already differ from each other this same way (compare
  `_create_annotation` vs. `_create_collection_membership` today).

**What it enables:** the two audit Tier-1 candidates —
`sub_surveyors/data_profiler.py`'s per-file `SchemaAnalysisAnnotation`s
linked to its aggregate `ResourceMeasureAnnotation`, and
`sub_surveyors/dependency.py`'s per-ecosystem `DataClassAnnotation`s linked
to its aggregate — become real, queryable `AnnotationExtension` edges in
Egeria. An external consumer walking the catalog can now enumerate "which
schema annotations back this file-count summary" without re-running RE.

**Verification:** publish once against a live project with data files;
confirm via `MetadataExpert.get_all_related_elements` (or
`DataDiscovery.get_annotation_extensions`, the read-only call, which does
already exist and was never in question) that the expected N links exist,
pointing the expected direction. Re-publish the identical run a second time
(simulating exactly the "40 duplicate edges" / "69 where 35 belonged"
failure mode named in the task brief) and confirm the count is still N, not
2N — this is the known-negative the task's guard rule requires: the test
must be run once *without* the idempotency guard (temporarily) to confirm
it actually would have duplicated, before trusting that the guard's "still
N" result means anything.

**Rollback:** the new `element_kind` and its creator are additive to
`_CREATORS`; removing them stops new link rows from being enqueued, and any
already-created `AnnotationExtension` relationships in Egeria are inert —
nothing else reads them yet at this phase, so leaving them in place after a
code rollback is harmless. If Phase 0 finds `AnnotationExtension` rejects
creation outright against this server version, this phase does not proceed
(hard blocker, not a partial-ship).

### Phase 3 — Cross-run linking (security_summary.py and the rest of Tier 2) — NOT covered by this plan's implementation, scoped for a future pass

This plan deliberately stops before implementing Phase 3. Reasons, restated
from Q3 findings:

1. It requires the granular per-input findings
   (`security_hygiene`/`ci_quality`/etc.'s individual checks, currently
   local-only per the audit's Tier 2 table) to become their own Egeria
   annotations first — a real increase in annotation volume and a separate
   design decision the audit already flagged as out of its own scope, and
   which this plan does not resolve either.
2. Even with Phase 1's `egeria_annotation_guid` column landed, it is
   populated only going forward — every finding row from before that
   migration has no recoverable GUID (Q3's "hole in history"). A summary
   published today that reduces over pre-migration findings has nothing
   Phase 2's mechanism can link to.
3. The three sub-surveyors the audit found *already* publishing one
   `ClassificationAnnotation` per check_name (`security_features.py`,
   `repo_conventions.py`, `ci_quality.py`) do so under a *different*
   qualifiedName scheme than `security_summary.py`'s own reducer output —
   reconciling "which of security_summary's 8 inputs corresponds to which
   of ci_quality's already-published annotations" is a matching problem
   this plan has not attempted, on top of everything above.

Phase 3, when picked up, should start by re-confirming point 3 specifically
(a live query comparing `security_hygiene`'s `check_name`s against
`ci_quality.py`'s published `annotationType` values) — that reconciliation
question is unanswered here and is very likely a bigger design problem than
the plumbing this document covers.

`foss_scorecard.py`, `cve_scan.py`, `community_support.py`,
`chaoss_metrics.py`, and the architecture-recovery family
(`arch_summary.py` etc.) are not covered for the same reason as #1 above —
none of their evidence exists as Egeria annotations today, and this plan
does not propose starting that publication (that decision belongs to
whoever owns the volume/cost tradeoff the audit already named, not to a
linking plan).

## Honest-limits section

- **Direction of `AnnotationExtension`'s two ends** (audit's own
  unresolved item) — not determined here either. The Java model
  (`OpenMetadataType.java:6008-6014`) gives no end-1/end-2 semantic beyond
  the class names on `AnnotationExtensionProperties`
  (`extends LabeledRelationshipProperties`, no additional fields of its
  own — confirmed by reading the class), and going further into the
  repository-services relationship-def archive to resolve end
  cardinality/label was out of the time budget for this pass. Phase 0's
  live measurement should record this alongside the UNI/MULTI_LINK finding
  — same experiment, negligible extra cost.
- **Whether `MULTI_LINK` is in fact `AnnotationExtension`'s category** — not
  determined; flagged in Phase 0 as the load-bearing unknown the rest of
  Phase 2's idempotency design branches on. Do not build the "skip if
  UNI_LINK" code path before this is confirmed.
- **Whether the generic `related-elements` endpoint enforces end-type
  restrictions that would reject `AnnotationExtension` between two
  `Annotation`s specifically** — plausible either way; Java source alone
  does not settle it (validation of this kind commonly lives in the
  repository's type-def enforcement, not the REST layer), hence Phase 0
  treats this as a live-call question, not something resolved by more
  reading.
- **`security_hygiene`/`ci_quality`/`repo_conventions`'s existing
  qualifiedName scheme for their per-check annotations**, and whether it is
  reconcilable with `security_summary`'s `check_name`s at all — read
  enough to know this is a real question (Phase 3, point 3) but not
  resolved here; would need reading those three sub-surveyors' own
  qualifiedName construction in full, which this pass did not do.
- **Cost of Phase 1's back-fill for cross-run linking** — not estimated.
  ~68,000 existing rows (task brief's figure) times however many of them
  are reducer-kind findings whose annotations still exist in Egeria and are
  resolvable by re-deriving their qualifiedName (Q3 already found this
  reconstruction path unreliable in general) is not a number this pass
  computed.
