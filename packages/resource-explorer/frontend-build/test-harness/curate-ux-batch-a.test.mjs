/** Curate UX batch A (owner feedback on egeria_git, 2026-10-07): items 1, 3, 4, 9, 10.
 *
 *  Real app.js, real router (the Curate nav button is clicked), a stub server behind fetch whose
 *  write answers can be held open, so the PENDING state of a pressed control is observable.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms));
const SUBS = ['docs/a', 'docs/b', 'docs/c'];
const PLAN = {
  technology_type: 'Git repository', disposition: 'using', in_population: true, last_surveyed_at: null,
  what_it_is: [{ kind: 'Library', label: 'A library', evidence: 'x', source: 'manifest_parse', state: 'measured', count: 1, members: null, candidate: true, detail: {} }],
  what_it_holds: [
    { kind: 'DataFile', label: '0 data files', evidence: '', source: 'data_file_profiling', state: 'measured', count: 0, members: null, candidate: false, detail: {} },
    { kind: 'SubResource', label: '3 of 3 sub-resources worth cataloging', evidence: '', source: 'sub_resource_survey', state: 'measured', count: 3, members: null, candidate: true, detail: { worthy: SUBS } },
  ],
  relates: [{ kind: 'Dependency', label: '4 dependencies', evidence: '', source: 'dependency_analysis', state: 'measured', count: 4, members: null, candidate: false, detail: {} }],
  commits: [], writes: {}, keeps_current: 'x',
};
const BRANCH = { path: 'packages/x', name: 'x', components: 1, accepted: 0, rejected: 0, undecided: 1, low_confidence: 0, types: {}, type: 'Service', ports: 0, own_ports: [], verdict: null };

function makeServer(over = {}) {
  const s = { calls: [], hold: {}, verdictStatus: 200, ...over };
  globalThis.fetch = async (url, opts = {}) => {
    const u = String(url);
    const method = opts.method || 'GET';
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    s.calls.push({ method, url: u, body });
    const ok = (b, status = 200) => ({ ok: true, status, json: async () => b });
    const err = (status, detail) => ({ ok: false, status, statusText: detail, json: async () => ({ detail }) });
    if (u.endsWith('/curate/commit')) {
      if (s.hold.commit) await s.hold.commit;
      if (s.commitStatus) return err(s.commitStatus, 'boom');
      return ok({ curation: { id: 'c1', state: 'queued', steps: [], author: 'dan', requested_at: '2026-10-07T00:00:00' }, activity_id: 'a1' });
    }
    if (u.endsWith('/components/verdicts')) {
      if (s.hold.verdict) await s.hold.verdict;
      if (s.verdictStatus !== 200) return err(s.verdictStatus, 'boom');
      return ok({ verdicts: body.scope_locators.map((x) => ({ scope: x })), queued: 1 });
    }
    if (u.includes('/curate/commits/')) return ok({ id: 'c1', state: 'done', steps: [], author: 'dan', requested_at: '2026-10-07T00:00:00' });
    if (u.includes('/api/activity')) return ok({ id: 'a1', status: 'success' });
    if (u.includes('/curate/plan')) return ok(PLAN);
    if (u.includes('/components/tree')) return ok({ branches: [BRANCH], total_components: 1, accepted: 0, reviewed: 0, topology: '' });
    if (u.includes('/components/blueprints')) return ok({ blueprints: [], perspectives: [] });
    if (u.endsWith('/publish-state')) return ok({ slug: 's', in_egeria: false, asset_guid: '', row: { word: 'none' }, project: { status: 'unset', word: 'no project' }, can_publish_again: false });
    if (u.endsWith('/file-types')) return ok({ types: [{ label: 'Python', file_count: 12, extensions: ['.py'], cataloged: false, linked: false, dataset_guid: '' }], blocker: '' });
    if (u.endsWith('/publish-report')) { if (s.hold.publish) await s.hold.publish; return ok({ ok: true }); }
    if (u.includes('/questions')) return ok({ questions: [] });
    if (u.includes('/api/context/')) return ok({ enrichment: {}, question_answers: {} });
    if (u.includes('/investigations') || u.includes('/subscriptions') || u.includes('/schedules')) return ok([]);
    return ok(u.includes('/api/curate/') ? [] : {});
  };
  return s;
}

async function setUp(serverOver = {}) {
  const { document, window } = makeDomEnvironment();
  const server = makeServer(serverOver);
  ensureLoaderRegistered();
  globalThis.location = window.location;
  globalThis.history = window.history;
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const app = await import('/static/next/app.js');
  app.state.resourceType = 'repo';
  app.state.selectedSlug = 'egeria_git';
  app.state.stage = 'understanding';
  app.state.subTab = 'questions';
  app.state.investigations = []; app.state.investigation = '';
  app.state.workListSlug = null; app.state.workListIndex = false;
  app.state.me = { user_id: 'dan' };
  app.state.curate = {}; app.state.curateSelection = null;
  app.state.groups = [];
  app.state.projects = [{ slug: 'egeria_git' }];
  app.state.perspectives = []; app.state.allPerspectives = [];
  for (const id of ['content', 'intent-nav', 'rail-evidence', 'perspective-row', 'app-grid']) {
    const d = document.createElement('div'); d.id = id; document.body.appendChild(d);
  }
  app.renderIntentNav();
  document.querySelector('#intent-nav button[data-stage="curate"]').click();
  await wait(400);
  return { document, app, server };
}
const holds = (d) => d.getElementById('curate-sec-what-holds');
const norm = (el) => el.textContent.replace(/\s+/g, ' ').trim();
const deferred = () => { let resolve; const p = new Promise((r) => { resolve = r; }); return { p, resolve }; };
const commitBody = (server) => server.calls.find((c) => c.url.endsWith('/curate/commit'))?.body;

/* ── item 1: select all / none ─────────────────────────────────────────── */

