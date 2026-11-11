/** EA Dashboards, B7a: every tile kind draws, a lower bound never shows as a bare number, tiles run by
 *  themselves (at most three at a time), and nothing from Egeria runs as script.
 *
 *  Runs the REAL vendored marked + DOMPurify, the REAL render.js and the REAL static/dashboards_view.js in
 *  a jsdom window. The tiles drawn are the server's own: tests/unit/fixtures/dashboards/tiles_for_js.json
 *  is made by advisor.egeria_dashboards._tile() from real-shape results (live laz captures and pyegeria
 *  6.2.34's own output), and a Python test fails if it drifts from what the server makes. Only fetch,
 *  Auth and vegaEmbed are stubbed.
 *
 *  Run:  node --test advisor/web/static/test/dashboards_view.test.mjs   (jsdom: see render.test.mjs)
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.resolve(HERE, '..');
const REPO = path.resolve(STATIC, '../../../../..');
const TILES = JSON.parse(fs.readFileSync(path.resolve(STATIC, '../../../tests/unit/fixtures/dashboards/tiles_for_js.json'), 'utf8'));

function findJsdom() {
  const dirs = [process.env.EA_JSDOM_DIR,
    path.join(REPO, 'packages/resource-explorer/frontend-build/node_modules'),
    path.join(REPO, '../trellis/packages/resource-explorer/frontend-build/node_modules')].filter(Boolean);
  for (const d of dirs) {
    if (fs.existsSync(path.join(d, 'jsdom', 'package.json'))) return createRequire(path.join(d, 'x.js'))('jsdom');
  }
  return null;
}
const jsdom = findJsdom();
const REQUIRED = process.env.EA_RENDER_HARNESS_REQUIRED === '1';
const SKIP = jsdom ? false : 'jsdom not found (set EA_JSDOM_DIR to a node_modules directory holding jsdom)';

test('the harness can run (jsdom found)', { skip: !REQUIRED && SKIP }, () => {
  assert.ok(jsdom, `EA_RENDER_HARNESS_REQUIRED=1 but ${SKIP}`);
});

const read = (rel) => fs.readFileSync(path.join(STATIC, rel), 'utf8');
const GE = '≥';

function makeWindow() {
  const dom = new jsdom.JSDOM('<!doctype html><html><body><div id="messages"></div>' +
    '<div id="dashboard-status"></div><div id="dashboard-list"></div></body></html>', { runScripts: 'outside-only' });
  const w = dom.window;
  w.eval(read('vendor/marked.min.js'));
  w.eval(read('vendor/purify.min.js'));
  w.eval(read('render.js'));
  w.Auth = { getHeaders: () => ({ Authorization: 'Bearer t' }) };
  w.embedded = [];
  w.vegaEmbed = (el, spec, opts) => { w.embedded.push({ el, spec, opts }); return Promise.resolve({}); };
  w.eval(read('dashboards_view.js'));
  return w;
}

function draw(w, t, p = {}) {
  const out = w.document.createElement('div');
  w.document.body.appendChild(out);
  w.EADashboards.renderTileBody(out, t, p);
  return out;
}

/** All text a viewer can read in `node`, SVG titles included. */
const allText = (node) => node.textContent;

test('kpi: the number, as the server gave it', { skip: SKIP }, () => {
  const out = draw(makeWindow(), TILES.kpi_count);
  assert.equal(out.querySelector('.dash-kpi').textContent, '68739');
});

test('kpis: an unmeasured count reads "not measured", with why', { skip: SKIP }, () => {
  const out = draw(makeWindow(), TILES.kpis_unmeasured);
  const cells = [...out.querySelectorAll('.dash-kpis > div')].map(c => c.textContent);
  assert.deepEqual(cells, ['272contextualisedCount', 'not measuredassetTotal', 'not measuredcontextualisedPct']);
  assert.match(out.querySelector('.dash-unmeasured').textContent, /at least 500/);
});

