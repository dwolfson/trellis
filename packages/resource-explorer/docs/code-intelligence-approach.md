# Code Intelligence: Symbol Extraction and Inventory

## Problem Statement

The current system can answer semantic questions about code ("how is authentication implemented?") by searching vector chunks. It cannot answer structural questions:

- "How many classes does egeria have?"
- "List all public methods in the ingestion pipeline."
- "What does the `CodeParser.parse` method return?"
- "Show me the signature for `query_project_stats`."
- "Which files define a class called `Agent`?"

These questions have precise, structured answers that require AST-level understanding — not similarity search. The current `CodeParser` does fixed-size token windows with no language structure awareness (there is a `# TODO` for this at `code_parser.py:43`).

---

## Design Overview

Two complementary additions:

1. **`CodeSymbolExtractor`** — runs during ingestion alongside the existing chunker; uses Python's `ast` module for Python files and regex for other languages; writes extracted symbols to a new SQLite table.
2. **`query_code_symbols` tool** — a BeeAI `@tool` that answers counting, listing, and signature queries against the symbol table, without touching Milvus.

The vector store keeps its role for semantic ("what does X do?") queries. The symbol table handles structural ("list X", "how many X", "signature of X") queries.

---

## Symbol Extraction

### What to Extract

| Kind | Python | JavaScript/TS | Java | Go |
|---|---|---|---|---|
| `class` | `ClassDef` | `class Foo` | `class Foo` | `type Foo struct` |
| `interface` | — | `interface Foo` | `interface Foo` | `type Foo interface` |
| `function` | top-level `FunctionDef` | top-level `function` / arrow | static methods | top-level `func` |
| `method` | `FunctionDef` inside `ClassDef` | method inside class | instance methods | methods on a type |
| `enum` | — | `enum Foo` | `enum Foo` | `iota` const blocks (best-effort) |

Per symbol, extract:
- `name` — simple name: `parse`
- `qualified_name` — fully qualified within file: `CodeParser.parse`
- `signature` — parameter list with type hints if present: `(self, file_path: str, content: str, project_slug: str) -> list[CodeChunk]`
- `docstring` — first string literal in the body, trimmed
- `start_line`, `end_line` — for citation
- `file_path` — relative to repo root

### Language Strategy

**Python — AST (stdlib, zero new dependencies):**

```python
import ast

class SymbolVisitor(ast.NodeVisitor):
    def __init__(self, source: str, file_path: str, project_slug: str):
        self.source = source
        self.symbols: list[dict] = []
        self._class_stack: list[str] = []
        self.file_path = file_path
        self.project_slug = project_slug

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.symbols.append(self._make(node, "class", node.name))
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def _visit_func(self, node) -> None:
        kind = "method" if self._class_stack else "function"
        self.symbols.append(self._make(node, kind, node.name))
        # Don't recurse into nested functions — they clutter the index

    def _make(self, node, kind: str, name: str) -> dict:
        qualified = ".".join(self._class_stack + [name])
        sig = self._signature(node) if kind != "class" else ""
        doc = (ast.get_docstring(node) or "").split("\n")[0].strip()  # first line only
        return dict(
            project_slug=self.project_slug,
            file_path=self.file_path,
            language="python",
            kind=kind,
            name=name,
            qualified_name=qualified,
            signature=sig,
            docstring=doc,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
        )

    def _signature(self, node) -> str:
        args = node.args
        parts = []
        # positional args with annotations
        for arg in args.args:
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            parts.append(s)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        ret = ""
        if node.returns:
            ret = f" -> {ast.unparse(node.returns)}"
        return f"({', '.join(parts)}){ret}"
```

**JavaScript / TypeScript — regex (pragmatic, no new deps):**

Patterns cover the common cases: named functions, class declarations, arrow functions assigned to `const`, and class methods. TypeScript type annotations are preserved verbatim in the signature string but not parsed.

