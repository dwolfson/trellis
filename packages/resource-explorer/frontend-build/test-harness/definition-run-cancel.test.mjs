/** Cancel on a definition's Egeria-coordinated run (DESIGN-ENGINE-HOST-GOVERNANCE-ENGINE-API §2.4; designer words Q4,
 *  2026-10-17). "Cancel run" sits on its own line under the run line, only when the server offers it to this reader
 *  (owner Q2/Q3); the confirm is in place; every cue comes from the server's row (the press's proof row and Egeria's
 *  read-back), never from the click. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const QN = 'GovActionProcess::DatabaseAnalysisSurvey';
const GUID = '06994d5d-a228-408c-8842-fd6256db4c34';
const ctx = { running: { step: 2, label: 'postgres_operations' }, cancelled_step: null,
  later: ['db_derived', 'nested_columns'], finished: ['postgres_column_profile'], finished_count: 1, of: 4 };
const run = (over = {}) => ({ state: 'running', line: 'Database Analysis Survey · step 1 ✓ · step 2 running', egeria_status: 'IN_PROGRESS',
  engine_action_guid: GUID, submitted_at: '2026-10-17T09:00:00', read_at: '2026-10-17T09:05:00', error: '', steps: [],
  cancel_context: ctx, ...over });
const row = (r = run(), pc = {}) => ({ qualified_name: QN, display_name: 'Database Analysis Survey', kind: 're_definition',
  runnable: true, in_flight: ['running', 'submitted'].includes(r.state), run: r,
  process_cancel: { offered: false, outside: false, finishing: null, viewer: 'dan', ...pc } });
const norm = (el) => el.textContent.replace(/\s+/g, ' ').trim();

async function setUp() {
  const { document } = makeDomEnvironment();
  ensureLoaderRegistered();
  await import('/static/next/app.js');
  const ns = await import('/static/next/stages/native-surveys.js');
  return { document, ns };
}
function draw(document, ns, r) {
  const box = document.createElement('div');
  box.innerHTML = ns.definitionRunLineHtml(r);
  document.body.appendChild(box);
  return box;
}

test('"Cancel run" is on its own line, only when the server offers it to this reader', async () => {
  const { document, ns } = await setUp();
  const on = draw(document, ns, row(run(), { offered: true }));
  const btn = on.querySelector('[data-process-cancel]');
  assert.equal(btn.textContent.trim(), 'Cancel run');
  assert.equal(btn.closest('[data-process-cancel-box]').tagName, 'DIV', 'its own line, not beside "check now"');
  assert.equal(draw(document, ns, row(run(), { offered: false })).querySelector('[data-process-cancel]'), null);
  assert.equal(draw(document, ns, row(run({ engine_action_guid: '' }), { offered: true })).querySelector('[data-process-cancel]'), null);
});

test('the confirm names the step, what will not start and what keeps its report; unknown step has its own words', async () => {
  const { ns } = await setUp();
  assert.equal(ns.PROCESS_CANCEL_WORDS.confirm(ctx),
    "Cancel this run? Step 2, postgres_operations, finishes but publishes nothing, and db_derived and nested_columns won't start. Postgres_column_profile keeps its report.");
  assert.equal(ns.PROCESS_CANCEL_WORDS.confirm({ running: null }),
    'Cancel this run? The running step finishes but publishes nothing, and no later step starts. Finished steps keep their reports.');
});

test('press shows the confirm in place with "Yes, cancel" · "keep running"; keep running puts the control back', async () => {
  const { document, ns } = await setUp();
  const box = draw(document, ns, row(run(), { offered: true }));
  ns.bindRunLineControls(box, 'coco_pharma', {});
  box.querySelector('[data-process-cancel]').click();
  const conf = box.querySelector('[data-process-cancel-confirm]');
  assert.equal(conf.hidden, false);
  assert.match(norm(conf), /Yes, cancel/);
  assert.match(norm(conf), /keep running/);
  box.querySelector('[data-process-cancel-no]').click();
  assert.equal(conf.hidden, true);
  assert.equal(box.querySelector('[data-process-cancel]').hidden, false);
});

test('each cue reads from the row: pending, finishing, done, done outside, too late, not permitted, not sent, outside', async () => {
  const { document, ns } = await setUp();
  const pending = norm(draw(document, ns, row(run({ cancel: { state: 'pending', by: 'dan', at: '2026-10-17T09:06:00' } }))));
  assert.match(pending, /cancel requested by you · \d\d:\d\d · waiting for Egeria · step 2, postgres_operations, finishes first/);
  const other = norm(draw(document, ns, row(run({ cancel: { state: 'pending', by: 'peter', at: '2026-10-17T09:06:00' } }))));
  assert.match(other, /cancel requested by peter/);
  const cancelled = run({ state: 'failed', egeria_status: 'CANCELLED', cancel: { state: 'done', by: 'dan', at: '2026-10-17T09:06:00', finished: 1, of: 4 } });
  assert.match(norm(draw(document, ns, row(cancelled))), /⊘ cancelled by dan · \d\d:\d\d · 1 of 4 steps finished/);
  assert.match(norm(draw(document, ns, row(cancelled, { finishing: { step: 2, label: 'postgres_operations' } }))),
    /⊘ cancelled · step 2, postgres_operations, is finishing and will publish nothing/);
  const outside = run({ state: 'failed', egeria_status: 'CANCELLED', cancel: { state: 'done', outside: true, at: '2026-10-17T09:06:00', finished: 1, of: 4 } });
  assert.match(norm(draw(document, ns, row(outside))), /⊘ cancelled in Egeria · \d\d:\d\d · not from Resource Explorer/);
  assert.match(norm(draw(document, ns, row(run({ cancel: { state: 'refused', kind: 'too_late', by: 'dan' } })))),
    /too late to cancel · the run had already finished/);
  assert.match(norm(draw(document, ns, row(run({ cancel: { state: 'refused', kind: 'not_permitted', by: 'peter', reason: 'OMAG-403 not permitted' } })))),
    /Egeria won't let peter cancel this run · OMAG-403 not permitted/);
  const unsent = norm(draw(document, ns, row(run({ cancel: { state: 'unsent', by: 'dan' } }))));
  assert.match(unsent, /cancel not sent · couldn't reach Egeria · try again/);
  assert.doesNotMatch(unsent, /refused/);
  const out = draw(document, ns, row(run(), { outside: true })).querySelector('[data-process-cancel-outside]');
  assert.equal(norm(out), 'started outside Resource Explorer');
  assert.equal(out.getAttribute('title'), 'RE can cancel only runs it started; cancel this one in Egeria');
});