test('chart: pyegeria\'s Vega-Lite spec is embedded as given; a spec that loads a URL is refused', { skip: SKIP }, () => {
  const w = makeWindow();
  draw(w, TILES.chart_pie);
  assert.equal(w.embedded.length, 1);
  assert.deepEqual(w.embedded[0].spec, TILES.chart_pie.spec);
  assert.equal(w.embedded[0].opts.actions, false);
  const hostile = { kind: 'chart', spec: { ...TILES.chart_pie.spec, data: { url: 'https://evil.example/x.json' } } };
  const out = draw(w, hostile);
  assert.equal(w.embedded.length, 1, 'vegaEmbed must not be called');
  assert.match(out.textContent, /asks to load data from a URL/);
});

test('trend: exact points, headline and sparkline', { skip: SKIP }, () => {
  const out = draw(makeWindow(), TILES.trend_exact);
  assert.equal(out.querySelector('.dash-kpi').textContent, '1065');
  assert.equal(out.querySelectorAll('circle.dash-point').length, 3);
  assert.equal(out.querySelectorAll('circle.dash-bound').length, 0);
  assert.ok(out.querySelector('svg.dash-spark path'));
});

test('trend: a capped point is never rendered without its marker (W2)', { skip: SKIP }, () => {
  const out = draw(makeWindow(), TILES.trend_capped);
  const bounds = out.querySelectorAll('circle.dash-bound');
  assert.equal(bounds.length, 2, 'each lower bound is drawn as a bound');
  for (const b of bounds) {
    assert.equal(b.getAttribute('fill'), 'none');
    assert.match(b.querySelector('title').textContent, new RegExp(`: ${GE}500$`));
  }
  // Every place a point's NUMBER is shown: the headline, the points list, the marker titles. (The
  // not-measured note is pyegeria's sentence, "...so there are at least 500": words, not a value.)
  const shown = [out.querySelector('.dash-kpi'), out.querySelector('.dash-trend-points'),
    ...out.querySelectorAll('svg title')].map(allText).join(' | ');
  assert.equal((shown.match(new RegExp(`${GE}500`, 'g')) || []).length, 4, shown);   // 2 in the list, 2 titles
  assert.doesNotMatch(shown.replace(new RegExp(`${GE}500`, 'g'), ''), /(^|\D)500(\D|$)/, `a bare 500: ${shown}`);
  assert.match(allText(out), /2 of 3 points are lower bounds/);
  assert.match(out.querySelector('.dash-unmeasured').textContent, /at least 500/);
});

test('trend: an unmeasured point is a gap that says "not measured"', { skip: SKIP }, () => {
  const out = draw(makeWindow(), TILES.trend_not_measured);
  assert.match(out.querySelector('.dash-trend-points').textContent, /not measured · .* not measured · .* 1065/);
  assert.equal(out.querySelectorAll('circle').length, 0, 'one measured point: no line to draw');
});

test('absent and empty: the sentence is the answer', { skip: SKIP }, () => {
  const w = makeWindow();
  assert.match(draw(w, TILES.absent_trend).querySelector('.dash-absent').textContent, /not measured/);
  assert.equal(draw(w, TILES.empty).querySelector('.dash-empty').textContent, "'Collections' ran and found nothing.");
});

test('saved query (Route B): cached with its as-of time, live, and a lower bound', { skip: SKIP }, () => {
  const w = makeWindow();
  const cached = draw(w, TILES.saved_cached);
  assert.equal(cached.querySelector('.dash-kpi').textContent, '37');
  assert.equal(cached.querySelector('.dash-asof').textContent, 'cached · as of 2026-11-10T18:02:11+00:00');
  assert.match(draw(w, TILES.saved_live).querySelector('.dash-asof').textContent, /^live · as of /);
  const capped = draw(w, TILES.saved_capped);
  assert.equal(capped.querySelector('.dash-kpi').textContent, `${GE}30`);
  assert.match(capped.textContent, /a lower bound/);
});

test('markdown: tables and mermaid from Egeria draw, and hostile text is inert', { skip: SKIP }, () => {
  const w = makeWindow();
  assert.ok(draw(w, TILES.markdown_records).querySelector('table'));
  assert.ok(draw(w, TILES.markdown_mermaid).querySelector('div.mermaid'));
  const out = draw(w, { kind: 'markdown', markdown: '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>[x](javascript:window.__pwned=3)' });
  assert.equal(out.querySelectorAll('script, img[onerror]').length, 0);
  assert.equal(w.__pwned, undefined);
});

// ── a sheet: tiles run by themselves ─────────────────────────────────────────

