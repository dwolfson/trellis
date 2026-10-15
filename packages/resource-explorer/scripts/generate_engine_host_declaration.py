"""Generate the Dr.Egeria document that declares RE's engine host to Egeria (E1 of
docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md §5.1).

Written to `docs/dr-egeria/engine-host/resource-explorer-survey-engine.md`, generated from
DATABASE_STEP_REGISTRY through `resource_explorer.engine_host` (the same names the claim sweep dispatches on),
together with its sibling `resource-explorer-survey-engine.pyegeria-steps.json`: the three elements pyegeria
6.2.3's Dr.Egeria has no command for (the SurveyActionEngine, one SurveyActionService per step, and their
SupportedGovernanceService links), which `resource_explorer.dr_egeria_runner` runs as find-or-create pyegeria
steps BEFORE the document. This script never talks to Egeria, and the folder has no `_batch.json`, so RE's
bootstrap never runs it: an admin runs it with `resource-explorer dr-egeria run
engine-host/resource-explorer-survey-engine.md` (or the admin route).

TODO (engine host, step 2 live gate): add this folder to the initialization batches (a `_batch.json` here and
an entry in `_folder_order.json`) only AFTER the live gate of engine-host step 2 has passed against Egeria.

    uv run python packages/resource-explorer/scripts/generate_engine_host_declaration.py [--check]

`--check` writes nothing and exits 1 when the committed document or steps file differs from what would be generated.
tests/test_engine_host_declaration.py holds the committed document to this generator and to the registry.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
DOC = PKG / "docs" / "dr-egeria" / "engine-host" / "resource-explorer-survey-engine.md"
STEPS = DOC.with_name(DOC.stem + ".pyegeria-steps.json")      # dr_egeria_runner.STEPS_SUFFIX

ENGINE_DESCRIPTION = (
    "Resource Explorer's survey engine. It is hosted by Resource Explorer's worker, outside any Egeria engine "
    "host (Q-M4): no Java engine host configuration may list it, or a JVM host races Resource Explorer for "
    "every claim.")


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

RE's bootstrap never runs this document (this folder is not a bootstrap batch); an admin runs it with
`resource-explorer dr-egeria run engine-host/{DOC.name}`.

NOT EXPRESSIBLE IN Dr.Egeria (pyegeria 6.2.3 has no command for these). They are pyegeria steps in
{STEPS.name}, which `resource-explorer dr-egeria run` runs
FIRST, in this order, each finding its element by qualifiedName and creating it only when absent:
  - {eh.ENGINE_TYPE_NAME} `{eh.ENGINE_QUALIFIED_NAME}` (display name "{eh.ENGINE_DISPLAY_NAME}"). Hosted by
    Resource Explorer's worker, outside any Egeria engine host (Q-M4). No Java engine host configuration may
    list it, or a JVM host races RE for every claim.
{rows}
The commands below are the ones Dr.Egeria has: the GovernanceActionType a person or process initiates, and its
GovernanceActionExecutor link to the engine. "Link Action to Action Executor" is NOT safe to repeat; the runner
refuses a second run of the same content unless forced.

TODO (engine host, step 2 live gate): this folder joins the initialization batches (_batch.json +
_folder_order.json) only after the live gate of engine-host step 2.
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


def render_steps() -> str:
    """The pyegeria steps file: engine, then one service and one SupportedGovernanceService link per step, in the
    order dr_egeria_runner requires (engine -> services -> links)."""
    from resource_explorer import engine_host as eh

    steps = [{"command": "Create Survey Action Engine", "qualified_name": eh.ENGINE_QUALIFIED_NAME,
              "display_name": eh.ENGINE_DISPLAY_NAME, "description": ENGINE_DESCRIPTION}]
    declared = eh.declared_steps()
    for step_key, info in declared.items():
        steps.append({"command": "Create Survey Action Service",
                      "qualified_name": eh.service_qualified_name(step_key),
                      "display_name": f"Resource Explorer Survey Service — {step_key}",
                      "description": info.description})
    for step_key in declared:
        steps.append({"command": "Link Supported Governance Service",
                      "governance_engine": eh.ENGINE_QUALIFIED_NAME,
                      "governance_service": eh.service_qualified_name(step_key),
                      "request_type": eh.request_type_for_step(step_key),
                      "service_request_type": eh.request_type_for_step(step_key)})
    doc = {"$comment": [
        f"GENERATED with {DOC.name} by packages/resource-explorer/scripts/generate_engine_host_declaration.py "
        "from DATABASE_STEP_REGISTRY. Do not hand-edit; regenerate.",
        "pyegeria steps for what pyegeria 6.2.3's Dr.Egeria cannot express (docs/dr-egeria-engine-host-gaps.md). "
        "resource_explorer.dr_egeria_runner runs them, in this order, before the document: each finds its "
        "element by qualifiedName (the link: by engine, service and requestType) and creates it only when absent.",
        "TODO (engine host, step 2 live gate): add engine-host to the initialization batches only after that gate.",
    ], "steps": steps}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when the document is stale")
    args = ap.parse_args(argv)
    stale = 0
    for path, text in ((DOC, render()), (STEPS, render_steps())):
        current = path.read_text() if path.is_file() else None
        if args.check:
            if current != text:
                print(f"STALE: {path} (run {Path(__file__).name})")
                stale = 1
            else:
                print(f"up to date: {path}")
            continue
        if current == text:
            print(f"unchanged: {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path}")
    return stale


if __name__ == "__main__":
    sys.exit(main())
