/* Discovery import — corpus-level "find and import candidate repos".
 *
 * NOT a stage module, deliberately: SPEC-ACTIONABLE-AND-HONEST.md point 2
 * (project owner's round, 2026-09-15) found that `Find repos` had been
 * placed as a per-stage sub-tab and ruled that wrong — searching/importing
 * repos happens BEFORE any stage applies and is the same action on
 * Scouting as on Curate, so it does not belong to Discovery any more than
 * to any other stage. It now lives beside the sidebar's `Repos · DBs · FS`
 * switcher (`app.js`'s `find-repos` sidebar action), which is the control
 * that already scopes the whole left column — this module is what that
 * action opens, replacing the old "open the current UI" stub for
 * `state.resourceType === 'repo'`.
 *
 * This is the real port of classic's (`index.html`) three corpus-level
 * Discovery affordances `stages/discovery.js`'s header comment named as not
 * yet ported: repo search (`searchScoutRepos()`), the `/from-list` bulk
 * loader (`_loadRepoListFromFile()`), and the inventory CSV export
 * (`_downloadInventory()`). Org import folds into search (`RepoSearchRequest.org`
 * is a plain qualifier field, same as classic) plus from-list's own
 * account-URL expansion (`_expand_org`, server-side) — there is no separate
 * "org import" affordance in the backend to port a third UI for.
 *
 * Same two-step shape as classic throughout: searching or loading a list
 * only produces REVIEW rows (`DiscoveredRepo`) — nothing is registered
 * until rows are selected and "Import selected" is pressed. Disposition
 * (👁 track / 🔬 investigate / 👍 recommend / ✅ using / ⛔ abandon / 🚫
 * ignore) can be set on a row before it's ever imported, exactly as
 * classic's per-row disposition buttons do, because `repo_dispositions`
 * keys on `github_url`, not on a registered project.
 */
import { openDialog } from '/static/next/worklist.js';
import {
  searchDiscoveryRepos, discoverFromList, fetchInventoryCsv, importDiscoveredRepos,
  setDisposition, listGroups,
} from '/static/re-api.js';
import { esc, icon, refreshGroupsAndSidebar } from '/static/next/app.js';

// Module-local view state for the one dialog this file renders — mirrors
// classic's own module-level `_scout*` globals, scoped here instead of
// polluting app.js's shared `state` with a feature only this dialog reads.
const view = {
  mode: 'search',        // 'search' | 'list'
  filters: {
    keyword: '', min_stars: 0, language: '', license: '', pushed_after: '',
    org: '', topic: '', include_archived: false, include_forks: false,
  },
  results: [],            // DiscoveredRepo[]
  resultsSource: '',       // provenance line ("GitHub search", a filename)
  selected: new Set(),     // indices into `results`
  filterText: '',
  groups: [],
  status: '',              // feedback line above the results table
  statusIsError: false,
  listStatus: '',          // separate feedback line for the from-list panel
  listStatusIsError: false,
  busy: false,
};

const DISPOSITION_EMOJI = {
  tracking: '👁', investigating: '🔬', recommended: '👍',
  using: '✅', abandoned: '⛔', ignored: '🚫',
};
const HIDDEN_DISPOSITIONS = new Set(['abandoned', 'ignored']);

/** Opens the dialog and kicks off the first render. The only export — every
 *  other function here is reached only from within the dialog it builds. */
export async function openFindReposDialog() {
  const el = openDialog('Find and import candidate repos',
    'Search GitHub or load a list — nothing is registered until you select rows below',
    { wide: true });
  try { view.groups = await listGroups(); } catch { view.groups = []; }
  render(el);
}

function render(el) {
  const body = el.querySelector('#wl-detail-body');
  body.innerHTML = `
    ${modeTabsHtml()}
    ${view.mode === 'search' ? searchFormHtml() : listPanelHtml()}
    ${statusLineHtml(view.status, view.statusIsError)}
    <div class="my-s3 h-px bg-rule"></div>
    ${resultsHtml()}
  `;
  bind(el);
}

function statusLineHtml(text, isError) {
  if (!text) return '';
  return `<p class="mt-s2 text-caveat ${isError ? 'text-state-warn' : 'text-ink-muted'}">${esc(text)}</p>`;
}

