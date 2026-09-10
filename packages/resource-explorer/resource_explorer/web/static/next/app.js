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

// The Scouting slice — work lists, batch runs and the comparison grid. Its
// own module: it is the one surface that reads a SET rather than a resource,
// and it goes when the experiment goes.
import { listWorkLists, openWorkList, saveAsWorkList } from '/static/next/worklist.js';
import { ago } from '/static/next/format.js';
import {
  ApiError,
  VALID_DISPOSITIONS,
  addInvestigationMember,
  ask,
  REPO_CHARTS,
  getAnswer,
  getChart,
  getDispositionHistory,
  getMe,
  getQuestions,
  getScoutingOverview,
  listActivity,
  listAnalyses,
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
  showMarkKey: false,
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
  promoted: null,              // a chat answer promoted into the pane
  charts: null,                // Understanding's probed chart index
  workLists: [],               // saved work lists
  workListSlug: null,          // the open one; the pane takes over when set
  lastWorkListSlug: null,      // the one you were last in, for the way back
  workListIndex: false,        // showing the list OF work lists
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
  // Understanding was marked "not built" here. It renders charts now — see
  // loadChartsPane(); the catalog rows it lacks were never what fed it.
  { id: 'understanding', label: 'Understanding' },
  { id: 'curate',        label: 'Curate' },
  { id: 'automate',      label: 'Automate' },
];

/** Sub-tab order is IDENTICAL across every stage, on purpose. A stage that
 *  lacks one greys it out rather than removing it, so the tab under the
 *  cursor does not change meaning when you switch stages. */
/**
 * Sub-tab order is IDENTICAL across every stage, on purpose.
 *
 * `label` is what the current UI calls it; `does` is what it actually is.
 * They differ for Search, which is REPO DISCOVERY — saved sources, a GitHub
 * search form and a list importer — and has nothing to do with the selected
 * resource. Naming the deferred stub "Search" made /next mis-describe the
 * thing it was deferring.
 */
const SUB_TABS = [
  { id: 'search', label: 'Search', does: 'Repo discovery — find and import candidate repos' },
  { id: 'survey', label: 'Survey', does: 'Survey definitions, their steps, and running them' },
  { id: 'dashboard', label: 'Dashboard', does: 'Survey results — health, maturity, community, charts' },
  { id: 'questions', label: 'Questions', does: 'The question checklist' },
  { id: 'disposition', label: 'Disposition', does: 'Set a verdict on this resource, and its history' },
];

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


/* ────────────────────────────────────────────────────────────────────────
 * Icons
 *
 * Lucide, vendored as a sprite by frontend-build/build-next-icons.py and
 * injected into the document once, so `currentColor` inherits — which is the
 * whole point, since several of these carry state.
 *
 * Emoji is not the icon system, but the replacement rule is "nearest Lucide
 * equivalent of the SAME metaphor", not "an abstract shape". A cloud stays a
 * cloud. Only the six question states use an abstract glyph, because no
 * metaphor exists for them and a legend keys them instead.
 * ──────────────────────────────────────────────────────────────────────── */

async function loadIcons() {
  if (document.getElementById('lucide-sprite')) return;
  try {
    const res = await fetch('/static/next/icons.svg');
    if (!res.ok) return;                     // icons are an enhancement
    const holder = document.createElement('div');
    holder.id = 'lucide-sprite';
    holder.style.display = 'none';
    holder.innerHTML = await res.text();
    document.body.prepend(holder);
  } catch { /* the labels still read without them */ }
}

/** An inline icon. `title` is required wherever the icon is the only label —
 *  an unlabelled pictogram is the emoji problem with better provenance. */
function icon(name, { size = 15, cls = '', title = '' } = {}) {
  return `<svg width="${size}" height="${size}" class="inline-block shrink-0 align-[-2px] ${cls}"
    aria-hidden="${title ? 'false' : 'true'}" ${title ? `role="img"` : ''}
    ><use href="#i-${esc(name)}"/>${title ? `<title>${esc(title)}</title>` : ''}</svg>`;
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
  answered: '✓',
  automatic: '✓',
  unrun: '○',
  human: '⚠',
  'no-surveyor': '○',
  unclassified: '·',
  running: '◔',
  error: '✕',
};

/**
 * State colour, per ground.
 *
 * Hue is back — ALONGSIDE the glyph, never instead of it. Colour is not the
 * only channel carrying meaning here (the glyph and the legend words carry
 * it too), and it does not carry two meanings at once: gold is reserved for
 * "needs your attention" and is not a state role.
 *
 * Two variants per role because one value cannot hold 4.5:1 against both a
 * paper and a chrome ground — see the measurement in tailwind-next.config.js.
 */
const STATE_TONE = {
  answered:      { paper: 'text-state-ok',    chrome: 'text-state-ok-on-dark' },
  automatic:     { paper: 'text-state-ok',    chrome: 'text-state-ok-on-dark' },
  unrun:         { paper: 'text-state-warn',  chrome: 'text-state-warn-on-dark' },
  human:         { paper: 'text-accent-ink',  chrome: 'text-accent-on-dark' },
  'no-surveyor': { paper: 'text-state-gap',   chrome: 'text-state-gap-on-dark' },
  unclassified:  { paper: 'text-ink-muted',   chrome: 'text-chrome-muted' },
  running:       { paper: 'text-accent-ink',  chrome: 'text-accent-on-dark' },
  error:         { paper: 'text-state-warn',  chrome: 'text-state-warn-on-dark' },
};

