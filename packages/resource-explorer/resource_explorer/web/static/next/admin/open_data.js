/* Open data (OD1): Data portals, Portal directories, and the imported datasets' own page.
 *
 * Reached from Admin → Open data. Nothing here surveys, profiles or publishes; a dataset's page offers no Run.
 *
 *  Data portals       the registered portals; Register (name, API kind, base URL, optional key); a portal opens
 *                     into its discovery-source pane: terms and filters, the PRICE LINE before the press, the
 *                     candidate table, tick rows, Import into a work list (cap shown, Admin-changeable).
 *  Portal directories a directory's Run lists portals as candidate rows; "already registered", "adapter: ckan"
 *                     or "no adapter for <kind> yet · registered for later" on each; Import registers them.
 *  Open data          the datasets held; a dataset opens into its page: the publisher's record verbatim, the
 *                     normalised fields "stated by <portal> · retrieved <time>", and the absence word for every
 *                     question a survey will answer.
 *
 * Absent fields read "not reported by this source" (the server sends the typed `not_reported`). Cues, not
 * sentences; every table is resizable (colresize.js).
 */
import {
  listOpenDataPortals, registerOpenDataPortal, checkOpenDataPortal, openDataPrice, searchOpenData, importOpenData,
  openDataLensTerms, listPortalDirectories, registerPortalDirectory, runPortalDirectory, importDirectoryPortals,
  listOpenData, getOpenData,
} from '/static/re-api.js';
import { esc } from '/static/next/app.js';
import { ago } from '/static/next/format.js';
import { watchTables } from '/static/next/colresize.js';

export const NOT_REPORTED = 'not_reported';
export const NOT_REPORTED_WORDS = 'not reported by this source';
export const NO_SURVEY_WORDS = 'no survey yet · scout arrives with OD2';
const SURVEY_QUESTIONS = ['Licence and terms (O1)', 'Description (O2)', 'Update cadence (O3)', 'Coverage (O4)',
  'Formats and access (O5)', 'Structure (O6)', 'Size and cost (O7)', 'Quality (O8)', 'Personal data (O9)',
  'Provenance (O10)', 'Overlap with data held (O11)', 'Citations (O12)', 'Change since last look (O13)'];

/** A value as the screen shows it: the typed absence becomes the words; lists join; flags become cues. */
export function show(v) {
  if (v === NOT_REPORTED || v === undefined || v === null) return `<span class="text-ink-muted">${NOT_REPORTED_WORDS}</span>`;
  if (v === true) return '✓';
  if (v === false) return '✗';
  if (Array.isArray(v)) return esc(v.join(', '));
  return esc(String(v));
}
const showDir = (v) => (v === NOT_REPORTED ? '<span class="text-ink-muted">not reported by this directory</span>' : show(v));

export function flagsCue(l) {
  if (!l) return show(NOT_REPORTED);
  const f = (name, v) => `${name} ${v === NOT_REPORTED ? '?' : v ? '✓' : '✗'}`;
  return esc(`${f('attr', l.attribution)} · ${f('share-alike', l.share_alike)} · ${f('commercial', l.commercial)}`);
}

export function bytes(n) {
  if (n === NOT_REPORTED || n === null || n === undefined || n === '') return show(NOT_REPORTED);
  const x = Number(n);
  if (!Number.isFinite(x)) return esc(String(n));
  if (x >= 1e6) return esc(`${(x / 1e6).toFixed(1)} MB`);
  if (x >= 1e3) return esc(`${(x / 1e3).toFixed(0)} kB`);
  return esc(`${x} B`);
}

const BTN = 'cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-caveat text-ink hover:border-accent';
const INPUT = 'rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-caveat text-ink';
const TH = 'pb-s2 pr-s3 font-normal';
const TD = 'py-s2 pr-s3 text-caveat align-top';
const errText = (e) => esc((e && (e.detail || e.message)) || String(e));
const q = (host, sel) => host.querySelector(sel);

