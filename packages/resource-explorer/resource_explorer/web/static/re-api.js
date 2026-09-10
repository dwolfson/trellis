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

/**
 * Every registered repo.
 *
 * NOTE the default filters, which are stronger than their names suggest:
 * `include_ignored=false` drops BOTH `ignored` and `abandoned` repos, and
 * `include_working_set_hidden=false` drops anything hidden from the personal
 * view. A sidebar that offers disposition facets has to ask for the full
 * list and filter client-side, or the facets for those two dispositions can
 * never have anything in them.
 */
export const listProjects = ({ includeIgnored = false, includeHidden = false } = {}) =>
  get(`/api/projects/?include_ignored=${includeIgnored}`
      + `&include_working_set_hidden=${includeHidden}`);

/** The Scouting-tier facts for one repo — this is where `homepage`,
 *  `last_published_at` and `egeria_link_stale` live; they are NOT on the
 *  summary row that the list endpoint returns. */
export const getScoutingOverview = (slug) =>
  get(`/api/projects/${encodeURIComponent(slug)}/scouting-overview`);
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

/* ── Write paths ─────────────────────────────────────────────────────── */

/**
 * A repo's disposition.
 *
 * Keyed on `github_url`, NOT the slug — the endpoint is reachable for a repo
 * that has not been imported yet, and it resolves the slug server-side.
 * Passing a slug here silently fails to match anything.
 */
export const VALID_DISPOSITIONS = [
  'undecided', 'tracking', 'investigating', 'recommended',
  'using', 'abandoned', 'ignored',
];

export const setDisposition = (githubUrl, disposition, reason = '') =>
  post('/api/discovery/disposition', { github_url: githubUrl, disposition, reason });

export const getDispositionHistory = (githubUrl) =>
  get(`/api/discovery/disposition-history?github_url=${encodeURIComponent(githubUrl)}`);

/**
 * Hide or unhide a resource in the personal working set.
 *
 * A view preference, not a judgement about the resource, and a different
 * axis from disposition — the endpoint's own docstring is explicit about
 * that. Nothing is deleted.
 */
export const setWorkingSetHidden = (entityType, entitySlug, hidden) =>
  post('/api/discovery/working-set', {
    entity_type: entityType, entity_slug: entitySlug, hidden,
  });

/**
 * Unregister a repo and delete its local survey data.
 *
 * DESTRUCTIVE and irreversible: it drops the repo's pgvector collections and
 * removes the registry row. The endpoint takes no confirmation flag of any
 * kind, so the only confirmation that will ever exist is the caller's.
 */
export const removeProject = (slug) =>
  request(`/api/projects/${encodeURIComponent(slug)}`, { method: 'DELETE' });

/* ── Groups ──────────────────────────────────────────────────────────── */

export const listGroups = () => cached('groups', () => get('/api/projects/groups'));

export const assignGroup = (slug, groupSlug, resourceType = 'repo') =>
  post(`/api/projects/${encodeURIComponent(slug)}/group`,
       { resource_type: resourceType, group_slug: groupSlug });

/* ── Investigations ──────────────────────────────────────────────────── */

export const listInvestigationMembers = (slug) =>
  get(`/api/investigations/${encodeURIComponent(slug)}/members`);

export const addInvestigationMember = (slug, entityType, entitySlug, rationale = '') =>
  post(`/api/investigations/${encodeURIComponent(slug)}/members`, {
    entity_type: entityType, entity_slug: entitySlug,
    membership_rationale: rationale, state: 'in-scope',
  });

export const removeInvestigationMember = (slug, entityType, entitySlug) =>
  request(`/api/investigations/${encodeURIComponent(slug)}/members/`
          + `${encodeURIComponent(entityType)}/${encodeURIComponent(entitySlug)}`,
          { method: 'DELETE' });

/* ── Query ───────────────────────────────────────────────────────────── */

export const ask = (query, { resourceSlug, perspectives = [], sessionId } = {}) =>
  post('/api/query/', {
    query,
    project_slug: resourceSlug || null,   // the wire key is still the old name
    perspectives: [...perspectives],
    session_id: sessionId || null,
  });

/**
 * Rate an answer.
 *
 * `vote` is THREE states, not a thumb: +1 helpful, 0 partially correct,
 * -1 not helpful. Recording a "partly" as either of the others is the kind
 * of quiet flattening that makes the feedback corpus useless.
 *
 * `queryHash` always comes from a prior server response — the client never
 * computes it — so that a vote on the same question text lands under one key
 * whether the answer came from retrieval or from measurements.
 */
