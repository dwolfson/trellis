# Blueprint container shape and what-it-represents names — implemented (2026-10-08)

Built from `DESIGN-BLUEPRINT-BENCHMARK-EGERIA-WORKSPACES.md` (0, 6, 6a) and
the 2026-10-08 naming ruling (blueprint and component names say what they represent) on `re/blueprint-container-shape`.

## What is written

* **Container shape (default, the root is a real component):** the root is the only blueprint member
  (`CollectionMembership`, outbox, idempotent) and each other member is its sub-component by
  `SolutionComposition` (`link_subcomponent`, idempotent by the pair, key
  `SolutionComposition::<container QN>::<child QN>`). A pair already present is not rewritten.
* **Contents shape (the root is a grouping, or a person flips it):** the children are the members, no root
  element, no composition. Never both a container and its contents as direct members.
* The shape, and why, is named in the accept dialog before the write (a flip is an explicit choice) and
  stored as a `shape` proof row; each composition has a proof row that says whether a read by GUID really
  backed it. No zone and no ownership is written. RE deletes, detaches and renames nothing.

## Names (displayName only, never qualifiedName)

Five closed words derived from the evidence class (`blueprint_shape.represents_kind`): code module (a
package manifest), container definition (a Dockerfile or compose service, built, shipped or referenced),
image, runtime, none (a content-pack element). Components read `<name> (<word>)`; a blueprint of one kind
reads `Egeria Deployment Blueprint (container definitions)`; a mixed blueprint, or one with a member whose
kind is not known, takes no suffix; sub-resource names (`<path> · <repository>`) take none. A repo-derived
component that maps to a content-pack element (image `odpi/egeria-platform` is the only mapping proved so
far, `CONTENT_PACK_IMAGES`) ADOPTS it: no second component, no rename, words
"OMAG Server Platform · adopted from the content pack · matched by image odpi/egeria-platform".
**Names written before this change are pre-suffix** and are not renamed here. A future classification
(`Represents(kind)`, proposed to the Egeria leads) would replace the suffix by classify then rename-forward,
additive.

## Verified versus inferred (the children read)

* Verified in Egeria's source (`AttributedMetadataElement`, `OpenMetadataTypesArchive1_7`): the
  `SolutionComposition` end on the CONTAINER that lists its children is `nestedSolutionComponents`; the end
  on the child is `usedInSolutionComponents` ("the solution components that embed this component").
* Verified in pyegeria: `get_component_related_elements` flattens `nestedSolutionComponents` and
  `subComponents` into one list and yields `[]` when both are absent, so it cannot tell "none" from "did not
  say". RE therefore reads the element with `get_solution_component_by_guid` and trusts an empty answer only
  when at least one of the two keys is PRESENT; otherwise nothing is written and the row says "the read did
  not say whether children exist".
* Inferred, not run live: that the default report spec returns `subComponents` (or the raw form returns
  `nestedSolutionComponents`) even when empty. If Egeria omits an empty list, a childless container will
  report "unconfirmed" instead of writing: safe, and the live gate will show it.
* Absence is decided by `egeria_absence.is_absent` only: Egeria's no-elements answer, a not-found
  exception or an API exception carrying 404. Unauthorised, transport and anything else is unreadable, and
  RE never creates or forgets a cached GUID on it. A name search that raises creates nothing.
* The content-pack by-name lookup requires an equal displayName; two matches adopt nothing and say so.
  Adoption by qualifiedName verifies the element is a SolutionComponent with that qualifiedName and reports
  what it skipped.
* Direct members left by an earlier run are read (`collectionMembers`, key presence required) and reported
  as `extra_members` with the words "a steward can detach them in Egeria Explorer"; RE never removes them.

## The blueprint's identity is kind + repository (follow-up to #556, 2026-10-08)

The architect's ruling, recorded in `DESIGN-BLUEPRINT-NAMING-WHAT-IT-REPRESENTS.md` section 2a, took the root
cluster's name out of a blueprint's Egeria identity: #556 still wrote
`SolutionBlueprint::<type>::<slug>::<Kind> Blueprint::<cluster>` and keyed its cache on the cluster. Now:

