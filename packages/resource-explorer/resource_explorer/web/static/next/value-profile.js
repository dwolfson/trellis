/** Value profile (database-only): what the latest value-profile batch measured, one card per table, one row per column.
 *
 *  Design: ~/.re-gate/DESIGN-VALUE-PROFILE-SCREEN-2026-10-30.md. The words are the server's
 *  (resource_explorer/value_profile_screen.py), so the screen, the "numbers behind this" rows and the tests share one
 *  vocabulary; this file draws them and wires the filters and cards.
 *
 *  Rules kept here:
 *   - every card is collapsed until opened, and a card's columns are read when it opens (one table at a time);
 *   - a table that was not measured has no opener: its reason is its whole card;
 *   - a column that was not profiled is one row with its state cue and reason, never a row of empty cells;
 *   - a muted cell keeps its title, which says which absence it is (not a measure of this type, not asked for, ...).
 *
 *  The module takes its API and callbacks as arguments, so it loads without the rest of the app and a test can drive it
 *  with a stub. Column tables use colresize (report-tables.js). */
import { esc, gridHtml, attachGrids } from '/static/next/stages/report-tables.js';
import { stateEntry } from '/static/next/glyphs.js';

export const VP_COLS = {
  id: 'db-value-profile', chrome: 70,
  columns: [
    { key: 'column', label: 'Column', def: 190, min: 90, align: 'left', breakLong: true },
    { key: 'type', label: 'Type', def: 70, min: 60 },
    { key: 'filled', label: 'Filled', def: 140, min: 100 },
    { key: 'distinct', label: 'Distinct', def: 110, min: 80 },
    { key: 'range', label: 'Range', def: 230, min: 110, breakLong: true },
    { key: 'common', label: 'Most common', def: 240, min: 120, align: 'left', breakLong: true },
    { key: 'flags', label: 'Flags', def: 110, min: 80, breakLong: true },
    { key: 'checks', label: 'Checks', def: 220, min: 90, breakLong: true },
  ],
};

/** The glyph a not-profiled column's cue carries (the glyph table's): ◌ not measured, ⊘ not permitted, — not applicable. */
const CUE_OF = { not_measured: '◌', not_permitted: '⊘', not_applicable: '—' };

/* ── the door from Schema Inventory and the "numbers behind this" rows ─────────────────────────────────────────── */
let _pick = '';
/** A door leaves the table ("schema.table") it was pressed on; the tab opens that card once. */
export function setProfilePick(key) { _pick = key || ''; }
export function takeProfilePick() { const p = _pick; _pick = ''; return p; }

/* ── pure helpers (exported for the harness) ────────────────────────────────────────────────────────────────── */

export const tableKey = (t) => `${t.schema_name}.${t.table_name}`;

/** A cell from the server's `{text, title, muted}`. The most common values keep their "+N more" as a button that opens
 *  the whole list in place. */
export function cellHtml(cell, key) {
  if (!cell) return '';
  const title = cell.title ? ` title="${esc(cell.title)}"` : '';
  if (key === 'common' && cell.more && Array.isArray(cell.values)) {
    const list = cell.values.map((v) => `<li><span class="font-mono">${esc(v.value)}</span> <span class="text-ink-muted">×${esc(v.count)}</span></li>`).join('');
    return `<span data-vp-cell="${key}" class="${cell.muted ? 'text-ink-muted' : 'text-ink'}"${title}>${esc(cell.top)}</span>
      <button type="button" data-vp-more data-label="+${esc(cell.more.toLocaleString('en-US'))} more" class="cursor-pointer bg-transparent text-provenance text-accent-ink underline">+${esc(cell.more.toLocaleString('en-US'))} more</button>
      <ul data-vp-values hidden class="mt-[2px] text-provenance">${list}</ul>`;
  }
  if (key === 'checks' && !cell.muted) {
    return `<button type="button" data-vp-checks class="cursor-pointer bg-transparent text-left text-accent-ink underline"${title}>${esc(cell.text)}</button>`;
  }
  return `<span data-vp-cell="${key}" class="${cell.muted ? 'text-ink-muted' : 'text-ink'}"${title}>${esc(cell.text)}</span>`;
}

