# Phase 4: Frontend JavaScript Implementation

Complete JavaScript code to add to `explorer/web/static/index.html` in the `<script>` section.

## 1. State Variables (Add after line 176)

```javascript
// Database state
let selectedDatabase = null;
let currentEntityType = 'projects';  // 'projects' | 'databases'
let currentDatabaseChart = 'schema_dist';
```

## 2. Entity Tab Functions (Add after loadProjects, ~line 227)

```javascript
// ── entity tabs ────────────────────────────────────────────────────────────────
function showEntityTab(tab) {
  currentEntityType = tab;
  
  // Hide all tabs
  document.getElementById('projects-tab').classList.add('hidden');
  document.getElementById('databases-tab').classList.add('hidden');
  
  // Show selected tab
  document.getElementById(`${tab}-tab`).classList.remove('hidden');
  
  // Update tab buttons
  document.querySelectorAll('.entity-tab').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.add('active');
  
  // Clear selections
  selectedProject = null;
  selectedDatabase = null;
  document.querySelectorAll('.project-btn, .database-btn').forEach(b => {
    b.classList.remove('selected');
  });
  
  // Hide charts and main nav
  document.getElementById('charts-section').classList.add('hidden');
  document.getElementById('main-nav').classList.add('hidden');
  document.getElementById('scope-badge').classList.add('hidden');
  
  // Load data if needed
  if (tab === 'databases') {
    loadDatabases();
  }
}

async function loadDatabases() {
  try {
    const res = await fetch('/api/databases/');
    const databases = await res.json();
    const list = document.getElementById('database-list');
    list.innerHTML = databases.map(renderDatabaseItem).join('');
  } catch (e) {
    console.error('Failed to load databases:', e);
  }
}

function renderDatabaseItem(db) {
  const colors = {
    active: 'text-green-400',
    indexing: 'text-yellow-400',
    error: 'text-red-400',
    paused: 'text-slate-500'
  };
  const color = colors[db.status] || 'text-slate-400';
  
  return `
    <button class="database-btn w-full text-left px-3 py-1.5 rounded text-sm hover:bg-slate-700 transition-colors"
      data-slug="${db.slug}" onclick="selectDatabase('${_esc(db.slug)}')">
      <div class="flex items-center justify-between gap-1 min-w-0">
        <div class="font-medium text-slate-200 truncate">${_esc(db.display_name)}</div>
        <div class="proj-actions">
          <button class="proj-action-btn" data-tip="Run survey"
            onclick="event.stopPropagation(); showSurveyDatabaseModal('${_esc(db.slug)}')">📊</button>
          <button class="proj-action-btn" data-tip="Remove"
            onclick="event.stopPropagation(); removeDatabase('${_esc(db.slug)}')">🗑️</button>
        </div>
      </div>
      <div class="text-xs ${color}">
        ${db.db_type} · ${db.status}
        ${db.schema_count ? ` · ${db.schema_count} schemas` : ''}
      </div>
    </button>
  `;
}

function selectDatabase(slug) {
  selectedDatabase = slug;
  selectedProject = null;
  
  document.querySelectorAll('.database-btn, .project-btn').forEach(b => {
    b.classList.remove('selected');
  });
  
  if (slug) {
    document.querySelector(`[data-slug="${slug}"].database-btn`)?.classList.add('selected');
    document.getElementById('scope-badge').textContent = `🗄️ ${slug}`;
    document.getElementById('scope-badge').classList.remove('hidden');
    document.getElementById('charts-section').classList.remove('hidden');
    document.getElementById('main-nav').classList.remove('hidden');
    
    // Show database charts
    document.getElementById('project-charts').classList.add('hidden');
    document.getElementById('database-charts').classList.remove('hidden');
    
    showDatabaseChart(currentDatabaseChart);
    _reportLoaded = false;
    showMainView('chat');
  } else {
    document.getElementById('scope-badge').classList.add('hidden');
    document.getElementById('charts-section').classList.add('hidden');
    document.getElementById('main-nav').classList.add('hidden');
    document.querySelectorAll('.database-btn[data-slug=""]').forEach(b => b.classList.add('selected'));
  }
}
```

## 3. Database Modal Functions