function sheetOf(n) {
  const placements = [];
  for (let i = 1; i <= n; i++) {
    placements.push({ position: i, kind: 'report', title: `T${i}`, span: '1', emphasis: 'kpi', spec: 'S', source: 'builtin',
      runnable: true, params: { searchString: '*' }, analytic: false, report: { output_format: 'DICT' } });
  }
  placements.push({ position: n + 1, kind: 'restricted', title: 'Hidden', reason: 'not visible to you' });
  placements.push({ position: n + 2, kind: 'text', content: 'hello' });
  placements.push({ position: n + 3, kind: 'report', title: 'No', runnable: false, refusal: 'cannot run', spec: 'X' });
  return { name: 'sheet <x>', heading: 'Sheet', viewer: 'peterprofile', breaks: [], placements };
}

test('a sheet runs its runnable tiles by itself, at most three at a time, each once', { skip: SKIP }, async () => {
  const w = makeWindow();
  let inFlight = 0, most = 0;
  const calls = [];
  w.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    inFlight++; most = Math.max(most, inFlight);
    await new Promise(r => setTimeout(r, 5));
    inFlight--;
    return { ok: true, status: 200, json: async () => ({ state: 'ok', tile: TILES.kpi_count, cache: { state: 'hit', age_s: 42 } }) };
  };
  const wrap = w.EADashboards.renderDashboard(sheetOf(7));
  await wrap._ready;
  assert.equal(calls.length, 7);
  assert.ok(most <= 3 && most >= 2, `in flight at once: ${most}`);
  assert.deepEqual(calls.map(c => c.url).sort(), [1, 2, 3, 4, 5, 6, 7].map(i => `/api/dashboards/sheet%20%3Cx%3E/placements/${i}/run`).sort());
  assert.ok(calls.every(c => c.body.refresh === false && c.body.params === null));
  const tiles = wrap.querySelectorAll('.dash-tile');
  assert.equal(tiles[0].querySelector('.dash-kpi').textContent, '68739');
  assert.equal(tiles[0].querySelector('.dash-age').textContent, 'answer 42s old');
  assert.match(tiles[7].textContent, /restricted: not visible to you/);
  assert.match(tiles[9].textContent, /cannot run/);
  assert.equal(tiles[9].querySelector('.dash-refresh'), null);
});

test('↻ runs one tile now; a stale answer says it is refreshing; a refusal is shown in words', { skip: SKIP }, async () => {
  const w = makeWindow();
  const bodies = [];
  let answer = { state: 'ok', tile: TILES.kpi_count, cache: { state: 'stale', age_s: 125 } };
  w.fetch = async (url, init) => { bodies.push(JSON.parse(init.body)); return { ok: true, status: 200, json: async () => answer }; };
  const wrap = w.EADashboards.renderDashboard(sheetOf(1));
  await wrap._ready;
  const tile = wrap.querySelector('.dash-tile');
  assert.equal(tile.querySelector('.dash-age').textContent, 'answer 2 min old · refreshing');
  answer = { state: 'refused', message: "'collectionGuid' is not a parameter of this placement" };
  await tile._run({ refresh: true });
  assert.equal(bodies[1].refresh, true);
  assert.match(tile.querySelector('.dash-out').textContent, /not a parameter of this placement/);
});

test('⚙ sends only what the viewer changed, for this view', { skip: SKIP }, async () => {
  const w = makeWindow();
  const bodies = [];
  w.fetch = async (url, init) => { bodies.push(JSON.parse(init.body)); return { ok: true, status: 200, json: async () => ({ state: 'ok', tile: TILES.kpi_count, cache: {} }) }; };
  const wrap = w.EADashboards.renderDashboard(sheetOf(1));
  await wrap._ready;
  const tile = wrap.querySelector('.dash-tile');
  tile.querySelector('.dash-adjust').click();
  const inp = tile.querySelector('.dash-adj-param[data-key="searchString"]');
  assert.equal(inp.value, '*');
  inp.value = 'Sales';
  tile.querySelector('.dash-adjust-panel button').click();
  await new Promise(r => setTimeout(r, 10));
  assert.deepEqual(bodies[1].params, { searchString: 'Sales' });
  assert.equal(bodies[1].output_format, null);
});

