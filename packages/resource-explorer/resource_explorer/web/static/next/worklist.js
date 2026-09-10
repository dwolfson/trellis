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
  //
  // HOLLOW, not filled. A filled square was the heaviest mark in the set
  // while meaning the least — "we haven't looked" — and that inversion is a
  // shape problem, not a colour one; muting a heavy shape fights it rather
  // than fixing it. Hollow reads as a container waiting to be filled, which
  // is exactly what it is: opening the cell resolves it, and so does the
  // background pass. It also sits correctly beside `○` (nothing here) and
  // the filled glyphs (something definite).
  stored:        { glyph: '□', tone: 'text-ink-muted',  label: 'has results · not read yet' },
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
  digestOpen: false,     // the digest is collapsed until asked for
  onlyQuestion: null,    // narrowed to one column, by index
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
    <button data-act="refresh"
      class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-ink"
      title="Re-run only what is stale, for ${n ? 'the selected rows' : 'every row'}. Shows the plan first."
      >Bring up to date</button>
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
  host.querySelector('[data-act="refresh"]').addEventListener('click', () => openRefreshPlan(ctx));
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

/** Fill the readout slot for one column, and mark that column's number.
 *
 * It HOLDS until another column is touched — the point is that you can read
 * the question while looking at the row you are comparing, which a tooltip
 * cannot do because it times out and covers the grid.
 */
/** Name the cause of an unreadable cell, from the server's own message.
 *
 * Deliberately a small, closed set of causes with a fallback that admits it
 * does not know. Guessing a cause would be worse than the bare `?` it
 * replaces — the point is to make a real defect recognisable on sight, and a
 * confident wrong label defeats exactly that.
 */
function whyUnreadable(msg) {
  const m = String(msg || '').toLowerCase();
  if (/timeout|timed out/.test(m)) return 'the read timed out';
  if (/no such|not found|unknown analysis|missing/.test(m)) return 'the analysis is not in the catalog';
  if (/json|decode|parse|unparsable|invalid/.test(m)) return 'the stored result could not be parsed';
  if (/permission|forbidden|denied|401|403/.test(m)) return 'not permitted to read this';
  if (/connect|refused|unreachable|network|load failed/.test(m)) return 'the server could not be reached';
  return 'the reader failed — cause not recognised';
}

/* ── The column digest ───────────────────────────────────────────────────
 *
 * One line per question showing how its states distribute across the rows in
 * view, sorted by how much is unresolved.
 *
 * At twelve rows it is a summary you glance at. Its real job is at fifty,
 * where the grid stops being scannable: the answer to scale is not a smaller
 * cell, it is an inversion — read the distribution first, then open the one
 * question that looks wrong. Growing the grid was never the fix, because a
 * matrix earns its cost by holding a cohort you can keep in your head, and
 * nobody holds fifty.
 *
 * Clicking a line narrows the grid to that question, which is the same move
 * as opening a cell, one axis up.
 */

const DIGEST_TONE = {
  answered: 'var(--wl-ok, #2f6f4f)',
  nothing: 'var(--wl-neutral, #6b6b68)',
  partial: 'var(--wl-warn, #a8712a)',
  human: 'var(--wl-warn, #a8712a)',
  stored: 'var(--wl-unread, #8d8a83)',
};
const DIGEST_REST = 'var(--wl-none, #c9c6bf)';

/** State counts for one question across the given members. */
function columnDigest(members, q) {
  const counts = {};
  let unresolved = 0;
  for (const m of members) {
    const slug = m.entity_slug;
    const row = grid.rows.get(slug);
    const per = grid.states?.[slug] || {};
    const ids = q.analysis_ids || [];
    let st;
    if (!ids.length) st = q.kind === 'gap' ? 'no-surveyor' : q.kind === 'human' ? 'human' : 'unclassified';
    else if (row && !row.error && ids.some((a) => row.factsById.has(a))) st = cellState(q, row.factsById);
    else if (ids.some((a) => per[a]?.has_results)) st = 'stored';
    else if (ids.every((a) => per[a]?.certain_never_run)) st = 'unrun';
    else st = 'unknown';
    counts[st] = (counts[st] || 0) + 1;
    // "Unresolved" means nobody has an answer yet — NOT that the answer is
    // uncomfortable. `nothing` is a result; `stored` is one we have not read.
    if (['unrun', 'human', 'unknown', 'no-surveyor'].includes(st)) unresolved += 1;
  }
  return { counts, unresolved };
}

