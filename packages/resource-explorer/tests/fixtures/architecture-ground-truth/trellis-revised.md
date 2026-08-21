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
