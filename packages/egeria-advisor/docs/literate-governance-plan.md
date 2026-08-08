# Literate Governance with Context Intelligence — Plan Proposal

> **Status:** v5 — Incorporates: routing defect analysis, negative routing guard, plan editor mode (direct command builder), command keyword index, action catalog gap analysis, Phase 11b completions (transcript viewer, Egeria context enrichment, partial execution detection, governance zone valid values).
>
> **Note (2026-07-11):** The core vision, design philosophy, and workflow described below are
> still accurate and haven't changed. This design narrative predates several later phases
> that extended the implementation without changing the underlying design principles —
> report spec builder & parameter model (Phase 12), composite Examples Agent (Phase 12b),
> and Plan Templates sidebar + natural-language reorder/relationship editing (Phase 13). See
> `docs/PROJECT_SUMMARY.md` for those phases' details, and
> `docs/design/RELATIONSHIP_LINKING_SCOPE.md` for the relationship-editing design that
> extends section 5 (Plan Canvas) below.
>
> **What this is:** A design and phased implementation plan for a major new Egeria Advisor capability. The goal is to allow a user to describe a data management task in plain language, receive a complete, executable, and reviewable plan document, iterate on it conversationally and/or directly, execute it against Egeria, and receive a verified outcome report.

---

## 1. Vision

A user should be able to describe what they want to accomplish — including their perspective, role, and purpose — and receive back a complete, structured plan document. The system will generate a reasonable first draft immediately, then support iterative refinement through conversation and direct editing, side by side.

Example starting point:

> *"As a data steward for the Finance division, I want to set up a glossary for the finance domain with standard terms, categories, and data steward assignments"*

The resulting document is both **human-readable** (structured narrative with rationale and context) and **machine-executable** (Dr.Egeria markdown command blocks). After execution, the document is extended with a verified outcome section — creating an auditable record of the work done.

---

## 2. Design Philosophy

These principles emerged from reviewing real-world deployment experience with conversational systems and dialogue research.

### 2.1 Generate first, refine second

Users consistently prefer reacting to a proposal over answering questions before seeing anything. Systems that interrogate users before generating anything have poor completion rates and low satisfaction. The right pattern:

1. Generate a reasonable draft from minimal input
2. Show it immediately — gaps marked as placeholders
3. Let the user point at what's wrong or missing
4. Ask at most one focused question per turn when genuinely blocked

This is the pattern used by GitHub Copilot, Cursor, v0.dev, and Claude Artifacts — all of which achieve high user satisfaction precisely because they show something concrete to react to.

### 2.2 The three-question threshold

Research on task-oriented dialogue (Walker PARADISE framework; commercial data from Intercom, Typeform) consistently identifies three to four sequential questions as the point at which users abandon or disengage. A multi-step interrogation before generating anything violates this threshold badly. Slot-filling dialogue works for narrow, bounded tasks (flight booking, timer setting) but fails for open-ended planning tasks where users don't know what information they need to provide.

### 2.3 Mixed initiative

Horvitz (1999) established that users prefer systems where they can volunteer information and take initiative, not just answer questions. System-driven slot-filling feels like being cross-examined. The plan flow must allow the user to skip questions, redirect the conversation, add detail in any order, and refine either conversationally or by direct editing.

### 2.4 Conversation handles structure; canvas handles detail

These are different cognitive modes. Structural changes ("add a sub-project for data quality", "move the design phase earlier", "remove the governance zone") are natural in conversation. Field-level detail (descriptions, dates, owners, zone assignments) is better handled by clicking a field in a visible artifact. Neither should force the user into the other mode.

---

## 3. Workflow

The flow is **non-linear and re-entrant**. Users can exit and return at any point, jump back to an earlier step to change direction, add context after seeing the draft, or return from the editor to conversation. The numbered sequence below shows the natural progression, not a required order.

```
1. DESCRIBE    User states intent, perspective, role, and purpose
      ↕  (can return here at any time to change direction)
2. GENERATE    System builds IntentModel → derives commands → generates first draft
               (shown immediately in the Plan Canvas alongside the chat)
      ↕  (can return to DESCRIBE, or stay here iterating)
3. REFINE      User iterates: conversationally or by direct canvas editing
               (add/remove/reorder commands; fill in fields; both views stay in sync)
               Can jump back to step 1 or 2 at any time
      ↓
4. DOCUMENT    User requests full Plan Document (narrative + commands + rationale)
      ↓
5. EXECUTE     User approves; system runs the document via Dr.Egeria MCP
      ↓
6. REPORT      System verifies results via report_specs, appends outcome section
      ↓
7. STORE       Final document (plan + outcome) saved to user's folder
      ↓
8. TRACK       Usage and outcome data captured for insight and improvement
```

**Step 2** generates immediately from whatever is known. Gaps are shown as placeholders in the canvas, not as blocking questions. The user sees the shape of the plan before any elicitation occurs.

**Step 3** is the primary interaction. The user works in the canvas (direct editing) and/or the chat (conversational refinement) — both views are always live and in sync. There is no mode switch. At any point the user can say "I want to start over" or "let me rethink the goal" and return to step 1.

---

## 4. The IntentModel

Before mapping to Dr.Egeria commands, the system builds an **IntentModel** — a structured representation of what the user wants to achieve, expressed in domain terms rather than tool terms. This is an internal representation; users never see it directly.

```json
{
  "goal": "Set up a campaign to consolidate sales forecasting",
  "entities": {
    "campaign": {
      "name": "Sales Forecast Consolidation",
      "purpose": null,
      "leader": "Tom Tally",
      "sub_projects": [
        "Survey of Existing Systems",
        "Requirements Refinement",
        "Design Proposal"
      ]
    }
  },
  "roles": [
    {"type": "Project Leader", "holder": "Tom Tally", "scope": "campaign"}
  ],
  "open_slots": ["campaign.purpose", "campaign.start_date"]
}
```

The IntentModel serves three purposes:

1. **Better generation** — commands are derived from a structured semantic model, not extracted directly from natural language, reducing hallucination of unmentioned objects
2. **Context for additions** — when the user adds something ("also add a sub-project for design"), the system knows the parent entity name and pre-fills it
3. **Refinement tracking** — the model captures what's known, what's been asked, and what's still open, without driving a sequential Q&A

### 4.1 Grounding in Dr.Egeria templates

The slot vocabulary for each entity type — what properties it has, which are required, what relationships it supports — is derived from the **Dr.Egeria templates**, not directly from the full Egeria type system. The templates define what is currently implementable. Egeria has over 600 entity types; Dr.Egeria currently provides **~126 unique commands** across **12 command families** (253 template files in basic/advanced pairs):

| Family | Unique commands | Notes |
|---|---|---|
| Governance Officer | ~37 | Largest family: zones, policies, controls, regulations, risks, metrics |
| Collections | 15 | Folders, folios, subject areas, security groups |
| Data Designer | 15 | Data specs, structures, fields, data classes |
| Solution Architect | 13 | Blueprints, components, supply chains |
| Digital Product Manager | 11 | Products, catalogs, agreements, subscriptions |
| External Reference | 9 | Documents, media, source references |
| Feedback | 9 | Comments, tags, ratings, likes |
| Projects | 7 | Campaigns, projects, tasks, dependencies |
| Glossary | 5 | Glossaries, terms, term relationships |
| Report | 1 | Report runner |

The **action catalog** (`config/dr_egeria_actions.yaml`) currently covers **42 of these ~126 commands** — those most commonly used in conversational planning. The remaining ~84 are available as template files and are fully usable in the Plan Editor (direct builder) mode, but are not yet wired into the conversational decomposition flow. Expanding the action catalog to cover all 126 commands is a medium-term priority (see Phase 4).

As Dr.Egeria's template coverage grows, the IntentModel vocabulary grows with it. The `egeria_types` vector collection is a useful secondary reference for understanding the full type semantics, but the templates are the authoritative source for what the system can actually execute.

### 4.2 Command derivation and ordering

Given a populated (or partially populated) IntentModel, commands are derived using a rule set. The ordering is not arbitrary — **Dr.Egeria uses internal placeholder references** so that later commands can refer to objects created earlier in the same document. For example:

- Create Campaign in step 1 → Dr.Egeria generates an internal qualified name for it
- Create Project (sub-project) in step 4 → references the campaign by its display name; Dr.Egeria resolves this to the qualified name created in step 1
- Link Person Role Appointment in step 8 → references the role and the project by name

This means the command sequence must be a valid topological ordering of the dependency graph. Rules:

- Each entity → one or more `Create` commands
- Sub-project entities → `Create Project` with `Parent ID` and `Parent Relationship Type Name = ProjectHierarchy` baked in (single command; no separate Link step needed)
- Named role holders → `Create Person Role` + `Link Person Role Appointment`, in that order
- Required containers created before their contents (Glossary before GlossaryTerm; Campaign before its sub-Projects)
- `Link` and `Classify` commands always follow their referenced `Create` commands

The derivation is **deterministic given the IntentModel** — the LLM's job is building the model, not producing the command ordering.

---

## 5. The Plan Canvas

The Plan Canvas replaces the current full-screen Plan Editor modal. It is a **persistent side panel** — always visible alongside the chat when a plan draft is active. Both views are live and in sync; neither is the "main" interface.

### 5.1 Layout

**Option A — Even split with draggable divider** *(selected)*

A 50/50 default split with a draggable resize handle so the user can allocate more space to whichever panel they are working in. This gives equal weight to both views and lets the user adapt the layout to the current task.

```
┌─────────────────────────╫──────────────────────────────────┐
│  Chat                   ║  Plan Canvas                     │
│                         ║                                  │
│  You: "Add a sub-       ║  Sales Forecast Consolidation    │
│  project for design"    ║  ─────────────────────────────   │
│                         ║                                  │
│  Added. Pre-filled      ║  ≡  Create Campaign          ✕  │
│  parent as Sales        ║     Sales Forecast Consolidation │
│  Forecast.              ║     ─────────────────────────    │
│                         ║     [narrative: rationale text]  │
│  Anything else to       ║                                  │
│  add or change?         ║  ≡  Create Project           ✕  │
│                         ║     Survey of Existing Systems   │
│                         ║     ✓ Parent: Sales Forecast     │
│                         ║     ─────────────────────────    │
│                         ║     [narrative: optional text]   │
│                         ║                                  │
│                         ║  ≡  Create Project  ← NEW    ✕  │
│                         ║     Design Proposal              │
│                         ║     ✓ Parent: Sales Forecast     │
│                         ║                                  │
│  [input]                ║  [+ Add step]                    │
│                         ║  [Generate Plan]  [Execute]      │
└─────────────────────────╫──────────────────────────────────┘
                          ↕ drag to resize
```

Other layouts (canvas-primary 30/70, collapsible drawer) are not precluded — the draggable handle provides those naturally.

### 5.2 Canvas card behaviour

Each command card supports:

- **Drag handle (≡)** — reorder by dragging
- **↑ / ↓ arrows** — reorder via keyboard/click
- **Remove (✕)** — removes the command (with undo)
- **Expand** — inline field editing without leaving the canvas
- **Narrative text area** — freeform markdown text that can appear above or below the command fields (see 5.3)
- **Status indicator** — green check when required fields complete; amber dot when fields missing; grey when optional only
- **[+ Add step]** — inserts a new command card below (opens a command picker filtered to relevant families)

Field editing within an expanded card is the primary way to add detail. The chat handles structural changes (add, remove, reorder, change type).

### 5.3 Narrative text per command

Each command card has an optional narrative text area — editable freeform markdown that appears in the generated Plan Document above or below the command block. This serves several purposes:

- **System-generated rationale** — when a command is added (by chat or by canvas), the system generates a brief explanation of why this step is needed and what it creates. This becomes the "annotation" in the final document.
- **User instructions** — the user can add notes for whoever will review or execute the plan, e.g. *"Check with the Finance team before executing this step."*
- **TODO notes** — for steps where required fields are missing, the system can generate placeholder text: *"TODO: Confirm the project leader with the Finance governance team."*