test('↗ drill-down runs the detail spec and shows its answer under the tile', { skip: SKIP }, async () => {
  const w = makeWindow();
  const urls = [];
  w.fetch = async (url) => {
    urls.push(url);
    const tile = url.endsWith('/detail') ? TILES.markdown_records : TILES.kpi_count;
    return { ok: true, status: 200, json: async () => ({ state: 'ok', tile, cache: {} }) };
  };
  const sheet = sheetOf(1);
  sheet.placements[0].detail_spec = 'Collections';
  const wrap = w.EADashboards.renderDashboard(sheet);
  await wrap._ready;
  const tile = wrap.querySelector('.dash-tile');
  tile.querySelector('.dash-drill').click();
  await new Promise(r => setTimeout(r, 10));
  assert.ok(urls.some(u => u.endsWith('/placements/1/detail')));
  assert.ok(tile.querySelector('.dash-detail table'));
  assert.match(tile.querySelector('.dash-detail').textContent, /Drill-down: Collections/);
});

test('a nested sheet opens in place; no inline handlers anywhere in the module', { skip: SKIP }, async () => {
  const w = makeWindow();
  const opened = [];
  w.fetch = async (url) => { opened.push(url); return { ok: true, status: 200, json: async () => ({ state: 'ok', sheet: { ...sheetOf(0), name: 'inner' } }) }; };
  const sheet = { name: 'outer', heading: 'Outer', viewer: 'v', breaks: [], placements: [
    { position: 1, kind: 'sheet', title: 'Inner', sheet_ref: 'inner', note: 'nested sheet: Inner (1 placements)' }] };
  const wrap = w.EADashboards.renderDashboard(sheet);
  wrap.querySelector('.dash-nested').click();
  await new Promise(r => setTimeout(r, 10));
  assert.deepEqual(opened, ['/api/dashboards/inner']);
  assert.doesNotMatch(read('dashboards_view.js'), /\son[a-z]+\s*=\s*["']/);
});

// ── the list: a configured folder's own reason (Architect F3) ─────────────────

const LISTING = JSON.parse(fs.readFileSync(path.resolve(STATIC,
  '../../../tests/unit/fixtures/dashboards/listing_folder_not_found_2026-11-11.json'), 'utf8'));

test('a folder that is not found says its reason, not "no sheets"', { skip: SKIP }, async () => {
  const w = makeWindow();
  const message = `No Dashboard Sheets to show for erinoverview: ${LISTING.notes[0]}.`;
  w.fetch = async () => ({ ok: true, status: 200, json: async () => ({ state: 'no_sheets', sheets: [], viewer: 'erinoverview',
    message, notes: LISTING.notes, folders: LISTING.folders }) });
  await w.EADashboards.loadDashboards(false);
  const status = w.document.getElementById('dashboard-status');
  assert.equal(status.textContent, message);
  assert.match(status.textContent, /DashboardFolder::Consumer::EgeriaAdvisor: not found, or not visible to erinoverview/);
});

test('with sheets, the folder notes show under the count', { skip: SKIP }, async () => {
  const w = makeWindow();
  w.fetch = async () => ({ ok: true, status: 200, json: async () => ({ state: 'ok', viewer: 'erinoverview',
    sheets: [{ name: 'a', heading: 'A', description: '', placement_count: 1, breaks: [] }],
    message: LISTING.notes[0], notes: LISTING.notes, folders: LISTING.folders }) });
  await w.EADashboards.loadDashboards(false);
  const status = w.document.getElementById('dashboard-status');
  assert.match(status.textContent, /^1 sheet visible to erinoverview/);
  assert.equal(status.querySelector('.dash-list-notes').textContent, LISTING.notes[0]);
});

test('with sheets and no notes, only the count shows', { skip: SKIP }, async () => {
  const w = makeWindow();
  w.fetch = async () => ({ ok: true, status: 200, json: async () => ({ state: 'ok', viewer: 'erinoverview',
    sheets: [{ name: 'a', heading: 'A', description: '', placement_count: 1, breaks: [] }], message: null, notes: [], folders: [] }) });
  await w.EADashboards.loadDashboards(false);
  const status = w.document.getElementById('dashboard-status');
  assert.equal(status.textContent, '1 sheet visible to erinoverview');
  assert.equal(status.querySelector('.dash-list-notes'), null);
});
