/* Activity — the operation log, readable in /next.
 *
 * PLAN-FINISH-REPOS.md Part 3 item 6: "the activity log is readable in
 * /next, not only a data source." Named as an example file alongside
 * enrichment.js/understanding.js/curate.js, but Activity is NOT one of the
 * nine canonical stage ids in app.js's `STAGES` array (investigation,
 * scouting, discovery, assessment, analysis, enrichment, understanding,
 * curate, automate). Per packages/resource-explorer/CLAUDE.md, the 📋
 * Activity log is a persistent surface reachable from the header — decoupled
 * from `#intent-nav`/`currentNavIntent`, the same pattern as ⚙ Admin — not
 * something a user does to a specific resource under one of the eight
 * intents. So this is a header-triggered overlay panel, not a STAGES entry
 * with `built: true`.
 *
 * SCOPE. The classic UI's activity view (index.html's `renderActivityLog`)
 * merges a client-only in-memory log with `GET /api/activity/` results, has
 * a client-side "Clear" that only clears the in-memory merge, an unread
 * badge, and a `_openActivityEntry` deep-link jump used by one caller. None
 * of that survives a reload on its own — the persistent record is entirely
 * server-side (`activity_log` table, `GET /api/activity/`). This pane reads
 * that same endpoint directly: no client-side merge, no fabricated "Clear"
 * that cannot touch the record it names. What it keeps from classic: one
 * row per operation, an expandable detail (annotations tally, cataloged
 * items, free-text detail), and GUIDs rendered short with click-to-copy.
 * What it deliberately leaves out: RFA rendering (the RFA drawer, `#rfa-
 * drawer`, is /next's OWN separate not-yet-built item — this reads the same
 * `annotations` field but its RequestForAction rows belong to that surface,
 * not this one; this list still SHOWS an rfa-operation row, since rule 16
 * requires it be logged and hiding it would be exactly the "logged but
 * invisible" gap that rule closes), and the classic advanced filter form
 * (entity_type/intent/operation/status/since as separate selects) — this
 * pane offers one text filter (matches slug or summary) plus a status chip
 * row, client-side over the fetched page, which is enough to find "what
 * failed" or "what happened to this repo" without reproducing every control.
 */
import { listActivity } from '/static/re-api.js';
import { esc, tnum } from '/static/next/app.js';
import { ago } from '/static/next/format.js';

const PANEL_ID = 'activity-panel';
const FETCH_LIMIT = 300;

const OPERATION_LABEL = {
  survey: 'Survey', catalog: 'Catalog → Egeria', publish: 'Publish → Egeria',
  scout: 'Scout', discover: 'Discover', refresh: 'Refresh', rfa: 'RFA',
  analysis_run: 'Analysis run',
};
const OPERATION_ICON = {
  survey: '📊', catalog: '☁', publish: '☁', scout: '🔍', discover: '🔍',
  refresh: '🔄', rfa: '📝', analysis_run: '⚙',
};
const ENTITY_ICON = { repo: '📁', database: '🗄', server: '🖥', filesystem: '📂', file: '📄' };
const STATUS_TONE = {
  ok: 'text-state-ok', success: 'text-state-ok',
  error: 'text-state-warn', failed: 'text-state-warn',
  running: 'text-accent-ink', queued: 'text-accent-ink', pending: 'text-accent-ink',
};
const STATUS_GLYPH = { ok: '✓', success: '✓', error: '✗', failed: '✗', running: '◔', queued: '◔', pending: '⏳' };

const GUID_RX = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/gi;

/** Same short-GUID-with-copy convenience classic's activity log offers,
 *  applied AFTER esc() so it operates on already-safe text. */
function hiGuid(escapedText) {
  return escapedText.replace(GUID_RX, (m) =>
    `<span class="cursor-pointer font-mono text-provenance text-ink-muted hover:text-ink"
      title="${m} — click to copy" data-copy-guid="${m}">${m.slice(0, 8)}…</span>`);
}

/** Local, per-open state — not persisted, not shared with app.js's `state`.
 *  Filters reset every time the panel opens, same as the classic tab does
 *  not remember a filter across a reload. */
const panel = { entries: null, error: null, statusFilter: 'all', textFilter: '' };

function closeActivityPanel() {
  document.getElementById(PANEL_ID)?.remove();
  document.removeEventListener('keydown', onPanelKeydown);
}

function onPanelKeydown(e) {
  if (e.key === 'Escape') closeActivityPanel();
}

/** Open the panel, freshly fetched every time — activity keeps happening
 *  while the panel is closed, and a stale cached page would misreport a
 *  finished run as still `running`. */
