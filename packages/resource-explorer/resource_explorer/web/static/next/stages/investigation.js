/* Investigation — the frame, not a stage.
 *
 * docs/investigation-framing-design.md §1: Investigation sits ABOVE the
 * eight canonical intents. It answers "why does this body of work exist",
 * not "what kind of work is happening" — that is why `STAGES` in app.js
 * marks it `class: 'frame'` rather than `run`/`cross-cutting`, and why this
 * pane bypasses the generic Questions-checklist engine entirely, the same
 * shape as Understanding (charts) and Automate (subscriptions/schedules):
 * `loadPane()` calls `renderInvestigation()` directly for
 * `state.stage === 'investigation'` and returns.
 *
 * This used to be a 17-line honest placeholder pointing at classic's
 * `index.html` as the only live implementation. It is now a real, in-place
 * port of that implementation against the same `/api/investigations/*`
 * surface (`web/routes/investigations.py`) — list/create, per-investigation
 * detail (members across resource types, per-member disposition,
 * next-steps, purposes, classification), and the Egeria bind/promote/sync/
 * reclassify flow. It does NOT duplicate the sidebar's own "current
 * investigation" selector (app.js's `investigationBarHtml()`/
 * `setInvestigation()`) — that stays the chrome-level scoping control; this
 * pane is where an investigation itself is managed (created, described,
 * classified, bound to Egeria, closed), the two working together the same
 * way classic's nav-level Investigations tab and its per-repo "add to
 * investigation" toggle always have.
 */
import { ago } from '/static/next/format.js';
import {
  listInvestigations, getInvestigationPurposes, getInvestigationClassifications,
  getInvestigation, createInvestigation, updateInvestigation,
  listInvestigationMembers, addInvestigationMember, removeInvestigationMember,
  closeInvestigation, suspendInvestigation, reopenInvestigation,
  bindInvestigationEgeriaProject, promoteInvestigation, reclassifyInvestigation,
  relinkInvestigationMembers, syncInvestigationEgeria,
  getInvestigationDispositions, setInvestigationDisposition, getInvestigationNextSteps,
} from '/static/re-api.js';
import {
  state, esc, $, icon, setInvestigation, refreshInvestigationsAndSidebar,
} from '/static/next/app.js';
import { openDialog, closeCellDetail } from '/static/next/worklist.js';

// Module-local view state — which investigation (if any) is open, and
// whether the list includes closed ones. Not on `state`: nothing outside
// this pane reads it, same reasoning as automate.js's `_tab`.
let _detailSlug = null;
let _includeClosed = false;

// Vocabularies are server-served (registry.py's PROJECT_CLASSIFICATIONS /
// VALID_PURPOSES / dispositions) and cached here for the life of the page —
// they change when someone edits Python, not per click.
let _purposes = null;
let _classifications = null;

const DISPOSITION_GLYPH = {
  tracking: '👁', investigating: '🔬', recommended: '👍',
  using: '✅', abandoned: '🪦', ignored: '🚫',
};

async function vocab() {
  if (!_purposes) {
    try { _purposes = (await getInvestigationPurposes()).purposes || []; } catch { _purposes = []; }
  }
  if (!_classifications) {
    try { _classifications = await getInvestigationClassifications(); } catch {
      _classifications = { classifications: [], bindings: [], default_classification: 'StudyProject', default_binding: 'egeria' };
    }
  }
  return { purposes: _purposes, classifications: _classifications };
}

export async function renderInvestigation() {
  if (_detailSlug) return renderDetail(_detailSlug);
  return renderList();
}

/** Called from app.js's resource header ("Open Investigation →", the /next
 *  equivalent of classic's index.html link at ~line 5779) so navigating
 *  into the Investigation frame lands on the resource's current
 *  investigation, not the bare list. */
export function openInvestigationDetail(slug) {
  _detailSlug = slug;
}

/* ── List ─────────────────────────────────────────────────────────────── */

function statusGlyph(status) {
  if (status === 'closed') return '<span class="text-ink-muted" title="closed">● closed</span>';
  if (status === 'suspended') return '<span class="text-state-warn" title="suspended">◐ suspended</span>';
  return '<span class="text-state-ok" title="open">○ open</span>';
}

function bindingGlyph(inv) {
  // `egeria_context` (registry.py get_investigation()) is a small object,
  // not a display string — {status, egeria_project_guid,
  // egeria_project_qualified_name, free_text_name}. Use the qualified name
  // straight off the row, same as the detail view does.
  return inv.egeria_project_guid
    ? `<span title="${esc(inv.egeria_project_qualified_name || 'bound to an Egeria Project')}">☁ Egeria</span>`
    : '<span class="text-ink-muted" title="no Egeria Project">🏠 local</span>';
}

