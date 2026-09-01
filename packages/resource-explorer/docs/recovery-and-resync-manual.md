# Recovery and resync: which flavour, and what actually proves it worked

**Status:** written 2026-08-31/09-01, from the recovery it describes rather than from
theory. Every number below was measured during that recovery, and every trap named is one
that cost time on the night.

This is the **routing document**. It does not repeat the procedures in
[`egeria-reset-recovery.md`](egeria-reset-recovery.md) or
[`egeria-publishing-a-changed-definition.md`](egeria-publishing-a-changed-definition.md) —
it tells you which of them you are in, what the Alignment panel now does for you
automatically, and — the part that has repeatedly been got wrong — **what counts as
evidence that a recovery succeeded.**

---

## 0. The one thing to read if you read nothing else

**Not one of the five bugs found during the 2026-08-31 recovery raised an error.**

A successful promotion showed a red toast. A scan reported zero while 36 items needed
repair. A card never rendered. A claim outlived the report it named. A count could not
decrease no matter how much work was completed.

Every one of them looked exactly like *nothing to do here*. So the governing rule of this
document is:

> **A zero is a claim, not a result.** Before believing a recovery is complete, confirm
> the thing you want is PRESENT. Do not accept that the thing you feared is ABSENT.

Concretely: after relinking, do not check that "unlinked members = 0". Ask Egeria for the
collection's member list and count what is in it. Those two questions came apart on the
night — the scan said 0 because it could not see the members at all.

---

## 1. Which flavour are you in?

The flavours are distinguished by **what was lost**, not by what you did.

| # | Flavour | Symptom | What was lost | Go to |
|---|---|---|---|---|
| 1 | **Platform reset / redeploy** | Everything in Egeria is gone; RE looks fine | All Egeria elements. **Nothing of RE's.** | §2 |
| 2 | **Changed definition** | A survey gained/lost a step | Nothing — this is a deliberate edit | [publishing-a-changed-definition](egeria-publishing-a-changed-definition.md) |
| 3 | **Drift without a reset** | "I published it but cannot find it" | One asset, or one link | §3 |
| 4 | **Half-finished recovery** | Some repos catalogued, some not | Nothing new — but see §4, this flavour has its own trap | §4 |
| 5 | **RE registry lost** | RE is empty; Egeria is fine | RE's own tables | §5 |

**Flavour 1 is the common one and the one most often mis-diagnosed.** A wipe destroys
Egeria and leaves RE's registry untouched *by design* — that is the premise
`egeria_resync.py` is built on. Which leads directly to:

### 1a. How to tell whether a wipe has actually happened

On the night, a session answered "has Egeria been wiped?" by counting rows in RE's
`projects` and `project_analysis_findings` tables, found 60 and 68,215, and concluded it
had not. Those tables read **identically on both sides of a wipe**, so the measurement
could not distinguish the two states at all. A correct count of the wrong population.

Ask something that only exists on one side of the event:

```bash
uv run python -c "
from resource_explorer.registry import ProjectRegistry
with ProjectRegistry()._conn() as c:
    print('assets  :', c.execute(\"SELECT count(*) FROM projects WHERE coalesce(egeria_asset_guid,'')<>''\").fetchone()[0])
    print('reports :', c.execute('SELECT count(*) FROM project_egeria_surveys').fetchone()[0])"
```

Both zero, on a corpus that was previously published, means the assets are gone and the
sweep has already cleared the pointers. Both non-zero means you are not in flavour 1.

---

## 2. Flavour 1 — platform reset

### 2.1 Let bootstrap heal. Do not hand-run Dr.Egeria documents.

`bootstrap.check_and_heal()` re-runs any batch whose canary is missing, every 10 minutes
while the web server is up, then runs the post-heal reconciler. On a wiped platform every
canary is missing, so it heals unattended.

