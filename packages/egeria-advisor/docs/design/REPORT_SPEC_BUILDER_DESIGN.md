# Report Spec Builder — Design Reference

**Last updated:** 2026-06-26

---

## Core concept

A **Report Spec** (also called a FormatSet) is a persistent **view definition** — it declares
what to fetch (`action_function`), what to show (`columns`), and how to filter and shape the
output.  It is *not* a one-time document; it is closer to a saved SQL view:

- Same spec + same parameters → repeatable, comparable output
- Users iterate: preview → tweak → preview → save (or discard)
- Saving results is a separate, explicit gesture from saving the spec

This is the key distinction from the LGCI Plan builder, where a plan is an imperative,
single-run document.

---

## Lifecycle model

```
[User query / Plan Builder]
        │
        ▼
   Draft (JSON)              ── ~/egeria-reports/drafts/draft_report_<ts>_<slug>.json
        │  conversational Q&A via ReportSpecElicitor
        │  canvas edits via PATCH /api/reports/drafts/{draft_id}/columns
        ▼
   Catalog entry (Markdown)  ── ~/egeria-reports/inbox/<spec_id>.md
        │  stays here permanently; can be previewed / edited at any time
        │  execute → writes result snapshot to outbox; spec is NOT moved
        ▼
   Result snapshot (Markdown) ── ~/egeria-reports/outbox/<spec_id>_executed_<ts>.md
        │  each run produces a new timestamped snapshot
        ▼
   Trash (Markdown)          ── ~/egeria-reports/trash/   (soft-delete, restorable)
   Versions (Markdown)       ── ~/egeria-reports/versions/ (auto-saved before each overwrite)
```

### Key rules

- Specs **never leave inbox on execute**. `move_to_outbox` writes a new snapshot; it does
  not unlink the source file.
- `retry` re-runs by stripping the `_executed_<ts>` suffix and calling `execute()` on the
  base spec in inbox.
- `recover` confirms the spec is in the catalog (it always is, unless explicitly deleted).
- Drafts are separate from the catalog. A draft becomes a catalog entry only after
  `_generate_report_spec` is called (the `elicit_columns → refine` transition).

---

## Spec model

```
ReportSpec (draft JSON / Markdown)
├── Identity
│   ├── title             slug-safe identifier, also the filesystem key
│   ├── heading           human-readable report title
│   ├── description       one-line summary
│   ├── target_type       Egeria entity type (Asset, Glossary, Project, …)
│   └── family            grouping for the catalog sidebar
├── Source
│   └── action_function   "ClientClass.method" — the FROM clause
├── Projection
│   └── columns[]         ordered list of Column definitions (SELECT clause)
│       ├── name          display label
│       ├── key           pyegeria attribute key
│       ├── format        False | True | "bulleted-list" | …
│       ├── detail_spec   name of a nested FormatSet (master-detail)
│       └── formats       which output formats include this column ("ALL" or CSV list)
├── content_filters       dict  ← part of spec identity; saved with spec
│   ├── search_string     glob filter applied to the fetch
│   ├── status_filter     ACTIVE | DRAFT | DEPRECATED | …
│   └── …                 other per-function filters
├── shape_defaults        dict  ← how data is organized; collapsible in UI
│   ├── sort_field        attribute key to sort by
│   ├── sort_order        ASC | DESC
│   ├── graph_query_depth int (0 = shallow, higher = deeper traversal)
│   ├── include_anchors   bool
│   └── include_lineage   bool
└── performance_hints     dict  ← operational tuning; advanced panel
    ├── page_size         int (default 100)
    └── start_from        int (default 0)
```

### Three parameter categories

| Category | UX treatment | Part of spec identity? |
|---|---|---|
| **Content filters** | Front and centre; run modal pre-fills these | Yes — change them, get different data |
| **Shape defaults** | Collapsible "Report Configuration" section | Yes — change them, get different layout |
| **Performance hints** | "Advanced / Execution Settings" panel | No — operational tuning only |

`graph_query_depth` straddles shape and performance: it affects both the data returned
(shape) and query cost (performance).  It lives in `shape_defaults`.

