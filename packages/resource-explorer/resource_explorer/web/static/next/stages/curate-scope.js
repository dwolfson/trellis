/* Curate, database, band 2, first section: "What gets catalogued".
 *
 * The designer's reply on catalogue scope and
 * wireframes/CatalogueScope.dc.html (page 18), slice A: everything up to the
 * commit button. There is NO Catalogue button here and nothing on this page
 * writes to Egeria: the scope is a declared, signed, dated choice stored in
 * RE (web/routes/catalogue_scope.py), and a later slice compiles it.
 *
 * Rules this file keeps:
 *  - what a row says comes from the server's re-read AFTER a write, never
 *    from what the click assumed; a status sentence is derived from those
 *    rows (the same rule curate-bands.js keeps);
 *  - every write control is disabled, with a plain reason, when nobody is
 *    signed in (the routes answer 401 then), and the tree stays readable;
 *  - the proposal glyph and word come from glyphs.js; this file declares no
 *    glyph of its own;
 *  - system schemas are folded with their one sentence, never offered;
 *  - a proposal is only ever drawn from a measurement the server returned,
 *    and an unconfirmed proposal is drawn as undecided (it removes nothing).
 */
import {
  getCatalogueScope, setCatalogueDepth, setCatalogueNode, confirmCatalogueNode,
  overrideCatalogueNode, clearCatalogueNode, redeclareCatalogueScope,
  resolveCatalogueConflict,
} from '/static/re-api.js';
import { state, esc } from '/static/next/app.js';
import { glyphSpan } from '/static/next/glyphs.js';

