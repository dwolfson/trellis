/** Behaviour: Curate for a DATABASE draws "What gets catalogued" as the first
 *  section of band 2 -- the scope tree, the depth line, proposals, the four
 *  observation states, inheritance, name conflicts and "new since" rows --
 *  and its controls call the right API shapes.
 *  (the designer reply on catalogue scope (page 18 of the CatalogueScope wireframe); slice A, no commit,
 *  nothing is sent to Egeria.)
 *
 *  Real app.js, real router, the real Curate nav button. A stateful stub
 *  stands behind fetch so every row shown is a re-read of what the "server"
 *  holds after a write; the known-negative makes it drop a write.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms));
const flat = (el) => el.textContent.replace(/\s+/g, ' ').trim();

const node = (kind, name, over = {}) => ({
  kind, name, key: name, state: 'undecided', proposal: null, live_proposal: null, overridden: null,
  disagrees: null, notes: [], marks: [], explicit: null, effective: null, effective_from: null,
  new_since: false, conflict: null, access: 'established', provenance: '',
  last_write: { state: 'not_established', from: '', to: '' },
  data_classes: { state: 'not_established', classes: [], pii_columns: 0 }, ...over,
});
const table = (schema, name, over = {}) => node('table', name, {
  schema, key: `${schema}.${name}`, table_type: 'BASE TABLE', row_count: 10, row_count_state: 'measured',
  inherited: null, differs_from_schema: false, column_count: 1, ...over,
});
const schema = (name, tables = [], over = {}) => node('schema', name, {
  classification: 'data', table_count: tables.length, row_total: 20, bytes_total: null, is_estimate: false,
  undecided_words: 'keeps what’s in Egeria now', tables, ...over,
});
const person = (choice, by = 'dwolfson', at = '2026-10-04T10:00:00', extra = {}) => ({
  choice, action: 'set', source: 'person', by, at, reason: '', proposal_rule: '', proposal_choice: '',
  measured_at: '', measured: {}, ...extra,
});

function baseView(over = {}) {
  return {
    database: 'adventureworks',
    egeria_element: { guid: 'abcdef12-0', short: 'abcdef12', text: 'abcdef12' },
    survey: { state: 'measured', schema_count: 29, table_count: 266, surveyed_at: '2026-10-03T00:00:00', report_guid: 'g' },
    declared: { declared: false, by: '', at: '', kind: '', baseline_survey_at: '' },
    depth: {
      value: 'schemas_and_tables', declared: false, by: '', at: '',
      help: 'Views follow the table lists: a view is catalogued when its name is in the table list.',
      options: [
        { id: 'database_only', label: 'the database only', how: 'no catalog target at all' },
        { id: 'schemas', label: 'schemas', how: 'an include-schema list, with an impossible table name in the include-table list' },
        { id: 'schemas_and_tables', label: 'schemas and tables', how: 'include lists, with an impossible column name in the include-column list' },
        { id: 'tables_and_columns', label: 'tables and columns', how: 'everything' },
      ],
    },
    system: { folded: 3, text: 'not catalogued: system schemas are never offered' },
    counts: { schemas_offered: 3, schemas_catalogue: 0, schemas_leave_out: 0, schemas_undecided: 3 },
    new_since: { declared: false, schemas: 0, tables: 0, tables_in_known_schemas: 0, schema_names: [], text: '' },
    conflicts: { count: 0, names: [], pairs: [] },
    schemas: [
      schema('sales', [table('sales', 'orders'), table('sales', 'customers')]),
      schema('archive', [table('archive', 'orders')]),
      schema('empty_one', [], { classification: 'no_tables', row_total: null }),
    ],
    ...over,
  };
}

const proposalFor = (choice, reason, rule = 'empty_schema') => ({
  rule, choice, reason, measured: { table_count: 0 }, measured_at: '2026-10-02T09:00:00',
});

function makeServer(view, { signedIn = true, dropWrites = false } = {}) {
  const s = { calls: [], view, signedIn, dropWrites };
  const find = (sn, tn) => {
    const sc = s.view.schemas.find((x) => x.name === sn);
    return tn ? sc.tables.find((t) => t.name === tn) : sc;
  };
  globalThis.fetch = async (url, opts = {}) => {
    const u = String(url);
    const method = opts.method || 'GET';
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    s.calls.push({ method, url: u, body });
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    const err = (status, detail) => ({ ok: false, status, statusText: detail, json: async () => ({ detail }) });
    if (u.includes('/api/catalogue-scope/')) {
      if (method === 'GET') return ok(s.view);
      if (!s.signedIn) return err(401, 'Sign in to change the scope');
      if (!s.dropWrites) {
        if (u.endsWith('/depth')) { s.view.depth.value = body.depth; s.view.depth.declared = true; s.view.depth.by = 'me'; s.view.depth.at = '2026-10-04T11:00:00'; }
        if (u.endsWith('/node')) {
          const n = find(body.schema_name, body.table_name);
          n.explicit = person(body.choice, 'me'); n.effective = body.choice; n.state = 'chosen'; n.proposal = null;
        }
        if (u.endsWith('/node/confirm')) {
          const n = find(body.schema_name, body.table_name);
          n.explicit = person(n.proposal.choice, 'me', '2026-10-04T11:00:00', { action: 'confirm', source: n.proposal.rule, reason: n.proposal.reason });
          n.effective = n.proposal.choice; n.state = 'confirmed'; n.proposal = null;
        }
        if (u.endsWith('/node/override')) {
          const n = find(body.schema_name, body.table_name);
          const o = n.proposal; const choice = o.choice === 'leave_out' ? 'catalogue' : 'leave_out';
          n.explicit = person(choice, 'me', '2026-10-04T11:00:00', { action: 'override', proposal_rule: o.rule, proposal_choice: o.choice, reason: o.reason });
          n.effective = choice; n.state = 'overridden'; n.overridden = { rule: o.rule, choice: o.choice, reason: o.reason }; n.proposal = null;
        }
        if (u.endsWith('/node/clear')) {
          const n = find(body.schema_name, body.table_name);
          n.explicit = null; n.effective = null; n.state = 'undecided';
        }
        if (u.endsWith('/resolve')) {
          for (const sc of s.view.schemas) for (const t of sc.tables) {
            if (t.name === body.name && t.conflict) {
              t.explicit = person(body.choice, 'me'); t.effective = body.choice; t.state = 'chosen'; t.conflict = null;
            }
          }
          s.view.conflicts = { count: 0, names: [], pairs: [] };
        }
        if (u.endsWith('/redeclare')) { s.view.new_since = { declared: true, schemas: 0, tables: 0, tables_in_known_schemas: 0, schema_names: [], text: '' }; for (const sc of s.view.schemas) { sc.new_since = false; sc.tables.forEach((t) => { t.new_since = false; }); } }
      }
      return ok({ state: 'ok' });
    }
    if (u.includes('/api/journal/')) return ok({ entries: [], suggested_to: [] });
    if (u.includes('/api/curate/') || u.includes('/api/projects/groups') || u.includes('/api/projects/?')) return ok([]);
    if (u.includes('/api/databases/')) return ok([{ slug: 'adventureworks', group_slug: '' }]);
    if (u.includes('/api/filesystems/')) return ok([{ slug: 'adventureworks', group_slug: '' }]);
    return ok({});
  };
  return s;
}

async function setUp(view, opts = {}) {
  const { document, window } = makeDomEnvironment();
  const signedIn = opts.signedIn !== false;
  const server = makeServer(view, { signedIn, dropWrites: !!opts.dropWrites });
  ensureLoaderRegistered();
  (await import('/static/next/stages/curate-scope.js')).resetScopeUi();
  globalThis.location = window.location;
  globalThis.history = window.history;
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const app = await import('/static/next/app.js');
  app.state.resourceType = 'db';
  app.state.selectedSlug = 'adventureworks';
  app.state.stage = 'understanding';
  app.state.subTab = 'questions';
  app.state.investigations = [];
  app.state.investigation = '';
  app.state.workListSlug = null;
  app.state.workListIndex = false;
  app.state.me = signedIn ? { user_id: 'me' } : null;
  app.state.groups = [];
  app.state.databasesLoaded = true;
  app.state.filesystemsLoaded = true;
  app.state.databases = [{ slug: 'adventureworks', group_slug: '' }];
  app.state.filesystems = [{ slug: 'adventureworks', group_slug: '' }];
  app.state.perspectives = []; app.state.allPerspectives = [];
  for (const id of ['content', 'intent-nav', 'rail-evidence', 'perspective-row', 'app-grid']) {
    const d = document.createElement('div');
    d.id = id;
    document.body.appendChild(d);
  }
  app.renderIntentNav();
  const btn = document.querySelector('#intent-nav button[data-stage="curate"]');
  assert.ok(btn, 'nav must offer a Curate button');
  btn.click();
  await wait();
  return { document, window, app, server };
}

const scopeEl = (d) => d.querySelector('[data-curate-scope]');
const row = (d, key) => d.querySelector(`[data-scope-row="${key}"]`);
const calls = (server, method, frag) => server.calls.filter((c) => c.method === method && c.url.includes(frag));

/* ── the section, its header, the element ──────────────────────────────── */

