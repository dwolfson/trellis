# Investigation classification and zoning — design & plan

**Status: design. Phase 1 is built and live-verified (2026-09-07); Phases 2–6 are not.** Extends
`docs/investigation-framing-design.md` §1 (the Investigation record) and §6a
(promotion). Does not supersede it; that document still governs membership,
Purpose, and the local-first/promotable shape. This one covers two things it
left open: **which Egeria classification an investigation carries**, and
**who can see the investigation and the artifacts it produces**.

Written 2026-09-07 from a proposal by the project owner. Everything asserted
about Egeria below was read out of the Egeria 6 source in
`~/localGit/egeria-v6/egeria`, not from documentation — file and line given
in each case, because two of the findings are the opposite of what the type
model suggests.

---

## 0. Summary of the findings that shape the design

Four facts do most of the work here. Three of them were surprises.

1. **`Experiment` is a real Egeria classification**, and Dr.Egeria already
   accepts it. RE's local vocabulary is missing it.
2. **RE already collects a classification and never sends it.** Every
   investigation ever promoted is a bare `Project`.
3. **Zoning is legal on any element, not just Assets** — `ZoneMembership` is
   defined against `OpenMetadataRoot` as of the 6.0 archive. Projects,
   Collections, SurveyReports and Annotations can all carry it.
4. **Zone enforcement fails open, and the obvious private-zone spelling
   denies nobody.** An element with no `ZoneMembership` is not evaluated at
   all, and a zone the platform does not recognise is *ignored* rather than
   treated as restrictive. Both directions read as "visible".

(4) is the one that decides how this gets built. It is the shape
`find-absence-as-answer` describes with real consequences attached: the UI
says private, Egeria serves the element, and nothing errors.

---

## 1. The vocabulary

### 1.1 What Egeria actually has

`OpenMetadataType.java` (model 0130 Projects) defines five classifications
that are peers, plus one that is not:

| Classification | Egeria's own definition |
|---|---|
| `PersonalProject` | "an informal project that has been created by an individual to help them organize their work" |
| `StudyProject` | "a focused analysis of a topic, person, object, or situation" |
| `Task` | "a self-contained, short activity, typically for one or two people" |
| `Campaign` | "a long-term strategic initiative that is implemented through multiple related projects" |
| `Experiment` | "a project conducting an experiment that is testing a hypothesis (documented in the `hypothesis` attribute)" |
| `ProjectClassification` | **not a peer** — "capturing the description of a project's governance and the expectation of how the results will be used" |

Dr.Egeria's `Project Type` attribute
(`egeria-python/md_processing/data/compact_commands/commands_project_compact.json`)
already carries all five plus a bare `Project` in its `valid_values`, so the
authoring path needs nothing new. Its *description* string is stale and names
only four — logged as ISSUE-92 in `egeria-python/PYEGERIA_ISSUES.md`, not
fixed here.

RE's `ProjectRegistry.PROJECT_CLASSIFICATIONS` (`registry.py:5441`) is
`("PersonalProject", "Task", "StudyProject", "Campaign")` — correct as far as
it goes, missing `Experiment`.

### 1.2 `StudyProject` gets its Egeria meaning back

The proposal's motivation for a new category is that RE has been using
"Study" to mean *investigate without commitment yet*, which is not what
Egeria's `StudyProject` means. Egeria's is "a focused analysis of a topic,
person, object or situation" — which is a good description of most RE
investigations, and is the meaning we should adopt. `StudyProject` stays the
default for that reason, and the docstring at `registry.py:5440` that
justifies the default as "the least committal" should be rewritten: the
reason to default to it is that it is *accurate*, not that it is timid.

### 1.3 `adHoc` is not a classification — it is the absence of a binding

`project_classification` is validated against an Egeria vocabulary and is
destined for `initialClassifications` on the create body. A value in that
column that Egeria has never heard of gets dropped or rejected at the
boundary, and the column's name would then be a lie about what it holds.

