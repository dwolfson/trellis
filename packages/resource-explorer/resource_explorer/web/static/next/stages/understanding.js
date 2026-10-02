/* Understanding — charts.
 *
 * Moved out of app.js (PLAN-FINISH-REPOS.md, Part 2 §1): app.js keeps
 * routing, shared state and chrome; each stage owns its own pane's
 * rendering logic. This is Understanding's whole pane — `loadPane()` in
 * app.js calls `loadChartsPane()` directly for `state.stage === 'understanding'`
 * and returns, without going through the generic Questions-checklist engine
 * every other stage shares (see app.js's own comment at that call site).
 *
 * The lower-level chart-rendering machinery (`drawChart`, `chartLayout`,
 * `chartAxes`, `timeAxisData`, `tokens`, `asFigure`, `allPointDates`,
 * `chartIsStale`) stays in app.js rather than moving here, because
 * `drawChart`/`chartLayout`/`tokens` are also used by app.js's own
 * `promoteToPane()` — the chat "promote an answer into the pane" feature,
 * which can promote a chart from ANY stage's chat turn, not just
 * Understanding's. That machinery is shared chrome-adjacent infrastructure,
 * not something this stage owns alone; only the actual per-stage entry
 * point (`loadChartsPane`) is Understanding's to keep changing.
 */
import { REPO_CHARTS, getChart, getDbChart, getDatabaseDiff } from '/static/re-api.js';
import {
  state, esc, $, paneMessage, bindSubTabs, resourceHeaderHtml, bindResourceHeader,
  asFigure, allPointDates, chartIsStale, drawChart, apiEntityType,
  chartLayout, loadScript,
} from '/static/next/app.js';
import { provenanceFromResponse, saveChartImage } from '/static/next/chart-export.js';

/* ── Understanding for a database ─────────────────────────────────────────
 *
 * REPLY-DESIGNER-CURATE-AND-UNDERSTANDING-ALL-KINDS.md §3-§5. Two sections,
 * "Now" (one run, named in the header) and "Over time". The repo chart kinds
 * and CHART_NO_EQUIVALENT_REASON are gone: a database sees ITS charts.
 *
 * Every status word on screen is read from the response it describes
 * (`state`, `reasons`, `not_established_count`, `run`, `scope`), never from
 * which branch of this file ran. A `not_measured` response draws no figure
 * at all, so a "zero" cannot appear where nothing was measured.
 */
export const FILE_SHARE_SENTENCE =
  'No charts for file shares yet. Their survey isn\'t charted anywhere today.';

//: The chart kinds a database has, in the order a person asks. `route` is
//: the stats route that serves it; a kind with no route is listed and
//: explained ("not wired up yet"), never hidden.
export const DB_CHARTS = [
  { kind: 'schema_distribution', section: 'now', title: 'Tables and columns per schema',
    route: 'schema_distribution', counts: 'tables and columns per schema' },
  { kind: 'table_sizes', section: 'now', title: 'Largest tables, by rows',
    route: 'table_sizes', counts: '' },
  { kind: 'column_types', section: 'now', title: 'Column types',
    route: 'column_types', counts: 'columns per declared type' },
  { kind: 'survey_history', section: 'time', title: 'Structure over runs',
    route: 'survey_history', counts: 'schemas, tables and columns per run, one point per run' },
  { kind: 'table_growth', section: 'time', title: 'Rows per table over runs',
    route: 'table_growth', counts: 'established row counts of the largest tables, per run' },
  { kind: 'table_activity', section: 'time', title: 'Activity per table',
    route: null, counts: '' },
];

const STATE_WORD = { measured: 'measured', partial: 'partial', not_measured: 'not measured' };
const STATE_GLYPH = { measured: '●', partial: '◐', not_measured: '○' };

