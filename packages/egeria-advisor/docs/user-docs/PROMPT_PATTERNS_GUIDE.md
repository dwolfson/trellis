# Egeria Advisor — Prompt Patterns Guide

**Last Updated:** 2026-07-11

This guide gives you concrete, copy-ready prompt patterns organised by what you want to accomplish. Each pattern shows the recommended role, the recommended intent button, the query text, and the type of response you will get.

> **New: Literate Governance** — For multi-step tasks (set up a glossary *with* terms, categories, *and* steward assignments), the advisor generates a complete, reviewable Plan Document and executes it against Egeria. See [LITERATE_GOVERNANCE_GUIDE.md](LITERATE_GOVERNANCE_GUIDE.md).

---

## Quick Reference Matrix

| I want to… | Role | Intent | Sample prompt | Response type |
|---|---|---|---|---|
| Understand a concept | Anyone | Explain | "What is a governance zone?" | Explanation from docs |
| See current live data | Anyone | Report | "List available glossaries" | Live MCP report table |
| Get Python code for a task | Developer | Auto or Show me | "Give me a python example to create a governance zone" | Runnable Python script |
| Discover available API methods | Developer | Auto or Show me | "What methods are available for governance definitions?" | Class + method table |
| Get a Dr.Egeria notebook command | Data Steward | Act | "Show me a Dr.Egeria template for creating a glossary" | Markdown command template |
| Execute a single governance action | Data Steward | Act | "Create a governance zone called Finance" | Dr.Egeria command execution |
| **Plan a multi-step governance task** | **Any** | **Auto** | **"Set up a glossary for Finance with terms, categories, and steward assignments"** | **Reviewed Plan Document → execute → outcome report** |
| Diagnose an error | Developer | Troubleshoot | "Why am I getting a 403 when calling create_governance_definition?" | Diagnostic explanation |
| Compare two concepts | Anyone | Explain | "What is the difference between a glossary and a data dictionary?" | Side-by-side comparison |
| Find a CLI command | Anyone | Auto | "What hey_egeria command lists glossary terms?" | CLI command reference |

---

## Patterns by Role

### Anyone (default — no role selected)

Use this when you want general information, live data reports, or conceptual explanations and have no particular coding or governance preference.

#### Conceptual questions

```
"What is a governance zone?"
"What is the difference between a glossary term and a data field?"
"How does data lineage work in Egeria?"
"Explain the purpose of an Asset Manager OMAS"
"What is a governance domain?"
"How are governance definitions related to governance zones?"
```

**→ Response:** DocAgent — explanation drawn from `egeria_concepts`, `egeria_general`, and `egeria_types`. Grounded in indexed documentation.

---

#### Live data (reports)

Use the **Report** intent button, or phrase your query as a listing/enumeration:

```
"List available glossaries"
"What collections exist in Egeria?"
"Show me all governance zones"
"List active projects"
"What glossary terms are defined?"
"Run the Governance Zones report"
```

**→ Response:** MCP report pipeline — live data from your running Egeria instance, rendered as a markdown table.

> **Tip:** You can also click any report in the left sidebar and optionally add a filter string (e.g., `finance`) before running.

---

#### CLI commands (hey_egeria)

```
"What hey_egeria command lists all glossary terms?"
"How do I use hey_egeria to check Egeria server status?"
"Show me the CLI command for creating a project"
```

**→ Response:** CLI command lookup from the `pyegeria_cli` collection.

---

### Developer / Data Engineer

These roles trigger automatic routing to ExamplesAgent for any query that involves code, examples, methods, or API usage. You can also use the **Show me** intent button explicitly.

#### Runnable Python code examples

The system always follows the canonical pyegeria pattern: both constructor options, `create_egeria_bearer_token()`, try/except/finally.

**Creating objects:**
```
"Give me a python example to create a governance zone"
"Write python code to create a glossary called 'Finance Terms'"
"Show me python code for creating a glossary term"
"Give me a python example for creating a project"
"Write python to create a data dictionary entry"
"Python example to create a certification type"
"Give me python code to link a term to a governance definition"
```

