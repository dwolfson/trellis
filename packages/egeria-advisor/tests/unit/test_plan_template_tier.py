"""BACKLOG.md PC-1 — plan composition must load the draft's own template tier.

Before this fix `_load_template()` loaded `basic/` unconditionally, and
`_compose_command_block()` only emits an attribute that appears in the loaded
template's `attributes` list. Any advanced-only field the user had set was
therefore dropped at compose time with no error and no warning — confirmed
live 2026-07-06 with `Parent ID` / `Parent Relationship Type Name` on a
Create Project command.

The tests below render an actual command block and assert on the markdown,
rather than asserting on which file got loaded — the bug was invisible at the
loading layer and only showed up in the document.
"""
import pytest

from advisor.agents.governance_plan_agent import GovernancePlanAgent


@pytest.fixture
def agent():
    return GovernancePlanAgent()


def _render(agent, action, params, mode):
    return agent._compose_command_block(
        {
            "action": action,
            "narrative": "",
            "params": params,
            "template_parsed": agent._load_template(action, mode),
        },
        1,
    )


class TestTierSelection:
    def test_advanced_tier_carries_more_attributes_than_basic(self, agent):
        basic = agent._load_template("Create Project", "basic")
        advanced = agent._load_template("Create Project", "advanced")
        assert basic and advanced
        assert len(advanced["attributes"]) > len(basic["attributes"])

    def test_advanced_is_a_superset_of_basic(self, agent):
        """No field is lost by moving up a tier — the reason no cross-tier
        merge is needed."""
        names = lambda t: {a["name"] for a in t["attributes"]}
        assert names(agent._load_template("Create Project", "basic")) <= names(
            agent._load_template("Create Project", "advanced")
        )

    def test_required_fields_are_identical_across_tiers(self, agent):
        """So loading advanced cannot introduce a new '<!-- TODO: fill in -->'."""
        req = lambda t: {a["name"] for a in t["attributes"] if a["required"]}
        assert req(agent._load_template("Create Project", "basic")) == req(
            agent._load_template("Create Project", "advanced")
        )

    def test_defaults_to_basic(self, agent):
        names = lambda t: {a["name"] for a in t["attributes"]}
        assert names(agent._load_template("Create Project")) == names(
            agent._load_template("Create Project", "basic")
        )

    def test_an_unknown_tier_falls_back_to_basic_rather_than_returning_none(self, agent):
        """A template collection predating the two-tier layout must still work."""
        assert agent._load_template("Create Project", "no-such-tier") is not None


class TestAdvancedFieldsSurviveComposition:
    """The actual PC-1 regression."""

    PARAMS = {
        "Display Name": "Child Project",
        "Description": "A sub-project",
        "Parent ID": "parent-project-qname",
        "Parent Relationship Type Name": "ProjectHierarchy",
    }

    def test_advanced_mode_renders_parent_id(self, agent):
        rendered = _render(agent, "Create Project", self.PARAMS, "advanced")
        assert "### Parent ID" in rendered
        assert "parent-project-qname" in rendered

    def test_advanced_mode_renders_parent_relationship_type_name(self, agent):
        rendered = _render(agent, "Create Project", self.PARAMS, "advanced")
        assert "### Parent Relationship Type Name" in rendered
        assert "ProjectHierarchy" in rendered

    def test_basic_mode_still_drops_them_because_the_fields_do_not_exist_there(self, agent):
        """Not a bug: basic-tier Create Project has no such field. This asserts
        the fix did not change basic mode's output."""
        rendered = _render(agent, "Create Project", self.PARAMS, "basic")
        assert "### Parent ID" not in rendered

    def test_basic_fields_are_unaffected_by_the_tier(self, agent):
        for mode in ("basic", "advanced"):
            rendered = _render(agent, "Create Project", self.PARAMS, mode)
            assert "### Display Name" in rendered
            assert "Child Project" in rendered

    def test_unset_advanced_fields_add_nothing_to_the_document(self, agent):
        """Optional attributes render only when they have a value, so moving to
        the advanced tier does not bloat a plan that sets nothing extra."""
        minimal = {"Display Name": "Plain Project"}
        basic = _render(agent, "Create Project", minimal, "basic")
        advanced = _render(agent, "Create Project", minimal, "advanced")
        assert advanced.count("### ") == basic.count("### ")

    def test_no_new_todo_placeholders_appear_at_the_advanced_tier(self, agent):
        minimal = {"Display Name": "Plain Project"}
        basic = _render(agent, "Create Project", minimal, "basic")
        advanced = _render(agent, "Create Project", minimal, "advanced")
        assert advanced.count("TODO: fill in") == basic.count("TODO: fill in")


class TestDraftModeResolution:
    def test_no_draft_id_means_basic(self, agent):
        assert agent._draft_mode(None) == "basic"

    def test_an_unreadable_draft_falls_back_to_basic_rather_than_raising(self, agent):
        assert agent._draft_mode("definitely-not-a-real-draft-id") == "basic"
