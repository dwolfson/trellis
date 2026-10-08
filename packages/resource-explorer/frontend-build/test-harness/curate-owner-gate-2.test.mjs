/** Curate, owner's answers "yes to all of 1-8" (2026-10-08): nothing pre-ticked, a "behind" cue, an unsaved-ticks
 *  rail that points to the saving control, Curate started before the questions chain, sections loaded only when
 *  opened, one blueprints heading with a capped list, and a jump that lands under the jump line and settles.
 *  Real app.js and router; a stub server behind fetch. Each guard below was made to fail first (red) by running
 *  this file against the code it replaced. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';
import { makeScopeStore } from './repo-scope-kit.mjs';

globalThis.CSS = globalThis.CSS || { escape: (v) => String(v).replace(/(["\\\]\[])/g, '\\$1') };
const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms));
const row = (o) => ({ evidence: '', source: 'manifest_parse', state: 'measured', count: null, members: null, candidate: true, detail: {}, ...o });
const planBase = () => ({
  technology_type: 'Git repository', disposition: 'using', in_population: true, last_surveyed_at: null,
  what_it_is: [row({ kind: 'Library', label: 'A library' }), row({ kind: 'Endpoint', label: 'Endpoint × 1' })],
  what_it_holds: [], relates: [], commits: [], writes: {}, keeps_current: 'x',
  made_of: [{ detail: { reviewed: 0, blueprints_reviewed: 0, blueprints_accepted: 0, blueprint_kinds: [] } }],
  survey: { exists: true, surveyed_at: '2026-10-07T01:00:00', age_seconds: 7200, annotations: 42, steps: 12, stale_steps: 0, stale: [] },
  project: { status: 'linked', word: 'project', name: 'P' },
});
const BRANCH = { path: 'packages/x', name: 'x', components: 3, accepted: 0, rejected: 0, undecided: 3, low_confidence: 0, types: {}, type: 'Service', ports: 0, own_ports: [], verdict: null };
const bp = (n, o = {}) => ({ perspective: 'logical', cluster_name: `c${n}`, members: [], member_status: [], child_status: [], verdict: null, ...o });

function makeServer(over = {}) {
  const s = { calls: [], plan: planBase(), scope: makeScopeStore(), blueprints: { blueprints: [], perspectives: [] }, ...over };
  globalThis.fetch = async (url, opts = {}) => {
    const u = String(url); const method = opts.method || 'GET';
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    s.calls.push({ method, url: u, body, at: s.calls.length });
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    const err = (status, detail) => ({ ok: false, status, statusText: detail, json: async () => ({ detail }) });
    const scoped = await s.scope.handle(u, method, body, ok, err);
    if (scoped) return scoped;
    if (u.endsWith('/curate/commit')) return ok({ curation: { id: 'c1', state: 'queued', steps: [], author: 'dan', requested_at: new Date().toISOString() }, activity_id: 'a1' });
    if (u.includes('/curate/commits/')) return ok({ id: 'c1', state: 'done', steps: [], author: 'dan', requested_at: new Date().toISOString() });
    if (u.includes('/api/activity')) return ok({ id: 'a1', status: 'success' });
    if (u.includes('/curate/plan')) { if (s.holdPlan) await s.holdPlan; return ok(s.plan); }
    if (u.includes('/components/tree')) { if (s.treeDelay) await wait(s.treeDelay); return ok({ branches: [BRANCH], total_components: 3, accepted: 0, reviewed: 0, topology: '' }); }
    if (u.includes('/components/blueprints')) { if (s.bpDelay) await wait(s.bpDelay); return ok(s.blueprints); }
    if (u.includes('/api/analyses/facts')) return ok({ subjects: {} });
    if (u.endsWith('/dependencies')) return ok({ heading: 'Dependencies · by kind', kinds: [], counts: {}, runtime_state: '', rows: [] });
    if (u.includes('/catalogue-depth-offer')) return ok({ layer1_done: false });
    if (u.endsWith('/publish-state')) return ok(s.publishState || { slug: 's', in_egeria: false, asset_guid: '', row: { word: 'none' }, project: { status: 'unset', word: 'no project' }, can_publish_again: false, survey: { exists: false } });
    if (u.endsWith('/file-type-measurements')) return ok({ inventoried: true, profiles: [], retired: [] });
    if (u.includes('/members/')) return ok({ analysis_id: 'sub_resource_survey', title: 'Sub-resource survey', total: 2, source: 'x', scope_honoured: true,
      groups: [{ name: 'well_known_file', count: 2, members: [{ name: 'bom', detail: 'well_known_file' }, { name: 'bom/README.md', detail: 'well_known_file' }] }] });
    if (u.includes('questions')) { if (s.holdQuestions) await s.holdQuestions; return ok({ questions: [] }); }
    if (u.includes('/api/context/')) return ok({ enrichment: {}, question_answers: {} });
    if (u.includes('/investigations') || u.includes('/subscriptions') || u.includes('/schedules')) return ok([]);
    return ok(u.includes('/api/curate/') ? [] : {});
  };
  return s;
}

async function setUp(over = {}, { settle = 400, preOpen = [] } = {}) {
  delete globalThis.localStorage;
  const { document, window } = makeDomEnvironment();
  Object.defineProperty(globalThis, 'localStorage', { value: window.localStorage, configurable: true, writable: true });
  for (const id of preOpen) window.localStorage.setItem(`re.curate.collapsed.${id}`, '0');
  const scrolls = [];
  window.Element.prototype.scrollIntoView = function scrollIntoView(o) { scrolls.push({ id: this.id, opts: o }); };
  const server = makeServer(over);
  ensureLoaderRegistered();
  globalThis.location = window.location; globalThis.history = window.history;
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const app = await import('/static/next/app.js');
  Object.assign(app.state, { resourceType: 'repo', selectedSlug: 'egeria_git', stage: 'understanding', subTab: 'questions',
    investigations: [], investigation: '', workListSlug: null, workListIndex: false, me: { user_id: 'dan' }, curate: {},
    curateSelection: null, groups: [], projects: [{ slug: 'egeria_git' }], perspectives: [], allPerspectives: [] });
  for (const id of ['content', 'intent-nav', 'rail-evidence', 'perspective-row', 'app-grid']) {
    const d = document.createElement('div'); d.id = id; document.body.appendChild(d);
  }
  app.renderIntentNav();
  document.querySelector('#intent-nav button[data-stage="curate"]').click();
  await wait(settle);
  return { document, app, server, window, scrolls };
}
const norm = (el) => el.textContent.replace(/\s+/g, ' ').trim();
const calls = (s, frag) => s.calls.filter((c) => c.url.includes(frag));
const jump = (document, id) => document.querySelector(`[data-curate-nav="${id}"]`).click();

/* 1 ─ nothing is pre-ticked ───────────────────────────────────────────────────────────────── */
test('1: "what it is" starts with nothing ticked, and the press sends only what the owner ticked', async () => {
  const { document, server } = await setUp();
  assert.equal(document.querySelectorAll('[data-curate-pick]:checked').length, 0);
  assert.match(norm(document.querySelector('[data-manifest-row="entities"]')), /0 entities · 2 proposed, not ticked/);
  document.querySelector('[data-curate-pick="Endpoint"]').click();
  await wait(150);
  assert.match(norm(document.querySelector('[data-manifest-row="entities"]')), /1 entity · 1 proposed, not ticked/);
  document.querySelector('[data-curate-go]').click();
  await wait(200);
  assert.deepEqual(calls(server, '/curate/commit')[0].body.confirm, ['Endpoint']);
});