test('what is in it: select none / select all drive what Catalog sends, and the count shows it at once', async () => {
  const { document, server } = await setUp();
  const sec = holds(document);
  assert.match(norm(sec.querySelector('[data-curate-subs-count]')), /3 of 3 sub-resources selected/);
  assert.ok(sec.querySelector('[data-curate-subs-all]').disabled, 'already all selected: nothing to press');
  sec.querySelector('[data-curate-subs-none]').click();
  await wait();
  assert.match(norm(holds(document).querySelector('[data-curate-subs-count]')), /0 of 3 sub-resources selected/);
  assert.equal(holds(document).querySelectorAll('[data-curate-sub]:checked').length, 0);
  holds(document).querySelector('[data-curate-subs-all]').click();
  await wait();
  assert.equal(holds(document).querySelectorAll('[data-curate-sub]:checked').length, 3);
  // one by one, then Catalog sends exactly the ticked ones
  holds(document).querySelector('[data-curate-sub="docs/b"]').click();
  await wait();
  assert.match(norm(holds(document).querySelector('[data-curate-subs-count]')), /2 of 3/);
  document.querySelector('[data-curate-go]').click();
  await wait();
  assert.deepEqual(commitBody(server).sub_resources, ['docs/a', 'docs/c']);
});

test('select none then Catalog sends no sub-resources', async () => {
  const { document, server } = await setUp();
  holds(document).querySelector('[data-curate-subs-none]').click();
  await wait();
  document.querySelector('[data-curate-go]').click();
  await wait();
  assert.deepEqual(commitBody(server).sub_resources, []);
});

/* ── item 3: the mark is not a check ───────────────────────────────────── */

test('plan rows carry a short word, never a check mark that reads as accepted or published', async () => {
  const { document } = await setUp();
  const host = document.getElementById('curate-host');
  for (const id of ['curate-sec-what-holds', 'curate-sec-relates']) {
    assert.doesNotMatch(norm(document.getElementById(id)), /✓(?! surveyed)/, `${id}: a check never stands alone`);
  }
  const chips = [...document.getElementById('curate-sec-what-holds').querySelectorAll('[data-row-found]')];
  assert.deepEqual(chips.map((c) => norm(c)), ['none found', 'found']);
  assert.match(chips[1].title, /nothing here has been accepted or published/);
  assert.equal(norm(host.querySelector('#curate-sec-relates [data-row-found]')), 'info only');
  const cue = holds(document).querySelector('[data-cue="measured"]');
  assert.match(norm(cue), /✓ surveyed/);
  assert.match(cue.title, /nothing here is accepted or published yet/);
});

/* ── item 4: immediate feedback on accept ──────────────────────────────── */

