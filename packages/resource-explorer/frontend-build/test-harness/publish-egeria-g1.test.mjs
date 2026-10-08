/** Parity slice G1 (PI-001..PI-008): the Publish band of Curate, on a repository and on a database.
 *
 *  Real app.js, real router (the Curate nav button is clicked), a stateful stub server behind fetch.
 *  The rule under test: every word on screen follows the server's re-read rows, never the click. The
 *  known-negatives make the server answer 200 to a write while its record says otherwise, and watch
 *  the words follow the record.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms));
const GUID = 'asset-guid-0001';
const REPORT = { guid: 'rep-guid-0001', qualified_name: 'SurveyReport::GitHubRepo::egeria_git::2026-10-07', display_name: 'Survey: egeria_git',
  surveyed_at: '2026-10-07T01:00:00', annotation_count: 42, schema_count: 0, table_count: 0, column_count: 0, description: '' };

function makeServer(over = {}) {
  const s = {
    calls: [],
    inEgeria: false, row: { word: 'none', read_at: '', sentence: '', first: '' }, project: { status: 'unset', word: 'no project', name: '' },
    canAgain: false,
    survey: { exists: true, surveyed_at: '2026-10-07T01:00:00', age_seconds: 7200, annotations: 42, steps: 12, stale_steps: 0, stale: [] },
    resurveyAnswers: 'ok',
    publishAnswers: 'ok',     // 'ok' | '428' | '409' | 'drop' (200 but nothing recorded) | 'sent'
    reports: [REPORT], reportsStatus: 200,
    annotations: [{ guid: 'ann-1', annotation_type: 'SchemaAnalysisAnnotation', summary: 'ok', confidence: 90, analysis_step: 'files', explanation: 'because', content_status: '' }],
    fileTypes: [{ label: 'Python', file_count: 12, extensions: ['.py'], cataloged: false, linked: false, dataset_guid: '' }],
    blocker: '',
    ...over,
  };
  const state = () => ({ slug: 'egeria_git', in_egeria: s.inEgeria, asset_guid: s.inEgeria ? GUID : '', row: s.row,
    project: s.project, can_publish_again: s.canAgain, survey: s.survey });
  globalThis.fetch = async (url, opts = {}) => {
    const u = String(url);
    const method = opts.method || 'GET';
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    s.calls.push({ method, url: u, body });
    const ok = (b, status = 200) => ({ ok: true, status, json: async () => b });
    const err = (status, detail) => ({ ok: false, status, statusText: detail, json: async () => ({ detail }) });
    if (u.endsWith('/publish-state')) return ok(state());
    if (u.endsWith('/resurvey')) {
      if (s.resurveyAnswers === '409') return err(409, 'a survey for egeria_git is already running');
      s.survey = { ...s.survey, exists: true, surveyed_at: '2026-10-07T09:00:00', age_seconds: 5, stale_steps: 0, stale: [] };
      return ok({ ok: true, errors: [], survey: s.survey });
    }
    if (u.endsWith('/publish-report')) {
      if (s.publishAnswers === 'nosurvey') return err(409, 'no survey to publish yet · run the first survey');
      if (s.publishAnswers === '428') return err(428, 'egeria_project_context_required');
      if (s.publishAnswers === '409') return err(409, 'a publish for egeria_git is already running');
      if (body.without_project) s.project = { status: 'declined', word: 'no project (chosen)', name: '' };
      if (s.publishAnswers === 'ok') {
        s.inEgeria = true; s.canAgain = true;
        s.row = { word: 'published', read_at: new Date().toISOString(), report_guid: REPORT.guid, reused: false, annotation_count: 42, surveyed_at: s.survey.surveyed_at };
      } else if (s.publishAnswers === 'sent') {
        s.inEgeria = true; s.canAgain = true; s.row = { word: 'sent', read_at: new Date().toISOString(), sentence: 'sent · waiting for Egeria', first: '' };
      } else if (s.publishAnswers === 'fail') {
        s.row = { word: 'not published', read_at: '', sentence: 'OMAG-500 refused. Context: more', first: 'OMAG-500 refused.' };
      } // 'drop': 200 and nothing recorded
      return ok({ ok: true });
    }
    if (u.endsWith('/forget-links')) {
      s.inEgeria = false; s.canAgain = false; s.row = { word: 'forgotten', read_at: new Date().toISOString(), sentence: '', first: '' };
      return ok({ ok: true, surveys_deleted: 3, asset_guid_cleared: true });
    }
    if (u.endsWith('/egeria-surveys')) return s.reportsStatus === 200 ? ok(s.reports) : err(s.reportsStatus, 'Egeria is not reachable');
    if (u.includes('/egeria-surveys/') && u.endsWith('/annotations')) return ok(s.annotations);
    if (u.endsWith('/file-types')) return ok({ slug: 'egeria_git', asset_guid: GUID, in_egeria: s.inEgeria, types: s.fileTypes, blocker: s.blocker });
    if (u.endsWith('/file-types/commit')) {
      s.fileTypes = s.fileTypes.map((t) => body.elements.some((e) => e.label === t.label) ? { ...t, cataloged: true, linked: true, dataset_guid: 'ds-1' } : t);
      return ok({ ok: true, items: body.elements.map((e) => ({ label: e.label, state: 'cataloged', guid: 'ds-1', words: 'cataloged · read back' })) });
    }
    if (u.includes('/curate/plan')) return ok({ technology_type: 'Git repository', disposition: 'using', in_population: true,
      last_surveyed_at: null, what_it_is: [], what_it_holds: [], relates: [], commits: [] });
    if (u.includes('/components/tree')) return ok({ branches: [], topology: '' });
    if (u.includes('/blueprints')) return ok({ blueprints: [], perspectives: [] });
    if (u.includes('/questions')) return ok({ questions: [] });
    if (u.includes('/api/context/')) return ok({ enrichment: {}, question_answers: {} });
    if (u.includes('/investigations') || u.includes('/subscriptions') || u.includes('/schedules')) return ok([]);
    if (u.includes('/api/curate/tags') && !u.includes('/api/curate/tags/')) return ok([]);
    return ok(u.includes('/api/curate/') ? [] : {});
  };
  return s;
}

async function setUp(resourceType, serverOver = {}, { signedIn = true, slug = 'egeria_git', rows = {} } = {}) {
  const { document, window } = makeDomEnvironment();
  const server = makeServer(serverOver);
  ensureLoaderRegistered();
  globalThis.location = window.location;
  globalThis.history = window.history;
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const app = await import('/static/next/app.js');
  app.state.resourceType = resourceType;
  app.state.selectedSlug = slug;
  app.state.stage = 'understanding';
  app.state.subTab = 'questions';
  app.state.investigations = []; app.state.investigation = '';
  app.state.workListSlug = null; app.state.workListIndex = false;
  app.state.me = signedIn ? { user_id: 'dan' } : null;
  app.state.groups = [];
  app.state.databasesLoaded = true; app.state.filesystemsLoaded = true;
  app.state.projects = [{ slug, ...rows }]; app.state.databases = [{ slug, ...rows }]; app.state.filesystems = [{ slug, ...rows }];
  app.state.perspectives = []; app.state.allPerspectives = [];
  for (const id of ['content', 'intent-nav', 'rail-evidence', 'perspective-row', 'app-grid']) {
    const d = document.createElement('div'); d.id = id; document.body.appendChild(d);
  }
  app.renderIntentNav();
  return { document, app, server };
}

async function openCurate(document) {
  document.querySelector('#intent-nav button[data-stage="curate"]').click();
  await wait();
}
const band = (d) => d.getElementById('curate-host').querySelector('[data-curate-band="publish"]');
const q = (d, sel) => band(d).querySelector(sel);
const post = (server, frag) => server.calls.filter((c) => c.method === 'POST' && c.url.includes(frag));

/* ── PI-001 / PI-002 ─────────────────────────────────────────────────── */