//: Reason codes the chart routes return, in words. A code not listed shows
//: as itself: an unexplained code is visible, an invented sentence is not.
const REASON_WORDS = {
  credential_scope: 'this credential could read only part of the database',
  row_counts_not_established: 'some row counts are not established',
  sizes_not_established: 'some sizes are not established',
  type_not_recorded: 'some columns have no recorded type',
  runs_without_table_measurement: 'some runs did not measure tables',
  row_counts_missing_in_some_runs: 'some runs have no established row count for some tables',
  never_surveyed: 'no survey has run for this database',
  not_materialized: 'this run predates the structured tables and has not been backfilled',
  not_permitted: 'the credential was not permitted to read this',
  not_collected: 'the server has not collected the statistics for this',
  not_supported: 'this database engine cannot provide this',
  not_measured: 'the step that measures this did not run in that survey',
  no_run_measured_tables: 'no run measured tables',
};
const reasonWord = (r) => REASON_WORDS[r]
  || (/^columns_/.test(r) ? `columns were not measured in this run (${r.slice(8)})` : r);

/** The state line, from the response's own `state` and `reasons`. */
export function stateLineHtml(resp) {
  const st = resp && resp.state;
  const word = STATE_WORD[st];
  if (!word) {
    return `<span data-state="unreported" class="text-state-warn">state not reported by the server</span>`;
  }
  const reasons = Array.isArray(resp.reasons) ? resp.reasons : [];
  return `<span data-state="${esc(st)}" class="${st === 'measured' ? 'text-ink-muted' : 'text-state-gap'}">${
    STATE_GLYPH[st]} ${esc(word)}${reasons.length
    ? ` — ${esc(reasons.map(reasonWord).join('; '))}` : ''}</span>`;
}

const fmtN = (n) => (typeof n === 'number' ? n.toLocaleString('en-US') : String(n));

