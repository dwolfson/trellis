/* re-api.js — the client half of Resource Explorer's API, as an ES module.
 *
 * Placed at /static/re-api.js rather than under /static/next/ deliberately:
 * it is meant to be imported by BOTH shells, and a module that lives inside
 * one UI's directory is a module the other will never adopt. Today only
 * /next imports it; rewiring index.html's inlined equivalents to import it
 * is a separate change with its own verification, because index.html's
 * copies carry behaviour (toasts, view routing) this module deliberately
 * does not.
 *
 * Every function here returns data or throws. Nothing in this file touches
 * the DOM, shows a toast, or knows what a tab is — that is what makes it
 * shareable.
 *
 * AUTH: /static/auth.js monkey-patches window.fetch to attach the bearer
 * token to same-origin requests, and it must be loaded before this module
 * issues its first call. This module does not re-implement that.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/** A failed API call, carrying the status so a caller can tell 401 from 500. */
export class ApiError extends Error {
  constructor(status, message, path) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
  }
}

async function request(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch (_) { /* a non-JSON error body is still an error */ }
    throw new ApiError(res.status, detail, path);
  }
  if (res.status === 204) return null;
  return res.json();
}

const get = (path) => request(path);
const post = (path, body) =>
  request(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/* ────────────────────────────────────────────────────────────────────────
 * A small TTL cache.
 *
 * The catalog and perspective vocabularies change when someone edits a YAML
 * file, not between two clicks, so re-fetching them per render is waste.
 * Answers are NOT cached: an answer's whole job is to say what is true now,
 * and a stale one is the failure this app spends most of its design effort
 * avoiding.
 * ──────────────────────────────────────────────────────────────────────── */
const CACHE_TTL_MS = 60_000;
const _cache = new Map();

async function cached(key, loader, ttl = CACHE_TTL_MS) {
  const hit = _cache.get(key);
  if (hit && Date.now() - hit.at < ttl) return hit.value;
  const value = await loader();
  _cache.set(key, { at: Date.now(), value });
  return value;
}

/** Drop every cached vocabulary. Call after anything that edits a catalog. */
export function clearCache() {
  _cache.clear();
}

/* ── Session ─────────────────────────────────────────────────────────── */

export const getPolicy = () => cached('policy', () => get('/api/auth/policy'));
export const getMe = () => get('/api/auth/me');

/* ── Resources ───────────────────────────────────────────────────────── */

export const listProjects = () => get('/api/projects/');
export const getProject = (slug) => get(`/api/projects/${encodeURIComponent(slug)}`);
export const listDatabases = () => get('/api/databases/');
export const listFilesystems = () => get('/api/filesystems/');

/* ── Catalog vocabularies ────────────────────────────────────────────── */

/** The perspectives that can actually narrow something — never a hardcoded
 *  list. The vocabulary is a union of the analysis and question catalogs and
 *  has changed size more than once. */
export const listPerspectives = () =>
  cached('perspectives', () => get('/api/analyses/perspectives'));

export const listAnalyses = (resourceType, { intent, perspective } = {}) => {
  const qs = new URLSearchParams();
  if (intent) qs.set('intent', intent);
  if (perspective) qs.set('perspective', perspective);
  const suffix = qs.toString() ? `?${qs}` : '';
  return cached(`analyses:${resourceType}${suffix}`, () =>
    get(`/api/analyses/${encodeURIComponent(resourceType)}${suffix}`));
};

/* ── Questions and answers ───────────────────────────────────────────── */

/**
 * The question checklist for one repo and one funnel stage.
 *
 * `perspectives` is a Set or array; empty means all, which is the API's own
 * default — do not send an empty `perspectives=` param, it is not the same
 * thing as omitting it.
 */
export function getQuestions(slug, { phase = 'scouting', perspectives = [], purposes = [] } = {}) {
  const qs = new URLSearchParams({ phase });
  const persp = [...perspectives];
  const purp = [...purposes];
  if (persp.length) qs.set('perspectives', persp.join(','));
  if (purp.length) qs.set('purposes', purp.join(','));
  return get(`/api/projects/${encodeURIComponent(slug)}/scouting-questions?${qs}`);
}

/**
 * The answer envelope for one catalogued question, from the FactLayer.
 *
 * This is the source of the answer, the caveat and the state in a question
 * row. Facts arrive ALREADY JUDGED — each carries a state from
 * `surveyors/result_status.py`'s vocabulary (`measured`, `nothing_found`,
 * `partial`, `never_run`, `not_established`) rather than a bare value.
 *
 * An envelope whose `answerable` is false carries `blocked_reason` and MUST
 * NOT be rendered as a negative answer about the resource. For most of the
 * 41 catalogued questions that is the correct outcome, and inventing an
 * answer for them is exactly what this layer exists to prevent.
 */
export const getAnswer = (slug, question) =>
  get(`/api/analyses/facts/${encodeURIComponent(slug)}/answer`
      + `?question=${encodeURIComponent(question)}`);

/* ── Running an analysis ─────────────────────────────────────────────── */

export const runAnalysis = (slug, analysisId) =>
  post(`/api/projects/${encodeURIComponent(slug)}/analyses/${encodeURIComponent(analysisId)}/run`);

export const getActivityEntry = (entryId) =>
  get(`/api/activity/${encodeURIComponent(entryId)}`);

export const listActivity = (limit = 50) => get(`/api/activity/?limit=${limit}`);
export const listRfas = () => get('/api/activity/rfas');

/**
 * Poll one activity entry until it stops running.
 *
 * Resolves with the finished entry. Rejects on timeout — which is NOT the
 * same as failure, and a caller must render it as "we stopped watching",
 * never as "it failed". A pending marker that cannot distinguish a stalled
 * run from a slow one is worse than no marker at all.
 *
 * @param {object} opts
 * @param {number} opts.intervalMs   gap between polls
 * @param {number} opts.timeoutMs    give up after this long
 * @param {(entry: object) => void} opts.onTick  called with each poll result
 */
export async function pollActivity(entryId, {
  intervalMs = 2000,
  timeoutMs = 5 * 60_000,
  onTick = () => {},
} = {}) {
  const deadline = Date.now() + timeoutMs;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  for (;;) {
    const entry = await getActivityEntry(entryId);
    onTick(entry);
    const status = (entry?.status || '').toLowerCase();
    if (status && status !== 'running' && status !== 'queued' && status !== 'pending') {
      return entry;
    }
    if (Date.now() >= deadline) {
      const err = new Error(`Still running after ${Math.round(timeoutMs / 1000)}s`);
      err.name = 'PollTimeout';
      err.entry = entry;
      throw err;
    }
    await sleep(intervalMs);
  }
}

/* ── Investigations ──────────────────────────────────────────────────── */

export const listInvestigations = () => get('/api/investigations/');
