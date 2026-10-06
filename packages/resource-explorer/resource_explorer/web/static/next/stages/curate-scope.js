/* Curate, database, band 2, first section: "What gets catalogued".
 *
 * The designer's reply on catalogue scope and
 * wireframes/CatalogueScope.dc.html (page 18). Slice A drew the scope: a declared,
 * signed, dated choice stored in RE (web/routes/catalogue_scope.py). Slice B
 * (BRIEF-CURATE-CATALOGUE-COMMIT-DATABASES.md) adds the commit: a manifest of the
 * three mechanisms, the Catalogue button, and the per-node proof states. Editing
 * the scope still writes nothing to Egeria; only the Catalogue button and "Read
 * Egeria again" do, and both are disabled when nobody is signed in.
 *
 * Rules this file keeps:
 *  - what a row says comes from the server's re-read AFTER a write, never
 *    from what the click assumed; a status sentence is derived from those
 *    rows (the same rule curate-bands.js keeps). The "In Egeria" column and the
 *    header marker are drawn from `view.commit`, which the server derives from
 *    persisted proof rows only: a state with no proof row is never drawn;
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
  setCatalogueNodes, getCatalogueCommitPreview,
  postCatalogueCommit, getCatalogueCommitRecord, postCatalogueReadBack,
} from '/static/re-api.js';
import { state, esc } from '/static/next/app.js';
import { glyphSpan } from '/static/next/glyphs.js';
import {
  SOURCE_WORD, md, nodeSourceLine, scopeCollapsedText,
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
/** Which schema rows are ticked for a bulk choice (spent when a bulk action completes). */
const selected = new Set();
/** Which table rows are ticked, as `schema` + TAB + `table`. */
const selectedTables = new Set();
const tkey = (schema, tbl) => `${schema}\t${tbl}`;
/** The name filter over schemas and tables; it survives a redraw. */
let filterText = '';
/** A keystroke redraws the tree this long after the last one. */
const FILTER_DEBOUNCE_MS = 150;
let openFor = '';
/** Rows whose choice was just saved: key -> {by, at}. A plain line on the row says so for a few seconds. */
const savedNotes = new Map();
let savedNoteMs = 6000;
export function setSavedNoteMs(ms) { savedNoteMs = ms; }
/** The last commit pressed on this pane, kept so its steps survive the re-draw that follows it. */
let commitUi = null;
/** How long between reads of a running commit's record (a test shortens it). */
let commitPollMs = 2000;
export function setCommitPollMs(ms) { commitPollMs = ms; }
/** Forget which schemas were expanded or ticked (another database, or a fresh pane). */
export function resetScopeUi() { savedNotes.clear(); openSchemas.clear(); selected.clear(); selectedTables.clear(); filterText = ''; openFor = ''; sectionOpen = null; commitUi = null; }

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

