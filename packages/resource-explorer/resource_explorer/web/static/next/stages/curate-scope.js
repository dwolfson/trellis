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
  postCatalogueCommit, getCatalogueCommitRecord, getCatalogueLatestCommit, postCatalogueReadBack,
} from '/static/re-api.js';
import { state, esc } from '/static/next/app.js';
import { glyphSpan } from '/static/next/glyphs.js';
import { savedLine } from '/static/next/format.js';
import {
  SOURCE_WORD, md, nodeSourceLine, scopeCollapsedText,
  readScopePref, writeScopePref, scopeStartsOpen,
} from '/static/next/stages/scope-sources.js';

const whoAmI = () =>
  (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
const words = (choice) => (choice === 'leave_out' ? 'leave out' : choice === 'catalogue' ? 'include' : '');
const opposite = (choice) => (choice === 'leave_out' ? 'catalogue' : 'leave_out');
const signInReason = 'sign in to change what gets cataloged: every choice needs an author';
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
/** Rows whose write is in flight (a second press on them is ignored) and rows flashing after a save. */
const pendingRows = new Set();
let bulkBusy = false;
const flashRows = new Set();
let flashMs = 1500;
export function setFlashMs(ms) { flashMs = ms; }
const rowKeyOf = (node) => (node.kind === 'schema' ? `schema:${node.name}` : `table:${node.schema}.${node.name}`);
/** A node is "lowered" (its whole row in muted ink) when it is not included: left out by the
 *  person, or deleted in Egeria. Nothing else lowers a row, and nothing but superseded text is struck. */
const isLowered = (node, commit) => {
  if (node.effective === 'leave_out') return true;
  const st = commit && (node.kind === 'schema' ? (commit.schemas || {})[node.name] : (commit.tables || {})[`${node.schema}.${node.name}`]);
  return !!(st && st.state === 'deleted');
};
/** A left-edge rule means "this row needs you": the survey disagrees with a choice, or Egeria failed. */
const needsYou = (node, commit) => {
  if (node.state === 'disagrees') return true;
  const st = commit && (node.kind === 'schema' ? (commit.schemas || {})[node.name] : (commit.tables || {})[`${node.schema}.${node.name}`]);
  return !!(st && st.state === 'failed');
};
export function setSavedNoteMs(ms) { savedNoteMs = ms; }
/** The last commit pressed on this pane, kept so its steps survive the re-draw that follows it. */
let commitUi = null;
/** How long between reads of a running commit's record (a test shortens it). */
let commitPollMs = 2000;
export function setCommitPollMs(ms) { commitPollMs = ms; }
/** What this page has read of the newest commit in the registry, once per database per page load. A reload or a second
 *  tab starts with none of this: it is read again, from the same rows. `resumeFor` is the slug it was read for. */
let resumed = null;
let resumeFor = null;
/** The one survey watch on this page: starting another stops the first. */
let pageWatchStop = null;
/** A finished commit is drawn in full for this long; after that it is one line with its steps behind a disclosure. */
const RESUME_FULL_HOURS = 24;
/** Forget which schemas were expanded or ticked (another database, or a fresh pane). */
export function resetScopeUi() { commitUi = null; resumed = null; resumeFor = null; if (pageWatchStop) { pageWatchStop(); pageWatchStop = null; } savedNotes.clear(); pendingRows.clear(); flashRows.clear(); bulkBusy = false; openSchemas.clear(); selected.clear(); selectedTables.clear(); filterText = ''; openFor = ''; sectionOpen = null; commitUi = null; }

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

/** The two-part selector under "Include in catalog?": the chosen segment filled in ink, the other
 *  outlined, "×" back to undecided. A segment is an answer, not a verb; "catalog" is on the commit
 *  button alone. Dimmed and disabled while the row's write is out. */
function setterButtons(node, me) {
  const busy = pendingRows.has(rowKeyOf(node));
  const off = !me || busy;
  const dis = me ? (busy ? 'disabled aria-busy="true"' : '') : `disabled title="${esc(signInReason)}"`;
  const sch = esc(node.kind === 'schema' ? node.name : node.schema);
  const tbl = node.kind === 'table' ? esc(node.name) : '';
  const own = node.explicit ? node.explicit.choice : '';
  const seg = (choice, label) => `<button type="button" data-scope-act="set" data-scope-choice="${choice}"
    data-scope-schema="${sch}" data-scope-table="${tbl}" ${dis} aria-pressed="${own === choice ? 'true' : 'false'}"
    class="${own === choice ? 'bg-ink text-paper border border-ink' : 'bg-transparent text-ink border border-rule-strong'} ${off ? 'opacity-60' : 'cursor-pointer'} px-[6px] py-[1px] text-provenance">${label}</button>`;
  const clear = node.explicit ? `<button type="button" data-scope-act="clear" data-scope-schema="${sch}" data-scope-table="${tbl}" ${dis}
    aria-label="clear the choice (undecided)" title="${node.state === 'disagrees' ? 'reconsider: back to undecided' : 'back to undecided'}"
    class="${off ? 'opacity-60' : 'cursor-pointer'} bg-transparent px-[4px] text-provenance text-ink-muted">×</button>` : '';
  return `<div data-scope-selector role="group" aria-label="Include in catalog?" class="inline-flex items-baseline gap-[2px]">${seg('catalogue', 'Include')}${seg('leave_out', 'Leave out')}${clear}</div>`;
}

function proposalControls(node, me) {
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const sch = esc(node.kind === 'schema' ? node.name : node.schema);
  const tbl = node.kind === 'table' ? esc(node.name) : '';
  const attrs = `data-scope-schema="${sch}" data-scope-table="${tbl}" ${dis}`;
  return `<button type="button" data-scope-act="confirm" ${attrs} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">confirm</button> ·
    <button type="button" data-scope-act="override" ${attrs} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">${esc(words(opposite(node.proposal.choice)))} instead</button>`;
}

/** The sentence one gesture away: a disclosure (touch) and the cell's title (hover). */
const moreHtml = (sentence) => (sentence
  ? ` <details data-scope-details class="inline text-provenance text-ink-muted"><summary class="inline cursor-pointer">details</summary> ${esc(sentence)}</details>` : '');
const tagHtml = (kind, text) => `<span data-scope-tag="${kind}" class="border border-rule-strong px-[4px] text-provenance text-ink">${esc(text)}</span>`;
const who = (by) => (by && by === whoAmI() ? 'you' : by);

/** The left-hand choice cell: the selector, then a cue under it in the same cell (a short word, the
 *  sentence behind "details"), tags for what differs or came from a rule, and, only for rows that need
 *  a person, a visible second line (a proposal's reason, a survey disagreement). */
export function choiceCellHtml(node, me, commit = null) {
  return choiceCellCore(node, me) + blockedMarkHtml(node, commit) + savedNoteHtml(node, commit);
}

/** ISSUE-117: Egeria archives a database's WHOLE tree when any part of it is archived, so a leave-out of a
 *  schema that is cataloged in Egeria sends nothing. The choice is kept; the row says so with a mark and a
 *  short word, the sentence on hover. (The server's preview names the same reason on the commit.) */
const ISSUE_117_TITLE = 'Egeria archives the whole database tree when any part of it is archived (ISSUE-117, archiveBeanInRepository) · choice kept, nothing sent';
const CATALOGED = ['catalogued', 'attached_waiting', 'queued', 'sent', 'failed'];
function blockedMarkHtml(node, commit) {
  if (node.kind !== 'schema' || node.effective !== 'leave_out') return '';
  const st = ((commit || {}).schemas || {})[node.name];
  if (!st || !CATALOGED.includes(st.state)) return '';
  return `<div data-scope-blocked class="text-provenance font-semibold text-ink" title="${esc(ISSUE_117_TITLE)}"><span aria-hidden="true">⛔</span> kept · not sent <details data-scope-details class="inline text-provenance text-ink-muted font-normal"><summary class="inline cursor-pointer">why</summary> ${esc(ISSUE_117_TITLE)}</details></div>`;
}

/** "saved · you · just now" in the cell that was pressed, for a few seconds; the full sentence rides
 *  in its title ("saved in Resource Explorer · who · when · not yet cataloged in Egeria"). */
function savedNoteHtml(node, commit) {
  const key = node.kind === 'schema' ? `schema:${node.name}` : `table:${node.schema}.${node.name}`;
  const n = savedNotes.get(key);
  if (!n) return '';
  const st = node.kind === 'schema' ? ((commit || {}).schemas || {})[node.name] : ((commit || {}).tables || {})[`${node.schema}.${node.name}`];
  const tail = !st || ['none', 'uncommitted', 'left_out'].includes(st.state) ? 'not yet cataloged in Egeria' : 'Egeria changes when you press Catalog';
  return `<div><span data-scope-saved-note title="saved in Resource Explorer · ${esc(n.by)} · ${esc(n.at)} · ${tail}" class="text-provenance text-ink-muted">saved · ${esc(who(n.by))} · just now</span></div>`;
}

function choiceCellCore(node, me) {
  const ex = node.explicit;
  const by = ex ? `${esc(ex.by)} ${esc(md(ex.at))}` : '';
  const who1 = ex ? `${esc(who(ex.by))} · ${esc(md(ex.at))}` : '';
  const sel = setterButtons(node, me);
  if (node.state === 'proposed' && node.proposal) {
    return `${sel}<div data-scope-state-word="proposed">${glyphSpan('proposal')}
      <span class="text-ink">proposed: <span class="font-semibold">${esc(words(node.proposal.choice))}</span></span>
      <span class="text-ink-muted"> · ${esc(node.proposal.reason)}</span></div>
      <div class="text-provenance">${proposalControls(node, me)}</div>`;
  }
  if (ex && node.state === 'confirmed') {
    return `${sel}<div data-scope-state-word="confirmed" class="text-provenance text-ink-muted">${who1} ${tagHtml('rule', ex.source && ex.source !== 'person' ? ex.source : 'confirmed')}${moreHtml(`${words(ex.choice)} · confirmed by ${by}${ex.reason ? ` · ${ex.reason}` : ''}`)}</div>`;
  }
  if (ex && node.state === 'overridden') {
    const o = node.overridden || {};
    return `${sel}<div data-scope-state-word="overridden" class="text-provenance text-ink-muted">${who1} ${tagHtml('rule', 'overridden')}${moreHtml(`${words(ex.choice)} · overridden by ${by}`)}</div>
      <div data-scope-struck class="text-provenance text-ink-muted line-through">proposed: ${esc(words(o.choice))} · ${esc(o.reason || '')}</div>`;
  }
  if (ex && node.state === 'disagrees') {
    const d = node.disagrees || {};
    const was = ex.action === 'override' ? 'Overridden' : 'Confirmed';
    const choiceWord = ex.action === 'override' ? words(ex.proposal_choice) : words(ex.choice);
    const verb = ex.action === 'override' ? `${was} (proposal: ${choiceWord})` : `${was} ${words(ex.choice)}`;
    return `${sel}<div data-scope-state-word="disagrees" class="text-provenance text-ink-muted">${who1}${moreHtml(`${words(ex.choice)} · set by ${by}`)}</div>
      <div data-scope-disagrees class="text-provenance text-ink">${glyphSpan('human')} survey now disagrees: ${esc(verb)} on ${esc(md(ex.at))}, when ${esc(d.words || '')} (survey of ${esc(md(d.survey_at))}). The choice has not changed.</div>`;
  }
  if (ex) {
    const differs = node.differs_from_schema ? ` ${tagHtml('differs', 'differs')}` : '';
    return `${sel}<div data-scope-state-word="chosen" class="text-provenance text-ink-muted">${who1}${differs}${moreHtml(`${words(ex.choice)} · set by ${by}${node.differs_from_schema ? ' · differs from its schema' : ''}`)}</div>`;
  }
  if (node.effective && node.effective_from === 'schema') {
    return `${sel}<div data-scope-state-word="inherited" class="text-provenance text-ink-muted">(schema)${moreHtml(`${words(node.effective)} · from its schema`)}</div>`;
  }
  const tail = node.kind === 'schema' && node.undecided_words
    ? ` · <span data-scope-undecided-words>${esc(node.undecided_words)}</span>` : '';
  return `${sel}<div data-scope-state-word="undecided" class="text-provenance text-ink-muted">undecided${tail}</div>`;
}

/** The "In Egeria" cell: the commit's derived state for this node, with its glyph and its
 *  second line. `commit` is `view.commit`; a server that predates it says "not read yet".
 *  A node with no state ('none') says nothing about Egeria rather than inventing a word. */
const EGERIA_GLYPH = {
  catalogued: 'catalogued', attached_waiting: 'attached_waiting', queued: 'queued', sent: 'queued',
  failed: 'catalogue_failed', archived: 'archived',
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
  const lowered = isLowered(node, commit);
  const edge = needsYou(node, commit);
  return `<div class="flex items-baseline gap-s2 border-b border-rule border-l-[3px] pl-[4px] py-[3px] text-caveat ${edge ? 'border-l-ink' : 'border-l-transparent'} ${lowered ? 'text-ink-muted opacity-70' : ''} ${flashRows.has(key) ? 'bg-paper-surface' : ''}" data-scope-row="${esc(key)}" data-scope-effective="${esc(node.effective || '')}"${lowered ? ' data-scope-lowered' : ''}>
    <div class="w-[2ch] shrink-0" data-scope-select-cell>${pick}</div>
    <div class="w-[24ch] shrink-0" data-scope-choice-cell ${pendingRows.has(key) ? 'aria-busy="true"' : ''}>${choiceCellHtml(node, me, commit)}</div>
    <div class="min-w-[14ch] flex-1 break-words ${lowered ? 'text-ink-muted' : 'text-ink'}" data-scope-name-cell><span data-scope-bullet aria-hidden="true" class="text-ink-muted">${isSchema ? '▪' : '·'}</span> ${toggle}<span class="${isSchema ? 'font-mono font-semibold' : 'font-mono'}">${esc(node.name)}</span>${nameTail}${src}</div>
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
    <div class="w-[2ch] shrink-0"></div><div class="w-[24ch] shrink-0"></div>
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
    <div class="w-[2ch] shrink-0"></div><div class="w-[24ch] shrink-0 break-words" data-scope-choice-head>Include in catalog?</div><div class="min-w-[14ch] flex-1 break-words">Schema / table</div>
    <div class="w-[8ch] shrink-0 break-words text-right" title="Row count; the source and date ride on each cell">Rows</div>
    <div class="w-[8ch] shrink-0 break-words text-right" title="Size on disk; the source and date ride on each cell">Size</div>
    <div class="w-[14ch] shrink-0 break-words" data-scope-activity-head title="Activity: dormant means 0 writes in at least ${esc(String(view.dormancy_days || 90))} days of counter evidence">Activity</div>
    <div class="w-[14ch] shrink-0 break-words" data-scope-classes-head title="Data classes found in the columns">Classification</div>
    <div class="w-[18ch] shrink-0 break-words" data-scope-state-head title="State in Egeria">In Egeria</div></div>`;
  const plan = treePlan(view);
  const body = plan.rows.map(({ s, tables: shownTables, open }) => {
    const tables = open ? shownTables.map((t) => `<div class="ml-s3">${rowHtml(t, me, 1, TABLE_KIND[t.table_type] || 'table', view.commit)}${columnRowsHtml(t)}</div>`).join('')
      || '<div class="ml-s3 text-caveat text-ink-muted">No tables.</div>' : '';
    return `<div data-scope-schema-block="${esc(s.name)}" class="mt-[2px] border-t border-rule-strong">${rowHtml(s, me, 0, '', view.commit, open)}${tables}</div>`;
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
    ${bulk('catalogue', 'include selected')} · ${bulk('leave_out', 'leave out selected')} · ${bulk('clear', 'clear choice')}
    <span class="text-ink-muted">|</span>
    <button type="button" data-scope-catalogue-all ${dis} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">include all ${n} schemas</button></div>`;
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
  const element = el.short ? `reads Egeria element <span class="font-mono">${esc(el.short)}</span>…` : esc(el.text || 'not cataloged in Egeria');
  const ns = view.new_since || {};
  const dis = me ? '' : `disabled title="${esc(signInReason)}"`;
  const nsLine = ns.text
    ? `<div data-scope-new-since class="mb-s1 text-caveat text-ink">${esc(ns.text)}
        · <button type="button" data-scope-redeclare ${dis} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">Start a new baseline</button>
        <span class="text-provenance text-ink-muted">it saves where things stand now, so new things are counted from today; it does not change your choices</span></div>` : '';
  const declared = !!(view.declared && view.declared.declared);
  open = open || !declared;   // nothing to collapse to until a scope is declared
  const line = open ? scopeHeaderText(view) : scopeCollapsedText(view);
  // The marker under the header is the commit's state, derived by the server from proof rows;
  // the "not yet cataloged" words exist only server-side, and only while no commit has left a row.
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
    ${(view.schemas || []).length ? `<div data-scope-legend class="mb-s1 text-provenance text-ink-muted">filled = your choice · lowered row = not included · bordered tag = differs or from a rule</div>` : ''}
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

/** Two-word labels, one per step: a person scans these top to bottom. */
const STEP_LABEL = {
  publish_elements: 'Publish elements', zone_membership: 'Zone membership',
  owner: 'Set owner', schema_targets: 'Attach schemas', leave_outs: 'Leave outs',
  survey_report: 'Survey report', survey: 'Egeria survey', refresh: 'Refresh cataloger',
  read_back: 'Read back',
};
const STEP_GLYPH = { done: 'catalogued', failed: 'catalogue_failed', running: 'queued', pending: 'queued', submitted: 'queued', requested: 'queued' };

/** Egeria's long tail (the `* Context:` block) folded under "details": the row reads its first sentence. */
const detailsHtml = (more, attr) => (more
  ? ` <details ${attr} class="inline text-provenance text-ink-muted"><summary class="inline cursor-pointer">details</summary><div class="whitespace-pre-wrap break-words">${esc(more)}</div></details>` : '');

/** How long a real database survey takes (measured on coco_pharma: 15 min for 2 schemas, 22 min for 3). */
const SURVEY_TYPICAL = 'usually takes about 15-25 minutes';
/** How often the open page reads the survey's status again (a read-back, never a write). */
const SURVEY_CHECK_S = 60;
const hm = (iso) => { const m = /T(\d\d:\d\d)/.exec(String(iso || '')); return m ? m[1] : ''; };
const nowMs = () => scopeClock.now();
const scopeClock = {
  now: () => Date.now(),
  every: (fn, ms) => { const id = setInterval(fn, ms); if (id && id.unref) id.unref(); return () => clearInterval(id); },   // unref: a Node test run is never held open by it
};
/** A test swaps the clock (and so the 60 s interval and the elapsed minutes) for a fake. */
export function setScopeClock(c) { Object.assign(scopeClock, c); }

/** The step now being worked on: the one running, else the first still waiting or submitted. */
const currentStep = (rec) => {
  const steps = rec.steps || [];
  return steps.find((st) => st.state === 'running') || steps.find((st) => ['pending', 'submitted', 'requested'].includes(st.state)) || null;
};

/** The survey step while it runs in Egeria: elapsed time (ticking), annotations so far, the usual
 *  duration, a "check again" control and the stated interval. No spinner. */
function surveyRunningHtml(rec, st) {
  const since = Date.parse(rec.requested_at || '');
  const mins = Number.isFinite(since) ? Math.max(0, Math.floor((nowMs() - since) / 60000)) : null;
  const so = /(\d+) annotations so far/.exec(st.detail || '');
  const started = hm(rec.requested_at) || ((/^submitted · \S+ (\S+)/.exec(st.detail || '') || [])[1] || '');
  const bits = ['running in Egeria', started ? `started ${started}` : '', mins != null ? `<span data-scope-survey-elapsed>${mins} min</span>` : '',
    so ? `${so[1]} annotations so far` : ''].filter(Boolean).join(' · ');
  return `<div data-scope-step-hint class="text-provenance text-ink">${bits} · ${SURVEY_TYPICAL}: come back and press Read Egeria again
    · <button type="button" data-scope-check-again class="cursor-pointer bg-transparent p-0 text-accent-ink underline">check again</button>
    · <span data-scope-checking-every>checking every ${SURVEY_CHECK_S} s</span></div>`;
}

/** The steps of the curation record as a numbered list: one line each (number, glyph, two-word label,
 *  state word); the running step in normal weight and the rest muted; a failed step gets a left-edge
 *  rule and its first sentence at once; every other sentence is behind "details". The state words and
 *  details are the record's, which the server writes from rows, never a guess. */
export function commitStepsHtml(rec) {
  if (!rec) return '';
  const steps = rec.steps || [];
  const cur = currentStep(rec);
  const nFailed = steps.filter((st) => st.state === 'failed').length;
  const idx = cur ? steps.indexOf(cur) + 1 : steps.length;
  const head = cur
    ? `Catalog · commit ${esc(String(rec.id || '').slice(0, 8))} · step ${idx} of ${steps.length} · running: ${esc(STEP_LABEL[cur.name] || cur.name)} · ${nFailed} failed`
    : `Catalog · commit ${esc(String(rec.id || '').slice(0, 8))} · ${steps.length} of ${steps.length} steps · ${esc(rec.state || '')} · ${nFailed} failed`;
  // The step line already says its state; a detail that starts with the same word would say it twice.
  const bare = (st) => String(st.detail || '').replace(new RegExp(`^${String(st.state).replace(/[^a-z_]/gi, '')} · `, 'i'), '');
  const rows = steps.map((st, i) => {
    const failed = st.state === 'failed';
    const running = st === cur;
    const first = failed ? ` <span data-scope-step-first>${esc(bare(st))}</span>` : (bare(st) ? moreHtml(bare(st)) : '');
    const hint = running && st.name === 'survey' && st.state === 'submitted' ? surveyRunningHtml(rec, st) : '';
    return `<li data-scope-commit-step="${esc(st.name)}" data-state="${esc(st.state)}" class="${failed ? 'border-l-[3px] border-l-ink pl-[4px] text-ink' : running ? 'text-ink' : 'text-ink-muted'} text-provenance">
      <span class="tnum">${i + 1}.</span> ${STEP_GLYPH[st.state] ? `${glyphSpan(STEP_GLYPH[st.state])} ` : ''}${esc(STEP_LABEL[st.name] || st.name)} · ${esc(st.state)}${first}${detailsHtml(st.more, 'data-scope-step-details')}${hint}</li>`;
  }).join('');
  return `<div data-scope-commit-steps class="mt-s1"><div data-scope-steps-head class="text-caveat text-ink">${head}</div><ol class="list-none pl-0">${rows}</ol></div>`;
}

/** The manifest as a short table, one row per mechanism: what, how many, when. The long sentences
 *  sit behind "details" on the row they qualify. */
function manifestTableHtml(preview, view) {
  const m = preview.manifest || {};
  const line = (id) => (m.lines || []).find((l) => l.id === id);
  const detail = (...ids) => ids.map((id) => { const l = line(id); return l ? `<span data-scope-manifest-line="${esc(id)}" class="block">${l.mechanism ? `${l.mechanism}. ` : ''}${esc(l.text)}</span>` : ''; }).join('');
  const attach = preview.attach || [];
  const leave = preview.leave_out || [];
  const c = (view && view.counts) || {};
  const names = (xs) => (xs.length ? ` · ${xs.slice(0, 4).map(esc).join(', ')}${xs.length > 4 ? ` +${xs.length - 4}` : ''}` : '');
  const forms = (r) => (r.form === 'soft_delete' ? 'will delete' : r.form === 'archive' ? 'will archive' : r.form === 'cannot_check' ? 'not committed' : r.form === 'in_use' ? 'not committed' : 'nothing to change');
  const row = (id, who, what, howMany, when, more = '') => `<div role="row" data-scope-manifest-row="${id}" class="flex items-baseline gap-s2 text-ink">
    <div role="cell" class="w-[14ch] shrink-0 font-semibold">${who}</div>
    <div role="cell" class="min-w-[18ch] flex-1">${what}${more ? ` <details data-scope-details class="inline text-provenance text-ink-muted"><summary class="inline cursor-pointer">details</summary>${more}</details>` : ''}</div>
    <div role="cell" class="w-[24ch] shrink-0 tnum">${howMany}</div><div role="cell" class="w-[22ch] shrink-0 text-ink-muted">${when}</div></div>`;
  const leaveHow = leave.length ? `${leave.length}${names(leave.map((r) => r.schema))} · ${[...new Set(leave.map(forms))].join(', ')}` : '0';
  return `<div data-scope-manifest role="table" aria-label="What this commit does" class="text-caveat">
    <div role="row" class="flex items-baseline gap-s2 text-provenance text-ink-muted"><div role="columnheader" class="w-[14ch] shrink-0"></div><div role="columnheader" class="min-w-[18ch] flex-1">what</div><div role="columnheader" class="w-[24ch] shrink-0">how many</div><div role="columnheader" class="w-[22ch] shrink-0">when</div></div>
    ${row('publishes', 'RE publishes', 'the server and database', '2 elements', 'now', detail('re_publishes', 'survey_report_whole'))}
    ${row('catalogs', 'Egeria catalogs', 'your included schemas', `${attach.length}${names(attach)}`, 'next refresh (or now, if ticked)', detail('cataloguer_creates', 'whole_schemas'))}
    ${row('surveys', 'Egeria surveys', 'the same schemas', `${((preview.survey || {}).schemas || []).length}`, 'after attach', detail('survey_measures'))}
    ${row('left_out', 'Left out', leave.length ? 'what changes in Egeria' : 'nothing in Egeria to change', leaveHow, leave.length ? 'at this commit' : '—')}
    ${row('undecided', 'Undecided', 'Egeria stays as it is', `${c.schemas_undecided ?? 0}`, '—')}
  </div>`;
}

/** How a commit read from the registry is shown on load: `full` (its steps, and a watch while it runs) when it is not
 *  finished or finished within 24 h; `one_line` (a summary and "show steps") when it is older; `unfinished` when it was
 *  requested hours ago and never finished (said, not watched). */
export function resumeMode(latest) {
  // Anything that is not a commit record (an id and its steps) is no commit: the page must never follow a shape it does not know.
  if (!latest || !latest.commit || !latest.commit.id || !Array.isArray(latest.commit.steps)) return 'none';
  if (!latest.terminal) return latest.stale_unfinished ? 'unfinished' : 'full';
  return latest.age_hours != null && latest.age_hours > RESUME_FULL_HOURS ? 'one_line' : 'full';
}

/** `last commit <id> · <when> · <outcome>`, with the steps behind a disclosure, never the list by default. */
export function lastCommitHtml(latest) {
  const rec = latest.commit;
  const when = String(rec.finished_at || rec.requested_at || '');
  const nFailed = (rec.steps || []).filter((st) => st.state === 'failed').length;
  const outcome = !latest.terminal ? 'did not finish'
    : rec.state === 'failed' ? `failed${nFailed ? ` · ${nFailed} step${nFailed === 1 ? '' : 's'} failed` : ''}` : esc(rec.state || 'done');
  return `<div data-scope-last-commit class="mt-s1 text-provenance text-ink-muted">
    <span data-scope-last-commit-line>last commit ${esc(String(rec.id || '').slice(0, 8))} · ${esc(`${md(when)} ${hm(when)}`.trim())} · ${outcome}</span>
    <details class="inline"><summary class="inline cursor-pointer text-accent-ink underline">show steps</summary>${commitStepsHtml(rec)}</details></div>`;
}

/** What pressing Catalog would do: the manifest table with the button at its top right, anything that
 *  blocks it listed directly under the button, the refresh box under that. */
export function commitPanelHtml(preview, me, ui, declared = true, view = null) {
  const dis = (why) => `disabled title="${esc(why)}"`;
  const reason = !me ? signInReason : commitWhyNot(preview, declared);
  const refused = (preview.refused || []).map((r) => `<div data-scope-refused="${esc(r.schema)}" class="text-ink">${glyphSpan('human')} ${esc(r.text)}</div>`).join('');
  const collisions = (preview.collisions || []).map((c) => `<div data-scope-collision-line class="text-right text-ink">${esc(c.text)}</div>`).join('');
  const leave = (preview.leave_out || []).map((r) => `<div data-scope-leave-out="${esc(r.schema)}" data-form="${esc(r.form)}" class="${r.blocked ? 'text-ink' : 'text-ink-muted'}">${r.blocked ? `${glyphSpan('human')} ` : ''}${esc(r.text)}</div>`).join('');
  const blockers = (preview.blockers || []).map((b) => `<div data-scope-blocker class="text-ink">${glyphSpan('human')} ${esc(b)}</div>`).join('');
  const off = !!reason;
  const sent = ui && ui.polling ? '<div data-scope-commit-sent class="mt-s1 text-caveat text-ink">sent · waiting for Egeria</div>' : '';
  return `<div data-scope-commit-panel>
    <div class="mb-s1 text-answer text-ink">What this commit does</div>
    <div class="flex flex-wrap items-start justify-between gap-s3">
      <div class="min-w-0 flex-1">${manifestTableHtml(preview, view)}${refused}${leave}</div>
      <div data-scope-commit-row class="flex shrink-0 flex-col items-end gap-s1">
        <button type="button" data-scope-commit-btn ${off ? dis(reason) : ''} class="rounded-sm border border-accent bg-accent px-s3 py-[6px] text-resource font-semibold text-chrome ${off ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}">${esc(preview.button || 'Catalog')}</button>
        ${off ? `<span data-scope-commit-why class="text-right text-caveat text-ink">⚠ ${esc(reason)}</span>` : ''}
        ${collisions}${blockers}
        <label class="flex cursor-pointer items-baseline gap-[4px] text-caveat text-ink"><input type="checkbox" data-scope-refresh-now checked ${me ? '' : 'disabled'}> refresh Egeria's cataloger now (about 16 s; RE never restarts a connector)</label>
      </div>
    </div>
    ${sent}
    ${commitStepsHtml(ui && ui.rec)}
    ${ui && ui.last ? lastCommitHtml(ui.last) : ''}
    <div class="mt-s1 text-caveat"><button type="button" data-scope-read-back ${me ? '' : dis(signInReason)} class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">Read Egeria again</button></div>
    <div data-scope-commit-status class="mt-s1 text-provenance text-ink-muted"></div>
  </div>`;
}

/** Why the commit button is off, in the words a person needs ('' when it is on). */
export function commitWhyNot(preview, declared = true) {
  if (!declared) return 'no scope declared: choose what to include first';
  if (preview.can_commit) return '';
  const first = (preview.blockers || [])[0] || '';
  if (/^nothing to commit/.test(first)) return 'nothing chosen: include at least one schema';
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

/** What changed in a record's steps: one string per step state, so a poll can tell. */
const stepSig = (rec) => (rec && rec.steps ? rec.steps.map((st) => `${st.name}=${st.state}`).join('|') : '');
const surveyOpen = (rec) => !!(rec && (rec.steps || []).some((st) => st.name === 'survey' && st.state === 'submitted'));

async function loadCommitPanel(el, slug, me, redraw, declared = true, refreshScope = null, getView = () => null) {
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
  // A reload or a second tab: nothing of the commit this page was watching survives in the tab, so the newest commit
  // was read from the registry (renderCatalogueScope) and is shown from its rows. Never a write.
  let resumedPoll = false;
  if ((!commitUi || commitUi.slug !== slug) && resumed && resumed.slug === slug && resumeMode(resumed.latest) !== 'none') {
    const latest = resumed.latest;
    const mode = resumeMode(latest);
    const rec = latest.commit;
    if (mode === 'full') {
      commitUi = { slug, id: rec.id, rec, polling: !latest.terminal, sig: stepSig(rec), resumed: true };
      resumedPoll = !latest.terminal;
    } else {
      commitUi = { slug, id: rec.id, rec: null, polling: false, sig: stepSig(rec), last: latest, resumed: true };
    }
  }
  host.innerHTML = commitPanelHtml(preview, me, commitUi && commitUi.slug === slug ? commitUi : null, declared, getView());
  const say = (msg, warn = false) => {
    const e = host.querySelector('[data-scope-commit-status]');
    if (!e) return;
    e.textContent = msg;
    e.className = `mt-s1 text-provenance ${warn ? 'text-state-warn' : 'text-ink-muted'}`;
  };
  const expiredHtml = ' <button type="button" data-scope-sign-in class="cursor-pointer bg-transparent p-0 text-accent-ink underline">sign in</button>';
  const fail = (err, what) => (err.status === 401 ? 'your session expired · sign in again' : `${what} failed: ${err.message}`);
  const offerSignIn = (err) => {
    if (err.status !== 401) return;
    const e = host.querySelector('[data-scope-commit-status]');
    if (!e) return;
    e.insertAdjacentHTML('beforeend', expiredHtml);
    e.querySelector('[data-scope-sign-in]').addEventListener('click', () => {
      try { if (globalThis.Auth && globalThis.Auth.showLogin) globalThis.Auth.showLogin('Your session has expired. Please sign in again.'); } catch { /* the line above already says so */ }
    });
  };
  const paintSteps = () => {
    const old = host.querySelector('[data-scope-commit-steps]');
    const html = commitStepsHtml(commitUi && commitUi.rec);
    if (old) old.outerHTML = html; else host.querySelector('[data-scope-commit-panel]').insertAdjacentHTML('beforeend', html);
    bindCheckAgain();
  };
  /** A page must never show a row older than a step it shows: whenever a step changes state the scope
   *  is read again and the tree redrawn (one read per change, not per tick). */
  const onSteps = async (rec) => {
    const sig = stepSig(rec);
    if (commitUi && commitUi.sig !== sig) {
      commitUi.sig = sig;
      if (refreshScope) await refreshScope();
    }
  };
  // The survey runs for minutes in Egeria. While it is open the page reads its status again at a
  // stated interval: a read-back (never a write), one in flight at most, stopped when the survey
  // reaches an end, the page is hidden, or the pane goes away.
  let stopWatch = null;
  let inFlight = false;
  const checkSurvey = async (manual = false) => {
    if (inFlight || stale(host, slug) || !commitUi || commitUi.slug !== slug) return;
    if (!manual && globalThis.document && globalThis.document.hidden) return;
    inFlight = true;
    try {
      await postCatalogueReadBack(slug);
      const rec = await getCatalogueCommitRecord(slug, commitUi.id);
      commitUi.rec = rec;
      paintSteps();
      await onSteps(rec);
      if (!surveyOpen(rec) && stopWatch) { stopWatch(); stopWatch = null; }
    } catch (err) {
      say(`could not read how the survey is going: ${err.message}`, true);
      offerSignIn(err);
    } finally { inFlight = false; }
  };
  function bindCheckAgain() {
    host.querySelectorAll('[data-scope-check-again]').forEach((b) => b.addEventListener('click', () => checkSurvey(true)));
    const el1 = host.querySelector('[data-scope-survey-elapsed]');
    if (surveyOpen(commitUi && commitUi.rec) && !stopWatch) {
      const stopMin = scopeClock.every(() => {
        if (stale(host, slug) || !surveyOpen(commitUi && commitUi.rec)) { stopMin(); return; }
        const e = host.querySelector('[data-scope-survey-elapsed]');
        const since = Date.parse((commitUi.rec || {}).requested_at || '');
        if (e && Number.isFinite(since)) e.textContent = `${Math.max(0, Math.floor((nowMs() - since) / 60000))} min`;
      }, 30000);
      const stopPoll = scopeClock.every(() => {
        if (stale(host, slug) || !surveyOpen(commitUi && commitUi.rec)) { stopWatch && stopWatch(); stopWatch = null; return; }
        checkSurvey(false);
      }, SURVEY_CHECK_S * 1000);
      const mine = () => { stopMin(); stopPoll(); };
      if (pageWatchStop) pageWatchStop();               // never more than one watch on a page
      pageWatchStop = mine;
      stopWatch = () => { mine(); if (pageWatchStop === mine) pageWatchStop = null; };
    }
    void el1;
  }
  bindCheckAgain();
  const poll = async () => {
    if (stale(host, slug) || !commitUi || commitUi.slug !== slug) return;
    let rec;
    try { rec = await getCatalogueCommitRecord(slug, commitUi.id); } catch (err) { say(`could not read the commit record: ${err.message}`, true); offerSignIn(err); return; }
    commitUi.rec = rec;
    paintSteps();
    if (rec.state === 'done' || rec.state === 'failed') {
      commitUi.polling = false;
      commitUi.sig = stepSig(rec);
      await redraw(commitSummary(rec));          // the tree and header re-read from the proof rows
      return;
    }
    await onSteps(rec);
    setTimeout(poll, commitPollMs);
  };
  if (resumedPoll) setTimeout(poll, commitPollMs);        // a commit still running: follow it to its end
  const btn = host.querySelector('[data-scope-commit-btn]');
  if (btn) btn.addEventListener('click', async () => {
    const refreshNow = host.querySelector('[data-scope-refresh-now]').checked;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'sending…';
    say('Queuing the commit…');
    let out;
    try { out = await postCatalogueCommit(slug, refreshNow); } catch (err) {
      btn.disabled = false; btn.textContent = label; say(fail(err, 'the commit'), true); offerSignIn(err);
      if (err.status === 401) {
        const why = host.querySelector('[data-scope-commit-why]');
        if (!why) btn.insertAdjacentHTML('afterend', '<span data-scope-commit-why class="text-right text-caveat text-ink">⚠ your session expired · sign in again</span>');
      }
      return;
    }
    commitUi = { slug, id: out.curation.id, rec: out.curation, polling: true, sig: stepSig(out.curation) };
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
    try { r = await postCatalogueReadBack(slug); } catch (err) { say(fail(err, 'the read'), true); offerSignIn(err); return; }
    await redraw(`read back: ${r.catalogued || 0} cataloged · ${r.attached_waiting || 0} attached, waiting${r.read_failed ? ` · ${r.read_failed} read(s) failed` : ''}`);
  });
}

export async function renderCatalogueScope(el, slug, status = '', known = null) {
  if (!el) throw new Error('Catalog scope host missing');
  if (openFor !== slug) { openSchemas.clear(); selected.clear(); selectedTables.clear(); filterText = ''; openFor = slug; sectionOpen = null; }
  let view;
  try {
    view = known || await getCatalogueScope(slug);
    if (!view || !Array.isArray(view.schemas)) throw new Error('the server answered with something that is not a scope');
  } catch (err) {
    if (stale(el, slug)) return;
    el.innerHTML = `<div data-scope-error class="text-caveat text-state-warn">The catalog scope could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (stale(el, slug)) return;
  if (resumeFor !== slug && (!commitUi || commitUi.slug !== slug)) {
    resumeFor = slug;
    try { resumed = { slug, latest: await getCatalogueLatestCommit(slug) }; } catch { resumed = null; }   // the page works without it
    if (stale(el, slug)) return;
  }
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
  // A commit still running (or just finished) is what a reload must put in front of the person: open the section for it.
  if (!sectionOpen && resumed && resumed.slug === slug && resumeMode(resumed.latest) === 'full') sectionOpen = true;
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
  // Re-read the scope (one GET) and redraw the tree and the markers in place: used whenever a commit
  // step changes state, so no row shows a state older than a step on the same page.
  const refreshScope = async () => {
    let v;
    try { v = await getCatalogueScope(slug); } catch { return; }
    if (stale(el, slug) || !v || !Array.isArray(v.schemas)) return;
    view = v;
    redrawTree();
    const mk = el.querySelector('[data-scope-commit-header]');
    if (mk) { mk.textContent = commitHeaderText(v); mk.dataset.scopeCommitHeaderState = ((v.commit || {}).header || {}).state || 'unknown'; }
  };
  const startCommitPanel = () => loadCommitPanel(el, slug, me, (msg) => renderCatalogueScope(el, slug, msg),
    !!(view.declared && view.declared.declared), refreshScope, () => view);
  const say = (msg, warn = false) => {
    const s = el.querySelector('[data-scope-status]');
    if (!s) return;
    s.textContent = msg;
    s.className = `mt-s1 text-provenance ${warn ? 'text-state-warn' : 'text-ink-muted'}`;
  };
  const failure = (err, what) => (err.status === 401 ? signInReason : `${what} failed: ${err.message}`);

  const rowEl = (k) => [...el.querySelectorAll('[data-scope-row]')].find((r) => r.dataset.scopeRow === k);
  const nodeFor = (k) => {
    const rest = k.slice(k.indexOf(':') + 1);
    if (k.startsWith('table:')) { const d = rest.indexOf('.'); return find(view, rest.slice(0, d), rest.slice(d + 1)); }
    return find(view, rest, '');
  };
  /** What a node would look like with `want` chosen (or cleared, ''): the row shows it the moment the
   *  button is pressed, before the server has answered; a failed write puts the old state back. */
  const guess = (node, want) => {
    if (want) {
      return { ...node, explicit: { choice: want, by: whoAmI(), at: new Date().toISOString(), action: 'set', source: 'person', reason: '' },
        effective: want, effective_from: 'self', state: 'chosen', proposal: null, overridden: null, disagrees: null };
    }
    const parent = node.kind === 'table' ? (find(view, node.schema, '') || {}).effective || null : null;
    return { ...node, explicit: null, effective: parent, effective_from: parent ? 'schema' : null, state: 'undecided', proposal: null, overridden: null, disagrees: null };
  };
  const paintRow = (k, node) => {
    const r = rowEl(k);
    if (!r) return;
    const low = isLowered(node, view.commit);
    ['text-ink-muted', 'opacity-70'].forEach((c) => r.classList.toggle(c, low));
    r.toggleAttribute('data-scope-lowered', low);
    r.dataset.scopeEffective = node.effective || '';
    const nm = r.querySelector('[data-scope-name-cell]');
    if (nm) { nm.classList.toggle('text-ink-muted', low); nm.classList.toggle('text-ink', !low); }
    const cell = r.querySelector('[data-scope-choice-cell]');
    if (cell) {
      if (pendingRows.has(k)) cell.setAttribute('aria-busy', 'true'); else cell.removeAttribute('aria-busy');
      cell.innerHTML = choiceCellHtml(node, me, view.commit);
    }
  };
  const signIn = () => { try { if (globalThis.Auth && globalThis.Auth.showLogin) globalThis.Auth.showLogin('Your session has expired. Please sign in again.'); } catch { /* the page still says so */ } };
  const EXPIRED = 'your session expired · sign in again';
  // After a write the words come from the re-read view, not from the click. The scope is read
  // ONCE here and handed to the redraw (it used to be read again by the redraw: two GETs a write).
  // `rowKey` names the one row the press was on: it changes at once, is ignored if pressed again
  // while its write is out, flashes briefly when the server has taken it, and is rolled back with
  // "not saved" when it has not.
  const afterWrite = async (write, what, verify, spent = false, rowKey = '', want = null) => {
    let before = null;
    if (rowKey) {
      if (pendingRows.has(rowKey)) return;                 // already out: a second press is ignored
      const node = nodeFor(rowKey);
      const r = rowEl(rowKey);
      pendingRows.add(rowKey);
      if (node && r && want !== null) {
        const cell = r.querySelector('[data-scope-choice-cell]');
        before = { cell: cell ? cell.innerHTML : '', cls: r.className, eff: r.dataset.scopeEffective, node };
        paintRow(rowKey, guess(node, want));
        const c2 = r.querySelector('[data-scope-choice-cell]');
        if (c2) c2.insertAdjacentHTML('beforeend', '<div data-scope-saving class="text-provenance text-ink-muted">saving…</div>');
      }
    }
    const release = () => { if (rowKey) pendingRows.delete(rowKey); };
    try { await write(); } catch (err) {
      release();
      const expired = err.status === 401;
      const again = () => afterWrite(write, what, verify, spent, rowKey, want);   // "save again" re-sends the same choice
      if (before) {
        const r = rowEl(rowKey);
        if (r) {
          paintRow(rowKey, before.node);
          r.querySelector('[data-scope-choice-cell]').insertAdjacentHTML('beforeend',
            `<div data-scope-not-saved class="text-provenance font-semibold text-ink">✕ ${expired ? `unsaved · ${EXPIRED}` : `not saved · ${esc(err.message)}`}</div>${
              expired ? '<div class="text-provenance"><button type="button" data-scope-save-again class="cursor-pointer bg-transparent p-0 text-accent-ink underline">save again</button> · <button type="button" data-scope-sign-in class="cursor-pointer bg-transparent p-0 text-accent-ink underline">sign in</button></div>' : ''}`);
          const sa = r.querySelector('[data-scope-save-again]'); if (sa) sa.addEventListener('click', again);
          const si = r.querySelector('[data-scope-sign-in]'); if (si) si.addEventListener('click', signIn);
        }
      }
      say(expired ? `${EXPIRED} · the choice was not saved` : failure(err, what), true);
      if (expired && !before) {
        const st = el.querySelector('[data-scope-status]');
        if (st) {
          st.insertAdjacentHTML('beforeend', ' <button type="button" data-scope-save-again class="cursor-pointer bg-transparent p-0 text-accent-ink underline">save again</button> · <button type="button" data-scope-sign-in class="cursor-pointer bg-transparent p-0 text-accent-ink underline">sign in</button>');
          st.querySelector('[data-scope-save-again]').addEventListener('click', again);
          st.querySelector('[data-scope-sign-in]').addEventListener('click', signIn);
        }
      }
      return;
    }
    if (spent) { selected.clear(); selectedTables.clear(); }   // a finished bulk action spends the selection
    if (rowKey) {
      // the server has taken it: the cell shows the answer and says so NOW, in this same render,
      // before the scope is read again (the selector is live again; the row flashes briefly)
      const r = rowEl(rowKey);
      savedNotes.set(rowKey, { by: whoAmI(), at: md(new Date().toISOString()) });
      flashRows.add(rowKey);
      release();
      const mine = nodeFor(rowKey);
      if (r && mine) {
        r.classList.add('bg-paper-surface');
        paintRow(rowKey, want !== null ? guess(mine, want) : mine);
      }
      setTimeout(() => { flashRows.delete(rowKey); const rr = rowEl(rowKey); if (rr) rr.classList.remove('bg-paper-surface'); }, flashMs);
    }
    let again;
    try { again = await getCatalogueScope(slug); }
    catch (err) { release(); say(`${what}: written, but the scope could not be re-read: ${err.message}`, true); return; }
    if (rowKey) {
      const n = nodeIn(again, rowKey);
      const ex = n && n.explicit;
      savedNotes.set(rowKey, { by: ex ? ex.by : whoAmI(), at: ex ? md(ex.at) : md(new Date().toISOString()) });
      setTimeout(() => {
        savedNotes.delete(rowKey);
        const rr = rowEl(rowKey);
        if (rr) rr.querySelectorAll('[data-scope-saved-note]').forEach((e) => e.parentElement.remove());
      }, savedNoteMs);
    }
    release();
    await renderCatalogueScope(el, slug, verify(again) || '', again);
  };
  const nodeIn = (v, k) => {
    const rest = k.slice(k.indexOf(':') + 1);
    if (k.startsWith('table:')) { const d = rest.indexOf('.'); return find(v, rest.slice(0, d), rest.slice(d + 1)); }
    return find(v, rest, '');
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
    if (bulkBusy) return;                       // one bulk action at a time: a second press is ignored
    bulkBusy = true;
    const keys = [...names.map((n) => `schema:${n}`), ...tabs.map((t) => `table:${t.schema}.${t.table}`)];
    // the ticked rows show the new state now; their controls look pressed until the server answers
    keys.forEach((k) => {
      const node = nodeFor(k);
      if (!node || !rowEl(k)) return;
      pendingRows.add(k);
      paintRow(k, guess(node, choice));
      rowEl(k).querySelector('[data-scope-choice-cell]').insertAdjacentHTML('beforeend', '<div data-scope-saving class="text-provenance text-ink-muted">saving…</div>');
    });
    el.querySelectorAll('[data-scope-bulk-act], [data-scope-catalogue-all]').forEach((b) => { b.disabled = true; b.setAttribute('aria-busy', 'true'); });
    const settle = () => { bulkBusy = false; keys.forEach((k) => pendingRows.delete(k)); };
    afterWrite(async () => {
      try {
        if (names.length) await setCatalogueNodes(slug, names.map((n) => ({ schema: n })), choice, everySchema);
        for (const t of tabs) {
          if (choice) await setCatalogueNode(slug, t.schema, t.table, choice);
          else await clearCatalogueNode(slug, t.schema, t.table);
        }
      } catch (err) {
        settle();
        keys.forEach((k) => { const node = nodeFor(k); const r = rowEl(k); if (node && r) paintRow(k, node); });
        el.querySelectorAll('[data-scope-bulk-act], [data-scope-catalogue-all]').forEach((b) => { b.disabled = false; b.removeAttribute('aria-busy'); });
        throw err;
      }
      settle();
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
      const cur = find(view, schema, table) || {};
      if (act === 'set') afterWrite(() => setCatalogueNode(slug, schema, table, choice), 'set the choice', check(choice), false, rowKey, choice);
      else if (act === 'clear') afterWrite(() => clearCatalogueNode(slug, schema, table), 'clear the choice', check(''), false, rowKey, '');
      else if (act === 'confirm') {
        const want = cur.proposal;
        afterWrite(() => confirmCatalogueNode(slug, schema, table), 'confirm the proposal', check(want ? want.choice : ''), false, rowKey, want ? want.choice : null);
      } else if (act === 'override') {
        const want = cur.proposal;
        afterWrite(() => overrideCatalogueNode(slug, schema, table), 'override the proposal', check(want ? opposite(want.choice) : ''), false, rowKey, want ? opposite(want.choice) : null);
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
  if (again) again.addEventListener('click', () => afterWrite(() => redeclareCatalogueScope(slug), 'start a new baseline',
    (v) => ((v.new_since || {}).text ? 'the baseline was saved, but the re-read scope still shows new things'
      : `${savedLine((v.declared || {}).by, (v.declared || {}).at)} · new baseline: nothing is new since now`)));
  if (sectionOpen || !(view.declared && view.declared.declared)) startCommitPanel();
}