const tone = (st, ground = 'paper') =>
  (STATE_TONE[st] || STATE_TONE.unclassified)[ground];

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
  lines.mermaid = factMermaid(env);

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
    <!-- Work lists sit at the end of the frame row because, like
         Investigation, they are a FRAME around the stages rather than a stage:
         Investigation is why a body of work exists, a work list is which
         resources it covers. Fixed position, always present — the matrix had
         no front door before this, only a sidebar section and a crumb that
         existed once you had already found it. -->
    <span id="worklist-nav" class="flex items-center"></span>
    <span class="ml-auto flex gap-s2 text-subtab">
      <a href="/" title="The RFA drawer is not built in /next — opens the current UI"
        class="px-[10px] py-[9px] text-accent-on-dark no-underline"
        style="border-bottom:1px dashed currentColor">RFAs <span id="rfa-count" class="tnum">${
        state.counts.rfas === null ? '–' : state.counts.rfas}</span> ↗</a>
      <button id="chat-toggle" aria-expanded="true"
        class="cursor-pointer bg-transparent px-[10px] py-[9px] text-accent-on-dark">Chat ×</button>
    </span>`;

  renderWorkListNav();

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

/** The list OF work lists — the front door the matrix never had. */
function workListIndexHtml() {
  if (!state.workLists.length) {
    return `${subTabsHtml()}
      <h3 class="m-0 font-heading text-name font-normal">No work lists yet</h3>
      <div class="my-s3 h-px bg-rule"></div>
      <p class="max-w-[70ch] text-answer text-ink">
        A work list is a set of resources you compare as rows x questions, run a
        survey across, and narrow down. Make one from the sidebar:
        <strong>Select</strong>, tick some repos, then <strong>save as work list</strong>.
      </p>`;
  }
  return `${subTabsHtml()}
    <h3 class="m-0 font-heading text-name font-normal">Work lists</h3>
    <div class="my-s3 h-px bg-rule"></div>
    <div class="flex flex-col">
      ${state.workLists.map((w) => `<button data-open-wl="${esc(w.slug)}"
        class="cursor-pointer border-b border-rule bg-transparent py-s3 text-left hover:bg-accent-tint">
        <div class="font-heading text-question font-semibold text-ink">${esc(w.display_name)}</div>
        <div class="text-provenance text-ink-muted">
          <span class="tnum">${w.member_count}</span> resources
          ${w.investigation ? ` · ${esc(w.investigation)}` : ''}
          ${w.derived_from ? ` · narrowed from ${esc(w.derived_from)}` : ''}
          · ${w.egeria_guid ? 'published to Egeria' : 'not published'}
        </div>
      </button>`).join('')}
    </div>`;
}

/**
 * The work lists entry, permanently in the nav.
 *
 * The matrix is a view of a SET and every other pane is a view of one
 * resource, so there was nowhere on the Questions tab to put a route to it —
 * a single repo is not a set. The consequence was that the matrix had no
 * front door: you reached it from a sidebar section, or from a crumb that
 * only existed if you had already been there.
 *
 * ONE control, in a fixed place, doing both jobs: it names the open list when
 * you are in one, and takes you to the index when you are not. A separate
 * "back to X" crumb beside it would be two things for one job, which is the
 * complaint that retired the emoji.
 */
function renderWorkListNav() {
  const el = $('worklist-nav');
  if (!el) return;
  const byslug = (sl) => state.workLists.find((w) => w.slug === sl);
  const open = state.workListSlug ? byslug(state.workListSlug) : null;
  const last = !open && state.lastWorkListSlug ? byslug(state.lastWorkListSlug) : null;
  const n = state.workLists.length;
  const active = Boolean(state.workListSlug || state.workListIndex);

  // TWO controls, because they are two jobs — not one control with two
  // meanings. The index is "show me the sets"; the return is "put me back in
  // the one I was reading". Collapsing them cost a click on the path people
  // actually take, which is matrix -> a question -> back.
  el.innerHTML = `<button data-act="worklists"
      title="${open ? 'Go back to the list of work lists' : 'Compare a set of resources as rows x questions'}"
      class="cursor-pointer whitespace-nowrap bg-transparent px-3 py-[9px] ${
        active ? 'border-b-2 border-accent text-accent-on-dark'
               : 'border-b-2 border-transparent text-chrome-muted hover:text-chrome-ink'}"
      >▦ ${open ? esc(open.display_name) : `Work lists${n ? ` <span class="tnum">${n}</span>` : ''}`}</button>
    ${last ? `<button data-act="back-to-matrix"
      title="Back to the matrix you were reading"
      class="cursor-pointer whitespace-nowrap bg-transparent px-2 py-[9px] text-chrome-muted hover:text-chrome-ink"
      style="border-bottom:1px dashed currentColor">↩ ${esc(last.display_name)}</button>` : ''}`;

  el.querySelector('[data-act="worklists"]').addEventListener('click', () => {
    state.workListSlug = null;
    state.workListIndex = true;
    writeUrl(); renderSidebar(); loadPane();
  });
  el.querySelector('[data-act="back-to-matrix"]')?.addEventListener('click', () => {
    state.workListSlug = state.lastWorkListSlug;
    state.workListIndex = false;
    writeUrl(); renderSidebar(); loadPane();
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
 * Diagrams and charts
 *
 * They live in the CONTENT PANE, on paper. That is a real dividend of the
 * dark-chrome/paper-content split: Mermaid, Plotly and Kroki all default to
 * a light ground, so on paper they need no dark override and no second
 * theme — which is what the current dark UI has to fight for all three.
 *
 * Every renderer is bound to the TOKEN LAYER rather than to hardcoded
 * values, and the token values are read back off the live stylesheet rather
 * than restated here. Restating them would put the palette in two places,
 * which is the thing the token layer exists to prevent.
 *
 * Diagrams do NOT use the body serif. SVG text at small sizes in Lora or
 * Cormorant is a bad trade, so node labels, axis ticks and legends take the
 * `diagram` font token. This is the one place the type system is
 * deliberately overridden.
 * ════════════════════════════════════════════════════════════════════════ */

let _themeProbe = null;

/** Read a token's computed value off a probe element carrying its class.
 *  One source of truth: tailwind-next.config.js, via the built stylesheet. */
function tokens() {
  if (!_themeProbe) {
    _themeProbe = document.createElement('div');
    _themeProbe.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none';
    _themeProbe.innerHTML = `
      <span data-t="paper" class="bg-paper"></span>
      <span data-t="paper-surface" class="bg-paper-surface"></span>
      <span data-t="ink" class="text-ink"></span>
      <span data-t="ink-muted" class="text-ink-muted"></span>
      <span data-t="rule-strong" class="text-rule-strong"></span>
      <span data-t="accent" class="text-accent"></span>
      <span data-t="state-ok" class="text-state-ok"></span>
      <span data-t="state-warn" class="text-state-warn"></span>
      <span data-t="state-gap" class="text-state-gap"></span>
      <span data-t="font-diagram" class="font-diagram"></span>`;
    document.body.appendChild(_themeProbe);
  }
  const read = (name, prop) => {
    const el = _themeProbe.querySelector(`[data-t="${name}"]`);
    return el ? getComputedStyle(el)[prop] : '';
  };
  return {
    paper: read('paper', 'backgroundColor'),
    paperSurface: read('paper-surface', 'backgroundColor'),
    ink: read('ink', 'color'),
    inkMuted: read('ink-muted', 'color'),
    rule: read('rule-strong', 'color'),
    accent: read('accent', 'color'),
    ok: read('state-ok', 'color'),
    warn: read('state-warn', 'color'),
    gap: read('state-gap', 'color'),
    font: read('font-diagram', 'fontFamily'),
  };
}

/** Load a vendored script once. Both are already in static/vendor. */
const _scripts = new Map();
function loadScript(src) {
  if (_scripts.has(src)) return _scripts.get(src);
  const p = new Promise((resolve, reject) => {
    const el = document.createElement('script');
    el.src = src;
    el.onload = resolve;
    el.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.appendChild(el);
  });
  _scripts.set(src, p);
  return p;
}

/**
 * Form follows ANSWER SHAPE, not the model's preference.
 *
 *   scalar / short verdict     inline in the rail
 *   ranked list                table; promoted when wide
 *   anything over time         chart, promoted to the pane
 *   relationships / topology   Mermaid, always in the pane
 *   one question, many repos   the work-list grid (does not exist yet)
 *
 * A diagram cannot live in the rail: it is at most 290px wide and a topology
 * graph there is unreadable. So the rail shows a marker and promotes.
 */
function answerForm(turn) {
  if (turn.mermaid) return 'diagram';
  if (turn.chart) return 'chart';
  if (turn.candidates && turn.candidates.length) return 'list';
  return 'inline';
}

/* ── Understanding: the charts pane ──────────────────────────────────── */

/**
 * Every chart kind, with what each actually holds for this resource.
 *
 * The three outcomes are kept apart, because they are three different
 * sentences and this app's whole discipline is not folding them together:
 *   - a figure with series      -> render it
 *   - a 200 with no series      -> "nothing recorded yet", NOT an error and
 *                                  NOT an empty chart, which would read as
 *                                  a measured zero
 *   - a failed call             -> say the call failed, name the reason
 */
async function loadChartsPane() {
  const el = $('content');
  const slug = state.selectedSlug;

  if (!slug) {
    el.innerHTML = paneMessage('Select a resource',
      'Pick a repository from the sidebar to see its charts.');
    bindSubTabs();
    return;
  }


  // NO sub-tab row here. Understanding has no Search/Survey/Dashboard/
  // Questions/Disposition — rendering the strip with "Questions" underlined
  // while a chart is on screen says this pane is something it is not.
  el.innerHTML = `
    <div class="mb-s4 font-heading text-subtab text-ink">
      <span class="border-b border-accent pb-[2px]">Charts</span>
      <span class="ml-s3 text-caps uppercase tracking-caps text-ink-muted">Understanding has one pane</span>
    </div>
    <div id="resource-header">${resourceHeaderHtml(slug)}</div>
    <div class="my-s3 h-px bg-rule"></div>
    <div id="chart-index" class="flex flex-wrap gap-s2"></div>
    <div id="chart-body" class="mt-s4"></div>`;
  bindResourceHeader();

  const index = $('chart-index');
  index.innerHTML = REPO_CHARTS.map(([kind, label]) =>
    `<button data-chart="${kind}" disabled
      class="cursor-wait rounded-sm border border-rule-strong bg-transparent px-2 py-[3px]
             text-caveat text-ink-muted">${esc(label)}…</button>`).join('');

  // Probe each kind so the index never offers a chart with nothing in it.
  const results = await Promise.all(REPO_CHARTS.map(async ([kind, label]) => {
    try {
      const fig = await getChart(slug, kind);
      const series = Array.isArray(fig?.data) ? fig.data.length : 0;
      return { kind, label, fig, series, error: null };
    } catch (err) {
      return { kind, label, fig: null, series: 0, error: err.message };
    }
  }));
  if (slug !== state.selectedSlug) return;
  state.charts = results;

  index.innerHTML = results.map((r) => {
    if (r.error) {
      return `<span title="${esc(r.error)}"
        class="rounded-sm border border-dashed border-state-warn px-2 py-[3px] text-caveat text-state-warn"
        >${esc(r.label)} · unavailable</span>`;
    }
    if (!r.series) {
      return `<span title="The series exists and has nothing in it yet"
        class="rounded-sm border border-dashed border-rule-strong px-2 py-[3px] text-caveat text-ink-muted"
        >${esc(r.label)} · nothing recorded yet</span>`;
    }
    return `<button data-chart="${r.kind}"
      class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[3px]
             text-caveat text-ink hover:border-accent">${esc(r.label)}</button>`;
  }).join('');

  index.querySelectorAll('[data-chart]').forEach((b) => b.addEventListener('click', () => {
    index.querySelectorAll('[data-chart]').forEach((o) =>
      o.classList.toggle('border-accent', o === b));
    drawChart(results.find((r) => r.kind === b.dataset.chart));
  }));

  const first = results.find((r) => r.series);
  if (first) {
    index.querySelector(`[data-chart="${first.kind}"]`)?.classList.add('border-accent');
    drawChart(first);
  } else {
    $('chart-body').innerHTML = `<div class="text-answer text-ink">
      Nothing has been recorded for any of this resource's charts yet. That is
      a statement about the history collected so far, not about the resource.</div>`;
  }
}

