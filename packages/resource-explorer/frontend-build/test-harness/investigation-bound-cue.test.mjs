/** Investigation Egeria section: after a successful promote the 'Creating…' button must not stay greyed out;
 *  the section shows the bound cue, and members the write could not attach are counted from its own result. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const INDEX_HTML = fs.readFileSync(path.resolve(HERE, '../../resource_explorer/web/static/next/index.html'), 'utf8');
const tick = (ms = 60) => new Promise((r) => setTimeout(r, ms));
const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();

async function setUp({ promoteResult }) {
  const { document, window } = makeDomEnvironment();
  let bound = false;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    const u = String(url); const method = (options.method || 'GET').toUpperCase();
    calls.push(`${method} ${u}`);
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    if (/\/promote$/.test(u)) { bound = true; return ok(promoteResult); }
    if (/\/relink-members$/.test(u)) return ok({ ok: true, members_linked: ['a', 'b'], members_unlinkable: [] });
    if (/\/members$/.test(u)) return ok([{ entity_type: 'repo', entity_slug: 'a' }, { entity_type: 'repo', entity_slug: 'b' }]);
    if (/\/next-steps$/.test(u)) return ok({ steps: [], complete: true });
    if (/\/dispositions$/.test(u)) return ok({});
    if (u === '/api/investigations/purposes') return ok({ purposes: [] });
    if (u === '/api/investigations/classifications') return ok({ classifications: [], bindings: [] });
    let m = u.match(/^\/api\/investigations\/([^/?]+)$/);
    if (m) return ok({ slug: m[1], display_name: 'C', status: 'open', description: 'd', project_classification: 'StudyProject',
      purposes: [], visibility: 'public',
      ...(bound ? { egeria_project_guid: 'g-1', egeria_project_qualified_name: 'Project::C360' } : {}) });
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
  app.state.stage = 'investigation'; app.state.me = { user_id: 'me' }; app.state.investigations = [];
  inv.openInvestigationDetail('c360');
  await inv.renderInvestigation();
  await tick();
  return { document, calls };
}

test('after promote the Creating… button is gone and the bound cue shows', async () => {
  const t = await setUp({ promoteResult: { ok: true, classification_requested: 'StudyProject', classification_confirmed: 'StudyProject',
    members_linked: ['a', 'b'], members_unlinkable: [] } });
  const btn = t.document.querySelector('[data-act="inv-promote"]');
  assert.ok(btn, 'unbound: publish button present');
  btn.click();
  await tick(200);
  assert.equal(t.document.querySelector('[data-act="inv-promote"]'), null);
  assert.doesNotMatch(text(t.document.getElementById('content')), /Creating…/);
  const cue = t.document.querySelector('[data-inv-bound-cue]');
  assert.ok(cue);
  assert.match(text(cue.parentElement), /● bound · Project::C360/);
  assert.equal(t.document.querySelector('[data-inv-not-linked]'), null);
});

test('members the promote could not link are counted, with the existing link action', async () => {
  const t = await setUp({ promoteResult: { ok: true, classification_requested: 'StudyProject', classification_confirmed: 'StudyProject',
    members_linked: [], members_unlinkable: [{ entity_slug: 'a', reason: 'no asset' }, { entity_slug: 'b', reason: 'no asset' }] } });
  t.document.querySelector('[data-act="inv-promote"]').click();
  await tick(200);
  assert.match(text(t.document.querySelector('[data-inv-not-linked]')), /2 members not linked/);
  const link = t.document.querySelector('[data-act="inv-relink"]');
  assert.equal(text(link), 'Link members');
  assert.match(text(t.document.getElementById('inv-egeria-form')), /Could not link: a \(no asset\); b \(no asset\)/);
  link.click();
  await tick(200);
  assert.ok(t.calls.includes('POST /api/investigations/c360/relink-members'));
  assert.equal(t.document.querySelector('[data-inv-not-linked]'), null);
  assert.equal(text(t.document.querySelector('[data-act="inv-relink"]')), 'Relink members');
});
