/* Curate — review and commit.
 *
 * Moved out of app.js (PLAN-FINISH-REPOS.md, Part 2 §1): app.js keeps
 * routing, shared state and chrome; each stage owns its own pane's
 * rendering logic. `renderCurate` is the only export app.js's generic
 * Questions-checklist engine calls directly, when `state.stage === 'curate'`
 * (see `loadPane()`'s big shared function in app.js); everything else in
 * this file — the component-tree/branch/leaf review, the catalogue-depth
 * offer, the verdict recorder — is reached only from within `renderCurate`
 * itself or from other functions in this module, so it stays unexported.
 */
import { ago } from '/static/next/format.js';
import { openDialog, closeCellDetail } from '/static/next/worklist.js';
import {
  getBulkFacts, getCuratePlan, curateCommit, getCuration, pollActivity,
  getComponentTree, getComponentLeaves, postBranchVerdicts,
  getCatalogueDepthOffer, postCatalogueDepthOfferOutcome,
  getComponentBlueprints, postBlueprintVerdict,
} from '/static/re-api.js';
import {
  state, esc, $, icon, tnum, factGlyph, ensureRailShowing, railClaim, railFrame,
  openMembers, fmtSeconds, tokens, mermaidForKroki, themeSvgElement, deferredAttrs,
} from '/static/next/app.js';




/* ════════════════════════════════════════════════════════════════════════
 * Curate — review and commit
 *
 * One decision, one screen, one commit — and the commit has consequences in
 * two directions, so the screen's whole job is to show both before the
 * press. Three columns answer one question, "what should the catalogue know
 * about this?": what it IS, what it HOLDS, what it is MADE OF. Then how it
 * relates, then the manifest of what gets written. Almost everything on it
 * was decided earlier; this is where it is seen assembled.
 *
 * Rules held (Enrichment and Curate Wireframes; Repo Handoff item 6):
 * - Candidates with evidence, never auto-applied: every row names its
 *   analysis, its state, and opens its members. "Infrastructure Asset? 15
 *   Dockerfiles", with the question mark.
 * - Testimony is copied, measurements are linked, unresolved things travel.
 * - Only worthy things get curated: the population is `tracking` or `using`,
 *   and the pane says so rather than hiding the resource or the button.
 * - The commit is asynchronous and can fail elsewhere: the record shows each
 *   step as it lands, and a failed step is a failed step, not a lost act.
 * ═══════════════════════════════════════════════════════════════════════ */

// `pick` marks the one column whose rows are confirmed one by one; the
// others are counts whose members are reviewed, and the contained set is
// taken whole (the checkbox under the manifest) -- the wireframe's shape.
const CURATE_COLUMNS = [
  { key: 'what_it_is',    title: 'what it is',      sub: 'each confirmed line becomes an entity in the catalogue', pick: true },
  { key: 'what_it_holds', title: "what's in it",    sub: 'each becomes its own asset, related to this one' },
  { key: 'made_of',       title: "what it's made of", sub: 'components, with ports and wires derived — review stays on Architecture verdicts' },
  { key: 'relates',       title: 'how it relates',  sub: '' },
];

/* ── Page-level section nav (project owner's report after item 3 shipped:
 * "one very long page with no table of contents at the top, the sections
 * are not collapsible"). Six sections, each with a stable id the nav's
 * anchors target and each wrapped in <details>/<summary> so a viewer can
 * collapse what they are not using -- default open throughout, since the
 * reported problem was missing structure, not too much visible at once.
 * Anchor scrolling reuses classic's own convention (index.html's
 * `_curateJumpTo`/`_curateComponentAnchorId` and the diagram/dialog jumps
 * at index.html:4266/:4874): `scrollIntoView({ behavior: 'smooth',
 * block: 'center' })`. This is a page-level table of contents, a narrower
 * and separate thing from classic's component/blueprint cross-reference
 * jump -- there was no existing page-nav pattern to port, so this is new. */
const CURATE_SECTIONS = [
  { id: 'curate-sec-what-it-is', label: 'what it is' },
  { id: 'curate-sec-what-holds', label: "what's in it" },
  { id: 'curate-sec-made-of', label: "what it's made of" },
  { id: 'curate-sec-blueprints', label: 'blueprints' },
  { id: 'curate-sec-relates', label: 'how it relates' },
  { id: 'curate-sec-writes', label: 'what gets written' },
];

function curateSectionNavHtml() {
  return `<nav aria-label="Curate sections" class="sticky top-0 z-10 -mx-s2 mb-s3 flex flex-wrap items-baseline gap-x-s3 gap-y-[2px] border-b border-rule bg-paper px-s2 py-s2 text-provenance">
    ${CURATE_SECTIONS.map((s) => `<a href="#${s.id}" data-curate-nav="${s.id}" class="cursor-pointer text-accent-ink underline">${esc(s.label)}</a>`).join('')}
  </nav>`;
}

