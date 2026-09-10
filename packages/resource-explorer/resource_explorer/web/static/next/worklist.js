/* The Scouting vertical slice — work lists, batch runs, and the comparison grid.
 *
 * The path this exists to prove, end to end and without leaving /next:
 *
 *   select a set → save as a work list → run one survey across the whole set,
 *   concurrently → compare the set as rows × questions → disposition in bulk,
 *   with reasons → promote the survivors as a new, narrower list
 *
 * It is one continuous claim: if it works for fourteen repos it works for four
 * hundred, and if it does not the funnel needs a different design. Everything
 * built before this reads ONE resource at a time, which is the constraint the
 * whole review is about.
 *
 * THE GRID IS THE POINT, and its hardest requirement is the same one the
 * question rows have: every cell says which of the six states it is in,
 * including "ran and found nothing", which is not the same as an empty cell.
 *
 * One call per resource, not one per cell. `GET /api/analyses/facts/{slug}`
 * returns every fact for a resource already judged; the columns are the
 * stage's questions, and a cell is derived by looking up that question's
 * `analysis_ids` among them. Fourteen calls, not seventy.
 */

import {
  VALID_DISPOSITIONS,
  createWorkList,
  enqueueBatch,
  getBatchProgress,
  getQuestions,
  getResourceFacts,
  getWorkList,
  listAnalyses,
  listWorkLists,
  promoteWorkList,
  publishWorkList,
  setDisposition,
} from '/static/re-api.js';

/* ── Cell state ─────────────────────────────────────────────────────────
 *
 * The same six-state vocabulary the question rows use, derived per cell.
 * Deliberately NOT a boolean "has data": a grid of ticks and blanks would
 * collapse "never ran", "ran and found nothing" and "nothing can answer
 * this" into one mark, which is the failure this whole UI argues against —
 * and at grid density it would be far harder to notice.
 */
export const CELL = {
  answered:      { glyph: '✓', tone: 'text-state-ok',   label: 'answered' },
  nothing:       { glyph: '∅', tone: 'text-state-ok',   label: 'ran, found nothing' },
  partial:       { glyph: '◐', tone: 'text-state-warn', label: 'partial' },
  unrun:         { glyph: '○', tone: 'text-state-warn', label: 'not run' },
  human:         { glyph: '⚠', tone: 'text-accent-ink', label: 'needs you' },
  'no-surveyor': { glyph: '○', tone: 'text-state-gap',  label: 'no surveyor' },
  unclassified:  { glyph: '·', tone: 'text-ink-muted',  label: 'unclassified' },
  running:       { glyph: '◔', tone: 'text-accent-ink', label: 'running' },
  unknown:       { glyph: '?', tone: 'text-ink-muted',  label: 'could not read' },
};

/**
 * One cell's state, from a question and a resource's facts.
 *
 * `facts` is the array from `/api/analyses/facts/{slug}`, whose entries carry
 * `state` from `surveyors/result_status.py` — already judged, so nothing here
 * turns "never ran" into "none found".
 */
export function cellState(question, factsById) {
  const kind = question.kind || 'unknown';
  if (kind === 'gap') return 'no-surveyor';
  if (kind === 'human') return 'human';
  if (kind === 'unknown') return 'unclassified';

  const ids = question.analysis_ids || [];
  if (!ids.length) return 'unclassified';

  const found = ids.map((id) => factsById.get(id)).filter(Boolean);
  if (!found.length) return 'unrun';
  if (found.some((f) => f.state === 'measured')) {
    return found.some((f) => f.state === 'never_run') ? 'partial' : 'answered';
  }
  if (found.every((f) => f.state === 'nothing_found')) return 'nothing';
  if (found.some((f) => f.state === 'partial')) return 'partial';
  if (found.every((f) => f.state === 'never_run')) return 'unrun';
  return 'partial';
}

/* ── State ──────────────────────────────────────────────────────────── */

