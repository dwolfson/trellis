/* Automate — the 8th intent: local-first notification subscriptions plus
 * the global Schedules overview (packages/resource-explorer/CLAUDE.md's
 * Automate section; docs/discovery-automate-project-context-plan.md Part 4).
 *
 * PLAN-FINISH-REPOS.md item 4 asked for either a real port of the classic
 * `index.html` Automate view or an honest defer. This is a real, DELIBERATELY
 * PARTIAL port:
 *
 *   - VIEWING and TOGGLING subscriptions (🔔 Subscriptions) is built here,
 *     against the same `/api/automate/subscriptions` routes classic uses.
 *   - VIEWING and DELETING the global Schedules overview (⏱ Schedules) is
 *     built here too, against `/api/schedules/`.
 *   - CREATING a subscription is NOT built here, and that is the honest
 *     boundary, not a corner cut. Classic creates one from a "🔔 Notify me"
 *     button on an Assessment/Analysis CARD (index.html, `_notifyMe` /
 *     "Cross-stage definitions"). Assessment and Analysis are now built
 *     stages in /next (item 11), but through the generic Questions-checklist
 *     engine -- QUESTION ROWS, not the card grid classic's Notify-me button
 *     is attached to. That card grid still has no /next equivalent, so the
 *     gap this section describes is unchanged even though the stages
 *     themselves are no longer "not in /next" (see `STAGES` in app.js).
 *     Building a standalone create-subscription form here, detached from the
 *     card it is supposed to sit on, would recreate the exact half-built-
 *     feature outcome PLAN-FINISH-REPOS.md's own stub comment warns against.
 *     So creation stays a link into the current UI (`oldUiHref`), same
 *     pattern as the RFA drawer and every deferred sub-tab in app.js -- the
 *     difference is that here it names the ONE missing piece rather than
 *     deferring the whole stage.
 *
 * Like Understanding (next/stages/understanding.js), Automate bypasses the
 * generic Questions-checklist engine entirely -- `loadPane()` in app.js
 * calls `renderAutomate()` directly for `state.stage === 'automate'` and
 * returns. It also bypasses the standard SUB_TABS row: classic's Automate
 * view has its own two-tab subnav (Subscriptions / Schedules), unrelated to
 * Questions/Survey/By analysis/Disposition, and showing that strip here
 * would offer four tabs that mean nothing for this stage.
 */
import { ago } from '/static/next/format.js';
import {
  listSubscriptions, setSubscriptionActive, listAllSchedules, deleteSchedule, runScheduleNow,
} from '/static/re-api.js';
import { state, esc, $, icon, oldUiHref } from '/static/next/app.js';

// Module-local, not on `state`: which of Automate's two sub-tabs is showing,
// and whether the subscriptions list is filtered to the selected resource.
// Mirrors classic's `_automateSubTab`/`_automateFilterToSelected` -- this is
// view state for one pane, not something any other stage reads.
let _tab = 'subscriptions';
let _filterToSelected = false;

function subnavHtml() {
  const tabs = [
    ['subscriptions', '🔔 Subscriptions'],
    ['schedules', '⏱ Schedules'],
  ];
  return `<div class="mb-s4 flex items-center gap-s4 font-heading text-subtab text-ink">
    ${tabs.map(([id, label]) => `
      <button data-automate-tab="${id}"
        class="cursor-pointer border-0 bg-transparent pb-[2px] ${
          _tab === id ? 'border-b border-accent text-ink' : 'text-ink-muted hover:text-ink'}"
        >${esc(label)}</button>`).join('')}
    <span class="ml-auto text-caps uppercase tracking-caps text-ink-muted">Automate</span>
  </div>`;
}

function bindSubnav(rerender) {
  $('content').querySelectorAll('[data-automate-tab]').forEach((b) =>
    b.addEventListener('click', () => { _tab = b.dataset.automateTab; rerender(); }));
}

export async function renderAutomate() {
  if (_tab === 'schedules') return renderSchedules();
  return renderSubscriptions();
}

/* ── 🔔 Subscriptions ──────────────────────────────────────────────────── */

