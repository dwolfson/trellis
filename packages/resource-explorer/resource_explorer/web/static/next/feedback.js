// Floating "Feedback" button + modal for the /next UI.
//
// Deliberately independent of app.js and re-api.js (another agent is editing
// app.js concurrently) — plain `fetch`, no shared session-id helper, no
// imported ApiError. Self-initialises on import: builds the button, appends
// it, and lazily builds the modal the first time it's opened.
//
// Field names below are read from resource_explorer/web/routes/feedback.py's
// FeedbackSubmission model — verify there before changing any key.

const CATEGORIES = [
  { value: '', label: 'Category (optional)' },
  { value: 'bug', label: 'Bug' },
  { value: 'confusing', label: 'Confusing' },
  { value: 'suggestion', label: 'Suggestion' },
  { value: 'praise', label: 'Praise' },
];

// Per-tab session id, namespaced separately from the old UI's `re_session_id`
// so the two shells never collide if someone has both open.
const SESSION_KEY = 're_next_session_id';
function _sessionId() {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = 'next-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function _escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

let _rating = 0;
let _modalEl = null;

function _starsHtml() {
  let out = '';
  for (let i = 1; i <= 5; i++) {
    out += `<button type="button" class="fb-star cursor-pointer bg-transparent text-[1.1rem] leading-none px-[1px]" data-star="${i}" aria-label="${i} star${i === 1 ? '' : 's'}" aria-pressed="${i <= _rating}">${i <= _rating ? '●' : '○'}</button>`;
  }
  return out;
}

function _renderStars() {
  const wrap = _modalEl.querySelector('#fb-stars');
  if (wrap) wrap.innerHTML = _starsHtml();
}

function _buildModal() {
  const overlay = document.createElement('div');
  overlay.id = 'fb-modal-overlay';
  overlay.className = 'fixed inset-0 z-[90] flex items-center justify-center';
  overlay.style.background = 'rgba(27,26,25,0.55)';
  // `hidden` attribute loses to the `flex` utility (display:flex wins over
  // preflight's [hidden]); the `hidden` CLASS is ordered after `flex` and wins.
  overlay.classList.add('hidden');

  overlay.innerHTML = `
    <div id="fb-modal" role="dialog" aria-modal="true" aria-labelledby="fb-heading"
         class="w-[min(380px,92vw)] rounded-sm border border-chrome-line bg-paper p-s4 text-ink">
      <h2 id="fb-heading" class="mb-s3 font-heading text-caps tracking-caps uppercase text-ink">Feedback</h2>
      <div id="fb-body"></div>
    </div>
  `;

  document.body.appendChild(overlay);
  _modalEl = overlay;

  overlay.addEventListener('mousedown', (e) => {
    if (e.target === overlay) closeFeedbackModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _modalEl && !_modalEl.classList.contains('hidden')) closeFeedbackModal();
  });

  return overlay;
}

function _showError(msg) {
  const err = _modalEl.querySelector('#fb-error');
  if (!err) return;
  err.textContent = msg;
  err.hidden = false;
}

function openFeedbackModal() {
  if (!_modalEl) _buildModal();
  // Reset form state on every open — also undoes a previous submission's
  // "Thank you" message if the modal is reopened quickly.
  _rating = 0;
  _resetForm();
  _modalEl.classList.remove('hidden');
  const textarea = _modalEl.querySelector('#fb-message');
  if (textarea) textarea.focus();
}

