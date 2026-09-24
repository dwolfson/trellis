/* Enrichment — testimony, not paperwork.
 *
 * Moved out of app.js (PLAN-FINISH-REPOS.md, Part 2 §1): app.js keeps
 * routing, shared state and chrome; each stage owns its own pane's
 * rendering logic. `renderEnrichment` is called from app.js's generic
 * Questions-checklist engine when `state.stage === 'enrichment'` (see
 * `loadPane()`'s big shared function in app.js) — that engine itself stays
 * in app.js because it is shared machinery every built stage uses, not
 * Enrichment's alone. `renderEnrichmentEvidence` is exported too, though
 * only ever called from within `renderEnrichment` in this same module; it
 * stayed exported to mirror how app.js named it and in case a future
 * change needs to trigger the evidence rail from outside this file.
 */
import { ago, whenMs } from '/static/next/format.js';
import { getBulkFacts, saveEnrichmentField } from '/static/re-api.js';
import { state, esc, $, tnum, factGlyph, ensureRailShowing, railClaim, apiEntityType } from '/static/next/app.js';

/* ── Enrichment: testimony, not paperwork ──────────────────────────────────
 *
 * Two halves, not one list of eight fields with one Save. The line between
 * them is not arbitrary: a field is a JUDGEMENT if a person's opinion is the
 * value — sensitivity, criticality, intended use, actual use, owner — and an
 * OBSERVATION if a person is supplying a fact about the world — licence,
 * environment, retention. Opinions need an author, a date and a review
 * state. Observations need a source.
 *
 * Judgements come first and get the room: they are the part only a person
 * can supply. Every field saves alone — someone who knows the owner and not
 * the sensitivity can say so and leave. The author and date sit on every
 * judgement without hovering, because testimony without an author is not
 * testimony, and because that is what makes review meaningful later.
 *
 * Perishability, which needs no per-field configuration: a judgement carries
 * the measurements that were on screen when it was made. When one of those
 * moves, the judgement is not invalidated — it gets a flag that says what
 * moved. "⚠ review — evidence moved: cve_scan" is a specific, answerable
 * prompt, not a staleness timer.
 *
 * Evidence sits in the rail as MATERIAL, never as proposals. No "apply
 * suggestion". The one exception is a fact a survey already established —
 * the licence — which is offered to confirm, with its source, into the
 * observations half.
 *
 * Nothing here is written to the catalogue until Curate. That sentence is
 * the one misconception worth pre-empting, and it is on the pane.
 */
const JUDGEMENTS = [
  { key: 'sensitivity',  label: 'Sensitivity',  options: ['public', 'internal', 'confidential', 'restricted'] },
  { key: 'criticality',  label: 'Criticality',  options: ['low', 'important', 'critical'] },
  { key: 'intended_use', label: 'Intended use', placeholder: 'what is this for, here?' },
  { key: 'actual_use',   label: 'Actual use',   placeholder: 'how is it used today?' },
  { key: 'owner',        label: 'Owner',        placeholder: 'who answers for it?' },
];
const OBSERVATIONS = [
  { key: 'licence',      label: 'Licence',      fromAnalysis: 'license_classification' },
  { key: 'environment',  label: 'Environment',  options: ['prod', 'dev', 'test', 'research', 'archive'] },
  { key: 'retention',    label: 'Retention',    placeholder: 'how long, and by whose rule?' },
];
// The analyses whose current state is the evidence for a judgement.
const ENRICHMENT_EVIDENCE = ['interface_surface', 'security_scan', 'chaoss_metrics', 'cve_scan',
  'repository_health', 'license_classification', 'secret_scan', 'documentation_coverage'];

function evidenceSnapshot() {
  const snap = {};
  for (const [id, f] of Object.entries(state.enrichmentFacts || {})) if (f.last_run_at) snap[id] = f.last_run_at;
  return snap;
}

/** Which of a judgement's evidence has moved since it was made. */
function movedSince(field) {
  const moved = [];
  for (const [id, at] of Object.entries(field.evidence || {})) {
    const now = state.enrichmentFacts?.[id]?.last_run_at;
    // Instants, not strings: `Z`, `+00:00` and naive stamps all occur, and
    // a string compare between spellings fires or fails on the suffix.
    if (now && whenMs(now) > whenMs(at)) moved.push(id);
  }
  return moved;
}

