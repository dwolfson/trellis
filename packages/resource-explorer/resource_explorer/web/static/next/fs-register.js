/* Register a file system on /next (Files step 1, parity PI-022).
 *
 * Reached from the sidebar's "＋ Add a file system" (the Find action while the FS chip is on). The form posts to
 * the existing `POST /api/filesystems/` with the route's own model and nothing else:
 *
 *   slug, display_name, local_mount_point, canonical_mount_point, group_slug
 *
 * There is NO Egeria field. The platform URL and view server come from the platform configuration the server
 * already reads (classic's modal asked for them per resource; that is dropped on purpose). Registering sends
 * nothing to Egeria: attaching the root folder is the Publish on the file system's Curate page.
 *
 * Validation is a cue on the field (a glyph and a short word), not a sentence below the form:
 *   slug already registered     ✕  an ERROR: Register is held until the slug changes
 *   mount this server can't read ⚠  a WARNING: registering is still allowed (the server may see another path)
 * The word beside the glyph says which one applies. Words here are placeholders for the designer.
 *
 * On success the file system is in the sidebar under FS and selected, read back from the re-fetched list.
 */
import { esc, state, ensureResourceListLoaded, refreshGroupsAndSidebar, selectResourceFromChat }
  from '/static/next/app.js';
import { openDialog, closeCellDetail } from '/static/next/worklist.js';
import { registerFilesystem, checkFilesystemMount, listGroups } from '/static/re-api.js';

/** Placeholder words, in one table so the designer's words replace them in one place. */
export const FS_REGISTER_WORDS = {
  title: 'Add a file system',
  sub: 'Registering stores it here. Nothing is sent to Egeria.',
  slugTaken: 'already registered',
  mountUnreadable: "this server can't read this path · you can still register",
  mountNotFolder: 'this is a file, not a folder · you can still register',
  mountReadable: 'readable here',
  mountChecking: 'checking',
  register: 'Register',
  registering: 'Registering…',
};

const blank = () => ({ slug: '', display_name: '', local_mount_point: '', canonical_mount_point: '', group_slug: '' });

const view = {
  f: blank(),
  groups: [],
  mount: { state: 'unchecked', path: '' },   // unchecked | checking | readable | not_readable | not_a_folder
  takenByServer: '',                          // a slug the server itself refused as already registered
  reg: { phase: 'idle', error: '' },          // idle | saving | error
};

/** The slug as the registry stores it (dashes become underscores, lower case). */
export const storedSlug = (slug) => String(slug || '').trim().replace(/-/g, '_').toLowerCase();

/** Is this slug already a registered file system? From the list on screen, and from the server's own refusal. */
export function slugIsTaken(slug) {
  const s = storedSlug(slug);
  if (!s) return false;
  if (view.takenByServer && storedSlug(view.takenByServer) === s) return true;
  return (state.filesystems || []).some((r) => storedSlug(r.slug) === s);
}

const requiredFilled = (f) => !!(f.slug && f.display_name && f.local_mount_point);
const canRegister = () => requiredFilled(view.f) && !slugIsTaken(view.f.slug) && view.reg.phase !== 'saving';

/** The cue for the slug field: '' when fine. */
function slugCue() {
  return slugIsTaken(view.f.slug)
    ? { kind: 'error', glyph: '✕', word: FS_REGISTER_WORDS.slugTaken } : null;
}
/** The cue for the mount field: '' until it has been checked. */
function mountCue() {
  const s = view.mount.state;
  if (s === 'checking') return { kind: 'info', glyph: '◔', word: FS_REGISTER_WORDS.mountChecking };
  if (s === 'readable') return { kind: 'ok', glyph: '✓', word: FS_REGISTER_WORDS.mountReadable };
  if (s === 'not_readable') return { kind: 'warning', glyph: '⚠', word: FS_REGISTER_WORDS.mountUnreadable };
  if (s === 'not_a_folder') return { kind: 'warning', glyph: '⚠', word: FS_REGISTER_WORDS.mountNotFolder };
  return null;
}
const cueHtml = (cue, field) => (cue
  ? `<span data-fs-cue="${field}" data-cue-kind="${cue.kind}" class="${
    cue.kind === 'error' ? 'text-state-warn' : cue.kind === 'warning' ? 'text-ink' : 'text-ink-muted'}"><span class="font-glyph" aria-hidden="true">${cue.glyph}</span> ${esc(cue.word)}</span>`
  : `<span data-fs-cue="${field}" data-cue-kind="none"></span>`);

