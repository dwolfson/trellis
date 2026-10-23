/** Behaviour (architect rulings 2026-10-23):
 *  (A) the LANGUAGE tile names its source with a visible chip, "measured" (solid) or "GitHub" (outline); the basis is
 *      in the hover; neither source keeps the existing "not measured" cue, never an empty "measured".
 *  (B) the catalogue read-back is three count chips in a fixed order, "published by RE N", "attached N",
 *      "catalogued by Egeria N", each with its cue (✓ / ◌), and "not checked since" on a stale pending count.
 *      The word "waiting" is gone. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

async function load(path) {
  makeDomEnvironment();
  ensureLoaderRegistered();
  return import(path);
}
const strip = (h) => h.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
const languageTile = (h) => (/<div data-scouting-tile="language"[\s\S]*?<\/div><\/div>/.exec(h) || [''])[0];

const MEASURED = {
  value: 'Python', source: 'measured', chip: 'measured', basis: 'source files 839/983',
  hover: 'measured · 839 of 983 source files · 2026-10-20\nGitHub says HTML (by bytes)',
  disagreement: 'GitHub says HTML (by bytes)',
};

test('measured: value with a solid "measured" chip, basis and disagreement in the hover', async () => {
  const { scoutingTilesHtml } = await load('/static/next/stages/repo-header.js');
  const t = languageTile(scoutingTilesHtml({ primary_language: 'Python', language: MEASURED, stats_unread: [] }));
  assert.match(t, /data-language-source="measured"[^>]*class="[^"]*bg-ink[^"]*text-paper/);
  assert.equal(strip(t), 'LanguagePython measured');
  assert.match(t, /title="measured · 839 of 983 source files · 2026-10-20\nGitHub says HTML \(by bytes\)"/);
});

test('GitHub only: outline "GitHub" chip and the by-bytes hover, no disagreement line', async () => {
  const { scoutingTilesHtml } = await load('/static/next/stages/repo-header.js');
  const lang = { value: 'HTML', source: 'github', chip: 'GitHub', basis: 'bytes', hover: 'GitHub · primary by bytes · fetched 2026-10-19', disagreement: '' };
  const t = languageTile(scoutingTilesHtml({ primary_language: 'HTML', language: lang, stats_unread: [] }));
  assert.match(t, /data-language-source="github"[^>]*class="[^"]*border-rule-strong/);
  assert.ok(!/bg-ink/.test(t));
  assert.equal(strip(t), 'LanguageHTML GitHub');
  assert.match(t, /title="GitHub · primary by bytes · fetched 2026-10-19"/);
  assert.ok(!/says/.test(t));
});

test('neither source: the existing "not read" cue, never an empty "measured"', async () => {
  const { scoutingTilesHtml } = await load('/static/next/stages/repo-header.js');
  const t = languageTile(scoutingTilesHtml({ primary_language: '', language: { value: '', source: '' }, stats_unread: ['primary_language'] }));
  assert.match(t, /data-unread/);
  assert.ok(!/data-language-source/.test(t));
  assert.ok(!/measured/.test(strip(t)));
});

const chips = (published, attached, catalogued, cue, stale = '') => ({ chips: [
  { key: 'published', word: 'published by RE', count: published, cue: published ? 'read_back' : 'none', hover: 'the server and database elements RE published · read 10-23 09:00', not_checked_since: '' },
  { key: 'attached', word: 'attached', count: attached, cue: attached ? 'read_back' : 'none', hover: 'chosen schemas attached', not_checked_since: '' },
  { key: 'catalogued', word: 'catalogued by Egeria', count: catalogued, cue, hover: 'chosen schemas whose tables Egeria built', not_checked_since: stale },
] });

test('read-back chips: three in a fixed order, ✓ on read back, ◌ while the cataloguer has not run', async () => {
  const { readBackChipsHtml } = await load('/static/next/stages/curate-scope.js');
  const h = readBackChipsHtml(chips(2, 2, 0, 'pending'));
  assert.deepEqual([...h.matchAll(/data-read-back-chip="([a-z]+)"/g)].map((m) => m[1]), ['published', 'attached', 'catalogued']);
  assert.equal(strip(h), 'published by RE 2 ✓attached 2 ✓catalogued by Egeria 0 ◌');
  assert.ok(!/waiting/.test(h));
  assert.match(h, /data-read-back-chip="published"[^>]*title="the server and database elements RE published · read 10-23 09:00"/);
});

test('read-back chips: the tree built reads "catalogued by Egeria 18 ✓"', async () => {
  const { readBackChipsHtml } = await load('/static/next/stages/curate-scope.js');
  assert.match(strip(readBackChipsHtml(chips(2, 18, 18, 'read_back'))), /catalogued by Egeria 18 ✓$/);
});

test('read-back chips: a stale pending count says "not checked since"', async () => {
  const { readBackChipsHtml } = await load('/static/next/stages/curate-scope.js');
  const h = readBackChipsHtml(chips(2, 2, 0, 'pending', '2026-10-23T09:12:00'));
  assert.match(h, /data-read-back-not-checked/);
  assert.match(strip(h), /catalogued by Egeria 0 ◌ ◌ not checked since 09:12$/);
});

test('read-back chips: nothing derived draws nothing; the scope section carries the row under its header', async () => {
  const { readBackChipsHtml, scopeSectionHtml } = await load('/static/next/stages/curate-scope.js');
  assert.equal(readBackChipsHtml(null), '');
  assert.equal(readBackChipsHtml({ chips: [] }), '');
  const view = { schemas: [], declared: { declared: true }, commit: { header: { state: 'committed', text: 'Database element abcd1234 in Egeria' }, read_back: chips(2, 2, 1, 'pending') } };
  const h = scopeSectionHtml(view, { user_id: 'me' });
  assert.match(h, /data-scope-commit-header[\s\S]*data-read-back-host[\s\S]*data-read-back-chip="published"[\s\S]*data-read-back-chip="attached"[\s\S]*data-read-back-chip="catalogued"/);
});
