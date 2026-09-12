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
import { listWorkLists, openWorkList, saveAsWorkList, openDialog, closeCellDetail, CELL }
  from '/static/next/worklist.js';
import { ago, whenMs } from '/static/next/format.js';
import {
  ApiError,
  VALID_DISPOSITIONS,
  addInvestigationMember,
  ask,
  CHART_MEASURE,
  REPO_CHARTS,
  getAnswer,
  getChart,
  getDispositionHistory,
  enqueueBatch,
  getAnalysisTrend,
  getDeclaredVsReceived,
  getResourceRuns,
  getSurveyCandidates,
  getSurveyDashboards,
  runSurveyDefinition,
  getMe,
  getBulkFacts,
  getMemberChildren,
  getMembers,
  promoteMembers,
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
  getContext,
  getJournal,
  questionKey,
  writeJournal,
  saveEnrichmentField,
  saveQuestionAnswer,
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
  // NAMED FOR WHAT IT IS. Calling it "Search" inherits the current UI's label
  // and teaches the wrong noun on first contact: it is not a search of the
  // selected resource, it is how candidate repos are found and imported.
  { id: 'search', label: 'Find repos', does: 'Repo discovery — find and import candidate repos' },
  { id: 'survey', label: 'Survey', does: 'Survey definitions, their steps, and running them', built: true },
  { id: 'dashboard', label: 'Dashboard', does: 'Survey results — health, maturity, community, charts', built: true },
  { id: 'questions', label: 'Questions', does: 'The question checklist' },
  { id: 'disposition', label: 'Disposition', does: 'Set a verdict on this resource, its history, and the journal', built: true },
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
  partial: '◐',
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
  partial:       { paper: 'text-accent-ink',  chrome: 'text-accent-on-dark' },
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
    if (f.last_run_at && (!lines.lastRun || whenMs(f.last_run_at) > whenMs(lines.lastRun))) lines.lastRun = f.last_run_at;
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
  // Joined on ' · ', not ' '. Six analyses' sentences run together read as
  // one broken sentence — "all 3 checks pass one contributor writes most of
  // the code" — and a reader cannot tell where one claim ends. The separator
  // makes the boundaries visible without deciding how the claims combine,
  // which is the judgement still owed (Dashboard Round Three).
  lines.answer = sentences.join(' · ');

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

/** The app's own text-size control: 100 / 112 / 125%.
 *
 * Wired once, and persisted — a size someone chose because they could not
 * read the pane is not a per-session preference. It is stored globally rather
 * than per work list, deliberately: unlike the digest toggle, this is a fact
 * about the reader, not about a list.
 */
let textSizeWired = false;
function wireTextSize() {
  if (textSizeWired) return;
  textSizeWired = true;
  const host = $('textsize');
  if (!host) return;
  const apply = (v) => {
    document.documentElement.setAttribute('data-textsize', String(v));
    host.querySelectorAll('[data-textsize]').forEach((b) =>
      b.setAttribute('aria-pressed', b.dataset.textsize === String(v) ? 'true' : 'false'));
    LS.set('re-next.textSize', String(v));
  };
  host.querySelectorAll('[data-textsize]').forEach((b) =>
    b.addEventListener('click', () => apply(b.dataset.textsize)));
  apply(LS.get('re-next.textSize', '100'));
}

/** Below 780px the sidebar is a drawer, and this is the way in.
 *
 * Wired ONCE. This sits beside a function that re-renders, and attaching per
 * render stacked a second listener on the same button: the class was toggled
 * on and then straight back off, so the drawer never appeared and nothing
 * looked broken enough to suspect it.
 */
let sidebarWired = false;
function wireSidebarDrawer() {
  if (sidebarWired) return;
  sidebarWired = true;
  const btn = $('sidebar-toggle');
  if (!btn) return;
  const set = (open) => {
    document.body.classList.toggle('sidebar-open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    set(!document.body.classList.contains('sidebar-open'));
  });
  // A tap outside closes it. At this width the drawer covers most of the
  // content, so leaving it open is never what the next tap meant.
  document.addEventListener('click', (e) => {
    if (!document.body.classList.contains('sidebar-open')) return;
    if (!e.target.closest('.pane-sidebar')) set(false);
  });
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

  $('chat-toggle').addEventListener('click', () => {
    const nowOpen = !$('app-grid').classList.contains('rail-closed');
    setRailOpen(!nowOpen, { persist: !shellIsNarrow() });
  });
  setRailOpen(railIsOpen() && !shellIsNarrow(), { persist: false });

  wireSidebarDrawer();
  wireTextSize();

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
/** Axis labels, a stated zero, and a title that names the measurement.
 *
 * Three faults compounded here: an unhighlighted selector meant you did not
 * know WHICH chart you were looking at; not knowing that, an unlabelled
 * vertical scale had no referent; and a bare date axis left nothing to anchor
 * it to. The selector is fixed above, which half-fixes these by context —
 * this states them outright.
 *
 * **If the axis does not start at zero, it says so on the axis.** A truncated
 * scale that does not admit it is the oldest chart lie there is.
 */
function chartAxes(entry) {
  const layout = { ...(entry.fig.layout || {}) };
  const [measure, range] = CHART_MEASURE[entry.kind] || [entry.label.toLowerCase(), ''];
  const span = entry.first && entry.last && entry.first !== entry.last
    ? `${entry.first} – ${entry.last}` : (entry.last || '');
  layout.title = {
    text: `${entry.label} — ${measure}${range ? `, ${range}` : ''}`,
    subtitle: undefined,
  };
  // Radar has no cartesian axes to label; everything else gets both.
  if ((entry.fig.data || []).some((t) => t.type === 'scatterpolar')) return layout;

  const ys = (entry.fig.data || []).flatMap((t) => (t.y || []).filter((v) => typeof v === 'number'));
  const min = ys.length ? Math.min(...ys) : 0;
  const zeroed = min <= 0;
  layout.yaxis = {
    ...(layout.yaxis || {}),
    title: { text: `${measure}${range ? ` (${range})` : ''}${
      zeroed ? '' : ' — axis does not start at zero'}` },
    showticklabels: true,
    rangemode: zeroed ? 'tozero' : 'normal',
  };
  layout.xaxis = {
    ...(layout.xaxis || {}),
    title: { text: entry.timeAxis
      ? 'Measurement date — plotted to scale, so gaps are real'
      : (layout.xaxis?.title?.text || layout.xaxis?.title || '') },
    showticklabels: true,
  };
  layout.margin = { l: 70, r: 20, t: 54, b: 62, ...(layout.margin || {}) };
  return layout;
}

/** A REAL TIME AXIS, not evenly spaced points.
 *
 * Surveys run irregularly. Three measurements at 14, 68 and 88 days drawn
 * equidistant invent a steady cadence that never happened — and the shape of
 * the line is precisely what someone reads off it. Plotted to scale, a long
 * unmeasured gap reads as a gap rather than as a slow steady climb: the same
 * argument as the staleness rule, drawn instead of marked.
 *
 * The last point is labelled with its value, because that is the number
 * someone came for.
 */
function timeAxisData(entry) {
  const data = entry.fig.data || [];
  if (!entry.timeAxis) return data;
  return data.map((t, i) => {
    if (i > 0 || !(t.x || []).length) return t;
    const y = t.y || [];
    const last = y.length - 1;
    return {
      ...t,
      mode: 'lines+markers+text',
      text: y.map((v, j) => (j === last ? String(Math.round(v * 10) / 10) : '')),
      textposition: 'top left',
      marker: { ...(t.marker || {}), size: 7 },
    };
  });
}

/** Not every chart endpoint returns a Plotly figure.
 *
 * `survey_history` returns `{dates, total_files}` — raw series, no `data`
 * array — because the current UI builds that figure client-side. Everything
 * else returns `fig.to_json()`. Reading `fig.data` on it therefore found no
 * traces, and `/next` reported **"nothing recorded yet"** on every repository
 * in the corpus while the registry held ten points per repo: 6,107 → 6,423
 * files over a month on egeria-workspaces alone.
 *
 * That is the failure this project keeps hunting, in a new place: a fact about
 * the ENDPOINT rendered as a fact about the RESOURCE. And it hid in the one
 * state that looks like diligence — an honest-sounding empty.
 *
 * The endpoint is not changed, because the current UI depends on this shape;
 * the adapting happens here, where the assumption was.
 */
function asFigure(raw) {
  if (!raw || Array.isArray(raw.data)) return raw;
  if (Array.isArray(raw.dates) && Array.isArray(raw.total_files)) {
    return {
      data: [{
        type: 'scatter', mode: 'lines+markers',
        x: raw.dates, y: raw.total_files, name: 'Total files',
      }],
      layout: { xaxis: { title: 'Surveyed' }, yaxis: { title: 'Files' } },
    };
  }
  return raw;
}

/** Where a chart means something different from a number elsewhere, say so.
 *
 * The radar was cut from the Dashboard because `repository_health` composes
 * FOUR sub-scores on 0-100 while this plots FIVE different axes on 0-10 — two
 * models of one word, forty pixels apart. Cutting it there and leaving it here
 * did not resolve that; it moved the collision one pane away, where it is
 * harder to notice rather than absent.
 *
 * It stays, because on this pane it is not sitting beside its rival and the
 * series is real. It now says what it is not. The proper fix is the designer's
 * own: plot the four published sub-scores on their own scale, which needs an
 * endpoint that does not exist yet.
 */
const CHART_CAVEATS = {
  health: 'These five axes on a 0–10 scale are not the same composition as '
        + 'the Dashboard\'s repository_health score, which combines four '
        + 'sub-scores on 0–100. Two models of the same word: read them '
        + 'separately, and do not compare the numbers.',
};

/** Every date-shaped x-value in a figure, sorted. */
function allPointDates(traces) {
  const out = [];
  for (const t of traces || []) {
    for (const x of t.x || []) {
      const v = String(x);
      if (/^\d{4}-\d{2}-\d{2}/.test(v)) out.push(v.slice(0, 10));
    }
  }
  return out.sort();
}

/** Same threshold as the grid's, and the same placeholder caveat. */
function chartIsStale(dateStr) {
  const d = (Date.now() - Date.parse(dateStr)) / 86400000;
  return Number.isFinite(d) && d >= 7;
}

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
      const fig = asFigure(await getChart(slug, kind));
      // POINTS, NOT TRACES. `fig.data.length` counts series, so a trace
      // holding a single observation counted as a usable chart and drew one
      // dot — the flat-line lie in chart form, and the same mistake as a
      // sparkline of one point. Some repos here are at 2.
      const traces = Array.isArray(fig?.data) ? fig.data : [];
      const points = traces.reduce((n, t) => n + (
        (t.x || t.labels || t.r || t.values || []).length), 0);
      const dates = allPointDates(traces);
      return {
        kind, label, fig, traces: traces.length, points,
        first: dates[0] || '', last: dates[dates.length - 1] || '',
        // A date x-axis means the spacing can be honest; a categorical one
        // (languages, file types, committers) has no time to be true to.
        timeAxis: dates.length > 1 && dates.length === points,
        error: null,
      };
    } catch (err) {
      return { kind, label, fig: null, traces: 0, points: 0, last: '', error: err.message };
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
    if (!r.points) {
      return `<span title="The series exists and has nothing in it yet"
        class="rounded-sm border border-dashed border-rule-strong px-2 py-[3px] text-caveat text-ink-muted"
        >${esc(r.label)} · nothing recorded yet</span>`;
    }
    // ONE OBSERVATION IS NOT A TREND. Offered, because the value is real and
    // worth seeing — labelled, because a chart of it would imply a shape it
    // does not have.
    const one = r.points === 1;
    // SELECTION IS THE ONE THING THAT MUST NEVER BE INFERRED, and it gets the
    // treatment the stage tabs already use — accent ink plus an accent
    // underline — so the app speaks one visual language rather than two.
    // Without it you cannot tell WHICH chart you are looking at, which is what
    // made the unlabelled axes hard to notice underneath.
    return `<button data-chart="${r.kind}" aria-pressed="false"
      title="${r.points} observation(s)${r.last ? ` · latest ${r.last}` : ''}"
      class="wl-chartchip cursor-pointer border-0 bg-transparent px-2 py-[3px]
             text-caveat text-ink-muted hover:text-ink">${esc(r.label)}${
      one ? ' · first measurement'
          : `<span class="tnum text-ink-muted"> · ${r.points}</span>`}${
      r.last && chartIsStale(r.last)
        ? '<span class="wl-age-text"> </span>' : ''}</button>`;
  }).join('');

  const select = (kind) => {
    index.querySelectorAll('[data-chart]').forEach((o) =>
      o.setAttribute('aria-pressed', o.dataset.chart === kind ? 'true' : 'false'));
    drawChart(results.find((r) => r.kind === kind));
  };
  index.querySelectorAll('[data-chart]').forEach((b) =>
    b.addEventListener('click', () => select(b.dataset.chart)));

  const first = results.find((r) => r.points);
  if (first) {
    select(first.kind);
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
        <span class="tnum">${entry.points}</span> observation(s) in
        <span class="tnum">${entry.traces}</span> series${
        entry.last ? ` · latest ${esc(entry.last)}${
          chartIsStale(entry.last) ? ' — nothing newer has been recorded' : ''}` : ''} ·
        from the registry's recorded history · no retrieval</div>
      ${entry.points === 1 ? `<div class="mt-s1 text-caveat text-ink-muted">
        One observation. This is a value, not a trend — the shape of a chart
        with a single point is drawn by the axes, not by the data.</div>` : ''}
      ${CHART_CAVEATS[entry.kind]
        ? `<div class="mt-s1 max-w-[70ch] text-caveat text-accent-ink">${esc(CHART_CAVEATS[entry.kind])}</div>`
        : ''}`;
    await window.Plotly.newPlot($('chart-canvas'), timeAxisData(entry),
                                chartLayout(chartAxes(entry)),
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

/** Below the drawer breakpoint the rail must not open ITSELF.
 *
 * The stored preference is a wide-screen preference: someone who likes the
 * chat rail open on a laptop has not asked for a drawer covering the whole
 * screen on a phone. So a narrow shell starts closed regardless, and opening
 * it there is a deliberate tap that is not written back over the preference.
 */
function shellIsNarrow() {
  return window.matchMedia('(max-width: 780px)').matches;
}

function setRailOpen(open, { persist = true } = {}) {
  if (persist) LS.set('re-next.railOpen', open ? 'true' : 'false');
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
      <span class="font-mono text-provenance text-ink-muted">${esc(slug)}</span>
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
// `target` names the element to fill. Two places show the trail -- the
// header popover and the Disposition pane -- and they carried the same id
// until 2026-09-12; getElementById found the popover's (earlier in the
// DOM) once it had been opened, so the pane's trail never refreshed again
// and the no-URL message landed in the popover instead of the pane.
async function renderDispositionHistory(githubUrl, target = 'disposition-history') {
  const el = $(target);
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
      <div id="disposition-history-popover" class="mt-s2 text-provenance text-ink-muted">Loading history…</div>`;
    // The HISTORY, alongside the picker. It exists in the current UI and
    // nowhere in /next, and it is the only place the SEQUENCE of verdicts is
    // visible — which is the rationale trail, not decoration. A single
    // current value cannot say that something was abandoned and then picked
    // back up.
    renderDispositionHistory(p.github_url, 'disposition-history-popover');
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
      if (t.id === 'questions' || t.built) {
        return `<button data-subtab="${t.id}" class="cursor-pointer bg-transparent text-ink hover:text-accent-ink">${t.label}</button>`;
      }
      return `<button data-deferred="${t.id}" title="${esc(t.does)} — not built in /next"
        class="cursor-pointer bg-transparent text-ink-muted"
        style="border-bottom:1px dashed currentColor;padding-bottom:1px">${t.label}</button>`;
    }).join('')}
  </div>`;
}

/* The header no longer says "N of these are not built in /next". That
 * sentence was review-speak — correct in a handoff, unreadable in the
 * product to anyone who was not in the conversation — and the dashed
 * underline on a deferred tab already carries the fact (design rule 6). */
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

/* ════════════════════════════════════════════════════════════════════════
 * Survey and Dashboard
 *
 * Both were deferred in /next, and both were deferred against data that was
 * already one GET away — the same mistake Understanding turned out to be.
 * Neither pane invents anything: Survey lists the Survey Definitions the
 * adapter says can run against this resource, Dashboard reads the dashboards
 * the registry already declares for the current stage.
 * ════════════════════════════════════════════════════════════════════════ */

/** A resource must be selected and be a repo for either pane to mean anything. */
/* ── Disposition and the journal ─────────────────────────────────────────
 *
 * The verdict and its dated trail were already in the resource header. What
 * was missing is the journal: WHY a resource matters, written to be read by
 * someone else. Everything else on these screens is written to be correct;
 * this is the first thing written to be read. So the affordance shows it —
 * room to write, no dropdown, a name on it.
 *
 * Append-only. An entry is a statement someone made on a date; later events
 * do not invalidate it, they get a later entry. Outside the durable /
 * perishable split entirely: no review flags, nothing to reconcile.
 *
 * Suggestion is a routing question and perspectives answer it — a note on a
 * data-heavy repo is for Data Experts and Consumers, the same tags on every
 * question row. It arrives as a WORK-LIST ENTRY for them, not a
 * notification: work lists already exist, carry counts, and survive being
 * ignored for a fortnight; a notification is a thing you dismiss. The UI
 * says where it landed rather than "sent".
 *
 * Nothing prompts for an entry at cataloguing time, and nothing blocks on
 * one. Advocacy written to satisfy a required field is "useful library" on
 * two hundred assets. The empty state is visible instead.
 */
async function loadDispositionPane() {
  const el = $('content');
  const blocked = paneNeedsRepo();
  if (blocked) { el.innerHTML = subTabsHtml() + blocked; bindSubTabs(); return; }
  const slug = state.selectedSlug;
  el.innerHTML = `${subTabsHtml()}
    <div id="resource-header">${resourceHeaderHtml(slug)}</div>
    <div class="my-s3 h-px bg-rule"></div>
    <div class="mb-s1 text-caps uppercase tracking-caps text-ink">Verdicts</div>
    <div id="disposition-history" class="mb-s4 text-provenance text-ink-muted">Loading history…</div>
    <div class="mb-s1 flex items-baseline gap-s2">
      <span class="text-caps uppercase tracking-caps text-ink">Journal</span>
      <span class="text-provenance text-ink-muted">why it matters, and to whom · written to be read</span>
    </div>
    <div id="journal-write"></div>
    <div id="journal-entries" class="mt-s3 text-caveat text-ink-muted">Reading the journal…</div>`;
  bindSubTabs();
  bindResourceHeader();
  const project = state.projects.find((x) => x.slug === slug);
  if (project?.github_url) renderDispositionHistory(project.github_url);
  else $('disposition-history').textContent = 'No GitHub URL, so no disposition can be keyed to this resource.';
  renderJournalWrite(slug);
  await renderJournalEntries(slug);
}

function renderJournalWrite(slug) {
  const host = $('journal-write');
  if (!host) return;
  const who = (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
  const perspectives = (state.perspectives || []).map((p) => p.name || p.id || p).filter(Boolean);
  host.innerHTML = `
    <textarea id="journal-body" rows="4" placeholder="Worth using for anyone who… Note the… before depending on it."
      class="w-full rounded-sm border border-rule-strong bg-transparent p-s2 text-answer text-ink placeholder:text-ink-muted"></textarea>
    <div class="mt-s1 flex flex-wrap items-baseline gap-x-s3 gap-y-[2px] text-caveat">
      <span class="text-ink-muted">suggest to</span>
      ${perspectives.map((p) => `<label class="flex cursor-pointer items-baseline gap-[4px]">
        <input type="checkbox" data-suggest="${esc(p)}"> ${esc(p)}</label>`).join('')}
      <label class="flex items-baseline gap-[4px] text-ink-muted">+ <input id="journal-person" type="text" placeholder="a person…"
        class="w-[12ch] rounded-sm border border-rule-strong bg-transparent px-[4px] text-caveat text-ink placeholder:text-ink-muted"></label>
    </div>
    <div class="mt-s2 flex items-baseline gap-s3">
      <button id="journal-save" type="button"
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-answer text-accent-ink">Write</button>
      <span class="text-provenance text-ink-muted">${who ? `as ${esc(who)}` : 'sign in to write — an entry needs an author'}
        · a suggestion is a work-list entry for them, not a notification</span>
    </div>`;
  $('journal-save').addEventListener('click', async () => {
    const body = $('journal-body').value.trim();
    if (!body) { $('journal-body').focus(); return; }
    const targets = [...host.querySelectorAll('[data-suggest]:checked')].map((c) => c.dataset.suggest);
    const person = ($('journal-person').value || '').trim();
    if (person) targets.push(person);
    const b = $('journal-save'); b.disabled = true; b.textContent = 'writing…';
    try {
      const out = await writeJournal(slug, body, targets);
      $('journal-body').value = ''; $('journal-person').value = '';
      host.querySelectorAll('[data-suggest]').forEach((c) => { c.checked = false; });
      b.disabled = false; b.textContent = 'Write';
      const where = (out.work_lists || []).map((w) => w.work_list).join(', ');
      const note = document.createElement('div');
      note.className = 'mt-s1 text-provenance text-ink-muted';
      note.textContent = where ? `written · suggested — now in ${where}` : 'written';
      host.appendChild(note);
      setTimeout(() => note.remove(), 6000);
      await renderJournalEntries(slug);
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 401 ? 'sign in to write' : `not written: ${err.message}`;
    }
  });
}

async function renderJournalEntries(slug) {
  const host = $('journal-entries');
  if (!host) return;
  let data;
  try { data = await getJournal(slug); }
  catch (err) { host.innerHTML = `<span class="text-state-warn">The journal could not be read: ${esc(err.message)}</span>`; return; }
  if (slug !== state.selectedSlug) return;
  const entries = data.entries || [];
  if (!entries.length) {
    // Visible, and a fair thing for a corpus view to count: catalogued,
    // never written about.
    host.innerHTML = `<span class="text-ink-muted">Nobody has written about this resource yet.</span>`;
    return;
  }
  host.innerHTML = `
    <div class="mb-s1 text-caps uppercase tracking-caps text-ink-muted">Earlier entries · <span class="tnum">${entries.length}</span>${
      data.suggested_to?.length ? ` · suggested to ${esc(data.suggested_to.join(', '))}` : ''}</div>
    ${entries.map((e) => `<div class="border-t border-rule py-s2">
      <p class="m-0 max-w-[70ch] text-answer text-ink">${tnum(esc(e.body))}</p>
      <div class="text-provenance text-ink-muted">${esc(e.author)} · <span class="tnum">${esc(ago(e.written_at))}</span>${
        e.suggested_to?.length ? ` · suggested to ${esc(e.suggested_to.join(', '))}` : ''}</div>
    </div>`).join('')}`;
}

function paneNeedsRepo() {
  if (state.resourceType !== 'repo') {
    return paneMessage('Repos only, in /next',
      'Surveys and dashboards are built for repositories here. Databases and '
      + 'filesystems have their own survey endpoints, and they are live in the '
      + 'current UI.');
  }
  if (!state.selectedSlug) {
    return paneMessage('Select a resource',
      'Pick a repository from the sidebar.');
  }
  return '';
}

/** The tiers, in the order a funnel is worked through. */
const SURVEY_TIERS = ['scouting', 'discovery', 'assessment', 'analysis',
                      'refresh', 'automate_full'];

/** Placeholder, like the matrix's — see STALE_DAYS there. */
const SURVEY_STALE_DAYS = 7;

/** The first sentence of a description: what this will produce.
 *
 * The full text is a maintainer's CHANGELOG — which definition was renamed,
 * that `qualified_name` never changed across either rename. That is real
 * provenance and it is how a real bug was once found, but it answers a
 * question nobody deciding whether to spend compute is asking, and it was the
 * longest text on the pane. It moves behind a disclosure; the first sentence,
 * which is the purpose, comes up to the row.
 */
function onePurpose(text) {
  const t = String(text || '').trim();
  if (!t) return '';
  const stop = t.search(/[.!?](\s|$)/);
  const first = stop === -1 ? t : t.slice(0, stop + 1);
  return first.length > 160 ? `${first.slice(0, 157)}…` : first;
}

/** Last run, with the matrix's own staleness treatment — a rule, not a colour. */
function lastRunHtml(c) {
  const when = c.last_run_at || '';
  if (!when) return '<span class="text-ink-muted">never run</span>';
  const days = (Date.now() - Date.parse(when)) / 86400000;
  const stale = Number.isFinite(days) && days >= SURVEY_STALE_DAYS;
  const ok = (c.last_run_status || '') === 'ok';
  return `<span title="${esc(when)}${c.last_run_status ? ` · ${esc(c.last_run_status)}` : ''}">
    ${ok ? '<span class="text-state-ok">✓</span> '
         : c.last_run_status ? `<span class="text-state-warn">⚠</span> ` : ''}
    <span class="${stale ? 'wl-age-text' : ''}">ran ${esc(ago(when))}</span></span>`;
}

/** The union of annotation types a definition's steps declare — RE steps carry
 *  their own `annotation_types`, native (Egeria-executed) steps carry theirs
 *  nested one level down, in `egeria_produced_annotation_types[].annotation_type`.
 *  De-duplicated because two steps commonly declare the same type. */
function producesTypes(c) {
  const seen = new Set();
  for (const s of c.steps || []) {
    for (const t of s.annotation_types || []) if (t) seen.add(t);
    for (const p of s.egeria_produced_annotation_types || []) if (p && p.annotation_type) seen.add(p.annotation_type);
  }
  return [...seen];
}

function surveyRowHtml(c) {
  const steps = (c.steps || []).length || c.step_count || 0;
  const produces = producesTypes(c);
  return `<div class="flex flex-wrap items-baseline gap-s3 border-b border-rule py-s2">
    <div class="min-w-0 flex-1">
      <div class="text-answer text-ink">${esc(c.display_name || c.qualified_name)}</div>
      ${c.description ? `<div class="text-caveat text-ink-muted">${esc(onePurpose(c.description))}</div>` : ''}
      <div class="mt-[2px] font-mono text-provenance text-ink-muted">${esc(c.qualified_name || '')}${
        c.description ? ` · <button type="button" data-defhist="${esc(c.qualified_name)}"
          class="cursor-pointer bg-transparent underline">definition history</button>` : ''}</div>
      <div class="mt-[2px] text-provenance text-ink-muted">produces · ${
        produces.length ? `<span class="font-mono">${produces.map((t) => esc(t)).join(', ')}</span>` : 'nothing declared'}</div>
    </div>
    <div class="tnum shrink-0 text-caveat text-ink-muted">${steps} step(s)</div>
    <div class="tnum shrink-0 text-caveat">${lastRunHtml(c)}</div>
    <button data-run-survey="${esc(c.qualified_name || c.guid)}"
      class="shrink-0 cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[2px] text-caveat text-accent-ink"
      >Run →</button>
  </div>`;
}

async function loadSurveyPane() {
  const el = $('content');
  const blocked = paneNeedsRepo();
  if (blocked) { el.innerHTML = subTabsHtml() + blocked; bindSubTabs(); return; }
  const slug = state.selectedSlug;
  el.innerHTML = subTabsHtml() + '<div class="text-caveat text-ink-muted">Reading the survey catalog…</div>';
  bindSubTabs();

  let data;
  try {
    data = await getSurveyCandidates(slug, { phase: state.stage });
  } catch (err) {
    el.innerHTML = subTabsHtml() + paneMessage('The survey catalog could not be read',
      `${err.message}. This is a fact about the request, not about ${slug} — nothing
       here says the repo has no surveys.`);
    bindSubTabs();
    return;
  }
  const all = data.candidates || [];
  const stage = data.phase || state.stage;

  // THE TIER IS ON THE ROW, so an unscoped list stops being a problem worth a
  // paragraph. The four-line cold-server warning becomes a chip that says
  // which scope you are looking at, with a retry.
  const heavy = all.filter((c) => c.survey_kind === 'automate_full');
  const rest = all.filter((c) => c.survey_kind !== 'automate_full');
  const byTier = new Map();
  for (const c of rest) {
    const t = c.survey_kind || 'unclassified';
    byTier.set(t, [...(byTier.get(t) || []), c]);
  }
  const tierOrder = [...byTier.keys()].sort(
    (a, b) => (SURVEY_TIERS.indexOf(a) + 1 || 99) - (SURVEY_TIERS.indexOf(b) + 1 || 99));
  const here = tierOrder.filter((t) => t === stage);
  const elsewhere = tierOrder.filter((t) => t !== stage);
  const nElsewhere = elsewhere.reduce((n, t) => n + byTier.get(t).length, 0);

  el.innerHTML = subTabsHtml() + `
    <div class="mb-s3 flex flex-wrap items-baseline gap-s3">
      <span class="text-caps uppercase tracking-caps text-ink-muted">Survey definitions ·
        ${esc(data.technology_type || 'unknown technology type')}</span>
      <span class="ml-auto rounded-sm border ${
        data.scoping === 'full-scan' ? 'border-state-warn text-state-warn' : 'border-rule-strong text-ink-muted'}
        px-2 py-[1px] text-provenance">
        Scope: ${data.scoping === 'full-scan'
          ? `all tiers — stage filter unavailable · <button type="button" data-act="rescope"
              class="cursor-pointer bg-transparent underline">retry</button>`
          : esc(stage)}</span>
    </div>

    ${here.map((t) => `
      <div class="mt-s3 text-caps uppercase tracking-caps text-ink-muted">${esc(t)} ·
        <span class="tnum">${byTier.get(t).length}</span></div>
      ${byTier.get(t).map(surveyRowHtml).join('')}`).join('')}

    ${nElsewhere ? `
      <details class="mt-s3">
        <summary class="cursor-pointer text-caps uppercase tracking-caps text-ink-muted">
          Other stages · <span class="tnum">${nElsewhere}</span>
          <span class="normal-case tracking-normal">— ${esc(elsewhere.map(
            (t) => `${t} ${byTier.get(t).length}`).join(' · '))}</span>
        </summary>
        ${elsewhere.map((t) => `
          <div class="mt-s2 text-caps uppercase tracking-caps text-ink-muted">${esc(t)}</div>
          ${byTier.get(t).map(surveyRowHtml).join('')}`).join('')}
      </details>` : ''}

    ${heavy.map((c) => {
      // SET APART, GIVEN A PLAN VERB, AND NOT PLACED FIRST. Its own
      // description says it scales poorly by construction and is meant as a
      // scheduled choice; a row that argues against being clicked should not
      // be the most default-looking row on the pane.
      const steps = (c.steps || []).length;
      return `<div class="mt-s4 border border-rule bg-[rgba(32,31,29,.03)] p-s3">
        <div class="flex flex-wrap items-baseline gap-s2">
          <span class="text-answer text-ink">${esc(c.display_name)}</span>
          <span class="tnum rounded-sm border border-state-warn px-2 py-[1px] text-provenance text-state-warn"
            >${steps} steps · all tiers</span>
          <button data-plan-survey="${esc(c.qualified_name)}"
            class="ml-auto cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-caveat text-ink"
            >Plan a run…</button>
        </div>
        <div class="mt-s1 max-w-[60ch] text-caveat text-ink-muted">${esc(onePurpose(c.description))}</div>
      </div>`;
    }).join('')}

    ${!all.length ? paneMessage('No survey definitions for this resource',
        'The adapter registered none for this technology type. That is a fact about '
        + 'the catalog, not about the repository.') : ''}
    <div id="survey-note" class="mt-s3 text-caveat text-ink"></div>`;
  bindSubTabs();

  el.querySelector('[data-act="rescope"]')?.addEventListener('click', () => loadSurveyPane());
  el.querySelectorAll('[data-defhist]').forEach((b) => b.addEventListener('click', () => {
    const c = all.find((x) => x.qualified_name === b.dataset.defhist);
    const d = openDialog(c.display_name || c.qualified_name, c.qualified_name);
    d.querySelector('#wl-detail-body').innerHTML = `
      <div class="mb-s2 text-caps uppercase tracking-caps text-ink-muted">Definition history</div>
      <p class="max-w-[70ch] whitespace-pre-line">${esc(c.description || '')}</p>`;
  }));
  el.querySelectorAll('[data-run-survey], [data-plan-survey]').forEach((b) =>
    b.addEventListener('click', () => {
      const ref = b.dataset.runSurvey || b.dataset.planSurvey;
      planSurveyRun(all.find((x) => (x.qualified_name || x.guid) === ref), slug);
    }));
}

/** RUN GOES THROUGH THE SAME PREVIEW as the matrix's two plans.
 *
 * This is the third and most expensive of them, and if they answer "what am I
 * about to spend" in three shapes people learn to read one and skim the rest.
 */
function planSurveyRun(c, slug) {
  if (!c) return;
  const steps = (c.steps || []).length;
  const el = openDialog(c.display_name || c.qualified_name, `${slug} · ${c.survey_kind || 'unclassified'}`);
  const body = el.querySelector('#wl-detail-body');
  const local = (c.steps_local || []).length;
  const native = (c.steps_native || []).length;
  body.innerHTML = `
    <p>This runs <span class="tnum">${steps}</span> step(s) against
      <span class="font-mono">${esc(slug)}</span>.</p>
    <ul class="ml-s3 mt-s2 list-disc">
      ${local ? `<li><span class="tnum">${local}</span> run here</li>` : ''}
      ${native ? `<li><span class="tnum">${native}</span> are coordinated by Egeria</li>` : ''}
      <li>${c.last_run_at
            ? `last ran ${esc(ago(c.last_run_at))}${
                c.last_run_status ? ` · ${esc(c.last_run_status)}` : ''} —
               <strong>everything it covers will be measured again</strong>`
            : 'it has never run on this resource'}</li>
      ${(c.analysis_ids || []).length
        ? `<li>writes: <span class="font-mono">${esc((c.analysis_ids || []).join(', '))}</span></li>` : ''}
      ${c.auto_publishes ? '<li>publishes its results to Egeria when it finishes</li>' : ''}
    </ul>
    <div id="plan-movement" class="mt-s2 text-caveat text-ink-muted"></div>
    <p class="mt-s3 text-ink">Nothing runs until you confirm.</p>
    <div class="mt-s3 flex gap-s3 border-t border-rule pt-s2">
      <button type="button" data-act="go"
        class="cursor-pointer rounded-sm border border-accent px-2 py-[2px] text-accent-ink"
        >Run <span class="tnum">${steps}</span> step(s)</button>
      <button type="button" data-act="close"
        class="cursor-pointer bg-transparent text-ink-muted underline">Cancel</button>
    </div>`;
  body.querySelector('[data-act="go"]').addEventListener('click', () => {
    closeCellDetail();
    launchSurvey(slug, c.qualified_name || c.guid);
  });

  // WHAT MOVED LAST TIME, HERE, WHERE IT CHANGES A DECISION.
  //
  // "Unchanged across N runs" reports a fact on a dashboard row; in a plan it
  // is an argument. A survey whose measurements have not moved across several
  // runs is a survey whose cadence is costing more than it returns, and this
  // is the moment that matters — before paying for it again rather than after.
  reportPlanMovement(slug, c);
}

async function reportPlanMovement(slug, c) {
  const ids = (c.analysis_ids || []).filter((a) => trendSupport(a) === 'tracked');
  if (!ids.length) return;
  const checked = ids.slice(0, 6);         // enough to characterise, not a survey of its own
  const deltas = await Promise.all(checked.map(async (a) => ({ a, text: await deltaFor(slug, a) })));
  const slot = document.getElementById('plan-movement');
  if (!slot) return;                        // the dialog was closed while we read
  const still = deltas.filter((d) => /^unchanged/.test(d.text));
  const moved = deltas.filter((d) => d.text && !/^unchanged|^first/.test(d.text));
  if (!still.length && !moved.length) return;
  slot.innerHTML = `
    ${still.length ? `<div class="text-accent-ink"><span class="tnum">${still.length}</span> of
      <span class="tnum">${checked.length}</span> tracked measurement(s) have not moved across
      their recorded runs — <span class="font-mono">${esc(still.map((d) => d.a).join(', '))}</span>.
      Running this again will re-measure them and, on this evidence, change nothing.</div>` : ''}
    ${moved.length ? `<div class="mt-[2px]"><span class="tnum">${moved.length}</span> did move
      last time: ${esc(moved.map((d) => `${d.a} ${d.text}`).join(' · '))}.</div>` : ''}`;
}

async function launchSurvey(slug, ref) {
  const note = $('survey-note');
  if (note) note.innerHTML = `Launching <span class="font-mono">${esc(ref)}</span>…`;
  try {
    const res = await runSurveyDefinition(slug, ref);
    if (note) note.innerHTML = `Launched <span class="font-mono">${esc(ref)}</span>.
      ${res && (res.guid || res.engine_action_guid)
        ? `Egeria action <span class="font-mono">${esc(res.guid || res.engine_action_guid)}</span>.` : ''}
      It runs asynchronously — its results appear in Dashboard and in the question rows
      as each step lands, not when this line changes.`;
  } catch (err) {
    if (!note) return;
    // 401 is not a failure of the survey, it is a fact about this session.
    note.innerHTML = err.status === 401
      ? `<span class="text-accent-ink">Not launched — running a survey is a write, and
         this session is not signed in. Sign in with an Egeria user id to launch it;
         everything else on this pane is readable without one.</span>`
      : `<span class="text-state-warn">It was not launched: ${esc(err.message)}</span>`;
  }
}

/* ── The shared measurement detail ────────────────────────────────────────
 *
 * THE MISSING MIDDLE. Survey says what you can run; Dashboard says what is
 * currently true; nothing said what a run FOUND, and no value opened into its
 * evidence or its history.
 *
 * Evidence was never missing — it was unrouted. The matrix cell popup has done
 * this job since the round that produced "the grid carries state, the popup
 * carries meaning"; the Dashboard simply did not call it. So this is one
 * component with several entry points: a dashboard finding, a count, and (via
 * the history section) the matrix's own cell popup. If they diverge, people
 * learn one and distrust the others.
 */

/** What the catalog says about an analysis: `tracked`, `not_tracked`, or
 *  `unknown` when it is not in the results map at all. */
function trendSupport(analysisId) {
  const entry = (state.analyses || []).find((a) => a.id === analysisId);
  return entry?.trend || 'unknown';
}

/** The recorded series for one analysis, oldest first.
 *
 * WITH ONE MEASUREMENT THERE IS NO TREND. It says "first measurement" rather
 * than drawing a flat line — a sparkline of a single point is the same lie as
 * a tick standing in for an unread cell.
 */
async function historyHtml(slug, analysisId, metric = '') {
  // ASK THE DESCRIPTOR, NOT THE ENDPOINT. A current-state classification
  // correctly keeps no series; that is a property of the analysis, so the UI
  // renders no history section at all rather than an empty one — and never
  // makes a request whose only possible answer is "no".
  //
  // This is what replaced a 400. The endpoint's message was a good sentence
  // in the wrong place: an error is not how a system reports that something
  // is working as designed.
  if (trendSupport(analysisId) === 'not_tracked') return '';

  let series;
  try {
    const res = await getAnalysisTrend(slug, analysisId, metric);
    series = (res.runs || res.series || []).filter((r) => r && r.surveyed_at);
  } catch (err) {
    // A 400 here is an ANSWER, not a failure: the endpoint says this analysis
    // keeps no trend because it is a current-state classification. Rendering
    // that as "could not be read" turns a fact about the analysis into a fault
    // in the reader — the same mistake as "no results" for "not looked at".
    if (err.status === 400) {
      return `<p class="text-caveat text-ink-muted">${esc(err.message)}</p>`;
    }
    return `<p class="text-caveat text-state-warn">The history could not be read:
      ${esc(err.message)}</p>`;
  }
  if (!series.length) return '<p class="text-caveat text-ink-muted">No recorded history.</p>';
  if (series.length === 1) {
    // "There WILL be a trend" is the whole difference from `not tracked`, and
    // it is the half a reader cannot infer from an empty list.
    return `<p class="text-caveat text-ink-muted">First measurement,
      ${esc(ago(series[0].surveyed_at))}. Tracked, but measured once — there will
      be a trend; there isn't one yet.</p>`;
  }
  series.sort((a, b) => String(a.surveyed_at).localeCompare(String(b.surveyed_at)));
  // A history is interesting exactly where it steps. Thirty rows of which
  // twenty-eight are identical HIDE the two that matter — the dependency
  // count went 57 to 68 over five weeks and a reader had to read thirty
  // figures to notice. So the transitions lead: each value the series ever
  // took, dated where it first appeared, and the count of runs and changes.
  // The full table stays one click on, for the reader who wants every run.
  const val = (r) => r.metric_value ?? r.value;
  const steps = [];
  for (const r of series) {
    if (!steps.length || steps[steps.length - 1].v !== val(r)) steps.push({ v: val(r), at: r.surveyed_at, m: r.metric });
  }
  const changes = steps.length - 1;
  const transitions = steps.map((st) => `<span class="tnum">${esc(fmtScalar(st.v, st.m || metric))}</span>
      <span class="text-ink-muted">${esc(String(st.at).slice(5, 10))}</span>`).join(' → ');
  return `
    <div class="mb-s1 text-caveat text-ink">${transitions}
      <span class="text-ink-muted">· <span class="tnum">${series.length}</span> runs, <span class="tnum">${changes}</span> change${changes === 1 ? '' : 's'}</span></div>
    <details><summary class="cursor-pointer text-caps uppercase tracking-caps text-ink-muted">Every run · oldest first ·
      <span class="tnum">${series.length}</span> recorded</summary>
    <table class="w-full border-collapse text-caveat">
      ${series.map((r, i) => `<tr class="border-b border-rule">
        <td class="tnum py-[4px] pr-s3 text-ink-muted">${esc(String(r.surveyed_at).slice(0, 10))}</td>
        <td class="tnum py-[4px] text-ink ${i === series.length - 1 ? 'font-semibold' : ''}">${
          esc(fmtScalar(r.metric_value ?? r.value, r.metric || metric))}</td>
      </tr>`).join('')}
    </table></details>`;
}

