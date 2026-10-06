"""Source pins for the Curate scope table layout (Part 2 of the 2026-10-06 slice): the table scrolls
INSIDE its own box and its headers wrap. The behaviour is in the harness test
`curate-scope-layout.test.mjs`; these pins keep the structure from being edited away unseen."""
from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"
SCOPE = (NEXT / "stages" / "curate-scope.js").read_text(encoding="utf-8")
BANDS = (NEXT / "stages" / "curate-bands.js").read_text(encoding="utf-8")


def test_the_tree_host_scrolls_inside_its_own_box_and_can_shrink():
    assert 'data-scope-tree class="min-w-0 max-w-full overflow-x-auto"' in SCOPE


def test_the_section_that_holds_the_scope_can_shrink_in_its_parent():
    assert 'data-curate-work="scope" class="mb-s3 min-w-0"' in BANDS


def test_the_classification_header_is_the_full_word_and_wraps():
    assert ">Classification</div>" in SCOPE
    assert ">Classes</div>" not in SCOPE


def test_no_truncating_class_in_the_scope_table():
    for bad in ("truncate", "text-ellipsis"):
        assert bad not in SCOPE
