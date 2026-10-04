/** Behaviour: slice W1-B of REPLY-DESIGNER-WORK-LISTS-VS-INVESTIGATIONS.md §2.
 *
 *  The work list pane and the list of work lists carry "Add these N to
 *  <investigation>" and "Start an investigation from this list…"; a list tagged
 *  with an investigation says, live, "7 of 9 in scope for <name> · 2 not added"
 *  and each row says in scope / not in scope, in ink; the ▦ index names the
 *  investigation instead of its slug.
 *
 *  Real app.js, real router, the shipped index.html body; only fetch is stubbed.
 *  The stub plays the server's part for the add route (skip what is in scope).
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const NEXT_DIR = path.resolve(HERE, '../../resource_explorer/web/static/next');
const INDEX_HTML = fs.readFileSync(path.join(NEXT_DIR, 'index.html'), 'utf8');

const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));
const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();

const INVESTIGATIONS = [
  { slug: 'c360', display_name: 'Customer 360', status: 'open' },
  { slug: 'a-very-long-investigation-name-indeed', display_name: 'A very long investigation name indeed', status: 'open' },
];
const wlRow = (slug, over = {}) => ({
  slug, display_name: slug, description: '', entity_type: 'database', investigation: '', member_count: 9, egeria_guid: '',
  derived_from: '', ...over,
});
let WORK_LISTS; let SCOPE; let CALLS;

function reset() {
  WORK_LISTS = [
    wlRow('sales-databases', { display_name: 'Sales databases', investigation: 'c360' }),
    wlRow('old-postgres', { display_name: 'Old Postgres', description: 'Legacy boxes to look at', member_count: 4 }),
  ];
  // c360's scope: 7 of the 9 sales databases (0..6), one with its own reason, plus a repo.
  SCOPE = {
    c360: [
      ...Array.from({ length: 7 }, (_, i) => ({ entity_type: 'database', entity_slug: `sales-databases-${i}`, membership_rationale: i === 0 ? 'mine' : '' })),
      { entity_type: 'repo', entity_slug: 'sales-databases-8' },   // same name, WRONG kind: must not count
    ],
  };
  CALLS = [];
}

const membersOf = (slug, n) => Array.from({ length: n }, (_, i) => ({
  entity_slug: `${slug}-${i}`, entity_type: 'database', rationale: i === 1 ? 'big one' : '' }));

function stubBackend() {
  globalThis.fetch = async (url, options = {}) => {
    const u = String(url);
    const method = (options.method || 'GET').toUpperCase();
    const body = options.body ? JSON.parse(options.body) : null;
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    if (method !== 'GET') CALLS.push({ method, url: u, body });
    if (method === 'GET' && u.startsWith('/api/investigations/?')) return ok(INVESTIGATIONS);
    if (method === 'POST' && u === '/api/investigations/') {
      const inv = { slug: 'from-sales', display_name: body.display_name, status: 'open' };
      INVESTIGATIONS.push(inv); SCOPE['from-sales'] = [];
      return ok(inv);
    }
    let m = u.match(/^\/api\/investigations\/([^/?]+)\/members$/);
    if (m) return ok(SCOPE[m[1]] || []);
    m = u.match(/^\/api\/investigations\/([^/?]+)$/);
    if (m && method === 'GET' && !['purposes', 'classifications'].includes(m[1])) {
      const inv = INVESTIGATIONS.find((i) => i.slug === m[1]);
      return ok({ ...inv, description: 'd', project_classification: 'StudyProject', purposes: [], visibility: 'public' });
    }
    if (/\/next-steps$/.test(u)) return ok({ steps: [], complete: true });
    if (/\/dispositions$/.test(u)) return ok({});
    if (u === '/api/investigations/purposes') return ok({ purposes: ['Migration', 'Audit'] });
    if (u === '/api/investigations/classifications') {
      return ok({ classifications: [{ name: 'StudyProject', label: 'Study' }], default_classification: 'StudyProject',
        bindings: [{ name: 'egeria', label: 'Egeria Project' }, { name: 'local', label: 'Local only' }], default_binding: 'egeria' });
    }
    m = u.match(/^\/api\/work-lists\/([^/?]+)\/add-to-investigation$/);
    if (m && method === 'POST') {
      const wl = WORK_LISTS.find((w) => w.slug === m[1]);
      const slugs = body.entity_slugs || membersOf(wl.slug, wl.member_count).map((x) => x.entity_slug);
      const have = new Set((SCOPE[body.investigation] ||= []).filter((x) => x.entity_type === wl.entity_type).map((x) => x.entity_slug));
      const added = slugs.filter((s) => !have.has(s));
      const already = slugs.filter((s) => have.has(s));
      added.forEach((s) => SCOPE[body.investigation].push({ entity_type: wl.entity_type, entity_slug: s }));
      const inv = INVESTIGATIONS.find((i) => i.slug === body.investigation);
      return ok({ investigation: body.investigation, investigation_name: inv.display_name, added, already_in_scope: already });
    }
    m = u.match(/^\/api\/work-lists\/([^/?]+)\/investigation$/);
    if (m && method === 'PUT') {
      WORK_LISTS.find((w) => w.slug === m[1]).investigation = body.investigation;
      return ok({});
    }
    if (u.startsWith('/api/work-lists/') && !u.startsWith('/api/work-lists/runs')) {
      const slug = decodeURIComponent(u.replace('/api/work-lists/', '').split('?')[0]);
      if (!slug) return ok(WORK_LISTS.map((w) => ({ ...w })));
      const row = WORK_LISTS.find((w) => w.slug === slug);
      return ok({ ...row, members: membersOf(slug, row.member_count) });
    }
    if (/\/api\/analyses\/(repo|database|filesystem)(\?|$)/.test(u)) return ok([]);
    if (u.includes('/api/analyses/facts')) return ok({ states: {}, subjects: {} });
    if (u.includes('/api/doc-sources/')) return ok({ sources: [], published: false, publish_note: '' });
    if (u.includes('/api/context/')) return ok({ enrichment: {}, question_answers: {} });
    if (u.includes('/questions')) return ok({ questions: [{ question: 'Who owns it?', kind: 'human', analysis_ids: [] }] });
    if (u === '/api/db-servers/') return ok([]);
    if (u.includes('/subscriptions') || u.includes('/schedules') || u.includes('/groups')) return ok([]);
    return ok({});
  };
}

async function setUp({ investigation = '', open = null, index = false, narrow = false } = {}) {
  reset();
  const { document, window } = makeDomEnvironment();
  stubBackend();
  ensureLoaderRegistered();
  globalThis.location = window.location;
  globalThis.history = window.history;
  globalThis.getComputedStyle = window.getComputedStyle.bind(window);
  window.matchMedia = () => ({ matches: narrow, addEventListener() {}, removeEventListener() {} });
  window.history.replaceState(null, '', '/next');
  document.body.innerHTML = INDEX_HTML.match(/<body[^>]*>([\s\S]*)<\/body>/)[1].replace(/<script[\s\S]*?<\/script>/g, '');
  const rail = document.createElement('div');
  rail.id = 'rail-evidence';
  document.getElementById('rail').appendChild(rail);
  const api = await import('/static/re-api.js');
  api.clearCache();
  const app = await import('/static/next/app.js');
  const s = app.state;
  s.resourceType = 'db';
  s.databases = [{ slug: 'crm_prod', display_name: 'crm_prod', disposition: 'undecided', group_slug: '', working_set_hidden: false }];
  s.databasesLoaded = true; s.projects = []; s.filesystems = [];
  s.groups = [];
  s.investigations = INVESTIGATIONS.map((i) => ({ ...i }));
  s.investigation = ''; s.workingSet = new Set(); s.scopeCount = null;
  s.selected = new Set(); s.selectMode = false; s.dispositionFacet = 'all'; s.filter = ''; s.showHidden = false; s.scope = '';
  s.workLists = WORK_LISTS.map((w) => ({ ...w }));
  s.workListSlug = open; s.lastWorkListSlug = null; s.workListIndex = index; s.workListIndexNote = '';
  s.selectedSlug = 'crm_prod';
  s.stage = 'scouting'; s.subTab = 'questions'; s.lastRunStage = 'scouting';
  s.answers = new Map();
  app.renderIntentNav();
  if (investigation) await app.setInvestigation(investigation); else app.renderSidebar();
  app.renderTopBar();
  if (open) await reload(document);
  if (index) { document.querySelector('[data-act="worklists"]').click(); await tick(150); }
  return { document, window, app, s };
}

/** loadPane isn't exported: a click on the current stage's nav button re-runs it. */
async function reload(d, stage = 'scouting') {
  d.querySelector(`#intent-nav button[data-stage="${stage}"]`).click();
  await tick(200);
}
const act = (d, name) => d.querySelector(`#wl-actions [data-act="${name}"]`);
const addCalls = () => CALLS.filter((c) => /add-to-investigation$/.test(c.url));
const note = (d) => text(d.getElementById('wl-note'));

