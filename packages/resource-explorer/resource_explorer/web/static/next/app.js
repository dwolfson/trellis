/* Resource Explorer — /next
 *
 * An experimental parallel UI. Skin 1c ("dark chrome, paper content") and one
 * redesigned screen: the Questions checklist, changed from reporting HOW a
 * question would be answered to reporting WHAT THE ANSWER IS, with its
 * caveat, its provenance and its state, per row.
 *
 * SCOPE, deliberately: the frame plus ONE real pane. That pane is Questions,
 * for a repo, live against the API — parameterised by stage rather than
 * duplicated per stage, because the endpoint already takes a `phase` and
 * because the six row states this screen argues for only ALL occur once you
 * leave Scouting. Every other sub-tab renders an honest "not built in /next"
 * rather than a half-working version: a half-built version of everything
 * proves nothing and takes ten times as long.
 *
 * THE ONE BEHAVIOUR THIS SCREEN EXISTS FOR: distinguishing "ran and found
 * nothing" from "never ran" from "cannot be answered here". The backend
 * already carries that distinction — `surveyors/result_status.py`'s states,
 * surfaced through `facts.py`'s Envelope — and this file must not collapse
 * it. A confident wrong answer is worse than no answer.
 */

import {
  ApiError,
  VALID_DISPOSITIONS,
  addInvestigationMember,
  ask,
  getAnswer,
  getMe,
  getQuestions,
  getScoutingOverview,
  listActivity,
  listGroups,
  listInvestigationMembers,
  listInvestigations,
  listPerspectives,
  listProjects,
  listRfas,
  pollActivity,
  removeInvestigationMember,
  removeProject,
  runAnalysis,
  sendFeedback,
  setDisposition,
  setWorkingSetHidden,
} from '/static/re-api.js';

/* ════════════════════════════════════════════════════════════════════════
 * State
 * ════════════════════════════════════════════════════════════════════════ */

const state = {
  resourceType: 'repo',        // repo | db | filesystem — only repo is real here
  projects: [],
  groups: [],
  selectedSlug: null,
  overview: null,              // the selected repo's scouting-overview, or null
  filter: '',
  scope: 'working-set',        // lifecycle scope chip; '' means All
  dispositionFacet: 'all',
  showHidden: false,
  showEmptyFacets: false,
  selectMode: false,
  selected: new Set(),
  investigations: [],
  investigation: '',           // slug; client-side only, no server session
  workingSet: new Set(),       // repo slugs in the current investigation
  workingSetUnknown: false,
  stage: 'scouting',
  subTab: 'questions',
  perspectives: [],            // the vocabulary, from the API — never hardcoded
  activePerspectives: new Set(),  // empty means all
  questions: [],              // the stage's questions AFTER perspective filtering
  allQuestions: null,         // the stage's questions UNFILTERED; null = unknown
  answers: new Map(),          // question text -> envelope | {error} | 'loading'
  runsInFlight: new Map(),     // question text -> {analysisId, activityId}
  me: null,
  counts: { activity: null, rfas: null },
  chat: [],                    // the transcript: one entry per turn
};

/** The eight intents, in their canonical order, plus Investigation as the
 *  frame. `built` is about /next, not about the product. */
const STAGES = [
  { id: 'investigation', label: 'Investigation', frame: true },
  { id: 'scouting',      label: 'Scouting',      built: true },
  { id: 'discovery',     label: 'Discovery' },
  { id: 'assessment',    label: 'Assessment' },
  { id: 'analysis',      label: 'Analysis' },
  { id: 'enrichment',    label: 'Enrichment' },
  // Understanding is MARKED, not dimmed: it has zero rows in both the
  // analysis catalog and the activity log, so presenting it as a peer of
  // four working stages is a claim the data does not support. Full
  // legibility, a dashed rule, and the words.
  { id: 'understanding', label: 'Understanding · not built', unbuilt: true },
  { id: 'curate',        label: 'Curate' },
  { id: 'automate',      label: 'Automate' },
];

/** Sub-tab order is IDENTICAL across every stage, on purpose. A stage that
 *  lacks one greys it out rather than removing it, so the tab under the
 *  cursor does not change meaning when you switch stages. */
const SUB_TABS = ['Search', 'Survey', 'Dashboard', 'Questions', 'Disposition'];

/* ════════════════════════════════════════════════════════════════════════
 * Helpers
 * ════════════════════════════════════════════════════════════════════════ */

const $ = (id) => document.getElementById(id);

/** The active stage's display label, for the pane header. */
const stageLabel = () =>
  STAGES.find((s) => s.id === state.stage)?.label || state.stage;

/** Escape for interpolation into a template literal that becomes innerHTML.
 *  Every value below that came from the API goes through this — question
 *  text, headlines and notes are authored content, and one unescaped `<`
 *  would silently eat the rest of a row. */
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // NAMED entities only, never numeric. `tnum()` below wraps every run of
    // digits in a span, and it runs after this — so a `&#39;` became
    // `&#<span…>39</span>;`, which the browser renders as the literal text
    // "&#39;". Seen on screen as "Egeria&#39;s catalog". Named entities carry
    // no digits, so the two passes stop interfering.
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

/** Wrap every run of digits in a tabular-figures span.
 *  Applied to answer, caveat and provenance lines — the places that hold
 *  counts, percentages, run numbers and ages. Running prose keeps its
 *  default figures, which is why this is applied per line and not to body. */
function tnum(html) {
  return html.replace(/(\d[\d,.]*%?)/g, '<span class="tnum">$1</span>');
}

/** "5d ago" / "3h ago" / "just now" — or "" when there is no timestamp,
 *  which is a real state and must not render as "now". */
function ago(iso) {
  if (!iso) return '';
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, (Date.now() - then) / 1000);
  if (secs < 90) return 'just now';
  const mins = secs / 60;
  if (mins < 90) return `${Math.round(mins)}m ago`;
  const hours = mins / 60;
  if (hours < 36) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/* ════════════════════════════════════════════════════════════════════════
 * Reading an envelope — the honest part
 * ════════════════════════════════════════════════════════════════════════ */

/** Fact states, from surveyors/result_status.py. */
const MEASURED = 'measured';
const NOTHING_FOUND = 'nothing_found';
const NOT_ESTABLISHED = 'not_established';
const NEVER_RUN = 'never_run';
const PARTIAL = 'partial';

/**
 * The six row states from the design's legend. Each is a different SENTENCE,
 * never a different shade of the same one.
 *
 * `answered`  — an analysis ran and produced a result
 * `automatic` — answered without a survey: a direct field, the registry, a chart
 * `unrun`     — nothing has run yet; there IS a surveyor
 * `human`     — needs someone to say; Enrichment's job
 * `no-surveyor` — nothing has run AND nothing can; no surveyor exists
 * `unclassified` — the catalog does not say how this would be answered
 */
function rowState(entry, env) {
  const kind = entry.kind || 'unknown';
  if (kind === 'gap') return 'no-surveyor';
  if (kind === 'human') return 'human';
  if (kind === 'unknown') return 'unclassified';
  if (env && env.answerable) {
    return ['direct', 'registry', 'chart'].includes(kind) ? 'automatic' : 'answered';
  }
  return 'unrun';
}

const GLYPH = {
  answered: '✓',      // ✓
  automatic: '✓',
  unrun: '○',         // ○
  human: '⚠',         // ⚠
  'no-surveyor': '○',
  unclassified: '·',  // ·
  running: '◔',       // ◔
  error: '✕',         // ✕
};

/** Verdict words the design sets at weight 600. Matched only at the head of
 *  a sentence and only when a separator follows, so a headline that merely
 *  starts with "No" as part of a phrase is left alone. Bolding the wrong
 *  word would assert a verdict the analysis did not make. */
const VERDICT = /^(Yes|No|Partly|Partially|Likely|Unlikely|Mixed|Narrowly maintained|Actively maintained)(\s*[—–,-]\s+)/;

/** Sentence case for a verdict word an analysis wrote in lower case. */
function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

function answerHtml(headline) {
  const m = VERDICT.exec(headline);
  if (!m) return tnum(esc(headline));
  const rest = headline.slice(m[0].length);
  return `<strong class="font-semibold">${esc(m[1])}</strong>${esc(m[2])}${tnum(esc(rest))}`;
}

/** The analysis's own prose, if it wrote any. Never assembled here. */
function prose(f) {
  const v = f.value || {};
  const text = v.detail || v.summary || v.description || '';
  return typeof text === 'string' ? text.trim() : '';
}

/** The scalar measures, relayed as `key value` pairs.
 *
 *  Deliberately last-resort. Structured fields (lists, objects) are NOT
 *  flattened into this line — they belong in `evidence`, where they can be
 *  read rather than skimmed. */
function scalarMeasures(value, max = 6) {
  if (!value || typeof value !== 'object') return '';
  const pairs = [];
  for (const [k, v] of Object.entries(value)) {
    if (v === null || v === undefined || v === '') continue;
    if (typeof v === 'object') continue;
    if (k === 'verdict') continue;   // already used as the verdict word
    const shown = typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v);
    if (shown.length > 60) continue;
    pairs.push(`${k.replace(/_/g, ' ')} ${shown}`);
    if (pairs.length >= max) break;
  }
  return pairs.join(' · ');
}

/**
 * Turn an envelope into the lines a row shows.
 *
 * The rule this function exists to keep: a fact's state decides the SENTENCE,
 * not just an icon. `nothing_found` is knowledge — a measured zero — and says
 * so. `never_run` says nothing ran. `not_established` says the method could
 * not settle it. Folding any two of those together is the failure the
 * FactLayer was built to prevent, and it would be undone here.
 */
