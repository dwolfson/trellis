"""BRIEF-KEYS-AND-ACTIVITY-CLOBBER.md §D: `facts.py`'s `_renders_text` is a
Python hand-mirror of `readEnvelope`'s rendering rungs in
`web/static/next/app.js` (now split into `web/static/next/envelope.js`, see
that module's own header comment). There is no shared source between the two
implementations, and they have drifted twice already — once the day
`_renders_text` was written, and again in Slice 21a (the Level column
shipped, `_headline_for` never read it, and container-level questions ticked
✓ on resource-level sentences for two days, caught at a live gate, not by a
test). Every pre-existing test asserts only the Python side.

This file feeds the SAME corpus of fact envelopes to both implementations,
via node (the pattern `test_next_journal_fidelity.py` and
`test_next_enrichment_persistence.py` already establish for this repo):
copy the target `.js` file to a `.mjs` sibling in `tmp_path` so node treats it
as an ES module (`TestTheFormatter._run` in test_next_journal_fidelity.py),
and extract a function's own source text out of app.js by string-slicing
between its declaration and the next top-level declaration
(`_extract` in test_next_enrichment_persistence.py) for the handful of small
helpers (`esc`, `tnum`, `isFullyAnswered`) that stayed in app.js rather than
moving to envelope.js, since app.js itself cannot be imported whole under
node (it runs `Auth.init(start)` and reads `document.getElementById(...)` at
module top level, both of which throw with no DOM/no auth.js present).

Two things are cross-checked, per corpus case:

  (a) renders-or-not — Python's `FactLayer._renders_text(fact)` against
      whether JS's `readEnvelope(...).answer` comes out non-empty for an
      envelope holding exactly that one fact. `_renders_text` does not
      itself consult `fact.is_known` (`test_slice17c_renderable_answer_
      gate.py`'s `TestRendersText` calls it directly on facts of any state,
      including ones that are not "known"), and neither does the per-fact
      branch inside `readEnvelope`'s own sentence loop -- only the OUTER
      `known = facts.filter(f.is_known)` filter (which both `_check_level`
      and `readEnvelope` apply before ever reaching this per-fact logic)
      does. To compare the two primitives on equal footing, the JS side's
      envelope forces `is_known: true` on the single fact regardless of its
      state, mirroring how `test_slice17c`'s Python tests call
      `_renders_text` directly, bypassing the outer filter, on facts of
      every state.

  (b) the level verdict -- Python's `FactLayer._check_level(env, question)`
      sets `env.level_mismatch`/`env.answerable`; JS's `isFullyAnswered(env)`
      is the one sanctioned way to turn that into "does this get a
      checkmark" (its own docstring: "callers that count or gate on
      'answered' must use this, not `env.answerable` alone"). Here `is_known`
      is NOT forced -- this half exercises the real pipeline shape, where an
      unrenderable fact of a not-known state never reaches `_check_level`'s
      own `known` filter either.

The corpus spans the five fact states BRIEF-KEYS-AND-ACTIVITY-CLOBBER.md §D
names (measured, nothing-found, not-established, no-reader, measured-within-
credential-scope) × with/without a headline × the four question levels
(resource, container, member, field) = 40 cases, plus four extra cases that
exercise `readEnvelope`'s rung 2 (prose) and rung 3 (scalar fallback, and the
db_resilience-shaped nested-dict-only value that rung 3 can never render --
`test_slice17c_renderable_answer_gate.py`'s own trigger) at resource level,
where headline alone would not have distinguished them. 44 total. The count
is asserted directly so a shrunk corpus — someone "simplifying" the loop and
quietly dropping a dimension — fails loudly rather than silently reducing
coverage.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from resource_explorer.facts import Envelope, Fact, FactLayer, clear_target_shape_cache
from resource_explorer.surveyors.result_status import (
    MEASURED,
    MEASURED_WITHIN_CREDENTIAL_SCOPE,
    NO_READER,
    NOT_ESTABLISHED,
    NOTHING_FOUND,
)

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"
APP_JS = NEXT / "app.js"
ENVELOPE_JS = NEXT / "envelope.js"
FORMAT_JS = NEXT / "format.js"

STATES = [MEASURED, NOTHING_FOUND, NOT_ESTABLISHED, NO_READER, MEASURED_WITHIN_CREDENTIAL_SCOPE]
LEVELS = ["resource", "container", "member", "field"]

ANALYSIS_ID = "cross_check_analysis"


def _extract(src: str, signature: str) -> str:
    """The text of one top-level function, from its `function`/`export
    function` line up to (not including) the next top-level `function`
    declaration. Same helper as test_next_enrichment_persistence.py's."""
    start = src.index(signature)
    candidates = []
    for marker in ("\nfunction ", "\nexport function ", "\nconst ", "\nasync function "):
        try:
            candidates.append(src.index(marker, start + len(signature)))
        except ValueError:
            pass
    end = min(candidates)
    return src[start:end]


