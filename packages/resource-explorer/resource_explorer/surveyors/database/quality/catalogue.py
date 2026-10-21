"""The vendored quality-check catalogue: loading it, its selection rules as Python, and rendering its SQL.

The catalogue is DataKitchen TestGen's test-type YAML, copied unchanged into
`configdata/quality/testgen/` (PROVENANCE.md). Two parts of each file are used, in two different ways:

- **`selection_criteria`** is Postgres SQL over TestGen's own `profile_results`. RE's registry can be SQLite,
  so these fragments are ported to Python predicates (`PREDICATES`). Each predicate carries the SHA-256 of the
  fragment it was ported from; `tests/test_quality_catalogue.py` fails when the vendored text no longer
  matches, so adopting an upstream change forces a re-port instead of a silent divergence. The predicates use
  SQL's three-valued logic (`_and`, `_not`, `_cmp`): a rule that SQL would evaluate to NULL returns `None`
  here, which the propose step records as `not_established`, never as "no".
- **The Postgres `cat_test_conditions` entry** (`measure`, `test_operator`, `test_condition`) runs verbatim
  against the surveyed database, through `render_measure`, which validates every parameter by type before it
  is substituted. Nothing read from a person or from Egeria is ever executed as SQL.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOGUE_DIR = Path(__file__).resolve().parents[3] / "configdata" / "quality" / "testgen"
TEST_TYPES_DIR = CATALOGUE_DIR / "test_types"
POSTGRES_DIR = CATALOGUE_DIR / "postgresql"

#: The upstream commit the catalogue was copied from (PROVENANCE.md). Part of every proposal's catalogue_ref.
UPSTREAM_COMMIT = "3606859c"

#: Slice 1's seven test types. Recency is slice 2 (its selection rule reads functional_data_type, which slice 1
#: does not infer, so the rule would silently propose nothing).
SLICE_1_TEST_TYPES = (
    "Missing_Pct", "Required", "Required_No_Placeholder", "Unique", "Future_Date", "Min_Date", "Row_Ct_Pct",
)

#: The test type RE proposes on its own initiative: TestGen has no selection rule for it (manual-only there).
RE_PROPOSED = frozenset({"Row_Ct_Pct"})

#: TestGen's default_severity -> the ODCS/Egeria severity word a rule carries.
SEVERITY = {"Fail": "error", "Warning": "warning", "Log": "info"}

#: TestGen's FAIL-WHEN operator -> the ODCS MUST-BE operator (its inverse), as Publish will write it (design §7).
MUST_BE = {
    ">": "mustBeLessOrEqualTo",
    ">=": "mustBeLessThan",
    "<": "mustBeGreaterOrEqualTo",
    "<=": "mustBeGreaterThan",
    "=": "mustNotBe",
    "<>": "mustBe",
}

_FAIL_WHEN: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq, "<>": operator.ne,
}


@dataclass(frozen=True)
class TestType:
    """One vendored test type, as slice 1 reads it."""

    __test__ = False  # not a pytest test class, despite the name

    test_type: str
    id: str
    name_short: str
    description: str
    usage_notes: str
    dimension: str
    default_severity: str
    measure_uom: str
    test_scope: str
    selection_criteria: str | None
    default_parm_columns: tuple[str, ...]
    default_parm_values: str | None
    measure: str
    test_operator: str
    test_condition: str

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.default_severity, "error")

    @property
    def origin(self) -> str:
        """`re` for a check RE proposes on its own initiative, `vendored` for one the catalogue's rule selects."""
        return "re" if self.test_type in RE_PROPOSED else "vendored"

    @property
    def is_table_check(self) -> bool:
        return self.test_scope == "table"


def sha256_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _postgres_condition(raw: dict) -> dict:
    for cond in raw.get("cat_test_conditions") or []:
        if cond.get("sql_flavor") == "postgresql":
            return cond
    raise ValueError(f"{raw.get('test_type')}: no postgresql cat_test_conditions entry")


