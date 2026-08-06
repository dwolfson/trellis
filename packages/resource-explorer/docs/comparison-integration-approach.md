# Comparison and Integration Query Approach

## Problem Statement

Users frequently ask questions that span multiple projects:

- **Comparison**: "How does egeria compare to odpi in community health?"
- **Comparison**: "Which project has more contributors — agentstack or beeai?"
- **Integration**: "Can I use egeria with agentstack?"
- **Integration**: "Which LF AI projects work well together for an MLOps pipeline?"

The current system routes each query to a single project's collections and can only answer within that scope. These cross-project queries fall through to the general RAG path with no multi-project awareness.

---

## Detection

### Comparison Signals

Patterns that identify a comparison intent:

```yaml
comparison:
  - 'compar\w* .+ (vs?\.?|versus|and|with) .+'
  - '(vs?\.?|versus) .+'
  - 'difference between .+ and .+'
  - 'better .+ (or|vs?\.?) .+'
  - 'which .+ (more|most|best|worse|least)'
  - 'rank .+ project'
```

### Integration Signals

```yaml
integration:
  - '(work|use|integrate|combine|connect) .+ (with|and|together)'
  - '(compatible|interoperable|plug.?in) .+ with'
  - 'use .+ alongside'
  - '(stack|pipeline|workflow) .* (using|with) .+ and .+'
```
# Open questions before implementation
* What if one project isn't indexed? — Integration questions require both projects to have content in Milvus. The agent should check and give a useful message if one is missing.
* Two slugs vs. one slug + pattern — "What project is healthier?" has no explicit second project. This needs either cross-project comparison (compare all projects) or a clarification response. Probably the latter is safer initially.
* Scoring integration quality — A "How do I use X with Y" answer synthesized from two codebases may not be grounded in actual integration documentation. The agent should caveat when it's inferring rather than citing explicit docs.
* Display name aliases — "Docling" is straightforward. "Data Prep Toolkit" requires matching a 3-word name against a slug data_prep_kit_git. Worth considering whether projects should have user-defined aliases in the registry.
---

## Architecture

### Routing Priority

The `QueryProcessor` handles these before other intent categories:

```
comparison  →  CompareAgent
integration →  IntegrationAgent (or CompareAgent with integration mode)
statistical →  StatsAgent
health      →  HealthAgent
code_search →  CodeAgent
conceptual  →  DocAgent
general     →  RAGSystem
```

### CompareAgent

Located at `explorer/agents/compare_agent.py`.

**Inputs**: Two or more project slugs extracted from the query.

**Steps**:
1. **Slug extraction** — parse the query for known project slugs using `_infer_project_slug` extended to return multiple matches.
2. **Stats retrieval** — call `query_project_stats` for each slug.
3. **Vector search** — run `vector_search` across the union of collections from all projects, scoped per-project. Deduplication by source collection.
4. **Structured diff** — produce a side-by-side comparison table for numeric stats (stars, forks, contributors, commit activity).
5. **Narrative synthesis** — LLM prompt that receives: the stats diff table + top retrieved chunks per project + the original question.

**Fallback**: If fewer than two slugs can be resolved, ask the user to clarify which projects to compare.

### IntegrationAgent

Focuses on ecosystem fit rather than feature comparison.

**Steps**:
1. Retrieve README and documentation chunks for each project.
2. Search for explicit mentions of the other project(s) in those chunks.
3. Query the stats for shared contributors (intersection of `author_email` in `project_commits`).
4. Synthesize: "These projects share N contributors. Project A's docs mention B in the context of X. They use compatible languages (Y, Z)."

---

## Data Sources

| Query Type | Primary Source | Secondary Source |
|---|---|---|
| Numeric comparison | `project_stats` table (SQLite) | GitHub API via `query_project_stats` tool |
| Conceptual comparison | Milvus collections (`markdown_docs`, `web_docs`) | `api_reference` collections |
| Integration fit | `markdown_docs` (README, guides) | `project_commits` shared-author lookup |
| Shared contributors | `project_commits` table | `query_top_committers` tool |

---

## Extended Statistics

The egeria-advisor project (`/Users/dwolfson/localGit/egeria-v5-1/openlineage/dev/get_contributor_stats.py`) provides a contributor-centric analytics model that fills significant gaps in what the current system can answer. The additions below are designed to make the existing `project_commits` table richer and to enable queries like "who is driving most of the code change?" and "is this contributor core or occasional?"

