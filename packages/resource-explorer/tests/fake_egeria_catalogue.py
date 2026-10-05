"""A stateful stand-in for Egeria, behind `CatalogueGateway`, for the slice B tests.

Built from what the scratch runs RECORDED (`evidence/SCRATCH-CATALOGUER-TEST-2-2026-10-05.md`),
not from what would be convenient:

* a schema-kind target makes the cataloguer create exactly that schema's tables and
  columns on its next refresh, and nothing under the database;
* the cataloguer hands names to JDBC as patterns, so a schema `a_b` also pulls in
  `aXb`'s tables and a table `x_y` also gets `xZy`'s columns;
* an archive hides the element (and its children) from a plain read; a read with
  `for_lineage` still sees it, as a Memento; recreating an archived name fails 400;
* a soft delete of a parent that still has visible children is refused (the strict
  reading, so a parent-first delete order fails in the test, never silently passes);
* a removed target is still refreshed by the running connector until it is
  restarted (S17), and the connector never recreates an archived or deleted schema;
* creating a schema element whose qualified name already exists returns the same GUID.

Nothing here touches a network, a file or a registry.
"""
from __future__ import annotations

from resource_explorer.catalogue_gateway import (
    ARCHIVE, CatalogTarget, ConnectorStatus, ElementRead, GatewayError, PublishedDatabase,
    Relationship, like_matches, schema_type_qualified_name)

PROCESS_QN = "PostgreSQLSurvey::survey-postgres-database"