// ── Data portals ──────────────────────────────────────────────────────────────

export async function renderDataPortals(host) {
  const portals = await listOpenDataPortals();
  host.innerHTML = `
    <div class="mb-s2 flex items-center justify-between">
      <h3 class="m-0 font-heading text-name font-normal text-ink">🌐 Data portals</h3>
      <button type="button" data-od-register-toggle class="${BTN}">Register</button>
    </div>
    <form data-od-register class="mb-s3 hidden flex-wrap items-end gap-[6px]">
      <label class="text-caveat text-ink-muted">Name <input name="display_name" required class="${INPUT}"></label>
      <label class="text-caveat text-ink-muted">API <select name="api_kind" class="${INPUT}"><option>CKAN</option></select></label>
      <label class="text-caveat text-ink-muted">Base URL <input name="base_url" required placeholder="https://demo.ckan.org" class="${INPUT} w-[260px]"></label>
      <label class="text-caveat text-ink-muted">API key <input name="api_key" type="password" autocomplete="off" class="${INPUT}"></label>
      <button type="button" data-od-check class="${BTN}">Check</button>
      <button type="submit" class="${BTN}">Register</button>
      <span data-od-register-state class="text-provenance text-ink-muted"></span>
    </form>
    ${portals.length ? `<table class="w-full text-left" data-rc-id="od-portals">
      <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
        <th class="${TH}">Portal</th><th class="${TH}">API</th><th class="${TH}">URL</th><th class="${TH}">Origin</th>
        <th class="${TH}">Cost</th><th class="${TH}">Registered</th><th class="${TH}"></th></tr></thead>
      <tbody>${portals.map((p) => `<tr class="border-b border-rule" data-od-portal="${esc(p.slug)}">
        <td class="${TD}">${esc(p.display_name)}</td>
        <td class="${TD}">${esc(p.api_kind)}${p.adapter_available ? '' : ' <span class="text-state-warn">· no adapter yet</span>'}</td>
        <td class="${TD} font-mono text-provenance">${esc(p.base_url)}</td>
        <td class="${TD} text-ink-muted">${esc(p.origin)}</td>
        <td class="${TD} tnum text-ink-muted">${p.cost && p.cost.calls_per_page ? `${p.cost.calls_per_page} call/page · ${p.cost.page_size} rows` : '–'}${p.has_key ? ' · key held' : ''}</td>
        <td class="${TD} text-ink-muted">${esc(ago(p.registered_at))} · ${esc(p.registered_by || 'not recorded')}</td>
        <td class="${TD}">${p.adapter_available ? `<button type="button" data-od-open="${esc(p.slug)}" class="${BTN}">Search</button>` : '<span class="text-ink-muted">registered for later</span>'}</td>
      </tr>`).join('')}</tbody></table>` : '<p data-od-empty class="text-answer text-ink">No portals registered yet.</p>'}
    <div data-od-pane class="mt-s4"></div>`;
  watchTables(host);
  const form = q(host, '[data-od-register]');
  q(host, '[data-od-register-toggle]').addEventListener('click', () => form.classList.toggle('hidden'));
  const body = () => Object.fromEntries(new FormData(form).entries());
  const state = q(host, '[data-od-register-state]');
  q(host, '[data-od-check]').addEventListener('click', async () => {
    state.textContent = 'checking…';
    try { const r = await checkOpenDataPortal(body()); state.textContent = r.words; } catch (e) { state.innerHTML = errText(e); }
  });
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { await registerOpenDataPortal(body()); await renderDataPortals(host); } catch (e) { state.innerHTML = errText(e); }
  });
  host.querySelectorAll('[data-od-open]').forEach((b) => b.addEventListener('click', () => openPortalPane(host, b.dataset.odOpen)));
}

