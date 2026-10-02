/** Behaviour: the Curate pane draws the designer's three bands on every kind,
 *  and its controls call the right API shapes.
 *  (REPLY-DESIGNER-CURATE-AND-UNDERSTANDING-ALL-KINDS.md §1-2;
 *  CURATE-UI-DATABASES-IMPLEMENTED.md.)
 *
 *  Real app.js, real router: the real Curate nav button is clicked, the
 *  stage draws through loadPane -> renderCurate. A stateful stub server
 *  stands behind fetch so every list the UI shows is a re-read of what the
 *  "server" holds after the write -- which is also what lets the
 *  known-negatives make the server drop a write and watch the status words
 *  follow the rows rather than the click.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const UNSIGNED = 'unsigned · from before authors were recorded';

function makeServer(over = {}) {
  const s = {
    calls: [],
    tags: [{ tag: 'sales', created_at: '2026-09-01T10:00:00', author: 'mchessell', authored: true, author_label: 'mchessell' }],
    allTags: [{ tag: 'sales', count: 3 }, { tag: 'postgres', count: 2 }],
    feedback: [
      { id: 'f1', rating: 5, category: 'usefulness', message: 'Good sample.', created_at: '2026-09-30T10:00:00', author: 'mchessell', authored: true, author_label: 'mchessell' },
      { id: 'f2', rating: 5, category: '', message: 'Loved it.', created_at: '2026-09-29T10:00:00', author: 'jdoe', authored: true, author_label: 'jdoe' },
      { id: 'f3', rating: 3, category: '', message: 'Fine.', created_at: '2026-09-28T10:00:00', author: 'jdoe', authored: true, author_label: 'jdoe' },
      { id: 'f4', rating: 2, category: 'documentation', message: 'No column comments.', created_at: '2026-08-14T10:00:00', author: null, authored: false, author_label: UNSIGNED },
    ],
    notes: [
      { id: 'n-legacy', note: 'Old unsigned remark.', created_at: '2026-08-01T10:00:00', author: null, authored: false, author_label: UNSIGNED },
      { id: 'n-signed', note: 'Signed Classic remark.', created_at: '2026-09-20T10:00:00', author: 'dwolfson', authored: true, author_label: 'dwolfson' },
    ],
    journal: [{ id: 'j1', body: 'Use the sales schema only.', author: 'dwolfson', written_at: '2026-09-29T10:00:00', suggested_to: [] }],
    groups: [{ slug: 'sales-platform', display_name: 'Sales platform' }, { slug: 'other', display_name: 'Other' }],
    groupOf: { adventureworks: 'sales-platform' },
    signedIn: true,
    dropWrites: false,   // known-negative: the server accepts a write and persists nothing
    status: {},          // path-substring -> status to answer instead
    ...over,
  };
  globalThis.fetch = async (url, opts = {}) => {
    const u = String(url);
    const method = opts.method || 'GET';
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    s.calls.push({ method, url: u, body });
    const ok = (b, status = 200) => ({ ok: true, status, json: async () => b });
    const err = (status, detail) => ({ ok: false, status, statusText: detail, json: async () => ({ detail }) });
    for (const [frag, st] of Object.entries(s.status)) if (u.includes(frag) && method !== 'GET') return err(st, `forced ${st}`);
    const m = u.match(/\/api\/curate\/(tags-detail|tags|feedback|notes)\/(?:[a-z]+)\/([^/?]+)(?:\/([^/?]+))?/);
    if (method === 'GET' && u.endsWith('/api/curate/tags')) return ok(s.allTags);
    if (m) {
      const [, kind, , extra] = m;
      if (method === 'GET') return ok(kind === 'feedback' ? s.feedback : kind === 'notes' ? s.notes : s.tags);
      if (!s.signedIn) return err(401, 'Sign in to do that');
      if (kind === 'tags' && method === 'POST') {
        const t = body.tag.trim().toLowerCase();
        if (!s.dropWrites) s.tags.push({ tag: t, created_at: '2026-10-01T10:00:00', author: 'me', authored: true, author_label: 'me' });
        return ok({ status: 'success', tag: t, author: 'me' });
      }
      if (kind === 'tags' && method === 'DELETE') {
        if (!s.dropWrites) s.tags = s.tags.filter((t) => t.tag !== decodeURIComponent(extra));
        return ok({ status: 'success', removed_by: 'me' });
      }
      if (kind === 'feedback' && method === 'POST') {
        if (!s.dropWrites) s.feedback.push({ id: 'new', ...body, created_at: '2026-10-01T10:00:00', author: 'me', authored: true, author_label: 'me' });
        return ok({ id: 'new' });
      }
    }
    if (method === 'DELETE' && u.includes('/api/curate/notes/')) {
      if (!s.signedIn) return err(401, 'Sign in');
      const id = decodeURIComponent(u.split('/api/curate/notes/')[1]);
      const n = s.notes.find((x) => x.id === id);
      if (n && n.authored) return err(409, 'A signed note cannot be deleted — notes are append-only.');
      if (!s.dropWrites) s.notes = s.notes.filter((x) => x.id !== id);
      return ok({ status: 'success' });
    }
    if (u.includes('/api/journal/')) {
      if (method === 'GET') return ok({ entries: s.journal, suggested_to: [] });
      if (!s.signedIn) return err(401, 'Sign in');
      s.journal.push({ id: 'j-new', body: body.body, author: 'me', written_at: '2026-10-01T10:00:00', suggested_to: body.suggest_to });
      return ok({ id: 'j-new', work_lists: [] });
    }
    if (u.endsWith('/group') && method === 'POST') {
      s.groupOf.adventureworks = body.group_slug;
      return ok({ slug: 'adventureworks', group_slug: body.group_slug });
    }
    if (u.includes('/api/projects/groups')) return ok(s.groups);
    if (u.includes('/api/databases/')) return ok([{ slug: 'adventureworks', group_slug: s.groupOf.adventureworks || '' }]);
    if (u.includes('/api/filesystems/')) return ok([{ slug: 'adventureworks', group_slug: '' }]);
    if (u.includes('/api/projects/?')) return ok([]);
    if (u.includes('/curate/plan')) return ok({
      technology_type: 'Git repository', disposition: 'using', in_population: true,
      last_surveyed_at: null, what_it_is: [], what_it_holds: [], relates: [], commits: [],
    });
    if (u.includes('/components/tree')) return ok({ branches: [], topology: '' });
    if (u.includes('/blueprints')) return ok({ blueprints: [], perspectives: [] });
    if (u.includes('/questions')) return ok({ questions: [] });
    if (u.includes('/api/context/')) return ok({ enrichment: {}, question_answers: {} });
    if (u.includes('/investigations') || u.includes('/subscriptions') || u.includes('/schedules')) return ok([]);
    return ok({});
  };
  return s;
}

const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms));

async function setUp(resourceType, serverOver = {}, { signedIn = true } = {}) {
  const { document, window } = makeDomEnvironment();
  const server = makeServer({ signedIn, ...serverOver });
  ensureLoaderRegistered();
  globalThis.location = window.location;
  globalThis.history = window.history;
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const app = await import('/static/next/app.js');
  app.state.resourceType = resourceType;
  app.state.selectedSlug = 'adventureworks';
  app.state.stage = 'understanding';
  app.state.subTab = 'questions';
  app.state.investigations = [];
  app.state.investigation = '';
  app.state.workListSlug = null;
  app.state.workListIndex = false;
  app.state.me = signedIn ? { user_id: 'me' } : null;
  app.state.groups = server.groups;
  app.state.databasesLoaded = true;
  app.state.filesystemsLoaded = true;
  app.state.databases = [{ slug: 'adventureworks', group_slug: server.groupOf.adventureworks || '' }];
  app.state.filesystems = [{ slug: 'adventureworks', group_slug: '' }];
  app.state.perspectives = []; app.state.allPerspectives = [];
  for (const id of ['content', 'intent-nav', 'rail-evidence', 'perspective-row', 'app-grid']) {
    const d = document.createElement('div');
    d.id = id;
    document.body.appendChild(d);
  }
  app.renderIntentNav();
  return { document, app, server };
}

async function openCurate(document) {
  const btn = document.querySelector('#intent-nav button[data-stage="curate"]');
  assert.ok(btn, 'nav must offer a Curate button');
  btn.click();
  await wait();
}

const host = (d) => d.getElementById('curate-host');
const band = (d, name) => host(d).querySelector(`[data-curate-band="${name}"]`);
const q = (d, sel) => host(d).querySelector(sel);
const calls = (server, method, frag) => server.calls.filter((c) => c.method === method && c.url.includes(frag));

/* ── three bands on a database ─────────────────────────────────────────── */