test('a repository never published: not in Egeria, no row, the publish control is there', async () => {
  const { document } = await setUp('repo');
  await openCurate(document);
  const t = band(document).textContent;
  assert.match(t, /Publish to Egeria/);
  assert.match(t, /not in Egeria/);
  assert.match(t, /no publish recorded here/);
  assert.equal(q(document, '[data-publish-go]').textContent.trim(), 'Publish to Egeria →');
  assert.equal(q(document, '[data-publish-go]').disabled, false);
  assert.equal(q(document, '[data-forget-open]').disabled, true, 'nothing to forget when not in Egeria');
});

test('signed out: the publish control is disabled and says why', async () => {
  const { document } = await setUp('repo', {}, { signedIn: false });
  await openCurate(document);
  assert.equal(q(document, '[data-publish-go]').disabled, true);
  assert.match(q(document, '[data-publish-feedback]').textContent, /sign in to publish/);
});

test('publish: POSTs whole (no zones, no steps), then the words come from the re-read; the control becomes Publish again', async () => {
  const { document, server } = await setUp('repo', { project: { status: 'personal', word: 'personal exploration', name: '' } });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  const [c] = post(server, '/api/egeria/egeria_git/publish-report');
  assert.deepEqual(c.body, { without_project: false }, 'no zone field, no steps field');
  assert.match(q(document, '[data-publish-row]').textContent, /published · from the survey of 2026-10-07 · read back/);
  assert.match(q(document, '[data-publish-status]').textContent, /in Egeria/);
  assert.equal(q(document, '[data-publish-status] [data-guid]').dataset.guid, GUID, 'the asset GUID is shown');
  assert.ok(q(document, '[data-copy-guid]'), 'and copyable');
  assert.equal(q(document, '[data-publish-go]').textContent.trim(), 'Publish again');
  assert.match(q(document, '[data-publish-project]').textContent, /personal exploration/);
  assert.ok(server.calls.filter((x) => x.url.endsWith('/publish-state')).length >= 2, 'the state was re-read after the write');
});

