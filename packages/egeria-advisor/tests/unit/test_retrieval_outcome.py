"""Tests for the four distinguished "nothing to build context from" cases —
ea-context-compilation-design.md §6/§7 step 0.

`RAGRetriever.build_context()` used to return the single bare string
"No relevant code found." for four genuinely different situations. Each test
below forces the real condition through `retrieve()` (not a mocked return
value standing in for the whole pipeline), then asserts on what
`build_context()` actually renders. `TestFourCasesProduceDifferentResults`
is the known-negative: it fails if the four cases were ever collapsed back
onto one constant message, which a test suite built only from mocked
returns would not have caught.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from advisor.multi_collection_store import MultiCollectionSearchResult
from advisor.retrieval_outcome import NEVER_RUN, NOT_ESTABLISHED, NOTHING_FOUND


def _fake_result(text: str, score: float, name: str = "x"):
    return SimpleNamespace(
        text=text,
        score=score,
        metadata={"file_path": "f.py", "type": "function", "name": name},
    )


class _FakeMultiStore:
    """Stands in for MultiCollectionStore.search_with_routing() only —
    everything else about RAGRetriever.retrieve() (the cache check, the
    min_score re-filter, the empty-result diagnosis) runs for real."""

    def __init__(self, result: MultiCollectionSearchResult):
        self._result = result
        self.calls = 0

    def search_with_routing(self, **kwargs):
        self.calls += 1
        return self._result


def _make_retriever(min_score=0.30, use_multi=True, multi_store=None, vector_store=None, embedding_gen=None):
    """Construct a RAGRetriever without running its heavy __init__ (vector
    store / embeddings / real Postgres) — same technique as
    tests/unit/test_model_tier.py's _make_retriever, extended with the
    multi/single-collection plumbing these tests exercise."""
    from advisor.rag_retrieval import RAGRetriever

    retriever = object.__new__(RAGRetriever)
    retriever.top_k = 5
    retriever.min_score = min_score
    retriever.max_context_length = 100_000
    retriever.rag_context_budget_tokens = None
    retriever.use_multi_collection = use_multi
    retriever.enable_cache = False
    retriever.cache = None
    retriever.multi_store = multi_store
    retriever.vector_store = vector_store
    retriever.embedding_gen = embedding_gen
    retriever._last_outcome = None
    return retriever


def _run(retriever, query="what is a glossary term"):
    """retrieve() then build_context() on whatever it returned — the real
    call sequence every production caller uses (retrieve_and_build_context,
    get_file_context)."""
    results = retriever.retrieve(query)
    return retriever.build_context(results, include_metadata=False)


# ---------------------------------------------------------------------------
# Case 1 — retrieval ran, nothing scored above min_score
# ---------------------------------------------------------------------------

class TestBelowThreshold:
    def test_forces_real_below_threshold_condition(self):
        # A genuine low-scoring hit comes back from the store — not a
        # canned "empty" stub — and min_score (0.30, EA's real default)
        # legitimately filters it out.
        multi_result = MultiCollectionSearchResult(
            results=[_fake_result("weak match", score=0.12, name="weak")],
            collections_searched=["pyegeria"],
        )
        retriever = _make_retriever(min_score=0.30, multi_store=_FakeMultiStore(multi_result))

        context = _run(retriever)

        assert retriever._last_outcome.state == NOTHING_FOUND
        assert retriever._last_outcome.reason == "below_threshold"
        # Actionable per the task's constraint 4: the threshold itself is named.
        assert "0.30" in context
        assert "threshold" in context.lower()


# ---------------------------------------------------------------------------
# Case 2 — the collection is empty (ingested, zero matching rows)
# ---------------------------------------------------------------------------

class TestCollectionEmpty:
    def test_forces_real_empty_ingested_collection(self):
        multi_result = MultiCollectionSearchResult(
            results=[],
            collections_searched=["pyegeria_cli"],
        )
        retriever = _make_retriever(multi_store=_FakeMultiStore(multi_result))

        fake_db = SimpleNamespace(
            execute_query=lambda sql, params: [{"collection_name": "pyegeria_cli"}]
        )
        with patch("advisor.db_consolidated.get_db_manager", return_value=fake_db):
            context = _run(retriever)

        assert retriever._last_outcome.state == NOTHING_FOUND
        assert retriever._last_outcome.reason == "collection_empty"
        assert "ingested" in context.lower()
        assert "nothing there to find" in context.lower()


# ---------------------------------------------------------------------------
# Case 3 — the collection was never ingested
# ---------------------------------------------------------------------------

class TestNeverIngested:
    def test_forces_real_uningested_collection(self):
        multi_result = MultiCollectionSearchResult(
            results=[],
            collections_searched=["egeria_workspaces"],
        )
        retriever = _make_retriever(multi_store=_FakeMultiStore(multi_result))

        # No row for this collection in ingest_log — genuinely never ingested.
        fake_db = SimpleNamespace(execute_query=lambda sql, params: [])
        with patch("advisor.db_consolidated.get_db_manager", return_value=fake_db):
            context = _run(retriever)

        assert retriever._last_outcome.state == NEVER_RUN
        assert retriever._last_outcome.reason == "never_ingested"
        assert "never" in context.lower()


# ---------------------------------------------------------------------------
# Case 4 — the vector store was unreachable
# ---------------------------------------------------------------------------

class TestStoreUnreachable:
    def test_multi_collection_all_searches_fail(self):
        # Every collection the router tried came back as an error, not an
        # empty result -- MultiCollectionStore.search_collection() records
        # this in .errors rather than silently returning [].
        multi_result = MultiCollectionSearchResult(
            results=[],
            collections_searched=["pyegeria", "egeria_java"],
            errors={
                "pyegeria": "connection refused",
                "egeria_java": "connection refused",
            },
        )
        retriever = _make_retriever(multi_store=_FakeMultiStore(multi_result))

        context = _run(retriever)

        assert retriever._last_outcome.state == NOT_ESTABLISHED
        assert retriever._last_outcome.reason == "store_unreachable"
        assert "infrastructure failure" in context.lower()
        # The whole point: it must not read like a corpus fact.
        assert "nothing there to find" not in context.lower()
        assert "never ingested" not in context.lower()

    def test_single_collection_search_raises(self):
        # The single-collection path (use_multi_collection=False) has no
        # per-collection error-swallowing layer — it raises directly.
        vector_store = SimpleNamespace(
            search=lambda **kwargs: (_ for _ in ()).throw(ConnectionError("db down"))
        )
        embedding_gen = SimpleNamespace(generate_embedding=lambda q: [0.1, 0.2])
        retriever = _make_retriever(
            use_multi=False, vector_store=vector_store, embedding_gen=embedding_gen
        )

        context = _run(retriever)

        assert retriever._last_outcome.state == NOT_ESTABLISHED
        assert retriever._last_outcome.reason == "store_unreachable"
        assert "db down" in context

    def test_ingest_log_lookup_failure_is_also_store_unreachable_not_a_guess(self):
        # Search itself succeeded (reachable), but the ingest_log check used
        # to disambiguate case 2 from case 3 fails — that failure is a fact
        # about us too, and must not be silently reported as either "empty"
        # or "never ingested".
        multi_result = MultiCollectionSearchResult(
            results=[], collections_searched=["pyegeria"],
        )
        retriever = _make_retriever(multi_store=_FakeMultiStore(multi_result))

        fake_db = SimpleNamespace(
            execute_query=lambda sql, params: (_ for _ in ()).throw(
                RuntimeError("ingest_log table unreachable")
            )
        )
        with patch("advisor.db_consolidated.get_db_manager", return_value=fake_db):
            context = _run(retriever)

        assert retriever._last_outcome.state == NOT_ESTABLISHED
        assert retriever._last_outcome.reason == "store_unreachable"
        assert "ingest_log table unreachable" in context


# ---------------------------------------------------------------------------
# Known-negative: the four cases must actually read differently.
# ---------------------------------------------------------------------------

class TestFourCasesProduceDifferentResults:
    """The bug being fixed is "one confident string for four situations".
    A suite where every case passes against a stub returning one constant
    proves nothing — this test fails unless the four messages, and their
    FactLayer-borrowed states, are genuinely distinct."""

    def _outcome_for(self, case: str):
        if case == "below_threshold":
            retriever = _make_retriever(
                multi_store=_FakeMultiStore(
                    MultiCollectionSearchResult(
                        results=[_fake_result("weak", score=0.05)],
                        collections_searched=["pyegeria"],
                    )
                )
            )
            context = _run(retriever)
            return retriever._last_outcome, context

        if case == "collection_empty":
            retriever = _make_retriever(
                multi_store=_FakeMultiStore(
                    MultiCollectionSearchResult(results=[], collections_searched=["pyegeria"])
                )
            )
            with patch(
                "advisor.db_consolidated.get_db_manager",
                return_value=SimpleNamespace(
                    execute_query=lambda sql, params: [{"collection_name": "pyegeria"}]
                ),
            ):
                context = _run(retriever)
            return retriever._last_outcome, context

        if case == "never_ingested":
            retriever = _make_retriever(
                multi_store=_FakeMultiStore(
                    MultiCollectionSearchResult(results=[], collections_searched=["pyegeria"])
                )
            )
            with patch(
                "advisor.db_consolidated.get_db_manager",
                return_value=SimpleNamespace(execute_query=lambda sql, params: []),
            ):
                context = _run(retriever)
            return retriever._last_outcome, context

        if case == "store_unreachable":
            retriever = _make_retriever(
                multi_store=_FakeMultiStore(
                    MultiCollectionSearchResult(
                        results=[],
                        collections_searched=["pyegeria"],
                        errors={"pyegeria": "timeout"},
                    )
                )
            )
            context = _run(retriever)
            return retriever._last_outcome, context

        raise ValueError(case)

    def test_all_four_messages_are_pairwise_distinct(self):
        cases = ["below_threshold", "collection_empty", "never_ingested", "store_unreachable"]
        outcomes = {c: self._outcome_for(c) for c in cases}

        messages = {c: ctx for c, (_outcome, ctx) in outcomes.items()}
        # Pairwise distinct — this is the assertion that would fail if all
        # four collapsed back onto "No relevant code found." (or any other
        # single shared string).
        seen = set()
        for case, message in messages.items():
            assert message not in seen, (
                f"case {case!r} produced a message already seen for another "
                f"case — the four situations have collapsed back together"
            )
            seen.add(message)

        # None of them may be the old collapsed string.
        for message in messages.values():
            assert message != "No relevant code found."

    def test_states_are_not_all_the_same(self):
        # Two states legitimately coincide (below_threshold and
        # collection_empty are both a real, measured NOTHING_FOUND — see
        # advisor/retrieval_outcome.py's module docstring for why that is
        # a deliberate choice, not the bug). But collapsing all four to one
        # state would be exactly the bug this module fixes, so require at
        # least the three states the design distinguishes.
        cases = ["below_threshold", "collection_empty", "never_ingested", "store_unreachable"]
        states = {self._outcome_for(c)[0].state for c in cases}
        assert states == {NOTHING_FOUND, NEVER_RUN, NOT_ESTABLISHED}

    def test_store_unreachable_never_reads_as_nothing_found(self):
        # Design constraint 2, made concrete: a fact about us (case 4) must
        # never render with the vocabulary used for a genuine corpus zero.
        outcome, context = self._outcome_for("store_unreachable")
        assert outcome.state != NOTHING_FOUND
        for phrase in ("nothing there to find", "real, measured zero"):
            assert phrase not in context.lower()
