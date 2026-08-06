"""Database server management endpoints — register, list, discover databases."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ServerRegistration(BaseModel):
    slug: str
    display_name: str
    db_type: str = "postgresql"
    host: str
    port: int = 5432
    description: str = ""
    db_user: str = ""
    db_password: str = ""
    egeria_host: str = ""
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    egeria_password: str = ""
    group_slug: str = ""


class ServerSummary(BaseModel):
    slug: str
    display_name: str
    db_type: str
    host: str
    port: int
    description: str
    db_user: str
    egeria_host: str
    egeria_url: str
    egeria_server: str
    egeria_user: str
    status: str
    registered_at: str
    group_slug: str = ""
    databases: list[dict] = []  # from databases table (server_slug FK)


class DiscoveredDatabase(BaseModel):
    name: str
    size_pretty: str
    size_bytes: int
    owner: str
    description: str
    encoding: str
    is_registered: bool  # already in our databases table?


@router.get("/", response_model=list[ServerSummary])
async def list_servers():
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    servers = registry.list_servers()
    result = []
    for srv in servers:
        dbs = registry.list_databases(server_slug=srv.slug)
        result.append(ServerSummary(
            slug=srv.slug,
            display_name=srv.display_name,
            db_type=srv.db_type,
            host=srv.host,
            port=srv.port,
            description=srv.description,
            db_user=srv.db_user,
            egeria_host=srv.egeria_host,
            egeria_url=srv.egeria_url,
            egeria_server=srv.egeria_server,
            egeria_user=srv.egeria_user,
            status=srv.status.value,
            registered_at=srv.registered_at,
            group_slug=srv.group_slug or "",
            databases=[
                {
                    "slug": d.slug,
                    "display_name": d.display_name,
                    "database_name": d.database_name,
                    "last_surveyed_at": d.last_surveyed_at,
                    "status": d.status.value,
                }
                for d in dbs
            ],
        ))
    return result


@router.post("/register", response_model=ServerSummary)
async def register_server(req: ServerRegistration):
    from resource_explorer.registry import DatabaseServer, ProjectRegistry
    registry = ProjectRegistry()
    if registry.get_server(req.slug):
        raise HTTPException(400, f"Server '{req.slug}' already exists")
    server = DatabaseServer(
        slug=req.slug,
        display_name=req.display_name,
        db_type=req.db_type,
        host=req.host,
        port=req.port,
        description=req.description,
        db_user=req.db_user,
        db_password=req.db_password,
        egeria_host=req.egeria_host,
        egeria_url=req.egeria_url,
        egeria_server=req.egeria_server,
        egeria_user=req.egeria_user,
        egeria_password=req.egeria_password,
        group_slug=req.group_slug,
    )
    registry.register_server(server)
    return ServerSummary(
        slug=server.slug,
        display_name=server.display_name,
        db_type=server.db_type,
        host=server.host,
        port=server.port,
        description=server.description,
        db_user=server.db_user,
        egeria_host=server.egeria_host,
        egeria_url=server.egeria_url,
        egeria_server=server.egeria_server,
        egeria_user=server.egeria_user,
        status=server.status.value,
        registered_at=server.registered_at,
        group_slug=server.group_slug or "",
    )


@router.delete("/{slug}")
async def remove_server(slug: str):
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get_server(slug):
        raise HTTPException(404, f"Server '{slug}' not found")
    registry.remove_server(slug)
    return {"removed": slug}


@router.post("/{slug}/discover", response_model=list[DiscoveredDatabase])
async def discover_databases(slug: str):
    """Connect to the server and list available databases."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.database.connection import server_connection
    registry = ProjectRegistry()
    server = registry.get_server(slug)
    if not server:
        raise HTTPException(404, f"Server '{slug}' not found")
    if not server.db_user:
        raise HTTPException(
            400,
            "Server has no stored credentials — update the server registration first",
        )

    registered_dbs = {d.database_name for d in registry.list_databases(server_slug=slug)}

    def _discover():
        with server_connection(
            server.host, server.port, server.db_user, server.db_password, server.db_type
        ) as conn:
            return conn.list_databases()

    try:
        databases = await asyncio.to_thread(_discover)
        return [
            DiscoveredDatabase(
                name=db["name"],
                size_pretty=db["size_pretty"],
                size_bytes=db["size_bytes"],
                owner=db["owner"],
                description=db["description"],
                encoding=db["encoding"],
                is_registered=db["name"] in registered_dbs,
            )
            for db in databases
        ]
    except Exception as exc:
        raise HTTPException(500, f"Could not connect to server: {exc}") from exc


