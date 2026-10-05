"""The LIVE answer shapes the gateway parses, as recorded by the 2026-10-05 rehearsal.

Source: the live rehearsal's evidence note (branch `re/curate-commit-rehearsal-evidence`, section
"Live shapes", pyegeria 6.1.15, `MetadataExpert`) and the rehearsal's own read scripts, which
printed `el["elementGUID"]`, `el["type"]["typeName"]`,
`el["elementProperties"]["propertiesAsStrings"]["qualifiedName"]`, `rel["elementList"][i]`
with `type.typeName`, `relationshipGUID`, `element`, `elementAtEnd1`, and the classification's
`classificationName`.

What is recorded is the KEYS and the paths above; the values here are the rehearsal's own
(the throwaway database's GUID and qualified name) or minimal stand-ins where the note recorded
no value. Nothing below has an `elementHeader`, `guid` or `properties` key, because the live
element has none: that is the defect (D2) these fixtures exist to pin.

`tests/fake_egeria_catalogue.py` builds its raw payloads through `raw_element` and `raw_related`
below, and `test_catalogue_live_shapes.py` asserts the fake's output has exactly these shapes.
"""
from __future__ import annotations

DB_GUID = "edb12250-e7e2-4024-9c6d-a8fb384d7956"
DB_QN = "PostgreSQL Relational Database::host.docker.internal:5442::scratch_cat_test3"

#: `get_metadata_element_by_unique_name` / `get_metadata_element_by_guid` / one item of
#: `find_metadata_elements_with_string`: the RAW element.
LIVE_ELEMENT = {
    "headerVersion": 0,
    "status": "ACTIVE",
    "type": {"typeName": "RelationalDatabase"},
    "origin": {},
    "versions": {},
    "elementGUID": DB_GUID,
    "classifications": [
        {"classificationName": "ZoneMembership",
         "classificationProperties": {"propertiesAsStrings": {"zoneMembership": "egeria-runtime"}}},
    ],
    "elementProperties": {
        "propertiesAsStrings": {
            "qualifiedName": DB_QN,
            "description": "throwaway rehearsal database",
            "versionIdentifier": "not recorded",
        },
    },
}

#: The key sets of the live element, for the fake-equals-live test.
ELEMENT_KEYS = frozenset({"headerVersion", "status", "type", "origin", "versions", "elementGUID",
                          "classifications", "elementProperties"})

#: `get_all_related_elements`: a DICT, not a list. The database had five relationships:
#: ReportSubject x2, ActionTarget, SourcedFrom, ResourceConnection.
def _rel(rel_type: str, rel_guid: str, other_guid: str, other_type: str, other_qn: str) -> dict:
    return {
        "headerVersion": 0, "status": "ACTIVE", "type": {"typeName": rel_type}, "origin": {}, "versions": {},
        "relationshipGUID": rel_guid,
        "element": {"headerVersion": 0, "status": "ACTIVE", "type": {"typeName": other_type}, "origin": {},
                    "versions": {}, "elementGUID": other_guid, "classifications": [],
                    "elementProperties": {"propertiesAsStrings": {"qualifiedName": other_qn}}},
        "elementAtEnd1": {"elementGUID": other_guid},
    }


LIVE_RELATED = {
    "startingElement": LIVE_ELEMENT,
    "elementList": [
        _rel("ReportSubject", "r1", "0eafcee7-5ec9-4cf0-a2a8-aafd32e5028a", "SurveyReport", "SurveyReport::native"),
        _rel("ReportSubject", "r2", "db988bc3-1a4e-4265-b240-b03c8f97d724", "SurveyReport", "SurveyReport::re"),
        _rel("ActionTarget", "r3", "6c5100b1-d4ad-4466-8554-76ce07c876e3", "EngineAction", "EngineAction::1"),
        _rel("SourcedFrom", "r4", "d87059ce-2d87-4e0a-b35f-0652dc00d841", "SoftwareServer", "PostgreSQL Server::x"),
        _rel("ResourceConnection", "r5", "75434d74-6a29-4eb8-8b85-0cfcaf8490e9", "VirtualConnection", "conn::x"),
    ],
    "mermaidGraph": "graph TD",
}
RELATED_KEYS = frozenset({"startingElement", "elementList", "mermaidGraph"})
RELATED_ITEM_KEYS = frozenset({"headerVersion", "status", "type", "origin", "versions", "relationshipGUID",
                               "element", "elementAtEnd1"})
