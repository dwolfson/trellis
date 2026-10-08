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