function readEnvelope(entry, env) {
  const facts = (env && env.facts) || [];
  const known = facts.filter((f) => f.is_known);
  const lines = {
    answer: '', caveat: '', sources: [], lastRun: '', canRun: [],
    // Analyses that measured something but have no written summary, so the
    // answer line above is raw measures. Named, because the fix is a
    // headline_reader on that analysis and nobody can act on "somewhere".
    unwritten: [],
    // True when at least one fact is known but no fact recorded WHEN it ran.
    // Missing timestamp is a gap in the record, NOT evidence that nothing
    // ran — printing "never run" here would report a fact about the row as
    // a fact about the repository.
    runTimeUnrecorded: false,
  };

  for (const f of facts) {
    if (f.can_run && f.can_run.length) lines.canRun.push(...f.can_run);
    if (f.analysis_id) lines.sources.push(f.analysis_id);
    if (f.last_run_at && f.last_run_at > lines.lastRun) lines.lastRun = f.last_run_at;
  }
  lines.sources = [...new Set(lines.sources)];
  lines.canRun = [...new Set(lines.canRun)];

  // The answer, in preference order. Every rung RELAYS something the
  // analysis wrote; none of them composes a verdict here.
  //
  //   1. `headline`  — the analysis's own summary sentence.
  //   2. `value.detail` / `value.summary` — also its own prose, with
  //      `value.verdict` as the bolded verdict word when it states one.
  //   3. the scalar measures themselves, plus a caveat saying the analysis
  //      has no written summary.
  //
  // Rung 3 exists because most analyses do not have a headline_reader wired
  // up yet, and a row that shows a tick with nothing beside it is the exact
  // shape this screen was built to stop: a claim of "answered" with no
  // answer under it.
  const sentences = [];
  for (const f of known) {
    if (f.state === NOTHING_FOUND && !f.headline && !prose(f)) {
      // A measured zero. Said in words, because the bare number reads as
      // "we didn't look".
      sentences.push(tnum(esc(`${f.analysis_id} ran and found nothing.`)));
      continue;
    }
    if (f.headline) { sentences.push(answerHtml(f.headline)); continue; }
    const p = prose(f);
    if (p) {
      // The analysis's own verdict word, set at weight 600 like the design's
      // "Yes". Marked up here rather than re-detected from the joined string
      // downstream: this is the one place that knows the word came from a
      // `verdict` field rather than from the first word of a sentence.
      const verdict = f.value && f.value.verdict;
      sentences.push(verdict
        ? `<strong class="font-semibold">${esc(cap(String(verdict)))}</strong> — ${tnum(esc(p))}`
        : tnum(esc(p)));
      continue;
    }
    const scalars = scalarMeasures(f.value);
    if (scalars) {
      sentences.push(tnum(esc(scalars)));
      lines.unwritten.push(f.analysis_id);
    }
  }
  // NOTE: `lines.answer` is HTML, already escaped by each branch above.
  // Do not run it through esc() or answerHtml() again downstream.
  lines.answer = sentences.join(' ');

  // The caveat — the most important content on the screen. These sentences
  // already exist in the survey output; they used to sit three panes away in
  // the chat rail, which is not where the decision is made.
  const caveats = [];
  for (const f of facts) {
    if (f.note) caveats.push(f.note);
    if (f.state === PARTIAL && !f.note) {
      caveats.push(`${f.analysis_id} covered only part of what it measures.`);
    }
    if (f.state === NOT_ESTABLISHED && !f.note) {
      caveats.push(`${f.analysis_id} ran but could not establish a result.`);
    }
  }
  // A fact offered as evidence rather than as the answer says so, because
  // whether a resource REPLACES something you already have is a decision
  // about intent that no query settles.
  if (known.some((f) => f.evidence_only)) {
    caveats.push('Offered as evidence for a judgement, not as the judgement.');
  }
  lines.caveat = [...new Set(caveats)].join(' ');

  // Which facts have NOT run, when some have. A partly-answered row that
  // shows only the answered half is the confident-wrong-answer shape.
  const unrun = facts.filter((f) => f.state === NEVER_RUN).map((f) => f.analysis_id);
  if (known.length && unrun.length) {
    lines.caveat = `${lines.caveat} ${unrun.join(', ')} ${unrun.length === 1 ? 'has' : 'have'} not run, so this answer is partial.`.trim();
  }
  if (lines.unwritten.length) {
    lines.caveat = `${lines.caveat} ${lines.unwritten.join(', ')} ${
      lines.unwritten.length === 1 ? 'has' : 'have'} no written summary — the figures above are the raw measures.`.trim();
  }

  lines.runTimeUnrecorded = known.length > 0 && !lines.lastRun;

  return lines;
}

/* ════════════════════════════════════════════════════════════════════════
 * Chrome
 * ════════════════════════════════════════════════════════════════════════ */

function renderTopBar() {
  $('scope-slug').textContent = state.selectedSlug || 'no resource selected';
  const inv = state.investigations.find((i) => i.slug === state.investigation);
  $('investigation-name').textContent = state.investigation
    ? (inv?.display_name || state.investigation)
    : 'No investigation';
  $('whoami').textContent =
    (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || 'not signed in';
  $('activity-count').textContent =
    state.counts.activity === null ? '–' : state.counts.activity;
  const link = $('switch-ui');
  // Same resource in the other UI. index.html has no deep link for a
  // selected repo, so this is the app root — named, so nobody thinks the
  // selection carried over when it did not.
  link.textContent = state.selectedSlug
    ? '/next · open current UI'
    : '/next · open current UI';
}

function renderIntentNav() {
  const nav = $('intent-nav');
  const items = STAGES.map((s) => {
    const active = s.id === state.stage;
    if (s.frame) {
      return `<button data-stage="${s.id}" class="cursor-pointer bg-transparent px-3 py-[9px] font-heading
        text-accent-on-dark ${active ? 'border-b-2 border-accent' : 'border-b-2 border-transparent'}">${esc(s.label)}</button>`;
    }
    if (s.unbuilt) {
      // Marked, not dimmed: chrome-muted is a 6.7:1 role, not a fade.
      return `<span title="Not implemented — zero rows in the analysis catalog and the activity log"
        class="whitespace-nowrap px-3 pb-[1px] pt-[9px] text-chrome-muted"
        style="border-bottom:1px dashed currentColor">${esc(s.label)}</span>`;
    }
    return `<button data-stage="${s.id}" class="cursor-pointer bg-transparent px-3 py-[9px]
      ${active ? 'border-b-2 border-accent text-chrome-ink' : 'border-b-2 border-transparent text-chrome-muted hover:text-chrome-ink'}"
      >${esc(s.label)}</button>`;
  }).join('');

  nav.innerHTML = `${items}
    <span class="ml-auto flex gap-s2 text-subtab">
      <a href="/" title="The RFA drawer is not built in /next — opens the current UI"
        class="px-[10px] py-[9px] text-accent-on-dark no-underline"
        style="border-bottom:1px dashed currentColor">RFAs <span id="rfa-count" class="tnum">${
        state.counts.rfas === null ? '–' : state.counts.rfas}</span> ↗</a>
      <button id="chat-toggle" aria-expanded="true"
        class="cursor-pointer bg-transparent px-[10px] py-[9px] text-accent-on-dark">Chat ×</button>
    </span>`;

  $('chat-toggle').addEventListener('click', () => setRailOpen(!railIsOpen()));
  setRailOpen(railIsOpen());

  nav.querySelectorAll('button[data-stage]').forEach((b) => {
    b.addEventListener('click', () => {
      state.stage = b.dataset.stage;
      writeUrl();
      renderIntentNav();
      loadPane();
    });
  });
}

/**
 * The perspective row.
 *
 * The count and the residue are REQUIRED, not decoration: today a held
 * perspective that matched nothing is indistinguishable from one that
 * matched and passed. A chip that can only ever empty the list must say so.
 */
function renderPerspectiveRow() {
  const row = $('perspective-row');
  const held = state.activePerspectives;
  const total = state.perspectives.length;

  // Which perspectives match nothing AT THIS STAGE.
  //
  // Computed from the stage's UNFILTERED question set, never from the
  // filtered one. Reading it off the filtered set inverts the answer in
  // exactly the case the chip exists for: hold a perspective that matches
  // nothing, the filtered set is empty, so "matched" is empty too and the
  // chip reports nothing unusual. Seen live — `Privacy` hid all five
  // questions and rendered as an ordinary held chip.
  const matched = new Set();
  for (const q of state.allQuestions || []) {
    for (const p of q.perspectives || []) matched.add(p);
  }
  const questionsLoaded = Array.isArray(state.allQuestions);

  const chips = state.perspectives.map((p) => {
    const isHeld = held.has(p);
    if (isHeld && questionsLoaded && !matched.has(p)) {
      return `<button data-persp="${esc(p)}" class="cursor-pointer rounded-pill border border-dashed
        border-chrome-muted bg-transparent px-[9px] py-[2px] text-chrome-muted"
        >${esc(p)} · no questions here</button>`;
    }
    return `<button data-persp="${esc(p)}" class="cursor-pointer rounded-pill bg-transparent px-[9px] py-[2px]
      ${isHeld ? 'border border-accent text-accent-on-dark' : 'border border-chrome-line text-chrome-muted hover:border-accent'}"
      >${esc(p)}</button>`;
  }).join('');

  // The residue. Held perspectives narrow the checklist; how much they
  // narrowed it is the thing the old row never said.
  const shown = state.questions.length;
  const total_q = (state.allQuestions || []).length;
  const residue = !questionsLoaded || !held.size
    ? ''
    : `<span class="ml-auto text-chrome-muted"><span class="tnum">${shown}</span> of
       <span class="tnum">${total_q}</span> questions shown ·
       <span class="tnum">${Math.max(0, total_q - shown)}</span> hidden</span>`;

  row.innerHTML = `
    <span class="mr-1 font-heading uppercase tracking-caps text-caps">Perspective ·
      <span class="tnum">${held.size}</span> of <span class="tnum">${total}</span></span>
    ${chips}
    ${residue}`;

  row.querySelectorAll('button[data-persp]').forEach((b) => {
    b.addEventListener('click', () => {
      const p = b.dataset.persp;
      if (state.activePerspectives.has(p)) state.activePerspectives.delete(p);
      else state.activePerspectives.add(p);
      writeUrl();
      loadPane();
    });
  });
}


/* ════════════════════════════════════════════════════════════════════════
 * The sidebar — selection and grouping
 *
 * Restored wholesale after a first pass reduced it to a filter box and a
 * flat list. The handoff's advice to "show only non-zero disposition counts"
 * was about visual noise; read as a spec it deleted the disposition facets,
 * the scope chips, Select mode and the group tree together. These are not
 * chrome to be trimmed — a work list, the largest thing this UI is meant to
 * grow into, is built out of exactly this multi-select and grouping.
 * ════════════════════════════════════════════════════════════════════════ */

/** Lifecycle scope, matching the current UI's chips and their meanings. */
const SCOPE_CHIPS = [
  ['working-set', 'In scope'],   // needs a current investigation
  ['', 'All'],
  ['new', 'New'],
  ['surveyed', 'Surveyed'],
  ['published', 'Published'],
];

/** Where a repo is in the survey/catalog lifecycle. */
function lifecycleKind(p) {
  if (p.is_published) return 'published';
  if (p.last_surveyed_at) return 'surveyed';
  return 'new';
}

/** The mark shown beside a repo in the list.
 *
 *  Typographic, not emoji: the current UI uses ☁/📊/🆕 and 🔬/👍/✅, and this
 *  palette drops emoji as an icon system. Each mark carries a title so the
 *  glyph is never the only thing saying what it means. */
function lifecycleMark(p) {
  const kind = lifecycleKind(p);
  const mark = { published: '▣', surveyed: '▤', new: '▢' }[kind];
  const title = kind === 'published' ? 'Published to Egeria'
    : kind === 'surveyed' ? `Surveyed ${ago(p.last_surveyed_at)}`
    : 'Registered, not yet surveyed';
  return `<span title="${esc(title)}" class="text-chrome-muted">${mark}</span>`;
}

function dispositionMark(p) {
  const mark = { investigating: '◎', recommended: '✚', using: '●' }[p.disposition];
  if (!mark) return '';
  return `<span title="${esc(p.disposition)}" class="text-accent-on-dark">${mark}</span>`;
}

/** The repos passing every active filter, in list order. */
function visibleProjects() {
  const f = state.filter.trim().toLowerCase();
  return state.projects.filter((p) => {
    if (!state.showHidden && p.working_set_hidden) return false;
    if (state.dispositionFacet !== 'all'
        && (p.disposition || 'undecided') !== state.dispositionFacet) return false;
    if (state.scope === 'working-set') {
      if (!state.investigation) return false;
      if (!state.workingSet.has(p.slug)) return false;
    } else if (state.scope && lifecycleKind(p) !== state.scope) {
      return false;
    }
    if (f && !(`${p.slug} ${p.display_name}`.toLowerCase().includes(f))) return false;
    return true;
  });
}

function renderSidebar() {
  const el = $('sidebar');
  const types = [
    { id: 'repo', label: 'Repos' },
    { id: 'db', label: 'DBs' },
    { id: 'filesystem', label: 'FS' },
  ];

  const chip = (active, extra = '') =>
    `cursor-pointer rounded-pill bg-transparent px-2 py-[2px] ${extra} ${
      active ? 'border border-accent text-accent-on-dark'
             : 'border border-chrome-line text-chrome-muted hover:border-accent'}`;

  // Disposition counts over everything the filters have NOT already removed
  // by disposition, so the numbers describe the list you are choosing from.
  const counts = {};
  for (const p of state.projects) {
    if (!state.showHidden && p.working_set_hidden) continue;
    const d = p.disposition || 'undecided';
    counts[d] = (counts[d] || 0) + 1;
  }
  // Zeros are COLLAPSED, not removed — every disposition stays reachable
  // through the "more" control, because a facet you cannot select is a
  // filter you cannot undo.
  const present = Object.keys(counts).sort();
  const absent = VALID_DISPOSITIONS.filter((d) => !counts[d]);

  const visible = visibleProjects();
  const hiddenCount = state.projects.filter((p) => p.working_set_hidden).length;

  // Grouped by the repo's group. Group display names come from the groups
  // endpoint; a repo with no group lands in Ungrouped.
  const groups = new Map();
  for (const p of visible) {
    const g = p.group_slug || '';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(p);
  }
  const groupName = (slug) =>
    slug ? (state.groups.find((g) => g.slug === slug)?.display_name || slug) : 'Ungrouped';

  el.innerHTML = `
    <div class="mb-s2 flex gap-[5px] text-chip">
      ${types.map((t) => `<button data-type="${t.id}" class="${chip(state.resourceType === t.id).replace('rounded-pill', 'rounded-sm')}">${t.label}</button>`).join('')}
    </div>

    ${investigationBarHtml()}

    <input id="resource-filter" placeholder="Filter repos…" value="${esc(state.filter)}"
      class="mb-s2 w-full rounded-sm border border-chrome-line bg-transparent px-[9px] py-[5px]
             text-chip text-chrome-ink placeholder:text-chrome-muted">

    <div class="mb-s2 flex flex-wrap gap-[5px] text-caps">
      ${SCOPE_CHIPS.map(([id, label]) => {
        const disabled = id === 'working-set' && !state.investigation;
        return `<button data-scope="${id}" ${disabled ? 'disabled' : ''}
          title="${disabled ? 'Needs a current investigation' : ''}"
          class="${chip(state.scope === id)}${disabled ? ' border-dashed' : ''}">${label}</button>`;
      }).join('')}
    </div>

    <div class="mb-s2 flex flex-wrap gap-[5px] text-caps">
      <button data-facet="all" class="${chip(state.dispositionFacet === 'all')}">all</button>
      ${present.map((d) => `<button data-facet="${esc(d)}" class="${chip(state.dispositionFacet === d)}"
        >${esc(d)} <span class="tnum">${counts[d]}</span></button>`).join('')}
      ${absent.length && state.showEmptyFacets
        ? absent.map((d) => `<button data-facet="${esc(d)}" class="${chip(state.dispositionFacet === d)} border-dashed"
            >${esc(d)} <span class="tnum">0</span></button>`).join('')
        : absent.length
          ? `<button data-act="show-empty-facets" class="cursor-pointer bg-transparent text-chrome-muted underline"
              ><span class="tnum">${absent.length}</span> more…</button>`
          : ''}
    </div>

    <div class="mb-s3 flex flex-wrap items-baseline gap-s2 text-caps text-chrome-muted">
      <button data-act="select-mode" class="cursor-pointer bg-transparent ${
        state.selectMode ? 'text-accent-on-dark' : 'text-chrome-muted hover:text-chrome-ink'}"
        >${state.selectMode ? '☑ Selecting' : '☐ Select'}</button>
      ${hiddenCount ? `<button data-act="show-hidden" class="cursor-pointer bg-transparent ${
        state.showHidden ? 'text-accent-on-dark' : 'text-chrome-muted hover:text-chrome-ink'}"
        >Show hidden <span class="tnum">${hiddenCount}</span></button>` : ''}
      <span class="ml-auto"><span class="tnum">${visible.length}</span> shown</span>
    </div>

    ${state.selectMode ? selectActionsHtml() : ''}

    ${state.resourceType !== 'repo' ? `
      <div class="text-chip text-chrome-ink" style="border-bottom:1px dashed currentColor;padding-bottom:2px">
        Databases and filesystems · not built in /next
      </div>
      <div class="mt-s2 text-chip text-chrome-ink">
        This experiment covers one pane for one resource type.
        <a href="/" class="text-accent-on-dark underline">Open the current UI ↗</a>
      </div>`
    : visible.length === 0 ? `
      <div class="text-chip text-chrome-ink">Nothing matches these filters.</div>`
    : [...groups.entries()].sort((a, b) => groupName(a[0]).localeCompare(groupName(b[0]))).map(([g, rows]) => `
      <div class="mb-[7px] font-heading uppercase tracking-caps text-caps text-chrome-muted">
        ${esc(groupName(g))} · <span class="tnum">${rows.length}</span>
      </div>
      <div class="mb-s4 flex flex-col gap-[1px]">
        ${rows.map((p) => `<div class="flex items-baseline gap-[6px] px-2 py-[5px] ${
          p.slug === state.selectedSlug
            ? 'border-l-2 border-accent bg-chrome-surface'
            : 'border-l-2 border-transparent hover:bg-chrome-surface'}">
          ${state.selectMode ? `<input type="checkbox" data-sel="${esc(p.slug)}" ${
            state.selected.has(p.slug) ? 'checked' : ''} class="shrink-0">` : ''}
          ${lifecycleMark(p)}${dispositionMark(p)}
          <button data-slug="${esc(p.slug)}"
            class="min-w-0 flex-1 cursor-pointer truncate bg-transparent text-left text-chrome-ink"
            >${esc(p.display_name || p.slug)}</button>
          ${p.working_set_hidden ? '<span title="Hidden from your list" class="text-chrome-muted">⌀</span>' : ''}
        </div>`).join('')}
      </div>`).join('')}
  `;

  bindSidebar();
}