**Two people intervening on top of that is the worst available outcome.** Dr.Egeria's link
commands do not dedupe — one deliberate publish on 2026-08-31 produced 40 duplicate edges
across two definitions. There is a reconciler for those. For the questions batch's 168
perspective links **there is none**, so duplicates there have no cleanup path at all.

If a fix is needed, **one person drives and everyone else stays off Egeria entirely.**

### 2.2 Verify the heal — the canary is not the verification

**A canary proves a batch RAN, not that every element in it exists.** That is exactly how
8 of 49 catalog questions sat missing for weeks while the batch reported healthy.

Four checks, and all four must pass:

```
questions              49/49 resolve
RepoAssessmentSurvey   10 steps · reducer present · runs after all 8 inputs
RepoFullSurvey         35 steps · reducer present · runs after all 8 inputs
reconciler --dry-run   0 duplicate / 0 stale across all EIGHT definitions
```

Check **"runs after all its inputs"**, not "runs last". They are different requirements and
only the second is real: `repo_security_summary` is terminal in Assessment but *not* in
Full, where `repo_rag_ingestion` must stay last. "Last" passed under two different wrong
arrangements on 2026-08-31.

Perspectives are **not** covered by any of the above and must be checked separately:

```bash
uv run python scripts/verify_perspectives.py   # 0 all present · 1 missing · 2 undetermined
```

> Its first live run produced **three false OKs**, because it fell back to `displayName`,
> which is not unique across types — `Community`, `Privacy` and `Steward` resolved to
> unrelated elements. It reported 9 of 12 missing when the answer was 12. It is
> qualifiedName-only now. The lesson generalises: **run a new check against a known state
> before trusting it**, because a check that has never been seen to fail is a check nobody
> knows works.

### 2.3 Then use Admin → 🔄 Egeria Alignment for everything else

This is the part no older runbook describes. **Scanning never writes.** Repairs run only
for steps you tick, always in dependency order regardless of tick order.

`REPAIR_STEPS` — the order is load-bearing:

| # | Step | What it does | Cost |
|---|---|---|---|
| 1 | `reauthor_survey_definitions` | Re-runs the definitions batch + reconciler | slow, writes |
| 2 | `clear_stale_assets` | Drops asset GUIDs that no longer resolve | local only |
| 3 | `clear_orphan_publish_claims` | Drops claims naming reports that are gone | local only |
| 4 | `clear_stale_investigations` | Clears dead Project/Collection GUIDs | local only |
| 5 | `clear_stale_contexts` | Resets contexts pointing at dead Projects | local only |
| 6 | `catalog_assets` | Publishes `repo_health` → registers the asset | **no downloads** |
| 7 | `republish_survey_results` | Full survey → SurveyReport | **slow, downloads archives** |
| 8 | `relink_investigation_members` | Attaches members to their assets | fast, writes |

**Why the order matters, stated as failures rather than rules:**

- Publishing before clearing reuses a dead GUID.
- Relinking before cataloguing can do nothing — a member with no asset behind it cannot be
  attached. *This is why a promotion on a freshly rebuilt platform reports every member
  unlinkable, and it is not a fault.*
- Clearing orphan claims used to be outrun by cataloguing (see §4).

### 2.4 It is a TWO-PASS operation, and the first pass looks wrong

Expect this, because it was mistaken for failure twice on the night:

**Pass 1** — tick `catalog_assets`. Its card then goes to **0 and disappears**, and a
*different* card (`registration_only`) appears in its place with a similar count. On
2026-08-31 that read as "28 → 23, so 5 failed". Nothing had failed; all 28 succeeded.

**Pass 2** — click **Re-scan**. Only now can these appear, because they depend on the
assets existing:

- `orphan_publish_claims` — tick it
- `unlinked_members` — tick it; this is the one that ends the "0 linked" state
- `registration_only` — the slow full publish, unticked by default

**The counts line separates the two kinds:** *"0 repairable · 28 slow, not selected"*. The
second number does not go down when you complete work — it is work you declined, and it
persists across every re-scan by design.

---