async function renderList() {
  const el = $('content');
  el.innerHTML = listHeaderHtml() + '<p class="text-answer text-ink-muted">Loading…</p>';
  bindListHeader();

  let rows;
  try {
    rows = await listInvestigations({ includeClosed: _includeClosed });
  } catch (err) {
    el.innerHTML = listHeaderHtml()
      + `<p class="max-w-[70ch] text-answer text-state-warn">Could not load investigations: ${esc(err.message)}</p>`;
    bindListHeader();
    return;
  }

  const body = rows.length ? `<table class="w-full text-left">
      <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
        <th class="pb-s2 pr-s3 font-normal">Investigation</th>
        <th class="pb-s2 pr-s3 font-normal">Purposes</th>
        <th class="pb-s2 pr-s3 font-normal">Status</th>
        <th class="pb-s2 pr-s3 font-normal">Members</th>
        <th class="pb-s2 font-normal">Egeria</th>
      </tr></thead>
      <tbody>${rows.map((inv) => `
        <tr class="cursor-pointer border-b border-rule hover:bg-paper-alt" data-open-inv="${esc(inv.slug)}">
          <td class="py-s2 pr-s3 text-answer text-ink">
            ${inv.slug === state.investigation ? '<span title="current investigation">★ </span>' : ''}
            ${esc(inv.display_name || inv.slug)}
            ${inv.visibility === 'private' ? `<span class="ml-[4px] text-caveat text-ink-muted" title="${esc(inv.visibility_note || 'visible only to its creator')}">🔒</span>` : ''}
          </td>
          <td class="py-s2 pr-s3 text-caveat text-ink-muted">${(inv.purposes || []).map(esc).join(', ') || '—'}</td>
          <td class="py-s2 pr-s3 text-caveat">${statusGlyph(inv.status)}</td>
          <td class="py-s2 pr-s3 text-caveat tnum text-ink-muted">${inv.member_count ?? 0}</td>
          <td class="py-s2 text-caveat">${bindingGlyph(inv)}</td>
        </tr>`).join('')}
      </tbody>
    </table>` : '<p class="text-answer text-ink-muted">No investigations yet — create one to start scoping a body of work.</p>';

  el.innerHTML = listHeaderHtml() + body;
  bindListHeader();
  el.querySelectorAll('[data-open-inv]').forEach((tr) => tr.addEventListener('click', () => {
    _detailSlug = tr.dataset.openInv;
    renderInvestigation();
  }));
}

function listHeaderHtml() {
  return `<div class="mb-s3 flex items-center gap-s3">
      <h3 class="m-0 font-heading text-name font-normal text-ink">Investigations</h3>
      <label class="ml-s2 inline-flex cursor-pointer items-center gap-[5px] text-caveat text-ink-muted">
        <input type="checkbox" id="inv-include-closed" ${_includeClosed ? 'checked' : ''}>
        Show closed
      </label>
      <button data-act="inv-new" type="button"
        class="ml-auto cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px]
               text-caveat text-accent-ink">+ New investigation</button>
    </div>
    <p class="max-w-[70ch] text-caveat text-ink-muted">
      An investigation is the frame a body of work runs inside — why it exists, not what kind of
      work it is. Resources can belong to several at once; closing one keeps its findings queryable,
      it just drops out of the default scope.
    </p>
    <div class="my-s3 h-px bg-rule"></div>`;
}

function bindListHeader() {
  const el = $('content');
  el.querySelector('#inv-include-closed')?.addEventListener('change', (e) => {
    _includeClosed = e.target.checked;
    renderList();
  });
  el.querySelector('[data-act="inv-new"]')?.addEventListener('click', openCreateDialog);
}

/* ── Create ───────────────────────────────────────────────────────────── */

