/** Behaviour: proposed quality checks on a database's Curate page (stages/quality-checks.js).
 *  Real module, real colresize and selector; the API is a stub that behaves like the route (summary without rows,
 *  a group's rows on request, a verdict that is read back). Pinned: counts, collapsed groups, filters, the selector,
 *  the cue (pending, then the read-back, then a persistent failure), no selector on a not-established row, escaping,
 *  resizable columns, no bulk verdict, and signed-out disabling. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));

function check(over) {
  return {
    id: 1, check_key: 'sales.orders.placed::Required', schema_name: 'sales', table_name: 'orders', column_name: 'placed',
    test_type: 'Required', dimension: 'completeness', origin: 'vendored', general_type: 'D', params: { threshold_value: 0, profile_surveyed_at: 'x' },
    profile_surveyed_at: '2026-10-20T10:00:00+00:00', proposal_state: 'proposed', reason: '', status: 'proposed', selectable: true,
    verdict: null, ...over,
  };
}

function fakeApi(rows, { post = null, failRead = false } = {}) {
  const calls = { gets: [], posts: [] };
  const counts = () => {
    const c = { total: rows.length, proposed: 0, accepted: 0, rejected: 0, retired: 0, not_established: 0 };
    rows.forEach((r) => { c[r.status] += 1; });
    return c;
  };
  const api = {
    calls,
    async getProposals(slug, params = {}) {
      calls.gets.push(params);
      if (failRead) throw new Error('registry down');
      const match = (r) => (!params.test_type || r.test_type === params.test_type) && (!params.dimension || r.dimension === params.dimension)
        && (!params.state || r.status === params.state);
      const byTable = new Map();
      rows.forEach((r) => { const k = `${r.schema_name}.${r.table_name}`; (byTable.get(k) || byTable.set(k, []).get(k)).push(r); });
      let groups = [...byTable.entries()].map(([k, rs]) => {
        const f = rs.filter(match);
        const c = { total: f.length, proposed: 0, accepted: 0, rejected: 0, retired: 0, not_established: 0 };
        f.forEach((r) => { c[r.status] += 1; });
        const [schema_name, table_name] = k.split('.');
        return { schema_name, table_name, counts: c, rows: params.table ? f : null };
      }).filter((g) => g.counts.total);
      if (params.table) groups = groups.filter((g) => g.table_name === params.table);
      groups.sort((a, b) => `${a.schema_name}.${a.table_name}`.localeCompare(`${b.schema_name}.${b.table_name}`));
      const uniq = (key) => [...new Set(rows.map((r) => r[key]))].sort().map((v) => ({ value: v, count: rows.filter((r) => r[key] === v).length }));
      return {
        slug, has_proposals: rows.length > 0, tables: byTable.size, surveyed_at: '2026-10-21T08:00:00+00:00',
        profile_surveyed_at: '2026-10-20T10:00:00+00:00', counts: counts(), shown: {}, applied: { test_type: params.test_type || '', dimension: params.dimension || '', state: params.state || '' },
        filters: { test_types: uniq('test_type'), dimensions: uniq('dimension'),
          states: ['proposed', 'accepted', 'rejected', 'retired', 'not_established'].map((s) => ({ value: s, count: counts()[s] })) },
        groups,
      };
    },
    async postVerdict(slug, key, verdict) {
      calls.posts.push({ key, verdict });
      if (post) return post(key, verdict, rows);
      const r = rows.find((x) => x.check_key === key);
      r.status = verdict;
      r.verdict = { id: calls.posts.length, verdict, decided_by: 'steward', created_at: '2026-10-21T09:00:00+00:00', note: '' };
      return { recorded: true, check: { ...r } };
    },
  };
  return api;
}

async function setUp(rows, { me = 'steward', ...opts } = {}) {
  const { document } = makeDomEnvironment();
  ensureLoaderRegistered();
  globalThis.location = document.defaultView.location;
  globalThis.getComputedStyle = document.defaultView.getComputedStyle.bind(document.defaultView);
  globalThis.history = document.defaultView.history;
  document.defaultView.matchMedia = document.defaultView.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const mod = await import('/static/next/stages/quality-checks.js');
  const slot = document.createElement('div');
  document.body.appendChild(slot);
  const api = fakeApi(rows, opts);
  const view = mod.mountQualityChecks(slot, 'coco', { api, me });
  await tick(5);
  return { document, slot, api, view, mod };
}

const ROWS = () => [
  check({ id: 1 }),
  check({ id: 2, check_key: 'sales.orders.order_id::Unique', column_name: 'order_id', test_type: 'Unique', dimension: 'uniqueness' }),
  check({ id: 3, check_key: 'sales.orders.note::Missing_Pct', column_name: 'note', test_type: 'Missing_Pct', status: 'not_established',
    proposal_state: 'not_established', selectable: false, reason: 'its selection rule reads null_value_ct, which the profile did not measure' }),
  check({ id: 4, check_key: 'sales.items.sku::Required', table_name: 'items', column_name: 'sku' }),
];

const open = async (t, name) => {
  const g = [...t.slot.querySelectorAll('[data-qc-group]')].find((e) => e.dataset.qcGroup === name);
  g.open = true;
  g.dispatchEvent(new t.document.defaultView.Event('toggle'));
  await tick(5);
  return g;
};

test('counts and groups are drawn from the summary, collapsed, with no rows read yet', async () => {
  const t = await setUp(ROWS());
  assert.match(text(t.slot.querySelector('[data-qc-counts]')), /3 proposed · 1 not established/);
  assert.match(text(t.slot.querySelector('[data-qc-counts]')), /2 tables/);
  const groups = [...t.slot.querySelectorAll('[data-qc-group]')];
  assert.deepEqual(groups.map((g) => g.dataset.qcGroup), ['sales.items', 'sales.orders']);
  assert.ok(groups.every((g) => !g.open), 'collapsed');
  assert.match(text(groups[1].querySelector('[data-qc-group-counts]')), /2 proposed · 1 not established/);
  assert.equal(t.slot.querySelectorAll('[data-qc-row]').length, 0);
  assert.ok(t.api.calls.gets.every((p) => !p.table), 'no group read until opened');
});

test('opening a group reads that table only and draws a resizable grid with a selector per decidable check', async () => {
  const t = await setUp(ROWS());
  const g = await open(t, 'sales.orders');
  assert.deepEqual(t.api.calls.gets.at(-1), { test_type: '', dimension: '', state: '', schema: 'sales', table: 'orders' });
  const rows = [...g.querySelectorAll('[data-qc-row]')];
  assert.equal(rows.length, 3);
  const req = rows.find((r) => r.dataset.qcRow === 'sales.orders.placed::Required');
  assert.equal(req.querySelectorAll('[data-qc-act="verdict"]').length, 2);
  assert.deepEqual([...req.querySelectorAll('[data-qc-act="verdict"]')].map((b) => text(b)), ['Accept', 'Reject']);
  assert.match(text(req), /completeness/);
  assert.match(text(req), /threshold_value=0/);
  assert.doesNotMatch(text(req), /profile_surveyed_at/, 'the profile date has its own column');
  assert.ok(g.querySelector('[data-rc-handle], .rc-handle, [data-grid-host]'), 'colresize grid');
  assert.equal(g.querySelectorAll('[role="columnheader"]').length, 6);
});

test('a not-established row has no selector and says why on the row', async () => {
  const t = await setUp(ROWS());
  const g = await open(t, 'sales.orders');
  const ne = g.querySelector('[data-qc-row="sales.orders.note::Missing_Pct"]');
  assert.equal(ne.querySelectorAll('button').length, 0);
  assert.equal(ne.querySelector('[data-qc-cue]').dataset.qcCue, 'not_established');
  assert.match(text(ne.querySelector('[data-qc-reason]')), /null_value_ct/);
});

test('a press shows recording… at once, then the verdict only once it is read back', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const t = await setUp(ROWS(), { post: async (key, verdict, rows) => {
    await gate;
    const r = rows.find((x) => x.check_key === key);
    r.status = verdict;
    r.verdict = { id: 9, verdict, decided_by: 'steward', created_at: '2026-10-21T09:00:00+00:00', note: '' };
    return { recorded: true, check: { ...r } };
  } });
  const g = await open(t, 'sales.orders');
  g.querySelector('[data-qc-row="sales.orders.placed::Required"] [data-qc-verdict="accepted"]').click();
  await tick(5);
  let row = g.querySelector('[data-qc-row="sales.orders.placed::Required"]');
  assert.equal(row.querySelector('[data-qc-cue]').dataset.qcCue, 'pending');
  assert.match(text(row), /recording…/);
  assert.ok([...row.querySelectorAll('button')].every((b) => b.disabled), 'no second press while one is out');
  release();
  await tick(10);
  row = g.querySelector('[data-qc-row="sales.orders.placed::Required"]');
  assert.equal(row.querySelector('[data-qc-cue]').dataset.qcCue, 'accepted');
  assert.match(text(row), /accepted · you · 2026-10-21/);
  assert.equal(row.querySelector('[data-qc-verdict="accepted"]').getAttribute('aria-pressed'), 'true');
  assert.equal(row.querySelector('[data-qc-verdict="rejected"]').getAttribute('aria-pressed'), 'false');
  assert.deepEqual(t.api.calls.posts, [{ key: 'sales.orders.placed::Required', verdict: 'accepted' }]);
});

test('the group and page counts follow a recorded verdict', async () => {
  const t = await setUp(ROWS());
  const g = await open(t, 'sales.orders');
  g.querySelector('[data-qc-row="sales.orders.placed::Required"] [data-qc-verdict="rejected"]').click();
  await tick(15);
  assert.match(text(t.slot.querySelector('[data-qc-counts]')), /2 proposed · 1 rejected · 1 not established/);
  assert.match(text(g.querySelector('[data-qc-group-counts]')), /1 proposed · 1 rejected · 1 not established/);
  assert.equal(g.querySelector('[data-qc-row="sales.orders.placed::Required"]').dataset.qcStatus, 'rejected');
});

test('Accept then Reject on the same check is two presses; the later verdict wins on screen', async () => {
  const t = await setUp(ROWS());
  const g = await open(t, 'sales.orders');
  const sel = (v) => g.querySelector(`[data-qc-row="sales.orders.placed::Required"] [data-qc-verdict="${v}"]`);
  sel('accepted').click(); await tick(10);
  sel('rejected').click(); await tick(10);
  assert.deepEqual(t.api.calls.posts.map((p) => p.verdict), ['accepted', 'rejected']);
  assert.equal(sel('rejected').getAttribute('aria-pressed'), 'true');
});

test('a write that fails leaves a cue on the row until the next press, and the old verdict stands', async () => {
  const t = await setUp(ROWS(), { post: async () => { throw new Error('sign in to accept or reject a quality check'); } });
  const g = await open(t, 'sales.orders');
  g.querySelector('[data-qc-row="sales.orders.placed::Required"] [data-qc-verdict="accepted"]').click();
  await tick(10);
  const row = g.querySelector('[data-qc-row="sales.orders.placed::Required"]');
  assert.equal(row.querySelector('[data-qc-cue]').dataset.qcCue, 'failed');
  assert.match(text(row), /not recorded · sign in to accept or reject a quality check/);
  assert.equal(row.dataset.qcStatus, 'proposed');
  await tick(30);
  assert.equal(g.querySelector('[data-qc-row="sales.orders.placed::Required"] [data-qc-cue]').dataset.qcCue, 'failed', 'it persists');
});

test('a verdict that is not read back matching is not shown as recorded', async () => {
  const t = await setUp(ROWS(), { post: async (key) => ({ recorded: false, check: { ...check({}), check_key: key } }) });
  const g = await open(t, 'sales.orders');
  g.querySelector('[data-qc-row="sales.orders.placed::Required"] [data-qc-verdict="accepted"]').click();
  await tick(10);
  const row = g.querySelector('[data-qc-row="sales.orders.placed::Required"]');
  assert.equal(row.querySelector('[data-qc-cue]').dataset.qcCue, 'failed');
  assert.match(text(row), /could not be read back/);
});

test('filters re-read with the choice and keep every option', async () => {
  const t = await setUp(ROWS());
  const sel = t.slot.querySelector('[data-qc-filter="test_type"]');
  assert.deepEqual([...sel.options].map((o) => o.value), ['', 'Missing_Pct', 'Required', 'Unique']);
  sel.value = 'Required';
  sel.dispatchEvent(new t.document.defaultView.Event('change'));
  await tick(10);
  assert.equal(t.api.calls.gets.at(-1).test_type, 'Required');
  assert.match(text(t.slot.querySelector('[data-qc-counts]')), /2 of 2 tables match/);
  const sel2 = t.slot.querySelector('[data-qc-filter="test_type"]');
  assert.equal(sel2.value, 'Required');
  assert.equal(sel2.options.length, 4, 'the way back is still offered');
  assert.deepEqual([...t.slot.querySelectorAll('[data-qc-filter="state"] option')].map((o) => o.value),
    ['', 'proposed', 'accepted', 'rejected', 'retired', 'not_established']);
});

test('no proposals is said, not drawn as zero checks', async () => {
  const t = await setUp([]);
  assert.match(text(t.slot), /No quality checks have been proposed for this database yet/);
  assert.equal(t.slot.querySelectorAll('[data-qc-group]').length, 0);
});

test('nobody signed in: the selector is there but disabled, with the reason', async () => {
  const t = await setUp(ROWS(), { me: '' });
  const g = await open(t, 'sales.orders');
  const b = g.querySelector('[data-qc-verdict="accepted"]');
  assert.ok(b.disabled);
  assert.match(b.getAttribute('title'), /sign in/);
});

test('there is no bulk verdict anywhere on the view', async () => {
  const t = await setUp(ROWS());
  await open(t, 'sales.orders');
  assert.doesNotMatch(text(t.slot), /accept all|accept every|reject all/i);
  const verdictButtons = t.slot.querySelectorAll('[data-qc-act="verdict"]');
  assert.ok([...verdictButtons].every((b) => b.closest('[data-qc-row]')), 'every verdict button belongs to one check row');
});

test('column names, reasons and parameters are escaped', async () => {
  const evil = '"><img src=x onerror=alert(1)>';
  const t = await setUp([check({ check_key: `s.t.${evil}::Required`, schema_name: 's', table_name: 't', column_name: evil,
      params: { threshold_value: evil } }),
    check({ id: 2, check_key: 's.t::Row_Ct', schema_name: 's', table_name: 't', status: 'not_established', selectable: false,
      reason: evil })]);
  const g = await open(t, 's.t');
  assert.equal(t.slot.querySelectorAll('img').length, 0);
  assert.match(text(g), /onerror=alert/, 'shown as text');
  assert.equal(g.querySelectorAll('[data-qc-row]').length, 2);
});

test('a read that fails says so inside the block', async () => {
  const t = await setUp(ROWS(), { failRead: true });
  assert.match(text(t.slot.querySelector('[data-qc-error]')), /could not be read: registry down/);
});

test('the grid never lets a long value push the page wide: cells break and the host scrolls inside its box', async () => {
  const t = await setUp(ROWS());
  const g = await open(t, 'sales.orders');
  const host = g.querySelector('[data-grid-host]');
  assert.match(host.className, /overflow-x-auto/);
  assert.match(host.className, /max-w-full/);
});
