/** The blueprint's shape, named before the write (owner, 2026-10-08; DESIGN-BLUEPRINT-BENCHMARK-EGERIA-WORKSPACES.md 6a). */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

async function curate() {
  ensureLoaderRegistered();
  const { document } = makeDomEnvironment();
  const mod = await import(`/static/next/stages/curate.js?t=${Math.random()}`);
  return { mod, document };
}

const PLAN = {
  shape: 'container', default_shape: 'container', flip_to: 'contents', flip_refused: '',
  words: 'OMAG Server Platform as container · 6 sub-components',
  why: 'the root is a real component: built here',
  alternatives: {
    container: { shape: 'container', words: 'OMAG Server Platform as container · 6 sub-components', why: 'x', flip_refused: '' },
    contents: { shape: 'contents', words: 'OMAG Server Platform left out · 6 members · flipped', why: 'y', flip_refused: '' },
  },
};

test('the manifest names the shape and why, the chosen option reads "chosen"', async () => {
  const { mod, document } = await curate();
  const box = document.createElement('div');
  box.innerHTML = mod.shapeManifestHtml(PLAN);
  const text = box.textContent.replace(/\s+/g, ' ');
  assert.match(text, /shape · OMAG Server Platform as container · 6 sub-components/);
  assert.match(text, /the root is a real component: built here/);
  const [container, contents] = [...box.querySelectorAll('[data-shape-option]')];
  assert.equal(container.getAttribute('aria-pressed'), 'true');
  assert.match(container.textContent, /Container\s+chosen/);
  assert.equal(contents.getAttribute('aria-pressed'), 'false');
  assert.doesNotMatch(contents.textContent, /chosen/);
});

test('a refused flip is said beside the reason', async () => {
  const { mod, document } = await curate();
  const box = document.createElement('div');
  box.innerHTML = mod.shapeManifestHtml({ ...PLAN, shape: 'contents', default_shape: 'contents',
    words: 'root is a grouping · 6 members', why: 'no member is the cluster\'s root: it is a grouping',
    flip_refused: 'no member is the root, so there is nothing to be the container' });
  assert.match(box.textContent, /nothing to be the container/);
});

test('a cluster with no members has no manifest', async () => {
  const { mod } = await curate();
  assert.equal(mod.shapeManifestHtml(null), '');
});
