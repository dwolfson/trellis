/* Egeria-native surveys on Survey & analyses (BRIEF-NATIVE-EGERIA-SURVEY-LAUNCH.md).
 *
 * A survey Egeria's own survey action engine can run for this kind of resource
 * gets a Run control that submits an engine action through pyegeria. Prefect
 * is not in this path.
 *
 * THE RULE THIS FILE EXISTS TO KEEP: every status word on a row comes from the
 * server's `run` object, which the server derived from persisted proof
 * (`native_survey_run.derive_native_state`). This file never decides "running"
 * or "complete" from what the browser just did -- a click that got a 200 is not
 * a submission, an absent error is not a success. It only chooses how to say
 * what the proof already says:
 *
 *   submitted to Egeria · <time>          engine-action GUID stored
 *   running · read <time>                 Egeria's own status, read back
 *   complete · read <time>                + report GUID + annotations stored
 *   <Egeria's word> · <message>           Egeria's own words on a failure
 *
 * A survey RE cannot run for this kind is a ◌ row that says why -- never a
 * "○ not run", which would tell the reader it merely has not been run yet.
 *
 * Re-renders replace `#native-surveys` only. The engine-note bug
 * (ENGINE-NOTE-PERSISTENCE-IMPLEMENTED.md) was a status written to a transient
 * DOM node that a whole-pane reload then wiped; nothing here is transient.
 */
import { ago } from '/static/next/format.js';
import { stateEntry } from '/static/next/glyphs.js';
import {
  getNativeSurveys, runNativeSurvey, refreshNativeSurveys, getNativeSurveyReport,
} from '/static/re-api.js';
import { state, esc, apiEntityType } from '/static/next/app.js';
import { openDialog } from '/static/next/worklist.js';

const POLL_MS = 8000;

/** The state -> glyph-family mapping. Words come from the row, not from here:
 *  a glyph's own `word` is only its title. */
function glyphFor(run, runnable) {
  switch (run.state) {
    case 'complete': return 'measured';
    case 'failed': case 'submit_failed': return 'error';
    case 'submitted': case 'running': case 'awaiting_report': case 'report_incomplete': return 'running';
    case 'unreadable': return 'unknown';
    default: return runnable ? 'unrun' : 'no-surveyor';
  }
}

function timeSpan(iso) {
  if (!iso) return '';
  return `<span class="tnum" title="${esc(iso)}">${esc(ago(iso))}</span>`;
}

function guidSpan(guid) {
  return guid ? `<span class="font-mono" title="Egeria engine action ${esc(guid)}">${esc(guid)}</span>` : '';
}

/** The one line of status. Pure over `row.run`. */
export function nativeSurveyStatusHtml(row) {
  const r = row.run || { state: 'not_run' };
  const err = r.error ? ` · <span class="text-state-warn">${esc(r.error)}</span>` : '';
  switch (r.state) {
    case 'submit_failed':
      return `<span class="text-state-warn">not submitted — Egeria did not accept it: ${esc(r.error)}</span>`;
    case 'submitted':
      return `submitted to Egeria · ${timeSpan(r.submitted_at)} · ${guidSpan(r.engine_action_guid)}`;
    case 'unreadable':
      return `submitted to Egeria · ${timeSpan(r.submitted_at)} · ${guidSpan(r.engine_action_guid)}`
        + ` · <span class="text-state-warn">last read failed: ${esc(r.error)}</span>`;
    case 'running':
      return `running · Egeria says <span class="font-mono">${esc(r.egeria_status)}</span>`
        + ` · read ${timeSpan(r.read_at)} · ${guidSpan(r.engine_action_guid)}${err}`;
    case 'awaiting_report':
      return `Egeria says <span class="font-mono">${esc(r.egeria_status)}</span> · read ${timeSpan(r.read_at)}`
        + ` — its report is not read into RE yet${err}`;
    case 'report_incomplete':
      return `Egeria says <span class="font-mono">${esc(r.egeria_status)}</span> · read ${timeSpan(r.read_at)}`
        + ` — <span class="text-state-warn">RE's copy of the report is incomplete; reading it again</span>${err}`;
    case 'complete':
      return `complete · read ${timeSpan(r.read_at)} · report from ${timeSpan(r.report_at)}`
        + ` · <button type="button" data-native-report="${esc(r.report_guid)}"
            class="cursor-pointer bg-transparent p-0 text-accent-ink underline"
            ><span class="tnum">${esc(String(r.annotation_count))}</span> annotation${
              r.annotation_count === 1 ? '' : 's'} ›</button>`;
    case 'failed':
      return `<span class="text-state-warn"><span class="font-mono">${esc(r.egeria_status)}</span>`
        + ` · ${esc(r.message)}</span> · read ${timeSpan(r.read_at)} · ${guidSpan(r.engine_action_guid)}`;
    default:
      return row.runnable
        ? 'not run'
        : `<span class="text-ink-muted">can't be run from here — ${esc(row.cannot_run_reason)}</span>`;
  }
}

