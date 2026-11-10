"""Dashboard Sheets held in Egeria, read-only (brief EA-CATCHUP-AND-DASHBOARDS B5, decisions D4 and D6).

EA lists the Dashboard Sheets Egeria holds and shows one, AS THE SIGNED-IN USER. The data step is
pyegeria's (`pyegeria.view.dashboard_resolver`, the same step the Portal uses, D4); the display, the cache
and the sign-in are EA's own.

Visibility (§4.7 of the brief), stated here because the cache is where it would leak:
  - Every Egeria read here is made with the viewer's own bearer token (`apply_token`). There is no
    service-user fallback: with no token there is nothing to read as, so the caller is told to sign in.
    Egeria's zone check on that read decides what the viewer sees: a sheet in a zone they cannot see is
    not listed and reads as "not visible"; a Report or an EGERIA-tier ReportSpec in such a zone comes back
    from the resolver as a "restricted" placement ("not visible to you"), never runnable.
  - The cache is keyed by CREDENTIAL IDENTITY: a hash of the token actually presented, plus the platform
    and view server (the Portal's `credential_identity` rule, 11-09). Never a bare user_id and never a
    token's unverified `sub`: a cache hit makes no Egeria call, so a claim-based key would let one user
    read another's entry. A renewed token is a new key. Nothing secret is stored.
  - Only answers are cached ("ok", "no sheets", "not visible"). A failed read is never cached, and a
    refused token is raised to the caller as a sign-in problem, never cached as an answer.
  - The EGERIA spec tier is filled by EA's service user into a shared cache (B3), so a spec found there
    may be one this viewer cannot see. The resolver re-reads such a spec by GUID as the viewer
    (`check_spec_visibility=True`): Egeria's own check is the authority over the shared tier.

Absence is not zero: "no sheets" (Egeria answered and holds none this viewer can see), "could not read"
(Egeria did not answer), and "not visible" (no sheet of that name for this viewer) are three answers with
three messages.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

#: How long a viewer's listing or resolved sheet is reused before Egeria is read again.
CACHE_TTL_S = 120.0
_CACHE_MAX = 512

#: The reason a restricted placement gives; the same words as pyegeria and the Portal.
NOT_VISIBLE = "not visible to you"

#: Output formats a report placement may ask for that EA's report execution can display.
_DISPLAY_FORMATS = {"TABLE", "REPORT", "MERMAID", "LIST", "FORM", "HTML"}

_cache: Dict[str, Tuple[float, Any]] = {}
_lock = threading.Lock()


class SignInRequired(Exception):
    """No usable credential of the viewer's own: dashboards are read only as the signed-in user."""


class TokenRefused(Exception):
    """Egeria refused the viewer's token (expired or invalid): they must sign in again."""


# ── identity and clients ──────────────────────────────────────────────────────

def _connection(creds: Optional[Dict[str, str]]) -> Dict[str, str]:
    """The viewer's connection: EA's platform/server, the viewer's user id and token. Raises
    SignInRequired when there is no token: a password-backed (service) connection is never used here."""
    if not creds or not creds.get("token") or not creds.get("user_id"):
        raise SignInRequired("Sign in to see dashboards: they are read from Egeria as you.")
    from advisor.report_pipeline import get_report_pipeline
    conn = get_report_pipeline()._read_pyegeria_connection(egeria_credentials=creds)
    if not (conn.get("view_server") and conn.get("platform_url")):
        raise ConnectionError("Egeria connection is not configured (config/mcp_servers.json -> pyegeria.env)")
    conn["user_pwd"] = ""          # never a password: the token is the only credential used
    return conn


def credential_identity(conn: Dict[str, str]) -> str:
    """Who a cache entry belongs to: a hash of the token PRESENTED, plus platform and server."""
    digest = hashlib.sha256(conn["token"].encode()).hexdigest()
    return f"t:{digest}|{conn['platform_url']}|{conn['view_server']}"


def _build_client(conn: Dict[str, str]) -> Any:
    from pyegeria import EgeriaTech
    from advisor.auth import apply_token
    client = EgeriaTech(conn["view_server"], conn["platform_url"], conn["user_id"], "")
    apply_token(client, conn["token"])
    return client