const whoAmI = () =>
  (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
const md = (iso) => String(iso || '').slice(5, 10);
const words = (choice) => (choice === 'leave_out' ? 'leave out' : choice === 'catalogue' ? 'catalogue' : '');
const opposite = (choice) => (choice === 'leave_out' ? 'catalogue' : 'leave_out');
const signInReason = 'sign in to change what gets catalogued: every choice needs an author';
const num = (n) => Number(n).toLocaleString('en-US');

/** Which schemas are expanded survives a redraw (a write redraws the tree). */
const openSchemas = new Set();
let openFor = '';
/** Forget which schemas were expanded (another database, or a fresh pane). */
export function resetScopeUi() { openSchemas.clear(); openFor = ''; }

export function scopeHeaderText(view) {
  const sv = view.survey || {};
  if (view.declared && view.declared.declared) {
    const c = view.counts || {};
    return `Your scope: ${c.schemas_catalogue} of ${c.schemas_offered} schemas · declared by ${view.declared.by} ${md(view.declared.at)}`;
  }
  const covers = sv.state === 'measured'
    ? `Egeria's latest survey covers ${sv.schema_count} schemas, ${sv.table_count} tables`
    : "Egeria's latest survey: not measured yet";
  return `Your scope: none declared yet · ${covers}`;
}

/* ── one row ─────────────────────────────────────────────────────────── */

function setterButtons(node, me) {
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const sch = esc(node.kind === 'schema' ? node.name : node.schema);
  const tbl = node.kind === 'table' ? esc(node.name) : '';
  const own = node.explicit ? node.explicit.choice : '';
  const btn = (choice, label) => `<button type="button" data-scope-act="set" data-scope-choice="${choice}"
    data-scope-schema="${sch}" data-scope-table="${tbl}" ${dis} ${own === choice ? 'aria-pressed="true"' : 'aria-pressed="false"'}
    class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">${label}</button>`;
  const clear = node.explicit ? ` <button type="button" data-scope-act="clear" data-scope-schema="${sch}" data-scope-table="${tbl}" ${dis}
    class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">${node.state === 'disagrees' ? 'reconsider' : 'clear'}</button>` : '';
  return `<span class="text-provenance">${btn('catalogue', 'catalogue')} · ${btn('leave_out', 'leave out')}${clear}</span>`;
}

function proposalControls(node, me) {
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const sch = esc(node.kind === 'schema' ? node.name : node.schema);
  const tbl = node.kind === 'table' ? esc(node.name) : '';
  const attrs = `data-scope-schema="${sch}" data-scope-table="${tbl}" ${dis}`;
  return `<button type="button" data-scope-act="confirm" ${attrs} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">confirm</button> ·
    <button type="button" data-scope-act="override" ${attrs} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">${esc(words(opposite(node.proposal.choice)))} instead</button>`;
}

/** The left-hand choice cell: the person's choice, or the proposal, or what
 *  the row inherits, in the words the designer drew. */
export function choiceCellHtml(node, me) {
  const ex = node.explicit;
  const by = ex ? `${esc(ex.by)} ${esc(md(ex.at))}` : '';
  if (node.state === 'proposed' && node.proposal) {
    return `<div data-scope-state-word="proposed">${glyphSpan('proposal')}
      <span class="text-ink">proposed: <span class="font-semibold">${esc(words(node.proposal.choice))}</span></span>
      <span class="text-ink-muted"> · ${esc(node.proposal.reason)}</span></div>
      <div class="text-provenance">${proposalControls(node, me)}</div>`;
  }
  if (ex && node.state === 'confirmed') {
    return `<div data-scope-state-word="confirmed" class="text-ink">${esc(words(ex.choice))}
      <span class="text-ink-muted"> · confirmed by ${by}</span></div>
      <div class="text-provenance text-ink-muted">${esc(ex.reason || '')}</div>${setterButtons(node, me)}`;
  }
  if (ex && node.state === 'overridden') {
    const o = node.overridden || {};
    return `<div data-scope-state-word="overridden" class="text-ink">${esc(words(ex.choice))}
      <span class="text-ink-muted"> · overridden by ${by}</span></div>
      <div data-scope-struck class="text-provenance text-ink-muted line-through">proposed: ${esc(words(o.choice))} · ${esc(o.reason || '')}</div>${setterButtons(node, me)}`;
  }
  if (ex && node.state === 'disagrees') {
    const d = node.disagrees || {};
    const was = ex.action === 'override' ? 'Overridden' : 'Confirmed';
    const choiceWord = ex.action === 'override' ? words(ex.proposal_choice) : words(ex.choice);
    const verb = ex.action === 'override' ? `${was} (proposal: ${choiceWord})` : `${was} ${words(ex.choice)}`;
    return `<div data-scope-state-word="disagrees" class="text-ink">${esc(words(ex.choice))}
      <span class="text-ink-muted"> · set by ${by}</span></div>
      <div data-scope-disagrees class="text-provenance text-state-warn">${glyphSpan('human')} survey now disagrees: ${esc(verb)} on ${esc(md(ex.at))}, when ${esc(d.words || '')} (survey of ${esc(md(d.survey_at))}). The choice has not changed.</div>${setterButtons(node, me)}`;
  }
  if (ex) {
    const differs = node.differs_from_schema
      ? ' <span class="text-ink">· differs from its schema</span>' : '';
    return `<div data-scope-state-word="chosen" class="text-ink">${esc(words(ex.choice))}
      <span class="text-ink-muted"> · set by ${by}</span>${differs}</div>${setterButtons(node, me)}`;
  }
  if (node.effective && node.effective_from === 'schema') {
    return `<div data-scope-state-word="inherited" class="text-ink-muted">${esc(words(node.effective))} (from schema)</div>${setterButtons(node, me)}`;
  }
  const tail = node.kind === 'schema' && node.undecided_words
    ? ` · <span data-scope-undecided-words>${esc(node.undecided_words)}</span>` : '';
  return `<div data-scope-state-word="undecided" class="text-ink-muted">undecided${tail}</div>${setterButtons(node, me)}`;
}

function stateCellHtml(node, me) {
  const lines = [];
  if (node.conflict) {
    const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
    const name = esc(node.conflict.name);
    lines.push(`<div data-scope-conflict="${name}" class="text-ink">${glyphSpan('human')}
      needs a person: <span class="font-mono">${esc(node.conflict.name)}</span> is chosen differently in ${esc(node.conflict.text.replace(/^.* is chosen differently in /, ''))}.
      Egeria's filter can't tell them apart ·
      <button type="button" data-scope-resolve="catalogue" data-scope-name="${name}" ${dis} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">catalogue both</button> ·
      <button type="button" data-scope-resolve="leave_out" data-scope-name="${name}" ${dis} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">leave both out</button></div>`);
  }
  if (node.new_since) {
    lines.push(`<div data-scope-new-since-row class="text-ink">new since your scope was declared${node.explicit ? '' : ' · undecided'}</div>`);
  }
  if (node.access === 'not_established') {
    lines.push(`<div data-scope-not-established class="text-ink-muted">${glyphSpan('not_established')} not established: no access with this credential</div>`);
  }
  (node.notes || []).forEach((n) => lines.push(`<div data-scope-note class="text-ink-muted">${esc(n)}</div>`));
  if (node.provenance) lines.push(`<div data-scope-provenance class="text-provenance text-ink-muted">${esc(node.provenance)}</div>`);
  return lines.join('');
}

function dataClassCell(node) {
  if ((node.marks || []).length) return esc(node.marks.join(' · '));
  const dc = node.data_classes || {};
  if (dc.state === 'measured') return esc((dc.classes || []).join(', ') || 'none found');
  return '<span class="text-ink-muted">not established</span>';
}

function lastWriteCell(node) {
  const lw = node.last_write || {};
  if (lw.state === 'idle') return `none since ${esc(md(lw.from))}`;
  if (lw.state === 'active') return `written ${esc(md(lw.from))} to ${esc(md(lw.to))}`;
  return '<span class="text-ink-muted">not established</span>';
}

function rowsCell(node) {
  const v = node.kind === 'schema' ? node.row_total : node.row_count;
  if (v == null) return '<span class="text-ink-muted">not established</span>';
  const est = node.kind === 'schema' ? node.is_estimate : node.row_count_state === 'catalog_estimate';
  return `<span class="tnum">${est ? '~' : ''}${esc(num(v))}</span>${est ? ' <span class="text-ink-muted">(est.)</span>' : ''}`;
}


function rowHtml(node, me, depth, kindWord) {
  const isSchema = node.kind === 'schema';
  const key = isSchema ? `schema:${node.name}` : `table:${node.schema}.${node.name}`;
  const toggle = isSchema
    ? `<button type="button" data-scope-toggle="${esc(node.name)}" aria-expanded="${openSchemas.has(node.name) ? 'true' : 'false'}"
        class="cursor-pointer bg-transparent p-0 text-ink-muted">${openSchemas.has(node.name) ? '▾' : '▸'}</button> ` : '';
  const tablesCell = isSchema
    ? `<span class="tnum">${node.table_count == null ? '<span class="text-ink-muted">not established</span>' : esc(String(node.table_count))}</span>`
    : `<span class="text-ink-muted">${esc(kindWord)}</span>`;
  return `<div class="flex items-baseline gap-s2 border-b border-rule py-[3px] text-caveat" data-scope-row="${esc(key)}" data-scope-effective="${esc(node.effective || '')}">
    <div class="w-[34ch] shrink-0" data-scope-choice-cell>${choiceCellHtml(node, me)}</div>
    <div class="w-[22ch] shrink-0 text-ink" data-scope-name-cell>${toggle}<span class="${isSchema ? 'font-semibold' : ''}">${esc(node.name)}</span></div>
    <div class="w-[12ch] shrink-0" data-scope-tables-cell>${tablesCell}</div>
    <div class="w-[12ch] shrink-0" data-scope-rows-cell>${rowsCell(node)}</div>
    <div class="w-[12ch] shrink-0" data-scope-classes-cell>${dataClassCell(node)}</div>
    <div class="w-[12ch] shrink-0" data-scope-lastwrite-cell>${lastWriteCell(node)}</div>
    <div class="min-w-[24ch] flex-1" data-scope-state-cell>${stateCellHtml(node, me)}</div>
  </div>`;
}

function columnRowsHtml(table) {
  return (table.columns || []).map((c) => `<div data-scope-column class="ml-s4 flex items-baseline gap-s2 py-[1px] text-provenance text-ink-muted">
    <span class="font-mono text-ink">${esc(c.name)}</span> <span>${esc(c.type || '')}</span> <span class="text-accent-ink">${esc(c.key_role || '')}</span></div>`).join('');
}

const TABLE_KIND = { 'BASE TABLE': 'table', VIEW: 'view', 'MATERIALIZED VIEW': 'matview', FOREIGN: 'foreign table' };

export function treeHtml(view, me) {
  if (!(view.schemas || []).length && !view.system) {
    return `<div class="text-caveat text-ink-muted">No stored schema rows yet: run a survey first. Nothing to scope until Egeria's survey or RE's has listed the schemas.</div>`;
  }
  const head = `<div class="flex items-baseline gap-s2 border-b border-rule py-[3px] text-caveat text-caps uppercase tracking-caps text-ink-muted" data-scope-tree-head>
    <div class="w-[34ch] shrink-0">choice</div><div class="w-[22ch] shrink-0">name</div><div class="w-[12ch] shrink-0">tables</div>
    <div class="w-[12ch] shrink-0">rows</div><div class="w-[12ch] shrink-0">data classes</div><div class="w-[12ch] shrink-0">last write</div>
    <div class="min-w-[24ch] flex-1">state</div></div>`;
  const body = (view.schemas || []).map((s) => {
    const open = openSchemas.has(s.name) || s.tables.some((t) => t.conflict);
    if (open) openSchemas.add(s.name);
    const tables = open ? s.tables.map((t) => `<div class="ml-s3">${rowHtml(t, me, 1, TABLE_KIND[t.table_type] || 'table')}${columnRowsHtml(t)}</div>`).join('')
      || '<div class="ml-s3 text-caveat text-ink-muted">No tables.</div>' : '';
    return `<div data-scope-schema-block="${esc(s.name)}">${rowHtml(s, me, 0, '')}${tables}</div>`;
  }).join('');
  const sys = view.system
    ? `<div data-scope-system class="mt-s1 text-caveat text-ink-muted">${esc(String(view.system.folded))} system schemas folded · ${esc(view.system.text)}</div>` : '';
  return head + body + sys;
}

export function depthLineHtml(view, me) {
  const d = view.depth || { options: [], value: '' };
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const radios = d.options.map((o) => `<label class="inline-flex cursor-pointer items-baseline gap-[4px] text-caveat text-ink">
    <input type="radio" name="scope-depth" value="${esc(o.id)}" data-scope-depth-radio="${esc(o.id)}" ${o.id === d.value ? 'checked' : ''} ${dis}>${esc(o.label)}</label>`).join(' · ');
  const cur = d.options.find((o) => o.id === d.value) || {};
  return `<div data-scope-depth class="mb-s1 flex flex-wrap items-baseline gap-s2"><span class="text-caveat text-ink-muted">Depth</span> ${radios}</div>
    <div data-scope-depth-how class="text-provenance text-ink-muted">${esc(cur.label || '')}: ${esc(cur.how || '')}${d.declared ? ` · chosen by ${esc(d.by)} ${esc(md(d.at))}` : ' · not chosen yet, this is the default'}</div>
    <div data-scope-depth-help class="mb-s2 text-provenance text-ink-muted">${esc(d.help || '')} Depth only changes what this tree shows; nothing is sent to Egeria from here.</div>`;
}

export function scopeSectionHtml(view, me, status = '') {
  const el = view.egeria_element || {};
  const element = el.short ? `reads Egeria element <span class="font-mono">${esc(el.short)}</span>…` : esc(el.text || 'not catalogued in Egeria');
  const ns = view.new_since || {};
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const nsLine = ns.text
    ? `<div data-scope-new-since class="mb-s1 text-caveat text-ink">${esc(ns.text)}
        · <button type="button" data-scope-redeclare ${dis} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">declare the scope again</button>
        <span class="text-provenance text-ink-muted">counts new things from the day you do</span></div>` : '';
  const cf = (view.conflicts || {}).count || 0;
  const cfLine = cf
    ? `<div data-scope-conflict-summary class="mb-s1 text-caveat text-ink">${glyphSpan('human')} ${cf} choice${cf === 1 ? '' : 's'} Egeria can't express — resolve ${cf === 1 ? 'it' : 'them'} below</div>` : '';
  return `<div data-scope-header class="mb-s1 text-answer text-ink">${esc(scopeHeaderText(view))}</div>
    ${me ? '' : `<div data-scope-signed-out class="mb-s1 text-caveat text-ink-muted">You can read the scope as it stands. ${esc(signInReason)}.</div>`}
    ${nsLine}${cfLine}
    ${depthLineHtml(view, me)}
    <div data-scope-tree-header class="mb-s1 text-provenance text-ink-muted">${element} · ${
      view.survey && view.survey.state === 'measured'
        ? `Egeria's latest survey ${esc(md(view.survey.surveyed_at))}: ${esc(String(view.survey.schema_count))} schemas, ${esc(String(view.survey.table_count))} tables`
        : "Egeria's latest survey: not measured yet"} · nothing here is sent to Egeria</div>
    <div data-scope-tree>${treeHtml(view, me)}</div>
    <div data-scope-status class="mt-s1 text-provenance text-ink-muted">${esc(status)}</div>`;
}

/* ── wiring ──────────────────────────────────────────────────────────── */

const stale = (el, slug) => !el.isConnected || slug !== state.selectedSlug;
const find = (view, schema, table) => {
  const s = (view.schemas || []).find((x) => x.name === schema);
  if (!s) return null;
  return table ? (s.tables || []).find((t) => t.name === table) || null : s;
};

export async function renderCatalogueScope(el, slug, status = '') {
  if (!el) throw new Error('Catalogue scope host missing');
  if (openFor !== slug) { openSchemas.clear(); openFor = slug; }
  let view;
  try {
    view = await getCatalogueScope(slug);
    if (!view || !Array.isArray(view.schemas)) throw new Error('the server answered with something that is not a scope');
  } catch (err) {
    if (stale(el, slug)) return;
    el.innerHTML = `<div data-scope-error class="text-caveat text-state-warn">The catalogue scope could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (stale(el, slug)) return;
  const me = whoAmI();
  el.innerHTML = scopeSectionHtml(view, me, status);
  const say = (msg, warn = false) => {
    const s = el.querySelector('[data-scope-status]');
    if (!s) return;
    s.textContent = msg;
    s.className = `mt-s1 text-provenance ${warn ? 'text-state-warn' : 'text-ink-muted'}`;
  };
  const failure = (err, what) => (err.status === 401 ? signInReason : `${what} failed: ${err.message}`);

  // After a write the words come from the re-read view, not from the click.
  const afterWrite = async (write, what, verify) => {
    try { await write(); } catch (err) { say(failure(err, what), true); return; }
    let again;
    try { again = await getCatalogueScope(slug); }
    catch (err) { say(`${what}: written, but the scope could not be re-read: ${err.message}`, true); return; }
    await renderCatalogueScope(el, slug, verify(again) || '');
  };

  const bindTree = () => {
    el.querySelectorAll('[data-scope-toggle]').forEach((b) => b.addEventListener('click', () => {
      const n = b.dataset.scopeToggle;
      if (openSchemas.has(n)) openSchemas.delete(n); else openSchemas.add(n);
      el.querySelector('[data-scope-tree]').innerHTML = treeHtml(view, me);
      bindTree();
    }));
    el.querySelectorAll('[data-scope-act]').forEach((b) => b.addEventListener('click', () => {
      const { scopeAct: act, scopeSchema: schema, scopeTable: table, scopeChoice: choice } = b.dataset;
      const label = table ? `${schema}.${table}` : schema;
      const check = (want) => (v) => {
        const n = find(v, schema, table);
        const got = n && n.explicit ? n.explicit.choice : '';
        return got === want
          ? `${label}: ${words(want) || 'no choice'} is in the re-read scope${want ? ` · set by ${n.explicit.by}` : ''}`
          : `the write returned, but the re-read scope shows ${got ? words(got) : 'no choice'} for ${label}`;
      };
      if (act === 'set') afterWrite(() => setCatalogueNode(slug, schema, table, choice), 'set the choice', check(choice));
      else if (act === 'clear') afterWrite(() => clearCatalogueNode(slug, schema, table), 'clear the choice', check(''));
      else if (act === 'confirm') {
        const want = (find(view, schema, table) || {}).proposal;
        afterWrite(() => confirmCatalogueNode(slug, schema, table), 'confirm the proposal', check(want ? want.choice : ''));
      } else if (act === 'override') {
        const want = (find(view, schema, table) || {}).proposal;
        afterWrite(() => overrideCatalogueNode(slug, schema, table), 'override the proposal', check(want ? opposite(want.choice) : ''));
      }
    }));
    el.querySelectorAll('[data-scope-resolve]').forEach((b) => b.addEventListener('click', () => {
      const name = b.dataset.scopeName;
      const choice = b.dataset.scopeResolve;
      afterWrite(() => resolveCatalogueConflict(slug, name, choice), 'resolve the conflict', (v) =>
        ((v.conflicts || {}).names || []).includes(name)
          ? `the write returned, but ${name} is still in conflict in the re-read scope`
          : `${name} is no longer in conflict`);
    }));
  };
  bindTree();
  el.querySelectorAll('[data-scope-depth-radio]').forEach((r) => r.addEventListener('change', () => {
    const want = r.dataset.scopeDepthRadio;
    afterWrite(() => setCatalogueDepth(slug, want), 'choose the depth', (v) =>
      (v.depth && v.depth.value === want ? `depth is now ${(v.depth.options.find((o) => o.id === want) || {}).label}`
        : 'the write returned, but the re-read scope shows a different depth'));
  }));
  const again = el.querySelector('[data-scope-redeclare]');
  if (again) again.addEventListener('click', () => afterWrite(() => redeclareCatalogueScope(slug), 'declare the scope again',
    (v) => ((v.new_since || {}).text ? 'the declaration returned, but the re-read scope still shows new things' : 'declared again: nothing is new since now')));
}