/** The discovery-source pane for one portal: terms, filters, the price line, candidates, preview, Import. */
export async function openPortalPane(host, slug, { lens = null, investigation = '', requestName = '' } = {}) {
  const pane = q(host, '[data-od-pane]');
  const suggested = lens || investigation ? await openDataLensTerms(lens || {}, investigation).catch(() => null) : null;
  pane.innerHTML = `
    <h4 class="m-0 mb-s2 font-heading text-name font-normal text-ink">Search ${esc(slug)}</h4>
    <form data-od-search class="mb-s2 flex flex-wrap items-end gap-[6px]">
      <label class="text-caveat text-ink-muted">Terms <input name="terms" value="${esc(suggested ? suggested.terms : '')}" class="${INPUT} w-[240px]"></label>
      <label class="text-caveat text-ink-muted">Format <input name="format" placeholder="CSV" class="${INPUT} w-[80px]"></label>
      <label class="text-caveat text-ink-muted">Modified after <input name="modified_after" type="date" value="${esc((suggested && suggested.filters.modified_after) || '')}" class="${INPUT}"></label>
      <label class="text-caveat text-ink-muted">Licence needs
        <select name="need_commercial" class="${INPUT}"><option value="">commercial: any</option><option value="1">commercial use needed</option></select>
        <select name="need_share_alike" class="${INPUT}"><option value="">share-alike: any</option><option value="0">no share-alike</option></select></label>
      <label class="text-caveat text-ink-muted">Pages <input name="pages" type="number" min="1" max="20" value="2" class="${INPUT} w-[56px]"></label>
      <button type="submit" class="${BTN}">Run</button>
    </form>
    <p data-od-price class="mb-s2 text-provenance text-ink-muted tnum"></p>
    ${suggested && suggested.source ? `<p class="mb-s2 text-provenance text-ink-muted">terms from the ${esc(suggested.source)}; edit them</p>` : ''}
    <div data-od-results></div>`;
  const form = q(pane, '[data-od-search]');
  const price = q(pane, '[data-od-price]');
  const refreshPrice = async () => {
    try { const p = await openDataPrice(slug, Number(form.pages.value) || 1); price.textContent = `${p.line} · up to ${p.rows_at_most} rows`; }
    catch (e) { price.innerHTML = errText(e); }
  };
  form.pages.addEventListener('change', refreshPrice);
  refreshPrice();
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(form).entries());
    const filters = {};
    if (f.format) filters.format = f.format;
    if (f.modified_after) filters.modified_after = f.modified_after;
    const licence = {};
    if (f.need_commercial) licence.commercial = true;
    if (f.need_share_alike === '0') licence.share_alike = false;
    if (Object.keys(licence).length) filters.licence = licence;
    const out = q(pane, '[data-od-results]');
    out.innerHTML = '<p class="text-ink-muted">Searching…</p>';
    try {
      const res = await searchOpenData(slug, { terms: f.terms, filters, pages: Number(f.pages) || 1 });
      drawCandidates(pane, out, slug, res, f.terms, requestName, investigation);
    } catch (e) { out.innerHTML = `<p class="text-state-warn">${errText(e)}</p>`; }
  });
}

