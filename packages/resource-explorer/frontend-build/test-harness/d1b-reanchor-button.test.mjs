/** D1-b: the plan's database row carries ONE press, "Add the pack's N schemas to this database". It is off, with the
 *  reason, when nobody is signed in; a confirm names the count and the result before anything is sent; after the
 *  press the page reads the scope again, so the row shows what Egeria now holds (26 members, nothing to add, no
 *  button). A partial press names the schemas not added and is never worded as a failure of the whole press.
 *  Real app.js and router, a fake fetch. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { baseView, setUp, flat, wait } from './scope-test-kit.mjs';
import { autoAnswerConfirm } from './confirm-kit.mjs';

const PACK = 'Coco PostgreSQL Server 1';
const toAdd = (n) => Array.from({ length: n }, (_, i) => ({ guid: `pack-${i}`, schema: `s${i}`, family: PACK }));
const dbRow = (n, now = 4) => ({
  re_guid: 'c990f349-36de', re_qualified_name: 'PostgreSQL Relational Database::host.docker.internal:5442::coco_pharma',
  link_type: 'DataSetContent', schema_end: 1, members_now: now, members_after: n ? now + n : now, to_add: toAdd(n),
  words: n ? `add DataSetContent from c990f349 to the pack's ${n} schemas under '${PACK}' · after the press: ${now + n} members`
    : `every other-family schema is already a DataSetContent member of c990f349 · nothing to add`,
});
const endpoint = (row, press = null) => ({
  at: '2026-10-31T09:00:00', error: '', endpoint: 'host.docker.internal:5442/coco_pharma', families: [],
  plan: { pairs: 0, rows: [], words: 'this endpoint: …', database_link_type: 'DataSetContent', database_row: row },
  neither: null, press, words: 'this endpoint: …',
});
const view = (ep) => {
  const v = baseView();
  v.commit = { ...v.commit, endpoint: ep };
  return v;
};
const btn = (d) => d.querySelector('[data-scope-reanchor-btn]');

test('the database row offers the press, naming the count', async () => {
  const { document } = await setUp(view(endpoint(dbRow(22))));
  const b = btn(document);
  assert.ok(b, 'the press is on the database row');
  assert.equal(flat(b), "Add the pack's 22 schemas to this database");
  assert.equal(b.disabled, false);
  assert.ok(document.querySelector('[data-scope-plan-database]').contains(b));
});

test('signed out, the press is off and says why; nothing is sent', async () => {
  const { document, server } = await setUp(view(endpoint(dbRow(22))), { signedIn: false });
  const b = btn(document);
  assert.ok(b.disabled);
  assert.match(b.getAttribute('title'), /sign in/);
  b.click();
  await wait(50);
  assert.equal(server.calls.filter((c) => c.url.endsWith('/reanchor')).length, 0);
});

test('no button when there is nothing to add, or the type or ends were not read', async () => {
  for (const row of [dbRow(0, 26), { ...dbRow(22), members_after: null, link_type: 'not read' }]) {
    const { document } = await setUp(view(endpoint(row)));
    assert.equal(btn(document), null);
  }
});

test('cancel at the confirm sends nothing', async () => {
  const { document, server } = await setUp(view(endpoint(dbRow(22))));
  const asked = [];
  const kit = autoAnswerConfirm(document, { answer: false, asked });
  btn(document).click();
  await wait(100);
  kit.stop();
  assert.equal(asked.length, 1);
  assert.equal(server.calls.filter((c) => c.url.endsWith('/reanchor')).length, 0);
});

test('confirm, press once, then the row reads back 26 members and nothing to add', async () => {
  const ctx = await setUp(view(endpoint(dbRow(22))));
  const { document, server } = ctx;
  const base = globalThis.fetch;
  const words = "added 22 of 22 schemas to c990f349 (DataSetContent) · read back: 26 members";
  globalThis.fetch = async (url, opts = {}) => {
    if (String(url).endsWith('/reanchor') && opts.method === 'POST') {
      server.calls.push({ method: 'POST', url: String(url) });
      server.view = view(endpoint(dbRow(0, 26), { at: '2026-10-31T09:05:00', by: 'me', words, added: 22, failed: [], unverified: [], members_after: 26 }));
      return { ok: true, status: 200, json: async () => ({ state: 'added', words, members_after: 26 }) };
    }
    return base(url, opts);
  };
  const asked = [];
  const kit = autoAnswerConfirm(document, { answer: true, asked });
  btn(document).click();
  await wait(300);
  kit.stop();
  globalThis.fetch = base;
  assert.match(asked[0], /^Add the pack's 22 schemas to this database/);
  assert.match(asked[0], /each of the pack's 22 schemas/);
  assert.match(asked[0], /After the press: 26 members/);
  assert.match(asked[0], /nothing is deleted/);
  assert.equal(server.calls.filter((c) => c.url.endsWith('/reanchor')).length, 1, 'one press');
  assert.equal(flat(document.querySelector('[data-scope-status]')), words);
  const row = document.querySelector('[data-scope-plan-database]');
  assert.match(flat(row), /nothing to add/);
  assert.equal(btn(document), null, 'nothing left to press');
  assert.match(flat(document.querySelector('[data-scope-reanchor-result]')), /read back: 26 members/);
});

test('a partial press names what was not added and is never worded as failed for all', async () => {
  const words = 'added 21 of 22 schemas to c990f349 (DataSetContent) · 1 not added: sec_admin (not authorized) · read back: 25 members';
  const press = { at: '2026-10-31T09:05:00', by: 'me', words, added: 21, failed: ['sec_admin'], unverified: [], members_after: 25 };
  const { document } = await setUp(view(endpoint(dbRow(1, 25), press)));
  const line = document.querySelector('[data-scope-reanchor-result]');
  assert.equal(line.dataset.added, '21');
  assert.match(flat(line), /1 not added: sec_admin/);
  assert.doesNotMatch(flat(line), /^last press [^:]*: failed/);
  assert.ok(line.className.includes('text-state-warn'));
  assert.equal(flat(btn(document)), "Add the pack's 1 schema to this database", 'the one left can be pressed again');
});
