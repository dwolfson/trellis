"""ConversationAgent._last_compiled -- the seam the query routes read to
attach the same CompiledContext that shaped an answer onto the response,
without a second compile call (query.py's _compiled_payload)."""
from unittest.mock import patch

from resource_explorer.agents.conversation_agent import ConversationAgent
from resource_explorer.context_compile import CompiledContext


def _fake_compiled() -> CompiledContext:
    return CompiledContext(
        text="## repository_health\nscore: 85.8",
        manifest={
            "gaps": [{"key": "security_scan", "reason": "has not run"}],
            "packed": [{"key": "repository_health", "role": "evidence",
                        "rung": "SUMMARY", "size": 30}],
        },
        derivation=[{"question": "Is this healthy?", "analysis_ids": ["repository_health"]}],
    )


class TestCompiledEvidenceSeam:
    def test_sets_last_compiled_on_success(self):
        agent = ConversationAgent()
        with patch("resource_explorer.agents.conversation_agent._registry", return_value=object()), \
             patch("resource_explorer.context_compile.compile_context", return_value=_fake_compiled()):
            lines = agent._compiled_evidence("is this healthy?", "egeria_git", None)

        assert agent._last_compiled is not None
        assert agent._last_compiled.manifest["packed"][0]["key"] == "repository_health"
        assert any("repository_health" in line for line in lines)
        assert any("security_scan" in line for line in lines)  # the gap line

    def test_stays_none_when_compile_fails(self):
        """Fail-soft: a compiler that cannot compile must not cost the
        answer -- and must not leave a stale _last_compiled from a prior
        turn looking like it belongs to this one."""
        agent = ConversationAgent()
        agent._last_compiled = _fake_compiled()  # simulate a prior turn's leftover
        with patch("resource_explorer.agents.conversation_agent._registry", return_value=object()), \
             patch("resource_explorer.context_compile.compile_context", side_effect=RuntimeError("boom")):
            lines = agent._compiled_evidence("is this healthy?", "egeria_git", None)

        assert lines == []
        # _compiled_evidence itself doesn't reset on failure -- handle() does,
        # up front, every turn. Verified separately below.

    def test_handle_resets_last_compiled_when_no_slug_in_scope(self):
        """A question with no resource in scope must not carry over the
        previous turn's compiled evidence as if it belonged to this answer --
        the exact failure mode a stateful, reused agent instance risks."""
        agent = ConversationAgent()
        agent._last_compiled = _fake_compiled()
        with patch.object(agent, "_run_persistent", return_value="some answer"):
            agent.handle("a question naming no project", resource_slug=None)

        assert agent._last_compiled is None


class TestSystemPromptPrefersEvidenceOverSearch:
    """Measured 2026-08-31: asked about this repository's documentation
    survey results, the model called vector_search and answered from
    Egeria's OWN documentation about its unrelated Survey Framework feature
    -- a keyword match on "survey", not an answer about the resource. An
    Evidence block was present; nothing told the model to prefer it over a
    general-corpus tool call it was equally free to make. Locking in the
    prompt guidance added for this so a future rewrite doesn't drop it
    silently -- the failure mode is exactly the kind that "looks fine" in
    review (fluent prose, a real citation) and needs a live report to catch."""

    def test_prompt_names_the_evidence_block_and_tells_the_model_to_prefer_it(self):
        prompt = ConversationAgent().system_prompt()
        assert "Evidence (compiled from stored analysis results)" in prompt
        assert "prefer it over vector_search" in prompt

    def test_prompt_asks_for_clarification_rather_than_substitution(self):
        prompt = ConversationAgent().system_prompt()
        assert "clarifying question" in prompt
        assert "do not fall back to a broader search" in prompt
