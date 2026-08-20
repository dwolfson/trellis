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
