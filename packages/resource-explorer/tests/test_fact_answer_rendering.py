"""The chat answer to a catalogued question must lead with the answer.

Reported 2026-09-01 (Dan): clicking a question showed "Answering from 1
measurement(s)..." and no answer — "internal dialog from an agent ... but no
answer." The backend (`facts.py::FactLayer.answer()`) was already correct;
verified live against `GET /api/analyses/facts/egeria_git/answer` the same
day, which returned `concentration_detail`, a full sentence a surveyor wrote
itself ("One contributor accounts for half of all commits. Measured over the
491 commit(s) ..."). The UI discarded it in two places:

  * `_renderEnvelopeMarkdown` led with the process line ("Answering from N
    measurement(s)...") over a bullet that said only a state word
    ("measured"), with the sentence itself buried inside a collapsed
    <details> block.
  * `_summariseFactValue` then dropped it there too: its skip set literally
    contained `'detail'`, and its string branch kept only strings under 60
    characters — both filters hit exactly the fields carrying the prose
    (`detail`, `concentration_detail`, `measures_disagree`), and an array of
    named people (`top_authors`) collapsed to a bare count.

These tests pin the fix at the source level (the same style the rest of this
file's sibling tests use for index.html, since there is no JS test runner
wired into this suite) and, separately, the exact node invocation used to
verify the real rendered output against a live envelope — see the docstrings
below for the transcript.
"""
from __future__ import annotations

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"


def _fn(html: str, name: str) -> str:
    """Extract one top-level `function name(...) { ... }` body by brace
    matching, the same technique test_admin_feedback_view.py uses."""
    start = html.index(f"function {name}(")
    brace = html.index("{", start)
    depth = 1
    i = brace + 1
    while depth:
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
        i += 1
    return html[start:i]


def test_prose_fields_are_recognised_by_name():
    """detail / *_detail / measures_disagree are the fields a surveyor wrote
    itself (facts.py's `_r_community`, `project_commits`'s
    `concentration_detail`) — the exact set the bug's filters suppressed."""
    html = INDEX.read_text()
    fn = _fn(html, "_factProseKeys")
    assert "'detail'" in fn or '"detail"' in fn
    assert "endsWith" in fn and "_detail" in fn
    assert "measures_disagree" in fn


def test_answer_text_is_built_from_those_fields_only():
    html = INDEX.read_text()
    fn = _fn(html, "_factAnswerText")
    assert "_factProseKeys" in fn, "must reuse the same field set, not redefine it"


def test_the_envelope_renderer_promotes_prose_to_the_visible_line():
    """The whole bug: a fact's prose answer must appear on the line that is
    actually shown, not only inside a collapsed <details> block."""
    html = INDEX.read_text()
    fn = _fn(html, "_renderEnvelopeMarkdown")
    assert "_factAnswerText(f.value)" in fn, (
        "the renderer never calls _factAnswerText, so a fact's own prose "
        "answer is never promoted to the visible line"
    )
    # The promoted answer must land in a line pushed BEFORE the <details>
    # block, not only inside it.
    answer_push_idx = fn.index("answerText")
    details_idx = fn.index("<details>")
    assert answer_push_idx < details_idx, (
        "answerText is referenced only at or after the <details> block — "
        "it must be used to build the visible (non-collapsed) line first"
    )


def test_the_process_framing_is_a_footer_not_the_lead():
    """"Answering from N measurement(s)..." is provenance about the answer,
    not the answer. It must not be the first thing pushed for a known fact."""
    html = INDEX.read_text()
    fn = _fn(html, "_renderEnvelopeMarkdown")
    known_loop_idx = fn.index("known.forEach")
    footer_idx = fn.rindex("measurement(s) on")
    assert footer_idx > known_loop_idx, (
        "the measurement-count framing must appear after the per-fact loop "
        "(as a footer), not before it (as the lead)"
    )
    # And it must appear exactly once — not once as an intro AND once as a
    # footer, which would just add clutter back.
    assert fn.count("measurement(s) on") == 1