const inputClass = (cue) => `w-full rounded-sm border ${
  cue && cue.kind === 'error' ? 'border-state-warn' : cue && cue.kind === 'warning' ? 'border-state-gap' : 'border-rule'
} bg-transparent px-2 py-[3px] text-caveat text-ink`;

function formHtml() {
  const f = view.f;
  const sc = slugCue();
  const mc = mountCue();
  const field = (label, cueSlot, inner) => `<div>
    <div class="mb-[2px] flex flex-wrap items-baseline gap-s2"><label class="text-caps uppercase tracking-caps text-ink-muted">${esc(label)}</label>${cueSlot}</div>${inner}</div>`;
  const input = (key, placeholder, cue) =>
    `<input data-fsr="${key}" type="text" placeholder="${esc(placeholder)}" autocomplete="off" value="${esc(f[key] ?? '')}"
       class="${inputClass(cue)}">`;
  const groupOptions = view.groups.map((g) =>
    `<option value="${esc(g.slug)}" ${f.group_slug === g.slug ? 'selected' : ''}>${esc(g.display_name)}</option>`).join('');
  const saving = view.reg.phase === 'saving';
  return `
    <div class="grid grid-cols-2 gap-s2">
      ${field('Slug *', cueHtml(sc, 'slug'), input('slug', 'my-data', sc))}
      ${field('Display name *', '', input('display_name', 'My shared mount'))}
    </div>
    <div class="mt-s2">${field('Mount (local path) *', cueHtml(mc, 'mount'), input('local_mount_point', '/path/to/local/data', mc))}</div>
    <div class="mt-s2">${field('Canonical mount (blank = the mount)', '', input('canonical_mount_point', 'file://shared-nfs/data'))}</div>
    <div class="mt-s2">${field('Group', '', `<select data-fsr="group_slug" class="w-full rounded-sm border border-rule bg-transparent px-2 py-[3px] text-caveat text-ink">
      <option value="">No group</option>${groupOptions}</select>`)}</div>
    <div class="mt-s3 flex items-center gap-s2">
      <button data-act="fsr-register" ${canRegister() ? '' : 'disabled'}
        class="cursor-pointer rounded-sm border border-accent bg-transparent px-s3 py-[3px] text-caveat text-accent-ink disabled:cursor-default disabled:opacity-60"
        >${saving ? FS_REGISTER_WORDS.registering : FS_REGISTER_WORDS.register}</button>
      <span data-fsr-state class="text-caveat text-state-warn">${view.reg.error ? esc(view.reg.error) : ''}</span>
    </div>`;
}

/** Read the inputs into memory. */
function capture(host) {
  host.querySelectorAll('[data-fsr]').forEach((inp) => {
    view.f[inp.dataset.fsr] = inp.value.trim();
  });
}

/** Repaint the cues and the Register button in place (no re-render: the typing focus stays where it is). */
function paintCues(host) {
  const set = (field, cue, inputKey) => {
    const slot = host.querySelector(`[data-fs-cue="${field}"]`);
    if (slot) slot.outerHTML = cueHtml(cue, field);
    const inp = host.querySelector(`[data-fsr="${inputKey}"]`);
    if (inp) inp.className = inputClass(cue);
  };
  set('slug', slugCue(), 'slug');
  set('mount', mountCue(), 'local_mount_point');
  const reg = host.querySelector('[data-act="fsr-register"]');
  if (reg) reg.disabled = !canRegister();
}

