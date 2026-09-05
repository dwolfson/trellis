"""fastapi-route.yml's constraint (added 2026-09-03) — `@$APP.patch(...)`
must not match `@mock.patch(...)`/`@mocker.patch(...)`, the unittest.mock/
pytest-mock decorator idiom. Found live against sqlglot's test suite (no
FastAPI dependency at all): `tests`/`tests/dialects` were wrongly typed
"Software Service" at 70% confidence purely from `@mock.patch(...)`
decorators. Runs the real ast-grep binary against the real rule file —
this is exactly the kind of collision unit-testing the Python detector
logic alone would never catch, since the bug lives entirely in the YAML
pattern.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.arch_recovery import code_markers

pytestmark = pytest.mark.skipif(
    code_markers._binary() is None, reason="ast-grep not installed",
)


def _hits(tmp_path, source: str) -> list[dict]:
    (tmp_path / "probe.py").write_text(source)
    results = code_markers.scan(str(tmp_path))
    return results.get("fastapi-route-registration", [])


class TestFastapiRoutePatchDoesNotMatchMockPatch:
    def test_mock_patch_decorator_is_not_a_route(self, tmp_path):
        hits = _hits(tmp_path, '''
import unittest.mock as mock

@mock.patch("some.module.logger")
def test_something():
    pass
''')
        assert hits == []

    def test_mocker_patch_decorator_is_not_a_route(self, tmp_path):
        """pytest-mock's fixture-based idiom — same collision, different
        common name for the object."""
        hits = _hits(tmp_path, '''
def test_something(mocker):
    mocker.patch("some.module.logger")

@mocker.patch("some.module.logger")
def test_something_else():
    pass
''')
        assert hits == []

    def test_a_real_fastapi_patch_route_still_matches(self, tmp_path):
        """The fix must not throw out the real signal along with the false
        positive — a genuine FastAPI PATCH route on an object not named
        mock/mocker still counts."""
        hits = _hits(tmp_path, '''
from fastapi import FastAPI
app = FastAPI()

@app.patch("/items/{item_id}")
def update_item(item_id: int):
    return {}
''')
        assert len(hits) == 1

    def test_a_real_fastapi_get_route_is_unaffected(self, tmp_path):
        """The constraint is scoped to .patch() only — verb siblings never
        collided with mock/mocker and must keep matching unconstrained."""
        hits = _hits(tmp_path, '''
from fastapi import FastAPI
app = FastAPI()

@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {}
''')
        assert len(hits) == 1
