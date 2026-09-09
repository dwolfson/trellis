# Using the context-compilation tooling

Practical guide to what shipped. Architecture and rationale are in
`context-compilation-architecture.md`; this is what to type.

Everything here is **off by default** and additive. Nothing changes behaviour
until a flag is set.

## Turning containment trees on

```bash
ARTIFACT_TREE_ENABLED=true uv run resource-explorer refresh <slug> --no-stats
```

Off means byte-for-byte the previous behaviour: no connection opened, no table
created, no work done. On, trees are built **in addition to** the chunks that
walk already produces — never instead of them.

Trees land in their own Postgres schema, `artifact_tree`, created on first use.
It belongs to neither app: both RE and EA produce trees, so a read-only
cross-schema pattern could not serve it.

Four ingestion paths build trees: markdown, code (Python/Java/JavaScript), HTML
(`web_docs`), and PDF. Go has no grammar, so `go_code` reports `unsupported`
naming what is missing rather than failing per file.

### PDFs

OCR is **off by default and that is a workaround, not a preference**. Docling's
default engine is rapidocr, which needs omegaconf; omegaconf cannot resolve above
2.0.6 in this workspace because `soda-core` pins `antlr4~=4.11`, and 2.0.6 rejects
the `PosixPath` rapidocr passes. With the default engine *every* conversion fails.

Tables, headings and lists do **not** need OCR — `do_table_structure` is a
separate Docling stage and works without it. OCR is only for text that exists as
pixels: a scanned page, or labels inside a rasterised diagram.

To enable it, pick an engine that is not rapidocr:

```bash
pip install 'trellis-artifact-tree[ocr]'      # easyocr, portable
pip install 'trellis-artifact-tree[ocr-mac]'  # ocrmac, macOS, much lighter
PDF_OCR_ENABLED=true PDF_OCR_ENGINE=easyocr uv run resource-explorer refresh <slug>
```

Neither depends on omegaconf, so this does not require the `soda-core` migration.

## Compiling a context

```bash
curl -X POST http://localhost:8810/api/context/compile \
  -H 'Content-Type: application/json' \
  -d '{"resource_slug":"egeria_git","question":"is this ready to adopt?",
       "perspectives":["Security"],"budget":4000}'
```

Returns `{text, manifest, derivation}` together. A caller with only the text
cannot say why a section is there, what was dropped, or what is missing — the
three things people actually ask.

- **`manifest.packed`** — sections included, at which rung, and their size
- **`manifest.dropped`** — cut for budget, with the reason
- **`manifest.deferred`** — ranked below the section cap and never offered to
  the packer, with rank and weight. Since 2026-09-09 a compile packs at most
  `MAX_EVIDENCE_SECTIONS` (12) evidence sections, chosen after ranking;
  `compile_context(max_sections=...)` overrides it and 0 disables it. Measured
  on the experiment repos at budget 6000: uncapped, 26 sections shared the
  budget and 22% reached FULL; at 12, 88% did and the budget still filled to
  5610 of 6000, so the budget rather than the cap decides the last sections in
- **`manifest.gaps`** — sections the derivation says should exist, **judged**:
  `nothing_found` (ran, a real zero), `never_run`, `not_established`, each with
  `last_run_at` and `can_run` where known
- **`derivation`** — which question, which Purpose matched, which analysis
- **`compile_id`** (also `manifest.compile_id`) — a content hash of everything
  the packer saw: spec, version, budget, target model, and every candidate's
  rungs. Same materialised state → same id, so a repeated id is a compile that
  replayed. Every compile is persisted in the registry's `context_compiles`
  table (manifest and derivation as JSON, user, session, `hits`), and both
  conversation turns and feedback carry the id, so a rating can be traced to
  the exact context the model was given. Send it back on
  `POST /api/query/feedback` as `compile_id`; the chat stream's `done` event
  carries it at top level.

Budget is in **characters**, not tokens. The caller owns the conversion, because
only it knows which model the context is for.

Two conventions the packed text relies on — one a rung convention, the other
instruction wording — both from the 2026-09-08 audit of the compiled-versus-RAG
experiment (`packages/resource-explorer/docs/experiments/`):

