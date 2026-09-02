## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Refresh Plan

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_refresh_plan

### Description
What a refresh would actually need to do: which targets have never run, which are stale against the current head commit, and which are current. One GitHub call, no archive download. ADVISORY — the executor runs every step regardless, so this records the decision rather than enforcing it.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_refresh_plan |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Git Statistics

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_git_statistics

### Description
Refreshes project_stats (stars, forks, contributors, commit activity, releases, security config, deployments) from the GitHub API — the table eight other steps read. Replaces five independent StatsFetcher calls that each refreshed it separately in the same run.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_git_statistics |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo File Inventory

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_inventory

### Description
Refreshes project_file_inventory from a fresh zipball — the table every file-shape step reads. Closes the gap where the inventory was written only by RAG ingestion/refresh_profile and never by a survey step, so a survey reported whatever an earlier, unrelated run had left behind.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_inventory |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Manifest Parse

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_manifest_parse

### Description
Parses dependency manifests, CI workflow content, supply-chain signals and repo-convention signals from a freshly extracted zipball, refreshing project_dependencies and project_analysis_findings (kind="ci_quality"/"repo_conventions"/"supply_chain") — the three tables previously written only by full ingestion (and, for the latter two, refresh_profile), never by a survey step.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_manifest_parse |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo File Structure

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_structure

### Description
File counts, per-language breakdown, and top-level directory structure.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_structure |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo File Size

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_size

### Description
Per-file sizes, total footprint, size-by-type, top-10 largest files.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_size |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Language

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_language

### Description
Primary/secondary language and coarse project-type classification.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_language |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Health

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_health

### Description
Activity, community, release-cadence, and freshness scoring from GitHub stats.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_health |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Homepage

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_homepage

### Description
Finds the project's external website — GitHub's declared homepage first, falling back to pyproject.toml [project.urls], package.json or the README when that is empty (measured: 11 of 24 registered repos have no declared homepage). Surfaced in Scouting as a clickable link and published to Egeria as an ExternalReference linked to the repo.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_homepage |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Website Ingestion

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_website_ingestion

### Description
Ingests the project's documentation site into pgvector as web_docs_{host}, so Chat and Understanding can answer from the project's own documentation rather than only its source tree. Keyed on the site's host, not the repo slug — several repos in one project share one site and therefore one collection. Uses the site repo_homepage derived, collapsing versioned docs to the current release; skips entirely when the repo builds that site itself, since the source is already ingested in a better form.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_website_ingestion |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Dependency

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_dependency

### Description
Package dependencies per ecosystem (PyPI/npm/Maven).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_dependency |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Documentation

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_documentation

### Description
Presence of README/CHANGELOG/CONTRIBUTING/SECURITY and overall doc-quality label.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_documentation |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Security

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_security

### Description
Presence of SECURITY.md, CI config, LICENSE — flags gaps as RFAs.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_security |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Classification

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_classification

### Description
What the repo represents (7 roles, ranked, multi-valued), where each artifact its role implies actually lives, and whether architecture recovery is worth running at all (design §5.5b).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_classification |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo License Classification

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_license_classification

### Description
Classifies the repo's SPDX license id into a risk tier (permissive/weak copyleft/strong copyleft/source-available/unknown).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_license_classification |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Security Features

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_security_features

### Description
GitHub's native security feature toggles (Dependabot, secret scanning, etc.) — configuration state, not artifact presence.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_security_features |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Ci Quality

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_ci_quality

### Description
Whether CI workflows actually run tests/lint/build, via a keyword scan of workflow content — not just whether a CI config exists.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_ci_quality |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Interface Surface

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_interface_surface

### Description
What can be talked to, and whether the contract is written down — from the file inventory and declared dependencies. A committed openapi.yaml is 'specified'; a fastapi dependency is only 'implied', and never counts as a published API.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_interface_surface |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Chaoss Metrics

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_chaoss_metrics

### Description
CHAOSS community-health metrics over recorded commits — chiefly the elephant factor, the fewest contributors accounting for half the commits. Contributor COUNT calls deep_causality a five-person project; the distribution says one person wrote 98% of it.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_chaoss_metrics |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Cii Badge

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_cii_badge

### Description
The real OpenSSF Best Practices (CII) badge, read from bestpractices.dev rather than estimated. Reports the level with the age of the self-assessment behind it, and keeps 'no badge' apart from 'could not ask'.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_cii_badge |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Community Support

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_community_support

