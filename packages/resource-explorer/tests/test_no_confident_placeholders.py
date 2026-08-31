"""No annotation may publish a placeholder value at high confidence.

A step that reports "Primary language: Unknown" at confidence 95, or
"Database size: unknown" at confidence 100 with `size_bytes` defaulting to 0,
is making a confident claim about a thing it does not know. The reader has no
way to tell it apart from a real answer — which is this codebase's most
persistent bug shape, and the reason `result_status.py` and `step_outcome.py`
both exist.

Both real instances were found by a one-off sweep on 2026-08-31. This is that
sweep as a ratchet, because a one-off sweep answers about a moment: the next
placeholder is added by someone who has never read this file.

**Scope, stated so a later reader can judge whether it is enough.** It catches
a placeholder string reaching an annotation constructor at confidence >= 70,
either as a literal or through a local variable assigned `X or "unknown"` /
`.get(k, "unknown")`. It does NOT follow values across functions, through
attributes, or out of a registry row — a placeholder that arrives already
substituted is invisible here. It is a floor, not a proof.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

import resource_explorer

PLACEHOLDER = re.compile(
    r'^(unknown|n/?a|none|other|unspecified|undetermined|not[ _]available|tbd)$', re.I)

#: Below this, the annotation is already telling the reader not to trust it.
CONFIDENT = 70

#: Reviewed and accepted. Each entry is a placeholder that is a real value in
#: its own vocabulary, not a stand-in for a missing one.
ACCEPTED = {
    # SolutionPortDirection's own enum has Unknown(0) as a legitimate member —
    # "we could not determine the direction" is a direction the model names.
    ("persist.py", "Unknown"),
    ("mermaid.py", "Unknown"),
    # "no limit" — the absence of a cap, not the absence of a value.
    ("proposal.py", "none"),
    # `f"(last change {lens.date or 'unknown'})"` — prose INSIDE an explanation,
    # saying the document's last-change date could not be determined rather
    # than inventing one. The confidence attaches to the component-naming
    # count, not to the date. Saying "unknown" here is the honest behaviour the
    # rest of this check is trying to produce, not a violation of it.
    ("arch_lens.py", "unknown"),
}


def _placeholder_fallback(node: ast.AST) -> str | None:
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        last = node.values[-1]
        if isinstance(last, ast.Constant) and isinstance(last.value, str) \
                and PLACEHOLDER.match(last.value.strip()):
            return last.value
    if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get" \
            and len(node.args) == 2:
        default = node.args[1]
        if isinstance(default, ast.Constant) and isinstance(default.value, str) \
                and PLACEHOLDER.match(default.value.strip()):
            return default.value
    return None


def _confidence(call: ast.Call) -> int | None:
    for kw in call.keywords:
        if kw.arg == "confidence":
            return kw.value.value if isinstance(kw.value, ast.Constant) else None
    return 100          # the dataclass default


def _offences() -> list[str]:
    root = pathlib.Path(resource_explorer.__file__).parent
    out: list[str] = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            tainted: dict[str, str] = {}
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                        and isinstance(node.targets[0], ast.Name):
                    found = _placeholder_fallback(node.value)
                    if found:
                        tainted[node.targets[0].id] = found
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
                if not name.endswith("Annotation"):
                    continue
                conf = _confidence(node)
                if conf is None or conf < CONFIDENT:
                    continue
                for sub in ast.walk(node):
                    value = None
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                            and PLACEHOLDER.match(sub.value.strip()):
                        value = sub.value
                    elif isinstance(sub, ast.Name) and sub.id in tainted:
                        value = tainted[sub.id]
                    if value and (path.name, value) not in ACCEPTED:
                        out.append(f"{path.name}:{node.lineno} confidence={conf} "
                                   f"publishes placeholder {value!r}")
                        break
    return out


def test_no_placeholder_is_published_confidently():
    offences = _offences()
    assert not offences, (
        "An annotation publishes a placeholder at confidence >= "
        f"{CONFIDENT}:\n  " + "\n  ".join(sorted(set(offences))) +
        "\n\nReport the absence instead: drop the confidence to 0, say what was "
        "not measured, and omit the numeric field rather than defaulting it to a "
        "zero a reader cannot doubt. If the placeholder is a real value in its own "
        "vocabulary, add it to ACCEPTED with the reason."
    )


def test_the_check_can_actually_fail():
    """A ratchet nobody has seen fail is a ratchet nobody knows works.

    Both fixed instances are in git history; this reproduces the exact shape
    rather than trusting that the scan above would have caught them.
    """
    source = '''
def run(self):
    primary = row["primary_language"] or "Unknown"
    return [ClassificationAnnotation(summary=f"Primary language: {primary}",
                                     confidence=95, candidate_classifications=[primary])]
'''
    tree = ast.parse(source)
    fn = tree.body[0]
    tainted = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            found = _placeholder_fallback(node.value)
            if found:
                tainted[node.targets[0].id] = found
    assert tainted == {"primary": "Unknown"}, "the taint step must see the fallback"

    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", "").endswith("Annotation"))
    assert _confidence(call) == 95
    assert any(isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(call)), (
        "the placeholder must be seen reaching the annotation"
    )