test('KNOWN-NEGATIVE: a 200 with nothing recorded does not say published', async () => {
  const { document } = await setUp('repo', { publishAnswers: 'drop' });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  const t = band(document).textContent;
  assert.doesNotMatch(t, /published · from the survey of 2026-10-07 · read back/);
  assert.match(q(document, '[data-publish-row]').textContent, /no publish recorded here/);
});

test('a report sent but not read back says "sent · waiting for Egeria", never published', async () => {
  const { document } = await setUp('repo', { publishAnswers: 'sent' });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  assert.match(q(document, '[data-publish-row]').textContent, /sent · waiting for Egeria/);
  assert.doesNotMatch(q(document, '[data-publish-row]').textContent, /published · from the survey of 2026-10-07 · read back/);
});

test('Egeria refusing reads "not published · <first sentence>" with the full sentence one gesture away', async () => {
  const { document } = await setUp('repo', { publishAnswers: 'fail' });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  const row = q(document, '[data-publish-row]');
  assert.match(row.textContent, /not published · OMAG-500 refused\./);
  assert.match(row.querySelector('[data-egeria-sentence]').textContent, /Context: more/);
});

test('a second press while the first is pending is ignored: one POST, and the control looks pending', async () => {
  const { document, server } = await setUp('repo');
  await openCurate(document);
  const b = q(document, '[data-publish-go]');
  b.click(); b.click(); b.click();
  assert.equal(b.disabled, true);
  assert.match(b.textContent, /…/);
  await wait();
  assert.equal(post(server, '/publish-report').length, 1);
});

test('a 409 (already running) says so and sends nothing else', async () => {
  const { document, server } = await setUp('repo', { publishAnswers: '409' });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  assert.match(q(document, '[data-publish-feedback]').textContent, /already running/);
  assert.equal(post(server, '/publish-report').length, 1);
});

/* ── PI-006: the project gate ────────────────────────────────────────── */

test('a 428 shows the sentence and the two choices; "Publish without one" presses again with without_project', async () => {
  const { document, server } = await setUp('repo', { publishAnswers: '428' });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  const gate = q(document, '[data-publish-gate-panel]');
  assert.ok(gate);
  assert.equal(gate.querySelector('div').textContent, 'no Egeria project context · bind this investigation to a project, or publish without one');
  assert.ok(gate.querySelector('[data-gate-bind]') && gate.querySelector('[data-gate-without]'));
  assert.equal(q(document, '[data-publish-go]').disabled, false, 'the control is enabled again, not stuck pending');
  server.publishAnswers = 'ok';
  gate.querySelector('[data-gate-without]').click();
  await wait();
  const ps = post(server, '/publish-report');
  assert.deepEqual(ps.map((c) => c.body.without_project), [false, true]);
  assert.match(q(document, '[data-publish-row]').textContent, /published · from the survey of 2026-10-07 · read back/);
  assert.match(q(document, '[data-publish-project]').textContent, /no project \(chosen\)/);
});

