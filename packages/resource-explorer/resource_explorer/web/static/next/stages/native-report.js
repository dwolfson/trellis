/* Egeria survey report viewer: what a SurveyReport's annotations say, by element.
 *
 * Pure render functions (no imports) over the annotations RE stored from the report
 * (`GET .../reports/{guid}`, RE's own copy). Egeria writes one annotation per measured element, each with the
 * same generic type description, so a flat list of "type — summary" says nothing. This groups them by
 * annotation kind and shows, per element, the name and the measured values the annotation carries.
 *
 * Where the name and values come from (read from the stored rows, not assumed): every annotation's `detail`
 * holds `json_properties`, a JSON string with the measured values and the element's own name
 * (`qualifiedTableName`, `qualifiedColumnName`, `qualifiedSchemaName`, `resourceName`); `detail.qualified_name`
 * is "Annotation::<type>::<element name>::<guid>" and is the fallback. A kind whose rows carry no name says so
 * in its group; a value an annotation does not carry shows as "–", never 0.
 */
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/** Rows shown per group before "show all N". */
export const GROUP_CAP = 25;

const fmtN = (n) => (typeof n === 'number' ? n.toLocaleString('en-US') : String(n));

export function fmtBytes(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return String(n);
  if (n < 1024) return `${n} B`;
  const u = ['KB', 'MB', 'GB', 'TB'];
  let v = n;
  let i = -1;
  do { v /= 1024; i += 1; } while (v >= 1024 && i < u.length - 1);
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${u[i]}`;
}

/** The measured properties of one stored annotation: `json_properties` parsed, else the labelled map. */
export function propsOf(a) {
  const d = (a && a.detail) || {};
  let raw = d.json_properties;
  if (typeof raw === 'string' && raw.trim()) {
    try { const p = JSON.parse(raw); if (p && typeof p === 'object') return p; } catch { /* fall through */ }
  } else if (raw && typeof raw === 'object') {
    return raw;
  }
  return d.resource_properties && typeof d.resource_properties === 'object' ? d.resource_properties : {};
}

/** The kind of element an annotation measures, from its type name. */
export function kindOf(a) {
  const t = String((a && a.annotation_type) || '');
  const core = t.replace(/^Capture\s+/i, '').replace(/\s+Measurements?$/i, '').trim();
  const last = core.split(/\s+/).pop().toLowerCase();
  return ['database', 'schema', 'table', 'column'].includes(last) ? last : 'other';
}

const KIND_ORDER = ['database', 'schema', 'table', 'column', 'other'];
const KIND_WORDS = { database: ['database', 'databases'], schema: ['schema', 'schemas'],
  table: ['table', 'tables'], column: ['column', 'columns'] };

/** The element name the annotation was made for ('' when the stored row does not carry one). */
export function nameOf(a) {
  const p = propsOf(a);
  const direct = p.qualifiedColumnName || p.qualifiedTableName || p.qualifiedSchemaName || p.resourceName
    || p['Column qualified name'] || p['Table Qualified Name'] || p['Qualified Schema Name'] || p['Database Name'];
  if (direct) return String(direct);
  const qn = String(((a && a.detail) || {}).qualified_name || '');
  const m = /^Annotation::[^:]*(?:::|$)(.*)::[^:]+$/.exec(qn);
  return m && m[1] ? m[1] : '';
}

/** The columns a group shows: [label, key, format]. A kind outside the four gets the keys its rows carry. */
const SPECS = {
  database: [['Schemas', 'schemaCount'], ['Tables', 'tableCount'], ['Views', 'viewCount'],
    ['Columns', 'columnCount', '', 'z'], ['Size', 'size', 'bytes'], ['Rows fetched', 'rowsFetched', '', 'c']],
  schema: [['Tables', 'tableCount'], ['Views', 'viewCount'], ['Mat. views', 'materializedViewCount'],
    ['Columns', 'columnCount', '', 'z'], ['Size', 'totalTableSize', 'bytes', 'z']],
  table: [['Type', 'tableType'], ['Size', 'tableSize', 'bytes', 'z'], ['Columns', 'columnCount', '', 'z'],
    ['Rows added', 'numberOfRowsInserted', '', 'c'], ['Changed', 'numberOfRowsUpdated', '', 'c'],
    ['Removed', 'numberOfRowsDeleted', '', 'c']],
  column: [['Type', 'columnDataType'], ['Size', 'columnSize', '', 'z'], ['Not null', 'columnNotNull', 'bool'],
    ['Avg width', 'averageColumnWidth'], ['Distinct', 'numberOfDistinctValues']],
};
const NAME_KEYS = new Set(['qualifiedColumnName', 'qualifiedTableName', 'qualifiedSchemaName', 'resourceName',
  'columnName', 'tableName', 'schemaName']);

/** Generic columns for a kind with no spec: the (up to 5) scalar keys most rows carry. */
function genericSpec(anns) {
  const seen = new Map();
  for (const a of anns) {
    for (const [k, v] of Object.entries(propsOf(a))) {
      if (NAME_KEYS.has(k) || (v !== null && typeof v === 'object')) continue;
      seen.set(k, (seen.get(k) || 0) + 1);
    }
  }
  return [...seen.entries()].sort((x, y) => y[1] - x[1]).slice(0, 5).map(([k]) => [k, k]);
}

/** Per field: flag 'z' = Egeria stores 0 for a figure it did not measure (a table with columns reads columnCount 0),
 *  so a stored 0 there is "–" with the reason on hover. Counters ('c') keep a real 0. */
function cell(v, fmt, flag) {
  if (flag === 'z' && (v === 0 || v === '0')) {
    return '<span class="text-ink-muted" title="Egeria stored 0 here; it did not measure this">–</span>';
  }
  if (v === undefined || v === null || v === '') return '<span class="text-ink-muted" title="the annotation carries no value">–</span>';
  if (fmt === 'bytes' && typeof v === 'number') return esc(fmtBytes(v));
  if (fmt === 'bool' || typeof v === 'boolean') return v === true || v === 'true' ? 'yes' : 'no';
  return esc(typeof v === 'number' ? fmtN(v) : v);
}

/** The groups of a report, in the order a person asks: database, schemas, tables, columns, anything else. */
export function groupAnnotations(anns) {
  const byType = new Map();
  for (const a of anns || []) {
    const t = a.annotation_type || '(no type)';
    if (!byType.has(t)) byType.set(t, []);
    byType.get(t).push(a);
  }
  const groups = [...byType.entries()].map(([type, items]) => {
    const kind = kindOf(items[0]);
    return { type, kind, items, description: (items.find((i) => i.summary) || {}).summary || '' };
  });
  groups.sort((x, y) => KIND_ORDER.indexOf(x.kind) - KIND_ORDER.indexOf(y.kind) || x.type.localeCompare(y.type));
  return groups;
}

/** "71 annotations · 1 database · 4 schemas · 12 tables · 54 columns". Counts annotations, by kind. */
export function reportSummaryLine(anns) {
  const n = (anns || []).length;
  const counts = new Map();
  for (const a of anns || []) {
    const k = kindOf(a);
    const key = k === 'other' ? `other:${a.annotation_type || '(no type)'}` : k;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const bits = [`${fmtN(n)} annotation${n === 1 ? '' : 's'}`];
  for (const k of KIND_ORDER.filter((x) => x !== 'other')) {
    const c = counts.get(k);
    if (c) bits.push(`${fmtN(c)} ${KIND_WORDS[k][c === 1 ? 0 : 1]}`);
  }
  for (const [key, c] of counts) if (key.startsWith('other:')) bits.push(`${fmtN(c)} ${key.slice(6)}`);
  return bits.join(' · ');
}

function dbPrefix(anns) {
  const db = anns.find((a) => kindOf(a) === 'database');
  const name = db ? nameOf(db) : '';
  return name && !name.includes('.') ? `${name}.` : '';
}

function rowHtml(a, cols, prefix) {
  const full = nameOf(a);
  const name = full && prefix && full.startsWith(prefix) ? full.slice(prefix.length) : full;
  const p = propsOf(a);
  return `<tr data-report-row><td class="pr-s3 font-mono text-ink" title="${esc(full)}">${
    name ? esc(name) : '<span class="text-ink-muted font-sans" title="the stored annotation carries no element name">no name stored</span>'}</td>${
    cols.map(([, key, fmt, flag]) => `<td class="pr-s3 tnum text-right text-ink">${cell(p[key], fmt, flag)}</td>`).join('')}</tr>`;
}

function groupRowsHtml(g, cols, prefix, count) {
  const sorted = [...g.items].sort((x, y) => nameOf(x).localeCompare(nameOf(y)));
  return sorted.slice(0, count).map((a) => rowHtml(a, cols, prefix)).join('');
}

/** One group: collapsed by default; the generic type description is the summary's hover title, once. */
function groupHtml(g, prefix, cap) {
  const cols = SPECS[g.kind] || genericSpec(g.items);
  const unnamed = g.items.filter((a) => !nameOf(a)).length;
  const more = g.items.length - cap;
  return `<details class="mt-s2 border-b border-rule pb-s2" data-report-group="${esc(g.type)}" data-report-kind="${g.kind}">
    <summary class="cursor-pointer text-answer text-ink" title="${esc(g.description)}">${esc(g.type)}
      <span class="tnum text-ink-muted">· ${fmtN(g.items.length)}</span></summary>
    ${unnamed ? `<div class="mt-[2px] text-provenance text-state-warn" data-report-unnamed>${
      fmtN(unnamed)} of ${fmtN(g.items.length)} stored annotations carry no element name.</div>` : ''}
    <table class="mt-s2 text-caveat">
      <thead><tr><th class="pr-s3 text-left font-normal text-ink-muted">Element</th>${
  cols.map(([label, , , flag]) => `<th class="pr-s3 text-right font-normal text-ink-muted"${flag === 'c'
    ? ' title="cumulative since the server\'s statistics reset, not this survey"' : ''}>${esc(label)}</th>`).join('')}</tr></thead>
      <tbody data-report-tbody>${groupRowsHtml(g, cols, prefix, cap)}</tbody>
    </table>
    ${more > 0 ? `<button type="button" data-report-show-all class="mt-s2 cursor-pointer border-0 bg-transparent p-0 text-caveat text-accent-ink underline"
      >show all <span class="tnum">${fmtN(g.items.length)}</span></button>` : ''}
  </details>`;
}

/** The whole viewer body for a stored report (`rep` is the route's response). */
export function reportViewerHtml(rep, { cap = GROUP_CAP } = {}) {
  const anns = (rep && rep.annotations) || [];
  const proc = rep.process_qualified_name ? ` · ${esc(rep.process_qualified_name)}` : '';
  const head = `
    <div class="mb-s2 text-answer text-ink" data-report-summary>${esc(reportSummaryLine(anns))}</div>
    <div class="mb-s2 text-provenance text-ink-muted" data-report-meta>report from <span class="tnum">${
  esc(rep.report_at || 'an unrecorded time')}</span>${proc} · engine action <span class="font-mono">${
  esc(rep.engine_action_guid || 'not recorded')}</span></div>`;
  if (!anns.length) {
    return `${head}<p class="text-ink-muted">Egeria completed this survey and its report holds no annotations.</p>`;
  }
  const prefix = dbPrefix(anns);
  return `${head}<div class="max-w-[90ch]" data-report-groups>${
    groupAnnotations(anns).map((g) => groupHtml(g, prefix, cap)).join('')}</div>`;
}

/** Wire "show all N": it re-draws that group's rows in full. */
export function bindReportViewer(root, rep) {
  const anns = (rep && rep.annotations) || [];
  const prefix = dbPrefix(anns);
  const groups = new Map(groupAnnotations(anns).map((g) => [g.type, g]));
  root.querySelectorAll('[data-report-group]').forEach((d) => {
    const btn = d.querySelector('[data-report-show-all]');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const g = groups.get(d.dataset.reportGroup);
      if (!g) return;
      const cols = SPECS[g.kind] || genericSpec(g.items);
      d.querySelector('[data-report-tbody]').innerHTML = groupRowsHtml(g, cols, prefix, g.items.length);
      btn.remove();
    });
  });
}
