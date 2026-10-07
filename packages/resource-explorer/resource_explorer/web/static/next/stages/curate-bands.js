/* Curate bands that are the same on every resource kind.
 *
 * REPLY-DESIGNER-CURATE-AND-UNDERSTANDING-ALL-KINDS.md §1-2 and
 * wireframes/CurateAndUnderstanding.dc.html (page 16): Curate is "make it
 * findable and reusable", so every kind gets
 *   1. Findable  -- group (with its change control inline) and tags (chips,
 *                   autocomplete from GET /api/curate/tags). Local, not in Egeria.
 *   2. the kind's own work -- repo: the existing plan view (curate.js);
 *                   database: "What gets catalogued" (the scope tree,
 *                   curate-scope.js) first, then two sections that wait on
 *                   readers, each saying what for; file system: one sentence.
 *   3. What people say -- ratings as COUNTS (never an average), and notes as
 *                   the signed append-only journal, with Classic's curator
 *                   notes read-only beneath it.
 *
 * Rules this file keeps (CURATE-UI-DATABASES-IMPLEMENTED.md):
 *  - what a list shows is what the server returned on a re-read AFTER a write,
 *    never what the click handler assumed; a status sentence is derived from
 *    those rows;
 *  - every write control is disabled, with a plain reason, when nobody is
 *    signed in (the routes answer 401 then);
 *  - an author label is always shown. The server supplies `author_label`;
 *    this file falls back to the same words rather than ever drawing blank;
 *  - nothing here reads back from Egeria, and nothing publishes to it.
 */
import { ago, savedLine } from '/static/next/format.js';
import {
  getCurateTagsDetail, getCurateAllTags, addCurateTag, removeCurateTag,
  getCurateFeedback, addCurateFeedback, getCurateNotes, deleteCurateNote,
  assignGroup, listGroups, getDataClassRules,
} from '/static/re-api.js';
import {
  state, esc, tnum, refreshGroupsAndSidebar,
  renderJournalWrite, renderJournalEntries,
} from '/static/next/app.js';

export const UNSIGNED_LABEL = 'unsigned · from before authors were recorded';
const FEEDBACK_CATEGORIES = [
  ['', 'Category (optional)'], ['quality', 'Quality'], ['documentation', 'Documentation'],
  ['usefulness', 'Usefulness'], ['other', 'Other'],
];

