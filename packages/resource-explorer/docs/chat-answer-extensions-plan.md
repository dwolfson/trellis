# Chat answer extensions — design and plan

**Status:** proposed, for coordinator review. Nothing here is built.

**Date:** 2026-10-18

**Builds on:** [cross-resource-chat-extensions-plan.md](cross-resource-chat-extensions-plan.md) (merged in #740),
[chat-guide.md](chat-guide.md).

## 1. Why

Three kinds of question get a weaker answer than the stored data could support:

| Question | Today | Gap |
|---|---|---|
| "Can A integrate with B?" | Answered from documentation, shared contributors and repo-to-database links. | No compatibility facts: dependency overlap and conflicts, license compatibility, interface overlap are stored but never compared. |
| "How often are new features added?" | Release count, latest release and an average interval are stored. | One average only: no trend, no "since when". And "features" needs release notes read. |
| "Is X safe to adopt?", "What breaks if I upgrade Y?", "How do I run this?" | The model improvises from whatever retrieval returns. | Facts that exist (license, CVE, scorecard, maintenance) are never gathered into one answer with gaps named. |

The rule that already governs the chat applies: **tools return measured facts; the model explains them and labels
anything it infers.** Each extension below is a deterministic tool first and a model summary second.

## 2. Principles (carried over)

1. A tool states its coverage. Never run, not established, none found and measured stay distinct
   (`FactLayer` states). A missing fact is never a pass.
2. Read-only. No tool writes; RFA filing stays the propose-then-confirm tool in `agents/rfa_tools.py`, absent from A2A.
3. Bounded output: a default view of a few KB with counts of what was left out, and a parameter to widen it.
4. Agent tools live in `agents/tools.py` as `<name>_raw` plus a thin `@tool` wrapper (BeeAI tools are not callable).
   Logic lives in its own module (`discovery.py`, `history_diff.py` style), so it is testable without an agent.
5. Client and identity rules as elsewhere: no bare pyegeria clients, no environment reads outside `config.py`.

## 3. Extension A — `integration_fit` (A with B)

**Question:** "can A work with B?", "is A compatible with B?"

**Returns** one table per pair, each row a fact with its state:

| Row | Source | Notes |
|---|---|---|
| Shared dependencies, with versions on each side | `project_dependencies` (`dependency_analysis`) | Same package at different versions is shown as a *possible* conflict; **no resolver is run**, so it is never called a conflict. |
| Dependencies one side has that the other lacks | same | Informational. |
| Licenses and risk tiers on each side | `license_classification` | A combination note only for the clear case (strong copyleft with a non-copyleft consumer); otherwise "review". Not legal advice. |
| Languages and runtimes | `repository_health` / language breakdown | Same language is a signal, not a guarantee. |
| Interface surface | `interface_surface`, `api_structure` | Counts and names only; no signature matching in v1. |
| Shared databases | cross-asset links (high only) | Reuses the existing tool, with its caveat. |
| Shared contributors | commits | As today. |

Per side, rows that were never measured are listed under **Gaps**, so "no stored license result for B" cannot read
as "B has no license".

**Where it goes:** `resource_explorer/integration_fit.py` (`fit_between(registry, a, b)`), tool `integration_fit`
for `ConversationAgent` and `IntegrationAgent`. The integration agent's existing evidence compile stays; the table is
added to its evidence.

**Open questions:** (a) which version comparison is safe without a resolver (exact string equality and major-version
difference only?); (b) whether databases and filesystems get a form of this later (schema and connection overlap).

## 4. Extension B — `release_cadence`

**Question:** "how often does X release?", "is it speeding up?", "when was the last release?"

**What the registry holds:** per snapshot of `project_stats`: `releases_count`, `latest_release`,
`latest_release_at`, `avg_release_interval_days`, with `fetched_at`. It does **not** hold a list of releases.

**v1 (no new collection):**
- Latest release and its age, the stored average interval, and the number of releases between two stored
  snapshots (from `releases_count` deltas over `fetched_at`). With enough snapshots this gives a measured recent
  rate against the earlier one.
- States when there is one snapshot only ("cadence trend not established; surveyed once").

**v2 (new data, needs a decision):** store each release's tag and date in the repository survey, which makes the
median gap, the trend and "releases in the last year" exact. This adds a collection step and a table; it is a
separate decision.

**Release notes ("what was added"):** a separate, model-assisted step. It reads indexed documents classified
`release_notes` and the model summarises added features, fixes and breaking changes for named releases. The answer
cites the document and release, and is labelled **inferred from release notes, not measured**. If no release notes
are indexed, it says so. It is not a deterministic tool.

## 5. Extension C — `adoption_check`

**Question:** "is X safe to adopt?", "any concerns using X?"

Gathers, per repository, the existing results into one table with states, then the model summarises:
license tier, known vulnerabilities (`cve_scan`), secrets (`secret_scan`), maintenance (`repository_health`,
`chaoss_metrics`), scorecard (`foss_scorecard`), CI quality, and security features. **No composite score and no
verdict word in the tool**: a single score hides gaps. The tool states how many of the dimensions were measured.

**Open question:** how the model should phrase a conclusion when most dimensions are never-run. Proposed: it must
state "N of M checks have run" first, and may not say "safe".

## 6. Lower priority, model-assisted

| Question | Approach | Guard |
|---|---|---|
| "How do I run this locally?" | Retrieval over README and installation docs. | Cite the passage; say if no installation document is indexed. |
| "What breaks if I upgrade Y?" | Release notes and changelog retrieval for the versions between. | Labelled inferred; needs v2 release data to know which versions lie between. |
| "What does table T mean?" | Draft descriptions from names, columns and neighbours; offer an RFA. | Labelled a draft; filing stays confirm-first. |
| "What changed since the last review?" | Combine `database_schema_changes`, `dependency_changes`, new RFAs. | Deterministic digest; no model needed beyond phrasing. |

## 7. Testing

- Each tool: unit tests on synthetic registries for every state (measured, none found, never run, not established,
  single snapshot).
- A fixture-driven test per question in the guide, asserting the tool called and the key sentences of the answer,
  with the model stubbed.
- Coordinator: run against the laz data set (73 repositories, 20 databases) for timing, output size and plausibility,
  and the guide's **[V1]–[V6]** claims. The first matcher run showed that real data finds what fixtures do not, so
  every extension gets this run before it is called done.

## 8. Plan

| Step | Content | Size |
|---|---|---|
| 1 | `release_cadence` v1, with tests and a guide section. | small |
| 2 | `integration_fit` v1 (dependencies, licenses, languages, interfaces, links), with tests. | medium |
| 3 | `adoption_check`. | small to medium |
| 4 | Coordinator real-data run of steps 1–3 and the guide's V-claims. | — |
| 5 | Decide v2 release collection; then release-notes summarisation. | decision |
| 6 | Model-assisted items in section 6, as asked for. | later |

Each step is its own PR off `main`, with a gate before merge.

## 9. Questions for review

1. Is the "no resolver, so never say conflict" line for dependency versions the right bar?
2. Is `release_cadence` v1 (snapshot deltas) worth shipping before the per-release data, or should it wait for v2?
3. Should `adoption_check` exist as a tool at all, or is the existing evidence compile enough with a new perspective?
4. Anything in the registry that makes any of these cheaper or wrong than described (for example, the stored
   dependency shape across ecosystems)?