/* 2 ─ behind cue ──────────────────────────────────────────────────────────────────────────── */
const pubState = (rowAt) => ({ slug: 's', in_egeria: true, asset_guid: 'g1', can_publish_again: true, project: { status: 'linked', word: 'project', name: 'P' },
  row: { word: 'published', surveyed_at: rowAt, read_at: '2026-10-07T01:30:00' },
  survey: { exists: true, surveyed_at: '2026-10-08T05:00:00', age_seconds: 7200, annotations: 42, steps: 12, stale_steps: 0, stale: [] } });
test('2: a report published from an older survey than the kept one says "behind"; matching surveys do not', async () => {
  const a = await setUp({ publishState: pubState('2026-10-07T01:00:00') });
  const behind = a.document.querySelector('[data-publish-behind]');
  assert.ok(behind, 'behind cue');
  assert.match(norm(behind), /behind/);
  assert.ok(behind.querySelector('[data-cue]'), 'a cue glyph, not only a sentence');
  const b = await setUp({ publishState: pubState('2026-10-08T05:00:00') });
  assert.equal(b.document.querySelector('[data-publish-behind]'), null);
});
test('2: the two lines name two different surveys', async () => {
  const { document } = await setUp({ publishState: pubState('2026-10-07T01:00:00') });
  const row = norm(document.querySelector('[data-publish-row]'));
  const kept = norm(document.querySelector('[data-publish-survey]'));
  assert.match(row, /published · from the survey of 2026-10-07/);
  assert.match(kept, /kept survey · 2026-10-08/);
  assert.ok(!(/from the survey of/.test(row) && /from the survey of/.test(kept)), 'not both "from the survey of"');
});

