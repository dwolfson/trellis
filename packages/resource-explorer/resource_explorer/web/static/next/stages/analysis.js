/* Analysis.
 *
 * PLAN-FINISH-REPOS.md item 11: Analysis is `built: true` in app.js's
 * `STAGES` array. It needs no bespoke renderer for its Questions checklist
 * -- the generic Questions-checklist engine (`loadPane()` in app.js) already
 * reaches it correctly, the same as Scouting/Enrichment/Curate, because the
 * catalog carries 11 real Analysis-tagged questions (question_catalog.yaml)
 * backed by 11 `intent: analysis` analyses (analysis_catalog.yaml).
 *
 * This module exists for the one thing that DOES need bespoke code: classic's
 * Analysis pane also has a "Sub-Resources" sub-tab (index.html's
 * loadAnalysisSubResourcesView, ~380 lines across candidate discovery,
 * cataloguing and scoped-analysis dispatch). ITEM-11-DISCOVERY-ASSESSMENT-
 * ANALYSIS-IMPLEMENTED.md deferred it by name rather than build or drop it;
 * RULING-SUBRESOURCES-PLACEMENT.md (2026-09-22, docs/design-notes/) then
 * resolved WHERE it belongs, having found it is two features wearing one
 * tab's name:
 *
 *   - the candidate list / selection / catalogue UI is RUN CONFIGURATION --
 *     it belongs on Survey & analyses, attached to sub_resource_survey's own
 *     row, beside the Run button that was otherwise a dead end without it;
 *   - its results are an ORDINARY ANALYSIS'S OUTPUT (`sub_resource_survey`,
 *     intent: analysis, findings-shaped) -- they belong on By analysis, and
 *     in fact already render there with zero code here, because
 *     loadByAnalysisPane()'s dashboard loop already handles any analysis
 *     whose results carry a `findings` array generically (app.js's
 *     `data_profile` board carries sub_resource_survey alongside
 *     data_file_profiling for exactly this reason).
 *
 * Nothing joins the four-tab sub-strip -- the ruling's whole point. This
 * file therefore exports `mountSubResourcePanel`, called from app.js's
 * `renderAnalysesIndexSection` only for the one row whose
 * `analysis_id === 'sub_resource_survey'`, when that row's own
 * "Select & catalog" toggle is opened. The one-line deferral note this
 * module used to export is gone -- the feature it named is now built, and
 * nothing else classic's Sub-Resources view did was left out (see the ruling
 * and this branch's own report for what was and wasn't ported).
 */
import { state, esc } from '/static/next/app.js';
import {
  getAnalysisResults, listSubResources, listAnalyses, catalogSubResources,
  runScopedAnalysis, getScopedAnalysisResults, isShapeCompatible,
} from '/static/re-api.js';

// panel element -> { slug, findings, cataloged, catalog, sortKey, sortDir,
// filterText }. A WeakMap rather than a module-level object because the
// panel itself IS the identity that matters: it is destroyed and rebuilt
// every time the Survey & analyses pane re-renders (a re-run, a resource
// switch), and nothing here should outlive that DOM node.
const PANEL_STATE = new WeakMap();

/** Reset a panel's cached state and reload it from scratch -- used after any
 *  write (cataloging, a scoped run) that could change what "already
 *  catalogued" means. */
async function reload(panel) {
  const prior = PANEL_STATE.get(panel);
  PANEL_STATE.delete(panel);
  await mountSubResourcePanel(prior?.slug ?? state.selectedSlug, panel);
}

export async function mountSubResourcePanel(slug, panel) {
  if (!panel) return;
  const cached = PANEL_STATE.get(panel);
  if (cached && cached.slug === slug) {
    renderSubResourcePanel(panel, cached);
    return;
  }
  panel.innerHTML = '<div class="py-s2 text-caveat text-ink-muted">Reading candidates…</div>';
  const s = { slug, findings: [], cataloged: {}, catalog: [], sortKey: null, sortDir: 1, filterText: '' };
  try {
    const [results, catalogedRows, catalog] = await Promise.all([
      getAnalysisResults(slug, 'sub_resource_survey').catch(() => ({})),
      listSubResources(slug).catch(() => []),
      listAnalyses('repo').catch(() => []),
    ]);
    s.findings = results.findings || [];
    s.catalog = catalog || [];
    for (const r of catalogedRows || []) s.cataloged[r.locator] = r;
  } catch (err) {
    panel.innerHTML = `<p class="text-caveat text-state-warn">Could not read candidates: ${esc(err.message)}</p>`;
    return;
  }
  if (!panel.isConnected) return; // pane moved on while this awaited
  PANEL_STATE.set(panel, s);
  renderSubResourcePanel(panel, s);
}