test('Curate on a database draws the three bands with the real controls', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  assert.ok(host(document), 'Curate must have a host');
  // band 1: Findable
  const f = band(document, 'findable');
  assert.match(f.textContent, /Findable/);
  assert.match(f.textContent, /local · not in Egeria/);
  assert.match(f.textContent, /Sales platform/, 'current group is named');
  assert.ok(f.querySelector('[data-curate-group-select]') && f.querySelector('[data-curate-group-save]'), 'inline group change control');
  assert.ok(f.querySelector('[data-curate-tag="sales"]'), 'tag chip');
  assert.ok(f.querySelector('[data-curate-tag-input]') && f.querySelector('[data-curate-tag-add]'));
  const opts = [...f.querySelectorAll('#curate-tag-datalist option')].map((o) => o.value);
  assert.deepEqual(opts, ['sales', 'postgres'], 'autocomplete is GET /api/curate/tags');
  // band 2: the kind's own work, present with the sentence naming what it waits for
  const k = band(document, 'kind').textContent;
  assert.match(k, /Glossary terms on tables and columns/);
  assert.match(k, /needs data classes per column \(data_class_match\) and a glossary to match against/);
  assert.match(k, /Logical schema match/);
  assert.match(k, /needs the logical schemas Egeria knows to be read/);
  assert.equal(band(document, 'kind').querySelectorAll('table').length, 0, 'never an empty table');
  // band 3: what people say
  const p = band(document, 'people');
  assert.match(p.textContent, /What people say/);
  assert.ok(p.querySelector('[data-curate-fb-rating]') && p.querySelector('[data-curate-fb-submit]'));
  assert.ok(p.querySelector('#journal-save') && p.querySelector('#journal-body'), 'notes band is the journal');
  // order: findable, kind, people
  const order = [...host(document).querySelectorAll('[data-curate-band]')].map((e) => e.dataset.curateBand);
  assert.deepEqual(order, ['findable', 'kind', 'people']);
  // the false sentences are gone and no repo-only call fired
  assert.doesNotMatch(host(document).textContent, /reachable from the resource header|offers none of them|Curate isn't available/);
  assert.equal(server.calls.filter((c) => c.url.includes('/curate/plan')).length, 0);
});

