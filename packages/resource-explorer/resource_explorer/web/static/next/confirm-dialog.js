/* The app's in-page confirm and failure pop-up.
 *
 * A native `window.confirm` is declined by embedded browsers (the press then does nothing, silently) and cannot
 * be styled or tested like the rest of the page. These two draw a modal in the page and answer through a promise:
 *
 *   inPageConfirm({ title, message, confirmLabel })  -> Promise<boolean>   (Cancel, Escape, or a click outside = false)
 *   inPageNotice({ title, message })                 -> Promise<void>      (the failure pop-up: one Close button)
 *
 * No import of app.js, so any admin pane or stage can use it and a test can load it alone. */

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function open({ title, message, buttons, attr }) {
  const doc = document;
  // One dialog of a kind at a time: an older one is answered "no" (never left hanging) before the new one opens.
  doc.querySelectorAll(`[${attr}]`).forEach((n) => (n.__done ? n.__done(false) : n.remove()));
  return new Promise((resolve) => {
    const box = doc.createElement('div');
    box.setAttribute(attr, '1');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', title);
    box.className = 'fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-black/40 p-s4';
    box.innerHTML = `<div class="mt-[6vh] w-full max-w-[560px] rounded bg-paper p-s4 text-caveat text-ink shadow-lg">
      <div data-dialog-title class="text-answer text-ink">${esc(title)}</div>
      <div data-dialog-message class="mt-s1 text-ink" style="white-space:pre-line">${esc(message)}</div>
      <div class="mt-s3 flex flex-wrap gap-s3">${buttons.map((b) =>
    `<button type="button" ${b.attr} class="cursor-pointer rounded-sm border bg-transparent px-2 py-[2px] text-caveat ${b.primary ? 'border-accent text-accent-ink' : 'border-rule-strong text-ink'}">${esc(b.label)}</button>`).join('')}</div>
    </div>`;
    const done = (v) => { doc.removeEventListener('keydown', onKey); box.remove(); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    box.__done = done;
    doc.addEventListener('keydown', onKey);
    buttons.forEach((b) => box.querySelector(`[${b.attr}]`).addEventListener('click', () => done(b.value)));
    doc.body.appendChild(box);
    box.querySelector(`[${buttons[0].attr}]`)?.focus?.();
  });
}

/** Ask. Resolves true only when the confirm button is pressed. */
export function inPageConfirm({ title = 'Are you sure?', message = '', confirmLabel = 'Confirm', cancelLabel = 'Cancel' } = {}) {
  return open({
    title, message, attr: 'data-confirm-dialog',
    buttons: [
      { attr: 'data-confirm-no', label: cancelLabel, value: false },
      { attr: 'data-confirm-yes', label: confirmLabel, value: true, primary: true },
    ],
  });
}

/** Tell: the failure pop-up. Resolves when closed. */
export function inPageNotice({ title = 'That did not finish', message = '' } = {}) {
  return open({
    title, message, attr: 'data-notice-dialog',
    buttons: [{ attr: 'data-notice-close', label: 'Close', value: true, primary: true }],
  }).then(() => undefined);
}