function catalogedBadge(row) {
  return row.egeria_guid
    ? '<span class="text-accent-ink" title="Published to Egeria">☁ published</span>'
    : '<span class="text-ink-muted" title="Tracked locally only">🗂 catalogued</span>';
}

function subResRowHtml(f, s) {
  const locator = f.path || '';
  const cataloged = s.cataloged[locator];
  const checkedDefault = f.label === 'worthy' && !cataloged;
  const ownersStr = (f.owners || []).join(', ');
  return `<tr class="border-b border-rule ${f.label !== 'worthy' ? 'opacity-60' : ''}">
    <td class="py-[5px] pr-s2">
      ${cataloged
        ? '<input type="checkbox" disabled checked title="Already catalogued">'
        : `<input type="checkbox" data-subres-pick data-locator="${esc(locator)}" data-kind="${esc(f.kind)}" ${checkedDefault ? 'checked' : ''}>`}
    </td>
    <td class="py-[5px] pr-s2 max-w-[28ch] truncate font-mono text-caveat text-ink" title="${esc(locator)}">${esc(locator) || '(root)'}</td>
    <td class="py-[5px] pr-s2 text-caveat text-ink-muted">${f.kind === 'folder' ? '📁' : '📄'} ${esc(f.kind)}</td>
    <td class="py-[5px] pr-s2 text-caveat ${f.label === 'worthy' ? 'text-accent-ink' : 'text-ink-muted'}">${esc(f.label)}</td>
    <td class="py-[5px] pr-s2 max-w-[30ch] truncate text-caveat text-ink-muted" title="${esc(f.summary || '')}">${esc(f.summary || '')}</td>
    <td class="py-[5px] pr-s2 text-caveat text-ink-muted">${esc(f.last_updated_at ? f.last_updated_at.substring(0, 10) : '—')}</td>
    <td class="py-[5px] pr-s2 max-w-[16ch] truncate text-caveat text-ink-muted" title="${esc(ownersStr)}">${esc(ownersStr) || '—'}</td>
    <td class="py-[5px] text-caveat">${cataloged ? catalogedBadge(cataloged) : ''}</td>
  </tr>`;
}

const SUBRES_COLS = [
  ['path', 'Path'], ['kind', 'Kind'], ['label', 'Worthy?'],
  ['summary', 'Reason'], ['last_updated_at', 'Last updated'],
];

function subResCatalogedRowHtml(slug, locator, row, catalog) {
  const compatible = catalog.filter((a) => isShapeCompatible(a.target_shape, row.kind));
  const optionsHtml = compatible.length
    ? compatible.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')
    : '<option value="">(no scopable analyses)</option>';
  return `<tr class="border-b border-rule" data-subres-catalogued-row data-locator="${esc(locator)}" data-kind="${esc(row.kind)}">
    <td class="py-[5px] pr-s2">${catalogedBadge(row)}</td>
    <td class="py-[5px] pr-s2 max-w-[28ch] truncate font-mono text-caveat text-ink" title="${esc(locator)}">${esc(locator) || '(root)'}</td>
    <td class="py-[5px] pr-s2 text-caveat text-ink-muted">${row.kind === 'folder' ? '📁' : '📄'} ${esc(row.kind)}</td>
    <td class="py-[5px]">
      <div class="flex flex-wrap items-center gap-[6px]">
        <select data-subres-analyze-select ${compatible.length ? '' : 'disabled'}
          class="border border-rule-strong bg-transparent px-1 py-[1px] text-caveat text-ink">${optionsHtml}</select>
        <button type="button" data-subres-run-scoped ${compatible.length ? '' : 'disabled'}
          class="cursor-pointer rounded-sm border border-accent px-2 py-[1px] text-caveat text-accent-ink disabled:cursor-not-allowed disabled:opacity-40"
          >run ›</button>
      </div>
      <div data-subres-scoped-results class="mt-[3px] text-provenance text-ink-muted"></div>
    </td>
  </tr>`;
}

