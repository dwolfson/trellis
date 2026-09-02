"""Three anchors, because each catches what the others structurally cannot.

  produced  vs enqueued  -> a silent skip (never enqueued at all)
  enqueued  vs distinct GUIDs -> a qualifiedName collision
  distinct names              -> catches NOTHING, by construction: a collision
                                 is what merges two names into one, so this
                                 number agrees with itself either way.

The middle check is the one people reach for and the first is the one they
forget: both of its inputs are downstream of enqueue, so anything that never
reached the outbox is absent from both sides and 123 == 123 reads as clean.
`produced` comes from the SurveyResult itself, upstream of the outbox.
"""
import json, pathlib, sys
from resource_explorer.registry import ProjectRegistry

done = [json.loads(l) for l in pathlib.Path("/tmp/re_newscheme.done").read_text().split("\n") if l.strip()]
r = ProjectRegistry()
bad = []
print(f"{'repo':<26} {'produced':>9} {'enqueued':>9} {'guids':>7} {'names':>7}  verdict")
for rec in done:
    if not rec.get("ok"):
        print(f"{rec['slug']:<26} {'':>9} {'':>9} {'':>7} {'':>7}  PUBLISH FAILED: {rec.get('error','')[:40]}")
        bad.append((rec["slug"], "publish failed")); continue
    slug, produced = rec["slug"], rec.get("annotations", 0)
    with r._conn() as c:
        q = ("FROM egeria_outbox WHERE entity_slug=? AND element_kind='annotation' "
             "AND qualified_name !~ '::[0-9]+$'")
        enq = c.execute(f"SELECT COUNT(*) n {q}", (slug,)).fetchone()["n"]
        gu  = c.execute(f"SELECT COUNT(DISTINCT egeria_guid) n {q} AND status='done'", (slug,)).fetchone()["n"]
        nm  = c.execute(f"SELECT COUNT(DISTINCT qualified_name) n {q}", (slug,)).fetchone()["n"]
    v = []
    if enq != produced: v.append(f"SKIPPED {produced-enq}")
    if gu != enq:       v.append(f"COLLIDED {enq-gu}")
    verdict = "ok" if not v else " + ".join(v)
    if v: bad.append((slug, verdict))
    print(f"{slug:<26} {produced:>9} {enq:>9} {gu:>7} {nm:>7}  {verdict}")
print(f"\n{len(done)} repos checked, {len(bad)} with a discrepancy")
for s, w in bad: print(f"   {s}: {w}")