## 3. Flavour 3 — drift without a reset

Run the Alignment scan. It reports drift in both directions, and splits it into what has
**one correct repair** (a button) and what **needs a person** (no button, marked *your
call*). The second category is deliberate: RE does not know which Egeria Project an
unbound resource should join, and a guess written into the catalog reads exactly like a
decision.

For the single-asset case, see
[`egeria-reset-recovery.md` §3](egeria-reset-recovery.md) — unchanged and still correct.

---

## 4. Flavour 4 — the half-finished recovery, and why it has its own section

**A partially-completed recovery can put work permanently out of reach of the repair that
was meant to do it.** This is the least obvious flavour and produced the worst bug of the
night.

`clear_orphan_publish_claims` originally keyed on *"the project has no asset"*. So the
moment `catalog_assets` gave a repo its asset back, that repo's pre-wipe claims became
invisible to both the repair and the scan that surfaces it. The claims survived
**precisely because the situation had been half-repaired** — running the repairs in the
order the panel offers them meant the cataloguing step outran the clearing step.

Measured: the scan reported **0** while **36 orphaned claims across 12 repos** existed.

Both are now keyed on the claim itself — a claim whose `egeria_report_guid` is absent from
`project_egeria_surveys` names a report nothing stands behind, whether or not the project
currently has an asset. It can no longer be outrun.

**The general lesson for anyone writing a repair:** key it on the damage, not on a
correlate of the damage that another repair is going to change.

---

## 5. Flavour 5 — RE's registry lost

Not covered here, and deliberately so: nothing in this document restores RE's own tables.
RE's registry is the system of record for survey results — Egeria holds what was
*published*, which is a subset. Restore it from your Postgres backup. Re-surveying is not
equivalent: it re-derives current state, and loses the history that
`project_analysis_findings` and the `surveyed_at`-stamped tables carry.

---

## 6. What does *not* need doing

- **Re-surveying before publishing.** Publish runs `SurveyOrchestrator.run(slug)` itself,
  so a survey first just does the work twice.
- **Re-promoting an investigation that already has a Project GUID.** Dr.Egeria batches are
  not idempotent, and perspective links have no reconciler.
- **Anything to RE's local data after an Egeria wipe.** It is intact. Check before acting.

---

## 7. Traps, each of which cost time

- **`node --check` with the wrong Node.** nvm can move `node` under you; v14 cannot parse
  `||=` and reports valid code as a syntax error. Verify with a runtime matching browsers.
- **Start the app WITHOUT `--reload`.** `SourceCache` uses the relative path
  `data/source-cache`, so zipballs extract inside the tree uvicorn watches. Every large
  survey restarts the server and kills itself **silently** — no error, just zero rows. A
  `manifest_parse` ran ten minutes and wrote nothing before this was found.
- **A stale panel is not stale code.** The Alignment panel caches its scan in the page. On
  2026-08-31 a fix was correctly loaded and running while the browser showed the old
  numbers. Use the panel's **Re-scan** button, not just a browser refresh. To settle it,
  ask the server: `curl -s localhost:8810/api/egeria/resync/scan`.
- **`git add <path>` is per-file, not per-hunk.** An uncommitted edit to a file another
  session is also touching gets swept into their commit.
- **An empty result is not an unknown result.** pyegeria returns the *string*
  `"No members found"` for an empty collection. Treating that as malformed sent all three
  investigations to `undetermined`, so the relink card never rendered — in exactly the
  state the repair exists for.

---

## Related

- [`egeria-reset-recovery.md`](egeria-reset-recovery.md) — the step-by-step for flavour 1
- [`egeria-publishing-a-changed-definition.md`](egeria-publishing-a-changed-definition.md) — flavour 2
- [`open-stack-checklist.md`](open-stack-checklist.md) §7 — redeploy order and live checks
- [`outbox-publishing-design.md`](outbox-publishing-design.md) — **the outbox restores nothing**; see reset-recovery §3a