function digestHtml(members, qs) {
  if (!qs.length || !members.length) return '';
  const rows = qs.map((q, i) => ({ q, i, ...columnDigest(members, q) }))
    .sort((a, b) => b.unresolved - a.unresolved);
  const total = members.length;
  const bar = (counts) => {
    const order = ['answered', 'nothing', 'partial', 'stored', 'human'];
    const seg = order.filter((k) => counts[k]).map((k) =>
      `<i style="width:${(counts[k] / total) * 100}%;background:${DIGEST_TONE[k]}"></i>`).join('');
    const rest = total - order.reduce((n, k) => n + (counts[k] || 0), 0);
    return seg + (rest > 0 ? `<i style="width:${(rest / total) * 100}%;background:${DIGEST_REST}"></i>` : '');
  };
  return `
    <details id="wl-digest" class="mb-s3" ${grid.digestOpen ? 'open' : ''}>
      <summary class="cursor-pointer text-caps uppercase tracking-caps text-ink-muted">
        Column digest · <span class="tnum">${qs.length}</span> questions ×
        <span class="tnum">${total}</span> resources · sorted by unresolved
      </summary>
      <div class="mt-s2">
        ${rows.map((r) => `<button type="button" data-digest="${r.i}"
          class="flex w-full items-center gap-s2 border-0 bg-transparent px-0 py-[4px] text-left text-caveat text-ink hover:bg-[rgba(32,31,29,.05)]">
          <span class="tnum w-[22px] shrink-0 text-right font-mono text-ink-muted">${r.i + 1}</span>
          <span class="min-w-0 flex-1 truncate">${esc(r.q.question)}</span>
          <span class="wl-bar flex h-[9px] w-[160px] shrink-0 overflow-hidden rounded-[2px]">${bar(r.counts)}</span>
          <span class="tnum w-[34px] shrink-0 text-right ${
            r.unresolved ? 'text-accent-ink' : 'text-ink-muted'}">${r.unresolved}</span>
        </button>`).join('')}
      </div>
    </details>`;
}

/** Rows in triage order, banded by disposition.
 *
 * NAME ORDER IS A FILING CONVENTION and means nothing in a triage view. Two
 * changes, both aimed at the eye:
 *
 * - Within a band, the least resolved rows come FIRST. Ragged rows collect at
 *   one end instead of being sprinkled through, so the eye stops sweeping
 *   settled space looking for work.
 * - Bands by disposition, because once verdicts land a long grid is really
 *   several small grids — kept, parked, dropped — and only one of them is
 *   still work.
 *
 * Returns a flat list of `{member}` and `{band, count}` entries so the table
 * body stays one map.
 */
function orderedRows(members, qs) {
  const unresolvedOf = (m) => {
    const per = grid.states?.[m.entity_slug] || {};
    const row = grid.rows.get(m.entity_slug);
    let n = 0;
    for (const q of qs) {
      const ids = q.analysis_ids || [];
      if (!ids.length) continue;
      const settled = row && !row.error
        && ['answered', 'nothing'].includes(cellState(q, row.factsById));
      const stored = ids.some((a) => per[a]?.has_results);
      if (!settled && !stored) n += 1;
    }
    return n;
  };
  const byBand = new Map();
  for (const m of members) {
    const d = m.disposition || 'undecided';
    byBand.set(d, [...(byBand.get(d) || []), m]);
  }
  // Bands in the order a triage session works through them, not alphabetical.
  const ORDER = ['undecided', 'investigating', 'tracking', 'recommended',
                 'using', 'abandoned', 'ignored'];
  const bands = [...byBand.keys()].sort(
    (a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99));
  const out = [];
  const banded = bands.length > 1;   // one band is not a grouping, it is noise
  for (const b of bands) {
    const rows = byBand.get(b).sort((x, y) => unresolvedOf(y) - unresolvedOf(x));
    if (banded) out.push({ band: b, count: rows.length });
    for (const m of rows) out.push({ member: m });
  }
  return out;
}

