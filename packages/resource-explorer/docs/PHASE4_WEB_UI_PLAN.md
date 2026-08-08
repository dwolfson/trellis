# Phase 4: Web UI Integration for Databases

## Overview

Extend the Project Explorer Web UI to support database entities alongside GitHub repositories, providing a unified interface for exploring both code projects and database schemas.

## Current Web UI Architecture

### Backend (FastAPI)
- **`explorer/web/app.py`**: Main FastAPI application with route registration
- **`explorer/web/routes/projects.py`**: Project management endpoints (list, get, refresh, remove)
- **`explorer/web/routes/stats.py`**: Statistics and charts
- **`explorer/web/routes/egeria.py`**: Egeria integration (survey triggering, report retrieval)
- **`explorer/web/routes/query.py`**: RAG query processing
- **`explorer/web/routes/aliases.py`**: Project alias management
- **`explorer/web/routes/webhook.py`**: GitHub webhook handling

### Frontend (Vanilla JS + Tailwind)
- **`explorer/web/static/index.html`**: Single-page application
- **Sidebar**: Project list with selection, comparison mode, action buttons (refresh, survey, GitHub link)
- **Main View**: Tabbed interface (Chat, Survey Report)
- **Charts Section**: Visualizations (stars, commits, languages, health, file types, Egeria)
- **Chat Interface**: Multi-agent RAG with conversation history

### Key Features
1. **Project Selection**: Click to select, Shift+click for comparison mode
2. **Action Buttons**: Inline refresh (🔄) and survey (📊) buttons per project
3. **Survey Reports**: Dedicated tab showing Egeria survey results with annotations
4. **Charts**: Interactive Plotly visualizations for project metrics
5. **Scoped Queries**: RAG queries automatically scoped to selected project(s)

## Phase 4 Implementation Plan

### 1. Backend API Extensions

#### 1.1 Create `explorer/web/routes/databases.py`
Mirror the structure of `projects.py` with database-specific endpoints:

```python
# Models
class DatabaseSummary(BaseModel):
    slug: str
    display_name: str
    db_type: str
    host: str
    port: int
    database_name: str
    description: str
    status: str
    last_surveyed_at: str | None
    schema_count: int | None
    table_count: int | None

# Endpoints
GET    /api/databases/              # List all databases
GET    /api/databases/{slug}        # Get database details
POST   /api/databases/{slug}/survey # Trigger survey (hybrid mode)
DELETE /api/databases/{slug}        # Remove database
POST   /api/databases/register      # Register new database
```

#### 1.2 Extend `explorer/web/routes/stats.py`
Add database-specific chart endpoints:

```python
GET /api/stats/databases/{slug}/schema_distribution  # Schema sizes
GET /api/stats/databases/{slug}/table_sizes          # Table row counts
GET /api/stats/databases/{slug}/column_types         # Data type distribution
GET /api/stats/databases/{slug}/survey_history       # Survey timeline
```

#### 1.3 Update `explorer/web/routes/query.py`
Extend query routing to support database context:

```python
# Add database_slug parameter alongside project_slug
# Route queries to appropriate agents based on entity type
# Support mixed queries (project + database context)
```

#### 1.4 Create `explorer/web/routes/database_egeria.py`
Database-specific Egeria integration:

```python
POST /api/database-egeria/{slug}/survey  # Trigger Egeria PostgreSQL survey
GET  /api/database-egeria/{slug}/reports # Get survey reports
GET  /api/database-egeria/{slug}/annotations/{report_guid}  # Get annotations
```

### 2. Frontend UI Extensions

#### 2.1 Unified Sidebar with Entity Tabs

**Current**: Single "Projects" section
**New**: Tabbed sidebar with "Projects" and "Databases" tabs

```html
<!-- Sidebar header with tabs -->
<div class="flex border-b border-slate-700">
  <button onclick="showEntityTab('projects')" 
    class="entity-tab active">Projects</button>
  <button onclick="showEntityTab('databases')" 
    class="entity-tab">Databases</button>
</div>

<!-- Projects list (existing) -->
<div id="projects-tab" class="entity-list">
  <!-- Current project list -->
</div>

<!-- Databases list (new) -->
<div id="databases-tab" class="entity-list hidden">
  <div class="px-2 pb-1">
    <button onclick="selectDatabase(null)" class="entity-btn">
      All databases
    </button>
  </div>
  <div id="database-list" class="px-2 flex flex-col gap-0.5">
    <!-- Database items populated via JS -->
  </div>
  <div class="px-3 pt-2">
    <button onclick="showRegisterDatabaseModal()" 
      class="w-full px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 rounded text-sm">
      + Register Database
    </button>
  </div>
</div>
```

