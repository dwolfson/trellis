# Agents, routing, and code analysis

**Status:** consolidated design. Current as of 2026-09-03.
**Scope:** the CLI command agent, a routing/error fix worth not repeating, and
the two different things this codebase calls "code analysis" — one of which now
lives in Resource Explorer. For the live agent table and routing rules, see
`CLAUDE.md`.

> **This document consolidates four** notes from `design/`: the CLI command agent
> design, the agent error and routing fix, the code-analysis tools research, and
> the code-analysis update guide.
>
> **§4 is the part to read first.** The consolidation plan predicted that "code
> analysis moved from EA to RE" would make some of this stale. That is half
> right, and the half that is wrong matters more.

---

## 1. The CLI command agent

`CLICommandAgent` (`advisor/agents/cli_command_agent.py`) handles `hey_egeria`
CLI command lookup and generation — one of the format-specific routes that
`PerspectiveRoutingEngine` dispatches to when a query carries explicit CLI
phrasing.

It is a distinct capability from the CLI *itself* (`egeria-advisor --interactive`,
documented in `user-docs/CLI_GUIDE.md`) and from the agent's user guide
(`user-docs/CLI_COMMAND_AGENT_GUIDE.md`). Three things share the letters "CLI"
here and are routinely confused; only this one is an agent.

## 2. A routing/error fix worth not repeating

Agent mode failed with `generator didn't stop after throw()`.

**The cause was an interaction, not a bug in either part.** MLflow tracking wrapped
an LRU-cached call:

```python
with self.mlflow_tracker.track_operation(...) as tracker:
    response = self._cached_run(query, use_rag)   # LRU-cached
```

When an exception was raised inside the tracking context, the generator-based
context manager tried to handle it while the cache wrapper interfered with
exception propagation.

**The fix moved tracking inside the cached function** rather than around it, so
the context manager and the cache no longer nest. The general shape is worth
carrying: *a generator-based context manager wrapped around a memoised call is a
latent exception-handling bug*, and it surfaces only on the error path — which is
why it survived normal use.

## 3. The two things called "code analysis"

They are unrelated, they were described in separate documents that used the same
phrase, and only one of them moved.

| | **Symbol extraction** | **Repository metrics** |
|---|---|---|
| Produces | classes, methods, inheritance, call relationships | LOC/SLOC, cyclomatic complexity, maintainability index, Halstead |
| Tooling | AST parsing | Radon + Pygount |
| Consumers | `CodeIntelAgent`, `analytics.py` | offline analysis, cached JSON |
| **Owner now** | **Resource Explorer** — see §4a | **still Egeria Advisor** |

---

## 4. Checked against the code, 2026-09-03

### 4a. Symbol extraction did transfer — and the transfer is complete

EA no longer extracts code symbols. It reads Resource Explorer's:

- `advisor/re_code_symbol_reader.py` is a thin reader over
  `resource_explorer.project_code_symbols` / `project_code_relationships`,
  deliberately mirroring `CodeSymbolStore`'s method names so `analytics.py`'s call
  sites did not change — only what backs them. Rows are aliased
  `project_slug AS collection` so existing formatting code needs no edits.
- `advisor/agents/code_intel_agent.py` queries those RE tables directly.
- `advisor/analytics.py` resolves to `get_re_code_symbol_reader()`.

**Both migration phases are done.** The write path was removed from
`ingest_file()` (Phase 8), and the Java extraction helper is marked *"Deprecated,
no longer called from ingest_file()"*.

**The old writer and its tables are kept deliberately.** Per decision D8,
`code_symbol_store.py`'s write path is *deprecated, not deleted*, and
`code_symbols` / `code_relationships` are "left in place, unwritten, as a rollback
safety net". That is a considered state, not drift — worth knowing before someone
tidies away tables that appear unused.

One consequence to be aware of: EA now depends on RE having populated those
tables. A question about code structure is answerable only for repositories
Resource Explorer has surveyed.

### 4b. Repository metrics did **not** transfer, and the tooling is still here

`radon` and `pygount` remain in `pyproject.toml`, and the scripts remain:
`scripts/generate_enhanced_metrics.py`, `scripts/update_all_analysis.sh`.

So `CODE_ANALYSIS_UPDATE_GUIDE`'s instructions are about a capability EA still
owns — they are not made obsolete by the symbol-extraction transfer, and reading
the two documents as one subject would have retired live instructions.

**The cache it writes to is not present.** `data/cache/enhanced_metrics.json` does
not exist on this checkout, so the tooling is live and has not been run here —
or its output was cleared and never regenerated. Anything consuming those metrics
is therefore reading nothing, and the update guide's instructions are the way to
fix that rather than a formality.

### 4c. The routing fix is a closed bug, kept for its shape

`AGENT_ERROR_AND_ROUTING_FIX` records a fix that shipped. It is retained here not
as open work but because the failure mode — a context manager wrapped around a
memoised call, failing only on the exception path — is easy to reintroduce and
hard to find.

---

## 5. Settled — do not reopen without re-measuring

| Question | Settled | On what basis |
|---|---|---|
| Does EA still extract code symbols? | **No** | Reads `resource_explorer.project_code_symbols`; the write path was removed from `ingest_file()` |
| Should `code_symbols` / `code_relationships` be dropped? | **No** — not yet | Kept unwritten as a deliberate rollback net (decision D8) |
| Did repository metrics move to RE too? | **No** | Radon/Pygount and their scripts are still EA's; only symbol extraction transferred |
| Can EA answer code-structure questions about any repository? | **No** | Only those Resource Explorer has surveyed and populated |
| Should MLflow tracking wrap the cached call? | **No** — put it inside | The generator context manager and the LRU wrapper interfere on the exception path |
| Are "CLI agent", "CLI guide" and "CLI command agent guide" the same thing? | **No** | Three distinct surfaces sharing three letters |
