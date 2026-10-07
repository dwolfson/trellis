/** Resizable columns (next/colresize.js): drag, minimum, double-click reset, keyboard,
 *  persistence with storage present and with storage throwing, and never wider than the host.
 *  jsdom does no layout, so the host's visible width is stated with clientWidth. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';
import { ensureLoaderRegistered } from './dom-harness.mjs';
import { baseView, setUp, scopeEl } from './scope-test-kit.mjs';

ensureLoaderRegistered();
const { attachColumnResize, handleHtml, cellStyle } = await import('/static/next/colresize.js');

const SPEC = {
  id: 't1', nameMin: 100, chrome: 20,
  columns: [{ key: 'a', def: 100, min: 40 }, { key: 'b', def: 100, min: 40 }],
};

function make({ clientWidth = 0, storage = 'ok' } = {}) {
  const dom = new JSDOM(`<div id="host">${handleHtml(SPEC, 'a', 'A')}${handleHtml(SPEC, 'b', 'B')}</div>`, { url: 'http://localhost/' });
  const { window } = dom;
  if (storage === 'throws') {
    Object.defineProperty(window, 'localStorage', { get() { throw new window.DOMException('denied', 'SecurityError'); } });
  }
  const host = window.document.getElementById('host');
  if (clientWidth) Object.defineProperty(host, 'clientWidth', { value: clientWidth });
  const api = attachColumnResize(host, SPEC);
  const handle = (k) => host.querySelector(`[data-rc-handle="${k}"]`);
  const px = (k) => host.style.getPropertyValue(`--rc-${k}`);
  const ptr = (type, x, target = window.document) => target.dispatchEvent(new window.MouseEvent(type, { clientX: x, bubbles: true, cancelable: true }));
  const drag = (k, from, to) => { ptr('pointerdown', from, handle(k)); ptr('pointermove', to); ptr('pointerup', to); };
  const key = (k, shiftKey = false) => handle('a').dispatchEvent(new window.KeyboardEvent('keydown', { key: k, shiftKey, bubbles: true, cancelable: true }));
  return { window, host, api, handle, px, drag, key, ptr };
}

test('dragging a handle changes that column\'s width and not the other\'s', () => {
  const t = make();
  t.drag('a', 100, 160);
  assert.equal(t.px('a'), '160px');
  assert.equal(t.px('b'), '', 'the other column keeps its default');
  assert.equal(t.api.isCustom(), true);
});

test('a column never goes below its minimum width', () => {
  const t = make();
  t.drag('a', 100, -500);
  assert.equal(t.px('a'), '40px');
});

test('double-click on a handle resets that column only', () => {
  const t = make();
  t.drag('a', 100, 180); t.drag('b', 100, 150);
  t.handle('a').dispatchEvent(new t.window.MouseEvent('dblclick', { bubbles: true, cancelable: true }));
  assert.equal(t.px('a'), '', 'a is back to its default');
  assert.equal(t.px('b'), '150px', 'b is untouched');
});

test('a focused handle moves with Left/Right, Shift for larger steps', () => {
  const t = make();
  t.key('ArrowRight'); assert.equal(t.px('a'), '110px');
  t.key('ArrowRight', true); assert.equal(t.px('a'), '160px');
  t.key('ArrowLeft'); assert.equal(t.px('a'), '150px');
  t.key('ArrowLeft', true); t.key('ArrowLeft', true); t.key('ArrowLeft', true); t.key('ArrowLeft', true);
  assert.equal(t.px('a'), '40px', 'keyboard stops at the minimum too');
  assert.equal(t.handle('a').getAttribute('tabindex'), '0', 'reachable by keyboard');
  assert.equal(t.handle('a').getAttribute('aria-valuenow'), '40');
});

test('widths persist per table id, and a fresh table reads them back', () => {
  const t = make();
  t.drag('a', 100, 170);
  assert.deepEqual(JSON.parse(t.window.localStorage.getItem('re.colwidths.t1')), { a: 170 });
  // a second host in the same window (a re-drawn page) starts from the stored width
  const host2 = t.window.document.createElement('div');
  t.window.document.body.append(host2);
  attachColumnResize(host2, SPEC);
  assert.equal(host2.style.getPropertyValue('--rc-a'), '170px');
  t.api.reset();
  assert.equal(t.window.localStorage.getItem('re.colwidths.t1'), null, 'reset forgets them');
  assert.equal(t.api.isCustom(), false);
});

test('with storage throwing, the table still resizes and nothing throws', () => {
  const t = make({ storage: 'throws' });
  t.drag('a', 100, 150); t.key('ArrowRight'); t.api.reset(); t.drag('b', 100, 130);
  assert.equal(t.px('b'), '130px');
  assert.equal(t.px('a'), '');
});

test('the columns together never make the table wider than its host', () => {
  const t = make({ clientWidth: 500 });
  t.drag('a', 100, 5000);
  // 500 visible - other column 100 - name floor 100 - chrome 20 = 280
  assert.equal(t.px('a'), '280px');
  t.drag('b', 100, 5000);
  const sum = Number.parseInt(t.px('a'), 10) + Number.parseInt(t.px('b') || '100', 10) + SPEC.nameMin + SPEC.chrome;
  assert.ok(sum <= 500, `columns + name floor + chrome = ${sum}, within the 500px host`);
  assert.equal(t.px('b'), '100px', 'b cannot grow once a fills the host');
});

test('each cell carries its default as the var() fallback', () => {
  assert.equal(cellStyle(SPEC, 'a'), 'width:var(--rc-a,100px);flex:none;min-width:0');
});

test('Curate scope table: handles on the resizable headers, widths move every row, reset is live only when changed', async () => {
  const { document, window } = await setUp(baseView());
  const el = scopeEl(document);
  const host = el.querySelector('[data-scope-tree]');
  const handles = [...host.querySelectorAll('[data-scope-tree-head] [data-rc-handle]')].map((h) => h.dataset.rcHandle);
  assert.deepEqual(handles, ['choice', 'rows', 'size', 'act', 'cls', 'egeria']);
  const reset = el.querySelector('[data-rc-reset]');
  assert.equal(reset.disabled, true, 'nothing changed yet');
  const h = host.querySelector('[data-rc-handle="egeria"]');
  h.dispatchEvent(new window.MouseEvent('pointerdown', { clientX: 500, bubbles: true, cancelable: true }));
  document.dispatchEvent(new window.MouseEvent('pointermove', { clientX: 540 }));
  document.dispatchEvent(new window.MouseEvent('pointerup', { clientX: 540 }));
  assert.equal(host.style.getPropertyValue('--rc-egeria'), '300px');
  const cell = host.querySelector('[data-scope-row="schema:sales"] [data-scope-state-cell]');
  assert.match(cell.getAttribute('style'), /width:var\(--rc-egeria,260px\)/);
  assert.equal(reset.disabled, false, 'the reset control is live');
  host.querySelector('[data-scope-toggle="sales"]').click();   // a redraw keeps the width
  assert.equal(host.style.getPropertyValue('--rc-egeria'), '300px');
  assert.equal(host.querySelectorAll('[data-rc-handle]').length, 6);
  reset.click();
  assert.equal(host.style.getPropertyValue('--rc-egeria'), '');
  assert.equal(reset.disabled, true);
});