test('"Bind this investigation to a project" goes to the Investigation stage and publishes nothing', async () => {
  const { document, app, server } = await setUp('repo', { publishAnswers: '428' });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  q(document, '[data-gate-bind]').click();
  await wait();
  assert.equal(app.state.stage, 'investigation');
  assert.equal(post(server, '/publish-report').length, 1, 'only the first press went out');
});

/* ── PI-005 ──────────────────────────────────────────────────────────── */

test('Forget Egeria links: the confirmation says what survives; Cancel sends nothing; confirm forgets in RE and re-reads', async () => {
  const { document, server } = await setUp('repo', { inEgeria: true, canAgain: true, row: { word: 'published', read_at: new Date().toISOString(), report_guid: REPORT.guid } });
  await openCurate(document);
  assert.equal(q(document, '[data-forget-open]').textContent.trim(), 'Forget Egeria links…');
  q(document, '[data-forget-open]').click();
  assert.equal(q(document, '[data-forget-sentence]').textContent,
    'Egeria is unchanged; Resource Explorer forgets its cached GUIDs and survey history for this resource and re-reads them on the next publish.');
  q(document, '[data-forget-cancel]').click();
  assert.equal(post(server, '/forget-links').length, 0);
  assert.equal(q(document, '[data-forget-panel]'), null);
  q(document, '[data-forget-open]').click();
  const go = q(document, '[data-forget-go]');
  go.click(); go.click();
  await wait();
  assert.equal(post(server, '/forget-links').length, 1, 'a second press is ignored');
  assert.match(q(document, '[data-publish-status]').textContent, /not in Egeria/);
  assert.match(q(document, '[data-publish-row]').textContent, /links forgotten/);
  assert.match(q(document, '[data-publish-feedback]').textContent, /Egeria unchanged/);
  assert.doesNotMatch(band(document).textContent, /reset Egeria/i, 'roll-forward language, never "reset Egeria"');
});

/* ── PI-003 / PI-008: the one Egeria reports component ────────────────── */

test('Egeria reports: lists the asset\'s reports, expands annotations by report, shows a copyable GUID', async () => {
  const { document, server } = await setUp('repo', { inEgeria: true });
  await openCurate(document);
  const r = q(document, `[data-egeria-report="${REPORT.guid}"]`);
  assert.ok(r, 'the report from Egeria is listed (not only runs RE launched)');
  assert.match(r.textContent, /42/);
  assert.ok(r.querySelector('[data-copy-guid]'));
  assert.equal(server.calls.filter((c) => c.url.includes('/annotations')).length, 0, 'annotations are read on expand, not before');
  r.querySelector('[data-report-toggle]').click();
  await wait();
  assert.match(r.querySelector(`[data-report-annotations="${REPORT.guid}"]`).textContent, /SchemaAnalysisAnnotation/);
  assert.equal(server.calls.filter((c) => c.url.includes(`/egeria-surveys/${REPORT.guid}/annotations`)).length, 1);
  r.querySelector('[data-report-toggle]').click();
  assert.equal(r.querySelector(`[data-report-annotations="${REPORT.guid}"]`).textContent, '');
});

test('Egeria reports: Refresh re-reads; a failed read says so and is not "no reports"', async () => {
  const { document, server } = await setUp('repo', { inEgeria: true });
  await openCurate(document);
  const before = server.calls.filter((c) => c.url.endsWith('/egeria-surveys')).length;
  q(document, '[data-reports-refresh]').click();
  await wait();
  assert.equal(server.calls.filter((c) => c.url.endsWith('/egeria-surveys')).length, before + 1);
  server.reportsStatus = 503;
  q(document, '[data-reports-refresh]').click();
  await wait();
  assert.match(q(document, '[data-reports-error]').textContent, /Egeria could not be read: Egeria is not reachable/);
  assert.doesNotMatch(band(document).textContent, /holds no survey reports/);
});