export const grid = {
  workList: null,        // the open work list
  questions: [],         // columns
  rows: new Map(),       // entity_slug -> { facts, factsById, error }
  selected: new Set(),   // rows ticked for a bulk action
  analyses: null,        // the CURRENT STAGE's analyses; null = not read yet
  stageLabel: '',        // for the question key's heading
  batch: null,           // the running set's progress
  poll: null,            // its interval handle
  note: '',
};

/* ── Rendering ──────────────────────────────────────────────────────── */

const esc = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&apos;');

/**
 * Render the whole slice into the content pane.
 *
 * `ctx` carries the few things this module needs from the shell rather than
 * reaching into it: `el` (the pane), `stage`, `analyses` (the catalog for the
 * run picker), and `onExit` (back to the questions pane).
 */
export async function renderWorkListPane(ctx) {
  const { el, stage } = ctx;
  const wl = grid.workList;
  if (!wl) return;

  el.innerHTML = `
    <div class="mb-s4 flex flex-wrap items-baseline gap-s3 font-heading text-subtab">
      <span class="border-b border-accent pb-[2px] text-ink">Work list</span>
      <button data-act="exit" class="cursor-pointer bg-transparent text-ink-muted hover:text-ink">← back to questions</button>
    </div>
    <div class="flex flex-wrap items-baseline gap-s3">
      <h3 class="m-0 font-heading text-name font-normal">${esc(wl.display_name)}</h3>
      <span class="tnum text-[12px] text-ink-muted">
        <span class="tnum">${wl.members.length}</span> resources · ${esc(stage)}
        ${wl.derived_from ? ` · narrowed from <span class="font-mono">${esc(wl.derived_from)}</span>` : ''}
        ${wl.egeria_guid ? ' · published to Egeria' : ' · not published'}
      </span>
    </div>
    <div id="wl-actions" class="mt-s3 flex flex-wrap items-baseline gap-s3 text-caveat"></div>
    <div id="wl-note" class="mt-s2 text-caveat text-ink"></div>
    <div id="wl-progress" class="mt-s2"></div>
    <div class="my-s3 h-px bg-rule"></div>
    <div id="wl-grid" class="overflow-x-auto"></div>
    <div id="wl-legend" class="mt-s3 flex flex-wrap gap-s3 text-caveat text-ink"></div>`;

  el.querySelector('[data-act="exit"]').addEventListener('click', () => ctx.onExit());

  // The runnable analyses for THIS STAGE, re-read whenever the pane renders.
  //
  // The dropdown used to show the whole catalog — 36 analyses on every stage —
  // because it was filled once at boot with no intent filter. Offering
  // `security_scan` under Scouting is not a longer menu, it is a menu that
  // disagrees with the funnel the rest of the screen is arranged around.
  grid.stageLabel = stage;
  grid.analyses = null;
  renderActions(ctx);
  renderLegend();
  try {
    grid.analyses = await listAnalyses('repo', { intent: stage });
  } catch (err) {
    grid.analyses = { error: err.message };
  }
  renderActions(ctx);

  await loadGrid(ctx);
}

