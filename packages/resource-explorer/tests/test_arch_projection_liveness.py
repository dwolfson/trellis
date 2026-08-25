"""Projection works; it is not configured. These pin the difference.

`arch_recovery/projection.py` has carried `DEFAULT_PROJECTION_DEPTH` and a
`STAGE_PROJECTION_DEPTH` table ("the level a stage wants") since it was
written. Nothing read the table and no route passed the parameter, so the
obvious next move looked like threading `depth` through the results route and
putting a depth selector on the architecture-recovery card.

Measured first, on real stored results:

    milvus      depth 0/1/2/3/None -> 204 components, every time
    genaicomps  depth 0/1/2/3/None -> 311 components, every time

The mechanism is sound; it has never been given resolvable input. `project_rows` walks `parent_path`,
which the results reader resolves from `parent_slug` via a slug->path map, and
that lookup resolves **nothing**: milvus persists 213 component slugs and
references 6 parents, of which 0 are themselves persisted components. Every
parent reference is an orphan, so every node is treated as root-attached and
projection is an identity function.

So the depth control is withheld pending that fix rather than abandoned: the
feature is unconfigured, not disproven. Configuring it means re-parenting to
the nearest surviving ancestor at persist time, or persisting the ancestors
that get referenced.
"""
from __future__ import annotations

from resource_explorer.surveyors.arch_recovery import projection as P


def _rows(pairs):
    return [{"path": p, "parent_path": par, "depth": d} for p, par, d in pairs]


def test_the_mechanism_works_on_a_resolvable_hierarchy():
    """Control case: given parents that actually exist, projection collapses."""
    rows = _rows([("a", "", 0), ("a/b", "a", 1), ("a/b/c", "a/b", 2)])
    assert len(P.project_rows(rows, max_depth=None)) == 3
    assert len(P.project_rows(rows, max_depth=0)) < 3, (
        "projection failed to collapse a genuinely nested input — the mechanism "
        "itself is broken, not merely starved of data"
    )


def test_orphan_parents_make_projection_an_identity_function():
    """Pins the measured production state, not the intent.

    Parents that name a node which was never persisted cannot resolve, so every
    node reads as root-attached. This is the real shape of milvus/genaicomps.
    """
    rows = _rows([("a/b", "nonexistent", 1), ("c/d", "also-missing", 2), ("e", "", 0)])
    assert len(P.project_rows(rows, max_depth=0)) == 3
    assert len(P.project_rows(rows, max_depth=None)) == 3


def test_depth_control_stays_unconfigured_while_parents_are_orphans():
    """A reminder with an address.

    If this starts failing, parents began resolving — detectors now persist the
    ancestors they reference — and the withdrawn depth control becomes worth
    building. Change this test deliberately at that point, not incidentally.
    """
    resolvable = _rows([("a", "", 0), ("a/b", "a", 1)])
    orphaned = _rows([("a", "", 0), ("a/b", "missing", 1)])
    assert len(P.project_rows(resolvable, max_depth=0)) == 1
    assert len(P.project_rows(orphaned, max_depth=0)) == 2