All generated narrative text is fully editable and deletable by the user. Nothing is locked.

In the generated Plan Document, this narrative appears as the comment block above each Dr.Egeria command block (the `<!-- Step N: ... -->` annotations).

---

## 6. The Plan Document

> **Naming note:** "Governance" carries negative connotations in some organisations. The document and feature will use neutral language — "Plan Document" or "Data Management Plan" — and avoid "governance" where possible in user-facing text. The internal code name remains LGCI.

The Plan Document is the central artifact. It is a single markdown file with the following sections:

### 6.1 Header

```markdown
# Data Management Plan: <task title>
**Created:** <date>        **Last edited:** <date and time>
**Status:** Draft | Approved | Executed
**Created by:** <user>     **Perspective:** <role>
**Purpose:** <stated purpose>
```

The header captures who created the plan, when it was last modified, and the perspective and purpose — all important context for reviewers and executors who may encounter the document later.

### 6.2 Goal and Requirements

```markdown
## Goal
<one-paragraph statement of what this plan achieves and why>

## Requirements
- <requirement 1>
- <requirement 2>
```

### 6.3 Approach

Ordered summary of which Dr.Egeria command families are used and in what sequence, with a brief rationale for each step and an explanation of the dependency ordering.

### 6.4 Command Sequence

The actual Dr.Egeria markdown commands, pre-filled and ready to execute. Each command block is preceded by its narrative annotation (rationale, instructions, TODOs) which is editable in the canvas.

### 6.5 Outcome (added post-execution)

```markdown
## Outcome
**Executed:** <date>   **Status:** Success | Partial | Failed

### Summary
<LLM-generated narrative>

### Verification Reports
<embedded report output>
```

---

## 7. Plan Templates

Users can save any completed plan as a reusable **Plan Template** — the plan structure with specific values replaced by `{{placeholder}}` tokens. Starting a new plan from a template skips intent decomposition and goes directly to filling in the placeholder fields.

This is already implemented via `PlanTemplateManager` (`advisor/plan_templates.py`). Templates are stored in `~/egeria-plans/plan_templates/` and are available from the Plans sidebar.

Common use cases:
- A team repeatedly sets up glossaries with the same structure — save as "Standard Glossary Setup"
- A governance programme has a standard project structure — save as "Governance Project Template"
- A data steward runs a quarterly data quality campaign — save as "Data Quality Campaign"

---

## 8. The Artifact Canvas Pattern

The Plan Canvas is an instance of a more general interaction pattern applicable across Egeria Advisor wherever a structured artifact is being created or refined.

**The pattern applies when:**
- An interaction produces a structured artifact (plan, report spec, query result, metadata record)
- The artifact benefits from iterative refinement
- The artifact has both high-level structure and field-level detail
- Users may approach from either the conversational or the direct-editing end

### 8.1 Candidate applications

| Context | Artifact | Canvas content | Chat role |
| --- | --- | --- | --- |
| **Plan creation** | Plan Document | Command cards (ordered) with narrative and fields | Add/remove/reorder commands; structural changes |
| **Report Spec design** | Report Spec (question_spec) | Spec fields: name, query pattern, collections, perspective filter | Define the report in plain language; system proposes a spec; user refines |
| **Report execution** | Report results | Live tabular/graph output, filterable | "Show only Finance zone", "add a column for steward", follow-up questions |
| **Dr.Egeria command composition** | Single command block | Field cards for one command | "Set the zone to Finance", "what does this field mean?" |
| **Collection building** | Collection membership | Member list with metadata | "Add all assets tagged Finance", "remove anything without a steward" |
| **Governance Zone design** | Zone definition + governed assets | Zone properties + asset list | "Which assets should be in this zone?" |

### 8.2 Common component

These are all instances of the same `ArtifactCanvas` component:

```
ArtifactCanvas
  ├── artifact_type          (plan | report_spec | report_result | command | ...)
  ├── items[]                (cards or rows — the editable units)
  │     ├── type             (action name, field name, ...)
  │     ├── fields{}         (key-value, typed)
  │     ├── narrative        (freeform markdown, editable, generated or user-written)
  │     ├── status           (complete | incomplete | error)
  │     └── actions          (reorder, remove, expand, ...)
  ├── toolbar                (Add, Generate/Run, Save, Execute)
  └── sync_endpoint          (which API endpoint to write changes to)
```

The chat panel's response handler checks whether an `artifact_type` and `items` delta are present in the API response and applies them to the canvas directly — without requiring a full page refresh.

### 8.3 Report Spec design flow

*(To be specified in detail — Phase 3)*

Outline:
1. User describes a desired report in plain language
2. System proposes a draft ReportSpec in the canvas
3. User refines via chat or direct editing
4. [Run Preview] shows live results below the spec
5. User saves → spec added to report catalog

---

## 9. System Components

### 9.1 GovernancePlanAgent  `advisor/agents/governance_plan_agent.py`

Orchestrates the plan generation lifecycle:

1. **Intent capture** — extracts entities and roles from the user description (see *Two-stage extraction* below); bounded by the Dr.Egeria template vocabulary
2. **Command derivation** — `_entities_to_commands()` deterministically maps extracted entities → ordered command list with pre-filled params (Parent ID for sub-projects, role/person for appointments)
3. **Validation** — `validate_commands()` (post-processing pass) corrects structural errors
4. **Narrative generation** — LLM writes Goal, Requirements, Approach sections, and per-command rationale annotations
5. **Document composition** — assembles full Plan Document markdown

#### Two-stage extraction (`_decompose_intent`)

The intent-capture step deliberately keeps the LLM away from command structure. Local 8B models hallucinate when asked to emit Dr.Egeria command JSON directly — they copy values out of the format examples (e.g. emitting a project literally named "Analysis") and repeat commands. The two-stage design solves this:

- **Stage 1 — entity extraction.** First a **pattern-based** extractor (`_extract_entities_patterns`) handles common phrasings with regexes — *"called X"*, *"a campaign for X"*, *"led by X as Y"*, *"sub-projects for A and B"*. It needs no LLM and is instant and deterministic. Only when patterns don't match does it fall back to an **LLM extractor** (`_extract_entities_llm`) with a simple prompt that asks for entity names and roles — never command names.
- **Stage 2 — deterministic command mapping.** `_entities_to_commands()` maps each extracted entity type to its Dr.Egeria action via the `_ENTITY_TO_ACTION` table, sets Parent ID on sub-projects by construction, and always expands a named role holder into `Create Person Role` + `Link Person Role Appointment`.

The LLM's job is *understanding intent and extracting names*; it never decides command structure. New phrasings are added to the pattern library; new object types to the action catalog. This is where the system "learns" without fine-tuning.

#### Model routing

Planning code calls `get_planning_llm()` (not `get_ollama_client()`), which returns a client pinned to the `llm.models.planning` model — **`qwen2.5-coder:32b`** — for narrative generation, change application, answer parsing, and the LLM extraction fallback. The high-volume RAG Q&A path stays on the faster `llama3.1:8b`. See design decisions Q15–Q16.

### 9.2 PlanElicitor  `advisor/agents/plan_elicitor.py`

Drives the multi-turn planning flow. Phases:

| Phase | Description |
| --- | --- |
| `confirm_commands` | Shows derived command set in canvas; user confirms, adds, or removes |
| `elicit_required` | Asks about genuinely blocking missing fields (max 1–2 per turn) |
| `generate` | Composes and saves the Plan Document |
| `refine` | NL-driven iterative changes; applied to both canvas and document |
| `template_offer` | Offers to save the result as a reusable template |
| `done` | Terminal |

All phases are re-entrant. The user can jump back to `confirm_commands` from `refine`, return to conversation from the editor, or restart entirely without losing previously entered values.

### 9.3 DraftManager  `advisor/governance_draft.py`

Persists planning session state (IntentModel + commands + answers + history stack) as JSON in `~/egeria-plans/drafts/`. Supports Back navigation via history stack. Draft state survives page refresh via `sessionStorage`.

### 9.4 PlanTemplateManager  `advisor/plan_templates.py`

Saves completed plans as reusable templates with `{{placeholder}}` tokens. Lists templates in sidebar. Starting from a template skips intent decomposition.

### 9.5 DocumentManager  `advisor/governance_docs.py`

Manages the lifecycle of completed Plan Documents.

```
{docs_root}/
  inbox/           — plans awaiting review or execution
  outbox/          — executed plans with outcome sections
  archived/        — superseded or cancelled plans
  drafts/          — in-progress planning sessions (DraftManager)
  plan_templates/  — reusable plan templates (PlanTemplateManager)
  sessions/        — full conversation transcripts (SessionLogger)
  versions/        — automatic backups before each plan edit
```

### 9.6 ActionCatalog  `advisor/action_catalog.py` + `config/dr_egeria_actions.yaml`

The authoritative, structured definition of the Dr.Egeria actions the planner understands. Each entry carries: family, intent entity type, natural-language aliases, ordering priority, `requires`/`required_before` dependencies, `container_for`, `supersedes` rules, and a narrative template. Drives command derivation, the post-processing validator, and narrative pre-population. Extended as Dr.Egeria's template coverage grows — *not* embedded in LLM prompts.

**Current state:** 42 catalog entries cover the most common commands used in conversational planning. Dr.Egeria provides ~126 unique commands total (253 template files in basic/advanced pairs across 12 families). The ~84 uncatalogued commands are available for direct use in Plan Editor mode. Expanding catalog coverage to all 126 commands is a Phase 4 priority.

#### Command keyword index *(planned)*

The action catalog aliases support intent matching for commands the catalog knows about. For Plan Editor mode and for routing, a broader **command keyword index** is needed — covering all ~126 template names and their natural-language synonyms (e.g. "blueprint" → "Create Solution Blueprint", "component" → "Create Solution Component"). This index is built from:

1. Template file names (canonical command names, underscore-decoded)
2. Catalog aliases (where the command is already catalogued)
3. LLM-expanded synonyms (offline expansion, written back to config)

The keyword index replaces the current `"Create Project"` fallback for unknown entity types and enables confidence-gated clarification ("did you mean Solution Blueprint?").

### 9.7 Plan validator  `advisor/plan_validator.py`

`validate_commands()` applies deterministic post-processing rules after every decomposition (and after canvas additions), in order:

- **Deduplicate** — drop identical action+display_name commands; strip person/role fields that don't belong on `Create Project`
- **Remove superseded** — `Link Project Hierarchy` → `Create Project` with Parent ID
- **Clear self-referential / orphaned Parent IDs** — a top-level project must not parent itself
- **Ensure containers** — insert a missing `Create Glossary` before `Create Glossary Term`, etc.
- **Role before appointment** — `Create Person Role` precedes `Link Person Role Appointment`
- **Topological sort** — by catalog ordering priority

Corrections are surfaced to the user in the `confirm_commands` note ("Auto-corrected: …").

### 9.8 SessionLogger  `advisor/session_logger.py`

Append-only JSONL transcript per planning session (`~/egeria-plans/sessions/{draft_id}.jsonl`). Captures every user turn, system response, phase, perspective, user identity, and a terminal summary with outcome and command families. Exposed via `GET /api/sessions` and `GET /api/sessions/{id}` for review and learning (Section 13).

### 9.9 Plan Canvas  `advisor/web/static/plan_canvas.js` + `artifact_canvas.js`

`ArtifactCanvas` is the generic split-view canvas base; `PlanCanvas` is a thin adapter over it. Supports:
- Persistent side panel alongside chat (Option A, draggable `ew-resize` divider)
- Live sync with draft spec via `/api/drafts/{id}` + `PATCH /api/drafts/{id}/commands`
- Drag-to-reorder; add / remove commands
- Inline field editing (expand card) with Basic/Advanced toggle and scrollable field list
- Per-card narrative text (generated and user-editable)
- Status indicators (complete / incomplete / placeholder)
- Generate Plan and Execute toolbar buttons

