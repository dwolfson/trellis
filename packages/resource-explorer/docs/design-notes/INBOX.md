# Designer inbox

**One writer: the designer session.** Implementers never need to edit this file
— the *answered* column is derived from the `*-IMPLEMENTED.md` you write, and
each of those already names what it replies to in its header. Two writers on one
file is how the 02:32 crossing lost an index; signal by adding your reply
document and this gets regenerated from it.

**Last reconciled:** 2026-09-17 against the implementer's report of 09-16.
`origin/main` was at `05cb63c0` (after `#104`) when the specs were written.

---

## Start here — what is ready to pick up

**One item.** Everything else on the last board had already shipped — see below,
because the reason matters more than the list.

| | take this | read | verified |
|---|---|---|---|
| **Stale publish** | *Publish state after a redeploy* — publish rows name created elements that a wipe destroyed, and nothing ever checks | `SPEC-PUBLISH-STATE-AFTER-REDEPLOY.md` | **Defect confirmed by me** at `342e0ca3`: `registry.py` ~1015/~1052/~1109 store `egeria_report_guid`; no function resolves one. Fix is one `ClassificationExplorer.get_element_by_guid` per connection. §5 is a short survey to do first. |

### In flight right now — do not take

**Verdict subject** (`RULING-WHAT-A-VERDICT-IS-ABOUT.md`) is being built as I
write this: `component_tree.py`, `repo_survey_definition_adapter.py`,
`index.html`, `next/app.js` and `test_architecture_verdict_coverage.py` are all
modified in the shared checkout. Whoever has them, has them.

*And a warning I caused:* I ran `git checkout -b re/design-verdict-ruling` in the
shared checkout, which moved the branch for everyone in that working directory —
a whole-tree operation of exactly the kind root `CLAUDE.md` rule 1 prohibits.
Nothing was lost (the branch came off `342e0ca3`, so the tree was identical, and
my commits touch only `design-notes/`), but work committed there lands on a
branch nobody chose. Switch or merge as suits you.

### Shipped, verified against `342e0ca3` — three boards' worth

Everything below was on a previous board as ready-to-start. All of it was
already done.

- **`interface_surface`'s three-rung ladder**, reading `[project.scripts]` from
  DistributionParser — `interface_surface.py:87-88`, `_cli_entry_points` at
  `:174`, and its docstring states the defect I wrote the spec about: *"a
  `[project.scripts]` entry point IS the CLI, not a hint of one."*
- **The four destinations** — `destinations.py`, with `judgement`/`task`/`context`
  declarable and **`ours` computed rather than declared**, which is better than
  what I specified: a check should not be able to nominate its own gap as
  someone else's problem.
- **The gaps collection** — `gaps.py`, dated 09-15, with `not_measurable` and
  `disagreement` as its only two shapes.
- **`proposed_by` on the component rows** — `component_tree.py:231` at HEAD.
- **`Find repos` out of `SUB_TABS`** — four entries at `app.js:179`, no `search`.
- **The caveat attribution rule** — `app.js:453` carries it as a comment, and
  `attribute(f, f.note)` at `:464` implements it.
- **The plural ports case, the tree's foot sentence, sort-by-confidence** —
  `portsWords()`, `totals_sentence()`, and the `sort === 'confidence'` branch.

### Why this kept happening, and the rule that actually fixes it

Three rounds running, this board listed shipped work as ready-to-start. Same
mechanism every time: **the state column derived from whether a
`*-IMPLEMENTED.md` existed, and reply documents lag the code.** `gaps.py` is
dated 09-15 — it was being written while I was writing the spec that asked for
it.

I wrote the convention that fixes this into this file yesterday — *a
ready-to-start row must cite the code it was checked against* — and then added
four rows with no citations. Stating a rule is not following it.

**So the default flips.** A row does not go on this board as ready-to-start
until someone has looked at the code and put the citation in the row. Absent a
citation the row is *unknown*, never *ready*. "Unanswered until proven shipped"
manufactures work; "unknown until verified" costs one grep. The designer session
can now read the repo directly, so there is no excuse left.

