# Cross-resource and conversational intelligence extensions — design and implementation plan

**Status:** In progress (Group 1 implemented and verified, Groups 2–4 planned).  
**Written:** 2026-10-16  
**Branch:** `re/cross-resource-chat-extensions`  
**Referenced from:** `docs/Architecture.md`, `CLAUDE.md`, `AGENTS.md`

---

## 1. Context and Problem Statement

Resource Explorer originally evolved from Project Explorer with a primary focus on individual Git repositories. While individual asset surveying, single-resource context compilation (`trellis-context`), and specialized agents (`CompareAgent`, `IntegrationAgent`, `ConversationAgent`) were established, significant architectural and operational gaps remained when reasoning across heterogeneous assets:

1. **Siloed Asset Types in Comparison and Integration:**
   `CompareAgent` and `IntegrationAgent` were historically optimized for repository-to-repository comparisons (commit velocity, stars, contributors, doc embeddings). Cross-database comparisons (schema diffing, column types, nullability, primary key constraints) and cross-tier comparisons (application repo ↔ PostgreSQL database) lacked dedicated tools and structured syntheses.

2. **Single-Resource Context Compilation Limitation:**
   The deterministic context compiler (`context_compile.py` + `trellis-context`) strictly compiled survey findings for a single resource slug. Comparative and integration queries either bypassed context compilation entirely or relied on unpredictable, multi-step LLM vector search tool calls that risk token overflow and hallucinations.

3. **Missing Cross-Asset Dependency Linkage:**
   Surveys independently extract ORM models, SQL queries, and migration files in code repositories, and table/column schemas in database surveys. However, no deterministic bridge connected code assets to the database catalog entities they query.

4. **Lack of Chat-Driven Actionability:**
   When conversational agents discovered architectural drift, schema mismatches, or missing documentation, users had no mechanism to convert those conversational findings into persistent governance tasks without manually navigating to other forms.

---

## 2. Design Principles and Architectural Boundaries

To preserve system determinism, auditability, and token efficiency, this work adheres to the core repository constraints:

1. **Zero LLM Calls in Surveyors:**
   All surveys and cross-resource linkages remain strictly deterministic (AST parsing, SQL metadata introspection, regex extraction, schema joins). LLMs are employed exclusively at the query and conversational synthesis layer.
2. **Deterministic Context Compilation Over Open-Ended Tool Loops:**
   Rather than letting agents execute dozens of exploratory tool calls to inspect two assets, the system deterministically compiles structured multi-resource evidence ladders fitting precise token budgets before LLM invocation.
3. **Epistemological Honesty ("Known vs. Never Run"):**
   Comparisons must surface survey coverage discrepancies explicitly using `FactLayer` states (`KNOWN`, `NEVER_RUN`, `FAILED`) to prevent treating an unmeasured property as an absent feature.
4. **Local-First with Graceful Degradation:**
   All cross-resource tools and fallbacks must function fully offline using local PostgreSQL/SQLite registry state, while providing clean hooks into upstream Egeria Open Metadata Highway / OMAG services when configured.

---

## 3. Four-Group Structured Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Group 1: Immediate Actionability & Single-Domain Diffing   │
│ • Chat-to-RFA synthesis tool (create_rfa_from_finding)      │
│ • Database schema comparison tool (compare_database_schemas)│
│ • CompareAgent & ConversationAgent tool integration         │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Group 2: Multi-Resource Context Compilation & Budgeting     │
│ • Multi-slug trellis-context evidence ladder partitioning   │
│ • Epistemological asymmetry matrix (FactLayer coverage diff)│
│ • Proportional token budget allocation (40/40/20 split)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Group 3: Cross-Asset Static Linkage & Agent Delegation      │
│ • Static Repo-to-Database table reference extraction        │
│ • ConversationAgent dynamic delegation to specialist agents │
│ • Cross-resource dependency graph resolution                │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Group 4: Upstream Governance Traversal & Frontend UX        │
│ • Egeria OMAG/OMVS lineage queries in IntegrationAgent      │
│ • Interactive multi-resource disambiguation chips in Web UI │
│ • Seamless A2A input_required handling                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Group 1: Immediate Actionability & Single-Domain Diffing (Implemented)

### 4.1 Objectives
- Provide agents with the ability to file structured `RequestForAction` (RFA) entries directly into the persistent `#rfa-drawer`.
- Enable deep, structural database schema comparisons across registered databases.

### 4.2 Implemented Components

1. **`create_rfa_from_finding` Tool (`resource_explorer/agents/tools.py`):**
   - Resolves target resource across repos, databases, and filesystems via `ProjectRegistry`.
   - Persists open RFA entries using `activity_logger.log_rfa()`.
   - Records corresponding activity log entries for full operational auditability.

2. **`compare_database_schemas` Tool (`resource_explorer/agents/tools.py`):**
   - Retrieves latest survey data for two databases from `ProjectRegistry.get_latest_database_survey()`.
   - Computes structural diffs:
     - High-level dimensions (host, port, db_type, total tables/columns).
     - Exclusive vs. common schemas and tables.
     - Per-table column-level diffs (data types, nullability, primary key constraints).
   - Supports optional schema-level filtering (`schema_name_a`, `schema_name_b`).

3. **Agent Integration:**
   - **`CompareAgent` (`resource_explorer/agents/compare_agent.py`):** Enhanced with database detection, schema diffing prompt guidance, and direct fallback execution via `compare_database_schemas_raw`.
   - **`ConversationAgent` (`resource_explorer/agents/conversation_agent.py`):** Registered `compare_database_schemas` and `create_rfa_from_finding` tools in the BeeAI agent toolset.
   - **Prompt Templates (`resource_explorer/prompt_templates.py`):** Updated system instructions to guide agents on when and how to invoke schema diffing and RFA logging.