def parse_test_type(raw: dict) -> TestType:
    cond = _postgres_condition(raw)
    return TestType(
        test_type=raw["test_type"],
        id=str(raw["id"]),
        name_short=raw.get("test_name_short") or raw["test_type"],
        description=raw.get("test_description") or "",
        usage_notes=raw.get("usage_notes") or "",
        dimension=raw.get("dq_dimension") or "",
        default_severity=raw.get("default_severity") or "Fail",
        measure_uom=raw.get("measure_uom") or "",
        test_scope=raw.get("test_scope") or "column",
        selection_criteria=raw.get("selection_criteria"),
        default_parm_columns=tuple(c.strip() for c in (raw.get("default_parm_columns") or "").split(",") if c.strip()),
        default_parm_values=raw.get("default_parm_values"),
        measure=cond["measure"],
        test_operator=cond["test_operator"],
        test_condition=cond["test_condition"],
    )


def read_raw(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("test_types") or {}


@lru_cache(maxsize=1)
def load_catalogue() -> dict[str, TestType]:
    """{test_type: TestType} for slice 1, read from the vendored YAML."""
    return {name: parse_test_type(read_raw(TEST_TYPES_DIR / f"{name}.yaml")) for name in SLICE_1_TEST_TYPES}


def catalogue_ref(test_type: TestType) -> str:
    """Where a proposal's rule came from: the upstream commit and the SHA-256 of the selection fragment (or of
    the Postgres measure, for a check RE proposes itself)."""
    if test_type.selection_criteria is not None:
        return f"vendored-catalog@{UPSTREAM_COMMIT}:{test_type.test_type}:selection_criteria:sha256:" \
               f"{sha256_text(test_type.selection_criteria)}"
    return f"vendored-catalog@{UPSTREAM_COMMIT}:{test_type.test_type}:measure:sha256:{sha256_text(test_type.measure)}"


# ── selection rules: SQL three-valued logic, then the seven ports ────────────────────────────────────────────

def _and(*values: bool | None) -> bool | None:
    """SQL AND: FALSE if any operand is FALSE, else NULL if any is NULL, else TRUE."""
    if any(v is False for v in values):
        return False
    if any(v is None for v in values):
        return None
    return True


def _not(value: bool | None) -> bool | None:
    return None if value is None else not value


def _coalesce(*values):
    return next((v for v in values if v is not None), None)


def _cmp(left, op: str, right) -> bool | None:
    """SQL comparison: NULL when either side is NULL."""
    if left is None or right is None:
        return None
    return _FAIL_WHEN[op](left, right)


@dataclass(frozen=True)
class Predicate:
    """A ported selection rule: the fragment's pinned hash, the profile inputs it reads, and the port."""

    fragment_sha256: str | None
    inputs: tuple[str, ...]
    rule: Callable[[dict], bool | None]

    def evaluate(self, profile: dict) -> bool | None:
        return self.rule(profile)

    def null_inputs(self, profile: dict) -> list[str]:
        """The inputs this rule reads that are NULL in `profile`; `sample_ratio` is read by IS NULL, so its NULL
        is a value, never a missing input."""
        return [name for name in self.inputs if name != "sample_ratio" and profile.get(name) is None]


def _p(row: dict, name: str):
    return row.get(name)


# Each rule below is the vendored fragment, term for term. The fragment is quoted above its port.
PREDICATES: dict[str, Predicate] = {
    # record_ct <> value_ct
    "Missing_Pct": Predicate(
        "788cb3933546b28f0d8b9d8bcfc9a15aa0a86b8cae26289429ed41814383193b",
        ("record_ct", "value_ct"),
        lambda p: _cmp(_p(p, "record_ct"), "<>", _p(p, "value_ct")),
    ),
    # record_ct = value_ct AND record_ct > 10 AND NOT COALESCE(general_type = 'A' AND zero_length_ct = 0
    #   AND filled_value_ct = 0 AND sample_ratio IS NULL, FALSE)
    "Required": Predicate(
        "8ec541f833fe241959272d67e56abf21531ba64ed06b8396be9fb9dde0f43894",
        ("record_ct", "value_ct", "general_type", "zero_length_ct", "filled_value_ct", "sample_ratio"),
        lambda p: _and(
            _cmp(_p(p, "record_ct"), "=", _p(p, "value_ct")),
            _cmp(_p(p, "record_ct"), ">", 10),
            _not(_coalesce(_and(
                _cmp(_p(p, "general_type"), "=", "A"),
                _cmp(_p(p, "zero_length_ct"), "=", 0),
                _cmp(_p(p, "filled_value_ct"), "=", 0),
                _p(p, "sample_ratio") is None,
            ), False)),
        ),
    ),
    # record_ct = value_ct AND record_ct > 10 AND general_type = 'A' AND zero_length_ct = 0
    #   AND filled_value_ct = 0 AND sample_ratio IS NULL
    "Required_No_Placeholder": Predicate(
        "de6007a4f24be5371ba244212e6201bac5ec713b5d66208f02c4ad0487107bba",
        ("record_ct", "value_ct", "general_type", "zero_length_ct", "filled_value_ct", "sample_ratio"),
        lambda p: _and(
            _cmp(_p(p, "record_ct"), "=", _p(p, "value_ct")),
            _cmp(_p(p, "record_ct"), ">", 10),
            _cmp(_p(p, "general_type"), "=", "A"),
            _cmp(_p(p, "zero_length_ct"), "=", 0),
            _cmp(_p(p, "filled_value_ct"), "=", 0),
            _p(p, "sample_ratio") is None,
        ),
    ),
    # record_ct > 500 and record_ct = distinct_value_ct and value_ct > 0
    "Unique": Predicate(
        "d1ffee508acd1cbb2349028da390e0acebf5c2023e74f5f782f3ad01a9f36e72",
        ("record_ct", "distinct_value_ct", "value_ct"),
        lambda p: _and(
            _cmp(_p(p, "record_ct"), ">", 500),
            _cmp(_p(p, "record_ct"), "=", _p(p, "distinct_value_ct")),
            _cmp(_p(p, "value_ct"), ">", 0),
        ),
    ),
    # general_type='D'AND future_date_ct = 0
    "Future_Date": Predicate(
        "bbc5d8abe13875e63d7e0179eb54ea7c1b3563c867da38b9b35c6990b7300bba",
        ("general_type", "future_date_ct"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "D"), _cmp(_p(p, "future_date_ct"), "=", 0)),
    ),
    # general_type='D'and min_date IS NOT NULL AND distinct_value_ct > 1
    "Min_Date": Predicate(
        "81422ad9c3f37e2ff7697c5772ca740da32ab43649ae5f085578f1e1661bddc4",
        ("general_type", "min_date", "distinct_value_ct"),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "D"),
            _p(p, "min_date") is not None,
            _cmp(_p(p, "distinct_value_ct"), ">", 1),
        ),
    ),
    # No fragment: TestGen leaves Row_Ct_Pct manual-only. RE's own rule, for every table with record_ct > 0.
    "Row_Ct_Pct": Predicate(
        None,
        ("record_ct",),
        lambda p: _cmp(_p(p, "record_ct"), ">", 0),
    ),
}