The proposal already contains the resolution: point 4 says every kind
*except* ad-hoc is created in or linked to Egeria. So ad-hoc is not a kind of
project at all — it is **"this investigation has no Egeria Project"**, which
the schema already models as a nullable `egeria_project_guid`
(`investigation-framing-design.md` §1 calls that "the single most important
structural decision here").

**Two columns, one control.** The create form shows one dropdown with six
entries; underneath it writes two fields:

| UI choice | `project_classification` | `egeria_binding` |
|---|---|---|
| Ad-hoc | `StudyProject` (kept, unused until promoted) | `local` |
| Study | `StudyProject` | `egeria` |
| Task | `Task` | `egeria` |
| Campaign | `Campaign` | `egeria` |
| Personal | `PersonalProject` | `egeria` |
| Experiment | `Experiment` | `egeria` |

Keeping the classification on an ad-hoc row (rather than nulling it) matches
what the schema comment at `registry.py:2046` already says about this column:
promoting later should not have to re-ask for something the user decided at
creation.

`egeria_binding` is a new column and is derived state — it is `egeria`
exactly when the row has, or is meant to have, a project GUID. It exists so
the *intent* is recorded before the promotion succeeds; a promotion that
fails halfway must not look like a deliberate ad-hoc investigation.

### 1.4 `Experiment` needs `hypothesis`

`ExperimentProperties` carries `hypothesis`, and it is what the
classification is *for*. Offering `Experiment` without collecting a
hypothesis publishes a classification whose defining property is empty —
which is the catalog-description version of the same absence problem. The
create/edit form must require it when `Experiment` is chosen, and the
publisher must send it.

---

## 2. The classification is collected and then thrown away — **fixed, Phase 1**

`project_classification` is:

- stored — `registry.py:2050` (column) and `:2068` (migration)
- offered in the UI — `web/static/index.html:10075`
- validated on create — `registry.py:5459`, which raises on an unknown value

and then `EgeriaInvestigationPublisher.promote()`
(`surveyors/egeria_investigation_publisher.py:140`) builds:

```python
res.project_guid = pm.create_project(
    body={"class": "NewElementRequestBody", "properties": properties},
)
```

with no `initialClassifications` key anywhere in the body. Every investigation
ever promoted from RE is an unclassified `Project`.

This is the same shape as the `Ownership`/purposes correction already
recorded in that file's own comments: a value collected carefully, validated
carefully, and dropped at the last hop. It is one field, it is independent of
everything else in this document, and it should land first.

**Verification, since a passing publish proves nothing here:** read the
classification back off the created Project. A test that only asserts
`create_project` was called with *a* body would have passed for the whole
period this has been broken.

**Built 2026-09-07.** `promote()` now sends
`initialClassifications: {"<Name>": {"class": "<Name>Properties"}}`, then reads
the classification back off the created Project and records the outcome in
three distinguishable states on `PromotionResult` — `classification_confirmed`
is the name when verified present, `""` when verified **absent** (an error,
though the Project stays bound because the route binds on `project_guid`), and
`None` when the read-back could not be made at all. An unrecognised
classification refuses *before* any Egeria write rather than creating a Project
without one. The promote panel renders all three states differently, since the
whole failure was that nothing on that screen said anything.

Six tests in `tests/test_investigation_routes.py`; each guard was made to fail
on purpose before being trusted — removing the `initialClassifications` line
fails the two body assertions, and stubbing the read-back to always confirm
fails the drop-detection and the could-not-verify tests.

---

## 3. Zoning

### 3.1 What is legal

`OpenMetadataTypesArchive6_0.getZoneMembershipClassification()` builds the
`ZoneMembership` classification against
`OpenMetadataType.OPEN_METADATA_ROOT` — every element, not `Asset`. So the
Project, its Folio/WorkingSet Collection, and the SurveyReports and
Annotations RE publishes can all carry zones. Nothing in the type model
blocks the proposal.

### 3.2 How enforcement actually decides — and the two ways it says "yes"

`OpenMetadataAccessSecurityConnector.validateZoneAccess()` (line 1090). The
loop over the element's zones:

```java
if (userId.equals(zoneName))
{
    return true;
}
else if (zoneName != null)
{
    List<String> associatedSecurityList = getAssociatedSecurityListForZone(zoneName, operation);

    // If the zone has no associated security list, then it is not a secured
    // zone and is ignored.  This is different from giving everyone access.
    if (associatedSecurityList != null)
    {
        securedZoneCount++;
        ... group / role / account-type / instance-based checks ...
    }
}
```

and after the loop:

```java
if (securedZoneCount > 0)
{
    return false;
}
...
// If this point is reached, the user has access.
return true;
```

Two things follow, and they are the crux of the whole design.

**(a) A zone named with a userId is a private grant.** Egeria has already
built "visible only to the creator" — it needs no configuration, because the
comparison is against the string itself.

**(b) A userId-only zone list denies nobody.** For any *other* user,
`"dwolfson"` is not their userId, `getAssociatedSecurityListForZone("dwolfson")`
returns null because no such zone is configured, the zone is ignored,
`securedZoneCount` stays 0, the loop ends, and the method returns `true`.
`zoneMembership = ["<userId>"]` is, for everyone except the owner, exactly
equivalent to no zone at all.

Denial requires **at least one zone in the list that the platform recognises
as secured**. So the correct spelling of a private element is a pair:

```
zoneMembership = ["resource-explorer-private", "<creator userId>"]
```

- the **owner** matches on entry two and short-circuits to `true`
- **everyone else** finds entry one *is* secured, fails its security list,
  reaches the end with `securedZoneCount == 1`, and gets `false`

One shared secured zone, and the per-user part is carried by the userId
string. No per-user configuration at any scale.

### 3.3 Where the security list lives — and why this answers "can we create a personal zone?"

Asked directly: **can RE create a personal zone for a user who does not have
one, and assign them to it?** The answer is in two halves and they differ.

**The `GovernanceZone` metadata element: yes.** RE already does this —
`egeria_identity.ensure_draft_zone_exists()`, leader-elected and one-shot from
`worker.py:231`. Creating another one per user is mechanically easy.

**The enforcement: no, and this is the important half.**
`getAssociatedSecurityListForZone` (line 911) reads *only* from
`secretsStoreConnectorMap` — the platform's `SecretsStoreConnector`. It never
consults open metadata. The `associatedSecurityList` that makes a zone
*secured* lives in the deployment's `.omsecrets` file, under
`secretsCollections.userDirectory.securityAccessControls`:

```yaml
      security:
        controlDisplayName: Security Zone
        controlTypeName: GovernanceZone
        associatedSecurityList:
          DEFAULT:
            - securityManager
            - governanceEngine
            - integrationConnector
```

(`egeria-workspaces-fs/compose-configs/egeria-freshstart/secrets/egeria-user-directory.omsecrets`,
lines 697–735.)

There is no Egeria API that writes this. So **a zone RE creates at runtime is
decorative** — it exists as a catalog element, has no security list, and is
therefore *ignored* by the check. An element zoned into it would look private
in every UI and be readable by everyone. That is strictly worse than no zone,
because it manufactures the exact false reassurance this whole section is
guarding against.

**Which is why per-user zones are the wrong answer and are not needed.** The
`userId.equals(zoneName)` shortcut exists precisely so private content does
not require a zone per person. The design therefore is:

- **One** secured zone, `resource-explorer-private`, added once to the
  deployment's `.omsecrets` at install time, with an `associatedSecurityList`
  granting a group **nobody holds** — so the zone denies universally and the
  userId entry is the only key.
- Every private element carries `["resource-explorer-private", "<userId>"]`.
- Adding a user requires **nothing**. There is no per-user zone to create, no
  assignment step, and no question of "does this user have a personal zone
  yet" — the answer is always yes, because their userId is the zone.

Two cautions on the security list's contents:

- Do **not** grant `instanceOwnersGroup`. `isUserAnOwner()` (line 1260)
  returns **true when the element has no `Ownership` classification at all**
  — "if no ownership classification is assigned to the element, then the user
  is considered to be an owner." RE does stamp Ownership, but a single
  unstamped element would then be readable by anyone. Same fail-open shape;
  don't build on it.
- Do **not** grant `openMetadataMember` (which the broad READ lists use) —
  that is effectively everyone.

**If per-user zones are ever genuinely wanted** — e.g. to set per-user
`otherProperties.defaultZones` / `publishZones`, which `getZonesForUser()`
reads for new elements — it means writing the `.omsecrets` file. Feasible
without a restart: `SecretsStoreConnector` line 169 computes
`refreshTimeInterval * 60 * 1000`, so the freshstart config's
`refreshTimeInterval: 10` is **ten minutes**, and the store re-reads on its
own. But that file also holds `clearPassword` entries for every account on
the platform, and giving RE write access to it is a trust escalation well out
of proportion to the feature. **Recommend against; use the shared-zone design
above.**

### 3.4 Fail-open, and why anchoring is the answer

`validateUserForAnchorMemberRead` (line 1403) only evaluates zones when the
requested entity actually carries the classification:

```java
if (repositoryHelper.getClassificationProperties(serviceName,
                                                 requestedEntity.getClassifications(),
                                                 ZONE_MEMBERSHIP_CLASSIFICATION.typeName,
                                                 methodName) != null)
```

An artifact that misses the stamp is not "denied by default" — it is not
checked. Combined with §3.2's "an unrecognised zone is ignored", the failure
mode in both directions is *visible*.

A design that depends on stamping every artifact correctly is therefore a
design with N chances to silently leak, where N grows with every new
annotation type. Do not build that.

**Use the anchor instead.** `OpenMetadataAPIAnchorHandler` (around line 152)
copies `ZoneMembership` onto the `Anchors` classification, with the comment
*"If the ZoneMembership classification is set then add it to the anchor. This
allows for efficient security evaluation."* So if RE anchors the artifacts it
produces to the investigation's Project, the zone travels with the anchor and
the invariant collapses from *"is every artifact stamped?"* to *"is every
artifact anchored?"* — one property, checkable in one query.

**This must be verified live before it is relied on**, against a second
userId, on a real SurveyReport. The check to run is not "does the owner see
it" — that passes under every broken variant. It is **"does a second user
fail to see it"**, and it has to be seen to fail. A zoning scheme that has
never been observed to deny anybody is not known to work.

### 3.5 Public means *in the publish zone*, not *unzoned*

Proposal point 6 asks that Task / Campaign / Study be publicly visible. Do
not implement that as "leave it unzoned". Unzoned means *not evaluated*,
which today happens to render as public and is a different fact — it diverges
the moment the connector or the deployment config tightens.

Put them explicitly in `egeria_identity.publish_zones()`
(`DEFAULT_PUBLISH_ZONES = ("egeria-runtime",)`), which is the machinery RE
already uses for curate-accept. "Follow the visibility rules of an existing
project" (also point 6) then means: when binding to an existing Egeria
Project, read that Project's `ZoneMembership` and use it, rather than
asserting our default over it.

### 3.6 What an investigation may zone — and what it must not

`investigation-framing-design.md` already establishes that membership is
many-to-many: "the same repo is simultaneously something you are evaluating,
something a compliance sweep is checking, and something someone else's
Campaign owns."

So the rule is:

> **An investigation zones what it produced, never what it references.**

In scope: the Project, its Folio/WorkingSet Collection, and the
SurveyReports/Annotations produced under it.

Out of scope: the repo/database/filesystem Assets themselves. Adding a public
repo to a personal investigation must not hide that repo from everyone else —
a privacy feature that removes other people's access is a data-loss feature.

This is a constraint on the promotion and zoning code, and it deserves a test
that adds an already-public asset to a `PersonalProject` investigation and
asserts the asset's zones are unchanged.

---

## 4. RE's own visibility — the half Egeria cannot enforce

Egeria zoning hides nothing inside RE. RE reads its own registry, and the
`investigations` table today has **no creator column at all** (DDL at
`registry.py:2030–2056`). `list_investigations()` returns every investigation
to every caller.

So proposal point 5 has no local anchor yet, and this is probably the larger
practical gap: most people looking at a personal investigation will be
looking at it in RE's UI, not in Egeria.

Needed:

- `created_by` on `investigations`, populated from `current_user_id()` — the
  same mechanism `resource_working_set` already uses for per-user view
  preferences (`registry.py:5380`), including its `SHARED_USER_ID` fallback
  for rows written before scoping existed.
- `list_investigations()` filters out `PersonalProject` / `Experiment`
  investigations not created by the caller. Note the fallback rule already
  established for the working set: a pre-existing row with no creator should
  not vanish from the person who made it.
- The same filter on the findings/dashboard reads that join through an
  investigation.

Backfill is a real decision, not a detail: existing investigations have no
creator, and defaulting them to "private to nobody" hides them from everyone
while defaulting them to public exposes anything that should have been
personal. Since none were created under a personal/private expectation (the
feature did not exist), **backfill to shared** and say so in the migration
comment.

---

## 5. Reclassification (proposal point 7)

Changing an investigation's classification is **a flow with a report, not an
UPDATE**. It is up to three Egeria operations, each of which can fail
independently:

1. remove the old classification (`validateUserForElementDeclassify`)
2. add the new one (`validateUserForElementClassify`)
3. change `ZoneMembership` — which routes through
   `validateUserForElementClassify`'s ZoneMembership branch (line 1798) and
   requires `AccessOperation.PUBLISH` **on the original zones**, throwing
   `throwUnauthorizedZoneChange` otherwise

Plus the constraint RE already documented in `egeria_identity.current_zones`'
docstring: the connector rejects a zone change whose before and after are
equal.

Two directions, asymmetric risk:

- **Loosening** (Personal → Task): artifacts become visible. If a step fails,
  something stays private that should be public. Annoying, safe, visible to
  the user who asked.
- **Tightening** (Task → Personal): artifacts are *already public* and every
  one must be re-zoned. **Anything the sweep misses stays readable while the
  UI says private.** This is the dangerous direction and it is the one that
  must be built defensively: enumerate the targets first, re-zone, then
  **re-read and verify**, and report any element that could not be moved as a
  loud, per-element failure rather than a summary count.

Model the return on `PromotionResult` (`egeria_investigation_publisher.py:53`)
— it already gets this right: `members_linked`, `members_unlinkable`,
`errors`, and an `ok` that is false if anything went wrong. A tightening that
partially fails must report `ok = False` and name what is still public.

§3.4's anchoring makes this dramatically simpler: re-zone the Project, and
anchored artifacts follow. That is another reason to do anchoring first.

---

## 6. Plan

Ordered smallest-blast-radius first. Each step is independently useful and
independently shippable.

**Phase 1 — publish what we already collect. ✅ Done 2026-09-07.** Added
`initialClassifications` to `EgeriaInvestigationPublisher.promote()`'s create
body, with read-back verification and a tri-state result. See §2. *(No schema
change, no security implications; one addition to the promote panel so the
outcome is visible.)*

**Live-checked 2026-09-07, and the check found a real defect in itself.** All
five classifications — Campaign, Task, PersonalProject, StudyProject and
**Experiment** — were created against `qs-view-server` and read back
CONFIRMED, then deleted; a follow-up search by a different route showed 50
Projects before and 50 after, zero leftovers. Egeria accepts
`initialClassifications` exactly as sent.

But the read-back parsing was **wrong**, in the direction that hides the bug.
`_confirm_classification` had guessed a top-level `classifications` list.
The real payload from `get_project_by_guid(..., output_format="JSON")` is an
`OpenMetadataRootElement` whose project classifications live under
**`elementHeader.projectKinds`**, grouped apart from `elementHeader.anchor`
(which carries `Anchors`) because they are all `ProjectKind` subtypes:

```
{"class": "OpenMetadataRootElement",
 "elementHeader": {"guid": ..., "type": {...}, "anchor": {...},
                   "projectKinds": [{"class": "ElementClassification",
                                     "classificationName": "Task",
                                     "type": {"typeName": "Task",
                                              "superTypeNames": ["ProjectKind"]}}]},
 "properties": {...}, "resourceList": [...], "mermaidGraph": ...}
```

Against that shape the original function found nothing, and returned `None` —
"could not tell" — on **every** call. The safe direction, as predicted, and
therefore invisible: the five tests passed, because the stub had invented the
same wrong shape the code assumed. Two artefacts agreeing with each other and
neither agreeing with Egeria.

One further measured detail, now load-bearing: **`projectKinds` is omitted, not
null, when a Project has no kind** — 36 of 50 live Projects carry the key and
14 lack it entirely. So an absent key cannot by itself be read as "not
classified", since a changed payload shape looks identical. `elementHeader.guid`
is the sentinel that separates them, and `_StrangePayloadPM` in the tests pins
the distinction.

**Phase 2 — vocabulary.** (`Experiment` is already de-risked: Phase 1's live
check created and confirmed one, so Egeria accepts `ExperimentProperties` as an
initial classification.) Add `Experiment` to `PROJECT_CLASSIFICATIONS` plus
a `hypothesis` field required when it is chosen. Add the `egeria_binding`
column and split ad-hoc onto it. Rewrite the `StudyProject`-default docstring
to say *accurate* rather than *least committal*. UI: one six-entry dropdown.

**Phase 3 — local visibility.** `created_by` on `investigations`, backfilled
to shared; filter `list_investigations()` and the reads that join through it.
*This is the phase that makes "personal" mean anything to a person using RE,
and it needs no Egeria change at all.*

**Phase 4 — anchoring.** Anchor investigation-produced artifacts
(SurveyReports, Annotations, the Folio) to the investigation Project. Verify
the `Anchors` classification actually carries `zoneMembership` through, live.
*Prerequisite for Phase 5 being safe; independently valuable for lineage.*

**Phase 5 — zoning.** Requires a deployment change first: add
`resource-explorer-private` to the `.omsecrets` `securityAccessControls` with
a security list nobody holds. Then zone Personal/Experiment investigations as
`["resource-explorer-private", "<creator userId>"]` and Task/Campaign/Study
into `publish_zones()`. **Gate on the live two-user denial test** in §3.4 —
if a second user can still read a private SurveyReport, the phase is not
done, regardless of what the code does.

**Phase 6 — reclassification.** The flow in §5, with the tightening direction
built verify-then-report.

---

## 7. Open questions

- **Does `Anchors.zoneMembership` propagate to *newly created* children, or
  only to elements anchored at creation time?** The handler copies it when
  deriving anchor identifiers; whether a SurveyReport published after a later
  zone change picks up the new value, or the old one cached on the anchor,
  decides whether §5's tightening sweep can rely on it. **Measure before
  designing around it.**
- **What is RE's userId, really?** §3.2's private grant compares against the
  string in `zoneMembership`. RE publishes queued work *as the service
  account with `Ownership` set to `requested_by`*
  (`egeria_identity.py` module docstring — deliberate, and documented as
  interim). If the zone carries `requested_by` but the write runs as the
  service account, the service account must also be able to read back what it
  wrote. Probably fine (it is doing the writing, and `PUBLISH` is checked
  against the original zones) but it is exactly the kind of thing that works
  in the owner's session and fails in the worker.
- **`ProjectClassification`** — "the expectation of how the results will be
  used" — may be a better home for the public/private *intent* than inferring
  it from the project-type classification. Worth a look before Phase 5
  hardcodes the mapping "PersonalProject/Experiment ⇒ private".
- **Should `Experiment` be private by default?** The proposal groups it with
  `PersonalProject`. Egeria's definition ("testing a hypothesis") is about
  method, not confidentiality — a team experiment is a normal thing. Suggest
  private *by default*, changeable at creation, rather than private *by
  classification*.
- **Deployment config ownership.** Phase 5 needs a line in
  `egeria-workspaces-fs`'s `.omsecrets`. That is a different repo with a
  different change policy; confirm who lands it and whether it belongs in the
  freshstart config, the quickstart config, or both.

---

## 8. Observation for `egeria-workspaces-fs` (not changed here)

In `compose-configs/egeria-freshstart/secrets/egeria-user-directory.omsecrets`,
the `digital-products` zone's `READ:` and `DEFAULT:` keys sit at the same
indent as `otherProperties` rather than nested under an
`associatedSecurityList:` key, as they correctly are for `egeria-runtime` and
`security` immediately above and below it. As written, that zone has no
`associatedSecurityList` at all, so `getAssociatedSecurityListForZone` returns
null and the zone is **ignored** — unsecured. Its own `description` says
"This is an unsecured governance zone", so the outcome may well be intended;
but the presence of the two keys suggests someone meant them to bind, and the
config reads as if they do. Flagged rather than changed, since the correct
resolution depends on which of the two was meant.