/* ── Add these N to <investigation> ─────────────────────────────────────── */

test('the add action names the current investigation, skips what is in scope, and says so', async () => {
  const { document, s } = await setUp({ investigation: 'c360', open: 'sales-databases' });
  const b = act(document, 'add-to-investigation');
  assert.equal(text(b), 'Add these 9 to Customer 360', 'names the investigation, never "scope" alone');
  assert.equal(document.querySelector('#wl-actions [data-act="publish"]').parentElement, b.parentElement, 'beside publish to Egeria');
  b.click();
  await tick(200);
  assert.equal(addCalls().length, 1);
  assert.deepEqual(addCalls()[0].body, { investigation: 'c360' }, 'every member; the server skips the ones in scope');
  assert.equal(note(document), 'Added 2 to Customer 360. 7 were already in scope; their reasons were kept.');
  assert.equal(s.investigation, 'c360');
  assert.equal(text(document.getElementById('wl-linked')), '9 of 9 in scope for Customer 360', 'the header re-reads the scope');
});

test('one member already in scope reads in the singular', async () => {
  const { document } = await setUp({ investigation: 'c360', open: 'old-postgres' });
  SCOPE.c360.push({ entity_type: 'database', entity_slug: 'old-postgres-0' });
  act(document, 'add-to-investigation').click();
  await tick(200);
  assert.equal(note(document), 'Added 3 to Customer 360. 1 was already in scope; its reason was kept.');
});