### Description
Community support as separate dimensions — attention, participation, channels — rather than one number. repository_health's community_score is dominated by stars and forks, and scores a four-contributor project 100/100; this reports the weakest dimension instead of averaging it away.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_community_support |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Cve Scan

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_cve_scan

### Description
Dependency advisories from OSV.dev, over dependencies the manifest parser already recorded. Reports coverage with the count: declared dependencies only, and only those with a pinned, parseable version.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_cve_scan |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Secret Scan

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_secret_scan

### Description
Committed-credential scan over HEAD content, using a VENDORED gitleaks ruleset (222 rules, MIT, provenance recorded). Reports what it matched AND which ruleset version it matched with — never 'no secrets', only 'no matches against this ruleset in HEAD'.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_secret_scan |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Telemetry Scan

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_telemetry_scan

### Description
Telemetry / phone-home indicators: known SDK imports and literal outbound endpoints, paired with whether the project discloses them. Never labels an ordinary API client as telemetry.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_telemetry_scan |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Contribution Provenance

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_contribution_provenance

### Description
CLA/DCO provenance, kept as two separate questions: whether sign-off is STATED, and whether it is ENFORCED. Config presence alone is reported `partial`, never `pass`.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_contribution_provenance |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Sla Content

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_sla_content

### Description
Whether the project publishes support or service-level commitments. Deliberately NEUTRAL (present/absent, not pass/gap): most repositories legitimately publish none, and absence alone never raises an action.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_sla_content |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Foss Scorecard

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_foss_scorecard

### Description
OpenSSF-Scorecard-shaped checks computed from data already held — an unevaluable check reports unknown and is excluded from the score, rather than scored zero as OpenSSF's own tool does.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_foss_scorecard |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Maturity

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_maturity

### Description
Project age/lifecycle stage (nascent/emerging/established/mature), from repo_created_at — a CHAOSS-informed Discovery-tier signal.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_maturity |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Conventions

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_conventions

### Description
Discovery-tier repo conventions: security policy content, build automation, deployment/Docker evidence, catalog self-description (Backstage-style), documentation breadth.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_conventions |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Api Structure

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_api_structure

### Description
Public API surface (functions/classes/methods) per language.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_api_structure |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Data Profiling

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_data_profiling

### Description
Inventories data files and profiles their schema (rows/columns/dtypes/nulls).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_data_profiling |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo File Classification

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_classification

### Description
Classifies every file by type using filename/extension mapping (Egeria-enrichable).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_classification |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Symbol Extraction

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_symbol_extraction

### Description
Extracts class/function/method symbols (tree-sitter/ast) for every supported language, refreshing project_code_symbols/project_code_relationships — D5's self-contained microflow closing the bug where those tables were only ever populated by RAG ingestion, never by a survey step.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_symbol_extraction |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Arch Detect

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_arch_detect

### Description
Recovers candidate architecture components from package manifests, deployment units (Dockerfile/compose), and ast-grep code markers — the deterministic half of architecture recovery (design doc §5.1).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_arch_detect |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Arch Coupling

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_arch_coupling

### Description
Proposes additional architecture-component boundaries from import coupling and co-change coupling — the conventional, undeclared components (Agents, Core, Surveyors, ...) that manifests and code markers structurally cannot see (design doc §5.5, Phase 1 plan §4.1). Needs real git history, not just a checkout.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | prefect |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_arch_coupling |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Arch Lens

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_arch_lens

### Description
Labels recovered components against the project's own architecture document, wherever it lives — in-repo, a sibling repository, or a documentation site. A LENS: it adds no component, removes none and assigns no type. Milvus goes from 206 candidates to 15 the authors actually name (finding 102).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_arch_lens |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Arch Summary

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_arch_summary

### Description
Collapses architecture-recovery findings to the depth the question asked for — the summarising half nothing owned. Milvus recovers 218 candidate components where its own authors describe eight; a suitability answer is 'serves gRPC (297 operations), 24 runnable units, 31 third-party'.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_arch_summary |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Sub Resource Survey

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_sub_resource_survey

### Description
Surveys file/folder characteristics to recommend which sub-resources are worthy of cataloging as their own Egeria assets (Assessment sub-resource cataloging plan) — survey only, does not catalog.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_sub_resource_survey |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Security Summary

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_security_summary

