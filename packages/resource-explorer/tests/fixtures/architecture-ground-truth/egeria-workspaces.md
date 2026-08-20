# Ground-truth partition — egeria-workspaces

> **PRE-REGISTERED.** Write this by hand and commit it **before** running any detector
> against this target, then do not edit it. See `README.md` for why.
> Valid component types: `docs/architecture-recovery-design.md` §3.1 (13 values).

**Target:** egeria-workspaces
**Checkout:** `/Users/dwolfson/localGit/egeria-v6/egeria-workspaces-fs`
(the current one; plain `egeria-workspaces` is ~6 months stale)
**Written by:** <name>
**Written at:** <YYYY-MM-DD>

---

## Blueprints

> Two **solution deployments** (design doc Q8, revised).
>
> The 11 optional runtime add-ons under `compose-configs/optional-associated-runtimes/`
> are **not** blueprints — record their components below and note which solution(s) admit
> each (§8.2b).
>
> The 3 runtime modes (`demo-quickstart` / `local-quickstart` / `freshstart`, selected by
> flags in `demo_config.py`) are **not components at all** — one component, configured.

### QuickStart

- PyegeriaWebHandler (QuickStart)
- <Component name>

### FreshStart

- PyegeriaWebHandler (FreshStart)
- <Component name>

---

## Components

> The two entries below are **already pre-registered by decision** — do not re-open
> (plan §3, T1 item 3): the two `PyegeriaWebHandler` copies are TWO components, split by
> deployment unit.

### PyegeriaWebHandler (QuickStart)

- **Type:** Software Service
- **Files:**
  - `compose-configs/egeria-quickstart/PyegeriaWebHandler/**`
- **Identity:** deployment unit — QuickStart, pre-configured environment

### PyegeriaWebHandler (FreshStart)

- **Type:** Software Service
- **Files:**
  - `compose-configs/egeria-freshstart/PyegeriaWebHandler/**`
- **Identity:** deployment unit — FreshStart, unconfigured environment
- **Notes:** Near-subset of the QuickStart copy — 90 of its 94 first-party files share a
  relative path, 60 byte-identical and 30 divergent. Divergence is partly intentional; see
  `compose-configs/ENVIRONMENT_DIVERGENCE.md`.

### <Component name>

- **Type:** <one of the 13 values>
- **Files:**
  - `<glob>`
- **Identity:** <optional>
- **Notes:** <optional>

---

## Unassigned OK

- `<glob>`

---

## Excluded — not first-party

> `node_modules` **is tracked** in this repo — 1697 of 1703 tracked `.js` files.

- `obsidian-plugins/**/node_modules/**`
- `<glob>`
