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

import glob
import os
from pathlib import Path

import pytest

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


def test_the_answer_line_carries_both_halves_of_the_value():
    """Reported twice. The second time (2026-09-01, "Is this repository
    actively maintained?") the reply was "389 commit(s) in the last 90
    days" — the justification, with the verdict nowhere on screen.

    `_r_maintained` returns {maintained, verdict, detail}. The renderer
    used `proseAnswer || summary`, so prose won outright and the scalars —
    the literal answer to a yes/no question — went into a collapsed
    Evidence block. Joining rather than choosing is the fix.

    Asserted by EXECUTING the extracted functions, not by grepping the
    source. The previous version of this test grepped for "<details>" and
    kept passing after that block was deleted, because a nearby COMMENT
    still mentioned it — a test satisfied by prose rather than behaviour.
    """
    node = _node_or_skip()
    out = _run_js(node, INDEX.read_text(), {
        "maintained": True, "verdict": "pass",
        "detail": "389 commit(s) in the last 90 days.",
    })
    assert "verdict: pass" in out, (
        f"the verdict is missing from the answer line: {out!r}"
    )
    assert "maintained: true" in out
    assert "389 commit(s)" in out, (
        f"the supporting prose was dropped instead: {out!r}"
    )


def test_a_fact_with_no_prose_is_unaffected():
    """12 of the 14 resolvers carry no prose at all, so `summary` already
    reached the answer line — which is why the bug looked fixed after the
    first pass. Joining must not change them."""
    node = _node_or_skip()
    assert _run_js(node, INDEX.read_text(), {"catalogued": True}) == "- catalogued: true"


def test_an_empty_value_still_yields_no_answer(): 
    """The no-answer path stays reachable: joining two empty halves must
    produce an empty string, not a stray separator, so the caller still
    falls through to the state line."""
    node = _node_or_skip()
    assert _run_js(node, INDEX.read_text(), {}) == ""


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



def _node_or_skip() -> str:
    """A node new enough to parse this file's JS, or skip.

    The functions under test are plain ES2020, but index.html at large uses
    `||=`, so a stale `node` on PATH can fail to parse a probe that embeds
    more than the extracted functions. Probing for capability rather than
    version keeps this honest about what it needs.
    """
    import shutil
    import subprocess

    candidates = [shutil.which("node")] + sorted(
        glob.glob("/opt/homebrew/opt/node@*/bin/node"), reverse=True
    )
    for exe in candidates:
        if not exe:
            continue
        probe = subprocess.run(
            [exe, "-e", "let a={}; a.x ??= 1; console.log('ok')"],
            capture_output=True, text=True,
        )
        if probe.returncode == 0 and "ok" in probe.stdout:
            return exe
    pytest.skip("no node available to execute the extracted renderer functions")


def _js_preamble(html: str) -> list[str]:
    """Every renderer function the answer line depends on.

    Built in one place because the first version had two runners each with
    their own list; adding _factFindingArrayKeys as a dependency of
    _summariseFactValue broke the runner that had not been updated. A shared
    preamble makes that drift impossible rather than merely unlikely.
    """
    return [
        "function _esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}",
        _fn(html, "_factProseKeys"),
        _fn(html, "_factAnswerText"),
        _fn(html, "_factFindingArrayKeys"),
        _const(html, "_FINDING_LINE_CAP"),
        _fn(html, "_factFindingLines"),
        _fn(html, "_summariseFactValue"),
        _fn(html, "_factValueLines"),
    ]


def _answer_expression(html: str) -> str:
    """The `const answerText = ...;` line as _renderEnvelopeMarkdown writes
    it, so the test runs the app's rule rather than a restatement of it."""
    fn = _fn(html, "_renderEnvelopeMarkdown")
    for line in fn.splitlines():
        if line.strip().startswith("const answerText"):
            return line.strip()
    raise AssertionError("no `const answerText = ...` line in _renderEnvelopeMarkdown")