```python
import re

_JS_CLASS    = re.compile(r'^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)', re.M)
_JS_IFACE    = re.compile(r'^(?:export\s+)?interface\s+(\w+)', re.M)
_JS_FUNC     = re.compile(r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(\([^)]*\))', re.M)
_JS_ARROW    = re.compile(r'^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*(?::\s*\S+\s*)?=>', re.M)
_JS_METHOD   = re.compile(r'^\s+(?:async\s+)?(\w+)\s*(\([^)]*\))\s*(?::\s*\S+\s*)?[{]', re.M)
```

**Java — regex:**

Captures `public|private|protected` methods and class declarations including generics. Return types are included in the signature.

```python
_JAVA_CLASS  = re.compile(r'(?:public|private|protected|abstract|final|\s)+class\s+(\w+)', re.M)
_JAVA_IFACE  = re.compile(r'(?:public|private|protected|\s)+interface\s+(\w+)', re.M)
_JAVA_METHOD = re.compile(
    r'(?:public|private|protected|static|final|abstract|\s)+'
    r'(?:<[^>]+>\s+)?(\w[\w<>\[\]]*)\s+(\w+)\s*(\([^)]*\))',
    re.M,
)
```

**Go — regex:**

Go functions have a distinctive `func (receiver) Name(params) (returns)` syntax that regex handles reliably.

```python
_GO_FUNC     = re.compile(r'^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*(\([^)]*\))', re.M)
_GO_STRUCT   = re.compile(r'^type\s+(\w+)\s+struct\b', re.M)
_GO_IFACE    = re.compile(r'^type\s+(\w+)\s+interface\b', re.M)
```

### `CodeSymbolExtractor` Class

```python
class CodeSymbolExtractor:
    """Extract class/function/method symbols from source files during ingestion."""

    def extract(self, file_path: str, content: str, project_slug: str, language: str) -> list[dict]:
        if language == "python":
            return self._extract_python(file_path, content, project_slug)
        elif language in ("javascript", "typescript"):
            return self._extract_js(file_path, content, project_slug, language)
        elif language == "java":
            return self._extract_java(file_path, content, project_slug)
        elif language == "go":
            return self._extract_go(file_path, content, project_slug)
        return []
```

### Placement in the Ingestion Pipeline

`IngestionPipeline._ingest_collection()` already calls `CodeParser.parse(file_path, content, slug)` for each file. The `CodeSymbolExtractor` is called on the same content in the same loop, with its output batched into a registry write:

```python
# In IngestionPipeline._ingest_code_collection()
extractor = CodeSymbolExtractor()
all_symbols: list[dict] = []
for file_path, content in files:
    chunks = parser.parse(file_path, content, slug)
    # ... embed and store chunks as before ...
    symbols = extractor.extract(file_path, content, slug, language)
    all_symbols.extend(symbols)

# Bulk write — one transaction
registry.upsert_code_symbols(slug, all_symbols)
```

On `refresh`, the symbol table for affected collections is cleared and repopulated alongside the Milvus re-ingestion.

---

## Storage

### New SQLite Table: `project_code_symbols`

Added to `registry.py` `_init_schema()`:

```sql
CREATE TABLE IF NOT EXISTS project_code_symbols (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug   TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    language       TEXT NOT NULL,
    kind           TEXT NOT NULL,        -- class | function | method | interface | enum
    name           TEXT NOT NULL,
    qualified_name TEXT NOT NULL,        -- e.g. "CodeParser.parse"
    signature      TEXT DEFAULT '',      -- e.g. "(self, file_path: str) -> list[CodeChunk]"
    docstring      TEXT DEFAULT '',      -- first line of docstring; empty if none
    summary        TEXT DEFAULT '',      -- LLM-generated one-liner; populated lazily
    start_line     INTEGER DEFAULT 0,
    end_line       INTEGER DEFAULT 0,
    UNIQUE(project_slug, file_path, qualified_name),
    FOREIGN KEY (project_slug) REFERENCES projects(slug)
);
CREATE INDEX IF NOT EXISTS idx_symbols_slug_kind
    ON project_code_symbols(project_slug, kind);
CREATE INDEX IF NOT EXISTS idx_symbols_name
    ON project_code_symbols(project_slug, name);
```

`UNIQUE(project_slug, file_path, qualified_name)` allows `INSERT OR REPLACE` for idempotent refresh.

