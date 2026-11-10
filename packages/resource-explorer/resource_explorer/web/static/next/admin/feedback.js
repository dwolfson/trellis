/* Admin → Feedback — both feedback stores, badged by origin.
 *
 * Full port of classic's `loadAdminFeedbackPanel` against the same GET
 * /api/curate/feedback (see curate.py's `list_all_feedback` — it already
 * combines resource_feedback and the page-level `feedback` table, each row
 * carrying `source: "page" | "resource"`, precisely because a 2026-09-01
 * incident found a page-level submission rendering as "no feedback" when the
 * pane simply never read that store).
 *
 * The route is admin-gated (`_require_admin` in curate.py, matching
 * routes/feedback.py's `X-Admin-Token` check) because it can surface contact
 * fields on the resource side. This module reproduces classic's gate exactly
 * — same sessionStorage key (`re_admin_token`), same header — rather than
 * inventing a second mechanism: entering the token in either surface
 * authenticates both. This is NOT routed through re-api.js's `request()`,
 * because a 403 here is a distinct, expected state (not authenticated yet)
 * that must render its own explanation rather than the generic ApiError
 * path — an unauthenticated view and a genuinely empty store must not look
 * alike.
 */
import { esc } from '/static/next/app.js';

const TOKEN_KEY = 're_admin_token';

const filter = { entity_type: '', category: '', source: '', status: '' };
let _host = null;

function authHeaders() {
  const t = sessionStorage.getItem(TOKEN_KEY) || '';
  return t ? { 'X-Admin-Token': t } : {};
}

function ratingHtml(r) {
  if (r === null || r === undefined) {
    return '<span class="text-ink-muted" title="No rating given">—</span>';
  }
  return `<span class="text-state-warn">${'★'.repeat(r)}<span class="text-ink-muted">${'★'.repeat(Math.max(0, 5 - r))}</span></span>`;
}

function sourceBadge(source) {
  if (source === 'answer') {
    return '<span class="rounded-sm border border-state-warn px-[6px] py-[1px] text-provenance text-ink" title="A rating of one answer: a chat vote, or a Questions-checklist verdict. Kept with the question, the answer and who rated it">answer</span>';
  }
  return source === 'page'
    ? '<span class="rounded-sm border border-rule-strong px-[6px] py-[1px] text-provenance text-ink" title="feedback table — the page-level widget, reachable from anywhere in the app">page</span>'
    : '<span class="rounded-sm border border-accent-deep px-[6px] py-[1px] text-provenance text-accent-ink" title="resource_feedback table — recorded from a resource\'s Curate tab">resource</span>';
}

/** +1 / 0 / -1, as the thumbs the person pressed said it. */
const VOTE_WORDS = { 1: 'helpful', 0: 'partly right', '-1': 'not helpful' };

/** An answer row's message cell: the vote, the question, any comment, and the answer folded away (it can be long). */
function answerMessageHtml(r) {
  const who = r.user_id ? ` · ${esc(r.user_id)}` : ' · anonymous';
  // A turn that was not stored (or too far back) keeps the text the browser sent, not the stored exchange.
  const sent = r.extra?.text_from === 'client'
    ? ' · <span class="text-state-warn" title="This question and answer are what the browser sent with the vote, not read from the stored chat exchange">text as sent</span>'
    : '';
  const answer = r.response_text
    ? `<details class="mt-[2px]"><summary class="cursor-pointer text-provenance text-ink-muted">answer</summary>
        <div class="mt-[2px] max-h-[12rem] overflow-auto whitespace-pre-wrap text-provenance text-ink-muted">${esc(r.response_text)}</div></details>`
    : '';
  return `<div><span class="text-ink">${esc(VOTE_WORDS[String(r.vote)] || String(r.vote))}</span>${who}${sent}</div>
    <div class="text-ink">Q: ${esc(r.query_text || '')}</div>
    ${r.message ? `<div class="text-ink-muted">${esc(r.message)}</div>` : ''}${answer}`;
}

