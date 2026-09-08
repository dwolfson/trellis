"""The envelope must carry the same feedback key the query path uses."""
import hashlib

from resource_explorer.facts import Envelope, _query_hash


def test_the_envelope_carries_a_feedback_key():
    """Without it, an answer composed from measurements cannot be rated at all —
    which is how the feedback corpus came to be silently biased toward typed
    questions: only the streaming path emitted a hash, so only typed answers
    got vote buttons."""
    env = Envelope(subject="egeria_python_git", question="What is Egeria?")
    assert env.as_dict()["query_hash"] == _query_hash("What is Egeria?")


def test_it_is_the_SAME_key_the_query_path_records_against():
    """Deliberately identical to web/routes/query.py's inline expression. A vote
    on one question must land in one place whether the answer came from RAG or
    from measurements — two hashes for one question would split the corpus by an
    implementation detail the person voting cannot see.

    Computed server-side for the same reason: two independent implementations
    would agree until some question contained a character they encoded
    differently, and then votes would silently land under a key nothing reads.
    """
    for q in ("What is Egeria?", "Does it replace something?", "naïve café — 日本語", ""):
        assert _query_hash(q) == hashlib.sha256(q.encode()).hexdigest()[:16], q


def test_an_unanswerable_envelope_still_gets_a_key():
    """"Nothing has measured this" is an answer, and a wrong one is worth
    flagging — arguably more than a merely unhelpful one."""
    env = Envelope(subject="x", question="Any known feedback?")
    assert env.as_dict()["answerable"] is False
    assert env.as_dict()["query_hash"]