### Blocked, or still on the designer's desk

- **The component branch tree with its type evidence** — **drawn**, on canvas
  page seven. Its spec waits for **Verdict subject** to land, because the tree is built out of
  the Verdict subject row changes and writing the prose before that is specifying against a
  guess. One correction is already on the drawing: I had it sorted
  strongest-first, and `#86`'s weakest-first is better — a review queue should
  open on what needs attention.
- **The wire diagram beside the tree** — layout and the two ceilings. Mine.
- **Switching readings with verdicts already recorded** — a verdict is about the
  path, so it shows on every reading; switching must not look like fresh
  proposals with mysteriously pre-filled verdicts. Noted on the tree drawing,
  drawn next round.
- **Nested proposals** — where two extractors propose components over the same
  scope at *different granularities*. `curation-lenses-design.md` §4.4's overlap
  object, deliberately out of scope in today's ruling; a round of its own.

---

## The ledger

| written | designer reply | subject | state |
|---|---|---|---|
| 09-17 | `SPEC-PUBLISH-STATE-AFTER-REDEPLOY.md` | Publish state is stored locally and never reconciled; one resolve per connection; created vs archive GUIDs; the fourth publish state | **ready to start — Stale publish** |
| 09-17 | `ComponentTree.dc.html` (canvas page 7) | The branch tree: type evidence in words, agreement in the sort, absence in both columns, accept as the catalogue act | drawn; spec follows **Verdict subject** |
| 09-17 | `REPLY-RETRACTION-WITHDRAWN.md` | Withdrawing §4; two kinds of correction under one word; the gaps-list seed | needs no build; its §4 question is answered by the spec above |
| 09-16 | `RULING-WHAT-A-VERDICT-IS-ABOUT.md` + `VerdictSubject` | What a verdict is *about*; the three meanings of "perspective"; the withdrawal asymmetry | **ready to start — Verdict subject** |
| 09-15 | `SPEC-ACTIONABLE-AND-HONEST.md` + `Actionable` / `WhatWeFound` | Whose absence it is; the four destinations; population and caveat attribution; the interface ladder's missing rung | answered in part — `#98`–`#104`; **Honest rows** and **Findings that act** remain |
| 09-14 | `REPLY-CATALOGUE-IN-LAYERS.md` | Conceding the type error; layer 2 = accepted verdicts; the retraction | answered — the bulk-accept wording landed; §4 **superseded** by `REPLY-RETRACTION-WITHDRAWN.md` |
| 09-14 | `SPEC-THE-STAGE-PAGE.md` + `StagePage` / `FactInPlace` / `AnalysesIndex` | The owner's round — points 1/2/3/6/7/9/10, the fold, and the fact under the answer | answered — `#93` (endpoints), `#94`, `#99` (the split) |
| 09-14 | `REPLY-PORTS-SCARCITY-CORRECTED.md` | A correction against myself on port scarcity; the plural ports case; round two's agenda | answered — `#85`, `#86` (all three items; no `*-IMPLEMENTED.md` was written, which is how this row went stale) |
| 09-14 | `SPEC-PORTS-ROUND-ONE.md` + `ComponentReview` / `PortsAndWires` | The Curate claim corrected; ports as a column not a screen; review at the branch | answered — `PORTS-ROUND-ONE-IMPLEMENTED.md` (`#84`, `#85`) |
| 09-14 | `REPLY-CORRECTION-POPULATION.md` | Keep the whole current list; one clause when the corrected record carried a facet | answered — `#84` |
| 09-14 | `SPEC-REPORT-ACTS.md` + `ReportActs.dc.html` | The three acts on a report; the whole report as default; staleness carried; the record's uses | answered — `REPORT-ACTS-IMPLEMENTED.md` (`#83`, correction act included) |
| 09-13 | `SPEC-RECORDS-AND-COST-CALLS.md` + `RunChoice` / `DepthOffer` | The re-run choice, §3's depth offer, the report record | answered — `TWO-CALLS-AND-THE-RECORD-IMPLEMENTED.md` (`#81`, `#82`) |
| 09-13 | `REVIEW-RAIL-SENTENCE.md` | Review of `#60` — three copy defects | answered — `#72`, all four points |
| 09-13 | `REPLY-COST-LADDER-AND-PUBLISH-STATE.md` | Publish stays out of the ladder; three publish states, one condition | answered — `FUNNEL-COST-IMPLEMENTED.md` (`#70`, `#71`, `#75`, `#76`) |
| 09-13 | `REPLY-FUNNEL-COST.md` | Rulings on the funnel measurement | answered — `FUNNEL-COST-STATUS.md` + addendum, `#61`, `#63` |
| 09-12 | `REPLY-BLANK-RAIL-AND-LIST-ANSWERS.md` | The blank evidence rail; list answers side by side; the report as a Record | answered — `#59`, `#60` |
| 09-12 | `REVIEW-PROMOTION.md` | Review of `#41`; "no fix" answered as a value not a flag | answered — `PROMOTION-AND-RAIL-IMPLEMENTED.md` |
| 09-12 | `REVIEW-ENRICHMENT-JOURNAL-VENDORED.md` | Review of `#34`/`#35`/`#36`/`#39`; the four open items answered | answered — `REVIEW-FIXES-IMPLEMENTED.md` |

