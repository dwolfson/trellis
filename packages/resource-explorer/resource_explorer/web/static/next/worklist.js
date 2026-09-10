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
  getBulkFacts,
  getBulkStates,
  getWorkList,
  listAnalyses,
  listWorkLists,
  promoteWorkList,
  publishWorkList,
  setDisposition,
} from '/static/re-api.js';
import { ago, daysSince } from '/static/next/format.js';

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
  // Stored output exists; which of measured/partial it is has NOT been
  // established, because establishing it costs 47s for one analysis. Its own
  // glyph rather than a tick: a tick would claim `answered`, which is
  // precisely the state nobody has read.
  stored:        { glyph: '▪', tone: 'text-ink-muted',  label: 'has results · not read' },
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

/** Every analysis id the given questions read — the scope for the bulk call.
 *  Questions with no analysis contribute nothing, which is why a stage of
 *  `gap`/`human` questions costs almost nothing to display. */
function qsAnalysisIds(questions) {
  return (questions || []).flatMap((q) => q.analysis_ids || []);
}

/**
 * Analyses whose RESULTS READER is slow enough to be worth loading second.
 *
 * Measured on `egeria_git`, not guessed: 47.7s and 22.5s respectively, where
 * the other 32 analyses with readers total 0.6s between them. Named here in
 * one place with the numbers, because a list like this rots silently — if a
 * reader gets fixed, or another gets slow, this is the thing to re-measure.
 *
 * Being on this list costs nothing but arrival order, so a wrong entry is
 * cheap; missing one costs a blank-looking pane.
 */
const EXPENSIVE_ANALYSES = new Set(['architecture_recovery', 'architecture_diagram']);

/* ── State ──────────────────────────────────────────────────────────── */