class FakeEgeria:
    def __init__(self, source: dict[str, dict[str, list[str]]] | None = None):
        # schema -> table -> [columns]; what the real database holds
        self.source = source or {}
        self.elements: dict[str, dict] = {}
        self.targets: list[CatalogTarget] = []
        self.calls: list[tuple] = []
        self.schema_types: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.rels: dict[str, list[Relationship]] = {}
        self.deleted_order: list[tuple[str, str, str]] = []   # (qn, type, form)
        self.surveys: list[tuple[str, dict]] = []
        self.refreshes = 0
        self.restarts = 0
        self.connector_time = "2026-10-05T09:05:00"
        self.connector_errors: list[str] = []
        self.lingering: set[str] = set()
        self.fail: dict[str, str] = {}
        self.zones_ok = True
        self.owner_policy = "set"          # set | refuse | fail
        self.zones: dict[str, list[str]] = {}
        self.owners: dict[str, str] = {}
        self._n = 0
        self.db_guid = ""
        self.server_guid = ""

    # -- helpers ---------------------------------------------------------
    def _guid(self, prefix: str = "g") -> str:
        self._n += 1
        return f"{prefix}{self._n:04d}-0000-0000-0000-000000000000"

    def _boom(self, op: str) -> None:
        if op in self.fail:
            raise GatewayError(self.fail[op])

    def _visible(self, e: dict) -> bool:
        return not e["deleted"] and not e["archived"]

    def by_qn(self, qn: str) -> dict | None:
        for g, e in self.elements.items():
            if e["qn"] == qn and not e["deleted"]:        # a soft-deleted element is gone; its name is free
                return {**e, "guid": g}
        return None

    def add_element(self, qn: str, type_name: str, parent: str = "") -> str:
        g = self._guid("e")
        self.elements[g] = {"qn": qn, "type": type_name, "parent": parent, "archived": False, "deleted": False}
        return g

    def reset(self) -> None:
        """An Egeria reset: everything RE ever wrote is gone."""
        self.elements.clear()
        self.targets.clear()
        self.schema_types.clear()
        self.lingering.clear()
        self.db_guid = self.server_guid = ""

    def ops(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]

    # -- step 1 ----------------------------------------------------------
    def publish_database(self, db_entity, db_user, db_pwd, *, registry=None, submitted_by="") -> PublishedDatabase:
        self.calls.append(("publish_database",))
        self._boom("publish_database")
        server = f"{getattr(db_entity, 'egeria_host', '') or db_entity.host}:{db_entity.port}"
        qn = f"PostgreSQL Relational Database::{server}::{db_entity.database_name}"
        if not self.db_guid:
            self.server_guid = self._guid("s")
            self.db_guid = self._guid("d")
            self.elements[self.db_guid] = {"qn": qn, "type": "RelationalDatabase", "parent": "", "archived": False, "deleted": False}
        return PublishedDatabase(self.server_guid, self.db_guid, server, qn)

    def publish_local_report(self, db_entity, db_user, db_pwd, measured, *, registry=None, submitted_by="") -> dict:
        self.calls.append(("publish_local_report", measured.get("surveyed_at")))
        self._boom("publish_local_report")
        return {"report_guid": self._guid("r"), "annotation_count": 3}

    def set_zone_membership(self, guid, zones) -> bool:
        self.calls.append(("set_zone_membership", guid, tuple(zones)))
        if not self.zones_ok:
            return False
        self.zones[guid] = list(zones)
        return True

    def set_owner(self, guid, owner):
        self.calls.append(("set_owner", guid, owner))
        if self.owner_policy == "fail":
            raise GatewayError("500 Egeria failed")
        if self.owner_policy == "refuse":
            return "refused", "LOCAL_CANNOT_CHANGE_EXTERNAL"
        self.owners[guid] = owner
        return "set", f"Ownership set to {owner}"

    # -- reads and schema elements --------------------------------------
    def read_element(self, qualified_name, *, for_lineage=False):
        self.calls.append(("read_element", qualified_name, for_lineage))
        self._boom("read_element")
        e = self.by_qn(qualified_name)
        if e is None:
            return None
        if e["archived"] and not for_lineage:
            return None
        return ElementRead(e["guid"], e["qn"], e["type"], e["archived"])

    def find_schema_type(self, qualified_name):
        self.calls.append(("find_schema_type", qualified_name))
        return self.schema_types.get(qualified_name, "")

    def create_schema_element(self, db_entity, schema, database_guid, *, description=""):
        self.calls.append(("create_schema_element", schema, database_guid))
        self._boom("create_schema_element")
        server = f"{getattr(db_entity, 'egeria_host', '') or db_entity.host}:{db_entity.port}"
        qn = f"PostgreSQL Relational Database Schema::{server}::{db_entity.database_name}.{schema}"
        e = self.by_qn(qn)
        if e is not None and e["archived"]:
            raise GatewayError(f"400 OMAG-REPOSITORY-HANDLER-400-010 A DeployedDatabaseSchema entity with unique "
                               f"identifier {e['guid']} is not visible [Anchors, Memento]")
        if e is not None and not e["deleted"]:
            return e["guid"]
        return self.add_element(qn, "DeployedDatabaseSchema", parent=database_guid)

    def link_schema_type(self, schema_guid, schema_type_guid):
        self.calls.append(("link_schema_type", schema_guid, schema_type_guid))
        self.links.append((schema_guid, schema_type_guid))

    # -- targets -----------------------------------------------------------
    def list_catalog_targets(self):
        self.calls.append(("list_catalog_targets",))
        self._boom("list_catalog_targets")
        return list(self.targets)

    def add_catalog_target(self, element_guid, name):
        self.calls.append(("add_catalog_target", element_guid, name))
        self._boom("add_catalog_target")
        el = self.elements.get(element_guid)
        assert el is not None and el["type"] == "DeployedDatabaseSchema", \
            "a catalog target must be a SCHEMA-kind element, never the database or the server"
        rel = self._guid("t")
        self.targets.append(CatalogTarget(rel, element_guid, name))
        return rel

    def remove_catalog_target(self, relationship_guid):
        self.calls.append(("remove_catalog_target", relationship_guid))
        self._boom("remove_catalog_target")
        for t in list(self.targets):
            if t.relationship_guid == relationship_guid:
                self.targets.remove(t)
                self.lingering.add(t.element_guid)      # S17: the running connector keeps it

    # -- under a schema ----------------------------------------------------
    def elements_under(self, prefix):
        self.calls.append(("elements_under", prefix))
        self._boom("elements_under")
        return [ElementRead(g, e["qn"], e["type"], False) for g, e in self.elements.items()
                if self._visible(e) and e["qn"].startswith(prefix)]

    def relationships(self, guid):
        self.calls.append(("relationships", guid))
        self._boom("relationships")
        out = list(self.rels.get(guid, []))
        e = self.elements.get(guid)
        if e is not None and e["type"] == "DeployedDatabaseSchema":
            out.append(Relationship("AssetSchemaType", other_guid="st"))      # structural noise
            out.append(Relationship("CatalogTarget", other_guid="cat"))
        return out

    def add_term_assignment(self, qn_suffix: str, schema_qn: str, n: int = 1) -> None:
        g = self.by_qn(f"{schema_qn}::{qn_suffix}")["guid"]
        self.rels.setdefault(g, []).extend(Relationship("SemanticAssignment", other_guid="term") for _ in range(n))

    def delete_element(self, guid, form):
        self.calls.append(("delete_element", guid, form))
        self._boom("delete_element")
        e = self.elements[guid]
        if form == ARCHIVE:
            stack = [guid]
            while stack:
                g = stack.pop()
                self.elements[g]["archived"] = True
                stack += [c for c, x in self.elements.items() if x["parent"] == g]
            self.deleted_order.append((e["qn"], e["type"], form))
            return
        kids = [c for c, x in self.elements.items() if x["parent"] == guid and self._visible(x)]
        if kids:
            raise GatewayError(f"401 OMAG-GENERIC-HANDLERS-403-005 A delete of {e['type']} element {guid} is not "
                               f"permitted because it still has a dependent element {kids[0]}")
        e["deleted"] = True
        self.deleted_order.append((e["qn"], e["type"], form))

    # -- survey and connector ---------------------------------------------
    def initiate_survey(self, database_guid, request_parameters):
        self.calls.append(("initiate_survey", database_guid, dict(request_parameters)))
        self._boom("initiate_survey")
        self.surveys.append((database_guid, dict(request_parameters)))
        return self._guid("a"), PROCESS_QN

    def connector_status(self):
        self.calls.append(("connector_status",))
        self._boom("connector_status")
        return ConnectorStatus("JDBCDatabaseCataloguer", "WAITING", self.connector_time)

    def refresh_connector(self, timeout=120):
        self.calls.append(("refresh_connector", timeout))
        self._boom("refresh_connector")
        self.refreshes += 1
        self.connector_time = f"2026-10-05T09:{10 + self.refreshes:02d}:00"
        self.run_cataloguer()

    def restart_connector(self):          # RE must never call this; a test asserts it stays 0
        self.restarts += 1

    def run_cataloguer(self) -> None:
        """One cataloguer cycle: every attached (and, per S17, every lingering) schema."""
        seen: set[str] = set()
        for t in list(self.targets):
            self._cycle(t.element_guid)
            seen.add(t.element_guid)
        for g in sorted(self.lingering - seen):
            self._cycle(g)

    def _cycle(self, schema_guid: str) -> None:
        e = self.elements.get(schema_guid)
        if e is None or e["deleted"] or e["archived"]:
            self.connector_errors.append(f"JDBC-INTEGRATION-CONNECTOR-0006 {schema_guid} not visible: nothing recreated")
            return
        # the schema name is everything after `<db>.`; qualified names are `...::<db>.<schema>`
        pattern = e["qn"].split("::", 2)[2].split(".", 1)[1]
        for sname, tables in self.source.items():
            if not like_matches(pattern, sname):        # JDBC pattern: a_b also returns aXb
                continue
            for tname, cols in tables.items():
                tqn = f"{e['qn']}::{tname}"
                tg = (self.by_qn(tqn) or {}).get("guid") or self.add_element(tqn, "RelationalTable", parent=schema_guid)
                allcols = list(cols)
                for t2, c2 in tables.items():              # column pattern: x_y also returns xZy's columns
                    if t2 != tname and like_matches(tname, t2):
                        allcols += c2
                for c in dict.fromkeys(allcols):
                    cqn = f"{tqn}::{c}"
                    if self.by_qn(cqn) is None:
                        self.add_element(cqn, "RelationalColumn", parent=tg)

    def orphan_schema_type(self, db_entity, schema: str) -> str:
        server = f"{getattr(db_entity, 'egeria_host', '') or db_entity.host}:{db_entity.port}"
        qn = schema_type_qualified_name(server, db_entity.database_name, schema)
        self.schema_types[qn] = self._guid("o")
        return self.schema_types[qn]