/** "09-28 14:02" from a run's own timestamp; the full value is the title. */
function runLabel(run) {
  const t = String((run && run.surveyed_at) || '');
  const m = t.match(/^\d{4}-(\d{2}-\d{2})[T ](\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : t;
}

function provenanceLineHtml(slug, resp, counts) {
  const run = resp && resp.run;
  const where = run
    ? `run <span class="tnum">${esc(run.surveyed_at)}</span> · source ${esc(run.source || 'unknown')}`
    : 'no run';
  return `${esc(slug)} · ${where}${counts ? ` · ${esc(counts)}` : ''}`;
}

async function plotlyGlobal() {
  if (typeof window !== 'undefined' && window.Plotly) return window.Plotly;
  await loadScript('/static/vendor/plotly.min.js');
  return window.Plotly;
}

const LINK_BTN = `cursor-pointer border-0 bg-transparent p-0 text-caveat text-accent-ink underline`;

/** One chart card. Draws the response's figure unless the response says it
 *  measured nothing. Everything it says comes from `resp`. */
async function drawCard(card, spec, slug, resp, { counts = spec.counts, extraHtml = '' } = {}) {
  const body = card.querySelector('[data-card-body]');
  const provenance = card.querySelector('[data-card-provenance]');
  card.dataset.cardState = (resp && resp.state) || 'unreported';
  card.querySelector('[data-card-state]').innerHTML = stateLineHtml(resp);

  if (!resp || resp.state === 'not_measured') {
    // Not-run family, in the chart's own slot: never "no data", never zeros.
    const reasons = (resp && resp.reasons) || [];
    const neverRan = reasons.includes('never_surveyed');
    body.innerHTML = `<div class="mt-s2 text-answer text-ink" data-not-measured>${
      neverRan
        ? '○ not run: needs a database survey'
        : `○ not measured — ${esc(((resp && resp.notes) || [])[0]
          || reasons.map(reasonWord).join('; ') || 'the server did not say why')}`}${
      neverRan ? `<div class="mt-s2"><button data-run-survey type="button"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px]
               text-caveat text-accent-ink">Run survey ›</button></div>` : ''}${extraHtml}</div>`;
    const rs = body.querySelector('[data-run-survey]');
    if (rs) {
      rs.addEventListener('click', () => {
        const nav = document.querySelector('#intent-nav button[data-stage="discovery"]');
        if (nav) nav.click();
      });
    }
    provenance.innerHTML = provenanceLineHtml(slug, resp, '');
    return;
  }

  const fig = resp.figure;
  body.innerHTML = `<div data-plot style="height:260px"></div>${extraHtml}`;
  const plot = body.querySelector('[data-plot]');
  provenance.innerHTML = `${provenanceLineHtml(slug, resp, counts)} ·
    <button data-save-image type="button"
      class="cursor-pointer border-0 bg-transparent p-0 text-provenance text-accent-ink underline">Save image</button>
    <span data-save-status class="text-ink-muted"></span>`;
  if (!fig || !Array.isArray(fig.data)) {
    plot.outerHTML = '<div class="text-caveat text-ink-muted" data-no-figure>The server sent no figure for this chart.</div>';
    return;
  }
  const layout = JSON.parse(JSON.stringify(fig.layout || {}));
  delete layout.title;
  const horizontal = fig.data.some((t) => t.orientation === 'h');
  const themed = Object.assign(chartLayout(layout), {
    margin: { l: horizontal ? 150 : 56, r: 16, t: 12, b: 40 },
  });
  try {
    const Plotly = await plotlyGlobal();
    await Plotly.newPlot(plot, fig.data, themed, { displaylogo: false, responsive: true });
  } catch (err) {
    plot.outerHTML = `<div class="text-answer text-state-warn">${esc(spec.title)} could not be drawn: ${esc(err.message)}</div>`;
  }
  const status = provenance.querySelector('[data-save-status]');
  provenance.querySelector('[data-save-image]').addEventListener('click', async () => {
    status.textContent = '';
    try {
      const Plotly = await plotlyGlobal();
      const title = card.querySelector('[data-card-title]').textContent;
      const out = await saveChartImage({
        Plotly,
        figure: { data: fig.data, layout: Object.assign({}, themed, {
          title: { text: title }, margin: Object.assign({}, themed.margin, { t: 48 }) }) },
        provenance: provenanceFromResponse(slug, title, resp),
      });
      status.textContent = ' saved';
      card.dataset.lastFooter = out.footer;
    } catch (err) {
      status.textContent = ` could not save: ${err.message}`;
    }
  });
}

function cardShell(spec) {
  const card = document.createElement('div');
  card.dataset.chart = spec.kind;
  card.className = 'rounded-sm border border-rule-strong p-s3';
  card.innerHTML = `
    <div class="font-heading text-name" data-card-title>${esc(spec.title)}</div>
    <div class="mt-[2px] text-caveat" data-card-state></div>
    <div data-card-body><div class="mt-s2 text-caveat text-ink-muted">Reading…</div></div>
    <div class="mt-s2 text-provenance text-ink-muted" data-card-provenance></div>`;
  return card;
}

/** Names behind a count ("counts open what they counted"): the count is a
 *  button, the names are a hidden block that sits AFTER the sentence so
 *  opening it never breaks the sentence in two. */
let _namesSeq = 0;
function namesToggle(label, names) {
  if (!names || !names.length) return { label, block: '' };
  const id = `names-${_namesSeq += 1}`;
  return {
    label: `<button type="button" data-names-toggle="${id}" class="${LINK_BTN}">${label}</button>`,
    block: `<div hidden data-names="${id}" class="mt-[2px] font-diagram text-provenance">${names.map(esc).join('<br>')}</div>`,
  };
}

/** One delegated handler per host: a names toggle opens its block. */
function bindNamesToggles(root) {
  root.addEventListener('click', (ev) => {
    const t = ev.target.closest && ev.target.closest('[data-names-toggle]');
    if (!t) return;
    const block = root.querySelector(`[data-names="${t.dataset.namesToggle}"]`);
    if (block) block.hidden = !block.hidden;
  });
}

function tableSizesExtra(resp, measure) {
  const what = measure === 'size' ? 'sizes' : 'row counts';
  const other = measure === 'size' ? 'rows' : 'size';
  const bits = [];
  const n = resp.not_established_count || 0;
  if (n) {
    const names = namesToggle(`<span class="tnum">${n}</span> tables' ${what}`, resp.not_established_tables);
    bits.push(`<div class="mt-s2 text-caveat text-ink" data-not-established>? ${names.label
    } not established — statistics not gathered on the server · <button data-measure="${other}" type="button"
      class="${LINK_BTN}">${measure === 'size' ? 'by rows instead ›' : 'by size instead ›'}</button>${names.block}</div>`);
  } else if (resp.state === 'not_measured' && measure === 'rows') {
    bits.push(`<div class="mt-s2 text-caveat text-ink"><button data-measure="size" type="button"
      class="${LINK_BTN}">by size instead ›</button></div>`);
  }
  if (resp.truncated_by_limit) {
    bits.push(`<div class="mt-[2px] text-caveat text-ink-muted" data-truncated>Showing the largest ${
      fmtN(resp.tables.length)} of ${fmtN(resp.ranked_count)} with an established ${
      measure === 'size' ? 'size' : 'row count'}.</div>`);
  }
  if (resp.views_excluded) {
    bits.push(`<div class="mt-[2px] text-caveat text-ink-muted">${fmtN(resp.views_excluded)} views not counted: a view has no row count to establish.</div>`);
  }
  return bits.join('');
}

function columnTypesExtra(resp) {
  return resp.type_not_recorded
    ? `<div class="mt-s2 text-caveat text-ink" data-type-not-recorded>? type not recorded · <span class="tnum">${fmtN(resp.type_not_recorded)}</span></div>`
    : '';
}

function schemaScopeExtra(resp) {
  const limited = Object.entries(resp.schema_scope || {}).filter(([, v]) => v && v !== 'readable');
  return limited.length
    ? `<div class="mt-s2 text-caveat text-ink-muted">Not fully readable with this credential: ${
      esc(limited.map(([n, v]) => `${n} (${String(v).replace(/_/g, ' ')})`).join(', '))}.</div>`
    : '';
}

/** "Since the last run": a sentence from the existing diff route only. */
export function sinceLastRunHtml(diff) {
  if (!diff || !diff.curr_date) {
    return 'Only one run so far — nothing to compare.';
  }
  const since = String(diff.prev_date || '').slice(0, 10);
  if (diff.table_diff_state !== 'measured') {
    return `Since the run of ${esc(since)}: ${esc(diff.table_diff_note
      || 'the two runs cannot be compared table by table.')}`;
  }
  const added = diff.new_tables || [];
  const removed = diff.removed_tables || [];
  const dCols = (diff.deltas || {}).columns;
  const parts = [];
  const blocks = [];
  const add = (label, names) => { const n = namesToggle(label, names); parts.push(n.label); blocks.push(n.block); };
  if (added.length) add(`${added.length} table${added.length === 1 ? '' : 's'} added`, added);
  if (removed.length) add(`${removed.length} removed`, removed);
  if (typeof dCols === 'number' && dCols !== 0) {
    parts.push(`${Math.abs(dCols)} columns net ${dCols > 0 ? 'added' : 'removed'}`);
  }
  return `Since the run of ${esc(since)}: ${parts.length
    ? parts.join(', ') : 'no tables added or removed and no net change in columns'}.${blocks.join('')}`;
}

/** Understanding on a database. Draws into `#understanding-host`; a missing
 *  host throws (the caller writes the message), it never returns silently. */
export async function renderDatabaseUnderstanding(slug) {
  const host = $('understanding-host');
  if (!host) throw new Error('Understanding pane host missing: #understanding-host');
  const stale = () => slug !== state.selectedSlug || state.stage !== 'understanding';
  bindNamesToggles(host);

  const slot = (c) => `<div data-slot="${c.kind}"></div>`;
  const grid = 'style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))"';
  host.innerHTML = `
    <div id="chart-index" class="mb-s3 flex flex-wrap gap-s2" data-chart-index></div>
    <section data-section="now">
      <div class="flex items-baseline gap-s2"><h3 class="m-0 font-heading text-name font-normal">Now</h3>
        <span class="text-caveat text-ink-muted" data-now-header>reading the latest survey…</span></div>
      <div class="mt-s2 grid gap-s3" ${grid}>${DB_CHARTS.filter((c) => c.section === 'now').map(slot).join('')}</div>
    </section>
    <section data-section="time" class="mt-s6">
      <div class="flex items-baseline gap-s2"><h3 class="m-0 font-heading text-name font-normal">Over time</h3>
        <span class="text-caveat text-ink-muted" data-time-header></span></div>
      <p class="my-s2 text-answer text-ink" data-since-last-run>Comparing the last two runs…</p>
      <div class="mt-s2 grid gap-s3" ${grid}>${DB_CHARTS.filter((c) => c.section === 'time').map(slot).join('')}</div>
    </section>`;
  const cards = {};
  const chips = {};
  const chipsEl = host.querySelector('[data-chart-index]');
  for (const spec of DB_CHARTS) {
    const card = cardShell(spec);
    host.querySelector(`[data-slot="${spec.kind}"]`).replaceWith(card);
    cards[spec.kind] = card;
    // The per-kind list: every chart this database has, each with the state
    // word the server gave it. A kind with no route says so in its entry.
    const chip = document.createElement('span');
    chip.dataset.chartChip = spec.kind;
    chip.className = 'rounded-sm border border-rule-strong px-2 py-[3px] text-caveat text-ink-muted';
    chip.textContent = `${spec.title} · ${spec.route ? '…' : 'not wired up yet'}`;
    chipsEl.appendChild(chip);
    chips[spec.kind] = chip;
  }
  const setChip = (spec, text) => { chips[spec.kind].textContent = `${spec.title} · ${text}`; };
  const specOf = (k) => DB_CHARTS.find((c) => c.kind === k);

  // Activity per table has no route: present and explained in its own slot.
  const act = cards.table_activity;
  act.querySelector('[data-card-state]').innerHTML =
    '<span data-state="not_wired" class="text-state-gap">○ not wired up yet</span>';
  act.querySelector('[data-card-body]').innerHTML =
    `<div class="mt-s2 text-answer text-ink" data-not-wired>Activity per table needs the
      table-activity series (<span class="font-diagram">db_change_rates</span>), which no
      route serves to this screen yet. It is not a statement about this database.</div>`;
  act.querySelector('[data-card-provenance]').textContent = `${slug} · no run read`;

  const grab = (kind, params) => getDbChart(slug, kind, params)
    .catch((err) => ({ __error: err.message }));
  const [dist, sizes, types, hist, growth, diff] = await Promise.all([
    grab('schema_distribution'), grab('table_sizes', { measure: 'rows' }), grab('column_types'),
    grab('survey_history'), grab('table_growth'),
    getDatabaseDiff(slug).catch((err) => ({ __error: err.message })),
  ]);
  if (stale()) return;

  const settle = async (spec, resp, opts) => {
    const card = cards[spec.kind];
    if (resp && resp.__error) {
      card.dataset.cardState = 'error';
      card.querySelector('[data-card-state]').innerHTML =
        '<span data-state="error" class="text-state-warn">could not be read</span>';
      card.querySelector('[data-card-body]').innerHTML =
        `<div class="mt-s2 text-answer text-state-warn">${esc(spec.title)} could not be read: ${esc(resp.__error)}</div>`;
      card.querySelector('[data-card-provenance]').textContent = `${slug} · no run read`;
      setChip(spec, 'could not be read');
      return;
    }
    await drawCard(card, spec, slug, resp, opts);
    setChip(spec, STATE_WORD[resp.state] || 'state not reported');
  };
  const ok = (r) => r && !r.__error;

  await settle(specOf('schema_distribution'), dist, { extraHtml: ok(dist) ? schemaScopeExtra(dist) : '' });
  const drawSizes = async (resp, measure) => {
    await settle(specOf('table_sizes'), resp, {
      counts: ok(resp) ? resp.provenance || '' : '',
      extraHtml: ok(resp) ? tableSizesExtra(resp, measure) : '',
    });
    cards.table_sizes.querySelector('[data-card-title]').textContent =
      measure === 'size' ? 'Largest tables, by size' : 'Largest tables, by rows';
    const sw = cards.table_sizes.querySelector('[data-measure]');
    if (sw) {
      sw.addEventListener('click', async () => {
        const next = sw.dataset.measure;
        const r = await grab('table_sizes', { measure: next });
        if (!stale()) await drawSizes(r, next);
      });
    }
  };
  await drawSizes(sizes, 'rows');
  await settle(specOf('column_types'), types, { extraHtml: ok(types) ? columnTypesExtra(types) : '' });
  await settle(specOf('survey_history'), hist);
  await settle(specOf('table_growth'), growth);
  setChip(specOf('table_activity'), 'not wired up yet');

  // Section headers come from the responses' own run / scope fields.
  const withRun = [dist, sizes, types].find((r) => ok(r) && r.run);
  const nowHeader = host.querySelector('[data-now-header]');
  if (withRun) {
    const scope = [dist, sizes, types].map((r) => ok(r) && r.scope).find((sc) => sc && sc.partial);
    nowHeader.innerHTML = `from the survey of <span class="tnum" title="${esc(withRun.run.surveyed_at)}">${
      esc(runLabel(withRun.run))}</span> · ${esc(withRun.run.source || 'unknown source')}${
      scope ? ` · ◐ credential scope: ${esc(scope.schema_fraction || scope.fraction || 'partial')} readable` : ''}`;
  } else {
    nowHeader.textContent = 'no survey has run for this database';
  }
  const pts = ok(hist) ? hist.points || [] : [];
  host.querySelector('[data-time-header]').textContent = pts.length
    ? `${pts.length} run${pts.length === 1 ? '' : 's'} since ${runLabel(pts[0].run)}` : '';
  host.querySelector('[data-since-last-run]').innerHTML = diff && diff.__error
    ? `The comparison with the previous run could not be read: ${esc(diff.__error)}`
    : sinceLastRunHtml(diff);
}

export async function loadChartsPane() {
  const el = $('content');
  if (!el) throw new Error('Understanding pane host missing: #content');
  const slug = state.selectedSlug;

  if (!slug) {
    el.innerHTML = paneMessage('Select a resource',
      'Pick a repository from the sidebar to see its charts.');
    bindSubTabs();
    return;
  }


  // NO sub-tab row here. Understanding has no Search/Survey/Dashboard/
  // Questions/Disposition — rendering the strip with "Questions" underlined
  // while a chart is on screen says this pane is something it is not.
  const entityType = apiEntityType(state.resourceType);
  el.innerHTML = `
    <div class="mb-s4 font-heading text-subtab text-ink">
      <span class="border-b border-accent pb-[2px]">Charts</span>
      <span class="ml-s3 text-caps uppercase tracking-caps text-ink-muted">Understanding has one pane</span>
    </div>
    <div id="resource-header">${resourceHeaderHtml(slug)}</div>
    <div class="my-s3 h-px bg-rule"></div>${entityType === 'repo'
    ? `<div id="chart-index" class="flex flex-wrap gap-s2"></div>
    <div id="chart-body" class="mt-s4"></div>`
    : '<div id="understanding-host"></div>'}`;
  bindResourceHeader();

  // A database has its own six charts (module section above); a file share
  // has none yet and says so. Neither goes through the repo probe.
  if (entityType !== 'repo') {
    if (entityType === 'database') {
      try {
        await renderDatabaseUnderstanding(slug);
      } catch (err) {
        // A renderer that cannot draw says so in the pane, never nothing.
        const host = $('understanding-host') || el;
        host.insertAdjacentHTML('beforeend', `<p class="max-w-[70ch] text-answer text-state-warn"
          data-understanding-error>Understanding could not be drawn: ${esc(err.message)}</p>`);
      }
    } else {
      $('understanding-host').innerHTML = `<p class="max-w-[70ch] text-answer text-ink"
        data-understanding-not-charted>${esc(FILE_SHARE_SENTENCE)}</p>`;
    }
    return;
  }

  const index = $('chart-index');
  index.innerHTML = REPO_CHARTS.map(([kind, label]) =>
    `<button data-chart="${kind}" disabled
      class="cursor-wait rounded-sm border border-rule-strong bg-transparent px-2 py-[3px]
             text-caveat text-ink-muted">${esc(label)}…</button>`).join('');

  // Probe each kind so the index never offers a chart with nothing in it.
  const results = await Promise.all(REPO_CHARTS.map(async ([kind, label]) => {
    try {
      const fig = asFigure(await getChart(slug, kind));
      // POINTS, NOT TRACES. `fig.data.length` counts series, so a trace
      // holding a single observation counted as a usable chart and drew one
      // dot — the flat-line lie in chart form, and the same mistake as a
      // sparkline of one point. Some repos here are at 2.
      const traces = Array.isArray(fig?.data) ? fig.data : [];
      const points = traces.reduce((n, t) => n + (
        (t.x || t.labels || t.r || t.values || []).length), 0);
      const dates = allPointDates(traces);
      return {
        kind, label, fig, traces: traces.length, points,
        first: dates[0] || '', last: dates[dates.length - 1] || '',
        // A date x-axis means the spacing can be honest; a categorical one
        // (languages, file types, committers) has no time to be true to.
        timeAxis: dates.length > 1 && dates.length === points,
        error: null,
      };
    } catch (err) {
      return { kind, label, fig: null, traces: 0, points: 0, last: '', error: err.message };
    }
  }));
  if (slug !== state.selectedSlug) return;
  state.charts = results;

  index.innerHTML = results.map((r) => {
    if (r.error) {
      return `<span title="${esc(r.error)}"
        class="rounded-sm border border-dashed border-state-warn px-2 py-[3px] text-caveat text-state-warn"
        >${esc(r.label)} · unavailable</span>`;
    }
    if (!r.points) {
      return `<span title="The series exists and has nothing in it yet"
        class="rounded-sm border border-dashed border-rule-strong px-2 py-[3px] text-caveat text-ink-muted"
        >${esc(r.label)} · nothing recorded yet</span>`;
    }
    // ONE OBSERVATION IS NOT A TREND. Offered, because the value is real and
    // worth seeing — labelled, because a chart of it would imply a shape it
    // does not have.
    const one = r.points === 1;
    // SELECTION IS THE ONE THING THAT MUST NEVER BE INFERRED, and it gets the
    // treatment the stage tabs already use — accent ink plus an accent
    // underline — so the app speaks one visual language rather than two.
    // Without it you cannot tell WHICH chart you are looking at, which is what
    // made the unlabelled axes hard to notice underneath.
    return `<button data-chart="${r.kind}" aria-pressed="false"
      title="${r.points} observation(s)${r.last ? ` · latest ${r.last}` : ''}"
      class="wl-chartchip cursor-pointer border-0 bg-transparent px-2 py-[3px]
             text-caveat text-ink-muted hover:text-ink">${esc(r.label)}${
      one ? ' · first measurement'
          : `<span class="tnum text-ink-muted"> · ${r.points}</span>`}${
      r.last && chartIsStale(r.last)
        ? '<span class="wl-age-text"> </span>' : ''}</button>`;
  }).join('');

  const select = (kind) => {
    index.querySelectorAll('[data-chart]').forEach((o) =>
      o.setAttribute('aria-pressed', o.dataset.chart === kind ? 'true' : 'false'));
    drawChart(results.find((r) => r.kind === kind));
  };
  index.querySelectorAll('[data-chart]').forEach((b) =>
    b.addEventListener('click', () => select(b.dataset.chart)));

  const first = results.find((r) => r.points);
  if (first) {
    select(first.kind);
  } else {
    $('chart-body').innerHTML = `<div class="text-answer text-ink">
      Nothing has been recorded for any of this resource's charts yet. That is
      a statement about the history collected so far, not about the resource.</div>`;
  }
}
