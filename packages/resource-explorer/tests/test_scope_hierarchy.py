"""The hierarchy the scope locator already encodes.

`projection.py` collapses a hierarchy to a level and had never been given one:
milvus reported 204 components at every depth, genaicomps 311. Two earlier
diagnoses were wrong — the backlog said persistence filtered out intermediate
candidates, the presentation session then found persisting them changed
nothing. Measured directly: 201 of milvus's 217 component rows carry
`parent_slug = ""`, because only `code::` components ever had a hierarchy at
all and everything else is parentless by construction.
"""
from __future__ import annotations

from resource_explorer.surveyors.arch_recovery import scope_hierarchy as sh


class TestBothLocatorShapesNameAParent:
    def test_a_path_names_its_directory(self):
        assert sh.parent_of("internal/agg") == "internal"

    def test_an_identity_names_its_deployment_unit(self):
        """`compose::agent` means "the agent service declared in that compose
        file", and the compose file is a real deployment unit. Reading it is
        reading what the detector wrote down, not splitting a string hopefully."""
        assert sh.parent_of("compose::agent") == "compose"
        assert sh.parent_of("cluster::milvus-proxy") == "cluster"

    def test_a_single_segment_has_no_parent(self):
        assert sh.parent_of("cmd") == ""

    def test_the_repo_root_still_counts_as_a_unit(self):
        """milvus has eight `.::<service>` components from a root compose file,
        and `.` is itself a scope. Discarding it left all eight as separate
        roots when the file declaring them is exactly what groups them."""
        assert sh.parent_of(".::azurite") == "."


class TestItAttachesToTheNearestANCESTORThatGroups:
    """Not the nearest parent. `internal/parser/planparserv2` has one sibling
    under `internal/parser` and dozens under `internal`; attaching only to the
    immediate parent left it a root three levels deep while `internal` sat
    there grouping the rest."""

    def test_it_walks_past_a_parent_too_small_to_qualify(self):
        scopes = ["internal/parser/planparserv2", "internal/agg", "internal/kv",
                  "internal/cdc"]
        parents, _ = sh.derive(scopes)
        assert parents["internal/parser/planparserv2"] == "internal"

    def test_it_prefers_the_nearest_qualifying_ancestor(self):
        scopes = ["a/b/one", "a/b/two", "a/c", "a/d"]
        parents, _ = sh.derive(scopes)
        assert parents["a/b/one"] == "a/b", "a/b groups two, so it wins over a"
        assert parents["a/c"] == "a"


class TestAParentOfOneIsNotAParent:
    def test_a_lone_child_creates_no_node(self):
        """It collapses nothing and adds a level a reader must traverse to
        reach a single child."""
        parents, structural = sh.derive(["solo/only", "other"])
        assert parents == {} and structural == set()

    def test_two_children_do(self):
        parents, structural = sh.derive(["g/a", "g/b"])
        assert set(parents) == {"g/a", "g/b"}
        assert structural == {"g"}


class TestDerivedParentsAreStructuralNotComponents:
    def test_a_parent_that_is_itself_a_scope_is_not_structural(self):
        """`pkg` is a real detected component AND a parent. It must not be
        duplicated as a structural node."""
        _, structural = sh.derive(["pkg", "pkg/a", "pkg/b"])
        assert structural == set()

    def test_a_parent_nobody_detected_is_structural(self):
        """Nothing detected `internal/` — its children were detected. It has no
        marker evidence of its own, so it carries no type and no confidence;
        emitting it as an ordinary component would invent evidence, which is
        what design §5's no-metric-no-number rule exists to prevent."""
        _, structural = sh.derive(["internal/a", "internal/b"])
        assert structural == {"internal"}


class TestItActuallyCollapses:
    def test_a_flat_set_stays_flat(self):
        scopes = ["a", "b", "c"]
        parents, _ = sh.derive(scopes)
        assert parents == {}, "nothing to group is a real answer, not a failure"

    def test_the_summary_reports_shape_not_a_bare_count(self):
        """A hierarchy that collapsed nothing and one that collapsed everything
        both report a number; only roots-and-groups distinguishes them."""
        scopes = ["g/a", "g/b", "h/c", "h/d"]
        parents, _ = sh.derive(scopes)
        line = sh.summarise(scopes, parents)
        assert "4 scope(s)" in line and "0 root(s)" in line and "2 parent group(s)" in line

    def test_no_scope_becomes_its_own_parent(self):
        for scopes in (["a", "a/a"], ["x::x"], ["."]):
            parents, _ = sh.derive(scopes)
            assert all(k != v for k, v in parents.items())