function readout(qi) {
  const q = grid.questions[qi];
  const el = document.getElementById('wl-readout');
  if (!q || !el) return;
  const ids = q.analysis_ids || [];
  el.innerHTML = `
    <span class="tnum font-mono text-accent-ink">${qi + 1}</span>
    <span class="text-ink">${esc(q.question)}</span>
    <span class="ml-auto shrink-0 text-provenance text-ink-muted">${
      ids.length
        ? `<span class="tnum">${ids.length}</span> ${
            ids.length === 1 ? 'analysis' : 'analyses'} · ${esc(ids.join(', '))}`
        : esc(q.kind === 'gap' ? 'no surveyor exists for this'
            : q.kind === 'human' ? 'answered by a person'
            : q.kind === 'direct' ? 'a direct field, not a survey'
            : 'no analysis is mapped to this')}</span>`;
  const host = document.getElementById('wl-grid');
  host?.querySelectorAll('th[data-col]').forEach((th) => {
    th.classList.toggle('wl-col-live', Number(th.dataset.col) === qi);
  });
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

  // The columns actually rendered. Narrowing keeps each question's TRUE
  // index, so cell clicks, the readout and the key all still address the same
  // question they did in the full grid.
  const shown = grid.onlyQuestion == null || !qs[grid.onlyQuestion]
    ? qs.map((q, i) => ({ q, i }))
    : [{ q: qs[grid.onlyQuestion], i: grid.onlyQuestion }];

  const cr = document.getElementById('wl-common-rationale');
  if (cr) cr.textContent = grid.commonRationale ? `All members: ${grid.commonRationale}` : '';

  host.innerHTML = `
    ${digestHtml(wl.members, qs)}
    <div id="wl-readout" class="mb-s2 flex items-baseline gap-s2 border-b border-rule pb-[4px] text-caveat">
      <span class="text-ink-muted">Hover or focus a column to read its question.</span>
    </div>
    ${grid.onlyQuestion != null && qs[grid.onlyQuestion] ? `
      <div class="mb-s2 text-caveat text-accent-ink">
        Showing question <span class="tnum">${grid.onlyQuestion + 1}</span> only ·
        <button type="button" data-act="all-cols"
          class="cursor-pointer bg-transparent underline">show all
          <span class="tnum">${qs.length}</span></button>
      </div>` : ''}
    <table class="w-full border-collapse text-caveat">
      <thead>
        <tr class="border-b border-rule">
          <th class="wl-freeze-1 w-[26px] p-[6px]"></th>
          <th class="wl-freeze-2 p-[6px] text-left font-heading text-ink">Resource</th>
          ${shown.map(({ q, i }) => `<th class="wl-col p-[6px] align-bottom font-heading text-ink"
            data-col="${i}" title="${esc(q.question)}">
            <span class="tnum">${i + 1}</span></th>`).join('')}
          <th class="p-[6px] text-left font-heading text-ink">Answered</th>
        </tr>
      </thead>
      <tbody>
        ${orderedRows(wl.members, qs).map((entry) => entry.band
          ? `<tr class="wl-band"><td colspan="${shown.length + 3}"
               class="p-[6px] text-caps uppercase tracking-caps text-ink-muted">
               ${esc(entry.band)} · <span class="tnum">${entry.count}</span></td></tr>`
          : rowHtml(entry.member, shown, qs)).join('')}
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

  host.querySelectorAll('button[data-cell]').forEach((b) => {
    b.addEventListener('click', () => openCellDetail(b.dataset.cell, Number(b.dataset.q), grid.ctx));
    // Pointer AND keyboard, the same way. A tooltip only ever served the first.
    b.addEventListener('mouseenter', () => readout(Number(b.dataset.q)));
    b.addEventListener('focus', () => readout(Number(b.dataset.q)));
  });
  host.querySelector('[data-act="all-cols"]')?.addEventListener('click', () => {
    grid.onlyQuestion = null;
    renderGrid();
  });
  host.querySelector('#wl-digest')?.addEventListener('toggle', (e) => {
    grid.digestOpen = e.target.open;
  });
  host.querySelectorAll('button[data-digest]').forEach((b) => {
    b.addEventListener('mouseenter', () => readout(Number(b.dataset.digest)));
    b.addEventListener('click', () => {
      // Narrowing to one question is the same move as opening one cell, one
      // axis up: same rows, one column, nothing hidden that was not chosen.
      grid.onlyQuestion = grid.onlyQuestion === Number(b.dataset.digest)
        ? null : Number(b.dataset.digest);
      renderGrid();
    });
  });
  host.querySelectorAll('th[data-col]').forEach((th) => {
    th.addEventListener('mouseenter', () => readout(Number(th.dataset.col)));
  });
  host.querySelectorAll('input[data-row]').forEach((cb) => cb.addEventListener('change', () => {
    if (cb.checked) grid.selected.add(cb.dataset.row);
    else grid.selected.delete(cb.dataset.row);
    renderActions(window.__wlCtx);
  }));
}

function rowHtml(member, shown, qs) {
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

  const cells = shown.map(({ q, i: qi }) => {
    // AGE IS A RULE UNDER THE GLYPH, not a mark beside it.
    //
    // An appended `·` inside a 26px cell was very nearly invisible, and it
    // could only ever say one bit. A rule on the cell's baseline does not
    // compete with the glyph for the same pixels, survives print, reads as an
    // annotation rather than as part of the mark — and it GRADES, which age
    // deserves, being continuous. Nothing under 7 days, a short hairline past
    // 7, the full cell width past 30.
    //
    // Still no recolouring: "this answer is old" and "this answer is bad" are
    // different claims, and the warn colour is already spent on the second.
    // Three channels that cannot collide — glyph says what state, hue says
    // whether a person is needed, rule says how old. A column of stale cells
    // then reads as a broken underline running down the grid.
    const ageClass = ageRule(cellStamp(q));

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
      // results. One state for "we could not look", never blank — and it says
      // WHY, because "could not read" found a real defect this round only
      // because somebody happened to be looking at it. A `?` that names its
      // own cause turns that accident into a routine catch.
      return `<td class="wl-cell p-[6px] ${CELL.unknown.tone}"
        title="${esc(q.question)} — ${esc(whyUnreadable(row.error))}\n${esc(row.error)}"
        >${CELL.unknown.glyph}</td>`;
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
      return `<td class="wl-cell p-[6px] ${c.tone}"><button type="button" class="wl-cellbtn ${ageClass}" data-cell="${esc(slug)}" data-q="${qi}" title="${esc(q.question)} — ${esc(c.label)}${esc(stampNote(q))}
click for the latest results">${c.glyph}</button></td>`;
    }
    // Otherwise the CHEAP PROJECTION answers, and only as far as it honestly
    // can: there is stored output, or there provably is not. It cannot tell
    // `measured` from `partial`, so it never claims `answered`.
    const proj = (q.analysis_ids || []).map((a) => per[a]).filter(Boolean);
    if (proj.length) {
      if (proj.some((v) => v.has_results)) {
        const c = CELL.stored;
        return `<td class="wl-cell p-[6px] ${c.tone}"><button type="button" class="wl-cellbtn ${ageClass}" data-cell="${esc(slug)}" data-q="${qi}" title="${esc(q.question)} — ${esc(c.label)}${esc(stampNote(q))}
click for the latest results">${c.glyph}</button></td>`;
      }
      if (proj.every((v) => v.certain_never_run)) {
        const c = CELL.unrun;
        return `<td class="wl-cell p-[6px] ${c.tone}"><button type="button" class="wl-cellbtn ${ageClass}" data-cell="${esc(slug)}" data-q="${qi}" title="${esc(q.question)} — ${esc(c.label)}
click for the latest results">${c.glyph}</button></td>`;
      }
    }
    // Nothing known yet — still loading. Never "not run": that would be a
    // confident wrong answer with a delay on it.
    return '<td class="wl-cell p-[6px] text-ink-muted" title="still loading">…</td>';
  }).join('');

  const staleCount = qs.reduce((n, q) => {
    const stamps = (q.analysis_ids || []).map((a) => per[a]?.measured_at || '').filter(Boolean);
    if (!stamps.length) return n;
    const d = daysSince(stamps.sort()[0]);
    return n + (d !== null && d >= STALE_DAYS ? 1 : 0);
  }, 0);

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
      answered === null ? '—' : `${answered} of ${qs.length}`}${
      // A row's age signal is a COUNT, not a date and not a span. A span is
      // two dates to interpret in a narrow column, where the first reads as
      // "the" date; a count is a plain fact about the row — how many of its
      // cells are old — and needs no interpretation at all.
      staleCount ? `<div class="text-provenance text-state-warn"
        title="Measured more than ${STALE_DAYS} days ago. The dates themselves are on the cells."
        >${staleCount} stale</div>` : ''}</td>
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
/** Past this, the rule runs the full width of the cell. */
const VERY_STALE_DAYS = 30;

