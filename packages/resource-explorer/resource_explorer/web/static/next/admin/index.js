/* Admin — system/catalog configuration, reachable from the header's own
 * ⚙ Admin button (PLAN-FINISH-REPOS.md item 5).
 *
 * Per packages/resource-explorer/CLAUDE.md's "System/catalog configuration
 * is not an intent" section, Admin is chrome-level and decoupled from
 * `#intent-nav`/`currentNavIntent` — the same pattern as 📋 Activity
 * (next/stages/activity.js). It is NOT one of app.js's STAGES entries.
 *
 * SCOPE. Classic's Admin (index.html, `_ADMIN_GROUPS`) groups eleven panes
 * into three groups by "what a person came to do" (commit 4fb48071/26320f89):
 *
 *   Configure  Annotation Types, Groups, Discovery Sources, Question Catalog
 *   Reconcile  Egeria Alignment, Egeria Links, Publish Queue, Repair
 *   Observe    Prefect, Feedback, Logs
 *
 * (packages/resource-explorer/CLAUDE.md's own "Annotation Types registry,
 * resource Groups, and the Schedules overview" description is now stale on
 * two counts: Schedules moved to Automate's own sub-tab on 2026-08-13, and
 * Feedback/Logs were added under Observe on 2026-08-31/09-01 — eleven panes
 * total today, not the "ten classic admin views" PLAN-FINISH-REPOS.md
 * expected; see ITEM-5-ADMIN-IMPLEMENTED.md for the reconciliation.)
 *
 * Eight panes are real ports here — Annotation Types (browse), Question
 * Catalog (browse), Logs, Feedback, Prefect, Discovery Sources (full CRUD +
 * preview-then-apply refresh + preview-then-import run — see
 * discovery_sources.js's own header and
 * docs/design-notes/DISCOVERY-SOURCES-ADMIN-IMPLEMENTED.md), and (2026-09-20,
 * SPEC-ADMIN-THE-FOUR-GAPS.md §1) Egeria Alignment and Repair, built as TWO
 * separate panes because classic has them as two separate screens doing
 * different jobs — see admin/resync.js and admin/repair.js's own header
 * comments for why folding them together would be wrong. Three remain
 * DELIBERATE, NAMED deferrals: Groups, Egeria Links and Publish Queue are
 * reconciliation/config-mutation surfaces whose classic implementations run
 * 200-1000+ lines each (bulk GitHub-org import and drag-drop membership for
 * Groups; a divergence-repair flow for Egeria Links; retry semantics tied
 * to outbox internals for Publish Queue) — see DEFERRED_TABS below for the
 * per-pane reason, each linking out to classic via the shared `oldUiHref()`
 * helper.
 */
import { $, esc, icon, oldUiHref } from '/static/next/app.js';
import { renderAnnotationTypes } from '/static/next/admin/annotation_types.js';
import { renderQuestionCatalog } from '/static/next/admin/question_catalog.js';
import { renderLogs } from '/static/next/admin/logs.js';
import { renderFeedback } from '/static/next/admin/feedback.js';
import { renderPrefect } from '/static/next/admin/prefect.js';
import { renderResync } from '/static/next/admin/resync.js';
import { renderRepair } from '/static/next/admin/repair.js';
import { renderDiscoverySources } from '/static/next/admin/discovery_sources.js';

const PANEL_ID = 'admin-panel';

/** Same grouping and order as classic's `_ADMIN_GROUPS` — a person who knows
 *  the current UI should find the same three groups here, not a reshuffled
 *  version of them. `render` is set only for the seven built panes; a
 *  deferred one carries `defer` naming exactly what and why instead. */
const GROUPS = [
  { name: 'Configure', tabs: [
    { id: 'annotations', label: '📝 Annotation Types', render: renderAnnotationTypes },
    { id: 'admin-groups', label: '🗂 Groups', defer: {
      does: 'Create/rename/delete resource Groups, assign members by drag-and-drop, '
        + 'and bulk-register a whole GitHub org into the catalog',
      why: "classic's Groups pane is ~900 lines and covers three separable jobs "
        + '(group CRUD, per-repo group assignment, and org-wide GitHub discovery/'
        + 'import) that would each need their own design pass here rather than a '
        + 'straight port; see next/admin/index.js',
    } },
    { id: 'admin-discovery-sources', label: '🔍 Discovery Sources', render: renderDiscoverySources },
    { id: 'admin-question-catalog', label: '❓ Question Catalog', render: renderQuestionCatalog },
  ]},
  { name: 'Reconcile', tabs: [
    { id: 'admin-resync', label: '🔄 Egeria Alignment', render: renderResync },
    { id: 'admin-egeria-links', label: '🔗 Egeria Links', defer: {
      does: "Reconcile a resource's local record against the Egeria asset(s) it "
        + 'should be linked to, and repair a missing or wrong link',
      why: 'same shape as Egeria Alignment above — a reconciliation surface whose '
        + 'repair actions write to the shared Egeria catalog, not a read-only view',
    } },
    { id: 'admin-outbox', label: '📤 Publish Queue', defer: {
      does: 'Show queued/failed publish attempts to Egeria and retry them',
      why: "retry semantics are tied to the outbox's own internal state machine "
        + '(routes/outbox.py) in a way a read-only port would misrepresent — a '
        + 'queue view that cannot retry is not the pane, and one that can needs '
        + 'the same live-write caution as the two panes above',
    } },
    { id: 'admin-repair', label: '🔧 Repair', render: renderRepair },
  ]},
  { name: 'Observe', tabs: [
    { id: 'admin-prefect', label: '⚡ Prefect', render: renderPrefect },
    { id: 'admin-feedback', label: '💬 Feedback', render: renderFeedback },
    { id: 'admin-logs', label: '📜 Logs', render: renderLogs },
  ]},
];