def _grid_corpus() -> list[dict]:
    """The 5 states x 2 headline states x 4 levels grid the brief asks for."""
    cases = []
    for state in STATES:
        for has_headline in (True, False):
            for level in LEVELS:
                cases.append({
                    "name": f"{state}/{'headline' if has_headline else 'no-headline'}/{level}",
                    "state": state,
                    "headline": "A written summary sentence." if has_headline else "",
                    "value": {},
                    "level": level,
                })
    return cases


def _rung_coverage_corpus() -> list[dict]:
    """Rung 2 (prose) and rung 3 (scalar / nested-dict-only) cases, at
    resource level, where headline presence alone does not distinguish the
    rungs `readEnvelope` and `_renders_text` both walk through in order."""
    return [
        {
            "name": "measured/prose-only/resource",
            "state": MEASURED, "headline": "",
            "value": {"detail": "Some real prose, no headline."},
            "level": "resource",
        },
        {
            "name": "measured/scalar-only/resource",
            "state": MEASURED, "headline": "",
            "value": {"table_count": 56},
            "level": "resource",
        },
        {
            "name": "measured/nested-dicts-only-renders-nothing/resource",
            # The exact db_resilience shape from test_slice17c_renderable_
            # answer_gate.py: rung 3 skips every list/object field by
            # design, so this must render NOTHING on both sides.
            "state": MEASURED, "headline": "",
            "value": {
                "replication": {"is_in_recovery": False, "replicas": []},
                "wal_archiving": {"archive_mode": "off"},
            },
            "level": "resource",
        },
        {
            "name": "nothing_found/prose-only/resource",
            # NOTHING_FOUND's own special case only fires when there is
            # NEITHER headline NOR prose -- prose present must win instead
            # of the synthesized "ran and found nothing" sentence.
            "state": NOTHING_FOUND, "headline": "",
            "value": {"summary": "Ran; genuinely nothing matched the filter."},
            "level": "resource",
        },
    ]


def _corpus() -> list[dict]:
    return _grid_corpus() + _rung_coverage_corpus()


@pytest.fixture(autouse=True)
def _clear_shape_cache():
    clear_target_shape_cache()
    yield
    clear_target_shape_cache()


def _fact_layer(monkeypatch) -> FactLayer:
    monkeypatch.setattr(
        "resource_explorer.surveyors.analysis_catalog_reader.get_analyses",
        lambda resource_type, **kwargs: [{"id": ANALYSIS_ID, "target_shape": "whole_resource_only"}],
    )
    fl = FactLayer.__new__(FactLayer)  # skip __init__ -- no registry needed
    fl.resource_type = "database"
    # `_check_level` reaches `_level_specific_headline_exists` -> `_map(...)`
    # for any headlined sub-resource-level case, which reads `_maps_cache`
    # directly -- `__init__` sets it and `__new__` skips `__init__`.
    fl._maps_cache = {}
    return fl


