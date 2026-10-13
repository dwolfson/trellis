/** (owner, 2026-10-13) An investigation whose members are not in Egeria: Relink says why in words from link-status,
 *  each member row carries "not published" with the reason on hover, and [Publish the N unpublished members] shows
 *  the server's plan, asks, presses once, draws per-member results from the rows, then offers Relink. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const INDEX_HTML = fs.readFileSync(path.resolve(HERE, '../../resource_explorer/web/static/next/index.html'), 'utf8');
const INV_SRC = fs.readFileSync(path.resolve(HERE, '../../resource_explorer/web/static/next/stages/investigation.js'), 'utf8');
const tick = (ms = 60) => new Promise((r) => setTimeout(r, ms));
const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();

const REASON = 'not in Egeria yet — no asset GUID (not published)';
const LINK_STATUS = {
  bound: true, not_published: 2,
  counts: { linked: 1, not_linked: 2, could_not_tell: 0, linkable: 0 },
  summary: ['nothing to link', '2 members are not in Egeria yet (not published)'],
  members: [
    { entity_type: 'repo', entity_slug: 'pub', state: 'linked', reason: '' },
    { entity_type: 'repo', entity_slug: 'new1', state: 'not_linked', not_published: true, reason: REASON },
    { entity_type: 'repo', entity_slug: 'new2', state: 'not_linked', not_published: true, reason: REASON },
  ],
};
const PLAN = { count: 2, slugs: ['new1', 'new2'], words: 'will publish 2 repos: new1, new2', publish: [{ entity_type: 'repo', entity_slug: 'new1' }, { entity_type: 'repo', entity_slug: 'new2' }], waiting: [], running: '' };
const RUNNING = { batch_id: 'mp-1', running: true, words: ['1 published', '1 publishing'], relink_next: false,
  members: [{ entity_type: 'repo', entity_slug: 'new1', state: 'published', words: '' },
    { entity_type: 'repo', entity_slug: 'new2', state: 'publishing', words: '' }] };
const DONE = { batch_id: 'mp-1', running: false, words: ['1 published', '1 failed'], relink_next: true, waiting_next_press: [],
  members: [{ entity_type: 'repo', entity_slug: 'new1', state: 'published', words: '' },
    { entity_type: 'repo', entity_slug: 'new2', state: 'failed', words: 'Egeria went away' }] };

async function setUp({ linkStatus = LINK_STATUS, relinkResult, pressConflict = false } = {}) {
  const { document, window } = makeDomEnvironment();
  const calls = [];
  const bodies = [];
  let reads = 0;
  globalThis.fetch = async (url, options = {}) => {
    const u = String(url); const method = (options.method || 'GET').toUpperCase();
    calls.push(`${method} ${u}`);
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    if (/\/publish-members\/mp-1$/.test(u)) { reads += 1; return ok(reads >= 1 ? DONE : RUNNING); }
    if (/\/publish-members$/.test(u)) {
      if (method === 'POST') {
        bodies.push(JSON.parse(options.body || 'null'));
        if (pressConflict) return { ok: false, status: 409, json: async () => ({ detail: 'the list changed, confirm again' }), text: async () => 'the list changed, confirm again' };
        return ok(RUNNING);
      }
      return ok(PLAN);
    }
    if (/\/relink-members$/.test(u)) return ok(relinkResult || { ok: true, members_linked: [], members_unlinkable: [], errors: [], link_status: linkStatus });
    if (/\/link-status$/.test(u)) return ok(linkStatus);
    if (/\/members$/.test(u)) return ok(linkStatus.members.map((m) => ({ entity_type: m.entity_type, entity_slug: m.entity_slug })));
    if (/\/next-steps$/.test(u)) return ok({ steps: [], complete: true });
    if (/\/dispositions$/.test(u)) return ok({});
    if (u === '/api/investigations/purposes') return ok({ purposes: [] });
    if (u === '/api/investigations/classifications') return ok({ classifications: [], bindings: [] });
    const m = u.match(/^\/api\/investigations\/([^/?]+)$/);
    if (m) return ok({ slug: m[1], display_name: 'P', status: 'open', description: 'd', project_classification: 'PersonalProject',
      purposes: [], visibility: 'private', egeria_project_guid: 'g-1', egeria_project_qualified_name: 'Project::P' });
    if (/^\/api\/investigations\/\?/.test(u)) return ok([]);
    return ok({});
  };
  ensureLoaderRegistered();
  globalThis.location = window.location; globalThis.history = window.history;
  globalThis.getComputedStyle = window.getComputedStyle.bind(window);
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  window.history.replaceState(null, '', '/next');
  document.body.innerHTML = INDEX_HTML.match(/<body[^>]*>([\s\S]*)<\/body>/)[1].replace(/<script[\s\S]*?<\/script>/g, '');
  const api = await import('/static/re-api.js'); api.clearCache();
  const app = await import('/static/next/app.js');
  const inv = await import('/static/next/stages/investigation.js');
  inv.setMemberPublishPollMs(10);
  app.state.stage = 'investigation'; app.state.me = { user_id: 'alice' }; app.state.investigations = [];
  inv.openInvestigationDetail('proof');
  await inv.renderInvestigation();
  await tick();
  return { document, calls, bodies, inv };
}

test('each unpublished member row shows the cue and "not published", the reason on hover', async () => {
  const t = await setUp();
  const cells = [...t.document.querySelectorAll('[data-inv-member-link="not_published"]')];
  assert.equal(cells.length, 2);
  for (const c of cells) {
    assert.equal(text(c), '○ not published');
    assert.equal(c.querySelector('[data-cue]').getAttribute('title'), REASON);
  }
  assert.ok(t.document.querySelector('[data-inv-member-link="linked"]'), 'a published member still reads linked');
});

test('Relink with nothing in Egeria says why in words from the link-status rows', async () => {
  const t = await setUp();
  t.document.querySelector('[data-act="inv-relink"]').click();
  await tick(200);
  const words = t.document.querySelector('[data-inv-relink-words]');
  assert.ok(words, 'the relink result carries the words');
  assert.equal(text(words), 'nothing to link · 2 members are not in Egeria yet (not published)');
  assert.match(text(t.document.querySelector('[data-inv-relink-result]')), /0 linked/);
});

test('the words also name other states, e.g. could not tell', async () => {
  const ls = { ...LINK_STATUS, summary: ['2 members are not in Egeria yet (not published)', '3 could not tell'] };
  const t = await setUp({ linkStatus: ls });
  t.document.querySelector('[data-act="inv-relink"]').click();
  await tick(200);
  assert.equal(text(t.document.querySelector('[data-inv-relink-words]')),
    '2 members are not in Egeria yet (not published) · 3 could not tell');
});

test('[Publish the 2 unpublished members] is offered from link-status, and not when there are none', async () => {
  const t = await setUp();
  assert.equal(text(t.document.querySelector('[data-act="inv-publish-members"]')), 'Publish the 2 unpublished members');
  const none = await setUp({ linkStatus: { ...LINK_STATUS, not_published: 0, summary: ['nothing to link'] } });
  assert.equal(none.document.querySelector('[data-act="inv-publish-members"]'), null);
});

test('plan, confirm, one press, per-member results, then Relink offered', async () => {
  const t = await setUp();
  t.document.querySelector('[data-act="inv-publish-members"]').click();
  await tick(120);
  // The plan's own words are shown, and the confirmation names the same list.
  assert.equal(text(t.document.querySelector('[data-inv-members-plan]')), 'will publish 2 repos: new1, new2');
  const dialog = t.document.querySelector('[role="alertdialog"]');
  assert.ok(dialog, 'asks before an Egeria write');
  assert.match(text(dialog.querySelector('[data-dialog-message]')), /will publish 2 repos: new1, new2/);
  assert.equal(t.calls.filter((c) => c.startsWith('POST') && c.endsWith('/publish-members')).length, 0, 'nothing sent before the yes');
  const yes = [...dialog.querySelectorAll('button')].find((b) => /Publish 2 to Egeria/.test(b.textContent));
  yes.click();
  await tick(300);
  assert.equal(t.calls.filter((c) => c === 'POST /api/investigations/proof/publish-members').length, 1);
  assert.deepEqual(t.bodies, [{ slugs: ['new1', 'new2'] }], 'the press names exactly the confirmed list');
  const result = t.document.querySelector('[data-inv-members-publish-result]');
  assert.equal(text(result.querySelector('[data-inv-members-publish-words]')), '1 published · 1 failed');
  const lines = Object.fromEntries([...result.querySelectorAll('[data-inv-member-publish]')].map((li) => [text(li).split(' ').pop(), li]));
  assert.equal(text(lines.new1), '✓ published new1');
  assert.equal(lines.new2.getAttribute('data-inv-member-publish'), 'failed');
  assert.equal(lines.new2.querySelector('[data-cue]').getAttribute('title'), 'Egeria went away');
  // Relink is offered next, not run for you.
  assert.equal(t.calls.filter((c) => c.endsWith('/relink-members')).length, 0);
  const relink = result.querySelector('[data-act="inv-relink-after-publish"]');
  assert.ok(relink);
  relink.click();
  await tick(200);
  assert.equal(t.calls.filter((c) => c === 'POST /api/investigations/proof/relink-members').length, 1);
});

test('declining the confirmation sends nothing', async () => {
  const t = await setUp();
  t.document.querySelector('[data-act="inv-publish-members"]').click();
  await tick(120);
  const dialog = t.document.querySelector('[role="alertdialog"]');
  [...dialog.querySelectorAll('button')].find((b) => /Cancel/.test(b.textContent)).click();
  await tick(60);
  assert.equal(t.calls.filter((c) => c.startsWith('POST') && c.endsWith('/publish-members')).length, 0);
  assert.equal(t.document.querySelector('[data-act="inv-publish-members"]').disabled, false);
});

test('the new markup uses literal class strings only (no interpolated class names)', () => {
  for (const fn of ['publishMembersButtonHtml', 'memberPublishLineHtml', 'memberPublishResultHtml', 'publishMembersFlow']) {
    const start = INV_SRC.indexOf(`function ${fn}(`);
    assert.ok(start > 0, fn);
    const body = INV_SRC.slice(start, INV_SRC.indexOf('\n}\n', start));
    assert.doesNotMatch(body, /class="[^"]*\$\{/, `${fn} interpolates a class name`);
  }
});

test('a press whose list changed since the confirmation says so and sends nothing more', async () => {
  const t = await setUp({ pressConflict: true });
  t.document.querySelector('[data-act="inv-publish-members"]').click();
  await tick(120);
  const dialog = t.document.querySelector('[role="alertdialog"]');
  [...dialog.querySelectorAll('button')].find((b) => /Publish 2 to Egeria/.test(b.textContent)).click();
  await tick(200);
  assert.match(text(t.document.querySelector('[data-inv-members-plan-changed]')), /the list changed, confirm again/);
  assert.equal(t.calls.filter((c) => /publish-members\/mp-/.test(c)).length, 0);
  assert.equal(t.document.querySelector('[data-act="inv-publish-members"]').disabled, false);
});
