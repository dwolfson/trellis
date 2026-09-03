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
print(f"{'repo':<26} {'prod':>6} {'enq':>6} {'done':>6} {'guids':>6} {'names':>6}  verdict")
for rec in done:
    if not rec.get("ok"):
        print(f"{rec['slug']:<26} {'':>9} {'':>9} {'':>7} {'':>7}  PUBLISH FAILED: {rec.get('error','')[:40]}")
        bad.append((rec["slug"], "publish failed")); continue
    slug, produced = rec["slug"], rec.get("annotations", 0)
    with r._conn() as c:
        q = ("FROM egeria_outbox WHERE entity_slug=? AND element_kind='annotation' "
             "AND qualified_name !~ '::[0-9]+$'")
        enq = c.execute(f"SELECT COUNT(*) n {q}", (slug,)).fetchone()["n"]
        dn  = c.execute(f"SELECT COUNT(*) n {q} AND status='done'", (slug,)).fetchone()["n"]
        fl  = c.execute(f"SELECT COUNT(*) n {q} AND status IN ('failed','dead')", (slug,)).fetchone()["n"]
        pd  = c.execute(f"SELECT COUNT(*) n {q} AND status='pending'", (slug,)).fetchone()["n"]
        gu  = c.execute(f"SELECT COUNT(DISTINCT egeria_guid) n {q} AND status='done'", (slug,)).fetchone()["n"]
        nm  = c.execute(f"SELECT COUNT(DISTINCT qualified_name) n {q}", (slug,)).fetchone()["n"]
    v = []
    if enq != produced: v.append(f"SKIPPED {produced-enq}")
    # A collision is done-rows sharing a GUID. Comparing GUIDs against ENQUEUED
    # rows instead reports every failed or pending row as a collision — which is
    # what this script did on its first run, calling 56 timeouts and a 401
    # "COLLIDED 57". The number was right and its name was wrong: the exact
    # defect the three-way check exists to catch, reproduced in the checker.
    if gu != dn:        v.append(f"COLLIDED {dn-gu}")
    if fl:              v.append(f"FAILED {fl}")
    if pd:              v.append(f"PENDING {pd}")
    verdict = "ok" if not v else " + ".join(v)
    if v: bad.append((slug, verdict))
    print(f"{slug:<26} {produced:>6} {enq:>6} {dn:>6} {gu:>6} {nm:>6}  {verdict}")
print(f"\n{len(done)} repos checked, {len(bad)} with a discrepancy")
for s, w in bad: print(f"   {s}: {w}")
