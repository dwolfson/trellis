# Database survey history: "show invalid" view — implemented

Branch `re/database-survey-history-invalid-view`, cut from origin/main 04e76e35.

## Environment evidence (before any test run)

`uv sync --all-packages --extra dev` was run in the worktree, then:

```
$ .venv/bin/python -c "import resource_explorer; print(resource_explorer.__file__)"
/Users/dwolfson/localGit/egeria-v6/trellis-re-history-invalid-view/packages/resource-explorer/resource_explorer/__init__.py
```

That path is INSIDE this worktree (`trellis-re-history-invalid-view`), not main's
checkout (`trellis`). Test numbers below are only evidence because of this line.

(Implementation notes follow as the work lands.)
