# Architecture ground truth — pre-registered partitions

Hand-written component partitions for the Phase 0 architecture-recovery spike
(`docs/architecture-recovery-phase0-plan.md` §4).

## Why these are committed before the spike runs

The Phase 0 exit criterion is whether detector output matches a human's reading of the
architecture. If the human reads the detector output first, that criterion is unfalsifiable —
any coherent-looking clustering is easy to rationalise after the fact, so nothing would ever
fail. Committing the expected answer first makes the comparison meaningful.

## Rules

1. **Written by hand, by a maintainer** — never generated, and never drafted from detector
   output or by an assistant that has already read the repo. A partition inferred from the
   code and then compared against the code measures nothing.
2. **Committed before the detectors are first run** against that target. The commit timestamp
   is the evidence.
3. **Not edited afterwards.** If the detectors show the ground truth was wrong, that is a
   finding for the write-up — not a file to correct. This rule is what the whole exercise
   rests on.

Corrections do belong in a *new* file (`{target}-revised.yaml`) with a note explaining what
changed and why, so both versions survive.

## Why these live in `tests/fixtures/` rather than with the spike

`scripts/arch-spike/` is explicitly throwaway. These are not: once Phase 1 exists, they become
regression fixtures for the real detectors. They should outlive the spike that motivated them.

## Partial partitions are expected

Docs, CI config, and test files often belong to no component. Say so in `unassigned_ok` rather
than leaving it implicit — scoring only covers files that both sides placed, and coverage is
reported separately (plan §5).

## Files

| File | Target | Notes |
|---|---|---|
| `trellis.md` | the trellis monorepo (this repo) | no deployment artifacts at all — the premise test |
| `egeria-workspaces.md` | `dwolfson/egeria-workspaces`, `-fs` checkout | two blueprints; see its own notes |
| `egeria.md` | `odpi/egeria` | top level of `open-metadata-implementation` only |
| `_TEMPLATE.md` | — | copy this for a new target |
| `validate.py` | — | parses and checks one file; see below |

## Perspective and vocabulary — read this before writing one

A partition is only meaningful **within a perspective** (design doc §4.1). Every file declares
one in its header, and it determines two things:

| Perspective | `Vocabulary` for `Type:` | File globs |
|---|---|---|
| `logical` | `SolutionComponentType` — the closed 13 (§3.1) | required |
| `deployment` | Area 0 `SoftwareCapability` subtypes — `Application`, `EventBroker`, … | optional |
| `physical` / `dev` | Area 0 model 0280 — `SourceCodeFile`, `BuildInstructionFile`, … | required |

**Do not mix them in one file**, and do not translate between them — `Application` (a deployed
capability) and `Software Service` (a designed component) are one system seen from two layers,
joined by `ImplementedBy`, not two names for one thing (§4.2).

Deployment components frequently own **no first-party files at all** — `kafka`, `postgres` and
`kroki` are third-party images. That is why globs are optional there, and why file-partition
scoring does not apply to that perspective; only component-set agreement does (plan §5a).

An optional `Scope:` line narrows which paths count. Without it, coverage on a monorepo is
meaningless: trellis ground truth excludes `packages/egeria-advisor` (879 files), so whole-repo
coverage reads 15% where in-scope coverage is 48%.

## Provenance

Each component carries a `Provenance:` line — `maintainer`, `maintainer (type assigned by
assistant)`, `assistant`, and so on. Scoring can then be reported twice: maintainer-authored
only, and maintainer-plus-assisted. The contamination is measured rather than denied, which is
the only honest way to accept assistance in a pre-registered artifact.

## Format

Markdown, loosely following this repo's Dr.Egeria convention (`##` section, `###` item):
`## Blueprints` / `## Components` / `## Unassigned OK` / `## Excluded — not first-party`,
with one `###` heading per blueprint or component and `- **Label:** value` bullets beneath.
Blockquotes are guidance and are ignored by the parser, so instructions can stay in the file.

## Validating

```
python3 validate.py trellis.md
```

Checks that every component has one of the 13 valid types, that every glob matches at least
one real file, that blueprints only reference defined components, and that the `Written by` /
`Written at` fields are filled in — a pre-registration without a date is not one. Warns on
files claimed by two components (legal, but usually a slip). Non-zero exit on any error.

`score.py` consumes the same parse, so a file that validates is a file the spike can read.

## Development fixture vs held-out fixtures (added 2026-08-23)

Rule 3 forbids editing a fixture after the fact. It does not, on its own, stop the subtler version of
the same mistake: **iterating something else until a fixture scores well.** A prompt revised until
`prometheus.md` reads 11/11 has fitted the fixture just as surely as editing the fixture would have,
and design §5.5c says the same thing about weights — *"a weight fitted to make `prometheus.md` score
11/11 makes that 11/11 meaningless."*

Prompts, weights, thresholds and filter rules are all the same hazard. So:

| fixture | status | ground truth written by |
|---|---|---|
| `prometheus.md` | **DEV** — iterate against it freely | owner-published doc |
| `milvus.md` | **HELD OUT** | owner-published doc |
| `kubernetes.md` | **DEV** (moved 2026-08-23) — the entry-point partition check was derived from its failure | owner-published doc |
| `trellis.md` | **HELD OUT** | maintainer |
| `egeria-workspaces.md` | **HELD OUT** | maintainer |

**Dev-fixture scores are a development signal, not a result**, and must be labelled as such wherever
they are quoted. A held-out fixture is run **once**, after the thing being developed is settled, and
that run is the measurement.

If a held-out fixture is ever used for iteration it should be moved to DEV in this table rather than
quietly reused — the table is only useful if it is honest about which numbers still mean something.

Note the second column: `trellis.md` and `egeria-workspaces.md` are the only fixtures whose ground
truth was **written by the maintainer** rather than transcribed from a project's published
architecture document. They are therefore the only fixtures against which an adjudicator that is
*given* the published architecture doc could ever be measured honestly — scoring that against the
other three would be measuring transcription against transcription.