def _run_js(node: str, html: str, value: dict, headline: str = "") -> str:
    """Build the answer line the renderer would build for `value`, by
    running the real extracted functions."""
    import json
    import subprocess
    import tempfile

    src = "\n".join([
        *_js_preamble(html),
        f"const value = {json.dumps(value)};",
        f"const f = {{value: value, headline: {json.dumps(headline)}}};",
        "const proseAnswer = _factAnswerText(value);",
        "const summary = _summariseFactValue(value);",
        # The renderer's OWN expression, lifted from its source -- not a
        # copy of it. A copy is how the first version of this test kept
        # passing when the renderer was reverted to `proseAnswer ||
        # summary`: it exercised the helpers and the test's own
        # transcription of the rule, never the rule the app runs.
        _answer_expression(html),
        # The rendered BLOCK, not just the answer line: since 2026-09-02 the
        # values render as bullets under the sentence rather than joined onto
        # it, so asserting they share one line would pin the old shape. What
        # must hold is that neither half is lost.
        "const _lines = []; if (answerText) _lines.push(answerText);",
        "_factValueLines(value).forEach(l => _lines.push('- ' + l));",
        "console.log(_lines.join('\\n'));",
    ])
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(src)
        path = fh.name
    try:
        res = subprocess.run([node, path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return res.stdout.strip()
    finally:
        os.unlink(path)

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


def _run_findings_js(node: str, html: str, value: dict) -> list[str]:
    """The sub-bullets _factFindingLines produces for `value`, plus the
    answer line, by running the real extracted functions."""
    import json
    import subprocess
    import tempfile

    src = "\n".join([
        *_js_preamble(html),
        f"const value = {json.dumps(value)};",
        "const f = {value: value, headline: ''};",
        "const proseAnswer = _factAnswerText(value);",
        "const summary = _summariseFactValue(value);",
        _answer_expression(html),
        "console.log(JSON.stringify([_summariseFactValue(value), ..._factFindingLines(value)]));",
    ])
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(src)
        path = fh.name
    try:
        res = subprocess.run([node, path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout.strip())
    finally:
        os.unlink(path)


def _const(html: str, name: str) -> str:
    start = html.index(f"const {name}")
    return html[start:html.index("\n", start)]


_CHAOSS = {"findings": [
    {"check_name": "elephant_factor", "label": "sole",
     "summary": "One contributor accounts for half of all commits."},
    {"check_name": "organizational_diversity", "label": "single",
     "summary": "1 organization(s) identifiable across 93% of commits."},
]}


class TestNestedObjects:
    """A value the renderer cannot shape is not a value that is not there.

    _summariseFactValue handled arrays, numbers, booleans and strings. A
    plain object matched none of them and fell through to nothing — silently.

    Found 2026-09-02 from the live app: "How much code is there? How
    complex?" answered `relationship_count: 437`. That was the only scalar in
    the value; `by_language` and `complexity_by_language` — the two fields
    that actually answer the question — were dropped on the floor. The
    complexity number had been persisted, verified in the metric, and
    reported as done. Verifying the metric was not verifying the answer.
    """

    def test_a_nested_object_is_rendered_not_dropped(self):
        node = _node_or_skip()
        out = _run_js(node, INDEX.read_text(), {
            "complexity_by_language": {"python": {"max": 120, "avg": 3.0}},
            "relationship_count": 437,
        })
        assert "python" in out and "max 120" in out, (
            f"the nested object was dropped; only scalars survived: {out!r}"
        )

    def test_a_dict_of_scalars_renders_its_keys(self):
        node = _node_or_skip()
        out = _run_js(node, INDEX.read_text(), {"by_language": {"python": 8632, "go": 22}})
        assert "python: 8632" in out

    def test_an_empty_object_adds_nothing(self):
        """An empty dict must not produce a stray `k: ` with nothing after
        it — absence renders as absence, not as a colon."""
        node = _node_or_skip()
        assert _run_js(node, INDEX.read_text(), {"complexity_by_language": {}}) == ""


class TestFindingsArrays:
    """A fact whose payload is a list of findings answered with its length.

    Measured across all 53 questions on egeria_python_git (2026-09-01):
    `chaoss_metrics`, `repo_classification` and `interface_surface` rendered
    "findings: 5 (growing, sole, …)" -- a count and two labels -- while the
    per-finding sentences the surveyors wrote went unshown. Not the
    verdict-behind-a-toggle bug (nothing was hidden; there was no toggle),
    but the same complaint: the reading was thinner than the measurement.
    """

    def test_each_finding_gets_its_own_sentence(self):
        node = _node_or_skip()
        out = _run_findings_js(node, INDEX.read_text(), _CHAOSS)
        body = " ".join(out)
        assert "One contributor accounts for half of all commits." in body
        assert "1 organization(s) identifiable across 93% of commits." in body
        assert "**sole**" in body and "**single**" in body

    def test_the_array_is_not_also_collapsed_to_a_count(self):
        """The two readers must agree. If _summariseFactValue did not skip
        these keys, the answer line would say "findings: 2" AND the same two
        findings would be listed underneath."""
        node = _node_or_skip()
        answer = _run_findings_js(node, INDEX.read_text(), _CHAOSS)[0]
        assert "findings: 2" not in answer, (
            f"the array is counted on the answer line as well as expanded: {answer!r}"
        )

    def test_an_array_of_plain_names_is_not_treated_as_findings(self):
        """`top_authors` is a list of names, not findings -- it must keep its
        existing count-plus-preview rendering, not become sub-bullets."""
        node = _node_or_skip()
        value = {"top_authors": [{"name": "Dan Wolfson"}, {"name": "Peter Coldicott"}]}
        out = _run_findings_js(node, INDEX.read_text(), value)
        assert "top_authors: 2 (Dan Wolfson, Peter Coldicott)" in out[0]
        assert len(out) == 1, f"a name list must not expand into bullets: {out!r}"

    def test_truncation_says_so(self):
        """The lesson from the 48,581-row secret scan the same day: a
        silently truncated list reads as a complete one. Known-negative --
        drop the "more not shown" line and this fails."""
        node = _node_or_skip()
        html = INDEX.read_text()
        cap = int(_const(html, "_FINDING_LINE_CAP").split("=")[1].strip(" ;"))
        many = {"findings": [
            {"label": f"f{i}", "summary": f"finding {i}"} for i in range(cap + 3)
        ]}
        out = _run_findings_js(node, html, many)
        assert any("3 more not shown" in line and f"{cap + 3} in total" in line
                   for line in out), (
            f"a truncated findings list must state what it omitted: {out!r}"
        )


class TestHeadlineLeadsTheAnswer:
    """A summary sentence, then the facts under it.

    Dan, 2026-09-02, shown a `·`-joined field dump:
    "that is not a good answer - should be a summary sentence and maybe some
    bullet points with the facts."

    The sentence was not invented for this. Every one of the 33 analyses with
    a results reader already defines a `headline_reader` — `api_structure`'s
    returns "8654 symbol(s) across 2 language(s)" — and NOTHING on the fact
    path called any of them. The chat rendered "relationship_count: 437"
    while a written sentence sat one function away.

    Order of preference, pinned here: a surveyor's own prose beats the
    analysis's generic headline, and both beat a bare field list.
    """

    def test_every_analysis_with_results_defines_a_headline(self):
        """The premise. If this ever stops holding, the renderer falls back
        to a field list for that analysis and someone should know why."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS)
        missing = [
            k for k, v in ANALYSIS_KINDS.items()
            if getattr(v, "results", None)
            and not getattr(v.results, "headline_reader", None)
        ]
        assert missing == [], f"analyses with results but no headline: {missing}"

    def test_the_fact_layer_reads_it(self):
        """Known-negative for the actual defect: the mechanism existed and
        was never called."""
        import inspect

        from resource_explorer import facts as facts_mod
        src = inspect.getsource(facts_mod.FactLayer)
        assert "headline_reader" in src, (
            "FactLayer never reads headline_reader, so the analysis's own "
            "summary sentence cannot reach the answer"
        )

    def test_prose_still_beats_the_headline(self):
        """A surveyor that wrote its own sentence must not be overridden by
        the generic one."""
        html = INDEX.read_text()
        fn = _fn(html, "_renderEnvelopeMarkdown")
        line = next(l for l in fn.splitlines() if "const answerText" in l)
        assert line.index("proseAnswer") < line.index("f.headline"), (
            f"headline must be the fallback, not the winner: {line.strip()!r}"
        )

    def test_the_values_render_as_separate_lines(self):
        """The bullets. _factValueLines splits the same extraction rather
        than re-parsing it — one extraction, two presentations."""
        node = _node_or_skip()
        html = INDEX.read_text()
        block = _run_js(node, html, {"a": 1, "b": 2})
        assert block.splitlines() == ["- a: 1", "- b: 2"], (
            f"each measured field belongs on its own line: {block!r}"
        )
        fn = _fn(html, "_factValueLines")
        assert "_summariseFactValue" in fn, (
            "_factValueLines must reuse _summariseFactValue rather than "
            "growing a second parser that can drift from it"
        )


class TestSummaryFailureCannotFailARun:
    """Building the display summary must never sink the run it describes.

    Found by the full suite, 2026-09-02. summarise_annotations did
    `a.annotation_type.value` unguarded; a malformed entry raised, the
    Analyses-card background thread crashed, and a run whose findings were
    computed and STORED reported "crashed" to the user. The work succeeded
    and the sentence about it did not — and the sentence won.
    """

    def test_malformed_entries_are_skipped_not_raised(self):
        from resource_explorer.surveyors.survey_report import summarise_annotations

        class _Ann:
            def __init__(self):
                self.annotation_type = type("T", (), {"value": "ClassificationAnnotation"})()
                self.analysis_step = "Step"
                self.summary = "a real one"

        out = summarise_annotations(["a string", None, 42, _Ann()])
        assert len(out) == 1, f"malformed entries must be skipped, not raised on: {out}"
        assert out[0]["summary"] == "a real one"

    def test_an_all_malformed_list_yields_nothing_rather_than_raising(self):
        from resource_explorer.surveyors.survey_report import summarise_annotations

        assert summarise_annotations(["a", "b"]) == []