- A results-reader section at its SUMMARY rung is headed **`structure only`**:
  scalar values are shown as values, lists and mappings are named but not
  counted. The counts (`5 key(s)`) were being narrated as findings ("5 lines of
  code by language"), which is where compiled answers picked up more unsupported
  claims than RAG-only ones.
- The refusal wording is deliberately loose: *"If the evidence does not answer
  the question, say so and name what is missing — do not infer from absence."*
  A one-shape refusal template was tried instead and reverted — run 3
  (`packages/resource-explorer/docs/experiments/compiled-vs-rag.md`,
  run3-20260909) found it over-triggered, turning 107 of 156 compiled answers
  into pure-template refusals, some for questions whose answering analysis was
  packed at FULL. The agent's system prompt is back to its original wording too
  — "say so plainly and either ask a clarifying question or name what analysis
  would need to run" — and tightening the refusal shape without over-triggering
  is noted as a rubric-side follow-up, not a compiler change.

## In the UI

**Chat answers now use compiled evidence.** The agent no longer just names the
available collections; the analyses that answer the question are packed into the
prompt with the missing ones named. Nothing is run to fill a gap, so a question
never blocks on a survey.

**The `Evidence` button beside Send** shows the manifest, gaps first. It is
deliberately not rendered under the assistant's reply, and says so: that reply
comes from RAG, and a manifest beneath an answer it did not produce is a
provenance claim.

## Measuring what a corpus wants

```bash
uv run python scripts/profile_corpus.py egeria_python_git --min-docs 20
```

Reads trees already in Postgres — no re-parse, no fetch — and reports per
top-level path boundary:

```
boundary       docs  u/doc  p75 unit  p75 doc  chunk  basis
sample-data     960   21.0        28     1728     28  unit
pyegeria         82   19.5       495    31260    495  unit
```

`basis` is the decision: around one unit per document means the document *is* the
unit; many means the unit is sub-document. **It reports only** — changing a chunk
size means re-embedding a corpus.

Requires `ARTIFACT_TREE_ENABLED` to have been on for an ingest of that resource.

## Collection drift

`refresh` now reports collection types a resource is eligible for but not
ingesting — a query over the file inventory, no scan:

```
Eligible but not enabled — pdfs: 15 matching file(s) (needs 1)
```

Collections are proposed once, at onboarding, and never re-evaluated, so a repo
that later gains PDFs keeps ignoring them. To act on it:

```bash
uv run resource-explorer repair enable-collection egeria_docs pdfs
```

It refuses on zero chunks rather than enabling an empty collection.

## Repair operations

```bash
uv run resource-explorer repair rename <old> <new>
uv run resource-explorer repair set-github-url <slug> <url>
uv run resource-explorer repair enable-collection <slug> <type>
uv run resource-explorer repair list-memberships <slug>
uv run resource-explorer repair repoint-membership <slug> <from-inv> <to-inv>
uv run resource-explorer repair drop-membership <slug> <investigation>
```

Also in Admin → 🔧 Repair. `rename` moves every table carrying the slug *and* the
pgvector collection names, which embed it; `set-github-url` refuses unless
confirmed, because existing collections hold content from the old URL.

## Catalog coverage

```bash
uv run python scripts/question_catalog_coverage.py          # table
uv run python scripts/question_catalog_coverage.py --json
```

Recomputes Purpose × analysis and Perspective × analysis reachability. Purpose
measures 0.22 mean pairwise overlap and Perspective 0.37 — the gap that makes
Purpose the primary dispatch axis. `Privacy` reaches zero analyses.

## Inventory export — and an overlap to resolve

```bash
uv run python scripts/export_inventory.py --no-timestamp -o inventory.json
```

Exits non-zero if the export fails verification, so a backup that captured
nothing cannot look successful.

**This overlaps existing functionality and should be consolidated.**
`resource-explorer export-resources <path.csv>` already exports repos, databases,
filesystems, groups and dispositions — with a matching `import-resources`, which
the JSON export has no equivalent of. I wrote the JSON export without checking,
and duplicated that half.

What the JSON export adds and the CSV genuinely lacks: **investigations and their
membership** (zero coverage in `batch_io.py`), servers, aliases, and a counted
manifest that `verify()` checks — an export that captured nothing otherwise reads
exactly like a correct export of an empty estate.

The right resolution is to add investigations to the CSV path rather than keep
two exports. Until then, use `export-resources` for anything you intend to import
back, and the JSON export when you need investigation membership captured.