#### 2.2 Database List Items

Similar structure to project buttons with database-specific actions:

```javascript
function renderDatabaseItem(db) {
  const colors = {
    active: 'text-green-400',
    surveying: 'text-yellow-400', 
    error: 'text-red-400',
    pending: 'text-slate-500'
  };
  const color = colors[db.status] || 'text-slate-400';
  
  return `
    <button class="database-btn" data-slug="${db.slug}">
      <div class="flex items-center justify-between gap-1">
        <div class="font-medium text-slate-200 truncate">
          ${db.display_name}
        </div>
        <div class="entity-actions">
          <button data-tip="Run survey" 
            onclick="runDatabaseSurvey('${db.slug}', this)">📊</button>
          <button data-tip="Connection info"
            onclick="showDatabaseInfo('${db.slug}')">ℹ️</button>
          <button data-tip="Remove"
            onclick="removeDatabase('${db.slug}')">🗑️</button>
        </div>
      </div>
      <div class="text-xs ${color}">
        ${db.db_type} · ${db.status}
        ${db.schema_count ? ` · ${db.schema_count} schemas` : ''}
      </div>
    </button>
  `;
}
```

#### 2.3 Database Charts Section

When a database is selected, show database-specific visualizations:

```javascript
// Chart types for databases
const databaseCharts = [
  { id: 'schema_dist', label: 'Schema Sizes' },
  { id: 'table_sizes', label: 'Table Sizes' },
  { id: 'column_types', label: 'Column Types' },
  { id: 'survey_history', label: 'Survey History' },
  { id: 'egeria', label: 'Egeria' }
];

function showDatabaseChart(chartType) {
  // Fetch data from /api/stats/databases/{slug}/{chartType}
  // Render with Plotly
}
```

#### 2.4 Database Survey Report View

Extend the "Survey Report" tab to handle database surveys:

```javascript
async function loadDatabaseSurveyReport(slug) {
  const surveys = await fetch(`/api/databases/${slug}/surveys`).then(r => r.json());
  const latest = surveys[0];
  
  // Render database-specific metrics
  renderDatabaseMetrics(latest);
  renderSchemaBreakdown(latest);
  renderTableDetails(latest);
  renderAnnotations(latest);
}

function renderDatabaseMetrics(survey) {
  return `
    <div class="grid grid-cols-4 gap-3">
      <div class="rpt-card">
        <div class="rpt-card-val">${survey.schema_count}</div>
        <div class="rpt-card-lbl">Schemas</div>
      </div>
      <div class="rpt-card">
        <div class="rpt-card-val">${survey.table_count}</div>
        <div class="rpt-card-lbl">Tables</div>
      </div>
      <div class="rpt-card">
        <div class="rpt-card-val">${survey.column_count}</div>
        <div class="rpt-card-lbl">Columns</div>
      </div>
      <div class="rpt-card">
        <div class="rpt-card-val">${survey.total_rows}</div>
        <div class="rpt-card-lbl">Total Rows</div>
      </div>
    </div>
  `;
}
```

#### 2.5 Register Database Modal

Modal dialog for registering new databases:

```html
<div id="register-db-modal" class="modal hidden">
  <div class="modal-content">
    <h3>Register Database</h3>
    <form id="register-db-form">
      <input name="slug" placeholder="Slug (e.g., my-postgres)" required>
      <input name="display_name" placeholder="Display Name" required>
      <select name="db_type" required>
        <option value="postgresql">PostgreSQL</option>
        <option value="mysql">MySQL (future)</option>
      </select>
      <input name="host" placeholder="Host" required>
      <input name="port" type="number" placeholder="Port" value="5432">
      <input name="database_name" placeholder="Database Name" required>
      <input name="username" placeholder="Username" required>
      <input name="password" type="password" placeholder="Password" required>
      <textarea name="description" placeholder="Description"></textarea>
      
      <div class="flex gap-2">
        <button type="submit" class="btn-primary">Register</button>
        <button type="button" onclick="closeRegisterModal()">Cancel</button>
      </div>
    </form>
  </div>
</div>
```

#### 2.6 Unified Scope Badge

Update the scope badge to show selected entity type:

```javascript
function updateScopeBadge() {
  const badge = document.getElementById('scope-badge');
  if (selectedProject) {
    badge.textContent = `📁 ${selectedProject}`;
  } else if (selectedDatabase) {
    badge.textContent = `🗄️ ${selectedDatabase}`;
  } else {
    badge.classList.add('hidden');
    return;
  }
  badge.classList.remove('hidden');
}
```

### 3. Query Routing Enhancements

#### 3.1 Context Detection

Automatically route queries based on selected entity:

```javascript
async function sendQuery() {
  const query = document.getElementById('query-input').value.trim();
  if (!query) return;
  
  let context = {};
  if (selectedProject) {
    context.project_slug = selectedProject;
    context.entity_type = 'project';
  } else if (selectedDatabase) {
    context.database_slug = selectedDatabase;
    context.entity_type = 'database';
  }
  
  // Send to backend with context
  const response = await fetch('/api/query/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, ...context, session_id: sessionId })
  });
  
  // Handle response...
}
```

#### 3.2 Mixed Context Queries

Support queries that span both projects and databases:

```javascript
// Example: "Compare the API structure in project X with the schema in database Y"
// Backend routes to CompareAgent with both contexts
```

### 4. State Management

#### 4.1 Unified Selection State

```javascript
let selectedEntity = {
  type: null,      // 'project' | 'database' | null
  slug: null,      // entity slug
  compareSet: []   // for multi-entity comparison
};

function selectEntity(type, slug) {
  selectedEntity.type = type;
  selectedEntity.slug = slug;
  selectedEntity.compareSet = [];
  
  // Update UI
  updateScopeBadge();
  updateChartsSection();
  updateMainNav();
  
  // Clear pending clarifications
  if (pendingClarification) {
    resolveClarification();
  }
}
```

### 5. Styling Consistency

#### 5.1 Entity Type Icons

Use consistent icons throughout:
- Projects: 📁
- Databases: 🗄️
- Survey: 📊
- Refresh: 🔄
- Info: ℹ️
- Remove: 🗑️

#### 5.2 Color Coding

Maintain existing color scheme:
- Active: green-400
- Pending/Surveying: yellow-400
- Error: red-400
- Paused: slate-500

### 6. Implementation Steps

#### Step 1: Backend Foundation (2-3 hours)
1. Create `databases.py` routes module
2. Add database endpoints to `app.py`
3. Extend stats routes for database charts
4. Update query routing for database context

#### Step 2: Frontend Structure (2-3 hours)
1. Add entity tabs to sidebar
2. Implement database list rendering
3. Create register database modal
4. Update state management

#### Step 3: Database Charts (1-2 hours)
1. Implement chart data endpoints
2. Add Plotly visualizations for databases
3. Wire up chart tab switching

#### Step 4: Survey Integration (2-3 hours)
1. Add database survey report view
2. Implement survey triggering from UI
3. Add Egeria integration for databases
4. Show survey status and results

#### Step 5: Query Routing (1-2 hours)
1. Update query endpoint for database context
2. Test agent routing with database queries
3. Implement mixed context queries

#### Step 6: Polish & Testing (1-2 hours)
1. Add loading states and error handling
2. Test all CRUD operations
3. Verify chart rendering
4. Test survey workflows

**Total Estimated Time**: 9-15 hours

## Success Criteria

- ✅ Users can view all registered databases in the sidebar
- ✅ Users can register new databases via modal form
- ✅ Users can select a database and see database-specific charts
- ✅ Users can trigger surveys (hybrid mode) from the UI
- ✅ Users can view survey reports with schema/table details
- ✅ Users can ask questions scoped to a database
- ✅ Users can compare projects and databases
- ✅ All database operations (register, survey, remove) work via UI
- ✅ UI maintains consistency with existing project features

## Future Enhancements (Phase 5+)

1. **Database Comparison View**: Side-by-side schema comparison
2. **Schema Visualization**: Interactive ER diagrams
3. **Query Builder**: Visual query construction for databases
4. **Data Profiling Dashboard**: Real-time data quality metrics
5. **Scheduled Surveys**: Automated periodic surveying
6. **Alert Configuration**: Notifications for schema changes
7. **Multi-Database Queries**: Federated queries across databases
8. **Export Functionality**: Export survey reports as PDF/JSON

## Notes

- Maintain backward compatibility with existing project features
- Use same authentication/authorization patterns as projects
- Follow existing code style and conventions
- Ensure responsive design works on mobile
- Add comprehensive error handling and user feedback
- Document all new API endpoints in OpenAPI schema