# Resource Explorer — User Guide

**Last revised:** 2026-06-10

Resource Explorer discovers, surveys, and catalogs information resources using Egeria as the metadata catalog. This guide covers the web UI, the four user intents, and how to get the most out of each workflow.

---

## Starting the web UI

```bash
uv run resource-explorer web     # → http://localhost:8810
```

---

## Layout

The web UI has three zones:

- **Left sidebar** — select a resource type (Repos / Databases / Filesystems) and choose a specific resource
- **Main panel** — survey report, analysis menu, discovery results, or RFA panel depending on the active intent tab
- **Header** — global navigation: Survey Report | 📋 RFAs | 🔬 Analyses | 📋 Context | 💬 Chat | 📊 Activity

---

## Four Intents

### Scouting
*Goal: broad inventory across many resources, fast*

Select **Scouting** in the Analyses panel, then click **Run all scouting analyses**. This runs:
- Language and file classification
- Repository health metrics
- Basic dependency detection

Results appear in the Activity Log and are visible in the Survey Report immediately after the run completes.

### Assessment
*Goal: deep analysis of a specific resource*

Select a resource, open **Analyses**, and choose Assessment intent. Run individual analyses:
- **Dependency Analysis** — full dependency graph with version pins
- **Security Scan** — secrets, vulnerable patterns, exposed credentials
- **Documentation Coverage** — doc ratio by file type
- **Data File Profiling** — column counts, row counts, null rates for CSV/Parquet/etc.
- **API Structure** — detected API endpoints, OpenAPI specs
- **Catalog & Survey in Egeria** — register in Egeria and trigger native survey

Assessment analyses are marked ⏱ (minutes) or ⏳ (async for Egeria-native). Results appear in the Survey Report with a ☁ or 🏠 source badge indicating where the data came from.

### Discovery
*Goal: find resources by what surveys revealed*

Use the **Chat** panel to ask questions based on survey metadata:
- "Find databases with more than 50 tables"
- "Which repos have security annotations?"
- "Show me databases where the steward is unset"

### Enrichment
*Goal: provide human context; answer open RFAs*

Open the **RFAs** panel to see open RequestForAction annotations. These are generated automatically when:
- A survey creates a `RequestForAction` Egeria annotation
- The Context form has blank critical fields (environment, sensitivity, responsible steward, org owner)

Answer RFAs by clicking them and filling in the requested information. Answers are stored locally; Egeria write-back is coming in a future release.

The **Context** panel lets you fill in resource context proactively:

| Field | Why it matters |
|-------|---------------|
| Environment | prod / staging / dev — used for risk scoring |
| Org owner | Which team owns this resource |
| Responsible steward | Who to contact for data questions |
| Sensitivity | Public / Internal / Confidential / Restricted |
| Purpose | What this resource is used for |
| Geographic location | Compliance and data residency |
| Backup status | Recovery planning |

---

## Files and File Systems

Resource Explorer supports traversing local folders and data files (CSV, Parquet, Excel), profiling their schemas, and cataloging them in Egeria.

### Mount Point Translation
Egeria captures filesystem locations using two distinct mount points to allow separate services to align metadata:
*   **Local Mount Point** — the absolute root path as seen on the disk where the Resource Explorer is running (e.g., `/Users/dwolfson/localGit/data`).
*   **Canonical Mount Point** — the logical path used in Egeria's catalog so that different containerized/remote components agree on the resource's identity (e.g., `file://shared-nfs/data`).

During survey execution, file paths are automatically translated using:
$$\text{canonical\_path} = \text{canonicalMountPoint} + \text{relative\_path\_from\_localMountPoint}$$

### Walk & Data Profiling
Running a survey walks the local directory structure (excluding noise directories like `.git`, `node_modules`, `.venv`) and uses Pandas and PyArrow to profile data schemas. Profiled details include:
*   File format and file sizes.
*   Row and column counts.
*   Detailed schemas showing column names, datatypes, and null percentage rates.