test('the scope is the FIRST section of a database band 2, above the two waiting sections', async () => {
  const { document } = await setUp(baseView());
  const kind = document.querySelector('[data-curate-band="kind"]');
  const order = [...kind.querySelectorAll('[data-curate-work]')].map((e) => e.dataset.curateWork);
  assert.deepEqual(order, ['scope', 'glossary', 'schema-match']);
  assert.match(flat(kind.querySelector('[data-curate-work="scope"]')), /^What gets catalogued/);
  assert.match(flat(kind.querySelector('[data-curate-work="glossary"]')), /and the tables to be catalogued first \(above\)/);
  assert.match(flat(kind.querySelector('[data-curate-work="schema-match"]')), /and the tables to be catalogued first \(above\)/);
  assert.equal(kind.querySelectorAll('table').length, 0, 'never a <table>');
});

test('header, undeclared: names the scope as none declared and quotes Egeria’s latest survey', async () => {
  const { document } = await setUp(baseView());
  assert.equal(flat(document.querySelector('[data-scope-header]')),
    "Your scope: none declared yet · Egeria's latest survey covers 29 schemas, 266 tables");
  assert.match(flat(document.querySelector('[data-scope-tree-header]')), /reads Egeria element abcdef12/);
});

test('header, undeclared and never measured: says not measured yet, and an uncatalogued database says so', async () => {
  const { document } = await setUp(baseView({
    survey: { state: 'not_measured', schema_count: null, table_count: null, surveyed_at: '', report_guid: '' },
    egeria_element: { guid: '', short: '', text: 'not catalogued in Egeria' },
  }));
  assert.equal(flat(document.querySelector('[data-scope-header]')),
    "Your scope: none declared yet · Egeria's latest survey: not measured yet");
  assert.match(flat(document.querySelector('[data-scope-tree-header]')), /not catalogued in Egeria/);
});