function renderActions(ctx) {
  const host = document.getElementById('wl-actions');
  if (!host) return;
  const n = grid.selected.size;
  const loaded = Array.isArray(grid.analyses);
  const failed = grid.analyses && grid.analyses.error;
  const analyses = loaded ? grid.analyses.filter((a) => a.id || a.analysis_id) : [];
  // Four states, kept apart. "Not read yet", "this stage has none",
  // "the catalog could not be read" and "here they are" are different
  // sentences, and an empty dropdown that means the first three looks
  // identical to a broken one.
  const runnable = analyses.length > 0;
  host.innerHTML = `
    <select id="wl-analysis" ${runnable ? '' : 'disabled'}
      class="rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-ink">
      ${!loaded && !failed ? '<option value="">reading the catalog…</option>' : ''}
      ${failed ? `<option value="">catalog unavailable</option>` : ''}
      ${loaded && !runnable ? `<option value="">no analyses for ${esc(ctx.stage)}</option>` : ''}
      ${analyses.map((a) => `<option value="${esc(a.id || a.analysis_id)}">${esc(a.display_name || a.name || a.id || a.analysis_id)}</option>`).join('')}
    </select>
    <button data-act="run" ${runnable ? '' : 'disabled'}
      class="cursor-pointer rounded-sm border ${runnable ? 'border-accent text-accent-ink' : 'border-dashed border-rule-strong text-ink-muted'} bg-transparent px-2 py-[2px]"
      >Run across <span class="tnum">${n || grid.workList.members.length}</span></button>
    <span class="text-ink-muted">${
      failed ? `<span class="text-state-warn">the analysis catalog could not be read: ${esc(failed)}</span>`
      : !loaded ? 'reading the catalog…'
      : !runnable ? `<span class="text-accent-ink">${esc(ctx.stage)} has no analyses in the catalog — by design for Enrichment, Understanding and Automate, which are served elsewhere</span>`
      : n ? `${n} selected` : 'all rows'}</span>
    <span class="ml-auto flex flex-wrap items-baseline gap-s3">
      <select id="wl-disposition" ${n ? '' : 'disabled'}
        class="rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-ink">
        <option value="">mark selected as…</option>
        ${VALID_DISPOSITIONS.map((d) => `<option value="${esc(d)}">${esc(d)}</option>`).join('')}
      </select>
      <button data-act="promote" ${n ? '' : 'disabled'}
        class="cursor-pointer bg-transparent text-accent-ink underline">promote <span class="tnum">${n}</span> →</button>
      <button data-act="publish" class="cursor-pointer bg-transparent text-accent-ink underline"
        >${grid.workList.egeria_guid ? 're-publish' : 'publish to Egeria'}</button>
    </span>`;

  host.querySelector('[data-act="run"]').addEventListener('click', () => runBatch(ctx));
  host.querySelector('[data-act="promote"]')?.addEventListener('click', () => promote(ctx));
  host.querySelector('[data-act="publish"]')?.addEventListener('click', () => publish(ctx));
  host.querySelector('#wl-disposition')?.addEventListener('change', (e) => {
    const value = e.target.value;
    e.target.value = '';
    if (value) bulkDisposition(ctx, value);
  });
}

function renderLegend() {
  const host = document.getElementById('wl-legend');
  if (!host) return;
  host.innerHTML = '<span class="text-caps uppercase tracking-caps text-ink-muted">Key</span>'
    + Object.entries(CELL).filter(([k]) => k !== 'unknown').map(([, c]) =>
      `<span class="inline-flex items-baseline gap-[5px]">
        <span class="${c.tone}">${c.glyph}</span><span>${esc(c.label)}</span></span>`).join('');
}

function note(html) {
  const el = document.getElementById('wl-note');
  if (el) el.innerHTML = html;
}

async function loadGrid(ctx) {
  const host = document.getElementById('wl-grid');
  const wl = grid.workList;
  host.innerHTML = '<div class="py-s3 text-answer text-ink-muted">Reading the set…</div>';

  // Columns: the stage's questions. Taken from the first member, because the
  // catalog is per resource TYPE, not per resource.
  try {
    const checklist = await getQuestions(wl.members[0].entity_slug, { phase: ctx.stage });
    grid.questions = checklist.questions || [];
  } catch (err) {
    host.innerHTML = `<div class="py-s3 text-answer text-state-warn">
      The question columns could not be read: ${esc(err.message)}</div>`;
    return;
  }

  renderGrid();
  // Rows arrive independently, same as the question pane: one slow resource
  // must not hold up thirteen others.
  await Promise.all(wl.members.map(async (m) => {
    try {
      const res = await getResourceFacts(m.entity_slug);
      const byId = new Map();
      for (const f of res.facts || []) byId.set(f.analysis_id, f);
      grid.rows.set(m.entity_slug, { facts: res.facts || [], factsById: byId });
    } catch (err) {
      grid.rows.set(m.entity_slug, { error: err.message });
    }
    renderGrid();
  }));
}

