# Literate Governance Guide

Egeria Advisor can turn a plain-language description of a data management task into a
complete, reviewable, executable plan — and then verify that the work was done.

This feature is called **Literate Governance with Context Intelligence (LGCI)**.
It is named after *Literate Programming*: the idea that intent, approach, and executable
commands live together in one human-readable document.

---

## What it does

You describe what you want to accomplish. The advisor:

1. **Proposes** — extracts the objects and roles from your description and shows you
   the proposed list of steps for confirmation *before* asking any detail questions
2. **Builds** — opens a live **Plan Canvas** beside the chat where the steps appear as
   cards you can reorder, edit, add to, or remove
3. **Refines** — you iterate by talking to it *or* by editing cards directly; both views
   stay in sync
4. **Generates** — assembles a structured markdown Plan Document (goal, approach,
   pre-filled Dr.Egeria commands, per-step narrative)
5. **Executes** — submits the approved plan to Dr.Egeria via MCP
6. **Reports** — verifies what was created, appends an outcome section, saves to outbox

The whole flow is **non-linear**: you can jump back, change direction, leave and resume
later, or switch between the canvas and the chat at any point.

---

## When to use it

Use Literate Governance when you want to:

- Set up a **new glossary** with terms, categories, and steward assignments
- Create a **governance structure** (zones, policies, roles, appointments)
- Define a **data dictionary** with fields, data classes, and classifications
- Build a **project** with tasks and team assignments
- Do anything that requires **multiple related Dr.Egeria commands in sequence**

Use plain Dr.Egeria commands (Act intent) instead when you want to create or update
a **single object** (one glossary, one term, one zone).

---

## Triggering a plan

Describe what you want to accomplish in natural language. Multi-step requests are
automatically routed to the plan generator:

```
"I want to set up a glossary for the finance domain with standard terms,
 categories, and data steward assignments"

"Set up a governance structure for the HR division including governance zones,
 policies, and a governance officer role"

"Create a data dictionary for customer data with fields, data classes,
 and appropriate governance classifications"

"Plan to set up a project for the Q3 data quality initiative with tasks and
 team assignments"
```

**Tips for triggering a plan:**
- Include phrases like *"set up"*, *"plan to"*, *"with … and …"*, or describe
  multiple objects in one request
- Be specific about the domain, purpose, and who owns the data — the more context
  you give, the better the parameter suggestions
- To create **multiple items of the same type**, list them with commas and "and":
  *"solution components for UK Sales DB, EU Sales DB, US Sales DB and WorldWide Sales DB"*
- When you mention a **container** alongside its contents, name the container relationship:
  *"Put all of these components in the same blueprint"*
  The advisor will auto-name the blueprint from the common part of the item names and
  pre-fill each component's **In Solution Blueprints** field with the blueprint's
  qualified name — no separate Link step needed.

**What does NOT trigger a plan:**
- *"Create a glossary"* — single object, goes to DrEgeriaActionAgent directly
- *"Give me a Dr.Egeria template for a glossary"* — returns the template only
- *"List glossaries"* — a report query

### Supported multi-item types

The advisor detects lists of the following types automatically:

| Phrase pattern | Command generated |
|---|---|
| *"solution components for A, B and C"* | `Create Solution Component` × N |
| *"glossary terms for …"* | `Create Glossary Term` × N |
| *"tasks for …"* | `Create Task` × N |
| *"data structures for …"* | `Create Data Structure` × N |

When a **blueprint** is mentioned alongside components, the advisor:
1. Derives a blueprint name from the common part of the component names
2. Generates a `SolutionBlueprint::Name` qualified name for it
3. Pre-fills **In Solution Blueprints** on every component with that qualified name

You can override the auto-generated blueprint name or qualified name in the Plan Canvas
(expand the card → edit the field directly).

---

## The confirm step

Before the advisor asks you for any details, it shows you the **proposed steps** it
extracted from your description and asks you to confirm:

```
### Sales Forecast Consolidation
Here's what I'll create, in order:

1. Create Project — Sales Forecast Consolidation
2. Create Person Role — Project Leader
3. Link Person Role Appointment — Tom Tally

---
Does this look right?
- Say "yes" or "continue" to fill in any missing details
- Say "generate now" to create the plan immediately (gaps become placeholders)
- Describe anything to add:  "also create a sub-project for data collection"
- Describe anything to remove: "remove the governance zone"
- Say "completely wrong" to describe your intent from scratch
```

Four **buttons** also appear below the response:

| Button | What it does |
|--------|-------------|
| **⚡ Generate Now** | Skip the field Q&A and produce the plan immediately; required fields become `<!-- TODO -->` placeholders |
| **✗ Completely Wrong** | Clear the proposed steps entirely and ask you to re-describe what you want |
| **💾 Save & Exit** | Save the draft and return to normal chat; resume from the Plans sidebar |
| **✕ Cancel** | Discard the draft |

This is your chance to correct the *shape* of the plan before getting into field
details. If the advisor auto-corrected anything (for example, turning a self-referential
parent into a clean sub-project, or removing a duplicate step), it tells you:
*"Auto-corrected: …"*.

You can also respond conversationally:

- **"yes"** / **"continue"** — proceed to fill in detail fields
- **"also add a sub-project for Survey of Existing Systems"** — adds a step
- **"remove step 2"** / **"remove step N"** — removes a step by number
- **"steps 1 and 2 are duplicated"** — removes duplicates
- **"that's wrong"** — asks which step to change
- **"move step 3 to be the first step"** — reorder by ordinal or by name; works both before
  and after the plan document is generated
- **"make Campaign the parent of all other projects"** — establishes a Project Hierarchy
  relationship across steps in bulk, without a separate Link command
- **"Project 1 depends on Project 2 and 3"** — establishes Project Dependency relationships,
  fanning out across multiple named targets

These structural edits are deterministic (no LLM involved), so they apply reliably even on
large plans. Other relationship families beyond Projects are being rolled out incrementally —
see `docs/design/RELATIONSHIP_LINKING_SCOPE.md` for the current coverage and rollout order.

---

## The Plan Canvas

When a plan is active, a **Plan Canvas** panel opens to the right of the chat. Drag the
divider between them to give whichever side more room.

Each step is a **card** showing the command, its display name, any known parameters
(✓ green), and a status dot (green = named, amber = needs a name). On each card you can:

| Action | How |
|--------|-----|
| **Reorder** | Drag the card by its `≡` handle |
| **Expand fields** | Click `▾` — shows the template fields with inline editing |
| **Add a note** | Type in the narrative box — explains the step in the final document |
| **Remove** | Click `✕` |
| **Add a step** | Click **+ Add step** at the bottom |

Use the **Basic / Advanced** toggle in the canvas toolbar to switch between the key
fields (Basic) and the full template field set (Advanced).