function drawCandidates(pane, out, slug, res, terms, requestName, investigation) {
  const rows = res.rows;
  out.innerHTML = `
    <p class="mb-s2 text-provenance text-ink-muted tnum">${rows.length} row${rows.length === 1 ? '' : 's'} of ${show(res.total)} · ${res.calls_made} call${res.calls_made === 1 ? '' : 's'} made
      ${res.licence_dropped ? ` · ${res.licence_dropped} dropped on licence` : ''}</p>
    ${rows.length ? `<table class="w-full text-left" data-rc-id="od-candidates">
      <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
        <th class="${TH}"></th><th class="${TH}">Title</th><th class="${TH}">Publisher</th><th class="${TH}">Licence</th>
        <th class="${TH}">Flags</th><th class="${TH}">Modified</th><th class="${TH}">Formats</th><th class="${TH}">Size</th>
        <th class="${TH}">Identifier</th><th class="${TH}">Portal</th></tr></thead>
      <tbody>${rows.map((r, i) => `<tr class="border-b border-rule" data-od-row="${i}">
        <td class="${TD}"><input type="checkbox" data-od-pick="${i}"></td>
        <td class="${TD}">${show(r.title)}</td><td class="${TD}">${show(r.publisher)}</td>
        <td class="${TD}">${show(r.licence_id)}${r.licence_check ? ` <span class="text-state-warn">· ${esc(r.licence_check)}</span>` : ''}</td>
        <td class="${TD} text-ink-muted">${flagsCue(r.licence)}</td>
        <td class="${TD}">${show(r.modified)}</td><td class="${TD}">${show(r.formats)}</td><td class="${TD} tnum">${bytes(r.size)}</td>
        <td class="${TD} font-mono text-provenance">${show(r.identifier)}${r.doi === NOT_REPORTED ? ' <span class="text-ink-muted">· no DOI reported</span>' : ''}</td>
        <td class="${TD} text-ink-muted">${esc(r.portal_name)}</td></tr>`).join('')}</tbody></table>
      <form data-od-import class="mt-s3 flex flex-wrap items-end gap-[6px]">
        <label class="text-caveat text-ink-muted">Work list <input name="work_list_name" value="${esc(requestName || terms || 'open data')}" class="${INPUT} w-[240px]"></label>
        <button type="submit" class="${BTN}">Import chosen</button>
        <span data-od-import-price class="text-provenance text-ink-muted tnum">0 chosen · 0 calls</span>
        <span class="text-provenance text-ink-muted">at most 25 per import</span>
      </form><div data-od-import-result class="mt-s3"></div>` : '<p class="text-answer text-ink">No candidates.</p>'}`;
  watchTables(out);
  const form = q(out, '[data-od-import]');
  if (!form) return;
  const picked = () => [...out.querySelectorAll('[data-od-pick]:checked')].map((c) => rows[Number(c.dataset.odPick)]);
  out.querySelectorAll('[data-od-pick]').forEach((c) => c.addEventListener('change', () => {
    const n = picked().length;
    q(out, '[data-od-import-price]').textContent = `${n} chosen · ${n} call${n === 1 ? '' : 's'} (one read per dataset)`;
  }));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const chosen = picked().map((r) => ({ portal_slug: r.portal_slug, dataset_id: r.dataset_id }));
    const result = q(out, '[data-od-import-result]');
    if (!chosen.length) { result.textContent = 'Choose at least one row.'; return; }
    result.textContent = 'Importing…';
    try {
      const r = await importOpenData(slug, { rows: chosen, work_list_name: form.work_list_name.value, terms, investigation });
      result.innerHTML = importResultHtml(r);
      watchTables(result);
    } catch (e) { result.innerHTML = `<p class="text-state-warn">${errText(e)}</p>`; }
  });
}

export function importResultHtml(r) {
  const cue = (o) => (o.outcome === 'imported' ? '✓' : o.outcome === 'already_in_catalog' ? '=' : '✗');
  return `<p class="mb-s2 text-answer text-ink tnum">${r.imported} imported · ${r.already_in_catalog} already in the catalog${r.refused ? ` · ${r.refused} refused` : ''}
      ${r.work_list ? ` · work list <span class="font-mono">${esc(r.work_list)}</span>` : ''}</p>
    <table class="w-full text-left" data-rc-id="od-import-result"><thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
      <th class="${TH}"></th><th class="${TH}">Title</th><th class="${TH}">Identifier</th><th class="${TH}">Portals</th><th class="${TH}">Result</th><th class="${TH}">DataCite</th></tr></thead>
    <tbody>${r.rows.map((o) => `<tr class="border-b border-rule" data-od-result="${esc(o.outcome)}">
      <td class="${TD}">${cue(o)}</td><td class="${TD}">${show(o.title)}</td><td class="${TD} font-mono text-provenance">${esc(o.identifier || o.dataset_id || '')}</td>
      <td class="${TD} text-ink-muted">${esc((o.portals || [o.portal]).join(', '))}</td>
      <td class="${TD} ${o.outcome === 'refused' ? 'text-state-warn' : ''}">${esc(o.words)}</td>
      <td class="${TD} text-ink-muted">${esc(o.datacite || '')}</td></tr>`).join('')}</tbody></table>`;
}