function modeTabsHtml() {
  const tab = (id, label) => `<button data-mode="${id}"
    class="cursor-pointer border-0 bg-transparent pb-[2px] mr-s4 font-heading text-subtab ${
      view.mode === id ? 'border-b border-accent text-ink' : 'text-ink-muted hover:text-ink'}"
    >${esc(label)}</button>`;
  return `<div class="mb-s3 flex items-center gap-0 text-subtab">
    ${tab('search', '🔍 Search GitHub')}${tab('list', '📄 From a list')}
  </div>`;
}

/* ── Search GitHub ──────────────────────────────────────────────────────── */

function searchFormHtml() {
  const f = view.filters;
  const field = (id, label, extra = '') => `<div>
    <label class="mb-[2px] block text-caps uppercase tracking-caps text-ink-muted">${esc(label)}</label>
    ${extra}
  </div>`;
  const input = (key, placeholder = '', type = 'text') =>
    `<input data-f="${key}" type="${type}" placeholder="${esc(placeholder)}" value="${esc(f[key] ?? '')}"
       class="w-full rounded-sm border border-rule bg-transparent px-2 py-[3px] text-caveat text-ink">`;
  return `
    <p class="mb-s2 max-w-[70ch] text-caveat text-ink-muted">
      A general GitHub search for candidate repos — independent of any specific org. To pull in a
      whole account's repos, put an org/user search filter here, or paste an account URL
      (e.g. <span class="font-mono">github.com/apache</span>) into "From a list" and it expands
      automatically.
    </p>
    <div class="grid grid-cols-2 gap-s2 sm:grid-cols-4">
      ${field('keyword', 'Keyword', input('keyword', 'data catalog'))}
      ${field('min_stars', 'Min stars', input('min_stars', '0', 'number'))}
      ${field('language', 'Language', input('language', 'python'))}
      ${field('license', 'License', input('license', 'apache-2.0'))}
      ${field('pushed_after', 'Pushed after', input('pushed_after', '', 'date'))}
      ${field('org', 'Org', input('org', 'my-org'))}
      ${field('topic', 'Topic', input('topic', 'data-catalog'))}
    </div>
    <div class="mt-s2 flex flex-wrap items-center gap-s3 text-caveat text-ink-muted">
      <label class="flex items-center gap-[4px]"><input type="checkbox" data-f="include_archived" ${f.include_archived ? 'checked' : ''}> Include archived</label>
      <label class="flex items-center gap-[4px]"><input type="checkbox" data-f="include_forks" ${f.include_forks ? 'checked' : ''}> Include forks</label>
      <button data-act="search" class="ml-auto cursor-pointer rounded-sm border border-accent bg-transparent px-s3 py-[3px] text-caveat text-accent-ink" ${view.busy ? 'disabled' : ''}
        >${view.busy ? 'Searching…' : 'Search'}</button>
    </div>`;
}

function readFiltersFromDom(el) {
  el.querySelectorAll('[data-f]').forEach((inp) => {
    const key = inp.dataset.f;
    if (inp.type === 'checkbox') view.filters[key] = inp.checked;
    else if (inp.type === 'number') view.filters[key] = parseInt(inp.value, 10) || 0;
    else view.filters[key] = inp.value.trim();
  });
  // GitHub topics are always lowercase-hyphenated — same normalization
  // classic's `_currentScoutFilters()` applies, so a human-typed "Data
  // Catalog" becomes the valid qualifier "data-catalog" instead of a 400.
  view.filters.topic = view.filters.topic.toLowerCase().replace(/\s+/g, '-');
}

const NON_FILTER_KEYS = new Set(['min_stars', 'include_archived', 'include_forks']);

async function runSearch(el) {
  readFiltersFromDom(el);
  const hasFilter = Object.entries(view.filters).some(([k, v]) =>
    NON_FILTER_KEYS.has(k) ? (k === 'min_stars' && v > 0) : !!v);
  if (!hasFilter) {
    view.status = 'Enter at least one filter.';
    view.statusIsError = true;
    render(el);
    return;
  }
  view.busy = true;
  view.status = 'Searching…';
  view.statusIsError = false;
  render(el);
  try {
    view.results = await searchDiscoveryRepos({ ...view.filters, sort: 'stars', limit: 100 });
    view.resultsSource = 'GitHub search';
    view.selected.clear();
    view.filterText = '';
    view.status = `Found ${view.results.length} repo(s).`;
    view.statusIsError = false;
  } catch (err) {
    view.status = `Search failed: ${err.message}`;
    view.statusIsError = true;
  } finally {
    view.busy = false;
    render(el);
  }
}

