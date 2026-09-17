/* Admin → Logs — the in-process ring buffer (observability/logging_setup.py).
 *
 * Full port of classic's `loadAdminLogsPanel`. Deliberately states what the
 * buffer is: bounded, in-memory, empty after a restart. Three different
 * empties, three different sentences (see `emptyHtml` below) — collapsing
 * them to one "no logs" message is the absence-as-answer failure this
 * codebase keeps finding elsewhere (null_pct, cii_badge) and this pane
 * exists specifically to not repeat.
 */
import { listLogs } from '/static/re-api.js';
import { esc } from '/static/next/app.js';

const LEVEL_TONE = {
  DEBUG: 'text-ink-muted', INFO: 'text-ink', WARNING: 'text-state-warn',
  ERROR: 'text-state-warn', CRITICAL: 'text-state-warn',
};

const filter = { level: '', logger: '' };
let auto = false;
let timer = null;
let _host = null;

function emptyHtml(buf, filtered) {
  if (filtered) {
    return `<p class="py-s4 text-center text-caveat text-ink-muted">No records match this filter.
      ${buf.held} record${buf.held === 1 ? '' : 's'} held in total — clear the filter to see them.</p>`;
  }
  if (buf.held === 0) {
    return `<p class="py-s4 text-center text-caveat text-ink-muted">The buffer is empty.<br>
      <span class="text-ink-muted">It is in-memory and starts empty on every restart, so this is
      not evidence that nothing has happened.</span></p>`;
  }
  return '<p class="py-s4 text-center text-caveat text-ink-muted">No records to show.</p>';
}

function rowsHtml(rows) {
  return `<table class="w-full font-mono text-provenance">
    <tbody>${rows.map((r) => `<tr class="border-b border-rule align-top hover:bg-paper-raised">
      <td class="whitespace-nowrap px-[6px] py-[3px] text-ink-muted">${esc(r.ts || '')}</td>
      <td class="whitespace-nowrap px-[6px] py-[3px] ${LEVEL_TONE[r.level] || 'text-ink-muted'}">${esc(r.level || '')}</td>
      <td class="whitespace-nowrap px-[6px] py-[3px] text-accent-ink">${esc(r.logger || '')}</td>
      <td class="whitespace-pre-wrap break-words px-[6px] py-[3px] text-ink">${esc(r.message || '')}${
        r.exc ? `<pre class="mt-[2px] whitespace-pre-wrap break-words text-state-warn">${esc(r.exc)}</pre>` : ''}</td>
    </tr>`).join('')}</tbody></table>`;
}

function chip(label, value) {
  const active = filter.level === value;
  return `<button type="button" data-level="${esc(value)}"
    class="cursor-pointer rounded-sm border px-2 py-[2px] text-caveat
      ${active ? 'border-accent text-accent-ink' : 'border-rule-strong text-ink-muted hover:text-ink'}"
    >${esc(label)}</button>`;
}

async function reload() {
  if (!_host) return;
  let data;
  try {
    data = await listLogs({ limit: 300, level: filter.level, logger: filter.logger });
  } catch (err) {
    _host.innerHTML = `<p class="max-w-[70ch] text-answer text-state-warn">Could not load logs: ${esc(err.message)}</p>`;
    return;
  }
  const rows = data.records || [];
  const buf = data.buffer || {};
  const body = rows.length ? rowsHtml(rows) : emptyHtml(buf, data.filtered);

  _host.innerHTML = `
    <h3 class="m-0 font-heading text-name font-normal text-ink">📜 Logs</h3>
    <p class="mt-[2px] max-w-[65ch] text-caveat text-ink-muted">
      ${buf.held ?? 0} of ${buf.capacity ?? '?'} records held${buf.full ? ' — <span class="text-state-warn">buffer full, oldest are being dropped</span>' : ''}.
      Root level ${esc(data.root_level || '')}.
    </p>
    <p class="mt-[2px] max-w-[65ch] text-provenance text-ink-muted">${esc(buf.note || '')}</p>
    <div class="my-s3 flex flex-wrap items-center gap-[6px]">
      ${chip('All', '')}
      ${(data.levels || []).map((l) => chip(l, l)).join('')}
      <span class="px-[2px] text-ink-muted">|</span>
      <input data-logger-filter value="${esc(filter.logger)}" placeholder="logger name prefix"
        class="w-56 rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-caveat text-ink" />
      <button type="button" data-refresh
        class="cursor-pointer rounded-sm border border-rule-strong bg-transparent px-2 py-[2px] text-caveat text-ink hover:border-accent">↻ Refresh</button>
      <label class="flex items-center gap-[4px] text-caveat text-ink-muted">
        <input type="checkbox" data-auto ${auto ? 'checked' : ''} /> auto
      </label>
    </div>
    <div class="max-h-[46vh] overflow-auto rounded-sm border border-rule">${body}</div>`;

  bind();
}

function bind() {
  if (!_host) return;
  _host.querySelectorAll('[data-level]').forEach((b) => b.addEventListener('click', () => {
    filter.level = b.dataset.level;
    reload();
  }));
  const loggerInput = _host.querySelector('[data-logger-filter]');
  if (loggerInput) loggerInput.addEventListener('change', (e) => {
    filter.logger = e.target.value.trim();
    reload();
  });
  const refresh = _host.querySelector('[data-refresh]');
  if (refresh) refresh.addEventListener('click', () => reload());
  const autoBox = _host.querySelector('[data-auto]');
  if (autoBox) autoBox.addEventListener('change', (e) => setAuto(e.target.checked));
}

function setAuto(on) {
  auto = on;
  if (timer) { clearInterval(timer); timer = null; }
  if (!on) return;
  // Stops itself once the panel closes (the host element leaves the DOM),
  // rather than polling for the rest of the session — same rule classic's
  // version follows.
  timer = setInterval(() => {
    // Stops when the panel closes OR when the Admin subnav has switched to a
    // different pane — otherwise this timer would keep overwriting whatever
    // pane now occupies the same host element with stale logs content.
    if (!_host || !document.body.contains(_host) || _host.dataset.adminPane !== 'logs') {
      clearInterval(timer); timer = null; auto = false; return;
    }
    reload();
  }, 5000);
}

export async function renderLogs(host) {
  _host = host;
  host.dataset.adminPane = 'logs';
  filter.level = '';
  filter.logger = '';
  await reload();
}
