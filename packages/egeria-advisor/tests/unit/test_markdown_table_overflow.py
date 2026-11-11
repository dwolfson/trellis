"""The generic markdown table EA draws for a result with no TABLE columns in its spec keeps
MAX_TABLE_ROWS rows, MAX_TABLE_COLS columns and MAX_CELL_CHARS per cell. A cap is counted, never
silent: "+N more rows", "+N more columns: a, b, ..." (naming the hidden columns, as the Portal does,
odpi/egeria-workspaces#833), and a cut cell ends in "…". A table under every cap is unchanged."""
from __future__ import annotations

from advisor import report_pipeline as rp

table = rp.ReportPipeline._dict_to_markdown_table


def _rows(n_rows: int, n_cols: int, width: int = 3):
    return [{f"col_{c}": f"r{r}c{c}".ljust(width, "x") for c in range(n_cols)}
            for r in range(n_rows)]


def _table_lines(md: str):
    return [ln for ln in md.splitlines() if ln.startswith("|")]


def test_a_small_table_is_exactly_as_before():
    md = table(_rows(3, 4), "T")
    assert md.splitlines() == [
        "| col_0 | col_1 | col_2 | col_3 |",
        "| --- | --- | --- | --- |",
        "| r0c0 | r0c1 | r0c2 | r0c3 |",
        "| r1c0 | r1c1 | r1c2 | r1c3 |",
        "| r2c0 | r2c1 | r2c2 | r2c3 |",
    ]
    assert "more" not in md and "…" not in md


def test_rows_past_the_cap_are_counted():
    md = table(_rows(rp.MAX_TABLE_ROWS + 7, 2), "T")
    assert len(_table_lines(md)) == 2 + rp.MAX_TABLE_ROWS
    assert md.splitlines()[-1] == "*+7 more rows*"
    assert md.splitlines()[-2] == ""          # the note is a paragraph, not another table row


def test_one_more_row_is_singular():
    assert table(_rows(rp.MAX_TABLE_ROWS + 1, 2), "T").splitlines()[-1] == "*+1 more row*"


def test_columns_past_the_cap_are_counted_and_named():
    md = table(_rows(2, rp.MAX_TABLE_COLS + 2), "T")
    assert _table_lines(md)[0].count("|") == rp.MAX_TABLE_COLS + 1
    assert md.splitlines()[-1] == r"*+2 more columns: col\_8, col\_9*"


def test_a_long_list_of_hidden_columns_names_six_and_counts_the_rest():
    note = rp.hidden_columns_note([f"c{i}" for i in range(10)])
    assert note == "+10 more columns: c0, c1, c2, c3, c4, c5, and 4 more"


def test_rows_and_columns_together():
    md = table(_rows(rp.MAX_TABLE_ROWS + 3, rp.MAX_TABLE_COLS + 1), "T")
    assert md.splitlines()[-1] == r"*+3 more rows; +1 more column: col\_8*"


def test_a_cut_cell_ends_in_an_ellipsis():
    md = table([{"Name": "a" * 200}], "T")
    cell = _table_lines(md)[2].strip("| ").strip()
    assert len(cell) == rp.MAX_CELL_CHARS and cell.endswith("…")
    # Exactly at the cap: the whole cell.
    assert table([{"Name": "a" * rp.MAX_CELL_CHARS}], "T").count("…") == 0


def test_skipped_identity_columns_do_not_count_as_hidden():
    # Only lower-case names in the skip set match today (it compares c.lower() with
    # camelCase names, so qualifiedName is shown): guid and versions are the skipped
    # ones, and they are not "hidden columns".
    rows = [{"guid": "g", "versions": "v", "Name": "n"}]
    md = table(rows, "T")
    assert "more" not in md and _table_lines(md)[0] == "| Name |"