**Reading / searching objects:**
```
"Write python code to list all glossaries"
"Give me python code to find governance zones"
"Show me how to search for data assets in pyegeria"
"Python code to get all terms in a glossary"
"Give me a python example to find all active projects"
```

**Updating / managing objects:**
```
"Show me python to update a glossary term description"
"Write python code to add a glossary term to a collection"
"Give me python to set the status of a governance definition"
```

**→ Response:** Complete, runnable Python script. Includes the correct class (e.g., `GovernanceOfficer`), the correct method (e.g., `create_governance_definition(body)`), the full body dict structure with `typeName` and property class, and inline parameter comments.

> **Important:** Egeria uses a unified API for governance definitions. `GovernanceZone`, `GovernancePrinciple`, `GovernanceObligation`, etc. are all created with `GovernanceOfficer.create_governance_definition(body)` — the type is set via `"typeName": "GovernanceZone"` in the body. The generated example will reflect this correctly.

---

#### API reference / method discovery

When you know the topic but not the class or method names:

```
"What methods are available for governance definitions?"
"Which pyegeria class handles glossary management?"
"What API does pyegeria have for projects?"
"List methods for the GovernanceOfficer class"
"What pyegeria methods can I use with collections?"
"What functions are available for creating terms?"
"Which class do I use for data assets?"
"What operations are available for governance zones?"
"What can I do with GovernanceOfficer?"
"API reference for DataDesigner"
```

**→ Response:** Structured markdown table showing class name, import path, method names, signatures, and one-line descriptions from the docstrings. Only real, indexed methods are listed — no invented names.

---

#### Connection and setup

```
"Show me how to connect to Egeria using pyegeria"
"Give me python to authenticate with Egeria"
"What are the constructor options for GlossaryManager?"
"How do I create an Egeria client with environment variables?"
"Show me a zero-argument constructor example for GovernanceOfficer"
```

**→ Response:** Code showing both constructor forms — explicit parameters (with env var names documented as comments) and the zero-arg form that reads from `.env`.

---

#### Understanding an API you already have

Use **Show me** + the class/method name:

```
"Show me how to use create_governance_definition"
"What parameters does find_governance_definitions take?"
"Give me an example of calling link_term_to_governance_definition"
"Show me a python example using the GlossaryManager class"
```

---

### Data Steward / Governance Officer

These roles treat "show me" or "example" queries as ambiguous — the advisor asks whether you want Python code or a Dr.Egeria notebook template. Select the intent button to avoid the clarification step.

#### Dr.Egeria notebook templates (use **Act** intent)

Dr.Egeria templates are markdown commands you paste into a Jupyter cell in Egeria Workspaces. They cover all create/update/link operations and include all required and optional fields.

```
"Show me a Dr.Egeria template for creating a glossary"
"Give me the Dr.Egeria command for creating a governance zone"
"Dr.Egeria template for linking a term to a category"
"Show me the Act command for creating a project"
"Give me a Dr.Egeria sample for setting governance zone membership"
"What is the template for creating a certification type?"
"Show me a Dr.Egeria command for creating a business imperative"
```

**→ Response:** The pre-generated `.md` template from your workspace's `Templates/Dr-Egeria-Templates/basic/` directory, in a fenced markdown block, with a brief explanation of required vs optional fields.

> **Tip:** Add "advanced" to your query to get the full attribute set:
> `"Show me the advanced Dr.Egeria template for creating a governance zone"`

---

#### Live data (reports)

```
"What governance zones are defined?"
"List all glossaries"
"Show me active projects"
"What governance definitions exist?"
"List all collections in Egeria"
```

**→ Response:** Live data from your Egeria instance via the MCP report pipeline.

---

#### Concept explanations

```
"Explain what a governance zone is and when to use one"
"What is the difference between a governance principle and a governance obligation?"
"How do I decide which governance domain to assign to a definition?"
"What metadata should I include when creating a glossary term?"
"Explain the relationship between glossary terms and data fields"
```

