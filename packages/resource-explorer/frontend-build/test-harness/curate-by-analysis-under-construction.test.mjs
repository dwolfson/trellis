/** Curate's "By analysis" sub-tab says it is under construction (project owner, 2026-10-08:
 *  "say 'Under Construction' and just leave it for now"). One short line, no generic pane,
 *  no network read, no error -- for every resource kind. Other stages keep the real pane. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, loadAppModule } from './dom-harness.mjs';

async function mount(resourceType, stage) {
  const { document } = makeDomEnvironment();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return { ok: true, status: 200, json: async () => ({ boards: [], questions: [] }) };
  };
  const app = await loadAppModule();
  const content = document.createElement('div');
  content.id = 'content';
  document.body.appendChild(content);
  app.state.resourceType = resourceType;
  app.state.selectedSlug = 'some_resource';
  app.state.stage = stage;
  app.state.subTab = 'by_analysis';
  app.state.analyses = [];
  return { app, content, calls };
}

for (const kind of ['repo', 'db', 'filesystem']) {
  test(`Curate By analysis reads "Under construction" for ${kind}, with no read and no error`, async () => {
    const { app, content, calls } = await mount(kind, 'curate');
    await app.loadByAnalysisPane();
    assert.match(content.textContent, /Under construction/);
    assert.doesNotMatch(content.textContent, /could not|Reading|error|No dashboard/i);
    assert.deepEqual(calls, [], 'no request is made for a pane that is not built');
    assert.ok(content.querySelector('[data-under-construction]'), 'a marker the page can be found by');
  });
}

test('another stage still gets the real By analysis pane', async () => {
  const { app, content } = await mount('db', 'scouting');
  app.state.analyses = [{ id: 'b1', name: 'Board One', description: '', intent: 'scouting' }];
  app.loadByAnalysisPane();
  assert.doesNotMatch(content.textContent, /Under construction/);
});