/* ── tags ──────────────────────────────────────────────────────────────── */

test('adding a tag POSTs {tag} and the chip comes from the re-read list', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  const input = q(document, '[data-curate-tag-input]');
  input.value = 'Sample-Data';
  q(document, '[data-curate-tag-add]').click();
  await wait();
  const [c] = calls(server, 'POST', '/api/curate/tags/database/adventureworks');
  assert.ok(c, 'tag add must POST /api/curate/tags/database/adventureworks');
  assert.deepEqual(c.body, { tag: 'Sample-Data' });
  assert.ok(q(document, '[data-curate-tag="sample-data"]'), 'chip drawn from the re-read (server lower-cases)');
  assert.match(q(document, '[data-curate-findable-status]').textContent, /“sample-data” is on the list/);
});

test('removing a tag DELETEs /tags/{type}/{slug}/{tag}', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  q(document, '[data-curate-tag-remove="sales"]').click();
  await wait();
  assert.equal(calls(server, 'DELETE', '/api/curate/tags/database/adventureworks/sales').length, 1);
  assert.equal(q(document, '[data-curate-tag="sales"]'), null);
  assert.match(q(document, '[data-curate-findable-status]').textContent, /off the list/);
});

test('KNOWN-NEGATIVE: a server that drops the write does not get an "added" status', async () => {
  const { document } = await setUp('db', { dropWrites: true });
  await openCurate(document);
  q(document, '[data-curate-tag-input]').value = 'ghost';
  q(document, '[data-curate-tag-add]').click();
  await wait();
  assert.equal(q(document, '[data-curate-tag="ghost"]'), null);
  const s = q(document, '[data-curate-findable-status]').textContent;
  assert.match(s, /not in the re-read list/);
  assert.doesNotMatch(s, /is on the list/);
});

test('a 401 from the tag route says to sign in, in words', async () => {
  const { document } = await setUp('db', { status: { '/api/curate/tags/': 401 } });
  await openCurate(document);
  q(document, '[data-curate-tag-input]').value = 'x';
  q(document, '[data-curate-tag-add]').click();
  await wait();
  assert.match(q(document, '[data-curate-findable-status]').textContent, /sign in to add the tag/);
});

/* ── group ─────────────────────────────────────────────────────────────── */

test('changing the group POSTs resource_type database and the new group', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  const sel = q(document, '[data-curate-group-select]');
  sel.value = 'other';
  q(document, '[data-curate-group-save]').click();
  await wait();
  const [c] = calls(server, 'POST', '/api/projects/adventureworks/group');
  assert.ok(c);
  assert.deepEqual(c.body, { resource_type: 'database', group_slug: 'other' });
  assert.match(q(document, '[data-curate-group-now]').textContent, /Other/);
  assert.match(q(document, '[data-curate-findable-status]').textContent, /group is now Other/);
});

