/** Behaviour: Files step 2 (2026-10-20), the folder survey card.
 *
 *  Real fs-survey.js, native-surveys.js and re-api.js against a jsdom DOM; only fetch is stubbed.
 *
 *  - the probe's ONE sentence is drawn exactly as stored, for each outcome; "not checked yet" and "could not tell" are
 *    their own states and are never drawn as either outcome;
 *  - the Survey press is enabled only where an outcome names who leads;
 *  - the results name the surveyor and the report sentence, one shape for both leads;
 *  - a capped walk says it was capped and never reads as complete; a number the survey did not carry is "–", not 0;
 *  - a press posts to the folder-survey route and the card repaints from the re-read, not from the press;
 *  - Egeria's Folder Survey row on the native-survey list names its surveyor.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();

const REACH = {
  not_checked: { state: 'not_checked', sentence: 'not checked yet', checked_date: '', surveyor: '', why: '', decided: false },
  egeria: { state: 'egeria', sentence: 'Egeria can read /deployments/data-lake · checked 2026-10-20', checked_date: '2026-10-20',
    surveyor: "Egeria's Folder Survey", why: '', decided: true },
  re_only: { state: 're_only', sentence: 'only Resource Explorer can read this path · checked 2026-10-20',
    checked_date: '2026-10-20', surveyor: 'Resource Explorer', why: '', decided: true },
  undecided: { state: 'undecided', sentence: 'could not tell whether Egeria can read this path · checked 2026-10-20',
    checked_date: '2026-10-20', surveyor: '', why: 'timed out waiting for the engine action', decided: false },
};

const NONE = (reach) => ({ state: 'none', reach, results: null, limits: null, surveyor: '', published: false });

const MEASURED = (reach, over = {}) => ({
  state: 'measured', reach, surveyor: 'Resource Explorer', surveyed_at: '2026-10-20T12:00:00+00:00',
  report_guid: '', published: false, report_sentence: 'surveyed by Resource Explorer · Egeria could not reach the path',
  limits: { max_depth: 20, max_entries: 100000, capped: false, capped_reasons: [], entries_examined: 5000,
    deepest_level_reached: 7, not_walked_directory_names: ['.git', 'node_modules'], not_walked_directories: 12,
    symlinked_directories_not_followed: 1 },
  results: {
    measured: true,
    counts: { files: 4200, total_size_bytes: 1234567, subdirectories: 310, unclassified: 25, inaccessible: 2, hidden: null },
    times: { last_modified: '2026-10-19T08:00:00' },
    file_types: [{ name: 'CSV Data File', count: 90 }, { name: 'Markdown', count: 12 }],
    extensions: [{ name: 'csv', count: 90 }],
    inaccessible: { count: 2, listed: ['secret/a', 'secret/b'], requested: true },
  },
  ...over,
});

function makeBackend({ views = [NONE(REACH.not_checked)], reaches = [REACH.not_checked], runResult = { led_by: 'resource_explorer' } } = {}) {
  const calls = [];
  let v = 0;
  let r = 0;
  globalThis.fetch = async (url, options = {}) => {
    const u = String(url);
    const method = (options.method || 'GET').toUpperCase();
    calls.push({ method, url: u, body: options.body ? JSON.parse(options.body) : null });
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    if (method === 'GET' && /\/folder-survey$/.test(u)) return ok(views[Math.min(v++, views.length - 1)]);
    if (method === 'POST' && /\/reach$/.test(u)) return ok(reaches[Math.min(r++, reaches.length - 1)]);
    if (method === 'POST' && /\/folder-survey$/.test(u)) return ok(runResult);
    if (method === 'POST' && /\/folder-survey\/publish$/.test(u)) return ok({ published: true, report_guid: 'abcdef12345' });
    return ok({});
  };
  return calls;
}

async function setUp(opts = {}) {
  const { document, window } = makeDomEnvironment();
  const calls = makeBackend(opts);
  ensureLoaderRegistered();
  globalThis.location = window.location;
  globalThis.getComputedStyle = window.getComputedStyle.bind(window);
  globalThis.history = window.history;
  const api = await import('/static/re-api.js');
  api.clearCache();
  const fs = await import('/static/next/fs-survey.js');
  const host = document.createElement('div');
  document.body.appendChild(host);
  return { document, host, calls, fs };
}

test('each outcome draws the probe sentence exactly as stored, and who leads', async () => {
  const { fs } = await setUp();
  for (const key of ['egeria', 're_only']) {
    const d = new (globalThis.window.DOMParser)().parseFromString(`<body>${fs.reachLineHtml(REACH[key])}</body>`, 'text/html');
    const t = text(d.body);
    assert.ok(t.includes(REACH[key].sentence), `${key}: ${t}`);
    assert.ok(t.includes(`led by ${REACH[key].surveyor}`), `${key} names who leads`);
  }
});

test('"not checked yet" and "could not tell" are never drawn as either outcome', async () => {
  const { fs } = await setUp();
  for (const key of ['not_checked', 'undecided']) {
    const t = text(new (globalThis.window.DOMParser)().parseFromString(`<body>${fs.reachLineHtml(REACH[key])}</body>`, 'text/html').body);
    assert.doesNotMatch(t, /^.{0,3}Egeria can read /, `${key} is not outcome 1`);
    assert.doesNotMatch(t, /only Resource Explorer can read this path/, `${key} is not outcome 2`);
    assert.match(t, /no one can be named to lead yet/);
  }
  const t = text(new (globalThis.window.DOMParser)().parseFromString(`<body>${fs.reachLineHtml(REACH.undecided)}</body>`, 'text/html').body);
  assert.match(t, /timed out waiting for the engine action/, "Egeria's own words stay on the screen");
});

test('Survey is enabled only where an outcome names who leads', async () => {
  const { host, fs } = await setUp();
  for (const [key, enabled] of [['not_checked', false], ['undecided', false], ['egeria', true], ['re_only', true]]) {
    host.innerHTML = fs.folderSurveyCardHtml(NONE(REACH[key]));
    const press = host.querySelector('[data-fs-act="survey"]');
    assert.equal(press.disabled, !enabled, `${key}: survey enabled=${enabled}`);
    assert.equal(host.querySelector('[data-fs-act="check"]').disabled, false, 'Check again is always available');
  }
});

test('results name the surveyor and the report sentence; no survey is "no folder survey yet", not zeros', async () => {
  const { host, fs } = await setUp();
  host.innerHTML = fs.folderSurveyCardHtml(NONE(REACH.re_only));
  assert.match(text(host.querySelector('[data-fs-results]')), /no folder survey yet/);
  assert.equal(host.querySelector('[data-fs-results]').dataset.fsState, 'none');

  host.innerHTML = fs.folderSurveyCardHtml(MEASURED(REACH.re_only));
  const by = text(host.querySelector('[data-fs-surveyed-by]'));
  assert.match(by, /surveyed by Resource Explorer · 2026-10-20/);
  assert.match(by, /surveyed by Resource Explorer · Egeria could not reach the path/);
  assert.match(text(host.querySelector('[data-fs-published]')), /kept here · not published to Egeria/);
  const all = text(host.querySelector('[data-fs-results]'));
  assert.match(all, /Files\s?4,200/);
  assert.match(all, /Inaccessible\s?2/);
  assert.match(all, /CSV Data File\s?90/);
  assert.match(all, /secret\/a/);

  host.innerHTML = fs.folderSurveyCardHtml(MEASURED(REACH.egeria, {
    surveyor: "Egeria's Folder Survey", published: true, report_guid: 'abcdef12345', limits: null,
    report_sentence: "surveyed by Egeria's Folder Survey",
    results: { measured: true, counts: { files: 10, inaccessible: 3 }, times: {}, file_types: [], extensions: [],
      inaccessible: { count: 3, listed: null, requested: true } } }));
  const egeria = text(host.querySelector('[data-fs-results]'));
  assert.match(egeria, /surveyed by Egeria's Folder Survey/);
  assert.match(egeria, /Total size\s?–/, 'a size the survey did not carry is a dash, not 0');
  assert.match(egeria, /Folders\s?–/);
  assert.match(egeria, /the names are in Egeria's own file/);
  assert.equal(host.querySelector('[data-fs-limits]'), null, "Egeria's survey has no walk limits to show");
  assert.match(text(host.querySelector('[data-fs-published]')), /published · report abcdef12/);
});

test('a capped walk says so and never reads as complete; an uncapped walk says it reached the end', async () => {
  const { host, fs } = await setUp();
  const capped = MEASURED(REACH.re_only);
  capped.limits = { ...capped.limits, capped: true, capped_reasons: ['entry cap'] };
  host.innerHTML = fs.folderSurveyCardHtml(capped);
  const c = text(host.querySelector('[data-fs-limits]'));
  assert.match(c, /capped \(entry cap\) · not the whole tree/);
  assert.doesNotMatch(c, /walked to the end/);
  assert.ok(host.querySelector('[data-fs-capped]'));
  assert.match(c, /limits: depth 20, entries 100,000/);
  assert.match(c, /not walked: \.git, node_modules \(12 folders skipped\)/);

  host.innerHTML = fs.folderSurveyCardHtml(MEASURED(REACH.re_only));
  const u = text(host.querySelector('[data-fs-limits]'));
  assert.match(u, /walked to the end of every folder it entered/);
  assert.equal(host.querySelector('[data-fs-capped]'), null);
});

test('a press posts to the folder-survey route and the card repaints from the re-read', async () => {
  const { host, calls, fs } = await setUp({
    views: [NONE(REACH.re_only), MEASURED(REACH.re_only)], reaches: [REACH.re_only],
  });
  let changed = [];
  await fs.mountFolderSurvey(host, 'walkme', { onChange: (a) => changed.push(a) });
  assert.match(text(host), /no folder survey yet/);
  host.querySelector('[data-fs-act="survey"]').click();
  await tick(80);
  const post = calls.find((c) => c.method === 'POST' && /\/folder-survey$/.test(c.url));
  assert.ok(post, 'POST /api/filesystems/walkme/folder-survey');
  assert.deepEqual(post.body, { publish: false });
  assert.match(text(host), /surveyed by Resource Explorer · 2026-10-20/, 'repainted from the re-read view');
  assert.deepEqual(changed, ['survey']);
});

test('Check again runs the probe and shows what it then stores', async () => {
  const { host, calls, fs } = await setUp({
    views: [NONE(REACH.not_checked), NONE(REACH.egeria)], reaches: [REACH.egeria],
  });
  await fs.mountFolderSurvey(host, 'lake');
  assert.match(text(host), /not checked yet/);
  host.querySelector('[data-fs-act="check"]').click();
  await tick(80);
  assert.ok(calls.some((c) => c.method === 'POST' && /\/lake\/reach$/.test(c.url)));
  assert.match(text(host), /Egeria can read \/deployments\/data-lake · checked 2026-10-20/);
  assert.equal(host.querySelector('[data-fs-act="survey"]').disabled, false);
});

test('a walk of Resource Explorer\'s not yet published offers Publish, and publishing re-reads', async () => {
  const { host, calls, fs } = await setUp({
    views: [MEASURED(REACH.re_only), MEASURED(REACH.re_only, { published: true, report_guid: 'abcdef12345' })],
  });
  await fs.mountFolderSurvey(host, 'walkme');
  const pub = host.querySelector('[data-fs-act="publish"]');
  assert.ok(pub, 'a stored, unpublished walk offers Publish');
  pub.click();
  await tick(80);
  assert.ok(calls.some((c) => c.method === 'POST' && /\/walkme\/folder-survey\/publish$/.test(c.url)));
  assert.match(text(host.querySelector('[data-fs-published]')), /published · report abcdef12/);
  assert.equal(host.querySelector('[data-fs-act="publish"]'), null, 'once the re-read says published, no Publish is offered');
});

test('Egeria\'s Folder Survey row on the native-survey list names its surveyor', async () => {
  const { document } = await setUp();
  const ns = await import('/static/next/stages/native-surveys.js');
  const row = {
    qualified_name: 'FileSurvey::survey-folder', display_name: 'Survey Folder', kind: 'survey_existing',
    runnable: true, cannot_run_reason: '', neutral: false, in_flight: false, stale: false, name_taken: false,
    registered_again: false, credentials: 'present', credentials_note: '', surveyor: "Egeria's Folder Survey",
    run: { state: 'not_run' }, description: 'x', notes: [], tried: [],
  };
  const host = document.createElement('div');
  host.innerHTML = ns.nativeSurveysSectionHtml([row]);
  assert.match(text(host.querySelector('[data-native-surveyor]')), /surveyed by Egeria's Folder Survey/);
  const plain = document.createElement('div');
  plain.innerHTML = ns.nativeSurveysSectionHtml([{ ...row, surveyor: undefined }]);
  assert.equal(plain.querySelector('[data-native-surveyor]'), null, 'a row with no surveyor names none');
});

test('Understanding reads a file system\'s folder survey the same way whoever led it, naming the surveyor', async () => {
  for (const [label, view, expect] of [
    ['re-led', MEASURED(REACH.re_only), /surveyed by Resource Explorer · Egeria could not reach the path/],
    ['egeria-led', MEASURED(REACH.egeria, {
      surveyor: "Egeria's Folder Survey", published: true, report_guid: 'abcdef12345', limits: null,
      report_sentence: "surveyed by Egeria's Folder Survey",
      results: { measured: true, counts: { files: 10, total_size_bytes: 2048, subdirectories: 2, inaccessible: 0 },
        times: {}, file_types: [{ name: 'CSV Data File', count: 3 }], extensions: [],
        inaccessible: { count: 0, listed: null, requested: false } } }), /surveyed by Egeria's Folder Survey/],
  ]) {
    const { document, window } = makeDomEnvironment();
    makeBackend({ views: [view] });
    ensureLoaderRegistered();
    globalThis.location = window.location;
    globalThis.getComputedStyle = window.getComputedStyle.bind(window);
    globalThis.history = window.history;
    const api = await import('/static/re-api.js');
    api.clearCache();
    const app = await import('/static/next/app.js');
    app.state.resourceType = 'filesystem';
    app.state.filesystems = [{ slug: 'lake', display_name: 'Lake', local_mount_point: '/x', canonical_mount_point: '/x',
      status: 'active', description: '', last_surveyed_at: '', egeria_asset_guid: '', file_count: 0, data_file_count: 0 }];
    app.state.filesystemsLoaded = true;
    app.state.selectedSlug = 'lake';
    app.state.groups = [];
    const content = document.createElement('div');
    content.id = 'content';
    document.body.appendChild(content);
    const u = await import('/static/next/stages/understanding.js');
    await u.loadChartsPane();
    await tick(60);
    const pane = text(document.getElementById('fs-understanding-survey'));
    assert.match(pane, expect, `${label}: the surveyor is named`);
    assert.match(pane, /Files\s?(4,200|10)/, `${label}: the counts`);
    assert.match(pane, /CSV Data File\s?(90|3)/, `${label}: the file types`);
    assert.ok(document.querySelector('[data-understanding-not-charted]'), 'the not-charted sentence stays');
  }
});
