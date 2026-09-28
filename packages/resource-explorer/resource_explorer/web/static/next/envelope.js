/* Reading an envelope — the honest part.
 *
 * Split out of app.js (BRIEF-KEYS-AND-ACTIVITY-CLOBBER.md §D, 2026-09-27) so
 * `readEnvelope` can be imported directly by a node-run test and checked
 * against `facts.py`'s `_renders_text` — its Python mirror, which has no
 * shared source and had already drifted twice (see facts.py's own docstring
 * on `_renders_text`). Moving the code changes nothing about what it does;
 * only where it lives.
 *
 * `esc`/`tnum` are NOT imported from app.js here, even though that is where
 * they are defined and app.js imports this module — importing them back
 * would be circular. They are passed in as parameters instead, the same way
 * format.js's `verdictLineHtml(r, esc)` already does ("esc is passed in
 * because this module has no DOM helpers of its own"). `whenMs` has no such
 * problem — it lives in format.js, which nothing here or in app.js needs to
 * import back — so it is imported normally.
 */
import { whenMs } from '/static/next/format.js';

/** Fact states, from surveyors/result_status.py. */
export const MEASURED = 'measured';
export const NOTHING_FOUND = 'nothing_found';
export const NOT_ESTABLISHED = 'not_established';
export const NEVER_RUN = 'never_run';
export const NO_READER = 'no_reader';
export const PARTIAL = 'partial';

/** Verdict words the design sets at weight 600. Matched only at the head of
 *  a sentence and only when a separator follows, so a headline that merely
 *  starts with "No" as part of a phrase is left alone. Bolding the wrong
 *  word would assert a verdict the analysis did not make. */
export const VERDICT = /^(Yes|No|Partly|Partially|Likely|Unlikely|Mixed|Narrowly maintained|Actively maintained)(\s*[—–,-]\s+)/;

/** Sentence case for a verdict word an analysis wrote in lower case. */
export function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

export function answerHtml(headline, esc, tnum) {
  const m = VERDICT.exec(headline);
  if (!m) return tnum(esc(headline));
  const rest = headline.slice(m[0].length);
  return `<strong class="font-semibold">${esc(m[1])}</strong>${esc(m[2])}${tnum(esc(rest))}`;
}

/** The analysis's own prose, if it wrote any. Never assembled here. */
export function prose(f) {
  const v = f.value || {};
  const text = v.detail || v.summary || v.description || '';
  return typeof text === 'string' ? text.trim() : '';
}

/** The scalar measures, relayed as `key value` pairs.
 *
 *  Deliberately last-resort. Structured fields (lists, objects) are NOT
 *  flattened into this line — they belong in `evidence`, where they can be
 *  read rather than skimmed. */
export function scalarMeasures(value, max = 6) {
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

/** The Mermaid source a fact carries, if it carries any.
 *
 *  `architecture_diagram` writes its source into the fact value, so the
 *  relationship question ("How do its components relate to each other?") has
 *  a real diagram sitting behind it. This is the product path to a diagram —
 *  a chat answer is not the only one, and wiring promotion ONLY to chat left
 *  the feature unreachable for anyone who had not asked a question first.
 */
export function factMermaid(env) {
  for (const f of (env && env.facts) || []) {
    const src = f.value && (f.value.mermaid || f.value.diagram);
    if (typeof src === 'string' && src.trim()) {
      return { source: src.trim(), analysisId: f.analysis_id, lastRun: f.last_run_at || '' };
    }
  }
  return null;
}

/**
 * Turn an envelope into the lines a row shows.
 *
 * The rule this function exists to keep: a fact's state decides the SENTENCE,
 * not just an icon. `nothing_found` is knowledge — a measured zero — and says
 * so. `never_run` says nothing ran. `not_established` says the method could
 * not settle it. Folding any two of those together is the failure the
 * FactLayer was built to prevent, and it would be undone here.
 *
 * `esc`/`tnum` are passed in by the caller (app.js) rather than imported —
 * see this module's header comment.
 */
export function readEnvelope(entry, env, esc, tnum) {
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
    if (f.headline) { sentences.push(answerHtml(f.headline, esc, tnum)); continue; }
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
  // A caveat on a multi-analysis row names its analysis, or it does not
  // render (designer, SPEC-ACTIONABLE-AND-HONEST.md point 5): "This
  // analysis ran and found nothing" reads as a claim about whichever
  // number sits above it when three analyses answer one question, and it
  // is usually a claim about a DIFFERENT one. `f.note` is the analysis's
  // own prose, written as if it would be read alone -- attributed here,
  // not rewritten, since the sentence itself is correct and only its
  // referent was ambiguous.
  const attribute = (f, text) => (facts.length > 1 ? `${f.analysis_id} — ${text}` : text);
  const caveats = [];
  for (const f of facts) {
    if (f.note) caveats.push(attribute(f, f.note));
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