### Description
Reduces the security family's stored findings to one topic summary. Measures nothing itself — it reads what the other security steps wrote, so it belongs LAST in any survey that runs them. Reports coverage and the age of its oldest input alongside the verdict, and refuses a verdict at all below four inputs.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_security_summary |

___

## Create Governance Action Process Step
### Display Name
Full Survey (all steps) — Repo Rag Ingestion

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_rag_ingestion

### Description
Refreshes the project's pgvector collections via IncrementalIndexer — the queryable representation Chat, the query router and every RAG-backed answer read, previously built only at registration, on webhook or from a bespoke route branch and never by a survey step. A no-op when the repository's last indexed commit is unchanged.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_rag_ingestion |

___

## Create Governance Action Process
### Display Name
Full Survey (all steps)

### Qualified Name
GovActionProcess::RepoFullSurvey

### Description
Every current Resource Explorer repo analysis step, chained into one Survey Definition — the comprehensive bundle for an already-tracked repo, not Discovery's launch target. Regenerated by scripts/generate_repo_survey_definition.py from repo_survey_definition_adapter.py's STEP_REGISTRY, the single source of truth for what RE can actually run against a Git repository. Named 'Full Survey (all steps)' — deliberately NOT 'Scouting - ...', which it was briefly called: this is an automate_full bundle, and the Scouting prefix made it read as a Scouting-tier survey, which is how running it from Scouting came to deposit Assessment-tier results that rendered as Scouting Results cards. Scouting's own run-everything option is 'Scouting Survey'. qualified_name has never changed across either rename, so both were in-place updates of the same element. Scales poorly by construction: as repo survey steps grow into the dozens, some of them expensive, 'run every step' stops being a sensible default and this becomes a deliberate, scheduled choice rather than a convenient one.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | Git Repository |
| survey_kind | automate_full |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::RepoFullSurvey

### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_refresh_plan

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_refresh_plan

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_git_statistics

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_git_statistics

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_inventory

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_inventory

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_manifest_parse

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_manifest_parse

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_structure

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_structure

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_size

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_size

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_language

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_language

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_health

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_health

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_homepage

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_homepage

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_website_ingestion

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_website_ingestion

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_dependency

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_dependency

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_documentation

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_documentation

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_license_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_license_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security_features

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security_features

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_ci_quality

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_ci_quality

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_interface_surface

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_interface_surface

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_chaoss_metrics

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_chaoss_metrics

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_cii_badge

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_cii_badge

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_community_support

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_community_support

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_cve_scan

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_cve_scan

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_secret_scan

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_secret_scan

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_telemetry_scan

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_telemetry_scan

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_contribution_provenance

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_contribution_provenance

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_sla_content

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_sla_content

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_foss_scorecard

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_foss_scorecard

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_maturity

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_maturity

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_conventions

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_conventions

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_api_structure

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_api_structure

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_data_profiling

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_data_profiling

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_symbol_extraction

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_symbol_extraction

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_detect

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_detect

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_coupling

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_coupling

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_lens

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_lens

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_summary

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_arch_summary

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_sub_resource_survey

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_sub_resource_survey

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security_summary

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security_summary

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_rag_ingestion

### Guard
Any

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What languages and file types make up this repository?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Is this repository actively maintained?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Who maintains this repository?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
How widely adopted and active is the community around this repository?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
How is it supported?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What dependencies does this require?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
How well documented is it?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Does it fit into our security infrastructure?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Is there a current, published, security analysis?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What kind of thing is this repository — a library, an application, a tool, or samples?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What explicit license does the repository use, and are there non-standard or copyleft terms?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Is there a validation / deployment test for it?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What kinds of integrations does it support?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What APIs and code symbols does it expose to callers?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What are the public interfaces?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
How concentrated is authorship — would the project survive losing its top contributors?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Does it hold an OpenSSF Best Practices (CII) badge, and how current is the self-assessment behind it?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Are there outstanding CVEs?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
How does it score against OpenSSF Scorecard-style criteria?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
How mature is it?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What deployment styles does this support?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Does the repository publish a clear process for reporting security vulnerabilities?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Does the repository have automated build tooling in place?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
Is this repository already self-described for an enterprise catalog (e.g. Backstage catalog-info.yaml)?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
How much code is there? How complex?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What data files does it ship, and what shape are they?

___

## Link Element To Scope
### Target Element
Full Survey (all steps)

### Scope Reference
What is its internal architecture — what components exist and how do they relate?

