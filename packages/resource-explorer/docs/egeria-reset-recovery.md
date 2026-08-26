# Recovering RE after Egeria's database is reset

**Status:** written 2026-08-21, from an actual reset rather than from theory. Every
step below was run against a real recovery; where something is untested it says so.

Resetting Egeria's repository is routine in a development deployment — a quickstart
platform restart alone loses custom-authored elements. RE keeps its own registry, so
nothing of yours is lost, but two kinds of link into Egeria break, and they recover in
very different ways.

| what breaks | recovers how |
|---|---|
| Glossaries, funnel stages, perspectives, questions, Survey Definitions | **automatically**, via the bootstrap self-heal |
| Cached `egeria_asset_guid` on every registered resource | **only when you decide** what to do with each one |

The distinction matters: the first is content RE authors and can always re-author. The
second is a *pairing* between two systems, and RE cannot know whether you want the
Egeria side rebuilt from local data, re-derived from scratch, or abandoned. That is why
nothing happens to it on its own.

---

## 1. Let the bootstrap heal the definitions, then verify it

`resource_explorer/bootstrap.py` checks each Dr.Egeria batch for a *canary* element and
re-runs the batch when the canary is missing. It runs on a timer (10 minutes) whenever
the web server is up, so by the time you notice a reset it has usually already run.

Check what it did:

```bash
curl -s http://localhost:8810/api/bootstrap/status | python3 -m json.tool
```

Each batch reports `present`, `last_checked_at`, `last_healed_at` and
`last_heal_result`. To force a pass rather than wait: `POST /api/bootstrap/run`.

**Do not stop there.** A heal can succeed and still leave a definition wrong — this
happened on the recovery this document is written from. Verify with the live smoke tier,
which compares every authored definition against the CSV that generates it:

```bash
uv run pytest tests/test_egeria_live_smoke.py -q
```

That is the fastest accurate answer to "did the catalog come back correctly". On the
2026-08-21 recovery it reported, in one line:

```
'RepoFullSurvey' in Egeria does not match the CSV —
missing ['repo_sub_resource_survey', 'repo_rag_ingestion']
```

### If a definition does not match

Regenerate, re-author, reconcile — in that order, all three:

```bash
uv run python scripts/generate_repo_survey_definition.py
cd docs/dr-egeria/survey-definitions
uv run dr_egeria --process --summary-only repo-survey-definition-full.md
cd -
uv run python scripts/reconcile_survey_definition_links.py
```

The reconciler is **not optional**. `Link First/Next Process Step` is not idempotent:
re-running a document creates a second edge per step, the reader correctly refuses to
guess which chain is intended, and the whole definition drops out of service. The
reconciler strips those duplicates.

> **Regenerate before authoring — do not just re-run the existing document.**
> The reconciler derives the expected chain from `STEP_REGISTRY` order, so an edge that
> skips a registry step reads as *stale* and is removed, truncating the definition.
> A step present in `STEP_REGISTRY` but absent from the authored Full Survey therefore
> gets cut on every reconciler run. Observed twice on 2026-08-21: 22 steps to 20, and on
> an earlier occasion 22 to 7. A step may be absent from a *stage* survey; it may not be
> absent from Full Survey.

---

## 2. Deal with the stale asset GUIDs

After a reset, every `egeria_asset_guid` RE holds points at nothing. On the recovery
this was written from that was 19 repos and 1 database.

**Detection is reactive by default.** A divergence is recorded when something next tries
to use that GUID — so immediately after a wholesale reset, `Admin ▸ 🔗 Egeria Links`
shows an empty list while every cataloged resource is broken. That is correct behaviour
for the one-off case it was designed for and useless for a reset, which is why the sweep
in the next section exists.

### Make the state accurate first

```bash
uv run resource-explorer egeria-recheck --dry-run     # look before writing
uv run resource-explorer egeria-recheck               # record what it finds
```

