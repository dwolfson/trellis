"""One rule for "is this file a test", shared by anything that must not read a
test's mock registrations as the product's own surface.

Why it exists: dataops_testgen held 2,438 route markers and only 54 were real
routes; 2,373 sat under ``tests/`` and were mostly ``patch("...")`` calls read
as FastAPI ``@app.patch`` registrations. Route and message markers are facts
about what the product EXPOSES, so a test file contributes none.

Directory segments and file-name shapes only; no content is read. (The Spring
detector's ``_TEST_PATH_SEGMENTS`` and admission's ``FIXTURE_DIRS`` answer
narrower questions about compose files and resources and are left as they are.)
"""
from __future__ import annotations

import re

TEST_DIR_SEGMENTS = frozenset({"test", "tests", "__tests__", "__test__", "testdata"})

_TEST_FILE_RES = (
    re.compile(r"^test_.+\.py$"),
    re.compile(r"^.+_tests?\.(py|go)$"),
    re.compile(r"^conftest\.py$"),
    re.compile(r"^.+\.(test|spec)\.[cm]?[jt]sx?$"),
    re.compile(r"^.+(Test|Tests|IT|TestCase)\.(java|kt|scala)$"),
    re.compile(r"^Test.+\.java$"),
)


def is_test_path(rel: str) -> bool:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return False
    if any(seg.lower() in TEST_DIR_SEGMENTS for seg in parts[:-1]):
        return True
    return any(r.match(parts[-1]) for r in _TEST_FILE_RES)
