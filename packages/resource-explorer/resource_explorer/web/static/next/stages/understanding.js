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
import { REPO_CHARTS, getChart } from '/static/re-api.js';
import {
  state, esc, $, paneMessage, bindSubTabs, resourceHeaderHtml, bindResourceHeader,
  asFigure, allPointDates, chartIsStale, drawChart,
} from '/static/next/app.js';

export async function loadChartsPane() {
  const el = $('content');
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
  el.innerHTML = `
    <div class="mb-s4 font-heading text-subtab text-ink">
      <span class="border-b border-accent pb-[2px]">Charts</span>
      <span class="ml-s3 text-caps uppercase tracking-caps text-ink-muted">Understanding has one pane</span>
    </div>
    <div id="resource-header">${resourceHeaderHtml(slug)}</div>
    <div class="my-s3 h-px bg-rule"></div>
    <div id="chart-index" class="flex flex-wrap gap-s2"></div>
    <div id="chart-body" class="mt-s4"></div>`;
  bindResourceHeader();

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