test('header, declared: 7 of 29 schemas, declared by who and when', async () => {
  const { document } = await setUp(baseView({
    declared: { declared: true, by: 'dwolfson', at: '2026-10-04T08:00:00', kind: 'first', baseline_survey_at: '' },
    counts: { schemas_offered: 29, schemas_catalogue: 7, schemas_leave_out: 0, schemas_undecided: 22 },
  }));
  assert.equal(flat(document.querySelector('[data-scope-header]')), 'Your scope: 7 of 29 schemas · declared by dwolfson 10-04');
});

/* ── depth ─────────────────────────────────────────────────────────────── */

test('depth line: four depths, each honest about how, views follow the table lists, no Catalogue button', async () => {
  const { document, window, server } = await setUp(baseView());
  const radios = [...document.querySelectorAll('[data-scope-depth-radio]')];
  assert.deepEqual(radios.map((r) => r.dataset.scopeDepthRadio), ['database_only', 'schemas', 'schemas_and_tables', 'tables_and_columns']);
  assert.equal(radios.find((r) => r.checked).dataset.scopeDepthRadio, 'schemas_and_tables');
  assert.match(flat(document.querySelector('[data-scope-depth]')), /the database only.*schemas.*schemas and tables.*tables and columns/);
  assert.match(flat(document.querySelector('[data-scope-depth-how]')), /impossible column name in the include-column list/);
  assert.match(flat(document.querySelector('[data-scope-depth-help]')), /Views follow the table lists/);
  const buttons = [...scopeEl(document).querySelectorAll('button')].map((b) => b.textContent.trim());
  assert.ok(!buttons.some((t) => /^catalogue\s*(→|·|$)/i.test(t) && t.length > 9), 'no commit button in slice A');
  const r = radios.find((x) => x.dataset.scopeDepthRadio === 'schemas');
  r.checked = true;
  r.dispatchEvent(new window.Event('change', { bubbles: true }));
  await wait();
  const [c] = calls(server, 'PUT', '/depth');
  assert.deepEqual(c.body, { depth: 'schemas' });
  assert.match(flat(document.querySelector('[data-scope-status]')), /depth is now schemas/);
  assert.match(flat(document.querySelector('[data-scope-depth-how]')), /chosen by me 10-04/);
});

