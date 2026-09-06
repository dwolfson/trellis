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

import importlib.util
import json
import os
import shlex
import sys
from pathlib import Path
from typing import List, Optional, Tuple, TypedDict

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


def resolve_pyegeria_mcp_command() -> Optional[Tuple[str, List[str]]]:
    """
    Resolve the command + args used to spawn the "pyegeria" MCP server
    subprocess (report tools: run_report, find_report_specs, list_reports,
    describe_report — see CLAUDE.md rule 24).

    config/mcp_servers.json ships a host-specific dev path
    (``/Users/.../egeria-python/.venv/bin/python ... pyegeria/core/mcp_server.py``)
    that only exists on that one developer's machine — it doesn't exist
    inside a container image, so the subprocess fails to spawn at all
    (``[Errno 2] No such file or directory``).

    Priority, matching the "check os.environ directly, not a settings
    default" idiom used elsewhere in this module (resolve_model_tier(),
    resolve_mlflow_tracking_uri()) so an unset var never masquerades as an
    override:

      1. ``ADVISOR_PYEGERIA_MCP_COMMAND`` env var — the full argv to launch,
         either as a JSON array (``["python3", "-m", "pyegeria.core.mcp_server"]``)
         or a plain shell-split string (``python3 -m pyegeria.core.mcp_server``).
      2. ``sys.executable -m pyegeria.core.mcp_server`` — the *current*
         Python interpreter, used when ``pyegeria`` is importable in it. This
         is the common case both inside the packaged image and in the uv
         workspace: both install pyegeria into the same interpreter this
         process runs from, so there's no need for a separate host-only venv
         path at all.
      3. ``None`` — signals the caller to fall back to config/mcp_servers.json's
         configured ``command``/``args`` unchanged (today's behaviour).

    Logs which branch was chosen, so a container's startup log shows exactly
    which interpreter is about to be spawned.
    """
    env_cmd = os.environ.get("ADVISOR_PYEGERIA_MCP_COMMAND", "").strip()
    if env_cmd:
        argv: Optional[List[str]] = None
        try:
            parsed = json.loads(env_cmd)
            if isinstance(parsed, list) and parsed:
                argv = [str(x) for x in parsed]
        except json.JSONDecodeError:
            pass
        if argv is None:
            argv = shlex.split(env_cmd)
        if argv:
            logger.info(
                f"pyegeria MCP command resolved from ADVISOR_PYEGERIA_MCP_COMMAND: {argv}"
            )
            return argv[0], argv[1:]
        logger.warning(
            f"ADVISOR_PYEGERIA_MCP_COMMAND={env_cmd!r} did not resolve to any argv; "
            "falling back to the next resolution step"
        )

    if importlib.util.find_spec("pyegeria") is not None:
        argv = [sys.executable, "-m", "pyegeria.core.mcp_server"]
        logger.info(
            f"pyegeria MCP command resolved to the current interpreter (pyegeria "
            f"importable in it): {argv}"
        )
        return argv[0], argv[1:]

    logger.info(
        "pyegeria MCP command: pyegeria not importable in the current interpreter and "
        "ADVISOR_PYEGERIA_MCP_COMMAND is unset — falling back to config/mcp_servers.json's "
        "configured command/args"
    )
    return None


def resolve_report_specs_dir() -> Optional[str]:
    """
    Resolve an absolute path for the pyegeria MCP server's
    ``PYEGERIA_USER_REPORT_SPECS_DIR`` env var (annotated report specs —
    ``question_spec`` populated by ``scripts/generate_question_specs.py``).

    config/mcp_servers.json ships this as a relative ``config/report_specs``
    (see the "pyegeria" server's env block) so the JSON stays portable, but
    the value the MCP subprocess actually needs is absolute — it is spawned
    with its own cwd, not necessarily this process's. Same idiom as
    resolve_pyegeria_mcp_command(): check os.environ directly, not a
    settings default, so an unset var never masquerades as an override.

    Priority:
      1. ``PYEGERIA_USER_REPORT_SPECS_DIR`` env var, if set — an operator's
         explicit override, expanded (``~``) and returned as-is.
      2. ``<repo>/config/report_specs``, resolved to an absolute path — the
         directory actually shipped in this repo, shared workspace-wide rather
         than owned by EA (see advisor/configdata/advisor.yaml's
         ``data_sources.report_specs_dir`` for the same relative location).
      3. ``None`` if neither resolves to an existing directory — callers
         should fall back to config/mcp_servers.json's configured value
         unchanged, same as resolve_pyegeria_mcp_command()'s ``None`` case.
    """
    env_val = os.environ.get("PYEGERIA_USER_REPORT_SPECS_DIR", "").strip()
    if env_val:
        resolved = str(Path(env_val).expanduser())
        logger.info(f"PYEGERIA_USER_REPORT_SPECS_DIR resolved from env: {resolved}")
        return resolved

    # <repo>/config/report_specs — moved out of the package 2026-09-06.
    default_dir = Path(__file__).parent.parent.parent.parent / "config" / "report_specs"
    if default_dir.is_dir():
        resolved = str(default_dir.resolve())
        logger.info(f"PYEGERIA_USER_REPORT_SPECS_DIR resolved to repo default: {resolved}")
        return resolved

    logger.info(
        "PYEGERIA_USER_REPORT_SPECS_DIR: no env override and "
        f"{default_dir} does not exist — falling back to config/mcp_servers.json's "
        "configured value unchanged"
    )
    return None
