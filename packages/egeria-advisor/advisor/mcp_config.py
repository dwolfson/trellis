"""
Shared resolution for the pyegeria MCP server's Egeria connection config.

config/mcp_servers.json ships with defaults for local development (localhost
Egeria, qs-view-server). Environment variables (.env) take priority when set,
so switching deployments — e.g. pointing this Advisor at a different Egeria
instance for a remote/demo deployment — is a matter of setting two .env
values, with no need to edit the committed JSON config.

This is the single source every Egeria-connection reader should use
(advisor.auth, advisor.report_pipeline, advisor.egeria_context,
advisor.agents.dr_egeria_agent) instead of each independently parsing
config/mcp_servers.json with its own ad-hoc fallback logic — which is how
this drifted: those four readers previously had four subtly different
priority orders (and one, EGERIA_PLATFORM_URL in advisor.config.settings,
was never actually read anywhere).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict

from loguru import logger

_DEFAULT_MCP_CONFIG_PATH = Path(__file__).parent / "configdata" / "mcp_servers.json"


class PyegeriaPlatformConfig(TypedDict):
    view_server: str
    platform_url: str


def get_pyegeria_platform_config(config_path: "str | Path | None" = None) -> PyegeriaPlatformConfig:
    """
    Resolve the pyegeria MCP server's view_server/platform_url.

    Priority: EGERIA_VIEW_SERVER / EGERIA_VIEW_SERVER_URL environment
    variables (set via .env) first, then config/mcp_servers.json's
    mcpServers.pyegeria.env block. Returns empty strings for whichever value
    isn't resolvable either way — callers already treat that as "Egeria
    connection not configured."
    """
    path = Path(config_path) if config_path else _DEFAULT_MCP_CONFIG_PATH
    json_view_server = json_platform_url = ""
    try:
        if path.exists():
            cfg = json.loads(path.read_text())
            env = cfg.get("mcpServers", {}).get("pyegeria", {}).get("env", {})
            json_view_server = env.get("EGERIA_VIEW_SERVER", "")
            json_platform_url = env.get("EGERIA_VIEW_SERVER_URL", "")
    except Exception as exc:
        logger.warning(f"mcp_config: failed to read {path}: {exc}")

    view_server = os.environ.get("EGERIA_VIEW_SERVER", "") or json_view_server
    platform_url = os.environ.get("EGERIA_VIEW_SERVER_URL", "") or json_platform_url

    return {"view_server": view_server, "platform_url": platform_url}
