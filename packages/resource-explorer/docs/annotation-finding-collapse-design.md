# Collapsing findings and annotations onto one record

**Design, 2026-09-02.** Prompted by Dan pushing back on an earlier claim of
mine that findings and annotations were two irreducibly different things. He
was right and I was wrong; this records what measuring showed and what follows
from it.

## The pushback, and what it turned out to be worth

> **(a)** "It may be less convenient but it looks to me that an annotation has
> enough information for historic analysis — it has a timestamp, measures and
> values — they are just in the JSONProperties?"
>
> **(b)** "An annotation has a qualified name … there is nothing to say that
> this qualified name can't also include linkages back to RE if needed … it
> could also include other information — that's our choice on how to construct
> the qualified name."
>
> **(c)** "check_name could be in additional properties or in the
> qualified-name, same with label and other things."

**(a) is correct.** Verified against `docling`'s publish to the clean catalog:
`ResourceMeasureAnnotationProperties` carries `resourceProperties`;
`DataClassAnnotationProperties` carries a full `jsonProperties` payload
(dependency names, versions, types). The run timestamp is in the qualifiedName.
The *data* needed for trends is already published.

**(b) and (c) are correct, and they dissolve the argument I was making.** I had
framed annotation-vs-finding as a difference in identity model — annotations
positional, findings keyed by `check_name` — as though that were inherent. It
is not. We construct the qualifiedName.

## What is actually broken

The current scheme is `Annotation::{slug}::{surveyed_at}::{i}`, where `i` is
the **enumeration index within the run**. Positions are not stable across runs.

Measured on `egeria_git`'s two largest published runs, 115 overlapping
indices:

    same finding at the same index:  0 / 115   (0%)

    [0] 'Ruleset gitleaks rules last changed…'  vs  '★ 921 · 265 fork(s) · 63 contributor(s)'
    [1] '1172 secret-shaped match(es) found…'   vs  '6327 file(s) inventoried'
    [2] 'Possible secret: Detected a Generic…'  vs  '72 dependency(s) parsed from 1 manifest'

Not "sometimes drifts" — **zero stability**. A scoped run and a full run share
no meaning at any index. So today you cannot follow one check through time by
qualifiedName, even though every value you would want to trend is present in
the annotation.

**That is the whole defect.** Not a missing store; a chosen identity that
cannot be followed.

## Is `check_name` a usable identity?

Mostly, and the exception is well-defined. Over 27,710
`(slug, kind, run, check_name)` groups in `project_analysis_findings`:

    unique:      23,532   (84.9%)
    colliding:    4,178   (15.1%)

The collisions are entirely **list-shaped** analyses — one finding per item
rather than one per check:

    architecture_interfaces  2,384      cve_scan                154
    architecture_recovery    1,254      architecture_blueprints 101
    architecture_doc_lens      160      architecture_diagram     82
    documentation               37      secret_scan_findings      6

`scope_locator` does not discriminate them. What does is item-specific and
lives inside `detail_json` — a secret finding carries `path`, `line`,
`rule_id`; a doc-lens finding carries its term.

So there are two finding shapes, and the design has to name them:

- **verdict-shaped** — one finding per check. `check_name` is the identity.
  `security_policy`, `automated_build`, `catalog_info`.
- **list-shaped** — many findings per check. Needs an
  **analysis-supplied item key**, because only the surveyor knows what
  identifies its item (`path:line`, a term, a package name). Nothing universal
  exists and inventing one by hashing `detail_json` would produce an identity
  that changes when an unrelated field does.

## Proposal

**One record per observation, carrying the union.** Concretely:

1. **`Annotation` gains `check_name` and `label`.** These are the two fields
   findings have and annotations lack, and they are what makes an observation
   followable and comparable.
2. **List-shaped emitters supply `item_key`.** Explicit, per surveyor, because
   only they know it. Absent `item_key` on a colliding check is a bug the
   guard should catch, not a silent fallback to positional.