test('column depth: column rows appear under an opened table', async () => {
  const withCols = baseView();
  withCols.depth.value = 'tables_and_columns';
  withCols.schemas[0].tables[0].columns = [{ name: 'order_id', type: 'integer', key_role: 'PK' }];
  const { document } = await setUp(withCols);
  document.querySelector('[data-scope-toggle="sales"]').click();
  assert.match(flat(document.querySelector('[data-scope-column]')), /order_id integer PK/);
});

test('shallower depth: no column rows, and a table says which level the depth excludes', async () => {
  const shallow = baseView();
  shallow.schemas[0].tables.forEach((t) => { t.provenance = 'columns excluded via include list'; });
  const { document } = await setUp(shallow);
  document.querySelector('[data-scope-toggle="sales"]').click();
  assert.equal(document.querySelector('[data-scope-column]'), null);
  assert.match(flat(row(document, 'table:sales.orders')), /columns excluded via include list/);
});

/* ── proposals ─────────────────────────────────────────────────────────── */

function withProposal() {
  const v = baseView();
  const e = v.schemas[2];
  e.state = 'proposed';
  e.proposal = proposalFor('leave_out', '0 tables, measured 10-02');
  e.live_proposal = e.proposal;
  return v;
}

test('a proposal row: the proposal glyph and word, its reason, confirm and the other choice; effective stays undecided', async () => {
  const { document } = await setUp(withProposal());
  const r = row(document, 'schema:empty_one');
  assert.equal(flat(r.querySelector('[data-scope-choice-cell]')),
    '⏵ proposed: leave out · 0 tables, measured 10-02 confirm · catalogue instead');
  assert.equal(r.dataset.scopeEffective, '', 'an unconfirmed proposal is still undecided');
  assert.ok(r.querySelector('[aria-label="proposal"]'), 'the glyph carries the existing word');
});

test('confirm POSTs the node and the row reads confirmed from the re-read', async () => {
  const { document, server } = await setUp(withProposal());
  row(document, 'schema:empty_one').querySelector('[data-scope-act="confirm"]').click();
  await wait();
  const [c] = calls(server, 'POST', '/node/confirm');
  assert.deepEqual(c.body, { schema_name: 'empty_one', table_name: '' });
  assert.match(flat(row(document, 'schema:empty_one').querySelector('[data-scope-choice-cell]')), /^leave out · confirmed by me 10-04/);
  assert.match(flat(document.querySelector('[data-scope-status]')), /empty_one: leave out is in the re-read scope/);
});

test('override POSTs the node; the row shows the other choice and the proposal reason struck through', async () => {
  const { document, server } = await setUp(withProposal());
  row(document, 'schema:empty_one').querySelector('[data-scope-act="override"]').click();
  await wait();
  assert.equal(calls(server, 'POST', '/node/override').length, 1);
  const cell = row(document, 'schema:empty_one').querySelector('[data-scope-choice-cell]');
  assert.match(flat(cell), /^catalogue · overridden by me 10-04/);
  const struck = cell.querySelector('[data-scope-struck]');
  assert.ok(struck && struck.className.includes('line-through'));
  assert.match(flat(struck), /proposed: leave out · 0 tables, measured 10-02/);
});

test('survey now disagrees: both values and the survey date, and the choice does not move', async () => {
  const v = baseView();
  const e = v.schemas[2];
  e.explicit = person('leave_out', 'dwolfson', '2026-10-04T10:00:00', { action: 'confirm', source: 'empty_schema', proposal_rule: 'empty_schema' });
  e.effective = 'leave_out'; e.state = 'disagrees';
  e.disagrees = { was: { table_count: 0 }, now: { table_count: 4 }, survey_at: '2026-10-09T00:00:00', words: 'it had 0 tables; it now has 4' };
  const { document } = await setUp(v);
  const cell = row(document, 'schema:empty_one').querySelector('[data-scope-choice-cell]');
  assert.match(flat(cell.querySelector('[data-scope-disagrees]')),
    /survey now disagrees: Confirmed leave out on 10-04, when it had 0 tables; it now has 4 \(survey of 10-09\)\. The choice has not changed\./);
  assert.match(flat(cell), /^leave out/);
  assert.ok(cell.querySelector('[data-scope-act="clear"]'), 'offers to reconsider');
});

