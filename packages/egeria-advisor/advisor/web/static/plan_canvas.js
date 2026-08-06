/**
 * plan_canvas.js — Plan Canvas built on ArtifactCanvas
 *
 * Two modes, chosen automatically by open():
 *   draft mode      — before a plan has been generated into a document.
 *                      data shape: draft spec (commands_identified, answers, title, doc_id)
 *                      sync:       PATCH /api/drafts/{id}/commands (auto, per edit)
 *   document mode    — once a doc_id exists. Edits apply to the actual plan
 *                      document (same one the full-screen Plan Editor edits),
 *                      not a separate draft copy that would silently diverge
 *                      from it. Sync is explicit (a Save button), matching
 *                      the full-screen editor, since every save re-writes the
 *                      whole document rather than patching a JSON list.
 *                      data shape: parsed via _parsePlanMarkdown() (plan_editor.js)
 *                      sync:       PUT /api/plans/{id} with markdown re-synthesised
 *                      via _synthesizePlanMarkdownFrom() (plan_editor.js)
 *
 * fields (both modes): GET /api/templates/{action}/fields?level={mode}
 */

// Shared with the adapters below — set by open()/openDocument(), read by
// _planAdapter/_planItemAdapter to decide which shape/endpoints to use.
let _planCanvasDocMode = false;

// ── Draft-mode data adapter ────────────────────────────────────────────────────

const _planDraftAdapter = {
  async fetch(draftId) {
    const r = await fetch(`/api/drafts/${encodeURIComponent(draftId)}`, { headers: Auth.getHeaders() });
    if (!r.ok) throw new Error(`draft ${draftId} not found`);
    const spec = await r.json();
    return {
      title: spec.title || '',
      items: spec.commands_identified || [],
      meta:  { id: draftId, doc_id: spec.doc_id, answers: spec.answers || {} },
    };
  },

  async patch(draftId, items) {
    const r = await fetch(`/api/drafts/${encodeURIComponent(draftId)}/commands`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json', ...Auth.getHeaders() },
      body:    JSON.stringify({ commands: items }),
    });
    if (!r.ok) return null;
    const data = await r.json().catch(() => null);
    if (!data) return null;
    // Translate the draft-commands-specific response shape to the generic
    // {warnings, items} shape ArtifactCanvas expects.
    return { warnings: data.warnings, items: data.commands };
  },
};

// ── Document-mode data adapter ─────────────────────────────────────────────────
// Reuses plan_editor.js's markdown parser/synthesiser so there is exactly one
// place that knows the Command Sequence markdown format.