/** Render one figure into the pane, themed from the token layer. */
async function drawChart(entry) {
  const body = $('chart-body');
  if (!body || !entry) return;
  body.innerHTML = `<div class="text-caveat text-ink-muted">Drawing ${esc(entry.label)}…</div>`;
  try {
    await loadScript('/static/vendor/plotly.min.js');
    body.innerHTML = `<div id="chart-canvas" style="height:min(62vh,560px)"></div>
      <div class="mt-s2 text-provenance text-ink-muted">${esc(entry.label)} ·
        <span class="tnum">${entry.series}</span> series ·
        from the registry's recorded history · no retrieval</div>`;
    await window.Plotly.newPlot($('chart-canvas'), entry.fig.data || [],
                                chartLayout(entry.fig.layout),
                                { displaylogo: false, responsive: true });
  } catch (err) {
    body.innerHTML = `<div class="text-answer text-state-warn">
      ${esc(entry.label)} could not be drawn: ${esc(err.message)}</div>`;
  }
}

/**
 * The figure's own layout, with the token layer laid over it.
 *
 * Plotly's default template is a dark-on-white theme of its own; on paper it
 * has to be overridden or the chart is a different design from the page it
 * sits in. `template: undefined` drops that default rather than fighting it
 * property by property.
 */
function chartLayout(layout = {}) {
  const t = tokens();
  const axis = (a = {}) => Object.assign({
    gridcolor: t.rule, zerolinecolor: t.rule, linecolor: t.rule,
    tickfont: { family: t.font, color: t.inkMuted, size: 11 },
    titlefont: { family: t.font, color: t.inkMuted, size: 11 },
  }, a);
  return Object.assign({}, layout, {
    template: undefined,
    paper_bgcolor: t.paper,
    plot_bgcolor: t.paper,
    colorway: [t.accent, t.ok, t.gap, t.warn, t.inkMuted],
    font: { color: t.ink, family: t.font, size: 12 },
    xaxis: axis(layout.xaxis),
    yaxis: axis(layout.yaxis),
    legend: Object.assign({ font: { family: t.font, color: t.ink, size: 11 } }, layout.legend),
    margin: { l: 56, r: 24, t: 24, b: 48 },
  });
}

/** The Mermaid source a fact carries, if it carries any.
 *
 *  `architecture_diagram` writes its source into the fact value, so the
 *  relationship question ("How do its components relate to each other?") has
 *  a real diagram sitting behind it. This is the product path to a diagram —
 *  a chat answer is not the only one, and wiring promotion ONLY to chat left
 *  the feature unreachable for anyone who had not asked a question first.
 */
function factMermaid(env) {
  for (const f of (env && env.facts) || []) {
    const src = f.value && (f.value.mermaid || f.value.diagram);
    if (typeof src === 'string' && src.trim()) {
      return { source: src.trim(), analysisId: f.analysis_id, lastRun: f.last_run_at || '' };
    }
  }
  return null;
}

