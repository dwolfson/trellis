"""A published annotation must be followable across runs.

The scheme was `Annotation::{slug}::{surveyed_at}::{i}`, where `i` is the
enumeration index within the run. Positions are not stable. Measured on
egeria_git's two largest published runs, across 115 overlapping indices:

    same finding at the same index:  0 / 115   (0%)

    [0] 'Ruleset gitleaks rules last changed…'  vs  '★ 921 · 265 fork(s)…'
    [1] '1172 secret-shaped match(es) found…'   vs  '6327 file(s) inventoried'

So a check could not be followed through time, even though every value worth
trending was already published in the annotation's own
resourceProperties/jsonProperties. Dan's point, 2026-09-02: the qualifiedName
is ours to construct, and check_name can live in it.

check_name is a usable identity for 84.9% of stored findings. The other 15.1%
are list-shaped — one finding per item, not per check — and need an
`item_key` the surveyor supplies, because only it knows what identifies its
item.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation,
    annotation_qualified_name,
    assert_unique_qualified_names,
)


def _ann(**kw):
    kw.setdefault("summary", "s")
    kw.setdefault("analysis_step", "Step")
    return ClassificationAnnotation(**kw)


class TestIdentityIsStable:
    def test_the_name_does_not_depend_on_position(self):
        """The whole defect in one assertion: the same check emitted at a
        different index must publish the same name."""
        a = _ann(check_name="security_policy")
        assert (annotation_qualified_name("P", 0, a)
                == annotation_qualified_name("P", 112, a))

    def test_a_list_shaped_item_is_distinguished_by_its_key(self):
        first = _ann(check_name="secret_pattern", item_key="app.py:22")
        second = _ann(check_name="secret_pattern", item_key="lib.py:9")
        assert annotation_qualified_name("P", 0, first) != \
               annotation_qualified_name("P", 1, second)
        assert annotation_qualified_name("P", 0, first) == "P::secret_pattern::app.py:22"

    def test_no_check_name_falls_back_to_the_old_scheme(self):
        """A fallback, not a removal: a surveyor not yet migrated must still
        publish rather than fail."""
        assert annotation_qualified_name("P", 7, _ann()) == "P::7"

    def test_a_separator_inside_a_part_cannot_forge_a_name(self):
        """Escaped, not stripped. A check_name containing '::' would
        otherwise change the shape of the name and could collide with a
        different annotation's identity."""
        # STRIPPING the separator would map "a::b" and "ab" onto the same
        # name — two different checks silently sharing one identity, which the
        # collision guard would then refuse for the wrong reason or, worse,
        # not see at all across runs. The first version of this test compared
        # "weird::name" against check "weird" + item "name", which survives
        # stripping too, so it passed against the broken implementation.
        collide_a = _ann(check_name="a::b")
        collide_b = _ann(check_name="ab")
        assert annotation_qualified_name("P", 0, collide_a) != \
               annotation_qualified_name("P", 1, collide_b), (
            "escaping must preserve the distinction between 'a::b' and 'ab'")


class TestCollisionGuard:
    def test_two_annotations_sharing_an_identity_are_refused(self):
        """Known-negative. Without this, the second create is rejected by
        Egeria as a duplicate, apply_element ADOPTS the existing GUID, and the
        run reports success having published one element where two were
        produced — silent loss reported as a clean publish."""
        dupes = [_ann(check_name="security_policy"),
                 _ann(check_name="security_policy", summary="different text")]
        with pytest.raises(ValueError, match="item_key"):
            assert_unique_qualified_names("P", dupes)

    def test_the_message_names_the_offending_check(self):
        with pytest.raises(ValueError, match="secret_pattern"):
            assert_unique_qualified_names(
                "P", [_ann(check_name="secret_pattern"),
                      _ann(check_name="secret_pattern")])

    def test_list_shaped_with_distinct_keys_passes(self):
        assert_unique_qualified_names(
            "P", [_ann(check_name="secret_pattern", item_key="a:1"),
                  _ann(check_name="secret_pattern", item_key="b:2")])

    def test_legacy_positional_annotations_never_collide(self):
        """A whole run of un-migrated annotations must still publish."""
        assert_unique_qualified_names("P", [_ann() for _ in range(50)])


class TestBothPublishPathsAgree:
    def test_the_outbox_and_direct_paths_use_one_builder(self):
        """Two call sites with their own formatting would make a retry create
        a second element instead of converging on the one already written."""
        import inspect

        from resource_explorer import egeria_outbox
        from resource_explorer.surveyors import annotation_props

        for mod in (egeria_outbox, annotation_props):
            src = inspect.getsource(mod)
            assert "annotation_qualified_name(qualified_name_prefix" in src, mod.__name__
            assert '{qualified_name_prefix}::{i}' not in src, (
                f"{mod.__name__} still formats a qualifiedName itself")