3. **QualifiedName becomes**
   `Annotation::{slug}::{surveyed_at}::{check_name}[::{item_key}]`.
   Stable across runs, so a trend query is a prefix match with the timestamp
   varying.
4. **`project_analysis_findings` keeps its role as RE's own store**, but stops
   being a *separate hand-written record*: surveyors emit annotations, and the
   finding row is **derived** from the annotation rather than typed again
   beside it.

Point 4 is the one that fixes the real bug. Today 20 surveyors write both by
hand, and they have drifted — `security_hygiene`'s SECURITY.md check emits
`confidence=90` on the annotation and stores a finding with no confidence,
which defaults to **100**. Same check, same run, two different numbers in two
stores. The `explanation` is on the annotation and absent from the finding.
No comment anywhere describes the divergence as intentional; it is duplication
drift, not design.

## Migration: do it now, because it is nearly free

**This is the cheapest moment this change will ever have.** Measured:

    elements published to the CURRENT Egeria :    137   (docling only)
    outbox rows pointing at the WIPED Egeria : 13,742   (dead GUIDs)
    repos still holding a stale asset GUID   :     59 of 60

The catalog was wiped this morning and only `docling` has been republished. A
qualifiedName change costs **one republish now, versus sixty later** — and the
59 have to be republished regardless, since their cached GUIDs are dead.

On RE's own historical finding rows — 227,162 at 2026-09-02T16:00, and
growing with every survey, which is itself the point: any figure here is a
snapshot, not a constant — they have no `annotation_type`,
so they cannot be turned into annotations retroactively. **Leave them.** They
already serve RE's own trend charts, which read `check_name` and `surveyed_at`
and do not care about annotation shape. Backfilling a type onto them would be
inventing data. This is a development environment: the rows either earn their
keep as they are, or they are thrown away — they should not be migrated on
principle.

## What this does NOT settle

- **Whether to publish RE's history into Egeria at all.** That remains the
  open choice in `survey-history-and-egeria-replay.md`. This design makes
  replay *possible* by giving annotations a followable identity; it does not
  argue for doing it.
- **The `CodeAnalysisAnnotation` question** — RE publishes code findings under
  generic types while Egeria defines specific ones
  (`docs/fs-db-design-inputs.md`). Orthogonal, and worth settling in the same
  pass since both change what a surveyor emits.
- **Whether derived stores sit downstream of the annotations.** Dan's point,
  and it changes the disposal question rather than the design: *"as long as we
  preserve the original data we can always do more with it later."* Annotations
  are the record; flattening selected ones — from selected resources — into a
  local operational data store for trend charts or cross-repo comparison is a
  post-processing step, not a competing store. That is an argument for
  preserving annotation fidelity above all, and it removes the pressure to
  decide the shape of every downstream view now.
- **Whether `project_analysis_findings` survives long-term.** If annotations
  carry everything and are queryable in Egeria, the local table is a cache and
  a trend index rather than a source of truth. Not decided here; the proposal
  keeps it.

## Sequence

1. Settle the qualifiedName scheme, including `item_key`, before republishing
   the other 59 repos. Everything else can follow at leisure; this cannot.
2. Add `check_name`/`label` to `Annotation`, and a guard that a colliding
   check without an `item_key` fails loudly.
3. Derive the finding row from the annotation in one surveyor, prove the
   drift is gone, then do the remaining 19.
4. Republish the corpus under the new scheme.

**Steps 1–3 are done** (2026-09-02, `re/annotation-finding-derivation`).
`security_hygiene` was the surveyor, and the drift it exposed is worth
recording because it was invisible from either side: all 162 stored
`security_policy` gap rows in the live registry say `confidence=100`, while
the annotations Egeria received for those same runs said 90. Neither store
was internally inconsistent; only comparing them showed it. A fresh run on
`workshops` (real gaps in all three checks) now stores 90/85/90, matching its
annotations exactly.

19 surveyors remain. Nothing changes on publish for them until they set
`check_name` — an annotation without one still falls back to the positional
name, deliberately, so the migration can proceed one surveyor at a time
rather than as a flag day.