/** Render a promoted artefact in the content pane, at full width. */
async function promoteToPane(turn) {
  const el = $('content');
  if (!el) return;
  state.promoted = turn;
  const form = answerForm(turn);

  el.innerHTML = `${subTabsHtml()}
    <div class="flex flex-wrap items-baseline gap-s3">
      <h3 class="m-0 font-heading text-name font-normal">${esc(turn.question)}</h3>
      <button data-act="close-promoted"
        class="ml-auto cursor-pointer bg-transparent text-caveat text-accent-ink underline">back to questions</button>
    </div>
    <div class="mt-s1 text-provenance text-ink-muted">${esc(turn.source || '')}</div>
    <div class="my-s3 h-px bg-rule"></div>
    <div id="promoted-body" class="min-h-[320px]"></div>`;
  bindSubTabs();
  el.querySelector('[data-act="close-promoted"]').addEventListener('click', () => {
    state.promoted = null;
    loadPane();
  });

  const body = $('promoted-body');
  try {
    if (form === 'chart') {
      await loadScript('/static/vendor/plotly.min.js');
      const fig = turn.chart;
      // Same themed layout as the Understanding pane — one place, so a chat
      // chart and a stage chart cannot drift into two designs.
      await window.Plotly.newPlot(body, fig.data || [], chartLayout(fig.layout || {}),
                                  { displaylogo: false, responsive: true });
    } else if (form === 'diagram') {
      const t = tokens();
      const prepped = mermaidForKroki(turn.mermaid);
      // Server-side render via Kroki — the browser never loads mermaid.js.
      const res = await fetch('/api/diagrams/mermaid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: prepped.source }),
      });
      if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
        throw new ApiError(res.status, detail, '/api/diagrams/mermaid');
      }
      // The endpoint returns the RAW SVG body as image/svg+xml, not JSON —
      // it is a thin proxy to Kroki and hands back exactly what Kroki sent.
      const raw = await res.text();
      if (!raw.includes('<svg')) throw new Error('the renderer returned no SVG');

      body.innerHTML = `
        <div id="promoted-svg" class="w-full overflow-hidden rounded-sm border border-rule-strong"
          style="height:min(70vh,640px);background:${t.paper}">${raw}</div>
        <div id="diagram-note" class="mt-s2 text-provenance text-ink-muted"></div>`;

      await loadScript('/static/vendor/svg-pan-zoom.min.js');
      const svgEl = body.querySelector('#promoted-svg svg');
      const note = [];
      if (svgEl) {
        themeSvgElement(svgEl, t);
        // Read the INTRINSIC size before touching it. These diagrams are
        // extreme strips — the real one measures 14102 x 193, a 73:1 ratio —
        // and forcing width AND height to 100% squashed it to an invisible
        // sliver, which is what "blank space where the diagram should be"
        // was. Let svg-pan-zoom own the sizing instead, and say how big the
        // thing actually is so a flat-looking strip is not a surprise.
        const vb = (svgEl.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
        const w = Math.round(vb[2] || svgEl.getBoundingClientRect().width);
        const h = Math.round(vb[3] || svgEl.getBoundingClientRect().height);
        svgEl.removeAttribute('width');
        svgEl.removeAttribute('height');
        svgEl.style.width = '100%';
        svgEl.style.height = '100%';
        svgEl.style.maxWidth = 'none';       // mermaid sets an inline max-width
        if (window.svgPanZoom) {
          const pz = window.svgPanZoom(svgEl, {
            controlIconsEnabled: true, fit: true, contain: true, center: true,
            minZoom: 0.05, maxZoom: 60,
          });
          // `fit` fits the LIMITING dimension, which for a 73:1 strip means
          // fitting the width and leaving the diagram 8px tall — visually
          // indistinguishable from an empty box, and exactly what "blank
          // space where the diagram should be" looked like.
          //
          // For an extreme aspect the useful opening view is fit-to-HEIGHT
          // with the left edge in view: nodes are legible and you pan
          // sideways. Capped, so a pathological ratio cannot zoom to a pixel.
          try {
            const sz = pz.getSizes();
            const vbW = sz.viewBox.width;
            const vbH = sz.viewBox.height;
            if (vbW && vbH && vbW / vbH > 4) {
              const shownH = sz.width * (vbH / vbW);       // height after fit-to-width
              const factor = Math.min(sz.height / shownH, 12);
              if (factor > 1.2) {
                pz.zoom(pz.getZoom() * factor);
                // Let the library do the arithmetic. Computing the pan by
                // hand put the content at y = -609 — above the box, zero
                // nodes on screen, which measures as "53 nodes rendered at
                // 96x39" and looks like an empty white panel. Centre, then
                // move only the horizontal axis to the left edge.
                pz.center();
                pz.pan({ x: 0, y: pz.getPan().y });
              }
            }
          } catch (e) {
            // Pan/zoom tuning is a nicety; a diagram that opened badly
            // framed still beats one that threw on the way in.
            console.warn('could not frame the diagram:', e);
          }
        }
        if (w && h) {
          note.push(`<span class="tnum">${w}</span> × <span class="tnum">${h}</span> at full size`
            + (w / h > 6 ? ' — a wide strip; scroll-zoom or use the controls' : ''));
        }
      }
      if (prepped.droppedStyles) {
        // Say what was given up, and why. A silently unstyled node is the
        // kind of small loss this project keeps finding months later.
        note.push(`<span class="text-accent-ink">the dashed “pending” styling on
          <span class="tnum">${prepped.droppedStyles}</span> node(s) was dropped —
          this renderer refuses a diagram that styles more than
          <span class="tnum">${KROKI_MAX_CLASSED_NODES}</span></span>`);
      }
      const noteEl = $('diagram-note');
      if (noteEl) noteEl.innerHTML = note.join(' · ');
    } else {
      body.innerHTML = `<div class="whitespace-pre-wrap text-answer text-ink">${tnum(esc(turn.answer || ''))}</div>`;
    }
  } catch (err) {
    // Per-artefact failure, stated. Never a blank pane.
    body.innerHTML = `<div class="text-answer text-state-warn">
      This could not be rendered: ${esc(err.message)}</div>`;
  }
}

/** Mermaid's own init directive, carrying the token values.
 *  Prepended rather than configured in JS because the render happens on the
 *  server; the directive is the only channel a Kroki round trip has. */
/**
 * Make diagram source this renderer will actually accept.
 *
 * Three transforms, each measured against the live Kroki on 6002 rather than
 * assumed — every one of them was found by bisecting a diagram that returned
 * `400 Internal Server Error` with no other diagnostic:
 *
 *  1. NO `%%` LINES AT ALL. This Kroki rejects any line beginning `%%` —
 *     a plain comment and an `%%{init: …}%%` directive alike, on a two-node
 *     diagram. That is why theming moved out of an init directive and into
 *     `themeSvgElement()` below; it is not a preference.
 *  2. `%` IS ESCAPED to `&percnt;`. A literal percent anywhere in a node
 *     label fails the whole render, and `architecture_diagram` writes
 *     confidence as `40% ⚠` into every label, so this alone made it
 *     unrenderable. `&percnt;` and NOT `&#37;`: both are accepted (200), but
 *     the numeric one comes back rendered as `40&%` — measured by reading
 *     the text nodes of the returned SVG, which is the only way to tell the
 *     two apart, since both "work" by status code.
 *  3. `class` ASSIGNMENTS ARE CAPPED at 20 nodes total. 20 renders, 21 does
 *     not, deterministically, whether on one line or split across several.
 *     Excess assignments are dropped rather than the diagram, and the caller
 *     says how many — losing the dashed "pending" styling on some nodes
 *     beats losing the diagram.
 *
 * THE REAL FIX IS IN THE GENERATOR, which should not emit source its own
 * renderer refuses. Worth noting the fact value carries
 * `exceeds_renderer_limit: false` for a diagram that no renderer here will
 * take — a guard that reports the opposite of what is true.
 */
const KROKI_MAX_CLASSED_NODES = 20;

function mermaidForKroki(source) {
  const out = [];
  let classed = 0;
  let droppedStyles = 0;
  for (const raw of String(source).split('\n')) {
    if (raw.trimStart().startsWith('%%')) continue;
    const line = raw.replace(/%/g, '&percnt;');
    const m = /^\s*class\s+(\S+)\s+\S+;\s*$/.exec(line);
    if (m) {
      const n = m[1].split(',').length;
      if (classed + n > KROKI_MAX_CLASSED_NODES) { droppedStyles += n; continue; }
      classed += n;
    }
    out.push(line);
  }
  return { source: out.join('\n'), droppedStyles };
}

/**
 * Theme a rendered SVG, scoped to that SVG.
 *
 * Mermaid's own theming is unreachable here (this Kroki rejects every `%%`
 * line, so there is no init directive to carry themeVariables), so the token
 * values are applied to the output instead.
 *
 * EVERY selector is prefixed with the element's own id. An SVG `<style>` is
 * NOT scoped — it is ordinary CSS in the same document — so an earlier
 * version of this containing bare `text, span, p { … !important }` restyled
 * the entire application the moment a diagram opened, chrome included. The
 * id is stamped on here rather than trusting mermaid's own `#container`,
 * which is neither unique nor ours.
 */
const DIAGRAM_ID = 're-diagram-svg';