/* ── undecided and inheritance ─────────────────────────────────────────── */

test('an undecided schema says it keeps what is in Egeria now', async () => {
  const { document } = await setUp(baseView());
  assert.match(flat(row(document, 'schema:sales')), /undecided · keeps what’s in Egeria now/);
});

test('inherited and differing tables are drawn differently', async () => {
  const v = baseView();
  const s = v.schemas[0];
  s.explicit = person('catalogue'); s.effective = 'catalogue'; s.state = 'chosen'; s.effective_from = 'self';
  s.tables[0].effective = 'catalogue'; s.tables[0].effective_from = 'schema'; s.tables[0].inherited = 'catalogue';
  s.tables[1].explicit = person('leave_out'); s.tables[1].effective = 'leave_out'; s.tables[1].effective_from = 'self';
  s.tables[1].state = 'chosen'; s.tables[1].differs_from_schema = true;
  const { document } = await setUp(v);
  document.querySelector('[data-scope-toggle="sales"]').click();
  const inherited = row(document, 'table:sales.orders').querySelector('[data-scope-state-word="inherited"]');
  assert.equal(flat(inherited), 'catalogue (from schema)');
  assert.ok(inherited.className.includes('text-ink-muted'), 'muted ink');
  const differs = row(document, 'table:sales.customers').querySelector('[data-scope-choice-cell]');
  assert.match(flat(differs), /leave out · set by dwolfson 10-04 · differs from its schema/);
  assert.ok(!differs.querySelector('[data-scope-state-word]').className.includes('text-ink-muted'), 'in ink');
});

/* ── conflicts ─────────────────────────────────────────────────────────── */

function withConflict() {
  const v = baseView();
  const text = 'orders is chosen differently in sales and archive';
  const conflict = { name: 'orders', text, catalogue_in: ['sales'], leave_out_in: ['archive'] };
  v.schemas[0].tables[0].explicit = person('catalogue'); v.schemas[0].tables[0].effective = 'catalogue'; v.schemas[0].tables[0].conflict = conflict;
  v.schemas[1].tables[0].explicit = person('leave_out'); v.schemas[1].tables[0].effective = 'leave_out'; v.schemas[1].tables[0].conflict = conflict;
  v.conflicts = { count: 1, names: ['orders'], pairs: [{ name: 'orders', catalogue_in: 'sales', leave_out_in: 'archive' }] };
  return v;
}

