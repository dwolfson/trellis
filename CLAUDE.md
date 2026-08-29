# Trellis — repo-wide conventions

Package-specific guidance lives in `packages/resource-explorer/CLAUDE.md` and
`packages/egeria-advisor/CLAUDE.md`. This file covers what is true across the whole repo.

## Git: multiple sessions run in this repo at once

Several Claude Code sessions routinely work in this repo simultaneously, sometimes in the same
worktree on the same branch. Two rules follow, and the first matters most because it holds even
when you do not know what other sessions are doing.

**1. No whole-tree git operations in a shared checkout. Name the paths — every command that
takes a pathspec accepts one.**

This covers `git add -A` / `git add .` / `git commit -a`, and equally `git stash`, `git checkout`,
`git reset` and `git clean`. They all operate on *the tree*, which in this repo means everyone's
work, not yours.

Both halves have now happened. A blanket stage: `97ad95a` ("Checklist: record the 12-repo backfill
slice and its verification") also committed `docs/context-compilation-design.md`, an unrelated
design doc authored by a concurrent session and untracked at that moment — see `6756408` for the
record. And a blanket stash on 2026-08-28: a session ran `git stash` to answer "is this failing
test mine?", which reverted three files another session had in flight. Both were recoverable and
neither lost work, but only because the session that did it said so immediately.

The prohibition alone is not enough, because the need is real — you *will* legitimately want to
set your changes aside to check whether a failure is yours. Use the pathspec form:

```
git add path/one path/two
git stash push -- path/one path/two
git checkout -- path/one
```

`git stash push -- <paths>` is the safe door into the same room as `git stash`. Reach for it
rather than working around the rule.

Before committing, read `git status` and confirm every staged path is yours. An unexpected file is
a signal that another session is mid-write, not something to sweep in. If naming paths is tedious,
it is because the change is large, not because the rule is wrong.

**2. Worktrees are not currently a usable isolation mechanism here — know why before relying on
one.**

Every Claude session on this machine runs with `cwd: /Users/dwolfson`, which is not a git
repository. Sessions reach into this repo by absolute path, so they have no per-session repo
context and cannot take a worktree of it. That is why concurrent sessions all land in the same
checkout: not carelessness, but the absence of any mechanism that would separate them.

`git worktree list` does show worktrees (`.claude/worktrees/`, plus sibling checkouts). Those come
from subagents given an explicit repo path, or from manual setup — not from session isolation. A
stale one is normal and harmless; check it is clean and behind before removing it.

If you genuinely need isolation for a long parallel change, the fix is to start a session **inside
the repo** rather than in the home directory. That is a deliberate trade: sessions run from home
precisely so they can work across trellis, egeria-python, egeria-workspaces and pyegeria in one
place, and rooting a session in one repo gives that up.

Absent that, **rule 1 is the only control that actually operates.** Treat it accordingly.

**Before committing, read `git status` and confirm every staged path is yours.** An unexpected file
is a signal that another session is mid-write, not something to sweep in.

## DCO sign-off

All commits require sign-off: `git commit -s`, or an explicit `Signed-off-by:` trailer. This repo
feeds work toward odpi/Egeria, which enforces DCO.
