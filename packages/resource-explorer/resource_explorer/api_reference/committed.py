"""A spec committed in the repository: found and parsed during the survey, from the checkout already held.

No new download: `repo_symbol_extraction` already holds the zipball root, so it hands that root to
`capture_committed_specs`, which finds the repository's own OpenAPI/Swagger files (same rule as
`interface_surface`'s `published_spec`: a basename `openapi|swagger.(yaml|yml|json)` or a file in an
`openapi/` or `swagger/` directory; never vendored, generated, test or example trees), parses each, and stores
the result as findings of kind `api_reference_spec` (check_name = the file's path). Each capture supersedes the
previous one, so a spec that was deleted stops answering.

A file that cannot be read as a spec is stored as an `unreadable` finding with its reason: that is a statement
about the file, not an absence of a spec.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from resource_explorer.api_reference.model import SOURCE_COMMITTED, Interface
from resource_explorer.api_reference.openapi import load_document, openapi_rejection, parse_openapi
from resource_explorer.ingestion.vendored import is_vendored_abs

log = logging.getLogger(__name__)

KIND = "api_reference_spec"
MAX_SPEC_BYTES = 5_000_000
MAX_SPEC_FILES = 12
_SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "thirdparty", ".venv", "venv", "site-packages",
              "dist", "build", "target", "out", "generated", "__pycache__"}


def find_spec_files(root) -> list:
    """Relative POSIX paths of the repository's own OpenAPI/Swagger files under `root`, sorted."""
    from resource_explorer.surveyors.sub_surveyors.interface_surface import _SPEC_PATTERNS, _VENDORED

    root = Path(root)
    patterns = [_SPEC_PATTERNS["openapi"], _SPEC_PATTERNS["openapi_dir"]]
    found: list = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if _VENDORED.search(rel) or is_vendored_abs(full, root):
                continue
            if any(p.search(rel) for p in patterns):
                found.append(rel)
    return sorted(found)[:MAX_SPEC_FILES]


def capture_committed_specs(registry, slug: str, root, *, surveyed_at: str) -> dict:
    root = Path(root)
    paths = find_spec_files(root)
    findings: list = []
    parsed = 0
    for rel in paths:
        try:
            full = root / rel
            if full.stat().st_size > MAX_SPEC_BYTES:
                raise ValueError(f"not an OpenAPI document: the file is larger than {MAX_SPEC_BYTES} bytes")
            doc = load_document(full.read_text(encoding="utf-8", errors="replace"), hint=rel)
            reason = openapi_rejection(doc)
            if reason:
                raise ValueError(reason)
            iface = parse_openapi(doc, source=SOURCE_COMMITTED, origin=rel, as_of=surveyed_at)
        except (ValueError, OSError) as exc:
            msg = str(exc)
            if not msg.startswith("not an OpenAPI document"):
                msg = f"not an OpenAPI document: {msg}"
            findings.append({"check_name": rel, "label": "unreadable", "summary": msg, "confidence": 100,
                             "detail": {"reason": msg}})
            continue
        parsed += 1
        findings.append({
            "check_name": rel, "label": "parsed", "confidence": 100,
            "summary": f"{iface.spec_version}: {len(iface.operations)} operation(s) in {rel}",
            "detail": iface.to_dict()})
    registry.upsert_finding(slug, KIND, findings, surveyed_at=surveyed_at, supersedes_previous=True)
    return {"found": len(paths), "parsed": parsed, "paths": paths}


def load_committed(registry, slug: str):
    """([Interface], [problem]) from the latest capture. Interfaces: most operations first."""
    ifaces: list = []
    problems: list = []
    for row in registry.query_findings(slug, KIND) or []:
        raw = row.get("detail_json")
        try:
            detail = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            detail = {}
        if row.get("label") == "parsed" and detail:
            iface = Interface.from_dict(detail)
            iface.source, iface.origin = SOURCE_COMMITTED, row["check_name"]
            iface.as_of = row.get("surveyed_at") or iface.as_of
            ifaces.append(iface)
        else:
            problems.append({"path": row["check_name"], "reason": detail.get("reason") or row.get("summary", "")})
    ifaces.sort(key=lambda i: (-len(i.operations), i.origin))
    return ifaces, problems