function tokenGateHtml() {
  return `
    <h3 class="m-0 font-heading text-name font-normal text-ink">Admin credential required</h3>
    <div class="my-s3 h-px bg-rule"></div>
    <p class="max-w-[60ch] text-answer text-ink">This view reads submitted feedback, which can
      include contact details, so it is gated. <strong>This is not an empty list</strong> — it is
      a view you are not yet authenticated for.</p>
    <div class="mt-s3 flex max-w-[420px] gap-s2">
      <input data-token-input type="password" placeholder="Admin token"
        class="flex-1 rounded-sm border border-rule-strong bg-transparent px-2 py-[3px] text-caveat text-ink" />
      <button type="button" data-token-connect
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[3px] text-caveat text-accent-ink">Connect</button>
    </div>
    <p class="mt-s2 max-w-[60ch] text-provenance text-ink-muted">Held in sessionStorage for this
      tab only, and shared with <code>/admin/feedback</code> and the current UI's Admin → Feedback.</p>`;
}

function chip(label, key, value) {
  const active = filter[key] === value;
  return `<button type="button" data-filter-key="${esc(key)}" data-filter-val="${esc(value)}"
    class="cursor-pointer rounded-sm border px-2 py-[2px] text-caveat
      ${active ? 'border-accent text-accent-ink' : 'border-rule-strong text-ink-muted hover:text-ink'}"
    >${esc(label)}</button>`;
}

/** Status words as an admin reads them. The vocabulary itself comes from the server (`data.statuses`). */
const STATUS_WORDS = {
  new: 'new', triaged: 'triaged', known_issue: 'known issue', actioned: 'actioned',
  deferred: 'deferred', not_an_issue: 'not an issue',
};
const statusWord = (s) => STATUS_WORDS[s] || s;

/** The triage cell of a page or answer item: its status and who set it, a status control with a note, and its
 *  history on demand. Every change is a new event in trellis-feedback (append-only): the note belongs to that
 *  change and nothing earlier is overwritten. */
function triageHtml(r, statuses) {
  const t = r.triage || {};
  const current = r.triage_status || t.status || 'new';
  const by = t.actor ? ` · ${esc(t.actor)}` : '';
  const when = t.updated_at ? ` · ${esc(t.updated_at.slice(0, 16).replace('T', ' '))}` : '';
  const last = t.note ? `<div class="max-w-[28ch] whitespace-normal text-provenance text-ink-muted">“${esc(t.note)}”</div>` : '';
  const options = statuses.map((s) => `<option value="${esc(s)}"${s === current ? ' selected' : ''}>${esc(statusWord(s))}</option>`).join('');
  return `<div data-triage="${esc(r.id)}">
    <div><span class="text-ink">${esc(statusWord(current))}</span><span class="text-provenance text-ink-muted">${by}${when}</span></div>
    ${last}
    <div class="mt-[2px] flex flex-wrap items-center gap-[6px]">
      <select data-triage-status aria-label="Status" class="rounded-sm border border-rule-strong bg-transparent px-[6px] py-[1px] text-caveat text-ink">${options}</select>
      <input data-triage-note type="text" placeholder="Note (optional)" aria-label="Note"
        class="w-[16ch] rounded-sm border border-rule-strong bg-transparent px-[6px] py-[1px] text-caveat text-ink" />
      <button type="button" data-triage-save
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[1px] text-caveat text-accent-ink">Save</button>
    </div>
    <div data-triage-error class="text-provenance text-state-warn"></div>
    ${t.events ? `<details data-triage-history class="mt-[2px]"><summary class="cursor-pointer text-provenance text-ink-muted">history (${esc(String(t.events))})</summary><div data-history-body class="text-provenance text-ink-muted">Loading…</div></details>` : ''}
  </div>`;
}

const LOOK_NAMES = [['dark', 'Dark'], ['light', 'Light'], ['paper', 'Paper']];

