/* Resizable table columns, one helper for every /next table drawn as a grid of cells.
 *
 * A table gives this module a column spec; the module hands back the pieces:
 *   cellStyle(spec, key)   the inline style for one cell of that column (header and rows alike)
 *   handleHtml(spec, key, label)   the drag handle that sits at a header cell's right edge
 *   innerStyle(spec)       the inline style for the table's inner wrapper (its minimum width)
 *   attachColumnResize(host, spec)   once per scroll host: applies stored widths, wires drag,
 *                                    keyboard and double-click by delegation (so a re-draw of the
 *                                    host's innerHTML keeps working), returns {reset, isCustom}
 *
 * Widths live in CSS custom properties on the host (--rc-<key>), so a drag moves every row at
 * once without a re-draw; each cell's style carries the default as the var() fallback.
 * Rules kept here:
 *  - a column never goes below its minimum; the columns together never make the table wider
 *    than the host's visible width (the host scrolls inside its own box when the floor alone
 *    is wider than the pane);
 *  - double-click on a handle resets that column; Left/Right move a focused handle by 10px,
 *    Shift by 50px; the cue is a thin vertical bar on hover and on keyboard focus (see the
 *    `.rc-handle` rules in index.html);
 *  - widths persist per table id in localStorage, every access inside try/catch: with storage
 *    unavailable the table still resizes, it just forgets on reload.
 * A spec is { id, nameMin, chrome, columns: [{ key, def, min, resizable }] }, where the one
 * flexible "name" column is not listed (it takes what the others leave) and `chrome` is the
 * px of gaps, borders and indents around the cells.
 */
const VAR = (key) => `--rc-${key}`;
const STORE = (spec) => `re.colwidths.${spec.id}`;
const STEP = 10;
const STEP_BIG = 50;

const col = (spec, key) => spec.columns.find((c) => c.key === key);

export function cellStyle(spec, key) {
  const c = col(spec, key);
  return `width:var(${VAR(key)},${c.def}px);flex:none;min-width:0`;
}

export function totalFloor(spec, widths = {}) {
  return spec.columns.reduce((a, c) => a + (widths[c.key] ?? c.def), 0) + spec.nameMin + spec.chrome;
}

export function innerStyle(spec) {
  return `min-width:var(--rc-total,${totalFloor(spec)}px)`;
}

/** The right-edge handle. Focusable, so the keyboard can reach it. */
export function handleHtml(spec, key, label) {
  const c = col(spec, key);
  return `<span class="rc-handle" data-rc-handle="${key}" role="separator" aria-orientation="vertical" tabindex="0" `
    + `aria-label="Resize the ${String(label).replace(/"/g, '&quot;')} column (arrow keys; double-click resets)" `
    + `aria-valuemin="${c.min}" aria-valuenow="${c.def}"></span>`;
}

/** Header cell style: one line, ellipsis, the full text in the cell's title. */
export const headCellStyle = 'position:relative;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:6px';

function readStore(win, spec) {
  try {
    const raw = win.localStorage.getItem(STORE(spec));
    const o = raw ? JSON.parse(raw) : {};
    const out = {};
    for (const c of spec.columns) {
      const v = o && o[c.key];
      if (typeof v === 'number' && Number.isFinite(v) && v >= c.min) out[c.key] = Math.round(v);
    }
    return out;
  } catch (_e) { return {}; }
}

function writeStore(win, spec, widths) {
  try {
    if (Object.keys(widths).length) win.localStorage.setItem(STORE(spec), JSON.stringify(widths));
    else win.localStorage.removeItem(STORE(spec));
  } catch (_e) { /* storage unavailable: widths last for this page only */ }
}

const attached = new WeakMap();

export function attachColumnResize(host, spec, { onChange } = {}) {
  if (attached.has(host)) return attached.get(host);
  const win = host.ownerDocument.defaultView;
  let widths = readStore(win, spec);
  const widthOf = (key) => widths[key] ?? col(spec, key).def;

  /** The most `key` may take: what the host shows, less every other column and the name floor. */
  const maxOf = (key) => {
    const c = col(spec, key);
    const avail = host.clientWidth;
    if (!avail) return Infinity;
    const others = spec.columns.reduce((a, x) => a + (x.key === key ? 0 : widthOf(x.key)), 0);
    return Math.max(c.min, avail - others - spec.nameMin - spec.chrome);
  };
  const clamp = (key, w) => Math.round(Math.min(maxOf(key), Math.max(col(spec, key).min, w)));

  const apply = () => {
    for (const c of spec.columns) {
      if (widths[c.key] != null) host.style.setProperty(VAR(c.key), `${widths[c.key]}px`);
      else host.style.removeProperty(VAR(c.key));
    }
    host.style.setProperty('--rc-total', `${totalFloor(spec, widths)}px`);
    host.querySelectorAll('[data-rc-handle]').forEach((h) => {
      h.setAttribute('aria-valuenow', String(widthOf(h.dataset.rcHandle)));
    });
    if (onChange) onChange(api.isCustom());
  };
  const persist = () => writeStore(win, spec, widths);
  const set = (key, w) => { widths = { ...widths, [key]: clamp(key, w) }; apply(); };
  const resetOne = (key) => { const { [key]: _gone, ...rest } = widths; widths = rest; apply(); persist(); };

  const api = {
    isCustom: () => Object.keys(widths).length > 0,
    width: widthOf,
    reset: () => { widths = {}; apply(); persist(); },
    apply,
  };
  attached.set(host, api);

  let drag = null;
  host.addEventListener('pointerdown', (e) => {
    const h = e.target.closest && e.target.closest('[data-rc-handle]');
    if (!h || (e.button != null && e.button > 0)) return;
    e.preventDefault();
    drag = { key: h.dataset.rcHandle, x: e.clientX, w: widthOf(h.dataset.rcHandle), el: h };
    h.setAttribute('data-rc-active', '');
    const doc = host.ownerDocument;
    const move = (m) => { if (drag) set(drag.key, drag.w + (m.clientX - drag.x)); };
    const up = () => {
      doc.removeEventListener('pointermove', move);
      doc.removeEventListener('pointerup', up);
      doc.removeEventListener('pointercancel', up);
      if (drag) { drag.el.removeAttribute('data-rc-active'); persist(); }
      drag = null;
    };
    doc.addEventListener('pointermove', move);
    doc.addEventListener('pointerup', up);
    doc.addEventListener('pointercancel', up);
  });
  host.addEventListener('dblclick', (e) => {
    const h = e.target.closest && e.target.closest('[data-rc-handle]');
    if (h) { e.preventDefault(); resetOne(h.dataset.rcHandle); }
  });
  host.addEventListener('keydown', (e) => {
    const h = e.target.closest && e.target.closest('[data-rc-handle]');
    if (!h || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
    e.preventDefault();
    const key = h.dataset.rcHandle;
    set(key, widthOf(key) + (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? STEP_BIG : STEP));
    persist();
  });
  apply();
  return api;
}