### 9.10 Plan Editor Mode *(planned — Phase 4)*

A **direct command builder** that bypasses conversational planning entirely. Designed for users who know the Dr.Egeria command vocabulary and want precise control over the plan they are building. The conversational flow (GovernancePlanAgent) and the editor share the same Plan Canvas and the same draft persistence — they are two entry points into the same artifact.

**User flow:**
1. User opens "New Plan (Builder)" from the sidebar → blank Plan Canvas opens with a title prompt; no decomposition occurs
2. User searches/filters the full Dr.Egeria command catalog (~126 commands across 12 families) in a **command picker modal**
3. Selecting a command adds it as a card to the canvas; field editing works exactly as in the conversational path
4. User reorders, fills fields, adds narrative; chat panel is available alongside for help ("what does this field mean?", "what order should I add these?")
5. When complete, user clicks Generate Plan → assembles the Plan Document; Execute works as normal

**Chat role in editor mode:** When a draft is open in editor mode, chat queries that look like informational requests (`what does X mean?`, `in what order should I...?`, `explain field Y`) route to DocAgent or ExamplesAgent — *not* back to GovernancePlanAgent. The chat becomes a contextual help assistant rather than a plan generator. This distinction is controlled by a `builder_mode` flag on the draft that suppresses intent=Plan routing when set.

**Command picker modal:**
- Search input filtering against command names, aliases, and family labels
- Family filter tabs (Projects, Glossary, Governance Officer, Collections, etc.)
- Action cards showing: command name, family, brief description, required fields
- "Add to plan" button per command
- Powered by `GET /api/actions` endpoint returning catalog grouped by family, extended with uncatalogued template names from the template filesystem

**Relationship to conversational mode:** Conversational plans can be opened in the editor (they land in the canvas anyway). Editor plans can switch to conversational refinement ("describe a change in chat"). The two modes are the same canvas with a different entry point, not separate tools.

### 9.11 ExecutionOrchestrator  *(Phase 2 — complete)*

Submits the approved Plan Document's command sequence to Dr.Egeria via `dr_egeria_run_block`. Execution is whole-document — Dr.Egeria processes entire markdown files and commands reference objects created earlier in the same file by display name, resolved via internal placeholder mechanism.

### 9.12 OutcomeReporter  `advisor/agents/outcome_reporter.py` *(Phase 2 — complete)*

After execution: maps command families to relevant `report_specs`, runs verification reports, synthesises a narrative summary, appends outcome section to the Plan Document.

---

## 10. Phased Implementation Plan

### Phase 1 — Canvas + conversational plan generation  *(complete)*

**Deliverable:** User can describe a task, see a live Plan Canvas alongside the chat, refine conversationally or by direct editing (including add/reorder/remove commands and per-card narrative), and generate a full Plan Document.

- [x] `GovernancePlanAgent` — intent decomposition → template selection → ordering → param extraction → document composition
- [x] `PlanElicitor` — multi-phase flow with history (Back), save & exit, cancel, discard, resume; `confirm_commands` as entry phase
- [x] `DraftManager` — create/load/update/list drafts in `~/egeria-plans/drafts/`
- [x] `DocumentManager` — create/load/update/list plans in inbox/outbox
- [x] `PlanTemplateManager` — save/load/list plan templates with `{{placeholder}}` tokens
- [x] `config/advisor.yaml` — `governance_plans` paths (inbox, outbox, archived, drafts, plan_templates)
- [x] Web UI: `confirm_commands` phase with Back/Save&Exit/Cancel navigation buttons
- [x] Web UI: Active Drafts sidebar section with resume/discard
- [x] Web UI: `_activeDraftId` persisted to `sessionStorage`; `discuss_changes` button in editor
- [x] API: `/api/drafts`, `/api/plan-templates` endpoints; `draft_id` in plan listing
- [x] **Plan Canvas** — persistent side panel (Option A, draggable divider); drag-reorder; add/remove commands; per-card narrative text area; Basic/Advanced field toggle; scrollable expanded fields
- [x] **Action catalog** (`config/dr_egeria_actions.yaml` + `advisor/action_catalog.py`) — 42 actions with aliases, ordering priority, supersedes, requires, narrative templates
- [x] **Post-processing validation** (`advisor/plan_validator.py`) — Link Project Hierarchy conversion, missing container insertion, role ordering, topological sort
- [x] **Per-command narrative** — LLM generates narrative per command; falls back to catalog template; user-editable in canvas; written to Plan Document comment blocks
- [x] Layout: split-view with draggable ew-resize divider; canvas shown/hidden with draft lifecycle
- [x] Header: last-edited timestamp and Created by (OS user) in Plan Document
- [ ] **IntentModel** — replace direct LLM→commands with LLM→IntentModel→commands *(deferred to quality improvement pass)*

### Phase 2 — Execution and outcome  *(complete)*

- [x] ExecutionOrchestrator — `GovernancePlanAgent.execute()` extracts command section, submits to `dr_egeria_run_block` via `DrEgeriaActionAgent`
- [x] `config/governance_report_map.yaml` — family → report_spec mapping (10 families + fallback)
- [x] OutcomeReporter (`advisor/agents/outcome_reporter.py`) — report selection, execution, narrative synthesis
- [x] Plan Document outcome section — composed and appended post-execution
- [x] DocumentManager `move_to_outbox` — plan moved on success; outcome appended
- [x] Web UI: Execute button in canvas (shown once doc_id is set); `plan_executed` response type; outcome banner + outbox refresh

### Phase 3 — Artifact Canvas generalisation + LGCI quality  *(in progress)*