export const grid = {
  workList: null,        // the open work list
  questions: [],         // columns
  rows: new Map(),       // entity_slug -> { facts, factsById, error }
  selected: new Set(),   // rows ticked for a bulk action
  analyses: null,        // the CURRENT STAGE's analyses; null = not read yet
  stageLabel: '',        // for the question key's heading
  heldPerspectives: [],  // which perspectives narrowed the columns
  commonRationale: null, // a rationale every member shares, shown once
  pendingAnalyses: new Set(),  // slow columns still arriving
  states: {},            // the cheap projection, per resource
  statesError: null,
  slowError: null,
  questionsUnfiltered: null,
  batch: null,           // the running set's progress
  poll: null,            // its interval handle
  note: '',
  ctx: null,             // the pane context, for actions raised from a popup
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
    <div id="wl-common-rationale" class="mb-s2 text-provenance text-ink-muted"></div>
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
    // Perspectives NARROW THE COLUMNS here, exactly as they narrow the rows
    // in the questions pane. They were being ignored, so holding one changed
    // nothing on this screen — an inert control beside a live one.
    //
    // It is also the honest answer to "27 columns is too many": the axis for
    // cutting them down already exists and was simply not wired up.
    const held = [...(ctx.perspectives || [])];
    const checklist = await getQuestions(wl.members[0].entity_slug,
                                         { phase: ctx.stage, perspectives: held });
    grid.questions = checklist.questions || [];
    grid.heldPerspectives = held;
    if (held.length) {
      // The residue, said out loud: a filtered grid that does not say what it
      // hid is a grid you cannot trust to be complete.
      try {
        const all = await getQuestions(wl.members[0].entity_slug, { phase: ctx.stage });
        grid.questionsUnfiltered = (all.questions || []).length;
      } catch { grid.questionsUnfiltered = null; }
    } else {
      grid.questionsUnfiltered = grid.questions.length;
    }
  } catch (err) {
    host.innerHTML = `<div class="py-s3 text-answer text-state-warn">
      The question columns could not be read: ${esc(err.message)}</div>`;
    return;
  }

  // One shared rationale is said once, above the grid, rather than repeated
  // under all twelve rows — at 12 rows it was the noisiest thing on screen.
  const rationales = new Set(wl.members.map((m) => m.rationale || ''));
  grid.commonRationale = rationales.size === 1 ? [...rationales][0] : null;

  renderGrid();

  // TWO calls, cheap analyses first, so the matrix is READABLE IMMEDIATELY
  // and the slow columns fill in behind.
  //
  // Measured, on a large repo: `architecture_recovery`'s results reader takes
  // 47s and `architecture_diagram`'s 22s, against under a second for the
  // other 32 combined. Discovery's questions route to BOTH, so a four-member
  // Discovery matrix is ~65s even fanned out across resources — parallelism
  // cannot beat the slowest single resource, and that floor is one reader.
  //
  // So the split is not an optimisation, it is the difference between a blank
  // pane for a minute and a usable one in a second with two columns still
  // arriving. The cells that are still coming show their pending marker,
  // which the grid already distinguishes from every other state.
  const needed = [...new Set(qsAnalysisIds(grid.questions))];
  const quick = needed.filter((a) => !EXPENSIVE_ANALYSES.has(a));

  const applyBulk = (bulk) => {
    for (const m of wl.members) {
      const facts = bulk.subjects?.[m.entity_slug];
      const prev = grid.rows.get(m.entity_slug);
      if (facts) {
        const byId = prev?.factsById || new Map();
        for (const f of facts) byId.set(f.analysis_id, f);
        grid.rows.set(m.entity_slug, { facts: [...byId.values()], factsById: byId });
      } else if (!prev) {
        // Named by the server as unreadable, or simply absent. Either way it
        // is "we could not read this", not "this has no results".
        grid.rows.set(m.entity_slug, {
          error: bulk.unreadable?.[m.entity_slug] || 'no facts returned for this resource',
        });
      }
    }
  };

  const slugs = wl.members.map((m) => m.entity_slug);

  // PASS 1 — the cheap projection over EVERY column. Instant, and it carries
  // `measured_at`, so the grid can say how current it is before it knows what
  // it says.
  try {
    const proj = await getBulkStates(slugs, needed);
    grid.states = proj.states || {};
    renderGrid();
  } catch (err) {
    grid.statesError = err.message;
  }

  // PASS 2 — the full read, but ONLY for the analyses that are cheap to read.
  // The expensive ones keep the projection's honest "has results, not read"
  // rather than costing a minute to turn ▪ into ✓.
  try {
    if (quick.length) { applyBulk(await getBulkFacts(slugs, quick)); }
  } catch (err) {
    grid.slowError = err.message;
  }
  grid.pendingAnalyses = new Set();
  renderGrid();
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
  if (!qs.length) {
    host.innerHTML = `<div class="py-s3 text-answer text-ink">
      No questions in ${esc(grid.stageLabel || 'this stage')}${
        grid.heldPerspectives.length
          ? ` match ${esc(grid.heldPerspectives.join(' · '))}. That is a fact about the
              filter, not about these resources — drop a perspective to widen it.`
          : '.'}</div>`;
    return;
  }

  const cr = document.getElementById('wl-common-rationale');
  if (cr) cr.textContent = grid.commonRationale ? `All members: ${grid.commonRationale}` : '';

  host.innerHTML = `
    <table class="w-full border-collapse text-caveat">
      <thead>
        <tr class="border-b border-rule">
          <th class="wl-freeze-1 w-[26px] p-[6px]"></th>
          <th class="wl-freeze-2 p-[6px] text-left font-heading text-ink">Resource</th>
          ${qs.map((q, i) => `<th class="wl-col p-[6px] align-bottom font-heading text-ink"
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
        The questions · <span class="tnum">${qs.length}</span> in ${esc(grid.stageLabel || '')}${
          grid.heldPerspectives.length && grid.questionsUnfiltered != null
            ? ` · <span class="tnum">${Math.max(0, grid.questionsUnfiltered - qs.length)}</span> hidden by
               ${esc(grid.heldPerspectives.join(' · '))}`
            : ''}
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

  host.querySelectorAll('button[data-cell]').forEach((b) => b.addEventListener('click', () => {
    openCellDetail(b.dataset.cell, Number(b.dataset.q), grid.ctx);
  }));
  host.querySelectorAll('input[data-row]').forEach((cb) => cb.addEventListener('change', () => {
    if (cb.checked) grid.selected.add(cb.dataset.row);
    else grid.selected.delete(cb.dataset.row);
    renderActions(window.__wlCtx);
  }));
}