// ── Portal directories ────────────────────────────────────────────────────────

export async function renderPortalDirectories(host) {
  const dirs = await listPortalDirectories();
  host.innerHTML = `
    <div class="mb-s2 flex items-center justify-between">
      <h3 class="m-0 font-heading text-name font-normal text-ink">📚 Portal directories</h3>
      <button type="button" data-od-register-toggle class="${BTN}">Register</button>
    </div>
    <form data-od-register class="mb-s3 hidden flex-wrap items-end gap-[6px]">
      <label class="text-caveat text-ink-muted">Name <input name="display_name" required class="${INPUT}" value="dataportals.org"></label>
      <label class="text-caveat text-ink-muted">API <select name="api_kind" class="${INPUT}"><option>dataportals.org</option></select></label>
      <label class="text-caveat text-ink-muted">Listing URL <input name="base_url" placeholder="https://dataportals.org/api/data.json" class="${INPUT} w-[300px]"></label>
      <button type="submit" class="${BTN}">Register</button><span data-od-register-state class="text-provenance text-ink-muted"></span>
    </form>
    ${dirs.length ? `<table class="w-full text-left" data-rc-id="od-directories"><thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
      <th class="${TH}">Directory</th><th class="${TH}">API</th><th class="${TH}">URL</th><th class="${TH}">Last run</th><th class="${TH}"></th></tr></thead>
      <tbody>${dirs.map((d) => `<tr class="border-b border-rule"><td class="${TD}">${esc(d.display_name)}</td><td class="${TD}">${esc(d.api_kind)}</td>
        <td class="${TD} font-mono text-provenance">${esc(d.base_url)}</td><td class="${TD} text-ink-muted">${d.last_run_at ? esc(ago(d.last_run_at)) : 'never run'}</td>
        <td class="${TD}"><button type="button" data-od-run="${esc(d.slug)}" class="${BTN}">Run</button></td></tr>`).join('')}</tbody></table>`
      : '<p data-od-empty class="text-answer text-ink">No directories registered yet.</p>'}
    <div data-od-pane class="mt-s4"></div>`;
  watchTables(host);
  const form = q(host, '[data-od-register]');
  q(host, '[data-od-register-toggle]').addEventListener('click', () => form.classList.toggle('hidden'));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { await registerPortalDirectory(Object.fromEntries(new FormData(form).entries())); await renderPortalDirectories(host); }
    catch (e) { q(host, '[data-od-register-state]').innerHTML = errText(e); }
  });
  host.querySelectorAll('[data-od-run]').forEach((b) => b.addEventListener('click', () => runDirectoryPane(host, b.dataset.odRun)));
}

