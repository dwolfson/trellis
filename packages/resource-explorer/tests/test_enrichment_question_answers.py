"""The Enrichment context can hold answers to the catalog's Human-Supplied
questions.

Seven catalog questions are answered by a person rather than a survey -- do we
already support these dependencies, what does it cost to run, do we have the
skills, does it fit our monitoring / security / governance, does it fit or
extend the estate. Before 2026-09-11 there was nowhere to put those answers:
ContextData held environment, sensitivity, backup status, geographic location,
steward, owner, purpose and notes, and **none of those eight appears in the
question catalog at all**. The two sets are disjoint, which is what says they
are different things -- a catalog-time asset record on one side, the catalog's
own questions on the other.
"""
from __future__ import annotations

from resource_explorer.web.routes.context import ContextData


class TestQuestionAnswersOnContext:
    def test_defaults_to_empty_so_existing_callers_are_unchanged(self):
        """The field is additive. Every caller that never heard of it must
        keep working, and must not acquire a non-empty value by surprise."""
        assert ContextData().model_dump()["question_answers"] == {}

    def test_an_answer_round_trips_through_a_json_blob(self):
        """Storage is registry.save_context's `context_json` TEXT column, so
        the model has to survive json.dumps/loads with nothing lost. No
        schema change was needed precisely because of this."""
        import json
        data = ContextData(**{
            "environment": "research",
            "question_answers": {
                "do-we-have-the-skills-to-support-its-use": {
                    "question": "Do we have the skills to support its use?",
                    "answer": "Two Python engineers; nobody on the Java side.",
                    "answered_at": "2026-09-11T02:40:00Z",
                },
            },
        })
        restored = json.loads(json.dumps(data.model_dump()))
        answer = restored["question_answers"]["do-we-have-the-skills-to-support-its-use"]
        assert answer["answer"].startswith("Two Python engineers")
        assert restored["environment"] == "research", "fixed fields must survive alongside"

    def test_the_question_text_is_stored_not_only_used_as_the_key(self):
        """The catalog has no stable question id, so the key is a slug of the
        wording. Reword the CSV and the slug changes, orphaning the answer.

        Keeping the text ON the answer makes that recoverable and visible
        rather than silent -- an orphan still says which question it answered.
        This asserts the property that makes that possible; a stable id in the
        catalog would be the real fix.
        """
        data = ContextData(**{"question_answers": {"some-slug": {
            "question": "Do we have the skills to support its use?",
            "answer": "No.",
            "answered_at": "2026-09-11T02:40:00Z",
        }}})
        held = data.model_dump()["question_answers"]["some-slug"]
        assert held["question"] == "Do we have the skills to support its use?"


class TestTheTwoFieldSetsAreDisjoint:
    def test_no_fixed_context_field_is_a_catalog_question(self):
        """The evidence that these are different things. If a future change
        moves environment/sensitivity into the catalog, this fails and the
        split needs rethinking rather than quietly doubling up."""
        from resource_explorer.surveyors.question_catalog_reader import get_questions
        questions = " ".join(q["question"].lower() for q in get_questions("repo"))
        for field_name in ("environment", "sensitivity", "backup", "geographic"):
            assert field_name not in questions, (
                f"{field_name!r} now appears in the question catalog; the "
                "context form and the catalog have started to overlap"
            )