/* ── ratings ───────────────────────────────────────────────────────────── */

test('ratings are counts with no average, each entry signed and dated; unsigned shows the label', async () => {
  const { document } = await setUp('db');
  await openCurate(document);
  const h = q(document, '[data-curate-ratings-headline]').textContent;
  assert.match(h, /4 · ★★★★★ 2 · ★★★ 1 · ★★ 1/);
  const all = band(document, 'people').textContent;
  assert.doesNotMatch(all, /average|avg|mean|\d\.\d\s*(\/|out of)\s*5/i, 'never an average or a score');
  const entries = [...host(document).querySelectorAll('[data-curate-feedback]')].map((e) => e.textContent);
  assert.equal(entries.length, 4);
  assert.ok(entries.some((t) => /mchessell · 2026-09-30/.test(t)), 'signed and dated');
  assert.ok(entries.some((t) => t.includes(UNSIGNED)), 'legacy entry says it is unsigned');
});

test('KNOWN-NEGATIVE: a legacy row with no author_label from the server still shows the unsigned words', async () => {
  const { document } = await setUp('db', {
    feedback: [{ id: 'x', rating: 4, category: '', message: 'old', created_at: '2026-01-01T00:00:00', author: null }],
  });
  await openCurate(document);
  assert.match(q(document, '[data-curate-feedback]').textContent, /unsigned · from before authors were recorded/);
});

test('submitting a rating POSTs {rating, category, message}; list comes from the re-read', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  q(document, '[data-curate-fb-rating]').value = '4';
  q(document, '[data-curate-fb-category]').value = 'quality';
  q(document, '[data-curate-fb-message]').value = 'Solid.';
  q(document, '[data-curate-fb-submit]').click();
  await wait();
  const [c] = calls(server, 'POST', '/api/curate/feedback/database/adventureworks');
  assert.ok(c);
  assert.deepEqual(c.body, { rating: 4, category: 'quality', message: 'Solid.' });
  assert.match(q(document, '[data-curate-ratings-headline]').textContent, /5 · ★★★★★ 2 · ★★★★ 1/);
  assert.match(q(document, '[data-curate-ratings-status]').textContent, /it is in the list above/);
});

test('a message is required: no POST without one', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  q(document, '[data-curate-fb-submit]').click();
  await wait(50);
  assert.equal(calls(server, 'POST', '/api/curate/feedback').length, 0);
  assert.match(q(document, '[data-curate-ratings-status]').textContent, /feedback needs one/);
});

/* ── notes: the journal, and Classic's notes read-only beneath ─────────── */

test('a journal entry POSTs {body, suggest_to} to /api/journal/database/{slug} and appears', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  assert.match(q(document, '#journal-entries').textContent, /Use the sales schema only/);
  q(document, '#journal-body').value = 'Archive-shaped production.* tables.';
  q(document, '#journal-save').click();
  await wait();
  const [c] = calls(server, 'POST', '/api/journal/database/adventureworks');
  assert.ok(c);
  assert.deepEqual(c.body, { body: 'Archive-shaped production.* tables.', suggest_to: [] });
  assert.match(q(document, '#journal-entries').textContent, /Archive-shaped production/);
});

test('Classic notes: legacy unsigned note has the label and a delete; a signed note has no delete', async () => {
  const { document, server } = await setUp('db');
  await openCurate(document);
  const legacy = q(document, '[data-curate-classic-note="n-legacy"]');
  const signed = q(document, '[data-curate-classic-note="n-signed"]');
  assert.match(legacy.textContent, /unsigned · from before authors were recorded/);
  assert.ok(legacy.querySelector('[data-curate-note-delete]'), 'unsigned note is deletable');
  assert.match(signed.textContent, /dwolfson/);
  assert.equal(signed.querySelector('[data-curate-note-delete]'), null, 'a signed note has no delete control');
  assert.match(band(document, 'people').textContent, /Curator notes from Classic · 2 · 1 unsigned/);
  // newest first
  const ids = [...host(document).querySelectorAll('[data-curate-classic-note]')].map((e) => e.dataset.curateClassicNote);
  assert.deepEqual(ids, ['n-signed', 'n-legacy']);
  // delete asks first, then DELETEs, then re-reads
  legacy.querySelector('[data-curate-note-delete]').click();
  assert.equal(calls(server, 'DELETE', '/api/curate/notes/').length, 0, 'asks before deleting');
  legacy.querySelector('[data-yes]').click();
  await wait();
  assert.equal(calls(server, 'DELETE', '/api/curate/notes/n-legacy').length, 1);
  assert.equal(q(document, '[data-curate-classic-note="n-legacy"]'), null);
  assert.match(q(document, '[data-curate-notes-status]').textContent, /note deleted/);
});

