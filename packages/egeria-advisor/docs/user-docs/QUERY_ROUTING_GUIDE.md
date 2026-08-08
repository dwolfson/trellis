# Egeria Advisor Query Routing Guide

**Last Updated:** 2026-07-11

## Overview

Egeria Advisor routes every query through a multi-layer classification pipeline before touching the vector store or any external service. Understanding how routing works helps you phrase questions to get the best results, and helps developers understand where to look when routing misbehaves.

---

## Routing Pipeline (in order)

```
Query + perspective + intent_override
  │
  ├─ 1. QueryCache            ← cache hit → return immediately
  │
  ├─ 2. QueryProcessor        ← pattern match against routing.yaml (CRITICAL → HIGH → MEDIUM → LOW)
  │       └─ if 'general': LLM intent classifier → refined intent
  │
  ├─ 3. Role-aware routing    ← fires before pipeline; skipped when intent_override is set
  │
  └─ 4. Pipeline dispatch     ← sends to the right agent or RAG path
```

---

## Layer 1 — Pattern Matching (`config/routing.yaml`)

Patterns are checked in priority order. The **first match wins**; lower-priority patterns are ignored.

| Priority | Intent types covered |
|---|---|
| **CRITICAL** | `example` (Python code requests), `code_search` (method discovery, how-to navigation), `quantitative`, `debugging`, `best_practice`, `comparison` |
| **HIGH** | `report` (explicit run/show/list commands), `command` (Dr.Egeria create/update/link/set) |
| **MEDIUM** | `code_search` (broad show-me/how-to), `example`, `relationship`, `explanation` |
| **LOW** | `code_search`, `explanation`, `general` |

### CRITICAL patterns that matter most

**Python/code example requests** (`example` intent) — fire before any command or report pattern:
- `"python example"`, `"write python"`, `"give me a python"`, `"show me python"`
- `"python code example"`, `"python code for"`, `"python snippet"`
- `"give me an example"`, `"give me a code"`, `"code example for"`, `"code sample for"`

**Method/API discovery** (`code_search` intent) — fire before generic patterns:
- `"what methods"`, `"which methods"`, `"list methods"`, `"available methods"`
- `"what api"`, `"available api"`, `"api for"`, `"api reference"`
- `"what functions"`, `"list functions"`, `"what operations"`
- `"what can i do with"`, `"what class"`, `"which class"`, `"what pyegeria"`
- `"methods for"`, `"methods to"`

---

## Layer 2 — LLM Intent Classifier (`advisor/llm_intent_classifier.py`)

When pattern matching returns `general`, a zero-temperature LLM call refines the intent:

| Category | Maps to intent | Trigger condition |
|---|---|---|
| `LIVE_DATA` | `report` | User wants current data from Egeria right now |
| `CODE_HELP` | `code_search` | Query mentions "python", "example", "sample", "code", "how do I", "how to", "write a" |
| `CONCEPT` | `explanation` | User wants a definition or explanation |
| `WRITE_COMMAND` | `command` | Direct imperative command with **no** python/code/example qualifier |
| `AMBIGUOUS` | `general` | Genuinely unclear |

**Important:** `CODE_HELP` wins over `WRITE_COMMAND` whenever the query contains python/example/code keywords, even if the topic is about creating or updating objects (e.g., *"write a python example to create a governance definition"* → `CODE_HELP`, not `WRITE_COMMAND`).

---

## Layer 3 — Role-Aware Routing

Applied *after* classification but *before* pipeline dispatch. **Skipped when `intent_override` is set from the UI.**

| Role | Signals present | Routing |
|---|---|---|
| `developer` or `data_engineer` | code, example, how-to, or method-discovery keywords | → ExamplesAgent (bypasses pipeline) |
| `data_steward` or `governance_officer` | example/show-me signals, **without** Python keyword | → Clarification response (Python code vs Dr.Egeria template) |
| Any | Python keyword present | Never routed to report pipeline |

---

## Layer 4 — Pipeline Dispatch

| Classified intent | Additional condition | Agent / path |
|---|---|---|
| `quantitative` | — | Analytics module (SQLite) |
| `relationship` | — | RelationshipQueryHandler |
| `report` | semantic score ≥ 0.50 AND no Python keyword | MCP ReportPipeline |
| `command` | query contains "template", "sample", "example", "show me", or "give me" | DrEgeriaTemplateAgent → filesystem `.md` lookup |
| `command` | no template keyword | DrEgeriaActionAgent → MCP command execution |
| `code_search` or `example` | method-discovery signals ("what methods", "what api", …) | ExamplesAgent — **API reference mode** → class/method table |
| `code_search` or `example` | code-example signals | ExamplesAgent — **example mode** → runnable Python |
| `code_intel` | — | `CodeIntelAgent` — structural SQL over the code symbol table, no RAG/LLM involved |
| `create` | — | `CreateRouter` — classifies as a plan request (`PlanElicitor`), report spec request (`ReportSpecElicitor`), or ambiguous (Python/Dr.Egeria button choice) |
| `explanation`, `best_practice`, `comparison`, `debugging`, `general` | — | DocAgent → conceptual answer from indexed docs |
| *(fallback)* | — | RAG retrieval + LLM generation |

---

## What to Ask and What You Get Back

### Runnable Python Code Examples

Ask with Python/code keywords:

```
"Give me a python example to create a governance definition"
"Write python code to list all glossaries"
"Show me python code for creating a project"
"Python snippet for searching data assets"
```

You get back a complete, runnable Python script with:
- Both constructor options (explicit params and zero-arg from `.env`)
- `create_egeria_bearer_token()` before any API call
- `try / except PyegeriaException / finally client.close_session()`
- Inline parameter comments

### API Reference / Method Discovery

Ask what's available on a topic:

```
"What methods are available for governance definitions?"
"Which class handles glossary management in pyegeria?"
"What API does pyegeria have for projects?"
"List methods for DataDesigner"
"What pyegeria methods can I use with collections?"
"What functions are available for creating terms?"
```

You get back a structured markdown table: class name, import path, method names, parameters, and one-line docstring descriptions.

### Dr.Egeria Markdown Templates

Ask for the command template you paste into a Jupyter cell:

```
"Show me a Dr.Egeria template for creating a glossary"
"Give me the command template for creating a governance definition"
"Dr.Egeria sample for linking a term"
"Show me the Act template for creating a project"
```

You get back the pre-generated `.md` template content wrapped in a fenced block, plus a short explanation of required vs optional fields.

Templates are read from `{EGERIA_ROOT_PATH}/Templates/Dr-Egeria-Templates/{basic|advanced}/{family}/{command}.md`. They can be regenerated at any time with `generate_md_cmd_templates.py --advanced`.

### Live Egeria Reports

Ask for current data from a running Egeria instance:

```
"List available glossaries"
"Show me all governance zones"
"What collections exist?"
"Run the Glossary Terms report"
```

Or click any report in the left sidebar — the Run modal opens and always forces `intent_override: 'report'` regardless of which intent button is active.

### Conceptual Explanations

Ask open-ended questions about Egeria concepts:

```
"What is a governance zone?"
"How does data lineage work in Egeria?"
"Explain the difference between a glossary and a data dictionary"
"What is the purpose of an Asset Manager OMAS?"
```

These go to DocAgent, which searches `egeria_concepts`, `egeria_general`, `egeria_types`, and `pyegeria`.

---

## Using the Intent Override Buttons

The intent bar in the current Web UI is: **Auto / Explain / Show me / Inspect / Run Report /
Act / Create / Troubleshoot**. ("Report" was renamed "Run Report" and "Plan" was renamed
"Create" in Phase 12; "Inspect" was added after Phase 11g.)

| Button | Forced intent | Best used when |
|--------|-------------|----------------|
| **Auto** | *(classified)* | Default — role + signals determine the route |
| **Explain** | `explanation` | You want a concept explained, not code |
| **Show me** | `code_search` | You want Python code or an API reference listing |
| **Inspect** | `code_intel` | You want structural facts about the codebase itself — class lists, inheritance, method→class lookup, complexity stats — via `CodeIntelAgent` over the SQLite symbol table, not RAG |
| **Run Report** | `report` | You want current live data; also used by sidebar |
| **Act** | `command` | You want Dr.Egeria to do something (or give you the command template) |
| **Create** | `create` | You want to build a new governance plan or report spec; `CreateRouter` decides which (or asks) |
| **Troubleshoot** | `debugging` | You're diagnosing an error or unexpected behaviour |

---

## Role + Intent Combinations

| Role | Intent | Query type | Result |
|---|---|---|---|
| Developer | Auto | *"give me a python example to create a glossary"* | Runnable pyegeria code |
| Developer | Auto | *"what methods are available for governance?"* | API reference table |
| Developer | Show me | *"create a governance definition"* | Runnable pyegeria code (role override) |
| Data Steward | Auto | *"show me how to create a glossary"* | Clarification: Python or Dr.Egeria? |
| Data Steward | Act | *"show me a template for creating a glossary"* | Dr.Egeria markdown template |
| Anyone | Report | *"list all glossaries"* | MCP report result (live data) |
| Anyone | Auto | *"what is a governance zone?"* | Conceptual explanation |

---

## Code Example Guard (`_CODE_EXAMPLE_SIGNALS`)

The following keywords in a query **block the semantic report pre-check** entirely — these queries are never accidentally routed to the MCP report pipeline even if the topic (e.g. "glossary") normally scores high:

`"python"`, `"code example"`, `"code sample"`, `"write python"`, `"python code"`, `"pyegeria example"`, `"python snippet"`

---

## Troubleshooting Routing

### Query going to the report pipeline instead of ExamplesAgent?

Add "python" to your query: *"give me a **python** example for creating a glossary"*. The `_CODE_EXAMPLE_SIGNALS` guard prevents the semantic report check from running.

### Query going to ExamplesAgent when you want a report?

Click **Report** in the intent bar. The sidebar always forces `intent_override: 'report'` automatically.

### Getting a clarification response instead of code?

Set your role to **Developer** or **Data Engineer** in the **As:** selector. The role-aware routing then sends code/example signals directly to ExamplesAgent without asking.

### Getting a code example when you wanted a Dr.Egeria template?

Click **Act** in the intent bar, then include "template", "sample", or "example" in your query. Or: set role to Data Steward and ask with "show me" — you'll be offered the choice.

### Method-discovery query giving a code example instead of a reference listing?

Use one of the method-discovery phrases: *"what methods are available for…"*, *"list methods for…"*, *"what API does pyegeria have for…"*. These trigger API-reference mode in ExamplesAgent.