**Conversation handles structure; the canvas handles detail.** Adding, removing, and
reordering steps is most natural in the chat ("add a sub-project for X", "move design
before requirements"). Filling in a description, a date, or an owner is easiest by
clicking the card. Neither forces you into the other — both edit the same live plan.

When you are ready, click **Generate Plan** in the canvas toolbar to produce the full
Plan Document. **Execute** appears once the document exists.

---

## Drafts — leave and resume

Every planning session is saved as a **draft**. The **Plans** sidebar shows your active
drafts (amber) above your inbox and outbox plans. You can:

- **Leave** a session at any point (close the tab, ask something else) — it's saved
- **Resume** by clicking the draft in the sidebar; the advisor shows you exactly where
  you left off
- **Discard** with the `✕` next to the draft

The session also survives a browser refresh — the active draft is restored automatically.

---

## Reading the generated plan document

Once generated, the plan is a markdown document with five sections:

### 1. Header
```
# Data Management Plan: Finance Domain Glossary
**Created:** 2026-06-02 14:30   **Last edited:** 2026-06-02 14:42   **Status:** Draft
**Created by:** dwolfson   **Perspective:** Data Steward
**Purpose:** Establish canonical glossary for Finance business domain
```

### 2. Goal and Requirements
Plain-language statement of what the plan achieves and any constraints.

### 3. Approach
Ordered summary of which Dr.Egeria command families will be used and why —
for example: *"1. Create Glossary (Glossary family) — establishes the container…"*

### 4. Command Sequence
The actual Dr.Egeria markdown commands, pre-filled where possible. Parameters
the advisor couldn't determine are marked with an orange **⚠ fill in** badge.
These must be filled in before executing.

### 5. Outcome (added after execution)
Automatically appended when the plan is executed — includes execution status,
a narrative summary, and embedded verification report output.

---

## TODO markers

When a required parameter cannot be determined from your description, the plan
marks it with `<!-- TODO: fill in -->` rendered as an **⚠ fill in** badge.

To fill these in, ask the advisor conversationally:

```
"Change the glossary name to Finance Glossary 2026"
"Set the data steward to erinoverview"
"Add a description: Canonical glossary for Finance business domain"
```

Or use the CLI to open the plan in your editor (see [CLI tools](#cli-tools) below).

---

## Refining the plan

You can refine in **two ways**, and they edit the same live plan:

**In the chat** — best for structural changes:

```
"Add a term for Revenue Recognition"
"Remove the team membership step — we don't need that"
"Change the governance zone to Finance-Prod"
"Move the design phase before requirements"
"Add a second data steward role for the EMEA region"
```

**In the canvas** — best for field detail: expand a card (`▾`) and edit fields directly,
drag cards to reorder, or click **+ Add step**. Changes save automatically.

If you have already generated the document and opened the **Plan Editor**, a
**💬 Discuss changes** button returns you to the chat with the same draft active, so you
can describe structural changes conversationally and come back. The previous version of
any edited document is automatically backed up to `~/egeria-plans/versions/`.

---

## Executing the plan

When you are satisfied with the plan:

1. Click the **Execute** button in the violet banner below the plan text
2. Or type: `execute the plan {doc_id}` (the doc_id is shown in the banner)

The plan is submitted to Dr.Egeria as a single markdown file. All commands run
in sequence; later commands can reference objects created earlier in the same file
by display name.

**Dry run** (CLI only): `egeria-advisor-plans execute {doc_id} --dry-run`
Shows the extracted command sequence without submitting it to Dr.Egeria.

---

## Reviewing the outcome

After execution the advisor:

1. Runs verification reports for the command families used (e.g. *Glossaries*,
   *Glossary-Terms* for Glossary family commands)
2. Synthesises a narrative summary
3. Appends a **## Outcome** section to the plan document
4. Moves the document from `inbox/` to `outbox/`

The outcome section shows:
- **Status**: Success / Partial / Failed / Unknown
- **Summary**: LLM-generated narrative of what was created
- **Command Results** (on Partial/Failed): per-command success/failure table
- **Execution Output**: raw Dr.Egeria output (truncated)
- **Verification Reports**: embedded report output filtered to created objects

---

## Multi-session continuity

Plans persist between sessions. The left sidebar is tabbed — **Reports | Plans | Recent** —
and automatically switches to the **Plans** tab whenever a draft is opened or created. The
Plans tab lists drafts, inbox, and outbox plans, and includes a scrollable **Plan Templates**
sub-section: saved templates are one click to start from ("start from this template") without
needing to remember the chat phrase, with a delete button per template.

- Click an **inbox** plan to restore it into the chat with its Execute button
- Click an **outbox** plan to review the completed plan + outcome

The sidebar refreshes automatically after each plan lifecycle event.

---

## Where plans are stored

| Folder | Contents |
|--------|----------|
| `~/egeria-plans/inbox/` | Plans awaiting review or execution |
| `~/egeria-plans/outbox/` | Executed plans with outcome section appended |
| `~/egeria-plans/archived/` | Cancelled or superseded plans |
| `~/egeria-plans/drafts/` | In-progress planning sessions (the live draft state) |
| `~/egeria-plans/plan_templates/` | Reusable plan templates you've saved |
| `~/egeria-plans/sessions/` | Full conversation transcripts (for review / learning) |
| `~/egeria-plans/versions/` | Automatic backups saved before each edit |

Paths are configurable in `config/advisor.yaml`:

```yaml
governance_plans:
  inbox:          ~/egeria-plans/inbox/
  outbox:         ~/egeria-plans/outbox/
  archived:       ~/egeria-plans/archived/
  drafts:         ~/egeria-plans/drafts/
  plan_templates: ~/egeria-plans/plan_templates/
  sessions:       ~/egeria-plans/sessions/
```

Plan documents are markdown files named `{YYYYMMDD_HHMMSS}_{title-slug}.md`.
They are plain files — you can track them in git, share them, or edit them
with any markdown editor.

---

## CLI tools

The `egeria-advisor-plans` command provides a full review loop from the terminal:

```bash
# List plans in your inbox
egeria-advisor-plans list

# List inbox and outbox
egeria-advisor-plans list --outbox

# Print a plan with ⚠ fill in markers highlighted
egeria-advisor-plans show 20260602_143022_finance_glossary

# Open in $EDITOR, show a coloured diff, confirm before saving
egeria-advisor-plans edit 20260602_143022_finance_glossary

# Execute a plan (submits to Dr.Egeria)
egeria-advisor-plans execute 20260602_143022_finance_glossary

# Execute without submitting (shows extracted commands only)
egeria-advisor-plans execute 20260602_143022_finance_glossary --dry-run

# List saved edit backups
egeria-advisor-plans versions 20260602_143022_finance_glossary
```

---

## Full example walkthrough

**Step 1 — Describe the task**

> *"As a data steward for the Finance division, I want to set up a glossary for
> the finance domain with standard terms, categories, and data steward assignments"*

**Step 2 — Confirm the steps**

The advisor shows the proposed steps in the chat and opens the Plan Canvas. Check the
list is right — add, remove, or reorder by talking to it or editing cards. Then say
**"yes"** to fill in details, or **"generate now"** to build the document immediately.

**Step 3 — Refine in the canvas**

Expand cards to fill in fields, add narrative notes, or drag to reorder. The chat and
canvas stay in sync.

**Step 4 — Generate**

Click **Generate Plan**. The full Plan Document is produced and saved to your inbox.
Any unfilled required fields show a **⚠ fill in** marker.

**Step 5 — Execute**

Click **Execute**. The advisor submits the commands to Dr.Egeria.

**Step 6 — Review the outcome**

The outcome section appears inline. Check the Status and the verification report
to confirm the objects were created correctly.

**Step 7 — Reuse it**

The completed plan is in your outbox. You can also save the structure as a **template**
when prompted — future plans of the same shape start from it with just the names to fill in.

---

## Troubleshooting

**"I described a complex task but got a single Dr.Egeria command instead of a plan"**

The routing threshold for plan vs. single command is: does the request involve
multiple objects or families? Try making the request explicitly multi-step:
> *"Set up a glossary **with** terms, categories, **and** steward assignments"*
> (the *"with … and …"* pattern reliably triggers the plan generator)

**"The plan has many ⚠ fill in markers"**

This means the advisor couldn't extract those values from your description.
Provide more context upfront, or fill them in conversationally after generation.

**"Execution failed with status Partial"**

Some commands succeeded and some did not. Check the **Command Results** table
in the outcome section to see which ones failed. Common causes:
- A referenced object doesn't exist yet (e.g. a governance zone that needs to
  be created first in a separate step)
- Missing required field that was left as `<!-- TODO: fill in -->`

**"The plan is in outbox but I want to re-execute"**

Outbox plans are immutable. Generate a new plan from the same description,
or copy the command sequence from the outbox document into a new Dr.Egeria run.
