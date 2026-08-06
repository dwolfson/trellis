# Design Document: Dynamic Schema Discovery & Query Optimization

This document defines the design and technical specification for implementing dynamic schema discovery, a visual schema explorer tree UI, path-based auto-naming of nested properties, and automatic graph query depth optimization in the Egeria Advisor Report Spec Builder.

---

## 1. Problem Statement

Report specification authors face several challenges when configuring output columns for metadata views:
1. **Lack of Attribute Discoverability**: Standard Egeria payloads are hierarchical and dynamic, containing properties, relationship objects, and classifications. Authors must manually guess or search for correct dot-notation property paths (e.g. `properties.displayName` vs `member_of[].properties.displayName`).
2. **Missing Header Attributes**: The formatting engine (`materialize_egeria_summary`) skips critical header metadata like `status` and `versions` during flattening, making them completely unavailable for reporting.
3. **Suboptimal Graph Query Depths**: Fetching relations at high graph depths (e.g., `depth=5`) on every report run is highly inefficient. However, setting it too low (e.g. `depth=0`) breaks reports that query nested relationship attributes. The system needs to auto-tune parameters based on projected columns.

---

## 2. Technical Architecture

The feature set spans four layers: pyegeria serialization, advisor backend APIs, the query planner, and the frontend web UI.

```mermaid
flowchart TD
    subgraph UI (Canvas)
        Canvas[Report Spec Canvas] -->|GET /fields?draft_id=x| AppAPI
        Canvas -->|Browse Attributes| Modal[Schema Explorer Modal]
        Modal -->|GET /schema| AppAPI
    end
    subgraph Advisor Backend
        AppAPI[app.py Routes] -->|Speculative lookup| Discovery[discover_draft_schema_internal]
        Discovery -->|Register temp spec| Parser[report_spec_parser.py]
    end
    subgraph pyegeria SDK
        Discovery -->|get_report_spec_schema| Client[EgeriaTech Client]
        Client -->|Flatten| Materializer[materialize_egeria_summary]
    end
```

### 2.1 pyegeria Header Expansion
We will modify `materialize_egeria_summary` in `pyegeria.view.output_formatter` to map previously skipped header attributes back onto the flattened result dictionary:
* `status` ➔ `res["status"]`
* `origin` ➔ `res["origin"]`
* `versions` ➔ `res["version"]`, `res["created_by"]`, `res["create_time"]`, `res["updated_by"]`, `res["update_time"]`

### 2.2 Speculative Discovery API
A new API endpoint `GET /api/reports/drafts/{draft_id}/schema` will:
1. Load the active draft.
2. Form it into an in-memory `FormatSet` model and temporarily register it in the parser.
3. Execute `EgeriaTech.get_report_spec_schema` with a search string of `*` and `graph_query_depth=5` to fetch a deep sample element.
4. Return a list of all discovered property paths and their data types.

### 2.3 Query Planner & Depth Optimizer
In `ReportSpecAgent.execute()`, right before calling `exec_report_spec`, the Advisor will analyze the columns projected in the report spec:
* Compute the maximum required depth of any key path using a relationship-segment counting helper:
  * `properties.displayName` ➔ Depth 0
  * `member_of[].properties.displayName` ➔ Depth 1
  * `categories[].terms[].guid` ➔ Depth 2
* Set `graph_query_depth` to this computed maximum.
* If depth is `0`, also inject `skip_relationships = True` to bypass relationship fetches entirely.
* Respect any user-provided overrides in `custom_params`.

### 2.4 Visual Schema Explorer & Auto-Naming
* **Column Fields Endpoint**: Modify `GET /api/templates/Column/fields` to accept a `draft_id` query parameter and return the dynamic list of discovered keys as the `valid_values` auto-complete choices for the `Key` input field.
* **Path-to-Name Heuristic**: In the javascript UI, parse the dot-notation path to auto-generate a collision-free, human-readable name when the Key changes:
  * `categories[].terms[].guid` ➔ `"Category Term GUID"`
  * `member_of[].properties.displayName` ➔ `"Member Of Name"`
* **Visual Tree Modal**: Add a **Browse Attributes** button to the toolbar that renders a collapsible tree structure of the schema. Clicking `[+]` on any leaf automatically appends the card to the canvas.

---

## 3. Detailed Proposed Changes

### 3.1 pyegeria Modifications
* **File**: `pyegeria/view/output_formatter.py`
* **Changes**: Update `materialize_egeria_summary` to map `status`, `origin`, and `versions` properties.

### 3.2 Advisor Backend Modifications
* **File**: `advisor/web/app.py`
  * Add endpoint: `GET /api/reports/drafts/{draft_id}/schema`
  * Modify endpoint: `GET /api/templates/Column/fields`
* **File**: `advisor/agents/report_spec_agent.py`
  * Implement `calculate_required_depth()` and auto-tuning in `execute()`.

### 3.3 Frontend Modifications
* **File**: `advisor/web/static/report_spec_canvas.js`
  * Append `draft_id` to the fields URL.
  * Implement `_deriveColumnNameFromPath()`.
  * Add "Browse Attributes" UI modal and tree view.

---

## 4. Verification & Testing

### 4.1 Unit Testing
A new suite of tests in `tests/unit/test_report_spec_planner.py` will verify:
1. `calculate_required_depth` outputs correct depths (0, 1, 2) for standard and relationship-heavy property keys.
2. Query optimizer correctly maps and overrides parameters during execution when no user custom parameters are passed.

### 4.2 Integration & Manual Tests
1. Verify autocomplete list for Column Keys dynamically populates with Egeria properties.
2. Verify visual schema tree renders correctly in the dialog modal, allows expansion, and adds items successfully.
3. Validate auto-tuned query performance with live logging.
