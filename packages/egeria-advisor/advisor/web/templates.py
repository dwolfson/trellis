"""
Dr.Egeria command-template API routes for Egeria Advisor.

Extracted from `app.py` (TC-5, BACKLOG.md — router-per-domain refactor,
slice 3). Fully self-contained — no dependency on `advisor.web.shared`.

**Deliberately partial.** The "templates" group is two routes in app.py's
original docstring (`GET /api/templates/Column/fields`, `GET
/api/templates/{command_name}/fields`), but only the second moved here.
`Column/fields` calls `discover_draft_schema_internal()`, which is reports/
draft-schema business logic still living in app.py's not-yet-extracted
reports section (`_SCHEMA_CACHE` + `discover_draft_schema_internal`, used by
both `GET /api/reports/drafts/{draft_id}/schema` and this one templates
route). Moving `Column/fields` here now would mean either duplicating that
logic or reaching back into app.py from a "smaller" router than the thing
it depends on — reversed from how every other slice has gone. Left with
reports (TC-5's last, largest slice) instead, where it belongs alongside
`discover_draft_schema_internal`.

Endpoints:
  GET /api/templates/{command_name}/fields → template field metadata for a
                                              Dr.Egeria command
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/templates/{command_name}/fields")
async def get_template_fields(request: Request, command_name: str, level: str = "basic") -> Dict[str, Any]:
    """Return template field metadata for a Dr.Egeria command at the given template level.

    Requires login — the valid-values enrichment below performs live Egeria reads
    and must be attributable to the signed-in user, not a shared service account.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from urllib.parse import unquote
    from advisor.agents.tools import _templates_root, _normalise
    from advisor.agents.dr_egeria_agent import parse_template

    action = unquote(command_name)
    root   = _templates_root()
    if root is None:
        return {"fields": [], "level": level}

    level_dir = root / level
    if not level_dir.is_dir():
        level_dir = root / "basic"

    query_norm = _normalise(action)
    words      = [_normalise(w) for w in action.split() if len(w) > 3]

    best_score = 0
    best_file  = None
    for md_file in sorted(level_dir.rglob("*.md")):
        stem_norm = _normalise(md_file.stem)
        score = 0
        if query_norm == stem_norm:           score = 50
        elif query_norm in stem_norm:         score = 40
        elif stem_norm in query_norm:         score = 35
        elif words:
            hits = sum(1 for w in words if w in stem_norm)
            if hits == len(words):            score = 30
            elif hits > 0:                    score = 20 + hits
        if score > best_score:
            best_score = score
            best_file  = md_file

    if best_file is None or best_score == 0:
        return {"fields": [], "level": level}

    try:
        template = parse_template(str(best_file))
    except Exception:
        return {"fields": [], "level": level}

    # Enrich valid_values for known field patterns with live Egeria data
    zone_values: list[str] = []
    tech_type_values: list[str] = []
    for a in template["attributes"]:
        name_low = a["name"].lower()
        if not a.get("valid_values") and "zone" in name_low:
            if not zone_values:
                try:
                    from advisor.egeria_context import EgeriaContext
                    zone_values = EgeriaContext(egeria_credentials=egeria_credentials).list_governance_zones()
                except Exception:
                    pass
            if zone_values:
                a["valid_values"] = zone_values
        elif not a.get("valid_values") and "deployed implementation type" in name_low:
            if not tech_type_values:
                try:
                    from advisor.egeria_context import EgeriaContext
                    tech_type_values = EgeriaContext(egeria_credentials=egeria_credentials).list_technology_types()
                except Exception:
                    pass
            if tech_type_values:
                a["valid_values"] = tech_type_values

    return {
        "level": level,
        "fields": [
            {
                "name":               a["name"],
                "required":           a["required"],
                "type":               a["type"],
                "description":        a.get("description", ""),
                "valid_values":       a.get("valid_values", []),
                "default_value":      a.get("default_value", ""),
                "alternative_labels": a.get("alternative_labels", []),
            }
            for a in template["attributes"]
        ],
    }