/* ── From a list ────────────────────────────────────────────────────────── */

function listPanelHtml() {
  return `
    <p class="mb-s2 max-w-[70ch] text-caveat text-ink-muted">
      A CSV with an <span class="font-mono">address</span> column, or one GitHub URL per line —
      the same shape "Download inventory" writes, so it round-trips. An account URL expands to its
      member repos automatically. Loading fills the same review table as a search below; nothing
      is imported until you select rows and press Import.
    </p>
    <div class="flex flex-wrap items-center gap-s3">
      <label class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-s3 py-[3px] text-caveat text-accent-ink hover:border-accent">
        📄 Load from file
        <input data-list-file type="file" accept=".csv,.txt,text/csv,text/plain" class="hidden">
      </label>
      <button data-act="download-inventory" class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-s3 py-[3px] text-caveat text-accent-ink hover:border-accent"
        title="Download every registered resource as CSV — inventory plus current status. Re-importable: the status_ columns are ignored on the way back in.">
        ⬇ Download inventory
      </button>
    </div>
    <textarea data-list-text rows="4" placeholder="https://github.com/org/repo&#10;https://github.com/org/repo2"
      class="mt-s2 w-full rounded-sm border border-rule bg-transparent px-2 py-[4px] font-mono text-caveat text-ink"></textarea>
    <div class="mt-s2 flex items-center gap-s2">
      <button data-act="load-pasted" class="cursor-pointer rounded-sm border border-accent bg-transparent px-s3 py-[3px] text-caveat text-accent-ink" ${view.busy ? 'disabled' : ''}
        >${view.busy ? 'Loading…' : 'Load pasted list'}</button>
    </div>
    ${statusLineHtml(view.listStatus, view.listStatusIsError)}
  `;
}

function renderListLoadSummary(filename, d) {
  const shown = (d.repos || []).length;
  const lost = (d.rows_read || 0) - shown;
  const parts = [`✓ ${filename} loaded — ${d.rows_read} row(s) read → ${shown} listed below`
    + (d.already_registered ? `, ${d.already_registered} already registered` : '') + '.'];
  if ((d.expanded_orgs || []).length) {
    const bits = d.expanded_orgs.map((o) => o.error
      ? `${o.org} (could not expand: ${o.error})`
      : `${o.org} → ${o.count} repo(s)${o.truncated ? ' (first ' + o.count + ' only)' : ''}`);
    parts.push(`Organisation URL(s) expanded: ${bits.join('; ')}`);
  }
  if ((d.skipped || []).length) {
    parts.push(`${d.skipped.length} row(s) skipped: ${d.skipped.slice(0, 5).join('; ')}`
      + (d.skipped.length > 5 ? ` … and ${d.skipped.length - 5} more` : ''));
  }
  if ((d.unreachable || []).length) {
    parts.push(`${d.unreachable.length} not found on GitHub: ${d.unreachable.slice(0, 5).join(', ')}`
      + (d.unreachable.length > 5 ? ` … and ${d.unreachable.length - 5} more` : ''));
  }
  if (shown) parts.push('Nothing is registered yet — select rows below and Import Selected to add them.');
  view.listStatus = parts.join(' ');
  view.listStatusIsError = lost > 0 && shown === 0;
}

async function loadFromText(el, text, label) {
  view.busy = true;
  view.listStatus = `Reading ${label}…`;
  view.listStatusIsError = false;
  render(el);
  try {
    const d = await discoverFromList(text);
    view.results = d.repos || [];
    view.resultsSource = label;
    view.selected.clear();
    view.filterText = '';
    renderListLoadSummary(label, d);
  } catch (err) {
    view.listStatus = `Could not load ${label}: ${err.message}`;
    view.listStatusIsError = true;
  } finally {
    view.busy = false;
    render(el);
  }
}

async function downloadInventory(el) {
  const btn = el.querySelector('[data-act="download-inventory"]');
  const original = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⬇ Preparing…'; }
  try {
    const { text, filename } = await fetchInventoryCsv();
    if (!text.trim()) throw new Error('the server returned an empty file');
    const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    const rows = Math.max(0, text.trim().split('\n').length - 1);
    view.listStatus = `Downloaded ${filename} — ${rows} resource(s).`;
    view.listStatusIsError = false;
  } catch (err) {
    view.listStatus = `Export failed: ${err.message}. If the server was restarted recently, reload this page.`;
    view.listStatusIsError = true;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
    render(el);
  }
}