/** The Select-mode action bar. Every action here is a bulk write, so each
 *  says plainly what it touches — "remove from scope" and "delete" differ by
 *  everything, and the current UI's own tooltips are the wording. */
function selectActionsHtml() {
  const n = state.selected.size;
  return `<div class="mb-s3 flex flex-wrap items-baseline gap-s2 text-caps">
    <button data-act="sel-all" class="cursor-pointer bg-transparent text-chrome-ink underline">All shown</button>
    <button data-act="sel-none" class="cursor-pointer bg-transparent text-chrome-ink underline">None</button>
    <span class="text-chrome-muted"><span class="tnum">${n}</span> selected</span>
    <div class="flex w-full flex-wrap gap-s2 pt-s1">
      <button data-act="sel-scope-add" ${state.investigation ? '' : 'disabled'}
        title="${state.investigation ? 'Add to the current investigation’s scope' : 'Needs a current investigation'}"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-accent-on-dark ${
          state.investigation ? '' : 'border-dashed opacity-100'}">＋ scope</button>
      <button data-act="sel-scope-remove" ${state.investigation ? '' : 'disabled'}
        title="Remove from scope — the repo itself is untouched"
        class="cursor-pointer rounded-sm border border-chrome-line bg-transparent px-2 py-[2px] text-chrome-ink">− scope</button>
      <button data-act="sel-hide"
        title="Hide from your own list. A view preference, not a judgement"
        class="cursor-pointer rounded-sm border border-chrome-line bg-transparent px-2 py-[2px] text-chrome-ink">hide</button>
      <select data-act="sel-disposition"
        title="Set the disposition on every selected repo"
        class="rounded-sm border border-chrome-line bg-chrome px-2 py-[2px] text-chrome-ink">
        <option value="">mark as…</option>
        ${VALID_DISPOSITIONS.map((d) => `<option value="${esc(d)}">${esc(d)}</option>`).join('')}
      </select>
      <button data-act="sel-delete"
        title="Unregister entirely and delete all local survey data"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-accent-on-dark">delete…</button>
    </div>
    <div id="sidebar-action" class="w-full"></div>
  </div>`;
}

/** The current investigation — the frame every survey runs inside.
 *
 *  There is no server-side "current investigation": the current UI keeps it
 *  in localStorage under `re_current_investigation`, and /next reads and
 *  writes THE SAME KEY so switching between the two shells does not silently
 *  change what you are working on. */
const INVESTIGATION_KEY = 're_current_investigation';

function investigationBarHtml() {
  return `<div class="mb-s2 text-caps">
    <label for="investigation-select" class="mb-[3px] block uppercase tracking-caps text-chrome-muted">Investigation</label>
    <select id="investigation-select"
      class="w-full rounded-sm border border-chrome-line bg-chrome px-[6px] py-[3px] text-chip text-chrome-ink">
      <option value="">— none —</option>
      ${state.investigations.map((inv) => `<option value="${esc(inv.slug)}" ${
        inv.slug === state.investigation ? 'selected' : ''}>${esc(inv.display_name || inv.slug)}</option>`).join('')}
    </select>
  </div>`;
}

function bindSidebar() {
  const el = $('sidebar');
  const rerender = () => { renderSidebar(); writeUrl(); };

  el.querySelectorAll('button[data-type]').forEach((b) => b.addEventListener('click', () => {
    state.resourceType = b.dataset.type;
    rerender();
    loadPane();
  }));
  el.querySelectorAll('button[data-scope]').forEach((b) => b.addEventListener('click', () => {
    if (b.disabled) return;
    state.scope = b.dataset.scope;
    rerender();
  }));
  el.querySelectorAll('button[data-facet]').forEach((b) => b.addEventListener('click', () => {
    state.dispositionFacet = b.dataset.facet;
    rerender();
  }));
  el.querySelectorAll('input[data-sel]').forEach((cb) => cb.addEventListener('change', () => {
    if (cb.checked) state.selected.add(cb.dataset.sel);
    else state.selected.delete(cb.dataset.sel);
    renderSidebar();
  }));
  el.querySelectorAll('button[data-slug]').forEach((b) => b.addEventListener('click', () => {
    // Selecting a resource preserves stage and perspectives, deliberately.
    state.selectedSlug = b.dataset.slug;
    rerender();
    renderTopBar();
    loadPane();
  }));
  el.querySelector('#investigation-select')?.addEventListener('change', (e) => {
    setInvestigation(e.target.value);
  });
  el.querySelector('[data-act="sel-disposition"]')?.addEventListener('change', (e) => {
    const value = e.target.value;
    e.target.value = '';
    if (value) bulkDisposition(value);
  });

  const acts = {
    'show-empty-facets': () => { state.showEmptyFacets = true; renderSidebar(); },
    'show-hidden': () => { state.showHidden = !state.showHidden; rerender(); },
    'select-mode': () => {
      state.selectMode = !state.selectMode;
      if (!state.selectMode) state.selected.clear();
      renderSidebar();
    },
    'sel-all': () => { visibleProjects().forEach((p) => state.selected.add(p.slug)); renderSidebar(); },
    'sel-none': () => { state.selected.clear(); renderSidebar(); },
    'sel-scope-add': () => bulkScope(true),
    'sel-scope-remove': () => bulkScope(false),
    'sel-hide': () => bulkHide(),
    'sel-delete': () => confirmBulkDelete(),
  };
  for (const [name, fn] of Object.entries(acts)) {
    el.querySelector(`[data-act="${name}"]`)?.addEventListener('click', fn);
  }

  const filter = el.querySelector('#resource-filter');
  filter?.addEventListener('input', (e) => {
    state.filter = e.target.value;
    renderSidebar();
    const again = $('resource-filter');
    again.focus();
    again.setSelectionRange(again.value.length, again.value.length);
  });
}