async function openCreateDialog() {
  const { purposes, classifications } = await vocab();
  const d = openDialog('New investigation', '');
  const body = d.querySelector('#wl-detail-body');
  body.innerHTML = `
    <label class="mb-[3px] block text-caveat text-ink-muted">Name</label>
    <input id="inv-new-name" type="text" class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-answer text-ink">
    <label class="mb-[3px] block text-caveat text-ink-muted">Description</label>
    <textarea id="inv-new-desc" rows="2" class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink"></textarea>
    <label class="mb-[3px] block text-caveat text-ink-muted">Purposes</label>
    <div class="mb-s2 flex flex-wrap gap-s2">
      ${purposes.map((p) => `<label class="inline-flex cursor-pointer items-center gap-[4px] text-caveat text-ink">
        <input type="checkbox" class="inv-new-purpose" value="${esc(p)}"> ${esc(p)}</label>`).join('')}
    </div>
    <label class="mb-[3px] block text-caveat text-ink-muted">Kind</label>
    <select id="inv-new-class" class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
      ${classifications.classifications.map((c) => `<option value="${esc(c.name)}" ${
        c.name === classifications.default_classification ? 'selected' : ''}>${esc(c.label || c.name)}</option>`).join('')}
    </select>
    <div id="inv-new-hyp-wrap" class="mb-s2 hidden">
      <label class="mb-[3px] block text-caveat text-ink-muted">Hypothesis (required for Experiment)</label>
      <input id="inv-new-hyp" type="text" class="w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
    </div>
    <label class="mb-[3px] block text-caveat text-ink-muted">Where it lives</label>
    <select id="inv-new-binding" class="mb-s3 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
      ${classifications.bindings.map((b) => `<option value="${esc(b.name)}" ${
        b.name === classifications.default_binding ? 'selected' : ''}>${esc(b.label || b.name)}</option>`).join('')}
    </select>
    <div id="inv-new-error" class="mb-s2 text-caveat text-state-warn"></div>
    <div class="flex gap-s2">
      <button id="inv-new-submit" type="button"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-caveat text-accent-ink">Create</button>
      <button data-act="close" type="button" class="cursor-pointer bg-transparent text-caveat text-ink-muted underline">Cancel</button>
    </div>`;

  const classSel = body.querySelector('#inv-new-class');
  const hypWrap = body.querySelector('#inv-new-hyp-wrap');
  const requiresHyp = (name) => classifications.classifications.find((c) => c.name === name)?.requires_hypothesis;
  const syncHyp = () => {
    const need = requiresHyp(classSel.value);
    hypWrap.classList.toggle('hidden', !need);
    // Cleared, not hidden-but-still-posted — HYPOTHESIS_REQUIRED_FOR is about
    // Experiment specifically, and a stale value from switching kinds back
    // and forth must not silently ride along on a non-Experiment create.
    if (!need) body.querySelector('#inv-new-hyp').value = '';
  };
  classSel.addEventListener('change', syncHyp);
  syncHyp();

  body.querySelector('#inv-new-submit').addEventListener('click', async () => {
    const name = body.querySelector('#inv-new-name').value.trim();
    const errEl = body.querySelector('#inv-new-error');
    if (!name) { errEl.textContent = 'Name is required.'; return; }
    const selectedPurposes = [...body.querySelectorAll('.inv-new-purpose:checked')].map((c) => c.value);
    const projectClassification = classSel.value;
    const hypothesis = body.querySelector('#inv-new-hyp').value.trim();
    if (requiresHyp(projectClassification) && !hypothesis) {
      errEl.textContent = 'This kind requires a hypothesis.';
      return;
    }
    const btn = body.querySelector('#inv-new-submit');
    btn.disabled = true;
    btn.textContent = 'Creating…';
    try {
      const inv = await createInvestigation({
        displayName: name,
        description: body.querySelector('#inv-new-desc').value.trim(),
        purposes: selectedPurposes,
        projectClassification,
        egeriaBinding: body.querySelector('#inv-new-binding').value,
        hypothesis,
      });
      closeCellDetail();
      await refreshInvestigationsAndSidebar();
      _detailSlug = inv.slug;
      await renderInvestigation();
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Create';
      errEl.textContent = err.message;
    }
  });
}

/* ── Detail ───────────────────────────────────────────────────────────── */

function detailHeaderHtml(inv) {
  return `<div class="mb-s3 flex items-center gap-s3">
      <button data-act="inv-back" type="button"
        class="cursor-pointer bg-transparent text-caveat text-accent-ink underline">← Investigations</button>
      <h3 class="m-0 font-heading text-name font-normal text-ink">${esc(inv.display_name || inv.slug)}</h3>
      ${statusGlyph(inv.status)}
    </div>`;
}

