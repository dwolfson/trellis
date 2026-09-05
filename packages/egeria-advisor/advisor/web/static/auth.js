/**
 * Egeria Advisor — Auth module
 *
 * Manages JWT-based authentication state in sessionStorage.
 * Handles standalone login, portal SSO (postMessage + URL fragment), and logout.
 *
 * Usage:
 *   Auth.getHeaders()          — object with Authorization header for fetch calls
 *   Auth.isAuthenticated()     — boolean
 *   Auth.showLogin()           — programmatically show the login overlay
 *   Auth.init(onReady)         — call on DOMContentLoaded; fires onReady() when done
 */
const Auth = (() => {
  const TOKEN_KEY = 'ea_token';

  // ── Token helpers ────────────────────────────────────────────────────────

  function getToken() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    sessionStorage.removeItem(TOKEN_KEY);
  }

  function isAuthenticated() {
    const token = getToken();
    if (!token) return false;
    try {
      // Decode the JWT payload (no signature verification — server handles that)
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.exp > Math.floor(Date.now() / 1000);
    } catch {
      return false;
    }
  }

  function getUser() {
    const token = getToken();
    if (!token) return null;
    try {
      return JSON.parse(atob(token.split('.')[1]));
    } catch {
      return null;
    }
  }

  function getHeaders() {
    const token = getToken();
    return token ? { 'Authorization': `Bearer ${token}` } : {};
  }

  // ── UI helpers ───────────────────────────────────────────────────────────

  // Whether the server requires a signed-in user. Fetched once from the public
  // /api/auth/policy route at init; assumed true until then, because assuming
  // "login optional" and being wrong means starting the app into a page where
  // every panel is a failed fetch — the broken page this is here to prevent.
  let loginRequired = true;

  async function loadPolicy() {
    try {
      const r = await fetch('/api/auth/policy');
      if (!r.ok) return;
      const data = await r.json();
      loginRequired = data.login_required !== false;
    } catch {
      // Server unreachable — keep the safe default (login required).
    }
  }

  function showLogin(message) {
    // The "continue without signing in" footer only makes sense in the dev-only
    // anonymous-read mode; with login required it leads straight to a 401.
    const anonFooter = document.getElementById('login-anon-footer');
    if (anonFooter) anonFooter.hidden = loginRequired;
    const overlay = document.getElementById('login-overlay');
    if (!overlay) return;
    if (message) {
      const msg = document.getElementById('login-message');
      if (msg) { msg.textContent = message; msg.classList.remove('hidden'); }
    }
    overlay.classList.remove('hidden');
    setTimeout(() => document.getElementById('login-username')?.focus(), 50);
  }

  function hideLogin() {
    // When the server requires login, the overlay is not dismissible: hiding it
    // would reveal a shell whose every API call 401s. Dismissing is only a
    // choice in the dev-only TRELLIS_ANONYMOUS_READ mode, where reads work.
    if (loginRequired && !isAuthenticated()) return;
    const overlay = document.getElementById('login-overlay');
    if (overlay) overlay.classList.add('hidden');
    const msg = document.getElementById('login-message');
    if (msg) msg.classList.add('hidden');
    const err = document.getElementById('login-error');
    if (err) { err.textContent = ''; err.classList.add('hidden'); }
    // Show the "Sign in" button in the header so user can get back to login
    const signinBtn = document.getElementById('login-header-btn');
    if (signinBtn && !isAuthenticated()) signinBtn.classList.remove('hidden');
  }

  function updateUserDisplay() {
    const el = document.getElementById('current-user');
    if (!el) return;
    const user = getUser();
    const signinBtn = document.getElementById('login-header-btn');
    if (user) {
      el.textContent = user.egeria_user || user.sub || '';
      el.classList.remove('hidden');
      document.getElementById('logout-btn')?.classList.remove('hidden');
      if (signinBtn) signinBtn.classList.add('hidden');
    } else {
      el.textContent = '';
      el.classList.add('hidden');
      document.getElementById('logout-btn')?.classList.add('hidden');
    }
  }

  function setLoginLoading(loading) {
    const btn = document.getElementById('login-submit-btn');
    if (!btn) return;
    btn.disabled = loading;
    btn.textContent = loading ? 'Signing in…' : 'Sign in';
  }

  // Best-effort prefill of the username field from the server's configured
  // default (.env EGERIA_USER), for local/dev convenience. Never touches the
  // password field, and never overwrites anything the user has already typed.
  async function prefillLoginDefaults() {
    const userEl = document.getElementById('login-username');
    if (!userEl || userEl.value) return;
    try {
      const r = await fetch('/api/auth/defaults');
      if (!r.ok) return;
      const data = await r.json();
      if (!userEl.value && data.username) userEl.value = data.username;
    } catch {
      // Best-effort only — leave the field blank on any failure.
    }
  }

  // ── Login flow ───────────────────────────────────────────────────────────

  async function doLogin() {
    const username = document.getElementById('login-username')?.value.trim();
    const password = document.getElementById('login-password')?.value;
    const errEl    = document.getElementById('login-error');

    if (!username || !password) {
      if (errEl) { errEl.textContent = 'Please enter username and password.'; errEl.classList.remove('hidden'); }
      return;
    }

    setLoginLoading(true);
    if (errEl) errEl.classList.add('hidden');

    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await r.json();
      if (!r.ok) {
        const msg = data.detail || 'Login failed.';
        if (errEl) { errEl.textContent = msg; errEl.classList.remove('hidden'); }
        return;
      }
      setToken(data.access_token);
      hideLogin();
      updateUserDisplay();
      // Signal the app that auth succeeded
      document.dispatchEvent(new CustomEvent('ea:authenticated', { detail: { user: data.egeria_user } }));
    } catch (e) {
      if (errEl) { errEl.textContent = `Connection error: ${e.message}`; errEl.classList.remove('hidden'); }
    } finally {
      setLoginLoading(false);
    }
  }

  function doLogout() {
    clearToken();
    updateUserDisplay();
    fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
    showLogin();
  }

  // ── Portal SSO ───────────────────────────────────────────────────────────

  async function exchangePortalToken(portalToken) {
    try {
      const r = await fetch('/api/auth/portal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ portal_token: portalToken }),
      });
      if (!r.ok) return false;
      const data = await r.json();
      setToken(data.access_token);
      updateUserDisplay();
      document.dispatchEvent(new CustomEvent('ea:authenticated', { detail: { user: data.egeria_user } }));
      return true;
    } catch {
      return false;
    }
  }

  function listenForPortalMessage() {
    window.addEventListener('message', async (event) => {
      // Only accept messages from configured portal origins
      const allowed = ['http://localhost:8885', window.location.origin];
      if (!allowed.includes(event.origin)) return;
      if (event.data?.type !== 'egeria_auth' || !event.data?.portal_token) return;
      await exchangePortalToken(event.data.portal_token);
    });
  }

  async function checkUrlFragment() {
    const hash = window.location.hash;
    if (!hash.startsWith('#pt=')) return false;
    const portalToken = hash.slice(4);
    // Clear the fragment immediately so credentials don't stay in the URL bar
    history.replaceState(null, '', window.location.pathname + window.location.search);
    return await exchangePortalToken(portalToken);
  }

  // ── Handle 401 responses ─────────────────────────────────────────────────

  function handle401() {
    clearToken();
    updateUserDisplay();
    showLogin('Your session has expired. Please sign in again.');
  }

  // Wrap window.fetch once so ANY API call that gets a 401 triggers the
  // re-login overlay — not just the couple of call sites that used to check
  // this manually. Individual call sites can still check r.status === 401
  // themselves for their own early-return/spinner-reset behavior; this just
  // guarantees the overlay always appears too, even from call sites that
  // never checked. Auth's own login/portal-exchange endpoints are excluded:
  // a 401 there means "wrong credentials", not "your session expired", and
  // they already show their own inline error message — firing handle401
  // there would clear the in-progress login attempt and show a confusing
  // "session expired" message instead of "invalid credentials".
  const _origFetch = window.fetch.bind(window);
  const _AUTH_ENDPOINTS_EXCLUDED_FROM_401_HANDLING = ['/api/auth/login', '/api/auth/portal'];
  window.fetch = async (...args) => {
    // Proactive check: most endpoints (e.g. /api/query) never actually
    // return 401 for an expired token — get_current_user() in auth.py
    // deliberately never raises, it just silently falls back to anonymous
    // and callers decide what "anonymous" means for them (often a plain
    // 200 response with an in-band "please sign in" message). A reactive
    // 401 check alone would miss this entirely, so also check locally: if
    // we're sending a token that's already expired by its own `exp` claim,
    // treat that the same as a 401 — no need to wait for a round-trip that
    // may never signal failure. Only fires once per expiry (guarded by
    // whether a token is still present — handle401 clears it).
    const token = getToken();
    if (token && !isAuthenticated()) {
      handle401();
    }
    const response = await _origFetch(...args);
    if (response.status === 401) {
      const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
      const isExcluded = _AUTH_ENDPOINTS_EXCLUDED_FROM_401_HANDLING.some(p => url.includes(p));
      if (!isExcluded) handle401();
    }
    return response;
  };

  // ── Init ─────────────────────────────────────────────────────────────────

  async function init(onReady) {
    // Wire up login form submit
    document.getElementById('login-submit-btn')?.addEventListener('click', doLogin);
    document.getElementById('login-password')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') doLogin();
    });
    document.getElementById('login-username')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') document.getElementById('login-password')?.focus();
    });

    // Wire up logout button
    document.getElementById('logout-btn')?.addEventListener('click', doLogout);

    // Deferred app start, for the login-required case below: registered here,
    // BEFORE the sidebar-refresh listener, because listeners fire in
    // registration order and `loadReports`/`loadPlans`/`loadDrafts` expect the
    // app to have been started. `once` — a later re-login must not start it
    // twice. The flag is what makes this a no-op on every other path.
    let appStartDeferred = false;
    document.addEventListener('ea:authenticated', () => {
      if (appStartDeferred) onReady && onReady();
    }, { once: true });

    // After login, refresh Egeria-dependent sidebar sections
    document.addEventListener('ea:authenticated', () => {
      updateUserDisplay();
      if (typeof loadReports === 'function') loadReports();
      if (typeof loadPlans   === 'function') loadPlans();
      if (typeof loadDrafts  === 'function') loadDrafts();
    });

    // Start portal SSO listener
    listenForPortalMessage();

    // Ask the server whether login is required before deciding what to do with
    // an unauthenticated visitor. Runs alongside the Portal fragment check
    // rather than before it, so the SSO path pays nothing for it.
    const [, fromPortal] = await Promise.all([loadPolicy(), checkUrlFragment()]);

    // Already have a valid token (or just got one from portal — the Portal
    // exchange route is public, so an embedded Advisor never sees this form).
    if (isAuthenticated()) {
      updateUserDisplay();
      onReady && onReady();
      return;
    }

    // No valid token. When the server requires login (the default since
    // 2026-09-04), show the form and do NOT start the app: every panel it
    // would populate is a 401, which is exactly the broken page this replaces.
    // `ea:authenticated` starts it once sign-in succeeds.
    await prefillLoginDefaults();
    if (loginRequired) {
      appStartDeferred = true;
      showLogin('Sign in with your Egeria user id to continue.');
      return;
    }

    // Dev-only anonymous-read mode: reads work without a token, so start the
    // app and leave the (dismissible) overlay up for whoever wants to sign in.
    onReady && onReady();
    showLogin();
  }

  return { init, isAuthenticated, getToken, getHeaders, getUser, showLogin, hideLogin, doLogout, handle401, updateUserDisplay };
})();
