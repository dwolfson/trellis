# Ground-truth partition — trellis (REVISED)

> **Revision of `trellis.md`, not a replacement.** The original stays as written and as
> pre-registered; `README.md` rule 3 forbids editing it. This file records what the maintainer
> decided after seeing what the detectors surfaced, and **why** — the reasoning is the durable
> part, since it answers the next twenty cases rather than these three.

**Target:** trellis
**Checkout:** `/Users/dwolfson/localGit/egeria-v6/trellis`
**Perspective:** logical
**Revises:** `trellis.md` (pre-registered 2026-08-20)
**Written by:** dwolfson (decisions), assistant (transcription and the measurement below)
**Written at:** 2026-08-20

> **This is a delta and does not validate standalone.** `validate.py` will report zero components,
> which is correct: the file lists *additional* file assignments to components defined in
> `trellis.md`, not a whole partition. Applying a delta on top of a base fixture is not supported
> by the tooling — scoring still runs against `trellis.md`. Recorded as prose deliberately, because
> a half-machine-readable file that silently scores wrong would be worse than one that plainly does
> not score at all.

---

## What changed and why

The residue rule (spike README finding 44) surfaced three directories the original fixture never
assigned to any component: `github/`, `configdata/` and `dashboard/`. Asked where they belong, the
maintainer's answer was **not** "here is the component that owns them" but something more useful:
*the code is in the wrong place.*

That is architecture recovery doing the job it exists for. The tool did not describe the
architecture; it found where the code disagrees with the intended one.

### `configdata/` → **Core**

Configuration support for the RE module itself. It is package data rather than a subsystem, and
Core is where package-level concerns live.

### `dashboard/` → **Web backend**, provisionally

Presentation helpers for rendering result output. Imported by `web/routes/query.py`,
`web/routes/stats.py` and `cli/main.py` — two consumers, both presentation surfaces. The
maintainer's note that it "might not be properly organized" is fair: a helper shared by web and
CLI is not obviously *part of* either, and this assignment should be revisited if a presentation
component is ever named explicitly.

### `github/` → **Core**, and the maintainer's first instinct was measurably wrong

The initial read was *"these are utilities to fetch git data and statistics, so they are
effectively used by surveyors — you could move that folder."*

**The dependency data disagrees, and this is worth recording rather than quietly overriding.**
`resource_explorer.github` is imported by **six** subsystems:

| importer | files |
|---|---|
| `web/routes` | 2 |
| `surveyors/sub_surveyors` | 2 |
| `ingestion` | 2 |
| `cli` | 2 |
| `surveyors` | 1 |
| `agents` | 1 |

Surveyors are three of eleven importers, not the owner. Moving `github/` under `surveyors/` would
create upward dependencies from `web/`, `ingestion/`, `cli/` and `agents/` **into** `surveyors/`,
which is worse coupling than the current arrangement, not better.

This matches its measured signature exactly: fan-in 22 with dispersion 0.90 — the
**connective-library** shape (finding 34). A shared utility imported evenly by many components is
not misplaced; it is a library, and it belongs with Core or eventually as its own named component.

**The finding stands even though the conclusion flipped.** A human's intuition about where code
belongs, checked against the actual dependency structure, is precisely the interaction this
feature is for — and here the check changed the answer.

---

## Assignments

Additions to `trellis.md`'s components; everything else in that file stands unchanged.

### Core

- **Additional files:**
  - `packages/resource-explorer/resource_explorer/configdata/**`
  - `packages/resource-explorer/resource_explorer/github/**`
- **Notes:** `github/` is a connective library (fan-in 22 across 6 subsystems, dispersion 0.90),
  not a surveyor utility. Candidate to become its own named component later; assigned to Core for
  now because Core is where shared package-level code sits.
- **Provenance:** maintainer (assignment), assistant (the coupling measurement that changed it)

### Web backend