test('with rows ticked the button reads "Add 3 selected to Customer 360" and sends only those', async () => {
  const { document } = await setUp({ investigation: 'c360', open: 'old-postgres' });
  for (const r of ['old-postgres-0', 'old-postgres-2', 'old-postgres-3']) {
    const cb = document.querySelector(`input[data-row="${r}"]`);
    cb.checked = true;
    cb.dispatchEvent(new document.defaultView.Event('change', { bubbles: true }));
  }
  assert.equal(text(act(document, 'add-to-investigation')), 'Add 3 selected to Customer 360');
  act(document, 'add-to-investigation').click();
  await tick(200);
  assert.deepEqual(addCalls()[0].body, { investigation: 'c360', entity_slugs: ['old-postgres-0', 'old-postgres-2', 'old-postgres-3'] });
  assert.match(note(document), /^Added 3 to Customer 360\./);
});

test('a long investigation name is cut at 24 characters with the whole name in the title', async () => {
  const { document } = await setUp({ investigation: 'a-very-long-investigation-name-indeed', open: 'old-postgres' });
  const b = act(document, 'add-to-investigation');
  assert.equal(text(b), 'Add these 4 to A very long investigati…');
  assert.match(b.getAttribute('title'), /A very long investigation name indeed/);
});

test('with none current: "Add to an investigation…" opens the picker, then adds and makes it current', async () => {
  const { document, s } = await setUp({ open: 'old-postgres' });
  const b = act(document, 'add-to-investigation');
  assert.equal(text(b), 'Add to an investigation…');
  b.click();
  await tick(60);
  const picker = document.querySelector('[data-investigation-picker]');
  assert.ok(picker, 'the picker opens');
  assert.equal(addCalls().length, 0, 'nothing is written before a choice');
  picker.querySelector('[data-pick-investigation="c360"]').click();
  await tick(250);
  assert.equal(addCalls().length, 1);
  assert.equal(addCalls()[0].body.investigation, 'c360');
  assert.equal(s.investigation, 'c360', 'the chosen investigation becomes current');
  assert.match(note(document), /^Added 4 to Customer 360, now your current investigation\./);
  assert.equal(text(act(document, 'add-to-investigation')), 'Add these 4 to Customer 360');
});

/* ── Start an investigation from this list… ─────────────────────────────── */