const _planDocAdapter = {
  _narrative: '',
  _mode:      'basic',
  _outcome:   '',

  async fetch(docId) {
    const r = await fetch(`/api/plans/${encodeURIComponent(docId)}`, { headers: Auth.getHeaders() });
    if (!r.ok) throw new Error(`plan ${docId} not found`);
    const data   = await r.json();
    const parsed = _parsePlanMarkdown(data.content);
    this._narrative = parsed.narrative;
    this._outcome   = parsed.outcome;
    const titleMatch = parsed.narrative.match(/^#\s+(.+)/m);
    return {
      title: titleMatch ? titleMatch[1] : docId,
      items: parsed.commands,
      meta:  { id: docId, doc_id: docId, folder: data.folder },
    };
  },

  async patch(docId, items) {
    // Keep "Step N" labels and the synthesised order consistent regardless of
    // how items got reordered/added/removed (mirrors plan_editor.js's
    // _renumberCommands()).
    items.forEach((cmd, i) => { cmd.stepNum = i + 1; });
    const md = _synthesizePlanMarkdownFrom(this._narrative, items, this._mode, this._outcome);
    const r = await fetch(`/api/plans/${encodeURIComponent(docId)}`, {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json', ...Auth.getHeaders() },
      body:    JSON.stringify({ content: md }),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || r.statusText);
    }
  },
};

// ── Adapter dispatchers — chosen per-call by _planCanvasDocMode ────────────────

const _planAdapter = {
  fetch(id)          { return (_planCanvasDocMode ? _planDocAdapter : _planDraftAdapter).fetch(id); },
  patch(id, items)   { return (_planCanvasDocMode ? _planDocAdapter : _planDraftAdapter).patch(id, items); },
  fieldUrl(action, mode) {
    return `/api/templates/${encodeURIComponent(action)}/fields?level=${mode || 'basic'}`;
  },
};

// ── Draft-shape item adapter ───────────────────────────────────────────────────

const _planDraftItemAdapter = {
  getType(cmd)        { return cmd.action || ''; },
  getDisplayName(cmd) {
    return cmd.pre_filled?.['Display Name'] || cmd.display_name || '';
  },
  getParams(cmd) {
    const result = {};
    for (const [k, v] of Object.entries(cmd.pre_filled || {})) {
      if (k !== 'Display Name' && v) result[k] = v;
    }
    return result;
  },
  getNarrative(cmd)        { return cmd.narrative || ''; },
  setNarrative(cmd, v)     { cmd.narrative = v; },
  getFieldValues(cmd)      {
    return { ...(cmd.pre_filled || {}), 'Display Name': cmd.display_name || '' };
  },
  setFieldValue(cmd, name, v) {
    if (!cmd.pre_filled) cmd.pre_filled = {};
    cmd.pre_filled[name] = v;
    if (name === 'Display Name') cmd.display_name = v;
  },
  makeNew(typeName) {
    return {
      action:       typeName,
      display_name: '',
      description:  '',
      rationale:    '',
      narrative:    '',
      pre_filled:   {},
      placeholders: {},
    };
  },
  makeNote() {
    return {
      action:       '_note',
      display_name: '',
      description:  '',
      rationale:    '',
      narrative:    '',
      pre_filled:   {},
      placeholders: {},
    };
  },
};

// ── Document-shape item adapter ────────────────────────────────────────────────
// Matches _parsePlanMarkdown()'s {stepNum, action, rationale, fields, postNotes}
// shape, where fields is a list of {name, value, required, type, validValues}.

const _planDocItemAdapter = {
  getType(cmd) { return cmd.action || ''; },
  getDisplayName(cmd) {
    const first = (cmd.fields || [])[0];
    return (first && first.value) || cmd.action || '';
  },
  getParams(cmd) {
    const result = {};
    (cmd.fields || []).slice(1).forEach(f => { if (f.value) result[f.name] = f.value; });
    return result;
  },
  getNarrative(cmd)    { return cmd.rationale || ''; },
  setNarrative(cmd, v) { cmd.rationale = v; },
  getFieldValues(cmd) {
    const out = {};
    (cmd.fields || []).forEach(f => { out[f.name] = f.value; });
    return out;
  },
  setFieldValue(cmd, name, v) {
    if (!cmd.fields) cmd.fields = [];
    const existing = cmd.fields.find(f => f.name === name);
    if (existing) existing.value = v;
    else cmd.fields.push({ name, value: v, required: false, type: 'Simple', validValues: [] });
  },
  makeNew(typeName) {
    return { stepNum: 0, action: typeName, rationale: '', fields: [], postNotes: '' };
  },
  makeNote() {
    return { stepNum: 0, action: '_note', rationale: '', fields: [{ name: 'Display Name', value: '', required: false, type: 'Simple', validValues: [] }], postNotes: '' };
  },
};

const _planItemAdapter = {
  getType(cmd)                { return _dispatchItemAdapter().getType(cmd); },
  getDisplayName(cmd)         { return _dispatchItemAdapter().getDisplayName(cmd); },
  getParams(cmd)              { return _dispatchItemAdapter().getParams(cmd); },
  getNarrative(cmd)           { return _dispatchItemAdapter().getNarrative(cmd); },
  setNarrative(cmd, v)        { return _dispatchItemAdapter().setNarrative(cmd, v); },
  getFieldValues(cmd)         { return _dispatchItemAdapter().getFieldValues(cmd); },
  setFieldValue(cmd, name, v) { return _dispatchItemAdapter().setFieldValue(cmd, name, v); },
  makeNew(typeName)           { return _dispatchItemAdapter().makeNew(typeName); },
  makeNote()                  { return _dispatchItemAdapter().makeNote(); },
};

function _dispatchItemAdapter() {
  return _planCanvasDocMode ? _planDocItemAdapter : _planDraftItemAdapter;
}

// ── PlanCanvas singleton ──────────────────────────────────────────────────────

// Set by onRender() below whenever the open document-mode plan is in the
// outbox — already-executed plans are immutable (DocumentManager.update()
// only writes to inbox), so Save/Execute must not be offered for them; only
// Recover (outbox -> inbox) makes editing possible again.
let _planCanvasIsOutbox = false;

function _updateSaveButton(dirty) {
  const btn = document.getElementById('pcanvas-save-btn');
  if (!btn) return;
  btn.classList.toggle('hidden', !_planCanvasDocMode || _planCanvasIsOutbox);
  btn.disabled = !dirty;
  btn.textContent = dirty ? 'Save*' : 'Save';
}

const PlanCanvas = (() => {
  let _canvas = null;
  let _draftId = null;

  function _ensureCanvas() {
    if (_canvas) return _canvas;
    _canvas = new ArtifactCanvas({
      panelId:      'plan-canvas-panel',
      handleId:     'resize-chat-canvas',
      cardsId:      'pcanvas-cards',
      titleId:      'pcanvas-title',
      modeButtonId: 'pcanvas-mode-btn',
      adapter:      _planAdapter,
      itemAdapter:  _planItemAdapter,
      autoSync:     true,
      onDirtyChange(dirty) { _updateSaveButton(dirty); },
      onSyncWarnings(warnings) {
        _showToast('Auto-corrected: ' + warnings.join('; '));
      },
      onRefreshError(id, e) {
        alert(`Could not open plan "${id}": ${e.message}`);
      },
      onRender(data) {
        // Show Validate + Execute buttons and hide Generate Plan when plan document has been generated
        const docId = data?.meta?.doc_id;
        const isOutbox = data?.meta?.folder === 'outbox';
        _planCanvasIsOutbox = isOutbox;
        const titleEl = document.getElementById('pcanvas-title');
        if (titleEl) titleEl.dataset.docId = docId || '';
        document.getElementById('pcanvas-generate-btn')?.classList.toggle('hidden', !!docId);
        document.getElementById('pcanvas-validate-btn')?.classList.toggle('hidden', !docId);
        // Execute posts to the inbox-only /execute endpoint — never valid for an
        // already-executed outbox plan (use Recover, then Execute, instead).
        document.getElementById('pcanvas-execute-btn')?.classList.toggle('hidden', !docId || isOutbox);
        document.getElementById('pcanvas-recover-btn')?.classList.toggle('hidden', !isOutbox);
        _updateSaveButton(false);
      },
    });
    return _canvas;
  }

  async function open(draftId) {
    _draftId = draftId;
    _planCanvasDocMode = false;

    // If this draft's plan has already been generated into a document, edit
    // the document directly — a draft-mode edit at this point would silently
    // apply to a copy the document never sees again. See BACKLOG.md.
    let docId = null;
    try {
      const r = await fetch(`/api/drafts/${encodeURIComponent(draftId)}`, { headers: Auth.getHeaders() });
      if (r.ok) docId = (await r.json()).doc_id || null;
    } catch { /* fall through to draft mode */ }

    if (docId) {
      await openDocument(docId, draftId);
      return;
    }

    if (typeof setContext === 'function') {
      setContext({ task: 'plan_elicitor', draft_id: draftId, phase: 'confirm_action' });
    }
    const canvas = _ensureCanvas();
    canvas._opts.autoSync = true;
    await canvas.open(draftId);
    if (typeof ReportSpecCanvas !== 'undefined' && ReportSpecCanvas.close) ReportSpecCanvas.close();
  }

  async function openDocument(docId, draftId) {
    _draftId = draftId || null;
    _planCanvasDocMode = true;
    if (typeof setContext === 'function') {
      setContext({ task: 'plan_elicitor', draft_id: draftId || null, doc_id: docId, phase: 'edit_document' });
    }
    const canvas = _ensureCanvas();
    canvas._opts.autoSync = false;
    await canvas.open(docId);
    if (typeof ReportSpecCanvas !== 'undefined' && ReportSpecCanvas.close) ReportSpecCanvas.close();
  }

  function close() {
    const closedId = _draftId;
    _draftId = null;
    _planCanvasDocMode = false;
    if (typeof setContext === 'function' && typeof _ctx !== 'undefined' && _ctx?.draft_id === closedId) {
      setContext(null);
    }
    if (_canvas) _canvas.close();
  }

  async function refresh(id) {
    await _ensureCanvas().refresh(id || _draftId);
  }

  async function addStep() {
    await _ensureCanvas().addItem();
  }

  async function addNote() {
    const canvas = _ensureCanvas();
    const note = _dispatchItemAdapter().makeNote();
    canvas._items.push(note);
    await canvas._sync();
    canvas._render();
    // Scroll to the new note card
    const cardsEl = document.getElementById('pcanvas-cards');
    if (cardsEl) setTimeout(() => cardsEl.scrollTop = cardsEl.scrollHeight, 50);
  }

  function toggleMode() {
    _ensureCanvas().toggleMode();
  }

  async function save() {
    const canvas = _ensureCanvas();
    try {
      await canvas.flush();
    } catch (e) {
      // A save failure here usually means the plan moved out from under this
      // canvas — e.g. executed from another browser tab, or via chat, since
      // this canvas was opened. Don't retry the write blind (risks clobbering
      // whatever changed it) — reopen via the draft, which resolves the
      // current doc_id, so the user sees accurate state instead of a dead end.
      alert(
        `Could not save plan: ${e.message}\n\n` +
        `This can happen if the plan changed elsewhere (e.g. executed in another ` +
        `tab) since this canvas was opened. Reopening with the current version — ` +
        `your last edit was not saved and may need to be redone.`
      );
      if (_draftId) await open(_draftId);
    }
  }

  // Outbox plans are immutable (DocumentManager.update() only writes inbox) —
  // move it back to inbox first, then reopen the canvas on the new inbox
  // doc_id so Save/Execute become available again. Mirrors plan_editor.js's
  // pedRecoverForEditing().
  async function recover() {
    const docId = document.getElementById('pcanvas-title')?.dataset?.docId;
    if (!docId) return;
    if (!confirm(`Recover "${docId}" for editing?\nThis moves it back to inbox so you can edit, validate, and re-execute.`)) return;
    try {
      const r = await fetch(`/api/plans/${encodeURIComponent(docId)}/recover`, {
        method: 'POST', headers: Auth.getHeaders(),
      });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
      const res = await r.json();
      await openDocument(res.doc_id, _draftId);
      if (typeof loadPlans === 'function') loadPlans();
      if (typeof _showToast === 'function') _showToast('Plan recovered — you can now edit, validate, and execute.');
    } catch (e) {
      alert(`Recovery failed: ${e.message}`);
    }
  }

  return { open, openDocument, close, refresh, addStep, addNote, toggleMode, save, recover };
})();
