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
  asFigure, allPointDates, chartIsStale, drawChart, apiEntityType,
} from '/static/next/app.js';

/* ── Understanding for a database/filesystem (Tier 1 audit, 2026-09-23) ───
 *
 * Understanding is a generic nav item, reachable for any resource type, but
 * every one of `REPO_CHARTS`' 8 kinds resolves via `/api/stats/{slug}/
 * charts/{kind}`, which 404s through `ProjectRegistry.exists` (the repo-only
 * `projects` table) for a database/filesystem slug — so every tile rendered
 * "unavailable" with no way to tell "this chart genuinely does not exist
 * for this resource type" from "nobody has wired it up yet".
 *
 * Chose (b) over (a): `web/routes/stats.py` DOES have real database-side
 * routes (`/databases/{slug}/schema_distribution|table_sizes|column_types|
 * survey_history`), but they return plain arrays, not the Plotly figure
 * JSON (`fig.to_json()`) every repo chart route returns and `asFigure`/
 * `drawChart` expect — wiring them for real needs either a backend change
 * (build the Plotly figure server-side, as the repo routes already do) or a
 * client-side chart-building adapter, either of which is a real scoping
 * pass of its own, not a routing fix like fixes #1-#3/#6 in this same pass.
 * Filesystem has no chart-shaped stats routes at all yet.
 *
 * So: no chart is actually drawn for a database/filesystem here (unchanged
 * behaviour), but each tile now says WHICH kind of nothing it is, instead of
 * a uniform, misleading "unavailable".
 */
//: repo chart kind -> real backend route that exists for it today, keyed by
//: entity type — used only to pick the honest gap sentence below. A kind
//: absent from an entity type's map here has no real equivalent AT ALL for
//: that resource type (a permanent fact, not a gap).
const CHART_GAP_ROUTE = {
  database: {
    // schema/table/column charts obviously map to something real; things
    // like "commits over time" have no database equivalent at all.
    survey_history: '/api/stats/databases/{slug}/survey_history',
  },
};
//: Kinds with a genuinely no-equivalent-exists reason worth naming, rather
//: than the generic "no database/filesystem equivalent" fallback below.
const CHART_NO_EQUIVALENT_REASON = {
  stars: 'GitHub stars have no database/filesystem analogue.',
  commits: 'Commit history has no database/filesystem analogue.',
  weekly_commits: 'Commit history has no database/filesystem analogue.',
  top_committers: 'Git authorship has no database/filesystem analogue.',
};

/** Non-repo Understanding: every repo chart kind, each labelled as either a
 *  genuine non-equivalence (permanent) or a real backend gap (not wired up
 *  yet) — never the generic "unavailable" a probe failure would produce. */
function nonRepoChartIndexHtml(entityType) {
  return REPO_CHARTS.map(([kind, label]) => {
    const gapRoute = CHART_GAP_ROUTE[entityType]?.[kind];
    if (gapRoute) {
      return `<span title="A ${entityType} equivalent exists server-side (${gapRoute}) but Understanding does not call it yet — a real gap, not a data problem."
        class="rounded-sm border border-dashed border-rule-strong px-2 py-[3px] text-caveat text-ink-muted"
        >${esc(label)} · not wired up yet</span>`;
    }
    const reason = CHART_NO_EQUIVALENT_REASON[kind]
      || `This chart has no ${entityType} equivalent.`;
    return `<span title="${esc(reason)}"
      class="rounded-sm border border-dashed border-rule-strong px-2 py-[3px] text-caveat text-ink-muted"
      >${esc(label)} · does not apply to this resource type</span>`;
  }).join('');
}

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
  const entityType = apiEntityType(state.resourceType);

  // A database/filesystem's charts are never actually drawable today — see
  // this module's top-of-file note — so skip the probe entirely and say,
  // per kind, which of the two honest reasons applies, rather than firing
  // 8 requests that all 404 the same uninformative way.
  if (entityType !== 'repo') {
    index.innerHTML = nonRepoChartIndexHtml(entityType);
    $('chart-body').innerHTML = `<div class="text-answer text-ink">
      Understanding has no working charts for a ${esc(entityType)} yet — see each
      tile above for whether that is permanent or a wiring gap.</div>`;
    return;
  }

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
