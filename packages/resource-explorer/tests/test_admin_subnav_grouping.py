"""Admin's panes are grouped, and no pane may go missing in the grouping.

Admin was a flat row of nine buttons. Grouping them by what a person came to do
(Configure / Reconcile / Observe) is presentation, so these tests assert the
things a restyle must not break rather than the styling itself:

  - every pane is reachable from the subnav
  - no pane is listed twice, which would put the same destination in two
    unrelated groups and make the grouping meaningless
  - the panes listed are exactly the panes that exist

The last one is the point. A pane dropped from `_ADMIN_GROUPS` does not error —
its route still works and its view still renders — it simply becomes
unreachable, which is the failure a flat list made impossible and a grouped one
makes easy.
"""
from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"

#: Every Admin destination. Adding a pane means adding it here and to a group —
#: the test exists so that omitting the second step fails loudly.
ADMIN_PANES = {
    "annotations",
    "admin-groups",
    "admin-discovery-sources",
    "admin-question-catalog",
    "admin-resync",
    "admin-egeria-links",
    "admin-outbox",
    "admin-repair",
    "admin-prefect",
    "admin-feedback",
    "admin-logs",
}


def _grouped_tabs() -> list[str]:
    s = INDEX.read_text()
    i = s.index("const _ADMIN_GROUPS")
    block = s[i:s.index("function _adminSubnavHtml", i)]
    return re.findall(r"tab:\s*'([^']+)'", block)


def test_every_admin_pane_is_reachable_from_the_subnav():
    tabs = _grouped_tabs()
    assert tabs, "no tabs found — the _ADMIN_GROUPS structure moved or was renamed"
    missing = ADMIN_PANES - set(tabs)
    assert not missing, (
        f"Admin panes exist but no subnav button reaches them: {sorted(missing)}. "
        "A pane left out of a group does not error — it just becomes unreachable."
    )


def test_no_pane_is_listed_in_two_groups():
    tabs = _grouped_tabs()
    dupes = {t for t in tabs if tabs.count(t) > 1}
    assert not dupes, (
        f"{sorted(dupes)} appear in more than one Admin group. One destination in "
        "two groups means the grouping does not describe anything."
    )


def test_the_subnav_lists_no_pane_that_does_not_exist():
    extra = set(_grouped_tabs()) - ADMIN_PANES
    assert not extra, (
        f"subnav offers {sorted(extra)}, which are not known Admin panes — "
        "either the pane was removed and its button left behind, or this test's "
        "ADMIN_PANES needs the new name"
    )


def test_groups_are_named_by_the_question_being_asked():
    """Configure / Reconcile / Observe, not by subsystem.

    The axis matters more than the names: grouping by subsystem (Egeria things,
    Prefect things) would put Egeria Alignment and Egeria Links beside Annotation
    Types, which is a taxonomy of the code rather than of the user's errand.
    """
    s = INDEX.read_text()
    block = s[s.index("const _ADMIN_GROUPS"):s.index("function _adminSubnavHtml")]
    names = re.findall(r"name:\s*'([^']+)'", block)
    assert names == ["Configure", "Reconcile", "Observe"], names

def test_the_subnav_does_not_wrap_into_a_second_row():
    """Eleven buttons plus three labels will not stay on one line, and a wrapped
    row strands a group heading in the middle of it — reported from the running
    app 2026-08-31, which is how the button row was found to be wrong.

    Asserted structurally rather than visually: one control per group instead of
    one per pane is what makes the width independent of how many panes exist.
    """
    html = INDEX.read_text()
    fn = html[html.index("function _adminSubnavHtml"):]
    fn = fn[:fn.index("\nfunction ")]

    assert "<select" in fn, "the subnav no longer renders a control per group"
    assert "flex-wrap" not in fn, (
        "the subnav container allows wrapping again — with a control per group "
        "it does not need to, and wrapping is what stranded the group labels"
    )
    # One <select> per group, not one <button> per pane.
    assert fn.count("<button") == 0, (
        "buttons are back in the subnav: that is the layout that wrapped"
    )


def test_the_active_pane_is_selected_in_its_own_group():
    """A dropdown that does not show the current pane makes the subnav a
    navigation control with no state — the user cannot tell where they are."""
    html = INDEX.read_text()
    fn = html[html.index("function _adminSubnavHtml"):]
    fn = fn[:fn.index("\nfunction ")]
    assert "t.tab === active ? 'selected' : ''" in fn, (
        "no option is marked selected for the active pane"
    )
    assert "holdsActive" in fn, (
        "nothing distinguishes the group containing the active pane from the others"
    )
