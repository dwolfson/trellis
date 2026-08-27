# Trellis — repo-wide conventions

Package-specific guidance lives in `packages/resource-explorer/CLAUDE.md` and
`packages/egeria-advisor/CLAUDE.md`. This file covers what is true across the whole repo.

## Git: multiple sessions run in this repo at once

Several Claude Code sessions routinely work in this repo simultaneously, sometimes in the same
worktree on the same branch. Two rules follow, and the first matters most because it holds even
when you do not know what other sessions are doing.

**1. Never `git add -A`, `git add .`, or `git commit -a`. Stage explicit paths.**

A blanket stage sweeps up whatever any other session happens to have written — including files it
is still writing. This has already happened once: `97ad95a` ("Checklist: record the 12-repo
backfill slice and its verification") also committed `docs/context-compilation-design.md`, an
unrelated design doc authored by a concurrent session and untracked at that moment. See `6756408`
for the record. Nothing was lost, but the doc's history now points at a commit about something
else, and rewriting to fix it was not safe with another session live on the branch.

Stage the paths you actually changed. If that is tedious, it is because the change is large, not
because the rule is wrong.

**2. One session per worktree.**

Worktrees are already in use here (`git worktree list` — several branches, plus
`.claude/worktrees/`). Use them. If you want to work on a branch another session is already in,
create a worktree rather than sharing the checkout. Two sessions in one working directory race on
the index, the tip, and untracked files.

**Before committing, read `git status` and confirm every staged path is yours.** An unexpected file
is a signal that another session is mid-write, not something to sweep in.

## DCO sign-off

All commits require sign-off: `git commit -s`, or an explicit `Signed-off-by:` trailer. This repo
feeds work toward odpi/Egeria, which enforces DCO.