/* ── Results table (shared by both modes) ──────────────────────────────── */

function visibleResults() {
  const term = view.filterText.toLowerCase();
  return view.results
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => !term || [r.full_name, r.description, r.language, r.license]
      .some((v) => (v || '').toLowerCase().includes(term)));
}

function resultsHtml() {
  if (!view.results.length) return '';
  const visible = visibleResults();
  const groupOptions = view.groups.map((g) =>
    `<option value="${esc(g.slug)}">${esc(g.display_name)}</option>`).join('');
  const selectableCount = visible.filter(({ r }) => !r.already_registered
    && !HIDDEN_DISPOSITIONS.has(r.disposition)).length;

  const rows = visible.map(({ r, i }) => {
    const dimmed = r.already_registered || HIDDEN_DISPOSITIONS.has(r.disposition);
    const dispTitle = r.disposition_reason
      ? `${r.disposition}${r.disposition_decided_at ? ' — ' + r.disposition_decided_at : ''}: ${r.disposition_reason}`
      : r.disposition;
    return `<tr class="border-b border-rule ${dimmed ? 'opacity-50' : ''}">
      <td class="py-s1 pr-s2"><input type="checkbox" data-row="${i}" ${r.already_registered ? 'disabled' : ''} ${view.selected.has(i) ? 'checked' : ''}></td>
      <td class="py-s1 pr-s2 max-w-[220px] truncate font-mono text-caveat text-ink">
        <a href="${esc(r.html_url)}" target="_blank" rel="noopener noreferrer" class="hover:text-accent-ink">${esc(r.full_name)}</a>
      </td>
      <td class="py-s1 pr-s2 max-w-[260px] truncate text-caveat text-ink-muted">${esc(r.description) || '—'}</td>
      <td class="py-s1 pr-s2 text-caveat text-ink-muted">★ ${r.stars}</td>
      <td class="py-s1 pr-s2 text-caveat text-ink-muted">${esc(r.language) || '—'}</td>
      <td class="py-s1 pr-s2 text-caveat text-ink-muted">${esc(r.license) || '—'}</td>
      <td class="py-s1 pr-s2 text-caveat" title="${esc(dispTitle)}">${r.already_registered
        ? '<span class="text-ink-muted">already registered</span>'
        : (r.disposition && r.disposition !== 'undecided' ? esc(r.disposition) : '')}</td>
      <td class="py-s1 whitespace-nowrap text-caveat">
        ${Object.entries(DISPOSITION_EMOJI).map(([d, glyph]) =>
          `<button data-set-disp="${i}|${d}" title="${esc(d)}" class="cursor-pointer bg-transparent px-[2px] hover:opacity-70">${glyph}</button>`).join('')}
      </td>
    </tr>`;
  }).join('');

  return `
    <div class="mb-s2 flex flex-wrap items-center gap-s2 text-caveat">
      <button data-act="select-all-new" class="cursor-pointer bg-transparent text-accent-ink underline"
        >Select all new${selectableCount ? ` (${selectableCount})` : ''}</button>
      <button data-act="select-none" class="cursor-pointer bg-transparent text-ink-muted underline">Deselect all</button>
      <input data-act="filter" type="text" placeholder="Filter results…" value="${esc(view.filterText)}"
        class="rounded-sm border border-rule bg-transparent px-2 py-[2px] text-caveat text-ink">
      <span class="text-ink-muted">${visible.length} of ${view.results.length} shown${view.resultsSource ? ` · from ${esc(view.resultsSource)}` : ''}</span>
      <select data-act="group" class="ml-auto rounded-sm border border-rule bg-transparent px-2 py-[2px] text-caveat text-ink">
        <option value="">No group</option>${groupOptions}
      </select>
      <button data-act="import-selected" class="cursor-pointer rounded-sm border border-accent bg-transparent px-s3 py-[3px] text-caveat text-accent-ink" ${view.busy ? 'disabled' : ''}
        >Import Selected</button>
    </div>
    <div class="max-h-[40vh] overflow-auto rounded-sm border border-rule">
      <table class="w-full text-left">
        <thead class="sticky top-0 bg-paper text-caps uppercase tracking-caps text-ink-muted">
          <tr class="border-b border-rule">
            <th class="px-2 py-s1"></th>
            <th class="px-2 py-s1 font-normal">Name</th>
            <th class="px-2 py-s1 font-normal">Description</th>
            <th class="px-2 py-s1 font-normal">Stars</th>
            <th class="px-2 py-s1 font-normal">Language</th>
            <th class="px-2 py-s1 font-normal">License</th>
            <th class="px-2 py-s1 font-normal">Status</th>
            <th class="px-2 py-s1 font-normal">Disposition</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function setRowDisposition(el, i, disposition) {
  const r = view.results[i];
  if (!r) return;
  let reason = '';
  if (HIDDEN_DISPOSITIONS.has(disposition)) {
    reason = window.prompt(`Why ${disposition === 'abandoned' ? 'abandon' : 'ignore'} ${r.full_name}? (optional)`, '') || '';
  }
  try {
    await setDisposition(r.html_url, disposition, reason);
    r.disposition = disposition;
    r.disposition_reason = reason;
    render(el);
  } catch (err) {
    view.status = `Failed to set disposition: ${err.message}`;
    view.statusIsError = true;
    render(el);
  }
}

async function importSelected(el) {
  const groupSlug = el.querySelector('[data-act="group"]')?.value || '';
  const selected = [...view.selected].map((i) => view.results[i]).filter((r) => r && !r.already_registered);
  if (!selected.length) {
    view.status = 'No new repos selected.';
    view.statusIsError = true;
    render(el);
    return;
  }
  view.busy = true;
  render(el);
  try {
    const sourceLabel = view.mode === 'search'
      ? `search: ${view.filters.keyword || 'discover repos'}`
      : `list: ${view.resultsSource || 'from-list'}`;
    const data = await importDiscoveredRepos(selected, { groupSlug, sourceLabel });
    view.status = `Import started for ${data.queued} repo(s) — check the Activity log for progress.`
      + (data.skipped.length ? ` (${data.skipped.length} already registered, skipped.)` : '');
    view.statusIsError = false;
    view.results = [];
    view.selected.clear();
    // Import runs in a background thread (POST /api/discovery/import returns
    // as soon as it's queued), same as classic — an immediate refresh would
    // almost always race it, so give it a moment before pulling the sidebar
    // up to date. Not a full poll loop: the dialog's own status line already
    // told the user where to watch progress (the Activity log).
    if (data.queued > 0) setTimeout(() => { refreshGroupsAndSidebar(); }, 4000);
  } catch (err) {
    view.status = `Failed to start import: ${err.message}`;
    view.statusIsError = true;
  } finally {
    view.busy = false;
    render(el);
  }
}

/* ── Wiring ─────────────────────────────────────────────────────────────── */

function bind(el) {
  el.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => {
    view.mode = b.dataset.mode;
    render(el);
  }));

  el.querySelector('[data-act="search"]')?.addEventListener('click', () => runSearch(el));

  el.querySelector('[data-list-file]')?.addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const text = await file.text();
    loadFromText(el, text, file.name);
  });
  el.querySelector('[data-act="load-pasted"]')?.addEventListener('click', () => {
    const text = el.querySelector('[data-list-text]')?.value || '';
    if (!text.trim()) {
      view.listStatus = 'Paste at least one GitHub URL first.';
      view.listStatusIsError = true;
      render(el);
      return;
    }
    loadFromText(el, text, 'pasted list');
  });
  el.querySelector('[data-act="download-inventory"]')?.addEventListener('click', () => downloadInventory(el));

  el.querySelectorAll('[data-row]').forEach((cb) => cb.addEventListener('change', () => {
    const i = Number(cb.dataset.row);
    if (cb.checked) view.selected.add(i); else view.selected.delete(i);
  }));
  el.querySelector('[data-act="select-all-new"]')?.addEventListener('click', () => {
    visibleResults().forEach(({ r, i }) => {
      if (!r.already_registered && !HIDDEN_DISPOSITIONS.has(r.disposition)) view.selected.add(i);
    });
    render(el);
  });
  el.querySelector('[data-act="select-none"]')?.addEventListener('click', () => {
    view.selected.clear();
    render(el);
  });
  el.querySelector('[data-act="filter"]')?.addEventListener('input', (e) => {
    view.filterText = e.target.value;
    render(el);
    const again = el.querySelector('[data-act="filter"]');
    if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
  });
  el.querySelectorAll('[data-set-disp]').forEach((b) => b.addEventListener('click', () => {
    const [i, disposition] = b.dataset.setDisp.split('|');
    setRowDisposition(el, Number(i), disposition);
  }));
  el.querySelector('[data-act="import-selected"]')?.addEventListener('click', () => importSelected(el));
}