function bind(host) {
  host.querySelectorAll('[data-fsr]').forEach((inp) => {
    inp.addEventListener('input', () => {
      capture(host);
      if (inp.dataset.fsr === 'local_mount_point' && view.mount.path !== view.f.local_mount_point) {
        view.mount = { state: 'unchecked', path: '' };       // a changed path is not the checked one
      }
      paintCues(host);
    });
  });
  host.querySelector('[data-fsr="local_mount_point"]')?.addEventListener('change', () => checkMount(host));
  host.querySelector('[data-fsr="group_slug"]')?.addEventListener('change', () => capture(host));
  host.querySelector('[data-act="fsr-register"]')?.addEventListener('click', () => submit(host));
}

/** Ask the server whether it can read the mount. A warning at most; it never gates Register. */
async function checkMount(host) {
  capture(host);
  const path = view.f.local_mount_point;
  if (!path) { view.mount = { state: 'unchecked', path: '' }; paintCues(host); return; }
  view.mount = { state: 'checking', path };
  paintCues(host);
  let answer;
  try {
    answer = await checkFilesystemMount(path);
  } catch (_) {
    if (view.mount.path === path) view.mount = { state: 'unchecked', path: '' };   // could not ask: no claim either way
    paintCues(host);
    return;
  }
  if (view.mount.path !== path) return;                          // a newer path is being checked
  const st = answer && answer.state;
  view.mount = { state: ['readable', 'not_readable', 'not_a_folder'].includes(st) ? st : 'unchecked', path };
  paintCues(host);
}

async function submit(host) {
  capture(host);
  if (view.reg.phase === 'saving') return;                       // a second press is ignored
  if (!canRegister()) { paintCues(host); return; }
  const f = view.f;
  view.reg = { phase: 'saving', error: '' };
  paintCues(host);
  const btn = host.querySelector('[data-act="fsr-register"]');
  if (btn) btn.textContent = FS_REGISTER_WORDS.registering;
  let out;
  try {
    out = await registerFilesystem({
      slug: f.slug, display_name: f.display_name, local_mount_point: f.local_mount_point,
      canonical_mount_point: f.canonical_mount_point, group_slug: f.group_slug,
    });
  } catch (err) {
    const taken = err && err.status === 400 && /already registered/i.test(String(err.message || ''));
    if (taken) {
      // The cue is on the slug field; there is no sentence to add below the form.
      view.takenByServer = f.slug;
      view.reg = { phase: 'idle', error: '' };
    } else {
      view.reg = {
        phase: 'error',
        error: err && err.status === 401 ? 'not registered · sign in to register a file system'
          : `not registered · ${err && err.message ? err.message : err}`,
      };
    }
    const line = host.querySelector('[data-fsr-state]');
    if (line) line.textContent = view.reg.error;
    const b = host.querySelector('[data-act="fsr-register"]');
    if (b) b.textContent = FS_REGISTER_WORDS.register;
    paintCues(host);
    return;
  }
  // Registered. What follows is showing it: the list is re-read and the new row selected from that read.
  let selected = false;
  try {
    await ensureResourceListLoaded('filesystem');
    await refreshGroupsAndSidebar();
    selected = await selectResourceFromChat('filesystem', out.slug);
  } catch (_) { selected = false; }
  if (selected) {
    view.f = blank();
    view.mount = { state: 'unchecked', path: '' };
    view.reg = { phase: 'idle', error: '' };
    closeCellDetail();
    return;
  }
  view.reg = { phase: 'error', error: 'registered, but the list could not be re-read' };
  const line = host.querySelector('[data-fsr-state]');
  if (line) line.textContent = view.reg.error;
  const b = host.querySelector('[data-act="fsr-register"]');
  if (b) b.textContent = FS_REGISTER_WORDS.register;
  paintCues(host);
}

/** Open the dialog from a clean form. */
export async function openRegisterFileSystemDialog() {
  const el = openDialog(FS_REGISTER_WORDS.title, FS_REGISTER_WORDS.sub);
  view.f = blank();
  view.mount = { state: 'unchecked', path: '' };
  view.takenByServer = '';
  view.reg = { phase: 'idle', error: '' };
  const body = el.querySelector('#wl-detail-body');
  // The list the duplicate check reads must be there before the first keystroke.
  await ensureResourceListLoaded('filesystem');
  try { view.groups = (await listGroups()) || []; } catch (_) { view.groups = []; }
  body.innerHTML = formHtml();
  bind(body);
  return el;
}