### Current Gaps

| Metric | Egeria-Advisor | Current Project |
|---|---|---|
| Per-author additions / deletions | Yes | No |
| Per-author PR count | Yes | No |
| Community tier (core / regular / occasional) | Yes (committer/non-committer) | No |
| Metrics relative to team baseline | Yes | No |
| Configurable date ranges | Yes | Fixed 30d / 90d only |
| Code churn per period | Yes | No |

### Schema Changes

**`project_commits` — add two columns:**

```sql
ALTER TABLE project_commits ADD COLUMN additions INTEGER DEFAULT 0;
ALTER TABLE project_commits ADD COLUMN deletions INTEGER DEFAULT 0;
```

PyGitHub exposes `commit.stats.additions` and `commit.stats.deletions` per commit. These are included in the same API call as the commit metadata and cost no extra requests when fetched as part of `repo.get_commits()`.

**New table: `project_contributor_stats`**

Aggregated per-contributor, per-period metrics — pre-computed at `refresh` time so agent tools can query without re-scanning the full commits table:

```sql
CREATE TABLE IF NOT EXISTS project_contributor_stats (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug  TEXT NOT NULL,
    period_start  TEXT NOT NULL,   -- ISO date, e.g. "2025-01-01"
    period_end    TEXT NOT NULL,   -- ISO date, e.g. "2025-04-28"
    author_email  TEXT NOT NULL,
    author_name   TEXT NOT NULL,
    commits       INTEGER DEFAULT 0,
    additions     INTEGER DEFAULT 0,
    deletions     INTEGER DEFAULT 0,
    prs           INTEGER DEFAULT 0,
    tier          TEXT DEFAULT '',  -- "core" | "regular" | "occasional"
    UNIQUE(project_slug, period_start, period_end, author_email),
    FOREIGN KEY (project_slug) REFERENCES projects(slug)
);
```

### Tier Classification

Derived from commit frequency within the period, benchmarked against the project's own distribution (not a global threshold):

| Tier | Criterion |
|---|---|
| `core` | Commits ≥ 75th percentile for the project in the period |
| `regular` | Commits ≥ 25th percentile |
| `occasional` | Below 25th percentile |

This relative classification avoids the problem where a threshold like "5+ commits = core" makes no sense for a low-volume research repo vs. a high-velocity infrastructure project.

### New / Extended Agent Tools

```python
@tool
def query_contributor_profile(project_slug: str, author: str, days: int = 90) -> str:
    """
    Return a detailed profile for a specific contributor: commit count, lines added/deleted,
    tier classification, and their activity relative to the project median.
    author can be a name or email; fuzzy matched against project_commits.
    """

@tool
def query_commit_activity(project_slug: str, weeks: int = 13) -> str:
    """
    Return weekly commit trend (existing tool) — extend to also return
    additions/deletions per week so churn is visible alongside frequency.
    """

@tool
def query_project_stats(project_slug: str, days: int = 90) -> str:
    """
    Existing tool — extend the days parameter (currently fixed at 30/90)
    so callers can request any window: query_project_stats("egeria", days=180).
    """
```

### StatsFetcher Changes

`_fetch_commits()` already iterates `repo.get_commits()`. Two additions:

1. Store `commit.stats.additions` and `commit.stats.deletions` alongside existing fields.
2. After the commit loop, compute `project_contributor_stats` rows for standard periods (30d, 90d) and write them with `INSERT OR REPLACE`.

Note: `commit.stats` requires one extra GitHub API call per commit (it is not included in the list response). For large repos this is expensive. Mitigate with:
- Only fetch stats for commits in the last 90 days (already the window we fetch)
- Cache: skip commits whose SHA is already in `project_commits` with non-null `additions`
- Rate-limit guard: fall back gracefully if the rate limit is hit; leave additions/deletions as 0

---

## Dynamic Alias System

### Problem

`_infer_project_slug` matches against slugs and `display_name` fields. It fails for:
- Abbreviations: "AIMD" for "ai-model-deployment"
- Marketing names: "Data Prep Toolkit" for slug `data_prep_kit_git`
- Community names: "Egeria Platform" for slug `egeria`
- Typos / alternate spellings: "Egaria" for "egeria"

