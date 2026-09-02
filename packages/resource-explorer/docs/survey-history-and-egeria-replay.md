# Survey history, and what happens to it when Egeria is wiped

**A design note, not a plan.** Written 2026-09-02 after an Egeria-only
redeploy, when the question "how do the annotations get synced?" turned out
to have an answer nobody had chosen.

Dan, on being told the two-tier recovery was how it worked:

> "The reason that we accumulate old survey annotations and surveys is because
> history is important. We want to understand trends not just status. Now it
> could be that we give the user a choice about re-establishing history vs
> just moving forward — and that makes sense if replaying history is expensive
> — but it is a choice not a fixed policy. And we would want to expose the
> costs and options rather than make that choice for the user."

That is the correction this note exists to record. **What RE does today is a
policy by omission**: replay was never written, so "move forward" is what
happens, and nobody decided it.

---

## Where history actually lives

Measured 2026-09-02, after the wipe:

| store | rows | distinct runs | span | survived the wipe? |
|---|---|---|---|---|
| `project_analysis_findings` | 226,847 | 1,452 | 2026-08-08 → | **yes** |
| `project_analysis_metrics` | 100,260 | 1,754 | 2026-08-08 → | **yes** |
| `project_file_type_counts` | 5,386 | 286 | 2026-08-07 → | **yes** |
| `egeria_outbox` | 13,742 | — | 2026-09-01 only | yes, but see below |
| Egeria `SurveyReport` + `Annotation` | — | — | — | **no** |

Two things to take from that table.

**RE's own history is intact, and it is ~26 days deep.** 60 repos have
findings history; runs per repo range 8 to 83, median 16. The trend charts
read these tables, so RE's trends were untouched by the wipe. What was lost is
Egeria's *copy* — and therefore the visibility of that history to anything
that is not RE.

**The outbox is not the history store.** It is a publish queue with 14-day
retention (`purge_outbox_completed`), and it currently holds one day. It does
retain complete annotation bodies — `qualifiedName`, `annotationType`,
`summary`, `analysisStep`, `confidence`, `jsonProperties`, `qualityScores` —
which makes it *look* like a replay source. It is a poor one: it covers a
fraction of the history, and every payload's `parentGUID` points at a
`SurveyReport` that no longer exists.

---

## Why nothing replays today

Annotations only ever exist as the output of a live survey run.
`build_annotation_body()` takes `Annotation` objects from a `SurveyResult`;
the stored findings in `project_analysis_findings` are a different shape.
`egeria_resync._publish_one`'s own docstring is *"Survey then publish"* — even
the repair tooling re-surveys.

The qualifiedName embeds the run's timestamp, and each annotation hangs off a
`SurveyReport` by a `ReportedAnnotation` relationship. So the model treats a
publish as *"here is what I measured just now"*.

**That is a defensible position, and it is not the only one.** A survey report
is a point-in-time record; replaying old findings under a report created today
would misrepresent when they were observed — *unless* the synthesised report
carries the original `surveyed_at`, which it can.

---

## The three options, with what is measurable

| | restores in Egeria | cost | what it costs you |
|---|---|---|---|
| **Move forward** | nothing historical | none | Egeria loses 26 days of trend. RE keeps it, so RE's charts still work and the catalog's do not. |
| **Re-survey** (built) | today's findings, one point per repo | full survey × 60 repos; `repo_secret_scan` alone measured 277s, so minutes each | Still no history. Findings may legitimately differ from what was there — several analyses changed on 2026-09-01/02, so this is not a restoration. |
| **Replay history** (not built) | up to 1,452 runs across 60 repos | not built; see below | Restores the trend. Needs a decision about what timestamp a replayed report carries. |

There is also a **cheap registration tier** already built and worth knowing
about independently: `catalog_assets` publishes `repo_health` only
(`fetch_cost=none`, no zipball download), so a corpus can be re-catalogued in
seconds with every asset present. `REGISTRATION_ONLY_ANALYSES` then identifies
exactly which repos have an asset but no real survey report, so the state is
detectable rather than ambiguous.

---

## What replay would require

Not a design, but the shape is clear enough to size:

1. **A `SurveyReport` per historical run**, carrying that run's original
   `surveyed_at` rather than now. Without this the replay is a lie about when
   things were observed, and the trend it restores would be flat at today's
   date.
2. **Annotation bodies rebuilt from stored findings**, not from the outbox.
   `project_analysis_findings` is the real source: 1,452 runs versus the
   outbox's one day. This means a translation from the stored
   `{check_name, label, summary, confidence, detail_json}` shape back to
   annotation bodies — which is the inverse of what surveyors do today, and
   does not exist.
3. **A decision about lossy runs.** Findings are stored per analysis kind; not
   every annotation a surveyor emitted is recoverable from them (a
   `ResourceMeasureAnnotation` carrying `resource_properties` may have more in
   it than the finding row kept). A replay would restore *some* of each run,
   and should say so rather than implying fidelity.
4. **Volume awareness.** 226,847 finding rows is far more than the 2,000-per-run
   enqueue cap contemplates. A replay is a bulk operation and needs the cap,
   the cancel path, and a preview — all of which now exist.

**Point 3 is the one that would bite.** A replayed history that silently
contains less than the original is the failure mode this codebase keeps
paying for: a record that looks complete and is not.

---

## What should be exposed, if this is built

Per Dan's framing — a choice, with costs, not a policy:

- **What history exists**, per repo: runs, span, and finding counts. All
  available from `project_analysis_findings` today.
- **What each option costs**, in the units a person cares about: minutes for a
  re-survey, element counts for a replay.
- **What each option restores**, honestly. "Re-survey" restores *current*
  state, not history, and calling it a restore would be wrong.
- **What a replay cannot recover**, per point 3.
- **Resumability.** A 1,452-run replay will be interrupted. It should be
  restartable without duplicating, which the outbox's qualifiedName
  convergence already supports.

## Not decided here

Whether to build replay at all. The note exists so the choice is visible and
costed; today's behaviour is "move forward, then re-survey", and it should be
that because someone chose it.
