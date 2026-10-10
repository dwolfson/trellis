/** Behaviour: Brief D 7f.8 -- the run's publish word.
 *
 *  The adaptive step records `publish_state` in its detail ("published to
 *  Egeria" / "publish failed · <why>" / "local only · publish not chosen").
 *  `answered_by` says only which scan answered, so a failure and a publish
 *  nobody chose both read "local scan". Each step row now also carries a cue
 *  (glyph) plus a short word, with the full sentence on demand.
 *
 *  Real app.js; only fetch is stubbed. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();
const dlgOf = (document) => document.getElementById('wl-detail');

async function setUp(steps) {
  const { document, window } = makeDomEnvironment();
  const detail = JSON.stringify({ steps });
  const runs = [{ id: 'r1', operation: 'survey', ts: new Date().toISOString(), status: 'ok', summary: 'Done', detail }];
  globalThis.fetch = async (url) => {
    const u = String(url);
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    if (u.startsWith('/api/activity/?entity_slug=')) return ok(runs);
    return ok(u.includes('/groups') ? [] : {});
  };
  ensureLoaderRegistered();
  globalThis.location = window.location;
  globalThis.getComputedStyle = window.getComputedStyle.bind(window);
  globalThis.history = window.history;
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const api = await import('/static/re-api.js');
  api.clearCache();
  const app = await import('/static/next/app.js');
  return { document, app };
}

const stepRow = (document, name) =>
  [...dlgOf(document).querySelectorAll('li')].find((li) => li.textContent.includes(name));

test('a published step, a failed publish and a publish nobody chose each read differently', async () => {
  const { document, app } = await setUp([
    { step: 'S::pub', status: 'ok', answered_by: 'egeria-custom',
      detail: { source: 'egeria-custom', publish_state: 'published to Egeria' } },
    { step: 'S::bad', status: 'ok', answered_by: 'custom',
      detail: { source: 'custom', publish_state: 'publish failed · Egeria said no' } },
    { step: 'S::none', status: 'ok', answered_by: 'custom',
      detail: { source: 'custom', publish_state: 'local only · publish not chosen' } },
  ]);
  await app.openRunsList('coco');

  const pub = stepRow(document, 'pub').querySelector('[data-step-publish]');
  const bad = stepRow(document, 'bad').querySelector('[data-step-publish]');
  const none = stepRow(document, 'none').querySelector('[data-step-publish]');
  assert.equal(pub.dataset.stepPublish, 'measured');
  assert.equal(bad.dataset.stepPublish, 'error');
  assert.equal(none.dataset.stepPublish, 'unclassified');
  assert.match(text(pub), /^✓ published$/);
  assert.match(text(bad), /^✕ publish failed$/);
  assert.match(text(none), /^· not published$/);
  // the sentence is on demand, not on the row
  assert.equal(bad.getAttribute('title'), 'publish failed · Egeria said no');
  assert.doesNotMatch(text(stepRow(document, 'bad')), /Egeria said no/);
  // a failure and a not-chosen no longer look alike
  assert.notEqual(text(bad), text(none));
  // the answer source is still there beside it
  assert.match(text(stepRow(document, 'bad')), /answered by local scan/);
});

test('a step with no publish_state draws no publish word', async () => {
  const { document, app } = await setUp([
    { step: 'S::plain', status: 'ok', answered_by: 'local' },
    { step: 'S::str', status: 'ok', answered_by: 'local', detail: 'a plain string detail' },
  ]);
  await app.openRunsList('coco');
  assert.equal(dlgOf(document).querySelectorAll('[data-step-publish]').length, 0);
});

test('a failed publish on a step that records no answered_by still shows the word', async () => {
  const { document, app } = await setUp([
    { step: 'S::only', status: 'ok', detail: { publish_state: 'publish failed · boom' } },
  ]);
  await app.openRunsList('coco');
  assert.match(text(stepRow(document, 'only')), /✕ publish failed/);
});
