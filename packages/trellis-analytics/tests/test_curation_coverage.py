import json

from trellis_analytics.envelope import ResultState
from trellis_analytics.readers.ods import OdsReader
from trellis_analytics.routines import curation_coverage


def els(*tables):
    return json.dumps({"tables": list(tables)})


def test_counts_published_not_yet_blocked(make_ods):
    url = make_ods(
        schemas=["sales", "hr", "ops", "fin", "arch", "dev", "blk", "lone"],
        proofs=[
            ("schema", "sales", "elements_read_back", "2026-10-05T10:00:00Z", els("a", "b", "c")),
            ("schema", "hr", "elements_read_back", "2026-10-05T10:01:00Z", els("p", "q")),
            ("database", "", "report_published", "2026-10-05T10:02:00Z", json.dumps({"annotation_count": 76})),
            ("schema", "blk", "leave_out_blocked", "2026-10-05T11:00:00Z", "{}"),
        ],
        events=[("sales", "catalogue", "person"), ("hr", "catalogue", "person"),
                ("ops", "catalogue", "person"), ("fin", "catalogue", "rule-1"),
                ("arch", "leave_out", "person"), ("dev", "leave_out", "rule-2"), ("blk", "leave_out", "person")],
        outbox=["done", "superseded", "superseded"])
    r = curation_coverage(OdsReader(url), "database", "demo")
    assert r.envelope.result_state is ResultState.MEASURED
    assert r.count("published", "schemas") == 2 and r.count("published", "tables") == 5
    assert r.count("published", "report") == 1
    assert r.as_of == "2026-10-05T10:02:00Z"
    ny = {l.key: l for l in r.group("not_yet").lines}
    assert ny["undecided"].names == ["lone"]
    assert ny["chosen"].names == ["ops"]
    assert ny["chosen_confirmed"].names == ["fin"]
    assert ny["left_out"].names == ["arch"]
    assert ny["left_out_confirmed"].names == ["dev"]
    # the blocked schema is counted once, in blocked, not also as left out
    assert r.count("blocked", "blocked") == 1 and r.count("blocked", "superseded") == 2
    # every known schema lands in exactly one group
    assert 2 + sum(l.count for l in ny.values()) + 1 == r.known_schemas == 8
    # every count carries the ids it counts
    assert all(l.rows or l.count == 0 for g in r.groups for l in g.lines)
    assert r.group("published").lines[0].rows["catalogue_commit_proofs"]
    assert "read back 2026-10-05T10:02:00Z" in r.group("published").words


def test_a_later_removal_unpublishes_and_a_reset_forgets(make_ods):
    url = make_ods(
        schemas=["s1", "s2"],
        proofs=[("schema", "s1", "elements_read_back", "2026-10-01T00:00:00Z", els("a")),
                ("schema", "s1", "removed", "2026-10-02T00:00:00Z", "{}"),
                ("schema", "s2", "elements_read_back", "2026-10-01T00:00:00Z", els("b")),
                ("database", "", "egeria_reset", "2026-10-03T00:00:00Z", "{}")],
        events=[("s1", "catalogue", "person")])
    r = curation_coverage(OdsReader(url), "database", "demo")
    # s2's proof predates the reset, so it is not published; s1 was removed
    assert r.count("published", "schemas") == 0
    assert r.count("not_yet", "chosen") == 1 and r.count("not_yet", "undecided") == 1


def test_nothing_found_is_not_not_established(make_ods):
    empty = curation_coverage(OdsReader(make_ods(schemas=["a", "b"])), "database", "demo")
    assert empty.envelope.result_state is ResultState.NOTHING_FOUND
    assert "nothing published yet · 2 known to RE" == empty.summary

    broken = curation_coverage(OdsReader("sqlite:////nonexistent/dir/x.sqlite"), "database", "demo")
    assert broken.envelope.result_state is ResultState.NOT_ESTABLISHED
    assert broken.envelope.result_state_reason and broken.groups == []
    assert empty.envelope.result_state != broken.envelope.result_state


def test_missing_table_is_not_established_not_nothing(tmp_path):
    import sqlite3
    p = tmp_path / "bare.sqlite"
    sqlite3.connect(p).close()
    r = curation_coverage(OdsReader(f"sqlite:///{p}"), "database", "demo")
    assert r.envelope.result_state is ResultState.NOT_ESTABLISHED


def test_other_kinds_are_not_applicable(make_ods):
    r = curation_coverage(OdsReader(make_ods()), "repository", "demo")
    assert r.envelope.result_state is ResultState.NOT_APPLICABLE and r.envelope.result_state_reason


def test_slug_with_hyphens_is_normalised(make_ods):
    url = make_ods(slug="coco_pharma", schemas=["x"])
    assert curation_coverage(OdsReader(url), "database", "coco-pharma").known_schemas == 1


def test_notebook_import_path():
    from trellis_analytics.routines import curation_coverage as fn
    assert callable(fn)


def test_mixed_timestamp_shapes_order_correctly_around_a_reset(make_ods):
    # '20261006T2100Z' sorts AFTER '2026-10-08...' as a string, but is earlier in time: it predates the reset
    url = make_ods(schemas=["s1"],
                   proofs=[("schema", "s1", "restored", "20261006T2100Z", "{}"),
                           ("database", "", "egeria_reset", "2026-10-08T22:07:59", "{}")])
    r = curation_coverage(OdsReader(url), "database", "demo")
    assert r.count("published", "schemas") == 0