#: Inputs whose NULL is a real value rather than a missing measure: min_date is read by IS NOT NULL.
_NULL_IS_A_VALUE = {"Min_Date": {"min_date"}}


def not_established_inputs(test_type: str, profile: dict) -> list[str]:
    """The NULL inputs that made `test_type`'s rule NULL, for the not_established reason."""
    skip = _NULL_IS_A_VALUE.get(test_type, set())
    return [n for n in PREDICATES[test_type].null_inputs(profile) if n not in skip]


# ── default parameters ─────────────────────────────────────────────────────────────────────────────────────────

class ParameterError(ValueError):
    """A parameter that cannot be used: the check is not_established, with this message as the reason."""


def _split_sql_list(text: str) -> list[str]:
    """Split `default_parm_values` on commas outside single-quoted strings ('' is an escaped quote)."""
    items, current, in_quote, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if in_quote and i + 1 < len(text) and text[i + 1] == "'":
                current.append("''")
                i += 2
                continue
            in_quote = not in_quote
        if ch == "," and not in_quote:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    items.append("".join(current).strip())
    return items


_CAST = re.compile(r"::[A-Za-z_]+(\(\d+\))?$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _default_value(expr: str, profile: dict):
    """One `default_parm_values` expression: a profile column, a quoted literal, or a number (casts dropped)."""
    expr = _CAST.sub("", expr.strip())
    if expr.startswith("'") and expr.endswith("'") and len(expr) >= 2:
        return expr[1:-1].replace("''", "'")
    if _NUMBER.match(expr):
        return int(expr) if "." not in expr else float(expr)
    if _IDENT.match(expr):
        if expr not in profile:
            raise ParameterError(f"default parameter refers to {expr!r}, which the value profile does not have")
        return profile.get(expr)
    raise ParameterError(f"default parameter expression {expr!r} is not one this port understands")


#: catalogue column name -> the params_json key it fills.
_PARAM_KEYS = {
    "baseline_ct": "baseline_ct", "baseline_value_ct": "baseline_value_ct",
    "baseline_value": "baseline_value", "threshold_value": "threshold_value",
}


def default_params(test_type: TestType, profile: dict, row_ct_pct_threshold: float) -> dict:
    """The parameters a proposal starts with: the catalogue's defaults evaluated against the profile, plus the
    severity. Raises ParameterError when a default reads a profile measure that is NULL."""
    params: dict[str, Any] = {"baseline_ct": None, "baseline_value_ct": None, "baseline_value": None,
                              "threshold_value": None, "severity": test_type.severity}
    if test_type.test_type == "Row_Ct_Pct":
        # TestGen has no defaults for it: RE's baseline is the measured count, the threshold a setting.
        params["baseline_ct"] = profile.get("record_ct")
        params["threshold_value"] = row_ct_pct_threshold
    else:
        values = _split_sql_list(test_type.default_parm_values or "")
        if len(values) != len(test_type.default_parm_columns):
            raise ParameterError(f"{test_type.test_type}: {len(test_type.default_parm_columns)} default parameter "
                                 f"column(s) but {len(values)} value(s)")
        for column, expr in zip(test_type.default_parm_columns, values):
            if column not in _PARAM_KEYS:
                raise ParameterError(f"{test_type.test_type}: default parameter column {column!r} is not supported")
            params[_PARAM_KEYS[column]] = _default_value(expr, profile)
    missing = [k for k in _required_params(test_type) if params.get(k) is None]
    if missing:
        raise ParameterError(f"default {', '.join(missing)} would come from a measure that is NULL in the profile")
    return params


# ── rendering the target-side SQL ──────────────────────────────────────────────────────────────────────────────

_PLACEHOLDER = re.compile(r"\{([A-Z_]+)\}")
#: placeholder -> the params key it is filled from (the identifiers and RUN_DATE are filled by RE itself).
_PLACEHOLDER_PARAM = {
    "BASELINE_CT": "baseline_ct", "BASELINE_VALUE_CT": "baseline_value_ct",
    "BASELINE_VALUE": "baseline_value", "BASELINE_VALUE_LIST": "baseline_value",
    "THRESHOLD_VALUE": "threshold_value",
}
_RE_FILLED = {"COLUMN_NAME", "RUN_DATE"}


def _required_params(test_type: TestType) -> list[str]:
    names = _PLACEHOLDER.findall(test_type.measure) + _PLACEHOLDER.findall(test_type.test_condition)
    out: list[str] = []
    for n in names:
        key = _PLACEHOLDER_PARAM.get(n)
        if key and key not in out:
            out.append(key)
    return out


def quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def string_literal(value: str) -> str:
    """A Postgres escape-string literal: correct whatever standard_conforming_strings is set to."""
    return "E'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def parse_value_list(value) -> list[str]:
    """TestGen's list parameter: CSV text (`""` is the empty string), or an already-split list of strings."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        if not all(isinstance(v, str) for v in value):
            raise ParameterError(f"placeholder list must hold strings, got {value!r}")
        return list(value)
    if not isinstance(value, str):
        raise ParameterError(f"placeholder list must be text, got {value!r}")
    return [item for row in csv.reader(io.StringIO(value), skipinitialspace=True) for item in row]


def as_number(name: str, value) -> float | int:
    """A parameter that must be a finite number (ints stay ints). Raises ParameterError quoting the value."""
    if isinstance(value, bool) or value is None or value == "":
        raise ParameterError(f"{name} must be a number, got {value!r}")
    if isinstance(value, (int, float)):
        number = value
    else:
        text = str(value).strip()
        if not _NUMBER.match(text) and not re.match(r"^-?\d+(\.\d+)?[eE][+-]?\d+$", text):
            raise ParameterError(f"{name} must be a number, got {value!r}")
        number = float(text) if any(c in text for c in ".eE") else int(text)
    if isinstance(number, float) and not math.isfinite(number):
        raise ParameterError(f"{name} must be a finite number, got {value!r}")
    return number


def as_iso_date(name: str, value) -> str:
    """A parameter that must be an ISO date or timestamp; returned normalised (so no quote can reach the SQL)."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ParameterError(f"{name} must be an ISO date, got {value!r}") from None
    text = str(value).strip()
    return parsed.date().isoformat() if len(text) == 10 else parsed.isoformat(sep=" ")


def _sql_number(number: float) -> str:
    return repr(number) if isinstance(number, float) else str(number)


def render_measure(test_type: TestType, column_name: str, params: dict, run_date: str) -> str:
    """The test type's vendored Postgres measure with every placeholder filled from validated values.

    `params` is the check's parameters as accepted (or as Egeria holds them); each is validated by type here
    (numbers parse as numbers, the Min_Date baseline as an ISO date, the placeholder list item by item as string
    literals). Raises ParameterError, quoting the bad value, for anything that does not validate, and for any
    placeholder this port does not know: an unknown placeholder means the vendored SQL changed under us."""
    fills: dict[str, str] = {"COLUMN_NAME": quote_identifier(column_name), "RUN_DATE": run_date}
    for placeholder in set(_PLACEHOLDER.findall(test_type.measure)):
        if placeholder in _RE_FILLED:
            continue
        key = _PLACEHOLDER_PARAM.get(placeholder)
        if key is None:
            raise ParameterError(f"the vendored measure uses {{{placeholder}}}, which this port does not fill")
        value = params.get(key)
        if placeholder == "BASELINE_VALUE_LIST":
            items = parse_value_list(value)
            fills[placeholder] = ", ".join(string_literal(v) for v in items) or "NULL"
        elif placeholder == "BASELINE_VALUE":
            if test_type.test_type != "Min_Date":
                raise ParameterError(f"{{BASELINE_VALUE}} is only validated for Min_Date, not {test_type.test_type}")
            fills[placeholder] = as_iso_date("baseline_value", value)
        else:
            fills[placeholder] = _sql_number(as_number(key, value))
    return _PLACEHOLDER.sub(lambda m: fills[m.group(1)], test_type.measure)


def threshold(test_type: TestType, params: dict) -> float | int:
    """The condition's value: the vendored condition is `{THRESHOLD_VALUE}` for every slice-1 type."""
    if test_type.test_condition.strip() != "{THRESHOLD_VALUE}":
        raise ParameterError(f"{test_type.test_type}: condition {test_type.test_condition!r} is not a plain threshold")
    return as_number("threshold_value", params.get("threshold_value"))


def fails(test_type: TestType, measure: float, limit: float) -> bool:
    """TestGen's fail-when comparison, `measure <op> condition`, evaluated by RE on a non-NULL measure."""
    try:
        return _FAIL_WHEN[test_type.test_operator](measure, limit)
    except KeyError:
        raise ParameterError(f"{test_type.test_type}: operator {test_type.test_operator!r} is not supported") from None


def check_key(schema: str, table: str, column: str, test_type: str) -> str:
    """`schema.table.column::Test_Type`, or `schema.table::Test_Type` for a table check (design §5)."""
    path = f"{schema}.{table}.{column}" if column else f"{schema}.{table}"
    return f"{path}::{test_type}"