/* ── Sidebar write paths ─────────────────────────────────────────────── */

function sidebarNote(html) {
  const el = $('sidebar-action');
  if (el) el.innerHTML = `<div class="mt-s2 text-chip text-chrome-ink">${html}</div>`;
}

async function bulkScope(add) {
  if (!state.investigation || !state.selected.size) return;
  const slugs = [...state.selected];
  const failed = [];
  for (const slug of slugs) {
    try {
      if (add) await addInvestigationMember(state.investigation, 'repo', slug);
      else await removeInvestigationMember(state.investigation, 'repo', slug);
    } catch (err) { failed.push(`${slug}: ${err.message}`); }
  }
  await loadWorkingSet();
  // Report per-resource, never "done": a bulk write where some calls failed
  // and the banner says success is how a partial write becomes invisible.
  sidebarNote(failed.length
    ? `<span class="text-accent-on-dark"><span class="tnum">${slugs.length - failed.length}</span>
       of <span class="tnum">${slugs.length}</span> ${add ? 'added' : 'removed'};
       ${esc(failed.join('; '))}</span>`
    : `<span class="tnum">${slugs.length}</span> ${add ? 'added to' : 'removed from'} scope.`);
  renderSidebar();
}

async function bulkHide() {
  const slugs = [...state.selected];
  if (!slugs.length) return;
  const failed = [];
  for (const slug of slugs) {
    try {
      await setWorkingSetHidden('repo', slug, true);
      const p = state.projects.find((x) => x.slug === slug);
      if (p) p.working_set_hidden = true;
    } catch (err) { failed.push(`${slug}: ${err.message}`); }
  }
  sidebarNote(failed.length
    ? `<span class="text-accent-on-dark">${esc(failed.join('; '))}</span>`
    : `<span class="tnum">${slugs.length}</span> hidden. They are still registered — "Show hidden" brings them back.`);
  renderSidebar();
}

async function bulkDisposition(disposition) {
  const slugs = [...state.selected];
  if (!slugs.length) return;
  const failed = [];
  const noUrl = [];
  for (const slug of slugs) {
    const p = state.projects.find((x) => x.slug === slug);
    // The endpoint is keyed on github_url. A repo without one cannot be
    // dispositioned, and saying so beats a silent no-op.
    if (!p?.github_url) { noUrl.push(slug); continue; }
    try {
      await setDisposition(p.github_url, disposition);
      p.disposition = disposition;
    } catch (err) { failed.push(`${slug}: ${err.message}`); }
  }
  const parts = [];
  const ok = slugs.length - failed.length - noUrl.length;
  if (ok) parts.push(`<span class="tnum">${ok}</span> marked ${esc(disposition)}`);
  if (noUrl.length) parts.push(`<span class="text-accent-on-dark"><span class="tnum">${noUrl.length}</span> have no GitHub URL and could not be marked</span>`);
  if (failed.length) parts.push(`<span class="text-accent-on-dark">${esc(failed.join('; '))}</span>`);
  sidebarNote(parts.join(' · '));
  renderSidebar();
}

/**
 * Delete is the one action with no undo anywhere in the stack: the endpoint
 * takes no confirmation flag, drops the repo's pgvector collections and
 * removes the registry row. So the confirmation has to be here, it has to
 * name what is going, and it must not be a one-click button.
 */
function confirmBulkDelete() {
  const slugs = [...state.selected];
  if (!slugs.length) return;
  sidebarNote(`
    <div class="text-accent-on-dark">Unregister <span class="tnum">${slugs.length}</span>
      ${slugs.length === 1 ? 'repo' : 'repos'} and delete all local survey data?
      This cannot be undone.</div>
    <div class="mt-s1 break-words text-chrome-muted">${esc(slugs.join(', '))}</div>
    <div class="mt-s2 flex gap-s2">
      <button data-act="sel-delete-confirm"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-accent-on-dark">Delete</button>
      <button data-act="sel-delete-cancel"
        class="cursor-pointer bg-transparent text-chrome-ink underline">Cancel</button>
    </div>`);
  $('sidebar-action').querySelector('[data-act="sel-delete-confirm"]')
    .addEventListener('click', () => bulkDelete(slugs));
  $('sidebar-action').querySelector('[data-act="sel-delete-cancel"]')
    .addEventListener('click', () => { $('sidebar-action').innerHTML = ''; });
}

async function bulkDelete(slugs) {
  const failed = [];
  for (const slug of slugs) {
    try {
      await removeProject(slug);
      state.projects = state.projects.filter((p) => p.slug !== slug);
      state.selected.delete(slug);
      if (state.selectedSlug === slug) state.selectedSlug = null;
    } catch (err) { failed.push(`${slug}: ${err.message}`); }
  }
  renderSidebar();
  renderTopBar();
  sidebarNote(failed.length
    ? `<span class="text-accent-on-dark">${esc(failed.join('; '))}</span>`
    : `<span class="tnum">${slugs.length - failed.length}</span> removed.`);
  if (!state.selectedSlug) loadPane();
}

/* ── Investigation ───────────────────────────────────────────────────── */

function currentInvestigation() {
  return LS.get(INVESTIGATION_KEY, '') || '';
}

async function setInvestigation(slug) {
  state.investigation = slug;
  LS.set(INVESTIGATION_KEY, slug);
  if (!slug) {
    try { localStorage.removeItem(INVESTIGATION_KEY); } catch { /* private mode */ }
    state.workingSet = new Set();
    if (state.scope === 'working-set') state.scope = '';
  } else {
    await loadWorkingSet();
  }
  renderTopBar();
  renderSidebar();
}

async function loadWorkingSet() {
  if (!state.investigation) { state.workingSet = new Set(); return; }
  try {
    const members = await listInvestigationMembers(state.investigation);
    state.workingSet = new Set(
      (members || []).filter((m) => (m.entity_type || 'repo') === 'repo')
                     .map((m) => m.entity_slug));
  } catch {
    // Unknown, and kept unknown: an empty working set and an unreadable one
    // are different, and "In scope" showing nothing because a call failed
    // would read as "this investigation has no members".
    state.workingSet = new Set();
    state.workingSetUnknown = true;
  }
}

/* ════════════════════════════════════════════════════════════════════════
 * The right rail — Ask, scoped here
 * ════════════════════════════════════════════════════════════════════════ */


/* A browser-generated id, so the agent can keep cross-turn memory.
 *
 * Computed on FIRST USE, not at module scope: `LS` is a `const` declared
 * further down this file, and a top-level IIFE up here runs inside its
 * temporal dead zone — which threw on load and rendered nothing at all. */
let _sessionId = null;
function sessionId() {
  if (_sessionId) return _sessionId;
  _sessionId = LS.get('re-next.sessionId', '');
  if (!_sessionId) {
    _sessionId = (crypto.randomUUID && crypto.randomUUID()) || `s-${Date.now()}-${Math.random()}`;
    LS.set('re-next.sessionId', _sessionId);
  }
  return _sessionId;
}

/**
 * The rail is a chat DRAWER with a transcript, not a single question box.
 *
 * A first pass showed one question and one answer, because that is what the
 * static mock showed. History is not a nicety: the whole argument for the
 * sidecar is that a session accumulates — you ask, you narrow, you ask again
 * — and each answer is evidence you may want to cite later.
 *
 * Turns are labelled with the resource they were asked about, because the
 * transcript outlives the selection and an answer about a different repo
 * that is not marked as such is worse than no answer.
 */
function renderRail() {
  $('rail').innerHTML = `
    <div class="mb-s3 flex items-baseline gap-s2">
      <span class="font-heading uppercase tracking-caps text-caps text-accent-on-dark">Ask</span>
      <span class="text-caps text-chrome-muted">${
        state.selectedSlug ? `scoped to ${esc(state.selectedSlug)}` : 'no resource selected'}</span>
      ${state.chat.length ? `<button data-act="clear-chat"
        class="ml-auto cursor-pointer bg-transparent text-caps text-chrome-muted underline hover:text-chrome-ink"
        >clear</button>` : ''}
    </div>

    <div id="rail-evidence" class="mb-s3"></div>
    <div id="chat-log" class="mb-s3 flex flex-col gap-s3"></div>

    <textarea id="ask-input" rows="3" placeholder="Ask about this resource…"
      class="mb-s2 w-full rounded-sm border border-chrome-line bg-transparent p-s2 text-subtab
             text-chrome-ink placeholder:text-chrome-muted"></textarea>
    <div class="flex items-baseline gap-s2">
      <button id="ask-submit"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-[10px] py-[4px]
               text-chip text-accent-on-dark">Ask</button>
      <span class="text-caps text-chrome-muted">⌘/Ctrl + Enter</span>
    </div>`;

  $('ask-submit').addEventListener('click', submitAsk);
  $('ask-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitAsk();
  });
  $('rail').querySelector('[data-act="clear-chat"]')?.addEventListener('click', () => {
    state.chat = [];
    renderRail();
  });
  renderChatLog();
}

/** One turn's source footer.
 *
 *  A REQUIREMENT, not decoration: an answer composed from survey metadata
 *  and an answer retrieved from embeddings must not look alike. When the
 *  response does not say which, this says THAT — it never guesses, and it
 *  never quietly implies retrieval. */
function sourceLine(body) {
  const manifest = body.compiled && body.compiled.manifest;
  if (manifest && typeof manifest === 'object') {
    const parts = Object.keys(manifest).filter((k) => {
      const v = manifest[k];
      return Array.isArray(v) ? v.length : v != null && v !== '';
    });
    return parts.length
      ? `From compiled evidence · ${parts.join(', ')}`
      : 'Compiled evidence was empty · answered from retrieval';
  }
  return 'No compiled evidence on this answer · source not reported';
}

/** Does this answer look like a list of resources worth acting on?
 *  Only then is "Open as candidates" offered — an action that appears on
 *  every answer teaches people to ignore it. */
function listCandidates(text) {
  const lines = String(text || '').split('\n')
    .map((l) => l.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, '').trim())
    .filter((l) => l && l.length < 80);
  return lines.length >= 3 ? lines.slice(0, 25) : [];
}

