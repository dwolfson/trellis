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
  last_write: { state: 'not_established', from: '', to: '', text: 'not established' },
  source: { kind: 'egeria', as_of: '2026-10-04T06:00:00', text: 'from Egeria survey 10-04' }, facts_from: {},
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
    survey: { state: 'measured', schema_count: 29, table_count: 266, surveyed_at: '2026-10-04T06:00:00', report_guid: 'g' },
    sources: {
      chosen: { kind: 'egeria', as_of: '2026-10-04T06:00:00', schemas: 29, tables: 266, merged: false },
      egeria: { state: 'measured', schema_count: 29, table_count: 266, surveyed_at: '2026-10-04T06:00:00', report_guid: 'g' },
      local: { state: 'not_measured', schema_count: 0, table_count: 0, surveyed_at: '', surveyed_as: '', sees: '' },
      disagree: false, unreadable: 0,
    },
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
        if (u.endsWith('/nodes')) {
          const names = body.all_schemas ? s.view.schemas.map((x) => x.name) : body.nodes.map((n) => n.schema_name);
          for (const nm of names) {
            const n = find(nm, '');
            if (body.choice) { n.explicit = person(body.choice, 'me'); n.effective = body.choice; n.state = 'chosen'; n.proposal = null; }
            else { n.explicit = null; n.effective = null; n.state = 'undecided'; }
          }
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

test('header, undeclared, Egeria the source: "29 schemas · Egeria survey 10-04"', async () => {
  const { document } = await setUp(baseView());
  assert.equal(flat(document.querySelector('[data-scope-header]')),
    'Your scope: none declared yet · 29 schemas · Egeria survey 10-04');
  assert.match(flat(document.querySelector('[data-scope-tree-header]')), /reads Egeria element abcdef12/);
  assert.match(flat(document.querySelector('[data-scope-tree-header]')), /tree read from the Egeria survey 10-04: 29 schemas, 266 tables/);
});

test('header, RE local survey the only source: names the source, its date and what the credential sees', async () => {
  const { document } = await setUp(baseView({ sources: {
    chosen: { kind: 'local', as_of: '2026-10-03T09:00:00', schemas: 8, tables: 61, merged: false },
    egeria: { state: 'not_measured', schema_count: null, table_count: null, surveyed_at: '', report_guid: '' },
    local: { state: 'measured', schema_count: 8, table_count: 61, surveyed_at: '2026-10-03T09:00:00', surveyed_as: 'surveyor', sees: 'sees 6' },
    disagree: false, unreadable: 0 } }));
  assert.equal(flat(document.querySelector('[data-scope-header]')),
    'Your scope: none declared yet · 8 schemas · RE local survey 10-03 · sees 6 of 8');
});

test('header, the two sources DISAGREE: it names both, with their counts and dates', async () => {
  const { document } = await setUp(baseView({ sources: {
    chosen: { kind: 'egeria', as_of: '2026-10-04T06:00:00', schemas: 29, tables: 266, merged: true },
    egeria: { state: 'measured', schema_count: 29, table_count: 266, surveyed_at: '2026-10-04T06:00:00', report_guid: 'g' },
    local: { state: 'measured', schema_count: 8, table_count: 61, surveyed_at: '2026-10-03T09:00:00', surveyed_as: 'surveyor', sees: 'sees 6' },
    disagree: true, unreadable: 0 } }));
  assert.equal(flat(document.querySelector('[data-scope-header]')),
    "Your scope: none declared yet · Egeria's latest survey covers 29 schemas, 266 tables · RE's own survey saw 8 schemas, 61 tables, 10-03");
  assert.match(flat(document.querySelector('[data-scope-tree-header]')), /facts it lacked filled from the other survey/);
});

test('header, undeclared and never measured: says not measured yet, and an uncatalogued database says so', async () => {
  const { document } = await setUp(baseView({
    survey: { state: 'not_measured', schema_count: null, table_count: null, surveyed_at: '', report_guid: '' },
    sources: { chosen: { kind: 'local', as_of: '', schemas: 0, tables: 0, merged: false },
      egeria: { state: 'not_measured' }, local: { state: 'not_measured' }, disagree: false, unreadable: 0 },
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
  assert.equal(flat(document.querySelector('[data-scope-header]')),
    'Your scope: 7 of 29 schemas · declared by dwolfson 10-04 · 29 schemas · Egeria survey 10-04');
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

/* ── slice A2: sources on every row, activity, select-all and bulk, layout ── */

test('every row carries a muted source line, and a fact another survey supplied says where it came from', async () => {
  const v = baseView();
  v.schemas[0].tables[0].facts_from = { rows: { kind: 'local', as_of: '2026-10-03T09:00:00', text: '' } };
  v.schemas[1].source = { kind: 'local', as_of: '2026-10-03T09:00:00', text: 'from RE local survey 10-03' };
  const { document } = await setUp(v);
  document.querySelector('[data-scope-toggle="sales"]').click();
  const src = (key) => row(document, key).querySelector('[data-scope-source]');
  assert.equal(flat(src('schema:sales')), 'from Egeria survey 10-04');
  assert.equal(flat(src('schema:archive')), 'from RE local survey 10-03');
  assert.equal(flat(src('table:sales.orders')), 'from Egeria survey 10-04 · rows from RE local survey 10-03');
  assert.equal(flat(src('table:sales.customers')), 'from Egeria survey 10-04');
  for (const key of ['schema:sales', 'schema:archive', 'table:sales.orders']) {
    assert.ok(src(key).className.includes('text-ink-muted'), `${key}: the source line is muted ink`);
  }
});

test('activity is a word with its window: active, dormant, or can\'t tell with the reason; never "none since"', async () => {
  const v = baseView();
  v.schemas[0].tables[0].last_write = { state: 'active', text: 'active · 1,204 writes since counters reset 06-02' };
  v.schemas[0].tables[1].last_write = { state: 'cant_tell', text: "can't tell · counters reset 10-03 · 2 days of evidence" };
  v.schemas[1].last_write = { state: 'dormant', text: 'dormant · 0 writes in 336 days (counters reset 2025-11-02)' };
  v.schemas[2].last_write = { state: 'cant_tell', text: "can't tell · reset date not recorded" };
  const { document } = await setUp(v);
  document.querySelector('[data-scope-toggle="sales"]').click();
  const act = (key) => flat(row(document, key).querySelector('[data-scope-lastwrite-cell]'));
  assert.equal(act('table:sales.orders'), 'active · 1,204 writes since counters reset 06-02');
  assert.equal(act('table:sales.customers'), "can't tell · counters reset 10-03 · 2 days of evidence");
  assert.equal(act('schema:archive'), 'dormant · 0 writes in 336 days (counters reset 2025-11-02)');
  assert.equal(act('schema:empty_one'), "can't tell · reset date not recorded");
  assert.ok(row(document, 'table:sales.customers').querySelector('[data-scope-activity-cant-tell]').className.includes('text-ink-muted'));
  assert.doesNotMatch(flat(scopeEl(document)), /none since|no writes since/);
  assert.equal(scopeEl(document).querySelectorAll('[data-scope-act="confirm"]').length, 0, 'a can\'t tell proposes nothing');
  assert.match(flat(document.querySelector('[data-scope-activity-head]')), /^activity$/);
  assert.match(document.querySelector('[data-scope-activity-head]').title, /0 writes in at least 90 days/);
});

test('columns, left to right: choice, Schema / table, rows, size, activity, data classes, State in Egeria', async () => {
  const { document } = await setUp(baseView());
  const heads = [...document.querySelector('[data-scope-tree-head]').children].map((c) => flat(c).toLowerCase()).filter(Boolean);
  assert.deepEqual(heads, ['choice', 'schema / table', 'rows', 'size', 'activity', 'data classes', 'state in egeria']);
  const cells = [...row(document, 'schema:sales').children].map((c) => Object.keys(c.dataset)[0]);
  assert.deepEqual(cells, ['scopeSelectCell', 'scopeChoiceCell', 'scopeNameCell', 'scopeRowsCell', 'scopeSizeCell', 'scopeLastwriteCell', 'scopeClassesCell', 'scopeStateCell']);
  assert.match(flat(row(document, 'schema:sales').querySelector('[data-scope-name-cell]')), /sales · 2 tables/);
});

test('rows and size: a scan, an estimate (≈), not measured, and "◐ sources disagree" with both values', async () => {
  const v = baseView();
  const [orders, customers] = v.schemas[0].tables;
  orders.rows_view = { state: 'measured', value: 3412, text: '3,412', detail: 'RE local survey 10-14 · scan' };
  customers.rows_view = { state: 'estimate', value: 3400, estimate: true, text: '≈3,400', detail: 'RE local survey 10-14 · estimate' };
  v.schemas[1].tables[0].rows_view = { state: 'disagree', value: null, text: '◐ sources disagree', detail: 'RE local survey 10-02: ≈3,400 · Egeria survey 10-04: 0' };
  v.schemas[2].rows_view = { state: 'not_measured', value: null, text: 'not measured', detail: '' };
  orders.size_view = { state: 'measured', value: 1, text: '22 MB', detail: 'Egeria survey 10-04' };
  customers.size_view = { state: 'not_measured', value: null, text: 'not measured', detail: '' };
  const { document } = await setUp(v);
  document.querySelector('[data-scope-toggle="sales"]').click();
  document.querySelector('[data-scope-toggle="archive"]').click();
  const cell = (key, which) => row(document, key).querySelector(`[data-scope-${which}-cell]`);
  assert.equal(flat(cell('table:sales.orders', 'rows')), '3,412');
  assert.equal(flat(cell('table:sales.customers', 'rows')), '≈3,400');
  assert.match(cell('table:sales.customers', 'rows').querySelector('[title]').title, /estimate/);
  assert.match(flat(cell('table:archive.orders', 'rows')), /^◐ sources disagree RE local survey 10-02: ≈3,400 · Egeria survey 10-04: 0$/);
  assert.equal(flat(cell('schema:empty_one', 'rows')), 'not measured');
  assert.equal(flat(cell('table:sales.orders', 'size')), '22 MB');
  assert.equal(flat(cell('table:sales.customers', 'size')), 'not measured');
  assert.ok(cell('table:sales.orders', 'rows').querySelector('.tnum.text-right, .tnum'), 'tabular figures');
});

test('a lens term found in table names is a muted suggestion sentence, not a proposal and not a rule control', async () => {
  const v = baseView({ suggested_rules: [{ term: 'Sales', count: 14, text: 'The lens names Sales: 14 table names contain it · make that a rule?' }] });
  const { document } = await setUp(v);
  const line = document.querySelector('[data-scope-suggested-rule]');
  assert.equal(flat(line), 'The lens names Sales: 14 table names contain it · make that a rule?');
  assert.ok(line.className.includes('text-ink-muted'));
  assert.equal(line.querySelector('button'), null, 'rules are a later slice: no control');
  assert.equal(scopeEl(document).querySelectorAll('[data-scope-act="confirm"]').length, 0);
});

test('the column title is "Schema / table", tables are indented under their schema, and each says its kind', async () => {
  const { document } = await setUp(baseView());
  document.querySelector('[data-scope-toggle="sales"]').click();
  const head = flat(document.querySelector('[data-scope-tree-head]'));
  assert.match(head, /Schema \/ table/);
  assert.doesNotMatch(head, /(^|\s)name(\s|$)/i);
  const t = row(document, 'table:sales.orders');
  assert.ok(t.parentElement.className.includes('ml-s3'), 'the table row is indented');
  assert.match(flat(t.querySelector('[data-scope-kind]')), /^· table$/);
  assert.ok(row(document, 'schema:sales').querySelector('[data-scope-toggle]'), 'a schema row has its expander');
});

test('the STATE column is fully present and the tree scrolls sideways inside its own container', async () => {
  const { document } = await setUp(baseView());
  const host = document.querySelector('[data-scope-tree]');
  assert.equal(host.style.overflowX, 'auto', 'overflow-x is set on the container');
  assert.ok(host.className.includes('overflow-x-auto'));
  assert.equal(flat(document.querySelector('[data-scope-state-head]')), 'State in Egeria');
  assert.ok(host.querySelector('.min-w-max'), 'the rows keep their full width instead of shrinking and clipping');
  assert.ok(row(document, 'schema:sales').querySelector('[data-scope-state-cell]'));
  // jsdom does no layout: whether STATE is fully visible at ~1300px is NOT measured here.
});

test('select all schemas ticks every schema row, and the bulk bar counts them', async () => {
  const { document, window } = await setUp(baseView());
  const bar = document.querySelector('[data-scope-bulk]');
  assert.match(flat(bar), /select all schemas/);
  assert.match(flat(bar), /0 of 3 selected/);
  assert.ok(document.querySelector('[data-scope-bulk-act="catalogue"]').disabled, 'nothing selected: nothing to apply');
  const all = document.querySelector('[data-scope-all-box]');
  all.checked = true;
  all.dispatchEvent(new window.Event('change', { bubbles: true }));
  const boxes = [...document.querySelectorAll('[data-scope-select]')];
  assert.equal(boxes.length, 3);
  assert.ok(boxes.every((b) => b.checked));
  assert.match(flat(document.querySelector('[data-scope-bulk]')), /3 of 3 selected/);
  assert.equal(document.querySelector('[data-scope-bulk-act="leave_out"]').disabled, false);
  assert.equal(row(document, 'table:sales.orders'), null, 'tables carry no tick (schema rows only)');
});

test('catalogue selected: one POST naming the ticked schemas, and the status is derived from the re-read', async () => {
  const { document, window, server } = await setUp(baseView());
  for (const n of ['sales', 'archive']) {
    const b = document.querySelector(`[data-scope-select="${n}"]`);
    b.checked = true;
    b.dispatchEvent(new window.Event('change', { bubbles: true }));
  }
  assert.match(flat(document.querySelector('[data-scope-selected-count]')), /2 of 3 selected/);
  document.querySelector('[data-scope-bulk-act="catalogue"]').click();
  await wait();
  const [c] = calls(server, 'POST', '/nodes');
  assert.deepEqual(c.body, { nodes: [{ schema_name: 'sales', table_name: '' }, { schema_name: 'archive', table_name: '' }], choice: 'catalogue', all_schemas: false });
  assert.match(flat(document.querySelector('[data-scope-status]')), /^2 schemas now set to catalogue by me$/);
  assert.match(flat(row(document, 'schema:sales').querySelector('[data-scope-choice-cell]')), /catalogue · set by me/);
  assert.match(flat(document.querySelector('[data-scope-selected-count]')), /0 of 3 selected/, 'the selection is spent');
});

test('leave out selected and clear choice send their own choice', async () => {
  const { document, window, server } = await setUp(baseView());
  const tick = (n) => { const b = document.querySelector(`[data-scope-select="${n}"]`); b.checked = true; b.dispatchEvent(new window.Event('change', { bubbles: true })); };
  tick('sales');
  document.querySelector('[data-scope-bulk-act="leave_out"]').click();
  await wait();
  tick('sales');
  document.querySelector('[data-scope-bulk-act="clear"]').click();
  await wait();
  const posts = calls(server, 'POST', '/nodes');
  assert.deepEqual(posts.map((p) => p.body.choice), ['leave_out', '']);
  assert.match(flat(document.querySelector('[data-scope-status]')), /^1 schema now have no choice in the re-read scope$/);
});

test('catalogue all N schemas: one click, one POST asking for all of them, "3 schemas now set to catalogue by me"', async () => {
  const { document, server } = await setUp(baseView());
  const btn = document.querySelector('[data-scope-catalogue-all]');
  assert.equal(flat(btn), 'catalogue all 3 schemas');
  btn.click();
  await wait();
  const [c] = calls(server, 'POST', '/nodes');
  assert.equal(c.body.all_schemas, true);
  assert.equal(c.body.choice, 'catalogue');
  assert.match(flat(document.querySelector('[data-scope-status]')), /^3 schemas now set to catalogue by me$/);
});

test('bulk: a table with its own differing choice is reported from the re-read, not overwritten', async () => {
  const v = baseView();
  v.schemas[0].tables[0].explicit = person('catalogue'); v.schemas[0].tables[0].effective = 'catalogue';
  v.schemas[0].tables[0].differs_from_schema = true; v.schemas[0].tables[0].state = 'chosen';
  const { document, window } = await setUp(v);
  const b = document.querySelector('[data-scope-select="sales"]');
  b.checked = true; b.dispatchEvent(new window.Event('change', { bubbles: true }));
  document.querySelector('[data-scope-bulk-act="leave_out"]').click();
  await wait();
  assert.match(flat(document.querySelector('[data-scope-status]')), /^1 schema now set to leave out by me · 1 table keeps its own choice and differs from its schema$/);
  document.querySelector('[data-scope-toggle="sales"]').click();
  assert.match(flat(row(document, 'table:sales.orders').querySelector('[data-scope-choice-cell]')), /catalogue · set by dwolfson 10-04 · differs from its schema/);
});

test('bulk, signed out: every bulk control is disabled with the reason and nothing is sent', async () => {
  const { document, server } = await setUp(baseView(), { signedIn: false });
  const controls = [...document.querySelectorAll('[data-scope-all-box], [data-scope-select], [data-scope-bulk-act], [data-scope-catalogue-all]')];
  assert.ok(controls.length >= 7);
  for (const c of controls) {
    assert.ok(c.disabled, 'disabled');
    assert.match(c.title, /sign in to change what gets catalogued/);
  }
  document.querySelector('[data-scope-catalogue-all]').click();
  await wait(50);
  assert.equal(server.calls.filter((x) => x.method !== 'GET').length, 0);
});

test('KNOWN-NEGATIVE: a bulk write the server drops is not reported as done', async () => {
  const { document, server } = await setUp(baseView(), { dropWrites: true });
  document.querySelector('[data-scope-catalogue-all]').click();
  await wait();
  assert.equal(calls(server, 'POST', '/nodes').length, 1);
  const s = flat(document.querySelector('[data-scope-status]'));
  assert.match(s, /the write returned, but the re-read scope shows only 0 of 3 schemas set to catalogue/);
  assert.doesNotMatch(s, /now set to/);
});

test('a failed read of RE\'s own survey says so instead of "not measured"', async () => {
  const lo = { state: 'unreadable', read_error: 'RuntimeError: x', schema_count: 0, table_count: 0, surveyed_at: '', surveyed_as: '', sees: '' };
  const { document } = await setUp(baseView({ sources: {
    chosen: { kind: 'local', as_of: '', schemas: 0, tables: 0, merged: false },
    egeria: { state: 'not_measured' }, local: lo, disagree: false, unreadable: 0 } }));
  assert.equal(flat(document.querySelector('[data-scope-header]')),
    "Your scope: none declared yet · RE's own survey could not be read");
  assert.doesNotMatch(flat(document.querySelector('[data-scope-header]')), /not measured/);
  const { document: d2 } = await setUp(baseView({ sources: {
    chosen: { kind: 'egeria', as_of: '2026-10-04T06:00:00', schemas: 29, tables: 266, merged: false },
    egeria: { state: 'measured', schema_count: 29, table_count: 266, surveyed_at: '2026-10-04T06:00:00' }, local: lo, disagree: false, unreadable: 0 } }));
  assert.equal(flat(d2.querySelector('[data-scope-header]')),
    "Your scope: none declared yet · 29 schemas · Egeria survey 10-04 · RE's own survey could not be read");
});

test('when the earlier surveys could not be read, new-since says can\'t tell and no row is flagged new', async () => {
  const v = baseView({
    declared: { declared: true, by: 'dwolfson', at: '2026-10-04T08:00:00', kind: 'first', baseline_survey_at: '' },
    new_since: { declared: true, can_tell: false, schemas: 0, tables: 0, tables_in_known_schemas: 0, schema_names: [],
      text: "can't tell: the earlier surveys could not be read", since: '2026-10-04T08:00:00' },
  });
  const { document } = await setUp(v);
  assert.equal(flat(document.querySelector('[data-scope-new-since]')).startsWith("can't tell: the earlier surveys could not be read"), true);
  assert.equal(document.querySelectorAll('[data-scope-new-since-row]').length, 0);
});