function fieldControlHtml(def, field, kind = 'judgement') {
  const v = field?.value || '';
  // Judgements are the larger set on purpose; the recorded facts sit a
  // step down, at provenance size, so the split is visible, not narrated.
  const size = kind === 'judgement' ? 'text-answer' : 'text-provenance';
  if (def.options) {
    return `<select data-field="${def.key}" class="rounded-sm border border-rule-strong bg-transparent px-[6px] py-[2px] ${size} text-ink">
      <option value="">—</option>
      ${def.options.map((o) => `<option value="${o}" ${o === v ? 'selected' : ''}>${o}</option>`).join('')}
    </select>`;
  }
  return `<input data-field="${def.key}" type="text" value="${esc(v)}" placeholder="${esc(def.placeholder || '')}"
    class="w-full rounded-sm border border-rule-strong bg-transparent px-[6px] py-[2px] ${size} text-ink placeholder:text-ink-muted">`;
}

function fieldRowHtml(def, kind) {
  const field = (state.enrichment || {})[def.key];
  const moved = field && kind === 'judgement' ? movedSince(field) : [];
  // Judgements carry an author; observations carry a source. The server
  // stamps `author` on every field, so a source-only branch was dead code
  // and a confirmed licence read as "alice · 2d ago" with its source stored
  // and invisible. Both halves render now, in that order.
  const when = field?.set_at ? `<span class="tnum">${esc(ago(field.set_at))}</span>` : '';
  const who = field?.author
    ? [kind === 'observation' && field.source ? `from ${esc(field.source)}` : '',
       `${esc(field.author)}${field.interim ? ' · interim' : ''}`, when].filter(Boolean).join(' · ')
    : '';
  const proposed = def.fromAnalysis && !field?.value ? proposedFrom(def.fromAnalysis) : null;
  // "What we judge" is the larger of the two sets -- the split's whole
  // argument -- so its labels are body size in ink, not caption size muted.
  const labelCls = kind === 'judgement' ? 'text-question font-heading text-ink' : 'text-provenance text-ink-muted';
  return `<div class="grid grid-cols-[130px_1fr] items-baseline gap-x-s3 gap-y-[2px] border-b border-rule py-s2">
    <div class="${labelCls}">${esc(def.label)}</div>
    <div class="min-w-0">
      <div class="flex items-baseline gap-s2">${fieldControlHtml(def, field, kind)}
        <button type="button" data-save="${def.key}" data-kind="${kind}"
          class="shrink-0 cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[1px] text-provenance text-accent-ink">save</button></div>
      <div class="text-provenance text-ink-muted">
        ${moved.length ? `<span class="text-state-warn">⚠ review — evidence moved: ${esc(moved.join(', '))}</span> · ` : ''}
        ${who}
        ${proposed ? `<span>from survey: <span class="text-ink">${esc(proposed.value)}</span> ·
          <button type="button" data-confirm="${def.key}" data-source="${esc(def.fromAnalysis)}" data-value="${esc(proposed.value)}"
            class="cursor-pointer bg-transparent p-0 text-accent-ink underline">confirm</button></span>` : ''}
      </div>
      ${def.key === 'owner' ? ownerNoteHtml(field) : ''}
    </div>
  </div>`;
}

/** Owner candidates from contributor data are DEFERRED, and a deferred
 *  affordance is marked, never omitted (the sub-tab rule, app.js above).
 *  Until one is named, the investigator stands as interim owner -- offered
 *  as a one-click act by the signed-in person, not inferred from a blank. */
