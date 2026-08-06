# Egeria Push & Pull — Design Document

## Status — All phases complete

| Phase | Files | Status |
|---|---|---|
| **A1** — Real `SourceControlLibrary` creation | `egeria_publisher.py` | ✓ |
| **A2** — `egeria_asset_guid` column + registry cache | `registry.py` | ✓ |
| **A3** — `project_egeria_surveys` table + report GUID persistence | `registry.py`, `egeria_publisher.py` | ✓ |
| **A4** — Correct Egeria annotation subtype class names | `egeria_publisher.py` | ✓ |
| **B1** — `EgeriaReader` pull path | `egeria_reader.py` | ✓ |
| **B2** — `egeria-reports` CLI command | `cli/main.py` | ✓ |
| **C1** — Web API routes | `web/routes/egeria.py` | ✓ |
| **C2** — "Egeria" tab in web UI | `web/static/index.html` | ✓ |

---

## Background

The survey framework (Phase 1–2) already produces a complete `SurveyResult` from any indexed
project and prints it as a markdown report.  `EgeriaPublisher` exists but uses placeholder code
for asset registration (`SoftwareServer` stand-in) and does not persist Egeria GUIDs locally.

This document designs Phase 3: replacing the placeholder with real `SourceControlLibrary`
creation, improving the annotation push, adding a pull/read path, and surfacing Egeria surveys
in the CLI and web UI.

---

## What We Know From pyegeria

The correct API patterns (confirmed by `survey_crawler.py` and `asset_maker.py`):

| Operation | Method | Body class |
|---|---|---|
| Create SourceControlLibrary | `asset_maker.create_software_capability(body)` | `SoftwareCapabilityProperties` + `typeName: "SourceControlLibrary"` |
| Find existing capability | `asset_maker.find_software_capabilities(search_string)` | — |
| Create SurveyReport | `asset_maker.create_asset(body)` with `parentGUID` + `parentRelationshipTypeName: "ReportSubject"` | `SurveyReportProperties` |
| Create Annotation | `discovery.create_annotation(body)` with `parentGUID` + `parentRelationshipTypeName: "ReportedAnnotation"` | subtype `class` — see below |
| Link report to asset | `asset_maker.link_report_subject(subject_guid, report_guid)` | optional relationship props |

---

## Push — Phase A: Fix `EgeriaPublisher`

### A1 — `_find_or_create_asset`: replace placeholder with real call

Search first by `qualifiedName` so the operation is idempotent across multiple `--publish` runs.
If not found, create a `SourceControlLibrary` (a subtype of `ResourceManager → SoftwareCapability`).

```python
# Search
existing = asset_maker.find_software_capabilities(
    search_string=f"SourceControlLibrary::{github_url}",
    starts_with=True,
    output_format="DICT",
)
# → returns list of dicts; extract guid from existing[0]

# If not found — create
body = {
    "class": "NewElementRequestBody",
    "properties": {
        "class": "SoftwareCapabilityProperties",
        "typeName": "SourceControlLibrary",
        "qualifiedName": f"SourceControlLibrary::{github_url}",
        "displayName": display_name,
        "description": f"GitHub repository: {github_url}",
        "deployedImplementationType": "GitHub Repository",
        "additionalProperties": {
            "github_url": github_url,
            "project_slug": slug,
            "primary_language": primary_language,   # from project_stats
            "license": license,                      # from project_stats
            "topics": topics_csv,                    # from project_stats
        }
    }
}
guid = asset_maker.create_software_capability(body=body)
```

> **Resolved**: `SourceControlLibrary` adds one field: `libraryType` (string). Use
> `SoftwareCapabilityProperties` + `typeName: "SourceControlLibrary"` + `libraryType: "GitHub Repository"`.
> No dedicated subclass needed.

---

### A2 — Persist `egeria_asset_guid` in SQLite

Add column `egeria_asset_guid TEXT DEFAULT NULL` to the `projects` table.
Read it first in `_find_or_create_asset`; write it after creation or discovery.
This avoids a search call on every `--publish` run.

```python
# registry.py additions
def get_egeria_asset_guid(self, slug: str) -> str | None: ...
def set_egeria_asset_guid(self, slug: str, guid: str) -> None: ...
```

---

### A3 — `_create_survey_report`: store GUID in new `project_egeria_surveys` table

The `create_asset` call with `parentGUID` + `parentRelationshipTypeName: "ReportSubject"` is
already the correct pattern (confirmed by `survey_crawler.py`).  What's missing is persisting
the returned report GUID so we can retrieve it later for the pull path.
==> Remember that a survey happens at a point in time. We will often re-survey something periodically to pick up changes so we need to keep a timestamp at a minimum.
New SQLite table:

