# IMPLEMENTED

## Environment confirmation
resource_explorer resolves to `/Users/dwolfson/localGit/egeria-v6/trellis-re-arch-relabel/packages/resource-explorer/resource_explorer/__init__.py` (via `../../.venv`). Signed test commit showed `G`, dropped.

## What changed: bare-confidence-percentage sweep
Genuine hits, fixed to "confidence N%":
1. `next/stages/curate.js` ~473, PROPOSAL row "found by ... reading · N%" -> "reading · confidence N%". This row shows `p.type` only when present (no untyped placeholder), so only the confidence labelling applies; no "type not assigned" wording.
2. `index.html` ~4327, classic evidence line `(${e.confidence}%)` -> `(confidence ${e.confidence}%)`. Not on the original list; found by the sweep.

## Locations checked
Already fixed earlier on this branch (confirmed labelled): `arch_recovery/mermaid.py:167`, `index.html:4360`, `curate.js:483` (both branches), `curate.js:942` ("at or below 50% confidence").

False positives, left alone:
- `curate.js:449` "N at or below 50%": a count of components under the low-confidence threshold with a warning glyph, not a score. Context (a branch badge beside the count) names the threshold, and the sibling line 942 labels it. Left as is.
- `index.html:12967` file-type share pct; `13005`/`15130` null_pct; `13564`/`13582` portability rating; `14185` context-budget packed pct; `15056` classified-count share: all unrelated percentages.
- `next/worklist.js:776-788` digest bar widths and share: progress/share.
- `next/app.js:1668` comment; `app.js:5964/6039` `confidence` analysis key rendered as a plain number with no `%`.
- `next/stages/enrichment.js` probe seconds; `next/admin/discovery_sources.js` config key.
- Python: `mermaid.py:443` (labelled), `db_derived.py:873` (signal coverage, not confidence), `survey_definition_adapter.py:1089` (coverage), `column_matching.py` `confidence=int(round(100*...))` (data fields, not display strings), `exclusion.py`, `cii_badge.py`, `chaoss_metrics.py`, `documentation.py`, `repo_role.py`, `health_agent.py`, `agents/tools.py`, `sampling.py` and the `LIKE '%'` SQL patterns: shares, ratios, SQL.
- `vendor/*.min.js`: third-party, excluded.
No server-side Python code builds a user-facing bare confidence percentage outside mermaid.py.

## Tests
Added to `tests/test_confidence_relabel_outside_diagram.py`: `test_next_curate_proposal_row_labels_confidence`, `test_classic_evidence_line_labels_confidence`.
- Revert proof: with the two static files stashed (by path), both new tests fail (2 failed, 2 passed); restored, 4 passed.
- Confidence tests + test_arch_mermaid: 57 passed. `-k "curate or next or confidence or mermaid or arch"`: 1403 passed, 12 skipped.
- /next render harness, Node 20.11.0 (`npm ci` first): 168/168 pass.