function renderChatLog() {
  const log = $('chat-log');
  if (!log) return;
  log.innerHTML = state.chat.map((t, i) => {
    const offScope = t.slug && t.slug !== state.selectedSlug;
    return `
    <div class="border-l-2 ${offScope ? 'border-chrome-line' : 'border-accent'} pl-s2">
      <div class="text-caps uppercase tracking-caps text-chrome-muted">
        You${t.slug ? ` · ${esc(t.slug)}` : ''}${offScope ? ' · not the current resource' : ''}
      </div>
      <div class="mb-s2 text-subtab text-chrome-ink">${esc(t.question)}</div>

      ${t.pending ? `<div class="text-chip text-chrome-muted">Asking…</div>` : ''}
      ${t.error ? `<div class="text-chip text-accent-on-dark">${esc(t.error)}</div>` : ''}
      ${t.answer ? `
        <div class="rounded-sm border border-chrome-line p-s3 text-subtab">
          <div class="whitespace-pre-wrap text-chrome-ink">${tnum(esc(t.answer))}</div>
          ${t.candidates && t.candidates.length ? `
            <button data-candidates="${i}"
              class="mt-s3 cursor-pointer rounded-sm border border-accent bg-transparent px-[10px] py-[4px]
                     text-chip text-accent-on-dark">Open as candidates
              (<span class="tnum">${t.candidates.length}</span>)</button>` : ''}
          <div class="mt-[10px] border-t border-chrome-line-soft pt-[9px] text-caps text-chrome-muted">
            ${esc(t.source)}${t.intent ? ` · intent ${esc(t.intent)}` : ''}${t.cached ? ' · cached' : ''}
          </div>
          ${t.queryHash ? feedbackHtml(t, i) : ''}
        </div>` : ''}
    </div>`;
  }).join('');

  log.querySelectorAll('[data-vote]').forEach((b) => b.addEventListener('click', () => {
    vote(Number(b.dataset.turn), Number(b.dataset.vote));
  }));
  log.querySelectorAll('[data-candidates]').forEach((b) => b.addEventListener('click', () => {
    showCandidates(Number(b.dataset.candidates));
  }));
  log.scrollTop = log.scrollHeight;
}

/** Three states, not a thumb pair.
 *
 *  The endpoint records +1 / 0 / -1 as three explicit outcomes, and "partly
 *  right" is the one that actually distinguishes a routing problem from a
 *  content problem. Folding it into either neighbour loses the signal the
 *  vote exists to collect. Words rather than emoji, since emoji is not this
 *  UI's icon system. */
function feedbackHtml(turn, i) {
  if (turn.voted !== undefined) {
    const said = { 1: 'Marked helpful.', 0: 'Marked partly right.', '-1': 'Marked not helpful.' };
    return `<div class="mt-s2 text-caps text-chrome-muted">${esc(said[String(turn.voted)])}</div>`;
  }
  if (turn.voteError) {
    return `<div class="mt-s2 text-caps text-accent-on-dark">Vote not recorded: ${esc(turn.voteError)}</div>`;
  }
  return `<div class="mt-s2 flex flex-wrap gap-s2 text-caps">
    <span class="text-chrome-muted">Was this right?</span>
    <button data-turn="${i}" data-vote="1" class="cursor-pointer bg-transparent text-chrome-ink underline">yes</button>
    <button data-turn="${i}" data-vote="0" class="cursor-pointer bg-transparent text-chrome-ink underline">partly</button>
    <button data-turn="${i}" data-vote="-1" class="cursor-pointer bg-transparent text-chrome-ink underline">no</button>
  </div>`;
}

async function vote(i, value) {
  const turn = state.chat[i];
  if (!turn || !turn.queryHash) return;
  try {
    await sendFeedback(turn.queryHash, value, turn.compileId || null);
    turn.voted = value;
  } catch (err) {
    // Say it failed. A vote that silently did not record is worse than no
    // vote control, because the person believes they have reported it.
    turn.voteError = err.message;
  }
  renderChatLog();
}

/** Narrow the sidebar to the resources an answer named. */
function showCandidates(i) {
  const turn = state.chat[i];
  if (!turn) return;
  const wanted = new Set();
  for (const line of turn.candidates) {
    for (const p of state.projects) {
      if (line.includes(p.slug) || line.includes(p.display_name)) wanted.add(p.slug);
    }
  }
  if (!wanted.size) {
    turn.candidateNote = 'None of those match a registered resource.';
    renderChatLog();
    return;
  }
  state.selectMode = true;
  state.selected = wanted;
  state.scope = '';
  state.dispositionFacet = 'all';
  state.filter = '';
  renderSidebar();
}

async function submitAsk() {
  const input = $('ask-input');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';

  const turn = { question: q, slug: state.selectedSlug, pending: true };
  state.chat.push(turn);
  renderChatLog();

  try {
    const body = await ask(q, {
      resourceSlug: state.selectedSlug,
      perspectives: state.activePerspectives,
      sessionId: sessionId(),
    });
    turn.pending = false;
    turn.answer = body.response || '';
    turn.intent = body.intent || '';
    turn.cached = Boolean(body.cached);
    turn.source = sourceLine(body);
    // Never computed here — the hash always comes off a server response, so
    // a vote lands under the same key however the answer was produced.
    turn.queryHash = body.query_hash || '';
    turn.compileId = body.compiled?.manifest?.compile_id || null;
    turn.candidates = listCandidates(turn.answer);
  } catch (err) {
    turn.pending = false;
    turn.error = `The question could not be asked: ${err.message}`;
  }
  renderChatLog();
}

/* ════════════════════════════════════════════════════════════════════════
 * The content pane
 * ════════════════════════════════════════════════════════════════════════ */

/* ────────────────────────────────────────────────────────────────────────
 * Pane widths and the chat drawer
 *
 * Both are per-viewer conveniences, so localStorage is the right home —
 * wrapped, because a private window or a browser set to block site data
 * makes the accessor itself throw, and a page that cannot remember a width
 * must still render.
 * ──────────────────────────────────────────────────────────────────────── */

const LS = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : v;
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, String(value)); } catch { /* not fatal */ }
  },
};

const SIDEBAR_BOUNDS = [150, 520];
const RAIL_BOUNDS = [220, 620];

function clamp(n, [lo, hi]) { return Math.min(hi, Math.max(lo, n)); }

function applyWidths() {
  const grid = $('app-grid');
  const sidebar = clamp(parseInt(LS.get('re-next.sidebarWidth', '240'), 10) || 240, SIDEBAR_BOUNDS);
  const rail = clamp(parseInt(LS.get('re-next.railWidth', '290'), 10) || 290, RAIL_BOUNDS);
  grid.style.setProperty('--sidebar-w', `${sidebar}px`);
  grid.style.setProperty('--rail-w', `${rail}px`);
}

function initSeams() {
  const grid = $('app-grid');

  const drag = (seamId, cssVar, storageKey, bounds, measure) => {
    const seam = $(seamId);
    let raf = null;
    const onMove = (e) => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = null;
        const px = clamp(Math.round(measure(e, grid.getBoundingClientRect())), bounds);
        grid.style.setProperty(cssVar, `${px}px`);
      });
    };
    const onUp = () => {
      seam.classList.remove('dragging');
      document.body.classList.remove('resizing');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      LS.set(storageKey, parseInt(grid.style.getPropertyValue(cssVar), 10));
    };
    seam.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      seam.classList.add('dragging');
      document.body.classList.add('resizing');
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    });
    // Keyboard, because a drag handle that only responds to a pointer is an
    // affordance some people simply do not have.
    seam.addEventListener('keydown', (e) => {
      const step = e.shiftKey ? 32 : 8;
      const cur = parseInt(getComputedStyle(grid).getPropertyValue(cssVar), 10) || bounds[0];
      const sign = seamId === 'seam-rail' ? -1 : 1;
      let next = null;
      if (e.key === 'ArrowLeft') next = cur - step * sign;
      if (e.key === 'ArrowRight') next = cur + step * sign;
      if (next === null) return;
      e.preventDefault();
      const px = clamp(next, bounds);
      grid.style.setProperty(cssVar, `${px}px`);
      LS.set(storageKey, px);
    });
  };

  drag('seam-sidebar', '--sidebar-w', 're-next.sidebarWidth', SIDEBAR_BOUNDS,
       (e, r) => e.clientX - r.left);
  drag('seam-rail', '--rail-w', 're-next.railWidth', RAIL_BOUNDS,
       (e, r) => r.right - e.clientX);
}

function railIsOpen() {
  return LS.get('re-next.railOpen', 'true') !== 'false';
}

function setRailOpen(open) {
  LS.set('re-next.railOpen', open ? 'true' : 'false');
  $('app-grid').classList.toggle('rail-closed', !open);
  const btn = $('chat-toggle');
  if (btn) {
    btn.textContent = open ? 'Chat ×' : 'Chat';
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.className = open
      ? 'cursor-pointer bg-transparent px-[10px] py-[9px] text-accent-on-dark'
      : 'cursor-pointer bg-transparent px-[10px] py-[9px] text-chrome-muted hover:text-chrome-ink';
  }
}

/* ────────────────────────────────────────────────────────────────────────
 * URL state
 *
 * Neither UI had this. It is the cheapest thing that makes a parallel UI
 * comparable at all: two testers cannot discuss the same screen without a
 * link to it, and "select amundsen, then Analysis, then hold Security" is
 * not a way to report a bug.
 * ──────────────────────────────────────────────────────────────────────── */

let _restoringUrl = false;

function writeUrl() {
  if (_restoringUrl) return;
  const p = new URLSearchParams();
  if (state.resourceType !== 'repo') p.set('type', state.resourceType);
  if (state.selectedSlug) p.set('resource', state.selectedSlug);
  if (state.stage !== 'scouting') p.set('stage', state.stage);
  if (state.subTab !== 'questions') p.set('tab', state.subTab);
  if (state.activePerspectives.size) p.set('perspectives', [...state.activePerspectives].join(','));
  const url = `${location.pathname}${p.toString() ? `?${p}` : ''}`;
  history.replaceState(null, '', url);
}

/** Read the URL into state. Returns true if it named a resource. */
function readUrl() {
  const p = new URLSearchParams(location.search);
  _restoringUrl = true;
  try {
    if (p.get('type')) state.resourceType = p.get('type');
    if (p.get('resource')) state.selectedSlug = p.get('resource');
    if (p.get('stage')) state.stage = p.get('stage');
    if (p.get('tab')) state.subTab = p.get('tab');
    const persp = p.get('perspectives');
    if (persp) state.activePerspectives = new Set(persp.split(',').filter(Boolean));
  } finally {
    _restoringUrl = false;
  }
  return Boolean(p.get('resource'));
}

/* ────────────────────────────────────────────────────────────────────────
 * The resource header
 * ──────────────────────────────────────────────────────────────────────── */

/** The selected resource's summary row from `GET /api/projects/`. */
function selectedProject() {
  return state.projects.find((p) => p.slug === state.selectedSlug) || null;
}

/**
 * Name, external links, provenance, and the write paths.
 *
 * The external links are here because they were missing, and they are marked
 * as external (`↗`, `rel="noopener"`, a new tab) so they read differently
 * from internal navigation — a link that leaves the app and a link that
 * changes a pane should not look alike.
 *
 * The provenance line is the page's own: when this resource was last
 * surveyed, and whether it has been published to Egeria. "Never surveyed" is
 * a distinct statement from "surveyed and nothing changed", the same
 * distinction the rows below make.
 */