/** The inline delta beside a value: what it was, and when.
 *
 * That is the whole trend for most measurements most of the time — the series
 * itself lives in the detail.
 */
async function deltaFor(slug, analysisId, metric = '') {
  if (trendSupport(analysisId) === 'not_tracked') return '';
  try {
    const res = await getAnalysisTrend(slug, analysisId, metric);
    const series = (res.runs || res.series || []).filter((r) => r && r.surveyed_at);
    if (series.length < 2) return series.length === 1 ? 'first measurement' : '';
    series.sort((a, b) => String(a.surveyed_at).localeCompare(String(b.surveyed_at)));
    const now = series[series.length - 1];
    // The last value that DIFFERS, not simply the previous row: repeated runs
    // that changed nothing would otherwise report "was <the same> 2h ago",
    // which reads as movement where there was none.
    const prior = [...series].reverse().find(
      (r) => (r.metric_value ?? r.value) !== (now.metric_value ?? now.value));
    if (!prior) return `unchanged across ${series.length} runs`;
    // A row may name its own metric (the trend reader knows what `value`
    // is even when the caller does not); prefer that over the caller's.
    return `was ${fmtScalar(prior.metric_value ?? prior.value, prior.metric || metric)} ${ago(prior.surveyed_at)}`;
  } catch (_) {
    return '';
  }
}

