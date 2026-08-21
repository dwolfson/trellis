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
| `Funnel Stage` | Yes | Which funnel stage(s) this question belongs to: `Scouting`, `Discovery`, `Analysis`, `Assessment`, `Enrichment`, or `Automate`. May be **slash-combined** (e.g. `Analysis/Enrichment`) to signal an Analysis-first, Enrichment-fallback pattern (see `docs/confidence-gated-validation-plan.md`) — the question then shows up under both stages' checklists. |
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