const whoAmI = () =>
  (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
const stars = (n) => '★'.repeat(n);
const label = (row) => row.author_label || (row.author ? row.author : UNSIGNED_LABEL);
const day = (iso) => String(iso || '').replace('T', ' ').slice(0, 10);
const newestFirst = (rows) =>
  [...rows].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
/** The reason shown beside a write control that is disabled because nobody is signed in. */
const signInReason = (what) => `sign in to ${what} — it needs an author`;
const stale = (el, slug) => !el.isConnected || slug !== state.selectedSlug;

const bandHead = (title, extra = '') => `<div class="mb-s1 flex flex-wrap items-baseline gap-x-s2 text-caps uppercase tracking-caps text-ink-muted">
  <span class="text-ink">${esc(title)}</span>${extra}</div>`;

/* ── Band 2, database: present, explained, never an empty table ──────── */

const DB_WORK_SECTIONS = [
  {
    id: 'glossary',
    title: 'Glossary terms on tables and columns',
    waits: 'No proposals yet: needs data classes per column (data_class_match) and a glossary to match against, and the tables to be cataloged first (above).',
  },
  {
    id: 'schema-match',
    title: 'Logical schema match',
    waits: 'No proposals yet: needs the logical schemas Egeria knows to be read, and the tables to be cataloged first (above). Rows will be proposed, then confirmed, overridden, or flagged when a later survey disagrees.',
  },
];

/** The first section of a database's band 2: what gets catalogued (the
 *  scope tree, curate-scope.js, fills `[data-curate-scope]`). It comes first
 *  because the two sections below act on its output. */
export function databaseScopeHtml() {
  return `<div data-curate-work="scope" class="mb-s3 min-w-0">
    <div class="text-answer text-ink">What gets cataloged</div>
    <div data-curate-scope class="mt-s1 min-w-0 max-w-full text-caveat text-ink-muted">Reading the catalog scope…</div></div>`;
}

export function databaseWorkHtml() {
  // The rules block sits INSIDE the glossary (term) section, not beside it: the section order the
  // stage pins (scope, glossary, schema-match) is unchanged.
  return databaseScopeHtml() + DB_WORK_SECTIONS.map((s) => `<div data-curate-work="${s.id}" class="mb-s2">
    <div class="text-answer text-ink">${esc(s.title)}</div>
    <div class="text-caveat text-ink-muted">${esc(s.waits)}</div>${s.id === 'glossary' ? rulesBlockShellHtml() : ''}</div>`).join('');
}

/* ── PI-041: "Rules Egeria applies", read-only ───────────────────────────
 * Lists the data-class rules the server reads (`GET /api/egeria/rules/dataclasses`). That route
 * answers per rule with its own `source`: "Egeria (Active)" when the keywords were read from
 * Egeria's valid values, "Local Fallback" when the server used RE's built-in keyword list. Only the
 * first kind is called Egeria's; the second is shown apart, labelled as not read from Egeria, so the
 * block never claims a rule Egeria did not give. When nothing came from Egeria the block says "no
 * reader yet". It has no control and writes nothing. */
export function rulesBlockShellHtml() {
  return `<div data-curate-rules class="mt-s2 min-w-0">
    <div class="text-caveat text-ink">Rules Egeria applies</div>
    <div data-rules-body class="text-caveat text-ink-muted">Reading the data-class rules…</div></div>`;
}

const ruleRow = (r) => `<div data-rule="${esc(r.name)}" class="mt-[2px]">
  <span class="font-semibold text-ink">${esc(r.display_name || r.name)}</span>
  <span class="text-ink-muted"> — ${esc(r.description || '')}</span>
  <div class="text-provenance text-ink-muted">keywords: <span class="font-mono">${(r.keywords || []).map(esc).join(', ') || 'none'}</span></div></div>`;

/** The block's body from the route's answer (`rules`) or its failure (`error`). Pure. */
export function rulesBodyHtml(rules, error = '') {
  if (error) {
    return `<div data-rules-state="no_reader" class="text-caveat text-ink">no reader yet — the data-class rules could not be read: ${esc(error)}</div>`;
  }
  const list = Array.isArray(rules) ? rules : [];
  const fromEgeria = list.filter((r) => /^egeria/i.test(String(r.source || '')));
  const builtIn = list.filter((r) => !/^egeria/i.test(String(r.source || '')));
  const local = builtIn.length
    ? `<details data-rules-local class="mt-[2px]"><summary class="cursor-pointer text-provenance text-accent-ink underline">RE's built-in keyword list, not read from Egeria (${builtIn.length})</summary>${builtIn.map(ruleRow).join('')}</details>`
    : '';
  if (!fromEgeria.length) {
    return `<div data-rules-state="no_reader" class="text-caveat text-ink">no reader yet — Egeria's own data-class rules were not read${
      list.length ? `; the server answered only RE's built-in keyword list (${list.length} rules)` : '; the server answered no rules'}.</div>${local}`;
  }
  return `<div data-rules-state="read" data-rules-egeria>${fromEgeria.map(ruleRow).join('')}</div>${local}`;
}

/** Fill the block. A failure says so in the block; it never throws into the pane. */
export async function renderRulesBlock(slot) {
  if (!slot) return;
  const body = slot.querySelector('[data-rules-body]');
  try {
    body.innerHTML = rulesBodyHtml(await getDataClassRules());
  } catch (err) {
    if (slot.isConnected) body.innerHTML = rulesBodyHtml(null, err.message);
  }
}

export const FILESYSTEM_WORK_SENTENCE =
  'Nothing to review for file systems yet. Group, tags, ratings and notes above and below apply.';

export function filesystemWorkHtml() {
  return `<div data-curate-work="filesystem" class="text-caveat text-ink-muted">${esc(FILESYSTEM_WORK_SENTENCE)}</div>`;
}

/* ── Band 1: Findable ─────────────────────────────────────────────────── */

function currentGroupSlug(slug) {
  const rows = state.resourceType === 'db' ? state.databases
    : state.resourceType === 'filesystem' ? state.filesystems : state.projects;
  return ((rows || []).find((r) => r.slug === slug) || {}).group_slug || '';
}

const groupName = (gslug) =>
  gslug ? ((state.groups || []).find((g) => g.slug === gslug)?.display_name || gslug) : 'Ungrouped';

export async function renderFindableBand(el, slug, entityType, status = '') {
  if (!el) throw new Error('Findable band host missing');
  if (status === '') el.innerHTML = `<div class="text-caveat text-ink-muted">Reading tags…</div>`;
  let tags;
  let allTags = [];
  try {
    [tags, allTags] = await Promise.all([
      getCurateTagsDetail(entityType, slug),
      getCurateAllTags().catch(() => []),
    ]);
    if (!(state.groups || []).length) {
      try { state.groups = (await listGroups()) || []; } catch { /* the select says there are none */ }
    }
  } catch (err) {
    if (stale(el, slug)) return;
    el.innerHTML = `${bandHead('Findable')}<div class="text-caveat text-state-warn">Tags could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (stale(el, slug)) return;

  const me = whoAmI();
  const gslug = currentGroupSlug(slug);
  const groups = state.groups || [];
  const options = [`<option value="">— Ungrouped —</option>`]
    .concat(groups.map((g) => `<option value="${esc(g.slug)}" ${g.slug === gslug ? 'selected' : ''}>${esc(g.display_name || g.slug)}</option>`));
  if (gslug && !groups.some((g) => g.slug === gslug)) {
    options.push(`<option value="${esc(gslug)}" selected>${esc(gslug)}</option>`);
  }
  const chips = tags.length
    ? tags.map((t) => `<span data-curate-tag="${esc(t.tag)}" title="added by ${esc(label(t))}"
        class="inline-flex items-baseline gap-[4px] rounded-sm border border-rule-strong px-[6px] py-[1px] text-caveat text-ink">${esc(t.tag)}
        <button type="button" data-curate-tag-remove="${esc(t.tag)}" aria-label="remove tag ${esc(t.tag)}"
          ${me ? '' : `disabled title="${esc(signInReason('remove a tag'))}"`}
          class="${me ? 'cursor-pointer' : 'opacity-60'} bg-transparent p-0 text-ink-muted">×</button></span>`).join(' ')
    : `<span class="text-caveat text-ink-muted">No tags yet.</span>`;

  el.innerHTML = `${bandHead('Findable', `<span class="normal-case tracking-normal">· local · not in Egeria</span>`)}
    <div class="mb-s1 flex flex-wrap items-baseline gap-s2 text-caveat">
      <span class="text-ink-muted">group</span>
      <span data-curate-group-now class="text-ink">${esc(groupName(gslug))}</span>
      <select data-curate-group-select aria-label="group" class="rounded-sm border border-rule-strong bg-transparent px-1 text-caveat text-ink">${options.join('')}</select>
      <button type="button" data-curate-group-save class="cursor-pointer bg-transparent p-0 text-accent-ink underline">change</button>
      <span class="text-provenance text-ink-muted">${groups.length ? 'Admin keeps the full group manager' : 'no groups defined yet — Admin has the group manager'}</span>
    </div>
    <div class="mb-s1 flex flex-wrap items-baseline gap-s2">
      <span class="text-caveat text-ink-muted">tags</span>${chips}
    </div>
    <div class="flex flex-wrap items-baseline gap-s2 text-caveat">
      <input data-curate-tag-input list="curate-tag-datalist" type="text" placeholder="＋ tag" aria-label="add a tag"
        ${me ? '' : 'disabled'}
        class="w-[16ch] rounded-sm border border-rule-strong bg-transparent px-[4px] text-caveat text-ink placeholder:text-ink-muted">
      <datalist id="curate-tag-datalist">${(allTags || []).map((t) => `<option value="${esc(t.tag)}"></option>`).join('')}</datalist>
      <button type="button" data-curate-tag-add ${me ? '' : 'disabled'}
        class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">Save</button>
      <span data-curate-findable-status class="text-provenance text-ink-muted">${esc(me ? status : signInReason('add or remove a tag'))}</span>
    </div>`;

  const statusEl = el.querySelector('[data-curate-findable-status]');
  const say = (msg, warn = false) => {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.className = `text-provenance ${warn ? 'text-state-warn' : 'text-ink-muted'}`;
  };
  const failure = (err, what) => (err.status === 401 ? signInReason(what) : `${what} failed: ${err.message}`);

  // The words after a write come from the re-read rows, not from the click.
  const reload = async (verify) => {
    let rows;
    try { rows = await getCurateTagsDetail(entityType, slug); }
    catch (err) { say(`written, but the list could not be re-read: ${err.message}`, true); return; }
    await renderFindableBand(el, slug, entityType, verify(rows));
  };

  const addTag = async () => {
    const input = el.querySelector('[data-curate-tag-input]');
    const tag = (input.value || '').trim();
    if (!tag) { input.focus(); return; }
    try { await addCurateTag(entityType, slug, tag); }
    catch (err) { say(failure(err, 'add the tag'), true); return; }
    await reload((rows) => {
      const mine = rows.find((r) => r.tag === tag.toLowerCase());
      return mine ? `${savedLine(mine.author_label || mine.author, mine.created_at)} · tag “${tag.toLowerCase()}” is on the list`
        : `the write returned, but “${tag.toLowerCase()}” is not in the re-read list`;
    });
  };
  el.querySelector('[data-curate-tag-add]').addEventListener('click', addTag);
  el.querySelector('[data-curate-tag-input]').addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); addTag(); }
  });
  el.querySelectorAll('[data-curate-tag-remove]').forEach((b) => b.addEventListener('click', async () => {
    const tag = b.dataset.curateTagRemove;
    try { await removeCurateTag(entityType, slug, tag); }
    catch (err) { say(failure(err, 'remove the tag'), true); return; }
    await reload((rows) => (rows.some((r) => r.tag === tag)
      ? `“${tag}” is still on the list after the removal`
      : `tag “${tag}” is off the list`));
  }));

  el.querySelector('[data-curate-group-save]').addEventListener('click', async () => {
    const want = el.querySelector('[data-curate-group-select]').value;
    let saved;
    try { saved = await assignGroup(slug, want, entityType); }
    catch (err) { say(failure(err, 'change the group'), true); return; }
    try { await refreshGroupsAndSidebar(); } catch { /* the re-read below says what the row now holds */ }
    if (stale(el, slug)) return;
    const now = currentGroupSlug(slug);
    await renderFindableBand(el, slug, entityType,
      now === want ? `${savedLine((saved || {}).saved_by, (saved || {}).saved_at)} · group is now ${groupName(now)}`
        : `the change returned, but the list still shows ${groupName(now)}`);
  });
}

/* ── Band 3: What people say ─────────────────────────────────────────── */

export function ratingsHeadline(feedback) {
  const rated = feedback.filter((f) => f.rating != null && f.rating !== '');
  const unrated = feedback.length - rated.length;
  const levels = [5, 4, 3, 2, 1]
    .map((n) => [n, rated.filter((f) => Number(f.rating) === n).length])
    .filter(([, c]) => c > 0);
  const counts = rated.length
    ? `${rated.length} · ${levels.map(([n, c]) => `${stars(n)} ${c}`).join(' · ')}`
    : 'none yet';
  return `${counts}${unrated ? ` · ${unrated} comment${unrated === 1 ? '' : 's'} without a rating` : ''}`;
}

function feedbackEntryHtml(f) {
  return `<div data-curate-feedback class="border-t border-rule py-s1">
    <div class="text-caveat text-ink">${f.rating ? `<span class="text-ink">${esc(stars(Number(f.rating)))}</span> ` : ''}${
      f.category ? `<span class="text-ink-muted">${esc(f.category)}</span> — ` : ''}${tnum(esc(f.message))}</div>
    <div class="text-provenance text-ink-muted">${esc(label(f))} · <span class="tnum">${esc(day(f.created_at))}</span></div>
  </div>`;
}

export async function renderRatingsBand(el, slug, entityType, status = '') {
  if (!el) throw new Error('Ratings band host missing');
  if (status === '') el.innerHTML = `<div class="text-caveat text-ink-muted">Reading ratings…</div>`;
  let feedback;
  try { feedback = await getCurateFeedback(entityType, slug); }
  catch (err) {
    if (stale(el, slug)) return;
    el.innerHTML = `${bandHead('Ratings')}<div class="text-caveat text-state-warn">Ratings could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (stale(el, slug)) return;
  const me = whoAmI();
  const dis = me ? '' : `disabled title="${esc(signInReason('rate or comment'))}"`;
  el.innerHTML = `${bandHead('Ratings', `<span data-curate-ratings-headline class="normal-case tracking-normal text-ink">· ${esc(ratingsHeadline(feedback))}</span>`)}
    ${newestFirst(feedback).map(feedbackEntryHtml).join('')}
    <div class="mt-s2 flex flex-wrap items-baseline gap-s2 text-caveat">
      <span class="text-ink-muted">rate it</span>
      <select data-curate-fb-rating aria-label="rating" ${dis} class="rounded-sm border border-rule-strong bg-transparent px-1 text-caveat text-ink">
        <option value="">No rating</option>
        ${[5, 4, 3, 2, 1].map((n) => `<option value="${n}">${stars(n)}</option>`).join('')}
      </select>
      <select data-curate-fb-category aria-label="category" ${dis} class="rounded-sm border border-rule-strong bg-transparent px-1 text-caveat text-ink">
        ${FEEDBACK_CATEGORIES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join('')}
      </select>
    </div>
    <textarea data-curate-fb-message rows="2" ${dis} placeholder="How well did it serve you? A message is required."
      class="mt-s1 w-full rounded-sm border border-rule-strong bg-transparent p-s2 text-caveat text-ink placeholder:text-ink-muted"></textarea>
    <div class="mt-s1 flex items-baseline gap-s3">
      <button type="button" data-curate-fb-submit ${dis}
        class="${me ? 'cursor-pointer' : 'opacity-60'} rounded-sm border border-accent bg-transparent px-2 py-[2px] text-caveat text-accent-ink">Save rating</button>
      <span data-curate-ratings-status class="text-provenance text-ink-muted">${esc(me ? status : signInReason('rate or comment'))}</span>
    </div>`;
  const say = (msg, warn) => {
    const s = el.querySelector('[data-curate-ratings-status]');
    s.textContent = msg; s.className = `text-provenance ${warn ? 'text-state-warn' : 'text-ink-muted'}`;
  };
  el.querySelector('[data-curate-fb-submit]').addEventListener('click', async () => {
    const message = el.querySelector('[data-curate-fb-message]').value.trim();
    if (!message) { say('write a message — feedback needs one', true); el.querySelector('[data-curate-fb-message]').focus(); return; }
    const r = el.querySelector('[data-curate-fb-rating]').value;
    const category = el.querySelector('[data-curate-fb-category]').value;
    const b = el.querySelector('[data-curate-fb-submit]'); b.disabled = true;
    try { await addCurateFeedback(entityType, slug, { rating: r ? Number(r) : null, category, message }); }
    catch (err) {
      b.disabled = false;
      say(err.status === 401 ? signInReason('rate or comment') : `not saved: ${err.message}`, true);
      return;
    }
    let rows;
    try { rows = await getCurateFeedback(entityType, slug); }
    catch (err) { b.disabled = false; say(`saved, but the list could not be re-read: ${err.message}`, true); return; }
    await renderRatingsBand(el, slug, entityType,
      (() => {
        const mine = [...rows].reverse().find((x) => x.message === message);
        return mine ? `${savedLine(mine.author_label || mine.author, mine.created_at)} · it is in the list above`
          : 'the save returned, but the entry is not in the re-read list';
      })());
  });
}

/** Classic's curator notes: read-only, newest first, beneath the journal.
 *  Only an UNSIGNED note can be deleted from here (a signed one has an author
 *  to protect, and the server answers 409). */
export async function renderClassicNotes(el, slug, entityType, status = '') {
  if (!el) throw new Error('Classic notes host missing');
  let notes;
  try { notes = await getCurateNotes(entityType, slug); }
  catch (err) {
    if (stale(el, slug)) return;
    el.innerHTML = `<div class="text-caveat text-state-warn">Curator notes from Classic could not be read: ${esc(err.message)}</div>`;
    return;
  }
  if (stale(el, slug)) return;
  if (!notes.length) { el.innerHTML = status ? `<div class="text-provenance text-ink-muted">${esc(status)}</div>` : ''; return; }
  const me = whoAmI();
  const unsigned = notes.filter((n) => !n.authored).length;
  el.innerHTML = `<div class="mb-s1 text-caps uppercase tracking-caps text-ink-muted">Curator notes from Classic · <span class="tnum">${notes.length}</span> · ${
    unsigned === notes.length ? 'unsigned' : `<span class="tnum">${unsigned}</span> unsigned`}</div>
    ${newestFirst(notes).map((n) => `<div data-curate-classic-note="${esc(n.id)}" class="border-t border-rule py-s1">
      <div class="text-caveat text-ink">${tnum(esc(n.note))}</div>
      <div class="text-provenance text-ink-muted">${esc(label(n))} · <span class="tnum">${esc(day(n.created_at))}</span>${
        n.authored ? '' : ` · <button type="button" data-curate-note-delete="${esc(n.id)}" ${me ? '' : `disabled title="${esc(signInReason('delete a note'))}"`}
          class="${me ? 'cursor-pointer text-accent-ink underline' : 'opacity-60 text-ink-muted'} bg-transparent p-0">delete</button>${
          me ? '' : ` <span>${esc(signInReason('delete a note'))}</span>`}`}
        <span data-curate-note-confirm="${esc(n.id)}"></span></div>
    </div>`).join('')}
    <div data-curate-notes-status class="text-provenance text-ink-muted">${esc(status)}</div>`;
  el.querySelectorAll('[data-curate-note-delete]').forEach((b) => b.addEventListener('click', () => {
    const id = b.dataset.curateNoteDelete;
    const slot = el.querySelector(`[data-curate-note-confirm="${id}"]`);
    slot.innerHTML = ` Delete this unsigned note? <button type="button" data-yes class="cursor-pointer bg-transparent p-0 text-accent-ink underline">delete</button> <button type="button" data-no class="cursor-pointer bg-transparent p-0 text-ink underline">keep</button>`;
    slot.querySelector('[data-no]').addEventListener('click', () => { slot.innerHTML = ''; });
    slot.querySelector('[data-yes]').addEventListener('click', async () => {
      try { await deleteCurateNote(id); }
      catch (err) {
        slot.innerHTML = ` <span class="text-state-warn">${esc(err.status === 401 ? signInReason('delete a note') : err.message)}</span>`;
        return;
      }
      let rows;
      try { rows = await getCurateNotes(entityType, slug); } catch { rows = null; }
      await renderClassicNotes(el, slug, entityType,
        rows && !rows.some((n) => n.id === id) ? 'note deleted' : 'the delete returned, but the note is still in the list');
    });
  }));
}

/** Notes: the journal (the same component and data as Disposition's) plus
 *  Classic's notes beneath it. */
export async function renderNotesBand(el, slug, entityType) {
  if (!el) throw new Error('Notes band host missing');
  el.innerHTML = `${bandHead('Notes', `<span class="normal-case tracking-normal">· the journal · why it matters, and to whom · append-only</span>`)}
    <div id="journal-write"></div>
    <div id="journal-entries" class="mt-s2 text-caveat text-ink-muted">Reading the journal…</div>
    <div data-curate-classic-notes class="mt-s3"></div>`;
  renderJournalWrite(slug, entityType);
  await Promise.all([
    renderJournalEntries(slug, entityType),
    renderClassicNotes(el.querySelector('[data-curate-classic-notes]'), slug, entityType),
  ]);
}

/** Band 3 as a whole: ratings, then notes. */
export async function renderPeopleBand(el, slug, entityType) {
  if (!el) throw new Error('What-people-say band host missing');
  el.innerHTML = `${bandHead('What people say')}
    <div data-curate-ratings class="mb-s3"></div>
    <div data-curate-notes></div>`;
  await Promise.all([
    renderRatingsBand(el.querySelector('[data-curate-ratings]'), slug, entityType),
    renderNotesBand(el.querySelector('[data-curate-notes]'), slug, entityType),
  ]);
}

/** The frame every kind shares (G1 added `publish`, the Egeria band, after the kind's own work). Returns the band hosts; the kind's own
 *  work goes in `kind`. `findable` and `people` are filled by the callers
 *  below so that a repo can fill `people` after its (slow) plan loads. */
export function bandFrameHtml() {
  return `<section data-curate-band="findable" class="mb-s4 border-b border-rule pb-s2"></section>
    <section data-curate-band="kind" class="mb-s4"></section>
    <section data-curate-band="publish" class="mb-s4 border-b border-rule pb-s2"></section>
    <section data-curate-band="people" class="mb-s4"></section>`;
}