function themeSvgElement(svgEl, t) {
  svgEl.id = DIAGRAM_ID;
  const rules = [
    ['', `background:${t.paper}`],
    ['.node rect, .node polygon, .node circle, .node path',
     `fill:${t.paperSurface} !important; stroke:${t.rule} !important`],
    ['.cluster rect', `fill:none !important; stroke:${t.rule} !important`],
    ['.edgePath path, .flowchart-link', `stroke:${t.rule} !important; fill:none !important`],
    ['.arrowheadPath, marker path', `fill:${t.rule} !important; stroke:${t.rule} !important`],
    ['text, .nodeLabel, .edgeLabel, .cluster-label, span, p, div',
     `fill:${t.ink} !important; color:${t.ink} !important; font-family:${t.font} !important`],
    ['.edgeLabel rect, .labelBkg', `fill:${t.paper} !important; background:${t.paper} !important`],
    ['small', `color:${t.inkMuted} !important; fill:${t.inkMuted} !important`],
  ];
  // EVERY comma-separated part gets the prefix, not just the first.
  // `#id a, b, c` scopes only `a` — `b` and `c` stay global, which is how a
  // rule meant for diagram labels restyled the application's brand, nav and
  // sidebar the moment a diagram opened. The bug survived one fix because
  // the string LOOKED prefixed.
  const scope = (selectorList) => selectorList
    .split(',')
    .map((part) => `#${DIAGRAM_ID} ${part.trim()}`)
    .join(', ');
  const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
  style.textContent = rules
    .map(([sel, decl]) => `${sel ? scope(sel) : `#${DIAGRAM_ID}`}{${decl}}`)
    .join('\n');
  svgEl.prepend(style);
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
  const name = { published: 'cloud', surveyed: 'bar-chart-2', new: 'sparkles' }[kind];
  const title = kind === 'published' ? 'Published to Egeria'
    : kind === 'surveyed' ? `Surveyed ${ago(p.last_surveyed_at)}`
    : 'Registered, not yet surveyed';
  const cls = kind === 'published' ? 'text-state-ok-on-dark' : 'text-chrome-muted';
  return icon(name, { size: 14, cls, title });
}

/**
 * The glyph for a disposition — ONE map, read by both the row mark and the
 * facet chip.
 *
 * That shared map is the whole key mechanism: the chips at the top of the
 * list already pair a glyph with a word (`◎ investigating 6`), so as long as
 * a row's mark is the SAME glyph its chip uses, the filter row IS the
 * legend. No popover to find, no second thing to keep in sync.
 *
 * `undecided` deliberately has none — a mark on the default state is noise
 * on 45 of 59 rows, and its chip carries the word anyway.
 */
const DISPOSITION_ICON = {
  tracking: 'eye',
  investigating: 'microscope',
  recommended: 'thumbs-up-check',
  using: 'check-circle-2',
  abandoned: 'archive',
  ignored: 'ban',
};

function dispositionMark(p) {
  const name = DISPOSITION_ICON[p.disposition];
  if (!name) return '';
  return icon(name, { size: 14, cls: 'text-accent-on-dark', title: p.disposition });
}

/** The compact key — all three mark families in one place.
 *
 *  A backstop for the first run, not the primary mechanism: the disposition
 *  chips are already a legend, the lifecycle icons are metaphors that read
 *  without one, and every mark carries a `title`. Three families on one
 *  dense row is exactly where hover text earns its place.
 */
function markKeyHtml() {
  const row = (ic, label, note) => `<div class="flex items-baseline gap-[6px]">
    <span class="w-[16px] text-chrome-muted">${icon(ic, { size: 13 })}</span>
    <span class="text-chrome-ink">${esc(label)}</span>
    <span class="text-chrome-muted">${esc(note)}</span></div>`;
  return `<div class="mb-s3 rounded-sm border border-chrome-line p-s2 text-caps">
    <div class="mb-[4px] uppercase tracking-caps text-chrome-muted">Lifecycle</div>
    ${row('sparkles', 'new', 'registered, not surveyed')}
    ${row('bar-chart-2', 'surveyed', 'has survey results')}
    ${row('cloud', 'published', 'in the Egeria catalog')}
    <div class="mb-[4px] mt-s2 uppercase tracking-caps text-chrome-muted">Disposition</div>
    ${Object.entries(DISPOSITION_ICON).map(([d, ic]) => row(ic, d, '')).join('')}
    <div class="mt-[3px] text-chrome-muted">undecided has no mark</div>
    <div class="mb-[4px] mt-s2 uppercase tracking-caps text-chrome-muted">Your view</div>
    ${row('eye-off', 'hidden', 'still registered — “Show hidden” brings it back')}
  </div>`;
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
    <div class="mb-s2 flex items-center gap-[5px] text-chip">
      ${types.map((t) => `<button data-type="${t.id}" class="${chip(state.resourceType === t.id).replace('rounded-pill', 'rounded-sm')}">${t.label}</button>`).join('')}
      <button data-act="mark-key" title="What the marks in this list mean"
        aria-label="What the marks in this list mean"
        class="ml-auto cursor-pointer bg-transparent text-chrome-muted hover:text-chrome-ink"
        >${icon('circle-help', { size: 14 })}</button>
    </div>
    ${state.showMarkKey ? markKeyHtml() : ''}

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

    <div class="mb-[3px] text-caps uppercase tracking-caps text-chrome-muted"
      title="The current UI counts these over the investigation's working set instead; /next counts every registered repo, so the two do not match">
      Disposition · all registered repos
    </div>
    <div class="mb-s2 flex flex-wrap gap-[5px] text-caps">
      <button data-facet="all" class="${chip(state.dispositionFacet === 'all')}">all</button>
      ${present.map((d) => `<button data-facet="${esc(d)}" class="${chip(state.dispositionFacet === d)}"
        >${DISPOSITION_ICON[d] ? icon(DISPOSITION_ICON[d], { size: 12 }) : ''} ${esc(d)}
        <span class="tnum">${counts[d]}</span></button>`).join('')}
      ${absent.length && state.showEmptyFacets
        ? absent.map((d) => `<button data-facet="${esc(d)}" class="${chip(state.dispositionFacet === d)} border-dashed"
            >${DISPOSITION_ICON[d] ? icon(DISPOSITION_ICON[d], { size: 12 }) : ''} ${esc(d)}
            <span class="tnum">0</span></button>`).join('')
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

    ${state.workLists.length ? `
      <div class="mb-[7px] font-heading uppercase tracking-caps text-caps text-chrome-muted">
        Work lists · <span class="tnum">${state.workLists.length}</span>
      </div>
      <div class="mb-s4 flex flex-col gap-[1px]">
        ${state.workLists.map((w) => `<button data-worklist="${esc(w.slug)}"
          class="cursor-pointer truncate bg-transparent px-2 py-[5px] text-left ${
            w.slug === state.workListSlug
              ? 'border-l-2 border-accent bg-chrome-surface text-chrome-ink'
              : 'border-l-2 border-transparent text-chrome-ink hover:bg-chrome-surface'}"
          >${esc(w.display_name)} <span class="tnum text-chrome-muted">${w.member_count}</span>${
            w.egeria_guid ? ` ${icon('cloud', { size: 12, cls: 'text-state-ok-on-dark', title: 'Published to Egeria' })}` : ''}</button>`).join('')}
      </div>` : ''}

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
          ${p.working_set_hidden
            ? icon('eye-off', { size: 13, cls: 'text-chrome-muted', title: 'Hidden from your list — a view preference, not a verdict' })
            : ''}
          ${p.github_url ? `<a href="${esc(p.github_url)}" target="_blank" rel="noopener noreferrer"
            title="Open ${esc(p.display_name || p.slug)} on GitHub"
            class="shrink-0 text-chrome-muted hover:text-accent-on-dark"
            >${icon('external-link', { size: 13 })}</a>` : ''}
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
      <button data-act="sel-worklist"
        title="Save the selected resources as a work list you can run, compare and narrow"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-accent-on-dark">save as work list</button>
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
  el.querySelectorAll('button[data-worklist]').forEach((b) => b.addEventListener('click', () => {
    state.workListSlug = b.dataset.worklist;
    renderSidebar();
    loadPane();
  }));
  el.querySelectorAll('button[data-slug]').forEach((b) => b.addEventListener('click', () => {
    // Leaving the matrix is remembered, so the way back is one click rather
    // than a hunt. Losing a 12x27 grid to a stray click on a repo, with no
    // visible route back, is what "I somehow got off the matrix view and
    // don't know how to get back" was.
    if (state.workListSlug) state.lastWorkListSlug = state.workListSlug;
    state.workListSlug = null;
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
    'mark-key': () => { state.showMarkKey = !state.showMarkKey; renderSidebar(); },
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
    'sel-worklist': () => saveSelectionAsWorkList(),
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

/** Turn the sidebar's current selection into a work list.
 *
 *  This is the hinge of the slice: a selection is ephemeral and a work list
 *  is the thing you can run across, compare, narrow and publish. */
async function saveSelectionAsWorkList() {
  const slugs = [...state.selected];
  if (!slugs.length) return;
  const name = window.prompt(
    `Name for a work list of ${slugs.length} resource(s):`,
    state.investigation ? `${state.investigation} candidates` : 'Candidates');
  if (name === null) return;
  sidebarNote('Saving…');
  try {
    const wl = await saveAsWorkList(name.trim() || 'Candidates', slugs, {
      investigation: state.investigation,
      rationale: 'selected in the sidebar',
    });
    state.workLists = await listWorkLists();
    state.workListSlug = wl.slug;
    state.selectMode = false;
    state.selected.clear();
    renderSidebar();
    await loadPane();
  } catch (err) {
    sidebarNote(`<span class="text-accent-on-dark">Not saved: ${esc(err.message)}</span>`);
  }
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
      ${state.chat.length ? `<span class="ml-auto flex items-center gap-s2">
        <button data-act="copy-transcript" title="Copy the whole transcript as markdown, with each answer's source line"
          class="cursor-pointer bg-transparent text-caps text-chrome-muted hover:text-chrome-ink"
          >${icon('copy', { size: 13 })} transcript</button>
        <button data-act="clear-chat"
          class="cursor-pointer bg-transparent text-caps text-chrome-muted underline hover:text-chrome-ink"
          >clear</button>
      </span>` : ''}
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
  $('rail').querySelector('[data-act="copy-transcript"]')?.addEventListener('click', (e) =>
    copyAsEvidence(state.chat.map(turnAsMarkdown).join('\n\n---\n\n'), e.currentTarget));
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

/** Mermaid source fenced inside an answer, if there is any.
 *
 *  Several analyses carry their diagram source as text (architecture_recovery
 *  writes its Mermaid into the answer), so this is how a topology answer
 *  reaches the pane without a new endpoint. */
function extractMermaid(text) {
  const m = /```mermaid\s*\n([\s\S]*?)```/.exec(String(text || ''));
  return m ? m[1].trim() : null;
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
          ${(() => {
            const form = answerForm(t);
            const bits = [];
            if (form === 'chart' || form === 'diagram') {
              // A diagram cannot live in a 290px rail. The rail says what it
              // is and promotes; the pane is where it becomes readable.
              bits.push(`<button data-promote="${i}"
                class="cursor-pointer rounded-sm border border-accent bg-transparent px-[10px] py-[4px]
                       text-chip text-accent-on-dark">${icon('maximize-2', { size: 13 })}
                Open ${form === 'chart' ? 'chart' : 'diagram'} in pane</button>`);
            }
            if (t.candidates && t.candidates.length) {
              bits.push(`<button data-candidates="${i}"
                class="cursor-pointer rounded-sm border border-chrome-line bg-transparent px-[10px] py-[4px]
                       text-chip text-chrome-ink">Open as candidates
                (<span class="tnum">${t.candidates.length}</span>)</button>`);
            }
            return bits.length ? `<div class="mt-s3 flex flex-wrap gap-s2">${bits.join('')}</div>` : '';
          })()}
          <div class="mt-[10px] border-t border-chrome-line-soft pt-[9px] text-caps text-chrome-muted">
            ${esc(t.source)}${t.intent ? ` · intent ${esc(t.intent)}` : ''}${t.cached ? ' · cached' : ''}
          </div>
          ${t.queryHash ? feedbackHtml(t, i) : ''}
          <div class="mt-s2">
            <button data-copy-turn="${i}" title="Copy this answer and its source line as markdown"
              class="cursor-pointer bg-transparent text-caps text-chrome-muted opacity-100
                     hover:text-chrome-ink focus-visible:text-chrome-ink"
              >${icon('copy', { size: 13 })} copy as evidence</button>
          </div>
        </div>` : ''}
    </div>`;
  }).join('');

  log.querySelectorAll('[data-vote]').forEach((b) => b.addEventListener('click', () => {
    vote(Number(b.dataset.turn), Number(b.dataset.vote));
  }));
  log.querySelectorAll('[data-candidates]').forEach((b) => b.addEventListener('click', () => {
    showCandidates(Number(b.dataset.candidates));
  }));
  log.querySelectorAll('[data-promote]').forEach((b) => b.addEventListener('click', () => {
    promoteToPane(state.chat[Number(b.dataset.promote)]);
  }));
  log.querySelectorAll('[data-copy-turn]').forEach((b) => b.addEventListener('click', () =>
    copyAsEvidence(turnAsMarkdown(state.chat[Number(b.dataset.copyTurn)]), b)));
  log.scrollTop = log.scrollHeight;
}

/** Three states, not a thumb pair.
 *
 *  The endpoint records +1 / 0 / -1 as three explicit outcomes, and "partly
 *  right" is the one that actually distinguishes a routing problem from a
 *  content problem. Folding it into either neighbour loses the signal the
 *  vote exists to collect. Words rather than emoji, since emoji is not this
 *  UI's icon system. */
const VOTES = [
  [1, 'thumbs-up', 'Helpful', 'text-state-ok-on-dark'],
  // "Partly right" is the value that separates a routing problem from a
  // content problem. It is a real third state, not a midpoint.
  [0, 'minus', 'Partly right — the right idea, incomplete or partly off', 'text-state-warn-on-dark'],
  [-1, 'thumbs-down', 'Not helpful', 'text-state-warn-on-dark'],
];

function feedbackHtml(turn, i) {
  if (turn.voted !== undefined) {
    const said = { 1: 'Marked helpful.', 0: 'Marked partly right.', '-1': 'Marked not helpful.' };
    return `<div class="mt-s2 text-caps text-chrome-muted">${esc(said[String(turn.voted)])}</div>`;
  }
  if (turn.voteError) {
    return `<div class="mt-s2 text-caps text-state-warn-on-dark">Vote not recorded: ${esc(turn.voteError)}</div>`;
  }
  // Thumbs, not the words `yes / partly / no`. Substituting words for a
  // conventional pictogram turned a one-glance control into reading; the
  // objection to emoji was platform variance and non-recolourability, which
  // a Lucide glyph inheriting currentColor does not have.
  return `<div class="mt-s2 flex flex-wrap items-center gap-s3 text-caps">
    <span class="text-chrome-muted">Was this right?</span>
    ${VOTES.map(([v, ic, title, cls]) => `<button data-turn="${i}" data-vote="${v}"
      title="${esc(title)}" aria-label="${esc(title)}"
      class="cursor-pointer bg-transparent text-chrome-muted hover:${cls}"
      >${icon(ic, { size: 16 })}</button>`).join('')}
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
    // The chart the server chose to attach (statistical/health/comparison
    // intents produce one). A Plotly figure, and far too wide for the rail.
    turn.chart = body.chart || null;
    turn.mermaid = extractMermaid(turn.answer);
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
    btn.innerHTML = `Chat ${icon(open ? 'panel-right-close' : 'panel-right-open', { size: 14 })}`;
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
  if (state.workListSlug) p.set('worklist', state.workListSlug);
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
    if (p.get('worklist')) state.workListSlug = p.get('worklist');
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

/** The dated verdict trail for one repo. */
async function renderDispositionHistory(githubUrl) {
  const el = $('disposition-history');
  if (!el) return;
  let rows;
  try {
    rows = await getDispositionHistory(githubUrl);
  } catch (err) {
    el.innerHTML = `<span class="text-state-warn">History could not be read: ${esc(err.message)}</span>`;
    return;
  }
  if (!Array.isArray(rows) || !rows.length) {
    // Distinct from "no history was readable" above. Nothing has been set,
    // which is itself the answer.
    el.textContent = 'No disposition has been recorded for this repo.';
    return;
  }
  el.innerHTML = `<div class="mb-[3px] uppercase tracking-caps text-caps">History</div>`
    + rows.map((r) => {
      // The field is `decided_at` — verified against the endpoint, not
      // guessed. `decided_by` is often empty; it is shown only when set,
      // rather than rendering an empty attribution.
      const when = r.decided_at || '';
      const rel = ago(when);
      return `<div><span class="text-ink">${esc(r.disposition || '—')}</span>
        ${rel ? ` · <span class="tnum">${esc(rel)}</span>` : ''}
        ${when ? ` <span class="tnum">(${esc(String(when).slice(0, 10))})</span>` : ''}
        ${r.decided_by ? ` · ${esc(r.decided_by)}` : ''}
        ${r.reason ? ` · ${esc(r.reason)}` : ''}</div>`;
    }).join('');
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
      </div>
      <div id="disposition-history" class="mt-s2 text-provenance text-ink-muted">Loading history…</div>`;
    // The HISTORY, alongside the picker. It exists in the current UI and
    // nowhere in /next, and it is the only place the SEQUENCE of verdicts is
    // visible — which is the rationale trail, not decoration. A single
    // current value cannot say that something was abandoned and then picked
    // back up.
    renderDispositionHistory(p.github_url);
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
      if (t.id === state.subTab) {
        return `<span class="border-b border-accent pb-[2px] text-ink">${t.label}</span>`;
      }
      if (t.id === 'questions') {
        return `<button data-subtab="${t.id}" class="cursor-pointer bg-transparent text-ink hover:text-accent-ink">${t.label}</button>`;
      }
      return `<button data-deferred="${t.id}" title="${esc(t.does)} — not built in /next"
        class="cursor-pointer bg-transparent text-ink-muted"
        style="border-bottom:1px dashed currentColor;padding-bottom:1px">${t.label}</button>`;
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
/** A link into the current UI, on the same resource.
 *
 *  `index.html` gained a `?resource=` reader for this — it had no deep link
 *  of any kind, so "links out preserving the resource" was not satisfiable
 *  without adding one. Additive: an unrecognised slug selects nothing and
 *  the app starts exactly as before. */
function oldUiHref() {
  return state.selectedSlug
    ? `/?resource=${encodeURIComponent(state.selectedSlug)}`
    : '/';
}

function deferredPaneHtml(tab) {
  return `${subTabsHtml()}
    <h3 class="m-0 font-heading text-name font-normal">${esc(tab.label)} · not built in /next</h3>
    <div class="my-s3 h-px bg-rule"></div>
    <p class="max-w-[70ch] text-answer text-ink">${esc(tab.does)}.</p>
    <p class="max-w-[70ch] text-answer text-ink">
      <a href="${esc(oldUiHref())}" class="text-accent-ink underline"
        >Open ${state.selectedSlug ? `<span class="font-mono">${esc(state.selectedSlug)}</span>` : 'this'}
        in the current UI</a> ${icon('external-link', { size: 13, cls: 'text-accent-ink' })}
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

  const items = LEGEND.filter(([k]) => counts[k]).map(([k, label]) => `
    <span class="inline-flex items-baseline gap-[5px]">
      <span class="${tone(k, 'paper')}">${GLYPH[k]}</span>
      <span class="text-ink">${esc(label)}</span>
      <span class="tnum text-ink">${counts[k]}</span>
    </span>`);

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

  // The perspective row is re-rendered HERE, once, for every branch below.
  //
  // It used to be re-rendered inside individual branches, and the work-list
  // branch returned before reaching one — so holding a perspective updated
  // the state and never repainted the chip. Reported as "sometimes the
  // perspective stays highlighted and sometimes not": it depended entirely on
  // which pane you were in. One call site is the fix; a branch that forgets
  // is the bug.
  renderPerspectiveRow();
  renderWorkListNav();

  // A work list is a view of a SET, so it replaces the single-resource pane
  // rather than sitting inside it. Everything else in /next reads one
  // resource at a time; this is the one surface that does not.
  if (state.workListIndex && !state.workListSlug) {
    el.innerHTML = workListIndexHtml();
    bindSubTabs();
    el.querySelectorAll('[data-open-wl]').forEach((b) => b.addEventListener('click', () => {
      state.workListSlug = b.dataset.openWl;
      state.workListIndex = false;
      writeUrl(); renderSidebar(); loadPane();
    }));
    writeUrl();
    return;
  }

  if (state.workListSlug) {
    state.workListIndex = false;
    try {
      await openWorkList({
        el,
        stage: state.stage,
        perspectives: state.activePerspectives,
        projects: state.projects,
        analyses: state.analyses || [],
        onExit: () => {
          state.lastWorkListSlug = state.workListSlug;
          state.workListSlug = null;
          writeUrl(); renderSidebar(); loadPane();
        },
      }, state.workListSlug);
    } catch (err) {
      // A pane that throws on the way in leaves whatever was there before,
      // which reads as "clicking did nothing" — reported as both "the batch
      // could not be enqueued" and "switching the stage changed nothing"
      // when the server was restarted underneath the page. Say it instead.
      el.innerHTML = `
        <h3 class="m-0 font-heading text-name font-normal">This view could not be loaded</h3>
        <div class="my-s3 h-px bg-rule"></div>
        <p class="max-w-[70ch] text-answer text-ink">${esc(err.message)}</p>
        <p class="max-w-[70ch] text-caveat text-ink-muted">
          A network-level failure here usually means the server restarted. What
          you were looking at is unchanged — nothing was written.
        </p>
        <button data-act="retry-pane"
          class="mt-s2 cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px]
                 text-caveat text-accent-ink">Try again</button>`;
      el.querySelector('[data-act="retry-pane"]').addEventListener('click', () => loadPane());
    }
    writeUrl();
    return;
  }

  if (state.subTab !== 'questions') {
    const tab = SUB_TABS.find((t) => t.id === state.subTab)
      || { id: state.subTab, label: state.subTab, does: 'Not a pane /next knows about' };
    el.innerHTML = deferredPaneHtml(tab);
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

  // Understanding is CHARTS.
  //
  // It was marked "not built" on the strength of having zero rows in the
  // analysis catalog and the activity log — both true, and both irrelevant
  // to the seven Plotly figures `/api/stats/{slug}/charts/*` already serves
  // for a repo. The catalog is empty; the data is not. Since the fix round
  // puts "anything over time" in the pane as a chart, this is where charts
  // live, and leaving the marker up would have been marking a surface as
  // absent while its data sat one GET away.
  if (state.stage === 'understanding') {
    await loadChartsPane();
    renderPerspectiveRow();
    return;
  }

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
  // ALL of them, wrapping — not just the first. Seeing that a question
  // carries four perspectives is how you learn the axis barely filters, and
  // the first-only version hid exactly that.
  const perspectives = entry.perspectives || [];
  const running = state.runsInFlight.get(entry.question);
  const st = running ? 'running'
    : env === 'loading' ? 'loading'
    : env && env.__error ? 'error'
    : rowState(entry, env);

  const glyph = GLYPH[st] || '·';
  // Glyph AND colour. The glyph survives printing, greyscale and colour
  // blindness and is what the legend keys; the hue is what makes a column of
  // rows scannable for the exceptions. Neither is doing the job alone.
  //
  // The TITLE stays `ink` in every state. Colouring the state is not the same
  // as fading the question, and an earlier version put unrun titles in
  // `ink-muted`, which is de-emphasis by fading text toward the ground.
  const glyphColor = tone(st, 'paper');

  const perspectiveTags = perspectives.length
    ? `<span class="ml-auto flex flex-wrap justify-end gap-[4px]">${perspectives.map((pv) =>
        `<span class="rounded-pill border border-rule-strong px-2 py-[1px] text-caps text-ink-muted"
          >${esc(pv)}</span>`).join('')}</span>`
    : '';
  const tag = st === 'no-surveyor'
    ? `<span class="ml-auto flex flex-wrap justify-end gap-[4px]">
        <span class="rounded-pill border border-dashed border-state-gap px-2 py-[1px] text-caps text-state-gap">no surveyor yet</span>
        ${perspectives.map((pv) => `<span class="rounded-pill border border-rule-strong px-2 py-[1px] text-caps text-ink-muted"
          >${esc(pv)}</span>`).join('')}
      </span>`
    : perspectiveTags;

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
  // A relationship answer has a diagram behind it. It cannot be read in a
  // 290px rail, so the row promotes it straight into the pane.
  if (lines.mermaid) {
    actions.push(`<button data-diagram="${i}" class="cursor-pointer bg-transparent text-accent-ink underline">diagram</button>`);
  }
  if (st !== 'loading') {
    actions.push(`<button data-copy="${i}" title="Copy this answer and its provenance as markdown"
      class="cursor-pointer bg-transparent text-accent-ink underline">copy as evidence</button>`);
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
  el.querySelector(`[data-diagram="${i}"]`)?.addEventListener('click', () => showDiagram(entry));
  el.querySelector(`[data-copy="${i}"]`)?.addEventListener('click', (e) =>
    copyAsEvidence(rowAsMarkdown(entry, i), e.currentTarget));
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
  // A long string is SUMMARISED, never dumped. `architecture_diagram`'s value
  // carries 9,384 characters of Mermaid source, and rendering it as a scalar
  // filled the rail with raw diagram code — which reads as the app having
  // broken, not as a measure. The rail is 290px; nothing that wide belongs in
  // it, and the diagram already has its own action.
  if (shown.length > 120) {
    const isDiagram = /^(mermaid|diagram|svg)$/i.test(key);
    return `<div>${label} <span class="text-chrome-muted">${
      isDiagram ? 'diagram source' : 'text'} · <span class="tnum">${shown.length}</span> characters${
      isDiagram ? ' — use “Open diagram in pane”' : ''}</span></div>`;
  }
  return `<div>${label} <span class="tnum">${tnum(esc(shown))}</span></div>`;
}

/* ────────────────────────────────────────────────────────────────────────
 * Copy as evidence
 *
 * Labelled "Copy as evidence", not "Copy": the label says what the artifact
 * is for. These answers get pasted into issues, Dr.Egeria plans and review
 * documents — all markdown — and an answer pasted WITHOUT its source line
 * loses the thing this whole redesign is about. So the provenance is not
 * optional and is not a separate button.
 * ──────────────────────────────────────────────────────────────────────── */

/** Put text on the clipboard, and say so on the button that asked. */
async function copyAsEvidence(markdown, btn) {
  const done = (msg, ok = true) => {
    if (!btn) return;
    const prev = btn.innerHTML;
    btn.innerHTML = `<span class="text-caps ${ok ? '' : 'text-state-warn'}">${esc(msg)}</span>`;
    setTimeout(() => { btn.innerHTML = prev; }, 1600);
  };
  try {
    await navigator.clipboard.writeText(markdown);
    done('copied');
  } catch (err) {
    // A clipboard write can be refused (no permission, not a user gesture,
    // an insecure origin). Saying nothing would leave someone pasting a
    // stale buffer into an issue and not knowing.
    done('could not copy', false);
    console.warn('clipboard write refused:', err);
  }
}

/** One question row, as markdown with its provenance. */
function rowAsMarkdown(entry, i) {
  const env = state.answers.get(entry.question);
  const st = rowState(entry, env);
  const lines = (env && env !== 'loading' && !env.__error)
    ? readEnvelope(entry, env) : null;

  const out = [`**${entry.question}**`, ''];

  // The answer, as text. `lines.answer` is HTML by the time it reaches a row,
  // so it is rebuilt from the facts here rather than stripped of tags — a
  // regex over markup is how a stray `<` ends up in someone's issue.
  const said = [];
  for (const f of ((env && env.facts) || []).filter((x) => x.is_known)) {
    if (f.headline) said.push(f.headline);
    else if (prose(f)) said.push(f.value?.verdict ? `${cap(String(f.value.verdict))} — ${prose(f)}` : prose(f));
    else if (scalarMeasures(f.value)) said.push(scalarMeasures(f.value));
  }
  if (said.length) out.push(said.join(' '), '');
  else out.push(`_${(env && env.blocked_reason) || STATE_SENTENCE[st] || 'No answer recorded.'}_`, '');

  if (lines && lines.caveat) {
    // The caveat as a blockquote — it is the part a reader most needs to
    // carry across, and a quote survives being pasted into a thread.
    out.push(...lines.caveat.split('\n').map((l) => `> ${l}`), '');
  }

  const bits = [state.selectedSlug];
  const sources = (lines && lines.sources.length ? lines.sources : entry.analysis_ids) || [];
  if (sources.length) bits.push(sources.join(', '));
  if (lines && lines.lastRun) bits.push(`run ${String(lines.lastRun).slice(0, 10)}`);
  else if (lines && lines.runTimeUnrecorded) bits.push('run time not recorded');
  else bits.push('never run');
  bits.push(env && env.answerable
    ? 'answered from survey metadata, no retrieval'
    : `state: ${STATE_LABEL[st] || st}`);
  out.push(`— ${bits.filter(Boolean).join(' · ')}`);

  return out.join('\n');
}

/** One chat turn, as markdown with its source line. */
function turnAsMarkdown(t) {
  const out = [`**${t.question}**`, ''];
  out.push(t.answer || `_${t.error || 'No answer.'}_`, '');
  const bits = [t.slug, t.source].filter(Boolean);
  if (t.intent) bits.push(`intent ${t.intent}`);
  out.push(`— ${bits.join(' · ')}`);
  return out.join('\n');
}

const STATE_LABEL = {
  answered: 'answered', automatic: 'automatic', unrun: 'not run',
  human: 'needs human input', 'no-surveyor': 'no surveyor exists yet',
  unclassified: 'unclassified',
};
const STATE_SENTENCE = {
  unrun: 'Not run yet.',
  human: 'Answered by a person, not by a survey.',
  'no-surveyor': 'No surveyor exists for this question.',
  unclassified: 'The catalog does not state how this would be answered.',
};

/** Promote a question's diagram into the content pane. */
function showDiagram(entry) {
  const env = state.answers.get(entry.question);
  if (!env || env === 'loading' || env.__error) return;
  const found = factMermaid(env);
  if (!found) return;
  promoteToPane({
    question: entry.question,
    mermaid: found.source,
    source: `${found.analysisId}`
      + (found.lastRun ? ` · run ${ago(found.lastRun)}` : ' · run time not recorded')
      + ' · rendered by Kroki, no retrieval',
  });
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
      ${factMermaid(env) ? `<button data-act="evidence-diagram"
        class="mb-s2 w-full cursor-pointer rounded-sm border border-accent bg-transparent px-[10px] py-[4px]
               text-chip text-accent-on-dark">${icon('maximize-2', { size: 13 })} Open diagram in pane</button>` : ''}
      <div class="mt-[10px] border-t border-chrome-line-soft pt-[9px] text-caps text-chrome-muted">
        Answered from <span class="tnum">${env.known_count ?? 0}</span> of
        <span class="tnum">${(env.known_count ?? 0) + (env.unknown_count ?? 0)}</span> measurements ·
        no retrieval
      </div>
    </div>`;
  out.querySelector('[data-act="evidence-diagram"]')
    ?.addEventListener('click', () => showDiagram(entry));
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
  await loadIcons();
  applyWidths();
  initSeams();
  readUrl();
  renderIntentNav();
  renderRail();
  renderTopBar();

  // Everything below is independent; one failing must not take the frame
  // down with it. `allSettled`, and each consumer handles its own absence.
  state.investigation = currentInvestigation();

  const [me, projects, perspectives, activity, rfas, groups, investigations,
         workLists, analyses] =
    await Promise.allSettled([
      getMe(),
      // The FULL list — every disposition, hidden included — because the
      // sidebar filters client-side and the default server filters would
      // make the `ignored`, `abandoned` and hidden facets permanently empty.
      listProjects({ includeIgnored: true, includeHidden: true }),
      listPerspectives(), listActivity(ACTIVITY_LIMIT), listRfas(),
      listGroups(), listInvestigations(), listWorkLists(), listAnalyses('repo'),
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
  if (workLists.status === 'fulfilled') state.workLists = workLists.value || [];
  if (analyses.status === 'fulfilled') state.analyses = analyses.value || [];
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
