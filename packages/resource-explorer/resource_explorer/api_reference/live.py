"""A running instance's OpenAPI document: register its URL, fetch it read-only, validate it, store it.

Posture (mirrors `doc_source_probe.py`): GET only; http(s) only; a fresh client per fetch with no cookies, no
credentials and no environment proxy; the response is streamed and cut off at a byte cap; a timeout; at most a
few redirects and only to the same host and port. The body is accepted only when it parses as JSON or YAML AND
is an OpenAPI/Swagger document: a console that answers every path with HTML (TestGen's Streamlit UI does) is
rejected by name ("not an OpenAPI document: got text/html"), never read as an empty spec.

Address policy: `fetch_policy.py` (deny by default, setting RE_API_FETCH_ALLOW), checked at every hop, with the
connection pinned to the address that was checked.

Storage: the api_reference_* tables (`store.py`): one current `running_instance` document per repository whose
`origin` is the registered URL, with who registered it and when. A failed re-fetch keeps the last good content
and its capture time and records the failure beside them ("showing the copy fetched <time>; the last check
failed: <reason>"). A clear keeps a tombstone row (cleared_by, cleared_at).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from resource_explorer.api_reference import fetch_policy, store
from resource_explorer.api_reference.model import SOURCE_LIVE, Interface
from resource_explorer.api_reference.openapi import (
    bounded_dumps, load_document, openapi_rejection, parse_openapi)

log = logging.getLogger(__name__)

MAX_BYTES = 5_000_000
TIMEOUT_SECONDS = 8.0            # one read or connect may wait this long ...
TOTAL_SECONDS = 15.0             # ... but the whole fetch, redirects included, never runs longer than this
MAX_RECORD_BYTES = 8_000_000     # what one fetched document may serialise to
MAX_REDIRECTS = 3
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
        port = p.port           # raises ValueError for a bad port
    except ValueError:
        return "not a valid address"
    del port
    if p.scheme not in ("http", "https") or not p.hostname:
        return "only http(s) URLs are fetched"
    if p.username or p.password:
        return "a URL carrying credentials is refused: RE sends none"
    return ""


def _port(url: str) -> int:
    p = urlparse(url)
    return p.port or (443 if p.scheme == "https" else 80)


def _origin(url: str) -> tuple:
    return (urlparse(url).hostname, _port(url))


def _fail(url: str, reason: str, **kw) -> FetchResult:
    return FetchResult(ok=False, reason=reason, url=url, **kw)


def fetch_openapi(url: str, *, transport=None, timeout: float = TIMEOUT_SECONDS,
                  max_bytes: int = MAX_BYTES, total_seconds: float = TOTAL_SECONDS,
                  allow=None, resolver=None) -> FetchResult:
    """Never raises: every way this can go wrong is a FetchResult with a reason. Reasons say what kind of
    failure it was and not the raw exception text (which would tell a caller what is listening where).

    Pinning: each hop resolves the name once (`fetch_policy.check_target`) and the request goes to the address
    that was checked, with the original Host header and (https) the original name as the TLS server name, so a
    second DNS answer is never consulted. Only the first address is tried; there is no fallback to the others."""
    url = (url or "").strip()
    problem = _url_problem(url)
    if problem:
        return _fail(url, problem)
    deadline = time.monotonic() + total_seconds
    current = url
    try:
        with httpx.Client(transport=transport, follow_redirects=False, timeout=timeout, trust_env=False,
                          headers={"Accept": "application/json, application/yaml;q=0.9, */*;q=0.1",
                                   "User-Agent": "resource-explorer-api-reference/1"}) as client:
            for hop in range(MAX_REDIRECTS + 1):
                if time.monotonic() > deadline:
                    return _fail(url, "no answer in time")
                target = fetch_policy.check_target(urlparse(current).hostname, _port(current),
                                                   allow=allow, resolver=resolver)
                if not target.ok:
                    return _fail(url, target.reason)
                if not target.ip:
                    return _fail(url, "could not connect")
                parsed = urlparse(current)
                pinned = httpx.URL(current).copy_with(host=target.ip)
                host_header = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
                ext = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
                with client.stream("GET", pinned, headers={"Host": host_header}, extensions=ext) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        if hop >= MAX_REDIRECTS:
                            return _fail(url, "too many redirects")
                        nxt = urljoin(current, resp.headers["location"])
                        bad = _url_problem(nxt)
                        if bad == "not a valid address":
                            return _fail(url, "the address redirects to an address that is not valid")
                        if bad:
                            return _fail(url, "the address redirects to somewhere RE does not fetch from")
                        if _origin(nxt) != _origin(url):
                            t2 = fetch_policy.check_target(urlparse(nxt).hostname, _port(nxt), allow=allow, resolver=resolver)
                            return _fail(url, t2.reason or "the address redirects to another host; RE follows "
                                                             "redirects only within the same host")
                        current = nxt
                        continue
                    return _read(url, resp, max_bytes, deadline)
    except httpx.TimeoutException:
        return _fail(url, "no answer in time")
    except httpx.ConnectError:
        return _fail(url, "could not connect")
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, OSError):
        return _fail(url, "the request could not be completed")
    return _fail(url, "too many redirects")


def _read(url: str, resp, max_bytes: int, deadline: float) -> FetchResult:
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    code = resp.status_code
    if code in (401, 403):
        return _fail(url, f"needs sign-in ({code}); RE sends no credentials", status_code=code, content_type=ctype)
    if code in (404, 410):
        return _fail(url, f"answered {code}: no document at that address", status_code=code, content_type=ctype)
    if not 200 <= code < 300:
        return _fail(url, f"answered {code}", status_code=code, content_type=ctype)
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
        if time.monotonic() > deadline:
            return _fail(url, "no answer in time", status_code=code, content_type=ctype)
        chunks.append(chunk)
    text = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    try:
        doc = load_document(text, hint=ctype)
    except ValueError as exc:
        return _fail(url, f"not an OpenAPI document: {exc}", status_code=code, content_type=ctype, bytes=size)
    reason = openapi_rejection(doc)
    if not reason:
        try:
            parse_openapi(doc, source=SOURCE_LIVE, origin=url)      # a document that will not read is rejected NOW
            bounded_dumps(doc, MAX_RECORD_BYTES)                      # and so is one too big to keep
        except ValueError as exc:
            reason = str(exc) if str(exc).startswith("not an OpenAPI") else "the document is too large to keep"
    if reason:
        return _fail(url, reason, status_code=code, content_type=ctype, bytes=size)
    return FetchResult(ok=True, url=url, status_code=code, content_type=ctype, bytes=size, document=doc,
                       fetched_at=_now())


# ── storage (api_reference_* tables; see store.py) ───────────────────────────

def _view(doc: dict | None) -> dict | None:
    """The registration as the pane and routes read it (no content)."""
    if not doc:
        return None
    return {"id": doc["id"], "url": doc["origin"], "status": doc["status"], "error": doc["reason"],
            "fetched_at": doc["captured_at"], "attempted_at": doc["attempted_at"],
            "registered_by": doc["registered_by"], "registered_at": doc["registered_at"],
            "bytes": doc["byte_count"] or 0, "content_type": doc["content_type"], "cleared_by": doc["cleared_by"],
            "cleared_at": doc["cleared_at"]}


def _current(registry, slug: str) -> dict | None:
    docs = store.documents(registry, slug, SOURCE_LIVE)
    return docs[0] if docs else None


def load_instance(registry, slug: str) -> dict | None:
    """The live registration, or None when none is registered (a cleared one is history, see `clear_record`)."""
    d = _current(registry, slug)
    return _view(d) if d and d["status"] in ("ok", "failed") else None


def clear_record(registry, slug: str) -> dict | None:
    """Who cleared the last registration and when, kept after a clear so it is not a silent delete."""
    d = _current(registry, slug)
    return _view(d) if d and d["status"] == "cleared" else None


def register_instance(registry, slug: str, url: str, *, by: str = "", transport=None, allow=None,
                      resolver=None) -> dict:
    """Fetch `url`; keep it only when it is a real OpenAPI document. A rejected URL stores nothing."""
    res = fetch_openapi(url, transport=transport, allow=allow, resolver=resolver)
    if not res.ok:
        return {"ok": False, "reason": res.reason, "url": res.url}
    iface = parse_openapi(res.document, source=SOURCE_LIVE, origin=res.url, as_of=res.fetched_at)
    store.save_instance(registry, slug, res.url, iface, fetched_at=res.fetched_at, by=by,
                        content_type=res.content_type, byte_count=res.bytes)
    return {"ok": True, "reason": "", "url": res.url, "fetched_at": res.fetched_at, "bytes": res.bytes,
            "operations": iface.total_operations}


def refetch_instance(registry, slug: str, *, transport=None, allow=None, resolver=None) -> dict:
    rec = load_instance(registry, slug)
    if not rec:
        return {"ok": False, "reason": "no running-instance URL is registered"}
    res = fetch_openapi(rec["url"], transport=transport, allow=allow, resolver=resolver)
    if res.ok:
        iface = parse_openapi(res.document, source=SOURCE_LIVE, origin=rec["url"], as_of=res.fetched_at)
        store.update_instance(registry, slug, iface, fetched_at=res.fetched_at, content_type=res.content_type,
                              byte_count=res.bytes)
        return {"ok": True, "reason": "", "url": rec["url"], "fetched_at": res.fetched_at,
                "operations": iface.total_operations}
    store.update_instance(registry, slug, None, reason=res.reason)
    return {"ok": False, "reason": res.reason, "url": rec["url"]}


def clear_instance(registry, slug: str, *, by: str = "") -> bool:
    """Forget the URL and the stored copy. The header row stays as a tombstone naming who cleared it and when."""
    return store.clear_instance(registry, slug, by)


def instance_status(rec: dict | None) -> dict | None:
    if not rec:
        return None
    return {k: rec.get(k, "") for k in ("url", "status", "error", "fetched_at", "attempted_at", "registered_by",
                                         "registered_at", "bytes", "content_type")}


def instance_interface_with_reason(registry, slug: str):
    """(Interface | None, why not). A registration whose stored rows can no longer be read says so, in its own
    words, instead of reading as "nothing registered"."""
    d = _current(registry, slug)
    if not d or d["status"] not in ("ok", "failed"):
        return None, ""
    return store.load_interface(registry, d)


def instance_interface(registry, slug: str) -> Interface | None:
    return instance_interface_with_reason(registry, slug)[0]