/** The age rule's class for one measurement date: '' / short / full. */
function ageRule(iso) {
  const d = daysSince(iso);
  if (d === null) return '';
  if (d >= VERY_STALE_DAYS) return 'wl-age2';
  if (d >= STALE_DAYS) return 'wl-age1';
  return '';
}


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

/** The panel shell both the cell popup and the refresh plan use. One shell,
 *  so the two cannot drift apart in behaviour — backdrop closes, Escape
 *  closes, a click inside does not. */
function openDialog(title, sub) {
  closeCellDetail();
  const el = document.createElement('div');
  el.id = 'wl-detail';
  el.className = 'fixed inset-0 z-50 flex items-start justify-center '
    + 'bg-black/40 p-s4 overflow-auto';
  el.innerHTML = `
    <div class="mt-[6vh] w-full max-w-[640px] rounded bg-paper p-s4 shadow-lg"
      role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="flex items-start justify-between gap-s3">
        <div>
          <div class="font-heading text-answer text-ink">${esc(title)}</div>
          ${sub ? `<div class="mt-[2px] font-mono text-[11px] text-ink-muted">${esc(sub)}</div>` : ''}
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
  return el;
}

/* ── Bringing things up to date ───────────────────────────────────────────
 *
 * Staleness is per CELL, so refreshing is too. "Bring everything up to date"
 * across a twelve-repo list would re-run analyses measured this morning
 * alongside ones last measured in August — most of the work wasted, and none
 * of it visible before it started.
 *
 * So this plans first: which (resource, analysis) pairs are actually stale,
 * grouped BY ANALYSIS, because that is how a batch is enqueued — one run per
 * analysis carrying only the resources that need it. What is current is named
 * and skipped. What has NEVER run is counted separately and left out by
 * default: a first run is not a refresh, it can cost far more, and nobody
 * asking to freshen a matrix is asking to populate it.
 */

/** `{stale, never, current}` for `slugs` over the current columns. */
function refreshPlan(slugs) {
  const ids = [...new Set(qsAnalysisIds(grid.questions))];
  const stale = new Map();     // analysis id -> [slug]
  const never = new Map();     // analysis id -> [slug]
  let current = 0;
  // Pairs the projection knows NOTHING about. A confident zero here would be
  // the same failure the cells were fixed for: the fast path must not report
  // certainty it does not have, and "never run" is a claim, not a default.
  let unknown = 0;
  for (const slug of slugs) {
    const per = grid.states?.[slug] || {};
    for (const aid of ids) {
      const v = per[aid];
      // No projection entry means nothing has been established about this
      // pair. Not stale, not never-run — unknown, and unknown is not a
      // reason to run something.
      if (!v) { unknown += 1; continue; }
      if (!v.has_results) {
        if (v.certain_never_run) never.set(aid, [...(never.get(aid) || []), slug]);
        continue;
      }
      const d = daysSince(v.measured_at);
      if (d === null) continue;    // has results but no usable date: not evidence of age
      if (d >= STALE_DAYS) stale.set(aid, [...(stale.get(aid) || []), slug]);
      else current += 1;
    }
  }
  return { stale, never, current, unknown };
}

const planSize = (m) => [...m.values()].reduce((n, a) => n + a.length, 0);

function openRefreshPlan(ctx) {
  const slugs = targets();
  const scope = grid.selected.size ? `${grid.selected.size} selected` : 'all rows';
  const plan = refreshPlan(slugs);
  const el = openDialog('Bring up to date', `${slugs.length} resource(s) · ${scope}`);
  const body = el.querySelector('#wl-detail-body');

  const staleCount = planSize(plan.stale);
  const neverCount = planSize(plan.never);
  if (!staleCount && !neverCount) {
    body.innerHTML = `<p>Nothing here was measured more than
      <span class="tnum">${STALE_DAYS}</span> days ago.
      <span class="tnum">${plan.current}</span> measurement(s) across
      <span class="tnum">${slugs.length}</span> resource(s) are current, so
      there is nothing to refresh.</p>`;
    return;
  }

  const listing = (m) => [...m.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .map(([aid, ss]) => `<li><span class="font-mono">${esc(aid)}</span>
      — <span class="tnum">${ss.length}</span> resource(s)</li>`).join('');

  body.innerHTML = `
    ${staleCount
      ? `<p>Stale — measured more than <span class="tnum">${STALE_DAYS}</span> days ago:</p>
         <ul class="ml-s3 mt-[4px] list-disc">${listing(plan.stale)}</ul>`
      : `<p>Nothing is stale.</p>`}
    ${plan.current ? `<p class="mt-s2"><span class="tnum">${plan.current}</span>
      measurement(s) are already current and will be skipped.</p>` : ''}
    ${plan.unknown ? `<p class="mt-s2"><span class="tnum">${plan.unknown}</span>
      pair(s) have no state read yet, so whether they have ever run is
      <em>unknown</em>, not no. They are left out — this plan will not claim a
      first run for something it has not looked at.</p>` : ''}
    ${neverCount ? `
      <p class="mt-s2">
        <label><input type="checkbox" id="wl-incl-never"> also run the
        <span class="tnum">${neverCount}</span> that ${
          neverCount === 1 ? 'has' : 'have'} never run</label>
        — a first run, not a refresh, and it can cost far more.</p>
      <ul class="ml-s3 mt-[4px] list-disc" id="wl-never-list" hidden>${listing(plan.never)}</ul>`
      : ''}
    <p class="mt-s3 text-ink">This queues <span class="tnum" id="wl-plan-n">${staleCount}</span>
      run(s), one batch per analysis carrying only the resources that need it.
      Nothing runs until you confirm.</p>
    <div class="mt-s3 flex gap-s3 border-t border-rule pt-s2">
      <button type="button" data-act="go"
        class="cursor-pointer rounded-sm border border-accent px-2 py-[2px] text-accent-ink"
        >Queue them</button>
      <button type="button" data-act="close"
        class="cursor-pointer bg-transparent text-ink-muted underline">Cancel</button>
    </div>`;

  const incl = body.querySelector('#wl-incl-never');
  incl?.addEventListener('change', () => {
    body.querySelector('#wl-never-list').hidden = !incl.checked;
    body.querySelector('#wl-plan-n').textContent =
      planSize(plan.stale) + (incl.checked ? planSize(plan.never) : 0);
  });
  body.querySelector('[data-act="go"]').addEventListener('click', () => {
    // Merged per analysis, so one that is stale on some resources and never
    // run on others is ONE batch, not two.
    const merged = new Map();
    for (const [aid, ss] of plan.stale) merged.set(aid, [...ss]);
    if (incl?.checked) {
      for (const [aid, ss] of plan.never) {
        merged.set(aid, [...new Set([...(merged.get(aid) || []), ...ss])]);
      }
    }
    closeCellDetail();
    runRefresh(merged, ctx);
  });
}

/** Enqueue one batch per analysis, each carrying only its own resources. */
async function runRefresh(byAnalysis, ctx) {
  const entries = [...byAnalysis.entries()];
  if (!entries.length) return;
  let last = null;
  const done = [];
  for (const [aid, ss] of entries) {
    try {
      last = await enqueueBatch(aid, ss, grid.workList.slug);
      done.push(`${aid} \u00d7 ${ss.length}`);
    } catch (err) {
      // Report what DID get queued. A failure on the fourth analysis does not
      // un-queue the first three, and "it failed" would leave three batches
      // running that nobody was told about.
      note(`<span class="text-state-warn">Queued ${done.length ? esc(done.join(', ')) : 'nothing'},
        then <span class="font-mono">${esc(aid)}</span> was refused:
        ${esc(err.message)}</span>`);
      if (last?.set_id) watchBatch(ctx, last.set_id);
      return;
    }
  }
  note(`Queued ${esc(done.join(', '))}. Watching the last batch.`);
  if (last?.set_id) watchBatch(ctx, last.set_id);
}

async function openCellDetail(slug, qi, ctx) {
  const q = grid.questions[qi];
  if (!q) return;
  const el = openDialog(q.question, slug);
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

/**
 * Run one analysis across the set — THROUGH THE SAME PLAN PREVIEW the refresh
 * uses.
 *
 * Both actions answer one question, "what am I about to spend", and if they
 * answer it in two different shapes people learn to read one and skim the
 * other. So this one shows what it would run and what it already has, and
 * queues nothing until it is confirmed.
 */
function runBatch(ctx) {
  const analysisId = document.getElementById('wl-analysis')?.value;
  if (!analysisId) { note('<span class="text-state-warn">No analysis selected.</span>'); return; }
  const slugs = targets();
  const scope = grid.selected.size ? `${grid.selected.size} selected` : 'all rows';
  const el = openDialog('Run across the set', `${analysisId} · ${slugs.length} resource(s) · ${scope}`);
  const body = el.querySelector('#wl-detail-body');

  // What is already held for this analysis, so "run it again" is a choice
  // rather than an accident.
  let fresh = 0, stale = 0, none = 0;
  for (const slug of slugs) {
    const v = grid.states?.[slug]?.[analysisId];
    if (!v || !v.has_results) { none += 1; continue; }
    const d = daysSince(v.measured_at);
    if (d !== null && d >= STALE_DAYS) stale += 1; else fresh += 1;
  }
  body.innerHTML = `
    <p>This runs <span class="font-mono">${esc(analysisId)}</span> on
      <span class="tnum">${slugs.length}</span> resource(s), whatever they
      already hold.</p>
    <ul class="ml-s3 mt-s2 list-disc">
      <li><span class="tnum">${none}</span> have no result for it</li>
      <li><span class="tnum">${stale}</span> were measured more than
        <span class="tnum">${STALE_DAYS}</span> days ago</li>
      <li><span class="tnum">${fresh}</span> were measured more recently —
        <strong>these will be re-run too</strong>. To skip them, use
        <em>Bring up to date</em> instead.</li>
    </ul>
    <p class="mt-s3 text-ink">Nothing runs until you confirm.</p>
    <div class="mt-s3 flex gap-s3 border-t border-rule pt-s2">
      <button type="button" data-act="go"
        class="cursor-pointer rounded-sm border border-accent px-2 py-[2px] text-accent-ink"
        >Run <span class="tnum">${slugs.length}</span></button>
      <button type="button" data-act="close"
        class="cursor-pointer bg-transparent text-ink-muted underline">Cancel</button>
    </div>`;
  body.querySelector('[data-act="go"]').addEventListener('click', () => {
    closeCellDetail();
    enqueueRun(ctx, analysisId, slugs);
  });
}

async function enqueueRun(ctx, analysisId, slugs) {
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
