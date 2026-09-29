/** Real-DOM regression tests for the Documentation sources block on the
 *  Enrichment stage (BRIEF-DATABASE-DOCUMENTATION-SOURCES.md slice 1,
 *  "Declare and probe" -- resource_explorer/web/static/next/stages/
 *  enrichment.js's `renderDocSources`).
 *
 *  Per the project's 2026-09 harness-regression rule ("every /next fix
 *  from here on adds its regression to the harness, not only a source-text
 *  test" -- also applies to new features), this is a real jsdom render,
 *  not a string match against enrichment.js's source.
 *
 *  `renderDocSources` fetches from `/api/doc-sources/...` via re-api.js's
 *  `getDocSources`, so `globalThis.fetch` is stubbed per test to return
 *  fixture JSON keyed by URL -- the harness's documented pattern (dom-
 *  harness.mjs's header comment: "if a test needs a network response, stub
 *  globalThis.fetch before calling into app.js").
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

function stubFetchJson(responsesByUrlSubstring) {
  globalThis.fetch = async (url) => {
    const key = Object.keys(responsesByUrlSubstring).find((k) => String(url).includes(k));
    if (!key) {
      throw new Error(`_UNSTUBBED_FETCH in doc-sources test: no fixture for ${url}`);
    }
    const body = responsesByUrlSubstring[key];
    return {
      ok: true,
      status: 200,
      json: async () => body,
    };
  };
}

function docSourcesFixture(overrides = {}) {
  return {
    sources: [
      {
        id: 'src1', entity_type: 'database', entity_slug: 'adventureworks',
        url: 'https://docs.example/dictionary', label: 'Data dictionary',
        source_type: 'data_dictionary', added_at: '2026-09-28T00:00:00Z', added_by: 'dan',
        origin: 'local', probe_state: 'reachable', probe_status_code: 200,
        probe_ms: 180, probe_title: 'AdventureWorks Data Dictionary', probe_byte_count: 4096,
        probe_error: '', probed_at: '2026-09-28T00:00:05Z', egeria_external_ref_guid: '',
      },
    ],
    published: false,
    publish_note: '',
    ...overrides,
  };
}

async function setUpEnrichmentDom() {
  const { document } = makeDomEnvironment();
  ensureLoaderRegistered();
  // enrichment.js imports `state` from the PLAIN '/static/next/app.js'
  // specifier (no cache-bust query) -- dom-harness's own loadAppModule()
  // always cache-busts (`?t=...`), which is right for isolating app.js's
  // *own* tests from each other, but it means the module it returns is a
  // DIFFERENT instance than the one enrichment.js's static import resolves
  // to, so mutating ITS `state` would never be seen by renderDocSources.
  // Importing the plain specifier here gets the exact instance
  // enrichment.js itself imports.
  const app = await import('/static/next/app.js');
  const enrichment = await import(`/static/next/stages/enrichment.js?t=${Date.now()}_${Math.random()}`);

  app.state.resourceType = 'db';
  app.state.selectedSlug = 'adventureworks';

  const host = document.createElement('div');
  host.id = 'doc-sources-block';
  document.body.appendChild(host);

  return { document, app, enrichment, host };
}

test('a declared source renders its reachable state, HTTP status and fetch time', async () => {
  const { enrichment, host } = await setUpEnrichmentDom();
  stubFetchJson({ '/api/doc-sources/database/adventureworks': docSourcesFixture() });

  await enrichment.renderDocSources('adventureworks');

  assert.match(host.textContent, /Data dictionary/);
  assert.match(host.textContent, /reachable/);
  assert.match(host.textContent, /HTTP 200/);
  assert.match(host.textContent, /180ms/);
  assert.match(host.textContent, /local only/, 'unpublished resource must say "local only"');
});

test('needs_sign_in and not_found states render their own glyph/label, not "reachable"', async () => {
  const fixture = docSourcesFixture({
    sources: [
      { id: 's1', url: 'https://a', label: 'Needs sign-in', source_type: 'wiki', added_at: '',
        origin: 'local', probe_state: 'needs_sign_in', probe_status_code: 401, probe_ms: 50,
        probe_title: '', probe_byte_count: 0, probe_error: '', probed_at: '2026-09-28T00:00:00Z',
        egeria_external_ref_guid: '' },
      { id: 's2', url: 'https://b', label: 'Gone', source_type: 'runbook', added_at: '',
        origin: 'local', probe_state: 'not_found', probe_status_code: 404, probe_ms: 30,
        probe_title: '', probe_byte_count: 0, probe_error: '', probed_at: '2026-09-28T00:00:00Z',
        egeria_external_ref_guid: '' },
    ],
  });
  const { enrichment, host } = await setUpEnrichmentDom();
  stubFetchJson({ '/api/doc-sources/database/adventureworks': fixture });

  await enrichment.renderDocSources('adventureworks');

  assert.match(host.textContent, /needs sign-in/);
  assert.match(host.textContent, /HTTP 401/);
  assert.match(host.textContent, /not found/);
  assert.match(host.textContent, /HTTP 404/);
});

test('a published resource shows no "local only" note, and an unpublished one always does', async () => {
  const { enrichment, host } = await setUpEnrichmentDom();
  stubFetchJson({
    '/api/doc-sources/database/adventureworks': docSourcesFixture({ published: true }),
  });

  await enrichment.renderDocSources('adventureworks');

  assert.doesNotMatch(host.textContent, /local only/);
});

test('a stale-linkage publish note is shown verbatim instead of the generic "local only" copy', async () => {
  const { enrichment, host } = await setUpEnrichmentDom();
  stubFetchJson({
    '/api/doc-sources/database/adventureworks': docSourcesFixture({
      published: false,
      publish_note: 'published to Egeria · link stale since 2026-09-22 — element not found',
    }),
  });

  await enrichment.renderDocSources('adventureworks');

  assert.match(host.textContent, /link stale since 2026-09-22/);
});

test('the re-check button re-fetches and the row reflects the NEW probe state after a second render', async () => {
  // This is the harness's whole reason for existing (see its header
  // comment): assert what survives a SECOND render, not just the first.
  // NOTE: fetch is stubbed AFTER setUpEnrichmentDom(), not before --
  // makeDomEnvironment() (called inside it) installs its own loudly-failing
  // fetch stub, which would otherwise clobber a stub set earlier.
  const { enrichment, host, document } = await setUpEnrichmentDom();

  let call = 0;
  globalThis.fetch = async () => {
    call += 1;
    const body = call === 1
      ? docSourcesFixture()
      : docSourcesFixture({
          sources: [{
            ...docSourcesFixture().sources[0],
            probe_state: 'blocked', probe_status_code: 503, probe_error: 'HTTP 503',
          }],
        });
    return { ok: true, status: 200, json: async () => body };
  };

  await enrichment.renderDocSources('adventureworks');
  assert.match(host.textContent, /reachable/);

  const recheckBtn = host.querySelector('[data-doc-recheck]');
  assert.ok(recheckBtn, 'expected a re-check button on the declared source row');
  // The click handler calls recheckDocSource() (a POST) then
  // renderDocSources() again -- stub the POST leg too.
  globalThis.fetch = async (url, opts) => {
    if (opts && opts.method === 'POST') return { ok: true, status: 200, json: async () => ({}) };
    call += 1;
    return {
      ok: true, status: 200,
      json: async () => docSourcesFixture({
        sources: [{
          ...docSourcesFixture().sources[0],
          probe_state: 'blocked', probe_status_code: 503, probe_error: 'HTTP 503',
        }],
      }),
    };
  };
  recheckBtn.dispatchEvent(new document.defaultView.Event('click', { bubbles: true }));
  // Allow the async click handler's microtasks (recheck POST + re-render) to settle.
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.match(host.textContent, /blocked/);
  assert.match(host.textContent, /HTTP 503/);
});

test('the ingest action is present but disabled ("coming soon") -- slice 2 is not built here', async () => {
  const { enrichment, host } = await setUpEnrichmentDom();
  stubFetchJson({ '/api/doc-sources/database/adventureworks': docSourcesFixture() });

  await enrichment.renderDocSources('adventureworks');

  const buttons = [...host.querySelectorAll('button')];
  const ingestBtn = buttons.find((b) => /ingest/i.test(b.textContent));
  assert.ok(ingestBtn, 'expected an ingest affordance, even if disabled');
  assert.equal(ingestBtn.disabled, true);
});
