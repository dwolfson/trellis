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

A claim is not a lock. It says *someone is already on this*, so the next session asks before
starting rather than after. That alone would have caught the collision above.

| item | claimed by | status |
|---|---|---|
| ~~cross-run acquisition cache (`zipball_root`/`git_clone_root`)~~ | dwolfson-59 | **landed** `f8710ef`, S1 reviewing |
| architecture-focus UI (`index.html` arch block) | trellis-arch-ui-65 | in progress |
| analysis-card run/background UX | trellis-survey-flows-59 | **landed** `a505d6e` |
| take architecture results into Curate | trellis-survey-flows-59 | in progress |
| ~~`architecture_recovery` tier / `run_time`~~ | trellis-arch-ui-65 | **ruled: analysis** (Dan), landed `26c18f1`, on integration |
| ~~`_COCHANGE_MAX_FILES = 50`~~ | dwolfson-59 | **measured, keep 50** — it is a cost control, not a quality control |
| compiler item 10 — wire the Chat panel | — | open (S3) |
| docs-as-source | — | open, designed and unbuilt |

Remove a row (or strike it) once its work lands or is abandoned — a table of stale claims that
still look active is worse than no table.

**Two rows deliberately have no owner.** The tier question and the `max_files` cap are decisions,
not tasks: both were opened by measurement and both want either a maintainer's call or evidence
nobody has gathered. Claiming them would turn a judgement into an implementation, which is how the
`run_time: fast` value survived unexamined for as long as it did.

## Pushing: every session pushes its own branch

**Each session pushes its own branch to origin. Integration merges; it does not publish other
people's branches.** Asked by S3 on 2026-08-30 after noticing that two session branches were on
origin and three were not — that was accident, not policy, and one of the unpushed branches had a
commit existing nowhere but one worktree.

- **Push whenever you have local commits.** Origin is the backup, not a publication step. A branch
  ref sitting behind its local is unbacked-up work, and pushing your own branch is a fast-forward
  nothing else reads as authoritative.
- **Do not try to keep your branch level with the shared tip.** That is integration's job and it is
  a moving target — sync-to-match and you are behind again by the time you finish. Merge from
  `re/deferred-cleanup-followups` when you *want* what is in it, not to stay aligned.
- **You do not need to pull integration in before pushing.** Push your work; integration will merge
  it.

## Merging: two ways to lose content quietly

Both bit on 2026-08-30 and both were integration's fault, so they are written down rather than
remembered.

- **Do not cherry-pick from a branch you will later merge.** Cherry-picking two of
  `ui/architecture-focus`'s commits before it was pushed, then merging that branch, produced six
  same-content-different-history conflicts. One resolved wrong and silently reverted
  `question_catalog.yaml`, breaking a test on another session's branch. It merges clean and fails
  quietly.
- **Do not resolve a prose-file conflict with `--theirs`.** It drops your own side wholesale. Used
  on `docs/Backlog.md` during that same merge, it lost two entries written the same morning —
  found hours later only by going to look for one of them. On docs, merge both sides by hand even
  when the other side looks like a superset.

## The registry is shared, and the suite reads it

The worktrees partition **files**. All five sessions still share one Postgres, so **data**
contention is untouched by the split — and the test suite reads that shared registry.

Measured 2026-08-30: a peer surveying `egeria_workspaces_git` caught it mid-run, in a state the
security-features reader classifies into none of its three causes, and turned integration's suite
red **in a file that session had never touched**. It looks exactly like a regression, and cost real
time to rule out as one.

**Corpus-reading tests are now marked and skipped by default.** Four files assert over whatever the
live registry happens to hold rather than over fixtures:

```
test_security_features_visibility.py    test_persisted_detail_contracts.py
test_headline_readers.py                test_doc_ingestion_rendering.py
```

```
pytest tests/            # 68 corpus tests skipped
pytest tests/ --corpus   # runs them
```

**They were not deleted, and that is deliberate.** Asserting over real corpus contents is exactly
how "58 of 60 repos render an empty security-features card" was found — no fixture would have
produced that. Run them with `--corpus` when the corpus is quiet, which is the only time their
answer means anything.

**Still open, not addressed here:** `test_investigation_routes.py` *writes* to the shared registry
(creating investigations and cleaning up after). That is a stronger form of the same hazard, since
it mutates rather than reads. It has not bitten yet.

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
