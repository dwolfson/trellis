/* Admin → Annotation Types — read-only browse of the registry.
 *
 * Classic (index.html `loadAnnotationTypesView`) offers a list, a detail
 * view, and Register/Edit/Delete modals. This port keeps the list and detail
 * views — genuinely useful on their own, and the whole reason CLAUDE.md
 * names this pane first among the three it still describes as reachable
 * from ⚙ Admin — and defers the three mutating actions: registering a new
 * annotation type changes what the Questions engine and Egeria publishing
 * recognise app-wide, and that is exactly the kind of write this item's
 * verification could not exercise against a live signed-in session (see
 * ITEM-5-ADMIN-IMPLEMENTED.md). A viewer that cannot mutate is still real
 * work — it answers "what annotation types exist and what do they map to
 * in Egeria", which is the question this registry exists to answer.
 */
import { listAnnotationTypes } from '/static/re-api.js';
import { esc, icon, oldUiHref } from '/static/next/app.js';

let _types = null;
let _selected = null;

function listHtml() {
  const rows = (_types || []).map((a) => `
    <tr data-select-type="${esc(a.type)}" class="cursor-pointer border-b border-rule hover:bg-paper-raised">
      <td class="py-s2 pr-s3 text-answer text-ink">${esc(a.display_name || a.type)}</td>
      <td class="py-s2 pr-s3 font-mono text-caveat text-accent-ink">${esc(a.type)}</td>
      <td class="max-w-[28ch] truncate py-s2 pr-s3 text-caveat text-ink-muted" title="${esc(a.description || '')}">${esc(a.description || '—')}</td>
      <td class="py-s2 font-mono text-caveat text-ink-muted">${esc(a.egeria_type || '—')}</td>
    </tr>`).join('');

  return `
    <div class="mb-s3 flex items-start justify-between gap-s3">
      <div>
        <h3 class="m-0 font-heading text-name font-normal text-ink">Annotation Types registry</h3>
        <p class="mt-[2px] max-w-[65ch] text-caveat text-ink-muted">Metadata annotation schemas and
          their mapping to Egeria framework properties. Registering or editing a type is not built
          here — <a href="${esc(oldUiHref())}" class="text-accent-ink underline">open the current
          UI</a> ${icon('external-link', { size: 12, cls: 'text-accent-ink' })} for that.</p>
      </div>
    </div>
    ${_types && _types.length ? `<table class="w-full text-left">
      <thead><tr class="border-b border-rule text-caps uppercase tracking-caps text-ink-muted">
        <th class="pb-s2 pr-s3 font-normal">Display name</th>
        <th class="pb-s2 pr-s3 font-normal">Type key</th>
        <th class="pb-s2 pr-s3 font-normal">Description</th>
        <th class="pb-s2 font-normal">Egeria class</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>` : '<p class="text-answer text-ink-muted">No annotation types registered.</p>'}`;
}

function detailHtml(a) {
  const props = (a.properties || []).length
    ? a.properties.map((p) => `<span class="mr-[4px] mb-[4px] inline-block rounded-sm border border-rule-strong px-2 py-[1px] font-mono text-provenance text-ink">${esc(p)}</span>`).join('')
    : '<span class="text-caveat text-ink-muted">No properties defined.</span>';

  return `
    <button type="button" data-back class="mb-s3 cursor-pointer bg-transparent p-0 text-caveat text-accent-ink underline">← All annotation types</button>
    <div class="mb-s3 flex items-start justify-between gap-s3">
      <div>
        <div class="text-caps uppercase tracking-caps text-accent-ink">Annotation type schema</div>
        <h3 class="m-0 mt-[2px] font-heading text-name font-normal text-ink">${esc(a.display_name || a.type)}</h3>
        <div class="mt-[2px] font-mono text-caveat text-ink-muted">${esc(a.type)}</div>
      </div>
      <a href="${esc(oldUiHref())}" class="whitespace-nowrap text-caveat text-accent-ink underline"
        >Edit/Delete in current UI</a>
    </div>
    <div class="my-s3 h-px bg-rule"></div>
    <div class="mb-s3">
      <div class="text-caps uppercase tracking-caps text-ink-muted">Description</div>
      <p class="mt-[4px] max-w-[65ch] text-answer text-ink">${esc(a.description || 'No description provided.')}</p>
    </div>
    <div class="mb-s3">
      <div class="text-caps uppercase tracking-caps text-ink-muted">Properties / attributes</div>
      <div class="mt-[6px]">${props}</div>
    </div>
    <div>
      <div class="text-caps uppercase tracking-caps text-ink-muted">Catalog bindings</div>
      <div class="mt-[6px] text-caveat text-ink-muted">Egeria property class</div>
      <div class="font-mono text-caveat text-ink">${esc(a.egeria_type || '—')}</div>
      <div class="mt-[6px] text-caveat text-ink-muted">Python representation class</div>
      <div class="font-mono text-caveat text-ink">${esc(a.python_class || '—')}</div>
    </div>`;
}

function bind(host) {
  host.querySelectorAll('[data-select-type]').forEach((r) => r.addEventListener('click', () => {
    _selected = (_types || []).find((a) => a.type === r.dataset.selectType) || null;
    host.innerHTML = _selected ? detailHtml(_selected) : listHtml();
    bind(host);
  }));
  const back = host.querySelector('[data-back]');
  if (back) back.addEventListener('click', () => {
    _selected = null;
    host.innerHTML = listHtml();
    bind(host);
  });
}

export async function renderAnnotationTypes(host) {
  _selected = null;
  _types = await listAnnotationTypes();
  host.innerHTML = listHtml();
  bind(host);
}
