# Code volume, in-code documentation, and complexity — design

**Status: design only. Nothing below is built.**

## Where this came from

Dan added a question to `resource_questions.csv` — *"How much code is there?
How complex?"* — and then, on being told the size half could be answered from
existing file and symbol counts:

> "size would include lines of code - commented and non-comment"

and, on being told a rename of the misleading field was the fix:

> "I don't think its just a rename - the decomposition itself is
> interesting/important - it seems like these metrics are just different
> annotations that are part of the annotation type? It also seems that the
> amount of docstring and comments should also bear on the documentation
> coverage questions and assessment?"

Both points hold, and the second one turned out to be stronger than it was
put. This document is the design pass before any of it is built, because one
part changes a verdict that is already on screen and may already have been
acted on.

## What is measured today, and what it claims

Three separate defects, each measured on `egeria_python_git` (2026-09-01).

### 1. `ingestion_lines_of_code` is a correct number under a wrong label

`pipeline.py::_count_repo_stats` counts every newline in every file whose
suffix is in `_TEXT_SUFFIXES`, and stores it as
`project_stats.ingestion_lines_of_code`.

| | lines | share |
|---|---|---|
| `.json` | 378,652 | 40.7% |
| `.py` | 272,150 | 29.3% |
| `.md` | 262,375 | 28.2% |
| everything else | ~16,000 | 1.7% |

And within those 272,150 Python lines:

| | lines | share of Python |
|---|---|---|
| code | 156,297 | 57.4% |
| docstring | 69,931 | 25.7% |
| blank | 35,484 | 13.0% |
| comment | 10,537 | 3.9% |

**Reported as `lines_of_code`: 1,118,195. Actual Python code lines: 156,297 —
14%.** It is also written only by full ingestion, so it is NULL for repos
indexed another way (`egeria_git` and `amundsen` are both NULL today). It is
read by `web/routes/stats.py`, `agents/stats_agent.py`, and
`sub_surveyors/file_structure.py`'s `ResourceMeasureAnnotation`.

### 2. Documentation coverage does not look at whether the code is documented

`documentation_coverage` rates `egeria_python_git` **"Comprehensive (5
signal(s) detected)"**. The five signals, in full:

    collection_present  markdown_docs
    collection_present  examples
    collection_present  release_notes
    hygiene_files       README, Contributing guide
    quality_score       Comprehensive

Meanwhile `project_code_symbols.docstring` is already populated at ingestion:

| | symbols | with docstring | |
|---|---|---|---|
| all | 8,654 | 5,190 | 60.0% |
| **public only** | 6,752 | 3,767 | **55.8%** |

44% of the public API surface has no docstring, and the documentation verdict
is "Comprehensive" — because in-code documentation is not among the signals,
so the score *cannot* fall for it.

`documentation.py` already declares this limitation honestly, against a
GovernanceMetric, in a comment beside the code that computes it:

> counts KINDS of documentation and not quality — one excellent guide scores
> below five stubs. That limitation belongs in the declaration rather than in
> a reader's assumption.

The declaration is right and the score still reaches a reader as a verdict.
**Understanding a limitation is not protection from it**, which is the whole
reason this is a design pass and not a patch.

### 3. Complexity is computed and thrown away

`api_structure`'s surveyor derives a complexity summary from
`project_code_symbols.complexity` and then persists only `symbol_count`,
`relationship_count` and `by_language`. The number exists at survey time and
never reaches the question layer.

**Correction (2026-09-01, while implementing D3).** An earlier draft of this
section said complexity was "populated for all 437,064 symbols across every
language, unlike docstrings". That was wrong, and wrong in this document's own
signature way: it came from `COUNT(*) WHERE complexity IS NOT NULL`, which
counts a stored **0** as populated. The distribution says otherwise:

| language | functions/methods | min | max | avg | distinct values |
|---|---|---|---|---|---|
| java | 179,668 | 1 | 348 | 1.59 | 55 |
| python | 97,833 | 1 | 186 | 2.64 | 84 |
| **go** | 62,403 | 0 | 0 | 0.00 | **1** |
| **javascript** | 35,764 | 0 | 0 | 0.00 | **1** |

`go_symbol_extractor.py` and `js_symbol_extractor.py` contain **no
`complexity=` assignment at all**, so every row defaults to zero. Complexity
has exactly the same coverage gap as docstrings, in the same two languages, and
D3 inherits D4's constraint rather than being exempt from it. A mean complexity
computed across all four languages would be dragged toward zero by 98,167
symbols that were never measured.