/** One column row: a measured column's cells, or a not-profiled column's name, cue and reason. */
export function columnRow(c) {
  const name = `<span class="font-mono text-ink">${esc(c.column_name)}</span>`;
  if (!c.cells) {
    const glyph = CUE_OF[c.state] || stateEntry('unknown').glyph;
    return { attrs: `data-vp-column="${esc(c.column_name)}" data-vp-state="${esc(c.state)}"`, tone: 'lowered',
      cells: { column: name },
      after: `<div data-vp-sentence class="pl-s3 text-provenance text-ink-muted"><span class="font-glyph" aria-hidden="true">${glyph}</span> ${esc(c.state_words)} · ${esc(c.sentence)}</div>` };
  }
  const cells = { column: name };
  for (const k of ['type', 'filled', 'distinct', 'range', 'common', 'flags', 'checks']) cells[k] = cellHtml(c.cells[k], k);
  return { attrs: `data-vp-column="${esc(c.column_name)}" data-vp-state="measured"`, cells };
}

/** The rows a card shows under the filters: a state filter keeps columns in that state, a type filter measured
 *  columns of that type. */
export function filterColumns(columns, { state = '', type = '' } = {}) {
  return (columns || []).filter((c) => (!state || c.state === state) && (!type || (c.cells && c.type === type)));
}

export function bodyHtml(table, filters) {
  const rows = filterColumns(table.columns, filters);
  if (!rows.length) return '<div class="text-caveat text-ink-muted">No columns in this table match the filters.</div>';
  return gridHtml(VP_COLS, `Value profile of ${tableKey(table)}`, rows.map(columnRow));
}

/** The tables the filters keep, from the summary's per-table counts (no column read needed). */
export function filterTables(tables, { state = '', type = '', text = '' } = {}) {
  const q = text.trim().toLowerCase();
  return (tables || []).filter((t) => (!state || (t.state_counts || {})[state])
    && (!type || (t.type_counts || {})[type]) && (!q || tableKey(t).toLowerCase().includes(q)));
}

/** A card. A measured table opens; any other is one line with its reason and nothing to open. */
export function cardHtml(t, isOpen) {
  const key = tableKey(t);
  // The line starts with the table's own name; the name is drawn in monospace, the rest in muted words.
  const rest = String(t.line || '').slice(key.length);
  const head = `<span class="font-mono text-ink">${esc(key)}</span><span data-vp-line class="text-provenance text-ink-muted">${esc(rest)}</span>`;
  if (!t.openable) {
    return `<div data-vp-table="${esc(key)}" data-vp-table-state="${esc(t.state)}" class="border-t border-rule py-[3px] pl-[14px]">${head}</div>`;
  }
  return `<details data-vp-table="${esc(key)}" data-vp-table-state="${esc(t.state)}"${isOpen ? ' open' : ''} class="border-t border-rule py-[3px]">
    <summary class="cursor-pointer">${head}</summary>
    <div data-vp-body class="mt-s1 min-w-0 max-w-full">${isOpen ? '<div class="text-caveat text-ink-muted">Reading the columns…</div>' : ''}</div></details>`;
}

function filterSelect(name, label, options, value) {
  return `<label class="text-provenance text-ink-muted">${esc(label)}
    <select data-vp-filter="${name}" class="ml-[2px] border border-rule-strong bg-transparent text-ink">
      <option value="">all</option>${(options || []).map((o) =>
    `<option value="${esc(o.value)}"${o.value === value ? ' selected' : ''}>${esc(o.label)} (${Number(o.count).toLocaleString('en-US')})</option>`).join('')}
    </select></label>`;
}

/** "68 of 157 tables match" when filtered, "157 tables" otherwise. */
export function matchLine(shown, total, filtered) {
  const noun = (n) => (n === 1 ? 'table' : 'tables');
  return filtered ? `${shown.toLocaleString('en-US')} of ${total.toLocaleString('en-US')} ${noun(total)} match`
    : `${total.toLocaleString('en-US')} ${noun(total)}`;
}

export function summaryHtml(d, filters) {
  if (!d.profiled) return `<div data-vp-empty class="text-caveat text-ink-muted">${esc(d.sentence)}</div>`;
  return `<div data-vp-header class="mb-s1 text-answer text-ink">${esc(d.header)}</div>
    <div class="mb-s1 flex flex-wrap items-baseline gap-x-s3 gap-y-[2px]">
      ${filterSelect('state', 'State', d.filters.states, filters.state)}
      ${filterSelect('type', 'Type', d.filters.types, filters.type)}
      <input data-vp-filter="text" type="text" value="${esc(filters.text)}" placeholder="Filter by schema.table…"
        class="w-full max-w-[28ch] rounded-sm border border-rule bg-transparent px-s2 py-[2px] text-caveat text-ink placeholder:text-ink-muted" />
      <span data-vp-match class="text-provenance text-ink-muted"></span></div>`;
}