- [x] `ArtifactCanvas` class (`advisor/web/static/artifact_canvas.js`) — generic base; `PlanCanvas` refactored to use it via data adapter + item adapter pattern
- [x] Plan versioning — `DocumentManager.update()` saves versioned backup before each overwrite
- [x] TRACK — `metrics_collector.record_plan_event()` called on plan create and execute; admin dashboard has LGCI Plan Usage section
- [x] **Admin transcript viewer** — `admin.html` Sessions section: transcript table, session detail modal, failure/correction phrase detection, outcome badges
- [x] **Pattern library expansion** — `_ENTITY_PATTERNS` covers task, team, agreement, data-sharing-request; `_ROLE_PATTERNS` covers "have X be the Y" and "role as X"; `_NAME_STOP` prevents name capture bleeding
- [x] **Egeria context enrichment** — `advisor/egeria_context.py` (`EgeriaContext`): actor profile lookup by name (actor qualified name injected into `Link Person Role Appointment`), governance zone listing, project/glossary existence check; warnings surfaced in `confirm_commands`
- [x] **Governance zone valid values** — `/api/templates/{command}/fields` injects live zone names as `valid_values`; canvas renders `<datalist>` autocomplete for zone-type fields
- [x] **Partial execution detection** — `OutcomeReporter`: GUID count + command count comparison; `_infer_status()` returns Partial when fewer commands executed than expected; outcome section shows "N of M commands processed"
- [ ] Report Spec design flow — canvas + chat for creating/editing question_specs *(needs design session)*
- [ ] Report execution results in canvas — live results with conversational follow-up
- [ ] CLI review loop (`$EDITOR` + diff + confirm)

### Phase 4 — Routing quality + Plan Editor mode  *(Phase 4A/4B complete; 4C in progress)*

This phase addresses routing defects identified through real-use testing and adds the direct Plan Editor mode.

#### 4A — Routing fixes *(complete)*

**Issue 3 / Fix 1 — Negative routing guard** ✓
- [x] `_INTERROGATIVE_PREFIXES` constant + `_is_interrogative()` in `advisor/rag_system.py`
- [x] Guard fires before intent override: interrogative queries with intent=plan/command/act → redirected to `explanation`
- [x] Draft-active queries bypass the guard (draft_id routing fires first)

**Fix 2 — Intent override as suggestion not mandate** ✓
- [x] Priority order documented in code: interrogative guard > draft_id routing > intent override > pattern classifier

**Fix 3 — Dr.Egeria command keyword index** ✓
- [x] `advisor/command_keyword_index.py` — `CommandKeywordIndex` class
- [x] 4-tier confidence: exact alias (0.95) → catalog name (0.90) → template filesystem (0.75) → partial substring (0.55)
- [x] `lookup(phrase)` used in `_infer_type_from_context()` as last resort before "project" fallback
- [x] `all_commands()` powers `/api/actions` endpoint

**Fix 4 — Confidence-gated clarification in `confirm_commands`** ✓
- [x] Low-confidence inferences (< 0.80) flagged in `_extract_entities_patterns()`
- [x] `keyword_suggestions` threaded through `_decompose_intent()` → `PlanElicitor.start()` → stored in draft spec
- [x] `_build_confirm_commands_response()` shows "⚠️ I interpreted X as Y — if that's not right…"

**Issue 1 — "Completely wrong" correction path** ✓
- [x] `restart_signals` block in `_handle_confirm_commands()`: clears commands, prompts fresh description without leaving the draft

**Issue 4 / Fix 5 — Explain routing for Dr.Egeria concepts** ✓
- [x] `routing.yaml` explanation CRITICAL patterns expanded: all "what is/are a dr egeria template" variants
- [x] `egeria_general` and `pyegeria_drE` domain terms include "dr egeria template" keywords

**Issue 5 / Fix 6 — Show Me routing for Dr.Egeria templates** ✓
- [x] CRITICAL command patterns in `routing.yaml`: "show me a dr egeria template" → `DrEgeriaTemplateAgent`

**Solution Architect catalog gap** ✓ *(part of 4C)*
- [x] 13 Solution Architect commands added to `dr_egeria_actions.yaml` (catalog 42 → 55)
- [x] `_ENTITY_TO_ACTION` + `_infer_type_from_context()` wired for blueprint/component/supply chain

#### 4B — Plan Editor mode *(complete)*

- [x] `GET /api/actions` — all ~126 commands grouped by family (catalog + template filesystem)
- [x] `POST /api/drafts/builder` — blank draft with `builder_mode: true`; bypasses `_decompose_intent()`
- [x] "New Plan (Builder)" button in Plans sidebar
- [x] Builder title modal → blank canvas
- [x] Command picker modal: search input + family filter tabs + action cards with Add button
- [x] `addItem()` in `artifact_canvas.js` opens picker instead of `prompt()`
- [ ] Builder mode chat routing — `builder_mode` flag stored but not yet read by `_process_query` to switch chat to DocAgent for informational queries *(next)*

#### 4C — Action catalog expansion *(in progress)*

The 55-entry catalog covers the most common commands plus the full Solution Architect family. Phase 4C expands coverage to the ~71 remaining uncatalogued templates so that conversational planning can decompose intent involving any Dr.Egeria command family.

- [x] Solution Architect family — 13 commands *(complete)*
- [ ] Collections family — 12 remaining commands (Create_Subject_Area, Create_Security_Group, Create_Folio, etc.)
- [ ] Governance Officer family — ~27 remaining Create_* commands *(largest gap; prioritise most-used)*
- [ ] Data Designer family — 11 remaining commands *(needed for data structure planning)*
- [ ] Digital Product Manager family — 8 remaining commands
- [ ] External Reference family — 7 remaining commands
- [ ] Feedback family — 9 commands *(lower priority)*

---

## 11. Design Decisions

