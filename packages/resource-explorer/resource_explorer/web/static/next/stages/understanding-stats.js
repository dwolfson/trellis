/* Understanding — statistics currency (S4b). Pure render functions only.
 *
 * Every number and state here arrives from the server's one derivation
 * (`resource_explorer/statistics_currency.py`, served by
 * `/api/stats/databases/{slug}/statistics_currency` and, per ranked table, as
 * `statistics` on `table_sizes`). Nothing is computed here but wording: no
 * threshold, no date arithmetic, no clock. A state is a glyph plus a short
 * word; the threshold and the as-of rule are in `title`, not in the line.
 *
 * No imports: the only helper needed is escaping.
 */
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const OK = 'ok';
const WARN = 'warn';
const MUTED = 'muted';

/** "2026-10-02T..." -> "10-02". */
export function monthDay(iso) {
  const m = /^\d{4}-(\d{2}-\d{2})/.exec(String(iso || ''));
  return m ? m[1] : '';
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const span = (tone, glyph, word, attrs = '') =>
  `<span class="${tone === OK ? 'text-state-ok' : tone === WARN ? 'text-state-warn' : 'text-ink-muted'}" ${attrs}><span class="font-glyph" aria-hidden="true">${glyph}</span> ${esc(word)}</span>`;

/** One table's cue from the server's `statistics` object. */
export function tableCueHtml(st) {
  if (!st || st.state == null) return span(MUTED, '?', 'not collected', 'data-stats-state="not_collected"');
  const age = typeof st.age_days === 'number' ? st.age_days : null;
  const at = (st.last_analyzed || '').slice(0, 10);
  switch (st.state) {
    case 'current':
      return span(OK, '✓', `analysed ${age}d ago`, `data-stats-state="current" title="${esc(at)}"`);
    case 'stale':
      return span(WARN, '◐', `stale ${age}d`, `data-stats-state="stale" title="${esc(at)}"`);
    case 'never':
      return span(WARN, '○', 'never analysed', 'data-stats-state="never"');
    case 'reset':
      return span(MUTED, '?', `counters reset since${monthDay(st.stats_reset) ? ` ${monthDay(st.stats_reset)}` : ''}`,
        'data-stats-state="reset" title="The counters were reset, so whether it was analysed before the reset is not known from this survey."');
    case 'never_reset_unknown':
      return span(WARN, '○', 'not analysed · reset time not read', 'data-stats-state="never_reset_unknown"');
    default:
      return span(MUTED, '?', 'not collected', 'data-stats-state="not_collected"');
  }
}

/** The text for a "could not be read / not measured" response. */
function unreadable(resp, what) {
  if (resp && resp.__error) {
    return `<div class="text-caveat text-state-warn" data-stats-unreadable>${what} could not be read: ${esc(resp.__error)}</div>`;
  }
  const why = ((resp && resp.reasons) || []).join(', ').replace(/_/g, ' ');
  return `<div class="text-caveat text-ink-muted" data-stats-not-measured><span class="font-glyph" aria-hidden="true">?</span> ${
    what} not measured${why ? ` · ${esc(why)}` : ''}</div>`;
}

function resetWords(r) {
  if (!r) return 'counters reset time not read';
  if (r.state === 'reset_at') return `counters reset ${monthDay(r.at)}`;
  if (r.state === 'never_reset') return 'counters never reset';
  return 'counters reset time not read';
}

/** The whole-database line (At a glance). */
export function statsLineHtml(resp) {
  if (!resp || resp.__error || !resp.currency) return unreadable(resp, 'Statistics currency');
  const c = resp.currency, d = c.database;
  const days = c.stale_days;
  const glyph = d.behind ? '◐' : '✓';
  const tone = d.behind ? WARN : OK;
  const bits = [
    'statistics', resetWords(d.counters_reset),
    `${d.behind} of ${d.total} ${d.total === 1 ? 'table' : 'tables'} not analysed in ${days} days`,
  ];
  if (d.reset_tables) bits.push(`${d.reset_tables} unknowable since reset`);
  if (d.not_collected) bits.push(`${d.not_collected} not collected`);
  return `<div class="text-answer text-ink" data-stats-line title="Ages are measured at the survey time (${
    esc(c.as_of)}), not today. Stale means analysed more than ${days} days before the survey.">${
    esc(bits.join(' · '))} <span class="${tone === OK ? 'text-state-ok' : 'text-state-warn'} font-glyph" aria-hidden="true">${glyph}</span></div>`;
}

/** The rollup text for one schema row: "3 of 40 never · oldest 41d". */
export function schemaRollupWords(s) {
  if (s.empty) return 'no tables';
  const bits = [`${s.never} of ${s.total} never`];
  if (s.stale) bits.push(`${s.stale} stale`);
  if (s.reset_tables) bits.push(`${s.reset_tables} reset`);
  if (s.not_collected) bits.push(`${s.not_collected} not collected`);
  bits.push(s.oldest_days == null ? 'none analysed' : `oldest ${s.oldest_days}d`);
  return bits.join(' · ');
}

/** Schema rollups (Contents). */
export function schemaRollupsHtml(resp) {
  if (!resp || resp.__error || !resp.currency) return unreadable(resp, 'Statistics by schema');
  const rows = resp.currency.schemas || [];
  if (!rows.length) return '';
  return `<div class="mt-s3" data-stats-schemas><div class="mb-s1 text-caveat text-ink">Statistics by schema</div>${
    rows.map((s) => {
      const bad = !s.empty && (s.never || s.stale);
      return `<div class="text-caveat" data-stats-schema="${esc(s.schema)}"><span class="font-mono">${esc(s.schema)}</span> · ${
        span(s.empty ? MUTED : bad ? WARN : OK, s.empty ? '∅' : bad ? '◐' : '✓', schemaRollupWords(s))}</div>`;
    }).join('')}</div>`;
}

/** The never / stale counts across surveys (Over time). */
export function statsOverTimeHtml(resp) {
  if (!resp || resp.__error || !resp.currency) return unreadable(resp, 'Statistics currency over time');
  const pts = resp.history || [];
  const measured = pts.filter((p) => p.measured);
  if (measured.length < 2) {
    return `<div class="text-caveat text-ink-muted" data-stats-time-one>${measured.length
      ? 'Only one survey stored table activity, so there is no change to show yet.'
      : 'No survey stored table activity.'}</div>`;
  }
  const rows = pts.map((p) => {
    const when = esc((p.run && p.run.surveyed_at) || '');
    return p.measured
      ? `<tr data-stats-time-row><td class="pr-s3 tnum">${when}</td><td class="pr-s3 tnum">${p.never} never</td><td class="pr-s3 tnum">${
        p.stale} stale</td><td class="pr-s3 tnum">${p.reset_tables} reset</td><td class="text-ink-muted">${esc(resetWords(p.counters_reset))}</td></tr>`
      : `<tr data-stats-time-row><td class="pr-s3 tnum">${when}</td><td colspan="4" class="text-ink-muted"><span class="font-glyph" aria-hidden="true">?</span> not collected</td></tr>`;
  }).join('');
  return `<div class="mt-s3" data-stats-time><div class="mb-s1 text-caveat text-ink">Statistics currency by survey</div><table class="text-caveat">${rows}</table></div>`;
}
