"""
Tests for advisor.mcp_config.resolve_pyegeria_mcp_command() and its wiring
into advisor.mcp_agent.MCPConfig — the fix for EA's MCP server config
hardcoding a host-only egeria-python venv path, so the pyegeria MCP server
subprocess can't spawn inside a container (docs/packaging.md "EA gaps":
"[Errno 2] No such file or directory: '/Users/.../egeria-python/.venv/bin/python'").

Covers the resolution order:
  1. ADVISOR_PYEGERIA_MCP_COMMAND env var (JSON array or shell-split string)
  2. sys.executable -m pyegeria.core.mcp_server, when pyegeria is importable
     in the current interpreter
  3. fall back to the command/args from config/mcp_servers.json unchanged

...and that MCPConfig.from_dict only applies this to the "pyegeria" server,
leaving every other server's command/args untouched.
"""
import sys

import pytest

from advisor.mcp_config import resolve_pyegeria_mcp_command
from advisor.mcp_agent import MCPConfig


# ---------------------------------------------------------------------------
# resolve_pyegeria_mcp_command()
# ---------------------------------------------------------------------------

def test_env_var_json_array_wins(monkeypatch):
    monkeypatch.setenv(
        "ADVISOR_PYEGERIA_MCP_COMMAND",
        '["python3", "-m", "pyegeria.core.mcp_server", "--flag"]',
    )
    result = resolve_pyegeria_mcp_command()
    assert result == ("python3", ["-m", "pyegeria.core.mcp_server", "--flag"])


def test_env_var_shell_split_string(monkeypatch):
    monkeypatch.setenv(
        "ADVISOR_PYEGERIA_MCP_COMMAND", "python3 -m pyegeria.core.mcp_server"
    )
    result = resolve_pyegeria_mcp_command()
    assert result == ("python3", ["-m", "pyegeria.core.mcp_server"])


def test_env_var_takes_priority_over_current_interpreter(monkeypatch):
    monkeypatch.setenv("ADVISOR_PYEGERIA_MCP_COMMAND", "/custom/python -m foo")
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: object()
    )
    result = resolve_pyegeria_mcp_command()
    assert result == ("/custom/python", ["-m", "foo"])


def test_falls_back_to_current_interpreter_when_pyegeria_importable(monkeypatch):
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: object()
    )
    result = resolve_pyegeria_mcp_command()
    assert result == (sys.executable, ["-m", "pyegeria.core.mcp_server"])


def test_falls_back_to_none_when_pyegeria_not_importable(monkeypatch):
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: None
    )
    assert resolve_pyegeria_mcp_command() is None


def test_blank_env_var_is_ignored(monkeypatch):
    monkeypatch.setenv("ADVISOR_PYEGERIA_MCP_COMMAND", "   ")
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: None
    )
    assert resolve_pyegeria_mcp_command() is None


# ---------------------------------------------------------------------------
# MCPConfig wiring — only "pyegeria" is affected
# ---------------------------------------------------------------------------

_CONFIG_DICT = {
    "mcpServers": {
        "pyegeria": {
            "command": "/Users/someone/localGit/egeria-python/.venv/bin/python",
            "args": ["/Users/someone/localGit/egeria-python/pyegeria/core/mcp_server.py"],
            "env": {},
            "enabled": True,
        },
        "dr-egeria": {
            "command": "/Users/someone/localGit/egeria-python/.venv/bin/python",
            "args": ["/some/other/script.py"],
            "env": {},
            "enabled": True,
        },
    },
    "settings": {},
}


def test_from_dict_overrides_pyegeria_command_when_importable(monkeypatch):
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: object()
    )
    cfg = MCPConfig.from_dict(_CONFIG_DICT)
    assert cfg.servers["pyegeria"].command == sys.executable
    assert cfg.servers["pyegeria"].args == ["-m", "pyegeria.core.mcp_server"]


def test_from_dict_leaves_other_servers_untouched(monkeypatch):
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: object()
    )
    cfg = MCPConfig.from_dict(_CONFIG_DICT)
    assert cfg.servers["dr-egeria"].command == (
        "/Users/someone/localGit/egeria-python/.venv/bin/python"
    )
    assert cfg.servers["dr-egeria"].args == ["/some/other/script.py"]


def test_from_dict_falls_back_to_json_command_when_not_importable(monkeypatch):
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: None
    )
    cfg = MCPConfig.from_dict(_CONFIG_DICT)
    assert cfg.servers["pyegeria"].command == (
        "/Users/someone/localGit/egeria-python/.venv/bin/python"
    )
