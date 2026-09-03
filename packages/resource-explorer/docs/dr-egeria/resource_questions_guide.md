# `resource_questions.csv` — user guide

`docs/dr-egeria/resource_questions.csv` is the **single source of truth**
for the questions users can ask about a resource (currently: a repo) as
they move it through the Trellis funnel — Scouting, Discovery, Analysis,
Assessment, Enrichment, Automate. Two generated outputs are built from it,
never the other way around:

1. **`resource_explorer/configdata/question_catalog.yaml`** — via
   `scripts/csv_to_question_catalog_yaml.py`. Backs Resource Explorer's
   Scouting **"Questions" checklist tab** at runtime.
2. **Dr.Egeria markdown → real Egeria elements** — via
   `scripts/csv_to_dr_egeria_questions.py`, following the
   Question/Perspective/ScopedBy pattern documented in
   `docs/dr-egeria/foundations/foundations.md`. This publishes each row as
   a `Question` GlossaryTerm in Egeria, linked to its Perspectives and
   Funnel Stage.

**Edit the CSV, then regenerate — never hand-edit the YAML.** The YAML
file's own header says as much; it's overwritten every time the generator
script runs.

## Editing workflow

1. Open the CSV (a spreadsheet app or a plain editor both work — it's a
   simple comma-separated table, one row per question).
2. Add, edit, or remove a row (see column reference below).
3. Regenerate the runtime YAML:
   ```bash
   uv run --package resource-explorer \
       python packages/resource-explorer/scripts/csv_to_question_catalog_yaml.py \
       docs/dr-egeria/resource_questions.csv
   ```
