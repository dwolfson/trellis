/* The RFA drawer — /next's own view of RequestForAction.
 *
 * RFA is NOT one of the eight intents (see packages/resource-explorer's own
 * CLAUDE.md) — it is chrome-level infrastructure, a persistent panel
 * reachable from the header regardless of which stage is active, the same
 * role `#rfa-drawer` plays in the classic UI (index.html). This module is a
 * TOP-LEVEL shared module for exactly that reason: like worklist.js, it is
 * imported BY app.js rather than being one of app.js's per-stage panes, so
 * it deliberately does not import `state`/`esc`/`$` back from app.js (that
 * would be circular) and instead carries its own tiny versions of them.
 *
 * SCOPE (PLAN-FINISH-REPOS.md item 10, "RFAs — not started"): let someone
 * see and act on their RFAs without leaving /next. That means:
 *   - list open RFAs, globally and filtered to the resource in view;
 *   - show what each one is about (entity, analysis, summary, explanation,
 *     action requested/target — the fields the classic drawer already
 *     reads off the flattened `/api/activity/rfas` row, `activity.py`'s
 *     `_emit_rfa`);
 *   - take the three LOCAL response actions that already exist server-side:
 *     defer / reassign / complete (plus reopen, which is the same PATCH
 *     with `status: 'open'` — `RFA_STATUSES` in `web/routes/activity.py`).
 *
 * NOT in scope here, deliberately: the dismissal flow (not-applicable /
 * won't-do — `docs/rfa-dismissals.md`), the free-text notes field, and any
 * of that is real Egeria ToDo integration. All three response actions
 * stay local-only — `resource_explorer/registry.py`'s `rfa_actions` table
 * docstring and `docs/egeria-integration.md` §11 cover why (a real pyegeria
 * actor-GUID story is the blocker, not a design choice this file makes).
 * `rfa_egeria_sync.py` already attempts a best-effort Egeria ToDo write
 * behind `PATCH /api/activity/rfas/{id}` server-side; this drawer neither
 * knows nor needs to know that happened — its job ends at the local write
 * succeeding.
 */

import { listRfas, updateRfaAction } from '/static/re-api.js';

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const STATUS_LABEL = {
  open: 'Open',
  deferred: 'Deferred',
  reassigned: 'Reassigned',
  completed: 'Completed',
};

const STATUS_TONE = {
  open: 'text-accent-ink',
  deferred: 'text-state-warn',
  reassigned: 'text-state-warn',
  completed: 'text-state-ok',
};

let _drawerEl = null;
let _rfas = [];          // last fetch, raw rows from GET /api/activity/rfas
let _loadTicket = 0;     // guards against a slow fetch landing after a newer one started
let _scopeSlug = '';     // '' = all resources; set from the caller at open time
let _scopeOnly = true;   // "this resource" vs "all" — only meaningful when _scopeSlug is set
let _showClosed = false; // include completed alongside open/deferred/reassigned

function _buildShell() {
  const el = document.createElement('aside');
  el.id = 'next-rfa-drawer';
  el.className = 'fixed inset-y-0 right-0 z-[80] flex w-[26rem] max-w-[92vw] flex-col '
    + 'border-l border-chrome-line bg-chrome text-chrome-ink shadow-lg';
  el.style.display = 'none';
  el.innerHTML = `
    <div class="flex items-center justify-between border-b border-chrome-line px-s3 py-s2">
      <span class="font-heading text-caps uppercase tracking-caps text-chrome-ink">Open RFAs</span>
      <button type="button" id="next-rfa-close" aria-label="Close"
        class="cursor-pointer bg-transparent text-chrome-muted hover:text-chrome-ink">×</button>
    </div>
    <div class="flex items-center gap-s3 border-b border-chrome-line px-s3 py-s2 text-chip text-chrome-muted">
      <label class="flex cursor-pointer items-center gap-[6px]">
        <input type="checkbox" id="next-rfa-scope-only">
        <span id="next-rfa-scope-label">this resource only</span>
      </label>
      <label class="flex cursor-pointer items-center gap-[6px]">
        <input type="checkbox" id="next-rfa-show-closed">
        <span>show completed</span>
      </label>
    </div>
    <div id="next-rfa-list" class="flex-1 overflow-y-auto px-s3 py-s2 text-resource">reading…</div>
  `;
  document.body.appendChild(el);

  el.querySelector('#next-rfa-close').addEventListener('click', closeRfaDrawer);
  el.querySelector('#next-rfa-scope-only').addEventListener('change', (e) => {
    _scopeOnly = e.target.checked;
    _renderList();
  });
  el.querySelector('#next-rfa-show-closed').addEventListener('change', (e) => {
    _showClosed = e.target.checked;
    _renderList();
  });
  el.querySelector('#next-rfa-list').addEventListener('click', _onListClick);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && el.style.display !== 'none') closeRfaDrawer();
  });

  return el;
}