def test_evidence_no_longer_double_shows_or_drops_prose_fields():
    """`_summariseFactValue` used to hard-skip `'detail'` and cap strings at
    60 chars — the two filters that ate the answer. Now it must exclude
    prose fields dynamically (so they aren't duplicated under the promoted
    answer line) rather than unconditionally dropping a literal 'detail'
    key or truncating by length."""
    html = INDEX.read_text()
    fn = _fn(html, "_summariseFactValue")
    assert "'detail'" not in fn and '"detail"' not in fn, (
        "_summariseFactValue must not hard-code the literal key 'detail' — "
        "it should exclude prose fields via _factProseKeys(value) instead, "
        "so a value using a different *_detail field name isn't missed"
    )
    assert "_factProseKeys(value)" in fn
    assert "v.length < 60" not in fn, (
        "the blanket 60-char cutoff on string values is gone; only the "
        "prose fields (handled separately, in full, by _factAnswerText) "
        "needed the length exemption, so removing the cutoff here (rather "
        "than special-casing it) is the fix, not a regression risk — "
        "generic non-prose strings were the ones this cutoff protected "
        "against, and none of the value dicts observed carry long "
        "non-prose strings"
    )


def test_evidence_previews_named_items_in_arrays():
    """A bare "top_authors: 2" is strictly less informative than the field
    it summarises when the array holds named things."""
    html = INDEX.read_text()
    fn = _fn(html, "_summariseFactValue")
    assert "item.name" in fn, (
        "the array branch does not attempt a name preview, so a list like "
        "top_authors still collapses to a bare count"
    )


def test_the_no_answer_path_is_unchanged():
    """Promoting the answer path must not touch how "never measured" and
    "measured and found nothing" are told apart, or how a fully-unanswerable
    question is phrased."""
    html = INDEX.read_text()
    fn = _fn(html, "_renderEnvelopeMarkdown")
    assert "env.answerable" in fn and "I can't answer that yet" in fn
    assert "Not everything is known" in fn
    state_text = _fn_const(html, "_FACT_STATE_TEXT")
    assert "nothing_found" in state_text and "never_run" in state_text
    assert "measured zero, not a gap" in state_text
    assert "never run here" in state_text


def _fn_const(html: str, name: str) -> str:
    start = html.index(f"const {name}")
    end = html.index("};", start) + 2
    return html[start:end]


# ── Live verification transcript (not re-run in CI; recorded here for the
# record, since it needs a running server and the vendored marked.js) ───────
#
# The three functions above (`_factProseKeys`, `_factAnswerText`,
# `_renderEnvelopeMarkdown`, `_summariseFactValue`) were extracted from
# index.html by brace-matching and run under
# /Users/dwolfson/.nvm/versions/node/v18.16.1/bin/node against the real
# response of:
#
#     GET http://127.0.0.1:8810/api/analyses/facts/egeria_git/answer\
#         ?question=Who%20maintains%20this%20repository%3F
#
# which returned one `project_commits` fact carrying `concentration_detail`.
# The resulting markdown (this is the literal stdout, not a description):
#
#     - ✓ **project_commits**: One contributor accounts for half of all
#     commits. Measured over the 491 commit(s) recorded between 2026-05-12
#     and 2026-08-31, by 3 author(s); the single largest wrote 64%.
#
#       <span class="text-slate-500">measured</span>
#
#       <details><summary class="cursor-pointer text-slate-500">Evidence</summary>
#
#       people: 2 · commit_identities: 3 · commits: 491 · top_authors: 2
#       (Mandy Chessell, Karth) · concentration: sole
#       </details>
#
#     _Answered from 1 measurement(s) on **egeria_git**._
#
# The maintainer's name and the actual finding are both now on a visible
# line; the measurement count is a footer, not the lead. A synthetic
# unanswerable envelope and a synthetic known_count=0/never_run envelope were
# run the same way and were unchanged from before this fix:
#
#     **I can't answer that yet.**
#
#     No analysis in the catalog answers this question.
#
#     **Not everything is known.** `security_scan` never run here.
#
#     _Re-run `security_scan` to refresh this._
#
#     _Answered from 0 measurement(s) on **some_repo**._