/** One survey row: glyph, name, kind, status, and Run when RE can run it. */
export function nativeSurveyRowHtml(row) {
  const run = row.run || { state: 'not_run' };
  const g = stateGlyph(glyphFor(run, row.runnable));
  const busy = !!row.in_flight;
  const ran = run.state !== 'not_run';
  return `<div class="flex flex-wrap items-baseline gap-s2 border-b border-rule py-s2" data-native-survey="${esc(row.qualified_name)}">
    <span class="w-[16px] shrink-0 ${g.tone}" title="${esc(g.word)}" aria-label="${esc(g.word)}">${g.glyph}</span>
    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-baseline gap-s2">
        <span class="text-answer text-ink">${esc(row.display_name)}</span>
        <span class="text-provenance text-ink-muted">Egeria's own survey engine</span>
      </div>
      <div class="mt-[2px] text-provenance text-ink-muted" data-native-status>${nativeSurveyStatusHtml(row)}</div>
      ${row.credentials_note ? `<div class="mt-[2px] text-provenance text-ink-muted"><span class="text-ink-muted" title="not confirmed either way">?</span> ${esc(row.credentials_note)}</div>` : ''}
      ${row.description ? `<div class="mt-[2px] max-w-[70ch] text-provenance text-ink-muted">${esc(row.description)}</div>` : ''}
    </div>
    ${row.runnable ? `<button type="button" data-native-run="${esc(row.qualified_name)}" ${busy ? 'disabled' : ''}
      class="shrink-0 cursor-pointer rounded-sm border ${busy ? 'border-rule-strong text-ink-muted' : 'border-accent text-accent-ink'} bg-transparent px-2 py-[2px] text-caveat"
      >${busy ? 'in flight' : (ran ? 're-run →' : 'run →')}</button>` : ''}
    <span data-native-error="${esc(row.qualified_name)}" class="hidden w-full text-provenance text-state-warn"></span>
  </div>`;
}

const stateGlyph = stateEntry;

export function nativeSurveysSectionHtml(rows) {
  if (!rows || !rows.length) return '';
  return `<div class="mt-s3 mb-s3">
    <div class="text-caps uppercase tracking-caps text-ink-muted">Egeria's own surveys</div>
    <div class="text-caveat text-ink-muted">Run by Egeria's survey action engine; RE submits the
      action and reads back what Egeria says about it.</div>
    <div id="native-surveys">${rows.map(nativeSurveyRowHtml).join('')}</div>
  </div>`;
}

const _timers = new WeakMap();

/** Wire a rendered section: Run buttons, the annotations view, and the poll
 *  that runs only while something is in flight. Safe to call again on a fresh
 *  host; the previous host's timer dies with its detached node. */
export function bindNativeSurveys(root, slug, initialRows, { pollMs = POLL_MS } = {}) {
  const host = root.querySelector('#native-surveys');
  if (!host) return;
  let rows = initialRows || [];

  const paint = (next) => {
    rows = next;
    host.innerHTML = rows.map(nativeSurveyRowHtml).join('');
    bindRows();
    schedule();
  };
  const alive = () => host.isConnected && state.selectedSlug === slug && state.subTab === 'survey';
  const schedule = () => {
    clearTimeout(_timers.get(host));
    if (!rows || !rows.some((r) => r.in_flight)) return;
    _timers.set(host, setTimeout(async () => {
      if (!alive()) return;
      try {
        const res = await refreshNativeSurveys(slug, { entityType: apiEntityType(state.resourceType) });
        if (alive()) paint(res.surveys);
      } catch (_) { if (alive()) schedule(); }   // a failed poll is not a status; try again
    }, pollMs));
  };
  const showError = (qn, msg) => {
    const slot = [...host.querySelectorAll('[data-native-error]')].find((e) => e.dataset.nativeError === qn);
    if (!slot) return;
    slot.textContent = msg;
    slot.classList.remove('hidden');
  };
  const bindRows = () => {
    host.querySelectorAll('[data-native-run]').forEach((b) => b.addEventListener('click', async () => {
      const qn = b.dataset.nativeRun;
      b.disabled = true;
      try {
        const res = await runNativeSurvey(slug, qn, { entityType: apiEntityType(state.resourceType) });
        paint(res.surveys);
      } catch (err) {
        // 409 (already in flight) and 422 (RE knows why it cannot) are REASONS;
        // 502 (Egeria refused) is also persisted, so the repaint below shows it
        // on the row rather than only here.
        b.disabled = false;
        showError(qn, err.message);
        if (err.status === 502) {
          try { paint((await getNativeSurveys(slug, { entityType: apiEntityType(state.resourceType) })).surveys); }
          catch (_) { /* the message above already says what happened */ }
        }
      }
    }));
    host.querySelectorAll('[data-native-report]').forEach((b) => b.addEventListener('click',
      () => openReport(slug, b.dataset.nativeReport)));
  };

  // The rows were rendered by the pane from the same fetch; bind them, and
  // start polling only if any of them is in flight.
  bindRows();
  schedule();
}

async function openReport(slug, reportGuid) {
  const d = openDialog('Egeria survey report', reportGuid);
  const body = d.querySelector('#wl-detail-body');
  let rep;
  try {
    rep = await getNativeSurveyReport(slug, reportGuid, { entityType: apiEntityType(state.resourceType) });
  } catch (err) {
    body.innerHTML = `<p class="text-state-warn">${esc(err.message)}</p>`;
    return;
  }
  const anns = rep.annotations || [];
  body.innerHTML = `
    <div class="mb-s2 text-caps uppercase tracking-caps text-ink-muted">Report from ${
      esc(rep.report_at || 'an unrecorded time')} · read into RE ${esc(rep.read_at || '')}</div>
    <div class="mb-s2 text-provenance text-ink-muted">engine action <span class="font-mono">${esc(rep.engine_action_guid)}</span>
      · <span class="tnum">${anns.length}</span> annotation${anns.length === 1 ? '' : 's'}</div>
    ${anns.length ? `<ul class="max-w-[70ch] list-disc pl-s4">${anns.map((a) => `
      <li class="text-ink"><span class="text-ink-muted">${esc(a.annotation_type)}</span> — ${esc(a.summary)}</li>`).join('')}
    </ul>` : '<p class="text-ink-muted">Egeria completed this survey and its report holds no annotations.</p>'}`;
}