async function renderDetail(slug) {
  const el = $('content');
  el.innerHTML = `<p class="text-answer text-ink-muted">Loading…</p>`;

  let inv, members, dispositions, nextSteps;
  try {
    [inv, members, dispositions, nextSteps] = await Promise.all([
      getInvestigation(slug),
      listInvestigationMembers(slug),
      getInvestigationDispositions(slug),
      getInvestigationNextSteps(slug),
    ]);
  } catch (err) {
    el.innerHTML = `<button data-act="inv-back" type="button"
        class="mb-s3 cursor-pointer bg-transparent text-caveat text-accent-ink underline">← Investigations</button>
      <p class="max-w-[70ch] text-answer text-state-warn">Could not load '${esc(slug)}': ${esc(err.message)}</p>`;
    el.querySelector('[data-act="inv-back"]').addEventListener('click', () => { _detailSlug = null; renderInvestigation(); });
    return;
  }

  const { classifications } = await vocab();
  const classLabel = classifications.classifications.find((c) => c.name === inv.project_classification)?.label
    || inv.project_classification;

  const isCurrent = inv.slug === state.investigation;
  const lifecycleButtons = inv.status === 'open'
    ? `<button data-act="inv-suspend" class="${btnCls()}">Suspend</button>
       <button data-act="inv-close" class="${btnCls()}">Close</button>`
    : `<button data-act="inv-reopen" class="${btnCls()}">Reopen</button>`;

  el.innerHTML = `${detailHeaderHtml(inv)}
    <div class="mb-s3 flex flex-wrap items-center gap-s2 text-caveat text-ink-muted">
      <span title="Project classification">${esc(classLabel)}</span>
      ${inv.project_classification === 'Experiment' && inv.hypothesis
        ? `<span title="${esc(inv.hypothesis)}">· hypothesis set</span>` : ''}
      <span>·</span>
      ${bindingGlyph(inv)}
      ${(inv.purposes || []).length ? `<span>· ${inv.purposes.map(esc).join(', ')}</span>` : ''}
      ${inv.visibility === 'private' ? `<span title="${esc(inv.visibility_note || '')}">· 🔒 private</span>` : ''}
    </div>
    <p class="max-w-[70ch] text-answer text-ink">${esc(inv.description || 'No description.')}</p>
    <div class="mb-s3 flex flex-wrap gap-s2">
      <button data-act="inv-make-current" class="${btnCls()}" ${isCurrent ? 'disabled' : ''}>${
        isCurrent ? 'Current investigation' : 'Make current'}</button>
      <button data-act="inv-edit" class="${btnCls()}">Edit</button>
      <button data-act="inv-reclassify" class="${btnCls()}">Reclassify…</button>
      ${lifecycleButtons}
    </div>
    <div id="inv-edit-form"></div>
    <div id="inv-reclass-form"></div>

    <div class="my-s3 h-px bg-rule"></div>
    <h4 class="m-0 mb-s2 font-heading text-subtab font-normal text-ink">Next steps</h4>
    ${nextSteps.steps?.length ? `<ul class="mb-s3 list-none p-0">${nextSteps.steps.map((s) => `
      <li class="mb-s2 rounded-sm border border-rule p-s2">
        <div class="text-answer text-ink">${esc(s.title)}</div>
        <div class="text-caveat text-ink-muted">${esc(s.detail || '')}</div>
        ${s.action ? `<button data-next-step="${esc(s.action)}" class="${btnCls()} mt-s1">Go</button>` : ''}
      </li>`).join('')}</ul>`
      : `<p class="mb-s3 text-caveat text-ink-muted">${nextSteps.complete ? 'Nothing outstanding.' : 'No next steps offered.'}</p>`}

    <div class="my-s3 h-px bg-rule"></div>
    <div class="mb-s2 flex items-center gap-s2">
      <h4 class="m-0 font-heading text-subtab font-normal text-ink">Egeria</h4>
    </div>
    ${egeriaSectionHtml(inv)}
    <div id="inv-egeria-form"></div>

    <div class="my-s3 h-px bg-rule"></div>
    <h4 class="m-0 mb-s2 font-heading text-subtab font-normal text-ink">Members (${members.length})</h4>
    ${addMemberFormHtml()}
    ${membersTableHtml(inv, members, dispositions)}`;

  bindDetail(inv, members);
}

function btnCls() {
  return 'cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] '
    + 'text-caveat text-ink hover:border-accent disabled:cursor-default disabled:opacity-60';
}