### 4.3 Verification
- Tested via `tests/test_agent_tools.py` covering tool execution, RFA logging, database diff generation, and agent fallback modes against SQLite fixtures.

---

## 5. Group 2: Multi-Resource Context Compilation & Budgeting (Planned)

### 5.1 Objectives
Extend `context_compile.py` and `trellis-context` integration to compile structured comparative context for two or more resource slugs within a single token budget.

### 5.2 Key Decisions

1. **Proportional Token Allocation:**
   - When compiling context for resources $A$ and $B$, partition the available model context budget (e.g. 32k for dev, 2k for demo tiers):
     - Resource A Facts: 40%
     - Resource B Facts: 40%
     - Cross-Resource Vector/Shared Overlap: 20%
2. **Epistemological Asymmetry Matrix:**
   - Compare `FactLayer` states for both assets across standard survey dimensions (e.g., security scan, license classification, dependencies, schema profiling).
   - Generate an explicit coverage comparison block:
     ```markdown
     | Dimension | Resource A (repo-alpha) | Resource B (repo-beta) |
     |---|---|---|
     | Security Scan | KNOWN (Score: 88/100) | NEVER_RUN |
     | License | KNOWN (Apache-2.0) | KNOWN (MIT) |
     | CI Quality | KNOWN (GitHub Actions) | FAILED (Timeout) |
     ```
3. **Independent Ladder Degradation:**
   - If total facts exceed budget, degrade each resource independently using `trellis-context` rungs (`FULL` → `SUMMARY` → `STRUCTURE_ONLY`) to ensure both resources retain equal representation.

### 5.3 Planned Deliverables
- `resource_explorer/context_compile.py`: Implement `compile_multi_resource_context(slugs, query, perspective, budget)`.
- Unit tests validating token bounds, ladder degradation, and manifest generation across multiple resources.

---

## 6. Group 3: Cross-Asset Static Linkage & Agent Delegation (Planned)

### 6.1 Objectives
Bridge application code repositories to cataloged databases and enable `ConversationAgent` to dynamically delegate complex comparative/integration sub-goals.

### 6.2 Key Decisions

1. **Code-to-Database Static Matching:**
   - Extract table references from repo surveys:
     - SQL literals and migration scripts (e.g., Flyway, Liquibase, Alembic).
     - ORM entity definitions (e.g., JPA `@Table`, SQLAlchemy `__tablename__`, Django models).
   - Match extracted table names against database schemas stored in `ProjectRegistry`.
   - Store discovered linkages as cross-resource references without requiring external lineage tools.
2. **Sub-Agent Delegation in Multi-Turn Chat:**
   - Equip `ConversationAgent` with delegation tools (`delegate_to_compare_agent`, `delegate_to_integration_agent`).
   - When a user in a repository chat asks a side-by-side or pipeline question, `ConversationAgent` delegates execution and incorporates the specialized agent's structured response (including Plotly comparison figures or symbol tables).

### 6.3 Planned Deliverables
- `resource_explorer/surveyors/cross_asset_matcher.py`: Deterministic table-to-repo reference matcher.
- Delegation tool implementations in `resource_explorer/agents/conversation_agent.py`.
- Tests verifying cross-asset discovery and intent delegation handoffs.

---

## 7. Group 4: Upstream Governance Traversal & Frontend UX (Planned)

### 7.1 Objectives
Integrate upstream Egeria Open Metadata Highway lineage and governance classifications, and provide interactive multi-resource disambiguation in the Web UI.

### 7.2 Key Decisions

1. **Egeria OMAG Lineage Traversal:**
   - Add lineage query capabilities to `IntegrationAgent` targeting Egeria's `DataEngineOMAS` and `LineageOMVS` endpoints via `pyegeria`.
   - Trace end-to-end data flows (e.g., FileSystem Ingestion → Event Topic → DB Store → Service API).
   - Provide strict local fallback when Egeria is unreachable or lineage is unindexed.
2. **Interactive UI Disambiguation Chips:**
   - When `QueryProcessor` detects a comparative or integration query with ambiguous or missing targets, return candidate resource chips in the Web UI chat drawer (mirroring the A2A `input_required` protocol).
   - Allow users to click resource chips to populate the comparison targets directly.

### 7.3 Planned Deliverables
- `resource_explorer/agents/integration_agent.py`: Add Egeria lineage traversal tool with safe fallback.
- Web UI frontend updates in `index.html` / `query.py` handling `input_required` interactive chip payloads.
- Contract tests for Egeria lineage parsing with mocked network fixtures.

---

## 8. Summary of Milestones & Verification Matrix

| Group | Component | Deliverable | Status | Verification |
|---|---|---|---|---|
| **Group 1** | Actionable RFA Tool | `create_rfa_from_finding` | **Done** | `tests/test_agent_tools.py` |
| **Group 1** | Database Schema Diff | `compare_database_schemas` | **Done** | `tests/test_agent_tools.py` |
| **Group 2** | Multi-Resource Context | `compile_multi_resource_context` | Planned | Unit tests + token invariant tests |
| **Group 2** | Epistemological Matrix | Cross-slug `FactLayer` diff | Planned | Coverage diff test suite |
| **Group 3** | Code-to-DB Matcher | Static table-to-repo matcher | Planned | Repository AST join tests |
| **Group 3** | Dynamic Sub-Agent Delegation | `ConversationAgent` delegation tools | Planned | Delegation handoff test suite |
| **Group 4** | Egeria Lineage Traversal | `IntegrationAgent` lineage tools | Planned | PyEgeria mock contract tests |
| **Group 4** | Web UI Interactive Chips | Disambiguation chip rendering | Planned | Frontend UI integration tests |
