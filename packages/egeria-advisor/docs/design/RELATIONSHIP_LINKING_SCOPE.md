# Natural-Language Relationship Linking — Scope & Roadmap

**Last updated:** 2026-07-06
**Status:** Reference implementation done for Projects (hierarchy + dependency); general
catalog-driven mechanism for the other ~48 relationship types is future work, scoped here.

---

## Background

Chat-driven plan editing (`PlanElicitor`, both `confirm_commands` and `refine` phases) can now
reorder plan steps and establish two specific relationship types via natural language:

- **Project Hierarchy** — "make Campaign the parent of all other projects", "link Project 1 as
  a sub-project of Campaign"
- **Project Dependency** — "Project 1 depends on Project 2 and 3", "link Project 1 as dependent
  on Project 2"

These were built as a concrete, worked example — not a generalized system. This document scopes
what it would take to extend the same pattern to the other ~48 cataloged `Link *` relationships
(and the ~150 more Egeria natively supports that Dr.Egeria could eventually expose), based on a
full-family template scan done this session (see memory: `project_relationship_layering.md`).

---

## What's implemented (reference implementation)

`advisor/agents/plan_elicitor.py`:

- **Resolver primitives** (reusable for any future relationship): `_resolve_command_ref` (step
  N / exact name / ordinal-of-type "Project 2" / unique substring match), `_resolve_bulk_command_refs`
  (bulk selectors: "all projects", "all other projects"), `_split_multi_target_refs` ("Project 2
  and 3" → two refs).
- **`_apply_hierarchy_request`** — embedded mutation, appends to the *parent's* `Sub-Projects`
  field (Reference Name List, top-down). Deliberately does **not** use `Parent ID` (bottom-up) —
  see "Composer blocker" below.
- **`_apply_dependency_request`** — standalone command insertion, one `Link Project Dependency`
  per pair (`Child Project` = dependent, `Parent Project` = depended-upon).
- Both are wired into `confirm_commands` (pre-generation, mutates `spec["commands_identified"]`)
  and `refine` (post-generation, via `_rebuild_command_sequence` which regenerates only the
  `## Command Sequence` section, preserving narrative/outcome).
- All deterministic — no LLM in the structural path, consistent with design rule 15 (LLM stays
  out of command-structure decisions; only used for the two-stage entity extraction elsewhere).

---

## Composer blocker (must understand before generalizing) — BACKLOG.md PC-1

`GovernancePlanAgent._load_template()` always loads the **basic**-tier Dr.Egeria template,
regardless of `spec["mode"]`. `_compose_command_block()` only renders a field if it appears in
the loaded template's attribute list. **Consequence: any field that exists only in the advanced
template is silently dropped from every generated plan document**, in both basic and advanced
mode. Confirmed live: setting `Parent ID` (historically advanced-only) produced a document with
the field completely absent, no error.

This is why the hierarchy handler targets `Sub-Projects` (now promoted to basic-tier, per a
concurrent Dr.Egeria template change) instead of `Parent ID`. **It also means the "any command
can embed one relationship via advanced-mode `Parent ID` + `Parent Relationship Type Name`"
mechanism discussed earlier this session — the generic single-relationship-at-creation slot
available in advanced mode for any family — is currently a no-op through this pipeline,
regardless of `spec["mode"]`.**

**Before generalizing the embedded-mutation pattern to any other family, either:**
1. Fix PC-1 (`_load_template` becomes mode-aware / advanced-fallback-aware), or
2. Restrict the embedded-mutation path to fields confirmed present in the **basic** template
   for that specific command — i.e., always verify against the live basic template file, never
   assume an advanced-only field will render.

Until PC-1 is fixed, treat every embedded relationship candidate as **basic-tier-only, verified
per template**, not "advanced mode unlocks it."

---

## Catalog schema needed to generalize

Per-relationship metadata, sourced from actual template files (never assumed from the name —
see the naming traps below):

| Field | Purpose |
|---|---|
| `representation` | `embedded` \| `standalone` \| `both` |
| `embedded_on` | For `embedded`/`both`: which `Create *` command + field name (e.g. `Create Solution Blueprint.Solution Components`) |
| `embedded_direction` | `top_down` (container lists members) \| `bottom_up` (member lists container) — some relationships support only one direction even when a field technically exists (e.g. Solution SubComponents is documented bottom-up-only) |
| `embedded_tier` | `basic` \| `advanced` — **must be re-verified after any PC-1 fix**, since today only `basic` actually renders |
| `standalone_command` | For `standalone`/`both`: the `Link *` command name |
| `standalone_fields` | The two (or more) reference-name field names and which is subject/object |
| `metadata_shape` | `membership` (Rationale/Status/Type/Notes quartet — see below) \| `simple` (Label/Journal Entry/Description) \| `none` |
| `phrase_templates` | Verb-phrase patterns in both directions + synonyms |
| `bulk_capable` | Whether "all X", "all other X" selectors make sense for this relationship |

### The membership-metadata axis (found in the full-family scan)

A `Membership Rationale` / `Membership Status` (DISCOVERED/PROPOSED/VALIDATED/...) /
`Membership Type` / `Notes` quartet appears on Collections' `Add_Member_to_Collection`,
Solution Architect's Blueprint/Component/ISC-child links, and Governance Officer's
`Link_Agreement_Terms_and_Conditions`. Everything else uses a lighter `Label`/`Journal Entry`/
`Description` shape. This determines whether a chat phrase like "mark X as a proposed member of
Y" has anywhere to put "proposed" — worth surfacing as a capability check before attempting to
parse that kind of qualifier from a phrase.

---

## Rollout priority (by family, from the full scan)

Only **Solution Architect**, parts of **Data Designer**, **Glossary**, and **Projects** have any
embedded relationship fields at all — everywhere else (Actor Manager, Collections, Digital
Product Manager, External Reference, Action Author, nearly all of Governance Officer, most of
Data Designer's non-hierarchy relationships) is **standalone-Link-only already**, in both basic
and advanced templates. That's actually simpler to generalize than Projects was: no
embedded-vs-standalone branch to resolve, no PC-1 exposure — just "insert a Link command."

Suggested order:
1. **Solution Architect** — richest relationship set (Blueprint↔Component, Component↔SubComponent,
   ISC nesting, Design Pattern relations), good next test of the embedded/standalone split
   including the bidirectional case (Blueprint↔Component embeddable from either side).
2. **Collections** — standalone-only (`Add_Member_to_Collection`), moderate volume (15 collection
   types), good test of the "membership metadata" phrase (rationale/status).
3. **Governance Officer** — standalone-only, 13 of 14 relationships, highest count of `Link`
   commands (14) but structurally uniform (mostly peer-links with Label/Journal/Description).
4. **Digital Product Manager**, **External Reference**, **Action Author**, **Actor Manager** —
   all standalone-only, lower volume, mechanically identical to the Governance Officer case once
   that's built.
5. **Data Designer** — deferred last; the scan flagged multiple overlapping embedded mechanisms
   for what may be one conceptual relationship (DataValueHierarchy vs DataValueComposition vs
   NestedDataField) that need a design decision before encoding, not just a template read.

---

## Known template bugs to route around (not this codebase's problem, but will break naive parsing)

Filed to `egeria-python` (PR #252) and this repo's `BACKLOG.md`:
- `Link_Term-Term_Relationship` has no Term1/Term2 fields at all.
- `Attach_Comment` is missing its target-element field.
- `Link_Regulation_to_Regulator` has stale field names copy-pasted from `Link_Governed_By`.
- `Create_Regulation.Regulators` and `Link_Associated_Skill_Set.Actor Name` look like reference
  fields by name but are typed `Simple`/free-text — any auto-detection of "does this command
  have a reference field" must check the declared `Attribute Type`, never infer from the field
  name alone.

---

## Phrase-library approach

Given ~50 relationships today and potentially ~200 as Dr.Egeria grows, don't front-load
synonym lists speculatively. Build the mechanism (resolver + catalog schema above) against the
next 1-2 families from the rollout order, then expand **driven by real usage** — log
unrecognized relationship phrases via `SessionLogger` and use that to prioritize which
`phrase_templates` to add next, the same way `CommandKeywordIndex` grew organically.

**Fallback behavior for anything not yet cataloged:** never guess and never silently fail. Try
the existing LLM-extraction-fallback pattern (narrow, constrained JSON, temperature 0, validated
against known command names — same shape as the entity-extraction fallback already used in
`_decompose_intent`) to suggest a candidate relationship; if still low-confidence, surface the
nearest known relationship names and ask, mirroring the confidence-gated "Did you mean X?"
clarification already used for command-type inference.

---

## Open questions

1. Does establishing a relationship from both sides independently within the *same* plan (before
   execution) risk anything, or is Egeria's confirmed auto-dedupe (see memory:
   `project_relationship_layering.md`) sufficient reassurance even for not-yet-materialized plan
   commands? (Dedupe was confirmed for already-existing Egeria elements — worth re-confirming
   for two brand-new elements created in the same plan run.)
2. Once PC-1 is fixed, should embedded-mutation prefer advanced-tier fields when both a basic and
   advanced embedded option exist (e.g. richer metadata), or keep preferring basic for the
   broadest compatibility?
3. For bidirectional embeddable relationships (Solution Blueprint ↔ Component), should the NL
   handler always mutate a fixed canonical side, or follow the grammatical subject of the user's
   phrase (mirrors the top-down/bottom-up design intent described this session — users approach
   problems both ways depending on whether they're starting from the container or the part)?