/* 3 ─ the members rail does not pretend to save ─────────────────────────────────────────────── */
test('3: the sub-resource Members rail has no checkboxes or bulk links, says where to choose, and links there', async () => {
  const { document, app } = await setUp({}, { settle: 300 });
  await app.openMembers({ slug: 'egeria_git', analysisId: 'sub_resource_survey', title: 'x' });
  const rail = document.getElementById('rail-evidence');
  assert.equal(rail.querySelectorAll('input[data-pick]').length, 0);
  assert.equal(rail.querySelector('[data-facet-all]'), null);
  assert.equal(rail.querySelector('[data-facet-none]'), null);
  const note = rail.querySelector('[data-members-not-saved]');
  assert.match(norm(note), /not saved here · choose what is published with Include in what's in it/);
  note.querySelector('[data-members-goto-scope]').click();
  assert.equal(document.getElementById('curate-sec-what-holds').open, true);
});
test('3: "N included · saved" stays in the what\'s-in-it header', async () => {
  const { document } = await setUp({}, { settle: 300 });
  const head = () => document.querySelector('#curate-sec-what-holds > summary [data-scope-saved-count]');
  assert.ok(head());
  assert.match(norm(head()), /0 included · saved/);
  document.getElementById('curate-sec-what-holds').open = true;
  document.querySelector('[data-scope-row="docs/a.md"] [data-scope-choice="include"]').click();
  await wait(200);
  await wait(6500);
  assert.match(norm(head()), /1 included · saved/, 'still on screen after the transient note is gone');
});

/* 4 ─ Curate starts before the questions chain ──────────────────────────────────────────────── */
test('4: the plan is requested while the questions read is still pending', async () => {
  let release; const holdQuestions = new Promise((r) => { release = r; });
  const { server } = await setUp({ holdQuestions }, { settle: 200 });
  const planAt = calls(server, '/curate/plan')[0]?.at;
  assert.ok(planAt !== undefined, 'the plan was requested while the questions read was held');
  release();
  await wait(200);
  assert.equal(calls(server, '/curate/plan').length, 1, 'and once only');
});

/* 5 ─ lazy sections ─────────────────────────────────────────────────────────────────────────── */
test('5: nothing section-specific is read until its section opens', async () => {
  const { server } = await setUp();
  for (const f of ['/components/tree', '/components/blueprints', '/api/analyses/facts', '/catalogue-depth-offer']) {
    assert.equal(calls(server, f).length, 0, `${f} not read at open`);
  }
  assert.equal(server.calls.filter((c) => c.url.endsWith('/dependencies')).length, 0);
});
test('5: opening "what it\'s made of" shows a cue at once, reads the tree and the diagram fact together, once', async () => {
  const { document, server } = await setUp({ treeDelay: 200 });
  document.getElementById('curate-sec-made-of').open = true;
  document.getElementById('curate-sec-made-of').dispatchEvent(new document.defaultView.Event('toggle'));
  const slot = document.getElementById('component-tree');
  assert.ok(slot.querySelector('[data-cue="running"]'), 'immediate loading cue in the slot');
  await wait(30);
  assert.equal(calls(server, '/components/tree').length, 1);
  assert.equal(calls(server, '/api/analyses/facts').length, 1, 'diagram fact started beside the tree, not after it');
  await wait(400);
  assert.ok(document.querySelector('#component-tree [data-branch]'));
  document.getElementById('curate-sec-made-of').dispatchEvent(new document.defaultView.Event('toggle'));
  await wait(50);
  assert.equal(calls(server, '/components/tree').length, 1, 'a second toggle does not read again');
});
test('5: the blueprints data is read once for both sections that show it', async () => {
  const { document, server } = await setUp();
  jump(document, 'curate-sec-made-of'); jump(document, 'curate-sec-blueprints');
  await wait(300);
  assert.equal(calls(server, '/components/blueprints').length, 1);
});
test('5: opening "how it relates" reads the dependencies; a jump link opens and loads its target', async () => {
  const { document, server } = await setUp();
  jump(document, 'curate-sec-relates');
  await wait(300);
  assert.equal(document.getElementById('curate-sec-relates').open, true);
  assert.equal(server.calls.filter((c) => c.url.endsWith('/dependencies')).length, 1);
});
test('5: a section the viewer left open last time is read at once, beside the plan', async () => {
  let release; const holdPlan = new Promise((r) => { release = r; });
  const { server } = await setUp({ holdPlan }, { preOpen: ['curate-sec-made-of'], settle: 200 });
  assert.equal(calls(server, '/components/tree').length, 1, 'requested while the plan is still held');
  assert.equal(calls(server, '/api/analyses/facts').length, 1);
  release();
  await wait(300);
  assert.equal(calls(server, '/components/tree').length, 1, 'and not read again once drawn');
});

/* 6 ─ blueprints section ──────────────────────────────────────────────────────────────────────── */
const sec = (d) => d.getElementById('curate-sec-blueprints');
test('6a: one "blueprints" heading, a muted line under it, the verdict paragraph kept', async () => {
  const many = Array.from({ length: 3 }, (_, i) => bp(i));
  const { document } = await setUp({ blueprints: { blueprints: many, perspectives: ['logical'], kinds: [] } });
  jump(document, 'curate-sec-blueprints');
  await wait(300);
  const headings = [...sec(document).querySelectorAll('.font-heading')].filter((e) => norm(e) === 'blueprints');
  assert.equal(headings.length, 1);
  assert.match(norm(sec(document)), /candidate clusters, in the logical reading/);
  assert.match(norm(sec(document)), /A verdict here is recorded against logical::cluster name/);
  assert.doesNotMatch(norm(sec(document)), /clustering\.py proposed/);
});
test('6b: every section is anchored at its start under the jump line', async () => {
  const { document, scrolls } = await setUp();
  for (const id of ['what-it-is', 'what-holds', 'made-of', 'blueprints', 'relates', 'writes']) {
    const el = document.getElementById(`curate-sec-${id}`);
    assert.match(el.getAttribute('style') || '', /scroll-margin-top/, `${id} has a scroll margin`);
    jump(document, `curate-sec-${id}`);
  }
  assert.equal(scrolls.length, 6);
  assert.ok(scrolls.every((s) => s.opts.block === 'start'), 'block: start, never centre');
});
test('6c: only the first 10 clusters, "and N more clusters ›" shows the rest; warnings stay on the first page; the count is K of N', async () => {
  const many = Array.from({ length: 25 }, (_, i) => bp(i, i === 20 ? { oversized: true, target_size: 5 } : {}));
  const { document } = await setUp({ blueprints: { blueprints: many, perspectives: ['logical'], kinds: [] } });
  jump(document, 'curate-sec-blueprints');
  await wait(300);
  const rows = () => sec(document).querySelectorAll('[data-blueprint]').length;
  assert.equal(rows(), 11, '10 + the undecided oversized one beyond the page');
  assert.ok(sec(document).querySelector('[data-blueprint="logical::c20"]'));
  assert.match(norm(sec(document)), /11 of 25 clusters shown/);
  const more = sec(document).querySelector('[data-blueprint-more]');
  assert.match(norm(more), /and 14 more clusters/);
  more.click();
  await wait(100);
  assert.equal(rows(), 25);
  assert.match(norm(sec(document)), /25 of 25 clusters shown/);
});

/* 7 ─ the jump settles ─────────────────────────────────────────────────────────────────────── */
test('7: after the section\'s late load lands, the jump re-scrolls once', async () => {
  const { document, scrolls } = await setUp({ bpDelay: 200, blueprints: { blueprints: [bp(1)], perspectives: ['logical'], kinds: [] } });
  jump(document, 'curate-sec-blueprints');
  const first = scrolls.length;
  assert.equal(first, 1);
  await wait(500);
  assert.equal(scrolls.length, 2, 'one re-scroll after the content landed');
  assert.equal(scrolls[1].opts.block, 'start');
});
test('7: but not if the person scrolled meanwhile', async () => {
  const { document, scrolls, window } = await setUp({ bpDelay: 200, blueprints: { blueprints: [bp(1)], perspectives: ['logical'], kinds: [] } });
  jump(document, 'curate-sec-blueprints');
  window.dispatchEvent(new window.Event('wheel'));
  await wait(500);
  assert.equal(scrolls.length, 1);
});
test('7: a click before the plan returns is queued, not lost', async () => {
  let release; const holdPlan = new Promise((r) => { release = r; });
  const { document, scrolls } = await setUp({ holdPlan }, { settle: 150 });
  assert.ok(document.querySelector('[data-curate-nav="curate-sec-blueprints"]'), 'the jump line is there while the plan loads');
  jump(document, 'curate-sec-blueprints');
  assert.match(norm(document.getElementById('curate-host')), /will open when the plan is read/);
  release();
  await wait(500);
  assert.equal(document.getElementById('curate-sec-blueprints').open, true);
  assert.ok(scrolls.some((s) => s.id === 'curate-sec-blueprints' && s.opts.block === 'start'));
});