| | before (#556) | before that | now |
|---|---|---|---|
| qualifiedName | `SolutionBlueprint::repo::egeria_git::Deployment Blueprint::OMAG-Server-Platform` | `...::egeria_git::deployment::OMAG-Server-Platform` | `SolutionBlueprint::repo::egeria_git::deployment` |
| a second blueprint of the kind | one per cluster name | one per cluster name | `...::deployment::<identifier>`, the identifier a person's |
| `identifier` property | none | none | `EGERIA-GIT-DEPLOYMENT` (`<SLUG>-<KIND>`; a second one appends its identifier) |
| displayName | unchanged (`blueprint_suffix_name`, e.g. "Egeria Deployment Blueprint (container definitions)"); a second one reads "... Blueprint · <identifier>" | | |
| cache key | (entity, slug, perspective, cluster_name) | same | the identity string (entity, slug, kind, identifier or ''), held in the existing `qualified_name` column; `perspective` and `cluster_name` stay on the row as RE's internal key for the cluster |

**No DDL.** The string key lives in a column that already exists. `get_materialized_blueprint_by_identity`
reads by it; `record_materialized_blueprint` keeps one row per identity (a row left by a cluster that has since
been renamed is replaced). Rows written under the old key are read by a mapping: the cluster's own row is read
whatever name it carries, and a row whose qualifiedName is one of the two old forms is an adopted legacy
blueprint.

**A second blueprint of one kind** needs a person's identifier. The accept pane shows a short text input only
when another live cluster of that kind already holds the repository's identity (`identity.needs_identifier` on
the blueprint row): the word beside it reads "needed", "ready" or the one-word problem, and the sentence is the
field's title. Without one the write is refused before any search or create: "a Deployment Blueprint already
exists for egeria_git · give this one an identifier". The identifier is trimmed, 1 to 64 characters of
letters, digits, space, `.`, `_`, `-`, never `::`; it is never derived from a cluster name.

**Legacy names are adopt-only.** A blueprint found under either older form (searched after the new name) is
adopted, never duplicated, and nothing is ever created under them. Each adoption writes an activity row:
"adopted legacy-named blueprint <guid> · delete it in Egeria to recreate under the new name". Nothing in RE
deletes a blueprint (the ISSUE-117 block is untouched); for 254dbbe6-1367-40d1-889c-909a1e4489f7 the owner
deletes it in Egeria first, and the next accepted verdict (cache check by GUID) recreates it under the new name.

**Where the cluster name still shows.** The registry row, the verdict `scope_locator`, the shape proof rows'
`scope_key` and the child-blueprint cache lookup (`resolve_child_blueprint_guids`) still key on
`perspective::cluster_name`: that is RE's own key for the cluster, not Egeria's. A first-of-kind blueprint
accepted on a non-root cluster, with no identifier, still carries that cluster's name in its displayName only.
A blueprint adopted under a legacy name keeps carrying the root name until it is deleted and recreated.

### Unverified live

* The wire name of the identifier. pyegeria's `SolutionBlueprintProperties` declares no `identifier`
  (`ReferenceableProperties` has `version_identifier`; only `DesignPatternProperties` has `identifier`). RE
  sends `identifier`; whether Egeria's SolutionBlueprint accepts it under that name, or drops it, is not run.
* Whether Egeria rejects a create whose qualifiedName already exists (RE never relies on it: it searches
  first).
* Search behaviour for the new qualifiedName: `get_guid_for_name` searches several properties with no type
  restriction, so `...::deployment` may also match a longer name that contains it, or an element of another
  type. Not run.

Deleting a stale `architecture_materialized_blueprints` row when the same qualifiedName is re-recorded is
fine: that table is a cache of Egeria elements, not a proof or a decision, and proof rows are never deleted.

### Provenance, typed search and adoption (review round)

**Provenance.** On every SolutionBlueprint it creates, RE writes in `additionalProperties`: `re_entity_type`,
`re_slug`, `re_kind`, `re_cluster_key` (RE's internal cluster key, the registry column), `re_identifier` (only
when a person gave one) and `re_version` ("1", the format of this provenance). The element is the record; the
registry is its cache. A displayName changes with the suffix ruling and later classification, and the reset
script clears registry rows by design, but a property RE wrote survives both.

