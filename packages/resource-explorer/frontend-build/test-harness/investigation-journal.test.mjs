/** The investigation page's Journal section: entries newest first, an honest empty state, and a failed read
 *  (an error status, or a reply with no entries list) that is said as a failure and never drawn as an empty journal. */
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

async function setUp({ journal }) {
  const { document, window } = makeDomEnvironment();
  globalThis.fetch = async (url) => {
    const u = String(url);
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    if (u === '/api/journal/investigation/c360') {
      if (journal === 'error') return { ok: false, status: 500, json: async () => ({ detail: 'registry down' }), text: async () => 'registry down' };
      return ok(journal);
    }
    if (/\/members$/.test(u)) return ok([]);
    if (/\/next-steps$/.test(u)) return ok({ steps: [], complete: true });
    if (/\/dispositions$/.test(u)) return ok({});
    if (/\/link-status$/.test(u)) return ok({});
    if (u === '/api/investigations/purposes') return ok({ purposes: [] });
    if (u === '/api/investigations/classifications') return ok({ classifications: [], bindings: [] });
    if (/^\/api\/investigations\/([^/?]+)$/.test(u)) {
      return ok({ slug: 'c360', display_name: 'C', status: 'open', description: 'd', project_classification: 'StudyProject',
        purposes: [], visibility: 'public' });
    }
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
  return { document };
}

test('the journal lists its entries with author and date, and says they wait for promotion', async () => {
  const t = await setUp({ journal: { entries: [
    { id: 'e2', author: 'alice', written_at: '2026-10-19T10:00:00+00:00', body: 'Per chat: marquez emits OpenLineage.', suggested_to: [] },
    { id: 'e1', author: 'bob', written_at: '2026-10-18T09:00:00+00:00', body: 'First note.', suggested_to: [] },
  ], suggested_to: [] } });
  const section = text(t.document.getElementById('inv-journal'));
  assert.match(section, /Journal · 2/);
  assert.match(section, /alice · 2026-10-19/);
  assert.match(section, /Per chat: marquez emits OpenLineage\./);
  assert.match(section, /bob · 2026-10-18/);
  assert.match(section, /once this investigation is promoted/);
});

test('an empty journal says so and points at the chat action', async () => {
  const t = await setUp({ journal: { entries: [], suggested_to: [] } });
  const section = text(t.document.getElementById('inv-journal'));
  assert.match(section, /Journal · 0/);
  assert.match(section, /No entries yet/);
  assert.doesNotMatch(section, /could not be read/);
});

test('a failed read is said as a failure, never drawn as an empty journal', async () => {
  const t = await setUp({ journal: 'error' });
  const section = text(t.document.getElementById('inv-journal'));
  assert.match(section, /The journal could not be read/);
  assert.doesNotMatch(section, /No entries yet|Journal · 0/);
});

test('a reply with no entries list is a failed read too', async () => {
  const t = await setUp({ journal: {} });
  const section = text(t.document.getElementById('inv-journal'));
  assert.match(section, /The journal could not be read/);
  assert.doesNotMatch(section, /No entries yet|Journal · 0/);
});