/** Which look people use, from the activity rows each change writes (RULING-THEMES-PORTAL-DARK-LIGHT.md section 1).
 *  Says what the numbers cannot know: someone who never touched the control is on Dark and leaves no row. A fetch
 *  that fails is said to have failed, not shown as zeros. */
async function lookCountsHtml() {
  let data;
  try {
    const res = await fetch('/api/feedback/look-counts', { headers: authHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    return `<p class="mt-s3 text-caveat text-state-warn" data-look-counts-error>Could not load the look counts: ${esc(err.message)}</p>`;
  }
  const rows = LOOK_NAMES.map(([id, name]) => {
    const c = (data.looks || {})[id] || { people: 0, switched_away: 0 };
    return `<tr class="border-b border-rule" data-look-row="${id}">
      <td class="py-[3px] pr-s4 text-ink">${name}</td>
      <td class="tnum py-[3px] pr-s4 text-ink">${c.people}</td>
      <td class="tnum py-[3px] text-ink">${c.switched_away}</td></tr>`;
  }).join('');
  return `<div class="mt-s3" data-look-counts>
    <h4 class="m-0 mb-[2px] font-heading text-subtab font-normal text-ink">Which look people use</h4>
    <table class="text-caveat"><thead><tr class="text-caps uppercase tracking-caps text-ink-muted">
      <th class="pr-s4 text-left font-normal">Look</th>
      <th class="pr-s4 text-left font-normal">People on it now</th>
      <th class="text-left font-normal">Switched away from it</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <p class="mt-[2px] max-w-[65ch] text-provenance text-ink-muted">Counts people who have changed the look at least once
      (<span class="tnum">${data.people_who_changed || 0}</span> people, <span class="tnum">${data.changes || 0}</span> changes).
      Anyone who never touched the control is on Dark and leaves no row, so Dark's number is a floor, not a total.
      Comments sent from the look menu are in the list below, subject "Look: ...".</p></div>`;
}

async function reload() {
  if (!_host) return;
  const params = new URLSearchParams();
  if (filter.entity_type) params.set('entity_type', filter.entity_type);
  if (filter.category) params.set('category', filter.category);
  if (filter.source) params.set('source', filter.source);
  if (filter.status) params.set('status', filter.status);

  let res;
  try {
    res = await fetch(`/api/curate/feedback?${params}`, { headers: authHeaders() });
  } catch (err) {
    _host.innerHTML = `<p class="max-w-[70ch] text-answer text-state-warn">Could not load feedback: ${esc(err.message)}</p>`;
    return;
  }
  if (res.status === 403) {
    _host.innerHTML = tokenGateHtml();
    bindTokenGate();
    return;
  }
  if (!res.ok) {
    _host.innerHTML = `<p class="max-w-[70ch] text-answer text-state-warn">Could not load feedback: HTTP ${res.status}</p>`;
    return;
  }
  const data = await res.json();

  const rows = data.feedback || [];
  const counts = data.counts || { resource: { total: 0, resources: 0 }, page: { total: 0 } };
  const total = (counts.resource?.total || 0) + (counts.page?.total || 0) + (counts.answer?.total || 0);
  const types = [...new Set(rows.filter((r) => r.source !== 'page').map((r) => r.entity_type).filter(Boolean))].sort();
  const cats = [...new Set(rows.map((r) => r.category).filter(Boolean))].sort();
  const statuses = data.statuses || ['new'];

  let empty;
  if (data.filtered) {
    empty = `<p class="py-s4 text-center text-caveat text-ink-muted">No feedback matches this filter.
      Clear it to see all ${total} (${counts.page?.total || 0} page, ${counts.resource?.total || 0} resource, ${counts.answer?.total || 0} answer).</p>`;
  } else if (total === 0) {
    empty = `<p class="py-s4 text-center text-caveat text-ink-muted">No feedback has been left anywhere yet.<br>
      <span class="text-ink-muted">No page-level widget report, no resource's Curate tab row, and no rated answer.</span></p>`;
  } else {
    empty = '<p class="py-s4 text-center text-caveat text-ink-muted">Nothing rendered for this page, though feedback exists — try Refresh.</p>';
  }

  const body = rows.length ? `<table class="w-full text-left">
    <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
      <th class="pb-s2 pr-s3 font-normal">When</th>
      <th class="pb-s2 pr-s3 font-normal">Source</th>
      <th class="pb-s2 pr-s3 font-normal">Resource / Page</th>
      <th class="pb-s2 pr-s3 font-normal">Category</th>
      <th class="pb-s2 pr-s3 font-normal">Rating</th>
      <th class="pb-s2 pr-s3 font-normal">Message</th>
      <th class="pb-s2 font-normal">Status</th>
    </tr></thead>
    <tbody>${rows.map((r) => {
      const isPage = r.source === 'page';
      const isAnswer = r.source === 'answer';
      let context;
      if (isAnswer) {
        context = r.slug
          ? `<span class="text-ink-muted">${esc(r.entity_type || '')}</span> <span class="font-mono text-ink">${esc(r.slug)}</span>`
          : '<span class="text-ink-muted" title="No resource was in scope when this answer was rated">no resource</span>';
      } else {
        context = isPage
          ? (r.page ? `<span class="font-mono text-ink">${esc(r.page)}</span>` : '<span class="text-ink-muted" title="No page recorded with this submission">—</span>')
          : `<span class="text-ink-muted">${esc(r.entity_type || '')}</span> <span class="font-mono text-ink">${esc(r.entity_slug || '')}</span>`;
      }
      const status = (isPage || isAnswer)
        ? triageHtml(r, statuses)
        : '<span class="italic text-ink-muted" title="resource_feedback has no triage workflow yet">n/a</span>';
      return `<tr class="border-b border-rule hover:bg-paper-surface">
        <td class="whitespace-nowrap py-s2 pr-s3 font-mono text-provenance text-ink-muted">${esc((r.created_at || '').slice(0, 16).replace('T', ' '))}</td>
        <td class="whitespace-nowrap py-s2 pr-s3">${sourceBadge(r.source)}</td>
        <td class="whitespace-nowrap py-s2 pr-s3">${context}</td>
        <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc(r.category || '—')}</td>
        <td class="whitespace-nowrap py-s2 pr-s3">${ratingHtml(r.rating)}</td>
        <td class="max-w-[32ch] py-s2 pr-s3 text-caveat text-ink">${isAnswer ? answerMessageHtml(r) : esc(r.message || '')}</td>
        <td class="whitespace-nowrap py-s2 align-top text-caveat">${status}</td>
      </tr>`;
    }).join('')}</tbody></table>` : empty;

  _host.innerHTML = `
    <h3 class="m-0 font-heading text-name font-normal text-ink">💬 Feedback</h3>
    <p class="mt-[2px] max-w-[65ch] text-caveat text-ink-muted">
      ${counts.page?.total || 0} page item${(counts.page?.total || 0) === 1 ? '' : 's'} (the widget on
      any page) + ${counts.resource?.total || 0} resource item${(counts.resource?.total || 0) === 1 ? '' : 's'}
      across ${counts.resource?.resources || 0} resource${(counts.resource?.resources || 0) === 1 ? '' : 's'}
      (a resource's Curate tab) + ${counts.answer?.total || 0} rated answer${(counts.answer?.total || 0) === 1 ? '' : 's'}
      (chat votes and checklist verdicts) = ${total} total. Shown together, badged by origin — not merged.
      Checklist verdicts left before 2026-11-09 are page items whose message starts "[agree]", "[partly]" or "[disagree]".
    </p>
    ${await lookCountsHtml()}
    <div class="my-s3 flex flex-wrap items-center gap-[6px]">
      ${chip('All sources', 'source', '')}
      ${chip('Page', 'source', 'page')}
      ${chip('Resource', 'source', 'resource')}
      ${chip('Answer', 'source', 'answer')}
      <span class="px-[2px] text-ink-muted">|</span>
      ${chip('All resource types', 'entity_type', '')}
      ${types.map((t) => chip(t, 'entity_type', t)).join('')}
      ${cats.length ? '<span class="px-[2px] text-ink-muted">|</span>' : ''}
      ${cats.length ? chip('Any category', 'category', '') : ''}
      ${cats.map((c) => chip(c, 'category', c)).join('')}
    </div>
    <div class="mb-s3 flex flex-wrap items-center gap-[6px]">
      ${chip('Any status', 'status', '')}
      ${statuses.map((s) => chip(statusWord(s), 'status', s)).join('')}
      ${filter.status ? '<span class="text-provenance text-ink-muted">Resource feedback has no status yet, so a status filter shows page and answer items only.</span>' : ''}
    </div>
    <div class="max-h-[46vh] overflow-auto rounded-sm border border-rule">${body}</div>`;

  bindFilters();
  bindTriage();
}

/** Save one status change: PATCH /api/feedback/{id} with the status and note, then reload so the row, its counts
 *  and any active status filter all agree with the store. A refusal is said on the row, not swallowed. */
function bindTriage() {
  if (!_host) return;
  _host.querySelectorAll('[data-triage]').forEach((cell) => {
    const id = cell.dataset.triage;
    const error = cell.querySelector('[data-triage-error]');
    cell.querySelector('[data-triage-save]')?.addEventListener('click', async (e) => {
      const button = e.currentTarget;
      const triageStatus = cell.querySelector('[data-triage-status]').value;
      const note = cell.querySelector('[data-triage-note]').value.trim();
      button.disabled = true;
      error.textContent = '';
      let res;
      try {
        res = await fetch(`/api/feedback/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ triage_status: triageStatus, note }),
        });
      } catch (err) {
        error.textContent = `Not saved: ${err.message}`;
        button.disabled = false;
        return;
      }
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
        error.textContent = `Not saved: ${detail}`;
        button.disabled = false;
        return;
      }
      reload();
    });
    cell.querySelector('[data-triage-history]')?.addEventListener('toggle', async (e) => {
      const box = e.currentTarget;
      if (!box.open || box.dataset.loaded) return;
      const body = box.querySelector('[data-history-body]');
      try {
        const res = await fetch(`/api/feedback/${encodeURIComponent(id)}`, { headers: authHeaders() });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const item = await res.json();
        box.dataset.loaded = '1';
        body.innerHTML = (item.history || []).map((ev) => `<div>${esc((ev.created_at || '').slice(0, 16).replace('T', ' '))}
          · <span class="text-ink">${esc(statusWord(ev.status))}</span>${ev.actor ? ` · ${esc(ev.actor)}` : ''}${
          ev.note ? ` — ${esc(ev.note)}` : ''}</div>`).join('') || 'No changes recorded.';
      } catch (err) {
        body.textContent = `Could not load the history: ${err.message}`;
      }
    });
  });
}

function bindFilters() {
  if (!_host) return;
  _host.querySelectorAll('[data-filter-key]').forEach((b) => b.addEventListener('click', () => {
    // Setting entity_type has no meaning for page-sourced rows; clearing an
    // active page-only source filter here would silently show rows that
    // don't support the entity_type facet — leave source alone and let the
    // empty state say so, same as classic.
    filter[b.dataset.filterKey] = b.dataset.filterVal;
    reload();
  }));
}

function bindTokenGate() {
  if (!_host) return;
  const connect = _host.querySelector('[data-token-connect]');
  const input = _host.querySelector('[data-token-input]');
  if (!connect || !input) return;
  const submit = () => {
    const t = input.value.trim();
    if (!t) return;
    sessionStorage.setItem(TOKEN_KEY, t);
    reload();
  };
  connect.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
}

export async function renderFeedback(host) {
  _host = host;
  filter.entity_type = '';
  filter.category = '';
  filter.source = '';
  filter.status = '';
  await reload();
}
