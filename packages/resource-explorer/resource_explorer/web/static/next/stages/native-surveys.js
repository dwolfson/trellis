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
  registerWithEgeria, checkNativeSurveyPointers,
} from '/static/re-api.js';
import { state, esc, apiEntityType } from '/static/next/app.js';
import { openDialog } from '/static/next/worklist.js';

const POLL_MS = 8000;
const CONFIRM_MS = 6000;      // how long "Confirm: start again" stays armed

/** The state -> glyph-family mapping. Words come from the row, not from here:
 *  a glyph's own `word` is only its title. */
function glyphFor(run, runnable, row = {}) {
  // A registration that existed and is gone, and a database never given to Egeria, are NOT errors:
  // each has its own muted cue (registering with Egeria is optional; nothing is owed).
  if (row.stale) return 'gone';
  switch (run.state) {
    case 'complete': case 'registered': return 'measured';
    case 'failed': case 'submit_failed': return 'error';
    case 'submitted': case 'running': case 'awaiting_report': case 'report_incomplete':
    case 'awaiting_registration': return 'running';
    case 'unreadable': return 'unknown';
    case 'not_registered': return row.cannot_run_reason ? 'no-surveyor' : 'optional';
    default:
      if (row.neutral) return 'optional';
      return runnable ? 'unrun' : 'no-surveyor';
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
    case 'registered':
      return `registered with Egeria${row.asset_guid
        ? ` · database asset <span class="font-mono" title="Egeria database asset">${esc(row.asset_guid)}</span>` : ''}`;
    case 'awaiting_registration':
      return `Egeria says <span class="font-mono">${esc(r.egeria_status)}</span> · read ${timeSpan(r.read_at)}`
        + ' — the database is not readable in Egeria yet';
    case 'not_registered':
      // A kind RE cannot register says exactly why (not wired yet, or what the record lacks); a stale
      // pointer says so; otherwise this is the plain optional state.
      return row.cannot_run_reason
        ? `<span class="text-ink-muted">can't be registered from here — ${esc(row.cannot_run_reason)}</span>`
        : (row.stale
          ? `<span class="text-ink-muted">${esc('the Egeria asset RE had stored no longer exists')}</span>`
          : '<span class="text-ink-muted">not registered with Egeria · optional</span>');
    default:
      if (row.stale) return `<span class="text-ink-muted">${esc(row.cannot_run_reason)}</span>`;
      if (row.neutral) return `<span class="text-ink-muted">${esc(row.cannot_run_reason)}</span>`;
      return row.runnable
        ? 'not run'
        : `<span class="text-ink-muted">can't be run from here — ${esc(row.cannot_run_reason)}</span>`;
  }
}

/** The databases a server survey found, exactly as Egeria reported them. A database RE has registered and
 *  Egeria has no asset for is "found, not yet cataloged", with the one control. */
export function discoveredDatabasesHtml(row) {
  const found = row.discovered || [];
  if (!found.length) return '';
  return `<div class="mt-s2" data-native-discovered>
    <div class="text-caps uppercase tracking-caps text-ink-muted">Databases Egeria found on this server</div>
    ${found.map((d) => `<div class="flex flex-wrap items-baseline gap-s2 py-[2px]">
      <span class="font-mono text-ink">${esc(d.name)}</span>
      <span class="text-provenance text-ink-muted">${
        d.state === 'cataloged' ? 'cataloged in Egeria'
          : (d.re_slug ? 'found, not yet cataloged' : 'found · not registered in RE')}</span>
      ${d.control ? `<button type="button" data-native-register-slug="${esc(d.re_slug)}"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-caveat text-accent-ink"
        >${esc(d.control)}</button>` : ''}
    </div>`).join('')}
  </div>`;
}

/** Egeria's own sentence is in the status above, unchanged. When it reads as a connection problem the
 *  server adds one line, and RE's own survey stays available. */
function reachNoteHtml(row) {
  return row.reach_note
    ? `<div class="mt-[2px] text-provenance text-ink-muted" data-native-reach>${esc(row.reach_note)}</div>` : '';
}

