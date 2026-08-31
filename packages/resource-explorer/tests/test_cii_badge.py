"""The OpenSSF Best Practices (CII) badge.

Two failure modes carry the weight here, and both were found live rather than
imagined:

1. A network failure rendering as "this project has no badge" — a claim about
   someone's project derived from our own connectivity.
2. A URL-form mismatch doing the same thing quietly. Measured 2026-08-26:
   `https://github.com/odpi/egeria` returns a silver badge, and
   `https://github.com/odpi/egeria.git` — the form actually stored in the
   registry for that project — returns nothing at all.
"""
from unittest.mock import patch

from resource_explorer.surveyors.sub_surveyors import cii_badge as B


def test_url_variants_strip_the_git_suffix_that_hides_a_real_badge():
    assert B.url_variants("https://github.com/odpi/egeria.git")[0] == \
        "https://github.com/odpi/egeria"
    assert B.url_variants("https://github.com/odpi/egeria/")[0] == \
        "https://github.com/odpi/egeria"
    # A URL needing no change is asked once, not twice.
    assert B.url_variants("https://github.com/a/b") == ["https://github.com/a/b"]
    assert B.url_variants("") == []


def test_ssh_remotes_are_translated_not_asked_and_missed():
    """An SSH remote names the same project; sending it verbatim invents a false negative.

    Before 2026-08-31 `git@github.com:odpi/egeria.git` went to the API as-is,
    matched nothing, and — because "matched nothing" and "not registered" are
    the same `(None, "")` — was reported as `not_registered` for a project
    holding a silver badge. The URL form alone produced a confident, wrong
    claim about someone else's project.
    """
    for ssh in ("git@github.com:odpi/egeria.git",
                "git@github.com:odpi/egeria",
                "ssh://git@github.com/odpi/egeria.git"):
        assert B.url_variants(ssh)[0] == "https://github.com/odpi/egeria", ssh

    # And nothing un-askable survives into the query list.
    for v in B.url_variants("git@github.com:odpi/egeria.git"):
        assert v.startswith("https://"), v


def test_an_unusable_url_is_reported_as_our_failure_not_the_project_s(monkeypatch):
    """`assess` must never turn "we could not ask" into "they have no badge"."""
    called = []
    monkeypatch.setattr(B, "_query_one", lambda *a, **k: called.append(a) or (None, ""))

    record, error = B.fetch_badge("not-a-url-at-all")
    assert record is None
    assert error, "an un-askable URL must produce an error, not a silent miss"
    assert not called, "nothing should have been sent to the API"

    findings = B.assess(record, error)
    level = next(f for f in findings if f["check_name"] == "badge_level")
    assert level["detail"]["known"] is False
    assert level["label"] != "not_registered"
    assert "could not be looked up" in B.headline(findings)



def test_fetch_stops_at_the_first_variant_that_hits():
    calls = []

    def fake(url, timeout):
        calls.append(url)
        return ({"badge_level": "silver"}, "") if url.endswith("egeria") else (None, "")

    with patch.object(B, "_query_one", fake):
        record, error = B.fetch_badge("https://github.com/odpi/egeria.git")
    assert record["badge_level"] == "silver" and error == ""
    assert calls == ["https://github.com/odpi/egeria"]


def test_a_transient_error_on_one_variant_does_not_mask_a_real_answer():
    def fake(url, timeout):
        return ((None, "TimeoutError: x") if url.endswith(".git")
                else ({"badge_level": "passing"}, ""))

    with patch.object(B, "_query_one", fake):
        record, error = B.fetch_badge("https://github.com/a/b.git")
    assert record["badge_level"] == "passing" and error == ""


def test_an_unreachable_lookup_is_never_reported_as_no_badge():
    """The single most likely way this module could lie."""
    findings = B.assess(None, "TimeoutError: timed out")
    level = findings[0]
    assert level["label"] == "not_established"
    assert level["detail"]["known"] is False
    assert "not a finding that the project has no badge" in level["summary"]
    assert B.headline(findings) == "OpenSSF Best Practices badge could not be looked up"


def test_not_registered_is_an_answer_about_the_project_not_a_gap():
    findings = B.assess(None, "")
    assert findings[0]["label"] == "not_registered"
    assert findings[0]["detail"]["known"] is True
    assert B.headline(findings) == "No OpenSSF Best Practices badge"


def test_a_stale_self_assessment_gets_its_own_finding():
    """odpi/egeria really does hold a silver badge last updated in 2022. The
    level alone would carry the badge's authority and none of its age."""
    record = {"badge_level": "silver", "tiered_percentage": 296, "id": 3044,
              "updated_at": "2022-12-20T12:06:18.601Z",
              "homepage_url_status": "Met", "sites_https_status": "?"}
    findings = B.assess(record, "")
    fresh = next(f for f in findings if f["check_name"] == "badge_freshness")
    assert fresh["label"] == "stale"
    assert fresh["detail"]["age_days"] > B._STALE_DAYS
    assert "self-assessment is stale" in B.headline(findings)


def test_a_recent_badge_is_not_flagged_stale():
    from datetime import datetime, timedelta, timezone
    recent = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    findings = B.assess({"badge_level": "gold", "updated_at": recent}, "")
    fresh = next(f for f in findings if f["check_name"] == "badge_freshness")
    assert fresh["label"] == "current"
    assert B.headline(findings) == "OpenSSF Best Practices badge: gold"


def test_unanswered_criteria_are_neither_met_nor_unmet():
    """Of egeria's 196 criteria fields, 66 are '?'. Folding them into either
    side would misstate the maintainers' own record."""
    record = {"badge_level": "passing", "updated_at": "2026-08-01T00:00:00Z",
              "a_status": "Met", "b_status": "Unmet", "c_status": "?",
              "d_status": "N/A", "e_status": ""}
    crit = next(f for f in B.assess(record, "")
                if f["check_name"] == "criteria_coverage")
    assert crit["detail"] == {**crit["detail"], "met": 1, "unmet": 1,
                              "unanswered": 2, "not_applicable": 1}
    assert crit["detail"]["unmet_criteria"] == ["b"]
    assert crit["label"] == "partial"


def test_a_missing_update_date_is_unknown_rather_than_assumed_current():
    findings = B.assess({"badge_level": "passing"}, "")
    fresh = next(f for f in findings if f["check_name"] == "badge_freshness")
    assert fresh["label"] == "not_established"


def test_a_missing_level_defaults_to_in_progress_not_to_a_badge():
    findings = B.assess({"id": 1, "updated_at": "2026-08-01T00:00:00Z"}, "")
    assert findings[0]["label"] == "in_progress"
