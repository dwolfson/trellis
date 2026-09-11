/* Formatting shared by the shell and the work-list grid.
 *
 * `ago` lived in app.js and the grid needs it too. app.js already imports
 * worklist.js, so worklist.js cannot import app.js back — hence a third
 * module rather than a second copy that would drift. */

/** "5d ago" / "3h ago" / "just now" — or "" when there is no timestamp,
 *  which is a real state and must not render as "now". */
export function ago(iso) {
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

/** Days since `iso`, or null when there is no usable timestamp. Callers use
 *  this to decide staleness; `ago` is for showing it. */
export function daysSince(iso) {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  return (Date.now() - then) / 86400000;
}