#: An ActionTarget item also carries `relationshipProperties` (read-back note, item 3).
RELATED_ITEM_KEYS_WITH_PROPS = RELATED_ITEM_KEYS | {"relationshipProperties"}

#: `initiate` (governance action type) answer: a GUIDResponse whose guid is the ENGINE ACTION.
LIVE_INITIATE_RESPONSE = {"class": "GUIDResponse", "requestId": "e2931a25-0000-0000-0000-000000000000",
                          "relatedHTTPCode": 200, "guid": "dc40606d-5538-48b1-9094-d06c7a1bf3bf"}
ACTION_TYPE_QN = "PostgreSQLGovernance::catalog-postgres-schema"


def _enum(symbol: str) -> dict:
    return {"class": "EnumTypePropertyValue", "typeName": "ActivityStatus", "symbolicName": symbol}


def relationship_properties(name: str, status: str, completion_ms: str = "") -> dict:
    """`ActionTarget` relationshipProperties, live shape: typed map and string map side by side."""
    pv = {"actionTargetName": {"class": "PrimitiveTypePropertyValue", "primitiveValue": name},
          "activityStatus": _enum(status)}
    ps = {"actionTargetName": name, "activityStatus": status}
    if completion_ms:
        pv["completionTime"] = {"class": "PrimitiveTypePropertyValue", "primitiveValue": completion_ms}
        ps["completionTime"] = completion_ms
    return {"propertyValueMap": pv, "propertiesAsStrings": ps}


def raw_engine_action(guid: str, status: str, *, message: str = "", completion_ms: str = "") -> dict:
    """An EngineAction raw element: the status attribute is `activityStatus` (NOT `actionStatus`)."""
    ps = {"qualifiedName": f"EngineAction::{guid}", "activityStatus": status}
    if message:
        ps["completionMessage"] = message
    if completion_ms:
        ps["completionTime"] = completion_ms
    el = raw_element(guid, ps["qualifiedName"], "EngineAction", props={k: v for k, v in ps.items() if k != "qualifiedName"})
    el["elementProperties"]["propertyValueMap"] = {"activityStatus": _enum(status)}
    return el


def raw_element(guid: str, qn: str, type_name: str, *, archived: bool = False, zones: list[str] | None = None,
                props: dict | None = None) -> dict:
    """One raw element, exactly the live shape."""
    cls = []
    if archived:
        cls.append({"classificationName": "Memento", "classificationProperties": {}})
    if zones:
        cls.append({"classificationName": "ZoneMembership",
                    "classificationProperties": {"propertiesAsStrings": {"zoneMembership": ",".join(zones)}}})
    return {"headerVersion": 0, "status": "ACTIVE", "type": {"typeName": type_name}, "origin": {}, "versions": {},
            "elementGUID": guid, "classifications": cls,
            "elementProperties": {"propertiesAsStrings": {"qualifiedName": qn, **(props or {})}}}


def raw_related(start: dict, items: list[tuple]) -> dict:
    """The related-elements dict. `items` are (relationship type, relationship guid, raw other
    element[, relationshipProperties])."""
    out = []
    for it in items:
        t, g, el = it[:3]
        item = {"headerVersion": 0, "status": "ACTIVE", "type": {"typeName": t}, "origin": {},
                "versions": {}, "relationshipGUID": g, "element": el,
                "elementAtEnd1": {"elementGUID": start["elementGUID"]}}
        if len(it) > 3 and it[3]:
            item["relationshipProperties"] = it[3]
        out.append(item)
    return {"startingElement": start, "elementList": out, "mermaidGraph": "graph TD"}
