/** Routing-level reachability tests for the Enrichment -> Context tab
 *  (ENRICHMENT-E1 parity with the pre-E1 Enrichment form).
 *
 *  WHY THESE EXIST: E1 replaced a render path and silently dropped three
 *  things the old path did (the evidence rail, the licence row's survey
 *  proposal, and the Documentation sources block). PR #348's own tests
 *  called `renderDocSources` directly, so they stayed green while the block
 *  was unreachable from any tab. These tests go the way a person does: the
 *  Enrichment stage is set, the Context tab's strip button is CLICKED
 *  (`bindSubTabs` -> `loadPane` -> `loadContextPane` -> `renderContext`),
 *  and only then is the rendered DOM asserted.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const NOW = '2026-09-29T10:00:00Z';

function stubServer({ facts = [], doc = { sources: [], published: false, publish_note: '' } } = {}) {
  globalThis.fetch = async (url) => {
    const u = String(url);
    const ok = (body) => ({ ok: true, status: 200, json: async () => body });
    if (u.includes('/api/analyses/facts')) return ok({ subjects: { amundsen: facts } });
    if (u.includes('/api/doc-sources/')) return ok(doc);
    if (u.includes('/api/context/')) return ok({ enrichment: {}, question_answers: {} });
    if (u.includes('/questions')) return ok({ questions: [] });
    return ok({});
  };
}

const LICENCE_FACT = {
  analysis_id: 'license_classification', state: 'measured', last_run_at: NOW,
  headline: 'Apache License 2.0 — Permissive',
  value: { findings: [{ check_name: 'license_risk_tier', label: 'permissive', summary: 'Apache License 2.0 — Permissive' }] },
};
const SCAN_FACT = { analysis_id: 'security_scan', state: 'measured', last_run_at: NOW, headline: '0 high findings', value: {} };

/** Set the Enrichment stage and click the Context tab in the real strip. */
async function routeToContext(resourceType, slug, server) {
  const { document, window } = makeDomEnvironment();
  stubServer(server);   // after makeDomEnvironment(), which resets fetch
  ensureLoaderRegistered();
  // writeUrl() (called by the tab click) uses bare `location`/`history`.
  globalThis.location = window.location;
  globalThis.history = window.history;
  // The rail's ensureRailShowing() asks for a media query jsdom lacks.
  window.matchMedia = window.matchMedia || (() => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  const app = await import('/static/next/app.js');
  app.state.resourceType = resourceType;
  app.state.selectedSlug = slug;
  app.state.stage = 'enrichment';
  app.state.subTab = 'questions';
  app.state.investigations = [];
  app.state.investigation = '';
  const content = document.createElement('div');
  content.id = 'content';
  document.body.appendChild(content);
  // The page-shell hosts loadPane()/the rail expect (index.html).
  for (const id of ['rail-evidence', 'perspective-row', 'worklist-nav', 'app-grid']) {
    const d = document.createElement('div');
    d.id = id;
    document.body.appendChild(d);
  }
  content.innerHTML = app.subTabsHtml();
  app.bindSubTabs();
  const btn = content.querySelector('[data-subtab="context"]');
  assert.ok(btn, 'the Enrichment stage strip must offer a Context tab');
  btn.click();
  // loadPane is async: wait for renderContext to finish.
  for (let i = 0; i < 100 && !document.getElementById('context-human-questions'); i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  await new Promise((r) => setTimeout(r, 50));
  return { document, app };
}

test('routing: the Context tab shows the Evidence rail with the old form\'s measurements', async () => {
  const { document } = await routeToContext('repo', 'amundsen', { facts: [LICENCE_FACT, SCAN_FACT] });
  const rail = document.getElementById('rail-evidence').textContent;
  assert.match(rail, /Evidence · enrichment/);
  assert.match(rail, /0 high findings/);
  assert.match(rail, /security_scan/);
});

test('routing: the licence row offers the survey-measured licence to confirm', async () => {
  const { document } = await routeToContext('repo', 'amundsen', { facts: [LICENCE_FACT] });
  const html = document.getElementById('context-observations').innerHTML;
  assert.match(html, /from survey:/);
  assert.match(html, /Apache License 2\.0/);
  assert.match(html, /data-confirm="licence"/);
});

test('routing: the Context tab mounts the Documentation sources block, and says nothing is "not built"', async () => {
  const { document } = await routeToContext('db', 'amundsen', {
    doc: { sources: [{ id: 's1', url: 'https://docs.example/d', label: 'Data dictionary', source_type: 'data_dictionary',
      added_at: NOW, origin: 'local', probe_state: 'reachable', probe_status_code: 200, probe_ms: 10,
      probe_title: '', probe_byte_count: 0, probe_error: '', probed_at: NOW, egeria_external_ref_guid: '' }],
      published: false, publish_note: '' },
  });
  const block = document.getElementById('doc-sources-block');
  assert.ok(block, '#doc-sources-block must be present on Enrichment -> Context');
  assert.match(block.textContent, /Documentation sources/);
  assert.match(block.textContent, /Data dictionary/);
  assert.doesNotMatch(document.getElementById('context-form').textContent, /Documentation sources — not built/);
});