function egeriaSectionHtml(inv) {
  if (inv.egeria_project_guid) {
    return `<p class="max-w-[70ch] text-caveat text-ink-muted">
        Bound to <span class="font-mono">${esc(inv.egeria_project_qualified_name || inv.egeria_project_guid)}</span>.
      </p>
      <div class="flex flex-wrap gap-s2">
        <button data-act="inv-sync" class="${btnCls()}">Sync now</button>
        <button data-act="inv-relink" class="${btnCls()}">Relink members</button>
        <button data-act="inv-unbind" class="${btnCls()}">Unbind</button>
      </div>`;
  }
  return `<p class="max-w-[70ch] text-caveat text-ink-muted">
      No Egeria Project yet — local only. Bind an existing one, or create the Egeria side
      (Project + Folio + ResourceList) from this investigation's current members.
    </p>
    <div class="flex flex-wrap gap-s2">
      <button data-act="inv-bind" class="${btnCls()}">Bind existing project…</button>
      <button data-act="inv-promote" class="${btnCls()}">Create in Egeria →</button>
    </div>`;
}

const ENTITY_TYPES = [['repo', 'Repo'], ['database', 'Database'], ['filesystem', 'Filesystem']];

function addMemberFormHtml() {
  return `<div class="mb-s3 flex flex-wrap items-center gap-s2">
    <select id="inv-add-type" class="rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
      ${ENTITY_TYPES.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
    </select>
    <input id="inv-add-slug" list="inv-add-slug-list" type="text" placeholder="slug"
      class="rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
    <datalist id="inv-add-slug-list">
      ${(state.projects || []).map((p) => `<option value="${esc(p.slug)}">`).join('')}
    </datalist>
    <input id="inv-add-rationale" type="text" placeholder="why (optional)"
      class="flex-1 min-w-[160px] rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
    <button data-act="inv-add-member" class="${btnCls()}">Add</button>
    <span id="inv-add-error" class="text-caveat text-state-warn"></span>
  </div>`;
}