Hard-coding aliases per project does not scale. Users know the names they use; the system should learn them.

### Storage

New table in the registry:

```sql
CREATE TABLE IF NOT EXISTS project_aliases (
    alias        TEXT NOT NULL,        -- normalized (lowercase, hyphens→underscores)
    project_slug TEXT NOT NULL,
    confirmed_by TEXT DEFAULT 'user',  -- "user" | "auto"
    created_at   TEXT NOT NULL,
    PRIMARY KEY (alias),
    FOREIGN KEY (project_slug) REFERENCES projects(slug)
);
```

`alias` is the primary key — one alias maps to exactly one project. A project can have many aliases.

### Detection Flow

When `_infer_project_slug` (or `_infer_all_project_slugs`) finds no match, before returning `None`:

1. **Exact alias lookup** — check `project_aliases` for a match. If found, return immediately.
2. **Fuzzy candidate** — use `difflib.get_close_matches` (standard library) against all slugs and display names. If a candidate exists above a similarity threshold (0.70), trigger the alias prompt.
3. **No candidate** — fall through to clarification response as before.

```python
def _infer_project_slug(self, query: str) -> str | None:
    # ... existing exact matching logic ...

    # Exact alias lookup
    alias_match = self._lookup_alias(q_normalized)
    if alias_match:
        return alias_match

    # Fuzzy candidate
    candidate = self._fuzzy_candidate(q_normalized)
    if candidate:
        return self._prompt_alias(q_normalized, candidate)

    return None
```

### Alias Prompt — CLI

```
 No exact match for "Data Prep Toolkit". Did you mean "data_prep_kit_git"?
 Remember "data prep toolkit" as an alias for data_prep_kit_git? [y/N]:
```

If the user confirms, write the alias to `project_aliases` and proceed with the matched slug. If declined, fall through to the standard clarification response.

The prompt is issued via `rich.prompt.Confirm` — no change to the agent's handle() signature. The alias write happens before the agent call, so the first query using a new alias already resolves correctly.

### Alias Prompt — Web UI

When the API cannot resolve a slug but has a fuzzy candidate, the `_done` SSE event includes a new field:

```json
{
  "t": "done",
  "intent": "clarification",
  "alias_suggestion": {
    "term": "data prep toolkit",
    "candidate_slug": "data_prep_kit_git",
    "candidate_name": "Data Prep Kit"
  }
}
```

The frontend renders a banner:

> **"Data Prep Toolkit"** looks like it might be **Data Prep Kit**. Remember this alias? [Yes] [No]

A `POST /api/aliases` endpoint writes confirmed aliases:

```json
{ "alias": "data prep toolkit", "project_slug": "data_prep_kit_git" }
```

### Fuzzy Matching Implementation

```python
import difflib

def _fuzzy_candidate(self, term: str) -> str | None:
    from explorer.registry import ProjectRegistry
    candidates = []
    for p in ProjectRegistry().list_all():
        candidates.append(p.slug.lower())
        if p.display_name:
            candidates.append(p.display_name.lower().replace("-", "_").replace(" ", "_"))
    matches = difflib.get_close_matches(term, candidates, n=1, cutoff=0.70)
    if not matches:
        return None
    matched = matches[0]
    # Resolve back to a project slug
    for p in ProjectRegistry().list_all():
        if p.slug.lower() == matched or p.display_name.lower().replace("-", "_").replace(" ", "_") == matched:
            return p.slug
    return None
```

### Alias Management CLI Commands

```bash
# List all aliases for a project
project-explorer aliases list egeria

# Add an alias manually
project-explorer aliases add "Egeria Platform" egeria

# Remove an alias
project-explorer aliases remove "Egeria Platform"
```

---

## Multi-Slug Extraction

The current `_infer_project_slug` returns a single best match. A new `_infer_all_project_slugs` method returns all matches, ordered by position in the query:

```python
def _infer_all_project_slugs(self, query: str) -> list[str]:
    """Return all project slugs that appear in the query (longest match wins per position)."""
    import re
    from explorer.registry import ProjectRegistry
    q = query.lower().replace("-", "_")
    found: list[tuple[int, str]] = []  # (match_start, slug)
    for project in ProjectRegistry().list_all():
        slug = project.slug.lower()
        m = re.search(r"\b" + re.escape(slug) + r"\b", q)
        if m:
            found.append((m.start(), project.slug))
    # Sort by position, deduplicate by slug
    seen: set[str] = set()
    result: list[str] = []
    for _, slug in sorted(found):
        if slug not in seen:
            seen.add(slug)
            result.append(slug)
    return result
```

---

## Prompt Structure for CompareAgent

```
You are comparing two or more LF AI projects. Use the statistics and documentation
excerpts below to answer the user's question with a structured, factual response.

== STATISTICS ==
{side_by_side_stats_table}

== DOCUMENTATION EXCERPTS ==
{per_project_chunks}

== QUESTION ==
{user_query}

Respond with:
1. A brief summary of the key differences
2. A markdown table for numeric comparisons
3. Your recommendation if the user asked for one
```

---

## A2A Integration

The CompareAgent is exposed as port+5 in `agentstack_server.py`. It uses `input_required` state when fewer than two project slugs can be resolved:

```python
if len(slugs) < 2:
    yield TaskStatus(
        state=TaskState.input_required,
        message=Message(parts=[TextPart(text="Which two projects would you like to compare? Available: " + ", ".join(all_slugs))])
    )
    reply = yield
    slugs = self._infer_all_project_slugs(reply.content)
```

---

## Web UI Integration

The sidebar's compare flow:
1. User clicks a second project while holding Shift (or types "compare X vs Y").
2. The chat area shows a split-view with per-project stat cards side-by-side.
3. The chart panel shows a grouped bar chart from `/api/stats/compare/charts/stats?slugs=A,B`.

The `/api/stats/compare/charts/stats` endpoint already exists (`compare_stats_plotly` in `graphs.py`).

---

## Implementation Order

### Phase 1 — Minimum Viable ✅ IMPLEMENTED
1. `_infer_all_project_slugs` in `base.py`
2. `CompareAgent` with stats diff + vector search (also gains `query_code_symbols` + `get_symbol_detail`)
3. Routing patterns in `config/routing.yaml` (comparison + integration signals)

### Phase 2 — Alias System ✅ IMPLEMENTED
4. `project_aliases` table in `registry.py` `_init_schema()` + full CRUD + `fuzzy_candidate()`
5. `_lookup_alias` in `base.py` wired into `_infer_all_project_slugs`
6. CLI alias prompt (`rich.Confirm`) in `ask` command and `InteractiveSession` (deduplicates per-session)
7. `POST /api/aliases`, `GET /api/aliases/{slug}`, `DELETE /api/aliases/{alias}` endpoints; frontend confirmation banner with `alias_suggestion` SSE field
8. `project-explorer aliases list|add|remove` sub-commands in `cli/main.py`

### Phase 3 — Extended Statistics ✅ IMPLEMENTED
9. `additions` / `deletions` columns added to `project_commits` via migration in `_init_schema`
10. `project_contributor_stats` table + `_compute_contributor_stats()` in `StatsFetcher`; tier classification by commit percentile (75th = core, 25th = regular, below = occasional); per-commit stats fetched with graceful rate-limit fallback
11. `query_contributor_profile` tool — fuzzy author name/email match, shows commits, lines added/deleted, tier, relative-to-average comparison
12. `query_project_stats` extended with `days` parameter (default 90; any window 1–365d)
13. `query_commit_activity` extended with `weeks` parameter and shows `(+adds / -dels)` per week when churn data is available

### Phase 4 — Enhancements
14. `IntegrationAgent` (reuses CompareAgent infrastructure with integration-mode prompt)
15. Web UI: Shift+click multi-select in sidebar for comparison
16. A2A: CompareAgent exposed on port+5 with `input_required` for missing slugs

Phases 1 and 2 are independent and can be developed in parallel. Phase 3 depends only on the registry schema work in Phase 2 (step 9 is a migration). Phase 4 builds on all prior phases.

### Dependency: Code Intelligence

Phase 4's "API surface diff" comparison (comparing public classes and methods between projects) depends on the `project_code_symbols` table described in [code-intelligence-approach.md](code-intelligence-approach.md). That work can proceed independently and unlocks the structural comparison view.