### `summary` Column — Lazy Population

On first request for a summary (via the `get_symbol_detail` tool or a "what does X do?" query), if `docstring` is empty, the LLM generates a one-sentence summary from the symbol's source text and it is persisted. Summaries for symbols that have docstrings are derived directly from the docstring without an LLM call.

---

## Agent Tools

Two new `@tool` functions in `explorer/agents/tools.py`:

### `query_code_symbols`

Handles counting, listing, and filtering:

```python
@tool(description=(
    "List or count classes, functions, and methods defined in a project's source code. "
    "kind can be 'class', 'function', 'method', 'interface', or 'all' (default). "
    "pattern filters by name substring (case-insensitive). "
    "file_path filters to a specific file or directory prefix. "
    "Returns name, qualified_name, signature, and docstring for each match."
))
def query_code_symbols(
    project_slug: str,
    kind: str = "all",
    pattern: str = "",
    file_path: str = "",
    limit: int = 50,
) -> str:
    import sqlite3
    from explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    slug = registry._normalize_slug(project_slug)
    try:
        conn = sqlite3.connect(registry.db_path)
        conn.row_factory = sqlite3.Row
        filters = ["project_slug = ?"]
        params: list = [slug]
        if kind and kind != "all":
            filters.append("kind = ?")
            params.append(kind)
        if pattern:
            filters.append("name LIKE ?")
            params.append(f"%{pattern}%")
        if file_path:
            filters.append("file_path LIKE ?")
            params.append(f"{file_path}%")
        where = " AND ".join(filters)
        rows = conn.execute(
            f"SELECT kind, qualified_name, signature, docstring, file_path, start_line "
            f"FROM project_code_symbols WHERE {where} "
            f"ORDER BY file_path, start_line LIMIT ?",
            params + [limit],
        ).fetchall()
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM project_code_symbols WHERE {where}",
            params,
        ).fetchone()
        conn.close()
    except Exception as exc:
        return f"Error reading symbol table: {exc}"

    if not rows:
        return f"No {kind} symbols found in '{slug}'" + (f" matching '{pattern}'" if pattern else "") + "."

    total = count_row[0]
    lines = [f"{total} {kind if kind != 'all' else 'symbol'}(s) in {slug}" +
             (f" matching '{pattern}'" if pattern else "") +
             (f" — showing first {limit}" if total > limit else "") + ":"]
    for r in rows:
        sig = f"  {r['signature']}" if r['signature'] else ""
        doc = f"  # {r['docstring']}" if r['docstring'] else ""
        lines.append(f"\n[{r['kind']}] {r['qualified_name']}{sig}")
        lines.append(f"  {r['file_path']}:{r['start_line']}{doc}")
    return "\n".join(lines)
```

### `get_symbol_detail`

Returns full detail for a named symbol, including LLM summary generation if the docstring is absent:

```python
@tool(description=(
    "Get the full signature, docstring, and purpose summary for a specific class or method. "
    "name can be a simple name ('parse') or qualified name ('CodeParser.parse'). "
    "If the symbol has no docstring, a summary is generated from its source."
))
def get_symbol_detail(project_slug: str, name: str) -> str:
    import sqlite3
    from explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    slug = registry._normalize_slug(project_slug)
    try:
        conn = sqlite3.connect(registry.db_path)
        conn.row_factory = sqlite3.Row
        # Try qualified name first, then simple name
        row = conn.execute(
            "SELECT * FROM project_code_symbols "
            "WHERE project_slug = ? AND (qualified_name = ? OR name = ?) "
            "ORDER BY kind DESC LIMIT 1",  # prefer class over function if both match
            (slug, name, name),
        ).fetchone()
        conn.close()
    except Exception as exc:
        return f"Error: {exc}"

    if not row:
        return f"Symbol '{name}' not found in '{slug}'. Try query_code_symbols to list available symbols."

    r = dict(row)
    summary = r["summary"] or r["docstring"] or _generate_summary(slug, r)
    lines = [
        f"[{r['kind']}] {r['qualified_name']}",
        f"File: {r['file_path']} (lines {r['start_line']}–{r['end_line']})",
    ]
    if r["signature"]:
        lines.append(f"Signature: {r['signature']}")
    lines.append(f"Purpose: {summary}")
    return "\n".join(lines)
```

