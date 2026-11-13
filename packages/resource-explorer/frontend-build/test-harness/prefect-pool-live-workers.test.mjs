/** 2026-11-13 (BRIEF-RE-PREFECT-POOL-LIVE-WORKERS): the shell banner's Prefect pool line. The server counts LIVE
 *  workers, not registrations; with none live the banner says so in the server's own words, and says what runs in
 *  Resource Explorer's process instead (nothing waits). An unread or unreachable pool claims nothing.
 *  Real module; nothing stubbed but the status object. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

ensureLoaderRegistered();
const text = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();

const RUNS_LOCALLY = 'Prefect-dispatched steps (Soda data-quality, Great Expectations validation, any step marked '
  + "executes_at=prefect) run in Resource Explorer's process instead: no Prefect run history, retries or cancel.";
const POOL = (over = {}) => ({ reachable: true, live_count: 0, registered_count: 3, never_heard_from: 0, worker_count: 0,
  summary: 'no live worker: 3 registered, last heartbeat 32 days ago (2026-10-12T12:17:00Z)',
  runs_locally_instead: ['Soda data-quality'], runs_locally_words: RUNS_LOCALLY, ...over });
const B = { display_name: 'Foundations', state: 'present', present: true, last_healed_at: '', last_heal_result: '' };
const STATUS = (pool, over = {}) => ({ reinitializing: false, healing: '', egeria_reachable: true,
  batches: { foundations: B }, prefect_pool: pool, ...over });

async function loadShell() {
  const { document } = makeDomEnvironment();
  const mod = await import(`/static/next/shell-status.js?t=${Math.random()}`);
  return { document, mod };
}

test('no live worker: one warning line in the server words, with what runs locally instead, and no run button', async () => {
  const { document, mod } = await loadShell();
  mod.renderBootstrapBanner(document, STATUS(POOL()));
  const bar = document.getElementById('bootstrap-banner');
  assert.ok(bar, 'a pool with no live worker is never only a log line');
  const lines = bar.querySelectorAll('[data-prefect-pool-line]');
  assert.equal(lines.length, 1);
  assert.equal(text(bar.querySelector('[data-prefect-pool-word]')),
    'Prefect: no live worker: 3 registered, last heartbeat 32 days ago (2026-10-12T12:17:00Z)');
  assert.equal(text(bar.querySelector('[data-prefect-pool-runs-locally]')), RUNS_LOCALLY);
  assert.doesNotMatch(text(bar), /will wait|cannot run|not run/, 'nothing waits: the steps run locally');
  assert.equal(bar.querySelector('[data-bootstrap-run]'), null, 'a bootstrap run does not start a worker');
  assert.equal(bar.dataset.bootstrapKind, 'prefect-pool');
});

test('a live pool, an unread pool and an unreachable one draw no pool line', async () => {
  const { document, mod } = await loadShell();
  for (const pool of [POOL({ live_count: 1, summary: '1 live worker(s) of 3 registered; last heartbeat 20 seconds ago' }),
    undefined, POOL({ reachable: null, live_count: null }), POOL({ reachable: false, live_count: null })]) {
    mod.renderBootstrapBanner(document, STATUS(pool));
    assert.equal(document.getElementById('bootstrap-banner'), null, JSON.stringify(pool));
  }
});

test('the pool line rides along with a missing batch, and clears when a worker is live again', async () => {
  const { document, mod } = await loadShell();
  const missing = { foundations: { ...B, state: 'missing', present: false } };
  mod.renderBootstrapBanner(document, STATUS(POOL(), { batches: missing }));
  const bar = document.getElementById('bootstrap-banner');
  assert.ok(bar.querySelector('[data-prefect-pool-line]') && bar.querySelector('[data-bootstrap-run]'));
  mod.renderBootstrapBanner(document, STATUS(POOL({ live_count: 1 })));
  assert.equal(document.getElementById('bootstrap-banner'), null);
});

test('server text reaches the page as text, never markup', async () => {
  const { document, mod } = await loadShell();
  mod.renderBootstrapBanner(document, STATUS(POOL({ summary: '<img src=x onerror=alert(1)>', runs_locally_words: '<b>x</b>' })));
  const bar = document.getElementById('bootstrap-banner');
  assert.equal(bar.querySelector('img'), null);
  assert.equal(bar.querySelector('b'), null);
});