function resourceHeaderHtml(slug) {
  const p = selectedProject();
  const name = p?.display_name || slug;

  const links = [];
  if (p?.github_url) {
    links.push(`<a href="${esc(p.github_url)}" target="_blank" rel="noopener noreferrer"
      class="text-accent-ink underline">GitHub ↗</a>`);
  }
  // `homepage` is NOT on the summary row — it comes from the scouting
  // overview, and it is already the derived best link (GitHub's declared
  // homepage, then the packaging manifest, then the README), doing duty as
  // both project site and docs. There is no separate docs field to show.
  const homepage = state.overview?.slug === slug ? state.overview.homepage : '';
  if (homepage) {
    links.push(`<a href="${esc(homepage)}" target="_blank" rel="noopener noreferrer"
      class="text-accent-ink underline">Project site ↗</a>`);
  }

  const surveyed = p?.last_surveyed_at
    ? `surveyed <span class="tnum">${esc(ago(p.last_surveyed_at))}</span>`
    : 'never surveyed';
  const ov = state.overview?.slug === slug ? state.overview : null;
  let published = p?.is_published ? 'published to Egeria' : 'not published to Egeria';
  if (ov?.last_published_at && p?.is_published) {
    published += ` <span class="tnum">${esc(ago(ov.last_published_at))}</span>`;
  }
  // A "published" badge is actively misleading while the link is broken: it
  // reports a catalog entry RE can no longer reach.
  if (ov?.egeria_link_stale) {
    published = `<span class="text-accent-ink">published, but the Egeria link is stale —`
      + ` the catalog entry cannot be reached</span>`;
  }

  return `
    <div class="flex flex-wrap items-baseline gap-s3">
      <h3 class="m-0 font-heading text-name font-normal">${esc(name)}</h3>
      <span class="font-mono text-[11px] text-ink-muted">${esc(slug)}</span>
      ${links.length
        ? `<span class="flex flex-wrap gap-s3 text-caveat">${links.join('')}</span>`
        : `<span class="text-caveat text-ink-muted">no external links recorded</span>`}
      <span class="ml-auto flex flex-wrap items-baseline gap-s2 text-caveat">
        <button data-act="disposition" class="cursor-pointer rounded-pill border border-rule-strong bg-transparent px-2 py-[1px] text-ink hover:border-accent">
          ${esc(p?.disposition || 'undecided')} ▾
        </button>
        <button data-act="hide" class="cursor-pointer bg-transparent text-accent-ink underline">
          ${p?.working_set_hidden ? 'unhide' : 'hide'}
        </button>
        <button data-act="remove" class="cursor-pointer bg-transparent text-accent-ink underline">remove</button>
      </span>
    </div>
    <div class="mt-s1 text-provenance text-ink-muted">${surveyed} · ${published}</div>
    <div id="resource-action" class="mt-s2"></div>`;
}

/** The header's three write paths. `hide` is reversible, `disposition` is a
 *  judgement, `remove` is neither — so only one of them asks. */
function bindResourceHeader() {
  const el = $('resource-header') || $('content');
  const slot = $('resource-action');
  const p = selectedProject();
  if (!el || !slot) return;

  const note = (html) => { slot.innerHTML = `<div class="text-caveat text-ink">${html}</div>`; };

  el.querySelector('[data-act="disposition"]')?.addEventListener('click', () => {
    if (!p?.github_url) {
      note(`<span class="text-accent-ink">This repo has no GitHub URL recorded, and the
        disposition endpoint is keyed on that URL — so its disposition cannot be
        set from here.</span>`);
      return;
    }
    slot.innerHTML = `
      <div class="flex flex-wrap items-baseline gap-s2 text-caveat">
        <span class="text-ink-muted">Set disposition</span>
        ${VALID_DISPOSITIONS.map((d) => `<button data-disp="${esc(d)}"
          class="cursor-pointer rounded-pill bg-transparent px-2 py-[1px] ${
            d === (p.disposition || 'undecided')
              ? 'border border-accent text-accent-ink'
              : 'border border-rule-strong text-ink hover:border-accent'}"
          >${esc(d)}</button>`).join('')}
      </div>`;
    slot.querySelectorAll('[data-disp]').forEach((b) => b.addEventListener('click', async () => {
      const value = b.dataset.disp;
      note('Saving…');
      try {
        await setDisposition(p.github_url, value);
        p.disposition = value;
        renderSidebar();
        el.innerHTML = '';        // rebuilt below by loadPane
        await loadPane();
        $('resource-action').innerHTML =
          `<div class="text-caveat text-ink">Disposition is now <strong>${esc(value)}</strong>.</div>`;
      } catch (err) {
        note(`<span class="text-accent-ink">Not saved: ${esc(err.message)}</span>`);
      }
    }));
  });

  el.querySelector('[data-act="hide"]')?.addEventListener('click', async () => {
    const hiding = !p?.working_set_hidden;
    note(hiding ? 'Hiding…' : 'Unhiding…');
    try {
      await setWorkingSetHidden('repo', state.selectedSlug, hiding);
      if (p) p.working_set_hidden = hiding;
      renderSidebar();
      await loadPane();
      $('resource-action').innerHTML = `<div class="text-caveat text-ink">${
        hiding
          ? 'Hidden from your list. Still registered, and nothing was deleted — “Show hidden” in the sidebar brings it back.'
          : 'Back in your list.'}</div>`;
    } catch (err) {
      note(`<span class="text-accent-ink">Not saved: ${esc(err.message)}</span>`);
    }
  });

  el.querySelector('[data-act="remove"]')?.addEventListener('click', () => {
    slot.innerHTML = `
      <div class="text-caveat text-accent-ink">
        Unregister <span class="font-mono">${esc(state.selectedSlug)}</span> and delete all its
        local survey data? This cannot be undone, and it is not the same as marking it
        <em>ignored</em> — an ignored repo stays registered and can come back.
      </div>
      <div class="mt-s2 flex gap-s3 text-caveat">
        <button data-act="remove-confirm"
          class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-accent-ink">Remove</button>
        <button data-act="remove-cancel" class="cursor-pointer bg-transparent text-ink underline">Cancel</button>
      </div>`;
    slot.querySelector('[data-act="remove-cancel"]')
      .addEventListener('click', () => { slot.innerHTML = ''; });
    slot.querySelector('[data-act="remove-confirm"]').addEventListener('click', async () => {
      const slug = state.selectedSlug;
      note('Removing…');
      try {
        await removeProject(slug);
        state.projects = state.projects.filter((x) => x.slug !== slug);
        state.selectedSlug = state.projects[0]?.slug || null;
        renderSidebar();
        renderTopBar();
        await loadPane();
      } catch (err) {
        note(`<span class="text-accent-ink">Not removed: ${esc(err.message)}</span>`);
      }
    });
  });
}

/**
 * The sub-tab rail.
 *
 * A parallel UI may DEFER an affordance; it may not silently omit one. The
 * four unbuilt sub-tabs looked identical to the one that works, so the pane
 * was claiming a capability it does not have. They are marked with the same
 * dashed rule the unbuilt intent uses, and clicking one says so and links
 * out rather than doing nothing.
 */
function subTabsHtml() {
  return `<div class="mb-s4 flex flex-wrap items-baseline gap-s3 font-heading text-subtab">
    ${SUB_TABS.map((t) => {
      const id = t.toLowerCase();
      if (id === state.subTab) {
        return `<span class="border-b border-accent pb-[2px] text-ink">${t}</span>`;
      }
      if (t === 'Questions') {
        return `<button data-subtab="${id}" class="cursor-pointer bg-transparent text-ink hover:text-accent-ink">${t}</button>`;
      }
      return `<button data-deferred="${id}" title="Not built in /next — opens the current UI"
        class="cursor-pointer bg-transparent text-ink-muted"
        style="border-bottom:1px dashed currentColor;padding-bottom:1px">${t}</button>`;
    }).join('')}
    <span class="ml-auto text-caps uppercase tracking-caps text-ink-muted">Questions only, in /next</span>
  </div>`;
}

/** Sub-tab clicks: the real one switches, a deferred one says it is deferred. */
function bindSubTabs() {
  const el = $('content');
  el.querySelectorAll('[data-subtab]').forEach((b) => b.addEventListener('click', () => {
    state.subTab = b.dataset.subtab;
    writeUrl();
    loadPane();
  }));
  el.querySelectorAll('[data-deferred]').forEach((b) => b.addEventListener('click', () => {
    state.subTab = b.dataset.deferred;
    writeUrl();
    loadPane();
  }));
}

/** What a deferred sub-tab shows when you click it. */
function deferredPaneHtml(name) {
  return `${subTabsHtml()}
    <h3 class="m-0 font-heading text-name font-normal">${esc(name)} · not built in /next</h3>
    <div class="my-s3 h-px bg-rule"></div>
    <p class="max-w-[70ch] text-answer text-ink">
      This experiment builds one pane. ${esc(name)} is live in the current UI.
    </p>
    <p class="max-w-[70ch] text-answer text-ink">
      <a href="/" class="text-accent-ink underline">Open the current UI ↗</a>
    </p>
    <p class="max-w-[70ch] text-caveat text-accent-ink">
      The current UI has no deep link — navigation state lives in JavaScript
      variables, not in the URL — so it cannot be opened on
      ${state.selectedSlug ? `<span class="font-mono">${esc(state.selectedSlug)}</span>` : 'this resource'}
      directly. You will have to select it again there.
    </p>`;
}

/**
 * The state legend, with counts.
 *
 * The current UI has one across the top of its Questions tab, and dropping it
 * hurt more here than it would have there: this palette moved state from hue
 * to glyph, and a glyph vocabulary without a key is strictly less legible
 * than colour without one.
 *
 * Counted rather than static — `3 answered · 1 not run` earns the space a
 * fixed key does not — and only states actually present are listed, since a
 * key to a glyph that is not on screen is noise. Rows arriving is what moves
 * these numbers, so it re-renders with them.
 */
const LEGEND = [
  ['answered',     'answered'],
  ['automatic',    'automatic'],
  ['unrun',        'not run'],
  ['human',        'needs you'],
  ['no-surveyor',  'no surveyor'],
  ['unclassified', 'unclassified'],
  ['running',      'running'],
  ['error',        'could not load'],
];

function renderLegend() {
  const el = $('state-legend');
  if (!el) return;

  const counts = {};
  let pending = 0;
  for (const q of state.questions) {
    const env = state.answers.get(q.question);
    if (env === undefined || env === 'loading') { pending += 1; continue; }
    const st = state.runsInFlight.has(q.question) ? 'running'
      : env.__error ? 'error'
      : rowState(q, env);
    counts[st] = (counts[st] || 0) + 1;
  }

  const items = LEGEND.filter(([k]) => counts[k]).map(([k, label]) => {
    const accented = ['answered', 'automatic', 'human', 'running'].includes(k);
    return `<span class="inline-flex items-baseline gap-[5px]">
      <span class="${accented ? 'text-accent-ink' : 'text-ink-muted'}">${GLYPH[k]}</span>
      <span class="text-ink">${esc(label)}</span>
      <span class="tnum text-ink">${counts[k]}</span>
    </span>`;
  });

  if (pending) {
    items.push(`<span class="text-ink-muted">
      <span class="tnum">${pending}</span> still loading</span>`);
  }

  el.innerHTML = items.length
    ? `<span class="text-caps uppercase tracking-caps text-ink-muted">Key</span>${items.join('')}`
    : '';
}

function paneMessage(title, body) {
  return `${subTabsHtml()}
    <h3 class="m-0 font-heading text-name font-normal">${esc(title)}</h3>
    <div class="my-s3 h-px bg-rule"></div>
    <p class="max-w-[70ch] text-answer text-ink">${esc(body)}</p>`;
}

