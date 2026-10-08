/* Publish to Egeria -- the section of Curate that says what Egeria holds for this resource.
 *
 * Parity slice G1 (PARITY-G1-IMPLEMENTED.md, rows PI-001..PI-009), Egeria on a repository. Classic
 * had an "Egeria" tab per repository; /next had a publish-state line in the resource header and nothing
 * else. There is no separate Publish stage in STAGES, so this is the fourth band of the Curate pane
 * ([data-curate-band="publish"], after the kind's own work), one component for every kind:
 *
 *   status    in Egeria or not, the asset GUID (copyable), and for a repository the last report row
 *   project   which Egeria project the publish names, or "no project" (PI-006)
 *   publish   "Publish to Egeria →", then "Publish again" (repository only; PI-001). Whole report, never
 *             scoped, no zone choice. A first press with no project answer shows the two choices.
 *   forget    "Forget Egeria links…" (repository only; PI-005): RE's registry only, Egeria untouched
 *   reports   ONE "Egeria reports" component for every kind (PI-003): `mountEgeriaReports`, exported
 *   file types  preview-then-commit (PI-004)
 *
 * THE RULE: every status word comes from what the server derived from proof rows (resource_explorer/
 * repo_publish.py). This file chooses how to say it; it never decides "published" from a click that got a
 * 200. Each action re-reads the state afterwards and draws from the re-read. A pressed control dims and
 * ignores a second press. State is shown by a glyph (the Egeria lane) plus a short word; the full Egeria
 * sentence is one gesture away (a <details>). Accent colors are for controls, never states.
 *
 * `mountEgeriaReports(el, { entityType, slug, inEgeria, onAsk })` is the entry point stage code reuses
 * (G3's runs dialog links a report GUID into it). See PARITY-G1-IMPLEMENTED.md.
 */
import { ago } from '/static/next/format.js';
import { stateEntry } from '/static/next/glyphs.js';
import {
  getRepoPublishState, publishRepoReport, forgetEgeriaLinks, resurveyRepo,
  getEgeriaReports, getEgeriaReportAnnotations, getFileTypeMeasurements,
} from '/static/re-api.js';
import {
  state, esc, $, ensureRailShowing, copyAsEvidence, openCurrentInvestigationStage,
} from '/static/next/app.js';

/** The sentence a first press shows when no Egeria project answers (brief PI-006). */
export const NO_PROJECT_SENTENCE =
  'no Egeria project context · bind this investigation to a project, or publish without one';
/** What survives a "Forget Egeria links" (brief PI-005): roll-forward language, never "reset Egeria". */
export const FORGET_SENTENCE =
  'Egeria is unchanged; Resource Explorer forgets its cached GUIDs and survey history for this resource '
  + 'and re-reads them on the next publish.';

/* Buttons are built here, with their classes as literals in the markup: no dynamic class interpolation
 * (the class-coverage tripwire counts those, and a literal is what Tailwind's scanner can see). */
const button = (attrs, label, { disabled = false } = {}) =>
  `<button type="button" ${attrs} class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-caveat text-ink hover:border-accent disabled:cursor-default disabled:opacity-60"${disabled ? ' disabled' : ''}>${label}</button>`;

/** What the Publish button really does (repo_publish.publish_report, brief section 1): it publishes the
 *  survey ALREADY KEPT on this repository and reads the report back. It never runs a survey; "Re-survey
 *  now" is its own act, beside it. */
export const PUBLISH_SENTENCE =
  'Publishes the survey already kept on this repository to Egeria and reads the report back. '
  + 'It does not run a survey: Re-survey now does that, separately.';
/** The short words beside the button, idle and while it runs. */
export const PUBLISH_IDLE_WORDS = 'publishes the kept survey';
export const PUBLISH_RUNNING_WORDS = 'publishing the kept survey';
/** The sentence directly under a disabled Publish when nothing has been surveyed (brief section 1). */
export const NO_SURVEY_SENTENCE = 'no survey to publish yet · run the first survey';
/** What Re-survey now does, on hover. */
export const RESURVEY_SENTENCE =
  'Runs the survey on this repository and nothing else: nothing is sent to Egeria. The band then shows the new age.';
const linkButton = (attrs, label) =>
  `<button type="button" ${attrs} class="cursor-pointer bg-transparent text-accent-ink underline disabled:opacity-60">${label}</button>`;