```javascript
// ── database modals ────────────────────────────────────────────────────────────
function showRegisterDatabaseModal() {
  document.getElementById('register-db-modal').classList.remove('hidden');
}

function closeRegisterDatabaseModal() {
  document.getElementById('register-db-modal').classList.add('hidden');
  document.getElementById('register-db-form').reset();
}

async function registerDatabase(event) {
  event.preventDefault();
  const form = event.target;
  const data = {
    slug: form.slug.value,
    display_name: form.display_name.value,
    db_type: form.db_type.value,
    host: form.host.value,
    port: parseInt(form.port.value),
    database_name: form.database_name.value,
    connection_ref: form.connection_ref.value,
    description: form.description.value
  };
  
  try {
    const res = await fetch('/api/databases/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    
    if (res.ok) {
      closeRegisterDatabaseModal();
      loadDatabases();
      appendMessage('assistant', `✅ Database **${data.slug}** registered successfully!`);
    } else {
      const err = await res.json();
      alert(`Failed to register database: ${err.detail}`);
    }
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

function showSurveyDatabaseModal(slug) {
  document.getElementById('survey-db-slug').value = slug;
  document.getElementById('survey-db-modal').classList.remove('hidden');
}

function closeSurveyDatabaseModal() {
  document.getElementById('survey-db-modal').classList.add('hidden');
  document.getElementById('survey-db-form').reset();
}

async function surveyDatabase(event) {
  event.preventDefault();
  const form = event.target;
  const slug = form.slug.value;
  const data = {
    username: form.username.value,
    password: form.password.value,
    use_egeria: form.use_egeria.checked
  };
  
  closeSurveyDatabaseModal();
  appendMessage('assistant', `🔄 Starting survey of **${slug}**...`);
  
  try {
    const res = await fetch(`/api/databases/${slug}/survey`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    
    const result = await res.json();
    
    if (result.status === 'ok') {
      appendMessage('assistant', 
        `✅ Survey complete! Found ${result.schema_count} schemas, ${result.table_count} tables, ${result.column_count} columns. Source: **${result.source}**`);
      loadDatabases();
      if (selectedDatabase === slug) {
        showDatabaseChart(currentDatabaseChart);
      }
    } else {
      appendMessage('assistant', `❌ Survey failed: ${result.error}`);
    }
  } catch (e) {
    appendMessage('assistant', `❌ Error: ${e.message}`);
  }
}

async function removeDatabase(slug) {
  if (!confirm(`Remove database "${slug}"? This cannot be undone.`)) return;
  
  try {
    const res = await fetch(`/api/databases/${slug}`, {method: 'DELETE'});
    if (res.ok) {
      loadDatabases();
      if (selectedDatabase === slug) {
        selectDatabase(null);
      }
      appendMessage('assistant', `✅ Database **${slug}** removed.`);
    } else {
      const err = await res.json();
      alert(`Failed to remove: ${err.detail}`);
    }
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}
```

## 4. Database Chart Functions

```javascript
// ── database charts ────────────────────────────────────────────────────────────
async function showDatabaseChart(chartType) {
  if (!selectedDatabase) return;
  
  currentDatabaseChart = chartType;
  const container = document.getElementById('chart-container');
  container.innerHTML = '<div class="text-center text-slate-400 py-8">Loading...</div>';
  
  try {
    const res = await fetch(`/api/stats/databases/${selectedDatabase}/${chartType}`);
    if (!res.ok) {
      container.innerHTML = '<div class="text-center text-slate-400 py-8">No data available. Run a survey first.</div>';
      return;
    }
    
    const data = await res.json();
    
    let fig;
    if (chartType === 'schema_dist') {
      fig = {
        data: [{
          type: 'bar',
          x: data.schemas,
          y: data.table_counts,
          marker: {color: '#06b6d4'}
        }],
        layout: {
          title: 'Schema Distribution',
          paper_bgcolor: '#0f172a',
          plot_bgcolor: '#1e293b',
          font: {color: '#e2e8f0'},
          xaxis: {title: 'Schema'},
          yaxis: {title: 'Table Count'}
        }
      };
    } else if (chartType === 'table_sizes') {
      fig = {
        data: [{
          type: 'bar',
          x: data.tables,
          y: data.row_counts,
          marker: {color: '#10b981'}
        }],
        layout: {
          title: 'Top Tables by Row Count',
          paper_bgcolor: '#0f172a',
          plot_bgcolor: '#1e293b',
          font: {color: '#e2e8f0'},
          xaxis: {title: 'Table', tickangle: -45},
          yaxis: {title: 'Row Count'}
        }
      };
    } else if (chartType === 'column_types') {
      fig = {
        data: [{
          type: 'pie',
          labels: data.types,
          values: data.counts,
          marker: {colors: ['#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}
        }],
        layout: {
          title: 'Column Type Distribution',
          paper_bgcolor: '#0f172a',
          font: {color: '#e2e8f0'}
        }
      };
    } else if (chartType === 'survey_history') {
      fig = {
        data: [
          {
            type: 'scatter',
            mode: 'lines+markers',
            x: data.dates,
            y: data.schema_counts,
            name: 'Schemas',
            line: {color: '#06b6d4'}
          },
          {
            type: 'scatter',
            mode: 'lines+markers',
            x: data.dates,
            y: data.table_counts,
            name: 'Tables',
            line: {color: '#10b981'}
          }
        ],
        layout: {
          title: 'Survey History',
          paper_bgcolor: '#0f172a',
          plot_bgcolor: '#1e293b',
          font: {color: '#e2e8f0'},
          xaxis: {title: 'Date'},
          yaxis: {title: 'Count'}
        }
      };
    }
    
    Plotly.newPlot(container, fig.data, fig.layout, {responsive: true});
  } catch (e) {
    container.innerHTML = `<div class="text-center text-red-400 py-8">Error: ${e.message}</div>`;
  }
}
```

