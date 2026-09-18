"""Curate's page-level section nav + collapsible sections -- a follow-on to
item 3 (SPEC-CURATE-SELECTION-AND-BLUEPRINTS.md), not a new numbered plan
item. The project owner tested Curate live after item 3 shipped and reported
"one very long page with no table of contents at the top, the sections are
not collapsible." Same static-source-holds-the-design-rules approach as
test_next_curate_pane.py/test_next_curate_selection_and_blueprints.py: a
Python suite cannot run the browser, but it can hold the shipped source to
the rules this addition states as requirements.
"""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"

SECTION_IDS = [
    "curate-sec-what-it-is",
    "curate-sec-what-holds",
    "curate-sec-made-of",
    "curate-sec-blueprints",
    "curate-sec-relates",
    "curate-sec-writes",
]


def _curate_src():
    return (NEXT / "stages" / "curate.js").read_text(encoding="utf-8")


class TestSixSectionsExistWithStableIds:
    """One id per section, matching the six sections `renderCurate` renders:
    what it is, what's in it, what it's made of, blueprints, how it relates,
    what gets written."""

    def test_all_six_section_ids_are_declared(self):
        src = _curate_src()
        for sid in SECTION_IDS:
            assert sid in src, f"missing section id {sid!r}"

    def test_the_nav_links_to_all_six_sections(self):
        src = _curate_src()
        # The declared section list (CURATE_SECTIONS) drives both the ids
        # used elsewhere and the nav's own template -- check the list itself
        # names all six, and the nav template renders an anchor + data
        # attribute per entry via `s.id`.
        sections_body = src[src.index("const CURATE_SECTIONS = ["):src.index("];", src.index("const CURATE_SECTIONS = ["))]
        for sid in SECTION_IDS:
            assert f"id: '{sid}'" in sections_body
        nav_body = src[src.index("function curateSectionNavHtml("):src.index("function bindCurateSectionNav(")]
        assert 'href="#${s.id}"' in nav_body
        assert 'data-curate-nav="${s.id}"' in nav_body

    def test_blueprints_is_its_own_section_separate_from_made_of(self):
        # Item 3 nested the blueprint list inside the "made of" column;
        # this addition promotes it to its own top-level, independently
        # collapsible/anchored section. Look at the actual render call site
        # (in `draw`), not the CURATE_SECTIONS declaration list, where both
        # ids necessarily sit next to each other.
        src = _curate_src()
        draw_body = src[src.index("const draw = () => {"):src.index("bindCurateSectionNav(host);")]
        made_of_call = draw_body[draw_body.index("'curate-sec-made-of'"):draw_body.index("'curate-sec-blueprints'")]
        assert "blueprint-list" not in made_of_call
        assert "component-tree" in made_of_call


class TestSectionsAreCollapsibleDetailsDefaultOpen:
    """Matching /next's existing disclosure idiom (app.js's other <details>
    usage): <details>/<summary>, summary is the section's own heading text,
    default open -- the reported problem was missing navigation/structure,
    not too much visible at once, so collapse must not default-hide."""

    def test_the_section_wrapper_is_a_details_element(self):
        src = _curate_src()
        body = src[src.index("function curateSectionHtml("):src.index("async function renderCurate(")]
        assert "<details id=\"${id}\" open" in body
        assert "<summary" in body

    def test_every_call_site_uses_the_shared_wrapper_for_all_six_sections(self):
        src = _curate_src()
        body = src[src.index("const draw = () => {"):src.index("bindCurateSectionNav(host);")]
        for sid in SECTION_IDS:
            assert f"curateSectionHtml('{sid}'" in body


class TestAnchorScrollMatchesClassicsConvention:
    """The nav's anchor clicks scroll via `scrollIntoView({ behavior:
    'smooth', block: 'center' })`, the same convention classic's own
    `_curateJumpTo` (index.html) uses -- reused for consistency, not
    reinvented, since there is no existing PAGE-level nav pattern to port
    (classic's jump-to-component/blueprint is a narrower cross-reference
    feature, not this)."""

    def test_the_nav_click_handler_calls_scrollintoview_smooth_center(self):
        src = _curate_src()
        body = src[src.index("function bindCurateSectionNav("):src.index("function curateSectionHtml(")]
        assert "scrollIntoView({ behavior: 'smooth', block: 'center' })" in body

    def test_clicking_a_collapsed_section_opens_it_before_scrolling(self):
        src = _curate_src()
        body = src[src.index("function bindCurateSectionNav("):src.index("function curateSectionHtml(")]
        assert "el.open = true" in body


class TestComponentTreeInternalsUntouched:
    """A concurrent, separately-assigned piece of work (re/curate-tree-scope
    -groups) is building scope-hierarchy grouping against
    `renderComponentTree`'s row logic on a different branch. This addition
    must only wrap the section's OUTER container and must not touch what
    that function returns internally."""

    def test_render_component_tree_body_has_no_new_section_wrapper_markup(self):
        src = _curate_src()
        body = src[src.index("async function renderComponentTree("):src.index("/* ── Blueprints")]
        assert "curateSectionHtml" not in body
        assert "data-curate-nav" not in body
        assert "curate-sec-" not in body