const ALL_TABS = GROUPS.flatMap((g) => g.tabs);

/** Local, per-open state — not persisted, not on app.js's `state`. Mirrors
 *  activity.js's `panel` object: this is view state for one overlay, not
 *  something any other pane reads. */
const panel = { tab: 'annotations' };

function closeAdminPanel() {
  document.getElementById(PANEL_ID)?.remove();
  document.removeEventListener('keydown', onPanelKeydown);
}

function onPanelKeydown(e) {
  if (e.key === 'Escape') closeAdminPanel();
}

function deferredHtml(tab) {
  return `
    <h3 class="m-0 font-heading text-name font-normal text-ink">${esc(tab.label)} · not built in /next</h3>
    <div class="my-s3 h-px bg-rule"></div>
    <p class="max-w-[70ch] text-answer text-ink">${esc(tab.defer.does)}.</p>
    <p class="max-w-[70ch] text-caveat text-ink-muted">Deferred, deliberately: ${esc(tab.defer.why)}.</p>
    <p class="max-w-[70ch] text-answer text-ink">
      <a href="${esc(oldUiHref())}" class="text-accent-ink underline"
        >Open Admin → ${esc(tab.label.replace(/^\S+\s/, ''))} in the current UI</a>
      ${icon('external-link', { size: 13, cls: 'text-accent-ink' })}
    </p>`;
}

function groupSelectHtml(group) {
  const holdsActive = group.tabs.some((t) => t.id === panel.tab);
  const active = group.tabs.find((t) => t.id === panel.tab);
  return `<label class="flex items-center gap-[6px]">
    <span class="text-caps uppercase tracking-caps ${holdsActive ? 'text-accent-ink' : 'text-ink-muted'}">${esc(group.name)}</span>
    <select data-admin-group="${esc(group.name)}"
      title="${esc(group.name)}${holdsActive ? ` — showing ${esc(active.label)}` : ''}"
      class="cursor-pointer rounded-sm border px-2 py-[2px] text-caveat
        ${holdsActive ? 'border-accent text-accent-ink' : 'border-rule-strong text-ink-muted hover:text-ink'}">
      <option value="" ${holdsActive ? '' : 'selected'} disabled>${esc(group.name)}…</option>
      ${group.tabs.map((t) => `<option value="${esc(t.id)}" ${t.id === panel.tab ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}
    </select>
  </label>`;
}

function renderSubnav() {
  const host = document.getElementById('admin-panel-subnav');
  if (!host) return;
  host.innerHTML = GROUPS.map(groupSelectHtml).join('');
  host.querySelectorAll('[data-admin-group]').forEach((sel) => sel.addEventListener('change', () => {
    if (!sel.value) return;
    panel.tab = sel.value;
    renderSubnav();
    renderBody();
  }));
}

async function renderBody() {
  const host = document.getElementById('admin-panel-body');
  if (!host) return;
  const tab = ALL_TABS.find((t) => t.id === panel.tab);
  if (!tab) { host.innerHTML = '<p class="text-answer text-ink-muted">Unknown pane.</p>'; return; }
  if (!tab.render) { host.innerHTML = deferredHtml(tab); return; }
  host.innerHTML = '<p class="text-answer text-ink-muted">Loading…</p>';
  try {
    await tab.render(host);
  } catch (err) {
    host.innerHTML = `<p class="max-w-[70ch] text-answer text-state-warn">Could not load ${
      esc(tab.label)}: ${esc(err.message)}</p>`;
  }
}

/** Open the panel, freshly on every open — same reasoning as
 *  openActivityPanel: state (schedules, logs, feedback) keeps changing while
 *  the panel is closed, and reopening on the last-fetched data would misreport
 *  it. */
export async function openAdminPanel() {
  closeAdminPanel();
  panel.tab = 'annotations';

  const el = document.createElement('div');
  el.id = PANEL_ID;
  el.className = 'fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-s4 overflow-auto';
  el.innerHTML = `
    <div class="mt-[3vh] w-full max-w-[920px] rounded bg-paper p-s4 shadow-lg"
      role="dialog" aria-modal="true" aria-label="Admin">
      <div class="flex items-start justify-between gap-s3">
        <div>
          <div class="font-heading text-name text-ink">⚙ Admin</div>
          <div class="mt-[2px] text-caveat text-ink-muted">System and catalog configuration — not
            something a user does to curate a specific resource, so it lives here rather than
            under one of the eight intents.</div>
        </div>
        <button type="button" data-act="close" class="text-ink-muted hover:text-ink" aria-label="Close">×</button>
      </div>
      <div class="my-s3 h-px bg-rule"></div>
      <div id="admin-panel-subnav" class="mb-s3 flex flex-wrap items-center gap-s4"></div>
      <div id="admin-panel-body" class="max-h-[64vh] overflow-y-auto text-caveat text-ink-muted"></div>
    </div>`;
  document.body.appendChild(el);
  el.addEventListener('click', (e) => {
    if (e.target === el || e.target.closest('[data-act="close"]')) closeAdminPanel();
  });
  document.addEventListener('keydown', onPanelKeydown);

  renderSubnav();
  await renderBody();
}