function rowHtml(member, qs) {
  const slug = member.entity_slug;
  const row = grid.rows.get(slug);
  // Each cell carries ITS OWN measurement date, because each analysis ran
  // when it ran. The Measured column summarises; this is where the fact is.
  const per = grid.states?.[slug] || {};
  const cellStamp = (q) => {
    const stamps = (q.analysis_ids || [])
      .map((a) => per[a]?.measured_at || '').filter(Boolean);
    return stamps.length ? stamps.sort()[0] : '';   // oldest input to this answer
  };
  const stampNote = (q) => {
    const iso = cellStamp(q);
    if (!iso) return '';
    const d = daysSince(iso);
    return `\nmeasured ${ago(iso)} (${iso})${
      d !== null && d >= STALE_DAYS ? ' — stale' : ''}`;
  };

  const cells = qs.map((q, qi) => {
    const stale = (() => {
      const d = daysSince(cellStamp(q));
      return d !== null && d >= STALE_DAYS;
    })();
    // A stale cell keeps its own state glyph and gains a mark. Recolouring it
    // would conflate "this answer is old" with "this answer is bad".
    const mark = stale ? '<span class="text-state-warn">·</span>' : '';

    // KIND FIRST. A question with no surveyor, or one only a person can
    // answer, has no analysis to read and no facts to wait for — it is
    // settled before any of the fact logic below applies. Losing this branch
    // left such a column showing `…` forever, because "still loading" is what
    // the fall-through says when nothing is known and nothing ever will be.
    const kindState = { gap: 'no-surveyor', human: 'human', unknown: 'unclassified' }[q.kind];
    if (kindState || !(q.analysis_ids || []).length) {
      const c = CELL[kindState] || CELL.unclassified;
      return `<td class="wl-cell p-[6px] ${c.tone}" title="${esc(q.question)} — ${esc(c.label)}">${c.glyph}</td>`;
    }
    if (row?.error) {
      // A resource whose facts could not be read is NOT a resource with no
      // results. One state for "we could not look", never blank.
      return `<td class="wl-cell p-[6px] ${CELL.unknown.tone}" title="${esc(row.error)}">${CELL.unknown.glyph}</td>`;
    }
    const running = !!grid.batch?.runs?.find(
      (r) => r.entity_slug === slug && ['queued', 'claimed', 'running'].includes(r.state));
    if (running) {
      return `<td class="wl-cell p-[6px] ${CELL.running.tone}" title="${esc(q.question)} — ${esc(CELL.running.label)}">${CELL.running.glyph}</td>`;
    }
    // Full facts, when they have been read.
    const haveFacts = row && (q.analysis_ids || []).some((a) => row.factsById.has(a));
    if (haveFacts) {
      const c = CELL[cellState(q, row.factsById)] || CELL.unclassified;
      return `<td class="wl-cell p-[6px] ${c.tone}"><button type="button" class="wl-cellbtn" data-cell="${esc(slug)}" data-q="${qi}" title="${esc(q.question)} — ${esc(c.label)}${esc(stampNote(q))}
click for the latest results">${c.glyph}${mark}</button></td>`;
    }
    // Otherwise the CHEAP PROJECTION answers, and only as far as it honestly
    // can: there is stored output, or there provably is not. It cannot tell
    // `measured` from `partial`, so it never claims `answered`.
    const proj = (q.analysis_ids || []).map((a) => per[a]).filter(Boolean);
    if (proj.length) {
      if (proj.some((v) => v.has_results)) {
        const c = CELL.stored;
        return `<td class="wl-cell p-[6px] ${c.tone}"><button type="button" class="wl-cellbtn" data-cell="${esc(slug)}" data-q="${qi}" title="${esc(q.question)} — ${esc(c.label)}${esc(stampNote(q))}
click for the latest results">${c.glyph}${mark}</button></td>`;
      }
      if (proj.every((v) => v.certain_never_run)) {
        const c = CELL.unrun;
        return `<td class="wl-cell p-[6px] ${c.tone}"><button type="button" class="wl-cellbtn" data-cell="${esc(slug)}" data-q="${qi}" title="${esc(q.question)} — ${esc(c.label)}
click for the latest results">${c.glyph}</button></td>`;
      }
    }
    // Nothing known yet — still loading. Never "not run": that would be a
    // confident wrong answer with a delay on it.
    return '<td class="wl-cell p-[6px] text-ink-muted" title="still loading">…</td>';
  }).join('');

  const answered = row && !row.error
    ? qs.filter((q) => ['answered', 'nothing'].includes(cellState(q, row.factsById))).length
    : null;

  return `<tr class="border-b border-rule">
    <td class="wl-freeze-1 p-[6px]"><input type="checkbox" data-row="${esc(slug)}" ${
      grid.selected.has(slug) ? 'checked' : ''}></td>
    <td class="wl-freeze-2 p-[6px] text-ink">
      <span class="font-mono text-[11px]">${esc(slug)}</span>
      ${member.rationale && member.rationale !== grid.commonRationale
          ? `<div class="text-provenance text-ink-muted">${esc(member.rationale)}</div>` : ''}
    </td>
    ${cells}
    <td class="p-[6px] tnum text-ink-muted">${
      answered === null ? '—' : `${answered} of ${qs.length}`}</td>
  </tr>`;
}