function renderGrid() {
  const host = document.getElementById('wl-grid');
  if (!host) return;
  const wl = grid.workList;
  const qs = grid.questions;

  // Columns are NUMBERED and the questions are listed in full underneath.
  //
  // They used to be the question text clamped to three lines at 120px, which
  // at 27 columns meant nobody could read any of them — "I can't see the full
  // questions". A tooltip is not a fix: it shows one at a time, needs a mouse,
  // and cannot be read alongside the row you are comparing it against. The
  // key below is readable, printable, and keeps the cells narrow enough that
  // a wide stage still scans.
  host.innerHTML = `
    <table class="w-full border-collapse text-caveat">
      <thead>
        <tr class="border-b border-rule">
          <th class="w-[26px] p-[6px]"></th>
          <th class="p-[6px] text-left font-heading text-ink">Resource</th>
          ${qs.map((q, i) => `<th class="p-[6px] text-center align-bottom font-heading text-ink"
            title="${esc(q.question)}">
            <span class="tnum">${i + 1}</span></th>`).join('')}
          <th class="p-[6px] text-left font-heading text-ink">Answered</th>
        </tr>
      </thead>
      <tbody>
        ${wl.members.map((m) => rowHtml(m, qs)).join('')}
      </tbody>
    </table>

    <div class="mt-s4">
      <div class="mb-s2 text-caps uppercase tracking-caps text-ink-muted">
        The questions · <span class="tnum">${qs.length}</span> in ${esc(grid.stageLabel || '')}
      </div>
      <ol class="m-0 flex list-none flex-col gap-[6px] p-0">
        ${qs.map((q, i) => `<li class="flex gap-s2">
          <span class="tnum w-[22px] shrink-0 text-right text-ink-muted">${i + 1}</span>
          <span class="min-w-0">
            <span class="text-answer text-ink">${esc(q.question)}</span>
            ${(q.perspectives || []).length ? `<span class="ml-s2 text-caps text-ink-muted"
              >${esc((q.perspectives || []).join(' · '))}</span>` : ''}
            ${q.analysis_ids && q.analysis_ids.length
              ? `<div class="text-provenance text-ink-muted">${esc(q.analysis_ids.join(', '))}</div>`
              : `<div class="text-provenance text-ink-muted">${
                  q.kind === 'gap' ? 'no surveyor exists for this'
                  : q.kind === 'human' ? 'answered by a person, not a survey'
                  : q.kind === 'direct' ? 'a direct field, not a survey'
                  : 'no analysis is mapped to this'}</div>`}
          </span>
        </li>`).join('')}
      </ol>
    </div>`;

  host.querySelectorAll('input[data-row]').forEach((cb) => cb.addEventListener('change', () => {
    if (cb.checked) grid.selected.add(cb.dataset.row);
    else grid.selected.delete(cb.dataset.row);
    renderActions(window.__wlCtx);
  }));
}

function rowHtml(member, qs) {
  const slug = member.entity_slug;
  const row = grid.rows.get(slug);
  const running = grid.batch?.runs?.find(
    (r) => r.entity_slug === slug && ['queued', 'claimed', 'running'].includes(r.state));

  const cells = qs.map((q) => {
    if (!row) {
      return '<td class="p-[6px] text-ink-muted">…</td>';
    }
    if (row.error) {
      // A resource whose facts could not be read is NOT a resource with no
      // results. One state for "we could not look", never blank.
      return `<td class="p-[6px] ${CELL.unknown.tone}" title="${esc(row.error)}">${CELL.unknown.glyph}</td>`;
    }
    const st = running ? 'running' : cellState(q, row.factsById);
    const c = CELL[st] || CELL.unclassified;
    return `<td class="p-[6px] ${c.tone}" title="${esc(q.question)} — ${esc(c.label)}">${c.glyph}</td>`;
  }).join('');

  const answered = row && !row.error
    ? qs.filter((q) => ['answered', 'nothing'].includes(cellState(q, row.factsById))).length
    : null;

  return `<tr class="border-b border-rule">
    <td class="p-[6px]"><input type="checkbox" data-row="${esc(slug)}" ${
      grid.selected.has(slug) ? 'checked' : ''}></td>
    <td class="p-[6px] text-ink">
      <span class="font-mono text-[11px]">${esc(slug)}</span>
      ${member.rationale ? `<div class="text-provenance text-ink-muted">${esc(member.rationale)}</div>` : ''}
    </td>
    ${cells}
    <td class="p-[6px] tnum text-ink-muted">${
      answered === null ? '—' : `${answered} of ${qs.length}`}</td>
  </tr>`;
}

