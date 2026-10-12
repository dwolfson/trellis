"""2d: the tile's spec written as a Dr.Egeria report-spec document parses to the Python FormatSet."""
from pathlib import Path

from trellis_analytics.portal import TILE_LABEL, report_specs

DOC = Path(__file__).resolve().parents[1] / "examples" / "curation_coverage_tile.md"


def test_the_document_parses_to_the_python_formatset():
    from advisor.report_spec_parser import parse_report_spec_markdown
    parsed = parse_report_spec_markdown(DOC.read_text())
    expected = report_specs()[TILE_LABEL]
    assert parsed.model_dump() == expected.model_dump()
    # and the fields that make it a presentation spec are really there
    assert parsed.action.analytic_function == "trellis_analytics.portal.curation_coverage_tile"
    assert parsed.action.analytic_spec_params == {"resource_type": "database"}
    assert [f.types for f in parsed.formats] == [["DICT", "JSON", "BAR"]]