**→ Response:** DocAgent — conceptual explanation from indexed Egeria documentation.

---

#### Taking action (executing Dr.Egeria commands)

When you want the advisor to compose and execute a Dr.Egeria command against your Egeria instance:

```
"Create a governance zone called 'Finance Data'"
"Create a glossary called 'Corporate Terminology'"
"Link the term 'Customer ID' to the 'Data Privacy' governance principle"
"Set the governance zone for the Finance glossary to 'Finance Data'"
"Create a project called 'Data Quality Initiative' in domain 1"
```

**→ Response:** DrEgeriaActionAgent composes the pyegeria command and executes it via MCP. Returns the result (GUID or confirmation) plus the command that was run.

> **Tip:** Use `/dry-run` in the CLI interactive mode to preview the command without executing it.

---

## Patterns by What You Want to Know

### "What is X?" — Conceptual understanding

| Query | Best intent | Response |
|---|---|---|
| "What is a governance zone?" | Explain | Concept definition + context |
| "What does the GovernanceOfficer class do?" | Explain or Show me | Class purpose + key methods |
| "What is a qualified name in Egeria?" | Explain | Definition + usage guidance |
| "What is the difference between a glossary and a data dictionary?" | Explain | Side-by-side comparison |
| "What is a business imperative?" | Explain | Concept explanation |

---

### "How do I do X programmatically?" — Python code

| Query | Best intent | Response |
|---|---|---|
| "How do I create a governance zone in python?" | Show me (Developer) | Runnable code using `GovernanceOfficer.create_governance_definition` |
| "How do I authenticate with Egeria?" | Show me | Constructor + `create_egeria_bearer_token()` example |
| "How do I list all glossary terms?" | Show me | Code using `GlossaryManager.find_glossary_terms()` or similar |
| "How do I handle errors from pyegeria?" | Show me | try/except `PyegeriaException` pattern |
| "How do I use environment variables with pyegeria?" | Show me | Zero-arg constructor example reading from `.env` |

---

### "What API / methods exist for X?" — API discovery

| Query | Best intent | Response |
|---|---|---|
| "What methods are available for governance definitions?" | Show me (Developer) | GovernanceOfficer class + method table |
| "What pyegeria class handles glossary management?" | Show me | GlossaryManager class details |
| "What API does pyegeria have for data assets?" | Show me | AssetConsumer / AssetManager class table |
| "Which class do I use to manage projects?" | Show me | ProjectManager class details |
| "What operations can I do with collections?" | Show me | Collection management class + methods |

---

### "Show me the current state of X" — Live data

| Query | Best intent | Response |
|---|---|---|
| "List available glossaries" | Report | Table of glossaries from Egeria |
| "What governance zones exist?" | Report | Table of active governance zones |
| "Show me all active projects" | Report | Table of projects |
| "What collections are defined?" | Report | Table of collections |
| "List governance definitions" | Report | Table of definitions |

---

### "How do I do X in Dr.Egeria?" — Notebook templates

| Query | Best intent | Response |
|---|---|---|
| "Give me a Dr.Egeria template to create a glossary" | Act (Data Steward) | Markdown template with fields |
| "What is the Dr.Egeria command to create a governance zone?" | Act | Markdown template |
| "Show me how to link a term in Dr.Egeria" | Act | Link term template |
| "Dr.Egeria sample for creating a project" | Act | Project creation template |
| "What fields do I need to create a glossary term in Dr.Egeria?" | Act | Template showing required/optional fields |

---

## Multi-Turn Conversation Patterns

The web UI and CLI interactive mode maintain context across turns. Useful patterns:

### Exploring an API then getting an example

```
Turn 1: "What methods are available for governance definitions?"
        → API reference table showing GovernanceOfficer and its methods

Turn 2: "Give me a python example using create_governance_definition for a governance zone"
        → Runnable code using the method discovered in Turn 1

Turn 3: "How do I find all governance zones I've created?"
        → Code example for find_governance_definitions with GovernanceZone subtype filter
```