function _visibleRows() {
  let rows = _rfas;
  if (_scopeSlug && _scopeOnly) rows = rows.filter((r) => r.entity_slug === _scopeSlug);
  if (!_showClosed) rows = rows.filter((r) => r.rfa_status !== 'completed');
  // Newest first — matches the classic drawer and the activity log's own convention.
  return [...rows].sort((a, b) => String(b.ts || '').localeCompare(String(a.ts || '')));
}

function _rowHtml(rfa) {
  const tone = STATUS_TONE[rfa.rfa_status] || 'text-chrome-muted';
  const label = STATUS_LABEL[rfa.rfa_status] || rfa.rfa_status;
  const who = rfa.entity_name || rfa.entity_slug || 'unknown resource';
  const what = rfa.analysis_name || rfa.annotation_type || 'RFA';
  const dismissedNote = rfa.dismissed
    ? `<div class="mt-[2px] text-provenance text-chrome-muted">suppressed — ${esc((rfa.dismissal || {}).reason || '')}</div>`
    : '';
  const assigneeNote = rfa.assignee
    ? ` · assigned to <span class="text-chrome-ink">${esc(rfa.assignee)}</span>`
    : '';
  const deferNote = rfa.rfa_status === 'deferred' && rfa.defer_until
    ? ` · until <span class="tnum">${esc(rfa.defer_until)}</span>`
    : '';
  const canAct = rfa.rfa_status !== 'completed';
  const actions = `
    ${canAct ? `<button type="button" data-rfa-act="deferred" data-rfa-id="${esc(rfa.id)}"
        class="cursor-pointer bg-transparent text-accent-ink underline">Defer</button>` : ''}
    ${canAct ? `<button type="button" data-rfa-act="reassigned" data-rfa-id="${esc(rfa.id)}"
        class="cursor-pointer bg-transparent text-accent-ink underline">Reassign</button>` : ''}
    ${canAct ? `<button type="button" data-rfa-act="completed" data-rfa-id="${esc(rfa.id)}"
        class="cursor-pointer bg-transparent text-accent-ink underline">Complete</button>` : ''}
    ${rfa.rfa_status !== 'open' ? `<button type="button" data-rfa-act="open" data-rfa-id="${esc(rfa.id)}"
        class="cursor-pointer bg-transparent text-chrome-muted underline">Reopen</button>` : ''}
  `;
  return `
    <div class="border-b border-chrome-line py-s2" data-rfa-row="${esc(rfa.id)}">
      <div class="flex items-start justify-between gap-s2">
        <div class="min-w-0">
          <div class="truncate text-provenance text-chrome-muted">${esc(who)} · ${esc(what)}</div>
          <div class="text-resource text-chrome-ink">${esc(rfa.summary || '(no summary)')}</div>
          ${rfa.explanation ? `<div class="mt-[2px] text-provenance text-chrome-muted">${esc(rfa.explanation)}</div>` : ''}
          ${rfa.action_requested ? `<div class="mt-[2px] text-provenance text-chrome-muted">requested: ${esc(rfa.action_requested)}${
            rfa.action_target_name ? ` — ${esc(rfa.action_target_name)}` : ''}</div>` : ''}
        </div>
        <span class="shrink-0 whitespace-nowrap text-provenance ${tone}">${esc(label)}</span>
      </div>
      <div class="mt-[2px] text-provenance text-chrome-muted">${assigneeNote}${deferNote}</div>
      ${dismissedNote}
      <div class="mt-s2 flex flex-wrap gap-s3 text-chip" data-rfa-actions>${actions}</div>
    </div>
  `;
}