The sweep probes every cached GUID, records the ones that no longer resolve, and
**clears** rows for any that do — so it can be re-run safely and shrinks as you fix
things, rather than only ever accumulating. Output from the 2026-08-21 recovery:

```
checked: 20   ok: 0   stale: 20   errors: 0   skipped (no cached GUID): 40
```

`skipped` is resources with no cached GUID at all — never published, so nothing to
check. They are counted separately rather than as `ok`, because "nothing to verify" and
"verified fine" are different answers.

A failure that is *not* an unknown-GUID error — connection refused, auth — is counted
under `errors` and **does not** mark anything stale. Marking a healthy entity stale is
the more damaging mistake: it sends you to reconcile a catalog that was fine.

The sweep raises **one** summary RFA, not one per resource. A reset makes every
cataloged resource stale simultaneously, and twenty near-identical drawer items
describing a single event would bury whatever else is in there.

There is also `POST /api/egeria/linkage/recheck` for the same sweep from the UI or a
script.

### Choosing a resolution

Every option clears the unusable GUID; they differ in what runs afterwards.

| option | when it is right |
|---|---|
| **Republish** | Only Egeria was reset and the resource itself has not changed. Re-publishes what RE already holds — fast, no re-scan. **This is almost always the right answer after a reset.** |
| **Re-survey** | The resource may also have changed, or the local data is old enough to doubt. Full survey, then publish. Minutes per resource. |
| **Discard** | Clear the broken link and stop. Survey results and annotations are kept; past publishes remain in the activity log. |

Available from `Admin ▸ 🔗 Egeria Links` for every divergence at once, or from an
affected repo's own Scouting card. Both call
`POST /api/egeria/linkage/{entity_type}/{slug}/resolve`.

`resource-explorer egeria-reset <slug>` is the older, per-resource equivalent of
*discard*: it clears the cached GUID and that resource's published-survey records. It
predates the linkage work and is not divergence-aware — it will happily clear a link
that was perfectly healthy.

---

## 3. "I published it but I cannot find it in Egeria"

Almost always this, and it is not a failure: **a repo is not published as an Asset.**
Confirmed from the server 2026-08-21:

```
typeName   : SourceControlLibrary
superTypes : ResourceManager, SoftwareCapability, Referenceable, OpenMetadataRoot
description: Defines a software source code library that provides version control.
```

`SourceControlLibrary` is a **SoftwareCapability**, not an Asset, so it will not appear
in an Asset Catalog view or an asset search however hard you look. Search by its
qualified name instead — `SourceControlLibrary::<github url>` — or browse software
capabilities / resource managers.

To check one directly:

```bash
uv run python -c "
from resource_explorer.config import get_config
from resource_explorer.registry import ProjectRegistry
from pyegeria.omvs.metadata_expert import MetadataExpert
cfg = get_config().egeria
g = ProjectRegistry().get('SLUG').egeria_asset_guid
me = MetadataExpert(cfg.view_server, cfg.platform_url, cfg.user_id, cfg.user_password)
me.create_egeria_bearer_token()
print(me.get_metadata_element_by_guid(g)['type']['typeName'])"
```

> **The naming in RE lies about this, and it has already caused one bug.** The registry
> column is `egeria_asset_guid`, the publisher method is `_find_or_create_asset`, and
> `egeria_publisher.py`'s own docstring says "Asset type: SourceControlLibrary". None of
> them is about an Asset. The first version of `egeria-recheck` used
> `AssetMaker.get_asset_by_guid` as its existence probe — which correctly returns
> NotFound for a SoftwareCapability — and would therefore have reported every healthy
> repo as stale immediately after being republished. Use
> `MetadataExpert.get_metadata_element_by_guid`, which is type-agnostic.

Whether repos *should* be Assets is a real modelling question rather than a bug —
`SourceControlLibrary` is a defensible type for "a version-controlled library" — but it
is a decision to take deliberately, not one to make because a particular UI view is
empty.