/** One survey row: glyph, name, kind, status, and Run when RE can run it. */
export function nativeSurveyRowHtml(row) {
  const run = row.run || { state: 'not_run' };
  const g = stateGlyph(glyphFor(run, row.runnable, row));
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
      ${reachNoteHtml(row)}
      ${(row.notes || []).map((n) => `<div class="mt-[2px] text-provenance text-ink-muted" data-native-note>${esc(n)}</div>`).join('')}
      ${row.description ? `<div class="mt-[2px] max-w-[70ch] text-provenance text-ink-muted">${esc(row.description)}</div>` : ''}
      ${discoveredDatabasesHtml(row)}
    </div>
    ${(!row.runnable && row.register && row.register.available) ? `<button type="button" data-native-register="${esc(row.qualified_name)}" ${row.register.start_again ? `data-native-start-again="1" data-native-confirm="${esc(row.register.confirm || '')}"` : ''} ${busy ? 'disabled' : ''}
      class="shrink-0 cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-caveat text-accent-ink"
      >${esc(row.register.label)}</button>` : ''}
    ${row.runnable ? `<button type="button" data-native-run="${esc(row.qualified_name)}" ${busy ? 'disabled' : ''}
      class="shrink-0 cursor-pointer rounded-sm border ${busy ? 'border-rule-strong text-ink-muted' : 'border-accent text-accent-ink'} bg-transparent px-2 py-[2px] text-caveat"
      >${busy ? 'in flight' : (ran ? 'Run again in Egeria →' : 'Run in Egeria →')}</button>` : ''}
    <span data-native-info="${esc(row.qualified_name)}" class="hidden w-full text-provenance text-ink-muted"></span>
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

/** A failed native-survey read is not "no native surveys": the section keeps
 *  its heading and says the read failed, with a re-check. Never drawn as nothing. */
export function nativeSurveysUnreadableHtml() {
  return `<div class="mt-s3 mb-s3" id="native-surveys-unreadable">
    <div class="text-caps uppercase tracking-caps text-ink-muted">Egeria's own surveys</div>
    <div class="text-caveat text-state-warn">? couldn't read Egeria's surveys ·
      <button type="button" data-native-recheck class="cursor-pointer bg-transparent underline">re-check</button></div>
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
        if (err.status === 422) await checkPointers();     // a stale pointer is found by a READ, then the row offers the control
        if (err.status === 502) {
          try { paint((await getNativeSurveys(slug, { entityType: apiEntityType(state.resourceType) })).surveys); }
          catch (_) { /* the message above already says what happened */ }
        }
      }
    }));
    // Registering is a choice made with a press. The press shows at once that it was pressed
    // (disabled, "registering…"), and the result repaints from the server's rows -- never from the click.
    const showInfo = (qn, msg) => {
      const slot = [...host.querySelectorAll('[data-native-info]')].find((e) => e.dataset.nativeInfo === qn);
      if (!slot || !msg) return;
      slot.textContent = msg;
      slot.classList.remove('hidden');
    };
    // The confirm is a state of the button: it must not outlive its moment. Reset after a refused or
    // failed press, and on a timer, so a later click can never send without asking again.
    const resetConfirm = (b) => {
      if (b.dataset.confirm !== '1') return;
      clearTimeout(b._confirmTimer);
      delete b.dataset.confirm;
      if (b.dataset.label) b.textContent = b.dataset.label;
      b.classList.remove('border-state-warn');
    };
    const register = async (b, targetSlug, qn, startAgain = false) => {
      if (startAgain && b.dataset.confirm !== '1') {
        // A second registration can create a second database: ask once, visibly, before sending it.
        b.dataset.confirm = '1';
        b.dataset.label = b.textContent;
        b.textContent = 'Confirm: start again';
        b.classList.add('border-state-warn');
        showInfo(qn, `${b.dataset.nativeConfirm || 'This submits a second registration to Egeria.'} Press again to confirm.`);
        b._confirmTimer = setTimeout(() => resetConfirm(b), CONFIRM_MS);
        return;
      }
      clearTimeout(b._confirmTimer);
      const label = b.dataset.label || b.textContent;
      b.disabled = true;
      b.textContent = 'registering…';
      try {
        const res = await registerWithEgeria(targetSlug, { entityType: apiEntityType(state.resourceType), startAgain });
        if (targetSlug === slug) {
          paint(res.surveys);
          const proj = (res.registered && res.registered.projected) || {};
          // Said, never silent: the press may have written the local secrets file.
          showInfo(qn, proj.written ? 'RE re-projected the secrets file (a local write) so Egeria can read this database\'s credentials' : '');
          showInfo(qn, proj.checked === false ? proj.reason : '');
        }
        else {
          b.textContent = 'registered · see that database';
        }
      } catch (err) {
        b.disabled = false;
        b.textContent = label;
        resetConfirm(b);
        b.classList.remove('border-state-warn');
        delete b.dataset.confirm;
        showError(qn || '', err.message);
        if (err.status === 502 && targetSlug === slug) {
          try { paint((await getNativeSurveys(slug, { entityType: apiEntityType(state.resourceType) })).surveys); }
          catch (_) { /* the message above already says what happened */ }
        }
      }
    };
    host.querySelectorAll('[data-native-register]').forEach((b) => b.addEventListener('click',
      () => register(b, slug, b.dataset.nativeRegister, !!b.dataset.nativeStartAgain)));
    host.querySelectorAll('[data-native-register-slug]').forEach((b) => b.addEventListener('click',
      () => register(b, b.dataset.nativeRegisterSlug, '')));
    host.querySelectorAll('[data-native-report]').forEach((b) => b.addEventListener('click',
      () => openReport(slug, b.dataset.nativeReport)));
  };

  // Read the stored pointer back from Egeria, once, ONLY when one is stored (registered rows carry the
  // database asset's GUID). A never-registered database makes no Egeria call at all.
  const checkPointers = async () => {
    try {
      const res = await checkNativeSurveyPointers(slug, { entityType: apiEntityType(state.resourceType) });
      if (alive()) paint(res.surveys);
    } catch (_) { /* the rows already on screen are what RE knows; a failed check says nothing */ }
  };

  // The rows were rendered by the pane from the same fetch; bind them, and
  // start polling only if any of them is in flight.
  bindRows();
  schedule();
  if (rows.some((r) => r.asset_guid)) checkPointers();
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
