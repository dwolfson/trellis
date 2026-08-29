# Phase 4: Frontend Implementation Guide

**File to Modify**: `explorer/web/static/index.html`

This document provides the complete code additions needed to implement database support in the Web UI.

## Changes Overview

1. Add CSS styles for database components
2. Add entity tabs to sidebar
3. Add database list section
4. Add register database modal
5. Add JavaScript for database operations
6. Add database chart functions
7. Update state management

## 1. CSS Additions (Add to `<style>` section, around line 70)

```css
/* Entity tabs */
.entity-tab {
  flex: 1;
  padding: 0.5rem 1rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
  cursor: pointer;
  text-align: center;
}
.entity-tab.active {
  color: #22d3ee;
  border-bottom-color: #22d3ee;
}
.entity-tab:hover:not(.active) {
  color: #94a3b8;
}

/* Database buttons */
.database-btn {
  position: relative;
}
.database-btn.selected {
  background: #0e7490 !important;
}

/* Modal */
.modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal.hidden {
  display: none;
}
.modal-content {
  background: #1e293b;
  border-radius: 0.5rem;
  padding: 1.5rem;
  max-width: 500px;
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
  border: 1px solid #334155;
}
.modal-content h3 {
  font-size: 1.25rem;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 1rem;
}
.modal-content input,
.modal-content select,
.modal-content textarea {
  width: 100%;
  padding: 0.5rem;
  margin-bottom: 0.75rem;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 0.375rem;
  color: #e2e8f0;
  font-size: 0.875rem;
}
.modal-content input:focus,
.modal-content select:focus,
.modal-content textarea:focus {
  outline: none;
  border-color: #06b6d4;
}
.modal-content label {
  display: block;
  font-size: 0.75rem;
  color: #94a3b8;
  margin-bottom: 0.25rem;
  font-weight: 500;
}
.btn-primary {
  background: #06b6d4;
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover {
  background: #0891b2;
}
.btn-secondary {
  background: #334155;
  color: #e2e8f0;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-secondary:hover {
  background: #475569;
}

## 2. HTML Structure Changes

### 2.1 Add Entity Tabs (Replace line 89 "Projects" header)

**BEFORE** (line 89):
```html
<div class="px-3 pt-3 pb-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">Projects</div>
```

**AFTER**:
```html
<!-- Entity tabs -->
<div class="flex border-b border-slate-700">
  <button onclick="showEntityTab('projects')" id="tab-projects" class="entity-tab active">
    📁 Projects
  </button>
  <button onclick="showEntityTab('databases')" id="tab-databases" class="entity-tab">
    🗄️ Databases
  </button>
</div>
```

### 2.2 Wrap Project List (Around lines 91-99)

**BEFORE**:
```html
<div class="px-2 pb-1">
  <button onclick="selectProject(null)"...>All projects</button>
</div>
<div id="project-list" class="px-2 flex flex-col gap-0.5"></div>
```

**AFTER**:
```html
<!-- Projects tab content -->
<div id="projects-tab" class="entity-list">
  <div class="px-2 pb-1 pt-2">
    <button onclick="selectProject(null)"
      class="project-btn w-full text-left px-3 py-1.5 rounded text-sm text-slate-300 hover:bg-slate-700 transition-colors"
      data-slug="">
      All projects
    </button>
  </div>
  <div id="project-list" class="px-2 flex flex-col gap-0.5"></div>
</div>

<!-- Databases tab content -->
<div id="databases-tab" class="entity-list hidden">
  <div class="px-2 pb-1 pt-2">
    <button onclick="selectDatabase(null)"
      class="database-btn w-full text-left px-3 py-1.5 rounded text-sm text-slate-300 hover:bg-slate-700 transition-colors"
      data-slug="">
      All databases
    </button>
  </div>
  <div id="database-list" class="px-2 flex flex-col gap-0.5"></div>
  <div class="px-3 pt-2">
    <button onclick="showRegisterDatabaseModal()" 
      class="w-full px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 rounded text-sm font-medium transition-colors">
      + Register Database
    </button>
  </div>