---

## Markdown format (catalog entry)

The markdown file is both the serialization format and the editable representation a user
can open in an editor.  It follows Dr.Egeria `## Verb Object` / `### Attribute` conventions
so the `UniversalExtractor` can parse it.

```markdown
# <Heading>

## Create Report Spec
### Target Type
<target_type>

### Heading
<heading>

### Description
<description>

### Action Function
ClientClass.method

### Required Params
search_string

### Content Filters
search_string=*
status_filter=ACTIVE

### Shape Defaults
sort_field=display_name
sort_order=ASC
graph_query_depth=0

### Performance Hints
page_size=100
start_from=0

## Create Column
### Name
Display Name
### Key
display_name

## Create Column
### Name
GUID
### Key
guid
### Format
True
```

Parser behaviour:
- `Content Filters`, `Shape Defaults`, `Performance Hints` values are key=value blocks
  parsed by `_parse_spec_params` and merged into `ActionParameter.spec_params` at parse time.
- `Required Params` is a comma-separated list of parameter names the user must supply at
  run time (e.g., the search string in the run modal).
- `Spec Params` (legacy) is also merged into `spec_params` for backward compatibility.

---

## Component map

| Component | File | Responsibility |
|---|---|---|
| `ReportSpecElicitor` | `advisor/agents/report_spec_elicitor.py` | 3-phase conversational Q&A; markdown generator |
| `ReportSpecAgent` | `advisor/agents/report_spec_agent.py` | execute / retry / recover; calls pyegeria |
| `ReportDraftManager` | `advisor/report_draft.py` | JSON draft CRUD in `~/egeria-reports/drafts/` |
| `ReportSpecDocumentManager` | `advisor/report_spec_docs.py` | Markdown catalog CRUD; result snapshots |
| `parse_report_spec_markdown` | `advisor/report_spec_parser.py` | Markdown → FormatSet via UniversalExtractor |
| `validate_report_spec` | `advisor/report_spec_parser.py` | checks client class + method exist in pyegeria |
| `report_spec_canvas.js` | `advisor/web/static/report_spec_canvas.js` | Canvas UI for column editing |
| Web routes | `advisor/web/app.py` lines 855–1072 | REST API for all draft/doc/execute operations |

---

## Execution flow

```
POST /api/reports/docs/{doc_id}/execute
  → ReportSpecAgent.execute()
      1. load spec markdown from inbox
      2. parse_report_spec_markdown() → FormatSet
      3. register_report_spec(base_doc_id, spec)   ← registers under the SAME key exec_report_spec looks up
      4. validate_report_spec()                     ← warns; does not block
      5. merge params: spec.spec_params + custom_params
      6. pyegeria.exec_report_spec(base_doc_id, …)
      7. format output
      8. move_to_outbox()  → writes <base_doc_id>_executed_<ts>.md; spec stays in inbox
```

### Registration key alignment

`register_report_spec` uses `base_doc_id` (with `_executed_<ts>` stripped).  `exec_report_spec`
looks up the spec by the name passed to it.  Both use the same `base_doc_id`, so the lookup
always hits the in-memory registration from step 3.

---

## Known gaps (not yet implemented)

- **Discovery / meta-level navigation** — "databases" is ambiguous across conceptual, logical,
  and physical meta-levels.  Discovery should use RAG over `egeria_types` + `egeria_concepts`
  and present structured choices (buttons/cards), not freeform chat.
- **Master-detail parameter inheritance** — whether detail specs inherit `content_filters` /
  `shape_defaults` from the master spec or have their own three-category model is unresolved.
- **Parameter profiles** — named sets of parameters (e.g., "deep traversal", "quick lookup")
  that can be applied to any spec at run time.
- **Canvas parameter panels** — the canvas currently edits columns only.  A "Report
  Configuration" collapsible and an "Advanced" panel for the three parameter categories are
  the next UI work item.
- **Preview** — zero-cost stateless run that does NOT write a result snapshot.  Should be
  callable at any phase (draft or saved).
