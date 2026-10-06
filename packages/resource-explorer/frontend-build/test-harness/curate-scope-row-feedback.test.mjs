/** A choice press is seen at once, on the row, in its visible left part: a state mark (shape and
 *  position, never a new accent colour), a short word, a flash on success, a pressed look while the
 *  write is in flight (a second press is ignored), a rollback with a visible 'not saved' on failure,
 *  and all of it in the same render as the PUT's answer, before the scope is read again. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { baseView, setUp, row, flat, wait, calls, person } from './scope-test-kit.mjs';

const PREVIEW = { manifest: { lines: [] }, can_commit: false, blockers: [], button: 'Catalog · 0 schemas', leave_out: [], refused: [], collisions: [] };
async function open(view, opts) {
  const ctx = await setUp(view, opts);
  ctx.server.preview = PREVIEW;
  return ctx;
}
const choiceCell = (d, key) => row(d, key).querySelector('[data-scope-choice-cell]');
const press = (d, key, choice) => row(d, key).querySelector(`[data-scope-act="set"][data-scope-choice="${choice}"]`).click();
const hold = () => { let release; const p = new Promise((r) => { release = r; }); return [p, release]; };

test('a one-line legend above the table names the three marks', async () => {
  const { document } = await open(baseView());
  const lg = document.querySelector('[data-scope-legend]');
  assert.ok(lg);
  assert.match(flat(lg), /^● catalog · ⊘ left out \(struck through\) · ○ undecided$/);
});

test('every row carries a mark: hollow when undecided, filled when catalog, struck with a "left out" badge when left out', async () => {
  const v = baseView();
  v.schemas[0].explicit = person('catalogue'); v.schemas[0].effective = 'catalogue'; v.schemas[0].state = 'chosen';
  v.schemas[1].explicit = person('leave_out'); v.schemas[1].effective = 'leave_out'; v.schemas[1].state = 'chosen';
  const { document } = await open(v);
  const mark = (k) => row(document, k).querySelector('[data-scope-mark]');
  assert.equal(mark('schema:sales').dataset.scopeMark, 'catalogue');
  assert.equal(mark('schema:sales').textContent, '●');
  assert.equal(mark('schema:sales').getAttribute('aria-label'), 'catalog');
  assert.equal(mark('schema:archive').dataset.scopeMark, 'leave_out');
  assert.equal(mark('schema:archive').textContent, '⊘');
  assert.match(flat(choiceCell(document, 'schema:archive').querySelector('[data-scope-badge]')), /^left out$/);
  assert.equal(mark('schema:empty_one').dataset.scopeMark, 'none');
  assert.equal(mark('schema:empty_one').textContent, '○');
  assert.equal(mark('schema:empty_one').getAttribute('aria-label'), 'undecided');
  assert.ok(row(document, 'schema:sales').className.includes('border-l-ink'));
  assert.ok(row(document, 'schema:archive').className.includes('border-l-rule-strong'));
  assert.ok(row(document, 'schema:archive').querySelector('[data-scope-name-cell]').className.includes('line-through'));
  assert.ok(row(document, 'schema:empty_one').className.includes('border-l-transparent'));
  for (const k of ['schema:sales', 'schema:archive', 'schema:empty_one']) {
    assert.ok(!/accent/.test(row(document, k).className + mark(k).className), 'state never uses an accent colour');
  }
});

test('on press the row changes at once: new mark, strip, "saving…", pressed controls disabled', async () => {
  const ctx = await open(baseView());
  const [gate] = [hold()]; ctx.server.holdPut = gate[0];
  press(ctx.document, 'schema:sales', 'leave_out');
  await wait(15);
  const r = row(ctx.document, 'schema:sales');
  assert.equal(r.querySelector('[data-scope-mark]').dataset.scopeMark, 'leave_out');
  assert.ok(r.className.includes('border-l-rule-strong'));
  assert.match(flat(choiceCell(ctx.document, 'schema:sales')), /saving…/);
  const btns = [...r.querySelectorAll('[data-scope-act]')];
  assert.ok(btns.length && btns.every((b) => b.disabled), 'controls look pressed and cannot be pressed again');
  assert.equal(choiceCell(ctx.document, 'schema:sales').getAttribute('aria-busy'), 'true');
  gate[1]();
  await wait(60);
});

test('a second press on the same row while the first is out sends no second PUT', async () => {
  const ctx = await open(baseView());
  const g = hold(); ctx.server.holdPut = g[0];
  press(ctx.document, 'schema:sales', 'leave_out');
  await wait(15);
  row(ctx.document, 'schema:sales').querySelector('[data-scope-act="set"][data-scope-choice="leave_out"]').click();
  row(ctx.document, 'schema:sales').querySelector('[data-scope-act="set"][data-scope-choice="catalogue"]').click();
  g[1]();
  await wait(80);
  assert.equal(calls(ctx.server, 'PUT', '/node').length, 1);
  // and a different row is not blocked
  press(ctx.document, 'schema:archive', 'catalogue');
  await wait(60);
  assert.equal(calls(ctx.server, 'PUT', '/node').length, 2);
});

test('the cell already shows the new state and "saved" when the PUT has answered and the scope GET is still pending', async () => {
  const ctx = await open(baseView());
  const g = hold(); ctx.server.holdGet = null; ctx.server.holdPut = g[0];
  press(ctx.document, 'schema:sales', 'catalogue');
  await wait(15);
  const getGate = hold();
  ctx.server.holdGet = getGate[0];       // from now on the scope read hangs
  g[1]();
  await wait(60);
  const cell = choiceCell(ctx.document, 'schema:sales');
  assert.equal(cell.querySelector('[data-scope-mark]').dataset.scopeMark, 'catalogue');
  const note = cell.querySelector('[data-scope-saved-note]');
  assert.ok(note, 'the short word is there before the re-read');
  assert.equal(flat(note), 'saved');
  assert.match(note.title, /^saved in Resource Explorer · me · .* · not yet cataloged in Egeria$/);
  assert.ok(row(ctx.document, 'schema:sales').className.includes('bg-paper-surface'), 'the row flashes on success');
  assert.equal(calls(ctx.server, 'GET', '/api/catalogue-scope/adventureworks').filter((c) => !c.url.includes('/commit')).length >= 2, true);
  getGate[1]();
  await wait(80);
});

test('the flash is brief', async () => {
  const mod = await import('/static/next/stages/curate-scope.js');
  mod.setFlashMs(40);
  const ctx = await open(baseView());
  press(ctx.document, 'schema:sales', 'catalogue');
  await wait(25);
  assert.ok(row(ctx.document, 'schema:sales').className.includes('bg-paper-surface'));
  await wait(120);
  assert.ok(!row(ctx.document, 'schema:sales').className.includes('bg-paper-surface'));
  mod.setFlashMs(1500);
});

test('a failed write puts the row back and says "not saved" on it', async () => {
  const ctx = await open(baseView());
  ctx.server.failPut = 'disk is full';
  press(ctx.document, 'schema:sales', 'leave_out');
  await wait(80);
  const r = row(ctx.document, 'schema:sales');
  assert.equal(r.querySelector('[data-scope-mark]').dataset.scopeMark, 'none', 'back to what it was');
  assert.ok(r.className.includes('border-l-transparent'));
  assert.match(flat(r.querySelector('[data-scope-not-saved]')), /^✕ not saved/);
  assert.equal(r.querySelector('[data-scope-saving]'), null);
  assert.ok([...r.querySelectorAll('[data-scope-act]')].every((b) => !b.disabled), 'and it can be pressed again');
  assert.match(flat(ctx.document.querySelector('[data-scope-status]')), /disk is full/);
});

test('a bulk press shows the new state on the ticked rows at once, and a second bulk press is ignored', async () => {
  const ctx = await open(baseView());
  const g = hold(); ctx.server.holdPut = g[0];
  const b = ctx.document.querySelector('[data-scope-select="archive"]'); b.checked = true; b.dispatchEvent(new ctx.window.Event('change', { bubbles: true }));
  const bulk = () => ctx.document.querySelector('[data-scope-bulk-act="leave_out"]');
  bulk().click();
  await wait(15);
  assert.equal(row(ctx.document, 'schema:archive').querySelector('[data-scope-mark]').dataset.scopeMark, 'leave_out');
  assert.match(flat(choiceCell(ctx.document, 'schema:archive')), /saving…/);
  assert.equal(bulk().disabled, true);
  bulk().click();
  g[1]();
  await wait(80);
  assert.equal(calls(ctx.server, 'POST', '/nodes').length, 1);
});