---

## 4. What is *not* affected

Worth stating, because the natural fear after a reset is that everything must be redone:

- **Survey results, annotations, metrics, findings** — all in RE's own registry, untouched.
- **RAG collections in pgvector** — untouched; chat keeps working throughout.
- **Dispositions, groups, tags, curator notes, schedules, subscriptions** — untouched.
- **The activity log**, including every past publish and its report GUID. Those GUIDs now
  point into a repository that no longer has the elements, but the history of what was
  published and when survives.

The only thing genuinely lost is the Egeria-side elements themselves, and the identity
mapping to them.

---

## 5. Verifying the recovery

```bash
uv run pytest tests/test_egeria_live_smoke.py -q     # definitions match the CSV
uv run resource-explorer export-resources /tmp/after.csv
```

The export's `status_cataloged` and `status_egeria_link` columns give a one-page view of
which resources are re-linked and which are still stale — the same file being an
inventory and a scorecard. Diffing it against an export taken before the reset shows
exactly what is outstanding.

---

## Related

- `resource_explorer/bootstrap.py` — canary-gated self-heal, and why the
  survey-definitions batch is marked non-idempotent
- `resource_explorer/egeria_linkage.py` — divergence detection, and why it detects
  rather than auto-resolves
- `docs/survey-definitions.md` — the Survey Definition model and its current limitations
- `docs/Backlog.md` — the Egeria↔RE reconciliation entry, including what is still open

---

## 6. What this runbook did not cover until 2026-08-26

Three kinds of cached Egeria GUID exist, not one. The runbook above and the
sweep script both knew only about the first.

| cached in RE | what dangles after a reset |
|---|---|
| `projects.egeria_asset_guid` | the ☁ Published badge, and anything needing the asset |
| `investigations.egeria_project_guid` | the investigation renders "linked" to a Project that is gone; promoting again fails on a GUID nothing resolves |
| `working_sets.egeria_collection_guid` | each disposition's Collection |

`scripts/sweep_stale_egeria_guids.py` now checks all three, on both dry runs and
`--apply`. It also clears `project_published_annotation_types` alongside the
asset GUID: those rows are what the Analyses cards' "Published" / "Repo
published" badge is derived from, so leaving them puts a Published badge on a
repo whose catalog entry no longer exists — the same failure one table further
along.

### The sweep's staleness test was wrong

**Measured 2026-08-26 against a live, healthy catalog:** the sweep used
`get_asset_by_guid`, which raised `PyegeriaNotFoundException`/400 for GUIDs that
plainly existed. It reported **all 23 cached GUIDs stale** while
`find_asset_guid` returned those exact GUIDs for the same repos. Running
`--apply` on that verdict would have cleared every valid registration in the
catalog, with its survey records and publish history.

It now verifies the way `EgeriaPublisher._find_or_create_asset` does — search by
`qualifiedName`, check the GUID is among the results — so the sweep and the
publisher can no longer disagree about whether the same asset exists.
`tests/test_stale_guid_sweep.py` pins that.

### Perspectives now depend on the ScopedBy graph

Survey Definition perspectives are read from
`Survey --ScopedBy--> Question --> Perspective`. Until the `questions` batch and
the survey-definition `Link Element To Scope` commands have both re-run, surveys
fall back to step-derived perspectives and report `perspectives_source:
"derived"` instead of `"scoped"`. Nothing lies — the source is labelled — but a
recovery is not complete while surveys that should be `scoped` are `derived`.
`_folder_order.json` already puts `questions` before `survey-definitions` for
this reason.

### Verifying a recovery

`docs/egeria-redeploy-baseline-2026-08-26.json` captures the pre-redeploy state:
batch presence, the 12 perspectives, and all 8 Survey Definitions with their step
counts and perspective sources. Compare against it rather than against memory.
