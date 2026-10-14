"""Generate the Dr.Egeria document that declares RE's engine host to Egeria (E1 of
docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md §5.1).

Written to `docs/dr-egeria/engine-host/resource-explorer-survey-engine.md`, generated from
DATABASE_STEP_REGISTRY through `resource_explorer.engine_host` (the same names the claim sweep dispatches on).
This script never talks to Egeria, and the folder has no `_batch.json`, so RE's bootstrap never runs it:
the owner runs the document.

    uv run python packages/resource-explorer/scripts/generate_engine_host_declaration.py [--check]

`--check` writes nothing and exits 1 when the committed document differs from what would be generated.
tests/test_engine_host_declaration.py holds the committed document to this generator and to the registry.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
DOC = PKG / "docs" / "dr-egeria" / "engine-host" / "resource-explorer-survey-engine.md"


def _header() -> str:
    from resource_explorer import engine_host as eh

    steps = eh.declared_steps()
    rows = "\n".join(
        f"  - {eh.SERVICE_TYPE_NAME} `{eh.service_qualified_name(k)}`, linked to the engine by\n"
        f"    SupportedGovernanceService {{requestType: \"{eh.request_type_for_step(k)}\", "
        f"serviceRequestType: \"{eh.request_type_for_step(k)}\"}}"
        for k in steps)
    return f"""<!--
GENERATED from DATABASE_STEP_REGISTRY by packages/resource-explorer/scripts/generate_engine_host_declaration.py.
Do not hand-edit; regenerate. Design: docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md §5.1 (E1).

The owner runs this document; RE never does (this folder is not a bootstrap batch).

NOT YET EXPRESSIBLE IN Dr.Egeria (pyegeria 6.2.3 has no command for these; author them another way FIRST,
or the executor link below cannot resolve its engine):
  - {eh.ENGINE_TYPE_NAME} `{eh.ENGINE_QUALIFIED_NAME}` (display name "{eh.ENGINE_DISPLAY_NAME}"). Its
    description should say the engine is hosted by Resource Explorer's worker, outside any Egeria engine
    host (Q-M4). No Java engine host configuration may list it, or a JVM host races RE for every claim.
{rows}
The commands below are the ones Dr.Egeria has: the GovernanceActionType a person or process initiates, and its
GovernanceActionExecutor link to the engine.
-->
"""


def render() -> str:
    from resource_explorer import engine_host as eh

    parts = [_header()]
    for step_key, info in eh.declared_steps().items():
        request_type = eh.request_type_for_step(step_key)
        gat = eh.governance_action_type_qn(step_key)
        parts.append(f"""
## Create Governance Action Type
### Display Name
Resource Explorer Survey — {step_key}

### Qualified Name
{gat}

### Description
{info.description}

### Produced Guards
{", ".join(eh.SURVEY_GUARDS)}

### Content Status
ACTIVE

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| re_analysis_step | {step_key} |
| engine_host | resource-explorer-worker |

___

## Link Action to Action Executor
### Governance Action Type
{gat}

### Governance Engine
{eh.ENGINE_QUALIFIED_NAME}

### Request Type
{request_type}

### Description
Egeria dispatches {gat} to Resource Explorer's engine, which claims it and runs RE step {step_key}.

___
""")
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when the document is stale")
    args = ap.parse_args(argv)
    text = render()
    current = DOC.read_text() if DOC.is_file() else None
    if args.check:
        if current != text:
            print(f"STALE: {DOC} (run {Path(__file__).name})")
            return 1
        print(f"up to date: {DOC}")
        return 0
    if current == text:
        print(f"unchanged: {DOC}")
        return 0
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(text)
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
