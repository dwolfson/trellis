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
  getAnswer,
  getMe,
  getQuestions,
  listActivity,
  listPerspectives,
  listProjects,
  listRfas,
  pollActivity,
  runAnalysis,
} from '/static/re-api.js';

/* ════════════════════════════════════════════════════════════════════════
 * State
 * ════════════════════════════════════════════════════════════════════════ */

const state = {
  resourceType: 'repo',        // repo | db | filesystem — only repo is real here
  projects: [],
  selectedSlug: null,
  filter: '',
  dispositionFacet: 'all',
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
      <span class="px-[10px] py-[9px] text-accent-on-dark">RFAs <span id="rfa-count" class="tnum">${
        state.counts.rfas === null ? '–' : state.counts.rfas}</span></span>
      <span class="px-[10px] py-[9px] text-chrome-muted">Chat</span>
    </span>`;

  nav.querySelectorAll('button[data-stage]').forEach((b) => {
    b.addEventListener('click', () => {
      state.stage = b.dataset.stage;
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
      loadPane();
    });
  });
}

function renderSidebar() {
  const el = $('sidebar');
  const types = [
    { id: 'repo', label: 'Repos' },
    { id: 'db', label: 'DBs' },
    { id: 'filesystem', label: 'FS' },
  ];

  // Disposition facets: ONLY the non-zero ones, plus All. The current UI
  // renders six permanent zeros, which is six chips of nothing.
  const counts = {};
  for (const p of state.projects) {
    counts[p.disposition || 'undecided'] = (counts[p.disposition || 'undecided'] || 0) + 1;
  }
  const facets = ['all', ...Object.keys(counts).sort()];

  const visible = state.projects.filter((p) => {
    if (state.dispositionFacet !== 'all' && (p.disposition || 'undecided') !== state.dispositionFacet) return false;
    if (!state.filter) return true;
    const f = state.filter.toLowerCase();
    return (p.slug || '').toLowerCase().includes(f)
        || (p.display_name || '').toLowerCase().includes(f);
  });

  // Grouped by the repo's group, so the heading says what the list is.
  const groups = new Map();
  for (const p of visible) {
    const g = p.group_slug || 'Ungrouped';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(p);
  }

  el.innerHTML = `
    <div class="mb-3 flex gap-[5px] text-chip">
      ${types.map((t) => `<button data-type="${t.id}" class="cursor-pointer rounded-sm bg-transparent px-[10px] py-[3px]
        ${state.resourceType === t.id ? 'border border-accent text-accent-on-dark' : 'border border-chrome-line text-chrome-muted hover:border-accent'}"
        >${t.label}</button>`).join('')}
    </div>

    <input id="resource-filter" placeholder="Filter repos…" value="${esc(state.filter)}"
      class="mb-[10px] w-full rounded-sm border border-chrome-line bg-transparent px-[9px] py-[5px]
             text-chip text-chrome-ink placeholder:text-chrome-muted">

    <div class="mb-[14px] flex flex-wrap gap-[5px] text-caps">
      ${facets.map((f) => `<button data-facet="${esc(f)}" class="cursor-pointer rounded-pill bg-transparent px-2 py-[2px]
        ${state.dispositionFacet === f ? 'border border-accent text-accent-on-dark' : 'border border-chrome-line text-chrome-muted hover:border-accent'}"
        >${esc(f)}${f === 'all' ? '' : ` <span class="tnum">${counts[f]}</span>`}</button>`).join('')}
    </div>

    ${state.resourceType !== 'repo' ? `
      <div class="text-chip text-chrome-muted" style="border-bottom:1px dashed currentColor;padding-bottom:2px">
        Databases and filesystems · not built in /next
      </div>
      <div class="mt-s2 text-chip text-chrome-muted">
        This experiment covers one pane for one resource type. The current UI
        has both.
      </div>` : [...groups.entries()].map(([g, rows]) => `
      <div class="mb-[7px] font-heading uppercase tracking-caps text-caps text-chrome-muted">
        ${esc(g)} · <span class="tnum">${rows.length}</span>
      </div>
      <div class="mb-s4 flex flex-col gap-[1px]">
        ${rows.map((p) => `<button data-slug="${esc(p.slug)}" class="cursor-pointer bg-transparent px-2 py-[5px] text-left
          ${p.slug === state.selectedSlug
            ? 'border-l-2 border-accent bg-chrome-surface text-chrome-ink'
            : 'border-l-2 border-transparent text-chrome-ink hover:bg-chrome-surface'}"
          >${esc(p.display_name || p.slug)}</button>`).join('')}
      </div>`).join('')}
  `;

  el.querySelectorAll('button[data-type]').forEach((b) => b.addEventListener('click', () => {
    state.resourceType = b.dataset.type;
    renderSidebar();
    loadPane();
  }));
  el.querySelectorAll('button[data-facet]').forEach((b) => b.addEventListener('click', () => {
    state.dispositionFacet = b.dataset.facet;
    renderSidebar();
  }));
  el.querySelectorAll('button[data-slug]').forEach((b) => b.addEventListener('click', () => {
    // Selecting a resource preserves stage and perspectives, deliberately.
    state.selectedSlug = b.dataset.slug;
    renderSidebar();
    renderTopBar();
    loadPane();
  }));
  const filter = $('resource-filter');
  filter?.addEventListener('input', (e) => {
    state.filter = e.target.value;
    renderSidebar();
    $('resource-filter').focus();
  });
}

/* ════════════════════════════════════════════════════════════════════════
 * The right rail — Ask, scoped here
 * ════════════════════════════════════════════════════════════════════════ */

function renderRail() {
  $('rail').innerHTML = `
    <div class="mb-s3 font-heading uppercase tracking-caps text-caps text-accent-on-dark">
      Ask · scoped here
    </div>
    <textarea id="ask-input" rows="3" placeholder="Ask about this resource…"
      class="mb-s2 w-full rounded-sm border border-chrome-line bg-transparent p-s2 text-subtab
             text-chrome-ink placeholder:text-chrome-muted"></textarea>
    <button id="ask-submit"
      class="cursor-pointer rounded-sm border border-accent bg-transparent px-[10px] py-[4px]
             text-chip text-accent-on-dark">Ask</button>
    <div id="ask-answer" class="mt-s3"></div>`;

  $('ask-submit').addEventListener('click', submitAsk);
  $('ask-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitAsk();
  });
}

async function submitAsk() {
  const q = $('ask-input').value.trim();
  if (!q) return;
  const out = $('ask-answer');
  out.innerHTML = `<div class="text-chip text-chrome-muted">Asking…</div>`;
  try {
    const res = await fetch('/api/query/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: q,
        project_slug: state.selectedSlug,
        perspectives: [...state.activePerspectives],
      }),
    });
    if (!res.ok) throw new ApiError(res.status, res.statusText, '/api/query/');
    const body = await res.json();

    // The source footer is a REQUIREMENT, not decoration: an answer composed
    // from survey metadata and an answer retrieved from embeddings must not
    // look alike. When the response does not say which, this says THAT —
    // it does not guess, and it does not quietly imply retrieval.
    const manifest = body.compiled && body.compiled.manifest;
    let source;
    if (manifest && typeof manifest === 'object') {
      const parts = Object.keys(manifest).filter((k) => {
        const v = manifest[k];
        return Array.isArray(v) ? v.length : v != null && v !== '';
      });
      source = parts.length
        ? `From compiled evidence · ${parts.join(', ')}`
        : 'Compiled evidence was empty · answered from retrieval';
    } else {
      source = 'No compiled evidence on this answer · source not reported';
    }

    out.innerHTML = `
      <div class="rounded-sm border border-chrome-line p-s3 text-subtab">
        <div class="whitespace-pre-wrap">${tnum(esc(body.response || ''))}</div>
        <div class="mt-[10px] border-t border-chrome-line-soft pt-[9px] text-caps text-chrome-muted">
          ${esc(source)}${body.intent ? ` · intent ${esc(body.intent)}` : ''}${body.cached ? ' · cached' : ''}
        </div>
      </div>`;
  } catch (err) {
    out.innerHTML = `<div class="rounded-sm border border-chrome-line p-s3 text-chip text-accent-on-dark">
      The question could not be asked: ${esc(err.message)}
    </div>`;
  }
}

/* ════════════════════════════════════════════════════════════════════════
 * The content pane
 * ════════════════════════════════════════════════════════════════════════ */

function subTabsHtml() {
  return `<div class="mb-s4 flex flex-wrap gap-s3 font-heading text-subtab">
    ${SUB_TABS.map((t) => {
      const active = t.toLowerCase() === state.subTab;
      const available = t === 'Questions';   // the one real pane in /next
      if (active) return `<span class="border-b border-accent pb-[2px] text-ink">${t}</span>`;
      if (!available) return `<span title="Not built in /next — use the current UI"
        class="text-ink-muted" style="border-bottom:1px dashed currentColor;padding-bottom:1px">${t}</span>`;
      return `<button data-subtab="${t.toLowerCase()}" class="cursor-pointer bg-transparent text-ink-muted hover:text-ink">${t}</button>`;
    }).join('')}
  </div>`;
}

function paneMessage(title, body) {
  return `${subTabsHtml()}
    <h3 class="m-0 font-heading text-name font-normal">${esc(title)}</h3>
    <div class="my-s3 h-px bg-rule"></div>
    <p class="max-w-[70ch] text-answer text-ink-muted">${esc(body)}</p>`;
}

async function loadPane() {
  const el = $('content');

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
    renderPerspectiveRow();
    return;
  }

  if (state.resourceType !== 'repo') {
    el.innerHTML = paneMessage('Repos only, in /next',
      'The Questions pane is built for repositories. Databases and filesystems '
      + 'are live in the current UI.');
    return;
  }

  if (!state.selectedSlug) {
    el.innerHTML = paneMessage('Select a resource',
      'Pick a repository from the sidebar to see its question checklist.');
    return;
  }

  const slug = state.selectedSlug;
  // The frame first, then per-row skeletons — rows arrive independently, and
  // a centred spinner would hide the ones that are already here.
  el.innerHTML = `${subTabsHtml()}
    <div class="flex flex-wrap items-baseline gap-s3">
      <h3 class="m-0 font-heading text-name font-normal">${esc(slug)}</h3>
      <span id="answered-count" class="tnum text-[12px] text-ink-muted">loading…</span>
    </div>
    <div class="my-s3 h-px bg-rule"></div>
    <div id="question-rows"></div>`;

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
    rows.innerHTML = `<div class="py-s3 text-answer text-ink-muted">
      No catalogued questions match this stage and this perspective set.
      That is a fact about the filter, not about the repository.</div>`;
    $('answered-count').textContent = `0 questions · ${stageLabel()}`;
    return;
  }

  rows.innerHTML = state.questions.map((q, i) => rowShell(q, i)).join('');
  updateAnsweredCount();

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
  const dim = ['unrun', 'no-surveyor', 'unclassified'].includes(st);
  const glyphColor = ['answered', 'automatic', 'human', 'running'].includes(st)
    ? 'text-accent-ink' : 'text-ink-muted';

  const tag = st === 'no-surveyor'
    ? `<span class="ml-auto rounded-pill border border-dashed border-accent px-2 py-[1px] text-caps text-accent-ink">no surveyor yet</span>`
    : perspective
      ? `<span class="ml-auto rounded-pill border border-rule-strong px-2 py-[1px] text-caps text-ink-muted">${esc(perspective)}</span>`
      : '';

  const head = `<div class="flex flex-wrap items-baseline gap-[9px]">
      <span class="w-[13px] ${glyphColor} text-question">${st === 'loading' ? '' : glyph}</span>
      <span class="font-heading text-question font-semibold ${dim ? 'text-ink-muted' : 'text-ink'}">${esc(entry.question)}</span>
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
    return `<div class="${indent} text-caveat text-ink-muted">${tnum(esc(why))}</div>`;
  }

  if (st === 'human') {
    const why = entry.note || 'This is answered by someone stating it, not by a survey.';
    return `<div class="${indent} text-caveat text-ink-muted">${tnum(esc(why))}</div>
      <div class="${indent} text-provenance text-ink-muted">
        Enrichment · <span class="text-ink-muted">answer inline · not built in /next</span>
      </div>`;
  }

  if (st === 'unclassified') {
    return `<div class="${indent} text-caveat text-ink-muted">The catalog does not state how this
      question would be answered.</div>`;
  }

  if (st === 'unrun') {
    // NO answer line. Not a zero, not an empty string — the absence of the
    // line is the statement.
    const why = (env && env.blocked_reason) || 'Not run yet.';
    const lines = readEnvelope(entry, env);
    return `<div class="${indent} text-caveat text-ink-muted">${tnum(esc(why))}</div>`
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
  const out = $('ask-answer');
  if (!env || env === 'loading' || env.__error) return;

  const facts = (env.facts || []).map((f) => {
    const value = f.value && Object.keys(f.value).length
      ? `<div class="mt-[4px] leading-[1.95]">${Object.entries(f.value)
          .map(([k, v]) => measureHtml(k, v)).join('')}</div>`
      : '';
    return `<div class="mb-s2 border-b border-chrome-line-soft pb-s2 last:border-0">
      <div class="text-chip text-accent-on-dark">${esc(f.analysis_id)}</div>
      <div class="text-caps text-chrome-muted">state ${esc(f.state)} · ${esc(f.provenance)}${
        f.last_run_at ? ` · ${esc(ago(f.last_run_at))}` : ' · never run'}</div>
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
  renderIntentNav();
  renderRail();
  renderTopBar();

  // Everything below is independent; one failing must not take the frame
  // down with it. `allSettled`, and each consumer handles its own absence.
  const [me, projects, perspectives, activity, rfas] = await Promise.allSettled([
    getMe(), listProjects(), listPerspectives(), listActivity(ACTIVITY_LIMIT), listRfas(),
  ]);

  if (me.status === 'fulfilled') state.me = me.value;
  if (perspectives.status === 'fulfilled') state.perspectives = perspectives.value || [];
  // Both endpoints PAGE. A returned length equal to the limit is a page
  // that filled, not a total — rendering it as one would print an exact
  // figure that is exactly wrong, and nothing about the number would look
  // suspicious. Saturated counts are shown as "N+".
  state.counts.activity = countOf(activity, ACTIVITY_LIMIT, 'entries');
  state.counts.rfas = countOf(rfas, RFA_LIMIT, 'rfas');
  if (projects.status === 'fulfilled') {
    state.projects = projects.value || [];
    if (!state.selectedSlug && state.projects.length) state.selectedSlug = state.projects[0].slug;
  }

  renderTopBar();
  renderIntentNav();
  renderPerspectiveRow();
  renderSidebar();
  await loadPane();
}

// See the button's comment in index.html: hideLogin() is itself the guard.
document.getElementById('login-dismiss-btn')
  ?.addEventListener('click', () => Auth.hideLogin());

// auth.js owns the gate: it either starts us now or after a successful
// sign-in. Nothing here renders before it says so.
Auth.init(start);
