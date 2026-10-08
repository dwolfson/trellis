/* What this press does -- the commit summary for a repository (brief section 2, project owner
 * 2026-10-07: "yes, we need the summary for repos").
 *
 * The database Curate pane has "what this commit does" as a short table with the Catalog button at its
 * top right. The repository gets the same table, before the press and after it:
 *
 *   before   one row per mechanism: who acts, what, how many, from what. The numbers equal the
 *            selection (the lines ticked, the folders and files chosen, the file types ticked).
 *   after    the same table gains a state column derived from PROOF ROWS (the server read the
 *            elements back by GUID): sent / published · read back <when> / not published · <sentence>.
 *            The counts there are the proof rows' counts, never the request's.
 *
 * The button reads "Catalog N items" (N = what this press sends: the confirmed lines and the chosen
 * folders and files). What blocks it is written directly under it; the re-survey box (off by default)
 * sits under the blockers. This file draws; every state word comes from the plan or the proof summary
 * the server derived, never from the click.
 */
import { ago } from '/static/next/format.js';
import { stateEntry } from '/static/next/glyphs.js';
import { esc } from '/static/next/app.js';

export const NOTHING_SELECTED_SENTENCE = 'nothing selected · confirm a line under what it is, or choose folders and files';
export const NO_SURVEY_SENTENCE = 'no survey to publish yet · run the first survey';
export const NO_PROJECT_SENTENCE = 'no Egeria project context · bind this investigation to a project, or decline one';
export const RESURVEY_BOX_WORDS = 're-survey stale steps first (adds minutes)';

