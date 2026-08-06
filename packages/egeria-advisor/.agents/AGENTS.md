# Egeria Advisor Codebase Organization Rules

All agents must understand and align on the organization of the Egeria and egeria-python codebases:

## 1. Egeria (Java Repository)
- **Purpose**: The core Java repository implementing the Egeria backend metadata server platform, engines, OMAS, OMAG, and OMRS services.
- **Relational/Vector Collection**: `egeria_java`
- **Reference**: Any conceptual questions about the backend or Java classes/APIs belong here.

## 2. egeria-python (Python Repository)
- **Purpose**: The repository of Python code built on top of Egeria.
- **Relational/Vector Collection**: `pyegeria`
- **Sub-components**:
  1. `pyegeria` (under the `pyegeria/` directory): The Python client SDK API library used to communicate with Egeria backend servers.
  2. `commands` (under the `commands/` directory): Command-line tools (CLI) and interactive commands (such as `hey_egeria`) written in Python using the `pyegeria` SDK.
  3. `dr_egeria` (under the `md_processing/` directory): The Python implementation of the Dr. Egeria markdown processor, which is used to parse, draft, and execute governance metadata template plans.