---

## Newest: what a component verdict is about

`RULING-WHAT-A-VERDICT-IS-ABOUT.md`. The question could not be settled until the
research separated the three things called *perspective* (§0 above). Once
separated:

**A verdict is about the component — the thing at that path — not about the
proposal that surfaced it.** It stays keyed by `scope_locator`. Three reasons,
none of them mine: `materializer.py`'s own comment says *"accepting is the point
at which that evidence stops mattering to what gets written"*;
`curation-lenses-design.md` §4.3 already ruled *"one verdict per component,
reused by every lens"* on the neighbouring axis; and identity is path-only end to
end — `run_label` reaches Egeria nowhere at all.

Four consequences, and they are the work:

- **The row shows both proposals.** Today the card's type, confidence and reading
  come from `max(comp_rows, key=surveyed_at)` — whichever step wrote last — so a
  curator can rule on a card whose attributes came from the other extractor than
  the drawing they clicked from, with nothing saying so. That is the defect the
  ambiguity was hiding.
- **Agreement is the best signal in the data and `latest wins` discards it.** Two
  unrelated methods — one reading manifests, one reading twenty-four months of
  co-change — landing on one path is stronger evidence than either alone, and it
  is the answer to the owner's *"why do we think this is which kind"*. Same fix,
  both problems. It also outranks a single high confidence in the sort.
- **Withdrawal is already proposal-scoped while verdicts are path-scoped** —
  `_withdraw_vacated` skips scopes it did not write. So coupling can withdraw a
  path that still carries a verdict earned from detect's, and today that reads as
  nothing. It gets the perishability treatment, third time out: *⚠ review — no
  longer proposed by coupling*. **Flag, do not invalidate.**
- **The coverage sentence holds two identity regimes in one breath** — components
  keyed by path, blueprints by `perspective::cluster_name`. It should say which:
  *4 of 87 component paths reviewed · 0 of 12 clusters in the logical reading
  reviewed.*

`_DIAGRAM_PERSPECTIVE_PREFERENCE`'s coupling-over-detect order stays — it is a
reasonable default and nothing better is known — but it stops being invisible.
What stays recorded as deliberate is that the two are **never merged** in the
diagram.

## Actionable, and honest about which population

`SPEC-ACTIONABLE-AND-HONEST.md`, drawn on canvas page five. Two of the owner's
six are short answers; four are one habit and one missing half.

**The dashboard split shipped** — `Questions · Survey & analyses · By analysis ·
Disposition`, with the fetch counts on the definition rows.

