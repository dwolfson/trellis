"""The log viewer, and the three empties it must not conflate.

An empty log list has at least three causes — nothing logged, the buffer emptied
by a restart, a filter that excluded everything — and rendering them alike is the
absence-as-answer failure this codebase keeps finding (see `null_pct: 0.0`, and
`cii_badge`'s unreachable-vs-not-registered). The buffer being in-memory makes
the second cause routine rather than theoretical, so it is asserted here.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resource_explorer.observability import logging_setup as ls
from resource_explorer.web.app import app

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"


@pytest.fixture
def client():
    ls.configure_logging(force=True)
    ls.ring_handler.clear()
    return TestClient(app)


def test_records_reach_the_route(client):
    logging.getLogger("resource_explorer.viewer_test").warning("visible in the viewer")
    body = client.get("/api/logs/").json()
    msgs = [r["message"] for r in body["records"]]
    assert "visible in the viewer" in msgs, msgs[:5]


def test_the_response_says_enough_to_read_an_empty_list_correctly(client):
    """Records alone cannot distinguish the three empties. The metadata can."""
    body = client.get("/api/logs/").json()
    assert body["records"] == []
    buf = body["buffer"]
    assert buf["held"] == 0
    assert buf["durable"] is False, (
        "a viewer that does not know the buffer is volatile will report "
        "'no logs' after every restart as though it were a finding"
    )
    assert buf["capacity"] == ls.RING_CAPACITY
    assert body["filtered"] is False


def test_filtered_empty_is_distinguishable_from_genuinely_empty(client):
    logging.getLogger("resource_explorer.viewer_test").info("something happened")

    filtered = client.get("/api/logs/?level=CRITICAL").json()
    assert filtered["records"] == []
    assert filtered["filtered"] is True
    assert filtered["buffer"]["held"] > 0, (
        "held must report the whole buffer, not the filtered view — otherwise "
        "a filter that matches nothing looks like an empty buffer"
    )


def test_levels_are_not_derived_from_what_happens_to_be_buffered(client):
    """Offering only the levels present would hide ERROR from the filter exactly
    when no error has occurred — which is when someone goes looking for it."""
    body = client.get("/api/logs/").json()
    assert body["levels"] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_an_unknown_level_is_rejected_rather_than_silently_matching_nothing(client):
    res = client.get("/api/logs/?level=WARN")  # a plausible typo for WARNING
    assert res.status_code == 400, (
        "an unrecognised level returned 200 with an empty list, which reads as "
        "'no warnings' rather than 'that is not a level'"
    )


def test_limit_cannot_exceed_the_buffer(client):
    for i in range(20):
        logging.getLogger("resource_explorer.viewer_test").info("line %d", i)
    body = client.get(f"/api/logs/?limit={ls.RING_CAPACITY * 10}").json()
    assert len(body["records"]) <= ls.RING_CAPACITY


def test_newest_first(client):
    log = logging.getLogger("resource_explorer.viewer_test")
    log.info("older")
    log.info("newer")
    msgs = [r["message"] for r in client.get("/api/logs/").json()["records"]]
    assert msgs.index("newer") < msgs.index("older")


def test_the_pane_is_wired_and_states_the_buffer_is_volatile():
    html = INDEX.read_text()
    assert 'id="admin-logs-view"' in html, "no pane element"
    assert "adminLogsView" in html, "pane not in showMainView's hide-list"
    assert "tab === 'admin-logs'" in html, "no route in showMainView"
    assert "function loadAdminLogsPanel" in html, "no loader"

    groups = html[html.index("const _ADMIN_GROUPS"):html.index("function _adminSubnavHtml")]
    assert "admin-logs" in groups, "pane exists but no subnav button reaches it"

    panel = html[html.index("async function loadAdminLogsPanel"):]
    panel = panel[:panel.index("function _adminLogsSetLevel")]
    assert "restart" in panel, (
        "the empty state does not mention that the buffer starts empty on "
        "restart, so 'no logs' reads as a statement about the system"
    )
