/** Engine host case 3: the "coordinated by Egeria" control beside a Survey Definition's Run (owner, 2026-10-15).
 *  Never labelled "run in Egeria". Hidden, with a short reason, when the server says it cannot be offered. Its state
 *  is on the control: pressed -> starting -> started, or not started with the sentence on demand; "started" comes
 *  from the server's answer (derived from the persisted row), never from the click. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

ensureLoaderRegistered();
makeDomEnvironment();
const ns = await import('/static/next/stages/native-surveys.js');
const text = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const QN = 'GovActionProcess::DatabaseAnalysisSurvey';
const cand = (ctl) => ({ qualified_name: QN, display_name: 'Database Analysis Survey',
  coordinated_by_egeria: { label: 'coordinated by Egeria', available: true, why_not: '', state: '', line: '', ...ctl } });

test('available: one button labelled "coordinated by Egeria", never "run in Egeria"', () => {
  const h = ns.coordinateControlHtml(cand({}));
  assert.match(h, /data-coordinate-egeria="GovActionProcess::DatabaseAnalysisSurvey"/);
  assert.equal(text(h), 'coordinated by Egeria');
  assert.doesNotMatch(text(h).toLowerCase(), /run in egeria/);
});

test('engine host off: no button, the short reason instead', () => {
  const h = ns.coordinateControlHtml(cand({ available: false, why_not: 'engine host off' }));
  assert.doesNotMatch(h, /data-coordinate-egeria=/);
  assert.match(h, /data-coordinate-off=/);
  assert.match(text(h), /coordinated by Egeria · engine host off/);
});

test('a run Egeria is coordinating shows on the control, from the persisted state', () => {
  const h = ns.coordinateControlHtml(cand({ state: 'running', line: 'Database Analysis Survey · step 1 ... running' }));
  assert.match(h, /disabled/);
  assert.match(h, /aria-pressed="true"/);
  assert.match(text(h), /◔ coordinated by Egeria · running/);
});

test('no server answer about the control: nothing is drawn', () => {
  assert.equal(ns.coordinateControlHtml({ qualified_name: QN }), '');
});
