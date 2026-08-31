# Presenting Architecture Recovery — what a curator actually sees

**Status:** findings, not a design. Measured 2026-08-30 against a store
refreshed to current code. It reports what the UI renders today and where that
breaks; it deliberately stops short of proposing the fix, because how findings
should be presented is a product decision and this is the evidence for making
it.

Companion to `architecture-recovery-clustering.md` (which is about *grouping*)
and `architecture-recovery-scope-tombstoning.md` (about *staleness*). Those two
change what is stored. This is about the last hop.

---

## 1. What is rendered

`index.html` renders the `architecture_recovery` result as: a count line, then
**the first 20 components** (`_ARCH_ROW_CAP`), each three lines —

```
active-metadata-store                    Software Service · 85%
Containerized-OMAG-Server-Platform::active-metadata-store
spring:startup-server-list
```

sorted by `path`, from `_architecture_recovery_results`.

## 2. The numbers, on a store refreshed to current code

| | `egeria_git` | `egeria_workspaces_git` |
|---|---|---|
| components recovered (raw) | 1035 | 175 |
| after depth projection | 451 | 107 |
| **actually shown** | **20** | **20** |
| untyped rows | 321 (71%) | 35 |
| structural (grouping, not components) | 75 | 15 |
| **stale rows, rendered as current** | **69** | **7** |
| perspectives mixed in one list | logical 341, deployment 35, none 75 | deployment 71, logical 20, physical 1, none 15 |

**A curator asking "what is Egeria's architecture?" sees 20 rows chosen
alphabetically out of 1035.**

## 3. Four findings, in the order I would fix them

### 3a. The `structural` flag is computed and ignored — built and unwired

`_architecture_recovery_results` marks grouping nodes explicitly, and its own
comment says why:

> They carry no type and no confidence by design — they have no evidence of
> their own — so they are marked `structural` and a consumer can render them as
> grouping rather than as a recovered component.

**No consumer reads it.** `grep structural` across `index.html` returns only
unrelated prose. So a structural node renders as `untyped · 0%` with `—` for
provenance — visually identical to a component we recovered and know nothing
about, which is the opposite of what it is.

It is also the *first* thing a curator sees: rows sort by `path`, and `.` sorts
first. The top row of Egeria's architecture is a grouping placeholder for the
repository root, presented as a 0%-confidence component.

**75 of 451 rows for egeria (17%), 15 of 107 for workspaces (14%).** The writer
is careful about this distinction, the reader preserves it, and the last hop
drops it — the same shape as `import_cohesion`, the ports/wires finding, and the
doc-locator's outward hop.

### 3b. Ordering is alphabetical, so the cap shows an arbitrary slice

20 of 451 are shown and they are the 20 whose `path` sorts first. Nothing
prefers high confidence, typed components, or a particular perspective.

The consequence is specific and bad: today's consolidation work produced a
**clean 8-component deployment reading of Egeria** — one platform, five servers,
Kafka, PostgreSQL. It is in the payload. It is invisible, because 341 logical
rows outrank nothing and sorting is by string.

### 3c. Perspective is in the payload, and is neither shown nor filtered on

Design §4.1 is emphatic that the four perspectives are **not interchangeable**
and that a component is only comparable to another within its own. The UI
renders all four in one flat list with no label and no filter.

This is the finding I would most want a second opinion on, because it is the one
where the fix is a real product decision rather than a bug fix. Options, with
what each costs:

| option | effect | cost |
|---|---|---|
| **Perspective tabs** — pick one, default to the smallest non-empty | Egeria becomes "8 deployment components" or "341 logical", never a mix | a UI mode; needs a default rule |
| Group headers in one list | keeps one scroll, makes the mixing visible | cheap; does not fix the cap |
| A `perspective` facet beside the existing type facets | consistent with the existing shell | needs the facet row to carry it |

**Recommendation: perspective tabs, defaulting to the smallest non-empty
perspective.** It is the only option that makes the 8-component reading the
default answer for Egeria rather than something a curator has to dig for, and
"smallest non-empty" needs no tuning — it is a comparison, not a threshold.

### 3d. Stale components render identically to live ones

69 of Egeria's 451 rows were written by no current run. In the deployment
perspective it is **27 of 35**. Every one renders at its original confidence
with no marker.

Already designed for in `architecture-recovery-scope-tombstoning.md`, and that
note now carries the measurement. Listed here because it is a *presentation*
symptom too: even after withdrawal exists, the UI needs to decide whether a
withdrawn component is hidden or shown-and-marked, and those are different
answers for a curator auditing history versus one reading current state.

## 4. What I did not do, and why

- **No UI changes.** 3a is a two-line fix and I still did not make it, because
  "render grouping differently from components" needs a visual decision — an
  indent, a muted style, a separate tree — and picking one silently is how a UI
  accumulates styles nobody chose.
- **No cap change.** Raising `_ARCH_ROW_CAP` treats a symptom; 3b and 3c are why
  20 rows are the wrong 20, and fixing ordering may make 20 sufficient.
- **Nothing about stewardship.** Untouched, and it needs a decision about
  Egeria's own model rather than an inference from ours.

## 5. Honest limits

- **Two resources.** Both Egeria-family, both large. `petclinic` (1 component)
  and the small-repo case are not measured here, and a presentation that works
  at 451 may be silly at 1.
- **The 20-row cap is measured; readability is not.** Nobody has watched a
  curator use this. Everything above is derived from payload against renderer,
  which finds dropped distinctions and cannot find confusing ones.