def _is_token_refused(exc: BaseException) -> bool:
    """A 401 is the viewer's token, not an element: it must reach the UI as "sign in again". A 403 for an
    element in a hidden zone is the resolver's business ("restricted"), not this."""
    try:
        from pyegeria.core._exceptions import PyegeriaUnauthorizedException
    except ImportError:  # pragma: no cover
        PyegeriaUnauthorizedException = ()  # type: ignore[assignment]
    code = getattr(exc, "related_http_code", None)
    if isinstance(exc, PyegeriaUnauthorizedException) and code == 401:
        return True
    if code == 403:
        # pyegeria <= 6.2.32 words a 403-020 (element in a hidden zone) "AUTHORIZATION_ERROR_401":
        # that is the resolver's "restricted", never the viewer's token.
        return False
    text = str(exc)
    if "403-020" in text or "is not authorized to issue an operation read" in text:
        return False
    return "401" in text and ("token" in text.lower() or "unauthor" in text.lower())


def _words(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"


# ── the cache, per credential identity ────────────────────────────────────────

def _cache_get(key: str, refresh: bool) -> Any:
    if refresh:
        return None
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    return None


def _cache_put(key: str, value: Any) -> None:
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[: _CACHE_MAX // 4]:
                _cache.pop(k, None)
        _cache[key] = (time.monotonic(), value)


def invalidate() -> None:
    """Drop every cached listing and sheet (e.g. after the EGERIA spec tier is re-synced)."""
    with _lock:
        _cache.clear()


# ── source badges ─────────────────────────────────────────────────────────────

def _badge_source(spec_source: Optional[Dict[str, Any]], spec: Optional[str]) -> Optional[str]:
    """egeria / local / builtin from the resolver's spec_source, with EA's own registered specs shown as
    "user", consistent with the report catalog (B3). None when the spec was not found."""
    if not spec_source:
        return None
    tier = spec_source.get("tier")
    if tier == "local":
        from advisor.report_spec_parser import ea_registered_specs
        if spec in ea_registered_specs() or spec_source.get("label") in ea_registered_specs():
            return "user"
    return tier


# ── list ──────────────────────────────────────────────────────────────────────

def _sheet_summary(sheet: Any) -> Dict[str, Any]:
    placements = list(getattr(sheet, "placements", None) or [])
    return {
        "name": sheet.name,
        "heading": getattr(sheet, "heading", None) or sheet.name,
        "description": getattr(sheet, "description", None) or "",
        "family": getattr(sheet, "family", None),
        "placement_count": len(placements),
        "perspectives": sorted({x for p in placements for x in (getattr(p, "perspectives", None) or [])}),
        "breaks": list(getattr(sheet, "breaks", None) or []),
    }


def list_sheets(creds: Optional[Dict[str, str]], *, refresh: bool = False,
                client_factory: Optional[Callable[[Dict[str, str]], Any]] = None) -> Dict[str, Any]:
    """The sheets Egeria holds that this viewer can see.

    {"state": "ok" | "no_sheets" | "read_failed", "sheets": [...], "message": str | None, "viewer": id}
    Raises SignInRequired (no token) or TokenRefused (Egeria refused it)."""
    conn = _connection(creds)
    key = f"list|{credential_identity(conn)}"
    cached = _cache_get(key, refresh)
    if cached is not None:
        return {**cached, "cached": True}
    viewer = conn["user_id"]
    try:
        from pyegeria.view.dashboard_resolver import list_dashboard_sheets_for_viewer
        client = (client_factory or _build_client)(conn)
        sheets = list_dashboard_sheets_for_viewer(client)
    except Exception as exc:  # noqa: BLE001 -- said in words below; never cached
        if _is_token_refused(exc):
            raise TokenRefused("Egeria refused your sign-in token; sign in again.") from exc
        logger.warning(f"dashboards: listing sheets as {viewer!r} failed: {exc}")
        return {"state": "read_failed", "sheets": [], "viewer": viewer, "cached": False,
                "message": f"Could not read Dashboard Sheets from Egeria as {viewer}: {_words(exc)}"}
    out: Dict[str, Any] = {"state": "ok", "sheets": [_sheet_summary(s) for s in sheets], "viewer": viewer,
                           "message": None}
    if not out["sheets"]:
        out["state"] = "no_sheets"
        out["message"] = (f"Egeria holds no Dashboard Sheets that {viewer} can see. None may exist yet, "
                          "or every one may be in a zone you cannot see.")
    _cache_put(key, out)
    return {**out, "cached": False}


# ── show ──────────────────────────────────────────────────────────────────────

def _placement_dict(pl: Any) -> Dict[str, Any]:
    report = pl.report
    return {
        "position": pl.position,
        "ref": pl.ref,
        "kind": pl.kind,
        "title": pl.title,
        "span": pl.span,
        "emphasis": pl.emphasis,
        "perspectives": list(pl.perspectives or []),
        "content": pl.content,
        "note": pl.note,
        "restricted": bool(pl.restricted),
        "restricted_element": pl.restricted_element,
        "reason": pl.reason,
        "spec": pl.spec,
        "spec_source": dict(pl.spec_source) if pl.spec_source else None,
        "source": _badge_source(pl.spec_source, pl.spec),
        # A restricted or missing placement is never runnable, whatever else is known about it.
        "runnable": bool(pl.runnable) if pl.kind == "report" else False,
        "runnable_known": pl.runnable is not None,
        "refusal": pl.refusal,
        "error": pl.error,
        "report": None if report is None else {
            "name": report.name, "description": report.description, "output_format": report.output_format,
        },
    }


def show_sheet(creds: Optional[Dict[str, str]], name: str, *, perspective: Optional[str] = None,
               refresh: bool = False, client_factory: Optional[Callable[[Dict[str, str]], Any]] = None,
               ) -> Dict[str, Any]:
    """One sheet, resolved for this viewer (no report is run).

    {"state": "ok" | "not_visible" | "read_failed", "sheet": {...} | None, "message": str | None}
    Raises SignInRequired or TokenRefused."""
    resolved, answer = _resolved(creds, name, perspective, refresh, client_factory)
    if resolved is None:
        return answer
    sheet = {
        "name": resolved.name, "heading": resolved.heading, "description": resolved.description,
        "family": resolved.family, "perspective": resolved.perspective, "breaks": list(resolved.breaks),
        "viewer": resolved.viewer, "source": resolved.source,
        "placements": [_placement_dict(p) for p in sorted(resolved.placements, key=lambda p: p.position)],
    }
    message = None
    if not sheet["placements"]:
        message = (f"Sheet '{resolved.name}' has no placements"
                   + (f" for perspective '{perspective}'." if perspective else "."))
    return {**answer, "sheet": sheet, "message": message}


def _resolved(creds, name, perspective, refresh, client_factory) -> Tuple[Any, Dict[str, Any]]:
    """(ResolvedSheet | None, answer). The ResolvedSheet itself is cached so a run can reuse it."""
    conn = _connection(creds)
    viewer = conn["user_id"]
    key = f"sheet|{credential_identity(conn)}|{name}|{perspective or ''}"
    cached = _cache_get(key, refresh)
    if cached is not None:
        resolved = cached
        answer = {"cached": True}
    else:
        try:
            from pyegeria.view.dashboard_resolver import resolve_dashboard_sheet
            client = (client_factory or _build_client)(conn)
            resolved = resolve_dashboard_sheet(client, name, perspective=perspective, run=False,
                                               check_spec_visibility=True)
        except Exception as exc:  # noqa: BLE001 -- said in words; never cached
            if _is_token_refused(exc):
                raise TokenRefused("Egeria refused your sign-in token; sign in again.") from exc
            logger.warning(f"dashboards: resolving sheet {name!r} as {viewer!r} failed: {exc}")
            return None, {"state": "read_failed", "sheet": None, "viewer": viewer, "cached": False,
                          "message": f"Could not read Dashboard Sheet '{name}' from Egeria as {viewer}: "
                                     f"{_words(exc)}"}
        _cache_put(key, resolved if resolved is not None else _NOT_VISIBLE_MARK)
        answer = {"cached": False}
    if resolved is None or resolved is _NOT_VISIBLE_MARK:
        return None, {**answer, "state": "not_visible", "sheet": None, "viewer": viewer,
                      "message": (f"Egeria holds no Dashboard Sheet named '{name}' that {viewer} can see. "
                                  "It may not exist, or it may be in a zone you cannot see.")}
    return resolved, {**answer, "state": "ok", "viewer": viewer}


_NOT_VISIBLE_MARK = object()


# ── run one report placement ──────────────────────────────────────────────────

def _display_format(report_format: Optional[str], requested: Optional[str]) -> str:
    for fmt in (requested, report_format):
        if fmt and fmt.upper() in _DISPLAY_FORMATS:
            return fmt.upper()
    return "TABLE"


def run_placement(creds: Optional[Dict[str, str]], name: str, position: int, *,
                  perspective: Optional[str] = None, output_format: Optional[str] = None,
                  client_factory: Optional[Callable[[Dict[str, str]], Any]] = None,
                  pipeline: Any = None) -> Dict[str, Any]:
    """Run the report placement at `position` with EA's own report execution, as the viewer.

    {"state": "ok" | "failed" | "refused" | "not_visible" | "read_failed", "response": markdown | None,
     "message": str | None}. A restricted, missing or text placement is refused with its reason; a run
    that fails is "failed" with the executor's words, never "ok" with an empty response.

    An ANALYTIC spec (its action names an analytic_function) is sent its analytic params and nothing
    else: an analytic function refuses the find vocabulary (search_string, page_size, start_from) with a
    TypeError. The Portal learned this first (local_dashboards_handler, isAnalytic)."""
    resolved, answer = _resolved(creds, name, perspective, False, client_factory)
    if resolved is None:
        return {**answer, "response": None}
    pl = next((p for p in resolved.placements if p.position == position), None)
    if pl is None:
        return {"state": "refused", "response": None,
                "message": f"Sheet '{name}' has no placement at position {position} for this view."}
    if pl.kind == "restricted":
        return {"state": "refused", "response": None, "restricted": True,
                "message": f"'{pl.title}' is restricted: {pl.reason or NOT_VISIBLE}."}
    if pl.kind != "report":
        return {"state": "refused", "response": None,
                "message": f"'{pl.title}' is a {pl.kind} placement; there is no report to run"
                           + (f" ({pl.reason})." if pl.reason else ".")}
    if pl.error:
        return {"state": "refused", "response": None, "message": pl.error}
    if pl.runnable is False:
        return {"state": "refused", "response": None,
                "message": pl.refusal or f"Report spec '{pl.spec}' cannot run."}

    report = pl.report
    action = getattr(pl.format_set, "action", None)
    analytic = bool(getattr(action, "analytic_function", None)) if action is not None else False
    fmt = _display_format(report.output_format, output_format)

    if pipeline is None:
        from advisor.report_pipeline import get_report_pipeline
        pipeline = get_report_pipeline()
    query = f"dashboard {name}: {pl.title}"
    # EA's existing execution path, as the viewer: run_report -> exec_report_spec with their token.
    if analytic:
        result = pipeline._execute_report(query, pl.spec, extra_params=dict(report.analytic_params),
                                          output_type=fmt, egeria_credentials=creds, exact_params=True)
    else:
        params = dict(report.params)
        search = params.pop("search_string", None) or "*"
        result = pipeline._execute_report(query, pl.spec, search_string=search, extra_params=params or None,
                                          output_type=fmt, egeria_credentials=creds)
    base = {"output_format": fmt, "spec": pl.spec, "source": _badge_source(pl.spec_source, pl.spec),
            "analytic": analytic}
    run_error = (result or {}).get("run_error")
    response = (result or {}).get("response")
    if run_error or not response:
        words = run_error or "the run returned nothing"
        logger.info(f"dashboards: running {pl.spec!r} on {name!r} as {creds.get('user_id')!r} failed: {words}")
        return {**base, "state": "failed", "response": None,
                "message": f"'{pl.title}' did not run: {words}"}
    return {**base, "state": "ok", "response": response, "message": None}


def _reset_for_tests() -> None:
    invalidate()
