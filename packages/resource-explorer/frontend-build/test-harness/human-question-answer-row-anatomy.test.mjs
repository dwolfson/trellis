/** Real-DOM regression test for ENRICHMENT-E0-ROW-ANATOMY
 *  (docs/design-notes/REPLY-DESIGNER-ENRICHMENT-STAGE-IA.md §0.3/§6 item 1,
 *  docs/design-notes/ENRICHMENT-E0-ROW-ANATOMY-IMPLEMENTED.md).
 *
 *  THE PROBLEM: a person's input to a resource lived in two stores with two
 *  different rules. Enrichment's judgements/observations
 *  (`state.enrichment` via `saveEnrichmentField`, rendered by
 *  `stages/enrichment.js`'s `fieldRowHtml`) always carried who, when, and
 *  the "⚠ review — evidence moved: X" flag. The Questions tab's answers to
 *  the catalog's human questions (`state.contextAnswers` via
 *  `saveQuestionAnswer`, rendered by `app.js`'s `rowInner`/`bodyLines`)
 *  carried only a timestamp — no author at all — entered through a
 *  blocking `window.prompt()`.
 *
 *  THE FIX: `row-anatomy.js`'s `personRowLineHtml` is the ONE function that
 *  builds the who + when + evidence-moved-flag line. `fieldRowHtml` (judge-
 *  ments/observations) and `rowInner`'s `st === 'human'` branch (question
 *  answers) both call it — this is proven below by rendering BOTH kinds of
 *  row through the REAL, unmodified functions and asserting each one's
 *  provenance line matches, character for character, what `personRowLineHtml`
 *  itself returns for the equivalent input. A test that only checked "does
 *  the text look similar" could pass with two lookalike implementations that
 *  drift apart later; matching the shared function's own output exactly is
 *  what proves they are genuinely ONE component.
 *
 *  Imports below are deliberately NOT cache-busted (contrast
 *  `dom-harness.mjs`'s `loadAppModule()`, which busts on purpose so each
 *  *.test.mjs file gets its own `state`): this test needs `app.js`,
 *  `stages/enrichment.js` and `row-anatomy.js` to resolve to the SAME module
 *  instances real `/next` uses (enrichment.js and row-anatomy.js both import
 *  `esc`/`state` from the literal specifier `/static/next/app.js` with no
 *  query string), so that setting a field on `state` here is visible inside
 *  `fieldRowHtml`.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, loadAppModule } from './dom-harness.mjs';

test('a judgement row (enrichment.js) and a question-answer row (app.js) render their provenance line through the SAME shared function', async () => {
  makeDomEnvironment();
  // `/static/...` specifiers only resolve once static-loader.mjs is
  // registered -- loadAppModule() does that as a side effect. Its own
  // (cache-busted) return value is discarded: this test needs the
  // UN-busted `/static/next/app.js` instance, the same one
  // stages/enrichment.js itself imports internally, so writes to `state`
  // here are visible there.
  await loadAppModule();
  const app = await import('/static/next/app.js');
  const enrichment = await import('/static/next/stages/enrichment.js');
  const { personRowLineHtml } = await import('/static/next/row-anatomy.js');
  const { questionKey } = await import('/static/re-api.js');

  // ── Judgement row: sensitivity, confirmed, with evidence moved ──────────
  app.state.enrichment = {
    sensitivity: {
      value: 'confidential', kind: 'judgement', author: 'peterprofile',
      set_at: new Date().toISOString(), source: '', interim: false,
      evidence: { cve_scan: '2020-01-01T00:00:00Z' },  // older than any fact -> "moved"
    },
  };
  app.state.enrichmentFacts = { cve_scan: { last_run_at: new Date().toISOString() } };

  const judgementDef = { key: 'sensitivity', label: 'Sensitivity', options: ['public', 'internal', 'confidential', 'restricted'] };
  const judgementRowHtml = enrichment.fieldRowHtml(judgementDef, 'judgement');

  const expectedJudgementProvenance = personRowLineHtml({
    author: 'peterprofile',
    whenIso: app.state.enrichment.sensitivity.set_at,
    moved: ['cve_scan'],
  });
  assert.ok(expectedJudgementProvenance.includes('⚠ review — evidence moved: cve_scan'));
  assert.ok(
    judgementRowHtml.includes(expectedJudgementProvenance),
    'fieldRowHtml\'s provenance line must be exactly what personRowLineHtml produces for the same input',
  );

  // ── Question-answer row: a human-question answer, author-stamped ───────
  const question = 'Do we already support these dependencies?';
  app.state.contextAnswers = {
    [questionKey(question)]: {
      question, answer: 'Yes, two teams do.',
      answered_at: new Date().toISOString(), answered_by: 'peterprofile',
    },
  };
  app.state.runsInFlight = new Map();
  app.state.pendingProposals = new Map();
  app.state.editingAnswer = '';

  const entry = { question, kind: 'human', note: '', answering_mechanism: '', analysis_ids: [], perspectives: [] };
  const questionRowHtml = app.rowInner(entry, 0, {});

  const expectedAnswerProvenance = personRowLineHtml({
    author: 'peterprofile',
    whenIso: app.state.contextAnswers[Object.keys(app.state.contextAnswers)[0]].answered_at,
    verb: 'answered by',
  });
  assert.ok(
    questionRowHtml.includes(expectedAnswerProvenance),
    'the question row\'s provenance line must be exactly what personRowLineHtml produces for the same input -- ' +
    'same anatomy as the judgement row above, through the same function, not a lookalike',
  );

  // Both rows carry who AND when -- the row anatomy the design reply
  // requires (§0.3's table: judgements had both, question answers had
  // neither). Render each into a real DOM container and check visually,
  // not just in the raw HTML string.
  const { document } = makeDomEnvironment();
  const jHost = document.createElement('div');
  jHost.innerHTML = judgementRowHtml;
  document.body.appendChild(jHost);
  assert.match(jHost.textContent, /peterprofile/, 'judgement row must show WHO');
  assert.match(jHost.textContent, /just now|ago/, 'judgement row must show WHEN');

  const qHost = document.createElement('div');
  qHost.innerHTML = questionRowHtml;
  document.body.appendChild(qHost);
  assert.match(qHost.textContent, /answered by peterprofile/, 'question-answer row must show WHO, with the gate\'s exact wording');
  assert.match(qHost.textContent, /just now|ago/, 'question-answer row must show WHEN');
});

test('the gate scenario: a freshly-answered question renders "answered by <user> · just now"', async () => {
  makeDomEnvironment();
  const app = await loadAppModule();  // a fresh, isolated instance is fine here -- single-module test

  const question = 'What does it cost to run?';
  const key = 'what-does-it-cost-to-run';
  app.state.contextAnswers = {
    [key]: { question, answer: '$200/mo', answered_at: new Date().toISOString(), answered_by: 'dan' },
  };
  app.state.runsInFlight = new Map();
  app.state.pendingProposals = new Map();
  app.state.editingAnswer = '';

  const entry = { question, kind: 'human', note: '', answering_mechanism: '', analysis_ids: [], perspectives: [] };
  const html = app.rowInner(entry, 0, {});
  // "just now" renders inside a `<span class="tnum">` (same convention every
  // other relative-time render in `/next` uses) -- match through that span
  // rather than requiring literal adjacency.
  assert.match(html, /answered by dan\s*·\s*<span class="tnum">just now<\/span>/, `gate wording not found in: ${html}`);
  assert.match(html.replace(/<[^>]+>/g, ''), /answered by dan\s*·\s*just now/, 'plain-text reading must also say it');
});

test('a legacy answer with no recorded author degrades gracefully (no blank "· 2d ago" author slot)', async () => {
  makeDomEnvironment();
  const app = await loadAppModule();

  const question = 'Does it fit our estate?';
  const key = 'does-it-fit-our-estate';
  app.state.contextAnswers = {
    [key]: { question, answer: 'Yes.', answered_at: new Date().toISOString() },  // no answered_by
  };
  app.state.runsInFlight = new Map();
  app.state.pendingProposals = new Map();
  app.state.editingAnswer = '';

  const entry = { question, kind: 'human', note: '', answering_mechanism: '', analysis_ids: [], perspectives: [] };
  const html = app.rowInner(entry, 0, {});
  assert.match(html, /answered\s+just now/);
  assert.doesNotMatch(html, /answered by\s*·/, 'must not render an empty author slot');
});