test('there is no edit control for a journal entry or any note', async () => {
  const { document } = await setUp('db');
  await openCurate(document);
  const txt = band(document, 'people').innerHTML;
  assert.doesNotMatch(txt, /data-[a-z-]*(edit|amend)|>\s*edit\s*</i);
});

/* ── signed out ────────────────────────────────────────────────────────── */

test('signed out: every write control is disabled and says why', async () => {
  const { document, server } = await setUp('db', {}, { signedIn: false });
  await openCurate(document);
  const disabled = (sel) => {
    const els = [...host(document).querySelectorAll(sel)];
    assert.ok(els.length, `control ${sel} must be present`);
    for (const e of els) assert.ok(e.disabled, `${sel} must be disabled when signed out`);
  };
  disabled('[data-curate-tag-input]');
  disabled('[data-curate-tag-add]');
  disabled('[data-curate-tag-remove]');
  disabled('[data-curate-fb-rating]');
  disabled('[data-curate-fb-category]');
  disabled('[data-curate-fb-message]');
  disabled('[data-curate-fb-submit]');
  disabled('[data-curate-note-delete]');
  disabled('#journal-save');
  const text = host(document).textContent;
  assert.match(q(document, '[data-curate-findable-status]').textContent, /sign in to add or remove a tag — it needs an author/);
  assert.match(q(document, '[data-curate-ratings-status]').textContent, /sign in to rate or comment — it needs an author/);
  assert.match(text, /sign in to write — an entry needs an author/);
  q(document, '[data-curate-tag-add]').click();
  q(document, '#journal-save').click();
  await wait(50);
  assert.equal(server.calls.filter((c) => c.method !== 'GET').length, 0, 'no write is sent while signed out');
});

/* ── file share, repository ────────────────────────────────────────────── */

test('a file share gets the one honest sentence and the shared bands, no kind sections', async () => {
  const { document } = await setUp('filesystem');
  await openCurate(document);
  assert.match(band(document, 'kind').textContent,
    /Nothing to review for file shares yet\. Group, tags, ratings and notes above and below apply\./);
  assert.doesNotMatch(band(document, 'kind').textContent, /Glossary terms|Logical schema match/);
  assert.ok(band(document, 'findable').querySelector('[data-curate-tag-input]'));
  assert.ok(band(document, 'people').querySelector('[data-curate-fb-submit]'));
});

test('a database does not get the file-share sentence', async () => {
  const { document } = await setUp('db');
  await openCurate(document);
  assert.doesNotMatch(host(document).textContent, /Nothing to review for file shares/);
});

test('a repository keeps its plan view in the middle, with the bands around it', async () => {
  const { document, server } = await setUp('repo');
  await openCurate(document);
  assert.match(band(document, 'kind').textContent, /disposition/, 'existing plan view still renders');
  assert.doesNotMatch(band(document, 'kind').textContent, /Assembling what the catalogue/);
  assert.ok(server.calls.some((c) => c.url.includes('/curate/plan')));
  assert.ok(band(document, 'findable').querySelector('[data-curate-tag-input]'));
  assert.ok(band(document, 'people').querySelector('[data-curate-fb-submit]'));
  assert.ok(calls(server, 'GET', '/api/curate/tags-detail/repo/adventureworks').length >= 1, 'repo tags use entity type repo');
  assert.equal(band(document, 'kind').querySelector('[data-curate-work]'), null, 'no database sections on a repo');
});

/* ── a band that cannot read says so ───────────────────────────────────── */

test('a band whose read fails shows a visible message, not nothing', async () => {
  const { document, server } = await setUp('db');
  const real = globalThis.fetch;
  globalThis.fetch = async (url, o) => {
    if (String(url).includes('/api/curate/feedback/')) return { ok: false, status: 500, statusText: 'boom', json: async () => ({ detail: 'boom' }) };
    return real(url, o);
  };
  await openCurate(document);
  assert.match(band(document, 'people').textContent, /Ratings could not be read: boom/);
  assert.ok(band(document, 'findable').querySelector('[data-curate-tag-input]'), 'other bands still draw');
  void server;
});