export async function openActivityPanel() {
  closeActivityPanel();
  panel.entries = null;
  panel.error = null;
  panel.statusFilter = 'all';
  panel.textFilter = '';

  const el = document.createElement('div');
  el.id = PANEL_ID;
  el.className = 'fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-s4 overflow-auto';
  el.innerHTML = `
    <div class="mt-[4vh] w-full max-w-[760px] rounded bg-paper p-s4 shadow-lg"
      role="dialog" aria-modal="true" aria-label="Activity log">
      <div class="flex items-start justify-between gap-s3">
        <div>
          <div class="font-heading text-name text-ink">Activity</div>
          <div class="mt-[2px] text-caveat text-ink-muted">Every scouting, survey, catalog,
            publish and RFA operation this instance has recorded (rule 16) — read from the
            same log the current UI's Activity tab shows, not a separate client-side copy.</div>
        </div>
        <button type="button" data-act="close" class="text-ink-muted hover:text-ink" aria-label="Close">×</button>
      </div>
      <div class="my-s3 h-px bg-rule"></div>
      <div id="activity-panel-controls" class="flex flex-wrap items-center gap-s3 text-caveat"></div>
      <div id="activity-panel-body" class="mt-s3 max-h-[62vh] overflow-y-auto text-caveat text-ink-muted">reading…</div>
    </div>`;
  document.body.appendChild(el);
  el.addEventListener('click', (e) => {
    if (e.target === el || e.target.closest('[data-act="close"]')) closeActivityPanel();
    const copy = e.target.closest('[data-copy-guid]');
    if (copy) navigator.clipboard?.writeText(copy.dataset.copyGuid).catch(() => {});
    const toggle = e.target.closest('[data-activity-toggle]');
    if (toggle) {
      const body = document.getElementById(toggle.dataset.activityToggle);
      if (body) body.classList.toggle('hidden');
    }
  });
  document.addEventListener('keydown', onPanelKeydown);

  try {
    panel.entries = await listActivity(FETCH_LIMIT);
  } catch (err) {
    panel.error = err.message;
  }
  if (!document.getElementById(PANEL_ID)) return; // closed while the fetch was in flight
  renderControls();
  renderList();
}

function renderControls() {
  const host = document.getElementById('activity-panel-controls');
  if (!host) return;
  const statuses = ['all', 'ok', 'error', 'running'];
  host.innerHTML = `
    <input id="activity-filter-text" type="text" placeholder="filter by resource or summary…"
      value="${esc(panel.textFilter)}"
      class="min-w-[220px] flex-1 rounded-sm border border-rule bg-transparent px-2 py-[3px] text-caveat text-ink" />
    <span class="flex gap-[6px]">${statuses.map((s) => `<button data-activity-status="${s}"
      aria-pressed="${panel.statusFilter === s ? 'true' : 'false'}"
      class="cursor-pointer rounded-sm border border-rule bg-transparent px-2 py-[2px] text-caveat
        ${panel.statusFilter === s ? 'border-accent text-accent-ink' : 'text-ink-muted hover:text-ink'}"
      >${s}</button>`).join('')}</span>`;
  host.querySelector('#activity-filter-text').addEventListener('input', (e) => {
    panel.textFilter = e.target.value;
    renderList();
  });
  host.querySelectorAll('[data-activity-status]').forEach((b) => b.addEventListener('click', () => {
    panel.statusFilter = b.dataset.activityStatus;
    renderControls();
    renderList();
  }));
}

function filteredEntries() {
  if (!panel.entries) return [];
  const q = panel.textFilter.trim().toLowerCase();
  return panel.entries.filter((e) => {
    if (panel.statusFilter !== 'all' && (e.status || '').toLowerCase() !== panel.statusFilter) return false;
    if (!q) return true;
    return (e.entity_slug || '').toLowerCase().includes(q)
      || (e.entity_name || '').toLowerCase().includes(q)
      || (e.summary || '').toLowerCase().includes(q);
  });
}