4. If the question should also exist as a real Egeria element (so it's
   queryable/scopable live in Egeria, not just RE's local checklist),
   regenerate the Dr.Egeria markdown with
   `scripts/csv_to_dr_egeria_questions.py` and run it through Dr.Egeria
   (VALIDATE, then PROCESS) — see that script's docstring and
   `docs/dr-egeria/foundations/foundations.md` for the exact procedure.
   `foundations.md` must be run once, before any stage's questions file,
   since Perspectives and Funnel Stage terms are shared across all stages.
5. Commit the CSV *and* the regenerated YAML together — don't let them
   drift out of sync.

## Column reference

| Column | Required? | Meaning |
|---|---|---|
| `Question` | Yes | The question text, verbatim. This becomes the Egeria GlossaryTerm's **Display Name** — case- and punctuation-sensitive, since it's also the join key back to Egeria's own `Question` elements. Keep it phrased as an actual question a user would ask. |
| `Funnel Stage` | Yes | Which funnel stage(s) this question belongs to: `Scouting`, `Discovery`, `Analysis`, `Assessment`, `Enrichment`, or `Automate`. May be **slash-combined** (e.g. `Analysis/Enrichment`) to signal an Analysis-first, Enrichment-fallback pattern (see `docs/repo-analysis-funnel.md (§14)`) — the question then shows up under both stages' checklists. |
| `Why is this important?` | Optional but expected | One sentence on why a user would care. Becomes the term's **Summary**. |
| `Rationale/Source` | Optional but expected | Longer explanation: where the answer comes from, what tooling/signal is involved, any caveats. Becomes the term's **Description** (falls back to the question text itself if left blank). This is the column most worth writing carefully — it's what someone reads to understand *why* the answer works the way it does. |
| `Answering Analysis` | Optional, RE-internal | Free text describing how RE answers this today. Parsed by the generator into a structured `kind` — see **Answering Analysis conventions** below. Not published to Egeria. |
| `Answering Mechanism` | Optional, RE-internal | Which engine answers the question — one of: `Git Statistics`, `Code Analysis`, `RAG Queries`, `Agent-Based Analysis`, `Egeria Queries`, `Local Registry Query`, `Human-Supplied`, `Direct Field`, `Trend Chart`, `Gap`, `Automate Change Detection`, or a `+`-joined combination (e.g. `Code Analysis + Egeria Queries`). Orthogonal to `Answering Analysis`'s `kind` — this says *which system* answers it, not *how confidently*. Not published to Egeria. |
| **Perspective columns** (everything after `Answering Mechanism`) | Optional per question | One column per Perspective: `Financial`, `Governance`, `Steward`, `Data Owner`, `Consumer`, `App/AI Builder`, `Privacy`, `Community`, `Data Expert`, `Security`, `Architecture`, `Admin`. Put an `X` (any non-empty value works, but use `X` for consistency) in every column that applies to this question. Leave the cell blank if the perspective doesn't apply. A question can — and often should — have several perspectives marked. |

The generator treats **every column that isn't one of the six named lead
columns** (`Question`, `Funnel Stage`, `Why is this important?`,
`Rationale/Source`, `Answering Analysis`, `Answering Mechanism`) as a
perspective column, so column order for the perspectives doesn't matter —
but don't rename the six lead columns, and don't add a new perspective
column without also creating that Perspective in
`docs/dr-egeria/foundations/foundations.md` first (Perspectives are
resolved by name/qualified-name against existing Egeria elements when
publishing — an unrecognized perspective will fail validation there, even
though it'll happily show up in RE's own YAML-backed checklist).

## What each Perspective means

Perspectives are **lenses, not personas or job titles** — one person can
hold several depending on what they're doing at the moment. Full
descriptions live in `docs/dr-egeria/foundations/foundations.md`; summary:

- **Financial** — cost to acquire/run/support, cost of duplication vs. reuse.
- **Governance** — program-level compliance/policy oversight, not per-check detail.
- **Steward** — day-to-day data quality and correctness for a domain.
- **Data Owner** — accountable for whether a resource should exist, be retired, or change hands.
- **Consumer** — "is this worth using for my purpose" shopping lens.
- **App/AI Builder** — building an app or AI capability against the resource; content suitability, not just structural quality.
- **Privacy** — regulatory compliance and sensitive-data exposure.
- **Community** — contributor activity, responsiveness, adoption (mainly open-source repos).
- **Data Expert** — works with/moves/shapes data (consolidates data science, data engineering, and integration lenses).
- **Security** — risk signals: CVEs, dependency vulnerabilities, security responsiveness.
- **Architecture** — how the resource fits the broader information architecture/supply chain.
- **Admin** — operational/infrastructure upkeep, access, reliability.

## `Answering Analysis` conventions

The generator (`scripts/csv_to_question_catalog_yaml.py`) parses this
column's free text into a structured `kind` by recognizing a small set of
established prefixes/phrases — keep using them so new rows parse
correctly instead of falling into `unknown`:

| Write this... | ...to get `kind` | Meaning |
|---|---|---|
| `GAP: <description>` | `gap` | No RE tooling answers this today; real gap, name candidate tools if known. |
| `PARTIAL: <description>` | `partial` | Partially answerable; note what's missing. |
| `MIXED: <description>` | `mixed` | Answered by a combination of signals/analyses. |
| `N/A — <description>` | `direct` | Answered directly from a field/table, no analysis needed. |
| *(mentions "human-supplied")* | `human` | Needs a person to answer (e.g. via Enrichment Context form). |
| *(mentions "trend chart")* | `chart` | Answered by an Understanding-tier trend chart. |
| *(a bare known analysis id, e.g. `repository_health`)* | `analysis` | Answered by that specific `analysis_catalog.yaml` analysis. |
| anything else | `unknown` | Doesn't match a known convention — the generator surfaces it as `unknown` rather than guessing; fix the wording to use one of the conventions above. |

The generator also scans this column's text for any of the known
`repo_analyses` ids (`language_file_classification`, `repository_health`,
`dependency_analysis`, `security_scan`, `documentation_coverage`,
`license_classification`, `security_features`, `ci_quality`, `maturity`,
`repo_conventions`, `data_file_profiling`, `api_structure`,
`repo_profile_refresh`, `rag_ingestion`, `egeria_publish`) and records any
matches, regardless of `kind` — so mentioning an analysis id by name (even
inside a `MIXED:`/`PARTIAL:` note) links it, whether or not it fully
answers the question on its own. If `analysis_catalog.yaml` ever gains new
analysis ids, `KNOWN_ANALYSIS_IDS` at the top of
`scripts/csv_to_question_catalog_yaml.py` needs a matching update or new
ids won't be recognized here.

## From a row to an answer

Adding a row makes a question *appear*. Making it *answer* is a separate
thing, and the column that does it is `Answering Analysis`. A row with that
column blank generates `kind: unknown, analysis_ids: []` — the question
shows in the checklist and never answers anything.

The full chain, and where each link lives:

| # | Link | Where |
|---|---|---|
| 1 | The row | `docs/dr-egeria/resource_questions.csv` |
| 2 | `Answering Analysis` → `kind` + `analysis_ids` + `checks` | `scripts/csv_to_question_catalog_yaml.py` |
| 3 | Generated catalog | `resource_explorer/configdata/question_catalog.yaml` |
| 4 | Each `analysis_id` → a value | `FactLayer.fact()` via `REPO_ANALYSIS_RESULTS_MAP` |
| 5 | Value → the visible answer | `_renderEnvelopeMarkdown` in `index.html` |

**Regenerate the Survey Definitions too.** `scripts/generate_repo_survey_definition.py`
derives each definition's Question scope-links from `question_catalog.yaml`, so a
new question makes the committed markdown under `docs/dr-egeria/survey-definitions/`
stale. `tests/test_survey_definition_generator_guard.py::test_a_clean_tree_regenerates_to_nothing`
fails until you run it — which is how this step was found, after being left out of
the first draft of this section:

```bash
uv run python scripts/generate_repo_survey_definition.py
```

Commit the regenerated `.md` files and `.generated.json` alongside the CSV and the
question catalog. Three artifacts move together; leaving one behind is a silent
drift the guard catches only on the next full test run.

**Restart the web server after regenerating.** The catalog loader is
`@functools.lru_cache(maxsize=1)` (`surveyors/question_catalog_reader.py`),
so a running server keeps serving the old catalog and your new question
simply will not appear. This costs more debugging time than it should; check
it first.

### Two ways a question becomes answerable

**Path A — CSV only, no Python.** Name an analysis that already has a
results reader in `REPO_ANALYSIS_RESULTS_MAP`, and the fact layer resolves
it. This is the normal path and needs no code at all.

**Path B — a Python resolver.** `RESOURCE_STATE_SOURCES` in `facts.py` maps
*exact question text* to a resolver function, for questions answered from
registry state rather than from an analysis — description, disposition,
licence, feedback, "has this been catalogued". Adding one of these means
writing a `_r_*` function. Note the key is the question string verbatim, so
Path B questions are the ones where editing the wording silently breaks the
answer.

### Choosing the `kind` honestly

The conventions table above says what each prefix *produces*. What it does
not say is how to choose, and the choice is the part that matters, because
`analysis` is a claim that the question is answered.

**Check what the data actually contains before writing a bare analysis id.**
Not what the analysis is named, not what its description says — what its
results reader returns for a real resource. Two ways this goes wrong, both
found on 2026-09-01 while wiring two new rows:

- *The analysis computes it but does not persist it.* `api_structure`'s
  surveyor derives a complexity summary from
  `project_code_symbols.complexity` and then stores only `symbol_count`,
  `relationship_count` and `by_language`. The number exists at survey time
  and never reaches the question layer. Naming `api_structure` for a
  complexity question would have produced a question that looks wired and
  answers nothing.
- *The field's name is a claim its contents do not support.*
  `project_stats.ingestion_lines_of_code` sounds like the answer to "how
  much code is there". It counts every newline in every text-suffixed file
  (`pipeline.py::_count_repo_stats`). Measured on egeria-python: it reports
  **1,118,195**; actual Python code lines are **156,297** — 14%. The rest is
  JSON (40.7% of all lines), Markdown (28.2%), docstrings and blanks. It is
  also written only by full ingestion, so it is NULL for repos indexed
  another way.

`GAP:` is the right answer more often than it feels like it is. A question
marked `gap` renders a clear "No mechanism exists for this yet" and offers
no Run button (`can_run` is empty, verified) — which is strictly better than
a question wired to a number that does not mean what its name says.

**Mentioning an analysis id anywhere in the note links it**, including
inside a `GAP:` or `PARTIAL:` note, because the generator regex-scans the
whole column. That is usually what you want (it records what was
considered), and `kind` still governs answerability — a `gap` row with a
populated `analysis_ids` is still unanswerable. Just do not be surprised to
see the id in the generated YAML.

### Worked example: the two rows added 2026-09-01

**"What are the public interfaces?"** (Discovery) → `interface_surface`,
`kind: analysis`. Answers immediately, no code. Note it has a near-neighbour
already in the CSV — "What APIs and code symbols does it expose to callers?"
(Analysis, `api_structure + interface_surface`). They are not duplicates:
Discovery asks *is a contract published*, Analysis asks *what symbols
exist*, and `interface_surface` is itself a Discovery analysis.

**"How much code is there? How complex?"** (Assessment) → `GAP:`. Both
halves are gaps, for different reasons (the two failure modes above). File
and symbol counts do exist, but "how many files" is not "how much code", and
answering with them would be answering a different question.

### What the process caught by itself

Worth knowing, because these are the guards working rather than obstacles:

- `Purposes: "Asses; Maintain"` failed the generator outright — *"unknown
  Purpose(s) ['Asses']"*. A typo in a controlled vocabulary stops the build
  instead of creating a phantom purpose. (Whitespace after `;` is fine; it
  is stripped.)
- Both new rows parsed to 19 fields cleanly, so a mis-aligned row would have
  shown up immediately as a column-count mismatch.

## Notes and gotchas

- **Don't add a perspective column without creating the Perspective in
  Egeria first.** `foundations.md` documents the exact steps (including
  why each Perspective needs an explicit `Qualified Name` — several
  Perspective *display* names collide with pre-existing demo-data element
  names).
- **Keep `Question` text stable once published.** It's the case- and
  punctuation-sensitive join key back to the Egeria GlossaryTerm — editing
  it after publishing effectively creates a new question rather than
  updating the existing one, unless you also update/re-link the Egeria
  side.
- **The YAML is a build artifact.** If you find yourself editing
  `resource_explorer/configdata/question_catalog.yaml` directly, stop —
  edit the CSV and regenerate instead, or your change will be silently
  lost the next time someone else regenerates it.
- **This file only covers `repo` questions today.** `question_catalog_reader.py`'s
  loader is structured to support other resource types later
  (`{"repo": [...]}`), but only `repo` is populated currently.