async function runDirectoryPane(host, slug) {
  const pane = q(host, '[data-od-pane]');
  pane.innerHTML = `<form data-od-dirrun class="mb-s2 flex flex-wrap items-end gap-[6px]">
      <label class="text-caveat text-ink-muted">Filter <input name="terms" placeholder="name, country, API" class="${INPUT}"></label>
      <label class="text-caveat text-ink-muted">Pages <input name="pages" type="number" min="1" max="20" value="8" class="${INPUT} w-[56px]"></label>
      <button type="submit" class="${BTN}">Run</button><span data-od-dirprice class="text-provenance text-ink-muted tnum">8 pages × 1 call = 8 calls (the listing is read once)</span></form>
    <div data-od-results></div>`;
  const form = q(pane, '[data-od-dirrun]');
  form.pages.addEventListener('change', () => {
    const n = Number(form.pages.value) || 1;
    q(pane, '[data-od-dirprice]').textContent = `${n} page${n === 1 ? '' : 's'} × 1 call = ${n} call${n === 1 ? '' : 's'} (the listing is read once)`;
  });
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const out = q(pane, '[data-od-results]');
    out.innerHTML = '<p class="text-ink-muted">Running…</p>';
    try {
      const res = await runPortalDirectory(slug, { pages: Number(form.pages.value) || 1, terms: form.terms.value });
      out.innerHTML = `<p class="mb-s2 text-provenance text-ink-muted tnum">${res.rows.length} of ${show(res.total)} · ${esc(res.price.line)}</p>
        <table class="w-full text-left" data-rc-id="od-dir-candidates"><thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
          <th class="${TH}"></th><th class="${TH}">Portal</th><th class="${TH}">Country</th><th class="${TH}">Domain</th><th class="${TH}">API as stated</th>
          <th class="${TH}">URL</th><th class="${TH}">Datasets</th><th class="${TH}">State</th></tr></thead>
        <tbody>${res.rows.map((r, i) => `<tr class="border-b border-rule" data-od-dirrow="${i}">
          <td class="${TD}"><input type="checkbox" data-od-pick="${i}" ${r.already_registered || r.url === NOT_REPORTED ? 'disabled' : ''}></td>
          <td class="${TD}">${showDir(r.name)}</td><td class="${TD}">${showDir(r.country)}</td><td class="${TD}">${showDir(r.domain)}</td>
          <td class="${TD}">${showDir(r.api_kind)}</td><td class="${TD} font-mono text-provenance">${showDir(r.url)}</td>
          <td class="${TD}">${showDir(r.dataset_count)}</td>
          <td class="${TD} ${r.adapter ? '' : 'text-ink-muted'}">${esc(r.status)}</td></tr>`).join('')}</tbody></table>
        <button type="button" data-od-dirimport class="${BTN} mt-s3">Register chosen</button><div data-od-import-result class="mt-s3"></div>`;
      watchTables(out);
      q(out, '[data-od-dirimport]').addEventListener('click', async () => {
        const urls = [...out.querySelectorAll('[data-od-pick]:checked')].map((c) => res.rows[Number(c.dataset.odPick)].url);
        const target = q(out, '[data-od-import-result]');
        if (!urls.length) { target.textContent = 'Choose at least one portal.'; return; }
        try {
          const r = await importDirectoryPortals(slug, { urls });
          target.innerHTML = `<p class="text-answer text-ink tnum">${r.registered} registered</p><ul class="m-0 list-none p-0">${r.rows.map((o) => `<li class="text-caveat">${o.outcome === 'registered' ? '✓' : '='} ${esc(o.name || o.url)} · ${esc(o.words)}</li>`).join('')}</ul>`;
        } catch (e) { target.innerHTML = `<p class="text-state-warn">${errText(e)}</p>`; }
      });
    } catch (e) { out.innerHTML = `<p class="text-state-warn">${errText(e)}</p>`; }
  });
}

// ── Open data (the datasets) and the resource page ────────────────────────────

export async function renderOpenData(host) {
  const rows = await listOpenData();
  host.innerHTML = `<h3 class="m-0 mb-s2 font-heading text-name font-normal text-ink">🗂 Open data</h3>
    ${rows.length ? `<table class="w-full text-left" data-rc-id="od-datasets"><thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
      <th class="${TH}">Title</th><th class="${TH}">Identifier</th><th class="${TH}">Publisher</th><th class="${TH}">Licence</th><th class="${TH}">Portals</th><th class="${TH}">Work list</th><th class="${TH}">Imported</th></tr></thead>
      <tbody>${rows.map((d) => `<tr class="border-b border-rule"><td class="${TD}"><a href="#" data-od-dataset="${esc(d.slug)}" class="text-accent-ink">${show(d.title)}</a></td>
        <td class="${TD} font-mono text-provenance">${esc(d.identifier)}</td><td class="${TD}">${show(d.publisher)}</td><td class="${TD}">${show(d.licence_id)}</td>
        <td class="${TD} text-ink-muted">${esc(d.portals.join(', '))}</td><td class="${TD} font-mono text-provenance">${esc(d.work_list_slug)}</td>
        <td class="${TD} text-ink-muted">${esc(ago(d.imported_at))}</td></tr>`).join('')}</tbody></table>` : '<p data-od-empty class="text-answer text-ink">Nothing imported yet.</p>'}
    <div data-od-pane class="mt-s4"></div>`;
  watchTables(host);
  host.querySelectorAll('[data-od-dataset]').forEach((a) => a.addEventListener('click', async (ev) => {
    ev.preventDefault();
    q(host, '[data-od-pane]').innerHTML = datasetPageHtml(await getOpenData(a.dataset.odDataset));
    watchTables(q(host, '[data-od-pane]'));
  }));
}