async function loadPane() {
  const el = $('content');

  if (state.subTab !== 'questions') {
    const name = SUB_TABS.find((t) => t.toLowerCase() === state.subTab) || state.subTab;
    el.innerHTML = deferredPaneHtml(name);
    bindSubTabs();
    return;
  }

  // ONE pane, parameterised by stage — not eight panes.
  //
  // The questions endpoint already takes `phase`, so serving every stage from
  // this one pane costs a query parameter. It is also the only way the state
  // vocabulary gets exercised at all: Scouting's five questions are `analysis`
  // and `direct` only, while `gap`, `human`, `mixed`, `partial` and `chart`
  // all live in the Analysis and Enrichment stages. Building Scouting alone
  // would have shipped a screen whose whole argument — that six states are
  // scannable as glyph plus sentence — could not be looked at.
  const stageDef = STAGES.find((s) => s.id === state.stage);
  if (stageDef?.frame || stageDef?.unbuilt) {
    el.innerHTML = paneMessage(
      `${stageDef.label} · not in /next`,
      stageDef.frame
        ? 'Investigations are the frame around a body of work, and /next does not '
          + 'implement them. They are live in the current UI.'
        : 'This stage has no rows in the analysis catalog or the activity log, so '
          + 'there is nothing for a questions pane to show. It is marked here '
          + 'rather than hidden, which is the point.');
    bindSubTabs();
    renderPerspectiveRow();
    return;
  }

  if (state.resourceType !== 'repo') {
    el.innerHTML = paneMessage('Repos only, in /next',
      'The Questions pane is built for repositories. Databases and filesystems '
      + 'are live in the current UI.');
    bindSubTabs();
    return;
  }

  if (!state.selectedSlug) {
    el.innerHTML = paneMessage('Select a resource',
      'Pick a repository from the sidebar to see its question checklist.');
    bindSubTabs();
    return;
  }

  const slug = state.selectedSlug;

  // The overview carries `homepage`, `last_published_at` and the stale-link
  // flag, none of which are on the summary row. Fetched per selection, and
  // its absence is survivable — the header renders without it.
  if (state.overview?.slug !== slug) {
    state.overview = null;
    getScoutingOverview(slug)
      .then((ov) => {
        if (state.selectedSlug !== ov.slug) return;
        state.overview = ov;
        // Replace the header IN PLACE, by its own id, so the rows already on
        // screen stay put. An earlier version matched the header by its class
        // list and inserted a second copy — the resource name rendered twice.
        const host = $('resource-header');
        if (host) {
          host.innerHTML = resourceHeaderHtml(slug);
          bindResourceHeader();
        }
      })
      .catch(() => { /* the header is fine without it */ });
  }

  // The frame first, then per-row skeletons — rows arrive independently, and
  // a centred spinner would hide the ones that are already here.
  el.innerHTML = `${subTabsHtml()}
    <div id="resource-header">${resourceHeaderHtml(slug)}</div>
    <div class="mt-s3 flex flex-wrap items-baseline gap-s3 text-provenance">
      <span id="answered-count" class="tnum text-[12px] text-ink-muted">loading…</span>
    </div>
    <div id="state-legend" class="mt-s2 flex flex-wrap items-baseline gap-s3 text-caveat"></div>
    <div class="my-s3 h-px bg-rule"></div>
    <div id="question-rows"></div>`;
  bindSubTabs();
  bindResourceHeader();

  let checklist;
  try {
    checklist = await getQuestions(slug, {
      phase: state.stage,
      perspectives: [...state.activePerspectives],
    });
  } catch (err) {
    $('question-rows').innerHTML = `<div class="py-s3 text-answer text-accent-ink">
      The checklist could not be loaded: ${esc(err.message)}</div>`;
    return;
  }
  if (slug !== state.selectedSlug) return;   // a faster click won

  state.questions = checklist.questions || [];

  // The residue count needs the unfiltered total. One extra call, only when
  // a perspective is held — the number is the whole point of the chip row.
  if (state.activePerspectives.size) {
    try {
      const all = await getQuestions(slug, { phase: state.stage });
      state.allQuestions = all.questions || [];
    } catch {
      // Unknown, and it must stay unknown: with no unfiltered set there is
      // no basis for either the residue count or the matches-nothing chip,
      // and guessing one from the filtered set is the bug above.
      state.allQuestions = null;
    }
  } else {
    // Nothing held means nothing filtered — the two sets are the same list.
    state.allQuestions = state.questions;
  }
  renderPerspectiveRow();

  const rows = $('question-rows');
  if (!state.questions.length) {
    rows.innerHTML = `<div class="py-s3 text-answer text-ink">
      No catalogued questions match this stage and this perspective set.
      That is a fact about the filter, not about the repository.</div>`;
    $('answered-count').textContent = `0 questions · ${stageLabel()}`;
    return;
  }

  rows.innerHTML = state.questions.map((q, i) => rowShell(q, i)).join('');
  updateAnsweredCount();
  renderLegend();

  // Fetch each answer independently and replace its row as it lands.
  state.answers.clear();
  state.questions.forEach((q, i) => loadAnswer(q, i, slug));
}

function rowKey(i) { return `qrow-${i}`; }

function rowShell(entry, i) {
  const last = i === state.questions.length - 1;
  return `<div id="${rowKey(i)}" class="py-s3 ${last ? '' : 'border-b border-rule'}">
    ${rowInner(entry, i, 'loading')}
  </div>`;
}

/** One question row. The layout is fixed across states so a column of rows
 *  scans: glyph at 22px, everything below indented to match. */
function rowInner(entry, i, env) {
  const perspective = (entry.perspectives || [])[0] || '';
  const running = state.runsInFlight.get(entry.question);
  const st = running ? 'running'
    : env === 'loading' ? 'loading'
    : env && env.__error ? 'error'
    : rowState(entry, env);

  const glyph = GLYPH[st] || '·';
  // The GLYPH carries the state, not a shade of grey. An earlier version put
  // the question title in `ink-muted` for the unrun/gap/unclassified states —
  // which is de-emphasis by fading text toward the ground, the one thing this
  // palette forbids, and on the Analysis stage it was most of the page.
  // Titles are `ink` in every state now.
  const glyphColor = ['answered', 'automatic', 'human', 'running'].includes(st)
    ? 'text-accent-ink' : 'text-ink-muted';

  const tag = st === 'no-surveyor'
    ? `<span class="ml-auto rounded-pill border border-dashed border-accent px-2 py-[1px] text-caps text-accent-ink">no surveyor yet</span>`
    : perspective
      ? `<span class="ml-auto rounded-pill border border-rule-strong px-2 py-[1px] text-caps text-ink-muted">${esc(perspective)}</span>`
      : '';

  const head = `<div class="flex flex-wrap items-baseline gap-[9px]">
      <span class="w-[13px] ${glyphColor} text-question">${st === 'loading' ? '' : glyph}</span>
      <span class="font-heading text-question font-semibold text-ink">${esc(entry.question)}</span>
      ${tag}
    </div>`;

  return head + bodyLines(entry, i, st, env);
}

function bodyLines(entry, i, st, env) {
  const indent = 'ml-[22px] mt-[6px]';

  if (st === 'loading') {
    // A skeleton, not a spinner, and not a claim.
    return `<div class="${indent} h-[14px] w-[42%] rounded-sm bg-paper-surface"></div>`;
  }

  if (st === 'running') {
    const r = state.runsInFlight.get(entry.question);
    return `<div class="${indent} text-answer text-accent-ink">${esc(r.label)}</div>`
      + provenanceLine(entry, i, { canRun: [], sources: r.analysisId ? [r.analysisId] : [] }, st);
  }

  if (st === 'error') {
    // Per-row failure, per-row retry. Never a page-level error.
    return `<div class="${indent} text-answer text-accent-ink">${esc(env.__error)}</div>
      <div class="${indent} text-provenance text-ink-muted">
        <button data-retry="${i}" class="cursor-pointer bg-transparent text-accent-ink underline">retry</button>
      </div>`;
  }

  if (st === 'no-surveyor') {
    const why = (env && env.blocked_reason)
      || entry.note
      || 'No surveyor exists for this question. Nothing has run and nothing can.';
    return `<div class="${indent} text-answer text-ink">${tnum(esc(why))}</div>`;
  }

  if (st === 'human') {
    const why = entry.note || 'This is answered by someone stating it, not by a survey.';
    return `<div class="${indent} text-answer text-ink">${tnum(esc(why))}</div>
      <div class="${indent} text-provenance text-ink-muted">
        Enrichment · answer inline · not built in /next
      </div>`;
  }

  if (st === 'unclassified') {
    return `<div class="${indent} text-answer text-ink">The catalog does not state how this
      question would be answered.</div>`;
  }

  if (st === 'unrun') {
    // NO answer line. Not a zero, not an empty string — the absence of the
    // line is the statement.
    const why = (env && env.blocked_reason) || 'Not run yet.';
    const lines = readEnvelope(entry, env);
    return `<div class="${indent} text-answer text-ink">${tnum(esc(why))}</div>`
      + provenanceLine(entry, i, lines, st);
  }

  // answered | automatic
  const lines = readEnvelope(entry, env);
  let html = '';
  if (lines.answer) {
    html += `<div class="${indent} text-answer text-ink">${lines.answer}</div>`;
  }
  if (lines.caveat) {
    html += `<div class="ml-[22px] mt-[5px] text-caveat text-accent-ink">${tnum(esc(lines.caveat))}</div>`;
  }
  return html + provenanceLine(entry, i, lines, st);
}

function provenanceLine(entry, i, lines, st) {
  const bits = [];
  const sources = lines.sources && lines.sources.length
    ? lines.sources.join(', ')
    : (entry.analysis_ids || []).join(', ');
  if (sources) bits.push(esc(sources));
  else if (entry.answering_mechanism) bits.push(esc(entry.answering_mechanism));

  // WHEN, said exactly as precisely as the record allows. Three different
  // statements, never folded together:
  //   a recorded timestamp        -> "run 19d ago"
  //   measured, but no timestamp  -> "run time not recorded"
  //   nothing measured            -> "never run"
  // The middle one is a gap in the record. Rendering it as "never run" —
  // which this row did until it was checked against the API — puts a tick
  // beside a claim that nothing ever ran, and both halves cannot be true.
  if (lines.lastRun) {
    const rel = ago(lines.lastRun);
    bits.push(`run ${rel ? `<span class="tnum">${esc(rel)}</span>` : esc(lines.lastRun)}`);
  } else if (lines.runTimeUnrecorded) {
    bits.push('run time not recorded');
  } else if (st !== 'running') {
    bits.push('never run');
  }

  // How it was known, when it was not a survey. A direct field and a survey
  // result are different kinds of claim and must not read alike.
  if (st === 'automatic') {
    const how = { direct: 'direct field', registry: 'from the registry', chart: 'chart' }[entry.kind];
    if (how) bits.push(how);
  }

  const actions = [];
  if (st === 'answered' || st === 'automatic') {
    actions.push(`<button data-evidence="${i}" class="cursor-pointer bg-transparent text-accent-ink underline">evidence</button>`);
  }
  const canRun = (lines.canRun && lines.canRun.length) || (entry.analysis_ids || []).length;
  if (canRun && st !== 'running') {
    actions.push(`<button data-rerun="${i}" class="cursor-pointer bg-transparent text-accent-ink underline">${
      st === 'unrun' ? 'run' : 're-run'}</button>`);
  }

  if (!bits.length && !actions.length) return '';
  return `<div class="ml-[22px] mt-[7px] text-provenance text-ink-muted">${
    [bits.join(' · '), actions.join(' · ')].filter(Boolean).join(' · ')}</div>`;
}

