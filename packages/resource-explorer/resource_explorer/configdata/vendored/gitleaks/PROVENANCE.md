# Vendored ruleset: gitleaks default config

Pulled 2026-09-01, from the upstream gitleaks project.

- **Source URL**: https://github.com/gitleaks/gitleaks
- **File pulled**: `config/gitleaks.toml` (the project's own default rule
  config — 222 `[[rules]]` entries plus a global `[allowlist]` of paths and
  value-shaped noise regexes, at pull time)
- **Pulled from**: `master` branch, raw content at pull time
  (`https://raw.githubusercontent.com/gitleaks/gitleaks/master/config/gitleaks.toml`)
- **Upstream commit that last touched this file** (per `GET
  /repos/gitleaks/gitleaks/commits?path=config/gitleaks.toml`, measured at
  pull time): `09242ce9c8a60d9b051fc2d166f9e849b88c7ac0`, dated
  2025-11-20T15:12:31Z.
- **Latest tagged release at pull time**: `v8.30.1` (published
  2026-03-21T02:17:58Z) — recorded as context; the file itself is pulled
  from `master`, not a release tarball, so the commit SHA above (not the
  release tag) is the precise version pin. `repo_secret_scan`'s
  `version_or_as_of` field records the commit SHA for exactly this reason.
- **License**: MIT (`LICENSE-gitleaks.txt`, copied verbatim alongside this
  file) — permissive, compatible with vendoring a data file (not the
  gitleaks binary itself) into this project. No compiled/binary gitleaks
  code is vendored; only its rules-as-data TOML file, read and matched by
  this codebase's own regex engine (`secret_ruleset.py`), per the
  "rules-only data file" path the design (`docs/gap-analyses-design.md`
  §1) names as one of the two legitimate vendoring shapes.

## Staleness

`repo_secret_scan`'s `ruleset_freshness` finding is computed from the date
above (2025-11-20, the upstream commit's own date — not the pull date),
not from when `repo_secret_scan` itself runs. See
`resource_explorer/surveyors/sub_surveyors/secret_scan.py` for the
threshold and reasoning.

## Updating this vendored copy

Re-run the same pull (raw file + `GET .../commits?path=...&per_page=1` for
the new SHA/date), replace `gitleaks.toml`, and update the two fields above
(commit SHA, commit date) — do not silently drop the previous SHA from this
file's git history; it is only recoverable from there once overwritten.
