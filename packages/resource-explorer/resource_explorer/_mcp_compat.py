"""Compatibility shim: agentstack-sdk 0.7.x still imports ``streamablehttp_client``
from ``mcp.client.streamable_http``; mcp 2.x renamed it to ``streamable_http_client``
and moved header/auth configuration onto a caller-supplied ``httpx2.AsyncClient``.

trellis needs mcp 2.x because pyegeria's stdio MCP server imports
``mcp.server.mcpserver`` (egeria-python ISSUE-91), and the uv workspace resolves
one mcp for every package. Until agentstack-sdk ships an mcp-2 release, install
the old name with the old calling convention. Import this module BEFORE any
``agentstack_sdk`` import; it is a no-op when the old name already exists.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any


def install() -> bool:
    import mcp.client.streamable_http as sh

    if hasattr(sh, "streamablehttp_client"):
        return False
    new_client = getattr(sh, "streamable_http_client", None)
    if new_client is None:  # neither name: leave the ImportError to surface
        return False

    import httpx2

    @asynccontextmanager
    async def streamablehttp_client(
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | timedelta = 30,
        sse_read_timeout: float | timedelta = 60 * 5,
        terminate_on_close: bool = True,
        httpx_client_factory: Any = None,
        auth: Any = None,
    ):
        def _secs(v: float | timedelta) -> float:
            return v.total_seconds() if isinstance(v, timedelta) else float(v)

        if httpx_client_factory is not None:
            client = httpx_client_factory(headers=headers, timeout=timeout, auth=auth)
        else:
            client = httpx2.AsyncClient(
                headers=headers or {},
                auth=auth,
                timeout=httpx2.Timeout(_secs(timeout), read=_secs(sse_read_timeout)),
                follow_redirects=True,
            )
        async with client:
            async with new_client(url, http_client=client, terminate_on_close=terminate_on_close) as (read, write):
                # mcp 1.x yielded a third item: a callable returning the session id.
                yield read, write, (lambda: None)

    sh.streamablehttp_client = streamablehttp_client  # type: ignore[attr-defined]
    return True


INSTALLED = install()