/* ── Actions ────────────────────────────────────────────────────────── */

function targets() {
  return grid.selected.size
    ? [...grid.selected]
    : grid.workList.members.map((m) => m.entity_slug);
}

async function runBatch(ctx) {
  const analysisId = document.getElementById('wl-analysis')?.value;
  if (!analysisId) { note('<span class="text-state-warn">No analysis selected.</span>'); return; }
  const slugs = targets();
  note(`Enqueueing <span class="tnum">${slugs.length}</span> run(s)…`);
  let started;
  try {
    started = await enqueueBatch(analysisId, slugs, grid.workList.slug);
  } catch (err) {
    // `Load failed` / `Failed to fetch` is the browser's wording for a
    // network-level failure, not an application error — most often the
    // server restarting. Distinguish it, because "the batch could not be
    // enqueued" reads as a rejection and this is not one: nothing was
    // written and retrying is the right move.
    const networkish = /load failed|failed to fetch|networkerror/i.test(err.message || '');
    note(networkish
      ? `<span class="text-state-warn">The server could not be reached, so nothing was
         enqueued (${esc(err.message)}). If it was restarting, try again.</span>`
      : `<span class="text-state-warn">The batch was refused: ${esc(err.message)}</span>`);
    return;
  }
  note(`Batch <span class="font-mono">${esc(started.set_id)}</span> ·
        <span class="tnum">${started.runs.length}</span> run(s) across the set.`);
  watchBatch(ctx, started.set_id);
}

/**
 * Poll a set to completion.
 *
 * Shows queued / running / done / failed SEPARATELY. "12 of 14 finished" with
 * no split hides that two of them failed, and a batch view whose only number
 * is progress is the one thing worse than no batch view.
 */
function watchBatch(ctx, setId) {
  clearInterval(grid.poll);
  const tick = async () => {
    let p;
    try {
      p = await getBatchProgress(setId);
    } catch (err) {
      clearInterval(grid.poll);
      renderProgress(`<span class="text-state-warn">Lost track of this batch: ${esc(err.message)}</span>`);
      return;
    }
    grid.batch = p;
    // The queue's OWN vocabulary — `ProjectRegistry.RUN_STATES`. `done` is not
    // one of them; assuming it was is what made a finished batch poll forever.
    const order = ['queued', 'claimed', 'running', 'succeeded', 'failed', 'cancelled', 'unknown'];
    const tone = { succeeded: 'text-state-ok', failed: 'text-state-warn',
                   cancelled: 'text-state-warn', unknown: 'text-ink-muted' };
    const parts = order.filter((s) => p.counts[s]).map((s) =>
      `<span class="${tone[s] || 'text-ink'}"><span class="tnum">${p.counts[s]}</span> ${s}</span>`);
    // Anything the server flagged as unrecognised is named, not folded in.
    for (const s of p.unrecognised_states || []) {
      parts.push(`<span class="text-state-warn"><span class="tnum">${p.counts[s] || 0}</span> ${esc(s)} (unrecognised)</span>`);
    }
    renderProgress(`<span class="text-caps uppercase tracking-caps text-ink-muted">Batch</span>
      ${parts.join(' · ')} · <span class="tnum">${p.finished}</span> of
      <span class="tnum">${p.total}</span> finished`);
    renderGrid();
    if (p.complete) {
      clearInterval(grid.poll);
      grid.batch = null;
      // Re-read the facts: the whole reason for running was to change them.
      await loadGrid(ctx);
      renderProgress(`<span class="text-caps uppercase tracking-caps text-ink-muted">Batch</span>
        finished — <span class="tnum">${p.counts.succeeded || 0}</span> succeeded${
          p.counts.failed ? `, <span class="text-state-warn"><span class="tnum">${p.counts.failed}</span> failed</span>` : ''}`);
    }
  };
  tick();
  grid.poll = setInterval(tick, 3000);
}