const num = (n) => `<span class="tnum">${esc(n ?? 0)}</span>`;
const whoAmI = () => (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
const stale = (el, slug) => !el.isConnected || slug !== state.selectedSlug;

const cue = (stateKey, word, title = '') => {
  const e = stateEntry(stateKey);
  // The tone class is a literal in each branch (no class interpolation): ok, warn, or muted.
  const open = e.tone === 'text-state-ok' ? '<span class="text-state-ok"'
    : e.tone === 'text-state-warn' ? '<span class="text-state-warn"' : '<span class="text-ink-muted"';
  return `${open} data-cue="${esc(stateKey)}" title="${esc(title || e.word)}"><span class="font-glyph" aria-hidden="true">${e.glyph}</span> ${esc(word)}</span>`;
};

const guidHtml = (guid) => guid
  ? `<span class="font-mono" data-guid="${esc(guid)}">${esc(guid)}</span>
     ${linkButton(`data-copy-guid="${esc(guid)}" title="Copy the GUID"`, 'copy')}`
  : '';

function bindCopy(root) {
  root.querySelectorAll('[data-copy-guid]').forEach((b) => b.addEventListener('click', () =>
    copyAsEvidence(b.dataset.copyGuid, b)));
}

/** The full Egeria sentence, one gesture away. */
const detailsHtml = (full) => `<details class="inline"><summary class="inline cursor-pointer text-ink-muted underline">details</summary>
    <span class="block max-w-[70ch] whitespace-pre-wrap text-provenance text-ink-muted" data-egeria-sentence>${esc(full)}</span></details>`;

/** A sentence from Egeria: the first sentence shown, the rest one gesture away. */
const sentenceHtml = (first, full) => (!full || full === first) ? esc(first) : `${esc(first)} ${detailsHtml(full)}`;

/** Elements by attribute value without CSS.escape (a GUID is safe, but a label is not). */
const byAttr = (root, attr, value) => [...root.querySelectorAll(`[${attr}]`)].find((e) => e.getAttribute(attr) === value) || null;

/** The published report was made from an older survey than the kept one: a visible cue and a short word,
 *  the sentence on hover. Nothing when the two match, or when either date is unknown. */
export function behindCue(row, kept) {
  const a = Date.parse(row && row.surveyed_at);
  const b = Date.parse(kept && kept.exists ? kept.surveyed_at : '');
  if (Number.isNaN(a) || Number.isNaN(b) || a >= b) return '';
  return ` <span data-publish-behind>${cue('partial', 'behind', `The report in Egeria was made from the survey of ${String(row.surveyed_at).slice(0, 10)}; the kept survey is newer (${String(kept.surveyed_at).slice(0, 10)}). Publish again to bring it up to date.`)}</span>`;
}

/* ── the report row: words from the server's row, never from the click ─ */

/** `row` is `publish_state().row` from the server. Returns `{ state, html }`. */
export function reportRowHtml(row, keptSurvey = null) {
  switch (row?.word) {
    case 'published':
      return cue('measured', `published · ${row.surveyed_at ? `from the survey of ${row.surveyed_at.slice(0, 10)} · ` : ''}read back ${ago(row.read_at)}`)
        + behindCue(row, keptSurvey)
        + (row.reused ? ' <span class="text-provenance text-ink-muted">· reused the report already in Egeria</span>' : '')
        + (row.annotation_count != null ? ` <span class="text-provenance text-ink-muted">· ${num(row.annotation_count)} annotations</span>` : '');
    case 'sent':
      return cue('running', 'sent · waiting for Egeria')
        + (row.sentence && row.sentence !== 'sent · waiting for Egeria' ? ` <span class="text-provenance text-ink-muted">${esc(row.sentence)}</span>` : '');
    case 'not published':
      return cue('error', `not published · ${row.first || 'Egeria gave no sentence'}`)
        + (row.sentence && row.sentence !== row.first ? ` ${detailsHtml(row.sentence)}` : '');
    case 'forgotten':
      return cue('unrun', 'links forgotten · re-read on the next publish');
    default:
      return cue('unrun', 'no publish recorded here');
  }
}

function projectHtml(project) {
  if (!project || project.status === 'unset') {
    return `<span class="text-ink-muted">no project</span> <span class="text-provenance text-ink-muted">· the first press asks</span>`;
  }
  const name = project.name ? ` <span class="font-mono">${esc(project.name)}</span>` : '';
  const detail = project.detail ? ` <span class="text-provenance text-ink-muted">· ${esc(project.detail)}</span>` : '';
  return `<span class="text-ink">${esc(project.word)}</span>${name}${detail}`;
}

/* ── the one "Egeria reports" component (PI-003) ───────────────────────── */

const annotationRowHtml = (a) => `<li class="py-[2px] text-caveat" data-annotation="${esc(a.guid)}">
  <span class="text-ink">${esc(a.annotation_type)}</span>
  <span class="text-ink-muted">· ${esc(a.summary || '')}</span>
  ${a.confidence != null ? `<span class="tnum text-provenance text-ink-muted">· confidence ${esc(a.confidence)}</span>` : ''}
  ${a.analysis_step ? `<span class="text-provenance text-ink-muted">· ${esc(a.analysis_step)}</span>` : ''}
  ${a.content_status === 'DRAFT' ? '<span class="text-provenance text-ink-muted">· draft proposal</span>' : ''}
  ${a.explanation ? `<details class="inline"><summary class="inline cursor-pointer text-ink-muted underline">why</summary>
    <span class="block max-w-[70ch] whitespace-pre-wrap text-provenance text-ink-muted">${esc(a.explanation)}</span></details>` : ''}
</li>`;

export function reportRowListHtml(r) {
  const counts = r.schema_count || r.table_count || r.column_count
    ? ` · ${num(r.schema_count)} schemas · ${num(r.table_count)} tables · ${num(r.column_count)} columns` : '';
  return `<div class="border-t border-rule py-s1" data-egeria-report="${esc(r.guid)}">
    <div class="flex flex-wrap items-baseline gap-x-s2 text-caveat">
      <span class="text-ink">${esc(r.display_name || r.qualified_name)}</span>
      <span class="text-provenance text-ink-muted">surveyed ${r.surveyed_at ? esc(ago(r.surveyed_at)) : 'at an unknown time'}
        · ${num(r.annotation_count)} annotations${counts}</span>
      ${guidHtml(r.guid)}
      ${linkButton(`data-report-toggle="${esc(r.guid)}" aria-expanded="false"`, 'Show annotations')}
      ${linkButton(`data-report-ask="${esc(r.guid)}"`, 'Ask about this →')}
    </div>
    <div data-report-annotations="${esc(r.guid)}" class="ml-s3"></div>
  </div>`;
}

/** Chat-rail prefill (PI-008): the report's identity, nothing sent until the person presses Ask. */
export function askAboutText(entityType, slug, r) {
  return `Summarize the survey report "${r.display_name || r.qualified_name}" (Egeria GUID ${r.guid}`
    + `${r.surveyed_at ? `, surveyed ${r.surveyed_at}` : ''}) for the ${entityType} ${slug}.`;
}

function defaultAsk(text) {
  ensureRailShowing();
  const input = $('ask-input');
  if (!input) return false;
  input.value = text;
  input.focus();
  return true;
}

/** Mount the Egeria reports component into `el`.
 *  `entityType`  'repo' | 'database' | 'filesystem' (the API kind, never defaulted)
 *  `inEgeria`    whether the resource has an Egeria asset: with no asset the reader answers [] and that
 *                must read "not in Egeria", not "no reports"
 *  `onAsk`       optional (text) => boolean, replaces the chat-rail prefill
 *  Returns `{ refresh, expand(guid) }` so another stage can open one report. */
export function mountEgeriaReports(el, { entityType, slug, inEgeria, onAsk = defaultAsk }) {
  if (!entityType) throw new Error('mountEgeriaReports: entityType is required');
  let reports = [];
  const body = () => el.querySelector('[data-egeria-reports-body]');

  const frame = () => {
    el.innerHTML = `<div data-egeria-reports class="min-w-0">
      <div class="flex flex-wrap items-baseline gap-x-s2">
        <span class="text-answer text-ink">Egeria reports</span>
        ${button('data-reports-refresh', 'Refresh')}
        <span data-reports-status class="text-provenance text-ink-muted"></span>
      </div>
      <div data-egeria-reports-body class="mt-s1"></div></div>`;
    el.querySelector('[data-reports-refresh]').addEventListener('click', () => refresh());
  };

  const draw = () => {
    const b = body();
    if (!b) return;
    b.innerHTML = reports.map(reportRowListHtml).join('');
    bindCopy(b);
    b.querySelectorAll('[data-report-toggle]').forEach((t) =>
      t.addEventListener('click', () => toggle(t.dataset.reportToggle)));
    b.querySelectorAll('[data-report-ask]').forEach((t) => t.addEventListener('click', () => {
      const r = reports.find((x) => x.guid === t.dataset.reportAsk);
      if (r && !onAsk(askAboutText(entityType, slug, r))) {
        el.querySelector('[data-reports-status]').textContent = 'the chat rail could not be opened';
      }
    }));
  };

  async function toggle(guid) {
    const slot = byAttr(el, 'data-report-annotations', guid);
    const btn = byAttr(el, 'data-report-toggle', guid);
    if (!slot || !btn || btn.dataset.pending) return;
    if (btn.getAttribute('aria-expanded') === 'true') {
      slot.innerHTML = '';
      btn.setAttribute('aria-expanded', 'false');
      btn.textContent = 'Show annotations';
      return;
    }
    btn.dataset.pending = '1';
    btn.disabled = true;
    btn.textContent = 'Reading…';
    try {
      const rows = await getEgeriaReportAnnotations(entityType, slug, guid);
      slot.innerHTML = rows.length
        ? `<ul class="m-0 list-none p-0">${rows.map(annotationRowHtml).join('')}</ul>`
        : `<div class="text-caveat text-ink-muted">Egeria holds no annotations under this report.</div>`;
      btn.setAttribute('aria-expanded', 'true');
      btn.textContent = 'Hide annotations';
    } catch (err) {
      slot.innerHTML = `<div class="text-caveat text-state-warn">The annotations could not be read: ${esc(err.message)}</div>`;
      btn.textContent = 'Show annotations';
    } finally {
      btn.disabled = false;
      delete btn.dataset.pending;
    }
  }

  async function refresh() {
    if (!el.querySelector('[data-egeria-reports]')) frame();
    const status = el.querySelector('[data-reports-status]');
    const rbtn = el.querySelector('[data-reports-refresh]');
    if (rbtn.dataset.pending) return;
    rbtn.dataset.pending = '1';
    rbtn.disabled = true;
    status.textContent = 'reading Egeria…';
    try {
      if (!inEgeria) {
        reports = [];
        draw();
        body().innerHTML = `<div class="text-caveat text-ink-muted">Not in Egeria: there is no asset to list reports from.</div>`;
        status.textContent = '';
        return;
      }
      reports = await getEgeriaReports(entityType, slug);
      if (stale(el, slug)) return;
      draw();
      if (!reports.length) {
        body().innerHTML = `<div class="text-caveat text-ink-muted">Egeria holds no survey reports on this asset.</div>`;
      }
      status.textContent = `read ${new Date().toTimeString().slice(0, 5)} · ${reports.length} report${reports.length === 1 ? '' : 's'}`;
    } catch (err) {
      if (stale(el, slug)) return;
      reports = [];
      draw();
      body().innerHTML = `<div class="text-caveat text-state-warn" data-reports-error>Egeria could not be read: ${esc(err.message)}</div>`;
      status.textContent = '';
    } finally {
      rbtn.disabled = false;
      delete rbtn.dataset.pending;
    }
  }

  frame();
  const first = refresh();
  return {
    refresh,
    ready: first,
    async expand(guid) {
      await first;
      const btn = byAttr(el, 'data-report-toggle', guid);
      if (btn && btn.getAttribute('aria-expanded') !== 'true') await toggle(guid);
    },
  };
}

/* ── the Publish section ───────────────────────────────────────────────── */

function resourceRow(slug) {
  const rows = state.resourceType === 'db' ? state.databases
    : state.resourceType === 'filesystem' ? state.filesystems : state.projects;
  return (rows || []).find((r) => r.slug === slug) || null;
}

const head = '<div class="mb-s1 text-caps uppercase tracking-caps text-ink">Publish to Egeria</div>';

function nonRepoStatusHtml(entityType, slug) {
  const row = resourceRow(slug) || {};
  const guid = row.egeria_asset_guid || '';
  const note = row.egeria_publish_note
    ? ` <span class="text-provenance text-state-warn">${esc(row.egeria_publish_note)}</span>` : '';
  const how = entityType === 'database'
    ? 'A database reaches Egeria through Catalog → above (its survey report is published with it).'
    : 'A file system has no publish control here yet.';
  return `<div class="text-caveat" data-publish-status>${row.is_published
    ? cue('measured', 'in Egeria') + ` <span class="text-provenance text-ink-muted">· asset</span> ${guidHtml(guid)}`
    : cue('unrun', 'not in Egeria')}${note}</div>
    <div class="mt-s1 text-provenance text-ink-muted">${esc(how)}</div>`;
}

/** The survey a press would publish, before the press (brief section 1): its date, its age, its size,
 *  and how much of it is stale. Stale steps are NAMED, not auto-run: a ⚠ and the word "stale", the list
 *  one gesture away. With no survey: the sentence, and nothing else claims one exists. */
export function surveyLineHtml(survey) {
  if (!survey || !survey.exists) {
    return `<div class="mt-s1 text-caveat" data-publish-survey="none">${cue('unrun', survey?.sentence || NO_SURVEY_SENTENCE)}</div>`;
  }
  const date = String(survey.surveyed_at || '').slice(0, 10);
  const stale = survey.stale_steps
    ? `<div class="mt-[2px] text-caveat" data-publish-stale>${cue('partial', 'stale')}
        <span class="text-ink-muted">${num(survey.stale_steps)} of ${num(survey.steps)} steps are stale (older than their refresh rule) · re-survey to refresh</span>
        <details class="inline"><summary class="inline cursor-pointer text-ink-muted underline">which</summary>
          <span class="block font-mono text-provenance text-ink-muted">${(survey.stale || []).map(esc).join(', ')}</span></details></div>` : '';
  return `<div class="mt-s1 text-caveat" data-publish-survey="kept">kept survey · <span class="tnum">${esc(date)}</span>
      <span class="text-ink-muted">· ${esc(ago(survey.surveyed_at))} · ${num(survey.annotations)} annotations · ${num(survey.steps)} steps ran</span></div>${stale}`;
}

function repoStatusHtml(s) {
  return `<div class="text-caveat" data-publish-status>${s.in_egeria
    ? cue('measured', 'in Egeria') + ` <span class="text-provenance text-ink-muted">· asset</span> ${guidHtml(s.asset_guid)}`
    : cue('unrun', 'not in Egeria')}</div>
    <div class="mt-s1 text-caveat" data-publish-row>${reportRowHtml(s.row, s.survey)}</div>
    <div class="mt-s1 text-provenance text-ink-muted" data-publish-project>project · ${projectHtml(s.project)}</div>
    ${surveyLineHtml(s.survey)}`;
}

function controlsHtml(s, signedIn) {
  const label = s.can_publish_again ? 'Publish again' : 'Publish to Egeria →';
  const hasSurvey = !!(s.survey && s.survey.exists);
  const why = signedIn ? '' : 'sign in to publish — it needs an author';
  return `<div class="mt-s2 flex flex-wrap items-baseline gap-s3">
    ${button(`data-publish-go title="${esc(PUBLISH_SENTENCE)}"`, esc(label), { disabled: !(signedIn && hasSurvey) })}
    ${button(`data-resurvey-go title="${esc(RESURVEY_SENTENCE)}"`, hasSurvey ? 'Re-survey now →' : 'Run the first survey →', { disabled: !signedIn })}
    ${button('data-forget-open', 'Forget Egeria links…', { disabled: !(signedIn && s.in_egeria) })}
    <span data-publish-feedback class="text-provenance text-ink-muted" title="${esc(PUBLISH_SENTENCE)}">${esc(why || PUBLISH_IDLE_WORDS)}</span></div>
    ${hasSurvey ? '' : `<div class="mt-[2px] text-provenance text-ink-muted" data-publish-blocker>${esc(s.survey?.sentence || NO_SURVEY_SENTENCE)}</div>`}
    <div data-publish-gate></div><div data-forget-confirm></div>`;
}

function gateHtml() {
  return `<div class="mt-s2 max-w-[70ch] border-l border-rule-strong pl-s2" data-publish-gate-panel role="status">
    <div class="text-caveat text-ink">${esc(NO_PROJECT_SENTENCE)}</div>
    <div class="mt-s1 flex flex-wrap gap-s3">
      ${button('data-gate-bind', 'Bind this investigation to a project')}
      ${button('data-gate-without', 'Publish without one')}
    </div></div>`;
}

function forgetHtml() {
  return `<div class="mt-s2 max-w-[70ch] border-l border-rule-strong pl-s2" data-forget-panel role="alertdialog" aria-label="Forget Egeria links">
    <div class="text-caveat text-ink" data-forget-sentence>${esc(FORGET_SENTENCE)}</div>
    <div class="mt-s1 flex flex-wrap gap-s3">
      ${button('data-forget-go', 'Forget links')}
      ${button('data-forget-cancel', 'Cancel')}
    </div></div>`;
}

/** File types are a MEASUREMENT (ruling 2026-10-07): the survey report carries them as Egeria's own
 *  profile annotations, so this section only shows them. It sends nothing and has no button. DataSets
 *  an earlier press made stay in Egeria and read as history. */
async function renderFileTypeMeasurements(host, slug) {
  host.innerHTML = '<div class="text-caveat text-ink-muted">Reading the file types from RE\'s survey…</div>';
  let m;
  try { m = await getFileTypeMeasurements(slug); } catch (err) {
    if (host.isConnected) host.innerHTML = `<div class="text-caveat text-state-warn">The file types could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (!host.isConnected) return;
  if (!m.inventoried) {
    host.innerHTML = '<div class="text-caveat text-ink-muted" data-file-measurements-empty>No file inventory yet: survey the repository first.</div>';
    return;
  }
  const top = (counts) => Object.entries(counts).sort((x, y) => y[1] - x[1]).slice(0, 6)
    .map(([k, n]) => `${esc(k)} ${num(n)}`).join(' · ');
  const profiles = m.profiles.map((p) => `<div class="py-[1px] text-caveat" data-file-measurement="${esc(p.name)}">
      ${cue('measured', 'in the report')} <span class="text-ink">${esc(p.name)}</span>
      <span class="text-provenance text-ink-muted">· ${top(p.counts)}</span></div>`).join('');
  const retired = m.retired.length ? `<div class="mt-s2 text-provenance text-ink-muted" data-file-types-retired>earlier publishes</div>
    ${m.retired.map((r) => `<div class="py-[1px] text-caveat" data-retired-dataset="${esc(r.label)}">
      <span class="text-ink">${esc(r.label)}</span>
      <span class="text-provenance text-ink-muted">· ${esc(r.word)}</span> ${guidHtml(r.dataset_guid)}</div>`).join('')}` : '';
  host.innerHTML = `
    <div class="text-provenance text-ink-muted">Sent with the survey report, as profile annotations. Files are cataloged by selection on Curate.</div>
    <div class="mt-s1">${profiles}</div>${retired}`;
  bindCopy(host);
}

/** Draw the Publish band for the resource. Never throws into the pane: a failure says so in its own slot. */
export async function renderPublishBand(el, slug, entityType) {
  if (!el) throw new Error('Publish band host missing');
  const signedIn = !!whoAmI();
  if (entityType !== 'repo') {
    el.innerHTML = `${head}${nonRepoStatusHtml(entityType, slug)}<div class="mt-s2" data-egeria-reports-host></div>`;
    bindCopy(el);
    const row = resourceRow(slug) || {};
    mountEgeriaReports(el.querySelector('[data-egeria-reports-host]'), { entityType, slug, inEgeria: !!row.is_published });
    return;
  }
  el.innerHTML = `${head}<div class="text-caveat text-ink-muted">Reading what Egeria holds…</div>`;
  let s;
  try { s = await getRepoPublishState(slug); } catch (err) {
    if (!stale(el, slug)) el.innerHTML = `${head}<div class="text-caveat text-state-warn">The publish state could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (stale(el, slug)) return;

  const draw = (st, feedback = '') => {
    // File types are a measurement the report carries (ruling 2026-10-07): shown here, never pressed.
    el.innerHTML = `${head}${repoStatusHtml(st)}
      <details class="mt-s2" data-file-measurements-section><summary class="cursor-pointer text-answer text-ink">File types
        <span class="text-provenance text-ink-muted">· in the survey report</span></summary>
        <div class="mt-s1" data-file-measurements-host></div></details>
      ${controlsHtml(st, signedIn)}
      <div class="mt-s3" data-egeria-reports-host></div>`;
    bindCopy(el);
    if (feedback) el.querySelector('[data-publish-feedback]').textContent = feedback;
    wire(st);
    mountEgeriaReports(el.querySelector('[data-egeria-reports-host]'), { entityType: 'repo', slug, inEgeria: st.in_egeria });
  };

  const reread = async (feedback = '') => {
    const st = await getRepoPublishState(slug);
    if (!stale(el, slug)) draw(st, feedback);
  };

  const wire = (st) => {
    const go = el.querySelector('[data-publish-go]');
    const feedback = el.querySelector('[data-publish-feedback]');
    const gate = el.querySelector('[data-publish-gate]');
    const press = async (withoutProject) => {
      if (go.dataset.pending) return;                       // a second press is ignored
      go.dataset.pending = '1';
      go.disabled = true;
      const idle = go.textContent;
      go.textContent = `${idle} …`;
      feedback.innerHTML = cue('running', PUBLISH_RUNNING_WORDS);
      feedback.title = PUBLISH_SENTENCE;
      gate.innerHTML = '';
      try {
        await publishRepoReport(slug, { withoutProject });
        await reread();
      } catch (err) {
        if (err.status === 428) {
          go.disabled = false; go.textContent = idle; delete go.dataset.pending;
          feedback.textContent = '';
          gate.innerHTML = gateHtml();
          gate.querySelector('[data-gate-bind]').addEventListener('click', () => openCurrentInvestigationStage());
          gate.querySelector('[data-gate-without]').addEventListener('click', () => press(true));
          return;
        }
        try { await reread(); } catch { /* the failure below is what matters */ }
        const fb = el.querySelector('[data-publish-feedback]');
        if (fb) fb.innerHTML = err.status === 409 && err.message.startsWith('no survey')
          ? cue('unrun', err.message)                    // nothing surveyed: nothing was sent
          : err.status === 409
            ? cue('running', 'a publish is already running for this resource')
            : cue('error', `not published · ${err.message}`);
      }
    };
    go?.addEventListener('click', () => press(false));

    // Re-survey now: runs the survey and NOTHING else. An immediate visible change on the press; the
    // words after it come from the re-read state (the new age), never from the click.
    const rs = el.querySelector('[data-resurvey-go]');
    rs?.addEventListener('click', async () => {
      if (rs.dataset.pending) return;
      rs.dataset.pending = '1';
      rs.disabled = true;
      const idle = rs.textContent;
      rs.textContent = 'Re-surveying …';
      if (go) go.disabled = true;                          // a publish mid-survey would send a half-kept one
      feedback.innerHTML = cue('running', 'surveying · nothing is sent to Egeria');
      try {
        const out = await resurveyRepo(slug);
        await reread(out && out.ok === false
          ? `survey finished with problems · ${(out.errors || []).join('; ').slice(0, 200)}` : 'survey kept · see its age above');
      } catch (err) {
        rs.disabled = false; rs.textContent = idle; delete rs.dataset.pending;
        if (go) go.disabled = !(st.survey && st.survey.exists);
        feedback.innerHTML = err.status === 409
          ? cue('running', 'a survey is already running for this resource')
          : cue('error', `not surveyed · ${err.message}`);
      }
    });

    el.querySelector('[data-forget-open]')?.addEventListener('click', () => {
      const slot = el.querySelector('[data-forget-confirm]');
      slot.innerHTML = forgetHtml();
      slot.querySelector('[data-forget-cancel]').addEventListener('click', () => { slot.innerHTML = ''; });
      const fgo = slot.querySelector('[data-forget-go]');
      fgo.addEventListener('click', async () => {
        if (fgo.dataset.pending) return;
        fgo.dataset.pending = '1';
        fgo.disabled = true;
        fgo.textContent = 'Forgetting …';
        try {
          const out = await forgetEgeriaLinks(slug);
          await reread(`links forgotten · ${out.surveys_deleted} survey record${out.surveys_deleted === 1 ? '' : 's'} dropped · Egeria unchanged`);
        } catch (err) {
          fgo.disabled = false; fgo.textContent = 'Forget links'; delete fgo.dataset.pending;
          slot.querySelector('[data-forget-sentence]').insertAdjacentHTML(
            'afterend', `<div class="text-caveat text-state-warn" data-forget-error>Not forgotten · ${esc(err.message)}</div>`);
        }
      });
    });

    const ft = el.querySelector('[data-file-measurements-section]');
    ft?.addEventListener('toggle', () => {
      if (ft.open && !ft.dataset.loaded) {
        ft.dataset.loaded = '1';
        renderFileTypeMeasurements(ft.querySelector('[data-file-measurements-host]'), slug);
      }
    });
  };

  draw(s);
}
