/* Analysis.
 *
 * PLAN-FINISH-REPOS.md item 11: Analysis is now `built: true` in app.js's
 * `STAGES` array. It needed no bespoke renderer -- the generic
 * Questions-checklist engine (`loadPane()` in app.js) already reaches it
 * correctly, the same as Scouting/Enrichment/Curate, because the catalog
 * carries 11 real Analysis-tagged questions (question_catalog.yaml) backed
 * by 11 `intent: analysis` analyses (analysis_catalog.yaml) -- see
 * docs/design-notes/ITEM-11-DISCOVERY-ASSESSMENT-ANALYSIS-IMPLEMENTED.md for
 * how this was verified.
 *
 * The one thing this module exists for: classic's Analysis pane also has a
 * "Sub-Resources" sub-tab (index.html's loadAnalysisSubResourcesView, ~380
 * lines across candidate discovery, cataloguing and scoped-analysis
 * dispatch) that has no /next equivalent. It is deliberately NOT ported --
 * named here, not silently dropped, per the ITEM-11 doc's scoping decision.
 * `renderAnalysisNote` renders that one honest sentence into the
 * `enrichment-form` mount point (the same generic per-stage slot Curate
 * reuses for its own content, next/stages/curate.js) and is called from
 * app.js's `loadPane()` only when `state.stage === 'analysis'`.
 */
import { state, esc, $, oldUiHref, icon } from '/static/next/app.js';

export function renderAnalysisNote(slug) {
  const host = $('enrichment-form');
  if (!host) return;
  host.innerHTML = `<div class="mb-s3 max-w-[70ch] text-caveat text-ink-muted">
    Classic's Analysis pane also has a <span class="text-ink">Sub-Resources</span> sub-tab --
    selecting, cataloguing and scoping analysis to sub-resources of
    <span class="font-mono">${esc(slug)}</span>. That is not built in /next yet
    (a separable, non-trivial feature deferred by name, not dropped silently --
    see the ITEM-11 design note).
    <a href="${esc(oldUiHref())}" class="text-accent-ink underline">Open in the current UI</a>
    ${icon('external-link', { size: 13, cls: 'text-accent-ink' })}
  </div>`;
}