function membersTableHtml(inv, members, dispositions) {
  if (!members.length) return '<p class="text-caveat text-ink-muted">No members yet.</p>';
  // dispositions is {disposition: [members]} -- flip to a lookup by
  // (entity_type, entity_slug) so each row can show its own, since the
  // members list itself does not carry disposition.
  const byKey = new Map();
  for (const [disp, list] of Object.entries(dispositions || {})) {
    for (const m of list || []) byKey.set(`${m.entity_type}/${m.entity_slug}`, disp);
  }
  return `<table class="w-full text-left">
    <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
      <th class="pb-s2 pr-s3 font-normal">Type</th>
      <th class="pb-s2 pr-s3 font-normal">Resource</th>
      <th class="pb-s2 pr-s3 font-normal">Disposition</th>
      <th class="pb-s2 font-normal"></th>
    </tr></thead>
    <tbody>${members.map((m) => {
      const key = `${m.entity_type}/${m.entity_slug}`;
      const current = byKey.get(key) || '';
      return `<tr class="border-b border-rule">
        <td class="py-s2 pr-s3 text-caveat text-ink-muted">${esc(m.entity_type)}</td>
        <td class="py-s2 pr-s3 text-answer text-ink">${esc(m.entity_slug)}</td>
        <td class="py-s2 pr-s3 text-caveat">
          <select data-disposition="${esc(m.entity_type)}|${esc(m.entity_slug)}"
            class="rounded-sm border border-rule bg-paper px-1 py-[2px] text-caveat text-ink">
            <option value="" ${current ? '' : 'selected'}>◌ undecided</option>
            ${Object.entries(DISPOSITION_GLYPH).map(([d, g]) => `<option value="${d}" ${
              current === d ? 'selected' : ''}>${g} ${d}</option>`).join('')}
          </select>
        </td>
        <td class="py-s2">
          <button data-remove-member="${esc(m.entity_type)}|${esc(m.entity_slug)}"
            class="cursor-pointer bg-transparent text-caveat text-state-warn underline">Remove</button>
        </td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

function bindDetail(inv, members) {
  const el = $('content');
  const back = () => { _detailSlug = null; renderInvestigation(); };
  el.querySelectorAll('[data-act="inv-back"]').forEach((b) => b.addEventListener('click', back));

  el.querySelector('[data-act="inv-make-current"]')?.addEventListener('click', async () => {
    await setInvestigation(inv.slug);
    renderDetail(inv.slug);
  });

  el.querySelector('[data-act="inv-edit"]')?.addEventListener('click', () => {
    const host = $('inv-edit-form');
    host.innerHTML = `<div class="mb-s3 rounded-sm border border-rule p-s2">
      <label class="mb-[3px] block text-caveat text-ink-muted">Name</label>
      <input id="inv-edit-name" type="text" value="${esc(inv.display_name || '')}"
        class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-answer text-ink">
      <label class="mb-[3px] block text-caveat text-ink-muted">Description</label>
      <textarea id="inv-edit-desc" rows="2"
        class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">${esc(inv.description || '')}</textarea>
      <div class="flex gap-s2">
        <button id="inv-edit-save" class="${btnCls()}">Save</button>
        <button id="inv-edit-cancel" class="cursor-pointer bg-transparent text-caveat text-ink-muted underline">Cancel</button>
      </div>
      <span id="inv-edit-error" class="text-caveat text-state-warn"></span>
    </div>`;
    host.querySelector('#inv-edit-cancel').addEventListener('click', () => { host.innerHTML = ''; });
    host.querySelector('#inv-edit-save').addEventListener('click', async () => {
      const btn = host.querySelector('#inv-edit-save');
      btn.disabled = true;
      try {
        await updateInvestigation(inv.slug, {
          display_name: host.querySelector('#inv-edit-name').value.trim(),
          description: host.querySelector('#inv-edit-desc').value.trim(),
        });
        await refreshInvestigationsAndSidebar();
        renderDetail(inv.slug);
      } catch (err) {
        btn.disabled = false;
        host.querySelector('#inv-edit-error').textContent = err.message;
      }
    });
  });

  el.querySelector('[data-act="inv-reclassify"]')?.addEventListener('click', async () => {
    const { classifications } = await vocab();
    const host = $('inv-reclass-form');
    host.innerHTML = `<div class="mb-s3 rounded-sm border border-rule p-s2">
      <label class="mb-[3px] block text-caveat text-ink-muted">New kind</label>
      <select id="inv-reclass-select" class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
        ${classifications.classifications.map((c) => `<option value="${esc(c.name)}" ${
          c.name === inv.project_classification ? 'selected' : ''}>${esc(c.label || c.name)}</option>`).join('')}
      </select>
      <div id="inv-reclass-hyp-wrap" class="mb-s2 hidden">
        <label class="mb-[3px] block text-caveat text-ink-muted">Hypothesis</label>
        <input id="inv-reclass-hyp" type="text" value="${esc(inv.hypothesis || '')}"
          class="w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
      </div>
      <p class="mb-s2 text-caveat text-ink-muted">
        Loosening visibility (e.g. Personal/Experiment → a public kind) always works. Tightening
        can fail partway if artifacts already reached a public Egeria zone — the result will say
        exactly which elements moved and which did not.
      </p>
      <div class="flex gap-s2">
        <button id="inv-reclass-save" class="${btnCls()}">Reclassify</button>
        <button id="inv-reclass-cancel" class="cursor-pointer bg-transparent text-caveat text-ink-muted underline">Cancel</button>
      </div>
      <div id="inv-reclass-result" class="mt-s2 text-caveat"></div>
    </div>`;
    const sel = host.querySelector('#inv-reclass-select');
    const hypWrap = host.querySelector('#inv-reclass-hyp-wrap');
    const syncHyp = () => hypWrap.classList.toggle('hidden',
      !classifications.classifications.find((c) => c.name === sel.value)?.requires_hypothesis);
    sel.addEventListener('change', syncHyp);
    syncHyp();
    host.querySelector('#inv-reclass-cancel').addEventListener('click', () => { host.innerHTML = ''; });
    host.querySelector('#inv-reclass-save').addEventListener('click', async () => {
      const btn = host.querySelector('#inv-reclass-save');
      btn.disabled = true;
      btn.textContent = 'Reclassifying…';
      const resultEl = host.querySelector('#inv-reclass-result');
      try {
        // ReclassificationResult.as_dict() (investigation_reclassifier.py):
        // `still_public` is a LIST of guids still exposed on a tightening
        // (always [] otherwise), `local_applied`/`ok` are booleans. Left on
        // screen with an explicit "Reload" rather than an immediate
        // renderDetail() -- this is the one write in the whole pane where a
        // partial result naming exactly which elements did not move matters
        // more than snapping back to a clean view.
        const result = await reclassifyInvestigation(
          inv.slug, sel.value, host.querySelector('#inv-reclass-hyp').value.trim());
        btn.textContent = 'Reclassify';
        resultEl.innerHTML = (result.ok
          ? `<span class="text-state-ok">Reclassified to ${esc(result.to_classification)}.</span>`
          : `<span class="text-state-warn">Partial (${esc(result.direction)}): local_applied=${
              esc(String(result.local_applied))}.${result.still_public.length
                ? ` Still public: ${result.still_public.map(esc).join(', ')}.` : ''}${
              result.errors.length ? ` Errors: ${result.errors.map(esc).join('; ')}.` : ''}</span>`)
          + `<div class="mt-s2"><button id="inv-reclass-reload" class="${btnCls()}">Reload</button></div>`;
        resultEl.querySelector('#inv-reclass-reload').addEventListener('click', () => renderDetail(inv.slug));
        await refreshInvestigationsAndSidebar();
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Reclassify';
        resultEl.innerHTML = `<span class="text-state-warn">${esc(err.message)}</span>`;
      }
    });
  });

  el.querySelector('[data-act="inv-close"]')?.addEventListener('click', async () => {
    if (!window.confirm(`Close '${inv.display_name || inv.slug}'? Its findings stay queryable; it just drops out of the default scope. Nothing is deleted.`)) return;
    await closeInvestigation(inv.slug);
    await refreshInvestigationsAndSidebar();
    renderDetail(inv.slug);
  });
  el.querySelector('[data-act="inv-suspend"]')?.addEventListener('click', async () => {
    await suspendInvestigation(inv.slug);
    await refreshInvestigationsAndSidebar();
    renderDetail(inv.slug);
  });
  el.querySelector('[data-act="inv-reopen"]')?.addEventListener('click', async () => {
    await reopenInvestigation(inv.slug);
    await refreshInvestigationsAndSidebar();
    renderDetail(inv.slug);
  });

  el.querySelector('[data-act="inv-bind"]')?.addEventListener('click', () => {
    const host = $('inv-egeria-form');
    host.innerHTML = `<div class="mt-s2 rounded-sm border border-rule p-s2">
      <label class="mb-[3px] block text-caveat text-ink-muted">Egeria Project GUID</label>
      <input id="inv-bind-guid" type="text" class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
      <label class="mb-[3px] block text-caveat text-ink-muted">Qualified name (optional)</label>
      <input id="inv-bind-qn" type="text" class="mb-s2 w-full rounded-sm border border-rule bg-paper px-2 py-1 text-caveat text-ink">
      <div class="flex gap-s2">
        <button id="inv-bind-save" class="${btnCls()}">Bind</button>
        <button id="inv-bind-cancel" class="cursor-pointer bg-transparent text-caveat text-ink-muted underline">Cancel</button>
      </div>
      <span id="inv-bind-error" class="text-caveat text-state-warn"></span>
    </div>`;
    host.querySelector('#inv-bind-cancel').addEventListener('click', () => { host.innerHTML = ''; });
    host.querySelector('#inv-bind-save').addEventListener('click', async () => {
      const guid = host.querySelector('#inv-bind-guid').value.trim();
      if (!guid) { host.querySelector('#inv-bind-error').textContent = 'GUID is required.'; return; }
      const btn = host.querySelector('#inv-bind-save');
      btn.disabled = true;
      try {
        await bindInvestigationEgeriaProject(inv.slug, {
          status: 'linked', egeriaProjectGuid: guid,
          egeriaProjectQualifiedName: host.querySelector('#inv-bind-qn').value.trim(),
        });
        await refreshInvestigationsAndSidebar();
        renderDetail(inv.slug);
      } catch (err) {
        btn.disabled = false;
        host.querySelector('#inv-bind-error').textContent = err.message;
      }
    });
  });

  el.querySelector('[data-act="inv-unbind"]')?.addEventListener('click', async () => {
    if (!window.confirm('Unbind this investigation from its Egeria Project? The Egeria Project itself is not deleted.')) return;
    await bindInvestigationEgeriaProject(inv.slug, { status: 'unset' });
    await refreshInvestigationsAndSidebar();
    renderDetail(inv.slug);
  });

  el.querySelector('[data-act="inv-promote"]')?.addEventListener('click', async () => {
    const btn = el.querySelector('[data-act="inv-promote"]');
    btn.disabled = true;
    btn.textContent = 'Creating…';
    const host = $('inv-egeria-form');
    try {
      const result = await promoteInvestigation(inv.slug);
      const confirmedLine = result.classification_confirmed === result.classification_requested
        ? `confirmed as ${esc(result.classification_confirmed)}`
        : result.classification_confirmed === null || result.classification_confirmed === undefined
          ? 'could not verify the classification took'
          : `requested ${esc(result.classification_requested)}, Egeria reports ${esc(result.classification_confirmed)}`;
      host.innerHTML = `<div class="mt-s2 text-caveat ${result.ok ? 'text-state-ok' : 'text-state-warn'}">
        ${result.ok ? 'Created.' : 'Partial — see below.'} ${confirmedLine}.
        ${result.members_linked?.length ? ` Linked: ${result.members_linked.map(esc).join(', ')}.` : ''}
        ${result.members_unlinkable?.length ? ` Could not link: ${result.members_unlinkable.map(esc).join(', ')}.` : ''}
        ${result.errors?.length ? ` Errors: ${result.errors.map(esc).join('; ')}.` : ''}
        <div class="mt-s2"><button id="inv-promote-reload" class="${btnCls()}">Reload</button></div>
      </div>`;
      // Left on screen rather than an immediate renderDetail() -- see the
      // reclassify handler's identical reasoning: a partial promote's
      // members_unlinkable/errors matter more than snapping back to a
      // clean view that would otherwise erase them before they're read.
      host.querySelector('#inv-promote-reload').addEventListener('click', () => renderDetail(inv.slug));
      await refreshInvestigationsAndSidebar();
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Create in Egeria →';
      host.innerHTML = `<div class="mt-s2 text-caveat text-state-warn">${esc(err.message)}</div>`;
    }
  });

  el.querySelector('[data-act="inv-sync"]')?.addEventListener('click', async () => {
    const btn = el.querySelector('[data-act="inv-sync"]');
    btn.disabled = true;
    btn.textContent = 'Syncing…';
    try {
      await syncInvestigationEgeria(inv.slug);
      btn.disabled = false;
      btn.textContent = 'Synced';
      setTimeout(() => { btn.textContent = 'Sync now'; }, 3000);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = `Not synced: ${err.message}`;
    }
  });

  el.querySelector('[data-act="inv-relink"]')?.addEventListener('click', async () => {
    const btn = el.querySelector('[data-act="inv-relink"]');
    btn.disabled = true;
    btn.textContent = 'Relinking…';
    try {
      await relinkInvestigationMembers(inv.slug);
      renderDetail(inv.slug);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = `Not relinked: ${err.message}`;
    }
  });

  el.querySelector('[data-act="inv-add-member"]')?.addEventListener('click', async () => {
    const entityType = el.querySelector('#inv-add-type').value;
    const entitySlug = el.querySelector('#inv-add-slug').value.trim();
    const rationale = el.querySelector('#inv-add-rationale').value.trim();
    const errEl = el.querySelector('#inv-add-error');
    if (!entitySlug) { errEl.textContent = 'Slug is required.'; return; }
    try {
      await addInvestigationMember(inv.slug, entityType, entitySlug, rationale);
      if (inv.slug === state.investigation) {
        // Keep the sidebar's own working-set cache (used for "In scope"
        // filtering) in step, same reasoning as bulkScope() in app.js.
        await refreshInvestigationsAndSidebar();
      }
      renderDetail(inv.slug);
    } catch (err) {
      errEl.textContent = err.message;
    }
  });

  el.querySelectorAll('[data-remove-member]').forEach((b) => b.addEventListener('click', async () => {
    const [entityType, entitySlug] = b.dataset.removeMember.split('|');
    if (!window.confirm(`Remove ${entitySlug} from this investigation's scope?`)) return;
    try {
      await removeInvestigationMember(inv.slug, entityType, entitySlug);
      if (inv.slug === state.investigation) await refreshInvestigationsAndSidebar();
      renderDetail(inv.slug);
    } catch (err) {
      window.alert(`Not removed: ${err.message}`);
    }
  }));

  el.querySelectorAll('[data-disposition]').forEach((sel) => sel.addEventListener('change', async () => {
    const [entityType, entitySlug] = sel.dataset.disposition.split('|');
    const disposition = sel.value;
    sel.disabled = true;
    try {
      await setInvestigationDisposition(inv.slug, entityType, entitySlug, disposition);
    } catch (err) {
      window.alert(`Not saved: ${err.message}`);
    } finally {
      sel.disabled = false;
    }
  }));

  el.querySelectorAll('[data-next-step]').forEach((b) => b.addEventListener('click', () => {
    const action = b.dataset.nextStep;
    if (action === 'egeria') { $('inv-egeria-form').scrollIntoView({ behavior: 'smooth' }); return; }
    if (action === 'disposition') { el.querySelector('table:last-of-type')?.scrollIntoView({ behavior: 'smooth' }); return; }
    if (action === 'edit') { el.querySelector('[data-act="inv-edit"]')?.click(); return; }
    // 'scouting' -- and anything else unrecognised -- has no in-pane target;
    // naming it beats a button that silently does nothing.
    window.alert(`This step points at ${action}, which this pane does not deep-link to yet.`);
  }));
}