**Adopting an element found by qualifiedName** (no usable cache row for this cluster):

* (a) `re_cluster_key` equals this cluster's: adopt, and rewrite the lost registry row.
* (b) `re_cluster_key` present and different: refuse, "an element named <qn> already exists in Egeria for
  another cluster (<its key>) · give this one an identifier"; nothing created or attached. A renamed root
  cluster therefore also asks for an identifier rather than taking the old cluster's element.
* (c) no provenance (not RE-made, or made before it): adopt only when the displayName equals what this
  cluster would produce and no other cluster's row records the qualifiedName; otherwise refuse, "an element
  named <qn> already exists in Egeria and RE cannot tell which cluster it is for · give this one an
  identifier". A displayName that has legitimately changed since the create lands here and is refused.

Each adoption and each refusal writes an activity row with the GUID. The legacy-named adoption row is written
once per adopted blueprint (not on every cache hit) and carries the repository scope on the feed.

**The search is typed and verified.** `get_guid_for_name(qn, property_name=["qualifiedName"],
type_name="SolutionBlueprint")`, then the hit is read back: type SolutionBlueprint and an exactly equal
qualifiedName, else nothing is adopted or created. More than one hit (pyegeria raises on it) is reported as
ambiguous, not as a failed search.

**Uniqueness** of a person's identifier is checked on the resulting Egeria identifier, so `a b` and `a-b`, or
`X` and `x`, are the same identity and the second is refused as already used. Re-recording a row under a
qualifiedName another cluster's row held replaces that row and says whose, in the activity log.

**Known stale state (not fixed).** A takeover after the accept pane rendered leaves `needs_identifier` stale
until the pane reloads.

### Unverified live (review round)

* Egeria persisting `additionalProperties` on a SolutionBlueprint create, and returning them from
  `get_solution_blueprint_by_guid` under the "Solution-Blueprint" report spec (pyegeria's raw shape is
  `properties.additionalProperties`; a formatted one `additional_properties`). If the read omits them, every
  existing element falls to rule (c), which is the safe side.
* That the typed search (`property_name=["qualifiedName"]`, `type_name="SolutionBlueprint"`) matches an exact
  qualifiedName, and that the read-back carries `typeName` (an absent type is accepted when the qualifiedName
  matches).

### Re-surveys rename clusters (follow-up)

`re_cluster_key` is the cluster's name, and a re-survey can rename a cluster (the name is derived from its
members and wires), so the key is not stable. Rule (b) therefore refuses only when the other cluster is LIVE
(or when the live set is unknown): if the element's key names a cluster that no longer exists, the accepting
cluster is the same real cluster under a new name, and RE adopts the element, re-keys the registry row, and
writes the activity row "re-keyed from <old>". RE does not rewrite the element's `re_cluster_key`: the update
call's merge semantics are unverified live, so it stays stale and is read as stale each time. In rule (c) a
registry row of a cluster that no longer exists does not count as another cluster's row. A refusal is logged
once per element; an adoption row is written after the cache row is recorded.

**Known gap, left on purpose:** `resolve_child_blueprint_guids` still takes a child blueprint's GUID from the
registry row with no existence read (pre-existing). Adding one needs a connection in a method documented as
never raising, and an unreadable answer has no place to go in its return shape; it belongs with the shape
workflow's own cache verification, not in this change.

**One adopter, and a proof of the re-key.** If a re-cluster splits one group in two, both new clusters would
see the old key as gone. Among the live clusters with no cache row only the first by name adopts; the rest are
refused with the ordinary "another cluster" sentence, so an element never has two claimants. A re-key writes a
proof row of its own kind, `rekey`, into `catalogue_commit_proofs` (node_kind `blueprint_shape`, table_name
`<perspective>::<new key>`, element_guid the blueprint; detail holds the old key, the new key and the GUID), after
the element was read back and the cache row rewritten. No DDL and no new table. Proof rows are never edited or
deleted. RE writes nothing to the element: the publish does not touch `additionalProperties` after create, and
there is no new Egeria write kind, so the old `re_cluster_key` stays on the element as a hint, never a conflict;
the registry row is the authority.
