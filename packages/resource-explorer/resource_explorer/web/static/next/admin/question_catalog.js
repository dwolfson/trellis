/* Admin → Question Catalog — read-only browser over every authored question.
 *
 * Full port of classic's `loadAdminQuestionCatalogPanel`. Reads GET
 * /api/analyses/question-catalog (analyses.py's `list_question_catalog`,
 * backed by `docs/dr-egeria/resource_questions.csv` via
 * `question_catalog_reader.py`) — the source of truth for both Scouting's
 * Questions checklist and the Question elements published to Egeria. This
 * screen does not write back to the CSV; classic's own comment on the route
 * says the same.
 */
import { listQuestionCatalog } from '/static/re-api.js';
import { esc } from '/static/next/app.js';

const STATUS = {
  direct: { icon: '●', tone: 'text-state-ok', label: 'Answered directly from stored data' },
  analysis: { icon: '⚙', tone: 'text-accent-ink', label: 'Answered by running an analysis' },
  human: { icon: '◐', tone: 'text-state-warn', label: 'Needs a human answer' },
  mixed: { icon: '◑', tone: 'text-accent-ink', label: 'Mixed — some automatic, some human' },
  gap: { icon: '○', tone: 'text-ink-muted', label: 'No surveyor answers this yet' },
  chart: { icon: '📈', tone: 'text-accent-ink', label: 'Answered by a chart' },
};

function statusOf(kind) {
  return STATUS[kind] || { icon: '?', tone: 'text-ink-muted', label: kind || 'unclassified' };
}

let _data = null;
let _host = null;
const state = { stage: '', perspectives: new Set(), search: '' };

function stages() {
  const set = new Set();
  (_data || []).forEach((q) => set.add(q.stage));
  return [...set].filter(Boolean).sort();
}

function perspectives() {
  const set = new Set();
  (_data || []).forEach((q) => (q.perspectives || []).forEach((p) => set.add(p)));
  return [...set].sort();
}

function render() {
  if (!_host) return;
  const search = state.search.trim().toLowerCase();
  const questions = (_data || []).filter((q) => {
    if (state.stage && !q.stage.split('/').map((s) => s.trim()).includes(state.stage)) return false;
    if (state.perspectives.size && !(q.perspectives || []).some((p) => state.perspectives.has(p))) return false;
    if (search && !q.question.toLowerCase().includes(search)) return false;
    return true;
  });

  const stageChips = stages().map((s) => `<button type="button" data-stage="${esc(s)}"
    class="cursor-pointer rounded-sm border px-2 py-[2px] text-caveat
      ${s === state.stage ? 'border-accent text-accent-ink' : 'border-rule-strong text-ink-muted hover:text-ink'}"
    >${esc(s)}</button>`).join('');

  const perspChips = perspectives().map((p) => `<button type="button" data-persp="${esc(p)}"
    class="cursor-pointer rounded-full border px-2 py-[1px] text-provenance
      ${state.perspectives.has(p) ? 'border-accent text-accent-ink' : 'border-rule-strong text-ink-muted hover:text-ink'}"
    >${esc(p)}</button>`).join('');

  const rows = questions.map((q) => {
    const st = statusOf(q.answering.kind);
    return `<tr class="border-b border-rule align-top hover:bg-paper-surface">
      <td class="max-w-[36ch] py-s2 pr-s3 text-caveat text-ink">${esc(q.question)}</td>
      <td class="whitespace-nowrap py-s2 pr-s3 text-provenance text-ink-muted" title="Funnel stage">${esc(q.stage)}</td>
      <td class="py-s2 pr-s3 text-provenance text-ink-muted">${(q.perspectives || []).map((p) => esc(p)).join(' · ') || '—'}</td>
      <td class="whitespace-nowrap py-s2 pr-s3 text-caveat ${st.tone}" title="${esc(st.label)}">${st.icon} ${esc(q.answering.kind)}</td>
      <td class="whitespace-nowrap py-s2 pr-s3 text-provenance text-ink-muted">${esc(q.answering_mechanism || '—')}</td>
      <td class="max-w-[40ch] py-s2 text-provenance text-ink-muted" title="${esc(q.answering.note || '')}">${esc(q.answering.note || '')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="6" class="py-s4 text-center text-caveat text-ink-muted">No questions match this filter.</td></tr>`;

  _host.innerHTML = `
    <h3 class="m-0 font-heading text-name font-normal text-ink">❓ Question Catalog</h3>
    <p class="mt-[2px] max-w-[65ch] text-caveat text-ink-muted">Read-only view of every question
      authored in <code>docs/dr-egeria/resource_questions.csv</code> — the source of truth for both
      Scouting's Questions checklist and the Question elements published to Egeria. To add, edit or
      remove a question, edit that CSV and regenerate. This screen does not write back to it.</p>
    <div class="my-s3 space-y-s2">
      <input data-search value="${esc(state.search)}" placeholder="Search question text…"
        class="w-full max-w-[360px] rounded-sm border border-rule-strong bg-transparent px-2 py-[3px] text-caveat text-ink" />
      <div>
        <div class="text-caps uppercase tracking-caps text-ink-muted">Stage</div>
        <div class="mt-[4px] flex flex-wrap gap-[6px]">${stageChips || '<span class="text-caveat text-ink-muted">—</span>'}</div>
      </div>
      ${perspectives().length ? `<div>
        <div class="text-caps uppercase tracking-caps text-ink-muted">Perspective (filter)</div>
        <div class="mt-[4px] flex flex-wrap gap-[6px]">${perspChips}</div>
      </div>` : ''}
    </div>
    <div class="mb-s2 text-provenance text-ink-muted">${questions.length} / ${(_data || []).length} question(s)</div>
    <div class="max-h-[46vh] overflow-auto rounded-sm border border-rule">
      <table class="w-full text-left">
        <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
          <th class="px-s2 py-s2 font-normal">Question</th>
          <th class="px-s2 py-s2 font-normal">Stage</th>
          <th class="px-s2 py-s2 font-normal">Perspectives</th>
          <th class="px-s2 py-s2 font-normal">Kind</th>
          <th class="px-s2 py-s2 font-normal">Mechanism</th>
          <th class="px-s2 py-s2 font-normal">Note</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  bind();
}

function bind() {
  if (!_host) return;
  const search = _host.querySelector('[data-search]');
  if (search) search.addEventListener('input', (e) => { state.search = e.target.value; render(); });
  _host.querySelectorAll('[data-stage]').forEach((b) => b.addEventListener('click', () => {
    state.stage = state.stage === b.dataset.stage ? '' : b.dataset.stage;
    render();
  }));
  _host.querySelectorAll('[data-persp]').forEach((b) => b.addEventListener('click', () => {
    if (state.perspectives.has(b.dataset.persp)) state.perspectives.delete(b.dataset.persp);
    else state.perspectives.add(b.dataset.persp);
    render();
  }));
}

export async function renderQuestionCatalog(host) {
  _host = host;
  state.stage = '';
  state.perspectives = new Set();
  state.search = '';
  _data = await listQuestionCatalog('repo');
  render();
}