function _resetForm() {
  if (!_modalEl) return;
  const body = _modalEl.querySelector('#fb-body');
  // Rebuild the body fresh in case a previous submission replaced it with
  // the "Thank you" message.
  body.innerHTML = `
    <div class="mb-s3">
      <div id="fb-stars" class="mb-[2px]">${_starsHtml()}</div>
    </div>
    <select id="fb-category" class="mb-s3 w-full rounded-sm border border-chrome-line bg-paper px-s2 py-[6px] text-resource text-ink">
      ${CATEGORIES.map(c => `<option value="${c.value}">${c.label}</option>`).join('')}
    </select>
    <textarea id="fb-message" rows="4" placeholder="What's on your mind?"
      class="mb-s3 w-full resize-y rounded-sm border border-chrome-line bg-paper px-s2 py-[6px] text-resource text-ink"></textarea>
    <input id="fb-email" type="email" placeholder="Email (optional)"
      class="mb-s3 w-full rounded-sm border border-chrome-line bg-paper px-s2 py-[6px] text-resource text-ink">
    <label class="mb-[6px] flex items-center gap-s1 text-chip text-ink-muted">
      <input type="checkbox" id="fb-wants-response"> I'd like a response
    </label>
    <label class="mb-s3 flex items-center gap-s1 text-chip text-ink-muted">
      <input type="checkbox" id="fb-consent"> OK to contact me about this feedback
    </label>
    <div id="fb-error" class="mb-s3 text-chip text-state-warn" hidden></div>
    <div class="flex justify-end gap-s2">
      <button id="fb-cancel" type="button" class="cursor-pointer rounded-sm border border-chrome-line bg-transparent px-s3 py-[6px] text-resource text-ink-muted">Cancel</button>
      <button id="fb-send" type="button" class="cursor-pointer rounded-sm border border-accent bg-transparent px-s3 py-[6px] text-resource text-accent-ink">Send</button>
    </div>
  `;
  body.querySelector('#fb-stars').addEventListener('click', (e) => {
    const btn = e.target.closest('.fb-star');
    if (!btn) return;
    const n = Number(btn.dataset.star);
    _rating = _rating === n ? 0 : n;
    _renderStars();
  });
  body.querySelector('#fb-cancel').addEventListener('click', closeFeedbackModal);
  body.querySelector('#fb-send').addEventListener('click', submitFeedback);
}

function closeFeedbackModal() {
  if (_modalEl) _modalEl.classList.add('hidden');
}

async function submitFeedback() {
  const body = _modalEl.querySelector('#fb-body');
  const message = body.querySelector('#fb-message').value.trim();
  const email = body.querySelector('#fb-email').value.trim();
  const category = body.querySelector('#fb-category').value;
  const wantsResponse = body.querySelector('#fb-wants-response').checked;
  const consent = body.querySelector('#fb-consent').checked;

  const err = body.querySelector('#fb-error');
  if (err) err.hidden = true;

  const payload = {
    session_id: _sessionId(),
    page: location.pathname + location.search,
    element_guid: '',
    rating: _rating > 0 ? _rating : null,
    category,
    message,
    email,
    wants_response: wantsResponse,
    consent_to_contact: consent,
    build_version: '',
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    locale: navigator.language || '',
  };

  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.status === 401) {
      _showError('Sign in to send feedback');
      return;
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = await res.json();
        if (data && data.detail) detail = data.detail;
      } catch {
        // body wasn't JSON — keep the plain status message
      }
      _showError(detail);
      return;
    }

    // Success — replace the form body with a single confirmation line, then
    // auto-close so the modal doesn't linger.
    body.innerHTML = `<p class="text-resource text-ink">Thank you — recorded.</p>`;
    setTimeout(closeFeedbackModal, 1500);
  } catch (e) {
    _showError(_escapeHtml(e && e.message ? e.message : 'Could not reach the server'));
  }
}

function _buildButton() {
  const btn = document.createElement('button');
  btn.id = 'next-feedback-btn';
  btn.type = 'button';
  btn.textContent = 'Feedback';
  btn.className =
    'fixed z-40 cursor-pointer rounded-sm border border-accent bg-chrome px-s3 py-[6px] ' +
    'text-chip text-accent-on-dark';
  btn.style.bottom = '16px';
  btn.style.right = '16px';
  btn.addEventListener('click', openFeedbackModal);
  document.body.appendChild(btn);
}

_buildButton();