| # | Question | Decision |
| --- | --- | --- |
| Q1 | Where does `docs_root` default to? | Ask upfront; defaults drawn from `advisor.yaml` (inbox/outbox paths) or pyegeria config. Multi-user aware. |
| Q2 | What triggers "plan" vs "act now"? | Always plan first. Every multi-step request starts with confirm_commands in the canvas. |
| Q3 | Execution granularity | Whole-document. Document-scoped name references between commands require this. |
| Q4 | Command-family → report_spec mapping | Config file (`config/governance_report_map.yaml`). |
| Q5 | CLI review loop in Phase 1? | No. Web UI only for Phase 1 and 2. CLI deferred to Phase 3. |
| Q6 | Does the Plan Document live in git? | User's choice. The system neither requires nor prevents it. |
| Q7 | Interrogation vs. generate-first? | Generate-first. Show a draft immediately; refine through canvas and conversation. Never ask more than 1–2 questions before showing something. |
| Q8 | Slot-filling dialogue for elicitation? | No for UX. The IntentModel uses frame semantics internally without driving a Q&A. |
| Q9 | Canvas layout? | Option A (50/50) with draggable divider. User chooses allocation. |
| Q10 | Canvas pattern scope? | General `ArtifactCanvas` in Phase 3. Plan Canvas first; Report Spec canvas second. |
| Q11 | Is the workflow strictly linear? | No. Every step is re-entrant. Users can exit, return, jump back, or redirect at any point. |
| Q12 | IntentModel slot vocabulary source? | Dr.Egeria templates (currently ~12 command families). `egeria_types` collection as reference. Grows as templates grow. |
| Q13 | Per-command narrative text? | Yes — generated by LLM and user-editable. Appears in canvas and in the Plan Document as command annotations. |
| Q14 | Plan Templates? | Yes — already implemented. Save any plan as a template; start new plans from templates. Stored in `~/egeria-plans/plan_templates/`. |
| Q15 | How is intent decomposed reliably on a local 8B model? | Two-stage extraction. The LLM never emits command structure — it only extracts entity names and roles (pattern-based first, LLM fallback). A deterministic mapping step turns entities into commands. This eliminated hallucinated names and duplicate commands. |
| Q16 | Which LLM for planning? | `qwen2.5-coder:32b` via `get_planning_llm()` for narrative, refinement, and the LLM extraction fallback (quality matters). RAG Q&A stays on `llama3.1:8b` (latency matters). Configured in `llm.models.planning`. |
| Q17 | Does intent=Plan override all routing? | No — intent is a *suggestion*, not a mandate. A pre-flight `_is_interrogative()` guard fires before intent is applied. Interrogative queries (What is / How does / Explain) always route to DocAgent regardless of intent setting. Priority order: interrogative guard > draft_id routing > intent override > pattern classifier. |
| Q18 | Plan Editor vs. conversational — same canvas? | Yes. Both modes produce the same draft structure and use the same Plan Canvas and persistence layer. Editor mode = blank canvas + command picker modal + `builder_mode` flag. Conversational mode = decomposed commands pre-loaded into the same canvas. Users can freely switch between modes within a session. |
| Q19 | How large is the Dr.Egeria template library? | ~126 unique commands in 253 files (basic/advanced pairs), across 12 command families. The action catalog covers 42 of these (~1/3). The remaining ~84 are accessible via Plan Editor mode (filesystem scan) and are Phase 4C catalog additions for conversational use. |
| Q20 | Interrogative routing — what if the user is in plan refinement? | If `draft_id` is set AND the query is interrogative AND the query is about the plan itself ("what does step 3 do?"), still route to the draft context via PlanElicitor. The interrogative guard applies only when no draft is active (new query coming in with intent=Plan but no active session). |

---

## 12. What This Reuses from the Existing System

| Existing component | How it's reused |
| --- | --- |
| `_find_dre_template_raw()` + perspective boosting | Template selection and IntentModel slot vocabulary |
| `DrEgeriaActionAgent` template parsing + parameter extraction | Extended for multi-command parameter filling |
| `ReportPipeline.run_report()` | OutcomeReporter runs verification reports |
| `QuestionSpecIndex` | Finding relevant report_specs post-execution |
| `dr_egeria_run_block` MCP tool | Unchanged execution path |
| Web UI chat + markdown rendering | Conversational refinement alongside canvas |
| `egeria_types` vector collection | Secondary reference for type semantics |
| Template family taxonomy | Drives template selection, dependency ordering, and outcome report mapping |
| Existing resize handle implementation | Draggable divider between chat and canvas |

---

## 13. Continuous Learning and Context Intelligence

### 13.1 The learning loop

Every interaction is a signal. The goal is to capture those signals, make them reviewable, and use them to improve the system — first manually, then progressively more automatically.

#### Transcript capture

Every planning session is saved as a structured session log:
- Full conversation turns (user message → system response, with phase and query_type)
- User identity, active perspective, and intent history
- Draft lifecycle events (created, advanced to generate, executed, cancelled)
- Correction events — moments where the user had to correct the system — are the highest-value signal because they encode exactly what was wrong and what the right answer looks like
- Outcome: plan generated / executed / cancelled / abandoned

Session logs are saved to `~/egeria-plans/sessions/{draft_id}.jsonl`. One line per turn. Finalised on terminal state (done, cancelled, saved-and-exited).

#### Context we must capture

A session log without context is much less useful. Minimum required context per session:

| Field | Why it matters |
| --- | --- |
| `user` | Identity (OS user for now; Egeria Actor profile later) |
| `perspective` | Did the user self-identify their role? Which one? |
| `intent_overrides` | Did the user manually override Auto intent? A pattern here reveals classifier weaknesses |
| `session_history` | Is this a first-time user or experienced? What have they planned before? |
| `egeria_environment` | Which Egeria instance? Which server? Which metadata collections are active? |

#### Review workflow

Raw transcripts are noisy. The review approach is **targeted sampling**, not exhaustive manual review:

1. **Failure triage**: sample sessions where the user corrected the system, abandoned, or thumbs-downed — these are the highest-priority reviews
2. **Success sampling**: sample long sessions with positive outcomes — these reveal what's working and can become few-shot examples
3. **LLM-assisted pre-classification**: use a Claude API call to pre-classify transcripts (hallucination / wrong intent / correct but unhelpful / good) before a human reviews — reduces review burden significantly

#### Learning pipeline (progressive)

