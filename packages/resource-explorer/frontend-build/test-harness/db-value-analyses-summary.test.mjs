/** D1 (DB-RESULTS-READERS): the By-analysis pane renders the three value-reading
 *  analyses (data_class_match, reference_data_match, nested_column_profile)
 *  through its GENERIC mechanism -- the board's headline sentence, the COUNTS
 *  table and boardStateKey -- with no UI change. The fixtures below are the
 *  payloads `build_survey_results(..., board_id=...)` returns for a database
 *  (copied from tests/test_db_value_analyses_results_readers.py's real
 *  readers, `columns` trimmed), so a change to a reader's field names that
 *  the pane would stop rendering is caught here, not on the gate.
 *
 *  The properties pinned:
 *   - a stored result shows its headline (which is what keeps the card's
 *     "ran; no summary reader yet." fallback from appearing) and its counts;
 *   - a real zero prints as 0 in the COUNTS table (measured zero);
 *   - a run that established nothing shows the "?" glyph and carries NO match
 *     counts, so "not measured" is never drawn as 0;
 *   - a board never run reads as unrun, not as a zero.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, loadAppModule } from './dom-harness.mjs';

const T = '2026-10-02T10:00:00';

const stored = {
  id: 'data_class_match', has_results: true, last_surveyed_at: T,
  analyses: [{
    analysis_id: 'data_class_match', last_surveyed_at: T,
    headline: { label: '1 of 2 columns tested matched a known Data Class — 1 had no match', status: 'info' },
    results: {
      surveyed_at: T, column_count: 2, established_count: 2, not_established_count: 0,
      not_applicable_count: 0, matched_count: 1, no_match_count: 1, proposed_count: 0,
      privacy_relevant_count: 0, verdict_counts: { matched: 1, no_match: 1 },
    },
  }],
};

const zero = {
  id: 'reference_data_match', has_results: true, last_surveyed_at: T,
  analyses: [{
    analysis_id: 'reference_data_match', last_surveyed_at: T,
    headline: { label: '0 of 3 low-cardinality columns tested matched a known Valid Value Set — 3 had no match', status: 'info' },
    results: {
      surveyed_at: T, column_count: 3, established_count: 3, not_established_count: 0,
      not_applicable_count: 0, matched_count: 0, no_match_count: 3, proposed_count: 0, partial_count: 0,
      _status: { state: 'nothing_found' },
    },
  }],
};

const notEstablished = {
  id: 'data_class_match', has_results: true, last_surveyed_at: T,
  analyses: [{
    analysis_id: 'data_class_match', last_surveyed_at: T,
    headline: { label: "Not established — 1 of 1 column(s) could not be tested: the Egeria platform's Data Classes could not be read", status: 'info' },
    results: {
      surveyed_at: T, state: 'not_established', column_count: 1, not_established_count: 1,
      not_applicable_count: 0, verdict_counts: { no_candidates: 1 },
      explanation: "1 of 1 column(s) could not be tested: the Egeria platform's Data Classes could not be read",
      _status: { state: 'not_established', reason: 'nothing_established' },
    },
  }],
};

const neverRun = {
  id: 'nested_column_profile', has_results: false, last_surveyed_at: '',
  analyses: [{
    analysis_id: 'nested_column_profile', headline: null,
    results: { _status: { state: 'not_established', reason: 'no_stored_result' } },
  }],
};

test('a stored result renders its counts and is a measured board', async () => {
  const { document } = makeDomEnvironment();
  const app = await loadAppModule();
  assert.equal(app.boardStateKey({ status: 'done', board: stored }), 'measured');
  const host = document.createElement('div');
  host.innerHTML = app.boardCountsHtml(stored, new Set());
  const text = host.textContent;
  assert.match(text, /matched count\s*1/);
  assert.match(text, /no match count\s*1/);
});

test('a real zero is printed as 0, not hidden', async () => {
  const { document } = makeDomEnvironment();
  const app = await loadAppModule();
  const host = document.createElement('div');
  host.innerHTML = app.boardCountsHtml(zero, new Set());
  assert.match(host.textContent, /matched count\s*0/);
  assert.match(host.textContent, /no match count\s*3/);
});

test('a run that established nothing is "?" and prints no match counts', async () => {
  const { document } = makeDomEnvironment();
  const app = await loadAppModule();
  assert.equal(app.boardStateKey({ status: 'done', board: notEstablished }), 'not_established');
  const host = document.createElement('div');
  host.innerHTML = app.boardCountsHtml(notEstablished, new Set());
  assert.doesNotMatch(host.textContent, /matched count/);
  assert.doesNotMatch(host.textContent, /no match count/);
  assert.match(host.textContent, /not established count\s*1/);

  document.body.innerHTML = '<div id="by-analysis-contents"></div>';
  const boards = [{ id: 'data_class_match', title: 'Data Class Match', description: '' }];
  app.renderByAnalysisContents('coco', boards,
    new Map([['data_class_match', { status: 'done', board: notEstablished }]]), 1, 1, new Map());
  const row = document.querySelector('[data-jump-board="data_class_match"]');
  assert.equal(row.querySelector('.font-glyph').textContent, '?');
  assert.match(row.textContent, /Data Classes could not be read/);
});

test('a board never run reads as unrun and shows no counts or headline', async () => {
  const { document } = makeDomEnvironment();
  const app = await loadAppModule();
  assert.equal(app.boardStateKey({ status: 'done', board: neverRun }), 'unrun');
  assert.equal(app.boardCountsHtml(neverRun, new Set()), '');
  document.body.innerHTML = '<div id="by-analysis-contents"></div>';
  const boards = [{ id: 'nested_column_profile', title: 'Nested Column Profile', description: '' }];
  app.renderByAnalysisContents('coco', boards,
    new Map([['nested_column_profile', { status: 'done', board: neverRun }]]), 1, 1, new Map());
  const row = document.querySelector('[data-jump-board="nested_column_profile"]');
  assert.equal(row.querySelector('.truncate').textContent.trim(), '');
});

test('the card\'s "no summary reader yet" fallback is only for a board with results and no headline', async () => {
  // byAnalysisCardHtml is module-private; pin the gate on the source it runs from.
  const { readFileSync } = await import('node:fs');
  const src = readFileSync(new URL('../../resource_explorer/web/static/next/app.js', import.meta.url), 'utf8');
  assert.match(src, /boardHeadlineHtml\(board\) \|\| \(board && board\.has_results\s*\?\s*'<span class="text-ink-muted">ran; no summary reader yet\./);
  for (const b of [stored, zero, notEstablished]) {
    assert.ok(b.analyses[0].headline && b.analyses[0].headline.label, `${b.id} carries a headline`);
  }
});