function subResCatalogedSectionHtml(slug, s) {
  const locators = Object.keys(s.cataloged).sort();
  if (!locators.length) return '';
  return `
    <div class="mt-s3 text-caps uppercase tracking-caps text-ink-muted">Cataloged sub-resources ·
      <span class="tnum">${locators.length}</span></div>
    <p class="mt-[2px] max-w-[70ch] text-provenance text-ink-muted">Run a corpus/container/leaf-shaped analysis
      narrowed to just one of these, instead of the whole repo -- only analyses whose scope fits the item's kind
      are offered.</p>
    <table class="mt-s2 w-full border-collapse text-caveat">
      <thead><tr class="border-b border-rule-strong text-caps uppercase tracking-caps text-ink-muted">
        <th class="py-[4px] pr-s2 text-left"></th>
        <th class="py-[4px] pr-s2 text-left">Locator</th>
        <th class="py-[4px] pr-s2 text-left">Kind</th>
        <th class="py-[4px] text-left">Analyze</th>
      </tr></thead>
      <tbody>${locators.map((loc) => subResCatalogedRowHtml(slug, loc, s.cataloged[loc], s.catalog)).join('')}</tbody>
    </table>`;
}

function renderSubResourcePanel(panel, s) {
  const slug = s.slug;
  const catalogedHtml = subResCatalogedSectionHtml(slug, s);

  if (!s.findings.length) {
    panel.innerHTML = `
      <p class="max-w-[70ch] text-caveat text-ink-muted">No sub-resource survey results yet -- use the
        <span class="text-ink">run</span> button above to recommend which folders/files are worth cataloguing
        as their own Egeria assets, based on the current file inventory. This panel will show the candidate
        list once it has run.</p>
      ${catalogedHtml}`;
    bindCatalogedSection(panel, slug, s);
    return;
  }

  const filterLower = s.filterText.toLowerCase();
  let rows = s.findings.filter((f) => !filterLower || (f.path || '').toLowerCase().includes(filterLower));
  if (s.sortKey) {
    rows = rows.slice().sort((a, b) => {
      const av = a[s.sortKey] ?? ''; const bv = b[s.sortKey] ?? '';
      return av < bv ? -s.sortDir : av > bv ? s.sortDir : 0;
    });
  }
  const headerHtml = SUBRES_COLS.map(([key, label]) => `
    <th class="cursor-pointer select-none py-[4px] pr-s2 text-left" data-subres-sort="${key}">${esc(label)}${
      s.sortKey === key ? (s.sortDir === 1 ? ' ▲' : ' ▼') : ''}</th>`).join('');

  panel.innerHTML = `
    <p class="max-w-[70ch] text-caveat text-ink-muted">Review the recommendation list, select which folders/files
      are worth tracking as their own Egeria assets, then catalog the selection. Repeatable -- come back anytime
      with more information and add to what's already catalogued.</p>

    <div class="mt-s2 flex flex-wrap items-center gap-s2">
      <button type="button" data-subres-select-all="true" class="cursor-pointer bg-transparent text-caveat text-accent-ink underline">select all worthy</button>
      <button type="button" data-subres-select-all="false" class="cursor-pointer bg-transparent text-caveat text-ink-muted underline">deselect all</button>
      <input type="text" placeholder="Filter by path…" value="${esc(s.filterText)}" data-subres-filter
        class="border border-rule-strong bg-transparent px-[6px] py-[2px] text-caveat text-ink">
      <span class="text-provenance text-ink-muted">${rows.length} of ${s.findings.length} shown</span>
    </div>

    <table class="mt-s2 w-full border-collapse text-caveat">
      <thead><tr class="border-b border-rule-strong text-caps uppercase tracking-caps text-ink-muted">
        <th class="py-[4px] pr-s2"></th>
        ${headerHtml}
        <th class="py-[4px] pr-s2 text-left">Owners</th>
        <th class="py-[4px] text-left">Status</th>
      </tr></thead>
      <tbody>${rows.map((f) => subResRowHtml(f, s)).join('') || `<tr><td colspan="8" class="py-s3 text-center text-ink-muted">No matches.</td></tr>`}</tbody>
    </table>

    <div class="mt-s3 border-t border-rule pt-s2">
      <label class="flex items-center gap-[6px] text-caveat text-ink">
        <input type="checkbox" data-subres-publish checked> also publish to Egeria (uncheck to track locally only)
      </label>
      <button type="button" data-subres-catalog
        class="mt-s2 cursor-pointer rounded-sm border border-accent px-2 py-[2px] text-caveat text-accent-ink"
        >catalog selected</button>
      <div data-subres-feedback class="mt-[3px] text-caveat"></div>
    </div>

    ${catalogedHtml}`;

  panel.querySelectorAll('[data-subres-sort]').forEach((th) => th.addEventListener('click', () => {
    const key = th.dataset.subresSort;
    if (s.sortKey === key) s.sortDir *= -1; else { s.sortKey = key; s.sortDir = 1; }
    renderSubResourcePanel(panel, s);
  }));
  panel.querySelector('[data-subres-filter]')?.addEventListener('input', (e) => {
    s.filterText = e.target.value;
    renderSubResourcePanel(panel, s);
  });
  panel.querySelectorAll('[data-subres-select-all]').forEach((b) => b.addEventListener('click', () => {
    const checked = b.dataset.subresSelectAll === 'true';
    panel.querySelectorAll('[data-subres-pick]').forEach((cb) => { cb.checked = checked; });
  }));
  panel.querySelector('[data-subres-catalog]')?.addEventListener('click', (e) => submitSubResourceCatalog(panel, slug, e.target));

  bindCatalogedSection(panel, slug, s);
}