function bindCurateSectionNav(host) {
  host.querySelectorAll('[data-curate-nav]').forEach((a) => a.addEventListener('click', (ev) => {
    ev.preventDefault();
    const el = document.getElementById(a.dataset.curateNav);
    if (!el) return;
    if (el.tagName === 'DETAILS') el.open = true;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));
}

/** Wraps a section's already-built inner HTML in the shared collapsible
 *  shell -- <summary> is the section's existing heading text, `id` is what
 *  the nav's anchors target, default open. */
function curateSectionHtml(id, title, extraHeader, inner) {
  return `<details id="${id}" open class="mt-s4">
    <summary class="mb-s1 flex cursor-pointer items-baseline gap-s2 border-b border-rule pb-[3px]">
      <span class="font-heading text-name font-normal text-ink">${esc(title)}</span>
      ${extraHeader || ''}
    </summary>
    ${inner}
  </details>`;
}

function curateRowHtml(r, selected, pick) {
  const g = factGlyph(r.state);
  const mark = pick && r.candidate
    ? `<input type="checkbox" data-curate-pick="${esc(r.kind)}" ${selected ? 'checked' : ''}
         class="mt-[3px] shrink-0 cursor-pointer">`
    : `<span class="w-[13px] shrink-0 text-center ${r.candidate ? 'text-ink' : 'text-ink-muted'}">${r.candidate ? '✓' : '·'}</span>`;
  const members = r.members?.analysis_id
    ? ` · <button type="button" data-curate-members="${esc(r.members.analysis_id)}" data-metric="${esc(r.members.metric || '')}"
          class="cursor-pointer bg-transparent p-0 text-accent-ink underline">${r.count != null ? `review ${tnum(String(r.count))}` : 'members'} ›</button>`
    : '';
  return `<div class="flex items-start gap-s2 border-b border-rule py-s2">
    ${mark}
    <div class="min-w-0 flex-1">
      <div class="text-answer text-ink">${tnum(esc(r.label))}</div>
      <div class="text-provenance text-ink-muted">
        <span class="${g.tone}">${g.glyph}</span> <span class="font-mono">${esc(r.source)}</span>
        ${r.evidence ? ` · ${esc(r.evidence)}` : ''}${members}</div>
    </div>
  </div>`;
}

function curateWritesHtml(plan, picks, subCount) {
  const w = plan.writes || {};
  const cls = w.classifications || [];
  const lines = [];
  lines.push(`<span class="tnum">${picks.length}</span> entit${picks.length === 1 ? 'y' : 'ies'}${picks.length ? ` · ${picks.map(esc).join(', ')}` : ''}`);
  lines.push(`<span class="tnum">${subCount}</span> contained asset${subCount === 1 ? '' : 's'} (sub-resources)`);
  lines.push(cls.length
    ? `<span class="tnum">${cls.length}</span> authored classification${cls.length === 1 ? '' : 's'} · ${cls.map((c) =>
        `${esc(c.classification)} · ${esc(c.value)} · ${esc(c.author)}${c.interim ? ' · interim' : ''}${c.review ? ' · <span class="text-state-warn">flagged for review</span>' : ''}`).join(' · ')}`
    : `no authored classifications — nothing set on the Enrichment pane yet`);
  lines.push(w.owner?.value
    ? `Owner · ${esc(w.owner.value)}${w.owner.interim ? ' · interim' : ''}`
    : `Owner · the person who catalogues, as interim`);
  lines.push(w.licence ? `Licence · ${esc(w.licence)}` : `Licence · not confirmed on the Enrichment pane`);
  lines.push(`<span class="tnum">${w.survey_reports_linked || 0}</span> survey report${w.survey_reports_linked === 1 ? '' : 's'} already linked, not copied${
    w.last_published_at ? ` · last <span class="tnum">${esc(ago(w.last_published_at))}</span>` : ''}${
    w.catalogued ? ` · <span class="font-mono">${esc(String(w.asset_guid).slice(0, 8))}…</span> is the asset` : ' · no asset yet'}`);
  return lines.map((l) => `<div class="text-caveat text-ink">${l}</div>`).join('');
}

function curateRecordHtml(rec) {
  if (!rec) return '';
  const tone = { done: 'text-state-ok', failed: 'text-state-warn', running: 'text-accent-ink', skipped: 'text-ink-muted', pending: 'text-ink-muted' };
  const glyph = { done: '✓', failed: '✗', running: '◐', skipped: '○', pending: '○' };
  return `<div class="mt-s2 border-t border-rule pt-s2" data-curate-record="${esc(rec.id)}">
    <div class="text-provenance text-ink-muted">catalogued by ${esc(rec.author)} · <span class="tnum">${esc(ago(rec.requested_at))}</span>
      · ${esc(rec.state)}${rec.state === 'running' || rec.state === 'queued' ? ' · runs in the worker, not here' : ''}</div>
    ${rec.state === 'running' && (rec.steps || []).some((st) => st.state === 'running') ? `<div class="text-caveat text-accent-ink">◐ ${
      esc((rec.steps.find((st) => st.state === 'running') || {}).name)} is running — the survey step takes minutes; this line updates as steps land.</div>` : ''}
    ${(rec.steps || []).map((st) => `<div class="flex items-baseline gap-s2 text-caveat">
      <span class="${tone[st.state] || ''}">${glyph[st.state] || '·'}</span>
      <span class="font-mono text-ink">${esc(st.name)}</span>
      <span class="text-ink-muted">${esc(st.state)}${st.detail ? ` · ${esc(st.detail)}` : ''}</span></div>`).join('')}
  </div>`;
}

export async function renderCurate(slug) {
  const host = $('enrichment-form');
  if (!host) return;
  host.innerHTML = `<div class="text-caveat text-ink-muted">Assembling what the catalogue would learn…</div>`;
  let plan;
  try {
    plan = await getCuratePlan(slug);
  } catch (err) {
    host.innerHTML = `<div class="text-answer text-accent-ink">The plan could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (slug !== state.selectedSlug) return;
  state.curate = state.curate || {};
  const picks = new Set(state.curate.picks || plan.what_it_is.filter((r) => r.candidate && r.state === 'measured' && r.kind !== 'InfrastructureAsset').map((r) => r.kind));
  const subs = plan.what_it_holds.find((r) => r.kind === 'SubResource');
  const subLocators = subs?.detail?.worthy || [];
  const latest = (plan.commits || [])[0];
  const me = (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';

  const draw = () => {
    host.innerHTML = `
      <div class="mb-s2 text-caveat text-ink-muted">
        <span class="text-ink">${esc(plan.technology_type)}</span> · disposition <span class="text-ink">${esc(plan.disposition)}</span>${
          plan.last_surveyed_at ? ` · surveyed <span class="tnum">${esc(ago(plan.last_surveyed_at))}</span>` : ' · never surveyed'}
      </div>
      ${plan.in_population ? '' : `<p class="mb-s3 max-w-[70ch] text-answer text-accent-ink">Only worthy things get curated. Curate's population is
        disposition <em>tracking</em> or <em>using</em>; this one is <em>${esc(plan.disposition)}</em>. Set its disposition (header, or the Disposition
        sub-tab) and this screen commits. Everything below still shows what the catalogue would learn.</p>`}
      ${curateSectionNavHtml()}
      ${curateSectionHtml('curate-sec-what-it-is', CURATE_COLUMNS[0].title,
        `<span class="text-provenance text-ink-muted"><span class="tnum">${picks.size}</span> of <span class="tnum">${plan.what_it_is.filter((r) => r.candidate).length}</span> confirmed</span>
         <span class="text-provenance text-ink-muted">${esc(CURATE_COLUMNS[0].sub)}</span>`,
        (plan.what_it_is || []).map((r) => curateRowHtml(r, picks.has(r.kind), true)).join(''))}
      ${curateSectionHtml('curate-sec-what-holds', CURATE_COLUMNS[1].title,
        `<span class="text-provenance text-ink-muted">${esc(CURATE_COLUMNS[1].sub)}</span>`,
        (plan.what_it_holds || []).map((r) => curateRowHtml(r, picks.has(r.kind), false)).join(''))}
      ${curateSectionHtml('curate-sec-made-of', CURATE_COLUMNS[2].title,
        `<span class="text-provenance text-ink-muted">${esc(CURATE_COLUMNS[2].sub)}</span>`,
        `<div id="component-tree" class="text-caveat text-ink-muted">Reading the components…</div>`)}
      ${curateSectionHtml('curate-sec-blueprints', 'blueprints', '',
        `<div id="blueprint-list"></div>`)}
      ${curateSectionHtml('curate-sec-relates', CURATE_COLUMNS[3].title, '',
        (plan.relates || []).map((r) => curateRowHtml(r, picks.has(r.kind), false)).join(''))}
      ${curateSectionHtml('curate-sec-writes', 'what gets written',
        `<span class="text-provenance text-ink-muted">testimony copied · measurements linked · unresolved things travel</span>`,
        `${curateWritesHtml(plan, [...picks], state.curate.subs === false ? 0 : subLocators.length)}
      <label class="mt-s2 flex cursor-pointer items-baseline gap-s2 text-caveat text-ink">
        <input type="checkbox" data-curate-subs ${state.curate.subs === false ? '' : 'checked'}> include the <span class="tnum">${subLocators.length}</span> worthy sub-resources as contained assets</label>
      <div class="mt-s3 max-w-[70ch] text-caveat text-ink-muted">What keeps it current: ${esc(plan.keeps_current)}</div>
      <div class="mt-s1 max-w-[70ch] text-caveat text-ink-muted">On cataloguing, this repository becomes an asset the rest of Egeria can see. Reversing this needs a correction, which stays on the record.</div>
      <div class="mt-s3 flex items-baseline gap-s3">
        <button type="button" data-curate-go ${plan.in_population && me ? '' : 'disabled'}
          class="rounded-sm border border-accent bg-transparent px-3 py-[3px] text-answer text-accent-ink ${plan.in_population && me ? 'cursor-pointer' : 'opacity-60'}">Catalogue →</button>
        <span class="text-provenance text-ink-muted">${!me ? 'sign in to catalogue — the record needs an author' : !plan.in_population ? 'not in Curate’s population' : 'a queued run; each step reports as it lands'}</span>
      </div>
      ${curateRecordHtml(latest)}
      <div id="catalogue-depth-offer"></div>`)}`;

    bindCurateSectionNav(host);
    host.querySelectorAll('[data-curate-pick]').forEach((c) => c.addEventListener('change', () => {
      if (c.checked) picks.add(c.dataset.curatePick); else picks.delete(c.dataset.curatePick);
      state.curate.picks = [...picks]; draw(); renderComponentTree(slug);
    }));
    host.querySelector('[data-curate-subs]')?.addEventListener('change', (ev) => { state.curate.subs = ev.target.checked; draw(); renderComponentTree(slug); });
    host.querySelectorAll('[data-curate-members]').forEach((b) => b.addEventListener('click', () => {
      openMembers({ slug, analysisId: b.dataset.curateMembers, metric: b.dataset.metric || '', title: b.dataset.curateMembers });
    }));
    host.querySelector('[data-curate-go]')?.addEventListener('click', async (ev) => {
      const b = ev.currentTarget; b.disabled = true;
      // The first step re-surveys before it publishes -- minutes on a large
      // repository, and "nothing obvious happening" was the owner's report
      // from the first live press. Say what is happening, from the record.
      b.textContent = 'Cataloguing… surveying first, then publishing';
      try {
        const out = await curateCommit(slug, {
          confirm: [...picks], sub_resources: state.curate.subs === false ? [] : subLocators, data_files: false,
        });
        plan.commits = [out.curation, ...(plan.commits || [])];
        draw();
        await pollActivity(out.activity_id, { onTick: async () => {
          try {
            const rec = await getCuration(slug, out.curation.id);
            plan.commits[0] = rec;
            const slot = host.querySelector('[data-curate-record]');
            if (slot) slot.outerHTML = curateRecordHtml(rec);
          } catch { /* the next tick will */ }
        } });
        plan.commits[0] = await getCuration(slug, out.curation.id);
        draw();
        renderCatalogueDepthOffer(slug, host);
      } catch (err) {
        b.disabled = false; b.textContent = 'Catalogue →';
        const why = err.status === 401 ? 'sign in to catalogue' : err.status === 409 ? err.message : `not catalogued: ${err.message}`;
        host.querySelector('[data-curate-go]').insertAdjacentHTML('afterend', `<span class="text-caveat text-accent-ink">${esc(why)}</span>`);
      }
    });
  };
  draw();
  renderComponentTree(slug);
  renderBlueprintList(slug);
  renderCatalogueDepthOffer(slug, host);
}

/* ── The layer-2 catalogue-depth offer ────────────────────────────────────
 *
 * DepthOffer's three rules (FUNNEL-COST-RULINGS §3), applied to promoting
 * accepted architecture-recovery verdicts into real Egeria components
 * instead of running never-run analyses (owner's ruling, 2026-09-15, on
 * REPLY-CATALOGUE-IN-LAYERS.md §3):
 *
 *   not a nag   — offered once per catalogue record, in the pane, never a
 *                 modal (the backend refuses a second write on the same
 *                 record; already_decided is the UI's own courtesy check).
 *   not a gate  — layer 1 is already committed by the time this appears;
 *                 nothing here waits on an answer.
 *   not a scold — "N components recovered, M not catalogued" is a fact
 *                 about the record. No imperative sentence; the reader
 *                 decides whether it matters.
 *
 * Unlike DepthOffer, "accepted" here has no per-item choice to make: the
 * accept/reject decision already happens branch by branch in the component
 * tree (recordVerdicts). So the offer's one action is a link that opens the
 * tree, not a queue-in-background button — "choose which" would be asking
 * the reader to redo a decision the tree already offers properly.
 */
async function renderCatalogueDepthOffer(slug, host) {
  const slot = host.querySelector('#catalogue-depth-offer');
  if (!slot) return;
  let offer;
  try { offer = await getCatalogueDepthOffer(slug); } catch { slot.innerHTML = ''; return; }
  if (slug !== state.selectedSlug) return;   // a faster click, or a different resource, won
  if (!offer.layer1_done || offer.already_decided || !offer.remaining_components) { slot.innerHTML = ''; return; }

  const priceLine = () => {
    const c = offer.cost || {};
    if (c.basis !== 'measured') return `<span class="text-ink-muted">${esc(c.sentence || 'not yet measured')}</span>`;
    return `<span class="tnum">${esc(fmtSeconds(c.seconds))}</span> <span class="text-ink-muted">${esc(c.sentence.replace(/^about [^(]+/, '').trim())}</span>`;
  };
  slot.innerHTML = `
    <div data-catalogue-depth-offer class="mt-s3 border-t border-rule pt-s2">
      <div class="text-caveat text-ink"><span class="tnum">${offer.total_components}</span> component${offer.total_components === 1 ? '' : 's'} recovered ·
        <span class="tnum">${offer.remaining_components}</span> not catalogued.</div>
      <div class="mt-s2 flex flex-wrap items-baseline gap-s3 text-caveat">
        <button data-catalogue-depth="accepted" class="cursor-pointer bg-transparent p-0 text-accent-ink underline"
          >catalogue the next layer · <span class="tnum">${offer.remaining_components}</span> component${offer.remaining_components === 1 ? '' : 's'} · ${priceLine()} ›</button>
        <button data-catalogue-depth="declined" class="cursor-pointer bg-transparent p-0 text-provenance text-ink-muted underline">Not now</button>
        <span data-catalogue-depth-status class="text-provenance text-ink-muted"></span>
      </div>
    </div>`;
  const box = slot.querySelector('[data-catalogue-depth-offer]');
  const status = box.querySelector('[data-catalogue-depth-status]');
  const finish = async (outcome) => {
    try {
      await postCatalogueDepthOfferOutcome(slug, offer.curation_id, outcome);
    } catch (err) {
      status.innerHTML = `<span class="text-accent-ink">${
        err.status === 401 ? 'not recorded — sign in to answer the offer' : `not recorded: ${esc(err.message)}`}</span>`;
      return;
    }
    if (outcome === 'declined') {
      box.innerHTML = `<div class="text-provenance text-ink-muted">not now · on the catalogue record</div>`;
    } else {
      box.remove();
      document.getElementById('component-tree')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };
  box.querySelector('[data-catalogue-depth="declined"]').addEventListener('click', () => finish('declined'));
  box.querySelector('[data-catalogue-depth="accepted"]').addEventListener('click', () => finish('accepted'));
}



/* ── Component review at the branch ──────────────────────────────────────
 *
 * The designer's ports round (2026-09-14). Rows are branches of the path
 * the components are keyed by -- kafka's 642 become 71 -- and the decision
 * is made at the branch: a branch verdict inherits, a component's own
 * wins, and an inherited one says so (accepted · with pyegeria/) rather
 * than posing as a decision someone made about that file. Confidence
 * routes; it never hides: the ⚠ count rides on the branch. Grouping nodes
 * stay marked with the classic UI's words. Ports are two words on the row
 * where they exist, nothing where they do not, and one sentence at the
 * foot when a repository declares none, saying what it looked in. Bulk
 * accept goes through the shared preview dialog (rule 4): nothing runs
 * until confirmed. No undo, and the word is not offered -- a verdict is a
 * new row and the trail keeps both; the word is change. */
function verdictBadge(v) {
  if (!v) return `<span class="text-ink-muted">undecided</span>`;
  const word = esc(v.verdict);
  return v.inherited_from
    ? `<span class="text-ink">${word}</span> <span class="text-ink-muted">· with <span class="font-mono">${esc(v.inherited_from)}/</span></span>`
    : `<span class="text-ink">${word}</span>${v.decided_by ? ` <span class="text-ink-muted">· ${esc(v.decided_by)}</span>` : ''}`;
}

/** The column has two shapes (designer, round two): one or two ports are
 *  spelled out -- `8000 in, routes`; three or more become `15 ports ›`,
 *  opening the list in the rail, the way every other count in this app
 *  opens what it counted. `key` names the row so the click can find it. */
function portsWords(n, own, key) {
  if (own && own.length) {
    if (own.length <= 2) return `<span class="text-ink-muted">· ${own.map((p) => `${esc(p.name)}${p.direction ? ` ${esc(p.direction)}` : ''}`).join(', ')}</span>`;
    return `<span class="text-ink-muted">· <button data-ports-open="${esc(key)}" class="cursor-pointer bg-transparent p-0 text-accent-ink underline"><span class="tnum">${own.length}</span> ports${icon('chevron-right', { size: 12 })}</button></span>`;
  }
  return n ? `<span class="text-ink-muted">· <span class="tnum">${n}</span> port${n === 1 ? '' : 's'} declared below</span>` : '';
}

/** The rail: a component's declared ports, read from the artifacts. No
 *  verdict to give -- a port is a line in a Dockerfile. */
function openPortsInRail(slug, key, ports) {
  ensureRailShowing();
  railClaim();
  railFrame('Ports', slug, `
    <div class="mb-s1 text-caps text-chrome-muted"><span class="font-mono">${esc(key)}</span> · read from the deployment artifacts · no verdict to give</div>
    ${ports.map((p) => `<div class="flex items-baseline gap-s2 border-b border-chrome-line-soft py-[3px] text-caps">
      <span class="font-mono text-chrome-ink">${esc(p.name)}</span>
      ${p.direction ? `<span class="text-chrome-muted">${esc(p.direction)}</span>` : ''}
      ${p.protocol ? `<span class="text-chrome-muted">${esc(p.protocol)}</span>` : ''}
    </div>`).join('')}`, { sub: `${ports.length} declared` });
}

function branchRowHtml(b, selected) {
  // The branch's own type leads; the mix beneath it is the CHILDREN's, so
  // a branch whose only typed component is itself does not say it twice.
  const mix = Object.entries(b.types || {}).map(([t, n]) => [t, t === b.type ? n - 1 : n]).filter(([, n]) => n > 0);
  const types = mix.map(([t, n]) => `${esc(t)}${n > 1 ? ` <span class="tnum">×${n}</span>` : ''}`).join(', ');
  return `<div class="border-b border-rule py-[5px]" data-branch="${esc(b.path)}">
    <div class="flex flex-wrap items-baseline gap-x-s2 gap-y-[2px]">
      <input type="checkbox" data-branch-select="${esc(b.path)}" ${selected ? 'checked' : ''}
        aria-label="select ${esc(b.name)}" class="shrink-0 cursor-pointer">
      <button data-branch-open="${esc(b.path)}" class="cursor-pointer bg-transparent p-0 font-mono text-caveat text-ink">${esc(b.name)}/${icon('chevron-right', { size: 12 })}</button>
      <span class="text-provenance text-ink-muted">· <span class="tnum">${b.components}</span> component${b.components === 1 ? '' : 's'}</span>
      ${b.grouping_only ? `<span class="text-provenance text-ink-muted">· grouping only — a directory that holds components, not a component itself</span>` : b.type ? `<span class="text-provenance text-ink-muted">· ${esc(b.type)}</span>` : ''}
      ${types ? `<span class="text-provenance text-ink-muted">· ${types}</span>` : ''}
      ${b.low_confidence ? `<span class="text-provenance text-state-warn">· ⚠ <span class="tnum">${b.low_confidence}</span> at or below 50%</span>` : ''}
      ${portsWords(b.ports, b.own_ports, b.path)}
    </div>
    <div class="mt-[2px] flex flex-wrap items-baseline gap-x-s3 text-provenance">
      <span>${verdictBadge(b.verdict)}</span>
      <span class="text-ink-muted"><span class="tnum">${b.accepted}</span> accepted · <span class="tnum">${b.rejected}</span> rejected · <span class="tnum">${b.undecided}</span> undecided</span>
      <button data-branch-verdict="accepted" data-scope="${esc(b.path)}" class="cursor-pointer bg-transparent p-0 text-accent-ink underline">accept all ${b.components}</button>
      <button data-branch-verdict="rejected" data-scope="${esc(b.path)}" class="cursor-pointer bg-transparent p-0 text-ink-muted underline">reject all</button>
    </div>
    <div data-branch-leaves hidden class="mt-s1 pl-s3"></div>
  </div>`;
}

/** RULING-WHAT-A-VERDICT-IS-ABOUT.md §2a/§2b/§2c. When two extractors
 *  currently propose this path, both are shown -- not whichever wrote last
 *  -- with the agreement line that is the strongest signal the recovery
 *  has. `withdrawn_by` flags an accepted verdict whose extractor no longer
 *  proposes the path; it never invalidates the verdict itself. `run_label`
 *  ("detect"/"coupling") renders as "found by"; `perspective` (physical/
 *  deployment/logical/dev) renders as "reading" -- two different axes that
 *  used to share one word (§0). */
function leafRowHtml(l) {
  const multi = (l.proposals || []).length >= 2;
  const proposalLines = multi ? l.proposals.map((p) => `
    <div class="pl-s2 text-provenance text-ink-muted">found by ${esc(p.run_label)}${p.type ? ` — ${esc(p.type)}` : ''} · ${esc(p.perspective || 'physical')} reading · <span class="tnum">${p.confidence ?? 0}</span>%</div>
  `).join('') : '';
  const agreementLine = l.agreement
    ? `<div class="pl-s2 text-provenance text-accent-ink">two extractors agree this is a component</div>` : '';
  const withdrawnLine = (l.withdrawn_by || []).length
    ? `<div class="pl-s2 text-provenance text-state-warn">⚠ review — no longer proposed by ${esc(l.withdrawn_by.join(', '))}</div>` : '';
  return `<div class="flex flex-col gap-[1px] border-b border-rule py-[3px]">
    <div class="flex flex-wrap items-baseline gap-x-s2 text-provenance">
      <span class="font-mono text-ink">${esc(l.path.split('/').pop())}</span>
      ${!multi && l.type ? `<span class="text-ink-muted">· ${esc(l.type)}</span>` : ''}
      ${!multi && (l.low_confidence ? `<span class="text-state-warn">· ⚠ <span class="tnum">${l.confidence ?? 0}</span>%</span>` : l.confidence != null ? `<span class="text-ink-muted">· <span class="tnum">${l.confidence}</span>%</span>` : '')}
      ${l.ports?.length ? portsWords(0, l.ports, l.path) : ''}
      <span>· ${verdictBadge(l.verdict)}</span>
      <button data-leaf-verdict="accepted" data-scope="${esc(l.path)}" class="cursor-pointer bg-transparent p-0 text-accent-ink underline">${(l.verdict || {}).verdict ? 'change' : 'accept'}</button>
      <button data-leaf-verdict="rejected" data-scope="${esc(l.path)}" class="cursor-pointer bg-transparent p-0 text-ink-muted underline">reject</button>
    </div>
    ${proposalLines}${agreementLine}${withdrawnLine}
  </div>`;
}

/** A branch's leaves grouped by scope-hierarchy cluster (designer, 2026-09-17
 *  — see the addendum in docs/design-notes/ITEM-3-CURATE-IMPLEMENTED.md).
 *  `packages/` alone held 64 of 69 components as one flat list; the same
 *  clustering that already groups the blueprints panel's "scope-hierarchy ·
 *  collection" rows (`component_tree.group_leaves`, reading `scope_hierarchy.
 *  derive()`) turns that into ~8 groups of ~10 here too. Default OPEN when
 *  the group still has undecided work, default CLOSED once it is fully
 *  decided — the depth-1 accepted signal a reader used to get from the flat
 *  list is still here, just per-group instead of per-branch. */
function leafGroupHtml(g) {
  const open = g.undecided > 0;
  return `<details class="border-b border-rule py-[3px]" ${open ? 'open' : ''}>
    <summary class="cursor-pointer text-provenance">
      <span class="font-mono text-ink">${esc(g.name)}/</span>
      <span class="text-ink-muted">· <span class="tnum">${g.accepted}</span> accepted ·
        <span class="tnum">${g.rejected}</span> rejected · <span class="tnum">${g.undecided}</span> undecided</span>
    </summary>
    <div class="pl-s3">${g.members.map(leafRowHtml).join('')}</div>
  </details>`;
}

/** The tree's own checkbox selection (SPEC-CURATE-SELECTION-AND-BLUEPRINTS.md
 *  §1). No select-mode toggle -- the spec is explicit that the tree's rows
 *  are already a work queue, unlike the sidebar's navigation rows, so the
 *  checkboxes are simply present. Keyed per-slug so switching resources does
 *  not carry a stale selection into a different repository's tree. */
function curateSelectionSet(slug) {
  if (!state.curateSelection || state.curateSelection.slug !== slug) {
    state.curateSelection = { slug, paths: new Set() };
  }
  return state.curateSelection.paths;
}

function selectionBarHtml(selected, shown, total) {
  if (!total) return '';
  const selectedShown = shown.filter((b) => selected.has(b.path)).length;
  const overflow = selected.size > selectedShown ? selected.size - selectedShown : 0;
  return `<div class="mb-s1 flex flex-wrap items-baseline gap-s3 text-provenance">
    <label class="flex cursor-pointer items-baseline gap-[5px] text-ink-muted">
      <input type="checkbox" data-select-all-shown ${shown.length && selectedShown === shown.length ? 'checked' : ''}>
      select all shown</label>
    ${total > shown.length ? `<button data-select-all-matching class="cursor-pointer bg-transparent p-0 text-accent-ink underline"
        >select all <span class="tnum">${total}</span> branches${icon('chevron-right', { size: 12 })}</button>` : ''}
    <span class="text-ink-muted"><span class="tnum">${selectedShown}</span> of <span class="tnum">${shown.length}</span> shown selected${
      overflow ? ` · <span class="tnum">${selected.size}</span> selected in total` : ''}</span>
    ${selected.size ? `<button data-selection-verdict="accepted" class="cursor-pointer bg-transparent p-0 text-accent-ink underline"
        >accept <span class="tnum">${selected.size}</span> selected</button>
      <button data-selection-verdict="rejected" class="cursor-pointer bg-transparent p-0 text-ink-muted underline"
        >reject <span class="tnum">${selected.size}</span></button>
      <button data-selection-clear class="cursor-pointer bg-transparent p-0 text-ink-muted underline">clear</button>` : ''}
  </div>`;
}

async function renderComponentTree(slug, prefix = '') {
  const host = $('component-tree');
  if (!host) return;
  let tree;
  try { tree = await getComponentTree(slug, prefix); }
  catch (err) { host.innerHTML = `<span class="text-accent-ink">The components could not be read: ${esc(err.message)}</span>`; return; }
  if (slug !== state.selectedSlug) return;
  const me = (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
  if (!tree.branches.length) {
    host.innerHTML = `<div class="text-caveat text-ink-muted">No components recovered on this resource yet.</div>
      ${tree.topology ? `<div class="mt-s1 text-provenance text-ink-muted">${esc(tree.topology)}</div>` : ''}`;
    return;
  }
  const selected = curateSelectionSet(slug);
  const sort = state.componentSort || 'size';
  const rows = [...tree.branches];
  // A sort, never a filter: the ⚠ count already rides on the branch, so
  // ordering by confidence puts the weakest clusters first without hiding
  // one. By size is the repository's own shape.
  //
  // Agreement outranks a single high confidence (RULING-WHAT-A-VERDICT-IS-
  // ABOUT.md §2b) — two independent extractors landing on the same path is
  // a better bet than one extractor at 90%, so it sorts first, confidence
  // only breaking ties within the same agreement count.
  if (sort === 'confidence') rows.sort((a, b) => (b.agreement_count || 0) - (a.agreement_count || 0)
    || (a.min_confidence ?? 101) - (b.min_confidence ?? 101) || b.low_confidence - a.low_confidence);
  const shown = state.componentShowAll ? rows : rows.slice(0, 8);
  host.innerHTML = `
    <div class="mb-s1 text-provenance text-ink-muted"><span class="tnum">${tree.accepted}</span> of <span class="tnum">${tree.total_components}</span> component paths accepted ·
      <span class="tnum">${tree.reviewed}</span> with a verdict of their own · <span class="tnum">${tree.branches.length}</span> branches ·
      ports and wires read from the deployment artifacts; the diagram shows those belonging to accepted components
      ${me ? '' : ' · <span class="text-accent-ink">sign in to record a verdict</span>'}
      · sort <button data-tree-sort="size" class="cursor-pointer bg-transparent p-0 ${sort === 'size' ? 'text-ink' : 'text-accent-ink underline'}">by size</button>
      / <button data-tree-sort="confidence" class="cursor-pointer bg-transparent p-0 ${sort === 'confidence' ? 'text-ink' : 'text-accent-ink underline'}">by confidence</button></div>
    ${selectionBarHtml(selected, shown, rows.length)}
    ${shown.map((b) => branchRowHtml(b, selected.has(b.path))).join('')}
    ${!state.componentShowAll && rows.length > 8 ? `<div class="py-[5px] text-provenance"><button data-tree-more class="cursor-pointer bg-transparent p-0 text-accent-ink underline">and <span class="tnum">${rows.length - 8}</span> more branches${icon('chevron-right', { size: 12 })}</button></div>` : ''}
    ${tree.topology ? `<div class="mt-s2 text-provenance text-ink-muted">${esc(tree.topology)}</div>` : ''}
    ${tree.topology_totals ? `<div class="mt-s2 text-provenance text-ink-muted">${tnum(esc(tree.topology_totals))}</div>` : ''}
    <div id="component-tree-status" class="mt-s1 text-provenance text-ink-muted"></div>
    <div id="component-diagram" class="mt-s3"></div>`;
  host.querySelectorAll('[data-tree-sort]').forEach((b) => b.addEventListener('click', () => { state.componentSort = b.dataset.treeSort; renderComponentTree(slug, prefix); }));
  host.querySelector('[data-tree-more]')?.addEventListener('click', () => { state.componentShowAll = true; renderComponentTree(slug, prefix); });
  host.querySelectorAll('[data-ports-open]').forEach((b) => b.addEventListener('click', () => {
    const br = tree.branches.find((x) => x.path === b.dataset.portsOpen);
    if (br) openPortsInRail(slug, br.path, br.own_ports || []);
  }));
  renderComponentDiagram(slug, $('component-diagram'));

  host.querySelectorAll('[data-branch-select]').forEach((c) => c.addEventListener('change', () => {
    if (c.checked) selected.add(c.dataset.branchSelect); else selected.delete(c.dataset.branchSelect);
    renderComponentTree(slug, prefix);
  }));
  host.querySelector('[data-select-all-shown]')?.addEventListener('change', (ev) => {
    shown.forEach((b) => { if (ev.target.checked) selected.add(b.path); else selected.delete(b.path); });
    renderComponentTree(slug, prefix);
  });
  // "select all matching" acts on the FULL set at this level (`rows`), not
  // just the 8 shown by default -- and the button already named the total
  // before this click, so the act does not surprise (rule 4).
  host.querySelector('[data-select-all-matching]')?.addEventListener('click', () => {
    rows.forEach((b) => selected.add(b.path));
    renderComponentTree(slug, prefix);
  });
  host.querySelector('[data-selection-clear]')?.addEventListener('click', () => { selected.clear(); renderComponentTree(slug, prefix); });
  host.querySelector('[data-selection-verdict="accepted"]')?.addEventListener('click', () => {
    const paths = [...selected];
    const picked = tree.branches.filter((b) => paths.includes(b.path));
    recordVerdicts(slug, paths, 'accepted', {
      count: picked.reduce((n, b) => n + (b.components || 0), 0),
      low: picked.reduce((n, b) => n + (b.low_confidence || 0), 0),
      exists: picked.reduce((n, b) => n + (b.accepted || 0), 0),
    }, () => { selected.clear(); });
  });
  host.querySelector('[data-selection-verdict="rejected"]')?.addEventListener('click', () => {
    recordVerdicts(slug, [...selected], 'rejected', { count: 0, low: 0 }, () => { selected.clear(); });
  });

  host.querySelectorAll('[data-branch-open]').forEach((b) => b.addEventListener('click', async () => {
    const box = host.querySelector(`[data-branch="${CSS.escape(b.dataset.branchOpen)}"] [data-branch-leaves]`);
    if (!box) return;
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false; box.innerHTML = `<span class="text-provenance text-ink-muted">reading…</span>`;
    try {
      const out = await getComponentLeaves(slug, b.dataset.branchOpen);
      // Grouped by scope-hierarchy cluster when the backend found groups
      // worth having (`group_leaves`'s own MIN_GROUP=2 rule); ungrouped
      // leaves — a group of one collapses nothing — render plainly, same as
      // before this restructuring. A branch with no groups at all (small
      // branches, same as always) falls back to the flat list.
      const groups = out.groups || [];
      const ungrouped = out.ungrouped || out.leaves;
      box.innerHTML = (groups.map(leafGroupHtml).join('') + ungrouped.map(leafRowHtml).join(''))
        || `<span class="text-provenance text-ink-muted">nothing under this branch</span>`;
      box.querySelectorAll('[data-leaf-verdict]').forEach((lb) => lb.addEventListener('click', () =>
        recordVerdicts(slug, [lb.dataset.scope], lb.dataset.leafVerdict, { count: 1, low: 0 })));
      box.querySelectorAll('[data-ports-open]').forEach((pb) => pb.addEventListener('click', () => {
        const leaf = out.leaves.find((x) => x.path === pb.dataset.portsOpen);
        if (leaf) openPortsInRail(slug, leaf.path, leaf.ports || []);
      }));
    } catch (err) {
      box.innerHTML = `<span class="text-provenance text-accent-ink">could not read: ${esc(err.message)}</span>`;
    }
  }));
  host.querySelectorAll('[data-branch-verdict]').forEach((b) => b.addEventListener('click', () => {
    const br = tree.branches.find((x) => x.path === b.dataset.scope);
    recordVerdicts(slug, [b.dataset.scope], b.dataset.branchVerdict, { count: br?.components || 0, low: br?.low_confidence || 0, exists: br?.accepted || 0 });
  }));
}

/* ── Blueprints ───────────────────────────────────────────────────────────
 *
 * SPEC-CURATE-SELECTION-AND-BLUEPRINTS.md §2/§3/§4. A candidate blueprint is
 * clustering.py's proposal that a group of components forms a cohesive unit;
 * accepting one materialises a real Egeria SolutionBlueprint
 * (blueprint_materializer.py). "0 of 12 clusters in the logical reading
 * reviewed" was already the coverage sentence on this pane -- this is the
 * screen that count opens onto, since a count that opens nothing is the one
 * thing this app does not do.
 *
 * A cluster is keyed `perspective::cluster_name` and exists in exactly one
 * READING (RULING-WHAT-A-VERDICT-IS-ABOUT.md §0 renamed `Component.
 * perspective` to "reading" precisely so this would not read as the same
 * axis as the diagram's "found by" or the chrome's Perspective filter -- all
 * three used to share the one word "perspective"). So this list is scoped to
 * ONE reading at a time, says so at its head, and switching readings
 * REPLACES the list outright rather than diffing it against the last one. */

/** The blueprint's own verdict, rendered the same shape as a component's
 *  `verdictBadge` -- but a blueprint verdict never inherits (it has no
 *  ancestor scope the way a path does) and has no "retyped" outcome
 *  (BLUEPRINT_VERDICTS has no equivalent free-text field to correct). */
function blueprintVerdictBadge(v) {
  if (!v) return `<span class="text-ink-muted">undecided</span>`;
  return `<span class="text-ink">${esc(v.verdict)}</span>${v.decided_at ? ` <span class="text-ink-muted">· ${esc(ago(v.decided_at))}</span>` : ''}`;
}

/** SPEC §4, the hard requirement: accepting a blueprint materialises the
 *  SolutionBlueprint element itself, but blueprint_materializer.py does NOT
 *  attach members as a synchronous part of that write -- workflows/curate.py's
 *  materialize_blueprint_if_accepted queues them onto the outbox instead
 *  (egeria_outbox.enqueue_blueprint_members), which drains later, on its own
 *  schedule, and this pane has no record of whether a given queue row has
 *  actually landed as a real CollectionMembership by the time anyone reads
 *  this screen again. So the honest claim is narrower than "linked" and
 *  narrower than "not built" both: not-yet-confirmed-linked, counted.
 *
 *  "Accepted component" here means a member/child that itself has a
 *  materialized Egeria element (`member_status[].materialized`) -- the same
 *  fact `resolve_member_guids` requires before it will even attempt to
 *  enqueue that member's attachment (Decision 2: accepting a blueprint does
 *  NOT implicitly accept or materialize its members). A member with no
 *  verdict of its own, or an accepted-but-unmaterialized one, is not counted
 *  here -- it was never a membership candidate in the first place. */
function membershipHonestyLine(bp) {
  const materializedMembers = (bp.member_status || []).filter((m) => m.materialized).length;
  const materializedChildren = (bp.child_status || []).filter((c) => c.materialized).length;
  const total = materializedMembers + materializedChildren;
  if (!total) {
    return `<div class="text-caveat text-ink-muted">its members are not yet linked — none of its proposed members are catalogued as their own Egeria elements yet, so there is nothing to link</div>`;
  }
  const parts = [];
  if (materializedMembers) parts.push(`<span class="tnum">${materializedMembers}</span> accepted component${materializedMembers === 1 ? '' : 's'}`);
  if (materializedChildren) parts.push(`<span class="tnum">${materializedChildren}</span> child blueprint${materializedChildren === 1 ? '' : 's'}`);
  return `<div class="text-caveat text-ink-muted">its members are not yet confirmed linked — <button data-blueprint-standapart="${esc(bp.perspective)}::${esc(bp.cluster_name)}"
    class="cursor-pointer bg-transparent p-0 text-accent-ink underline">${parts.join(' and ')} stand apart${icon('chevron-right', { size: 12 })}</button></div>`;
}

function blueprintRowHtml(bp) {
  const v = bp.verdict;
  const accepted = v?.verdict === 'accepted';
  const rejected = v?.verdict === 'rejected';
  const memberCount = (bp.members || []).length;
  const acceptedMembers = (bp.member_status || []).filter((m) => (m.verdict || {}).verdict === 'accepted').length;
  const why = [bp.signal, bp.carrier].filter(Boolean).join(' · ');
  return `<div class="border-b border-rule py-s2" data-blueprint="${esc(bp.perspective)}::${esc(bp.cluster_name)}">
    <div class="flex flex-wrap items-baseline gap-x-s2 gap-y-[2px]">
      <span class="font-mono text-answer text-ink">${esc(bp.cluster_name)}</span>
      ${bp.oversized ? `<span class="text-provenance text-state-warn">· ⚠ oversized (target <span class="tnum">${bp.target_size ?? '?'}</span>)</span>` : ''}
      ${why ? `<span class="text-provenance text-ink-muted">· ${esc(why)}</span>` : ''}
      <span class="text-provenance text-ink-muted">· <button data-blueprint-members="${esc(bp.perspective)}::${esc(bp.cluster_name)}"
        class="cursor-pointer bg-transparent p-0 text-accent-ink underline"><span class="tnum">${acceptedMembers}</span> of <span class="tnum">${memberCount}</span> members accepted${icon('chevron-right', { size: 12 })}</button></span>
    </div>
    <div class="mt-[2px] flex flex-wrap items-baseline gap-x-s3 text-provenance">
      <span>${blueprintVerdictBadge(v)}</span>
      <button data-blueprint-verdict="accepted" data-key="${esc(bp.perspective)}::${esc(bp.cluster_name)}" class="cursor-pointer bg-transparent p-0 text-accent-ink underline">${accepted ? 'change' : 'accept'}</button>
      <button data-blueprint-verdict="rejected" data-key="${esc(bp.perspective)}::${esc(bp.cluster_name)}" class="cursor-pointer bg-transparent p-0 text-ink-muted underline">reject</button>
    </div>
    ${accepted
      ? (bp.materialized
          ? `<div class="mt-[2px] text-caveat text-ink">catalogued as a Solution Blueprint · <span class="font-mono">${esc((bp.materialized.guid || '').slice(0, 8))}…</span></div>
             ${membershipHonestyLine(bp)}`
          : `<div class="mt-[2px] text-caveat text-accent-ink">accepted, but not yet catalogued in Egeria — the write may not have completed; re-accepting will retry</div>`)
      : rejected ? `<div class="mt-[2px] text-caveat text-ink-muted">rejected · nothing created</div>` : ''}
  </div>`;
}

/** The rail: one cluster's members/children, each with its own verdict and
 *  materialization state -- what "N members" or "N stand apart" opens onto,
 *  the same "a count opens what it counted" rule every other rail here
 *  follows. */
function openBlueprintMembersInRail(slug, bp, { standApartOnly = false } = {}) {
  ensureRailShowing();
  railClaim();
  let members = (bp.member_status || []).map((m) => ({ ...m, kind: 'component' }));
  let children = (bp.child_status || []).map((c) => ({ ...c, kind: 'blueprint', slug: c.cluster_name }));
  if (standApartOnly) {
    members = members.filter((m) => m.materialized);
    children = children.filter((c) => c.materialized);
  }
  const rows = [...members, ...children];
  railFrame('Members', slug, `
    <div class="mb-s1 text-caps text-chrome-muted">${esc(bp.cluster_name)} · ${esc(bp.perspective)} reading${standApartOnly ? ' · catalogued but not confirmed linked to the blueprint' : ''}</div>
    ${rows.length ? rows.map((m) => `<div class="flex items-baseline gap-s2 border-b border-chrome-line-soft py-[3px] text-caps">
      <span class="font-mono text-chrome-ink">${esc(m.slug)}</span>
      <span class="text-chrome-muted">${m.kind === 'blueprint' ? 'child blueprint' : 'component'}</span>
      <span class="text-chrome-muted">${m.verdict ? esc(m.verdict.verdict) : 'undecided'}</span>
      <span class="text-chrome-muted">${m.materialized ? 'catalogued in Egeria' : 'not catalogued'}</span>
    </div>`).join('') : `<div class="text-caps text-chrome-muted">nothing to show</div>`}`,
    { sub: `${rows.length} of ${(bp.member_status || []).length + (bp.child_status || []).length}` });
}

function blueprintReadingKey(slug) {
  if (!state.blueprintReading || state.blueprintReading.slug !== slug) {
    state.blueprintReading = { slug, reading: null };
  }
  return state.blueprintReading;
}

async function renderBlueprintList(slug) {
  const host = $('blueprint-list');
  if (!host) return;
  let data;
  try { data = await getComponentBlueprints(slug); }
  catch (err) { host.innerHTML = `<span class="text-accent-ink">The blueprints could not be read: ${esc(err.message)}</span>`; return; }
  if (slug !== state.selectedSlug) return;
  const { blueprints, perspectives } = data;
  if (!perspectives.length) { host.innerHTML = ''; return; }
  const rk = blueprintReadingKey(slug);
  if (!rk.reading || !perspectives.includes(rk.reading)) rk.reading = perspectives[0];
  const reading = rk.reading;
  const inReading = blueprints.filter((bp) => bp.perspective === reading);
  const others = perspectives.filter((p) => p !== reading)
    .map((p) => ({ p, n: blueprints.filter((bp) => bp.perspective === p).length }));
  // §3: replaced outright on every render, never diffed against the
  // previous reading's rows -- this function is always called with a fresh
  // innerHTML assignment, so there is no patch step to accidentally add.
  host.innerHTML = `
    <div class="mb-s1 mt-s3 flex items-baseline gap-s2 border-b border-rule pb-[3px]">
      <span class="font-heading text-name font-normal text-ink">blueprints</span>
      <span class="text-provenance text-ink-muted">clusters clustering.py proposed as a cohesive unit, in the ${esc(reading)} reading</span>
    </div>
    <p class="mb-s2 max-w-[70ch] text-caveat text-ink-muted">A verdict here is recorded against <span class="font-mono">${esc(reading)}::cluster name</span>
      and applies in this reading only — switching readings shows a different set, not the same set re-judged.</p>
    ${inReading.length ? inReading.map(blueprintRowHtml).join('') : `<div class="text-caveat text-ink-muted">No candidate blueprints proposed in the ${esc(reading)} reading.</div>`}
    <div class="mt-s2 text-provenance text-ink-muted"><span class="tnum">${inReading.length}</span> of <span class="tnum">${inReading.length}</span> clusters shown · all in the <span class="text-ink">${esc(reading)}</span> reading
      ${others.map((o) => ` · <button data-blueprint-reading="${esc(o.p)}" class="cursor-pointer bg-transparent p-0 text-accent-ink underline">the ${esc(o.p)} reading has <span class="tnum">${o.n}</span>${icon('chevron-right', { size: 12 })}</button>`).join('')}</div>
    <div id="blueprint-status" class="mt-s1 text-provenance text-ink-muted"></div>`;

  host.querySelectorAll('[data-blueprint-reading]').forEach((b) => b.addEventListener('click', () => {
    rk.reading = b.dataset.blueprintReading;
    renderBlueprintList(slug);
  }));
  host.querySelectorAll('[data-blueprint-members]').forEach((b) => b.addEventListener('click', () => {
    const bp = inReading.find((x) => `${x.perspective}::${x.cluster_name}` === b.dataset.blueprintMembers);
    if (bp) openBlueprintMembersInRail(slug, bp);
  }));
  host.querySelectorAll('[data-blueprint-standapart]').forEach((b) => b.addEventListener('click', () => {
    const bp = inReading.find((x) => `${x.perspective}::${x.cluster_name}` === b.dataset.blueprintStandapart);
    if (bp) openBlueprintMembersInRail(slug, bp, { standApartOnly: true });
  }));
  host.querySelectorAll('[data-blueprint-verdict]').forEach((b) => b.addEventListener('click', () => {
    const bp = inReading.find((x) => `${x.perspective}::${x.cluster_name}` === b.dataset.key);
    if (bp) recordBlueprintVerdict(slug, bp, b.dataset.blueprintVerdict);
  }));
}

/** Same shared-preview-dialog rule as `recordVerdicts` (rule 4): accepting a
 *  cluster materialises a real Egeria SolutionBlueprint, so it names that
 *  before it does it. Rejecting creates nothing, so it records at once. */
function recordBlueprintVerdict(slug, bp, verdict) {
  const status = $('blueprint-status');
  const go = async () => {
    if (status) status.textContent = 'recording…';
    try {
      await postBlueprintVerdict(slug, bp.perspective, bp.cluster_name, verdict);
      renderBlueprintList(slug);
    } catch (err) {
      if (status) status.innerHTML = `<span class="text-accent-ink">not recorded${err.status === 401 ? ' — sign in to record a verdict' : err.status === 403 ? ' — you may not curate this element' : `: ${esc(err.message)}`}</span>`;
    }
  };
  if (verdict !== 'accepted') { go(); return; }
  const el = openDialog('Accept a blueprint', `${bp.perspective}::${bp.cluster_name}`);
  const body = el.querySelector('#wl-detail-body');
  const memberCount = (bp.members || []).length;
  body.innerHTML = `
    <p class="text-caveat text-ink">Catalogues <span class="font-mono">${esc(bp.cluster_name)}</span> as a real Egeria <span class="font-mono">SolutionBlueprint</span> —
      the type is pinned (SPEC-CURATE-SELECTION-AND-BLUEPRINTS.md §0), unlike an individual component's.</p>
    <p class="text-caveat text-ink-muted">${memberCount ? `<span class="tnum">${memberCount}</span> proposed member${memberCount === 1 ? '' : 's'}, but this does not accept or materialize them —
      only members already accepted and catalogued on their own get queued to link, and that queue is not confirmed done by the time this pane reads it back.` : 'This cluster has no proposed members.'}</p>
    <p class="text-caveat text-ink-muted">A verdict is a new row; changing it later is another row, and the trail keeps both.</p>
    <div class="mt-s3 flex gap-s3">
      <button data-act="confirm" class="cursor-pointer rounded-sm border border-accent bg-transparent px-3 py-[3px] text-answer text-accent-ink">Accept</button>
      <button data-act="close" class="cursor-pointer bg-transparent p-0 text-provenance text-ink-muted underline">not now</button>
    </div>`;
  body.querySelector('[data-act="confirm"]').addEventListener('click', () => { closeCellDetail(); go(); });
}

/** The diagram beside the tree. It is already verdict-aware -- rendered
 *  fresh on every read, rejected dropped, accepted solid, undecided dashed
 *  -- so accepting a branch and re-reading redraws it; nothing to build for
 *  that. What it is not is the acting surface: it comes back from Kroki as
 *  a finished SVG. It says its two ceilings in its own caption. The tree
 *  is the surface that scales; the diagram is the one that explains. */
async function renderComponentDiagram(slug, host) {
  if (!host) return;
  let fact;
  try {
    const res = await getBulkFacts([slug], ['architecture_diagram']);
    fact = (((res.subjects || {})[slug]) || []).find((f) => f.analysis_id === 'architecture_diagram');
  } catch { fact = null; }
  if (slug !== state.selectedSlug) return;
  const src = fact?.value?.mermaid;
  if (!src) { host.innerHTML = `<div class="text-provenance text-ink-muted">No diagram to read — architecture_diagram has not rendered one for this resource.</div>`; return; }
  // Which extractor drew this, and what else is on file — a value the
  // classic Curate panel already showed and this surface silently dropped.
  // RULING-WHAT-A-VERDICT-IS-ABOUT.md §3: `fact.value.perspective` here is a
  // run_label ("detect"/"coupling"), not a Component.perspective reading, so
  // it renders as "found by", never "perspective".
  const foundBy = fact.value.perspective
    ? `<div class="text-provenance text-ink-muted mt-s1">found by ${esc(fact.value.perspective)}` +
      ((fact.value.other_perspectives_available || []).length
        ? ` · ${esc(fact.value.other_perspectives_available.join(', '))} also on file`
        : '') + `</div>`
    : '';
  host.innerHTML = `<div class="mb-s1 text-caps uppercase tracking-caps text-ink">The diagram reads; the tree acts</div>
    <div class="text-provenance text-ink-muted">${tnum(esc(fact.value.caption || fact.headline || ''))}</div>
    ${foundBy}
    <div data-diagram-svg class="mt-s1 w-full overflow-auto rounded-sm border border-rule-strong" style="max-height:min(60vh,560px)">rendering…</div>`;
  try {
    const t = tokens();
    const prepped = mermaidForKroki(src);
    const res = await fetch('/api/diagrams/mermaid', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: prepped.source }) });
    if (!res.ok) throw new Error(`${res.status} from the renderer`);
    const raw = await res.text();
    if (!raw.includes('<svg')) throw new Error('the renderer returned no SVG');
    const slot = host.querySelector('[data-diagram-svg]');
    slot.innerHTML = raw;
    const svgEl = slot.querySelector('svg');
    if (svgEl) { themeSvgElement(svgEl, t); svgEl.removeAttribute('height'); svgEl.style.maxWidth = '100%'; svgEl.style.height = 'auto'; }
  } catch (err) {
    const slot = host.querySelector('[data-diagram-svg]');
    if (slot) slot.innerHTML = `<div class="p-s2 text-provenance text-accent-ink">The diagram could not be rendered: ${esc(err.message)}. The source is on the Analysis pane.</div>`;
  }
}

/** The shared preview dialog, because rule 4 makes it mandatory: the act
 *  names what it would do before it does it. Rejecting creates nothing in
 *  Egeria, so it records at once.
 *
 *  `scopes` may be several branches at once (the tree's own multi-select,
 *  SPEC-CURATE-SELECTION-AND-BLUEPRINTS.md §1) -- the confirmation states
 *  the TOTAL scope count across every selected branch before acting ("two
 *  branches selected — 20 scopes total"), not just that an action ran.
 *  `onDone` (optional) fires once the verdicts are recorded -- the
 *  selection-clearing callback, so a selection is not left checked against
 *  branches that were just acted on. */
function recordVerdicts(slug, scopes, verdict, { count, low, exists = 0 }, onDone) {
  const status = $('component-tree-status');
  const go = async () => {
    if (status) status.textContent = 'recording…';
    try {
      const out = await postBranchVerdicts(slug, scopes, verdict);
      if (status) status.innerHTML = verdict === 'accepted'
        ? `<span class="text-state-ok">→ <span class="tnum">${out.verdicts.length}</span> verdict${out.verdicts.length === 1 ? '' : 's'} recorded · <span class="tnum">${out.queued ?? 0}</span> component${out.queued === 1 ? '' : 's'} queued for Egeria — the pane does not wait</span>`
        : `<span class="text-state-ok">→ rejected · nothing created</span>`;
      onDone?.();
      renderComponentTree(slug);
    } catch (err) {
      if (status) status.innerHTML = `<span class="text-accent-ink">not recorded${err.status === 401 ? ' — sign in to record a verdict' : err.status === 403 ? ' — you may not curate this element' : `: ${esc(err.message)}`}</span>`;
    }
  };
  if (verdict !== 'accepted' || count <= 1) { go(); return; }
  const scopeLabel = scopes.length > 1
    ? `${scopes.length} branches selected — ${count} scope${count === 1 ? '' : 's'} total`
    : `${scopes.join(', ')} · ${count} component${count === 1 ? '' : 's'}`;
  const el = openDialog('Accept at the branch', scopeLabel);
  const body = el.querySelector('#wl-detail-body');
  body.innerHTML = `
    <p class="text-caveat text-ink"><span class="tnum">${count}</span> components${low ? `, <span class="tnum">${low}</span> of them at or below 50% confidence` : ''}.
      <span class="tnum">${Math.max(0, count - exists)}</span> will be created as software components in Egeria — the exact Egeria type is not yet pinned${exists ? `; <span class="tnum">${exists}</span> already accepted` : '; none exist yet'}.</p>
    <p class="text-caveat text-ink-muted">Publish time for component creation is not yet measured — the first branch is what fixes it. Queued, so the pane returns at once. Nothing runs until you confirm.</p>
    <p class="text-caveat text-ink-muted">A verdict is a new row; changing it later is another row, and the trail keeps both.</p>
    <div class="mt-s3 flex gap-s3">
      <button data-act="confirm" class="cursor-pointer rounded-sm border border-accent bg-transparent px-3 py-[3px] text-answer text-accent-ink">Accept ${count}</button>
      <button data-act="close" class="cursor-pointer bg-transparent p-0 text-provenance text-ink-muted underline">not now</button>
    </div>`;
  body.querySelector('[data-act="confirm"]').addEventListener('click', () => { closeCellDetail(); go(); });
}