class TestConnectionRequest(BaseModel):
    """Optional overrides for connection test — uses stored values if omitted."""
    host: str = ""
    port: int = 0
    db_user: str = ""
    db_password: str = ""


class InlineTestRequest(BaseModel):
    """Inline connection test — no registered server required."""
    host: str
    port: int = 5432
    db_user: str
    db_password: str = ""
    db_type: str = "postgresql"


@router.post("/_test-inline")
async def test_connection_inline(req: InlineTestRequest):
    """Test a database server connection using inline credentials (no registration needed)."""
    from resource_explorer.surveyors.database.connection import server_connection

    def _test():
        with server_connection(req.host, req.port, req.db_user, req.db_password, req.db_type) as conn:
            rows = conn.execute_query("SELECT version()")
            version = rows[0]["version"] if rows else "connected"
            db_rows = conn.list_databases()
            return {"version": version, "database_count": len(db_rows)}

    try:
        result = await asyncio.to_thread(_test)
        return {
            "status": "ok",
            "host": req.host,
            "port": req.port,
            "server_version": result["version"],
            "database_count": result["database_count"],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.post("/{slug}/test")
async def test_server_connection(slug: str, req: TestConnectionRequest = TestConnectionRequest()):
    """Test connectivity to a registered server.  Returns ok + server_version on success."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.database.connection import server_connection

    registry = ProjectRegistry()
    server = registry.get_server(slug)
    if not server:
        raise HTTPException(404, f"Server '{slug}' not found")

    host     = req.host     or server.host
    port     = req.port     or server.port
    db_user  = req.db_user  or server.db_user
    db_pwd   = req.db_password or server.db_password

    if not db_user:
        raise HTTPException(400, "No credentials stored — add a username and password to the server registration")

    def _test():
        with server_connection(host, port, db_user, db_pwd, server.db_type) as conn:
            rows = conn.execute_query("SELECT version()")
            version = rows[0]["version"] if rows else "connected"
            db_rows = conn.list_databases()
            return {"version": version, "database_count": len(db_rows)}

    try:
        result = await asyncio.to_thread(_test)
        return {
            "status": "ok",
            "host": host,
            "port": port,
            "server_version": result["version"],
            "database_count": result["database_count"],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/{slug}")
async def get_server(slug: str) -> ServerSummary:
    """Get details for a specific server."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    server = registry.get_server(slug)
    if not server:
        raise HTTPException(404, f"Server '{slug}' not found")
    dbs = registry.list_databases(server_slug=slug)
    return ServerSummary(
        slug=server.slug, display_name=server.display_name, db_type=server.db_type,
        host=server.host, port=server.port, description=server.description,
        db_user=server.db_user, egeria_host=server.egeria_host,
        egeria_url=server.egeria_url, egeria_server=server.egeria_server,
        egeria_user=server.egeria_user, status=server.status.value,
        registered_at=server.registered_at,
        databases=[{"slug": d.slug, "display_name": d.display_name,
                    "database_name": d.database_name, "last_surveyed_at": d.last_surveyed_at,
                    "status": d.status.value} for d in dbs],
    )


@router.post("/{slug}/add-database")
async def add_database_from_server(slug: str, database_name: str, display_name: str = ""):
    """Register a specific database from this server into the databases table."""
    from resource_explorer.registry import DatabaseEntity, ProjectRegistry
    registry = ProjectRegistry()
    server = registry.get_server(slug)
    if not server:
        raise HTTPException(404, f"Server '{slug}' not found")

    db_slug = f"{slug}-{database_name}".replace("_", "-")
    if registry.get_database(db_slug):
        raise HTTPException(400, f"Database '{db_slug}' already registered")

    db = DatabaseEntity(
        slug=db_slug,
        display_name=display_name or f"{database_name} @ {server.display_name}",
        db_type=server.db_type,
        host=server.host,
        port=server.port,
        database_name=database_name,
        server_slug=slug,
        group_slug=server.group_slug,
        db_user=server.db_user,
        db_password=server.db_password,
        egeria_host=server.egeria_host,
        egeria_url=server.egeria_url,
        egeria_server=server.egeria_server,
        egeria_user=server.egeria_user,
        egeria_password=server.egeria_password,
    )
    registry.register_database(db)
    return {"slug": db_slug, "database_name": database_name, "server_slug": slug}
