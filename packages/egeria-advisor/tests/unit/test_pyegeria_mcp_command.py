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

...and that MCPConfig.from_dict applies each resolver only to the server it
owns, leaving unrelated servers' command/args untouched. Since 2026-09-06
"dr-egeria" has its own resolver too (resolve_dr_egeria_mcp_command), and a
server whose resolved command does not exist is disabled rather than spawned.
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


def test_from_dict_leaves_unrelated_servers_untouched(monkeypatch):
    """The pyegeria resolver must not leak into servers it does not own.

    This used to assert that on "dr-egeria" — valid while pyegeria was the
    only server resolved. Since 2026-09-06 dr-egeria has its own resolver
    (advisor.mcp_config.resolve_dr_egeria_mcp_command), so it is no longer an
    example of an untouched server; asserting on it here would pin the very
    behaviour that fix removes. The invariant still matters, so it is
    asserted against a server neither resolver claims.
    """
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.delenv("ADVISOR_DR_EGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: object()
    )
    cfg_dict = dict(_CONFIG_DICT)
    cfg_dict["mcpServers"] = dict(cfg_dict["mcpServers"])
    cfg_dict["mcpServers"]["some-other-server"] = {
        # /bin/sh so the "never spawn a command that is not there" guard in
        # MCPConfig.from_dict does not disable it -- that guard is about
        # unspawnable commands, and this test is about resolver ownership.
        "command": "/bin/sh",
        "args": ["/some/other/script.py"],
        "enabled": True,
    }
    cfg = MCPConfig.from_dict(cfg_dict)
    assert cfg.servers["some-other-server"].command == "/bin/sh"
    assert cfg.servers["some-other-server"].args == ["/some/other/script.py"]


def test_from_dict_disables_a_server_whose_command_does_not_exist(monkeypatch):
    """Known-negative for the guard added with dr-egeria's resolver.

    config/mcp_servers.json ships placeholders for host-specific paths; a
    resolver that finds nothing leaves them in place. Spawning one produces
    `[Errno 2] No such file or directory: '<path-to-...>'` on every startup —
    EA BACKLOG DP-1's symptom. Such a server is disabled instead, and the
    placeholder is left visible so the log names what was wrong.
    """
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.delenv("ADVISOR_DR_EGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr("advisor.mcp_config._workspaces_checkout", lambda: None)
    cfg_dict = dict(_CONFIG_DICT)
    cfg_dict["mcpServers"] = {
        "placeholder-server": {
            "command": "<path-to-something>/.venv/bin/python",
            "args": [],
            "enabled": True,
        }
    }
    cfg = MCPConfig.from_dict(cfg_dict)
    assert cfg.servers["placeholder-server"].enabled is False
    assert "placeholder-server" not in cfg.get_enabled_servers()
    # left visible rather than blanked, so the warning can name it
    assert cfg.servers["placeholder-server"].command.startswith("<path-to-")


def test_from_dict_falls_back_to_json_command_when_not_importable(monkeypatch):
    monkeypatch.delenv("ADVISOR_PYEGERIA_MCP_COMMAND", raising=False)
    monkeypatch.setattr(
        "advisor.mcp_config.importlib.util.find_spec", lambda name: None
    )
    cfg = MCPConfig.from_dict(_CONFIG_DICT)
    assert cfg.servers["pyegeria"].command == (
        "/Users/someone/localGit/egeria-python/.venv/bin/python"
    )
