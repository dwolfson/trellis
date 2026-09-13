/* Formatting shared by the shell and the work-list grid.
 *
 * `ago` lived in app.js and the grid needs it too. app.js already imports
 * worklist.js, so worklist.js cannot import app.js back — hence a third
 * module rather than a second copy that would drift. */

/** "5d ago" / "3h ago" / "just now" — or "" when there is no timestamp,
 *  which is a real state and must not render as "now". */
/** Milliseconds for a registry timestamp, or NaN. The registry writes
 *  three spellings -- `...Z`, `...+00:00`, and NAIVE (`datetime.utcnow()`
 *  with no zone) -- and Date.parse reads a naive ISO string as LOCAL time,
 *  so a naive UTC stamp compared with a zoned one is off by the zone
 *  offset in whichever direction the viewer sits. Every comparison and
 *  every age goes through here; a naive stamp is UTC. */
export function whenMs(iso) {
  if (!iso) return NaN;
  const s = String(iso);
  const zoned = /(Z|[+-]\d\d:?\d\d)$/.test(s);
  return Date.parse(zoned ? s : `${s}Z`);
}

export function ago(iso) {
  if (!iso) return '';
  const then = whenMs(iso);
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, (Date.now() - then) / 1000);
  if (secs < 90) return 'just now';
  const mins = secs / 60;
  if (mins < 90) return `${Math.round(mins)}m ago`;
  const hours = mins / 60;
  if (hours < 36) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** Days since `iso`, or null when there is no usable timestamp. Callers use
 *  this to decide staleness; `ago` is for showing it. */
export function daysSince(iso) {
  if (!iso) return null;
  const then = whenMs(iso);
  if (Number.isNaN(then)) return null;
  return (Date.now() - then) / 86400000;
}

/** One disposition verdict, one line, the same in both views:
 *  `tracking · 32d ago (2026-08-11) · who · reason`. The reason sits in
 *  ink beside the word it explains -- a trail exists for the reasons, and
 *  rendering them dimmer than the one-word verdict says the opposite.
 *  `esc` is passed in because this module has no DOM helpers of its own. */
export function verdictLineHtml(r, esc) {
  const when = r.decided_at || '';
  const rel = ago(when);
  return `<span class="text-ink">${esc(r.disposition || '—')}</span>${
    rel ? ` · <span class="tnum">${esc(rel)}</span>` : ''}${
    when ? ` <span class="tnum">(${esc(String(when).slice(0, 10))})</span>` : ''}${
    r.decided_by ? ` · ${esc(r.decided_by)}` : ''}${
    r.reason ? ` · <span class="text-ink">${esc(r.reason)}</span>` : ''}`;
}

/** "changed once" / "changed 3 times" -- never `time(s)`. */
export function changedTimesHtml(n) {
  if (n < 1) return '';
  return n === 1 ? 'changed once' : `changed <span class="tnum">${n}</span> times`;
}
