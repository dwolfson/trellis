/** The commit control is an unmistakable button under the manifest, and a choice write says what it
 *  did: 'saved in Resource Explorer', not yet in Egeria. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { baseView, setUp, row, flat, wait } from './scope-test-kit.mjs';

const PREVIEW = (over = {}) => ({
  manifest: { lines: [{ id: 're_publishes', mechanism: 1, text: 'RE publishes the server and database assets.' },
    { id: 'whole_schemas', mechanism: 0, text: 'Egeria catalogs whole schemas' }] },
  can_commit: true, button: 'Catalog · 2 schemas', blockers: [], leave_out: [], refused: [], collisions: [], ...over,
});
const declaredView = () => baseView({ declared: { declared: true, by: 'me', at: '2026-10-04T08:00:00', kind: 'declare', baseline_survey_at: '' } });
async function open(view, preview, opts) {
  const ctx = await setUp(view, opts);
  ctx.server.preview = preview;
  const fold = ctx.document.querySelector('[data-scope-collapse]');
  if (fold.getAttribute('aria-expanded') === 'false') { fold.click(); await wait(); }
  return ctx;
}
const btn = (d) => d.querySelector('[data-scope-commit-btn]');

test('the commit control is a real primary button on its own line directly under the manifest and the refresh box', async () => {
  const { document } = await open(declaredView(), PREVIEW());
  const b = btn(document);
  assert.equal(b.tagName, 'BUTTON');
  assert.equal(flat(b), 'Catalog · 2 schemas');
  assert.ok(b.className.includes('bg-accent') && b.className.includes('font-semibold'), 'filled, not link-styled text');
  assert.ok(!b.className.includes('underline'));
  const rowEl = b.closest('[data-scope-commit-row]');
  assert.ok(rowEl, 'it has its own row');
  assert.equal(rowEl.querySelector('[data-scope-read-back]'), null, 'Read Egeria again is not on the primary row');
  const panel = document.querySelector('[data-scope-commit-panel]');
  const order = [...panel.querySelectorAll('[data-scope-manifest], [data-scope-refresh-now], [data-scope-commit-row], [data-scope-read-back]')]
    .map((e) => (e.hasAttribute('data-scope-manifest') ? 'manifest' : e.hasAttribute('data-scope-refresh-now') ? 'refresh' : e.hasAttribute('data-scope-commit-row') ? 'button' : 'read'));
  assert.deepEqual(order, ['manifest', 'refresh', 'button', 'read']);
  assert.ok(document.querySelector('[data-scope-read-back]').className.includes('underline'), 'secondary stays a link-style control');
});

test('a disabled commit button says why, in words, beside it', async () => {
  const nothing = await open(declaredView(), PREVIEW({ can_commit: false, button: 'Catalog · 0 schemas', blockers: ['nothing to commit: choose at least one schema to catalogue'] }));
  assert.equal(btn(nothing.document).disabled, true);
  assert.match(flat(nothing.document.querySelector('[data-scope-commit-why]')), /^nothing chosen/);
  const coll = await open(declaredView(), PREVIEW({ can_commit: false, blockers: ["1 name collision Egeria's listing can't tell apart: leave the schema out, or rename it in the database"] }));
  assert.match(flat(coll.document.querySelector('[data-scope-commit-why]')), /^name collisions: /);
  const undeclared = await open(baseView(), PREVIEW({ can_commit: false, blockers: ['nothing to commit: choose at least one schema to catalogue'] }));
  assert.match(flat(undeclared.document.querySelector('[data-scope-commit-why]')), /^no scope declared/);
  const out = await open(declaredView(), PREVIEW(), { signedIn: false });
  assert.match(flat(out.document.querySelector('[data-scope-commit-why]')), /sign in/);
});

test('an enabled button has no reason text', async () => {
  const { document } = await open(declaredView(), PREVIEW());
  assert.equal(btn(document).disabled, false);
  assert.equal(document.querySelector('[data-scope-commit-why]'), null);
});

test('while the commit is sent the button says sending… and is disabled, then "sent · waiting for Egeria"', async () => {
  const ctx = await open(declaredView(), PREVIEW());
  let release; ctx.server.holdCommit = new Promise((r) => { release = r; });
  btn(ctx.document).click();
  await wait(20);
  assert.equal(flat(btn(ctx.document)), 'sending…');
  assert.equal(btn(ctx.document).disabled, true);
  release();
  await wait(60);
  assert.match(flat(ctx.document.querySelector('[data-scope-commit-sent]')), /^sent · waiting for Egeria$/);
  assert.ok(ctx.document.querySelector('[data-scope-commit-step]') || ctx.document.querySelector('[data-scope-commit-steps]'), 'the steps follow');
});

test('a choice write shows saving…, then a plain "saved in Resource Explorer" line that says Egeria is not touched, then fades', async () => {
  const mod = await import('/static/next/stages/curate-scope.js');
  mod.setSavedNoteMs(120);
  const ctx = await open(declaredView(), PREVIEW());
  let release; ctx.server.holdPut = new Promise((r) => { release = r; });
  row(ctx.document, 'schema:sales').querySelector('[data-scope-act="set"][data-scope-choice="catalogue"]').click();
  await wait(20);
  assert.match(flat(row(ctx.document, 'schema:sales').querySelector('[data-scope-choice-cell]')), /saving…/);
  release();
  await wait(60);
  const note = row(ctx.document, 'schema:sales').querySelector('[data-scope-saved-note]');
  assert.ok(note, 'the row says what happened');
  assert.equal(flat(note), 'saved in Resource Explorer · me · 10-04 · not yet cataloged in Egeria');
  assert.equal(ctx.document.querySelector('[role="dialog"]'), null, 'not a modal');
  await wait(220);
  assert.equal(row(ctx.document, 'schema:sales').querySelector('[data-scope-saved-note]'), null);
  assert.match(flat(row(ctx.document, 'schema:sales').querySelector('[data-scope-choice-cell]')), /catalogue · set by me/, 'the choice itself stays');
  mod.setSavedNoteMs(6000);
});

test('the per-row choice links keep their words', async () => {
  const { document } = await open(declaredView(), PREVIEW());
  const r = row(document, 'schema:sales');
  assert.equal(flat(r.querySelector('[data-scope-act="set"][data-scope-choice="catalogue"]')), 'catalogue');
  assert.equal(flat(r.querySelector('[data-scope-act="set"][data-scope-choice="leave_out"]')), 'leave out');
});
