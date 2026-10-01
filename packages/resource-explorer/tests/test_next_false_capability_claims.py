"""On-screen capability claims in /next must not promise controls /next lacks
(CLASSIC-VS-NEXT-PARITY-2026-09-30.md C-02..C-04 and R-42). Source-level pins
(CI has no Node), same style as test_curate_honest_non_repo_degrade.py."""
from __future__ import annotations

import re
from pathlib import Path

NEXT = (Path(__file__).resolve().parents[1] / "resource_explorer" / "web"
        / "static" / "next")
CURATE = (NEXT / "stages" / "curate.js").read_text()
APP = (NEXT / "app.js").read_text()


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_curate_does_not_claim_header_has_tags_feedback_notes():
    assert "reachable from the resource header" not in _flat(CURATE)
    assert "regardless of type" not in _flat(CURATE)
    assert "offers none of them" in _flat(CURATE)


def test_publish_stale_does_not_point_at_a_missing_publish_control():
    assert "publish again from the Analysis pane" not in _flat(APP)
    assert "has no publish control" in _flat(APP)


def test_known_negative_the_header_really_has_no_tag_note_feedback_control():
    # If /next ever grows these controls, the honest wording must be revisited.
    for f in NEXT.rglob("*.js"):
        if "admin" in f.parts:
            continue  # admin/feedback.js is a cross-resource list, not the header
        t = f.read_text()
        assert "/api/curate/tags" not in t, f
        assert "/api/curate/notes" not in t, f
        assert "/api/curate/feedback/" not in t, f
