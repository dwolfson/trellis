# Ground-truth partition — <target>

> **PRE-REGISTERED.** Write this by hand and commit it **before** running any detector
> against this target, then do not edit it. See `README.md` for why.
> Valid component types: `docs/architecture-recovery-design.md` §3.1 (13 values).

**Target:** <repo name>
**Checkout:** <path used — some repos have several>
**Written by:** <name>
**Written at:** <YYYY-MM-DD, must precede the first detector run>

---

## Blueprints

> Omit this whole section for a repo that ships one solution.
> A blueprint is a *solution deployment* — not a compose file, and not a runtime mode
> (design doc §8.2b). A component may appear in more than one blueprint.

### <Solution name>

- <Component name>
- <Component name>

---

## Components

### <Component name>

- **Type:** <one of the 13 SolutionComponentType values>
- **Files:**
  - `<glob>`
- **Identity:** <optional — what makes this one component: deployment unit / package / path>
- **Notes:** <optional — anything a detector could not see>

---

## Unassigned OK

> First-party paths legitimately belonging to no component. Not a dumping ground —
> anything listed here is excluded from scoring, so over-listing hides real misses.

- `<glob>`

---

## Excluded — not first-party

> Vendored or generated trees that should never reach the identity logic at all
> (plan §3a). Distinct from *Unassigned OK*: those are unowned first-party files,
> these are not first-party at all.

- `<glob>`