```sql
CREATE TABLE project_egeria_surveys (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug      TEXT NOT NULL,
    surveyed_at       TEXT NOT NULL,   -- matches project_file_type_counts.surveyed_at
    egeria_report_guid TEXT NOT NULL,
    published_at      TEXT NOT NULL,
    UNIQUE(project_slug, surveyed_at)
)
```

```python
# registry.py additions
def record_egeria_survey(self, slug: str, surveyed_at: str, report_guid: str) -> None: ...
def get_egeria_surveys(self, slug: str) -> list[dict]: ...  # all published runs, newest first
def get_latest_egeria_survey(self, slug: str) -> dict | None: ...
```

---

### A4 — `_create_annotations`: use correct Egeria subtype class names

Current code puts everything under `AnnotationProperties` with subtype-specific data in
`additionalProperties`.  The correct approach uses the proper Egeria subtype `class` so the
metadata is stored in native typed fields:

> **Resolved** (confirmed from Egeria type archive + user):

| Our `AnnotationType` | Egeria type name | `class` in properties body |
|---|---|---|
| `RESOURCE_MEASURE` | `ResourceMeasureAnnotation` | `ResourceMeasureAnnotationProperties` |
| `CLASSIFICATION` | `ClassificationAnnotation` | `ClassificationAnnotationProperties` |
| `QUALITY_SCORE` | `QualityAnnotation` | `QualityAnnotationProperties` |
| `DATA_CLASS` | `DataClassAnnotation` | `DataClassAnnotationProperties` |
| `REQUEST_FOR_ACTION` | `RequestForAction` | `RequestForActionProperties` (no "Annotation" suffix) |
| `SCHEMA_ANALYSIS` | `SchemaAnalysisAnnotation` | `SchemaAnalysisAnnotationProperties` |
| `RELATIONSHIP` | `RelationshipAdviceAnnotation` | `RelationshipAdviceAnnotationProperties` |

Each subtype carries native typed fields. We populate the core fields now and will add more over time:

```python
# ClassificationAnnotation — many more fields available (classificationName, properties, etc.)
props = {
    "class": "ClassificationAnnotationProperties",
    "qualifiedName": qualified_name,
    "summary": ann.summary,
    "annotationType": "ClassificationAnnotation",
    "candidateClassifications": ann.candidate_classifications,  # list[str]
    "confidence": ann.confidence,
    "jsonProperties": json.dumps(ann.json_properties),
}

# RequestForAction — note: class is RequestForActionProperties, not RequestForActionAnnotationProperties
props = {
    "class": "RequestForActionProperties",
    "qualifiedName": qualified_name,
    "summary": ann.summary,
    "annotationType": "RequestForAction",
    "actionRequested": ann.action_requested,
    "actionTargetName": ann.action_target_name,
}

# ResourceMeasureAnnotation — resourceProperties is a typed map field, not serialised JSON
props = {
    "class": "ResourceMeasureAnnotationProperties",
    "qualifiedName": qualified_name,
    "summary": ann.summary,
    "annotationType": "ResourceMeasureAnnotation",
    "resourceProperties": ann.resource_properties,  # dict, not json.dumps()
    "jsonProperties": json.dumps(ann.json_properties),
}
```
---

## Pull — Phase B: `EgeriaReader`

New `explorer/surveyors/egeria_reader.py` — read-only counterpart to `EgeriaPublisher`.
No `SurveyResult` dependency; returns plain dicts suitable for the CLI and web UI.

```python
class EgeriaReader:
    def __init__(self, platform_url, view_server, user_id, user_password): ...

    def find_asset_guid(self, github_url: str) -> str | None:
        """Search for the SourceControlLibrary by qualifiedName."""

    def get_survey_reports(self, asset_guid: str) -> list[dict]:
        """
        Return survey reports linked to the asset.
        Uses find_assets(search_string="SurveyReport::GitHubRepo::{slug}",
                         metadata_element_type="SurveyReport")
        Returns list of {guid, display_name, surveyed_at, annotation_count, ...}
        """

    def get_annotations(self, report_guid: str) -> list[dict]:
        """
        Return all annotations for a report.
        Uses discovery.find_annotations(search_string=f"Annotation::{slug}::{ts}::")
        Returns list of {guid, annotation_type, summary, confidence, json_properties, ...}
        """

    def get_full_report(self, report_guid: str) -> dict:
        """Report metadata + all annotations in one call."""
```

> **Resolved**: Regular `find`/`get` methods return `relatedElements` in the JSON payload by
> default, so we can walk `ReportSubject` from an asset response without a separate relationship
> call. We'll use `find_assets(search_string="SurveyReport::...", metadata_element_type="SurveyReport")`
> as primary path and fall back to `relatedElements` from the asset response if needed.
---

