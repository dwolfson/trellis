"""Open data routes (slice OD1): Data portals, Portal directories, search, directory run, import.

Registration follows `filesystems.py`: POST /, a check call, a summary model. Any signed-in user may register, as
for file systems today (open question for the owner, noted in the PR: admin-only?). Nothing here surveys, profiles
or publishes, and nothing writes to Egeria; the one Egeria call is the read-first identifier match inside import.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from resource_explorer.open_data import service
from resource_explorer.open_data.adapters import discover_adapters
from resource_explorer.open_data.absence import NOT_REPORTED
from resource_explorer.open_data.store import OpenDataStore
from resource_explorer.open_data.transport import HttpTransport
from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)
router = APIRouter()


# Seams a test replaces: outbound HTTP, the Egeria read, and who is signed in.
def _transport():
    return HttpTransport()


def _egeria_lookup():
    from resource_explorer.open_data.match import EgeriaIdentifierLookup

    return EgeriaIdentifierLookup()


def _signed_in_user(request: Request) -> str:
    from resource_explorer.auth import get_current_user

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to register portals and import open data.")
    return str(user.get("sub") or user.get("user_id") or "")


def _store() -> OpenDataStore:
    return OpenDataStore(ProjectRegistry())


def _http(exc: service.OpenDataError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, service.NotFound) else 422, detail=str(exc))


class PortalRegistration(BaseModel):
    display_name: str
    api_kind: str = "CKAN"
    base_url: str
    api_key: str = ""
    slug: str = ""


class DirectoryRegistration(BaseModel):
    display_name: str
    api_kind: str = "dataportals.org"
    base_url: str = ""


class SearchRequest(BaseModel):
    terms: str = ""
    filters: dict = Field(default_factory=dict)
    pages: int = service.DEFAULT_SEARCH_PAGES


class ChosenRow(BaseModel):
    portal_slug: str
    dataset_id: str


class ImportRequest(BaseModel):
    rows: list[ChosenRow]
    work_list_name: str = ""
    work_list_slug: str = ""
    investigation: str = ""
    terms: str = ""


class DirectoryRunRequest(BaseModel):
    pages: int = 1
    terms: str = ""


class DirectoryImportRequest(BaseModel):
    urls: list[str]


def _portal_summary(p: dict) -> dict:
    cost = service.portal_cost(p)
    return {**{k: p[k] for k in ("slug", "display_name", "api_kind", "base_url", "origin", "registered_by",
                                 "registered_at", "adapter")},
            "has_key": bool(p["secret_ref"]), "cost": cost,
            "adapter_available": bool(cost)}


@router.get("/adapters")
def list_adapters() -> list[dict]:
    """What is installed (built-ins plus the `trellis.open_data` entry points), by manifest; an entry point that
    failed to load is listed too, with `error` and no cost shape."""
    from resource_explorer.open_data.adapters import adapter_load_failures

    rows = [{"name": c.manifest.name, "api_kind": c.manifest.api_kind, "role": c.manifest.role,
             "calls_per_page": c.manifest.calls_per_page, "page_size": c.manifest.page_size,
             "needs_key": c.manifest.needs_key, "error": ""} for c in discover_adapters().values()]
    rows += [{"name": n, "api_kind": "", "role": "", "calls_per_page": None, "page_size": None, "needs_key": False,
              "error": e} for n, e in adapter_load_failures().items()]
    return rows


# ── portals ──────────────────────────────────────────────────────────────────

@router.get("/portals")
def list_portals() -> list[dict]:
    return [_portal_summary(p) for p in _store().list_portals()]


@router.post("/portals")
def register_portal(reg: PortalRegistration, request: Request) -> dict:
    who = _signed_in_user(request)
    store = _store()
    try:
        portal = service.register_portal(store, display_name=reg.display_name, api_kind=reg.api_kind,
                                         base_url=reg.base_url, api_key=reg.api_key, registered_by=who, slug=reg.slug)
    except service.OpenDataError as exc:
        raise _http(exc) from exc
    return _portal_summary(portal)


@router.post("/portals/check")
def check_portal(reg: PortalRegistration) -> dict:
    """Can RE reach this portal? One read-only call (page 1, one row). A warning for the form, never a gate."""
    from resource_explorer.open_data.adapters import adapter_for_api_kind

    cls = adapter_for_api_kind(reg.api_kind, "portal")
    if cls is None:
        return {"ok": False, "words": f"no adapter for {reg.api_kind} yet"}
    try:
        got = cls(reg.base_url.rstrip("/"), _transport(), "").search("", {}, 1)
    except Exception as exc:
        return {"ok": False, "words": f"could not reach it · {exc}"[:240]}
    return {"ok": True, "words": "reachable", "total": got["total"]}


@router.delete("/portals/{slug}")
def remove_portal(slug: str, request: Request) -> dict:
    _signed_in_user(request)
    return {"removed": _store().remove_portal(slug)}


@router.post("/portals/{slug}/search")
def search_portal(slug: str, req: SearchRequest) -> dict:
    try:
        return service.run_search(_store(), slug, terms=req.terms, filters=req.filters, pages=req.pages,
                                  transport=_transport())
    except service.OpenDataError as exc:
        raise _http(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"The portal did not answer: {exc}") from exc


@router.get("/portals/{slug}/price")
def search_price(slug: str, pages: int = service.DEFAULT_SEARCH_PAGES) -> dict:
    """The price line, before the press."""
    portal = _store().get_portal(slug)
    if not portal:
        raise HTTPException(status_code=404, detail=f"No portal '{slug}'.")
    try:
        return service.search_price(portal, pages)
    except service.OpenDataError as exc:
        raise _http(exc) from exc


@router.post("/portals/{slug}/import")
def import_rows(slug: str, req: ImportRequest, request: Request) -> dict:
    who = _signed_in_user(request)
    chosen = [service.Chosen(c.portal_slug or slug, c.dataset_id) for c in req.rows]
    name = req.work_list_name or service.default_work_list_name("", req.terms)
    try:
        return service.import_datasets(
            _store(), chosen, work_list_name=name, transport=_transport(), egeria_lookup=_egeria_lookup(),
            imported_by=who, investigation=req.investigation, work_list_slug=req.work_list_slug)
    except service.OpenDataError as exc:
        raise _http(exc) from exc


@router.post("/lens-terms")
def lens_terms(lens: dict, investigation: str = "") -> dict:
    """Search terms from a data request's lens {subjects, period, places}; editable by the caller. No investigation
    lens is stored on this build (`catalogue_scope.data_lens_for`), so the lens comes in the body."""
    fallback = ""
    if investigation:
        try:
            inv = ProjectRegistry().get_investigation(investigation)
            fallback = (inv.get("display_name", "") if isinstance(inv, dict) else getattr(inv, "display_name", "")) or ""
        except Exception:
            fallback = ""
    return service.terms_from_lens(lens, fallback)


# ── datasets ─────────────────────────────────────────────────────────────────

@router.get("/datasets")
def list_datasets() -> list[dict]:
    return [{k: d[k] for k in ("slug", "identifier", "title", "publisher", "licence_id", "portals", "work_list_slug",
                               "imported_at")} for d in _store().list_datasets()]


@router.get("/datasets/{slug}")
def get_dataset(slug: str) -> dict:
    """The resource page: the verbatim record, the normalised fields with who stated them and when, and the
    absence word for every question a survey will answer (OD2)."""
    d = _store().get_dataset(slug)
    if not d:
        raise HTTPException(status_code=404, detail=f"No open data '{slug}'.")
    d["stated_by"] = d["portals"]
    d["survey"] = "no survey yet · scout arrives with OD2"
    return d


# ── directories ──────────────────────────────────────────────────────────────

@router.get("/directories")
def list_directories() -> list[dict]:
    return _store().list_directories()


@router.post("/directories")
def register_directory(reg: DirectoryRegistration, request: Request) -> dict:
    who = _signed_in_user(request)
    try:
        return service.register_directory(
            _store(), display_name=reg.display_name, api_kind=reg.api_kind,
            base_url=reg.base_url or "https://dataportals.org/api/data.json", registered_by=who)
    except service.OpenDataError as exc:
        raise _http(exc) from exc


@router.post("/directories/{slug}/run")
def run_directory(slug: str, req: DirectoryRunRequest) -> dict:
    try:
        return service.run_directory(_store(), slug, pages=req.pages, terms=req.terms, transport=_transport())
    except service.OpenDataError as exc:
        raise _http(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"The directory did not answer: {exc}") from exc


@router.post("/directories/{slug}/import")
def import_directory_rows(slug: str, req: DirectoryImportRequest, request: Request) -> dict:
    who = _signed_in_user(request)
    try:
        return service.import_portals(_store(), slug, req.urls, transport=_transport(), registered_by=who)
    except service.OpenDataError as exc:
        raise _http(exc) from exc