function entryRowHtml(op) {
  const opLabel = OPERATION_LABEL[op.operation] || op.operation || 'Operation';
  const opIcon = OPERATION_ICON[op.operation] || '•';
  const entityIcon = ENTITY_ICON[op.entity_type] || '';
  const tone = STATUS_TONE[(op.status || '').toLowerCase()] || 'text-ink-muted';
  const glyph = STATUS_GLYPH[(op.status || '').toLowerCase()] || '·';
  const when = op.ts ? ago(op.ts) : '';
  const whenTitle = (op.ts || '').replace('T', ' ').slice(0, 19) + ' UTC';

  const annotations = op.annotations || [];
  const annHtml = annotations.length
    ? `<div class="mt-[3px] text-provenance text-ink-muted">${
        annotations.slice(0, 6).map((a) => `${esc(a.analysis_name || a.annotation_type || '')}: ${tnum(String(a.count ?? ''))}`).join(' · ')
      }${annotations.length > 6 ? ` · +${annotations.length - 6} more` : ''}</div>`
    : '';

  const tableItems = (op.items || []).filter((it) => !it.link);
  const itemsHtml = tableItems.length
    ? `<table class="mt-s2 w-full border-collapse text-provenance">
        <thead><tr class="text-ink-muted"><th class="w-28 pb-[2px] text-left font-normal">Type</th>
          <th class="pb-[2px] text-left font-normal">Name</th>
          <th class="w-36 pb-[2px] text-left font-normal">GUID</th></tr></thead>
        <tbody class="divide-y divide-rule">${tableItems.map((it) => `<tr>
          <td class="py-[2px] pr-2 text-ink-muted">${esc(it.kind || '')}</td>
          <td class="max-w-[16rem] truncate py-[2px] pr-2 font-mono text-ink" title="${esc(it.display_name || it.name || '')}">${esc(it.display_name || it.name || '—')}</td>
          <td class="py-[2px]">${it.guid ? hiGuid(esc(it.guid)) : '<span class="text-ink-muted">—</span>'}</td>
        </tr>`).join('')}</tbody></table>`
    : '';

  const detailHtml = op.detail
    ? `<div class="mt-s2 whitespace-pre-wrap text-provenance text-ink-muted">${
        op.detail.split('\n').map((line) => hiGuid(esc(line))).join('<br/>')}</div>`
    : '';

  const hasDetail = !!(annHtml || itemsHtml || detailHtml);
  const detailId = `activity-d-${esc(op.id || '').replace(/[^a-z0-9]/gi, '_').slice(0, 24)}`;

  return `<div class="border-b border-rule py-s2">
    <div class="flex flex-wrap items-baseline gap-[6px]">
      <span class="shrink-0">${opIcon}</span>
      <span class="font-heading text-answer text-ink">${esc(opLabel)}</span>
      ${op.entity_slug ? `<span class="font-mono text-provenance text-ink-muted">${entityIcon} ${esc(op.entity_slug)}</span>` : ''}
      ${op.intent ? `<span class="text-provenance text-ink-muted">${esc(op.intent)}</span>` : ''}
      <span class="ml-auto shrink-0 text-provenance ${tone}">${glyph} ${esc(op.status || '')}</span>
      ${hasDetail ? `<button type="button" data-activity-toggle="${detailId}"
        class="cursor-pointer bg-transparent p-0 text-provenance text-accent-ink" title="Show detail">▶ detail</button>` : ''}
    </div>
    <div class="mt-[2px] text-caveat text-ink">${esc(op.summary || '')}</div>
    <div class="mt-[2px] text-provenance text-ink-muted" title="${esc(whenTitle)}">${esc(when)}</div>
    ${hasDetail ? `<div id="${detailId}" class="hidden">${annHtml}${itemsHtml}${detailHtml}</div>` : ''}
  </div>`;
}

function renderList() {
  const host = document.getElementById('activity-panel-body');
  if (!host) return;

  if (panel.error) {
    host.innerHTML = `<p class="max-w-[60ch] text-answer text-accent-ink">The activity log could
      not be read: ${esc(panel.error)}</p>`;
    return;
  }
  if (panel.entries === null) {
    host.innerHTML = '<p class="text-caveat text-ink-muted">reading…</p>';
    return;
  }

  const rows = filteredEntries();
  if (!panel.entries.length) {
    host.innerHTML = `<p class="max-w-[60ch] text-answer text-ink">No operations recorded yet.
      Scouting, running a survey, or publishing to Egeria all write here (rule 16) — this is
      empty because nothing has happened yet, not because logging is broken.</p>`;
    return;
  }
  if (!rows.length) {
    host.innerHTML = `<p class="max-w-[60ch] text-answer text-ink">Nothing recorded matches
      this filter. <span class="tnum">${panel.entries.length}</span> total entr${panel.entries.length === 1 ? 'y is' : 'ies are'}
      loaded; try a different filter or status.</p>`;
    return;
  }
  const shownOfLoaded = rows.length < panel.entries.length
    ? `<div class="mb-s2 text-provenance text-ink-muted"><span class="tnum">${rows.length}</span> of
       <span class="tnum">${panel.entries.length}</span> loaded entries match this filter.</div>`
    : (panel.entries.length >= FETCH_LIMIT
      ? `<div class="mb-s2 text-provenance text-ink-muted">Showing the most recent
         <span class="tnum">${FETCH_LIMIT}</span> entries.</div>`
      : '');
  host.innerHTML = shownOfLoaded + rows.map(entryRowHtml).join('');
}