test('Egeria reports: not in Egeria says so and never asks Egeria', async () => {
  const { document, server } = await setUp('repo', { inEgeria: false });
  await openCurate(document);
  assert.match(q(document, '[data-egeria-reports]').textContent, /Not in Egeria: there is no asset to list reports from/);
  assert.equal(server.calls.filter((c) => c.url.endsWith('/egeria-surveys')).length, 0);
});

test('Ask about this → prefills the chat rail with the report\'s identity and sends nothing', async () => {
  const { document, server } = await setUp('repo', { inEgeria: true });
  const ta = document.createElement('textarea'); ta.id = 'ask-input'; document.body.appendChild(ta);
  await openCurate(document);
  const before = server.calls.length;
  q(document, `[data-report-ask="${REPORT.guid}"]`).click();
  assert.match(ta.value, /Survey: egeria_git/);
  assert.match(ta.value, new RegExp(REPORT.guid));
  assert.equal(server.calls.length, before, 'prefill only: no request left');
});

/* ── one component, every kind ───────────────────────────────────────── */

test('a database: the same band, in Egeria from its row, reports from the database route, no publish control', async () => {
  const { document, server } = await setUp('db', {}, { slug: 'coco_pharma', rows: { is_published: true, egeria_asset_guid: 'db-asset-guid' } });
  await openCurate(document);
  const t = band(document).textContent;
  assert.match(t, /in Egeria/);
  assert.equal(q(document, '[data-publish-status] [data-guid]').dataset.guid, 'db-asset-guid');
  assert.equal(q(document, '[data-publish-go]'), null, 'a database publishes through Catalog');
  assert.match(t, /Catalog → above/);
  assert.equal(server.calls.filter((c) => c.url.includes('/api/databases/coco_pharma/egeria-surveys')).length, 1);
  assert.ok(q(document, '[data-egeria-report]'));
});

test('a file system: the same component on the file-system route', async () => {
  const { document, server } = await setUp('filesystem', {}, { slug: 'docs_fs', rows: { is_published: true, egeria_asset_guid: 'fs-guid' } });
  await openCurate(document);
  assert.equal(server.calls.filter((c) => c.url.includes('/api/filesystems/docs_fs/egeria-surveys')).length, 1);
  assert.equal(q(document, '[data-publish-go]'), null);
});

/* ── PI-004 ──────────────────────────────────────────────────────────── */

test('File types: preview first (nothing sent), then Catalog POSTs the chosen types and the list is re-read', async () => {
  const { document, server } = await setUp('repo', { inEgeria: true });
  await openCurate(document);
  const sec = q(document, '[data-file-types-section]');
  assert.equal(server.calls.filter((c) => c.url.endsWith('/file-types')).length, 0, 'nothing is read until opened');
  sec.open = true;
  sec.dispatchEvent(new document.defaultView.Event('toggle'));
  await wait();
  assert.equal(post(server, '/file-types/commit').length, 0, 'preview sends nothing');
  const cb = sec.querySelector('[data-ft-label="Python"]');
  assert.ok(cb && !cb.disabled);
  cb.checked = true;
  sec.querySelector('[data-file-types-go]').click();
  await wait();
  const [c] = post(server, '/file-types/commit');
  assert.deepEqual(c.body.elements, [{ label: 'Python', file_count: 12, extensions: ['.py'] }]);
  assert.match(sec.textContent, /cataloged · read back/);
  assert.equal(sec.querySelector('[data-ft-label="Python"]').disabled, true, 'already cataloged and linked: not offered twice');
});

test('File types: a repository not in Egeria shows the blocker and offers no commit', async () => {
  const { document } = await setUp('repo', { inEgeria: false, blocker: 'publish the report first: the repository is not in Egeria yet' });
  await openCurate(document);
  const sec = q(document, '[data-file-types-section]');
  sec.open = true;
  sec.dispatchEvent(new document.defaultView.Event('toggle'));
  await wait();
  assert.match(sec.textContent, /publish the report first/);
  assert.equal(sec.querySelector('[data-file-types-go]').disabled, true);
});