function ownerNoteHtml(field) {
  const me = (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
  const offer = !field?.value && me
    ? ` · <button type="button" data-owner-interim="${esc(me)}"
        class="cursor-pointer bg-transparent p-0 text-accent-ink underline">stand as interim owner</button>`
    : '';
  return `<div class="text-provenance text-ink-muted"><span class="border-b border-dashed border-current">owner candidates
    from contributor data · not built in /next</span>${offer}</div>`;
}

/** A fact a survey already established, offered to confirm — not applied.
 *  Gated on a CLASSIFIED licence: "No license detected on this repository."
 *  is a measured finding too, and offering it to confirm would write that
 *  sentence into the licence field. The tier finding's label says which. */
function proposedFrom(analysisId) {
  const f = state.enrichmentFacts?.[analysisId];
  if (!f || f.state !== 'measured') return null;
  const tier = (f.value?.findings || []).find((x) => x.check_name === 'license_risk_tier');
  // `none` is both "no licence" and "nothing examined"; `unknown` is a
  // licence that IS present and unclassified -- its name is still a fact.
  if (!tier || !tier.label || String(tier.label) === 'none') return null;
  // The licence itself, not its risk tier: the finding's label is
  // "permissive" and its summary is "Apache License 2.0 — Permissive". The
  // part before the dash is the fact a person would confirm.
  const raw = tier.summary || f.headline || '';
  if (!raw.includes(' — ')) return null;
  const value = String(raw).split(' — ')[0].trim();
  return value ? { value } : null;
}

export async function renderEnrichment(slug) {
  const host = $('enrichment-form');
  if (!host) return;
  host.innerHTML = `<div class="text-caveat text-ink-muted">Reading the evidence…</div>`;
  try {
    const res = await getBulkFacts([slug], ENRICHMENT_EVIDENCE);
    state.enrichmentFacts = Object.fromEntries(((res.subjects || {})[slug] || []).map((f) => [f.analysis_id, f]));
  } catch { state.enrichmentFacts = {}; }
  if (slug !== state.selectedSlug) return;
  renderEnrichmentForm(slug);
}

/** Re-render the form in place from already-fetched `state.enrichmentFacts`
 *  — no evidence re-fetch, no "Reading the evidence…" wipe. A save changes
 *  one field's value, not the survey evidence behind it, so re-running the
 *  full fetch-then-blank-then-rebuild `renderEnrichment` after every save
 *  was flashing the *entire* form to a loading placeholder and back for the
 *  ~2s the fetch took — every field, not just the one just saved. Call this
 *  from the save handlers below instead; `renderEnrichment` (the fetching
 *  one) stays for the initial pane load, where there is nothing on screen
 *  yet to flicker. */
function renderEnrichmentForm(slug) {
  const host = $('enrichment-form');
  if (!host) return;

  const setJ = JUDGEMENTS.filter((d) => state.enrichment?.[d.key]?.value).length;
  const me = (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
  host.innerHTML = `
    <p class="mb-s3 max-w-[70ch] text-caveat text-ink-muted">Nothing here is written to the catalogue until you catalogue it (Curate).
      What you set here is testimony — yours, dated — and the surveys' findings in the rail are material to read, not answers to accept.</p>
    <div class="mb-s1 flex items-baseline gap-s2">
      <span class="font-heading text-question text-ink">What we judge</span>
      <span class="text-provenance text-ink-muted"><span class="tnum">${setJ}</span> of <span class="tnum">${JUDGEMENTS.length}</span> set · perishable</span>
    </div>
    ${JUDGEMENTS.map((d) => fieldRowHtml(d, 'judgement')).join('')}
    <div class="mb-s1 mt-s4 flex items-baseline gap-s2">
      <span class="text-caps uppercase tracking-caps text-ink">What we record</span>
      <span class="text-provenance text-ink-muted">durable</span>
    </div>
    ${OBSERVATIONS.map((d) => fieldRowHtml(d, 'observation')).join('')}
    <div class="mb-s1 mt-s4 text-caps uppercase tracking-caps text-ink">What only you can answer</div>
    <div class="mb-s2 text-provenance text-ink-muted">The catalog's own questions for a person, below — each saves alone.</div>`;

  host.querySelectorAll('[data-save]').forEach((b) => b.addEventListener('click', async () => {
    const key = b.dataset.save; const kind = b.dataset.kind;
    const ctl = host.querySelector(`[data-field="${key}"]`);
    const value = (ctl?.value || '').trim();
    b.disabled = true; b.textContent = 'saving…';
    try {
      const out = await saveEnrichmentField(slug, key, {
        value, kind, evidence: kind === 'judgement' ? evidenceSnapshot() : {},
        // Interim means "the investigator stands in", which is a person
        // naming themself -- not a blank. A blank owner is no owner.
        interim: key === 'owner' && !!value && value === me,
        source: kind === 'observation' ? 'user' : '',
      }, apiEntityType(state.resourceType));
      state.enrichment = { ...(state.enrichment || {}), [key]: out.field };
      renderEnrichmentForm(slug);
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 401 ? 'sign in to record' : `not saved: ${err.message}`;
    }
  }));
  host.querySelectorAll('[data-owner-interim]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'recording…';
    try {
      const out = await saveEnrichmentField(slug, 'owner', {
        value: b.dataset.ownerInterim, kind: 'judgement', evidence: evidenceSnapshot(), interim: true,
      }, apiEntityType(state.resourceType));
      state.enrichment = { ...(state.enrichment || {}), owner: out.field };
      renderEnrichmentForm(slug);
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 401 ? 'sign in to record' : `not recorded: ${err.message}`;
    }
  }));
  host.querySelectorAll('[data-confirm]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'confirming…';
    try {
      const out = await saveEnrichmentField(slug, b.dataset.confirm, {
        value: b.dataset.value, kind: 'observation', source: b.dataset.source,
      }, apiEntityType(state.resourceType));
      state.enrichment = { ...(state.enrichment || {}), [b.dataset.confirm]: out.field };
      renderEnrichmentForm(slug);
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 401 ? 'sign in to record' : `not confirmed: ${err.message}`;
    }
  }));
  renderEnrichmentEvidence(slug);
}