/** One measurement, opened: what it says, its evidence, its history. */
/* ── What a measurement is entitled to claim ──────────────────────────────
 *
 * The catalog's Rationale/Source column carries, per question, what its
 * answer can and cannot mean: secret_scan never claims "no secrets", only no
 * matches against this ruleset in this snapshot; cve_scan sees declared
 * dependencies only, so a zero is "none found in what we can see".
 *
 * Those sentences have existed in the CSV since the catalog was authored and
 * have never reached a screen. They are the difference between a finding and
 * a claim, so they belong beside the value — as the second line of the
 * answer, not as help text.
 *
 * Keyed by analysis id because that is what a measurement knows about
 * itself. One analysis can answer several questions, so the value is a list
 * and duplicates are collapsed: two questions often share a rationale, and
 * printing it twice reads as two separate caveats.
 */
const RATIONALE_BY_ANALYSIS = new Map();

function rememberRationales(questions) {
  for (const q of questions || []) {
    const text = (q.rationale || '').trim();
    if (!text) continue;
    for (const id of q.analysis_ids || []) {
      const held = RATIONALE_BY_ANALYSIS.get(id) || [];
      if (!held.includes(text)) held.push(text);
      RATIONALE_BY_ANALYSIS.set(id, held);
    }
  }
}

/** The caveat block for one analysis, or '' when the catalog states none.
 *
 * Empty is rendered as nothing rather than as "no caveats recorded": this
 * cache is filled by whichever checklists have been loaded this session, so
 * an empty result means "not loaded here", NOT "this measurement claims
 * without limit". Saying the latter would be the fast-path-that-lies shape
 * the matrix was built to avoid.
 */
function rationaleHtml(analysisId) {
  const held = RATIONALE_BY_ANALYSIS.get(analysisId) || [];
  if (!held.length) return '';
  return `<div class="mt-s2 border-l-2 border-accent pl-s2">
      <div class="uppercase tracking-caps text-caps text-ink-muted">What this can claim</div>
      ${held.map((t) => `<p class="mt-[2px] max-w-[70ch] text-caveat text-accent-ink">${tnum(esc(t))}</p>`).join('')}
    </div>`;
}

async function openMeasurementDetail({ slug, analysisId, title, metric = '',
                                       glyph = '', summary = '', when = '' }) {
  const el = openDialog(title, `${slug} · ${analysisId}`);
  const body = el.querySelector('#wl-detail-body');
  body.innerHTML = `
    <div class="flex items-baseline gap-s2">
      ${glyph ? `<span>${glyph}</span>` : ''}
      <span class="text-answer text-ink">${esc(title)}</span>
      ${when ? `<span class="ml-auto text-provenance text-ink-muted">measured ${esc(ago(when))}</span>` : ''}
    </div>
    ${summary ? `<p class="mt-s1 max-w-[70ch] text-ink">${tnum(esc(summary))}</p>` : ''}
    ${rationaleHtml(analysisId)}
    ${trendSupport(analysisId) === 'not_tracked'
      // Said, flatly, once. No history SECTION — an empty section implies
      // something should be there — but not silence either: a reader who
      // expects a history and finds nothing cannot tell "correctly none" from
      // "we forgot". One line closes that.
      ? `<p class="mt-s3 text-caveat text-ink-muted">Current-state classification —
          not tracked over time.</p>`
      : `<div id="md-history" class="mt-s3 text-caveat text-ink-muted">Reading the history…</div>`}
    <div class="mt-s3 flex gap-s3 border-t border-rule pt-s2">
      <button type="button" data-act="rerun"
        class="cursor-pointer rounded-sm border border-accent px-2 py-[2px] text-accent-ink"
        >Re-run <span class="font-mono">${esc(analysisId)}</span> →</button>
      <button type="button" data-act="runs"
        class="cursor-pointer bg-transparent text-ink-muted underline">Runs on this resource</button>
    </div>`;
  const slot = body.querySelector('#md-history');
  if (slot) {
    const hist = await historyHtml(slug, analysisId, metric);
    if (hist) slot.innerHTML = hist; else slot.remove();
  }
  body.querySelector('[data-act="runs"]')?.addEventListener('click', () => openRunsList(slug));
  body.querySelector('[data-act="rerun"]')?.addEventListener('click', async () => {
    const b = body.querySelector('[data-act="rerun"]');
    b.disabled = true;
    b.textContent = 'Queueing…';
    try {
      await enqueueBatch(analysisId, [slug], '');
      b.textContent = 'Queued';
    } catch (err) {
      b.textContent = err.status === 401 ? 'Not signed in' : `Refused: ${err.message}`;
    }
  });
}

/* ── The run record ───────────────────────────────────────────────────────
 *
 * The level that regressed. The old Survey pane showed what a run FOUND, and
 * a definitions list replaced it without replacing that.
 *
 * The per-step detail is in the activity log's own `detail` payload — steps
 * with their statuses — so this is wiring too, not new persistence.
 */
/*
 * Declared vs received — DECLARED IS NOT PROMISED. A step's `declared`
 * annotation types are "this step is capable of emitting these", not "this
 * run definitely produced them". Whether it actually did can only be read
 * from the run's own Egeria report, and two of the six verdicts below are not
 * "zero" even when they render on the empty side of the line: `not-published`
 * means the run has no report to check at all, and `not-recorded` means it
 * has one but predates the publish bookkeeping (2026-09-07) that would let us
 * trust an absence. Both say "cannot be known" — never "no" — and never count
 * toward a total the way a real zero would.
 */

/** One `types[]` entry from GET …/declared-vs-received, rendered as a line:
 *  glyph, the type in mono, and a short plain-English reading of the verdict. */
function declaredVsReceivedLineHtml(t) {
  let glyph = '<span class="text-ink-muted">·</span>';
  let phrase;
  switch (t.verdict) {
    case 'received':
      glyph = '<span class="text-state-ok">✓</span>';
      phrase = 'received';
      break;
    case 'step-did-not-finish': {
      glyph = '<span class="text-state-warn">⚠</span>';
      const statuses = t.step_statuses || {};
      const failing = (t.declared_by || []).filter((s) => statuses[s] && statuses[s] !== 'ok');
      const detail = (failing.length ? failing : (t.declared_by || []))
        .map((s) => `${s}${statuses[s] ? ` (${statuses[s]})` : ''}`).join(', ');
      phrase = `the declaring step did not finish — ${detail}`;
      break;
    }
    case 'step-not-in-run':
      phrase = 'declared, but this run never reached the step that produces it';
      break;
    case 'nothing-of-this-type':
      phrase = 'ran clean, found nothing of this type';
      break;
    case 'not-published':
      phrase = 'cannot be known — this run has no Egeria report to check';
      break;
    case 'not-recorded':
      phrase = 'cannot be known — published before publish bookkeeping began (2026-09-07)';
      break;
    default:
      phrase = String(t.verdict || '');
  }
  return `<li class="flex gap-s2">
    <span class="w-[16px] shrink-0">${glyph}</span>
    <span class="min-w-0 font-mono text-provenance">${esc(t.annotation_type)}</span>
    <span class="text-ink-muted">— ${tnum(esc(phrase))}</span>
  </li>`;
}