/** Staleness threshold, for the mark on a cell and the wording in its popup.
 *
 * There is deliberately NO per-resource "as of" date. Each analysis ran when
 * it ran — on one row here the newest measurement is from today and the oldest
 * from 31 August — so a single date per row is wrong whichever end it takes.
 * The date belongs to the cell, and the cell shows it on click.
 */
const STALE_DAYS = 7;


/* ── One cell, opened ────────────────────────────────────────────────────
 *
 * A glyph says which state a question is in; it cannot say what the answer
 * WAS. This is where the answer lives — for one resource, one question, on
 * demand.
 *
 * On demand is the point. Reading full facts for the whole matrix costs 47s
 * on the expensive analyses; reading them for ONE cell is instant, and it is
 * the only cell anyone is looking at. The grid stays cheap and the detail
 * stays complete, instead of trading one for the other.
 */

const STATE_WORD = {
  measured: 'measured',
  nothing_found: 'ran, found nothing',
  partial: 'partial',
  not_established: 'ran, could not establish a result',
  never_run: 'never run',
};

function closeCellDetail() {
  document.getElementById('wl-detail')?.remove();
  document.removeEventListener('keydown', detailKeys);
}

function detailKeys(e) { if (e.key === 'Escape') closeCellDetail(); }

async function openCellDetail(slug, qi, ctx) {
  const q = grid.questions[qi];
  if (!q) return;
  closeCellDetail();

  const el = document.createElement('div');
  el.id = 'wl-detail';
  el.className = 'fixed inset-0 z-50 flex items-start justify-center '
    + 'bg-black/40 p-s4 overflow-auto';
  el.innerHTML = `
    <div class="mt-[6vh] w-full max-w-[640px] rounded bg-paper p-s4 shadow-lg"
      role="dialog" aria-modal="true" aria-label="Latest results">
      <div class="flex items-start justify-between gap-s3">
        <div>
          <div class="font-heading text-answer text-ink">${esc(q.question)}</div>
          <div class="mt-[2px] font-mono text-[11px] text-ink-muted">${esc(slug)}</div>
        </div>
        <button type="button" data-act="close"
          class="text-ink-muted hover:text-ink" aria-label="Close">×</button>
      </div>
      <div id="wl-detail-body" class="mt-s3 text-caveat text-ink-muted">reading…</div>
    </div>`;
  document.body.appendChild(el);
  el.addEventListener('click', (e) => {
    // The backdrop closes; the panel does not close itself out from under a
    // click meant for its own contents.
    if (e.target === el || e.target.closest('[data-act="close"]')) closeCellDetail();
  });
  document.addEventListener('keydown', detailKeys);

  const body = el.querySelector('#wl-detail-body');
  const ids = q.analysis_ids || [];
  if (!ids.length) {
    body.innerHTML = `<p>No analysis answers this question yet, so there is
      nothing to read. That is a gap in the catalog, not a finding about
      ${esc(slug)}.</p>`;
    return;
  }
  let facts;
  try {
    const res = await getBulkFacts([slug], ids);
    facts = res.subjects?.[slug] || [];
  } catch (err) {
    body.innerHTML = `<p class="text-state-warn">Could not read the results:
      ${esc(err.message)}</p>`;
    return;
  }
  // Fold what we just paid for back into the grid: a cell you have opened
  // stops being `▪ not read`, because now it HAS been read. Cheaper than the
  // matrix-wide read and it accumulates exactly where attention went.
  if (facts.length) {
    const prev = grid.rows.get(slug);
    const byId = prev?.factsById || new Map();
    for (const f of facts) byId.set(f.analysis_id, f);
    grid.rows.set(slug, { facts: [...byId.values()], factsById: byId });
    renderGrid();
  }
  if (!facts.length) {
    body.innerHTML = `<p>Nothing stored for ${esc(ids.join(', '))} on this
      resource.</p>`;
    return;
  }
  // A question is usually answered by MORE THAN ONE analysis, and they were
  // not measured at the same time — 8h ago and 3d ago on this very question.
  // So the re-run is offered per analysis, and the all-of-them action NAMES
  // them and says how many. "Re-run for this resource" said neither, and
  // quietly queued every one of them.
  const runnable = facts.map((f) => f.analysis_id).filter(Boolean);
  body.innerHTML = facts.map((f) => factDetailHtml(f, slug)).join('')
    + (runnable.length > 1
        ? `<div class="mt-s3 border-t border-rule pt-s2 text-caveat text-ink-muted">
            <button type="button" data-act="rerun"
              class="text-accent-ink underline">Re-run all
              <span class="tnum">${runnable.length}</span></button>
            — ${esc(runnable.join(', '))}. Each is queued as its own run.
          </div>`
        : '');
  el.querySelector('[data-act="rerun"]')?.addEventListener('click', () => {
    closeCellDetail();
    rerunOne(slug, runnable, ctx);
  });
  el.querySelectorAll('[data-rerun]').forEach((b) => b.addEventListener('click', () => {
    closeCellDetail();
    rerunOne(slug, [b.dataset.rerun], ctx);
  }));
}

