"""Nothing under `resource_explorer/` opens the registry with `sqlite3.connect`.

Eight chat tools did (`sqlite3.connect(registry.db_path)`). On a Postgres registry `db_path` is an
empty SQLite file, so each returned "no such table" and the model reported it as missing data
("I don't have the commit count") while the store held the commits. Everything reads through
`ProjectRegistry._conn()`, which is the one door that honours `REGISTRY_DATABASE_URL`.

The AST is walked, not text-grepped, so a docstring naming `sqlite3.connect` is not a hit.
"""
from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "resource_explorer"

#: Files that may open a SQLite file, and why. None of them opens the registry.
ALLOWLIST = {
    # The metrics database (observability.metrics_db), a separate SQLite file by design.
    "vector_store_pg.py",
    # A deliberate read-only, authorizer-guarded SQLite connection for user-supplied survey SQL.
    "surveyors/survey_step_host.py",
}


def _calls_sqlite_connect(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "sqlite3"
        ):
            lines.append(node.lineno)
    return lines


def test_no_module_opens_the_registry_with_sqlite3_connect():
    offenders = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        if rel in ALLOWLIST:
            continue
        for line in _calls_sqlite_connect(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{rel}:{line}")
    assert offenders == [], (
        f"{offenders} call sqlite3.connect. Read the registry through ProjectRegistry()._conn(); "
        "on a Postgres registry a SQLite connection reads an empty file."
    )


def test_the_check_sees_a_call_and_ignores_a_docstring():
    assert _calls_sqlite_connect(ast.parse("import sqlite3\nsqlite3.connect('x')\n")) == [2]
    assert _calls_sqlite_connect(ast.parse('"""sqlite3.connect(x)"""\n')) == []