/** The whole declared-vs-received block for one run. `data` is the parsed
 *  response of GET …/declared-vs-received. */
function declaredVsReceivedHtml(data) {
  const s = data.summary || {};
  const didNotFinish = s['step-did-not-finish'] || 0;
  // When the run has no report (`published` false) or predates publish
  // bookkeeping (`recorded` false), every "unknown" type says the identical
  // thing — so it is said ONCE, not once per type, to avoid drowning the
  // defect lines (which ARE knowable from the run record and always shown).
  const collapseUnknown = !data.published || !data.recorded;
  let unknownShown = false;
  const rows = (data.types || []).map((t) => {
    if (collapseUnknown && (t.verdict === 'not-published' || t.verdict === 'not-recorded')) {
      if (unknownShown) return '';
      unknownShown = true;
      const reason = !data.published
        ? 'this run has no Egeria report, so what it produced cannot be listed from here'
        : 'this run was published before publish bookkeeping began (2026-09-07), so absence here means nothing';
      return `<li class="flex gap-s2">
        <span class="w-[16px] shrink-0 text-ink-muted">·</span>
        <span class="min-w-0 text-ink-muted">The rest cannot be known — ${esc(reason)}.</span>
      </li>`;
    }
    return declaredVsReceivedLineHtml(t);
  }).join('');
  return `
    <div class="mt-s2 text-caps uppercase tracking-caps text-ink-muted">Declared vs received</div>
    <div class="mt-s1 text-provenance text-ink-muted">
      <span class="tnum">${esc(s.declared ?? 0)} declared</span> · <span class="tnum">${esc(s.received ?? 0)} received</span>${
        didNotFinish ? ` · <span class="tnum text-state-warn">${esc(didNotFinish)} did not finish</span>` : ''}</div>
    <ul class="m-0 mt-s1 list-none p-0 text-caveat">${rows}</ul>`;
}

async function openRunsList(slug) {
  const el = openDialog('Runs', slug);
  const body = el.querySelector('#wl-detail-body');
  let rows;
  try {
    rows = await getResourceRuns(slug);
  } catch (err) {
    body.innerHTML = `<p class="text-state-warn">The runs could not be read: ${esc(err.message)}</p>`;
    return;
  }
  const runs = (rows || []).filter((r) => r.operation === 'survey');
  if (!runs.length) {
    body.innerHTML = `<p>No survey run is recorded for ${esc(slug)}.</p>`;
    return;
  }
  body.innerHTML = runs.slice(0, 12).map((r) => {
    let steps = [];
    try {
      const d = typeof r.detail === 'string' ? JSON.parse(r.detail) : (r.detail || {});
      steps = d.steps || [];
    } catch (_) { /* a detail we cannot parse is a run with no step list */ }
    const ok = steps.filter((s) => s.status === 'ok').length;
    const bad = steps.filter((s) => s.status && s.status !== 'ok');
    return `<details class="border-b border-rule py-s2">
      <summary class="cursor-pointer">
        <span class="text-ink">${esc(r.summary || 'survey run')}</span>
        <span class="text-provenance text-ink-muted"> · ${esc(ago(r.ts))} · ${esc(r.status || '')}</span>
      </summary>
      ${steps.length ? `
        <div class="mt-s1 text-provenance text-ink-muted">
          <span class="text-state-ok">${ok} ran</span>${
          bad.length ? ` · <span class="text-state-warn">${bad.length} did not</span>` : ''}</div>
        <ul class="m-0 mt-s1 list-none p-0 text-caveat">
          ${steps.map((s) => `<li class="flex gap-s2">
            <span class="${s.status === 'ok' ? 'text-state-ok' : 'text-state-warn'}">${
              s.status === 'ok' ? '✓' : '⚠'}</span>
            <span class="min-w-0 font-mono text-provenance">${
              esc(String(s.step || '').split('::').pop())}</span>
            ${s.status !== 'ok' && s.detail
              ? `<span class="text-ink-muted">— ${esc(String(s.detail).slice(0, 120))}</span>` : ''}
          </li>`).join('')}
        </ul>`
        : '<p class="mt-s1 text-caveat text-ink-muted">This run recorded no step list.</p>'}
      <div data-dvr="${esc(r.id)}"></div>
    </details>`;
  }).join('');

  // Lazily fetched, per run, on first open — the reconciliation is a second
  // request per row and most rows in a list of 12 are never expanded. `toggle`
  // fires on both open and close, and on close-then-reopen, so a `fetched`
  // flag closed over the one placeholder guards against firing it twice.
  body.querySelectorAll('details').forEach((det) => {
    const holder = det.querySelector('[data-dvr]');
    if (!holder) return;
    const entryId = holder.dataset.dvr;
    let fetched = false;
    det.addEventListener('toggle', async () => {
      if (!det.open || fetched) return;
      fetched = true;
      let dvr;
      try {
        dvr = await getDeclaredVsReceived(entryId);
      } catch (err) {
        // A 409 means this activity entry is not a survey run with a step
        // list — not an error worth showing, just nothing to reconcile.
        if (err instanceof ApiError && err.status === 409) return;
        holder.innerHTML = `<p class="mt-s1 text-caveat text-ink-muted">Could not read the declaration: ${esc(err.message)}</p>`;
        return;
      }
      holder.innerHTML = declaredVsReceivedHtml(dvr);
    });
  });
}

/** Invalidates an in-flight dashboard read when the pane or resource changes. */
let dashToken = 0;

/* ── Dashboard ────────────────────────────────────────────────────────────
 *
 * THREE KINDS OF THING, THREE RANKS. Prose-as-peer worked and then everything
 * levelled up to meet it: twelve identical bordered cards, so a composed
 * score and "no specification file found" carried the same weight. Equal rank
 * for prose was the goal; equal rank for everything is what shipped.
 *
 *   headline  — the composed score, once, at size
 *   findings  — judgements, unresolved first, in the MATRIX'S OWN GLYPHS
 *   counts    — reference material, as a table, at reference weight
 *
 * Twelve bordered cards holding one number each IS a table, drawn expensively.
 */

/** Findings whose label means "nobody established this" sort to the top. */
const UNRESOLVED_LABELS = new Set([
  'not_established', 'unknown', 'none', 'not_measured', 'unavailable']);

/** ONE STATE VOCABULARY ACROSS BOTH SURFACES.
 *
 * The dashboard was shouting its enum — `— NOT_ESTABLISHED`, `— SOLE`,
 * `— PERIODIC` — as machine tokens welded to a title. They are the same kind
 * of fact the matrix encodes as glyphs, and someone who has learned the grid
 * should not have to learn a second language one click away.
 */
function findingGlyph(label) {
  const l = String(label || '').toLowerCase();
  if (UNRESOLVED_LABELS.has(l)) return CELL.nothing;          // ∅ ran, established nothing
  if (/^(fail|gap|missing|no|absent|gone)$/.test(l)) return CELL.human;   // ⚠ needs a person
  if (/(sole|risk|low|weak|stale|declining|concentrat)/.test(l)) return CELL.partial;
  return CELL.answered;                                        // ✓
}

/** `not_established` -> `not established`; `SOLE` -> `sole`. */
const humanLabel = (l) => String(l || '').replace(/_/g, ' ').toLowerCase();

/* ── The dashboard, by question ────────────────────────────────────────────
 *
 * The diagnosis, in one line: the dashboard was organised by the PRODUCER
 * while every other pane is organised by the CONSUMER. A question has one
 * answer even when six analyses contribute; on the authored boards that
 * answer was six paragraphs apart in six sections — and one analysis that
 * answers six questions (`repo_conventions`) appeared on two boards in full,
 * both times, under neither question.
 *
 * This view is generated, not authored. It reads the stage's questions, the
 * analyses they name, and the facts for those analyses — the same projection
 * the matrix reads, keyed by analysis id and independent of which board an
 * analysis was filed under. Adding an analysis to the catalog and naming it
 * on a question puts it here with no UI change, which was the bar.
 *
 * Three ranks per question, as before: the analysis's OWN sentence first
 * (`headline` — the annotation writes its summary, we render it rather than
 * re-composing from fields, which is where 82 / 82.2 came from), then
 * findings unresolved-first, then counts as a table.
 *
 * When one analysis serves several questions, the catalog's `checks` decide
 * what each question shows: a question declaring `repo_conventions:doc_breadth`
 * shows that finding and not the other four. A question that declares no
 * check takes the whole analysis — once. Later questions naming the same
 * analysis get a pointer to where it is shown, because the same five
 * findings rendered six times is the thing this view exists to stop.
 *
 * Two things deliberately NOT on this pane:
 *  - the ~40 `sub_resource_survey` worthy / not-worthy rows are promotion
 *    candidates and belong with the verdict loop; here they are one line
 *    with a count and a pointer to the work list;
 *  - nothing is hidden. An analysis the stage measures that no question
 *    asks for is listed at the end under its own heading, because that list
 *    is the standing check the catalog needs and it found nine on first run.
 */
const DASH_VIEW_KEY = 're-next.dashView';



/* Round two of the dashboard (DASHBOARD-ROUND-TWO.md): presentation, not
 * structure. The grouping by question stands; what was missing was the tier
 * it was meant to unlock — a reader still assembled every answer themselves
 * from raw rows, 2,300 pixels deep. Five rules, each a function below:
 *
 *   1. every section opens with its answer — the answer LAYER's sentence,
 *      the same one the Evidence rail shows, not one composed here;
 *   2. findings that agree collapse to one row with a count;
 *   3. provenance is section-level; the analysis name leaves every row;
 *   4. a disagreement is the section's headline, shown once and pointed to
 *      from any other question that reaches the same conflict;
 *   5. booleans and unsets leave the counts table — they are part of the
 *      answer, or they are "not recorded", never a number.
 */

function findingRowHtml(f, analysisId, when) {
  const c = findingGlyph(f.label);
  return `<button type="button" class="flex w-full items-baseline gap-s2 border-0 border-b border-rule bg-transparent px-0 py-s2 text-left"
    data-measure="${esc(analysisId)}" data-check="${esc(f.check_name || '')}"
    data-title="${esc((f.check_name || analysisId).replace(/_/g, ' '))}"
    data-summary="${esc(f.summary || '')}" data-when="${esc(when || '')}">
    <span class="w-[16px] shrink-0 ${c.tone}" title="${esc(c.label)}">${c.glyph}</span>
    <span class="min-w-0 flex-1 text-ink">
      <strong class="font-semibold">${
        f.check_name
          ? `${esc(f.check_name.replace(/_/g, ' '))}${f.label ? ` — ${esc(humanLabel(f.label))}` : ''}`
          : esc(humanLabel(f.label) || analysisId)}.</strong>
      ${f.summary ? ` ${tnum(esc(f.summary))}` : ''}</span>
    <span class="shrink-0 text-provenance text-ink-muted">›</span>
  </button>`;
}

function isUnresolved(f) {
  return UNRESOLVED_LABELS.has(String(f.label || '').toLowerCase());
}

/** Rule 2. Unresolved findings stay individual and first — each is a
 *  decision. The rest group by verdict: two or more that agree become one
 *  row naming the count and the checks, with the full rows behind a
 *  disclosure. "Five passes" is one fact, not five. */
function findingsHtml(findings, analysisId, when) {
  const open = findings.filter(isUnresolved);
  const rest = findings.filter((f) => !isUnresolved(f));
  const groups = new Map();
  for (const f of rest) {
    const k = String(f.label || '').toLowerCase();
    groups.set(k, [...(groups.get(k) || []), f]);
  }
  const out = [...open.map((f) => findingRowHtml(f, analysisId, when))];
  for (const [label, rows] of groups) {
    if (rows.length === 1) { out.push(findingRowHtml(rows[0], analysisId, when)); continue; }
    const c = findingGlyph(label);
    const names = rows.map((f) => (f.check_name || '').replace(/_/g, ' ')).filter(Boolean);
    out.push(`<details class="border-b border-rule py-s2">
      <summary class="flex cursor-pointer items-baseline gap-s2 list-none">
        <span class="w-[16px] shrink-0 ${c.tone}">${c.glyph}</span>
        <span class="min-w-0 flex-1 text-ink"><strong class="font-semibold tnum">${rows.length} checks — ${esc(humanLabel(label))}.</strong>
          <span class="text-ink-muted">${esc(names.join(', '))}</span></span>
        <span class="shrink-0 text-provenance text-ink-muted">show ${rows.length}</span>
      </summary>
      <div class="pl-[22px]">${rows.map((f) => findingRowHtml(f, analysisId, when)).join('')}</div>
    </details>`);
  }
  return out.join('');
}

function subResourceSummaryHtml(fact) {
  const rows = (fact.value && fact.value.findings) || [];
  const worthy = rows.filter((r) => String(r.label || '').toLowerCase() === 'worthy').length;
  return `<div class="mt-s1 text-caveat text-ink">
      <span class="tnum">${rows.length}</span> sub-resources assessed ·
      <span class="tnum">${worthy}</span> worthy · <span class="tnum">${rows.length - worthy}</span> not.
      <span class="text-ink-muted">These are promotion candidates, not findings about this repository —
        they belong with the verdict loop.</span>
      <button type="button" data-members="sub_resource_survey" data-title="sub-resources" class="cursor-pointer bg-transparent text-accent-ink underline">which ›</button>
      <button type="button" data-goto-worklist class="cursor-pointer bg-transparent text-accent-ink underline">Open work lists →</button>
    </div>`;
}

function factGlyph(state) {
  switch (state) {
    case 'measured': return { glyph: '✓', tone: 'text-state-ok' };
    case 'error': return { glyph: '✕', tone: 'text-state-warn' };
    case 'unrun': return { glyph: '○', tone: 'text-ink-muted' };
    default: return { glyph: '·', tone: 'text-ink-muted' };
  }
}

/** Rule 5. Split an analysis's scalar results three ways: numbers for the
 *  counts table; booleans, which ARE part of the answer; and unsets — null
 *  or empty — which are "not recorded" and must never render as a number.
 *  A zero is left as a zero: whether it means "none" or "not set" is the
 *  producer's to say, and guessing here would be the lie the round names. */
function splitScalars(value) {
  const numbers = []; const flags = []; const unset = [];
  for (const [k, v] of Object.entries(value || {})) {
    if (k === 'findings' || k === 'overall') continue;
    if (typeof v === 'number') numbers.push({ key: k, value: v });
    else if (typeof v === 'boolean') flags.push({ key: k, value: v });
    else if (v == null || v === '') unset.push(k);
  }
  return { numbers, flags, unset };
}

/** One analysis, under one question. `checks` is the set of check names this
 *  question declares for it, or null for the whole analysis. Provenance is
 *  NOT on the rows (rule 3): the analysis is named once, here, in the head
 *  line, and in the popup beside the run. */
