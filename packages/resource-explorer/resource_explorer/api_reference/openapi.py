"""Parse an OpenAPI 3.x or Swagger 2.0 document into the kind-agnostic `Interface` model.

One parser serves two sources: a spec file committed in the repository and a document fetched from a running
instance. The source is a label the caller passes; nothing here fetches, and nothing here trusts the text
before `openapi_rejection` has looked at it (a console that answers every path with HTML must never be read
as a spec).
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

from resource_explorer.api_reference.model import Interface, Operation

_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
MAX_OPERATIONS = 3000
MAX_SCHEMA_BYTES = 600_000


def load_document(text: str, hint: str = "") -> dict:
    """JSON or YAML text -> the parsed value. Raises ValueError (a sentence) when it is neither; HTML is
    neither. `hint` (a file name or content type) only breaks the tie for text that starts like both."""
    body = (text or "").strip()
    if not body:
        raise ValueError("the body is empty")
    value = None
    if body[0] in "{[":
        try:
            value = json.loads(body)
        except ValueError:
            value = None
    if value is None:
        if body[0] == "<":
            raise ValueError("the body is markup, not JSON or YAML")
        try:
            import yaml
            value = yaml.safe_load(body)
        except Exception as exc:  # yaml.YAMLError and friends
            raise ValueError(f"the body is not JSON or YAML ({type(exc).__name__})") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError("the body is not a JSON or YAML mapping")
    return value


def openapi_rejection(doc) -> str | None:
    """None when `doc` is an OpenAPI 3.x / Swagger 2.0 document; otherwise the sentence saying what it is not."""
    if not isinstance(doc, dict):
        return "not an OpenAPI document: the top level is not an object"
    if "openapi" in doc:
        v = str(doc.get("openapi"))
        if not v.startswith("3."):
            return f"not an OpenAPI document: openapi {v} is not a version this reader knows (3.x)"
    elif "swagger" in doc:
        v = str(doc.get("swagger"))
        if v != "2.0":
            return f"not an OpenAPI document: swagger {v} is not a version this reader knows (2.0)"
    else:
        return "not an OpenAPI document: no 'openapi' or 'swagger' key"
    if not isinstance(doc.get("paths"), dict):
        return "not an OpenAPI document: no 'paths' object"
    return None


def _ref_name(ref: str) -> str:
    return str(ref).rsplit("/", 1)[-1]


def _resolve(doc: dict, node):
    """Follow a local `$ref` (a few hops); anything else comes back unchanged."""
    hops = 0
    while isinstance(node, dict) and "$ref" in node and hops < 5:
        ref = str(node["$ref"])
        if not ref.startswith("#/"):
            return node
        cur = doc
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(cur, dict) or part not in cur:
                return node
            cur = cur[part]
        node = cur
        hops += 1
    return node


def schema_name(schema) -> str:
    """The name a reader would say for a schema: a component's name, `X[]` for an array of one, the bare type
    for an inline one, and '' for none or for `{}` (anything)."""
    if not isinstance(schema, dict) or not schema:
        return ""
    if "$ref" in schema:
        return _ref_name(schema["$ref"])
    t = schema.get("type")
    if t == "array":
        inner = schema_name(schema.get("items"))
        return f"{inner or 'array'}[]" if inner else "array"
    for combo in ("anyOf", "oneOf", "allOf"):
        parts = schema.get(combo)
        if isinstance(parts, list) and parts:
            real = [p for p in parts if not (isinstance(p, dict) and p.get("type") == "null")]
            if len(real) == 1:
                return schema_name(real[0]) or combo
            return combo
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "")
    return str(t or "")


def _type_text(p: dict) -> str:
    sch = p.get("schema") if isinstance(p.get("schema"), dict) else p
    name = schema_name(sch)
    fmt = sch.get("format") if isinstance(sch, dict) else None
    return f"{name} ({fmt})" if name and fmt else name


def _param(p: dict) -> dict:
    return {"name": str(p.get("name", "")), "in": str(p.get("in", "")),
            "required": bool(p.get("required")) or p.get("in") == "path",
            "type": _type_text(p), "description": str(p.get("description") or "")}


def _scheme_text(s) -> str:
    if not isinstance(s, dict):
        return ""
    t = str(s.get("type", ""))
    if t == "http":
        return f"http {s.get('scheme', '')}".strip()
    if t == "apiKey":
        return f"apiKey in {s.get('in', '')}".strip()
    return t


def _security_names(req) -> list:
    out = []
    for r in req or []:
        if isinstance(r, dict):
            for k in r:
                if k not in out:
                    out.append(str(k))
    return out


def _status_key(status: str):
    return (1, 0) if status == "default" else (0, int(status)) if status.isdigit() else (2, 0)


def _responses(doc: dict, op: dict, v3: bool, produces: list) -> list:
    out = []
    for status, r in (op.get("responses") or {}).items():
        r = _resolve(doc, r)
        if not isinstance(r, dict):
            continue
        if v3:
            content = r.get("content") or {}
            cts = list(content)
            sch = next((c.get("schema") for c in content.values() if isinstance(c, dict) and c.get("schema")), None)
        else:
            cts = list(produces) if r.get("schema") else []
            sch = r.get("schema")
        out.append({"status": str(status), "description": str(r.get("description") or ""),
                    "content_types": cts, "schema_name": schema_name(sch)})
    return sorted(out, key=lambda x: _status_key(x["status"]))


def _request_body_v3(doc: dict, op: dict):
    rb = _resolve(doc, op.get("requestBody"))
    if not isinstance(rb, dict):
        return None
    content = rb.get("content") or {}
    sch = next((c.get("schema") for c in content.values() if isinstance(c, dict) and c.get("schema")), None)
    return {"required": bool(rb.get("required")), "content_types": list(content), "schema_name": schema_name(sch)}


def _base_paths(doc: dict, v3: bool) -> list:
    out = []
    if v3:
        for s in doc.get("servers") or []:
            path = urlparse(str((s or {}).get("url", ""))).path.rstrip("/")
            if path and path not in out:
                out.append(path)
    else:
        bp = str(doc.get("basePath") or "").rstrip("/")
        if bp:
            out.append(bp)
    return out


def parse_openapi(doc: dict, *, source: str, origin: str = "", as_of: str = "",
                  max_operations: int = MAX_OPERATIONS, max_schema_bytes: int = MAX_SCHEMA_BYTES) -> Interface:
    """The interface a spec describes. Raises ValueError with the rejection sentence when it is not a spec."""
    reason = openapi_rejection(doc)
    if reason:
        raise ValueError(reason)
    v3 = "openapi" in doc
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    spec_version = f"openapi {doc['openapi']}" if v3 else f"swagger {doc['swagger']}"
    default_security = doc.get("security")
    doc_consumes = list(doc.get("consumes") or [])
    doc_produces = list(doc.get("produces") or [])
    ops: list[Operation] = []
    total = 0
    for path, item in doc["paths"].items():
        item = _resolve(doc, item)
        if not isinstance(item, dict):
            continue
        shared = [_resolve(doc, p) for p in item.get("parameters") or []]
        for method in item:
            if str(method).lower() not in _METHODS or not isinstance(item[method], dict):
                continue
            total += 1
            if len(ops) >= max_operations:
                continue
            op = item[method]
            meth = str(method).upper()
            merged: dict = {}
            for p in shared + [_resolve(doc, p) for p in op.get("parameters") or []]:
                if isinstance(p, dict) and p.get("name"):
                    merged[(p.get("name"), p.get("in"))] = p
            body = None
            if v3:
                body = _request_body_v3(doc, op)
            else:
                bp = next((p for p in merged.values() if p.get("in") == "body"), None)
                if bp:
                    body = {"required": bool(bp.get("required")), "schema_name": schema_name(bp.get("schema")),
                            "content_types": list(op.get("consumes") or doc_consumes)}
            params = [_param(p) for p in merged.values() if p.get("in") != "body"]
            sec = op["security"] if "security" in op else default_security
            ops.append(Operation(
                key=f"{meth} {path}", name=f"{meth} {path}", kind="http_api", method=meth, path=str(path),
                summary=str(op.get("summary") or ""), description=str(op.get("description") or ""),
                operation_id=str(op.get("operationId") or ""),
                tags=[str(t) for t in op.get("tags") or []], parameters=params, request_body=body,
                responses=_responses(doc, op, v3, list(op.get("produces") or doc_produces)),
                security=_security_names(sec), deprecated=bool(op.get("deprecated"))))
    raw_schemas = ((doc.get("components") or {}).get("schemas") if v3 else doc.get("definitions")) or {}
    schemas: dict = {}
    used = 0
    notes: list = []
    for name, sch in raw_schemas.items():
        size = len(json.dumps(sch, default=str))
        if used + size > max_schema_bytes:
            notes.append(f"schemas cut at {len(schemas)} of {len(raw_schemas)} (size cap); the names are still shown")
            break
        schemas[str(name)] = sch
        used += size
    if total > len(ops):
        notes.append(f"showing {len(ops)} of {total} operations (cap)")
    raw_sec = ((doc.get("components") or {}).get("securitySchemes") if v3 else doc.get("securityDefinitions")) or {}
    groups = {}
    for t in doc.get("tags") or []:
        if isinstance(t, dict) and t.get("name"):
            groups[str(t["name"])] = str(t.get("description") or "")
    return Interface(
        kind="http_api", source=source, origin=origin, as_of=as_of, title=str(info.get("title") or ""),
        version=str(info.get("version") or ""), spec_version=spec_version,
        description=str(info.get("description") or "")[:2000], base_paths=_base_paths(doc, v3),
        operations=ops, total_operations=total, schemas=schemas,
        security_schemes={str(k): _scheme_text(v) for k, v in raw_sec.items()}, groups=groups, notes=notes)