/** The rail: evidence as material. Each analysis's own sentence, its age, and
 *  "new since you judged" where its run postdates the latest judgement that
 *  saw it — the perishability mechanism doing its job at the moment it is
 *  useful. */
export function renderEnrichmentEvidence(slug) {
  const out = $('rail-evidence');
  if (!out) return;
  // Rail state is a persisted preference; "new since you judged" written
  // into a closed drawer is the perishability signal nobody sees. The DOM,
  // not the preference, says whether it is showing.
  ensureRailShowing();
  railClaim();
  const judged = Object.values(state.enrichment || {}).filter((f) => f.kind === 'judgement' && f.set_at);
  const items = ENRICHMENT_EVIDENCE.map((id) => state.enrichmentFacts?.[id]).filter(Boolean);
  out.innerHTML = `
    <div class="mb-s1 flex items-baseline gap-s2">
      <span class="font-heading uppercase tracking-caps text-caps text-accent-on-dark">Evidence · enrichment</span>
      <span class="text-caps text-chrome-muted">for <span class="font-mono">${esc(slug)}</span> · material, not proposals</span>
    </div>
    ${items.length ? items.map((f) => {
      const g = factGlyph(f.state);
      const seen = judged.some((j) => j.evidence?.[f.analysis_id]);
      const fresh = judged.some((j) => j.evidence?.[f.analysis_id] && whenMs(f.last_run_at) > whenMs(j.evidence[f.analysis_id]));
      return `<div class="border-b border-chrome-line-soft py-[4px]">
        <div class="flex items-baseline gap-s2 text-subtab text-chrome-ink">
          <span class="${g.tone === 'text-state-ok' ? 'text-state-ok-on-dark' : g.tone === 'text-state-warn' ? 'text-state-warn-on-dark' : 'text-chrome-muted'}">${g.glyph}</span>
          <span class="min-w-0 flex-1">${tnum(esc(f.headline || f.state))}</span></div>
        <div class="pl-[20px] text-caps text-chrome-muted"><span class="font-mono">${esc(f.analysis_id)}</span>${
          f.last_run_at ? ` · <span class="tnum">${esc(ago(f.last_run_at))}</span>` : ''}${
          fresh ? ` · <span class="text-accent-on-dark">new since you judged</span>` : seen ? '' : ''}</div>
      </div>`;
    }).join('') : `<div class="text-caps text-chrome-muted">No measurements to show yet.</div>`}
    <div class="mt-s2 text-caps text-chrome-muted">Material to read, not answers to accept. No "apply suggestion".</div>`;
}