`_generate_summary` fetches the source lines, passes them to `get_llm().complete()` with a short prompt ("Summarize this function in one sentence:"), then persists the result in the `summary` column.

---

## Query Routing

Add a `code_inventory` intent in `config/routing.yaml` (higher priority than `code_search`):

```yaml
code_inventory:
  priority: HIGH
  patterns:
    - 'how many (class\w*|method\w*|function\w*|interface\w*)'
    - 'list (all )?(class\w*|method\w*|function\w*|interface\w*)'
    - 'what class\w* (are|does|exist)'
    - 'show (me )?(the )?(class\w*|method\w*|function\w*|api surface|public interface)'
    - 'signature (of|for) .+'
    - 'what does .+ (class|method|function) do'
    - '(class|method|function|interface) (called|named) .+'
```

`code_inventory` is routed to `CodeAgent` (which gains `query_code_symbols` and `get_symbol_detail` in its `tools()` list) rather than to a new agent, since the existing `CodeAgent` already has the right system prompt for code-related questions.

---

## Counting and Listing Examples

After implementation, these queries resolve via `query_code_symbols` without any Milvus lookup:

| Query | Tool call | Expected output |
|---|---|---|
| "How many classes does egeria have?" | `query_code_symbols("egeria", kind="class")` | "247 class(es) in egeria" |
| "List all classes in the ingestion module" | `query_code_symbols("pe", kind="class", file_path="explorer/ingestion/")` | Class list with signatures |
| "What methods does CodeParser have?" | `query_code_symbols("pe", kind="method", pattern="CodeParser")` | Method list with signatures |
| "Show me the signature of parse" | `get_symbol_detail("pe", "CodeParser.parse")` | Full sig + docstring |
| "How many public functions are there?" | `query_code_symbols("egeria", kind="function")` | Count + list |

---

## Display and Formatting

The `query_code_symbols` tool returns structured plain text that the LLM reformats naturally. For the web UI, the `_done` SSE event can include a `symbol_table` field when the intent is `code_inventory`:

```json
{
  "t": "done",
  "intent": "code_inventory",
  "symbol_table": {
    "kind": "class",
    "project": "egeria",
    "total": 247,
    "items": [
      {"name": "CodeParser", "file": "ingestion/code_parser.py", "line": 14, "doc": "Splits source files into chunks suitable for embedding."},
      ...
    ]
  }
}
```

The frontend renders this as a sortable, searchable table when the `symbol_table` field is present — similar to how the `chart` field triggers a Plotly render.

---

## Implementation Order

### Phase 1 — Python extraction ✅ IMPLEMENTED
1. `CodeSymbolExtractor` in `explorer/ingestion/code_symbol_extractor.py` — Python AST only
2. `project_code_symbols` table + `upsert_code_symbols()` in `registry.py`
3. Wire extractor into `IngestionPipeline._ingest_collection()` for `python_code` collections
4. `query_code_symbols` tool in `agents/tools.py`
5. `code_inventory` patterns in `config/routing.yaml`
6. Add `query_code_symbols` to `CodeAgent.tools()`

### Phase 2 — Other languages + detail queries ✅ IMPLEMENTED
7. Regex extractors for JS/TS, Java, Go in `CodeSymbolExtractor`
8. Wire extractor for `javascript_code`, `java_code`, `go_code` collections
9. `get_symbol_detail` tool with lazy LLM summary generation
10. `_generate_summary` helper + `summary` column population
11. `extract_symbols_only()` in `IngestionPipeline` for lightweight backfill
12. `refresh --symbols` CLI flag for backfilling existing projects

### Phase 3 — Web UI display
13. `symbol_table` field in `_done` SSE event
14. Frontend: sortable/searchable symbol table component (rendered when `symbol_table` present)
15. `compare_symbols` view for comparison queries: side-by-side class counts and public API surface diff

Phase 1 and Phase 2 are complete. Phase 3 is a display enhancement that can be added incrementally.