const cue = (key, word, title = '') => {
  const e = stateEntry(key);
  const open = e.tone === 'text-state-ok' ? '<span class="text-state-ok"'
    : e.tone === 'text-state-warn' ? '<span class="text-state-warn"' : '<span class="text-ink-muted"';
  return `${open} data-cue="${esc(key)}" title="${esc(title || e.word)}"><span class="font-glyph" aria-hidden="true">${e.glyph}</span> ${esc(word)}</span>`;
};
const num = (n) => `<span class="tnum">${esc(n ?? 0)}</span>`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** The folders a chosen file needs above it (Egeria's NestedFile needs a FileFolder), not already chosen. */
export function ancestorFolders(chosen, kinds) {
  const have = new Set(chosen.filter((l) => (kinds[l] || 'folder') === 'folder'));
  const need = new Set();
  for (const loc of chosen) {
    if ((kinds[loc] || 'folder') !== 'file') continue;
    const parts = loc.split('/');
    for (let i = 1; i < parts.length; i += 1) {
      const anc = parts.slice(0, i).join('/');
      if (!have.has(anc)) need.add(anc);
    }
  }
  return [...need].sort();
}

/** The counts the table shows before a press, from the selection. Pure. */
export function manifestCounts({ plan, picks, chosenSubs, fileTypePicks }) {
  const holds = (plan.what_it_holds || []).find((r) => r.kind === 'SubResource');
  const kinds = (holds && holds.detail && holds.detail.kinds) || {};
  const worthy = (holds && holds.detail && holds.detail.worthy) || [];
  const files = chosenSubs.filter((l) => kinds[l] === 'file').length;
  const folders = chosenSubs.length - files;
  const containers = ancestorFolders(chosenSubs, kinds).length;
  const candidates = (plan.what_it_is || []).filter((r) => r.candidate);
  const entities = [...picks].filter((k) => candidates.some((r) => r.kind === k)).length;
  const made = ((plan.made_of || [])[0] || {}).detail || {};
  return {
    entities, files, folders, containers, subs: chosenSubs.length,
    blueprints: made.blueprints_accepted || 0, blueprintKinds: made.blueprint_kinds || [],
    notConfirmed: candidates.length - entities, notSelected: Math.max(0, worthy.length - chosenSubs.length),
    items: entities + chosenSubs.length,
  };
}

/** What stands under the button: each reason this press is refused, one line each (with its remedy). */
export function commitBlockers({ plan, counts, me }) {
  const out = [];
  if (!me) out.push({ key: 'signin', text: 'sign in to catalog — the record needs an author' });
  if (plan.survey && plan.survey.exists === false) out.push({ key: 'no_survey', text: plan.survey.sentence || NO_SURVEY_SENTENCE });
  if (counts.items === 0) out.push({ key: 'nothing', text: NOTHING_SELECTED_SENTENCE });
  if (plan.project && plan.project.status === 'unset') out.push({ key: 'no_project', text: NO_PROJECT_SENTENCE });
  if (!plan.in_population) out.push({ key: 'population', text: 'not in Curate’s population' });
  return out;
}

/** The state cell of one row after a press, from the server's `proof_summary`. */
function stateCell(id, ps) {
  if (!ps) return '';
  const subs = ps.sub_resources || {};
  if (id === 'report') {
    const r = ps.report || {};
    if (r.state === 'published') return cue('measured', `published · read back ${ago(r.read_at)}`)
      + (r.reused ? ' <span class="text-provenance text-ink-muted">· reused the report already in Egeria</span>' : '');
    if (r.state === 'sent') return cue('running', 'sent · waiting for Egeria');
    if (r.state === 'not published') return cue('error', `not published · ${r.first || 'Egeria gave no sentence'}`)
      + (r.rest ? ` <details class="inline"><summary class="inline cursor-pointer text-ink-muted underline">details</summary><span class="block whitespace-pre-wrap text-provenance text-ink-muted">${esc(`${r.first} ${r.rest}`)}</span></details>` : '');
    return cue('unrun', 'not sent');
  }
  if (id === 'contained') {
    const bits = [];
    if (subs.read_back) bits.push(cue('measured', `${plural(subs.read_back, 'element', 'elements')} read back`));
    if (subs.sent) bits.push(cue('running', `${subs.sent} sent, not yet read back`));
    if (subs.failed) bits.push(cue('error', `${subs.failed} not created${subs.first_failure ? ` · ${subs.first_failure}` : ''}`));
    return bits.length ? bits.join(' · ') : cue('unrun', 'nothing sent');
  }
  if (id === 'entities') return cue('unrun', 'recorded on the commit', 'These lines are kept on the commit record; Egeria receives the survey report and the elements listed beside it.');
  if (id === 'blueprints') return cue('unrun', 'written when you accept each', 'A blueprint is written to Egeria when it is accepted in what it’s made of.');
  return '';
}

/** The table. `ps` is the proof summary of the latest commit (after a press), else null. */
export function repoManifestHtml({ plan, picks, chosenSubs, fileTypePicks, ps = null }) {
  const c = manifestCounts({ plan, picks, chosenSubs, fileTypePicks });
  const sv = plan.survey && plan.survey.exists ? plan.survey : null;
  const after = !!ps;
  const row = (id, who, what, many, from, state) => `<div role="row" data-manifest-row="${id}" class="flex items-start gap-s2 py-[2px] text-ink">
    <div role="cell" class="w-[7.5rem] shrink-0 break-words font-semibold">${who}</div>
    <div role="cell" class="min-w-0 flex-1 break-words">${what}</div>
    <div role="cell" class="w-[13rem] shrink-0 break-words tnum">${many}</div>
    <div role="cell" class="w-[11rem] shrink-0 break-words text-ink-muted">${from}</div>
    ${after ? `<div role="cell" data-manifest-state="${id}" class="w-[15rem] shrink-0 break-words">${state}</div>` : ''}</div>`;
  const kindNames = c.blueprintKinds.length ? ` (${c.blueprintKinds.map(esc).join(', ')})` : '';
  const head = `<div role="row" class="flex items-start gap-s2 text-provenance text-ink-muted">
    <div role="columnheader" class="w-[7.5rem] shrink-0"></div><div role="columnheader" class="min-w-0 flex-1">what</div>
    <div role="columnheader" class="w-[13rem] shrink-0">how many</div><div role="columnheader" class="w-[11rem] shrink-0">from</div>
    ${after ? '<div role="columnheader" class="w-[15rem] shrink-0">state</div>' : ''}</div>`;
  const rows = [
    row('report', 'RE publishes', 'the repository asset and its survey report',
      sv ? `1 report · ${num(sv.annotations)} annotations` : 'no survey yet',
      sv ? `survey of ${esc(String(sv.surveyed_at).slice(0, 10))} (${esc(ago(sv.surveyed_at))})` : '—', stateCell('report', ps)),
    row('entities', 'Egeria gets', 'the lines you confirmed under “what it is”', `${num(c.entities)} entit${c.entities === 1 ? 'y' : 'ies'}`,
      'your confirmations', stateCell('entities', ps)),
    row('contained', 'Egeria gets', 'the folders and files you chose',
      `${num(c.files)} file${c.files === 1 ? '' : 's'} · ${num(c.folders)} folder${c.folders === 1 ? '' : 's'} · ${num(c.containers)} container${c.containers === 1 ? '' : 's'}`,
      'your selection', stateCell('contained', ps)),
    row('blueprints', 'Blueprints', 'the blueprints you chose to write', `${num(c.blueprints)}${kindNames}`,
      'your verdicts', stateCell('blueprints', ps)),
    row('left_out', 'Left out', 'nothing in Egeria changes',
      `${num(c.notConfirmed)} proposal${c.notConfirmed === 1 ? '' : 's'} not confirmed · ${num(c.notSelected)} not selected`, '—', ''),
  ].join('');
  return `<div data-repo-manifest role="table" aria-label="What this press does" class="min-w-0 max-w-full overflow-x-auto text-caveat">${head}${rows}</div>`;
}

/** The commit header line and the numbered steps (after a press). Counts of steps are the record's. */
export function commitHeaderHtml(rec, labelOf = (n) => n) {
  if (!rec) return '';
  const steps = rec.steps || [];
  const running = steps.find((s) => s.state === 'running');
  const doneN = steps.filter((s) => s.state === 'done' || s.state === 'skipped' || s.state === 'failed').length;
  const failed = steps.filter((s) => s.state === 'failed').length;
  const at = running ? steps.indexOf(running) + 1 : Math.min(steps.length, doneN);
  return `<div data-commit-header class="text-caveat text-ink">Publish · commit ${esc(String(rec.id || '').slice(0, 8))} · step ${at} of ${steps.length}${
    running ? ` · running: ${esc(labelOf(running.name))}` : ''} · ${failed} failed</div>`;
}

/** The panel: the table, the button at its top right, the blockers directly under the button, the box. */
export function repoCommitPanelHtml({ plan, picks, chosenSubs, fileTypePicks, me, resurvey, sentence = '', rec = null, ps = null }) {
  const counts = manifestCounts({ plan, picks, chosenSubs, fileTypePicks });
  const blockers = commitBlockers({ plan, counts, me });
  const off = blockers.length > 0;
  const sv = plan.survey && plan.survey.exists ? plan.survey : null;
  const staleLine = sv
    ? `<div data-commit-survey-line class="text-right text-caveat text-ink-muted">survey of ${esc(String(sv.surveyed_at).slice(0, 10))} · ${num(sv.stale_steps || 0)} stale step${sv.stale_steps === 1 ? '' : 's'}</div>` : '';
  return `<div data-repo-commit-panel class="min-w-0 max-w-full">
    <div class="text-answer text-ink">What this press does</div>
    <div class="flex flex-wrap items-start justify-between gap-s3">
      <div class="min-w-0 flex-1">${repoManifestHtml({ plan, picks, chosenSubs, fileTypePicks, ps })}</div>
      <div data-curate-go-col class="flex shrink-0 flex-col items-end gap-s1" style="width:260px">
        <button type="button" data-curate-go ${off ? 'disabled' : ''} title="${esc(sentence)}"
          class="rounded-sm border border-accent bg-transparent px-3 py-[3px] text-answer text-accent-ink ${off ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}">${counts.items ? `Catalog ${counts.items} item${counts.items === 1 ? '' : 's'} →` : 'Catalog →'}</button>
        <span data-curate-go-hint class="text-right text-provenance text-ink-muted">${off ? '' : 'a queued run; each step reports as it lands'}</span>
        ${blockers.map((b) => `<div data-commit-blocker="${esc(b.key)}" class="text-right text-caveat text-ink">⚠ ${esc(b.text)}${
          b.key === 'no_project' ? ` <button type="button" data-commit-bind class="cursor-pointer bg-transparent p-0 text-accent-ink underline">bind this investigation</button> · <button type="button" data-commit-decline class="cursor-pointer bg-transparent p-0 text-accent-ink underline">decline a project</button>` : ''}</div>`).join('')}
        ${staleLine}
        <label class="flex min-w-0 max-w-full cursor-pointer items-start gap-[4px] break-words text-right text-caveat text-ink">
          <input type="checkbox" data-commit-resurvey ${resurvey ? 'checked' : ''} ${sv && sv.stale_steps ? '' : 'disabled'}>
          ${esc(RESURVEY_BOX_WORDS)}</label>
      </div>
    </div>
  </div>`;
}