## The hard constraint: extractor coverage is not a property of the subject

`go_symbol_extractor.py` and `js_symbol_extractor.py` **hardcode
`docstring=""`** — 3 and 4 assignment sites respectively, all empty. Measured
across the whole symbol table:

| language | symbols | with docstring | complexity |
|---|---|---|---|
| java | 203,521 | 60,437 | 203,521 |
| python | 114,055 | 54,985 | 114,055 |
| **go** | 70,955 | **0** | 70,955 |
| **javascript** | 48,533 | **0** | 48,533 |

Go has doc comments and JavaScript has JSDoc. Both exist in the language and
neither is extracted. A docstring-coverage metric applied naively to a Go repo
reports **0% documented**, which is a claim about our extractor wearing the
clothes of a claim about their code — and 0% is the *worst* possible value, so
the error is maximally alarming rather than maximally quiet.

**This constraint governs the whole design.** Any coverage figure must carry
the language it was computed over and must refuse to produce a verdict for a
language whose extractor cannot see documentation at all. `not_established`
for Go is the correct answer; `0%` is a lie.

## Design

### D1 — Volume is a decomposition, not a scalar

Dan's framing is right: these are annotations, not one number. The shape
already exists — `file_structure.py` emits a `ResourceMeasureAnnotation`
carrying a `by_language` dict in `resource_properties`; `lines_of_code` is a
scalar sitting inside that same annotation.

- **One summary** `ResourceMeasureAnnotation`: total code lines and the file
  count they were measured over.
- **Per-language evidence** `ResourceMeasureAnnotation`s: `code`, `comment`,
  `docstring`, `blank` for that language, plus the files counted.
- Evidence links to summary via **`Annotation.evidence_of` →
  `AnnotationExtension`** — the Phase 2 mechanism merged 2026-09-01. This is
  the first consumer outside `data_profiler`/`dependency`, and it is the
  natural one: a per-language breakdown *is* the evidence for an aggregate.

`ingestion_lines_of_code` is **retired, not renamed.** A rename preserves a
number nobody should quote; the three readers move to the new annotation, and
the column is left in place unread for a soak period (the precedent the
generic-table migration already set).

Non-source files are counted separately and **not** folded into a code total.
"1,065 Markdown files, 262,375 lines" is a useful and honest fact; adding it
to a code figure is what produced the current defect.

### D2 — Documentation coverage gains a ratio, and the score stops being a count

Two changes, and the second matters more than the first.

**Add the measure**: docstring coverage over **public** symbols, per language,
from data already in the table. No new extraction for Python or Java.

**Stop summing incommensurables.** Today `score = len(present_doc_types) +
len(found_hygiene)`, thresholded at 5 and 2. Adding coverage as a sixth
"signal" would make things worse: a repo with 0% documented code would still
count 5 and still read "Comprehensive". A ratio over a denominator and a count
of present artifact kinds are different measurements, and adding them is how
"Comprehensive at 55.8%" happened in the first place.