- **Additional files:**
  - `packages/resource-explorer/resource_explorer/dashboard/**`
- **Notes:** Provisional. Shared by `web/routes` and `cli/main.py`; revisit if a presentation
  component is named.
- **Provenance:** maintainer

---

## Residue-ownership rule — decided

`Core` and `Utility scripts` disagreed about whether a component owns nested directories, and the
disagreement was deliberate (finding 44). Decision: **adopt by default, and ask when it is not
obvious.**

The asking surface the maintainer specified: **a file tree with checkboxes**, letting a human mark
which nested directories belong to a component when the signal is ambiguous. That fits
`approach-portfolio-model.md` §5a's rules — non-blocking, skippable, cheap to answer, impossible
to derive — and it is a better shape than a yes/no prompt because the answer is naturally a
*selection*, not a boolean.

Not built. Recorded here as the decided design so it is not re-litigated.

---

## Sub-structure — which components can be nested at all

Added 2026-08-22, after the generator moved from a fixed depth to a stored hierarchy
(`approach-portfolio-model.md` §2a). A flat fixture was being used to score a nested proposal, which
made the containment result harder to read than it needed to be.

**Provenance, and why this is not circular.** These sub-directories are read from `git ls-files` —
a fact about the repo that predates any detector run — **not** from what the generator proposed.
Recording detector output as ground truth is exactly the circularity pre-registration exists to
prevent. What is recorded here is *layout*; whether a given sub-directory is a **genuine
component** is a maintainer judgement and is marked below as unconfirmed.

**The headline: 9 of 11 `resource_explorer` components have no sub-directories at all.**

| component | sub-directories |
|---|---|
| `Agents`, `CLI`, `Textual TUI`, `RAG ingestion`, `Observability`, `Prefect orchestration` | **none — flat** |
| (also `github`, `dashboard`, `configdata`, now assigned to Core/Web backend above) | **none — flat** |
| **`Surveyors`** (87 files) | `arch_recovery`, `database`, `file_classifier`, `filesystem`, `sub_surveyors` |
| **`Web backend` / `Web front-end`** (32 files) | `routes`, `static` |

So **hierarchical and flat scoring are identical for nine of the eleven**, and the whole nested-vs-flat
question turns on two components. That is a much narrower problem than the redesign implied, and it
means the current 9/13 is not really a verdict on hierarchies — it is a verdict on two boundaries.

### The `web` split is the contested one, and the fixture already takes a side

`Web backend` is `web/routes/**` + `web/app.py`; `Web front-end` is `web/static/**` +
`frontend-build/**`. **That split is exactly the directory split** — `routes` and `static`.

The hierarchy generator produced something different: `web` as its own node (holding `app.py` and
one sibling), with `static` absorbed as residue because it has no import cohesion, and `routes` as a
separate cohesive node. Neither ground-truth component is reconstructed exactly, which is the whole
of the 10/13 → 9/13 movement.

**Worth being precise about who is wrong.** The fixture's boundary is defensible and so is the
generator's: `static` is JavaScript with no Python imports, so a cohesion-based signal cannot see it
as belonging with `routes`, while a human knows both are "the web tier". This is not a tuning
failure — it is a signal that **cohesion cannot recover a boundary that spans languages**, which is
the same limit finding 54 found in Java's wildcards and finding 57 in Rust.

### Unconfirmed — maintainer judgement needed

Whether these are genuine components or merely directories is not recorded here, because nobody has
said. The two that matter:

- Are `surveyors/database`, `surveyors/filesystem`, `surveyors/sub_surveyors` (etc.) **components**
  in their own right, or implementation detail of one `Surveyors` component?
- Should `Web backend` and `Web front-end` remain two components when the detector, working from
  imports alone, cannot see the boundary between them?

Neither blocks scoring — containment handles both readings — but answering them would make the
9/13 mean something. **Provenance:** assistant (layout, from `git ls-files`); maintainer judgement
outstanding on component status.
