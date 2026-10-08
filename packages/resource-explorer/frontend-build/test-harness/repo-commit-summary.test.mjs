/** Brief section 2 (owner, 2026-10-07): the commit summary for repositories.
 *
 *  Pure rendering of the table and its panel: before the press the numbers equal the selection; after
 *  it the state column is made of the server's proof summary, with the proof rows' counts and not the
 *  request's; a press with nothing selected, no survey or no project is refused with the sentence
 *  directly under the button. Section 1's box (re-survey the stale steps first) is off by default.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

async function mod() {
  ensureLoaderRegistered();
  const { document } = makeDomEnvironment();
  const m = await import(`/static/next/stages/repo-manifest.js?t=${Math.random()}`);
  return { m, document };
}

const KINDS = { 'docs': 'folder', 'docs/a.md': 'file', 'docs/b.md': 'file', 'src': 'folder', 'src/x/y.py': 'file' };
const PLAN = {
  in_population: true,
  survey: { exists: true, surveyed_at: '2026-10-07T01:00:00', age_seconds: 7200, annotations: 42, steps: 12, stale_steps: 3, stale: ['a', 'b', 'c'] },
  project: { status: 'linked', word: 'project', name: 'P' },
  what_it_is: [
    { kind: 'SoftwareCapability::pyegeria', candidate: true }, { kind: 'Endpoint', candidate: true }, { kind: 'InfrastructureAsset', candidate: true },
    { kind: 'Component', candidate: false }],
  what_it_holds: [{ kind: 'SubResource', candidate: true, detail: { worthy: Object.keys(KINDS), kinds: KINDS } }],
  made_of: [{ detail: { blueprints_accepted: 2, blueprint_kinds: ['Deployment Blueprint'] } }],
};
const sel = (over = {}) => ({ plan: PLAN, picks: new Set(['SoftwareCapability::pyegeria', 'Endpoint']),
  chosenSubs: ['docs/a.md', 'docs/b.md', 'src'], fileTypePicks: new Set(['Python']), ...over });
const cell = (box, id, col) => box.querySelector(`[data-manifest-row="${id}"]`).querySelectorAll('[role=cell]')[col].textContent.replace(/\s+/g, ' ').trim();

test('before the press the numbers equal the selection', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  box.innerHTML = m.repoManifestHtml(sel());
  assert.equal(cell(box, 'report', 2), '1 report · 42 annotations');
  assert.match(cell(box, 'report', 3), /survey of 2026-10-07 \(.*ago\)/);
  assert.equal(cell(box, 'entities', 2), '2 entities');
  assert.equal(cell(box, 'contained', 2), '2 files · 1 folder · 1 container');       // docs/ is the container of the two files
  assert.equal(box.querySelector('[data-manifest-row="file_types"]'), null, 'the DataSet-per-type row is retired');
  assert.equal(cell(box, 'blueprints', 2), '2 (Deployment Blueprint)');
  assert.equal(cell(box, 'left_out', 2), '1 proposal not confirmed · 2 not selected');
  assert.equal(box.querySelector('[data-manifest-state]'), null, 'no state column before a press');
});

test('the counts follow the selection and nothing else', async () => {
  const { m } = await mod();
  const c = m.manifestCounts(sel({ chosenSubs: [], picks: new Set() }));
  assert.deepEqual([c.entities, c.files, c.folders, c.containers, c.items], [0, 0, 0, 0, 0]);
  const d = m.manifestCounts(sel({ chosenSubs: ['src/x/y.py'] }));
  assert.deepEqual([d.files, d.folders, d.containers], [1, 0, 2], 'a file needs src and src/x above it');
  assert.deepEqual(m.ancestorFolders(['docs', 'docs/a.md'], KINDS), [], 'a chosen folder is not added twice');
});

test('after the press the state column is the proof summary, with the proof rows counts not the request', async () => {
  const { m, document } = await mod();
  const ps = {
    report: { state: 'published', read_at: new Date().toISOString(), annotation_count: 42, reused: true },
    sub_resources: { read_back: 2, sent: 1, failed: 1, first_failure: 'OMAG-404 element missing.' },
    file_types: { read_back: 0 },
  };
  const box = document.createElement('div');
  box.innerHTML = m.repoManifestHtml(sel({ ps }));
  const state = (id) => box.querySelector(`[data-manifest-state="${id}"]`).textContent.replace(/\s+/g, ' ').trim();
  assert.match(state('report'), /published · read back just now · reused the report already in Egeria/);
  assert.equal(box.querySelector('[data-manifest-state="report"] [data-cue]').dataset.cue, 'measured');
  assert.match(state('contained'), /2 elements read back/);
  assert.match(state('contained'), /1 sent, not yet read back/);
  assert.match(state('contained'), /1 not created · OMAG-404 element missing\./);
  assert.doesNotMatch(state('contained'), /(^|\s)4 (elements|read)/, 'the request said 4; the rows say otherwise');
  assert.equal(box.querySelector('[data-manifest-state="contained"] [data-cue="error"]') !== null, true);
});

test('sent, and not published, read as themselves', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  box.innerHTML = m.repoManifestHtml(sel({ ps: { report: { state: 'sent' }, sub_resources: {}, file_types: {} } }));
  assert.match(box.querySelector('[data-manifest-state="report"]').textContent, /sent · waiting for Egeria/);
  assert.equal(box.querySelector('[data-manifest-state="report"] [data-cue]').dataset.cue, 'running');
  box.innerHTML = m.repoManifestHtml(sel({ ps: { report: { state: 'not published', first: 'OMAG-409-001 name taken.', rest: 'More.' }, sub_resources: {}, file_types: {} } }));
  assert.match(box.querySelector('[data-manifest-state="report"]').textContent, /not published · OMAG-409-001 name taken\./);
  assert.equal(box.querySelector('[data-manifest-state="report"] [data-cue]').dataset.cue, 'error');
});

test('the button names the items it sends; blockers are directly under it', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  box.innerHTML = m.repoCommitPanelHtml({ ...sel(), me: 'dan', resurvey: false });
  assert.equal(box.querySelector('[data-curate-go]').textContent.trim(), 'Catalog 5 items →');
  assert.equal(box.querySelector('[data-curate-go]').disabled, false);
  assert.equal(box.querySelectorAll('[data-commit-blocker]').length, 0);

  box.innerHTML = m.repoCommitPanelHtml({ ...sel({ picks: new Set(), chosenSubs: [] }), me: 'dan', resurvey: false });
  assert.equal(box.querySelector('[data-curate-go]').disabled, true);
  assert.equal(box.querySelector('[data-commit-blocker="nothing"]').textContent.trim(), '⚠ nothing selected · confirm a line under what it is, or choose folders and files');

  const noSurvey = { ...PLAN, survey: { exists: false, sentence: 'no survey to publish yet · run the first survey' } };
  box.innerHTML = m.repoCommitPanelHtml({ ...sel({ plan: noSurvey }), me: 'dan', resurvey: false });
  assert.equal(box.querySelector('[data-curate-go]').disabled, true);
  assert.match(box.querySelector('[data-commit-blocker="no_survey"]').textContent, /no survey to publish yet · run the first survey/);

  const noProject = { ...PLAN, project: { status: 'unset', word: 'no project' } };
  box.innerHTML = m.repoCommitPanelHtml({ ...sel({ plan: noProject }), me: 'dan', resurvey: false });
  const b = box.querySelector('[data-commit-blocker="no_project"]');
  assert.match(b.textContent, /no Egeria project context/);
  assert.ok(b.querySelector('[data-commit-bind]') && b.querySelector('[data-commit-decline]'), 'the two choices are offered');

  box.innerHTML = m.repoCommitPanelHtml({ ...sel(), me: '', resurvey: false });
  assert.equal(box.querySelector('[data-curate-go]').disabled, true);
});

test('the re-survey box is off by default, names the stale count, and is unavailable when nothing is stale', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  box.innerHTML = m.repoCommitPanelHtml({ ...sel(), me: 'dan', resurvey: false });
  const cb = box.querySelector('[data-commit-resurvey]');
  assert.equal(cb.checked, false);
  assert.equal(cb.disabled, false);
  assert.match(box.querySelector('[data-commit-survey-line]').textContent, /survey of 2026-10-07 · 3 stale steps/);
  assert.match(box.querySelector('[data-commit-resurvey]').closest('label').textContent, /re-survey stale steps first \(adds minutes\)/);
  const fresh = { ...PLAN, survey: { ...PLAN.survey, stale_steps: 0, stale: [] } };
  box.innerHTML = m.repoCommitPanelHtml({ ...sel({ plan: fresh }), me: 'dan', resurvey: false });
  assert.equal(box.querySelector('[data-commit-resurvey]').disabled, true);
  box.innerHTML = m.repoCommitPanelHtml({ ...sel(), me: 'dan', resurvey: true });
  assert.equal(box.querySelector('[data-commit-resurvey]').checked, true);
});

test('the commit header reads "Publish · commit <id> · step n of m · running: <label> · k failed"', async () => {
  const { m } = await mod();
  const rec = { id: 'abcdef1234', steps: [{ name: 'publish_asset', state: 'done' }, { name: 'classifications', state: 'running' },
    { name: 'sub_resources', state: 'pending' }, { name: 'components', state: 'pending' }] };
  assert.equal(m.commitHeaderHtml(rec).replace(/<[^>]+>/g, '').trim(), 'Publish · commit abcdef12 · step 2 of 4 · running: classifications · 0 failed');
  rec.steps[1].state = 'failed';
  assert.match(m.commitHeaderHtml(rec).replace(/<[^>]+>/g, ''), /step 1 of 4 · 1 failed|step 2 of 4 · 1 failed/);
});