---

### Going from concept to action

```
Turn 1: "What is a governance zone and when should I create one?"
        → Conceptual explanation (DocAgent)

Turn 2: "What information do I need to define one?"
        → Explanation of required fields (displayName, domainIdentifier, etc.)

Turn 3 (Data Steward): "Show me the Dr.Egeria template to create one"
        → Dr.Egeria markdown template (DrEgeriaTemplateAgent)

  — or —

Turn 3 (Developer): "Give me python to create a governance zone called 'Finance Data'"
        → Runnable Python script (ExamplesAgent)
```

---

### Discovering then writing code

```
Turn 1: "Which pyegeria class do I use for glossary management?"
        → API reference: GlossaryManager class and methods

Turn 2: "Show me the constructor for GlossaryManager"
        → Code example with both constructor forms

Turn 3: "Write python to create a glossary called 'Finance Terminology' in domain 1"
        → Complete runnable script
```

---

## Common Mistakes and How to Avoid Them

### Getting a report when you wanted code

The word "list" or "show" in a query can trigger the report pipeline if the topic also matches a report spec.

**Fix:** Add "python" or "code example" to your query, or use the **Show me** intent button.

```
❌ "Show me all glossaries"       → may run a report
✅ "Give me python to list all glossaries"  → code example
✅ "Show me all glossaries" + Show me intent → code example
```

---

### Getting code when you wanted a report

**Fix:** Click the **Report** intent button, or click the report in the left sidebar.

```
❌ "List glossaries" (Developer role, Auto)  → may route to ExamplesAgent
✅ "List glossaries" + Report intent          → live data report
✅ Click "Glossary Terms" in sidebar          → live data report
```

---

### Getting a clarification instead of a direct answer (Data Steward role)

"Show me how to create a glossary" with Data Steward role and Auto intent returns a clarification asking whether you want Python or Dr.Egeria.

**Fix:** Set intent explicitly.

```
Wants Python code:       use Show me intent
Wants Dr.Egeria template: use Act intent
Wants current data:      use Report intent
```

---

### Getting hallucinated method names

If the generated code uses methods like `create_governance_zone()` that don't exist, the system was unable to find the correct method in its index.

**Fix:** Be more specific — include the class name or the operation.

```
❌ "Python code to create a governance zone"
✅ "Python code to create a governance zone using GovernanceOfficer"
✅ "Python example for GovernanceOfficer create_governance_definition with GovernanceZoneProperties"
```

---

## Intent Button Quick Reference

The buttons in the current Web UI read **Auto / Explain / Show me / Inspect / Run Report /
Act / Create / Troubleshoot**. Elsewhere in this guide, "Report intent" and "the Report
button" refer to what's now labelled **Run Report**, and "Plan"/planning patterns use the
**Create** button — the underlying behaviour described in each example is unchanged, only the
button labels moved.

| Button | When to use |
|---|---|
| **Auto** | Default. Works well when your query is clear and your role is set |
| **Explain** | Force a conceptual explanation — bypasses code routing even for Developer role |
| **Show me** | Force ExamplesAgent — use when Auto keeps returning a report or explanation |
| **Inspect** | Ask about the codebase's own structure (classes, inheritance, method locations, complexity) — answered via SQL over a symbol table, not RAG |
| **Run Report** | Force live data from MCP — use when Auto keeps returning code or docs |
| **Act** | Force Dr.Egeria — use when you want a template or to execute a command |
| **Create** | Build a new governance plan or report spec — `CreateRouter` decides which, or asks |
| **Troubleshoot** | Force diagnostic mode — describe the error or unexpected behaviour |

### Inspect examples

```
"How many classes are in pyegeria?"
"List methods on AssetManager"
"Does GlossaryManager inherit from Client?"
"What are the most complex methods in egeria_java?"
```

**→ Response:** `CodeIntelAgent` — structured answer from a live SQL query over the code
symbol table populated at ingest time. No LLM call, no hallucination risk.