/** The dataset's page: normalised fields with who stated them and when, the survey absence word, the record verbatim. */
export function datasetPageHtml(d) {
  const stated = `stated by ${(d.stated_by || d.portals || []).join(', ')} · retrieved ${d.retrieved_at ? ago(d.retrieved_at) : 'not recorded'}`;
  const field = (label, value) => `<tr class="border-b border-rule"><td class="${TD} text-ink-muted">${esc(label)}</td><td class="${TD}">${value}</td>
      <td class="${TD} text-provenance text-ink-muted">${esc(stated)}</td></tr>`;
  const dc = d.datacite;
  return `<div data-od-page>
    <h4 class="m-0 mb-s2 font-heading text-name font-normal text-ink">${show(d.title)}</h4>
    <p class="mb-s2 text-provenance text-ink-muted">${esc(d.identifier_kind === 'doi' ? 'DOI' : 'portal id')} <span class="font-mono">${esc(d.identifier)}</span>
      · imported ${esc(ago(d.imported_at))} by ${esc(d.imported_by || 'not recorded')} into <span class="font-mono">${esc(d.work_list_slug)}</span></p>
    <table class="w-full text-left" data-rc-id="od-fields"><thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
      <th class="${TH}">Field</th><th class="${TH}">Value</th><th class="${TH}">Source</th></tr></thead><tbody>
      ${field('Publisher', show(d.publisher))}${field('Licence', show(d.licence_id))}${field('Licence flags', flagsCue(d.licence))}
      ${field('Modified', show(d.modified))}${field('Formats', show(d.formats))}${field('Size', bytes(d.size))}
      ${dc ? `<tr class="border-b border-rule"><td class="${TD} text-ink-muted">DataCite publisher</td><td class="${TD}">${show(dc.publisher)}</td><td class="${TD} text-provenance text-ink-muted">stated by DataCite</td></tr>
        <tr class="border-b border-rule"><td class="${TD} text-ink-muted">Related identifiers</td><td class="${TD}">${show((dc.related_identifiers === NOT_REPORTED ? NOT_REPORTED : dc.related_identifiers.map((r) => `${r.relation} ${r.identifier}`)))}</td><td class="${TD} text-provenance text-ink-muted">stated by DataCite</td></tr>` : ''}
    </tbody></table>
    <h5 class="m-0 mb-s2 mt-s3 text-caps uppercase tracking-caps text-ink-muted">Questions</h5>
    <ul data-od-survey class="m-0 list-none p-0">${SURVEY_QUESTIONS.map((x) => `<li class="text-caveat"><span class="text-ink">${esc(x)}</span> <span class="text-ink-muted">· ${NO_SURVEY_WORDS}</span></li>`).join('')}</ul>
    <details class="mt-s3"><summary class="cursor-pointer text-caveat text-ink">The publisher's record, verbatim</summary>
      <pre data-od-record class="mt-s2 max-h-[420px] overflow-auto whitespace-pre-wrap font-mono text-provenance text-ink">${esc(JSON.stringify(d.record, null, 2))}</pre></details>
  </div>`;
}
