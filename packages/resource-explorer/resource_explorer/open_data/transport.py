"""The one place outbound HTTP happens for open data.

Adapters take a transport, so a test hands them a fake and CI never touches the network. A fake must bind this
signature (`tests/test_open_data.py::test_the_fake_transport_binds_the_real_signature`).
"""
from __future__ import annotations

from typing import Any, Protocol

USER_AGENT = "ResourceExplorer-OpenData/1 (read-only catalog queries)"
TIMEOUT_SECONDS = 20.0


class TransportError(RuntimeError):
    """The source could not be reached or answered with an error status. Never read as "found nothing"."""


class Transport(Protocol):
    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any: ...

    def get_text(self, url: str, params: dict | None = None, headers: dict | None = None) -> str: ...


class HttpTransport:
    """GET JSON over httpx. Read-only; a non-2xx answer or non-JSON body raises `TransportError`."""

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        import httpx

        sent = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        try:
            resp = httpx.get(url, params=params, headers=sent, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise TransportError(f"{url}: {exc}") from exc
        if resp.status_code >= 400:
            raise TransportError(f"{url}: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise TransportError(f"{url}: the answer was not JSON") from exc

    def get_text(self, url: str, params: dict | None = None, headers: dict | None = None) -> str:
        """GET a text body (re3data answers XML). Same rules as `get_json`: read-only, non-2xx raises."""
        import httpx

        sent = {"User-Agent": USER_AGENT, "Accept": "text/xml, application/xml", **(headers or {})}
        try:
            resp = httpx.get(url, params=params, headers=sent, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise TransportError(f"{url}: {exc}") from exc
        if resp.status_code >= 400:
            raise TransportError(f"{url}: HTTP {resp.status_code}")
        return resp.text
