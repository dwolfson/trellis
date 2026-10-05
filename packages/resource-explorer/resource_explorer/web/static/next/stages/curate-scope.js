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
  resolveCatalogueConflict, setCatalogueNodes,
} from '/static/re-api.js';
import { state, esc } from '/static/next/app.js';
import { glyphSpan } from '/static/next/glyphs.js';
import {
  SOURCE_WORD, md, nodeSourceLine, SCOPE_SAVED_MARKER, scopeCollapsedText,
  readScopePref, writeScopePref, scopeStartsOpen,
} from '/static/next/stages/scope-sources.js';

const whoAmI = () =>
  (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
const words = (choice) => (choice === 'leave_out' ? 'leave out' : choice === 'catalogue' ? 'catalogue' : '');
const opposite = (choice) => (choice === 'leave_out' ? 'catalogue' : 'leave_out');
const signInReason = 'sign in to change what gets catalogued: every choice needs an author';
const num = (n) => Number(n).toLocaleString('en-US');

/** Which schemas are expanded survives a redraw (a write redraws the tree). */
const openSchemas = new Set();
/** Which schema rows are ticked for a bulk choice (cleared after every write). */
const selected = new Set();
let openFor = '';
/** Forget which schemas were expanded or ticked (another database, or a fresh pane). */
export function resetScopeUi() { openSchemas.clear(); selected.clear(); openFor = ''; sectionOpen = null; }

/** Whether the whole section is open. Decided once per pane visit (from the remembered
 *  choice, else from whether a scope is declared) and then only a click changes it, so a
 *  write that redraws the section (or declares the scope) never flips it under the person. */
let sectionOpen = null;
const storage = () => { try { return globalThis.localStorage || null; } catch { return null; } };

/** What the header says about the measurement the tree is read from. One
 *  source: "29 schemas · Egeria survey 10-04". The two sources disagreeing:
 *  BOTH are named, so a reader can see the tree is not the thinner one. */
export function sourcesClause(view) {
  const src = view.sources;
  if (!src) {   // a server that predates the node-set resolver: the old sentence
    const sv = view.survey || {};
    return sv.state === 'measured'
      ? `Egeria's latest survey covers ${sv.schema_count} schemas, ${sv.table_count} tables`
      : "Egeria's latest survey: not measured yet";
  }
  const ch = src.chosen || {}; const eg = src.egeria || {}; const lo = src.local || {};
  const unreadable = lo.state === 'unreadable' ? "RE's own survey could not be read" : '';
  if (eg.state !== 'measured' && lo.state !== 'measured') return unreadable || "Egeria's latest survey: not measured yet";
  if (unreadable) return `${ch.schemas} schemas · ${SOURCE_WORD[ch.kind] || ch.kind} ${md(ch.as_of)} · ${unreadable}`;
  if (src.disagree && eg.state === 'measured' && lo.state === 'measured') {
    return `Egeria's latest survey covers ${eg.schema_count} schemas, ${eg.table_count} tables · RE's own survey saw ${lo.schema_count} schemas, ${lo.table_count} tables, ${md(lo.surveyed_at)}`;
  }
  const sees = ch.kind === 'local' && lo.sees ? ` · ${lo.sees} of ${lo.schema_count}` : '';
  return `${ch.schemas} schemas · ${SOURCE_WORD[ch.kind] || ch.kind} ${md(ch.as_of)}${sees}`;
}

export function scopeHeaderText(view) {
  if (view.declared && view.declared.declared) {
    const c = view.counts || {};
    return `Your scope: ${c.schemas_catalogue} of ${c.schemas_offered} schemas · declared by ${view.declared.by} ${md(view.declared.at)}${view.sources ? ` · ${sourcesClause(view)}` : ''}`;
  }
  return `Your scope: none declared yet · ${sourcesClause(view)}`;
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

/** Why a can't-tell row can't tell: the server's `reason`, or the text without its prefix. */
const cantTellReason = (lw) => lw.reason || String(lw.text || '').replace(/^can't tell( · )?/, '') || 'counters not measured';

/** The activity word, kept short ("can't tell", "dormant · 0 writes in 336 days",
 *  "active · 1,204 writes") with the whole sentence in the cell's title, so nothing is lost.
 *  A can't-tell proposes nothing, so it is drawn muted and carries no control; the reason
 *  it can't tell is said once above the tree (`activitySummaryHtml`) and on hover. */
function lastWriteCell(node) {
  const lw = node.last_write || {};
  const tip = lw.text ? ` title="${esc(lw.text)}"` : '';
  if (lw.state === 'cant_tell') return `<span class="text-ink-muted" data-scope-activity-cant-tell${tip}>can't tell</span>`;
  if (lw.state === 'dormant') {
    const short = lw.window_days != null ? `dormant · 0 writes in ${lw.window_days} days` : (lw.text || 'dormant');
    return `<span data-scope-activity-dormant${tip}>${esc(short)}</span>`;
  }
  if (lw.state === 'active') {
    const short = lw.writes != null ? `active · ${num(lw.writes)} writes` : (lw.text || 'active');
    return `<span data-scope-activity-active${tip}>${esc(short)}</span>`;
  }
  if (node.access === 'not_established') return '<span class="text-ink-muted">? not established</span>';
  return '<span class="text-ink-muted">not measured</span>';
}

/** ONE line above the tree for the can't-tell rows, grouped by reason, instead of the
 *  same reason repeated on every row: "Activity: can't tell on 266 rows: counter reset
 *  date not recorded". Counts tables, plus any schema that lists none. */
export function activitySummaryHtml(view) {
  const counts = new Map();
  const add = (n) => {
    const lw = n.last_write || {};
    if (lw.state !== 'cant_tell') return;
    const why = cantTellReason(lw).replace(/^reset date not recorded$/, 'counter reset date not recorded');
    counts.set(why, (counts.get(why) || 0) + 1);
  };
  (view.schemas || []).forEach((sc) => { if ((sc.tables || []).length) sc.tables.forEach(add); else add(sc); });
  if (!counts.size) return '';
  const parts = [...counts.entries()].sort((a, b) => b[1] - a[1])
    .map(([why, n]) => `on ${num(n)} row${n === 1 ? '' : 's'}: ${why}`);
  return `<div data-scope-activity-summary class="mb-s1 text-provenance text-ink-muted">Activity: can't tell ${esc(parts.join(' · '))}</div>`;
}

/** A rows or size cell: the number in its own kind (≈ for an estimate), "not measured",
 *  "? not established", or "◐ sources disagree" with both values dated beneath. The
 *  source and as-of ride on hover. Numbers align right in tabular figures. */
function factCell(v, fallback) {
  if (!v) return fallback;
  const tip = v.detail ? ` title="${esc(v.detail)}"` : '';
  if (v.state === 'disagree') {
    return `<div data-scope-disagree class="text-right text-ink"${tip}>${esc(v.text)}</div>
      <div class="text-right text-provenance text-ink-muted">${esc(v.detail)}</div>`;
  }
  if (v.state === 'not_measured' || v.state === 'not_established') {
    return `<span class="block text-right text-ink-muted"${tip}>${esc(v.text)}</span>`;
  }
  return `<span class="tnum block text-right"${tip}>${esc(v.text)}</span>`;
}

function rowsCell(node) {
  const v = node.kind === 'schema' ? node.row_total : node.row_count;
  const legacy = v == null ? '<span class="text-ink-muted">not established</span>'
    : `<span class="tnum">${node.is_estimate ? '~' : ''}${esc(num(v))}</span>`;
  return factCell(node.rows_view, legacy);
}

function sizeCell(node) {
  return factCell(node.size_view, '<span class="text-ink-muted">not measured</span>');
}


/* Column widths, shared by the header, rows and the column lines so they stay aligned.
 * Written out as literal classes (Tailwind scans this file; it cannot see a built string). */
function rowHtml(node, me, depth, kindWord) {
  const isSchema = node.kind === 'schema';
  const key = isSchema ? `schema:${node.name}` : `table:${node.schema}.${node.name}`;
  const toggle = isSchema
    ? `<button type="button" data-scope-toggle="${esc(node.name)}" aria-expanded="${openSchemas.has(node.name) ? 'true' : 'false'}"
        class="cursor-pointer bg-transparent p-0 text-ink-muted">${openSchemas.has(node.name) ? '▾' : '▸'}</button> ` : '';
  const nameTail = isSchema
    ? (node.table_count == null ? ' <span class="text-ink-muted">· tables not established</span>'
      : ` <span class="text-ink-muted" data-scope-table-count>· ${esc(String(node.table_count))} table${node.table_count === 1 ? '' : 's'}</span>`)
    : ` <span class="text-ink-muted" data-scope-kind>· ${esc(kindWord)}</span>`;
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const pick = isSchema
    ? `<input type="checkbox" data-scope-select="${esc(node.name)}" aria-label="select schema ${esc(node.name)}" ${selected.has(node.name) ? 'checked' : ''} ${dis}>` : '';
  const srcLine = nodeSourceLine(node);
  const src = srcLine ? `<div data-scope-source class="text-provenance text-ink-muted">${esc(srcLine)}</div>` : '';
  return `<div class="flex items-baseline gap-s2 border-b border-rule py-[3px] text-caveat" data-scope-row="${esc(key)}" data-scope-effective="${esc(node.effective || '')}">
    <div class="w-[2ch] shrink-0" data-scope-select-cell>${pick}</div>
    <div class="w-[24ch] shrink-0" data-scope-choice-cell>${choiceCellHtml(node, me)}</div>
    <div class="min-w-[16ch] flex-1 break-words text-ink" data-scope-name-cell>${toggle}<span class="${isSchema ? 'font-mono font-semibold' : 'font-mono'}">${esc(node.name)}</span>${nameTail}${src}</div>
    <div class="w-[9ch] shrink-0" data-scope-rows-cell>${rowsCell(node)}</div>
    <div class="w-[8ch] shrink-0" data-scope-size-cell>${sizeCell(node)}</div>
    <div class="w-[18ch] shrink-0" data-scope-lastwrite-cell>${lastWriteCell(node)}</div>
    <div class="w-[10ch] shrink-0 break-words" data-scope-classes-cell>${dataClassCell(node)}</div>
    <div class="w-[20ch] shrink-0" data-scope-state-cell><div data-scope-egeria-state class="text-ink-muted">not read yet</div>${stateCellHtml(node, me)}</div>
  </div>`;
}

/** A table's columns, directly beneath it and indented under the table's NAME (two empty
 *  cells the width of the tick and choice columns, then a rule and a "└" marker), muted and
 *  smaller than the rows, so they cannot read as belonging to the next table. */
function columnRowsHtml(table) {
  const cols = table.columns || [];
  if (!cols.length) return '';
  return `<div data-scope-columns class="mb-[3px] flex gap-s2">
    <div class="w-[2ch] shrink-0"></div><div class="w-[24ch] shrink-0"></div>
    <div class="flex-1 border-l border-rule pl-s2">${cols.map((c) => `<div data-scope-column class="py-[1px] text-provenance text-ink-muted">
      <span aria-hidden="true" class="text-rule-strong">└</span> <span class="font-mono">${esc(c.name)}</span> <span>${esc(c.type || '')}</span> <span class="text-accent-ink">${esc(c.key_role || '')}</span></div>`).join('')}</div></div>`;
}

const TABLE_KIND = { 'BASE TABLE': 'table', VIEW: 'view', 'MATERIALIZED VIEW': 'matview', FOREIGN: 'foreign table' };

export function treeHtml(view, me) {
  if (!(view.schemas || []).length && !view.system) {
    return `<div class="text-caveat text-ink-muted">No stored schema rows yet: run a survey first. Nothing to scope until Egeria's survey or RE's has listed the schemas.</div>`;
  }
  const head = `<div class="flex items-baseline gap-s2 border-b border-rule py-[3px] text-caveat text-caps uppercase tracking-caps text-ink-muted" data-scope-tree-head>
    <div class="w-[2ch] shrink-0"></div><div class="w-[24ch] shrink-0">choice</div><div class="min-w-[16ch] flex-1">Schema / table</div>
    <div class="w-[9ch] shrink-0 text-right" title="Row count; the source and date ride on each cell">Rows</div>
    <div class="w-[8ch] shrink-0 text-right" title="Size on disk; the source and date ride on each cell">Size</div>
    <div class="w-[18ch] shrink-0" data-scope-activity-head title="Activity: dormant means 0 writes in at least ${esc(String(view.dormancy_days || 90))} days of counter evidence">Activity</div>
    <div class="w-[10ch] shrink-0" data-scope-classes-head title="Data classes found in the columns">Classes</div>
    <div class="w-[20ch] shrink-0" data-scope-state-head title="State in Egeria">In Egeria</div></div>`;
  const body = (view.schemas || []).map((s) => {
    const open = openSchemas.has(s.name) || s.tables.some((t) => t.conflict);
    if (open) openSchemas.add(s.name);
    const tables = open ? s.tables.map((t) => `<div class="ml-s3">${rowHtml(t, me, 1, TABLE_KIND[t.table_type] || 'table')}${columnRowsHtml(t)}</div>`).join('')
      || '<div class="ml-s3 text-caveat text-ink-muted">No tables.</div>' : '';
    return `<div data-scope-schema-block="${esc(s.name)}">${rowHtml(s, me, 0, '')}${tables}</div>`;
  }).join('');
  const sys = view.system
    ? `<div data-scope-system class="mt-s1 text-caveat text-ink-muted">${esc(String(view.system.folded))} system schemas folded · ${esc(view.system.text)}</div>` : '';
  // A fixed floor (not max-content, which let one long sentence widen every row): at about
  // 1300px everything fits, and below the floor the host scrolls sideways inside its own
  // container instead of clipping at the edge.
  return `<div class="min-w-[64rem]">${head + body + sys}</div>`;
}

/** The tick-everything box and the bulk bar above the tree. */
export function bulkBarHtml(view, me) {
  const n = (view.schemas || []).length;
  if (!n) return '';
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const none = selected.size === 0;
  const need = (on) => (!me ? `disabled title="${esc(signInReason)}"` : (on ? '' : 'disabled title="select at least one schema first"'));
  const bulk = (act, label) => `<button type="button" data-scope-bulk-act="${act}" ${need(!none)} class="${me && !none ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">${label}</button>`;
  return `<div data-scope-bulk class="mb-s1 flex flex-wrap items-baseline gap-s2 text-caveat text-ink">
    <label class="inline-flex cursor-pointer items-baseline gap-[4px]"><input type="checkbox" data-scope-all-box ${selected.size === n ? 'checked' : ''} ${dis}> select all schemas</label>
    <span data-scope-selected-count class="text-ink-muted">${selected.size} of ${n} selected</span>
    ${bulk('catalogue', 'catalogue selected')} · ${bulk('leave_out', 'leave out selected')} · ${bulk('clear', 'clear choice')}
    <span class="text-ink-muted">|</span>
    <button type="button" data-scope-catalogue-all ${dis} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">catalogue all ${n} schemas</button></div>`;
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

/** Which measurement this tree was built from, with the merge said out loud. */
function treeSourceText(view) {
  const ch = (view.sources || {}).chosen;
  if (!ch) {
    return view.survey && view.survey.state === 'measured'
      ? `Egeria's latest survey ${md(view.survey.surveyed_at)}: ${view.survey.schema_count} schemas, ${view.survey.table_count} tables`
      : "Egeria's latest survey: not measured yet";
  }
  const unread = (view.sources || {}).unreadable;
  return `tree read from the ${SOURCE_WORD[ch.kind] || ch.kind} ${md(ch.as_of)}: ${ch.schemas} schemas, ${ch.tables} tables${ch.merged ? ', facts it lacked filled from the other survey' : ''}${unread ? ` · ${unread} annotation${unread === 1 ? '' : 's'} could not be read` : ''}`;
}

export function scopeSectionHtml(view, me, status = '', open = scopeStartsOpen(view, '')) {
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
  const declared = !!(view.declared && view.declared.declared);
  const line = open || !declared ? scopeHeaderText(view) : scopeCollapsedText(view);
  return `<div data-scope-saved-marker class="mb-s1 text-provenance text-ink-muted">${esc(SCOPE_SAVED_MARKER)}</div>
    <div data-scope-header class="mb-s1 text-answer text-ink"><button type="button" data-scope-collapse aria-expanded="${open ? 'true' : 'false'}"
      aria-controls="scope-section-body" title="${open ? 'Collapse to one line' : 'Show the whole scope'}"
      class="cursor-pointer bg-transparent p-0 text-left text-answer text-ink"><span aria-hidden="true" class="text-ink-muted">${open ? '▾' : '▸'}</span> <span data-scope-header-line>${esc(line)}</span></button></div>
    <div id="scope-section-body" data-scope-body${open ? '' : ' hidden'}>
    ${me ? '' : `<div data-scope-signed-out class="mb-s1 text-caveat text-ink-muted">You can read the scope as it stands. ${esc(signInReason)}.</div>`}
    ${nsLine}${cfLine}
    ${depthLineHtml(view, me)}
    <div data-scope-tree-header class="mb-s1 text-provenance text-ink-muted">${element} · ${esc(treeSourceText(view))} · nothing here is sent to Egeria</div>
    <div data-scope-activity-rule class="mb-s1 text-provenance text-ink-muted">activity comes from the cumulative write counters since their last reset: dormant means 0 writes in at least ${esc(String(view.dormancy_days || 90))} days of evidence, and “can't tell” proposes nothing</div>
    ${activitySummaryHtml(view)}
    ${(view.suggested_rules || []).map((r) => `<div data-scope-suggested-rule class="mb-s1 text-caveat text-ink-muted">${esc(r.text)}</div>`).join('')}
    ${bulkBarHtml(view, me)}
    <div data-scope-tree class="overflow-x-auto" style="overflow-x:auto">${treeHtml(view, me)}</div>
    </div>
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
  if (openFor !== slug) { openSchemas.clear(); selected.clear(); openFor = slug; sectionOpen = null; }
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
  if (sectionOpen === null) sectionOpen = scopeStartsOpen(view, readScopePref(storage(), me, slug));
  el.innerHTML = scopeSectionHtml(view, me, status, sectionOpen);
  const fold = el.querySelector('[data-scope-collapse]');
  if (fold) fold.addEventListener('click', () => {
    sectionOpen = !sectionOpen;
    writeScopePref(storage(), me, slug, sectionOpen);   // best effort: the page works without storage
    const body = el.querySelector('[data-scope-body]');
    if (body) body.hidden = !sectionOpen;
    // The same button is edited in place (focus stays on it); the words come from the view.
    const declared = !!(view.declared && view.declared.declared);
    fold.setAttribute('aria-expanded', sectionOpen ? 'true' : 'false');
    fold.title = sectionOpen ? 'Collapse to one line' : 'Show the whole scope';
    fold.querySelector('[aria-hidden]').textContent = sectionOpen ? '▾' : '▸';
    fold.querySelector('[data-scope-header-line]').textContent =
      sectionOpen || !declared ? scopeHeaderText(view) : scopeCollapsedText(view);
  });
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

  const offered = (view.schemas || []).map((x) => x.name);
  /** The bulk bar and the row ticks are re-drawn from `selected`, never from the DOM. */
  const bindBulk = () => {
    const bar = el.querySelector('[data-scope-bulk]');
    if (bar) {
      const all = bar.querySelector('[data-scope-all-box]');
      if (all) {
        all.indeterminate = selected.size > 0 && selected.size < offered.length;
        all.addEventListener('change', () => {
          selected.clear();
          if (all.checked) offered.forEach((n) => selected.add(n));
          refreshBulk();
        });
      }
      bar.querySelectorAll('[data-scope-bulk-act]').forEach((b) => b.addEventListener('click', () => {
        const act = b.dataset.scopeBulkAct;
        runBulk([...selected].filter((n) => offered.includes(n)), act === 'clear' ? '' : act, false);
      }));
      const every = bar.querySelector('[data-scope-catalogue-all]');
      if (every) every.addEventListener('click', () => runBulk(offered.slice(), 'catalogue', true));
    }
  };
  const refreshBulk = () => {
    const bar = el.querySelector('[data-scope-bulk]');
    if (bar) bar.outerHTML = bulkBarHtml(view, me);
    el.querySelector('[data-scope-tree]').innerHTML = treeHtml(view, me);
    bindBulk();
    bindTree();
  };
  /** Bulk choice: one write, then the sentence comes from the re-read scope. */
  const runBulk = (names, choice, everySchema) => {
    if (!names.length) { say('select at least one schema first', true); return; }
    selected.clear();
    const label = choice ? words(choice) : 'no choice';
    afterWrite(() => setCatalogueNodes(slug, names.map((n) => ({ schema: n })), choice, everySchema),
      'set the choices', (v) => {
        const got = names.map((n) => find(v, n, '')).filter(Boolean);
        const ok = got.filter((n) => (n.explicit ? n.explicit.choice : '') === choice);
        const by = [...new Set(ok.map((n) => (n.explicit ? n.explicit.by : '')).filter(Boolean))];
        const differ = got.reduce((acc, n) => acc + (n.tables || []).filter((t) => t.differs_from_schema).length, 0);
        const tail = differ
          ? (differ === 1 ? ' · 1 table keeps its own choice and differs from its schema'
            : ` · ${differ} tables keep their own choice and differ from their schema`) : '';
        if (ok.length !== names.length) {
          return `the write returned, but the re-read scope shows only ${ok.length} of ${names.length} schemas set to ${label}`;
        }
        return choice
          ? `${ok.length} schema${ok.length === 1 ? '' : 's'} now set to ${label} by ${by.join(', ')}${tail}`
          : `${ok.length} schema${ok.length === 1 ? '' : 's'} now have no choice in the re-read scope${tail}`;
      });
  };

  const bindTree = () => {
    el.querySelectorAll('[data-scope-select]').forEach((box) => box.addEventListener('change', () => {
      if (box.checked) selected.add(box.dataset.scopeSelect); else selected.delete(box.dataset.scopeSelect);
      const bar = el.querySelector('[data-scope-bulk]');
      if (bar) { bar.outerHTML = bulkBarHtml(view, me); bindBulk(); }
    }));
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
  bindBulk();
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