## 5. Update sendQuery Function

Find the existing `sendQuery()` function (around line 150-180) and replace it with:

```javascript
async function sendQuery() {
  const query = document.getElementById('query-input').value.trim();
  if (!query) return;
  
  appendMessage('you', query);
  document.getElementById('query-input').value = '';
  document.getElementById('thinking').classList.remove('hidden');
  
  try {
    const context = {
      query,
      session_id: sessionId
    };
    
    // Add entity context
    if (selectedProject) {
      context.project_slug = selectedProject;
    } else if (selectedDatabase) {
      context.database_slug = selectedDatabase;
    }
    
    const res = await fetch('/api/query/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(context)
    });
    
    const data = await res.json();
    document.getElementById('thinking').classList.add('hidden');
    appendMessage('assistant', data.response);
    
    if (data.chart) {
      const chartDiv = document.createElement('div');
      chartDiv.className = 'chart-box mt-2';
      lastAssistantEl.appendChild(chartDiv);
      Plotly.newPlot(chartDiv, data.chart.data, data.chart.layout, {responsive: true});
    }
  } catch (e) {
    document.getElementById('thinking').classList.add('hidden');
    appendMessage('assistant', `Error: ${e.message}`);
  }
}
```

## 6. Update selectProject Function

Find the existing `selectProject()` function and add this at the beginning to handle chart visibility:

```javascript
function selectProject(slug) {
  compareSet.clear();
  selectedProject = slug;
  selectedDatabase = null;  // ADD THIS LINE
  
  document.querySelectorAll('.project-btn, .database-btn').forEach(b => {  // UPDATE THIS LINE
    b.classList.remove('selected', 'compare-selected');
  });
  
  if (slug) {
    document.querySelector(`[data-slug="${slug}"]`)?.classList.add('selected');
    document.getElementById('scope-badge').textContent = slug;
    document.getElementById('scope-badge').classList.remove('hidden');
    document.getElementById('charts-section').classList.remove('hidden');
    document.getElementById('egeria-panel').classList.add('hidden');
    document.getElementById('chart-container').classList.remove('hidden');
    
    // Show project charts, hide database charts
    document.getElementById('project-charts').classList.remove('hidden');
    document.getElementById('database-charts').classList.add('hidden');
    
    showChart(currentChart);
    document.getElementById('main-nav').classList.remove('hidden');
    _reportLoaded = false;
    showMainView('chat');
    if (pendingClarification) {
      const q = pendingClarification;
      pendingClarification = null;
      appendMessage('assistant', `Got it — scoping to **${slug}** and re-running your question…`);
      runQuery(q.query, slug);
    }
  } else {
    document.getElementById('scope-badge').classList.add('hidden');
    document.getElementById('charts-section').classList.add('hidden');
    document.getElementById('main-nav').classList.add('hidden');
    document.querySelectorAll('.project-btn[data-slug=""]').forEach(b => b.classList.add('selected'));
  }
}
```

## Summary

**Total JavaScript**: ~400 lines
**Functions Added**: 11 new functions
**Functions Modified**: 2 existing functions

**Key Features**:
- Entity tab switching
- Database CRUD operations
- Survey triggering with credentials
- 4 chart types with Plotly
- Query routing with database context
- Complete error handling

**Integration Points**:
- Uses existing `appendMessage()` for feedback
- Uses existing `_esc()` for HTML escaping
- Uses existing Plotly for charts
- Follows existing UI patterns