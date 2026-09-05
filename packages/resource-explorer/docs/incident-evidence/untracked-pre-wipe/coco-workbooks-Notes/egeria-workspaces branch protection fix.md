# egeria-workspaces: fix "required review" blocking my own merges

**2026-08-29** — Claude added a "require 1 approving review" rule to
`odpi/egeria-workspaces`'s `main` branch protection as part of OpenSSF
Scorecard hardening (PR #408), with a bypass list meant to cover me and
Mandy Chessell. The bypass list does NOT reliably work (confirmed: still
blocked merging my own PRs, both via `gh pr merge` and — the second time —
the UI too). Claude is also blocked by its own safety classifier from
fixing this via the API on my behalf, so I need to do it by hand.

## Fix (2 minutes)

1. Go to `https://github.com/odpi/egeria-workspaces/settings/branches`
2. Edit the rule for `main`
3. Under "Require a pull request before merging" — either uncheck it
   entirely, or set **Required approvals** to **0** (keeps the rule
   structurally in place but stops it blocking merges)
4. Save

Everything else that rule change added is fine and worth keeping:
DCO required check, no force-push, no deletions, `enforce_admins`.
Just the review-count part needs to go back to 0.

## Still open / to revisit later
- 15 higher-risk Dependabot PRs on egeria-workspaces intentionally left
  unmerged (Python 3.14 base-image bumps ×7, pytest major ×2, docker CLI
  27→29 ×2, Node 18→25, airflow-providers-openlineage major, schemathesis
  major, codeql-action v3→v4 ×2) — worth a deliberate look, not an
  auto-merge.
- Asked egeria-python-07 (the Claude session on egeria-python) to do the
  same Scorecard audit there — flagged this exact bypass-list gotcha to it
  in advance so it doesn't burn time rediscovering it.