function updateAnsweredCount() {
  const el = $('answered-count');
  if (!el) return;
  const total = state.questions.length;
  const settled = state.questions.filter((q) => {
    const env = state.answers.get(q.question);
    return env && env !== 'loading' && !env.__error;
  });
  const answered = settled.filter((q) => {
    const env = state.answers.get(q.question);
    return env.answerable;
  }).length;
  const pending = total - settled.length;
  el.innerHTML = `<span class="tnum">${answered}</span> of <span class="tnum">${total}</span> answered`
    + (pending ? ` · <span class="tnum">${pending}</span> still loading` : '')
    + ` · ${stageLabel()}`;
}

async function loadAnswer(entry, i, slug) {
  state.answers.set(entry.question, 'loading');
  let env;
  try {
    env = await getAnswer(slug, entry.question);
  } catch (err) {
    // 404 means the question text is not in the catalog the FactLayer reads —
    // a real mismatch between two catalogs, said plainly rather than shown
    // as an unanswered question, which would blame the repository for a
    // catalog problem.
    env = {
      __error: err instanceof ApiError && err.status === 404
        ? 'This question is not in the catalog the answer layer reads — the two catalogs disagree.'
        : `The answer could not be loaded: ${err.message}`,
    };
  }
  if (slug !== state.selectedSlug) return;
  state.answers.set(entry.question, env);
  replaceRow(entry, i, env);
  updateAnsweredCount();
  renderLegend();
}

function replaceRow(entry, i, env) {
  const el = document.getElementById(rowKey(i));
  if (!el) return;
  el.innerHTML = rowInner(entry, i, env);
  bindRowActions(el, entry, i);
}

function bindRowActions(el, entry, i) {
  el.querySelector(`[data-retry="${i}"]`)?.addEventListener('click', () => {
    replaceRow(entry, i, 'loading');
    loadAnswer(entry, i, state.selectedSlug);
  });
  el.querySelector(`[data-rerun="${i}"]`)?.addEventListener('click', () => rerun(entry, i));
  el.querySelector(`[data-evidence="${i}"]`)?.addEventListener('click', () => showEvidence(entry));
}

/**
 * Re-run the analyses behind one row.
 *
 * The running state distinguishes QUEUED from RUNNING from STALLED. A pending
 * marker that cannot tell a stalled run from a slow one is worse than none:
 * it converts "we don't know" into "wait a bit longer" forever.
 */
async function rerun(entry, i) {
  const analysisId = (entry.analysis_ids || [])[0];
  if (!analysisId) return;
  const slug = state.selectedSlug;

  state.runsInFlight.set(entry.question, { analysisId, label: `Queued · ${analysisId}` });
  replaceRow(entry, i, state.answers.get(entry.question));

  try {
    const started = await runAnalysis(slug, analysisId);
    const activityId = started.activity_id;
    state.runsInFlight.set(entry.question, { analysisId, activityId, label: `Running · ${analysisId}` });
    replaceRow(entry, i, state.answers.get(entry.question));

    await pollActivity(activityId, {
      onTick: (e) => {
        const s = (e?.status || '').toLowerCase();
        const label = s === 'running' ? `Running · ${analysisId}`
          : s === 'queued' || s === 'pending' ? `Queued · ${analysisId}`
          : `Running · ${analysisId}`;
        const cur = state.runsInFlight.get(entry.question);
        if (cur && cur.label !== label) {
          state.runsInFlight.set(entry.question, { ...cur, label });
          replaceRow(entry, i, state.answers.get(entry.question));
        }
      },
    });
  } catch (err) {
    state.runsInFlight.delete(entry.question);
    const msg = err.name === 'PollTimeout'
      // Stopped watching is NOT failed. Saying "failed" here would report a
      // fact about this browser as a fact about the run.
      ? `Still running after five minutes — /next stopped watching. The run itself has not failed; check Activity in the current UI.`
      : `The run could not be started: ${err.message}`;
    state.answers.set(entry.question, { __error: msg });
    replaceRow(entry, i, state.answers.get(entry.question));
    updateAnsweredCount();
    renderLegend();
    return;
  }

  state.runsInFlight.delete(entry.question);
  await loadAnswer(entry, i, state.selectedSlug);
}

/** One measure, rendered for reading rather than for parsing.
 *
 *  A structured value is SUMMARISED, never JSON.stringify'd into the rail —
 *  a dumped array is not evidence, it is a reason to stop reading. Lists of
 *  findings show their own summaries; anything else shows its shape and its
 *  size, which is enough to know whether to go and look at it properly. */
function measureHtml(key, v) {
  const label = `<span class="text-chrome-muted">${esc(key.replace(/_/g, ' '))}</span>`;
  if (v === null || v === undefined || v === '') {
    return `<div>${label} <span class="text-chrome-muted">not set</span></div>`;
  }
  if (Array.isArray(v)) {
    const items = v.slice(0, 6).map((it) => {
      if (it && typeof it === 'object') {
        const name = it.check_name || it.name || it.id || '';
        const text = it.summary || it.detail || it.label || '';
        return `<div class="ml-s2">${name ? `<span class="text-accent-on-dark">${esc(name)}</span> ` : ''}${tnum(esc(text))}</div>`;
      }
      return `<div class="ml-s2">${tnum(esc(it))}</div>`;
    }).join('');
    const more = v.length > 6
      ? `<div class="ml-s2 text-chrome-muted">and <span class="tnum">${v.length - 6}</span> more</div>`
      : '';
    return `<div>${label} <span class="tnum">${v.length}</span></div>${items}${more}`;
  }
  if (typeof v === 'object') {
    const n = Object.keys(v).length;
    return `<div>${label} <span class="text-chrome-muted"><span class="tnum">${n}</span> fields</span></div>`;
  }
  const shown = typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v);
  return `<div>${label} <span class="tnum">${tnum(esc(shown))}</span></div>`;
}

/** The full measurement behind a claim, in the rail. The row states the
 *  answer; this is where the numbers it came from live. */
function showEvidence(entry) {
  const env = state.answers.get(entry.question);
  // Evidence lands in the rail, so open the drawer if it is closed —
  // otherwise the link appears to do nothing.
  if (!railIsOpen()) setRailOpen(true);
  const out = $('rail-evidence');
  if (!out || !env || env === 'loading' || env.__error) return;

  const facts = (env.facts || []).map((f) => {
    const value = f.value && Object.keys(f.value).length
      ? `<div class="mt-[4px] leading-[1.95]">${Object.entries(f.value)
          .map(([k, v]) => measureHtml(k, v)).join('')}</div>`
      : '';
    return `<div class="mb-s2 border-b border-chrome-line-soft pb-s2 last:border-0">
      <div class="text-chip text-accent-on-dark">${esc(f.analysis_id)}</div>
      <div class="text-caps text-chrome-muted">${esc(f.state)} · ${esc(f.provenance)} · ${
        f.last_run_at ? `run ${esc(ago(f.last_run_at))}`
          : f.is_known ? 'run time not recorded' : 'never run'}</div>
      ${f.headline ? `<div class="mt-[4px] text-subtab">${tnum(esc(f.headline))}</div>` : ''}
      ${f.note ? `<div class="mt-[4px] text-chip text-accent-on-dark">${tnum(esc(f.note))}</div>` : ''}
      ${value}
    </div>`;
  }).join('');

  out.innerHTML = `
    <div class="rounded-sm border border-chrome-line p-s3">
      <div class="mb-s2 font-heading uppercase tracking-caps text-caps text-accent-on-dark">Evidence</div>
      <div class="mb-s3 text-subtab">${esc(entry.question)}</div>
      ${facts || '<div class="text-chip text-chrome-muted">No facts on this envelope.</div>'}
      <div class="mt-[10px] border-t border-chrome-line-soft pt-[9px] text-caps text-chrome-muted">
        Answered from <span class="tnum">${env.known_count ?? 0}</span> of
        <span class="tnum">${(env.known_count ?? 0) + (env.unknown_count ?? 0)}</span> measurements ·
        no retrieval
      </div>
    </div>`;
}

/* ════════════════════════════════════════════════════════════════════════
 * Boot
 * ════════════════════════════════════════════════════════════════════════ */

const ACTIVITY_LIMIT = 200;   // the endpoint's own default; le=1000
const RFA_LIMIT = 500;        // the endpoint's own default; le=2000

/** A page length turned into a count, or `"N+"` when the page filled. */
function countOf(settled, limit, key) {
  if (settled.status !== 'fulfilled') return null;
  const v = settled.value;
  const rows = Array.isArray(v) ? v : (v?.[key] ?? null);
  if (!Array.isArray(rows)) return null;
  return rows.length >= limit ? `${limit}+` : rows.length;
}

async function start() {
  applyWidths();
  initSeams();
  readUrl();
  renderIntentNav();
  renderRail();
  renderTopBar();

  // Everything below is independent; one failing must not take the frame
  // down with it. `allSettled`, and each consumer handles its own absence.
  state.investigation = currentInvestigation();

  const [me, projects, perspectives, activity, rfas, groups, investigations] =
    await Promise.allSettled([
      getMe(),
      // The FULL list — every disposition, hidden included — because the
      // sidebar filters client-side and the default server filters would
      // make the `ignored`, `abandoned` and hidden facets permanently empty.
      listProjects({ includeIgnored: true, includeHidden: true }),
      listPerspectives(), listActivity(ACTIVITY_LIMIT), listRfas(),
      listGroups(), listInvestigations(),
    ]);

  if (me.status === 'fulfilled') state.me = me.value;
  if (perspectives.status === 'fulfilled') state.perspectives = perspectives.value || [];
  // Both endpoints PAGE. A returned length equal to the limit is a page
  // that filled, not a total — rendering it as one would print an exact
  // figure that is exactly wrong, and nothing about the number would look
  // suspicious. Saturated counts are shown as "N+".
  state.counts.activity = countOf(activity, ACTIVITY_LIMIT, 'entries');
  state.counts.rfas = countOf(rfas, RFA_LIMIT, 'rfas');
  if (groups.status === 'fulfilled') state.groups = groups.value || [];
  if (investigations.status === 'fulfilled') state.investigations = investigations.value || [];
  if (projects.status === 'fulfilled') {
    state.projects = projects.value || [];
  }

  // The investigation may have gone away since this browser last stored it.
  if (state.investigation
      && !state.investigations.some((i) => i.slug === state.investigation)) {
    state.investigation = '';
  }
  await loadWorkingSet();

  // "In scope" is the default chip, but only when it can mean anything.
  if (state.scope === 'working-set' && !state.investigation) state.scope = '';

  if (!state.selectedSlug) {
    const first = visibleProjects()[0] || state.projects[0];
    if (first) state.selectedSlug = first.slug;
  }
  writeUrl();

  renderTopBar();
  renderIntentNav();
  renderPerspectiveRow();
  renderSidebar();
  renderRail();
  await loadPane();
}

// See the button's comment in index.html: hideLogin() is itself the guard.
document.getElementById('login-dismiss-btn')
  ?.addEventListener('click', () => Auth.hideLogin());

// auth.js owns the gate: it either starts us now or after a successful
// sign-in. Nothing here renders before it says so.
Auth.init(start);