test('"Start an investigation from this list…": prefilled dialog, binding shown, Start creates, adds, tags, makes current; the list stays', async () => {
  const { document, s } = await setUp({ open: 'old-postgres' });
  act(document, 'start-from-list').click();
  await tick(100);
  const d = document.querySelector('[data-start-from-list]');
  assert.ok(d, 'the dialog opens');
  assert.equal(d.querySelector('#sfl-name').value, 'Old Postgres');
  assert.equal(d.querySelector('#sfl-desc').value, 'Legacy boxes to look at');
  const chips = [...d.querySelectorAll('[data-sfl-purpose]')];
  assert.deepEqual(chips.map((c) => c.value), ['Migration', 'Audit']);
  assert.ok(chips.every((c) => !c.checked), 'purpose chips unselected');
  const binding = d.querySelector('#sfl-binding');
  assert.deepEqual([...binding.options].map((o) => o.value), ['egeria', 'local'], 'the binding is shown and chosen');
  assert.equal(binding.value, 'egeria', 'default Egeria');
  assert.equal(CALLS.length, 0, 'nothing written until Start');
  d.querySelector('#sfl-start').click();
  await tick(300);

  const create = CALLS.find((c) => c.method === 'POST' && c.url === '/api/investigations/');
  assert.equal(create.body.display_name, 'Old Postgres');
  assert.equal(create.body.description, 'Legacy boxes to look at');
  assert.deepEqual(create.body.purposes, []);
  assert.equal(create.body.egeria_binding, 'egeria');
  assert.equal(addCalls()[0].url, '/api/work-lists/old-postgres/add-to-investigation');
  assert.deepEqual(addCalls()[0].body, { investigation: 'from-sales' });
  const link = CALLS.find((c) => c.method === 'PUT');
  assert.equal(link.url, '/api/work-lists/old-postgres/investigation');
  assert.deepEqual(link.body, { investigation: 'from-sales' });
  assert.equal(s.investigation, 'from-sales', 'made current');
  assert.equal(document.querySelector('[data-start-from-list]'), null, 'the dialog closed');

  // The list stays: still open, still in the sidebar, now under the investigation.
  assert.equal(s.workListSlug, 'old-postgres');
  assert.ok(document.getElementById('wl-grid'));
  assert.match(note(document), /^Started Old Postgres, now your current investigation, with 4 in scope\./);
  assert.equal(text(document.getElementById('wl-linked')), '4 of 4 in scope for Old Postgres');
  const sb = document.getElementById('sidebar');
  assert.equal(text(sb.querySelector('[data-linked-lists-head]')), 'Work lists for Old Postgres · 1');
  assert.ok(sb.querySelector('button[data-worklist="old-postgres"]'));
});

test('Start with a purpose and the local binding chosen sends both', async () => {
  const { document } = await setUp({ open: 'old-postgres' });
  act(document, 'start-from-list').click();
  await tick(100);
  const d = document.querySelector('[data-start-from-list]');
  const chip = d.querySelector('[data-sfl-purpose][value="Audit"]');
  chip.checked = true;
  const sel = d.querySelector('#sfl-binding');
  sel.value = 'local';
  d.querySelector('#sfl-start').click();
  await tick(300);
  const create = CALLS.find((c) => c.url === '/api/investigations/');
  assert.deepEqual(create.body.purposes, ['Audit']);
  assert.equal(create.body.egeria_binding, 'local');
});

/* ── The linked header and the scope column ─────────────────────────────── */

test('a linked list says "7 of 9 in scope for Customer 360 · 2 not added" and each row says which', async () => {
  const { document } = await setUp({ open: 'sales-databases' });
  assert.equal(text(document.getElementById('wl-linked')), '7 of 9 in scope for Customer 360 · 2 not added');
  const cells = [...document.querySelectorAll('[data-scope-cell]')];
  assert.equal(cells.length, 9);
  assert.equal(cells.filter((c) => text(c) === 'in scope').length, 7);
  assert.equal(cells.filter((c) => text(c) === 'not in scope').length, 2);
  assert.equal(text(document.querySelector('[data-scope-cell="sales-databases-7"]')), 'not in scope', 'the repo of the same name does not count');
  // In ink: no glyph, no accent or state colour.
  for (const c of cells) {
    assert.ok(!/accent|state-|font-glyph/.test(c.className), c.className);
    assert.equal(c.children.length, 0, 'plain words, no mark');
  }
  assert.ok(!/accent|state-/.test(document.getElementById('wl-linked').className));
});