function analysisUnderQuestionHtml(fact, id, checks) {
  if (!fact) {
    return `<div class="mt-s2 text-caveat text-ink-muted"><span class="font-mono">${esc(id)}</span> · not read</div>`;
  }
  const g = factGlyph(fact.state);
  const when = fact.last_run_at || '';
  const value = (fact.value && typeof fact.value === 'object') ? fact.value : {};
  let findings = Array.isArray(value.findings) ? value.findings : [];
  if (checks) findings = findings.filter((f) => checks.has(String(f.check_name || '')));
  findings = sortUnresolvedFirst(findings);
  const { numbers: allNumbers, flags, unset } = checks ? { numbers: [], flags: [], unset: [] } : splitScalars(value);
  // An analysis whose state is "nothing found" has said so in its sentence.
  // Four zeros under "Nothing ingested from site" restate it as a table, and
  // a zero that means "nothing happened" reads as a measurement of nothing.
  // The zeros are dropped only in that state; a zero from a measured run is
  // a value and stays.
  const numbers = fact.state === 'nothing_found' ? allNumbers.filter((c) => c.value !== 0) : allNumbers;
  const head = `<button type="button" class="mt-s2 flex w-full items-baseline gap-s2 border-0 bg-transparent px-0 text-left"
      data-measure="${esc(id)}" data-title="${esc(id.replace(/_/g, ' '))}"
      data-summary="${esc(fact.headline || '')}" data-when="${esc(when)}">
      <span class="w-[16px] shrink-0 ${g.tone}">${g.glyph}</span>
      <span class="min-w-0 flex-1 text-answer text-ink">${tnum(esc(fact.headline || fact.note || fact.state || ''))}${
        flags.length ? ` <span class="text-caveat text-ink-muted">· ${flags.map((f) => `${esc(f.key.replace(/_/g, ' '))}: ${f.value ? 'yes' : 'no'}`).join(' · ')}</span>` : ''}</span>
      <span class="shrink-0 font-mono text-provenance text-ink-muted">${esc(id)}${when ? ` · ${esc(ago(when))}` : ''} ›</span>
    </button>
    <div class="pl-[22px] text-provenance">
      <button type="button" data-members="${esc(id)}" data-title="${esc(id.replace(/_/g, ' '))}"
        class="cursor-pointer bg-transparent p-0 text-accent-ink underline">members ›</button>
    </div>`;
  if (id === 'sub_resource_survey') return head + subResourceSummaryHtml(fact);
  const scopedAndFound = checks && findings.length;
  return (scopedAndFound ? '' : head)
    + (findings.length ? findingsHtml(findings, id, when) : '')
    + (unset.length ? `<div class="mt-s1 text-caveat text-ink-muted">not recorded: ${esc(unset.map((k) => k.replace(/_/g, ' ')).join(', '))}</div>` : '')
    + (numbers.length ? `<table class="mt-s1 w-full border-collapse text-caveat">${numbers.map((c) => `
        <tr class="wl-countrow cursor-pointer border-b border-rule" data-members="${esc(id)}" data-metric="${esc(c.key)}"
          data-title="${esc(c.key.replace(/_/g, ' '))}" data-when="${esc(when)}">
          <td class="py-[5px] pr-s3 text-ink">${esc(c.key.replace(/_/g, ' '))}</td>
          <td class="tnum py-[5px] text-right text-ink">${esc(fmtScalar(c.value, c.key))}
            <span class="text-provenance text-ink-muted">members ›</span></td>
        </tr>`).join('')}</table>` : '');
}

function sortUnresolvedFirst(findings) {
  return [...findings].sort((x, y) => (isUnresolved(x) ? 0 : 1) - (isUnresolved(y) ? 0 : 1));
}

/** Rule 4. Every scalar name reported by more than one analysis with
 *  different values, across ALL the facts on the pane — so a conflict is
 *  found wherever it lives and shown wherever it is reached. */
function findDisputes(facts) {
  const seen = new Map();
  for (const [id, f] of facts) {
    const value = (f && f.value && typeof f.value === 'object') ? f.value : {};
    for (const [k, v] of Object.entries(value)) {
      if (typeof v !== 'number') continue;
      seen.set(k, [...(seen.get(k) || []), { analysis: id, value: v }]);
    }
  }
  const disputes = new Map();
  for (const [k, rec] of seen) {
    if (rec.length > 1 && new Set(rec.map((x) => x.value)).size > 1) disputes.set(k, rec);
  }
  return disputes;
}

function disputeHtml(key, rec, when) {
  return `<div class="mt-s2 border-l-2 border-state-warn pl-s2">
      <div class="text-caps uppercase tracking-caps text-state-warn">Disagreement · ${esc(key.replace(/_/g, ' '))}</div>
      <div class="mt-[2px] flex flex-wrap items-baseline gap-s3 text-answer text-ink">
        ${rec.map((x) => `<button type="button" class="cursor-pointer border-0 bg-transparent p-0 text-left"
            data-members="${esc(x.analysis)}" data-metric="${esc(key)}" data-title="${esc(key.replace(/_/g, ' '))}" data-when="${esc(when || '')}">
            <strong class="tnum font-semibold">${esc(fmtScalar(x.value, key))}</strong>
            <span class="font-mono text-provenance text-ink-muted">${esc(x.analysis)} ›</span></button>`).join('')}
      </div>
      <div class="text-caveat text-ink-muted">${rec.length} analyses report this name with different values; they may not be measuring the same thing. Open either to see what each counted — the members list in the rail.</div>
    </div>`;
}

/** The section's state, for the anchor rail: the worst thing in it. */
function sectionState(q, answerEnv, facts, ids) {
  const known = (answerEnv && answerEnv.facts || []).filter((f) => f.is_known);
  if (ids.some((id) => facts.get(id)?.state === 'error')) return 'error';
  if (!known.length) return 'unrun';
  // A question the catalog itself calls `mixed` or `partial` is not answered
  // by its analyses reporting; they are pieces of an answer. A tick here
  // said "answered" over prose that said "nothing detects one", and the
  // glyph is the one people read. Half-filled, in the accent — attention,
  // not completion.
  if (q && (q.kind === 'mixed' || q.kind === 'partial')) return 'partial';
  return 'answered';
}

/* ── The third door: the things a count counted ──────────────────────────
 *
 * There are three "show me more" requests on this pane and only one had a
 * path. About the MEASUREMENT — where did 68 come from, has it changed,
 * re-run it — is the popup. A question nobody asked — is this safe for
 * customer data? — is chat. The one in the middle, and the most common:
 * WHICH 68? Which 18 advisories, which 90 files, which three sub-resources
 * were not worthy? Nothing opened that. The popup looked like the door and
 * opened the number's history instead, so a reader learned that 18 had been
 * 18 for a fortnight.
 *
 * Members render in the right rail, which on Analysis held an empty ask box
 * and eighteen hundred pixels of nothing. Click a count, the rail lists the
 * members; the centre column keeps its place. No modal, no navigation.
 *
 * Members nest — file → symbol today; endpoint → operation → schema when
 * those are measured — and PURPOSE decides how much of the tree you see:
 * intent to use wants the public surface, intent to maintain wants that
 * plus the internal structure. One tree, two default expansions, because
 * maintain is a superset. Only symbols carry a public/internal marker, and
 * that marker is inferred from naming — the rail says so.
 *
 * This is also where two disagreeing counts get settled: "open either to
 * see what each counted" was already the instruction on the disagreement
 * block, and until now it could not be followed.
 */
function memberScope() {
  return currentPurposes().includes('Maintain') ? 'all' : 'public';
}

/* ── Promotion: the selection becomes a thing someone acts on ────────────
 *
 * A member list is the first place in the product where a person looks at
 * THINGS rather than NUMBERS, and things are what you act on. "18" is not a
 * work item; "three of these have no fix" is.
 *
 * The filters ARE the selection. "Everything matching the thing I noticed"
 * should not need a click per row: a facet — a severity, a package — selects
 * its members in one. Hand-picking stays. Facets come from the fields the
 * annotation already stores; nothing is invented, which is also why "no
 * fix" is not one here — cve_scan does not record fix availability, and a
 * facet the data cannot back would select nothing and look broken.
 *
 * Three acts, and they are different: add to work list (I will deal with
 * this), raise RFA (someone must), note in journal (worth knowing — no
 * obligation, so the likeliest used). One provenance line, composed on the
 * server, travels with all three. The selection is a SNAPSHOT of names,
 * never a query: a work item that changes what it refers to when the scan
 * re-runs is unusable.
 *
 * No "ignore" / "accept risk" here. That is a disposition on the finding — a
 * judgement with an author and a date — and belongs to the perishable-field
 * machinery, not a toolbar.
 */
function facetsHtml(groups) {
  const leaf = groups.flatMap((g) => g.members.filter((m) => !m.children_key).map((m) => ({ ...m, group: g.name })));
  if (!leaf.length) return '';
  const byDetail = new Map();
  for (const m of leaf) if (m.detail) byDetail.set(m.detail, (byDetail.get(m.detail) || 0) + 1);
  const detailFacets = [...byDetail.entries()].filter(([, n]) => n < leaf.length).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const groupFacets = groups.filter((g) => g.members.some((m) => !m.children_key) && groups.length > 1).slice(0, 8);
  if (!detailFacets.length && !groupFacets.length) return '';
  return `<div class="mb-s2 flex flex-wrap items-baseline gap-x-s2 gap-y-[2px] text-caps">
    <span class="text-chrome-muted">select</span>
    ${detailFacets.map(([d, n]) => `<button data-facet-detail="${esc(d)}" class="cursor-pointer bg-transparent p-0 font-mono text-chrome-ink underline">${esc(d)} <span class="tnum text-chrome-muted">${n}</span></button>`).join('')}
    ${groupFacets.map((g) => `<button data-facet-group="${esc(g.name)}" class="cursor-pointer bg-transparent p-0 font-mono text-chrome-muted underline">${esc(g.name.split(' ')[0])} <span class="tnum">${g.members.filter((m) => !m.children_key).length}</span></button>`).join('')}
    <button data-facet-all class="cursor-pointer bg-transparent p-0 font-mono text-chrome-muted underline">all <span class="tnum">${leaf.length}</span></button>
    <button data-facet-none class="cursor-pointer bg-transparent p-0 text-chrome-muted underline">none</button>
  </div>`;
}

function wireSelection(out, { slug, analysisId, metric, data }) {
  const picks = () => [...out.querySelectorAll('[data-pick]:checked')];
  const footer = out.querySelector('#member-selection');
  let facet = '';
  const project = state.projects.find((x) => x.slug === slug);
  const total = data.total || 0;
  const runAt = state.enrichmentFacts?.[analysisId]?.last_run_at || data.run_at || '';

  const setFacet = (pred, label) => {
    out.querySelectorAll('[data-pick]').forEach((c) => { c.checked = pred(c); });
    facet = label;
    render();
  };
  out.querySelector('[data-facet-all]')?.addEventListener('click', () => setFacet(() => true, ''));
  out.querySelector('[data-facet-none]')?.addEventListener('click', () => setFacet(() => false, ''));
  out.querySelectorAll('[data-facet-detail]').forEach((b) => b.addEventListener('click', () =>
    setFacet((c) => c.dataset.detail === b.dataset.facetDetail, b.dataset.facetDetail)));
  out.querySelectorAll('[data-facet-group]').forEach((b) => b.addEventListener('click', () =>
    setFacet((c) => c.dataset.group === b.dataset.facetGroup, b.dataset.facetGroup.split(' ')[0])));
  out.querySelectorAll('[data-pick]').forEach((c) => c.addEventListener('change', () => { facet = ''; render(); }));

  function proposed(n) {
    const what = (metric || data.metric || 'members').replace(/_/g, ' ');
    return `${project?.display_name || slug} — ${n} ${what}${facet ? `, ${facet}` : ''}`;
  }
  function render() {
    const sel = picks();
    if (!sel.length) { footer.hidden = true; footer.innerHTML = ''; return; }
    footer.hidden = false;
    const keep = footer.querySelector('#promote-name')?.value;
    footer.innerHTML = `
      <div class="mb-[3px] text-caps text-chrome-ink"><span class="tnum">${sel.length}</span> selected${facet ? ` · ${esc(facet)}` : ''}
        <span class="text-chrome-muted">· from <span class="font-mono">${esc(analysisId)}</span>${runAt ? ` · ${esc(ago(runAt))}` : ''} · a snapshot, not a query</span></div>
      <input id="promote-name" type="text" value="${esc(keep && !keep.startsWith(project?.display_name || slug) ? keep : proposed(sel.length))}"
        class="mb-[4px] w-full rounded-sm border border-chrome-line bg-transparent px-[6px] py-[2px] text-caps text-chrome-ink">
      <div class="flex flex-wrap items-baseline gap-x-s3 gap-y-[2px] text-caps">
        <button data-promote="work_list" class="cursor-pointer bg-transparent p-0 text-accent-on-dark underline">add to work list</button>
        <button data-promote="rfa" class="cursor-pointer bg-transparent p-0 text-accent-on-dark underline">raise RFA</button>
        <button data-promote="journal" class="cursor-pointer bg-transparent p-0 text-accent-on-dark underline">note in journal</button>
        <span id="promote-status" class="text-chrome-muted"></span>
      </div>`;
    footer.querySelectorAll('[data-promote]').forEach((b) => b.addEventListener('click', async () => {
      const status = footer.querySelector('#promote-status');
      const members = picks().map((c) => c.dataset.pick);
      b.disabled = true; status.textContent = '…';
      try {
        const out2 = await promoteMembers(slug, analysisId, {
          action: b.dataset.promote, metric: metric || data.metric || '', members, total, facet, runAt,
          name: footer.querySelector('#promote-name').value.trim(),
        });
        // Say where it went, not "sent".
        const where = out2.work_list ? `work list ${out2.work_list}` : out2.rfa ? `RFA ${String(out2.rfa).slice(0, 8)}` : 'the journal';
        status.innerHTML = `<span class="text-state-ok-on-dark">→ ${esc(where)}</span>`;
      } catch (err) {
        b.disabled = false;
        status.innerHTML = `<span class="text-state-warn-on-dark">${esc(err.status === 401 ? 'sign in to promote' : err.message)}</span>`;
      }
    }));
  }
}

async function openMembers({ slug, analysisId, metric = '', title = '' }) {
  const out = $('rail-evidence');
  if (!out) return;
  const scope = state.memberScope || memberScope();
  out.innerHTML = `<div class="text-caps text-chrome-muted">Reading the members of ${esc(title || analysisId)}…</div>`;
  let data;
  try {
    data = await getMembers(slug, analysisId, { metric, scope });
  } catch (err) {
    out.innerHTML = `<div class="text-caps text-state-warn-on-dark">The members could not be read: ${esc(err.message)}</div>`;
    return;
  }
  const groups = data.groups || [];
  const shown = groups.reduce((n, g) => n + g.members.length, 0);
  out.innerHTML = `
    <div class="mb-s1 flex items-baseline gap-s2">
      <span class="font-heading uppercase tracking-caps text-caps text-accent-on-dark">Members</span>
      <span class="text-caps text-chrome-muted"><span class="tnum">${data.total}</span> · ${esc(data.title)}</span>
      <button data-act="close-members" class="ml-auto cursor-pointer bg-transparent text-caps text-chrome-muted underline">close</button>
    </div>
    <div class="mb-s2 text-caps text-chrome-muted">
      <span class="font-mono">${esc(data.analysis_id)}</span>
      · <button data-act="member-history" class="cursor-pointer bg-transparent text-accent-on-dark underline">measurement ›</button>
      · scope
      <button data-scope="public" aria-pressed="${scope === 'public'}" class="wl-chartchip cursor-pointer bg-transparent px-[4px] text-chrome-muted">use</button>
      <button data-scope="all" aria-pressed="${scope === 'all'}" class="wl-chartchip cursor-pointer bg-transparent px-[4px] text-chrome-muted">maintain</button>
      ${data.scope_honoured ? '' : `<span class="text-chrome-muted">· scope not applicable to this set</span>`}
    </div>
    ${data.note ? `<div class="mb-s2 text-caps text-chrome-muted">${esc(data.note)}</div>` : ''}
    ${facetsHtml(groups)}
    <div class="flex flex-col gap-s1">
      ${groups.map((g, gi) => `<details class="border-b border-chrome-line-soft pb-s1" ${gi < 3 ? 'open' : ''}>
        <summary class="cursor-pointer text-subtab text-chrome-ink"><span class="tnum">${g.count}</span> · ${esc(g.name)}</summary>
        <ul class="m-0 mt-[2px] list-none p-0 pl-s2">
          ${g.members.map((m) => `<li class="flex items-baseline gap-s2 py-[2px] text-caps">
            ${m.children_key ? '' : `<input type="checkbox" data-pick="${esc(m.name)}" data-group="${esc(g.name)}" data-detail="${esc(m.detail || '')}" class="shrink-0 accent-accent">`}
            ${m.children_key
              ? `<button data-children="${esc(m.children_key)}" class="cursor-pointer bg-transparent p-0 text-left font-mono text-chrome-ink underline">${esc(m.name)}</button>
                 <span class="text-chrome-muted tnum">${m.count ?? ''}</span>`
              : `<span class="min-w-0 break-all font-mono text-chrome-ink">${esc(m.name)}</span>`}
            ${m.detail ? `<span class="shrink-0 text-chrome-muted">${esc(m.detail)}</span>` : ''}
          </li>`).join('')}
          ${g.truncated ? `<li class="text-caps text-chrome-muted">and more — the first ${g.members.length} are shown</li>` : ''}
        </ul>
      </details>`).join('')}
    </div>
    ${shown < data.total && !groups.some((g) => g.truncated)
      ? `<div class="mt-s1 text-caps text-chrome-muted"><span class="tnum">${shown}</span> of <span class="tnum">${data.total}</span> listed; the rest are nested under what is shown</div>` : ''}
    <div class="mt-s2 text-caps text-chrome-muted">read from <span class="font-mono">${esc(data.source)}</span></div>
    <div id="member-selection" class="mt-s2 border-t border-chrome-line pt-s2" hidden></div>`;

  out.querySelector('[data-act="close-members"]')?.addEventListener('click', () => { out.innerHTML = ''; });
  wireSelection(out, { slug, analysisId, metric, data });
  out.querySelector('[data-act="member-history"]')?.addEventListener('click', () => openMeasurementDetail({
    slug, analysisId, title: title || analysisId, metric,
  }));
  out.querySelectorAll('[data-scope]').forEach((b) => b.addEventListener('click', () => {
    state.memberScope = b.dataset.scope;
    openMembers({ slug, analysisId, metric, title });
  }));
  // One level down, on demand: a file opens its symbols in place.
  out.querySelectorAll('[data-children]').forEach((b) => b.addEventListener('click', async () => {
    const li = b.closest('li');
    if (li.querySelector('ul')) { li.querySelector('ul').remove(); return; }
    b.textContent = `${b.textContent} …`;
    let rows;
    try { rows = (await getMemberChildren(slug, analysisId, b.dataset.children, { scope })).members || []; }
    catch (err) { rows = [{ name: `could not read: ${err.message}`, detail: '' }]; }
    b.textContent = b.textContent.replace(/ …$/, '');
    const ul = document.createElement('ul');
    ul.className = 'm-0 mt-[2px] w-full list-none p-0 pl-s3';
    ul.innerHTML = rows.map((m) => `<li class="flex items-baseline gap-s2 py-[1px] text-caps">
        <span class="min-w-0 break-all font-mono text-chrome-ink">${esc(m.name)}</span>
        ${m.detail ? `<span class="shrink-0 text-chrome-muted">${esc(m.detail)}</span>` : ''}</li>`).join('')
      || `<li class="text-caps text-chrome-muted">nothing at this level</li>`;
    li.appendChild(ul);
  }));
  // The rail may be closed on a narrow shell; a members request opens it.
  if (typeof setRailOpen === 'function') setRailOpen(true);
}

