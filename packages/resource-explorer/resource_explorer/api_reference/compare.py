"""Compare two interfaces of the same kind: what each lists that the other does not.

Matching is by (method, normalised path): `{id}`, `<int:id>` and `:id` are the same segment. An operation that
matches nothing exactly but matches exactly one operation on the other side once a path PREFIX is ignored
(code registers `/jobs`, the running spec says `/api/v1/jobs`) is a *probable* match, listed with the prefix,
not counted as two absences. Everything left is listed. The comparison says the counts and the differences and
does NOT name a cause: a route can be missing from a running spec for several reasons, and which one applies is
for a person to say.
"""
from __future__ import annotations

import re

from resource_explorer.api_reference.model import SOURCE_WORDS, Interface, Operation

_BRACE = re.compile(r"\{[^}/]*\}")
_ANGLE = re.compile(r"<[^>/]*>")
_COLON = re.compile(r"(?<=/):[A-Za-z_][A-Za-z0-9_]*")


def normalize_path(path: str) -> str:
    p = (path or "").strip()
    p = _BRACE.sub("{}", p)
    p = _ANGLE.sub("{}", p)
    p = _COLON.sub("{}", p)
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1:
        p = p.rstrip("/") or "/"
    return p


def path_params(path: str) -> list:
    """Parameter names written into a path template, in order."""
    out = []
    for m in re.finditer(r"\{([^}/]+)\}|<(?:[^>:/]+:)?([^>/]+)>|(?<=/):([A-Za-z_][A-Za-z0-9_]*)", path or ""):
        name = next(g for g in m.groups() if g)
        if name not in out:
            out.append(name)
    return out


def _ident(op: Operation) -> tuple:
    return (op.method.upper(), normalize_path(op.path))


def _brief(op: Operation) -> dict:
    return {"key": op.key, "name": op.name, "summary": op.summary, "group": op.group, "location": op.location}


def _prefix_of(longer: str, shorter: str) -> str | None:
    if shorter == "/" or longer == shorter or not longer.endswith(shorter):
        return None
    prefix = longer[: len(longer) - len(shorter)]
    return prefix if prefix.startswith("/") and not prefix.endswith("/") or prefix == "" else None


def compare_interfaces(a: Interface, b: Interface) -> dict:
    a_by: dict = {}
    b_by: dict = {}
    for op in a.operations:
        a_by.setdefault(_ident(op), []).append(op)
    for op in b.operations:
        b_by.setdefault(_ident(op), []).append(op)
    both = sum(min(len(a_by[k]), len(b_by[k])) for k in a_by.keys() & b_by.keys())
    only_a = [op for k, v in a_by.items() for op in (v[len(b_by.get(k, [])):] if k in b_by else v)]
    only_b = [op for k, v in b_by.items() for op in (v[len(a_by.get(k, [])):] if k in a_by else v)]

    # Probable matches: same method, one path is the other plus a prefix, and the pairing is unambiguous.
    probable = []
    cand: dict = {}
    for ao in only_a:
        am, ap = _ident(ao)
        hits = []
        for bo in only_b:
            bm, bp = _ident(bo)
            if bm != am:
                continue
            prefix = _prefix_of(ap, bp) if len(ap) >= len(bp) else _prefix_of(bp, ap)
            if prefix:
                hits.append((bo, prefix))
        cand[id(ao)] = hits
    b_taken: set = set()
    a_taken: set = set()
    for ao in only_a:
        hits = cand[id(ao)]
        if len(hits) != 1:
            continue
        bo, prefix = hits[0]
        rivals = [x for x in only_a if x is not ao and any(h[0] is bo for h in cand[id(x)])]
        if rivals:
            continue
        probable.append({"a": ao.key, "b": bo.key, "prefix": prefix})
        a_taken.add(id(ao))
        b_taken.add(id(bo))
    only_a = [o for o in only_a if id(o) not in a_taken]
    only_b = [o for o in only_b if id(o) not in b_taken]

    def by_file(ops):
        out: dict = {}
        for o in ops:
            if o.location:
                f = o.location.rsplit(":", 1)[0]
                out[f] = out.get(f, 0) + 1
        return out

    na, nb = len(a.operations), len(b.operations)
    parts = [f"{a.source_phrase} lists {na} operation(s); {b.source_phrase} lists {nb} operation(s).",
             f"{both} match exactly" + (f", {len(probable)} more match once a path prefix is ignored" if probable else "")
             + f"; {len(only_a)} only in the first, {len(only_b)} only in the second.",
             "Why they differ is not decided here; the differences are listed below."]
    return {
        "a": {"source": a.source, "word": SOURCE_WORDS.get(a.source, a.source), "count": na, "origin": a.origin},
        "b": {"source": b.source, "word": SOURCE_WORDS.get(b.source, b.source), "count": nb, "origin": b.origin},
        "both": both, "probable": probable,
        "only_a": [_brief(o) for o in only_a], "only_b": [_brief(o) for o in only_b],
        "only_a_by_file": by_file(only_a), "only_b_by_file": by_file(only_b),
        "summary": " ".join(parts),
    }