| Stage | Mechanism | Effort |
| --- | --- | --- |
| **Immediate** | Fix bugs from reviews: add validator rules, update prompt rules, extend action catalog | Low — one rule per failure pattern |
| **Short-term** | Few-shot examples in decompose prompt from approved plans | Medium — requires curation |
| **Medium-term** | RAG over past plans: retrieve similar plans when generating new ones (pgvector already available) | Medium — new collection + indexing |
| **Longer-term** | Fine-tuning local model on curated plan transcripts | High — requires labelled dataset |

The action catalog and validator are the system's "learned rules" — structured, inspectable, and evolvable without touching the LLM. Every bug like the self-referential Parent ID issue becomes a catalog rule or validator fix that prevents all future occurrences permanently.

### 13.2 Personalization

As the system moves from single-user to multi-user, personalization becomes increasingly relevant. Three layers:

**User identity and history**
- Who the user is (Egeria Actor profile — name, role, team, organisation)
- What they've planned before (session history → vocabulary, naming conventions, preferred structure)
- What they always change or skip (implicit preference extraction from correction events)
- Personal plan templates saved from past approved plans

**Perspective-aware behaviour**
The system already supports perspective selection (Developer / Data Steward / Governance Officer etc.). This needs to go further:
- Perspective informs which Dr.Egeria command families are relevant
- Perspective informs the vocabulary used in generated narrative text
- Implicit perspective detection: if the user's history shows they always work in the Glossary family, offer that as the default

**Egeria Actor integration**
Egeria itself has Actor profiles, Person Roles, and Team structures. When a user logs in:
- Look up their Actor profile to pre-populate perspective and organisational context
- Suggest role assignments based on their known Egeria roles
- Use their team's zone assignments as defaults

### 13.3 Egeria as an active participant

The Advisor has a live connection to Egeria via MCP. This is underutilised. Egeria is not just the target of plans — it is an active knowledge resource that should inform plan generation.

**Glossary**
Egeria has a live glossary. When the user mentions a term ("Revenue Recognition", "Finance Domain", "data steward"), check the glossary first:
- Is this term already defined? Show the existing definition as context.
- Are there naming conventions in the glossary that should be applied to the new plan?
- Suggest glossary-conformant names for new objects rather than invented placeholders.

**Referenced data / valid values**
Egeria has reference data collections (project status, data classification levels, governance zone names, etc.). Rather than prompting the LLM to invent valid values, query Egeria:
- What governance zones exist? (Use as valid values for zone assignments)
- What project statuses are defined? (Use for status fields)
- What data classification levels are active? (Use for classification commands)
This dramatically reduces hallucination of field values and ensures plans use names that will actually resolve when executed.

**Context graph**
Egeria knows what already exists: existing projects, glossaries, teams, data assets. Before generating a plan:
- Check if the named project already exists — and if so, whether the user intends to extend it or create a new one
- Identify related objects that should be linked (e.g. a team that already manages the Finance domain)
- Detect potential conflicts (a zone name that already exists but with different access rules)

**User profiles**
Egeria's Actor management tracks people and their roles. When "Tom Tally" is mentioned as a project leader:
- Look up Tom Tally in Egeria's actor profiles — confirm the name, find their qualified name for the appointment command
- If Tom Tally doesn't exist yet, note that a Create Actor Profile command may be needed

**The principle**: before building anything from scratch, ask "does Egeria already have this?" — it usually does. The Advisor's job is to make Egeria's knowledge accessible conversationally, not to duplicate it.

### 13.4 Implementation roadmap for 13.1–13.3

| Priority | Item | Status |
| --- | --- | --- |
| Now | Session transcript saving (`~/egeria-plans/sessions/`) | **Complete** |
| Now | Context capture: user, perspective, intent history per session | **Complete** |
| Now | Admin dashboard: session list + transcript viewer with failure/correction tagging | **Complete** |
| Now | Egeria Actor profile lookup for named individuals (qualified name injection) | **Complete** |
| Now | Governance zone valid values in canvas field autocomplete | **Complete** |
| Now | Egeria project/glossary existence check with user warnings | **Complete** |
| Now | Partial execution detection (GUID count + command count comparison) | **Complete** |
| Now | Pattern library expansion (task, team, agreement, role phrasings, name stop) | **Complete** |
| Now | Negative routing guard — interrogative forms bypass plan agent | **Complete** |
| Now | Dr.Egeria concept routing fix (What is a Dr.Egeria Template?) | **Complete** |
| Now | Show Me routing fix for Dr.Egeria templates | **Complete** |
| Now | Command keyword index (blueprint/component/etc. → canonical command name) | **Complete** |
| Now | "Completely wrong" correction path in confirm_commands | **Complete** |
| Now | Confidence-gated "Did you mean X?" clarification | **Complete** |
| Now | Solution Architect catalog (13 commands) | **Complete** |
| Now | Plan Editor mode — command picker modal + builder entry point | **Complete** |
| Soon | Builder mode chat routing (read builder_mode flag in _process_query) | **Phase 4B remainder** |
| Soon | LLM-assisted transcript pre-classification (Claude API) | Planned |
| Medium | Few-shot examples from approved plans in decompose prompt | Planned |
| Medium | RAG over past plans (pgvector, new collection) | Planned |
| Medium | Egeria glossary lookup during plan generation | Planned |
| Medium | Egeria referenced data for valid values (ReferenceDataManager) | Planned |
| Medium | Unresolved actor handling (auto-insert Create Actor Profile when actor_found=False) | Planned |
| Medium | Action catalog expansion to cover all ~126 template commands | **Phase 4C** |
| Later | Context graph conflict detection pre-execution | Planned |
| Later | Implicit preference extraction from correction events | Planned |
| Later | Fine-tuning on curated plan transcripts | Research |

---

## 14. What's NOT in Scope (for now)

- Rollback / undo of executed commands (Dr.Egeria does not support this natively)
- Scheduling / deferred execution
- Multi-user real-time collaboration on a Plan Document
- Integration with external approval workflows (Jira, ServiceNow, etc.)
- Automatically detecting conflicts with existing Egeria metadata before execution
- Single-command "just do it" shortcut (all requests go through the plan-first flow)
- Direct editing of the generated markdown (users work through the canvas or chat)