async function submitSubResourceCatalog(panel, slug, btn) {
  const boxes = Array.from(panel.querySelectorAll('[data-subres-pick]:checked'));
  const feedback = panel.querySelector('[data-subres-feedback]');
  if (!boxes.length) {
    if (feedback) feedback.innerHTML = '<span class="text-state-warn">Select at least one item first.</span>';
    return;
  }
  const items = boxes.map((cb) => ({ locator: cb.dataset.locator, kind: cb.dataset.kind }));
  const publishToEgeria = panel.querySelector('[data-subres-publish]')?.checked ?? true;
  const original = btn.textContent;
  btn.textContent = 'cataloguing…';
  btn.disabled = true;
  try {
    const data = await catalogSubResources(slug, items, publishToEgeria);
    const publishedCount = Object.keys(data.published || {}).length;
    const msg = publishToEgeria
      ? `Catalogued ${data.cataloged.length} sub-resource(s), published ${publishedCount} to Egeria.`
      : `Catalogued ${data.cataloged.length} sub-resource(s) locally.`;
    if (feedback) feedback.innerHTML = `<span class="text-accent-ink">${esc(msg)}</span>`;
    await reload(panel);
  } catch (err) {
    if (feedback) feedback.innerHTML = `<span class="text-state-warn">Catalog failed: ${esc(err.message)}</span>`;
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
}

function bindCatalogedSection(panel, slug, s) {
  panel.querySelectorAll('[data-subres-catalogued-row]').forEach((tr) => {
    const locator = tr.dataset.locator;
    const runBtn = tr.querySelector('[data-subres-run-scoped]');
    const select = tr.querySelector('[data-subres-analyze-select]');
    const resultsEl = tr.querySelector('[data-subres-scoped-results]');
    runBtn?.addEventListener('click', async () => {
      const analysisId = select?.value;
      if (!analysisId) return;
      const original = runBtn.textContent;
      runBtn.textContent = '⟳';
      runBtn.disabled = true;
      if (resultsEl) resultsEl.textContent = 'running…';
      try {
        const data = await runScopedAnalysis(slug, analysisId, locator);
        if (data.status === 'ok') {
          await loadScopedResults(slug, analysisId, locator, resultsEl);
        } else if (resultsEl) {
          resultsEl.innerHTML = `<span class="text-state-warn">${esc(data.error || 'failed')}</span>`;
        }
      } catch (err) {
        if (resultsEl) resultsEl.innerHTML = `<span class="text-state-warn">${esc(err.message)}</span>`;
      } finally {
        runBtn.textContent = original;
        runBtn.disabled = false;
      }
    });
  });
}

async function loadScopedResults(slug, analysisId, locator, resultsEl) {
  if (!resultsEl) return;
  try {
    const data = await getScopedAnalysisResults(slug, analysisId, locator);
    if (!Object.keys(data).length) {
      resultsEl.innerHTML = '<span class="text-ink-muted">No results yet.</span>';
      return;
    }
    const parts = Object.entries(data)
      .filter(([k]) => k !== 'surveyed_at')
      .map(([k, v]) => `${esc(k)}: <span class="text-ink">${esc(String(v))}</span>`);
    resultsEl.innerHTML = parts.join(' · ') || '<span class="text-ink-muted">No results yet.</span>';
  } catch (err) {
    resultsEl.innerHTML = `<span class="text-state-warn">Failed to load results: ${esc(err.message)}</span>`;
  }
}
