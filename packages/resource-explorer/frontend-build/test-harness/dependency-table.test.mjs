/** Brief section 3 (owner, 2026-10-07): dependencies as ONE table with a kind column. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

const wait = (ms = 60) => new Promise((r) => setTimeout(r, ms));
const DATA = {
  heading: 'Dependencies · by kind', kinds: ['build-time', 'runtime'], counts: { 'build-time': 2, runtime: 1 }, runtime_state: '',
  rows: [
    { kind: 'build-time', name: 'fastapi', target: '0.110', source: 'pyproject.toml', state: 'measured', state_words: 'measured · from pyproject.toml', key: 'python:fastapi@pyproject.toml' },
    { kind: 'build-time', name: 'uvicorn', target: '0.30', source: 'pyproject.toml', state: 'measured', state_words: 'measured · from pyproject.toml', key: 'python:uvicorn@pyproject.toml' },
    { kind: 'runtime', name: 'web', target: 'db', source: 'deploy/docker-compose.yml:12', state: 'proposed', state_words: 'proposed · from docker-compose.yml', key: 'web->db@deploy/docker-compose.yml' },
  ],
};

async function mod() {
  ensureLoaderRegistered();
  const { document } = makeDomEnvironment();
  const m = await import(`/static/next/stages/dependencies.js?t=${Math.random()}`);
  return { m, document };
}
const text = (el) => el.textContent.replace(/\s+/g, ' ').trim();

test('one table: the heading is "Dependencies · by kind", the counts per kind, five columns', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  box.innerHTML = m.dependencyTableHtml(DATA);
  assert.equal(text(box.querySelector('[data-dep-heading]')), 'Dependencies · by kind');
  assert.equal(text(box.querySelector('[data-dep-counts]')), '2 build-time · 1 runtime');
  assert.deepEqual([...box.querySelectorAll('[role=columnheader]')].map((c) => text(c)), ['kind', 'name', 'version or target', 'source', 'state']);
  assert.equal(box.querySelectorAll('[data-dep-row]').length, 3);
  assert.equal(box.querySelectorAll('[role=table]').length, 1, 'one table, not a section per kind');
});

test('state words: measured from the manifest, proposed from the artifact, each with a cue', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  box.innerHTML = m.dependencyTableHtml(DATA);
  const s = (key) => box.querySelector(`[data-dep-row="${key}"] [data-dep-state]`);
  assert.equal(text(s('python:fastapi@pyproject.toml')), '✓ measured · from pyproject.toml');
  assert.equal(text(s('web->db@deploy/docker-compose.yml')).endsWith('proposed · from docker-compose.yml'), true);
  assert.equal(s('web->db@deploy/docker-compose.yml').querySelector('[data-cue]').dataset.cue, 'proposal');
});

test('a filter chip per kind narrows the rows; sorting by a column reorders them', async () => {
  const { m } = await mod();
  assert.deepEqual(m.visibleRows(DATA.rows, { kinds: new Set(['runtime']) }).map((r) => r.name), ['web']);
  assert.equal(m.visibleRows(DATA.rows, { kinds: new Set() }).length, 3, 'no chip = everything');
  assert.deepEqual(m.visibleRows(DATA.rows, { sort: 'name', dir: 'desc' }).map((r) => r.name), ['web', 'uvicorn', 'fastapi']);
});

test('a kind with no rows says why, never an empty section; no word says lineage', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  const manifestsOnly = { ...DATA, rows: DATA.rows.slice(0, 2), counts: { 'build-time': 2, runtime: 0 }, runtime_state: 'runtime not surveyed' };
  box.innerHTML = m.dependencyTableHtml(manifestsOnly);
  assert.equal(text(box.querySelector('[data-dep-runtime-state]')), 'runtime · runtime not surveyed');
  assert.equal(text(box.querySelector('[data-dep-counts]')), '2 build-time · 0 runtime');
  assert.doesNotMatch(box.innerHTML.toLowerCase(), /lineage/);
  box.innerHTML = m.dependencyTableHtml({ ...DATA, rows: [], counts: { 'build-time': 0, runtime: 0 }, runtime_state: 'no deployment artifact found' });
  assert.match(text(box), /no dependencies are recorded: survey the repository first/);
  assert.match(text(box), /runtime · no deployment artifact found/);
});

test('confirm is offered on runtime rows only, to a signed-in person, only when confirmable', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  box.innerHTML = m.dependencyTableHtml(DATA, {}, { confirmable: true, me: 'dan' });
  assert.equal(box.querySelectorAll('[data-dep-confirm]').length, 1);
  assert.equal(box.querySelector('[data-dep-row="python:fastapi@pyproject.toml"] [data-dep-confirm]'), null);
  box.innerHTML = m.dependencyTableHtml(DATA, {}, { confirmable: true, me: '' });
  assert.equal(box.querySelectorAll('[data-dep-confirm]').length, 0, 'signed out: no control');
  box.innerHTML = m.dependencyTableHtml(DATA, {});
  assert.equal(box.querySelectorAll('[data-dep-confirm]').length, 0, 'the Analysis pane only reads');
});

test('mounted: the chips filter in place, confirm posts once, and the row reads confirmed from the re-read', async () => {
  const { m, document } = await mod();
  const calls = [];
  let data = JSON.parse(JSON.stringify(DATA));
  globalThis.fetch = async (url, opts = {}) => {
    calls.push({ url: String(url), method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : undefined });
    if (String(url).endsWith('/dependencies/confirm')) {
      data.rows[2] = { ...data.rows[2], state: 'confirmed', state_words: 'confirmed · by dan · from docker-compose.yml' };
      return { ok: true, status: 200, json: async () => data };
    }
    return { ok: true, status: 200, json: async () => data };
  };
  const host = document.createElement('div');
  document.body.appendChild(host);
  await m.mountDependencyTable(host, 'p', { confirmable: true, me: 'dan' });
  const rowsShown = () => host.querySelectorAll('[data-dep-row]').length;
  assert.equal(rowsShown(), 3);
  host.querySelector('[data-dep-chip="runtime"]').click();          // turn runtime off
  assert.equal(rowsShown(), 2);
  assert.equal(host.querySelector('[data-dep-chip="runtime"]').getAttribute('aria-pressed'), 'false');
  host.querySelector('[data-dep-chip="runtime"]').click();          // and on again: everything
  assert.equal(rowsShown(), 3);
  host.querySelector('[data-dep-chip="build-time"]').click();       // turn build-time off: runtime only
  assert.equal(rowsShown(), 1);
  const b = host.querySelector('[data-dep-confirm]');
  b.click();
  assert.equal(b.disabled, true, 'a pressed control ignores a second press');
  assert.equal(b.textContent.trim(), 'confirming …', 'an immediate visible change');
  await wait();
  const posts = calls.filter((c) => c.method === 'POST');
  assert.equal(posts.length, 1);
  assert.deepEqual(posts[0].body, { keys: ['web->db@deploy/docker-compose.yml'], verdict: 'confirmed' });
  assert.match(text(host.querySelector('[data-dep-row] [data-dep-state]')), /confirmed · by dan · from docker-compose.yml/);
  assert.ok(host.querySelector('[data-dep-withdraw]'), 'a confirmed row offers withdraw');
});

test('a confirm that fails restores the control and says why, on the table', async () => {
  const { m, document } = await mod();
  globalThis.fetch = async (url, opts = {}) => (opts.method === 'POST'
    ? { ok: false, status: 401, statusText: 'x', json: async () => ({ detail: 'sign in' }) }
    : { ok: true, status: 200, json: async () => DATA });
  const host = document.createElement('div');
  document.body.appendChild(host);
  await m.mountDependencyTable(host, 'p', { confirmable: true, me: 'dan' });
  const b = host.querySelector('[data-dep-confirm]');
  b.click();
  await wait();
  assert.equal(host.querySelector('[data-dep-confirm]').disabled, false);
  assert.match(text(host.querySelector('[data-dep-status]')), /sign in to confirm/);
});

test('under Curate a measured row carries its word without a check mark; a confirmed one keeps it', async () => {
  const { m, document } = await mod();
  const box = document.createElement('div');
  const confirmed = { ...DATA, rows: [...DATA.rows.slice(0, 2), { ...DATA.rows[2], state: 'confirmed', state_words: 'confirmed · by dan · from docker-compose.yml' }] };
  box.innerHTML = m.dependencyTableHtml(confirmed, {}, { confirmable: true, me: 'dan' });
  assert.equal(text(box.querySelector('[data-dep-row="python:fastapi@pyproject.toml"] [data-dep-state]')), 'measured · from pyproject.toml');
  assert.match(text(box.querySelector('[data-dep-row="web->db@deploy/docker-compose.yml"] [data-dep-state]')), /^✓ confirmed · by dan/);
});
