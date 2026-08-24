# Architecture recovery — handoff, 2026-08-24

What a successor needs that is not already obvious from the code. The durable
record of *findings* is `scripts/arch-spike/README.md` (98 numbered entries);
this is the shorter list of things that were true in someone's head and needed
writing down before the session ended.

---

## 1. The corpus measurement, settled

`repo_classification` re-run across **all 60 registered repos**, 2026-08-24,
after the `doc-site-generator` gate fix (`b459cd8`). **25.5 min, 0 failures.**

```
gate    run 46 · skip 8 · none 6
roles   samples 16 · application 13 · documentation 11 · library 6
        tutorial 5 · middleware 2 · tool 1

the 8 skips
  course_material          tutorial       no structural evidence
  docling_langchain        samples        no structural evidence
  docs                     documentation  no structural evidence
  egeria_docs              documentation  no structural evidence
  monocle                  samples        no structural evidence
  opea_project_github_io   documentation  no structural evidence
  slack_archives           documentation  no structural evidence
  openlineage_site         documentation  generator-owned package manifest  <- the one that moved
```

**This supersedes the `47/7` in `Backlog.md`**, which was correct when measured
and is now stale. Exactly one repo changed and it changed for the stated
reason, which is the outcome a narrow fix should produce — the six repos with
`none` have no file inventory (never ingested), which is correct and unchanged.

The previous session deliberately left `47/7` in place rather than editing it
to a *predicted* `46/8`, on the grounds that a prediction written where a
measurement belongs is the substitution the entry exists to warn about. That
was right, and this is the re-measurement that discharges it.

## 2. Things known broken or half-done

- **`misgrouped` (`surveyors/result_status.py`) still has no emitter.** It
  exists for "right material, wrong structure" from the arch scorer. Nothing
  produces it. It should probably get one from the scoring path — an arch
  result whose components are all real but grouped wrongly is a genuinely
  different reader-state from `nothing_found` — but nobody has needed it
  enough to define the threshold, and a state with no emitter is honest as
  long as nobody assumes it is live. **Do not assume a `misgrouped` result can
  appear in the wild.**
- **Java marker components are all named `src`.** The code-marker proposer
  derives component names from path segments in a way that works for Go and
  Python layouts and collapses on Maven/Gradle `src/main/java` trees.
- **`find_artifact("readme")` prefers a nested README over the root one** in
  some layouts. Cosmetic in the expectation report, wrong in principle.
- **Go cohesion is ~0 without recursive rollup.** Subpackage edges are not
  rolled up into the parent component, so cohesion reads near zero for
  repos whose packages nest.
- **The `cmd/X` + `pkg/X` merge is unsolved.** Go repos routinely split one
  logical component across both; nothing merges them.
- **Rule 17's guard validates a step's *declaration*, not its behaviour.** A
  step can declare `fetch_cost: none` and call the network; `48fe0d3` fixed one
  instance, the guard did not catch it and still would not.

## 3. Approaches tried and rejected — do not retry these

The most expensive knowledge to lose, because nothing in the code says "we
tried this".

- **Egeria's `ResourceUse` as a disposition vocabulary — checked, genuinely
  absent.** Recorded fully as design §5.5d-i. The reasoning is the reusable
  part: reading the *descriptions* rather than the *names* showed them to be
  governance operations on metadata ("Extract metadata and add it to the open
  metadata repositories"), not judgements about a resource. Names invited
  exactly the wrong match. Egeria models the **action** (`ToDo`,
  `Certification`, `GovernanceAction`), not the **recommendation**.
- **A path-prefix rule to discount deployment artifacts under doc paths**
  (`content/`, `docs/`, `examples/`). Tempting after finding `kubernetes/website`
  runs on Dockerfiles that are documentation *content*. **Measured before
  building: of the 15 corpus repos overridden by deployment artifacts, 2 have
  all of theirs under doc paths, and both run anyway on other signals. Zero
  gate outcomes change.** A heuristic tuned on n=2 with no measured effect is
  the trap of finding 94's family. See finding 97.
- **`package-manifest` as the cause of the gate's 87% pass-through.** A
  plausible mechanism reasoned from the aggregate; the aggregate did not
  contain it. Present in 19 of 25 overrides, sole reason in 3. Dropping it
  moves 87% → 81%, not to anything defensible. See finding 97.
- **Perspective as a dispatch key.** Measured and cannot drive dispatch —
  see the investigation-framing design doc.

## 4. Claims in the repo that were wrong, and are now corrected

Listed so a successor knows the class exists and stays suspicious.

- `recovery_gate`'s docstring cited `kubernetes/website` as a repo the gate
  skips. **It runs, and always did.** Corrected in place, `b459cd8`.
- Findings 69 and 93 both said the code-marker rules covered Java. **They were
  Python-only.** Corrected in finding 94.
- Finding 86 claimed ports/wires were wired into the IR. **That was the spike
  only.** Corrected in finding 89.
- Finding 73's diagnosis of `trellis.md` was wrong — the fixture was fine and
  `score.py` never read its `Excluded` section.

Four times the *measuring instrument* was the broken part, not the detector.
That is the standing prior: when a number looks wrong, suspect the scorer.

## 5. What would have saved the most time today

- **Read the diff, not the topic.** Four attribution questions across three
  sessions; every guess from topic or ownership was wrong, every read of the
  diff or reflog was right in under a minute, and cheaper than asking.
- **Time the thing you are claiming about.** `resolve_doc_locations` (6–8s) was
  timed and reported as if it were `build_report` (57s) — out by 8×, in the
  flattering direction.
- **Check whether the name is taken before naming a module.** `disposition`
  was a live concept (`registry.repo_dispositions`, human-decided, 25 history
  rows, its own UI sub-tab). Caught two commits later; free then, not free once
  a card existed. See `github/suggested_action.py`'s opening docstring.
- **A green suite says nothing about reachability.** Finding 98: the gate fix
  was merged, pushed and live-verified while remaining unreachable from the UI.
  `tests/test_every_intent_can_run_its_analyses.py` now guards that class.