/** Draw the tab into `slot` and wire it. `deps` = { api: { getValueProfile(slug), getValueProfileTable(slug, s, t) },
 *  table: "schema.table" to open first ('' for none), onTable(key): the open card changed (the URL keeps it),
 *  openChecks(): go to Curate › Structure }. Returns { reload(), destroy() }. */
export function mountValueProfile(slot, slug, deps) {
  const filters = { state: '', type: '', text: '' };
  const open = new Set(deps.table ? [deps.table] : []);
  const columnsOf = new Map();
  const loading = new Set();
  let summary = null;
  let token = 0;
  let scrollTo = deps.table || '';

  const cardEl = (key) => [...slot.querySelectorAll('[data-vp-table]')].find((e) => e.dataset.vpTable === key);
  const paintBody = (key) => {
    const el = cardEl(key);
    const host = el && el.querySelector('[data-vp-body]');
    const t = columnsOf.get(key);
    if (!host || !t) return;
    host.innerHTML = bodyHtml(t, filters);
    attachGrids(host, () => VP_COLS);
  };

  async function loadColumns(t) {
    const key = tableKey(t);
    const mine = token;
    if (loading.has(key)) return;
    loading.add(key);
    let d = null;
    let failure = null;
    try { d = await deps.api.getValueProfileTable(slug, t.schema_name, t.table_name); } catch (err) { failure = err; }
    finally { loading.delete(key); }
    if (mine !== token) return;
    if (failure) {
      const el = cardEl(key);
      const host = el && el.querySelector('[data-vp-body]');
      if (host) host.innerHTML = `<div data-vp-error class="text-caveat text-state-warn">The columns of this table could not be read: ${esc(failure.message)}</div>`;
      return;
    }
    columnsOf.set(key, d);
    paintBody(key);
  }

  function paintCards() {
    const host = slot.querySelector('[data-vp-tables]');
    const shown = filterTables(summary.tables, filters);
    const filtered = Boolean(filters.state || filters.type || filters.text.trim());
    const match = slot.querySelector('[data-vp-match]');
    if (match) match.textContent = matchLine(shown.length, summary.tables.length, filtered);
    host.innerHTML = shown.length ? shown.map((t) => cardHtml(t, open.has(tableKey(t)))).join('')
      : '<div data-vp-no-match class="text-caveat text-ink-muted">No tables match these filters.</div>';
    host.querySelectorAll('details[data-vp-table]').forEach((el) => {
      const t = summary.tables.find((x) => tableKey(x) === el.dataset.vpTable);
      el.addEventListener('toggle', () => {
        const key = tableKey(t);
        if (el.open) {
          open.add(key);
          if (columnsOf.has(key)) paintBody(key); else loadColumns(t);
          if (deps.onTable) deps.onTable(key);
        } else {
          open.delete(key);
          if (deps.onTable) deps.onTable([...open].pop() || '');
        }
      });
      if (el.open) { if (columnsOf.has(tableKey(t))) paintBody(tableKey(t)); else loadColumns(t); }
    });
    if (scrollTo) {
      const el = cardEl(scrollTo);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start' });
      scrollTo = '';
    }
  }

  async function reload() {
    const mine = ++token;
    columnsOf.clear();
    let d;
    try { d = await deps.api.getValueProfile(slug); } catch (err) {
      if (mine !== token) return;
      slot.innerHTML = `<div data-vp-error class="text-caveat text-state-warn">The value profile could not be read: ${esc(err.message)}</div>`;
      return;
    }
    if (mine !== token) return;
    summary = d;
    slot.innerHTML = `<div data-vp-head>${summaryHtml(d, filters)}</div><div data-vp-tables></div>`;
    if (!d.profiled) return;
    slot.querySelectorAll('select[data-vp-filter]').forEach((sel) => sel.addEventListener('change', () => {
      filters[sel.dataset.vpFilter] = sel.value;
      paintCards();
    }));
    const input = slot.querySelector('input[data-vp-filter="text"]');
    if (input) input.addEventListener('input', () => { filters.text = input.value; paintCards(); });
    paintCards();
  }

  const onClick = (ev) => {
    const more = ev.target.closest && ev.target.closest('[data-vp-more]');
    if (more && slot.contains(more)) {
      const list = more.parentElement.querySelector('[data-vp-values]');
      if (list) { list.hidden = !list.hidden; more.textContent = list.hidden ? more.dataset.label : 'fewer'; }
      return;
    }
    const checks = ev.target.closest && ev.target.closest('[data-vp-checks]');
    if (checks && slot.contains(checks) && deps.openChecks) deps.openChecks();
  };
  slot.addEventListener('click', onClick);
  reload();
  return { reload, destroy() { token += 1; slot.removeEventListener('click', onClick); } };
}