function _renderList() {
  if (!_drawerEl) return;
  const host = _drawerEl.querySelector('#next-rfa-list');
  const scopeLabel = _drawerEl.querySelector('#next-rfa-scope-label');
  const scopeOnlyBox = _drawerEl.querySelector('#next-rfa-scope-only');
  if (scopeLabel) scopeLabel.textContent = _scopeSlug ? `this resource only (${_scopeSlug})` : 'this resource only';
  if (scopeOnlyBox) scopeOnlyBox.disabled = !_scopeSlug;

  const rows = _visibleRows();
  if (!rows.length) {
    host.innerHTML = `<p class="text-caveat text-chrome-muted">
      No ${_showClosed ? '' : 'open '}RFAs${_scopeSlug && _scopeOnly ? ` for ${esc(_scopeSlug)}` : ''}.
    </p>`;
    return;
  }
  host.innerHTML = rows.map(_rowHtml).join('');
}

async function _onListClick(e) {
  const btn = e.target.closest('[data-rfa-act]');
  if (!btn) return;
  const status = btn.dataset.rfaAct;
  const rfaId = btn.dataset.rfaId;
  const row = _rfas.find((r) => r.id === rfaId);
  if (!row) return;

  let assignee = row.assignee || '';
  let deferUntil = row.defer_until || '';
  let resolutionNote = row.resolution_note || '';

  if (status === 'reassigned') {
    const typed = window.prompt('Assign to (name or email):', assignee);
    if (typed === null) return;      // cancelled — nothing recorded
    assignee = typed.trim();
  } else if (status === 'deferred') {
    const typed = window.prompt('Defer until (any text — a date, "next survey", etc.):', deferUntil);
    if (typed === null) return;
    deferUntil = typed.trim();
  } else if (status === 'completed') {
    const typed = window.prompt('Resolution note (optional):', resolutionNote);
    if (typed === null) return;
    resolutionNote = typed.trim();
  }

  const actionsHost = _drawerEl.querySelector(`[data-rfa-row="${CSS.escape(rfaId)}"] [data-rfa-actions]`);
  if (actionsHost) actionsHost.textContent = 'saving…';

  try {
    await updateRfaAction(rfaId, { status, assignee, deferUntil, resolutionNote });
    // Reflect it locally rather than a full reload — the row's own PATCH
    // response already told us it succeeded, and a full re-fetch would
    // discard the scope/closed toggles' current state for no reason.
    Object.assign(row, {
      rfa_status: status, assignee, defer_until: deferUntil, resolution_note: resolutionNote,
    });
    _renderList();
  } catch (err) {
    if (actionsHost) {
      actionsHost.innerHTML = `<span class="text-state-warn">not recorded: ${esc(err && err.message ? err.message : 'could not reach the server')}</span>`;
    }
  }
}

async function _load() {
  const ticket = ++_loadTicket;
  const host = _drawerEl.querySelector('#next-rfa-list');
  host.innerHTML = 'reading…';
  try {
    const rows = await listRfas();
    if (ticket !== _loadTicket) return;   // a newer open()/refresh() already landed
    _rfas = Array.isArray(rows) ? rows : [];
    _renderList();
  } catch (err) {
    if (ticket !== _loadTicket) return;
    host.innerHTML = `<p class="text-caveat text-state-warn">
      Could not read RFAs: ${esc(err && err.message ? err.message : 'unknown error')}
    </p>`;
  }
}

/** Open the drawer, scoped to `slug` if given (the resource currently in
 *  view) — the toggle still lets the viewer widen to every RFA. Re-fetches
 *  every open, so a defer/reassign/complete made on the previous visit (or
 *  by another tab) is never shown stale. */
export function openRfaDrawer(slug = '') {
  if (!_drawerEl) _drawerEl = _buildShell();
  _scopeSlug = slug || '';
  const scopeOnlyBox = _drawerEl.querySelector('#next-rfa-scope-only');
  if (scopeOnlyBox) scopeOnlyBox.checked = _scopeOnly && !!_scopeSlug;
  _drawerEl.style.display = 'flex';
  _load();
}

export function closeRfaDrawer() {
  if (_drawerEl) _drawerEl.style.display = 'none';
}

export function isRfaDrawerOpen() {
  return !!_drawerEl && _drawerEl.style.display !== 'none';
}

/** The header button's handler: toggle, scoped to whatever resource is
 *  currently in view (app.js passes `state.slug`). */
export function toggleRfaDrawer(slug = '') {
  if (isRfaDrawerOpen()) {
    closeRfaDrawer();
  } else {
    openRfaDrawer(slug);
  }
}