### Egeria Publishing & Integration
Publishing a filesystem survey performs direct cataloging:
*   **Compensation Layer:** Since Egeria repository services fail to recognize the default `FileSystem` classification type during standard template instantiation on some platforms, Resource Explorer catalogs the filesystem root folder as a root `DataFolder` asset.
*   Data files are registered as `DataFile` variants (`CSV Data File`, `Parquet Data File`, `Spreadsheet Data File`, or generic `File`) using the computed `canonical_path`.
*   A `SurveyReport` is published under the root asset, containing a `ResourceMeasureAnnotation` (for overall folder stats) and a `SchemaAnalysisAnnotation` for each profiled data file.

---

## Survey Report

The Survey Report shows the current state of the selected resource. Each section has a source badge:
- **☁ Egeria** — data from the Egeria native survey
- **🏠 Local** — data from the local Python/SQL scan
- **⏳ Pending** — analysis triggered; results not yet available

The **Survey Analyses** section at the top of the report lists which analyses ran during the last survey execution and how many annotations each produced — making the survey's composition visible. This aligns with Egeria's model: a survey is a collection of analyses; each analysis produces annotations; the report is all annotations from one execution instance.

If two or more survey runs exist, a **"Changes since last run"** banner appears at the top showing what changed (file counts for repos; schema/table/column deltas for databases).

Below the main report, a **Survey History** chart shows key metrics over time.

---

## Analyses Panel

The Analyses panel lists all available analyses for the selected resource type, filterable by:
- **Intent**: All / Scouting / Assessment / Discovery / Enrichment  *(separate row)*
- **Perspective**: All / DBA / Data Scientist / Steward / Security  *(separate row)*

★ Recommended analyses are highlighted. Each card shows the intent tag, speed (⚡ fast / ⏱ minutes / ⏳ async), and the annotation count from the last survey run.

At the bottom of the panel, the **Schedule** section lets you configure recurring runs:
- Select an interval (manual / daily / weekly / monthly)
- Toggle enabled/disabled per analysis
- Changes are saved immediately and the background scheduler picks them up

---

## Activity Log

The **📊 Activity** link in the header opens the persistent activity log. Every operation writes an entry:
- **scout** / **survey** / **catalog** / **publish** / **rfa** / **refresh**
- Each entry shows status (ok / error / pending), summary, and expandable annotation details

---

## Chat Panel

The Chat panel provides RAG-backed Q&A scoped to the selected resource (or all resources if none is selected). Queries are classified by intent and routed to the appropriate agent:

| Intent | Agent | What it does |
|--------|-------|-------------|
| survey_meta | SurveyMetaAgent | Questions about surveys, schedules, RFAs, and resource context |
| statistical | StatsAgent | GitHub metrics, commit trends |
| comparison | CompareAgent | Side-by-side project comparison |
| examples | ExamplesAgent | Generates runnable Python code |
| code_search | CodeAgent | Searches code collections in pgvector |
| health | HealthAgent | Community health metrics |
| conceptual | DocAgent | Architecture, documentation |
| general | RAG | Searches all relevant collections |

`survey_meta` is checked first; use it for questions like "when was this last surveyed?", "what analyses are scheduled?", "what RFAs are open?", or "what is the sensitive data annotation for this database?".

Prefix your question with the resource slug to scope it: `mydb: how many tables are in the public schema?`

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Submit chat message |
| `Esc` | Clear chat input |

---

## CLI reference

```bash
# Survey a repo
uv run resource-explorer survey my-repo

# Survey and publish to Egeria
uv run resource-explorer survey my-repo --publish

# Register, list, and survey filesystems
uv run resource-explorer filesystem register my-data --local-path /Users/dwolfson/localGit/data --canonical-path file://shared-nfs/data
uv run resource-explorer filesystem list
uv run resource-explorer filesystem survey my-data            # Local walk and profiling
uv run resource-explorer filesystem survey my-data --egeria   # Survey and publish to Egeria

# Interactive chat
uv run resource-explorer chat

# Ask a one-shot question
uv run resource-explorer ask "how many files does my-repo have?"
```