async function renderDashboardByQuestion(slug, stage, host, live) {
  host.innerHTML = `<span class="text-caveat text-ink-muted">Reading the questions…</span>`;
  let questions;
  try {
    const res = await getQuestions(slug, {
      phase: stage, perspectives: [...state.activePerspectives], purposes: currentPurposes(),
    });
    questions = res.questions || [];
  } catch (err) {
    if (live()) host.innerHTML = `<span class="text-state-warn">The questions could not be read: ${esc(err.message)}</span>`;
    return;
  }
  if (!live()) return;
  rememberRationales(questions);

  const measured = questions.filter((q) => (q.analysis_ids || []).length);
  const unmeasured = questions.length - measured.length;
  const asked = new Set(measured.flatMap((q) => q.analysis_ids || []));

  let stageIds = [];
  try {
    const cat = await listAnalyses('repo', { intent: stage });
    stageIds = (cat.analyses || cat || []).map((a) => a.id || a.analysis_id).filter(Boolean);
  } catch (_) { /* the trailing section is then just what the questions named */ }
  const unasked = stageIds.filter((id) => !asked.has(id));

  host.innerHTML = `<span class="text-caveat text-ink-muted">Reading ${asked.size + unasked.length} measurements…</span>`;
  const facts = new Map();
  let answers;
  try {
    // The facts, and — rule 1 — each question's ANSWER from the same layer
    // the Evidence rail reads. Fetched together; the answers are per
    // question and independent, so a slow one does not hold the rest.
    const [res, envs, ctx] = await Promise.all([
      getBulkFacts([slug], [...asked, ...unasked]),
      Promise.allSettled(measured.map((q) => getAnswer(slug, q.question))),
      getContext('repo', slug).catch(() => ({})),
    ]);
    state.contextAnswers = ctx?.question_answers || {};
    for (const f of (res.subjects || {})[slug] || []) facts.set(f.analysis_id, f);
    answers = envs.map((e) => (e.status === 'fulfilled' ? e.value : null));
  } catch (err) {
    if (live()) host.innerHTML = `<span class="text-state-warn">The measurements could not be read: ${esc(err.message)}</span>`;
    return;
  }
  if (!live()) return;

  const disputes = findDisputes(facts);
  const disputeShownIn = new Map();     // key -> question index that rendered it
  const shownWhole = new Map();
  const sections = measured.map((q, qi) => {
    const ids = q.analysis_ids || [];
    const env = answers[qi];
    const declared = (q.checks || []).map((c) => String(c).split(':'));
    const checksFor = (id) => {
      const mine = declared.filter(([a]) => a === id).map(([, c]) => c).filter(Boolean);
      return mine.length ? new Set(mine) : null;
    };

    // Rule 1: the answer sentence, relayed from the answer layer — the same
    // one the Evidence rail shows. `lines.answer` is already HTML, escaped
    // by readEnvelope branch by branch, so it is NOT escaped again here.
    // Where the layer has nothing, say what was looked in — "0 of 3
    // reported" is a state. A human-answered question is a different case:
    // its answer is what a person said, and the analyses under it are
    // informants, not the answer.
    const lines = env ? readEnvelope(q, env) : null;
    const reported = ids.filter((id) => facts.get(id)?.state === 'measured').length;
    const human = q.kind === 'human' ? (state.contextAnswers || {})[questionKey(q.question)] : null;
    const answerLine = human && human.answer
      ? `<p class="mt-[2px] max-w-[70ch] text-answer text-ink">${tnum(esc(human.answer))}
           <span class="text-provenance text-ink-muted">· answered <span class="tnum">${esc(ago(human.answered_at))}</span></span></p>`
      : q.kind === 'human'
        ? `<p class="mt-[2px] text-answer text-ink-muted">needs a person to answer — the analyses below inform it, they do not decide it</p>`
      : lines && lines.answer
        ? `<p class="mt-[2px] max-w-[70ch] text-answer text-ink">${lines.answer}</p>`
        : `<p class="mt-[2px] text-answer text-ink-muted">not answered — <span class="tnum">${reported}</span> of <span class="tnum">${ids.length}</span> analyses reported</p>`;

    // Rule 4: the section's disagreements, once, above the detail.
    const mine = [...disputes].filter(([, rec]) => rec.some((x) => ids.includes(x.analysis)));
    const disputeBlocks = mine.map(([key, rec]) => {
      const prior = disputeShownIn.get(key);
      if (prior !== undefined) {
        return `<div class="mt-s2 text-caveat text-state-warn">Same disagreement on <em>${esc(key.replace(/_/g, ' '))}</em> as under
          <a href="#dq-${prior}" class="text-accent-ink underline">${esc(measured[prior].question)}</a>.</div>`;
      }
      disputeShownIn.set(key, qi);
      return disputeHtml(key, rec, facts.get(rec[0].analysis)?.last_run_at);
    }).join('');

    const body = ids.map((id) => {
      const checks = checksFor(id);
      if (!checks) {
        const prior = shownWhole.get(id);
        if (prior !== undefined && prior !== qi) {
          return `<div class="mt-s2 text-caveat text-ink-muted"><span class="font-mono">${esc(id)}</span> · shown in full under
            <a href="#dq-${prior}" class="text-accent-ink underline">${esc(measured[prior].question)}</a></div>`;
        }
        shownWhole.set(id, qi);
      }
      return analysisUnderQuestionHtml(facts.get(id), id, checks);
    }).join('');

    // Rule 3: provenance at section level.
    const nMeasures = ids.reduce((n, id) => {
      const v = facts.get(id)?.value; if (!v || typeof v !== 'object') return n;
      return n + (Array.isArray(v.findings) ? v.findings.length : 0)
        + Object.entries(v).filter(([k, x]) => k !== 'findings' && (typeof x === 'number' || typeof x === 'boolean')).length;
    }, 0);
    const st = sectionState(q, env, facts, ids);
    // Separation (Repo Handoff, item 2): a hairline above every question with
    // air above it, the glyph out in the margin, and weight in the order the
    // reader needs — the answer heaviest, the question next, the meta last.
    return `<section id="dq-${qi}" class="mt-s4 border-t border-rule pt-s3 scroll-mt-[8px]">
      <div class="flex items-baseline gap-s2 -ml-[22px] pl-0">
        <span class="w-[22px] shrink-0 text-right ${tone(st, 'paper')}">${GLYPH[st] || '·'}</span>
        <div class="min-w-0 flex-1">
          <div class="text-answer text-ink">${esc(q.question)}</div>
          ${answerLine.replace('text-answer text-ink"', 'text-answer font-semibold text-ink"')}
          <div class="text-provenance text-ink-muted"><span class="tnum">${ids.length}</span> analys${ids.length === 1 ? 'is' : 'es'} ·
            <span class="tnum">${nMeasures}</span> measurements${lines && lines.lastRun ? ` · latest ${esc(ago(lines.lastRun))}` : ''}</div>
        </div>
      </div>
      ${q.rationale ? `<p class="mt-[2px] max-w-[70ch] pl-[22px] text-caveat text-accent-ink">${esc(q.rationale)}</p>` : ''}
      ${q.catalog_history ? `<details class="pl-[22px]"><summary class="cursor-pointer text-provenance text-ink-muted">catalog history</summary>
        <p class="mt-[2px] max-w-[70ch] text-provenance text-ink-muted">${esc(q.catalog_history)}</p></details>` : ''}
      ${disputeBlocks}
      <details class="mt-s1"><summary class="cursor-pointer text-caveat text-ink-muted">detail</summary>${body}</details>
    </section>`;
  });

  const trailing = unasked.length ? `<section id="dq-unasked" class="mb-s5 border-t border-dashed border-rule-strong pt-s3">
      <div class="text-caps uppercase tracking-caps text-ink-muted">Measured, but no question asks ·
        <span class="tnum">${unasked.length}</span></div>
      <p class="mt-[2px] max-w-[70ch] text-caveat text-ink-muted">These analyses run at this stage and
        nothing in the question catalog names them. Either a question is missing, or the analysis is
        evidence for a judgement rather than an answer to a question. Listed so the gap is a fact
        rather than a surprise.</p>
      ${unasked.map((id) => {
        const f = facts.get(id); const g = f ? factGlyph(f.state) : { glyph: '·', tone: 'text-ink-muted' };
        return `<details class="mt-s2"><summary class="flex cursor-pointer items-baseline gap-s2 list-none">
            <span class="w-[16px] shrink-0 ${g.tone}">${g.glyph}</span>
            <span class="min-w-0 flex-1 text-answer text-ink">${tnum(esc(f?.headline || f?.state || 'not read'))}</span>
            <span class="shrink-0 font-mono text-provenance text-ink-muted">${esc(id)}${f?.last_run_at ? ` · ${esc(ago(f.last_run_at))}` : ''} ›</span>
          </summary><div class="pl-[22px]">${analysisUnderQuestionHtml(f, id, null)}</div></details>`;
      }).join('')}
    </section>` : '';

  // The anchor rail: five questions, five glyphs, jump to any. The same
  // vocabulary as the matrix, and the reason a 2,300-pixel page can be
  // seen whole.
  const rail = measured.length > 1 ? `<nav class="mb-s3 flex flex-wrap gap-x-s3 gap-y-[2px] text-caveat">
      ${measured.map((q, qi) => {
        const st = sectionState(q, answers[qi], facts, q.analysis_ids || []);
        return `<a href="#dq-${qi}" class="text-ink no-underline"><span class="${tone(st, 'paper')}">${GLYPH[st] || '·'}</span> ${esc(q.question)}</a>`;
      }).join('')}${unasked.length ? `<a href="#dq-unasked" class="text-ink-muted no-underline">· unasked (${unasked.length})</a>` : ''}
    </nav>` : '';

  host.innerHTML = `<div class="mb-s2 text-caveat text-ink-muted">
      <span class="tnum">${questions.length}</span> question${questions.length === 1 ? '' : 's'} at this stage ·
      <span class="tnum">${measured.length}</span> measured${
      unmeasured ? ` · <span class="tnum">${unmeasured}</span> answered another way — a direct fact, a person, or not yet` : ''}${
      unasked.length ? ` · <span class="tnum">${unasked.length}</span> measured and unasked` : ''}${
      disputes.size ? ` · <span class="text-state-warn tnum">${disputes.size}</span> disagreement${disputes.size === 1 ? '' : 's'}` : ''}
      ${purposeLegendHtmlFor(questions)}</div>
    ${rail}
    ${sections.join('') || `<p class="text-caveat text-ink-muted">No question at this stage names an analysis.</p>`}
    ${trailing}`;

  host.querySelectorAll('[data-measure]').forEach((n) => {
    n.addEventListener('click', () => openMeasurementDetail({
      slug, analysisId: n.dataset.measure, title: n.dataset.title || n.dataset.measure,
      metric: n.dataset.metric || '', summary: n.dataset.summary || '', when: n.dataset.when || '',
    }));
  });
  host.querySelectorAll('[data-members]').forEach((n) => {
    n.addEventListener('click', () => openMembers({
      slug, analysisId: n.dataset.members, metric: n.dataset.metric || '', title: n.dataset.title || n.dataset.members,
    }));
  });
  host.querySelectorAll('[data-goto-worklist]').forEach((b) => b.addEventListener('click', () => {
    state.stage = 'investigation';
    writeUrl();
    renderIntentNav();
    loadPane();
  }));
  for (const n of host.querySelectorAll('[data-delta]')) {
    const [analysisId] = n.dataset.delta.split('|');
    deltaFor(slug, analysisId).then((text) => {
      if (!live()) return;
      n.textContent = text || '';
      n.className = text === 'first measurement' ? 'block text-provenance text-ink-muted' : 'block text-provenance text-ink';
    });
  }
}

/** The purpose legend for a question list that is not `state.questions`. */
function purposeLegendHtmlFor(questions) {
  const purposes = currentPurposes();
  if (!purposes.length || !questions.length) return '';
  const lead = questions.filter((q) => q.derivation?.purpose_ranked).length;
  if (!lead) return `· <span class="text-ink-muted">none serve ${esc(purposes.join(', '))}</span>`;
  return `· <span class="text-ink-muted">ordered by purpose · ${esc(purposes.join(', '))} · <span class="tnum">${lead}</span> lead</span>`;
}

function dashView() {
  try { return localStorage.getItem(DASH_VIEW_KEY) === 'analysis' ? 'analysis' : 'question'; } catch { return 'question'; }
}