/** The state-derived marker line: what the proof rows say Egeria holds, never a constant. */
export function commitHeaderText(view) {
  const h = (view.commit || {}).header;
  return h && h.text ? h.text : 'Egeria state not read: this server sent no proof rows';
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
export function choiceCellHtml(node, me, commit = null) {
  return choiceCellCore(node, me) + savedNoteHtml(node, commit);
}

/** "saved in Resource Explorer · who · when · not yet cataloged in Egeria": shown for a few seconds
 *  after a choice write, so a choice is not read as a write to Egeria. The Egeria clause comes from the
 *  node's commit state: a node already in Egeria is told it changes only when Catalog is pressed. */
function savedNoteHtml(node, commit) {
  const key = node.kind === 'schema' ? `schema:${node.name}` : `table:${node.schema}.${node.name}`;
  const n = savedNotes.get(key);
  if (!n) return '';
  const st = node.kind === 'schema' ? ((commit || {}).schemas || {})[node.name] : ((commit || {}).tables || {})[`${node.schema}.${node.name}`];
  const tail = !st || ['none', 'uncommitted', 'left_out'].includes(st.state) ? 'not yet cataloged in Egeria' : 'Egeria changes when you press Catalog';
  return `<div data-scope-saved-note class="text-provenance text-ink-muted">saved in Resource Explorer · ${esc(n.by)} · ${esc(n.at)} · ${tail}</div>`;
}

function choiceCellCore(node, me) {
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

/** The "In Egeria" cell: the commit's derived state for this node, with its glyph and its
 *  second line. `commit` is `view.commit`; a server that predates it says "not read yet".
 *  A node with no state ('none') says nothing about Egeria rather than inventing a word. */
const EGERIA_GLYPH = {
  catalogued: 'catalogued', attached_waiting: 'attached_waiting', queued: 'queued', sent: 'queued',
  failed: 'catalogue_failed', removed: 'removed', archived: 'archived',
};
export function egeriaStateHtml(node, commit) {
  if (!commit) return '<div data-scope-egeria-state class="text-ink-muted">not read yet</div>';
  const st = node.kind === 'schema' ? (commit.schemas || {})[node.name] : (commit.tables || {})[`${node.schema}.${node.name}`];
  if (!st || st.state === 'none' || !st.words) {
    return '<div data-scope-egeria-state data-scope-egeria-word="none" class="text-ink-muted">—</div>';
  }
  const glyph = EGERIA_GLYPH[st.state] ? `${glyphSpan(EGERIA_GLYPH[st.state])} ` : '';
  const isMuted = ['uncommitted', 'left_out', 'follows_schema', 'not_read_back'].includes(st.state);
  const second = st.second ? `<div data-scope-egeria-second class="text-provenance text-ink-muted">${esc(st.second)}</div>` : '';
  return `<div data-scope-egeria-state data-scope-egeria-word="${esc(st.state)}" class="${isMuted ? 'text-ink-muted' : 'text-ink'}">${glyph}${esc(st.words)}${detailsHtml(st.details, 'data-scope-egeria-details')}</div>${second}`;
}

function collisionLines(node, commit) {
  return ((commit && commit.collisions) || [])
    .filter((c) => (node.kind === 'schema' ? c.kind === 'schema' && c.name === node.name
      : c.kind === 'table' && c.schema === node.schema && c.name === node.name))
    .map((c) => `<div data-scope-collision class="text-ink">${esc(c.text)}</div>`).join('');
}

function stateCellHtml(node) {
  const lines = [];
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
function rowHtml(node, me, depth, kindWord, commit, open = false) {
  const isSchema = node.kind === 'schema';
  const key = isSchema ? `schema:${node.name}` : `table:${node.schema}.${node.name}`;
  const toggle = isSchema
    ? `<button type="button" data-scope-toggle="${esc(node.name)}" aria-expanded="${open ? 'true' : 'false'}"
        class="cursor-pointer bg-transparent p-0 text-ink-muted">${open ? '▾' : '▸'}</button> ` : '';
  const nameTail = isSchema
    ? (node.table_count == null ? ' <span class="text-ink-muted">· tables not established</span>'
      : ` <span class="text-ink-muted" data-scope-table-count>· ${esc(String(node.table_count))} table${node.table_count === 1 ? '' : 's'}</span>`)
    : ` <span class="text-ink-muted" data-scope-kind>· ${esc(kindWord)}</span>`;
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const pick = isSchema
    ? `<input type="checkbox" data-scope-select="${esc(node.name)}" aria-label="select schema ${esc(node.name)}" ${selected.has(node.name) ? 'checked' : ''} ${dis}>`
    : `<input type="checkbox" data-scope-select-schema="${esc(node.schema)}" data-scope-select-table="${esc(node.name)}" aria-label="select table ${esc(node.schema)}.${esc(node.name)}" ${selectedTables.has(tkey(node.schema, node.name)) ? 'checked' : ''} ${dis}>`;
  const srcLine = nodeSourceLine(node);
  const src = srcLine ? `<div data-scope-source class="text-provenance text-ink-muted">${esc(srcLine)}</div>` : '';
  return `<div class="flex items-baseline gap-s2 border-b border-rule py-[3px] text-caveat" data-scope-row="${esc(key)}" data-scope-effective="${esc(node.effective || '')}">
    <div class="w-[2ch] shrink-0" data-scope-select-cell>${pick}</div>
    <div class="w-[22ch] shrink-0" data-scope-choice-cell>${choiceCellHtml(node, me, commit)}</div>
    <div class="min-w-[14ch] flex-1 break-words text-ink" data-scope-name-cell>${toggle}<span class="${isSchema ? 'font-mono font-semibold' : 'font-mono'}">${esc(node.name)}</span>${nameTail}${src}</div>
    <div class="w-[8ch] shrink-0" data-scope-rows-cell>${rowsCell(node)}</div>
    <div class="w-[8ch] shrink-0" data-scope-size-cell>${sizeCell(node)}</div>
    <div class="w-[14ch] shrink-0 break-words" data-scope-lastwrite-cell>${lastWriteCell(node)}</div>
    <div class="w-[14ch] shrink-0 break-words" data-scope-classes-cell>${dataClassCell(node)}</div>
    <div class="w-[18ch] shrink-0 break-words" data-scope-state-cell>${egeriaStateHtml(node, commit)}${collisionLines(node, commit)}${stateCellHtml(node)}</div>
  </div>`;
}

/** A table's columns, directly beneath it and indented under the table's NAME (two empty
 *  cells the width of the tick and choice columns, then a rule and a "└" marker), muted and
 *  smaller than the rows, so they cannot read as belonging to the next table. */
function columnRowsHtml(table) {
  const cols = table.columns || [];
  if (!cols.length) return '';
  return `<div data-scope-columns class="mb-[3px] flex gap-s2">
    <div class="w-[2ch] shrink-0"></div><div class="w-[22ch] shrink-0"></div>
    <div class="flex-1 border-l border-rule pl-s2">${cols.map((c) => `<div data-scope-column class="py-[1px] text-provenance text-ink-muted">
      <span aria-hidden="true" class="text-rule-strong">└</span> <span class="font-mono">${esc(c.name)}</span> <span>${esc(c.type || '')}</span> <span class="text-accent-ink">${esc(c.key_role || '')}</span></div>`).join('')}</div></div>`;
}

const TABLE_KIND = { 'BASE TABLE': 'table', VIEW: 'view', 'MATERIALIZED VIEW': 'matview', FOREIGN: 'foreign table' };

/** What the tree shows: every schema, or (with a filter) the schemas that match by name or hold a
 *  matching table, expanded, with the matching tables (all of them when the schema's own name matches).
 *  `shown` / `total` count schema and table rows for the "showing X of Y" line. Select all and clear
 *  act on `rows`: the rows actually drawn. */
export function treePlan(view) {
  const f = filterText.trim().toLowerCase();
  const rows = [];
  let shown = 0; let total = 0;
  for (const s of view.schemas || []) {
    const tabs = s.tables || [];
    total += 1 + tabs.length;
    const selfHit = !f || s.name.toLowerCase().includes(f);
    const hits = !f || selfHit ? tabs : tabs.filter((t) => t.name.toLowerCase().includes(f));
    if (f && !selfHit && !hits.length) continue;
    shown += 1 + hits.length;
    const open = f ? true : openSchemas.has(s.name);
    rows.push({ s, tables: hits, open });
  }
  return { rows, shown, total };
}

export function treeHtml(view, me) {
  if (!(view.schemas || []).length && !view.system) {
    return `<div class="text-caveat text-ink-muted">No stored schema rows yet: run a survey first. Nothing to scope until Egeria's survey or RE's has listed the schemas.</div>`;
  }
  const head = `<div class="flex items-baseline gap-s2 border-b border-rule py-[3px] text-caveat text-caps uppercase tracking-caps text-ink-muted" data-scope-tree-head>
    <div class="w-[2ch] shrink-0"></div><div class="w-[22ch] shrink-0 break-words">choice</div><div class="min-w-[14ch] flex-1 break-words">Schema / table</div>
    <div class="w-[8ch] shrink-0 break-words text-right" title="Row count; the source and date ride on each cell">Rows</div>
    <div class="w-[8ch] shrink-0 break-words text-right" title="Size on disk; the source and date ride on each cell">Size</div>
    <div class="w-[14ch] shrink-0 break-words" data-scope-activity-head title="Activity: dormant means 0 writes in at least ${esc(String(view.dormancy_days || 90))} days of counter evidence">Activity</div>
    <div class="w-[14ch] shrink-0 break-words" data-scope-classes-head title="Data classes found in the columns">Classification</div>
    <div class="w-[18ch] shrink-0 break-words" data-scope-state-head title="State in Egeria">In Egeria</div></div>`;
  const plan = treePlan(view);
  const body = plan.rows.map(({ s, tables: shownTables, open }) => {
    const tables = open ? shownTables.map((t) => `<div class="ml-s3">${rowHtml(t, me, 1, TABLE_KIND[t.table_type] || 'table', view.commit)}${columnRowsHtml(t)}</div>`).join('')
      || '<div class="ml-s3 text-caveat text-ink-muted">No tables.</div>' : '';
    return `<div data-scope-schema-block="${esc(s.name)}">${rowHtml(s, me, 0, '', view.commit, open)}${tables}</div>`;
  }).join('') || `<div data-scope-filter-empty class="py-s1 text-caveat text-ink-muted">Nothing matches “${esc(filterText.trim())}”.</div>`;
  const sys = view.system
    ? `<div data-scope-system class="mt-s1 text-caveat text-ink-muted">${esc(String(view.system.folded))} system schemas folded · ${esc(view.system.text)}</div>` : '';
  // A fixed floor (not max-content, which let one long sentence widen every row): at about
  // 1300px everything fits, and below the floor the host scrolls sideways inside its own
  // container instead of clipping at the edge.
  return `<div class="min-w-[52rem]">${head + body + sys}</div>`;
}

/** The rows select all and clear act on: the schemas and tables the tree is drawing now. */
function visibleRows(view) {
  const rows = treePlan(view).rows;
  return {
    schemas: rows.map((r) => r.s.name),
    tables: rows.flatMap((r) => (r.open ? r.tables : []).map((t) => ({ schema: r.s.name, table: t.name }))),
  };
}
const countTables = (view) => (view.schemas || []).reduce((a, s) => a + (s.tables || []).length, 0);

/** "showing X of Y": the rows (schemas and tables) that match the filter, of all of them. */
export function filterBarHtml(view) {
  const p = treePlan(view);
  return `<div data-scope-filterbar class="mb-s1 flex flex-wrap items-baseline gap-s2 text-caveat text-ink">
    <label class="inline-flex items-baseline gap-[4px]">filter
      <input type="search" data-scope-filter value="${esc(filterText)}" placeholder="schema or table name" autocomplete="off" class="rounded-sm border border-rule bg-transparent px-[4px] py-[1px] font-mono"></label>
    <span data-scope-filter-count class="text-ink-muted" title="schema and table rows that match the filter, of all rows">showing ${p.shown} of ${p.total}</span></div>`;
}

/** The tick-everything box and the bulk bar above the tree. */
export function bulkBarHtml(view, me) {
  const n = (view.schemas || []).length;
  if (!n) return '';
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const none = selected.size === 0 && selectedTables.size === 0;
  const vis = visibleRows(view);
  const nVis = vis.schemas.length + vis.tables.length;
  const nSelVis = vis.schemas.filter((x) => selected.has(x)).length
    + vis.tables.filter((t) => selectedTables.has(tkey(t.schema, t.table))).length;
  const need = (on) => (!me ? `disabled title="${esc(signInReason)}"` : (on ? '' : 'disabled title="select at least one schema or table first"'));
  const bulk = (act, label) => `<button type="button" data-scope-bulk-act="${act}" ${need(!none)} class="${me && !none ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">${label}</button>`;
  return `<div data-scope-bulk class="mb-s1 flex flex-wrap items-baseline gap-s2 text-caveat text-ink">
    <label class="inline-flex cursor-pointer items-baseline gap-[4px]"><input type="checkbox" data-scope-all-box ${nVis && nSelVis === nVis ? 'checked' : ''} ${dis}> select all shown</label>
    <button type="button" data-scope-clear-selection ${nSelVis ? '' : 'disabled'} class="${nSelVis ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">clear selection</button>
    <span data-scope-selected-count class="text-ink-muted">${selected.size} of ${n} schemas · ${selectedTables.size} of ${countTables(view)} tables selected</span>
    ${bulk('catalogue', 'catalog selected')} · ${bulk('leave_out', 'leave out selected')} · ${bulk('clear', 'clear choice')}
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
    <div data-scope-depth-help class="${d.commit_note ? '' : 'mb-s2 '}text-provenance text-ink-muted">${esc(d.help || '')}</div>
    ${d.commit_note ? `<div data-scope-depth-commit-note class="mb-s2 text-provenance text-ink">${esc(d.commit_note)}</div>` : ''}`;
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
  const declared = !!(view.declared && view.declared.declared);
  open = open || !declared;   // nothing to collapse to until a scope is declared
  const line = open ? scopeHeaderText(view) : scopeCollapsedText(view);
  // The marker under the header is the commit's state, derived by the server from proof rows;
  // the "not yet catalogued" words exist only server-side, and only while no commit has left a row.
  return `<div data-scope-saved-marker data-scope-commit-header data-scope-commit-header-state="${esc(((view.commit || {}).header || {}).state || 'unknown')}" class="mb-s1 text-provenance text-ink-muted">${esc(commitHeaderText(view))}</div>
    <div class="mb-s1 text-answer text-ink"><button type="button" data-scope-collapse aria-expanded="${open ? 'true' : 'false'}"
      aria-controls="scope-section-body" title="${open ? 'Collapse to one line' : 'Show the whole scope'}"
      class="cursor-pointer bg-transparent p-0 text-left text-answer text-ink"><span aria-hidden="true" class="text-ink-muted">${open ? '▾' : '▸'}</span> <span data-scope-header><span data-scope-header-line>${esc(line)}</span></span></button></div>
    <div id="scope-section-body" data-scope-body${open ? '' : ' hidden'}>
    ${me ? '' : `<div data-scope-signed-out class="mb-s1 text-caveat text-ink-muted">You can read the scope as it stands. ${esc(signInReason)}.</div>`}
    ${nsLine}
    ${depthLineHtml(view, me)}
    <div data-scope-tree-header class="mb-s1 text-provenance text-ink-muted">${element} · ${esc(treeSourceText(view))}</div>
    <div data-scope-activity-rule class="mb-s1 text-provenance text-ink-muted">activity comes from the cumulative write counters since their last reset: dormant means 0 writes in at least ${esc(String(view.dormancy_days || 90))} days of evidence, and “can't tell” proposes nothing</div>
    ${activitySummaryHtml(view)}
    ${(view.suggested_rules || []).map((r) => `<div data-scope-suggested-rule class="mb-s1 text-caveat text-ink-muted">${esc(r.text)}</div>`).join('')}
    ${(view.schemas || []).length ? filterBarHtml(view) : ''}${bulkBarHtml(view, me)}
    <div data-scope-tree class="min-w-0 max-w-full overflow-x-auto" style="overflow-x:auto">${treeHtml(view, me)}</div>
    <div data-scope-commit class="mt-s2"></div>
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

/* ── the commit (slice B) ───────────────────────────────────────────── */

const STEP_LABEL = {
  publish_elements: 'publish the server and database', zone_membership: 'ZoneMembership on the database',
  owner: 'owner from Context', schema_targets: 'attach the schema targets', leave_outs: 'leave outs',
  survey_report: "RE's own survey report", survey: "Egeria's survey", refresh: 'refresh the cataloguer',
  read_back: 'read Egeria back',
};
const STEP_GLYPH = { done: 'catalogued', failed: 'catalogue_failed', running: 'queued', pending: 'queued', submitted: 'queued', requested: 'queued' };

/** Egeria's long tail (the `* Context:` block) folded under "details": the row reads its first sentence. */
const detailsHtml = (more, attr) => (more
  ? ` <details ${attr} class="inline text-provenance text-ink-muted"><summary class="inline cursor-pointer">details</summary><div class="whitespace-pre-wrap break-words">${esc(more)}</div></details>` : '');

/** The steps of the curation record, exactly as the record holds them. A step's state word is
 *  the record's, which the server writes from rows (the outbox, the proof rows), never a guess. */
export function commitStepsHtml(rec) {
  if (!rec) return '';
  const rows = (rec.steps || []).map((st) => `<div data-scope-commit-step="${esc(st.name)}" data-state="${esc(st.state)}" class="text-provenance ${st.state === 'failed' ? 'text-state-warn' : 'text-ink-muted'}">
    ${STEP_GLYPH[st.state] ? `${glyphSpan(STEP_GLYPH[st.state])} ` : ''}${esc(STEP_LABEL[st.name] || st.name)} · ${esc(st.state)}${st.detail ? ` · ${esc(st.detail)}` : ''}${detailsHtml(st.more, 'data-scope-step-details')}</div>`).join('');
  return `<div data-scope-commit-steps class="mt-s1"><div class="text-caveat text-ink">Commit ${esc(String(rec.id || '').slice(0, 8))} · ${esc(rec.state || '')} · by ${esc(rec.author || '')}</div>${rows}</div>`;
}

/** What pressing Catalogue would do, as the server's preview says it: the three mechanisms in the
 *  order they run, what leaving schemas out does and in which form, anything that blocks the
 *  press, and the button whose label carries the counts. */
export function commitPanelHtml(preview, me, ui, declared = true) {
  const m = preview.manifest || {};
  const dis = (why) => `disabled title="${esc(why)}"`;
  const reason = !me ? signInReason : commitWhyNot(preview, declared);
  const lines = (m.lines || []).map((ln) => `<li data-scope-manifest-line="${esc(ln.id)}" class="${ln.mechanism ? 'text-ink' : 'text-ink-muted'}">${ln.mechanism ? `${ln.mechanism}. ` : ''}${esc(ln.text)}</li>`).join('');
  const refused = (preview.refused || []).map((r) => `<div data-scope-refused="${esc(r.schema)}" class="text-ink">${glyphSpan('human')} ${esc(r.text)}</div>`).join('');
  const collisions = (preview.collisions || []).map((c) => `<div data-scope-collision-line class="text-ink">${esc(c.text)}</div>`).join('');
  const leave = (preview.leave_out || []).map((r) => `<div data-scope-leave-out="${esc(r.schema)}" data-form="${esc(r.form)}" class="${r.blocked ? 'text-ink' : 'text-ink-muted'}">${r.blocked ? `${glyphSpan('human')} ` : ''}${esc(r.text)}</div>`).join('');
  const blockers = (preview.blockers || []).map((b) => `<div data-scope-blocker class="text-ink">${glyphSpan('human')} ${esc(b)}</div>`).join('');
  const off = !!reason;
  const sent = ui && ui.polling ? '<div data-scope-commit-sent class="mt-s1 text-caveat text-ink">sent · waiting for Egeria</div>' : '';
  return `<div data-scope-commit-panel>
    <div class="mb-s1 text-answer text-ink">What this commit does</div>
    <ol data-scope-manifest class="mb-s1 list-none pl-0 text-caveat">${lines}</ol>
    ${refused}${collisions}${leave}${blockers}
    <label class="mt-s1 flex cursor-pointer items-baseline gap-[4px] text-caveat text-ink"><input type="checkbox" data-scope-refresh-now checked ${me ? '' : 'disabled'}> refresh Egeria's cataloger now (about 16 s; RE never restarts a connector)</label>
    <div data-scope-commit-row class="mt-s1 flex flex-wrap items-baseline gap-s3">
      <button type="button" data-scope-commit-btn ${off ? dis(reason) : ''} class="rounded-sm border border-accent bg-accent px-s3 py-[6px] text-resource font-semibold text-chrome ${off ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}">${esc(preview.button || 'Catalog')}</button>
      ${off ? `<span data-scope-commit-why class="text-caveat text-ink">${esc(reason)}</span>` : ''}
    </div>
    ${sent}
    <div class="mt-s1 text-caveat"><button type="button" data-scope-read-back ${me ? '' : dis(signInReason)} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">Read Egeria again</button></div>
    <div data-scope-commit-status class="mt-s1 text-provenance text-ink-muted"></div>
    ${commitStepsHtml(ui && ui.rec)}
  </div>`;
}

/** Why the commit button is off, in the words a person needs ('' when it is on). */
export function commitWhyNot(preview, declared = true) {
  if (!declared) return 'no scope declared: choose what to catalog first';
  if (preview.can_commit) return '';
  const first = (preview.blockers || [])[0] || '';
  if (/^nothing to commit/.test(first)) return 'nothing chosen: choose at least one schema to catalog';
  if (/name collision/.test(first)) {
    const t = (preview.collisions || []).map((c) => String(c.text).replace(/^⚠\s*/, '')).join(' · ');
    return `name collisions: ${t || first}`;
  }
  return first || 'the commit is disabled';
}

/** One line for the status area, derived from the record's own steps. */
function commitSummary(rec) {
  const c = {};
  (rec.steps || []).forEach((st) => { c[st.state] = (c[st.state] || 0) + 1; });
  const bits = ['done', 'submitted', 'requested', 'failed', 'skipped'].filter((k) => c[k]).map((k) => `${c[k]} ${k}`);
  return `commit ${String(rec.id || '').slice(0, 8)} ${rec.state}: ${bits.join(' · ')}`;
}

async function loadCommitPanel(el, slug, me, redraw, declared = true) {
  const host = el.querySelector('[data-scope-commit]');
  if (!host) return;
  host.innerHTML = '<div data-scope-commit-loading class="text-provenance text-ink-muted">Reading what the commit would do (this reads Egeria and writes nothing)…</div>';
  let preview;
  try {
    preview = await getCatalogueCommitPreview(slug);
    if (!preview || !preview.manifest) throw new Error('the server answered with something that is not a commit preview');
  } catch (err) {
    if (stale(host, slug)) return;
    host.innerHTML = `<div data-scope-commit-error class="text-caveat text-state-warn">The commit preview could not be read: ${esc(err.message)}. The commit stays disabled until it can be.</div>`;
    return;
  }
  if (stale(host, slug)) return;
  host.innerHTML = commitPanelHtml(preview, me, commitUi && commitUi.slug === slug ? commitUi : null, declared);
  const say = (msg, warn = false) => {
    const e = host.querySelector('[data-scope-commit-status]');
    if (!e) return;
    e.textContent = msg;
    e.className = `mt-s1 text-provenance ${warn ? 'text-state-warn' : 'text-ink-muted'}`;
  };
  const fail = (err, what) => (err.status === 401 ? signInReason : `${what} failed: ${err.message}`);
  const paintSteps = () => {
    const old = host.querySelector('[data-scope-commit-steps]');
    const html = commitStepsHtml(commitUi && commitUi.rec);
    if (old) old.outerHTML = html; else host.querySelector('[data-scope-commit-panel]').insertAdjacentHTML('beforeend', html);
  };
  const poll = async () => {
    if (stale(host, slug) || !commitUi || commitUi.slug !== slug) return;
    let rec;
    try { rec = await getCatalogueCommitRecord(slug, commitUi.id); } catch (err) { say(`could not read the commit record: ${err.message}`, true); return; }
    commitUi.rec = rec;
    paintSteps();
    if (rec.state === 'done' || rec.state === 'failed') {
      commitUi.polling = false;
      await redraw(commitSummary(rec));          // the tree and header re-read from the proof rows
      return;
    }
    setTimeout(poll, commitPollMs);
  };
  const btn = host.querySelector('[data-scope-commit-btn]');
  if (btn) btn.addEventListener('click', async () => {
    const refreshNow = host.querySelector('[data-scope-refresh-now]').checked;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'sending…';
    say('Queuing the commit…');
    let out;
    try { out = await postCatalogueCommit(slug, refreshNow); } catch (err) { btn.disabled = false; btn.textContent = label; say(fail(err, 'the commit'), true); return; }
    commitUi = { slug, id: out.curation.id, rec: out.curation, polling: true };
    btn.textContent = label;
    if (!host.querySelector('[data-scope-commit-sent]')) host.querySelector('[data-scope-commit-row]').insertAdjacentHTML('afterend', '<div data-scope-commit-sent class="mt-s1 text-caveat text-ink">sent · waiting for Egeria</div>');
    say(`queued: commit ${String(out.curation.id).slice(0, 8)} · run ${String(out.run_id || '').slice(0, 8)}`);
    paintSteps();
    setTimeout(poll, commitPollMs);
  });
  const rb = host.querySelector('[data-scope-read-back]');
  if (rb) rb.addEventListener('click', async () => {
    say('Reading Egeria…');
    let r;
    try { r = await postCatalogueReadBack(slug); } catch (err) { say(fail(err, 'the read'), true); return; }
    await redraw(`read back: ${r.catalogued || 0} catalogued · ${r.attached_waiting || 0} attached, waiting${r.read_failed ? ` · ${r.read_failed} read(s) failed` : ''}`);
  });
}

export async function renderCatalogueScope(el, slug, status = '', known = null) {
  if (!el) throw new Error('Catalogue scope host missing');
  if (openFor !== slug) { openSchemas.clear(); selected.clear(); selectedTables.clear(); filterText = ''; openFor = slug; sectionOpen = null; }
  let view;
  try {
    view = known || await getCatalogueScope(slug);
    if (!view || !Array.isArray(view.schemas)) throw new Error('the server answered with something that is not a scope');
  } catch (err) {
    if (stale(el, slug)) return;
    el.innerHTML = `<div data-scope-error class="text-caveat text-state-warn">The catalogue scope could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (stale(el, slug)) return;
  try {
    paintScope(el, slug, status, view);
  } catch (err) {
    // A throw while drawing must never leave a blank pane: say what broke and what to do.
    el.innerHTML = `<div data-scope-render-error role="alert" class="text-caveat text-state-warn">The catalog scope could not be drawn: ${esc(err && err.message ? err.message : String(err))}. Reload the page to try again; nothing you chose was lost.</div>`;
  }
}

/** Draws the scope pane from a view and wires it (synchronous; the commit preview loads after). */
function paintScope(el, slug, status, view) {
  const me = whoAmI();
  if (sectionOpen === null) sectionOpen = scopeStartsOpen(view, readScopePref(storage(), me, slug));
  el.innerHTML = scopeSectionHtml(view, me, status, sectionOpen);
  const fold = el.querySelector('[data-scope-collapse]');
  if (fold) fold.addEventListener('click', () => {
    sectionOpen = !sectionOpen;
    writeScopePref(storage(), me, slug, sectionOpen);   // best effort: the page works without storage
    const declared = !!(view.declared && view.declared.declared);
    const shown = sectionOpen || !declared;   // a stored collapse takes effect only once declared
    const body = el.querySelector('[data-scope-body]');
    if (body) body.hidden = !shown;
    // The same button is edited in place (focus stays on it); the words come from the view.
    fold.setAttribute('aria-expanded', shown ? 'true' : 'false');
    fold.title = shown ? 'Collapse to one line' : 'Show the whole scope';
    fold.querySelector('[aria-hidden]').textContent = shown ? '▾' : '▸';
    fold.querySelector('[data-scope-header-line]').textContent =
      shown ? scopeHeaderText(view) : scopeCollapsedText(view);
    // The preview READS Egeria, so it is read when the section is open and not before.
    if (shown && !el.querySelector('[data-scope-commit-panel], [data-scope-commit-loading]')) startCommitPanel();
  });
  const startCommitPanel = () => loadCommitPanel(el, slug, me, (msg) => renderCatalogueScope(el, slug, msg), !!(view.declared && view.declared.declared));
  const say = (msg, warn = false) => {
    const s = el.querySelector('[data-scope-status]');
    if (!s) return;
    s.textContent = msg;
    s.className = `mt-s1 text-provenance ${warn ? 'text-state-warn' : 'text-ink-muted'}`;
  };
  const failure = (err, what) => (err.status === 401 ? signInReason : `${what} failed: ${err.message}`);

  // After a write the words come from the re-read view, not from the click. The scope is read
  // ONCE here and handed to the redraw (it used to be read again by the redraw: two GETs a write).
  const afterWrite = async (write, what, verify, spent = false, rowKey = '') => {
    const rowEl = (k) => [...el.querySelectorAll('[data-scope-row]')].find((r) => r.dataset.scopeRow === k);
    const cell = rowKey && rowEl(rowKey) ? rowEl(rowKey).querySelector('[data-scope-choice-cell]') : null;
    if (cell) cell.insertAdjacentHTML('beforeend', '<div data-scope-saving class="text-provenance text-ink-muted">saving…</div>');
    try { await write(); } catch (err) {
      if (cell) cell.querySelectorAll('[data-scope-saving]').forEach((e) => e.remove());
      say(failure(err, what), true); return;
    }
    if (spent) { selected.clear(); selectedTables.clear(); }   // a finished bulk action spends the selection
    let again;
    try { again = await getCatalogueScope(slug); }
    catch (err) { say(`${what}: written, but the scope could not be re-read: ${err.message}`, true); return; }
    if (rowKey) {
      const [kind, rest] = [rowKey.split(':')[0], rowKey.slice(rowKey.indexOf(':') + 1)];
      const dot = rest.indexOf('.');
      const n = kind === 'table' ? find(again, rest.slice(0, dot), rest.slice(dot + 1)) : find(again, rest, '');
      const ex = n && n.explicit;
      savedNotes.set(rowKey, { by: ex ? ex.by : whoAmI(), at: ex ? md(ex.at) : md(new Date().toISOString()) });
      setTimeout(() => {
        savedNotes.delete(rowKey);
        const r = rowEl(rowKey);
        if (r) r.querySelectorAll('[data-scope-saved-note]').forEach((e) => e.remove());
      }, savedNoteMs);
    }
    await renderCatalogueScope(el, slug, verify(again) || '', again);
  };

  const offered = (view.schemas || []).map((x) => x.name);
  // keep only ticks that still name a row in this view
  [...selected].forEach((n) => { if (!offered.includes(n)) selected.delete(n); });
  [...selectedTables].forEach((k) => { const [sn, tn] = k.split('\t'); if (!find(view, sn, tn)) selectedTables.delete(k); });
  const treeHost = () => el.querySelector('[data-scope-tree]');
  const repaintBar = () => {
    const bar = el.querySelector('[data-scope-bulk]');
    if (bar) { bar.outerHTML = bulkBarHtml(view, me); bindBulk(); }
  };
  const syncChecks = () => {
    el.querySelectorAll('[data-scope-select]').forEach((b) => { b.checked = selected.has(b.dataset.scopeSelect); });
    el.querySelectorAll('[data-scope-select-table]').forEach((b) => {
      b.checked = selectedTables.has(tkey(b.dataset.scopeSelectSchema, b.dataset.scopeSelectTable));
    });
  };
  const redrawTree = () => {
    const host = treeHost();
    if (host) host.innerHTML = treeHtml(view, me);
    const c = el.querySelector('[data-scope-filter-count]');
    if (c) c.textContent = `showing ${treePlan(view).shown} of ${treePlan(view).total}`;
    bindTree();
    repaintBar();
  };
  /** The bulk bar and the row ticks are re-drawn from `selected`, never from the DOM. */
  const bindBulk = () => {
    const bar = el.querySelector('[data-scope-bulk]');
    if (!bar) return;
    const all = bar.querySelector('[data-scope-all-box]');
    if (all) {
      const vis = visibleRows(view);
      const nSel = vis.schemas.filter((x) => selected.has(x)).length
        + vis.tables.filter((t) => selectedTables.has(tkey(t.schema, t.table))).length;
      all.indeterminate = nSel > 0 && nSel < vis.schemas.length + vis.tables.length;
      all.addEventListener('change', () => {
        const v = visibleRows(view);
        if (all.checked) { v.schemas.forEach((n) => selected.add(n)); v.tables.forEach((t) => selectedTables.add(tkey(t.schema, t.table))); }
        else { v.schemas.forEach((n) => selected.delete(n)); v.tables.forEach((t) => selectedTables.delete(tkey(t.schema, t.table))); }
        syncChecks(); repaintBar();
      });
    }
    const clr = bar.querySelector('[data-scope-clear-selection]');
    if (clr) clr.addEventListener('click', () => {
      const v = visibleRows(view);
      v.schemas.forEach((n) => selected.delete(n));
      v.tables.forEach((t) => selectedTables.delete(tkey(t.schema, t.table)));
      syncChecks(); repaintBar();
    });
    bar.querySelectorAll('[data-scope-bulk-act]').forEach((b) => b.addEventListener('click', () => {
      const act = b.dataset.scopeBulkAct;
      runBulk(act === 'clear' ? '' : act, false);
    }));
    const every = bar.querySelector('[data-scope-catalogue-all]');
    if (every) every.addEventListener('click', () => runBulk('catalogue', true));
  };
  /** Bulk choice over the whole selection: the ticked schemas in one bulk write, then each ticked
   *  table through the per-table node route (each signed and recorded by the server), then ONE
   *  re-read; the sentence comes from that re-read. */
  const runBulk = (choice, everySchema) => {
    const names = everySchema ? offered.slice() : [...selected].filter((n) => offered.includes(n));
    const tabs = everySchema ? [] : [...selectedTables].map((k) => { const [sn, tn] = k.split('\t'); return { schema: sn, table: tn }; })
      .filter((t) => find(view, t.schema, t.table));
    if (!names.length && !tabs.length) { say('select at least one schema or table first', true); return; }
    const label = choice ? words(choice) : 'no choice';
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    afterWrite(async () => {
      if (names.length) await setCatalogueNodes(slug, names.map((n) => ({ schema: n })), choice, everySchema);
      for (const t of tabs) {
        if (choice) await setCatalogueNode(slug, t.schema, t.table, choice);
        else await clearCatalogueNode(slug, t.schema, t.table);
      }
    }, 'set the choices', (v) => {
      const mine = (n) => (n.explicit ? n.explicit.choice : '') === choice;
      const got = names.map((n) => find(v, n, '')).filter(Boolean);
      const ok = got.filter(mine);
      const tgot = tabs.map((t) => find(v, t.schema, t.table)).filter(Boolean);
      const tok = tgot.filter(mine);
      if (ok.length !== names.length || tok.length !== tabs.length) {
        const bits = [names.length ? `${ok.length} of ${plural(names.length, 'schema')}` : '', tabs.length ? `${tok.length} of ${plural(tabs.length, 'table')}` : ''].filter(Boolean).join(' and ');
        return `the write returned, but the re-read scope shows only ${bits} set to ${label}`;
      }
      const by = [...new Set([...ok, ...tok].map((n) => (n.explicit ? n.explicit.by : '')).filter(Boolean))];
      const differ = got.reduce((acc, n) => acc + (n.tables || []).filter((t) => t.differs_from_schema).length, 0);
      const tail = differ
        ? (differ === 1 ? ' · 1 table keeps its own choice and differs from its schema'
          : ` · ${differ} tables keep their own choice and differ from their schema`) : '';
      const what = [names.length ? plural(names.length, 'schema') : '', tabs.length ? plural(tabs.length, 'table') : ''].filter(Boolean).join(' and ');
      return choice
        ? `${what} now set to ${label} by ${by.join(', ')}${tail}`
        : `${what} now ${names.length + tabs.length === 1 ? 'has' : 'have'} no choice in the re-read scope${tail}`;
    }, true);
  };

  const bindTree = () => {
    const host = treeHost();
    if (!host) return;
    host.querySelectorAll('[data-scope-select]').forEach((box) => box.addEventListener('change', () => {
      if (box.checked) selected.add(box.dataset.scopeSelect); else selected.delete(box.dataset.scopeSelect);
      repaintBar();
    }));
    host.querySelectorAll('[data-scope-select-table]').forEach((box) => box.addEventListener('change', () => {
      const k = tkey(box.dataset.scopeSelectSchema, box.dataset.scopeSelectTable);
      if (box.checked) selectedTables.add(k); else selectedTables.delete(k);
      repaintBar();
    }));
    host.querySelectorAll('[data-scope-toggle]').forEach((b) => b.addEventListener('click', () => {
      const n = b.dataset.scopeToggle;
      if (openSchemas.has(n)) openSchemas.delete(n); else openSchemas.add(n);
      redrawTree();
    }));
    host.querySelectorAll('[data-scope-act]').forEach((b) => b.addEventListener('click', () => {
      const { scopeAct: act, scopeSchema: schema, scopeTable: table, scopeChoice: choice } = b.dataset;
      const label = table ? `${schema}.${table}` : schema;
      const rowKey = table ? `table:${schema}.${table}` : `schema:${schema}`;
      const check = (want) => (v) => {
        const n = find(v, schema, table);
        const got = n && n.explicit ? n.explicit.choice : '';
        return got === want
          ? `${label}: ${words(want) || 'no choice'} is in the re-read scope${want ? ` · set by ${n.explicit.by}` : ''}`
          : `the write returned, but the re-read scope shows ${got ? words(got) : 'no choice'} for ${label}`;
      };
      if (act === 'set') afterWrite(() => setCatalogueNode(slug, schema, table, choice), 'set the choice', check(choice), false, rowKey);
      else if (act === 'clear') afterWrite(() => clearCatalogueNode(slug, schema, table), 'clear the choice', check(''), false, rowKey);
      else if (act === 'confirm') {
        const want = (find(view, schema, table) || {}).proposal;
        afterWrite(() => confirmCatalogueNode(slug, schema, table), 'confirm the proposal', check(want ? want.choice : ''), false, rowKey);
      } else if (act === 'override') {
        const want = (find(view, schema, table) || {}).proposal;
        afterWrite(() => overrideCatalogueNode(slug, schema, table), 'override the proposal', check(want ? opposite(want.choice) : ''), false, rowKey);
      }
    }));
  };
  bindTree();
  bindBulk();
  // The filter redraws only the tree (not the page, not this box), a beat after the last keystroke.
  const fbox = el.querySelector('[data-scope-filter]');
  if (fbox) {
    let timer = null;
    fbox.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => { filterText = fbox.value; redrawTree(); }, FILTER_DEBOUNCE_MS);
    });
  }
  el.querySelectorAll('[data-scope-depth-radio]').forEach((r) => r.addEventListener('change', () => {
    const want = r.dataset.scopeDepthRadio;
    afterWrite(() => setCatalogueDepth(slug, want), 'choose the depth', (v) =>
      (v.depth && v.depth.value === want ? `depth is now ${(v.depth.options.find((o) => o.id === want) || {}).label}`
        : 'the write returned, but the re-read scope shows a different depth'));
  }));
  const again = el.querySelector('[data-scope-redeclare]');
  if (again) again.addEventListener('click', () => afterWrite(() => redeclareCatalogueScope(slug), 'declare the scope again',
    (v) => ((v.new_since || {}).text ? 'the declaration returned, but the re-read scope still shows new things' : 'declared again: nothing is new since now')));
  if (sectionOpen || !(view.declared && view.declared.declared)) startCommitPanel();
}