test('accept all: the pressed control shows pending the instant it is pressed, then settled', async () => {
  const gate = deferred();
  const { document, server } = await setUp({ hold: { verdict: null } });
  server.hold.verdict = gate.p;
  const b = document.querySelector('[data-branch-verdict="accepted"]');
  b.click();                                   // components === 1: no dialog, goes straight out
  assert.equal(b.dataset.phase, 'pending', 'changed synchronously on press');
  assert.match(norm(b), /accepting…/);
  assert.ok(b.disabled, 'a second press is ignored');
  assert.match(norm(document.getElementById('component-tree-status')), /recording…/);
  gate.resolve();
  await wait(100);
  assert.match(norm(document.getElementById('component-tree-status')), /1 verdict recorded/);
});

test('reject all: pending cue on press as well', async () => {
  const gate = deferred();
  const { document, server } = await setUp();
  server.hold.verdict = gate.p;
  const b = document.querySelector('[data-branch-verdict="rejected"]');
  b.click();
  assert.equal(b.dataset.phase, 'pending');
  assert.match(norm(b), /rejecting…/);
  gate.resolve();
  await wait(100);
});

test('a failed accept shows an error state on the control, which can be pressed again', async () => {
  const { document, server } = await setUp({ verdictStatus: 500 });
  const b = document.querySelector('[data-branch-verdict="accepted"]');
  b.click();
  await wait(100);
  assert.equal(b.dataset.phase, 'error');
  assert.match(norm(b), /failed · press to retry/);
  assert.equal(b.disabled, false);
  assert.match(norm(document.getElementById('component-tree-status')), /not recorded — boom/);
  server.verdictStatus = 200;
  b.click();
  assert.equal(b.dataset.phase, 'pending');
  await wait(100);
});

/* ── item 10: Catalog says what it does ────────────────────────────────── */

test('Catalog: pressing shows a pending cue that says it refreshes stale surveys only, then publishes', async () => {
  const gate = deferred();
  const { document, server } = await setUp();
  server.hold.commit = gate.p;
  const go = document.querySelector('[data-curate-go]');
  assert.match(go.title, /only the surveys that have run before and are now out of date/);
  go.click();
  assert.match(norm(go), /Cataloging…/);
  assert.ok(go.disabled);
  const hint = go.nextElementSibling;
  assert.match(norm(hint), /refreshing stale surveys only, then publishing/);
  assert.doesNotMatch(norm(hint), /surveying first/);
  gate.resolve();
  await wait(100);
});

test('Catalog: a failed commit restores the button and says why', async () => {
  const { document } = await setUp({ commitStatus: 500 });
  const go = document.querySelector('[data-curate-go]');
  go.click();
  await wait(150);
  assert.equal(go.disabled, false);
  assert.equal(norm(go), 'Catalog →');
  assert.match(norm(document.getElementById('curate-host')), /not cataloged: boom/);
});

/* ── items 9 + 10: Publish band ────────────────────────────────────────── */

test('Publish band: file types come before the Publish controls and their button names its own act', async () => {
  const { document } = await setUp();
  const band = document.querySelector('[data-curate-band="publish"]');
  const ft = band.querySelector('[data-file-types-section]');
  const pub = band.querySelector('[data-publish-go]');
  assert.ok(ft && pub);
  assert.ok(ft.compareDocumentPosition(pub) & 4 /* FOLLOWING */, 'file types precede Publish');
  ft.open = true;
  ft.dispatchEvent(new document.defaultView.Event('toggle'));
  await wait();
  assert.equal(norm(ft.querySelector('[data-file-types-go]')), 'Catalog file types →');
  assert.match(norm(ft), /separate from Publish/);
});

test('Publish: idle and running words say it re-surveys everything, then publishes', async () => {
  const gate = deferred();
  const { document, server } = await setUp();
  server.hold.publish = gate.p;
  const band = document.querySelector('[data-curate-band="publish"]');
  const fb = band.querySelector('[data-publish-feedback]');
  assert.match(norm(fb), /re-surveys everything, then publishes/);
  assert.match(band.querySelector('[data-publish-go]').title, /every survey step/);
  band.querySelector('[data-publish-go]').click();
  assert.match(norm(band.querySelector('[data-publish-feedback]')), /re-surveying everything, then publishing/);
  assert.doesNotMatch(norm(band.querySelector('[data-publish-feedback]')), /takes a while/);
  gate.resolve();
  await wait(100);
});