async function renderSubscriptions() {
  const el = $('content');
  el.innerHTML = `${subnavHtml()}<p class="text-answer text-ink-muted">Loading…</p>`;
  bindSubnav(renderAutomate);

  const slug = state.selectedSlug;
  let subs;
  try {
    subs = await listSubscriptions(
      _filterToSelected && slug ? { entityType: state.resourceType, entitySlug: slug } : {});
  } catch (err) {
    el.innerHTML = `${subnavHtml()}
      <p class="max-w-[70ch] text-answer text-state-warn">Could not load subscriptions: ${esc(err.message)}</p>`;
    bindSubnav(renderAutomate);
    return;
  }

  const filterToggle = slug
    ? `<label class="ml-s3 inline-flex cursor-pointer items-center gap-[5px] text-caveat text-ink-muted">
         <input type="checkbox" data-automate-filter ${_filterToSelected ? 'checked' : ''}>
         Just <span class="font-mono">${esc(slug)}</span>
       </label>`
    : '';

  const rows = subs.map((s) => {
    // An active subscription with no recurring schedule for the same
    // analysis can never fire -- detection only runs off scheduled
    // completions (registry.py / scheduler._check_subscriptions). Said on
    // the row itself, not just at creation time, because the condition can
    // become true later (a schedule someone else removed).
    const status = !s.active
      ? '<span class="text-ink-muted">○ inactive</span>'
      : s.has_schedule === false
        ? `<span class="text-state-warn" title="Detection only runs off scheduled runs. Set a cadence for '${
            esc(s.analysis_id)}' on this resource in the ⏱ Schedules tab, or from the analysis card's ⏱ Schedule action."
            >● active — but never fires (no schedule)</span>`
        : '<span class="text-state-ok">● active</span>';
    const checked = s.last_checked_at ? `checked ${esc(ago(s.last_checked_at))}`
      : (s.active && s.has_schedule === false ? 'never — no schedule to run off' : 'never checked yet');
    const notified = s.notification_count > 0
      ? `🔔 notified <span class="tnum">${s.notification_count}</span>×${
          s.last_notified_at ? ` (last ${esc(ago(s.last_notified_at))})` : ''}`
      : '<span class="text-ink-muted">never notified</span>';
    return `<tr class="border-b border-rule">
      <td class="py-s2 pr-s3 text-answer text-ink">${esc(s.label || s.analysis_id)}</td>
      <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc(s.entity_type)}/${esc(s.entity_slug)}</td>
      <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc(s.analysis_id)}</td>
      <td class="py-s2 pr-s3 text-caveat">${status}</td>
      <td class="py-s2 pr-s3 text-caveat text-ink-muted" title="${esc(checked)}">${esc(checked)}</td>
      <td class="py-s2 pr-s3 text-caveat">${notified}</td>
      <td class="py-s2">
        <button data-toggle-sub="${s.id}" data-next-active="${s.active ? '0' : '1'}"
          class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px]
                 text-caveat text-ink hover:border-accent">${s.active ? 'Deactivate' : 'Activate'}</button>
      </td>
    </tr>`;
  }).join('');

  el.innerHTML = `${subnavHtml()}
    <div class="mb-s3 flex items-center">
      <h3 class="m-0 font-heading text-name font-normal text-ink">Subscriptions</h3>
      ${filterToggle}
    </div>
    <p class="max-w-[70ch] text-caveat text-ink-muted">
      A subscription watches an analysis for change on its <em>scheduled</em> runs (see ⏱ Schedules --
      one with no active schedule for its analysis never fires) and delivers via the RFA drawer when
      something changes. Creating one rides on the "🔔 Notify me" action on an Assessment/Analysis
      card, and those stages are not built in /next yet --
      <a href="${esc(oldUiHref())}" class="text-accent-ink underline">open ${
        slug ? `<span class="font-mono">${esc(slug)}</span>` : 'the current UI'
      } to create one</a> ${icon('external-link', { size: 12, cls: 'text-accent-ink' })}.
    </p>
    <div class="my-s3 h-px bg-rule"></div>
    ${subs.length ? `<table class="w-full text-left">
      <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
        <th class="pb-s2 pr-s3 font-normal">Watching</th>
        <th class="pb-s2 pr-s3 font-normal">Resource</th>
        <th class="pb-s2 pr-s3 font-normal">Analysis</th>
        <th class="pb-s2 pr-s3 font-normal">Status</th>
        <th class="pb-s2 pr-s3 font-normal">Last checked</th>
        <th class="pb-s2 pr-s3 font-normal">Notifications</th>
        <th class="pb-s2 font-normal"></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>` : `<p class="text-answer text-ink-muted">
      No subscriptions${_filterToSelected && slug ? ` for ${esc(slug)}` : ''} yet.</p>`}`;

  bindSubnav(renderAutomate);
  const filterBox = el.querySelector('[data-automate-filter]');
  if (filterBox) {
    filterBox.addEventListener('change', () => {
      _filterToSelected = filterBox.checked;
      renderSubscriptions();
    });
  }
  el.querySelectorAll('[data-toggle-sub]').forEach((b) => b.addEventListener('click', async () => {
    const id = b.dataset.toggleSub;
    const nextActive = b.dataset.nextActive === '1';
    b.disabled = true;
    b.textContent = 'Saving…';
    try {
      await setSubscriptionActive(id, nextActive);
      renderSubscriptions();
    } catch (err) {
      b.disabled = false;
      b.textContent = `Not saved: ${err.message}`;
    }
  }));
}

/* ── ⏱ Schedules ───────────────────────────────────────────────────────── */

const RESOURCE_ICON = { repo: '📁', database: '🗄', filesystem: '💾' };