## Display — Phase C: CLI and Web UI

### CLI: `project-explorer egeria-reports <slug> [--full]`

```
$ project-explorer egeria-reports egeria-python

Egeria surveys for egeria-python
Asset GUID : abc-123  (SourceControlLibrary)
Platform   : https://localhost:9443

  #  Surveyed at           Annotations  Egeria Report GUID
  1  2026-05-18 19:16 UTC       22      def-456   ← latest
  2  2026-05-10 14:02 UTC       20      ghi-789

Run with --full to display all annotations for the latest survey.
```

`--full` output groups annotations by type:

```
Classification Annotations (4)
  • 381 file(s) classified as 'Python Source File'  [confidence: 90]
  • 235 file(s) classified as 'Markdown Document'   [confidence: 90]
  ...

Quality Score Annotations (1)
  • Overall health score: 52/100
    activity=100  community=10  releases=0  freshness=98

Requests for Action (2)
  • Missing SECURITY.md — add a security policy
  • No CI configuration found
```

### Web UI: "Egeria" tab

New tab alongside Stars / Commits / Files in the project detail panel.

**Asset card** (top):
- Registration status badge: `Registered in Egeria` (green) or `Not published` (grey)
- Asset GUID + deep-link to Egeria UI (`{EGERIA_PLATFORM_URL}/open-metadata/...`) if set
- Button: `Publish survey →` (triggers `POST /api/egeria/{slug}/publish`)

**Survey history table**:
| Date | Annotations | Errors | Report GUID |
|---|---|---|---|
| 2026-05-18 19:16 | 22 | 0 | def-456 |

**Annotation detail panel** (expandable per report):
- Grouped by annotation type
- Classification annotations show candidate labels + confidence
- Quality Score shows a mini radar chart (reuse `health_radar_plotly`)
- Requests for Action highlighted in amber

**New API routes**:
```
GET  /api/egeria/{slug}/status           → asset guid, registration status
GET  /api/egeria/{slug}/reports          → list of published surveys
GET  /api/egeria/{slug}/reports/latest   → latest report + annotations
POST /api/egeria/{slug}/publish          → trigger --publish programmatically
```

> **Question Q5**: Should the web UI "Publish" button run the full survey + publish in one
> call, or should it only publish the most recently run local survey (assuming survey data
> already exists in SQLite)?  The latter is faster and avoids re-running all sub-surveyors.
In one go.
> Also we should provide feedback in the UI if the survey step fails, so the user knows to fix local issues before trying to publish again.
> And we should also display information as tables and graphs when appropriate
---

## Implementation Order

| Phase | Files changed | Outcome |
|---|---|---|
| **A1** | `egeria_publisher.py` | Real `SourceControlLibrary` creation (no placeholder) |
| **A2** | `registry.py` — add `egeria_asset_guid` column | GUID persisted, no repeat searches |
| **A3** | `registry.py` — add `project_egeria_surveys` table; `egeria_publisher.py` | Report GUIDs + annotation counts persisted |
| **A4** | `egeria_publisher.py` — subtype class names | Proper typed Egeria annotations |
| **B1** | `explorer/surveyors/egeria_reader.py` (new) | Pull path working |
| **B2** | `explorer/cli/main.py` — `egeria-reports` command | CLI inspectable |
| **C1** | `explorer/web/routes/egeria.py` (new) | Web API routes: status, annotations, publish |
| **C2** | `explorer/web/static/index.html` | "Egeria" tab: registration badge, survey history table, lazy annotation expand, publish button |

All phases complete.

---

## Open Questions — All Resolved

| # | Question | Resolution |
|---|---|---|
| Q1 | Additional `SourceControlLibraryProperties` fields? | `libraryType: "GitHub Repository"` — only one extra field beyond base `SoftwareCapabilityProperties` |
| Q2 | Exact `class` strings for annotation subtypes? | Confirmed from Egeria type archive: `RequestForActionProperties` (no "Annotation" suffix), `QualityAnnotationProperties` (not "QualityScore"), see Phase A4 table |
| Q3 | Is `resourceProperties` a typed map or JSON string? | Typed map — pass as `dict`, not `json.dumps()` |
| Q4 | Relationship-walk API for survey reports from asset GUID? | Regular `find`/`get` methods return `relatedElements`; primary path is `find_assets(search_string="SurveyReport::GitHubRepo::{slug}::")` |
| Q5 | Web "Publish" button: re-survey or publish last local survey? | Full survey + publish in one call; show feedback if either step fails (stage field distinguishes "survey" vs "publish" failure); display as tables and graphs |
