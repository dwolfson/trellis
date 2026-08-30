# Session worktrees — 2026-08-30

*How the five parallel work-streams are separated, what each one owns, and what does not come along
when you make a worktree. Read this before starting a session in one.*

Five sessions, five worktrees, five branches, all cut from `512a91e` on
`re/deferred-cleanup-followups`. **The point is `index.html`:** it is 14,460 lines and three of
these sessions edit it, which on one shared branch is exactly the contention CLAUDE.md rule 1's
incident history describes.

| session | worktree | branch | owns |
|---|---|---|---|
| **S1** Architecture focus UI | `trellis-arch-ui` | `ui/architecture-focus` | `index.html` arch block, `repo_survey_definition_adapter.py` reader |
| **S2** Survey flows & stages | `trellis-survey-flows` | `re/survey-flows` | `projects.py` routes, `analysis_catalog.yaml`, run/background UX |
| **S3** Chat panel surface | `trellis-chat-panel` | `ui/chat-compiler-surface` | `index.html` chat block, the compile route |
| **S4** Compiler plumbing | `trellis-compiler` | `re/compiler-plumbing` | `context_compile.py`, `trellis_context`, `trellis_artifact_tree`, `registry.py` |
| **S5** Research | `trellis-research` | `docs/research-track` | docs only |

Worktrees are **siblings of this repository's root**, not nested inside it — `trellis/` and
`trellis-arch-ui/` sit next to each other. Paths below are written absolute because that is what
`git worktree` prints; substitute your own checkout's parent directory.

## Before running anything in a worktree

`.env` files are already copied. **The venv is not** — it is 2.7 GB and lives outside git:

```
cd /Users/dwolfson/localGit/egeria-v6/<worktree>
uv sync --all-packages --extra dev
```

Never a bare `uv sync` (CLAUDE.md: it uninstalls the venv from the workspace root, and scopes the
shared venv down to one package from a package dir). `--all-extras` fails on macOS — onnxruntime-gpu
ships no arm64 wheel.

**S5 needs no venv at all** if it stays in docs.

## The corpus does not come along

`packages/egeria-advisor/data/repos/` is gitignored, so no worktree has the eight repo checkouts
(egeria, egeria-workspaces, polaris, openmetadata, petclinic, atlas, dataflow, datahub — ~1 GB).
Neither do the two pre-existing siblings; this is normal.

**Anything that surveys a real repo should run in the main checkout**
(`/Users/dwolfson/localGit/egeria-v6/trellis`), which has them. That specifically includes **S2's
profiling of `architecture_recovery`** — the 111s-warm measurement that gates the `run_time` ruling.

## What can run at the same time

```
parallel now:   S1 · S2 (profiling half) · S4 · S5
serialize:      S1 → S3          (both edit index.html)
blocked:        S2 (stage half)  — needs profiling, then a maintainer ruling
                S3 (pointer sections) — needs S4
```

## Backlog-item claims

*(Added 2026-08-30 after three sessions crossed on one `docs/Backlog.md` item within about ten
minutes: S2 told dwolfson-59 to take the cross-run acquisition cache, Dan separately assigned the
same item to S1, and S1/dwolfson-59 then messaged each other about it simultaneously. Nothing was
lost — dwolfson-59 had already built it before either flag landed — but it cost real time, and it
is the one failure mode the worktree split above does not address: the table partitions **files**,
and this was a collision in **assignment**, which lives in whoever last heard about it rather than
anywhere written down.)*

Before starting non-trivial work on a `docs/Backlog.md` item that is not already one worktree's
named territory in the table above, claim it here first — check this list before claiming, not
just before starting to code.

| item | claimed by | date |
|---|---|---|
| cross-run acquisition cache (`zipball_root`/`git_clone_root`) | dwolfson-59 (reviewed by S1) | 2026-08-30 |

Remove a row (or strike it) once its work lands or is abandoned — a table of stale claims that
still look active is worse than no table.

## Ports

One dev server at a time on 8810 (`.claude/launch.json`). A second session needs its own port, or
to use the one already running — `preview_start` refuses a port in use rather than stealing it.

## Rules that still apply everywhere

- Name paths in every git command. No `git add -A`, no bare `git stash`/`checkout`/`reset`.
- `git checkout -- <path>` is safer, not safe — read `git status` for the path first.
- `git commit -s` (DCO).
- Read `git status` before committing and confirm every staged path is yours.

## Cleanup

```
git worktree remove /Users/dwolfson/localGit/egeria-v6/<worktree>   # must be clean
git worktree list                                                  # check before removing
```

### Already cleaned up, 2026-08-30

`trellis-presentation` and `trellis-ui-question-catalog` were removed. Verified first: clean trees,
no stashes, `.env` files that were strict *subsets* of main's (missing the Prefect block), and every
commit on both branches already an **ancestor of `origin/main`**.

**The branch refs were kept.** `git worktree remove` takes the working directory, not the branch, so
`re/results-presentation` and `ui/question-catalog-admin` still exist and nothing is unreachable.
Recreate a worktree from either at any time.

### Also cleaned up: `.claude/worktrees/re-scouting-scan-fix`

Removed 2026-08-30 after its session was killed. It had been idle for **5 days 3 hours** on tty008
with 52 minutes of total CPU — parked, not runaway.

Nothing was lost. Its branch was fully contained in `origin/main`, and its one uncommitted file
(`uv.lock`, +15/-1, adding trellis-artifact-tree's `code` and `pdf` extras) was a **stale local
re-derivation**: the worktree sat 56 commits behind, on a base predating `a326204` where those
extras were declared properly. Someone had run `uv sync` there and it recomputed a change that had
since been committed by someone else.

Removed with `--force` for exactly that one file, having verified it first. The branch ref
`worktree-re-scouting-scan-fix` was kept.

**Why it mattered:** an idle process holding a stale `uv.lock` in a shared repo is how the
2026-08-29 incident happened — an agent saw the modification, reverted it with the pathspec form,
and destroyed another session's workspace wiring. Clearing it before five sessions start running
`uv sync` removes that trap.
