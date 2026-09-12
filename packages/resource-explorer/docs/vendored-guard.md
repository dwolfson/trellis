# The vendored-walk guard, and the record of it failing

**2026-09-12.** `tests/test_vendored.py::TestEveryWalkReadsTheRule`
exists because PR #36 fixed the ingestion pipeline's tree walks and missed
the survey step's duplicate of one of them, which put 20,654 vendored
symbols back one survey later. The rule is one function,
`resource_explorer/ingestion/vendored.py`; the guard's job is that no
walk over a repository's tree can be added without consulting it.

## Why it was rewritten

The first guard (#39) was two regex literals and a file-level substring
test: any file containing `rglob("*")` or `os.walk(` had to mention
`is_vendored` *somewhere*. Reviewed by the designer on 2026-09-12, it
missed exactly the shape it was built for:

- a bare walk **appended to a file that already reads the rule** —
  `pipeline.py` mentions `is_vendored` five times, so a sixth walk there
  was invisible; that is the "duplicated rather than imported" regression
  itself;
- `rglob("*.pdf")`, `rglob("*.py")`, `glob("**/*")`, `Path.walk()` —
  the PDF walks were already outside the detector;
- anything outside `surveyors/` and `ingestion/` — `cli/wizard.py` walked
  a user-supplied docs directory with no rule;
- an allowlist entry whose file was renamed died silently.

The rewrite is per **function** and **AST**-based over the whole package:
every function containing a tree walk (`.rglob(...)`, `os.walk(...)`,
`.walk(...)` on a path-like receiver, `.glob("**...")`) must reach
`is_vendored` / `is_vendored_abs` / `VENDORED_DIRS` through its own
call graph, resolved transitively within the module. The allowlist is
keyed by (module, function) and every entry must still name a function
that contains a walk.

## Made to fail, on purpose

A green guard proves only that it did not fire. Three deliberate failures,
each reverted after capture:

**1. A bare walk appended to `pipeline.py`** — the file the first guard
could not see into:

```
E       AssertionError: functions that walk a tree and never reach the vendored rule (module, function, line of first walk): ingestion/pipeline.py:_sixth_walk@902
E       assert [('ingestion/...h_walk', 902)] == []
E         
E         Left contains one more item: ('ingestion/pipeline.py', '_sixth_walk', 902)
E         Use -v to get more diff
1 failed, 9 deselected, 2 warnings in 3.30s
```

**2. An allowlist entry removed** — the exempt walk becomes an offender:

```
E       AssertionError: functions that walk a tree and never reach the vendored rule (module, function, line of first walk): ingestion/line_census.py:census_tree@256
E       assert [('ingestion/...s_tree', 256)] == []
E         
E         Left contains one more item: ('ingestion/line_census.py', 'census_tree', 256)
E         Use -v to get more diff
1 failed, 9 deselected, 2 warnings in 3.72s
```

**3. An allowlist entry naming a function that does not exist** — the
rename case, which used to pass silently:

```
E       AssertionError: allowlist entries that no longer name a walk (renamed or removed?): [('ingestion/pipeline.py', '_walk_that_was_renamed')]
E       assert [('ingestion/...was_renamed')] == []
E         
E         Left contains one more item: ('ingestion/pipeline.py', '_walk_that_was_renamed')
E         Use -v to get more diff
1 failed, 9 deselected, 2 warnings in 3.27s
```

## What the allowlist holds, and why

| module : function | why it may skip the rule |
|---|---|
| `ingestion/line_census.py : census_tree` | reads `VENDORED_DIRS` by its old name `_EXCLUDED_DIRS`; pinned by test |
| `ingestion/dependency_parser.py : parse` | manifest walk; excludes vendor/node_modules ad hoc per manifest kind |
| `ingestion/pipeline.py : _store_file_inventory` | records **every** file on purpose — the inventory carries provenance rather than dropping files; `registry.upsert_file_inventory` stamps the flag |
| `surveyors/arch_recovery/* ` (four functions) | arch recovery has its own exclusion module |
| `github/source_cache.py : _entries` | sums on-disk size of cache entries; not a measurement of repository content |

Two things the rewrite found on its first run, both fixed in the same PR:
`_local_files_for_paths` in `pipeline.py` referenced `local_root`, which
is not bound there — a `NameError` on any `extra_docs_paths` directory,
introduced by #36 with no test on that branch — and the extra-path PDF walk
checked vendored-ness against `local_root` when the extra directory lives
outside it, so `is_vendored_abs` failed open and never excluded anything.
Both now test against the extra directory itself.