export const sendFeedback = (queryHash, vote, compileId = null) =>
  post('/api/query/feedback',
       compileId ? { query_hash: queryHash, vote, compile_id: compileId }
                 : { query_hash: queryHash, vote });

/* ── Charts ──────────────────────────────────────────────────────────── */

/** The chart kinds `/api/stats/{slug}/charts/{kind}` serves for a repo. */
export const REPO_CHARTS = [
  ['stars', 'Stars over time'],
  ['commits', 'Commits over time'],
  ['weekly_commits', 'Commits by week'],
  ['languages', 'Languages'],
  ['file_types', 'File types'],
  ['top_committers', 'Top committers'],
  ['health', 'Health'],
  ['survey_history', 'Survey history'],
];

/**
 * One Plotly figure.
 *
 * A 200 with an empty `data` array is a real and different answer from a
 * failure: it means the series exists and has nothing in it yet. Callers
 * must not render the two the same way.
 */
export const getChart = (slug, kind) =>
  get(`/api/stats/${encodeURIComponent(slug)}/charts/${encodeURIComponent(kind)}`);

/* ── Work lists and batch runs ───────────────────────────────────────── */

export const listWorkLists = (investigation = '') =>
  get(`/api/work-lists/${investigation ? `?investigation=${encodeURIComponent(investigation)}` : ''}`);

export const getWorkList = (slug) => get(`/api/work-lists/${encodeURIComponent(slug)}`);

export const createWorkList = (displayName, entitySlugs, { investigation = '', rationale = '', description = '' } = {}) =>
  post('/api/work-lists/', {
    display_name: displayName, entity_slugs: [...entitySlugs],
    investigation, rationale, description,
  });

export const promoteWorkList = (slug, survivors, displayName = '', rationale = '') =>
  post(`/api/work-lists/${encodeURIComponent(slug)}/promote`,
       { survivors: [...survivors], display_name: displayName, rationale });

/**
 * Publish a work list to Egeria as a `WorkingSet` collection.
 *
 * NOT `WorkList` — that type does not exist in Egeria. `WorkingSet` is the
 * one whose definition is this feature ("a list of elements that are being
 * worked on"); `WorkItemList` is the neighbouring type and is for activities.
 *
 * Explicit: creating or editing a list publishes nothing.
 */
export const publishWorkList = (slug) =>
  post(`/api/work-lists/${encodeURIComponent(slug)}/publish`);

/**
 * Run one analysis across a SET of resources, concurrently.
 *
 * Returns a `set_id` to poll. One queue row per resource, so one failure is
 * one row — the rest still run.
 */
export const enqueueBatch = (analysisId, entitySlugs, workListSlug = '') =>
  post('/api/work-lists/runs/batch', {
    analysis_id: analysisId, entity_slugs: [...entitySlugs], work_list_slug: workListSlug,
  });

/** Progress for one batch, derived from the run rows on every read. */
export const getBatchProgress = (setId) =>
  get(`/api/work-lists/runs/sets/${encodeURIComponent(setId)}`);

/** Every fact known about ONE resource, already judged. */
export const getResourceFacts = (slug) =>
  get(`/api/analyses/facts/${encodeURIComponent(slug)}`);

/**
 * Facts for SEVERAL resources, in one call.
 *
 * ALWAYS pass `analysisIds` when you know them. The cost is dominated by two
 * analyses with expensive results readers — measured on `egeria_git`,
 * `architecture_recovery` 47s and `architecture_diagram` 22s, against under a
 * second for the other 32 combined. Reading all 34 is 70s per resource;
 * reading the 5 that Scouting's questions use is 0.5s. Omitting the scope is
 * what made a four-member work list look hung.
 *
 * Returns `{subjects: {slug: [fact]}, unreadable: {slug: reason}}` — a
 * resource that could not be read is named there rather than coming back as
 * an empty fact list, which would be indistinguishable from one that has no
 * results.
 */
export const getBulkFacts = (slugs, analysisIds = []) => {
  const qs = new URLSearchParams({ slugs: [...slugs].join(',') });
  if (analysisIds.length) qs.set('analysis_ids', [...analysisIds].join(','));
  return get(`/api/analyses/facts?${qs}`);
};

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