**Find repos leaves the strip, because a rule of mine was wrong.** *Identical
sub-tab order on every stage, grey what a stage lacks* is right for things that
are per-stage. Finding and importing repositories is corpus-level — the same
action on Scouting as on Curate — so greying it across nine stages is nine wrong
promises.

**Point 3 is the important one: the missing half is *whose absence it is.*** The
honesty rules produced a surface scrupulous about what it cannot say and silent
about what to do. *"responsiveness — not established"* is a true sentence about
the **analysis**, shown to someone who asked about the **repository**. So: a
finding about the analysis collapses to one line — *3 of 11 community measures
cannot be computed from what is collected — what is missing, and why › Not a
finding about this repository* — with an RFA against the analysis behind the
link. And every finding about the repository names one of **four destinations**:
a judgement (Enrichment, not a task), a task (RFA), context (nothing to do — as
important as the others), or **ours** (the gaps list). The gaps list *is* the
number behind the owner's instinct that the analytics need work.

**Points 4/5/6 are one habit** — a row composed from several analyses over
several populations, written as though it came from one:

- **The contradiction is real and diagnosable.** The row's provenance names three
  analyses; 24 is `architecture_recovery`'s, the nothing is
  `architecture_doc_lens`'s — and the answer line already says so, attributed,
  before the caveat repeats it as *"This analysis"*. Rule: **a caveat on a
  multi-analysis row names its analysis, or it does not render.**
- **Every count carries its population** — *24 at depth 1, of 87 recovered* — and
  no sentence holds two populations without *of* between them. Plus the type
  evidence (*a console entry point*, *two detectors agree*) on the row.
- **The interface ladder is missing its middle rung.** `interface_surface` has
  *declared* and *implied*; the truth is usually *implemented*. And its current
  sentence is wrong on this repository: *"cli — implied, depends on click"* while
  `[project.scripts]` is read in four other places, one of them
  `deployment_evidence.py` from `#94`, which calls a console entry point the
  strongest signal. **A fact known by one walk and not read by another** — the
  vendored defect, one analytic over.

## Cataloguing in layers

`REPLY-CATALOGUE-IN-LAYERS.md`. The owner's ruling corrected me, and for a better
reason than I got right: my S3 answer said *importable distribution → Software
Library*, and `SoftwareLibrary` is a classification meaning **a server that
manages distribution of software modules** — PyPI, Nexus, npm. It names the
manager, not the module. So my version would have kept cataloguing every package
as an artifact server while congratulating itself on fixing the applications.

Three things follow:

- **Layer 2 is the accepted verdicts**, which reframes the component column
  rather than adding to it — accepting a branch *is* the layer-2 catalogue act.
  So the bulk-accept dialog must say it catalogues, **but must not name a type
  nobody has verified**: *catalogues them as software components under
  `resource-explorer`; the exact Egeria type is not yet pinned.* Naming
  `DeployedSoftwareComponent` in a confirmation before verification is the
  `SoftwareLibrary` mistake one step earlier in its life.
- **The layer-2 offer is the depth offer's twin** — same three rules, same
  outcome-on-the-record — and unlike component creation its price has a basis:
  *about 1m 36s of Egeria writes (measured, 1.5s median)*.
- ~~**The retraction is not scheduled and should be.**~~ **Withdrawn on 09-17** —
  `REPLY-RETRACTION-WITHDRAWN.md`. The owner had already ruled on 09-14 (wipe and
  redeploy), `SoftwareLibrary` was never published, and my premise that every
  published SurveyReport hung off both elements was half false. What survives is
  one gaps entry: *there is no way to correct or annotate an element already
  published to Egeria.*

Also: the live metric is `code_lines`, not `lines_of_code` — the sheet is
corrected. And `#93`'s per-cell `opens` table is the best work in that round and
is not mine: refusing `opens` on `relationship_count` because `_symbol_members`
lists symbols rather than relationships, traced to the reader's own docstring, is
the honesty rule at a granularity I would not have thought to ask for.

## The owner's round