test('a name conflict marks BOTH rows with the designer’s words and two resolving controls, and says what the count blocks', async () => {
  const { document, server } = await setUp(withConflict());
  for (const key of ['table:sales.orders', 'table:archive.orders']) {
    const r = row(document, key);
    assert.ok(r, `${key} is visible without opening anything by hand (a conflict is never hidden)`);
    assert.match(flat(r.querySelector('[data-scope-conflict]')),
      /^⚠ needs a person: orders is chosen differently in sales and archive\. Egeria's filter can't tell them apart · catalogue both · leave both out$/);
  }
  assert.match(flat(document.querySelector('[data-scope-conflict-summary]')), /1 choice Egeria can't express — resolve it below/);
  row(document, 'table:sales.orders').querySelector('[data-scope-resolve="catalogue"]').click();
  await wait();
  const [c] = calls(server, 'POST', '/resolve');
  assert.deepEqual(c.body, { name: 'orders', choice: 'catalogue' });
  assert.equal(document.querySelector('[data-scope-conflict]'), null, 'resolved: the marks are gone');
  assert.match(flat(document.querySelector('[data-scope-status]')), /orders is no longer in conflict/);
});

/* ── new since ─────────────────────────────────────────────────────────── */

test('new since the scope was declared: rows say so, the count line quotes the manifest, declaring again resets it', async () => {
  const v = baseView({
    declared: { declared: true, by: 'dwolfson', at: '2026-10-04T08:00:00', kind: 'first', baseline_survey_at: '' },
    new_since: { declared: true, schemas: 1, tables: 3, tables_in_known_schemas: 0, schema_names: ['coco_new'],
      text: '1 new schema (3 tables) not in your scope', since: '2026-10-04T08:00:00' },
  });
  v.schemas.push(schema('coco_new', [table('coco_new', 'a')], { new_since: true }));
  v.schemas[3].tables[0].new_since = true;
  const { document, server } = await setUp(v);
  assert.match(flat(document.querySelector('[data-scope-new-since]')), /1 new schema \(3 tables\) not in your scope/);
  assert.match(flat(row(document, 'schema:coco_new')), /new since your scope was declared · undecided/);
  assert.equal(row(document, 'schema:sales').querySelector('[data-scope-new-since-row]'), null);
  document.querySelector('[data-scope-redeclare]').click();
  await wait();
  assert.equal(calls(server, 'POST', '/redeclare').length, 1);
  assert.equal(document.querySelector('[data-scope-new-since]'), null);
  assert.match(flat(document.querySelector('[data-scope-status]')), /declared again/);
});

/* ── marks, notes, access, system ──────────────────────────────────────── */

test('PII is a mark, staging a note, no access is "not established": none of them is a proposal', async () => {
  const v = baseView();
  v.schemas[0].marks = ['PII · 3 columns'];
  v.schemas[1].notes = ['name suggests staging'];
  v.schemas[2] = schema('locked', [], { classification: 'no_access', access: 'not_established', table_count: null, row_total: null });
  const { document } = await setUp(v);
  assert.match(flat(row(document, 'schema:sales').querySelector('[data-scope-classes-cell]')), /PII · 3 columns/);
  assert.match(flat(row(document, 'schema:archive').querySelector('[data-scope-state-cell]')), /name suggests staging/);
  assert.match(flat(row(document, 'schema:locked').querySelector('[data-scope-state-cell]')), /\? not established/);
  assert.equal(scopeEl(document).querySelectorAll('[data-scope-act="confirm"]').length, 0, 'no proposal anywhere');
  assert.match(flat(row(document, 'schema:locked').querySelector('[data-scope-rows-cell]')), /not established/);
});

test('system schemas are folded with their sentence and never offered a control', async () => {
  const { document } = await setUp(baseView());
  const sys = document.querySelector('[data-scope-system]');
  assert.match(flat(sys), /3 system schemas folded · not catalogued: system schemas are never offered/);
  assert.equal(sys.querySelector('button'), null);
  assert.equal(document.querySelector('[data-scope-row*="pg_catalog"]'), null);
});

test('a database with no stored rows says so in words, not an empty table', async () => {
  const { document } = await setUp(baseView({ schemas: [], system: null }));
  assert.match(flat(document.querySelector('[data-scope-tree]')), /No stored schema rows yet/);
  assert.equal(scopeEl(document).querySelectorAll('table').length, 0);
});

/* ── signed out, and a server that drops the write ─────────────────────── */

test('signed out: the tree reads, every control is disabled with the reason, and no write is attempted', async () => {
  const { document, server } = await setUp(withProposal(), { signedIn: false });
  assert.match(flat(document.querySelector('[data-scope-signed-out]')), /You can read the scope as it stands\. sign in to change what gets catalogued/);
  const controls = [...scopeEl(document).querySelectorAll('button[data-scope-act], input[data-scope-depth-radio]')];
  assert.ok(controls.length > 4);
  for (const c of controls) {
    assert.ok(c.disabled, 'control is disabled');
    assert.match(c.title, /sign in to change what gets catalogued/);
  }
  row(document, 'schema:empty_one').querySelector('[data-scope-act="confirm"]').click();
  await wait(50);
  assert.equal(server.calls.filter((c) => c.method !== 'GET').length, 0);
  assert.match(flat(row(document, 'schema:empty_one')), /proposed: leave out/);
});

test('KNOWN-NEGATIVE: a server that drops the write does not get a "saved" status', async () => {
  const { document } = await setUp(baseView(), { dropWrites: true });
  row(document, 'schema:sales').querySelector('[data-scope-act="set"][data-scope-choice="catalogue"]').click();
  await wait();
  const s = flat(document.querySelector('[data-scope-status]'));
  assert.match(s, /the write returned, but the re-read scope shows no choice for sales/);
  assert.doesNotMatch(s, /is in the re-read scope/);
  assert.match(flat(row(document, 'schema:sales')), /undecided/);
});

test('a 401 from a write says to sign in, in words', async () => {
  const { document, server } = await setUp(baseView());
  server.signedIn = false;
  row(document, 'schema:sales').querySelector('[data-scope-act="set"][data-scope-choice="leave_out"]').click();
  await wait();
  assert.match(flat(document.querySelector('[data-scope-status]')), /sign in to change what gets catalogued/);
});