def _python_side(monkeypatch, cases: list[dict]) -> list[dict]:
    """One fresh `FactLayer`/`Envelope` per case -- `_check_level` mutates
    the envelope it is given, so cases must not share one."""
    out = []
    for case in cases:
        fl = _fact_layer(monkeypatch)
        fact = Fact(analysis_id=ANALYSIS_ID, state=case["state"],
                    value=dict(case["value"]), headline=case["headline"])
        renders = fl._renders_text(fact)

        env = Envelope(subject="corpus_test")
        env.facts = [fact]
        fl._check_level(env, {"levels": [case["level"]]})
        fully_answered = bool(env.answerable and not env.level_mismatch)

        out.append({
            "name": case["name"],
            "renders": renders,
            "fully_answered": fully_answered,
            "answerable": env.answerable,
            "level_mismatch": env.level_mismatch,
            "fact_as_dict": fact.as_dict(),
        })
    return out


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
class TestRendersTextMatchesReadEnvelope:
    def _js_side(self, py_side: list[dict], tmp_path: Path) -> list[dict]:
        # envelope.js imports whenMs from format.js by absolute /static/...
        # path -- rewritten to a local sibling import so node can resolve it,
        # same trick test_next_enrichment_persistence.py uses for its own
        # format.js copy.
        format_mjs = tmp_path / "format.mjs"
        format_mjs.write_text(FORMAT_JS.read_text(encoding="utf-8"), encoding="utf-8")
        envelope_src = ENVELOPE_JS.read_text(encoding="utf-8")
        envelope_src = envelope_src.replace("/static/next/format.js", "./format.mjs")
        envelope_mjs = tmp_path / "envelope.mjs"
        envelope_mjs.write_text(envelope_src, encoding="utf-8")

        app_src = APP_JS.read_text(encoding="utf-8")
        esc_fn = _extract(app_src, "export function esc(s) {")
        tnum_fn = _extract(app_src, "export function tnum(html) {")
        is_fully_answered_fn = _extract(app_src, "function isFullyAnswered(env) {")

        # Everything the JS side needs per case: the fact (as the wire
        # format actually serializes it), and the two Envelope-level fields
        # `_check_level` computed (`answerable`, `level_mismatch`) -- these
        # are Python's own verdict, carried across so JS's `isFullyAnswered`
        # can be checked against exactly what Python decided, not against a
        # value JS re-derives on its own (it has no way to: computing
        # `level_mismatch` from scratch needs the catalog's target_shape
        # data, which only facts.py reads).
        cases_json = json.dumps([
            {
                "name": p["name"],
                "fact": p["fact_as_dict"],
                "answerable": p["answerable"],
                "level_mismatch": p["level_mismatch"],
            }
            for p in py_side
        ])

        script = f"""
import {{ readEnvelope }} from './envelope.mjs';
{esc_fn.replace('export function esc', 'function esc')}
{tnum_fn.replace('export function tnum', 'function tnum')}
{is_fully_answered_fn}

const cases = {cases_json};
const out = cases.map((c) => {{
  // (a) renders-or-not: is_known forced true so this exercises the SAME
  // state-agnostic per-fact predicate `_renders_text` is (see module
  // docstring) -- the outer known-filter is a separate, already-tested gate.
  const rendersEnv = {{ facts: [{{ ...c.fact, is_known: true }}] }};
  const lines = readEnvelope({{ question: c.name }}, rendersEnv, esc, tnum);
  const renders = !!(lines.answer && lines.answer.length);

  // (b) the level verdict: Python's own answerable/level_mismatch, read
  // back through the one sanctioned JS accessor for "does this get a tick".
  const levelEnv = {{ answerable: c.answerable, level_mismatch: c.level_mismatch }};
  return {{ name: c.name, renders, fullyAnswered: isFullyAnswered(levelEnv) }};
}});
console.log(JSON.stringify(out));
"""
        script_path = tmp_path / "run.mjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(["node", str(script_path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def test_corpus_size_is_the_documented_44(self):
        """A shrunk corpus must fail loudly, not silently cover less."""
        assert len(_corpus()) == 44

    def test_python_and_js_agree_on_every_case(self, monkeypatch, tmp_path):
        cases = _corpus()
        py_side = _python_side(monkeypatch, cases)
        js_side = self._js_side(py_side, tmp_path)
        assert len(js_side) == len(py_side) == len(cases)

        failures = []
        for case, p, j in zip(cases, py_side, js_side):
            assert j["name"] == case["name"] == p["name"]
            if p["renders"] != j["renders"]:
                failures.append(
                    f"{case['name']}: renders-or-not disagreement -- "
                    f"python={p['renders']!r} js={j['renders']!r}")
            if p["fully_answered"] != j["fullyAnswered"]:
                failures.append(
                    f"{case['name']}: level-verdict disagreement -- "
                    f"python={p['fully_answered']!r} js={j['fullyAnswered']!r}")
        assert not failures, "\n".join(failures)
