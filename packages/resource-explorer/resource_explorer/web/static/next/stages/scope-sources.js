/* Words about WHICH survey a schema list was read from, shared by the Curate
 * scope tree (curate-scope.js) and the Schema Inventory pane (app.js) so the
 * two screens name their sources identically. No imports: both sides load it.
 *
 * Slice A2.1: the Schema Inventory pane used to read RE's own credential-scoped
 * local survey alone and say nothing about that, while Curate read the fuller
 * Egeria native survey. Both now read `catalogue_scope.resolve_node_set`. */

export const SOURCE_WORD = { egeria: 'Egeria survey', local: 'RE local survey' };
export const md = (iso) => String(iso || '').slice(5, 10);

/** One sentence naming the survey a schema list was read from and, when the two
 *  surveys disagree on the counts, BOTH:
 *  "29 schemas · Egeria survey 10-04 · RE's own survey saw 8 schemas, 61 tables, 10-03". */
export function inventoryHeaderText(sources) {
  if (!sources || !sources.chosen) return '';
  const ch = sources.chosen; const eg = sources.egeria || {}; const lo = sources.local || {};
  const head = `${ch.schemas} schemas · ${SOURCE_WORD[ch.kind] || ch.kind} ${md(ch.as_of)}`;
  if (lo.state === 'unreadable') return `${head} · RE's own survey could not be read`;
  if (!sources.disagree) return head;
  if (ch.kind === 'local') {
    return `${head} · Egeria's survey saw ${eg.schema_count} schemas, ${eg.table_count} tables, ${md(eg.surveyed_at)}`;
  }
  return `${head} · RE's own survey saw ${lo.schema_count} schemas, ${lo.table_count} tables, ${md(lo.surveyed_at)}`;
}

/** "from Egeria survey 10-04", plus "rows from RE local survey 10-03" for a fact the
 *  node's own source lacked and another survey supplied. '' when the node has no source. */
export function nodeSourceLine(node) {
  const own = (node && node.source) || {};
  if (!own.kind) return '';
  const say = (src) => `${SOURCE_WORD[src.kind] || src.kind} ${md(src.as_of)}`;
  const parts = [`from ${say(own)}`];
  Object.entries(node.facts_from || {}).forEach(([fact, src]) => {
    if (src && (src.kind !== own.kind || src.as_of !== own.as_of)) parts.push(`${fact} from ${say(src)}`);
  });
  return parts.join(' · ');
}

/** The page-level credential line. It is about ONE survey, RE's own, and says so:
 *  "RE's own survey 10-03: connected as surveyor, sees 6 of 8 schemas, SELECT on 3 of 61
 *  relations; counts from that survey are scoped to this credential". `thin` is true
 *  when the credential cannot see everything; the scoped sentence is only said then. */
export function credentialLineText(cap, at, relTotal, relSelect) {
  const thin = (relSelect ?? 0) < (relTotal ?? 0)
    || (cap.schema_visible ?? 0) < (cap.schema_total ?? 0);
  const when = md(at) ? ` ${md(at)}` : '';
  const text = `RE's own survey${when}: connected as ${cap.connected_as || '(unknown)'}, `
    + `sees ${cap.schema_visible ?? 0} of ${cap.schema_total ?? 0} schemas, `
    + `SELECT on ${relSelect ?? 0} of ${relTotal ?? 0} relations`
    + (thin ? '; counts from that survey are scoped to this credential' : '');
  return { text, thin };
}

/* ── the scope section's one-line collapse (Curate, catalogue scope) ────────
 * Pure functions, no imports, so a test can run them under node. */

const isCount = (n) => typeof n === 'number' && Number.isFinite(n);

/** The marker under the scope header: where the scope lives and what has not happened. */
export const SCOPE_SAVED_MARKER = 'Saved in Resource Explorer \u00b7 not yet catalogued in Egeria';

/** The ONE line of essentials, or '' while no scope is declared:
 *  "Your scope: 3 of 29 schemas · declared by dan 10-04 · Egeria's latest survey covers 29 schemas, 412 tables".
 *  A clause whose figures are not available is omitted, never filled with zero or a guess. */
export function scopeCollapsedText(view) {
  const d = (view && view.declared) || {};
  if (!d.declared) return '';
  const c = view.counts || {};
  const sv = view.survey || {};
  const parts = [];
  parts.push(isCount(c.schemas_catalogue) && isCount(c.schemas_offered)
    ? `Your scope: ${c.schemas_catalogue} of ${c.schemas_offered} schemas` : 'Your scope');
  const decl = [d.by ? `declared by ${d.by}` : 'declared', md(d.at)].filter(Boolean).join(' ');
  parts.push(decl);
  if (sv.state === 'measured' && isCount(sv.schema_count) && isCount(sv.table_count)) {
    parts.push(`Egeria's latest survey covers ${sv.schema_count} schemas, ${sv.table_count} tables`);
  }
  return parts.join(' \u00b7 ');
}

/** localStorage key for the person's choice, per person per database; '' when nobody is signed in. */
export function scopeCollapseKey(person, slug) {
  return person && slug ? `re-next.scopeSection.${person}.${slug}` : '';
}

/** 'open' | 'collapsed' | '' (nothing remembered, or storage unavailable). Never throws. */
export function readScopePref(storage, person, slug) {
  const key = scopeCollapseKey(person, slug);
  if (!key) return '';
  try {
    const v = storage && storage.getItem(key);
    return v === 'open' || v === 'collapsed' ? v : '';
  } catch { return ''; }
}

/** Remember the choice. Returns whether it was stored; the page works either way. */
export function writeScopePref(storage, person, slug, open) {
  const key = scopeCollapseKey(person, slug);
  if (!key) return false;
  try { storage.setItem(key, open ? 'open' : 'collapsed'); return true; } catch { return false; }
}

/** Open until a scope has been declared, collapsed after; a remembered choice wins. */
export function scopeStartsOpen(view, pref) {
  if (pref === 'open') return true;
  if (pref === 'collapsed') return false;
  return !((view && view.declared) || {}).declared;
}
