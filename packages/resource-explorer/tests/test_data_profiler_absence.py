"""An unmeasured null rate must not render as zero.

`data_file_profiling` profiles CSV/TSV/Excel by reading them, and Parquet/
Feather/Arrow from file metadata — deliberately, since metadata gives schema and
row count without loading any row data. Metadata does not carry null rates.

Until 2026-08-31 the columnar paths emitted `null_pct: 0.0` for every column
anyway. Every column of every Parquet file ever profiled therefore reported
"0% null", which is a measurement claim about data nobody read. Both UI
consumers rendered it as a real zero, and one of them (`c.null_pct ?? 0`) would
have gone on doing so even after the profiler started sending null.

This is the codebase's most-named bug class — an absence presented as a
finding — so it gets a test rather than a comment.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from resource_explorer.surveyors.sub_surveyors.data_profiler import DataProfilerSurveyor


def _write_parquet(path: Path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    # A column with a real null in it: if null_pct were ever measured here, the
    # correct answer would be 50.0, not 0.0 — so a 0.0 result cannot be excused
    # as "happened to be right".
    pd.DataFrame({"a": [1, None], "b": ["x", "y"]}).to_parquet(path)


def test_parquet_null_pct_is_unknown_not_zero(tmp_path):
    p = tmp_path / "t.parquet"
    _write_parquet(p)

    profile = DataProfilerSurveyor._profile_parquet(p)
    assert profile is not None, "fixture produced no profile — the test would pass vacuously"

    assert profile["row_count"] == 2, "row count comes from metadata and should be real"
    assert profile["columns"], "fixture produced no columns"

    for col in profile["columns"]:
        assert col["null_pct"] is None, (
            f"column {col['name']!r} reports null_pct={col['null_pct']!r}. "
            "Metadata carries no null rates, so the honest answer is None. "
            "0.0 would claim 'measured, no nulls' about data never read — and "
            "column 'a' is genuinely 50% null, so 0.0 is also wrong."
        )

    assert profile["null_summary"], (
        "an empty null_summary leaves a reader no way to tell 'no nulls found' "
        "from 'null rates not read'"
    )


def test_csv_still_measures_null_pct(tmp_path):
    """The guard above must not be satisfiable by never measuring anything."""
    pd = pytest.importorskip("pandas")
    p = tmp_path / "t.csv"
    pd.DataFrame({"a": [1, None], "b": ["x", "y"]}).to_csv(p, index=False)

    import pandas as _pd
    profile = DataProfilerSurveyor._profile_file(p, "csv", _pd)

    assert profile is not None, "fixture produced no profile"
    by_name = {c["name"]: c for c in profile["columns"]}
    assert by_name["a"]["null_pct"] == 50.0, (
        "CSV is read, not metadata-scanned, so its null rates are genuinely "
        f"measured — got {by_name['a']['null_pct']!r}"
    )