`SPEC-THE-STAGE-PAGE.md`, drawn on canvas page four. Seven of the ten points are
one cause, and the code states it more sharply than the complaint: **the
Questions row renders the answer and cannot reach the members at all, while
`Dashboard · by question` renders the same sentence from the same envelope so it
can host a `detail` disclosure whose payload opens in a 290px rail.** The answer
is in two panes and the fact is in neither.

The spine: **one object, the analysis; one entry, the question; one place for the
fact, the pane under the answer.** Questions absorbs `Dashboard · by question`;
Survey becomes *Survey & analyses*; `By analysis` keeps its own tab; the rail
keeps provenance and only provenance — the code already admits members went there
because the pane *"held an empty ask box and eighteen hundred pixels of
nothing"*, and the pane is no longer empty.

Point 10's link is *the numbers behind this 6 ›*, and it opens a table of six
measurements under the answer — because 965 file names are not the fact behind
*965 source files*; the number is. Point 4: visuals return under one rule — a
visual may only show a number the row beneath it also shows, from the same value,
rounded the same way, because a tile reading *82/100* over a card reading *82.2*
was the defect, not the chart.

## Ports, and a correction against myself

`REPLY-PORTS-SCARCITY-CORRECTED.md` — **all of it shipped in `#85`/`#86`**; kept
here for the correction it records against me.

I wrote that most repositories have almost no ports, and built part of the
"column, not a screen" ruling on it. You measured **71 on egeria-workspaces, 68
with an owner.** My figure was the logical reading, where components are packages
and nothing declares a port; yours is deployment artifacts in a compose-heavy
repository. Both true; my generalisation across them was not.

The ruling stands on its stronger half — a port is a reading, not a proposal —
but 71 forces a **plural case** the drawing lacked: three or more as `15 ports ›`
opening the list in the rail, because counts open what they counted. And the
tree's foot gains the other end of the sentence: *71 ports across 9 components ·
3 not attributable to any shown component, counted apart.*

Three things in `#85` I would not have specified and would not change: ports
keyed by the deployment **service name** so the column and the diagram agree by
construction; the three unowned ports counted apart rather than attached to a
guess; and the price line reading *not yet measured — the first branch is what
fixes it*. **641 → 69 branches in 2.9 s** settles the scale question by
measurement.

---

## Conventions

- Designer replies land in this folder. `REVIEW-*` for a review of shipped work,
  `REPLY-*` for an answer to a question, `SPEC-*` for something buildable,
  `RULING-*` for a decision with consequences rather than a layout; wireframes in
  a `design_handoff_*` folder beside them.
- Every reply names the commit it was read against in its header. If main has
  moved, say so in your response rather than assuming the reply is current.
- Implementer replies are `*-IMPLEMENTED.md` in this same folder, naming what
  they reply to. **Write one even when the work shipped inside a PR raised for
  something else** — that omission is what left three shipped items sitting on
  the board as ready-to-start.
- **A ready-to-start row cites the code it was checked against**, with a path and
  a line or the grep that came back empty, and names who checked it. Mine say so
  when I could not check: no repo checkout is reachable from the designer session
  unless the user connects one, so a citation of mine may be a relay of yours.
- **Attribute decisions by role, not by first name** — *the project owner ruled
  X* — and give each ruling the repo-wide greppable callout,
  `**Decision (project owner, <date>):** ...`, rather than folding it into
  prose. Repo convention, in the root `CLAUDE.md`; these notes are a project
  record, not private correspondence. A username inside a UI mockup is sample
  data, not attribution, and is fine.
- **A designer ruling can be wrong.** Six are on the record here — the greyed
  `Find repos` tab, port scarcity, the `SoftwareLibrary` type, `lines_of_code`,
  the stale ports board rows, and the retraction that the owner had already ruled
  out — and every one was caught by measurement against the code or by someone
  remembering a decision. Measure and say so; it is the fastest correction path
  this pair has, and the ledger is more useful with the errors left legible in it
  than tidied out.
