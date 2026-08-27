"""CHAOSS metrics — chiefly that they are computed over disjoint data.

The bug this file exists to prevent is not hypothetical. The first version read
project_contributor_stats, whose "periods" are nested trailing windows (30d,
90d, 365d, all ending today). It therefore counted every recent commit once per
window, and compared the 30-day window against the 90-day window that contains
it: first-time contributors came out as zero for every repository in the
catalogue, and kafka, sqlglot, milvus and openmetadata were all labelled
"shrinking" for purely arithmetic reasons. It ran cleanly and said nothing true.
"""
from resource_explorer.surveyors.sub_surveyors import chaoss_metrics as C


def _commits(spec: dict) -> list:
    """{author: [day, ...]} -> one row per commit."""
    return [{"author_email": who, "author_name": who, "committed_at": f"{day}T12:00:00"}
            for who, days in spec.items() for day in days]


def test_elephant_factor_finds_the_smallest_half_holding_group():
    assert C.elephant_factor({"a": 98, "b": 1, "c": 1}) == 1
    assert C.elephant_factor({"a": 1, "b": 1, "c": 1, "d": 1}) == 2
    assert C.elephant_factor({f"u{i}": 1 for i in range(30)}) == 15


def test_no_commits_is_none_not_zero():
    """0 would read as "nobody holds any of it"; None means we counted nothing."""
    assert C.elephant_factor({}) is None
    assert C.elephant_factor({"a": 0}) is None


def test_each_commit_is_counted_once():
    """The nested-window bug in one assertion: an author with three commits
    contributes three, not three per overlapping window they appear in."""
    rows = _commits({"a": ["2026-01-01", "2026-01-02", "2026-02-01"],
                     "b": ["2026-01-03"]})
    ef = next(m for m in C.assess(rows, {}) if m["check_name"] == "elephant_factor")
    assert ef["detail"]["commits"] == 4
    assert ef["detail"]["authors"] == 2
    assert ef["detail"]["value"] == 1


def test_turnover_halves_are_disjoint_so_a_stable_project_reads_steady():
    """Everyone present throughout must not read as loss. Under the nested-window
    version this exact shape produced "shrinking"."""
    rows = _commits({who: ["2026-01-01", "2026-03-01"] for who in "abcdef"})
    t = next(m for m in C.assess(rows, {}) if m["check_name"] == "contributor_turnover")
    assert t["label"] == "steady"
    assert t["detail"]["lost"] == 0 and t["detail"]["new"] == 0
    assert t["detail"]["retained"] == 6


def test_turnover_detects_real_arrival_and_departure():
    rows = _commits({"old1": ["2026-01-01"], "old2": ["2026-01-02"],
                     "both": ["2026-01-03", "2026-03-02"],
                     "new1": ["2026-03-03"], "new2": ["2026-03-04"],
                     "new3": ["2026-03-05"]})
    t = next(m for m in C.assess(rows, {}) if m["check_name"] == "contributor_turnover")
    assert t["label"] == "growing"
    assert t["detail"]["new"] == 3 and t["detail"]["lost"] == 2


def test_a_single_day_of_commits_is_no_basis_for_a_comparison():
    rows = _commits({"a": ["2026-01-01"], "b": ["2026-01-01"]})
    t = next(m for m in C.assess(rows, {}) if m["check_name"] == "contributor_turnover")
    assert t["label"] == "not_established"
    assert t["detail"]["known"] is False


def test_organizational_diversity_is_withheld_when_authorship_is_personal():
    """72% of the catalogue's author emails are noreply/gmail addresses. Reading
    diversity off the remainder would describe a minority of the work as if it
    were the whole."""
    rows = _commits({"a@users.noreply.github.com": ["2026-01-01"] * 8,
                     "b@gmail.com": ["2026-01-02"] * 8,
                     "c@corp.com": ["2026-01-03"]})
    d = next(m for m in C.assess(rows, {})
             if m["check_name"] == "organizational_diversity")
    assert d["label"] == "not_established"
    assert d["detail"]["attributable_share"] < C._MIN_ATTRIBUTABLE


def test_organizational_diversity_is_reported_when_it_can_be():
    rows = _commits({"a@corp.com": ["2026-01-01"] * 5,
                     "b@other.org": ["2026-01-02"] * 5,
                     "c@gmail.com": ["2026-01-03"]})
    d = next(m for m in C.assess(rows, {})
             if m["check_name"] == "organizational_diversity")
    assert d["label"] == "diverse" or d["detail"]["value"] == 2
    assert d["detail"]["known"] is True


def test_time_to_first_response_is_named_even_though_it_is_unmeasured():
    """One of CHAOSS's most cited metrics. Omitting it silently would let a
    reader assume it was considered and found unremarkable."""
    m = next(x for x in C.assess([], {}) if x["check_name"] == "time_to_first_response")
    assert m["label"] == "not_established" and m["confidence"] == 0


def test_headline_names_concentration_and_never_averages():
    rows = _commits({"a": ["2026-01-01"] * 50, "b": ["2026-02-01"]})
    metrics = C.assess(rows, {"releases_count": 9, "avg_release_interval_days": 20})
    assert C.headline(metrics).startswith("elephant factor 1 (sole)")


def test_no_commits_at_all_reports_absence_not_an_even_spread():
    ef = next(m for m in C.assess([], {}) if m["check_name"] == "elephant_factor")
    assert ef["label"] == "not_established"
    assert "not a finding that it is evenly spread" in ef["summary"]