/** One analysis's contribution, shown as what it is rather than summarised.
 *  The measurement date is HERE, per analysis, because that is the only place
 *  it is true — each one ran when it ran. */
function factDetailHtml(f, slug) {
  // WHEN this was measured, from the stronger of the two records.
  //
  // They disagree, and not rarely. `last_run_at` comes from the run registry;
  // `surveyed_at` is stamped on the result rows themselves. On amundsen's
  // repository_health the run registry said 24 August while the metrics rows
  // were written 10 September at 02:57 — something wrote results without
  // recording a run. The rows are the harder evidence: they exist because a
  // measurement happened. So they win, and `last_run_at` is the fallback.
  //
  // Using the same source as the cell also means the popup and the grid can
  // never show one date each for the same measurement.
  const measured = grid.states?.[slug]?.[f.analysis_id]?.measured_at || '';
  const when = measured || f.last_run_at || '';
  const d = daysSince(when);
  const stale = d !== null && d >= STALE_DAYS;
  const bits = [];
  if (f.headline) bits.push(`<p class="text-answer text-ink">${esc(f.headline)}</p>`);
  const verdict = f.value && f.value.verdict;
  const detail = f.value && (f.value.detail || f.value.summary);
  if (!f.headline && (verdict || detail)) {
    bits.push(`<p class="text-answer text-ink">${
      verdict ? `<strong class="font-semibold">${esc(String(verdict))}</strong>` : ''}${
      verdict && detail ? ' — ' : ''}${detail ? esc(String(detail)) : ''}</p>`);
  }
  if (!bits.length) {
    bits.push(`<p>This analysis recorded measures but no written summary, so
      there is no sentence to show. Its values are in the resource's own
      results view.</p>`);
  }
  return `<div class="mb-s3">
    <div class="text-caps text-ink-muted">
      <span class="font-mono">${esc(f.analysis_id || 'unknown')}</span>
      · ${esc(STATE_WORD[f.state] || f.state || 'unknown')}
      · ${when
          ? `<span class="${stale ? 'text-state-warn' : ''}" title="${esc(when)}"
              >${esc(ago(when))}${stale ? ' — stale' : ''}</span>`
          : 'run time not recorded'}
      ${f.analysis_id
          ? ` · <button type="button" data-rerun="${esc(f.analysis_id)}"
                class="text-accent-ink underline">re-run this one</button>`
          : ''}
    </div>
    ${bits.join('')}
  </div>`;
}

/** Re-run exactly the analyses behind one cell, for one resource — the
 *  narrowest version of "bring this up to date". Same batch machinery the
 *  whole-list run uses, so it queues rather than blocking the page. */
async function rerunOne(slug, ids, ctx) {
  let last = null;
  try {
    // One batch per analysis: enqueueBatch takes a single analysis id, and a
    // question can be answered by more than one.
    for (const aid of ids) {
      last = await enqueueBatch(aid, [slug], grid.workList.slug);
    }
  } catch (err) {
    const networkish = /load failed|failed to fetch|networkerror/i.test(err.message || '');
    note(networkish
      ? `<span class="text-state-warn">The server could not be reached, so nothing was
         enqueued (${esc(err.message)}). If it was restarting, try again.</span>`
      : `<span class="text-state-warn">The re-run was refused: ${esc(err.message)}</span>`);
    return;
  }
  note(`Queued <span class="font-mono">${esc(ids.join(', '))}</span> for
        <span class="font-mono">${esc(slug)}</span>.`);
  // Watches the LAST set only — the progress line shows one set at a time,
  // and saying so is better than silently reporting one of several as if it
  // were the whole re-run.
  if (last?.set_id) watchBatch(ctx, last.set_id);
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
  grid.ctx = ctx;   // the cell popup's re-run needs it, and it is not passed down
  await renderWorkListPane(ctx);
}

export async function saveAsWorkList(displayName, slugs, { investigation = '', rationale = '' } = {}) {
  return createWorkList(displayName, slugs, { investigation, rationale });
}

export { listWorkLists };
