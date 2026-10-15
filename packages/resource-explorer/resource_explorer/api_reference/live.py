"""A running instance's OpenAPI document: register its URL, fetch it read-only, validate it, store it.

Posture (mirrors `doc_source_probe.py`): GET only; http(s) only; a fresh client per fetch with no cookies, no
credentials and no environment proxy; the response is streamed and cut off at a byte cap; a timeout; at most a
few redirects and only to the same host and port. The body is accepted only when it parses as JSON or YAML AND
is an OpenAPI/Swagger document: a console that answers every path with HTML (TestGen's Streamlit UI does) is
rejected by name ("not an OpenAPI document: got text/html"), never read as an empty spec.

Storage: no new table. One `app_settings` row per repository, key `api_reference:instance:<slug>`, whose value
is JSON {url, registered_at, registered_by, fetched_at, attempted_at, status, error, content_type, bytes,
document}. A failed re-fetch keeps the last good document and its `fetched_at` and records the failure beside
them, so the pane can say "showing the copy from <fetched_at>; the last check failed: <reason>".
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from resource_explorer.api_reference.model import SOURCE_LIVE, Interface
from resource_explorer.api_reference.openapi import load_document, openapi_rejection, parse_openapi

log = logging.getLogger(__name__)

MAX_BYTES = 5_000_000
TIMEOUT_SECONDS = 8.0
MAX_REDIRECTS = 3
SETTING_PREFIX = "api_reference:instance:"
_HTML_TYPES = ("text/html", "application/xhtml+xml")


@dataclass
class FetchResult:
    ok: bool
    reason: str = ""
    url: str = ""
    status_code: int | None = None
    content_type: str = ""
    bytes: int = 0
    document: dict | None = None
    fetched_at: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _url_problem(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return "only http(s) URLs are fetched"
    if p.scheme not in ("http", "https") or not p.hostname:
        return "only http(s) URLs are fetched"
    if p.username or p.password:
        return "a URL carrying credentials is refused: RE sends none"
    return ""


def _origin(url: str) -> tuple:
    p = urlparse(url)
    return (p.hostname, p.port or (443 if p.scheme == "https" else 80))


def _fail(url: str, reason: str, **kw) -> FetchResult:
    return FetchResult(ok=False, reason=reason, url=url, **kw)


def fetch_openapi(url: str, *, transport=None, timeout: float = TIMEOUT_SECONDS,
                  max_bytes: int = MAX_BYTES) -> FetchResult:
    url = (url or "").strip()
    problem = _url_problem(url)
    if problem:
        return _fail(url, problem)
    current = url
    try:
        with httpx.Client(transport=transport, follow_redirects=False, timeout=timeout, trust_env=False,
                          headers={"Accept": "application/json, application/yaml;q=0.9, */*;q=0.1",
                                   "User-Agent": "resource-explorer-api-reference/1"}) as client:
            for hop in range(MAX_REDIRECTS + 1):
                with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        if hop >= MAX_REDIRECTS:
                            return _fail(url, "too many redirects")
                        nxt = urljoin(current, resp.headers["location"])
                        if _url_problem(nxt) or _origin(nxt) != _origin(url):
                            return _fail(url, "the address redirects to another host; RE follows redirects only "
                                              "within the same host")
                        current = nxt
                        continue
                    return _read(url, resp, max_bytes)
    except httpx.TimeoutException:
        return _fail(url, f"no answer within {timeout:g}s")
    except httpx.ConnectError as exc:
        return _fail(url, f"could not connect: {str(exc)[:120] or 'connection refused'}")
    except httpx.RequestError as exc:
        return _fail(url, f"the request failed ({type(exc).__name__})")
    return _fail(url, "too many redirects")


def _read(url: str, resp, max_bytes: int) -> FetchResult:
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    code = resp.status_code
    if code in (401, 403):
        return _fail(url, f"the server asked for sign-in ({code}); RE sends no credentials", status_code=code,
                     content_type=ctype)
    if code == 404 or code == 410:
        return _fail(url, f"the server answered {code}: no document at that address", status_code=code,
                     content_type=ctype)
    if not 200 <= code < 300:
        return _fail(url, f"the server answered {code}", status_code=code, content_type=ctype)
    declared = resp.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        return _fail(url, f"the document is larger than {max_bytes} bytes", status_code=code, content_type=ctype)
    if ctype in _HTML_TYPES:
        return _fail(url, f"not an OpenAPI document: got {ctype}", status_code=code, content_type=ctype)
    chunks: list = []
    size = 0
    for chunk in resp.iter_bytes():
        size += len(chunk)
        if size > max_bytes:
            return _fail(url, f"the document is larger than {max_bytes} bytes", status_code=code, content_type=ctype)
        chunks.append(chunk)
    text = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    try:
        doc = load_document(text, hint=ctype)
    except ValueError as exc:
        return _fail(url, f"not an OpenAPI document: {exc}", status_code=code, content_type=ctype, bytes=size)
    reason = openapi_rejection(doc)
    if reason:
        return _fail(url, reason, status_code=code, content_type=ctype, bytes=size)
    return FetchResult(ok=True, url=url, status_code=code, content_type=ctype, bytes=size, document=doc,
                       fetched_at=_now())


# ── storage (app_settings, no new table) ─────────────────────────────────────

def _key(registry, slug: str) -> str:
    return SETTING_PREFIX + registry._normalize_slug(slug)


def load_instance(registry, slug: str) -> dict | None:
    raw = registry.get_setting(_key(registry, slug))
    if not raw:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def _save(registry, slug: str, rec: dict) -> None:
    registry.set_setting(_key(registry, slug), json.dumps(rec, default=str))


def register_instance(registry, slug: str, url: str, *, by: str = "", transport=None) -> dict:
    """Fetch `url`; keep it only when it is a real OpenAPI document. A rejected URL stores nothing."""
    res = fetch_openapi(url, transport=transport)
    if not res.ok:
        return {"ok": False, "reason": res.reason, "url": res.url}
    now = _now()
    rec = {"url": res.url, "registered_at": now, "registered_by": by, "fetched_at": res.fetched_at,
           "attempted_at": now, "status": "ok", "error": "", "content_type": res.content_type,
           "bytes": res.bytes, "document": res.document}
    _save(registry, slug, rec)
    return {"ok": True, "reason": "", "url": res.url, "fetched_at": res.fetched_at, "bytes": res.bytes,
            "operations": _count_operations(res.document)}


def refetch_instance(registry, slug: str, *, transport=None) -> dict:
    rec = load_instance(registry, slug)
    if not rec:
        return {"ok": False, "reason": "no running-instance URL is registered"}
    res = fetch_openapi(rec["url"], transport=transport)
    now = _now()
    if res.ok:
        rec.update(fetched_at=res.fetched_at, attempted_at=now, status="ok", error="",
                   content_type=res.content_type, bytes=res.bytes, document=res.document)
        _save(registry, slug, rec)
        return {"ok": True, "reason": "", "url": rec["url"], "fetched_at": res.fetched_at,
                "operations": _count_operations(res.document)}
    rec.update(attempted_at=now, status="failed", error=res.reason)
    _save(registry, slug, rec)
    return {"ok": False, "reason": res.reason, "url": rec["url"]}


def clear_instance(registry, slug: str) -> bool:
    key = _key(registry, slug)
    existed = registry.get_setting(key) is not None
    with registry._conn() as conn:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
    return existed


def instance_status(rec: dict | None) -> dict | None:
    if not rec:
        return None
    return {"url": rec.get("url", ""), "status": rec.get("status", ""), "error": rec.get("error", ""),
            "fetched_at": rec.get("fetched_at", ""), "attempted_at": rec.get("attempted_at", ""),
            "registered_by": rec.get("registered_by", ""), "registered_at": rec.get("registered_at", ""),
            "bytes": rec.get("bytes", 0), "content_type": rec.get("content_type", "")}


def instance_interface(registry, slug: str) -> Interface | None:
    rec = load_instance(registry, slug)
    if not rec or not isinstance(rec.get("document"), dict):
        return None
    try:
        return parse_openapi(rec["document"], source=SOURCE_LIVE, origin=rec.get("url", ""),
                             as_of=rec.get("fetched_at", ""))
    except ValueError:
        log.warning("stored instance document for %s no longer parses", slug, exc_info=True)
        return None


def _count_operations(doc: dict) -> int:
    n = 0
    for item in (doc.get("paths") or {}).values():
        if isinstance(item, dict):
            n += sum(1 for m in item if str(m).lower() in ("get", "put", "post", "delete", "options", "head", "patch", "trace"))
    return n