test('drift shows: a member removed from scope turns 7 of 9 into 6 of 9', async () => {
  const { document, s } = await setUp({ open: 'sales-databases' });
  assert.match(text(document.getElementById('wl-linked')), /^7 of 9 /);
  SCOPE.c360 = SCOPE.c360.filter((m) => m.entity_slug !== 'sales-databases-3');
  await reload(document);
  assert.equal(text(document.getElementById('wl-linked')), '6 of 9 in scope for Customer 360 · 3 not added');
  assert.equal(text(document.querySelector('[data-scope-cell="sales-databases-3"]')), 'not in scope');
  assert.equal(s.workListSlug, 'sales-databases');
});

test('the narrow (phone) view says in scope / not in scope too', async () => {
  const { document } = await setUp({ open: 'sales-databases', narrow: true });
  assert.match(text(document.getElementById('wl-grid')), /1 of 9 · scouting · in scope/);
  assert.equal(text(document.getElementById('wl-linked')), '7 of 9 in scope for Customer 360 · 2 not added');
});

test('an unlinked list has no header and no scope column', async () => {
  const { document } = await setUp({ open: 'old-postgres' });
  assert.equal(text(document.getElementById('wl-linked')), '');
  assert.equal(document.querySelector('[data-scope-col]'), null);
  assert.equal(document.querySelectorAll('[data-scope-cell]').length, 0);
});

test('a scope that cannot be read is said so, never shown as "0 in scope"', async () => {
  const { document } = await setUp({ open: 'sales-databases' });
  const real = globalThis.fetch;
  globalThis.fetch = async (u, o) => (/\/api\/investigations\/c360\/members$/.test(String(u))
    ? { ok: false, status: 500, json: async () => ({ detail: 'boom' }), text: async () => 'boom' } : real(u, o));
  await reload(document);
  assert.match(text(document.getElementById('wl-linked')), /scope of Customer 360 could not be read/);
  assert.doesNotMatch(text(document.getElementById('wl-linked')), /0 of/);
  assert.equal(text(document.querySelector('[data-scope-cell="sales-databases-0"]')), 'scope unknown');
});

/* ── The list of work lists ─────────────────────────────────────────────── */

test('the ▦ index shows the investigation’s NAME, not its slug', async () => {
  const { document } = await setUp({ index: true });
  const row = document.querySelector('[data-open-wl="sales-databases"]');
  assert.match(text(row), /Customer 360/);
  assert.doesNotMatch(text(row), /c360/);
});

test('each index row carries both actions; none current reads "Add to an investigation…"', async () => {
  const { document } = await setUp({ index: true });
  assert.equal(text(document.querySelector('[data-wl-add="old-postgres"]')), 'Add to an investigation…');
  assert.equal(text(document.querySelector('[data-wl-start="old-postgres"]')), 'Start an investigation from this list…');
  assert.equal(document.querySelector('[data-open-wl] button'), null, 'no button nested in a button');
});

test('index row, one current: "Add these 4 to Customer 360" adds and the note is shown there', async () => {
  const { document } = await setUp({ investigation: 'c360', index: true });
  const b = document.querySelector('[data-wl-add="old-postgres"]');
  assert.equal(text(b), 'Add these 4 to Customer 360');
  b.click();
  await tick(300);
  assert.deepEqual(addCalls()[0].body, { investigation: 'c360' });
  assert.equal(text(document.getElementById('wl-index-note')), 'Added 4 to Customer 360.');
});

test('index row, none current: the picker opens, then it adds', async () => {
  const { document, s } = await setUp({ index: true });
  document.querySelector('[data-wl-add="old-postgres"]').click();
  await tick(60);
  document.querySelector('[data-investigation-picker] [data-pick-investigation="c360"]').click();
  await tick(300);
  assert.equal(addCalls()[0].url, '/api/work-lists/old-postgres/add-to-investigation');
  assert.equal(s.investigation, 'c360');
});

test('index row Start opens the prefilled dialog for THAT list', async () => {
  const { document } = await setUp({ index: true });
  document.querySelector('[data-wl-start="old-postgres"]').click();
  await tick(100);
  assert.equal(document.querySelector('#sfl-name').value, 'Old Postgres');
});

/* ── Vocabulary guards ─────────────────────────────────────────────────── */

test('no "working set" label, no new glyph file entry, no delete wording', async () => {
  const src = fs.readFileSync(path.join(NEXT_DIR, 'worklist-actions.js'), 'utf8');
  assert.doesNotMatch(src, /working set/i);
  assert.doesNotMatch(src, /delete/i);
  const { document } = await setUp({ investigation: 'c360', open: 'sales-databases' });
  assert.doesNotMatch(document.body.textContent, /working set/i);
});