function renderProgress(html) {
  const el = document.getElementById('wl-progress');
  if (el) el.innerHTML = `<div class="flex flex-wrap items-baseline gap-s3 text-caveat">${html}</div>`;
}

async function bulkDisposition(ctx, disposition) {
  const slugs = [...grid.selected];
  const reason = window.prompt(
    `Why are these ${slugs.length} being marked "${disposition}"?\n\n`
    + 'The reason is stored with the verdict and is what the trail is for. '
    + 'Leave blank to record none.', '') ?? '';
  const failed = [];
  const noUrl = [];
  for (const slug of slugs) {
    const p = (ctx.projects || []).find((x) => x.slug === slug);
    if (!p?.github_url) { noUrl.push(slug); continue; }
    try {
      await setDisposition(p.github_url, disposition, reason);
      p.disposition = disposition;
    } catch (err) { failed.push(`${slug}: ${err.message}`); }
  }
  const ok = slugs.length - failed.length - noUrl.length;
  note([
    ok ? `<span class="tnum">${ok}</span> marked ${esc(disposition)}${reason ? ` — “${esc(reason)}”` : ' with no reason recorded'}` : '',
    noUrl.length ? `<span class="text-state-warn"><span class="tnum">${noUrl.length}</span> have no GitHub URL and could not be marked: ${esc(noUrl.join(', '))}</span>` : '',
    failed.length ? `<span class="text-state-warn">${esc(failed.join('; '))}</span>` : '',
  ].filter(Boolean).join(' · '));
}

async function promote(ctx) {
  const survivors = [...grid.selected];
  const name = window.prompt(
    `Name for the shortlist of ${survivors.length}:`,
    `${grid.workList.display_name} — shortlist`);
  if (name === null) return;
  try {
    const next = await promoteWorkList(grid.workList.slug, survivors, name);
    grid.workList = next;
    grid.selected.clear();
    grid.rows.clear();
    note(`Promoted <span class="tnum">${next.members.length}</span> into
      <strong>${esc(next.display_name)}</strong>, which records
      <span class="font-mono">${esc(next.derived_from)}</span> as its parent.`);
    await renderWorkListPane(ctx);
  } catch (err) {
    note(`<span class="text-state-warn">Could not promote: ${esc(err.message)}</span>`);
  }
}

async function publish(ctx) {
  note('Publishing to Egeria…');
  try {
    const res = await publishWorkList(grid.workList.slug);
    grid.workList = await getWorkList(grid.workList.slug);
    const bits = [
      `Published as a <strong>${esc(res.type_name)}</strong> collection
       (<span class="font-mono">${esc(res.egeria_guid)}</span>).`,
      `<span class="tnum">${res.queued_members}</span> membership(s) queued —
       they are applied by the worker that drains the outbox, not here.`,
    ];
    if (res.members_without_an_egeria_asset?.length) {
      // Named, not counted. These are not failed writes to retry: the repo
      // has never been published, so there is no asset to attach to.
      bits.push(`<span class="text-accent-ink">
        <span class="tnum">${res.members_without_an_egeria_asset.length}</span>
        member(s) have no Egeria asset and were not attached:
        ${esc(res.members_without_an_egeria_asset.join(', '))}</span>`);
    }
    note(bits.join(' '));
    renderActions(ctx);
  } catch (err) {
    note(`<span class="text-state-warn">Publish failed: ${esc(err.message)}</span>`);
  }
}

/* ── Entry points used by the shell ─────────────────────────────────── */

export async function openWorkList(ctx, slug) {
  grid.workList = await getWorkList(slug);
  grid.rows.clear();
  grid.selected.clear();
  clearInterval(grid.poll);
  window.__wlCtx = ctx;
  await renderWorkListPane(ctx);
}

export async function saveAsWorkList(displayName, slugs, { investigation = '', rationale = '' } = {}) {
  return createWorkList(displayName, slugs, { investigation, rationale });
}

export { listWorkLists };