async function loadDashboardPane() {
  const el = $('content');
  const blocked = paneNeedsRepo();
  if (blocked) { el.innerHTML = subTabsHtml() + blocked; bindSubTabs(); return; }
  const slug = state.selectedSlug;
  const stage = state.stage;

  // Two independent reads, each filling its own region as it lands. They were
  // a Promise.all, which showed one line for as long as the slowest took —
  // and on Analysis the dashboards read costs 109s.
  const token = ++dashToken;
  const view = dashView();
  el.innerHTML = subTabsHtml() + `
    <div class="mb-s3 flex flex-wrap items-baseline gap-s3">
      <span class="text-caps uppercase tracking-caps text-ink-muted">Survey results · ${esc(stage)}</span>
      <span class="ml-auto flex gap-[6px] text-caveat">
        <button type="button" data-dashview="question" aria-pressed="${view === 'question'}"
          class="wl-chartchip cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[1px]">by question</button>
        <button type="button" data-dashview="analysis" aria-pressed="${view === 'analysis'}"
          class="wl-chartchip cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[1px]">by analysis</button>
      </span>
    </div>
    <div id="dash-boards" class="text-caveat text-ink-muted">Reading the dashboards…</div>`;
  bindSubTabs();
  el.querySelectorAll('[data-dashview]').forEach((b) => b.addEventListener('click', () => {
    try { localStorage.setItem(DASH_VIEW_KEY, b.dataset.dashview); } catch { /* per-viewer convenience only */ }
    loadDashboardPane();
  }));

  const live = () => token === dashToken && state.subTab === 'dashboard';

  if (view === 'question') {
    await renderDashboardByQuestion(slug, stage, $('dash-boards'), live);
    return;
  }

  let data;
  try {
    data = await getSurveyDashboards(slug, stage, { includeEmpty: true });
  } catch (err) {
    if (live()) $('dash-boards').innerHTML =
      `<span class="text-state-warn">The dashboards could not be read: ${esc(err.message)}</span>`;
    return;
  }
  if (!live()) return;
  const boards = data.dashboards || [];
  if (!boards.length) {
    $('dash-boards').innerHTML = `No dashboard is registered for ${esc(stage)}.`;
    return;
  }

  // Every measurement on the pane, so a NAME REPORTED TWICE WITH DIFFERENT
  // VALUES can be marked where it is displayed rather than left for a reader
  // to notice or not.
  const seen = new Map();
  for (const b of boards) {
    for (const a of b.analyses || []) {
      for (const [k, v] of Object.entries(a.results || {})) {
        if (typeof v !== 'number') continue;
        const rec = seen.get(k) || [];
        rec.push({ analysis: a.analysis_id, value: v });
        seen.set(k, rec);
      }
    }
  }
  const disputed = new Map();
  for (const [k, rec] of seen) {
    if (rec.length > 1 && new Set(rec.map((x) => x.value)).size > 1) disputed.set(k, rec);
  }

  $('dash-boards').innerHTML = boards.map((b) => {
    const analyses = b.analyses || [];
    // THE GROUP HEADER CARRIES NO DATE. "Health & Maturity — measured 12h ago"
    // over cards from three analyses is the per-resource as-of date deleted
    // from the matrix, returned one level up. Dates belong on measurements.
    const headline = analyses.find((a) => typeof (a.results || {}).overall === 'number');
    const findings = [];
    const counts = [];
    for (const a of analyses) {
      const res = a.results || {};
      if (a === headline) continue;
      if (Array.isArray(res.findings) && res.findings.length) {
        for (const f of res.findings) findings.push({ ...f, analysis_id: a.analysis_id, when: a.last_surveyed_at });
        continue;
      }
      for (const [k, v] of Object.entries(res)) {
        if (typeof v === 'number' || typeof v === 'boolean') {
          counts.push({ key: k, value: v, analysis_id: a.analysis_id, when: a.last_surveyed_at });
        }
      }
    }
    findings.sort((x, y) => {
      const ux = UNRESOLVED_LABELS.has(String(x.label || '').toLowerCase()) ? 0 : 1;
      const uy = UNRESOLVED_LABELS.has(String(y.label || '').toLowerCase()) ? 0 : 1;
      return ux - uy;
    });

    return `
      <section class="mb-s5">
        <div class="text-answer text-ink">${esc(b.title || b.id)}</div>
        ${b.description ? `<p class="mt-[2px] max-w-[70ch] text-caveat text-ink-muted">${esc(b.description)}</p>` : ''}
        ${!b.has_results ? `<p class="mt-s1 text-caveat text-state-warn">Registered, never run.</p>` : ''}

        ${headline ? headlineHtml(headline) : ''}

        ${findings.length ? `
          <div class="mt-s3 text-caps uppercase tracking-caps text-ink-muted">Findings · unresolved first</div>
          ${findings.map((f) => {
            const c = findingGlyph(f.label);
            return `<button type="button" class="flex w-full items-baseline gap-s2 border-0 border-b border-rule bg-transparent px-0 py-s2 text-left"
              data-measure="${esc(f.analysis_id)}" data-check="${esc(f.check_name || '')}"
              data-title="${esc((f.check_name || f.analysis_id).replace(/_/g, ' '))}"
              data-summary="${esc(f.summary || '')}" data-when="${esc(f.when || '')}">
              <span class="w-[16px] shrink-0 ${c.tone}" title="${esc(c.label)}">${c.glyph}</span>
              <span class="min-w-0 flex-1 text-ink">
                <strong class="font-semibold">${
                  f.check_name
                    ? `${esc(f.check_name.replace(/_/g, ' '))}${
                        f.label ? ` — ${esc(humanLabel(f.label))}` : ''}`
                    : esc(humanLabel(f.label) || f.analysis_id)}.</strong>
                ${f.summary ? ` ${tnum(esc(f.summary))}` : ''}
                <span class="block text-provenance text-ink-muted"
                  data-delta="${esc(f.analysis_id)}|${esc(f.check_name || '')}">·</span></span>
              <span class="shrink-0 font-mono text-provenance text-ink-muted">${esc(f.analysis_id)}${
                f.when ? ` · ${esc(ago(f.when))}` : ''} ›</span>
            </button>`;
          }).join('')}` : ''}

        ${counts.length ? `
          <div class="mt-s3 text-caps uppercase tracking-caps text-ink-muted">Counts</div>
          <table class="w-full border-collapse text-caveat">
            ${(() => {
              // A disputed name is ONE row carrying every value, not one row
              // per analysis saying the same thing mirrored.
              const shown = new Set();
              return counts.map((c) => {
                const rec = disputed.get(c.key);
                if (rec) {
                  if (shown.has(c.key)) return '';
                  shown.add(c.key);
                  return `<tr class="border-b border-rule bg-[rgba(168,113,42,.07)]">
                    <td class="py-[5px] pr-s3 text-ink"><span class="text-state-warn">⚠</span>
                      ${esc(c.key.replace(/_/g, ' '))}
                      <span class="text-provenance text-ink-muted">— <span class="tnum">${
                        rec.length}</span> analyses report this name with different values;
                        they may not be measuring the same thing</span></td>
                    <td class="tnum py-[5px] pr-s3 text-right text-ink">${
                      esc(rec.map((x) => fmtScalar(x.value, c.key)).join(' / '))}</td>
                    <td class="py-[5px] text-right font-mono text-provenance text-ink-muted">${
                      esc(rec.map((x) => x.analysis).join(' / '))}</td>
                  </tr>`;
                }
                // Two analyses AGREEING on a name is one fact, not two rows.
                // Both are named, so the agreement itself stays visible.
                if (shown.has(c.key)) return '';
                shown.add(c.key);
                const agree = (seen.get(c.key) || []).filter((x) => x.analysis !== c.analysis_id);
                return `<tr class="wl-countrow cursor-pointer border-b border-rule"
                  data-measure="${esc(c.analysis_id)}" data-metric="${esc(c.key)}"
                  data-title="${esc(c.key.replace(/_/g, ' '))}" data-when="${esc(c.when || '')}">
                  <td class="py-[5px] pr-s3 text-ink">${esc(c.key.replace(/_/g, ' '))}</td>
                  <td class="tnum py-[5px] pr-s3 text-right text-ink">${esc(fmtScalar(c.value, c.key))}</td>
                  <td class="py-[5px] text-right font-mono text-provenance text-ink-muted">${
                    esc([c.analysis_id, ...agree.map((x) => x.analysis)].join(' · '))}${
                    c.when ? ` · ${esc(ago(c.when))}` : ''}</td>
                </tr>`;
              }).join('');
            })()}
          </table>` : ''}
      </section>`;
  }).join('');

  // EVERY MEASUREMENT OPENS THE SAME DETAIL. Three entry points, one
  // component — a dashboard finding, a count, and the matrix cell popup.
  $('dash-boards').querySelectorAll('[data-measure]').forEach((n) => {
    n.addEventListener('click', () => openMeasurementDetail({
      slug,
      analysisId: n.dataset.measure,
      title: n.dataset.title || n.dataset.measure,
      metric: n.dataset.metric || '',
      summary: n.dataset.summary || '',
      when: n.dataset.when || '',
    }));
  });

  // Inline deltas, from the same series the detail uses. Filled after render
  // so a slow trend read never delays the pane.
  for (const n of $('dash-boards').querySelectorAll('[data-delta]')) {
    const [analysisId] = n.dataset.delta.split('|');
    deltaFor(slug, analysisId).then((text) => {
      if (!live()) return;
      n.textContent = text || '';
      n.className = text === 'first measurement'
        ? 'block text-provenance text-ink-muted'
        : 'block text-provenance text-ink';
    });
  }
}

/** The composed score, once, at size — with its own sub-scores beside it.
 *
 * The radar chart is GONE. `repository_health` composes four sub-scores on
 * 0–100; the chart plotted five different axes on 0–10, on white, in a
 * foreign typeface — two incompatible definitions of the same word forty
 * pixels apart. If it returns it plots these four, on their own scale, in
 * this app's palette, and is then a picture of the number rather than a rival
 * to it.
 *
 * The summary tiles are gone for the same reason: they rendered `Health
 * 82/100` while the card below said `82.2` — one measurement at two
 * precisions, which costs trust in both.
 */
function headlineHtml(a) {
  const r = a.results || {};
  const subs = Object.entries(r)
    .filter(([k, v]) => k !== 'overall' && typeof v === 'number')
    .slice(0, 6);
  return `<div class="mt-s3 flex flex-wrap items-baseline gap-s5 border-b border-rule pb-s3">
    <div>
      <div class="text-caps uppercase tracking-caps text-ink-muted">${
        esc((a.analysis_id || '').replace(/_/g, ' '))}</div>
      <div class="tnum font-heading text-ink" style="font-size:44px;line-height:1.05">${
        esc(fmtScalar(r.overall))}</div>
    </div>
    <div class="text-caveat text-ink">
      ${subs.map(([k, v]) => `<span class="mr-s3">${esc(k.replace(/_/g, ' '))}
        <strong class="tnum font-semibold">${esc(fmtScalar(v))}</strong></span>`).join('')}
      <div class="mt-[3px] font-mono text-provenance text-ink-muted">${esc(a.analysis_id)}${
        a.last_surveyed_at ? ` · ${esc(ago(a.last_surveyed_at))}` : ''}</div>
    </div>
  </div>`;
}

/** A stored value rendered as what it IS, not as the number that stores it.
 *
 *  `was 21438268 8d ago` on ~40 sub_resource_survey rows was the defect: that
 *  is `total_size_bytes`, and 21,438,268 is a correct number that nobody can
 *  read as 21.4 MB at a glance. The formatter had no way to know, because it
 *  was handed the value and not the name — every call site HAD the name in
 *  scope and none passed it.
 *
 *  Rules, in order:
 *  - booleans as words;
 *  - a name ending in `bytes` renders as a size (B / KB / MB / GB / TB, one
 *    decimal above KB);
 *  - an integer at or above 1,000 gets digit grouping, so a count of files is
 *    read as a count and not as a code;
 *  - everything else to one decimal, as before.
 *
 *  Only the name's SUFFIX is read. Anything cleverer — guessing a unit from a
 *  magnitude — is exactly how a byte count becomes a "score" somewhere. With
 *  no name, only the grouping rule can apply: a bare 21,438,268 is still
 *  better than 21438268, and grouping is never wrong the way a unit can be. */
function fmtScalar(v, name = '') {
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (v == null || v === '') return '';
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (/bytes$/i.test(name)) return fmtBytes(n);
  if (Number.isInteger(n) && Math.abs(n) >= 1000) return n.toLocaleString('en-US');
  return String(Math.round(n * 10) / 10);
}