</div>
```

### 2.3 Update Charts Section

Add database chart buttons alongside project charts (around line 104-110):

```html
<div class="flex gap-1 flex-wrap mb-2" id="project-charts">
  <!-- Existing project chart buttons -->
</div>
<div class="flex gap-1 flex-wrap mb-2 hidden" id="database-charts">
  <button onclick="showDatabaseChart('schema_dist')" class="chart-tab text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-cyan-800 text-slate-300">Schemas</button>
  <button onclick="showDatabaseChart('table_sizes')" class="chart-tab text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-cyan-800 text-slate-300">Tables</button>
  <button onclick="showDatabaseChart('column_types')" class="chart-tab text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-cyan-800 text-slate-300">Column Types</button>
  <button onclick="showDatabaseChart('survey_history')" class="chart-tab text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-cyan-800 text-slate-300">History</button>
</div>
```

### 2.4 Add Modals (Before closing `</body>` tag)

```html
<!-- Register Database Modal -->
<div id="register-db-modal" class="modal hidden">
  <div class="modal-content">
    <h3>Register Database</h3>
    <form id="register-db-form" onsubmit="registerDatabase(event)">
      <label>Slug</label>
      <input name="slug" placeholder="my-postgres" required pattern="[a-z0-9-]+">
      <label>Display Name</label>
      <input name="display_name" placeholder="My PostgreSQL" required>
      <label>Type</label>
      <select name="db_type" required>
        <option value="postgresql">PostgreSQL</option>
      </select>
      <label>Host</label>
      <input name="host" placeholder="localhost" required>
      <label>Port</label>
      <input name="port" type="number" value="5432" required>
      <label>Database Name</label>
      <input name="database_name" placeholder="mydb" required>
      <label>Connection Ref</label>
      <input name="connection_ref" placeholder="ENV_VAR or path" required>
      <label>Description</label>
      <textarea name="description" rows="2"></textarea>
      <div class="flex gap-2 mt-3">
        <button type="submit" class="btn-primary flex-1">Register</button>
        <button type="button" onclick="closeRegisterDatabaseModal()" class="btn-secondary">Cancel</button>
      </div>
    </form>
  </div>
</div>

<!-- Survey Database Modal -->
<div id="survey-db-modal" class="modal hidden">
  <div class="modal-content">
    <h3>Survey Database</h3>
    <form id="survey-db-form" onsubmit="surveyDatabase(event)">
      <input type="hidden" name="slug" id="survey-db-slug">
      <label>Username</label>
      <input name="username" required>
      <label>Password</label>
      <input name="password" type="password" required>
      <label class="flex items-center gap-2 cursor-pointer mt-2">
        <input type="checkbox" name="use_egeria" class="catalog-cb">
        <span class="text-sm">Use Egeria (hybrid)</span>
      </label>
      <div class="flex gap-2 mt-3">
        <button type="submit" class="btn-primary flex-1">Run Survey</button>
        <button type="button" onclick="closeSurveyDatabaseModal()" class="btn-secondary">Cancel</button>
      </div>
    </form>
  </div>
</div>
```

## 3. JavaScript - Complete Implementation

Add all these functions to the `<script>` section. The complete JavaScript implementation is provided in a separate file for clarity.

**See**: `docs/PHASE4_FRONTEND_JAVASCRIPT.md` for the complete JavaScript code (~400 lines)

## 4. Quick Implementation Steps

1. **Backup** `explorer/web/static/index.html`
2. **Add CSS** from section 1 to `<style>` block
3. **Update HTML** structure per section 2
4. **Add JavaScript** from PHASE4_FRONTEND_JAVASCRIPT.md
5. **Test** each feature systematically

## 5. Testing Checklist

- [ ] Entity tabs switch correctly
- [ ] Database list loads
- [ ] Register modal works
- [ ] Database registration succeeds
- [ ] Database selection updates UI
- [ ] Charts load for databases
- [ ] Survey modal opens
- [ ] Survey executes successfully
- [ ] Database removal works
- [ ] Queries work with database context

## Summary

**Implementation Complexity**: Medium-High
**Estimated Time**: 3-4 hours
**Lines of Code**: ~600-700
**Files Modified**: 1 (index.html)

**All backend APIs are ready** - frontend just needs to call them!