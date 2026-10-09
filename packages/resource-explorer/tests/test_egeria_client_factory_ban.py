"""Brief I: every pyegeria client in RE comes from `egeria_clients.egeria_client`.

Walks every module under `resource_explorer/` (the AST, not a text grep, so a docstring that
names a class is not a hit) and fails on:

* a direct construction of any pyegeria client class — the class list is built from pyegeria
  itself (every `BaseServerClient`/`BasePlatformClient` subclass in `pyegeria.omvs`, plus the
  `Egeria*` facades), so a class pyegeria adds later is covered without editing this file;
* a direct token call: `create_egeria_bearer_token(`, `refresh_egeria_bearer_token(`,
  `set_bearer_token(`, or trellis-auth's `apply_token(`;
* a dynamic construction: `getattr(pyegeria, name)(...)`.

The allowlist is the factory module, and nothing else.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "resource_explorer"

ALLOWLIST = {"egeria_clients.py"}

TOKEN_CALLS = {"create_egeria_bearer_token", "refresh_egeria_bearer_token", "set_bearer_token",
               "apply_token"}


def _pyegeria_client_classes() -> set[str]:
    pyegeria = pytest.importorskip("pyegeria")
    from pyegeria.core._base_platform_client import BasePlatformClient
    from pyegeria.core._base_server_client import BaseServerClient

    names: set[str] = set()
    for m in pkgutil.iter_modules(pyegeria.omvs.__path__, "pyegeria.omvs."):
        mod = importlib.import_module(m.name)
        for n, o in inspect.getmembers(mod, inspect.isclass):
            if issubclass(o, (BasePlatformClient, BaseServerClient)):
                names.add(n)
    for n in dir(pyegeria):
        o = getattr(pyegeria, n)
        if inspect.isclass(o) and (issubclass(o, (BasePlatformClient, BaseServerClient))
                                   or n.startswith("Egeria")):
            names.add(n)
    return names


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _class_aliases(tree: ast.AST, classes: set[str]) -> tuple[set[str], set[str]]:
    """Per module: local names bound to a pyegeria client class, and names bound to pyegeria
    modules. Follows `from pyegeria[.x] import C as A`, `import pyegeria as pe`, and plain
    assignments `A = C` / `A = pe.C` / `A = getattr(pyegeria, ...)` (to a fixed point)."""
    names: set[str] = set(classes)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pyegeria"):
            for a in node.names:
                if a.name in classes:
                    names.add(a.asname or a.name)
                elif a.name.islower():               # a pyegeria submodule, e.g. `omvs`
                    modules.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("pyegeria"):
                    modules.add(a.asname or a.name.split(".")[0])
    modules.add("pyegeria")

    def refers(v: ast.AST) -> bool:
        if isinstance(v, ast.Name):
            return v.id in names
        if isinstance(v, ast.Attribute):
            return v.attr in classes
        if isinstance(v, ast.Call) and _call_name(v.func) == "getattr" and v.args:
            return isinstance(v.args[0], ast.Name) and v.args[0].id in modules
        return False

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and refers(node.value):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id not in names:
                        names.add(t.id)
                        changed = True
    return names, modules


def _hits(source: str, classes: set[str]) -> list[str]:
    tree = ast.parse(source)
    names, modules = _class_aliases(tree, classes)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                bname = base.id if isinstance(base, ast.Name) else (
                    base.attr if isinstance(base, ast.Attribute) else "")
                if bname in names or bname in classes:
                    out.append(f"{node.lineno}: class {node.name} subclasses {bname}")
            continue
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if isinstance(node.func, ast.Name) and node.func.id in names:
            out.append(f"{node.lineno}: constructs {node.func.id}")
        elif isinstance(node.func, ast.Attribute) and node.func.attr in classes:
            out.append(f"{node.lineno}: constructs {node.func.attr}")
        elif name in TOKEN_CALLS:
            out.append(f"{node.lineno}: calls {name}")
        elif (isinstance(node.func, ast.Call) and _call_name(node.func.func) == "getattr"
              and node.func.args and _call_name(node.func.args[0]) in modules):
            out.append(f"{node.lineno}: constructs getattr(pyegeria, ...)")
        elif name == "partial" and node.args and (
                (isinstance(node.args[0], ast.Name) and node.args[0].id in names)
                or (isinstance(node.args[0], ast.Attribute) and node.args[0].attr in classes)):
            out.append(f"{node.lineno}: partial over a pyegeria client")
    return out


def _scan(classes: set[str]) -> dict[str, list[str]]:
    found = {}
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        if rel in ALLOWLIST:
            continue
        hits = _hits(path.read_text(encoding="utf-8"), classes)
        if hits:
            found[rel] = hits
    return found


def test_no_pyegeria_client_is_built_outside_the_factory():
    classes = _pyegeria_client_classes()
    assert {"AssetMaker", "MetadataExpert", "EgeriaTech", "SecurityOfficer", "ServerOps"} <= classes
    found = _scan(classes)
    assert not found, "pyegeria clients built or tokens set outside egeria_clients.py:\n" + "\n".join(
        f"  {f}: {h}" for f, hs in found.items() for h in hs)


def test_the_ban_fires_on_each_shape():
    """Make the guard fail on purpose: each banned shape is a hit, a mention in a string is not."""
    classes = _pyegeria_client_classes()
    src = '''
from pyegeria import AssetMaker
import pyegeria
a = AssetMaker("v", "u", "me", "pw")
a.create_egeria_bearer_token()
b = getattr(pyegeria, "MetadataExpert")("v", "u", "me", "pw")
b.set_bearer_token("t")
"AssetMaker(...) in a string is not a construction"
'''
    hits = _hits(src, classes)
    assert len(hits) == 4, hits


@pytest.mark.parametrize("src", [
    "from pyegeria import AssetMaker as AM\nc = AM('v', 'u', 'me', 'pw')\n",
    "import pyegeria as pe\nc = pe.MetadataExpert('v', 'u', 'me', 'pw')\n",
    "from pyegeria import AssetMaker\nK = AssetMaker\nL = K\nc = L('v', 'u', 'me', 'pw')\n",
    "import pyegeria\nK = getattr(pyegeria, 'AssetMaker')\nc = K('v')\n",
    "import functools\nfrom pyegeria import AssetMaker\nmk = functools.partial(AssetMaker, 'v')\n",
    "from functools import partial\nimport pyegeria\nmk = partial(pyegeria.AssetMaker, 'v')\n",
    "from pyegeria import AssetMaker as Base\nclass Mine(Base):\n    pass\n",
    "import pyegeria\nclass Mine(pyegeria.EgeriaTech):\n    pass\n",
])
def test_the_ban_sees_through_aliases_assignments_partials_and_subclasses(src):
    assert _hits(src, _pyegeria_client_classes()), src


def test_the_allowlist_is_only_the_factory():
    assert ALLOWLIST == {"egeria_clients.py"}
    assert (PKG / "egeria_clients.py").exists()