/* ── brief section 1: publish the survey already kept; re-survey is its own act ───────────────── */

test('the band shows the survey it would publish, with its age, before the press', async () => {
  const { document } = await setUp('repo');
  await openCurate(document);
  const line = q(document, '[data-publish-survey="kept"]');
  assert.match(line.textContent.replace(/\s+/g, ' '), /from the survey of 2026-10-07 · .*ago · 42 annotations · 12 steps ran/);
  assert.equal(q(document, '[data-publish-go]').textContent.trim(), 'Publish to Egeria →');
  assert.equal(q(document, '[data-resurvey-go]').textContent.trim(), 'Re-survey now →');
  assert.equal(q(document, '[data-publish-stale]'), null, 'nothing stale: no stale line');
});

test('stale steps are named, not auto-run: a ⚠ cue, the word stale, the list one gesture away', async () => {
  const { document } = await setUp('repo', { survey: { exists: true, surveyed_at: '2026-10-07T01:00:00', age_seconds: 7200,
    annotations: 42, steps: 12, stale_steps: 3, stale: ['repo_health', 'repo_language', 'repo_security'] } });
  await openCurate(document);
  const stale = q(document, '[data-publish-stale]');
  assert.match(stale.textContent.replace(/\s+/g, ' '), /stale 3 of 12 steps are stale \(older than their refresh rule\) · re-survey to refresh/);
  assert.equal(stale.querySelector('[data-cue]').dataset.cue, 'partial');
  assert.match(stale.querySelector('details').textContent, /repo_health, repo_language, repo_security/);
});

test('no survey: Publish is disabled, the reason is directly under it, and only the survey control is live', async () => {
  const { document, server } = await setUp('repo', { survey: { exists: false, sentence: 'no survey to publish yet · run the first survey' } });
  await openCurate(document);
  assert.equal(q(document, '[data-publish-go]').disabled, true);
  assert.equal(q(document, '[data-resurvey-go]').disabled, false);
  assert.equal(q(document, '[data-resurvey-go]').textContent.trim(), 'Run the first survey →');
  assert.equal(q(document, '[data-publish-blocker]').textContent.trim(), 'no survey to publish yet · run the first survey');
  q(document, '[data-publish-go]').click();
  await wait();
  assert.equal(post(server, '/publish-report').length, 0, 'a disabled Publish sent nothing');
});

test('Re-survey now runs the survey and nothing else: no publish is sent, and the age changes from the re-read', async () => {
  const { document, server } = await setUp('repo', { survey: { exists: true, surveyed_at: '2026-10-01T01:00:00', age_seconds: 600000,
    annotations: 42, steps: 12, stale_steps: 2, stale: ['repo_health', 'repo_language'] } });
  await openCurate(document);
  assert.match(q(document, '[data-publish-survey]').textContent, /2026-10-01/);
  const b = q(document, '[data-resurvey-go]');
  b.click();
  assert.equal(b.disabled, true, 'a pressed control ignores a second press');
  assert.equal(b.textContent.trim(), 'Re-surveying …', 'an immediate visible change');
  assert.equal(q(document, '[data-publish-go]').disabled, true, 'no publish mid-survey');
  await wait(400);
  assert.equal(post(server, '/resurvey').length, 1);
  assert.equal(post(server, '/publish-report').length, 0, 're-survey must not publish');
  assert.match(q(document, '[data-publish-survey]').textContent, /2026-10-07/);
  assert.equal(q(document, '[data-publish-stale]'), null);
  assert.equal(q(document, '[data-publish-go]').disabled, false);
});

test('a publish answered 409 "no survey" says nothing was sent, not "already running"', async () => {
  const { document } = await setUp('repo', { publishAnswers: 'nosurvey' });
  await openCurate(document);
  q(document, '[data-publish-go]').click();
  await wait();
  assert.match(q(document, '[data-publish-feedback]').textContent, /no survey to publish yet · run the first survey/);
  assert.doesNotMatch(q(document, '[data-publish-feedback]').textContent, /already running/);
});