async function renderSchedules() {
  const el = $('content');
  el.innerHTML = `${subnavHtml()}<p class="text-answer text-ink-muted">Loading…</p>`;
  bindSubnav(renderAutomate);

  let schedules;
  try {
    schedules = await listAllSchedules();
  } catch (err) {
    el.innerHTML = `${subnavHtml()}
      <p class="max-w-[70ch] text-answer text-state-warn">Could not load schedules: ${esc(err.message)}</p>`;
    bindSubnav(renderAutomate);
    return;
  }

  const rows = schedules.map((s) => {
    const status = !s.last_run_status
      ? '<span class="text-ink-muted">— not run yet</span>'
      : s.last_run_status === 'error'
        ? '<span class="text-state-warn">⚠ error</span>'
        : '<span class="text-state-ok">✓ ok</span>';
    const cadence = s.enabled ? s.schedule : `${s.schedule} (disabled)`;
    return `<tr class="border-b border-rule">
      <td class="py-s2 pr-s3 text-caveat text-ink">${RESOURCE_ICON[s.entity_type] || '•'} ${esc(s.entity_slug)}</td>
      <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc(s.analysis_id)}</td>
      <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc(cadence)}</td>
      <td class="py-s2 pr-s3 text-caveat">${status}</td>
      <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc((s.last_run || '—').replace('T', ' ').slice(0, 16))}</td>
      <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc((s.next_run || '—').replace('T', ' ').slice(0, 16))}</td>
      <td class="py-s2 pr-s3">
        <button data-run-sched="${esc(s.entity_type)}|${esc(s.entity_slug)}|${esc(s.analysis_id)}"
          title="Run this scheduled analysis now, through the same dispatch the timer uses. Does not change its next scheduled run."
          class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px]
                 text-caveat text-accent-ink">Run now</button>
      </td>
      <td class="py-s2">
        <button data-delete-sched="${esc(s.entity_type)}|${esc(s.entity_slug)}|${esc(s.analysis_id)}"
          title="Remove this schedule"
          class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px]
                 text-caveat text-state-warn hover:border-state-warn">Remove</button>
      </td>
    </tr>`;
  }).join('');

  el.innerHTML = `${subnavHtml()}
    <h3 class="m-0 font-heading text-name font-normal text-ink">Schedules overview</h3>
    <p class="max-w-[70ch] text-caveat text-ink-muted">
      Every scheduled analysis across every resource -- what a 🔔 subscription actually needs to fire.
      To add or change a schedule, use the ⏱ Schedule action on the analysis card itself
      (Assessment / Analysis / Discovery, not built in /next) --
      <a href="${esc(oldUiHref())}" class="text-accent-ink underline">open the current UI</a>
      ${icon('external-link', { size: 12, cls: 'text-accent-ink' })} to add one. This view is for
      monitoring and removing stale entries, not for editing individual cadences.
    </p>
    <div class="my-s3 h-px bg-rule"></div>
    ${schedules.length ? `<table class="w-full text-left">
      <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
        <th class="pb-s2 pr-s3 font-normal">Resource</th>
        <th class="pb-s2 pr-s3 font-normal">Analysis</th>
        <th class="pb-s2 pr-s3 font-normal">Cadence</th>
        <th class="pb-s2 pr-s3 font-normal">Last run</th>
        <th class="pb-s2 pr-s3 font-normal">When</th>
        <th class="pb-s2 pr-s3 font-normal">Next run</th>
        <th class="pb-s2 pr-s3 font-normal"></th>
        <th class="pb-s2 font-normal"></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>` : '<p class="text-answer text-ink-muted">No schedules yet.</p>'}`;

  bindSubnav(renderAutomate);
  el.querySelectorAll('[data-run-sched]').forEach((b) => b.addEventListener('click', async () => {
    const [entityType, entitySlug, analysisId] = b.dataset.runSched.split('|');
    const original = b.textContent;
    b.disabled = true;
    // No timed "started" toast — classic's own runScheduleNow comment notes
    // some analyses run for minutes, and a toast that expires mid-run would
    // leave the same silent gap. The button IS the progress indicator.
    b.textContent = 'Running…';
    try {
      const result = await runScheduleNow(entityType, entitySlug, analysisId);
      const errs = result?.errors || [];
      b.textContent = errs.length ? `Ran with ${errs.length} error(s)` : 'Ran now';
      renderSchedules();
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 404 ? 'No schedule' : `Not run: ${err.message}`;
      setTimeout(() => { b.textContent = original; }, 4000);
    }
  }));
  el.querySelectorAll('[data-delete-sched]').forEach((b) => b.addEventListener('click', async () => {
    const [entityType, entitySlug, analysisId] = b.dataset.deleteSched.split('|');
    if (!window.confirm(`Remove the ${analysisId} schedule for ${entitySlug}?`)) return;
    b.disabled = true;
    try {
      await deleteSchedule(entityType, entitySlug, analysisId);
      renderSchedules();
    } catch (err) {
      b.disabled = false;
      b.textContent = `Not removed: ${err.message}`;
    }
  }));
}