Proposal: artifact presence (today's count, unchanged and still useful) and
API documentation coverage sit beside each other as two separate facts. **See
D2a — the coverage figure is a measure and not a graded dimension**; an
earlier draft of this paragraph proposed it as a second quality dimension,
which the author's own correction rules out.

This adds a fact beside a verdict already on screen. `egeria_python_git` keeps
its artifact-presence label and gains a coverage measurement next to it. Per
D2a the label is not downgraded by the coverage figure — the reader is given
both and draws their own conclusion, which is the honest arrangement when the
second number is not a score.

### D2a — Coverage is a measure, not a verdict (author's correction)

Dan, who wrote most of egeria-python, on being shown the 55.8% figure:

> "As the author of most of egeria-python, I can say that it has evolved over
> a couple of years - and that the documentation I put in was where I thought
> it was most useful... There probably is some cleanup and coverage to expand
> but quantity is not the same as usefulness."

This corrects D2 before it is built, and the correction matters more than the
feature. **55.8% is not a deficiency.** It is the visible shape of a
deliberate authorial choice about where documentation earns its keep, and a
metric that treats 100% as the target would be scoring a repo down for not
documenting things that did not need documenting.

Shipping "55.8% documented" as a documentation *quality* dimension would be
this codebase's signature defect one more time: a correct number under a wrong
label. The number is right. "Documentation quality" is the wrong thing to call
it.

So, binding on the implementation:

- **Coverage is reported as a `ResourceMeasureAnnotation`, not a
  `ClassificationAnnotation`.** It states what was counted. It does not grade.
- **It does not feed `quality_score`, in any form** — not as a sixth signal,
  and not as a second graded dimension either, which is what D2 above
  originally proposed. That proposal is superseded by this section: presence
  and coverage sit beside each other as two facts, and neither is a score.
- **Low coverage raises no RequestForAction.** An RFA asserts something should
  be done. Nobody here knows that a given undocumented symbol should have been
  documented, and the person best placed to know has just said the
  distribution was intentional.
- **The annotation says this in its own words**, so a reader three months from
  now does not have to find this document: coverage measures presence, not
  usefulness, and a lower figure may reflect a deliberate choice about where
  documentation is worth writing.

What would genuinely measure usefulness — is the *public entry-point* surface
documented, are the most-referenced symbols documented, is a docstring more
than a restatement of the signature — is real analysis and is **not** in
scope. Naming it here so the gap is on record rather than implied by the
metric that does not measure it.

### D3 — Complexity is persisted, not recomputed

`api_structure` already computes the summary. Persist it as a metric so the
question layer can read it. No new analysis and no new extraction — but, per
the correction above, **the same language guard as D2a applies**: complexity is
real only for Java and Python, and a figure spanning Go or JavaScript would be
averaging in zeros that mean "never measured". Report per language, name the
languages excluded, and refuse an aggregate that would silently include them.

### D4 — Coverage travels with every figure

Every measure above carries what it was computed over: which languages, how
many files, and — for docstring coverage — an explicit
`not_established`/`skipped_by_design` for any language whose extractor cannot
see documentation. The existing `result_status` and `step_outcome`
vocabularies already express this; nothing new is needed except the discipline
of using them.

## What this changes for questions

- **"How much code is there? How complex?"** (Assessment) — currently `GAP:`
  on both halves. D1 and D3 close it.
- **"How is it supported?"** and the documentation questions — currently
  answered by artifact presence alone. D2 makes the answer about the code.
- Any question consuming `lines_of_code` today is consuming "lines in text
  files"; D1 retires that.

## Sequencing

1. **D2's measure** — largest correctness win, no new extraction, data already
   present. Ship the *ratio* and the two-dimension reporting together; shipping
   the ratio as a sixth signal would entrench the defect.
2. **D3** — smallest change, closes half a question.
3. **D1** — the decomposition, and the retirement of
   `ingestion_lines_of_code` with its three readers.

## Deliberately not in scope

- **Go and JavaScript doc extraction.** Real work in the extractors, and a
  prerequisite for coverage verdicts on those languages — not for the design,
  which handles their absence by refusing to score rather than by scoring
  zero. Worth its own item.
- **A single documentation "grade".** Explicitly rejected above: collapsing
  presence and coverage into one number is the defect, not the fix.
- **Cyclomatic complexity thresholds / "too complex" verdicts.** D3 persists
  what is already computed. Turning a distribution into a judgement is a
  separate decision with its own rubric question, and this codebase's own
  precedent (`foss_scorecard`, CHAOSS) is to report on the metric's own terms
  rather than average into a score.

## Verification

- **Known-negative for the Go/JS constraint**: a repo whose symbols are all Go
  must produce `not_established` for docstring coverage, never `0%`. This is
  the test most worth writing first — it fails on the naive implementation,
  which is exactly the implementation someone would reach for.
- **The decomposition sums**: per-language `code + comment + docstring + blank`
  equals the total lines counted for that language, so a category silently
  dropped shows up as an arithmetic mismatch rather than as a plausible number.
- **Against a known checkout**: egeria-python's Python code lines should land
  near 156,297 and its public docstring coverage near 55.8% — both measured
  independently here, before any of this exists, precisely so the
  implementation has something to disagree with.
- **Coverage never becomes a grade**: a test asserting the coverage figure is
  emitted as a `ResourceMeasureAnnotation` and that `quality_score` is
  unchanged by it — the known-negative for D2a, which fails the moment someone
  folds the ratio back into the score.
- **Low coverage raises no RFA**: a repo with deliberately sparse docstrings
  must produce a measurement and no request for action.
