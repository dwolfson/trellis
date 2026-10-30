"""The words a person reads on a proposed quality check: a test type's short name, its parameters, and why a check could
not be established.

Three rules, from the new-user read of 2026-10-30:
 - a test type is named by TestGen's own `test_name_short` and `default_parm_prompts` (the vendored catalogue is the one
   source; nothing here is a hand-written list of test types);
 - a parameter with no value is absent, never "null": `None` is "not measured", not a setting;
 - a reason is reworded only when it matches a sentence this code knows; any other reason is returned as it was stored,
   never replaced by a guess.
"""
from __future__ import annotations

import json
import re

#: Parameters that are not a setting of the check (the profile the proposal was made from has its own column).
_NOT_A_SETTING = frozenset({"profile_surveyed_at"})
#: Parameters the catalogue's `default_parm_columns` does not list but every proposal carries.
_EXTRA_LABELS = {"severity": "severity"}
#: A comma list this long is a list of values (the placeholder list), not a single value that contains a comma.
_LIST_AT_LEAST = 10

#: The profile inputs a selection rule reads, in words. Any other input falls back to its name with spaces.
_INPUT_WORDS = {
    "frequent_patterns": "the common text patterns",
    "frequent_values": "the most frequent values",
    "date_months_present": "the months that hold dates",
    "date_weeks_present": "the weeks that hold dates",
    "percentile_25/50/75": "the 25th, 50th and 75th percentiles",
    "min_date": "the earliest date",
    "max_date": "the latest date",
}


def name_of_test_type(entry) -> str:
    """TestGen's short name for a test type ("Alpha Truncation"); "" when the catalogue has no such type."""
    return (entry.name_short or "") if entry is not None else ""


def _prompts(entry) -> dict[str, str]:
    columns, prompts = entry.default_parm_columns, [p.strip() for p in entry.default_parm_prompts.split(",")]
    labels = dict(zip(columns, (p.lower() for p in prompts), strict=True)) if len(columns) == len(prompts) else {}
    return {**_EXTRA_LABELS, **labels}


def _words(key: str) -> str:
    return key.replace("_", " ")


def parameter_items(entry, params: dict) -> list[dict]:
    """The parameters a check carries that have a value, each `{key, label, text}` or, for a long list of values,
    `{key, label, list, summary}`. A parameter whose value is None is left out: it was not measured."""
    labels = _prompts(entry) if entry is not None else dict(_EXTRA_LABELS)
    standard = (entry.default_parm_values or "") if entry is not None else ""
    out = []
    for key, value in (params or {}).items():
        if key in _NOT_A_SETTING or value is None or value == "":
            continue
        label = labels.get(key) or _words(key)
        if isinstance(value, str) and value.count(",") >= _LIST_AT_LEAST:
            items = [i.strip() for i in value.split(",")]
            origin = "standard " if value in standard else ""
            out.append({"key": key, "label": label, "list": items, "summary": f"{origin}{label} · {len(items)} values"})
        else:
            text = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            out.append({"key": key, "label": label, "text": text})
    return out


def _input_names(text: str) -> str:
    return ", ".join(_INPUT_WORDS.get(name.strip(), _words(name.strip())) for name in text.split(","))


_READS = re.compile(r"(?:its selection rule )?reads (?P<names>[^;]+?), which the profile did not measure")
_NEEDS = re.compile(r"needs (?P<names>[^;(]+?), which the profile does not take")


def _reads(match: re.Match) -> str:
    names = match.group("names")
    if names == "an input":
        return "needs an input that this profile did not collect (the rule does not say which)"
    return f"needs {_input_names(names)}, which this profile did not collect"


def reason_in_words(reason: str) -> str:
    """A not-established reason in a person's words: the missing input named, not the rule engine's sentence. A reason
    this code does not recognise comes back unchanged."""
    if not reason:
        return ""
    out = _READS.sub(_reads, reason)
    out = _NEEDS.sub(lambda m: f"needs {_input_names(m.group('names'))}, which this profile does not collect", out)
    out = out.replace("so its selection rule could not be evaluated", "so this check could not be evaluated")
    return out.replace("table type not inferred", "the table's type could not be worked out").replace(
        "type not inferred", "the column's type could not be worked out")