function fmtBytes(n) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let x = Math.abs(n);
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i += 1; }
  const shown = i === 0 ? String(Math.round(x)) : (Math.round(x * 10) / 10).toFixed(1);
  return `${n < 0 ? '-' : ''}${shown} ${units[i]}`;
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

  // The ordering legend sits beside the state key, not inside it: the key
  // says what the glyphs mean, this says why the rows are in this order.
  // Separated by a middle dot so it reads as a second clause, not a seventh
  // glyph.
  const order = purposeLegendHtml();
  el.innerHTML = items.length
    ? `<span class="text-caps uppercase tracking-caps text-ink-muted">Key</span>${items.join('')}${
      order ? `<span class="text-ink-muted">·</span>${order}` : ''}`
    : order;
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

  if (state.subTab === 'survey') { await loadSurveyPane(); return; }
  if (state.subTab === 'dashboard') { await loadDashboardPane(); return; }
  if (state.subTab === 'disposition') { await loadDispositionPane(); return; }

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
      <span id="answered-count" class="tnum text-caveat text-ink-muted">loading…</span>
    </div>
    <div id="state-legend" class="mt-s2 flex flex-wrap items-baseline gap-s3 text-caveat"></div>
    <div class="my-s3 h-px bg-rule"></div>
    <div id="enrichment-form"></div>
    <div id="question-rows"></div>`;
  bindSubTabs();
  bindResourceHeader();

  let checklist;
  try {
    checklist = await getQuestions(slug, {
      phase: state.stage,
      perspectives: [...state.activePerspectives],
      purposes: currentPurposes(),
    });
  } catch (err) {
    $('question-rows').innerHTML = `<div class="py-s3 text-answer text-accent-ink">
      The checklist could not be loaded: ${esc(err.message)}</div>`;
    return;
  }
  if (slug !== state.selectedSlug) return;   // a faster click won

  state.questions = checklist.questions || [];
  rememberRationales(state.questions);

  // Human answers for this resource, so a `human` row can show what was
  // already said rather than offering a blank box over the top of it. A
  // failure here leaves the rows answerable and unanswered, which is the
  // truthful degradation: we could not read them, so we do not claim any.
  try {
    const ctx = await getContext('repo', slug);
    state.contextAnswers = ctx?.question_answers || {};
    state.enrichment = ctx?.enrichment || {};
  } catch {
    state.contextAnswers = {};
    state.enrichment = {};
  }

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
  wireHumanAnswers(rows, slug);
  if (state.stage === 'enrichment') renderEnrichment(slug);
  updateAnsweredCount();
  renderLegend();

  // Fetch each answer independently and replace its row as it lands.
  state.answers.clear();
  state.questions.forEach((q, i) => loadAnswer(q, i, slug));
}

/* ── Answering a question that only a person can answer ───────────────────
 *
 * Seven catalog questions are Human-Supplied: do we already support these
 * dependencies, what does it cost to run, do we have the skills, does it fit
 * our monitoring / security / governance, does it fit or extend the estate.
 * They had nowhere to be stored — the Enrichment context form holds
 * environment, sensitivity, backup status and location, none of which appears
 * in the catalog at all — so the rows said "not built in /next" and stopped.
 *
 * Delegated from the container because rows re-render independently as their
 * answers land; binding per row would attach to elements that are about to be
 * replaced. Attached ONCE and marked, because the pane re-renders on every
 * perspective toggle and a second listener would save twice per click — the
 * same stacked-listener bug the sidebar toggle had.
 */
function wireHumanAnswers(host, slug) {
  if (host.dataset.humanWired === '1') return;
  host.dataset.humanWired = '1';
  host.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-human-edit]');
    if (!btn) return;
    const question = btn.getAttribute('data-human-edit');
    const key = questionKey(question);
    const prior = (state.contextAnswers || {})[key]?.answer || '';
    const next = window.prompt(question, prior);
    if (next === null) return;              // cancelled — not an empty answer
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
      await saveQuestionAnswer('repo', slug, question, next.trim());
      state.contextAnswers = {
        ...(state.contextAnswers || {}),
        [key]: { question, answer: next.trim(), answered_at: new Date().toISOString() },
      };
      // Redraw just this row, the way an arriving answer does. A whole-pane
      // reload would refetch every other answer to show one that is already
      // in hand.
      const i = state.questions.findIndex((q) => q.question === question);
      if (i >= 0) replaceRow(state.questions[i], i, state.answers.get(question));
    } catch (err) {
      // Left on the button rather than raised as a page error: the failure is
      // this one save, and the rest of the checklist is unaffected.
      btn.disabled = false;
      btn.textContent = err.status === 401 ? 'Not signed in' : `Not saved: ${err.message}`;
      setTimeout(() => { btn.textContent = label; }, 4000);
    }
  });
}

/* ── Enrichment: testimony, not paperwork ──────────────────────────────────
 *
 * Two halves, not one list of eight fields with one Save. The line between
 * them is not arbitrary: a field is a JUDGEMENT if a person's opinion is the
 * value — sensitivity, criticality, intended use, actual use, owner — and an
 * OBSERVATION if a person is supplying a fact about the world — licence,
 * environment, retention. Opinions need an author, a date and a review
 * state. Observations need a source.
 *
 * Judgements come first and get the room: they are the part only a person
 * can supply. Every field saves alone — someone who knows the owner and not
 * the sensitivity can say so and leave. The author and date sit on every
 * judgement without hovering, because testimony without an author is not
 * testimony, and because that is what makes review meaningful later.
 *
 * Perishability, which needs no per-field configuration: a judgement carries
 * the measurements that were on screen when it was made. When one of those
 * moves, the judgement is not invalidated — it gets a flag that says what
 * moved. "⚠ review — evidence moved: cve_scan" is a specific, answerable
 * prompt, not a staleness timer.
 *
 * Evidence sits in the rail as MATERIAL, never as proposals. No "apply
 * suggestion". The one exception is a fact a survey already established —
 * the licence — which is offered to confirm, with its source, into the
 * observations half.
 *
 * Nothing here is written to the catalogue until Curate. That sentence is
 * the one misconception worth pre-empting, and it is on the pane.
 */
const JUDGEMENTS = [
  { key: 'sensitivity',  label: 'Sensitivity',  options: ['public', 'internal', 'confidential', 'restricted'] },
  { key: 'criticality',  label: 'Criticality',  options: ['low', 'important', 'critical'] },
  { key: 'intended_use', label: 'Intended use', placeholder: 'what is this for, here?' },
  { key: 'actual_use',   label: 'Actual use',   placeholder: 'how is it used today?' },
  { key: 'owner',        label: 'Owner',        placeholder: 'who answers for it?' },
];
const OBSERVATIONS = [
  { key: 'licence',      label: 'Licence',      fromAnalysis: 'license_classification' },
  { key: 'environment',  label: 'Environment',  options: ['prod', 'dev', 'test', 'research', 'archive'] },
  { key: 'retention',    label: 'Retention',    placeholder: 'how long, and by whose rule?' },
];
// The analyses whose current state is the evidence for a judgement.
const ENRICHMENT_EVIDENCE = ['interface_surface', 'security_scan', 'chaoss_metrics', 'cve_scan',
  'repository_health', 'license_classification', 'secret_scan', 'documentation_coverage'];

function evidenceSnapshot() {
  const snap = {};
  for (const [id, f] of Object.entries(state.enrichmentFacts || {})) if (f.last_run_at) snap[id] = f.last_run_at;
  return snap;
}

/** Which of a judgement's evidence has moved since it was made. */
function movedSince(field) {
  const moved = [];
  for (const [id, at] of Object.entries(field.evidence || {})) {
    const now = state.enrichmentFacts?.[id]?.last_run_at;
    // Instants, not strings: `Z`, `+00:00` and naive stamps all occur, and
    // a string compare between spellings fires or fails on the suffix.
    if (now && whenMs(now) > whenMs(at)) moved.push(id);
  }
  return moved;
}

function fieldControlHtml(def, field, kind = 'judgement') {
  const v = field?.value || '';
  // Judgements are the larger set on purpose; the recorded facts sit a
  // step down, at provenance size, so the split is visible, not narrated.
  const size = kind === 'judgement' ? 'text-answer' : 'text-provenance';
  if (def.options) {
    return `<select data-field="${def.key}" class="rounded-sm border border-rule-strong bg-transparent px-[6px] py-[2px] ${size} text-ink">
      <option value="">—</option>
      ${def.options.map((o) => `<option value="${o}" ${o === v ? 'selected' : ''}>${o}</option>`).join('')}
    </select>`;
  }
  return `<input data-field="${def.key}" type="text" value="${esc(v)}" placeholder="${esc(def.placeholder || '')}"
    class="w-full rounded-sm border border-rule-strong bg-transparent px-[6px] py-[2px] ${size} text-ink placeholder:text-ink-muted">`;
}

function fieldRowHtml(def, kind) {
  const field = (state.enrichment || {})[def.key];
  const moved = field && kind === 'judgement' ? movedSince(field) : [];
  // Judgements carry an author; observations carry a source. The server
  // stamps `author` on every field, so a source-only branch was dead code
  // and a confirmed licence read as "alice · 2d ago" with its source stored
  // and invisible. Both halves render now, in that order.
  const when = field?.set_at ? `<span class="tnum">${esc(ago(field.set_at))}</span>` : '';
  const who = field?.author
    ? [kind === 'observation' && field.source ? `from ${esc(field.source)}` : '',
       `${esc(field.author)}${field.interim ? ' · interim' : ''}`, when].filter(Boolean).join(' · ')
    : '';
  const proposed = def.fromAnalysis && !field?.value ? proposedFrom(def.fromAnalysis) : null;
  // "What we judge" is the larger of the two sets -- the split's whole
  // argument -- so its labels are body size in ink, not caption size muted.
  const labelCls = kind === 'judgement' ? 'text-question font-heading text-ink' : 'text-provenance text-ink-muted';
  return `<div class="grid grid-cols-[130px_1fr] items-baseline gap-x-s3 gap-y-[2px] border-b border-rule py-s2">
    <div class="${labelCls}">${esc(def.label)}</div>
    <div class="min-w-0">
      <div class="flex items-baseline gap-s2">${fieldControlHtml(def, field, kind)}
        <button type="button" data-save="${def.key}" data-kind="${kind}"
          class="shrink-0 cursor-pointer rounded-sm border border-accent bg-transparent px-2 py-[1px] text-provenance text-accent-ink">save</button></div>
      <div class="text-provenance text-ink-muted">
        ${moved.length ? `<span class="text-state-warn">⚠ review — evidence moved: ${esc(moved.join(', '))}</span> · ` : ''}
        ${who}
        ${proposed ? `<span>from survey: <span class="text-ink">${esc(proposed.value)}</span> ·
          <button type="button" data-confirm="${def.key}" data-source="${esc(def.fromAnalysis)}" data-value="${esc(proposed.value)}"
            class="cursor-pointer bg-transparent p-0 text-accent-ink underline">confirm</button></span>` : ''}
      </div>
      ${def.key === 'owner' ? ownerNoteHtml(field) : ''}
    </div>
  </div>`;
}

/** Owner candidates from contributor data are DEFERRED, and a deferred
 *  affordance is marked, never omitted (the sub-tab rule, app.js above).
 *  Until one is named, the investigator stands as interim owner -- offered
 *  as a one-click act by the signed-in person, not inferred from a blank. */
function ownerNoteHtml(field) {
  const me = (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
  const offer = !field?.value && me
    ? ` · <button type="button" data-owner-interim="${esc(me)}"
        class="cursor-pointer bg-transparent p-0 text-accent-ink underline">stand as interim owner</button>`
    : '';
  return `<div class="text-provenance text-ink-muted"><span class="border-b border-dashed border-current">owner candidates
    from contributor data · not built in /next</span>${offer}</div>`;
}

/** A fact a survey already established, offered to confirm — not applied.
 *  Gated on a CLASSIFIED licence: "No license detected on this repository."
 *  is a measured finding too, and offering it to confirm would write that
 *  sentence into the licence field. The tier finding's label says which. */
function proposedFrom(analysisId) {
  const f = state.enrichmentFacts?.[analysisId];
  if (!f || f.state !== 'measured') return null;
  const tier = (f.value?.findings || []).find((x) => x.check_name === 'license_risk_tier');
  // `none` is both "no licence" and "nothing examined"; `unknown` is a
  // licence that IS present and unclassified -- its name is still a fact.
  if (!tier || !tier.label || String(tier.label) === 'none') return null;
  // The licence itself, not its risk tier: the finding's label is
  // "permissive" and its summary is "Apache License 2.0 — Permissive". The
  // part before the dash is the fact a person would confirm.
  const raw = tier.summary || f.headline || '';
  if (!raw.includes(' — ')) return null;
  const value = String(raw).split(' — ')[0].trim();
  return value ? { value } : null;
}

async function renderEnrichment(slug) {
  const host = $('enrichment-form');
  if (!host) return;
  host.innerHTML = `<div class="text-caveat text-ink-muted">Reading the evidence…</div>`;
  try {
    const res = await getBulkFacts([slug], ENRICHMENT_EVIDENCE);
    state.enrichmentFacts = Object.fromEntries(((res.subjects || {})[slug] || []).map((f) => [f.analysis_id, f]));
  } catch { state.enrichmentFacts = {}; }
  if (slug !== state.selectedSlug) return;

  const setJ = JUDGEMENTS.filter((d) => state.enrichment?.[d.key]?.value).length;
  const me = (state.me && (state.me.user_id || state.me.username || state.me.egeria_user)) || '';
  host.innerHTML = `
    <p class="mb-s3 max-w-[70ch] text-caveat text-ink-muted">Nothing here is written to the catalogue until you catalogue it (Curate).
      What you set here is testimony — yours, dated — and the surveys' findings in the rail are material to read, not answers to accept.</p>
    <div class="mb-s1 flex items-baseline gap-s2">
      <span class="font-heading text-question text-ink">What we judge</span>
      <span class="text-provenance text-ink-muted"><span class="tnum">${setJ}</span> of <span class="tnum">${JUDGEMENTS.length}</span> set · perishable</span>
    </div>
    ${JUDGEMENTS.map((d) => fieldRowHtml(d, 'judgement')).join('')}
    <div class="mb-s1 mt-s4 flex items-baseline gap-s2">
      <span class="text-caps uppercase tracking-caps text-ink">What we record</span>
      <span class="text-provenance text-ink-muted">durable</span>
    </div>
    ${OBSERVATIONS.map((d) => fieldRowHtml(d, 'observation')).join('')}
    <div class="mb-s1 mt-s4 text-caps uppercase tracking-caps text-ink">What only you can answer</div>
    <div class="mb-s2 text-provenance text-ink-muted">The catalog's own questions for a person, below — each saves alone.</div>`;

  host.querySelectorAll('[data-save]').forEach((b) => b.addEventListener('click', async () => {
    const key = b.dataset.save; const kind = b.dataset.kind;
    const ctl = host.querySelector(`[data-field="${key}"]`);
    const value = (ctl?.value || '').trim();
    b.disabled = true; b.textContent = 'saving…';
    try {
      const out = await saveEnrichmentField(slug, key, {
        value, kind, evidence: kind === 'judgement' ? evidenceSnapshot() : {},
        // Interim means "the investigator stands in", which is a person
        // naming themself -- not a blank. A blank owner is no owner.
        interim: key === 'owner' && !!value && value === me,
        source: kind === 'observation' ? 'user' : '',
      });
      state.enrichment = { ...(state.enrichment || {}), [key]: out.field };
      renderEnrichment(slug);
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 401 ? 'sign in to record' : `not saved: ${err.message}`;
    }
  }));
  host.querySelectorAll('[data-owner-interim]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'recording…';
    try {
      const out = await saveEnrichmentField(slug, 'owner', {
        value: b.dataset.ownerInterim, kind: 'judgement', evidence: evidenceSnapshot(), interim: true,
      });
      state.enrichment = { ...(state.enrichment || {}), owner: out.field };
      renderEnrichment(slug);
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 401 ? 'sign in to record' : `not recorded: ${err.message}`;
    }
  }));
  host.querySelectorAll('[data-confirm]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'confirming…';
    try {
      const out = await saveEnrichmentField(slug, b.dataset.confirm, {
        value: b.dataset.value, kind: 'observation', source: b.dataset.source,
      });
      state.enrichment = { ...(state.enrichment || {}), [b.dataset.confirm]: out.field };
      renderEnrichment(slug);
    } catch (err) {
      b.disabled = false;
      b.textContent = err.status === 401 ? 'sign in to record' : `not confirmed: ${err.message}`;
    }
  }));
  renderEnrichmentEvidence(slug);
}

/** The rail: evidence as material. Each analysis's own sentence, its age, and
 *  "new since you judged" where its run postdates the latest judgement that
 *  saw it — the perishability mechanism doing its job at the moment it is
 *  useful. */
function renderEnrichmentEvidence(slug) {
  const out = $('rail-evidence');
  if (!out) return;
  // Rail state is a persisted preference; "new since you judged" written
  // into a closed drawer is the perishability signal nobody sees.
  if (!railIsOpen()) setRailOpen(true);
  const judged = Object.values(state.enrichment || {}).filter((f) => f.kind === 'judgement' && f.set_at);
  const items = ENRICHMENT_EVIDENCE.map((id) => state.enrichmentFacts?.[id]).filter(Boolean);
  out.innerHTML = `
    <div class="mb-s1 flex items-baseline gap-s2">
      <span class="font-heading uppercase tracking-caps text-caps text-accent-on-dark">Evidence · enrichment</span>
      <span class="text-caps text-chrome-muted">for <span class="font-mono">${esc(slug)}</span> · material, not proposals</span>
    </div>
    ${items.length ? items.map((f) => {
      const g = factGlyph(f.state);
      const seen = judged.some((j) => j.evidence?.[f.analysis_id]);
      const fresh = judged.some((j) => j.evidence?.[f.analysis_id] && whenMs(f.last_run_at) > whenMs(j.evidence[f.analysis_id]));
      return `<div class="border-b border-chrome-line-soft py-[4px]">
        <div class="flex items-baseline gap-s2 text-subtab text-chrome-ink">
          <span class="${g.tone === 'text-state-ok' ? 'text-state-ok-on-dark' : g.tone === 'text-state-warn' ? 'text-state-warn-on-dark' : 'text-chrome-muted'}">${g.glyph}</span>
          <span class="min-w-0 flex-1">${tnum(esc(f.headline || f.state))}</span></div>
        <div class="pl-[20px] text-caps text-chrome-muted"><span class="font-mono">${esc(f.analysis_id)}</span>${
          f.last_run_at ? ` · <span class="tnum">${esc(ago(f.last_run_at))}</span>` : ''}${
          fresh ? ` · <span class="text-accent-on-dark">new since you judged</span>` : seen ? '' : ''}</div>
      </div>`;
    }).join('') : `<div class="text-caps text-chrome-muted">No measurements to show yet.</div>`}
    <div class="mt-s2 text-caps text-chrome-muted">Material to read, not answers to accept. No "apply suggestion".</div>`;
}

function rowKey(i) { return `qrow-${i}`; }

/* ── Purpose orders; Perspective filters ──────────────────────────────────
 *
 * The catalog carries a Purposes column — Explore, Select, Learn, Assess,
 * Certify, Deploy, Maintain, Share, Attest — and the reader has honoured it
 * since 2026-08-24: entries serving the investigation's purposes sort first,
 * the rest follow in catalog order, nothing is hidden. YAML, reader, route and
 * `getQuestions()` all carried it. This screen passed `phase` and
 * `perspectives` and not `purposes`, so the ordering never happened.
 *
 * Why ORDER and not FILTER is a recorded measurement, not a preference:
 * docs/investigation-framing-design.md §3 measured Purpose's overlap at 0.22
 * and Perspective's at 0.37 with strictly nested sets. Filtering on the axis
 * that discriminates hardest would hide the most; ordering on it puts the
 * dozen questions the task needs at the top and leaves the rest below,
 * deprioritised rather than gone. Perspective then filters, as built.
 *
 * The purposes come from the current investigation. No investigation, or one
 * with none set, means catalog order — and the legend says nothing, because
 * "not ordered" is the absence of a claim, not a claim of its own.
 */
function currentPurposes() {
  const inv = state.investigations.find((i) => i.slug === state.investigation);
  return [...(inv?.purposes || [])];
}

/** The ordering, said out loud. An ordering with no legend is
 *  indistinguishable from an arbitrary one. */
function purposeLegendHtml() {
  const purposes = currentPurposes();
  if (!purposes.length) return '';
  const lead = state.questions.filter((q) => q.derivation?.purpose_ranked).length;
  const total = state.questions.length;
  if (!total) return '';
  // Zero promoted is a real answer — this stage's questions serve none of the
  // investigation's purposes — and "0 of 7 lead" is not how anyone would say
  // it. Measured: Assessment has 0 of 7 for Explore + Learn.
  if (!lead) {
    return `<span class="text-ink-muted">none of these serve ${esc(purposes.join(', '))} ·
      catalog order</span>`;
  }
  return `<span class="text-ink-muted">ordered by purpose · ${esc(purposes.join(', '))} ·
    <span class="tnum">${lead}</span> of <span class="tnum">${total}</span> lead${
    lead < total ? ', the rest follow in catalog order' : ''}</span>`;
}

/** The boundary between the questions the investigation's purposes promoted
 *  and the ones they did not. Rendered ONCE, at the first unranked row, and
 *  only when both groups are non-empty — a rule above the first row or below
 *  the last says nothing. Without this the second group reads as a
 *  continuation, or as an oversight; with it, it reads as what it is. */
function purposeBreakHtml(i) {
  if (!currentPurposes().length) return '';
  const q = state.questions[i];
  const prev = state.questions[i - 1];
  if (!prev || !prev.derivation?.purpose_ranked || q.derivation?.purpose_ranked) return '';
  return `<div class="mt-s2 mb-s1 flex items-baseline gap-s2 text-caps uppercase tracking-caps text-ink-muted">
    <span>Not among this investigation's purposes</span>
    <span class="h-px flex-1 bg-rule"></span>
  </div>`;
}

function rowShell(entry, i) {
  const last = i === state.questions.length - 1;
  return `${purposeBreakHtml(i)}<div id="${rowKey(i)}" class="py-s3 ${last ? '' : 'border-b border-rule'}">
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
    const key = questionKey(entry.question);
    const held = (state.contextAnswers || {})[key];
    const declared = (entry.answering_mechanism || '');
    // The mechanism column declares "Egeria Queries" on six of these seven
    // questions, and none of the six names an analysis. So there is nothing
    // to run first, and the honest render says which — an empty state that
    // says what it looked in, per this round's own rule. Claiming a query
    // ran, or silently offering only the text box, would both misdescribe it.
    const wanted = /egeria quer/i.test(declared) && !(entry.analysis_ids || []).length;
    return `<div class="${indent} text-answer text-ink">${tnum(esc(why))}</div>
      ${held?.answer
        ? `<div class="${indent} mt-s1 text-answer text-ink">${tnum(esc(held.answer))}</div>
           <div class="${indent} text-provenance text-ink-muted">answered ${esc(ago(held.answered_at))}
             · <button type="button" data-human-edit="${esc(entry.question)}"
                 class="cursor-pointer bg-transparent text-accent-ink underline">change</button></div>`
        : `<div class="${indent} mt-s1">
             <button type="button" data-human-edit="${esc(entry.question)}"
               class="cursor-pointer rounded-sm border border-accent px-2 py-[2px] text-accent-ink"
               >Answer this →</button>
           </div>`}
      ${wanted
        ? `<div class="${indent} text-provenance text-ink-muted">The catalog says
             ${esc(declared)}, but no analysis is attached to this question, so
             nothing was queried — the answer here is yours alone.</div>`
        : ''}`;
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
