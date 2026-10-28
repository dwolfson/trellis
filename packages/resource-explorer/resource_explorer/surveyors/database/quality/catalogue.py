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
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from resource_explorer.surveyors.database.quality.functional_type import (
    INPUTS as INFERENCE_INPUTS,
)
from resource_explorer.surveyors.database.quality.functional_type import (
    as_timestamp,
    datediff_day,
    recency_excluded,
)

CATALOGUE_DIR = Path(__file__).resolve().parents[3] / "configdata" / "quality" / "testgen"
TEST_TYPES_DIR = CATALOGUE_DIR / "test_types"
POSTGRES_DIR = CATALOGUE_DIR / "postgresql"
GENERATION_TEMPLATES_DIR = CATALOGUE_DIR / "gen_query_tests"

#: The upstream commit the catalogue was copied from (PROVENANCE.md). Part of every proposal's catalogue_ref.
UPSTREAM_COMMIT = "3606859c"

#: Slice 1's seven test types.
SLICE_1_TEST_TYPES = (
    "Missing_Pct", "Required", "Required_No_Placeholder", "Unique", "Future_Date", "Min_Date", "Row_Ct_Pct",
)
#: Quality slice Q6 (DESIGN-QUALITY-Q6-RECENCY.md): Recency, whose rule reads the date branch of the
#: functional-type inference (`functional_type.py`), and Future_Date_1Y, which rides with it.
Q6_TEST_TYPES = ("Recency", "Future_Date_1Y")
#: Q4 port order step 2, B1a (DESIGN-QUALITY-B1A-BASELINE-MATCH.md): the Table Comparison types whose baseline is a
#: measure the value profile already takes. Proposed only for a table a person opted in (`table_comparison.py`).
B1A_TEST_TYPES = ("Match_Row_Ct", "Match_Distinct_Ct", "Match_Null_Ct", "Match_Zero_Length_Ct", "Match_Min_Date",
                  "Match_Max_Date")
#: Q4 port order step 3, profile 1b then B1b (DESIGN-QUALITY-PROFILE-1B.md): the Table Comparison types whose baseline
#: is a measure profile 1b adds, and Daily_Record_Ct (TestGen's Standard set, proposed without an opt-in). Match_Epoch_Sum
#: is not ported: upstream takes `epoch_sum` only for a column in its hashed set (step 8).
B1B_TEST_TYPES = ("Match_Min_Val", "Match_Max_Val", "Match_Sum", "Match_Stdev", "Match_Zero_Ct", "Match_Fractional_Sum",
                  "Match_Min_Length", "Match_Max_Length", "Match_Total_Length", "Match_True_Ct",
                  "Match_Distinct_Date_Ct", "Daily_Record_Ct")
#: Every test type RE has ported, in the order proposals are considered.
PORTED_TEST_TYPES = SLICE_1_TEST_TYPES + Q6_TEST_TYPES + B1A_TEST_TYPES + B1B_TEST_TYPES

#: TestGen's generation set for the baseline-match types. TestGen generates them only for a table group a person
#: opted into it; RE proposes them only for a table a person opted in (Q4 §7, question 2).
TABLE_COMPARISON = "Table Comparison"

#: The test type RE proposes on its own initiative: TestGen has no selection rule for it (manual-only there).
RE_PROPOSED = frozenset({"Row_Ct_Pct"})

#: TestGen's default_severity -> the ODCS/Egeria severity word a rule carries.
SEVERITY = {"Fail": "error", "Warning": "warning", "Log": "info"}

#: TestGen's data quality dimension -> the ODCS dimension word Egeria's `qualityDimension` carries
#: (`DataContractQualityDimension`: accuracy, completeness, conformity, consistency, coverage, timeliness,
#: uniqueness). Validity is Conformity and Recency is Timeliness; the rest map by name
#: (INVENTORY-TESTGEN-TEST-TYPES-MAPPED.md).
EGERIA_DIMENSION = {"Validity": "conformity", "Recency": "timeliness"}
ODCS_DIMENSIONS = frozenset({"accuracy", "completeness", "conformity", "consistency", "coverage", "timeliness",
                             "uniqueness"})


def egeria_dimension(testgen_dimension: str) -> str:
    """The ODCS dimension word for a TestGen `dq_dimension`; "" when it is not one Egeria names."""
    word = EGERIA_DIMENSION.get(testgen_dimension, (testgen_dimension or "").strip().lower())
    return word if word in ODCS_DIMENSIONS else ""


#: TestGen's FAIL-WHEN operator -> the ODCS MUST-BE operator (its inverse), as Publish will write it (design §7).
MUST_BE = {
    ">": "mustBeLessOrEqualTo",
    ">=": "mustBeLessThan",
    "<": "mustBeGreaterOrEqualTo",
    "<=": "mustBeGreaterThan",
    "=": "mustNotBe",
    "<>": "mustBe",
    "NOT BETWEEN": "mustBeBetween",
}


@dataclass(frozen=True)
class Between:
    """The limit of a `NOT BETWEEN low AND high` condition (Match_Sum, Match_Stdev): the check fails outside it."""

    low: Any
    high: Any

    def __str__(self) -> str:
        return f"{self.low} AND {self.high}"


_FAIL_WHEN: dict[str, Callable[[Any, Any], bool]] = {
    ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq, "<>": operator.ne,
    "NOT BETWEEN": lambda measure, limit: not (limit.low <= measure <= limit.high),
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
    generation_sets: tuple[str, ...] = ()
    generation_template: str | None = None
    #: Upstream's flag: a NULL measure is a failure rather than a pass. Read by `run_quality_checks`.
    null_measure_fails: bool = False

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

    @property
    def is_table_comparison(self) -> bool:
        """A baseline-match type: proposed only for a table a person opted in."""
        return TABLE_COMPARISON in self.generation_sets

    @property
    def measure_is_text(self) -> bool:
        """The measure is text compared with a quoted baseline (Match_Min_Date, Match_Max_Date), not a number."""
        return self.test_condition.strip() == "{BASELINE_VALUE_LITERAL}"

    @property
    def measure_is_exact(self) -> bool:
        """The measure is an exact NUMERIC compared with an exact decimal (Match_Sum, Match_Fractional_Sum), never
        through a float."""
        return self.test_type in EXACT_TEST_TYPES


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
        generation_sets=tuple(raw.get("generation_sets") or ()),
        generation_template=raw.get("generation_template"),
        null_measure_fails=bool(raw.get("null_measure_fails")),
    )


def read_raw(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("test_types") or {}


@lru_cache(maxsize=1)
def load_catalogue() -> dict[str, TestType]:
    """{test_type: TestType} for every ported test type, read from the vendored YAML."""
    return {name: parse_test_type(read_raw(TEST_TYPES_DIR / f"{name}.yaml")) for name in PORTED_TEST_TYPES}


# ── upstream's templated functions (`<%NAME;arg;arg%>`) ────────────────────────────────────────────────────────

TEMPLATED_FUNCTIONS_YAML = POSTGRES_DIR / "templated_functions.yaml"
_FUNCTION_CALL = re.compile(r"<%(\w+)(?:;(.+?))?%>")
_FUNCTION_ARG = re.compile(r"\{\$(\d+)\}")


@lru_cache(maxsize=1)
def templated_functions() -> dict[str, str]:
    """{name: template} from the vendored subset, comments dropped and whitespace squashed as upstream does."""
    raw = yaml.safe_load(TEMPLATED_FUNCTIONS_YAML.read_text(encoding="utf-8")) or {}
    return {name: re.sub(r"\s\s*", " ", re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)) for name, text in raw.items()}


def expand_templated_functions(text: str) -> str:
    """Upstream's `read_file.replace_templated_functions` for the Postgres flavour: each `<%NAME;a;b%>` becomes the
    template with `{$1}`, `{$2}` set to the arguments. Applied to VENDORED text only, before any placeholder is
    filled, so no identifier or parameter value is ever split on `;` or matched as `%>`. An unknown function or a
    missing argument raises ParameterError: the vendored SQL then calls something this port has not vendored."""
    functions = templated_functions()

    def call(match: re.Match) -> str:
        name, args = match.group(1), (match.group(2) or "").split(";")
        if name not in functions:
            raise ParameterError(f"the vendored SQL calls <%{name}%>, which templated_functions.yaml does not hold")

        def arg(m: re.Match) -> str:
            index = int(m.group(1)) - 1
            if index >= len(args):
                raise ParameterError(f"<%{name}%> is missing argument {index + 1}")
            return args[index]
        return _FUNCTION_ARG.sub(arg, functions[name])
    return _FUNCTION_CALL.sub(call, text)


def selection_source(test_type: TestType) -> str | None:
    """The vendored text a selection rule was ported from: the `selection_criteria` fragment, or, when that is
    upstream's `TEMPLATE` marker, the vendored generation template it names (Match_Row_Ct). None when there is no
    upstream rule (Row_Ct_Pct)."""
    if test_type.selection_criteria == "TEMPLATE":
        if not test_type.generation_template:
            raise ValueError(f"{test_type.test_type}: selection is TEMPLATE but no generation_template is named")
        return (GENERATION_TEMPLATES_DIR / test_type.generation_template).read_text(encoding="utf-8")
    return test_type.selection_criteria


def catalogue_ref(test_type: TestType) -> str:
    """Where a proposal's rule came from: the upstream commit and the SHA-256 of the selection fragment (or of the
    generation template, for a TEMPLATE type; or of the Postgres measure, for a check RE proposes itself)."""
    if test_type.selection_criteria == "TEMPLATE":
        return f"vendored-catalog@{UPSTREAM_COMMIT}:{test_type.test_type}:generation_template:sha256:" \
               f"{sha256_text(selection_source(test_type))}"
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


def _shift(ts: datetime | None, *, days: int) -> datetime | None:
    return None if ts is None else ts + timedelta(days=days)


def _midnight(ts: datetime | None) -> datetime | None:
    """`'...'::DATE`, compared with a timestamp: its midnight."""
    return None if ts is None else datetime(ts.year, ts.month, ts.day)  # noqa: DTZ001 - naive UTC, as upstream's timestamp columns


def _datediff_day(first, second) -> int | None:
    a, b = as_timestamp(first), as_timestamp(second)
    return None if a is None or b is None else datediff_day(a, b)


def _greatest(*values):
    """Postgres GREATEST: NULL arguments are ignored; NULL only when every argument is NULL."""
    known = [v for v in values if v is not None]
    return max(known) if known else None


def _abs(value):
    return None if value is None else abs(value)


def _mul(*values):
    return None if any(v is None for v in values) else math.prod(values)


def _sub(a, b):
    return None if a is None or b is None else a - b


#: The measure profile 1b always takes for a column of each general_type that has a value: NULL there, with
#: value_ct > 0, means the row was profiled before profile 1b existed (its migration left the column NULL).
PROFILE_1B_WITNESS = {"N": "min_value", "A": "min_length", "B": "boolean_true_ct", "D": "date_days_present"}


def _profiled_by_1b(row: dict) -> bool | None:
    """None when profile 1b's measures cannot be read from this row: the column was not profiled (`state`), or the row
    predates profile 1b (its general_type's witness measure is NULL though the column has values). Else True. A B1b
    rule ANDs this in, so either reads `not_established`, never a silent no: several of their fragments read a 1b
    measure with IS NOT NULL, where upstream's NULL means "not applicable" and an unprofiled column has no row."""
    if (row.get("state") or "measured") != "measured":
        return None
    witness = PROFILE_1B_WITNESS.get(row.get("general_type") or "")
    if witness is None:
        return True
    if row.get("value_ct") is None:
        return None
    if row["value_ct"] == 0:
        return True
    return None if row.get(witness) is None else True


def _is_not_null_1b(row: dict, measure: str) -> bool | None:
    """`<1b measure> IS NOT NULL`, unknown (None) when the row cannot carry 1b measures (`_profiled_by_1b`): FALSE
    there would win any SQL AND and turn "not measured" into a silent no."""
    return None if _profiled_by_1b(row) is None else row.get(measure) is not None


def _sql_or(*values: bool | None) -> bool | None:
    """SQL OR: TRUE if any operand is TRUE, else NULL if any is NULL, else FALSE."""
    if any(v is True for v in values):
        return True
    if any(v is None for v in values):
        return None
    return False


#: Daily_Record_Ct's anchor date, `'1800-01-05'::DATE` (its midnight).
_DAILY_ANCHOR = datetime(1800, 1, 5)  # noqa: DTZ001 - naive, as upstream's timestamp columns


def _date_span_days(min_date, max_date) -> int | None:
    """`DATEDIFF('day', '1800-01-05'::DATE, max_date) - DATEDIFF('day', '1800-01-05'::DATE, min_date) + 1`: the
    calendar days from the first date to the last, both counted."""
    first, last = _datediff_day(_DAILY_ANCHOR, max_date), _datediff_day(_DAILY_ANCHOR, min_date)
    return None if first is None or last is None else first - last + 1


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
    # general_type= 'D' AND max_date <= run_date + INTERVAL '1 day' AND NOT column_name IN ( 'filedate' ,
    #   'file_date' ) AND NOT functional_data_type IN ('Future Date', 'Schedule Date') AND DATEDIFF( 'DAY' ,
    #   max_date, run_date) <= 62
    # run_date is the profile's own instant (its batch `surveyed_at`); functional_data_type is the date branch of
    # the inference, ported in functional_type.py.
    "Recency": Predicate(
        "575ccbd3c20b457f0de7c76a98a1ac8d5c5900f544bc455f0017ed4826067c44",
        tuple(dict.fromkeys(("general_type", "max_date", "surveyed_at") + INFERENCE_INPUTS)),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "D"),
            _cmp(as_timestamp(_p(p, "max_date")), "<=", _shift(as_timestamp(_p(p, "surveyed_at")), days=1)),
            _not(_p(p, "column_name") in ("filedate", "file_date")),
            _not(recency_excluded(p)),
            _cmp(_datediff_day(_p(p, "max_date"), _p(p, "surveyed_at")), "<=", 62),
        ),
    ),
    # general_type='D'AND future_date_ct > 0 AND max_date <='{AS_OF_DATE}'::DATE + INTERVAL'365 DAYS'
    # {AS_OF_DATE} is the instant the checks are generated: the propose run (`as_of_date`), as TestGen's
    # generation run with no profiling delay.
    "Future_Date_1Y": Predicate(
        "90e86999535a8ca5b5acfb738507d1f6745e4888eb3851526c891716efa01027",
        ("general_type", "future_date_ct", "max_date", "as_of_date"),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "D"),
            _cmp(_p(p, "future_date_ct"), ">", 0),
            _cmp(as_timestamp(_p(p, "max_date")), "<=", _shift(_midnight(as_timestamp(_p(p, "as_of_date"))), days=365)),
        ),
    ),
    # ── B1a, the Table Comparison set: each runs only for a table a person opted in (propose.py) ──
    # gen_Match_Row_Ct.sql: every table of the profile run, with no condition (threshold_value = MAX(record_ct)).
    # A table RE could not profile has no record_ct; its default then reads NULL and it is not_established.
    "Match_Row_Ct": Predicate(
        "388b034e415c0229391f2e2405019fe5fc33df6c6113cdc75830be395f88c421",
        (),
        lambda p: True,
    ),
    # record_ct > 0 AND general_type <> 'X'
    "Match_Distinct_Ct": Predicate(
        "58e585157796b4807f7c5e18560ab021f575a3acabbbc0ed6c55cd7ea14245a5",
        ("record_ct", "general_type"),
        lambda p: _and(_cmp(_p(p, "record_ct"), ">", 0), _cmp(_p(p, "general_type"), "<>", "X")),
    ),
    # record_ct > 0 AND NOT (general_type = 'X' AND query_error IS NOT NULL)
    # query_error is TestGen's per-column profiling error. RE keeps no measured row with an error: a column whose read
    # failed is a row whose state is not `measured`, so that is the port of `query_error IS NOT NULL`.
    "Match_Null_Ct": Predicate(
        "a47c1abddc42557952036c5548933ff1bca2f940604b3a0633e60ecffa3442da",
        ("record_ct", "general_type"),
        lambda p: _and(
            _cmp(_p(p, "record_ct"), ">", 0),
            _not(_and(_cmp(_p(p, "general_type"), "=", "X"), (_p(p, "state") or "measured") != "measured")),
        ),
    ),
    # general_type = 'A' AND value_ct > 0\nAND sample_ratio IS NULL
    "Match_Zero_Length_Ct": Predicate(
        "359e71c7c48e6d6e625aefc828c381cbdae63f00a62fa74b6097fd0728f47e78",
        ("general_type", "value_ct", "sample_ratio"),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "A"),
            _cmp(_p(p, "value_ct"), ">", 0),
            _p(p, "sample_ratio") is None,
        ),
    ),
    # general_type = 'D' AND value_ct > 0
    "Match_Min_Date": Predicate(
        "d37f535f28c39a6fec1b6602b138cd7b327ca3c1e08d1db2246ea7043c2d19a7",
        ("general_type", "value_ct"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "D"), _cmp(_p(p, "value_ct"), ">", 0)),
    ),
    # general_type = 'D' AND value_ct > 0
    "Match_Max_Date": Predicate(
        "d37f535f28c39a6fec1b6602b138cd7b327ca3c1e08d1db2246ea7043c2d19a7",
        ("general_type", "value_ct"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "D"), _cmp(_p(p, "value_ct"), ">", 0)),
    ),
    # ── B1b, on profile 1b's measures. Each ANDs in `_profiled_by_1b` (an RE addition, named in its inputs) ──
    # general_type = 'N' AND value_ct > 0
    "Match_Min_Val": Predicate(
        "b5e6d3de37808d45817466a91cddf37dc88632bab718dff3d716ebb801b9ac09",
        ("general_type", "value_ct", "min_value"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "N"), _cmp(_p(p, "value_ct"), ">", 0), _profiled_by_1b(p)),
    ),
    # general_type = 'N' AND value_ct > 0
    "Match_Max_Val": Predicate(
        "b5e6d3de37808d45817466a91cddf37dc88632bab718dff3d716ebb801b9ac09",
        ("general_type", "value_ct", "min_value"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "N"), _cmp(_p(p, "value_ct"), ">", 0), _profiled_by_1b(p)),
    ),
    # general_type = 'N' AND value_ct > 0 AND GREATEST(ABS(min_value), ABS(max_value)) * value_ct < 1e30
    # AND (sum_value IS NOT NULL OR ABS(avg_value) >= 1e-5 * GREATEST(ABS(min_value), ABS(max_value)))
    "Match_Sum": Predicate(
        "18c91beb2f1dedf1164c971104dcac5ec6001004182898373d36333f0b9953bd",
        ("general_type", "value_ct", "min_value", "max_value", "sum_value", "avg_value"),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "N"),
            _cmp(_p(p, "value_ct"), ">", 0),
            _cmp(_mul(_greatest(_abs(_p(p, "min_value")), _abs(_p(p, "max_value"))), _p(p, "value_ct")), "<", 1e30),
            _sql_or(_is_not_null_1b(p, "sum_value"),
                    _cmp(_abs(_p(p, "avg_value")), ">=",
                         _mul(1e-5, _greatest(_abs(_p(p, "min_value")), _abs(_p(p, "max_value")))))),
            _profiled_by_1b(p),
        ),
    ),
    # general_type = 'N' AND value_ct > 1 AND distinct_value_ct > 1 AND stdev_value IS NOT NULL
    "Match_Stdev": Predicate(
        "37c334e78f5ebb4ebc3069b433808a25ca9a4685edfece61adc863f868907572",
        ("general_type", "value_ct", "distinct_value_ct", "stdev_value", "min_value"),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "N"),
            _cmp(_p(p, "value_ct"), ">", 1),
            _cmp(_p(p, "distinct_value_ct"), ">", 1),
            _is_not_null_1b(p, "stdev_value"),
        ),
    ),
    # general_type = 'N' AND value_ct > 0
    "Match_Zero_Ct": Predicate(
        "b5e6d3de37808d45817466a91cddf37dc88632bab718dff3d716ebb801b9ac09",
        ("general_type", "value_ct", "min_value"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "N"), _cmp(_p(p, "value_ct"), ">", 0), _profiled_by_1b(p)),
    ),
    # general_type = 'N' AND fractional_sum IS NOT NULL
    "Match_Fractional_Sum": Predicate(
        "3a01ea588bc1e733473008b3b9557fed37fb8f6652756cb2cef83a765d7cb81c",
        ("general_type", "fractional_sum", "min_value"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "N"), _is_not_null_1b(p, "fractional_sum")),
    ),
    # general_type = 'A' AND value_ct > 0
    "Match_Min_Length": Predicate(
        "d0557b9d9bd6b14ed583462b330402c1559fa790d99f26941badd66ddba9a283",
        ("general_type", "value_ct", "min_length"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "A"), _cmp(_p(p, "value_ct"), ">", 0), _profiled_by_1b(p)),
    ),
    # general_type = 'A' AND value_ct > 0
    "Match_Max_Length": Predicate(
        "d0557b9d9bd6b14ed583462b330402c1559fa790d99f26941badd66ddba9a283",
        ("general_type", "value_ct", "min_length"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "A"), _cmp(_p(p, "value_ct"), ">", 0), _profiled_by_1b(p)),
    ),
    # general_type = 'A' AND value_ct > 0\nAND sample_ratio IS NULL
    "Match_Total_Length": Predicate(
        "359e71c7c48e6d6e625aefc828c381cbdae63f00a62fa74b6097fd0728f47e78",
        ("general_type", "value_ct", "sample_ratio", "min_length"),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "A"),
            _cmp(_p(p, "value_ct"), ">", 0),
            _p(p, "sample_ratio") is None,
            _profiled_by_1b(p),
        ),
    ),
    # general_type = 'B' AND value_ct > 0
    "Match_True_Ct": Predicate(
        "b9c4460a9ceea97b193b0c5e58f3468d43e8dbdd1c06d8cf144a01e311484c13",
        ("general_type", "value_ct", "boolean_true_ct"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "B"), _cmp(_p(p, "value_ct"), ">", 0), _profiled_by_1b(p)),
    ),
    # general_type = 'D' AND date_days_present IS NOT NULL
    # COUNT(DISTINCT ...) is never NULL once taken, so upstream's IS NOT NULL is "was profiled"; RE's NULL here is a row
    # from before profile 1b, or a column not profiled, read as not_established rather than "no".
    "Match_Distinct_Date_Ct": Predicate(
        "84883274b83c4a9d84624f2c445158921eaf0335d159fb7b4740d36159ec674e",
        ("general_type", "date_days_present"),
        lambda p: _and(_cmp(_p(p, "general_type"), "=", "D"), _is_not_null_1b(p, "date_days_present")),
    ),
    # general_type= 'D' AND date_days_present > 21 AND date_days_present - (DATEDIFF('day', '1800-01-05'::DATE,
    #   max_date) - DATEDIFF('day', '1800-01-05'::DATE, min_date) + 1) = 0 AND future_date_ct::FLOAT /
    #   NULLIF(value_ct, 0) <= 0.75
    # Standard set: proposed without an opt-in, as TestGen generates it for every table group.
    "Daily_Record_Ct": Predicate(
        "74ba0096f8ab06169623e9b5b18e2089faa3ddc929e3fe92c521a5e0a74eba49",
        ("general_type", "date_days_present", "min_date", "max_date", "future_date_ct", "value_ct"),
        lambda p: _and(
            _cmp(_p(p, "general_type"), "=", "D"),
            _cmp(_p(p, "date_days_present"), ">", 21),
            _cmp(_sub(_p(p, "date_days_present"),
                      _date_span_days(_p(p, "min_date"), _p(p, "max_date"))), "=", 0),
            _cmp(None if _p(p, "future_date_ct") is None or not _p(p, "value_ct")
                 else _p(p, "future_date_ct") / float(_p(p, "value_ct")), "<=", 0.75),
        ),
    ),
}

#: Inputs whose NULL is a real value rather than a missing measure: min_date is read by IS NOT NULL. Recency's
#: inference reads zero_length_ct and filled_value_ct only through upstream's own NULL handling (neither is
#: measured on a date column, upstream either), and min_date only for the Period overrides. A B1b rule reads its
#: own measure with IS NOT NULL (NULL is "not applicable" there: no exact sum on a float column, no stdev of one
#: value); a missing measure is named through the profile 1b witness instead.
_NULL_IS_A_VALUE = {"Min_Date": {"min_date"},
                    "Recency": {"zero_length_ct", "filled_value_ct", "min_date"},
                    "Match_Sum": {"sum_value"},
                    "Match_Stdev": {"stdev_value"},
                    "Match_Fractional_Sum": {"fractional_sum"}}


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
    "baseline_ct": "baseline_ct", "baseline_value_ct": "baseline_value_ct", "baseline_unique_ct": "baseline_unique_ct",
    "baseline_value": "baseline_value", "threshold_value": "threshold_value",
    "baseline_sum": "baseline_sum", "baseline_sd": "baseline_sd", "upper_tolerance": "upper_tolerance",
}
#: Parameter keys a type carries only when its catalogue entry names them (so an earlier type's params_json keeps the
#: shape it was accepted with).
_OPTIONAL_PARAM_KEYS = ("baseline_unique_ct", "baseline_sum", "baseline_sd", "upper_tolerance")


def _recency_threshold(profile: dict):
    """Recency's default threshold, the vendored CASE over d = DATEDIFF('DAY', max_date, run_date):
    d <= 3: d + 3; d <= 7: d + 7; d <= 31: CEILING(d / 7.0) * 7; d > 31: CEILING(d / 30.0) * 30."""
    d = _datediff_day(profile.get("max_date"), profile.get("surveyed_at"))
    if d is None:
        return None
    if d <= 3:
        return d + 3
    if d <= 7:
        return d + 7
    if d <= 31:
        return math.ceil(d / 7.0) * 7
    return math.ceil(d / 30.0) * 30


#: `TO_CHAR(<ts>, 'YYYY-MM-DD HH24:MI:SS')`: the text form the Match_Min_Date/Match_Max_Date baseline and measure take.
TO_CHAR_SECONDS = "%Y-%m-%d %H:%M:%S"
_TO_CHAR_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def to_char_seconds(value) -> str | None:
    """Upstream's `TO_CHAR(min_date, 'YYYY-MM-DD HH24:MI:SS')` over a stored profile date. The profile stores the date
    as the target returned it (`value_profile._value`: ISO text, with an offset for a timestamptz, in the reading
    session's zone). TO_CHAR prints the wall-clock time and drops fractional seconds, so the offset is dropped, not
    converted: the run step's `CAST(MAX(col) AS TIMESTAMP)` reads the same wall clock through the same account's
    session. None for NULL."""
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, date):
        ts = datetime(value.year, value.month, value.day)  # noqa: DTZ001 - a date has no zone
    else:
        try:
            ts = datetime.fromisoformat(str(value).strip())
        except ValueError:
            raise ParameterError(f"the profile's date {value!r} is not an ISO date") from None
    return ts.replace(tzinfo=None).strftime(TO_CHAR_SECONDS)


_EPOCH = datetime(1970, 1, 1)  # noqa: DTZ001 - the text measure carries no zone; neither does its number


def text_measure_number(text: str) -> float | None:
    """A TO_CHAR date measure as the number `database_quality_results.measure` (DOUBLE PRECISION) can hold: seconds
    from 1970-01-01 00:00:00 of the same wall-clock text, lossless to the second TO_CHAR prints. None when the text is
    not that shape (the comparison itself is on the text, so the result does not depend on this)."""
    try:
        return (datetime.strptime(text, TO_CHAR_SECONDS) - _EPOCH).total_seconds()  # noqa: DTZ007
    except (TypeError, ValueError):
        return None


def text_measure_from_number(number: float) -> str:
    """`text_measure_number`, inverted: the TO_CHAR text a stored date measure stands for."""
    return (_EPOCH + timedelta(seconds=number)).strftime(TO_CHAR_SECONDS)


def _date_baseline(measure: str) -> Callable[[dict], Any]:
    return lambda profile: to_char_seconds(profile.get(measure))


def _rtrim(text: str, chars: str) -> str:
    return text.rstrip(chars)


def _match_sum_defaults(profile: dict) -> tuple[Any, Any]:
    """Match_Sum's two defaults, term for term:

        COALESCE(RTRIM(RTRIM(sum_value::VARCHAR, '0'), '.'), (avg_value * value_ct)::VARCHAR)
        CASE WHEN sum_value IS NULL THEN '0.000000001' ELSE '0' END

    `sum_value` is the exact decimal text the profile stored; `(avg_value * value_ct)::VARCHAR` is the float's
    shortest text, which Python's `repr` prints the same way. Both stay text, as upstream's parameters are, so the
    exact sum never passes through a float. NULL when neither measure was taken."""
    sum_value, avg, value_ct = profile.get("sum_value"), profile.get("avg_value"), profile.get("value_ct")
    if sum_value is not None:
        trimmed = _rtrim(_rtrim(str(sum_value), "0"), ".") if "." in str(sum_value) else str(sum_value)
        baseline = trimmed
    else:
        baseline = None if avg is None or value_ct is None else repr(float(avg) * value_ct)
    return baseline, ("0.000000001" if sum_value is None else "0")


def _total_length_default(profile: dict):
    """`CAST(ROUND(COALESCE(avg_length, 0) * (value_ct - COALESCE(zero_length_ct, 0))) AS BIGINT)`: avg_length is the
    mean over non-empty values (upstream's NULLIF(LENGTH, 0)), so times the non-empty count it is the total. Postgres
    rounds a double half to even, as Python's round does. NULL when value_ct is."""
    value_ct = profile.get("value_ct")
    if value_ct is None:
        return None
    return round((profile.get("avg_length") or 0) * (value_ct - (profile.get("zero_length_ct") or 0)))


#: Defaults that are an expression over the profile rather than a list of columns and literals: the SHA-256 of
#: the vendored `default_parm_values` each port was made from, the parameter (or parameters, in order) it fills, and
#: the port (returning a tuple when it fills several).
DEFAULT_PORTS: dict[str, tuple[str, str | tuple[str, ...], Callable[[dict], Any]]] = {
    # CASE WHEN DATEDIFF( 'DAY' , max_date, run_date) <= 3 THEN DATEDIFF('DAY', max_date, run_date) + 3 WHEN ...
    "Recency": ("4a8f8bd298ae8f1e20ff4b7251454697078c503ab760aed919b698a466a00622", "threshold_value",
                _recency_threshold),
    # TO_CHAR(min_date, 'YYYY-MM-DD HH24:MI:SS')
    "Match_Min_Date": ("a249544a0f690252db818b4c436431f6832f3b1be4d36910982e8ecbf5e01f40", "baseline_value",
                       _date_baseline("min_date")),
    # TO_CHAR(max_date, 'YYYY-MM-DD HH24:MI:SS')
    "Match_Max_Date": ("969773ce43fed7c2b153de336efddc38528ae80d47417d9ed31b10d73de93e97", "baseline_value",
                       _date_baseline("max_date")),
    # COALESCE(RTRIM(RTRIM(sum_value::VARCHAR, '0'), '.'), (avg_value * value_ct)::VARCHAR),CASE WHEN sum_value IS
    #   NULL THEN '0.000000001' ELSE '0' END
    "Match_Sum": ("baea8f54d3d7a291bc57510dcb93fd5548b3433a575ca830fb5f1373aa2c696b",
                  ("baseline_sum", "upper_tolerance"), _match_sum_defaults),
    # CAST(ROUND(COALESCE(avg_length, 0) * (value_ct - COALESCE(zero_length_ct, 0))) AS BIGINT)
    "Match_Total_Length": ("764c27fe862246b3e311ea6030ec1212802f99d752fd4f04b2575c469207bd6a", "baseline_sum",
                           _total_length_default),
}


def default_params(test_type: TestType, profile: dict, row_ct_pct_threshold: float) -> dict:
    """The parameters a proposal starts with: the catalogue's defaults evaluated against the profile, plus the
    severity. Raises ParameterError when a default reads a profile measure that is NULL."""
    params: dict[str, Any] = {"baseline_ct": None, "baseline_value_ct": None, "baseline_value": None,
                              "threshold_value": None, "severity": test_type.severity}
    for optional in _OPTIONAL_PARAM_KEYS:
        if optional in test_type.default_parm_columns:
            params[optional] = None
    if test_type.test_type == "Row_Ct_Pct":
        # TestGen has no defaults for it: RE's baseline is the measured count, the threshold a setting.
        params["baseline_ct"] = profile.get("record_ct")
        params["threshold_value"] = row_ct_pct_threshold
    elif test_type.test_type == "Match_Row_Ct":
        # gen_Match_Row_Ct.sql: `s.record_ct AS threshold_value`, the table's MAX(record_ct) in the profile run. RE's
        # record_ct is per table (every measured column's row carries the same count). Pinned with the predicate.
        if sha256_text(selection_source(test_type)) != PREDICATES["Match_Row_Ct"].fragment_sha256:
            raise ParameterError("Match_Row_Ct's vendored generation template changed: re-port it")
        params["threshold_value"] = profile.get("record_ct")
    elif test_type.test_type in DEFAULT_PORTS:
        sha, key, port = DEFAULT_PORTS[test_type.test_type]
        if sha256_text(test_type.default_parm_values) != sha:
            raise ParameterError(f"{test_type.test_type}'s vendored default_parm_values changed: re-port it")
        if isinstance(key, tuple):
            params.update(zip(key, port(profile)))
        else:
            params[key] = port(profile)
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
    "BASELINE_CT": "baseline_ct", "BASELINE_VALUE_CT": "baseline_value_ct", "BASELINE_UNIQUE_CT": "baseline_unique_ct",
    "BASELINE_VALUE": "baseline_value", "BASELINE_VALUE_LIST": "baseline_value",
    "BASELINE_VALUE_LITERAL": "baseline_value",
    "THRESHOLD_VALUE": "threshold_value",
    "BASELINE_SUM": "baseline_sum", "BASELINE_SD": "baseline_sd", "UPPER_TOLERANCE": "upper_tolerance",
}
_RE_FILLED = {"COLUMN_NAME", "COLUMN_NUM", "RUN_DATE"}


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


def column_num(column: str, is_money: bool = False) -> str:
    """Upstream's `{COL_NUM}` / `{COLUMN_NUM}` for Postgres (PostgresqlFlavorService.numeric_value): the quoted column,
    read through ::NUMERIC when it is money, which compares only with money and has no modulo or cast to float."""
    return f"{quote_identifier(column)}::NUMERIC" if is_money else quote_identifier(column)


def is_money_type(catalog_type: str | None) -> bool:
    """Whether a stored catalog type is Postgres's money (the one type `{COLUMN_NUM}` casts)."""
    return (catalog_type or "").strip().lower() == "money"


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


def render_measure(test_type: TestType, column_name: str, params: dict, run_date: str, *,
                   is_money: bool = False) -> str:
    """The test type's vendored Postgres measure with every placeholder filled from validated values.

    `params` is the check's parameters as accepted (or as Egeria holds them); each is validated by type here
    (numbers parse as numbers, the Min_Date baseline as an ISO date, the placeholder list item by item as string
    literals). Raises ParameterError, quoting the bad value, for anything that does not validate, and for any
    placeholder this port does not know: an unknown placeholder means the vendored SQL changed under us.
    `{COLUMN_NUM}` is the column read as a number (`column_num`; `is_money` for a money column)."""
    fills: dict[str, str] = {"COLUMN_NAME": quote_identifier(column_name), "RUN_DATE": run_date,
                             "COLUMN_NUM": column_num(column_name, is_money)}
    measure = expand_templated_functions(test_type.measure)
    for placeholder in set(_PLACEHOLDER.findall(measure)):
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
    return _PLACEHOLDER.sub(lambda m: fills[m.group(1)], measure)


def as_to_char_seconds(name: str, value) -> str:
    """A parameter that must be TO_CHAR's 'YYYY-MM-DD HH24:MI:SS' text (a Match_Min_Date/Match_Max_Date baseline) and
    a real date: returned as it is. It reaches the SQL only through `string_literal`, never formatted in."""
    if not isinstance(value, str) or not _TO_CHAR_SECONDS.match(value):
        raise ParameterError(f"{name} must be a date as 'YYYY-MM-DD HH:MM:SS', got {value!r}")
    try:
        datetime.strptime(value, TO_CHAR_SECONDS)  # noqa: DTZ007 - text compared as text, no zone involved
    except ValueError:
        raise ParameterError(f"{name} must be a date as 'YYYY-MM-DD HH:MM:SS', got {value!r}") from None
    return value


#: The conditions that are one placeholder, read from one parameter.
_CONDITIONS = {"{THRESHOLD_VALUE}": "threshold_value", "{BASELINE_CT}": "baseline_ct",
               "{BASELINE_UNIQUE_CT}": "baseline_unique_ct", "{BASELINE_VALUE_LITERAL}": "baseline_value",
               "{BASELINE_VALUE}": "baseline_value", "{BASELINE_SUM}": "baseline_sum"}

_DECIMAL = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
#: Postgres NUMERIC rounds half away from zero; Decimal's ROUND_HALF_UP is that rule.
_EIGHT_PLACES, _FIVE_PLACES = Decimal("1e-8"), Decimal("1e-5")


def as_decimal(name: str, value) -> Decimal:
    """A parameter that must be an exact finite number: an int, a Decimal, or numeric text (TestGen's parameters are
    text). A float is read through its shortest text, as Postgres reads a float literal. Raises ParameterError
    quoting the value. Never formatted into SQL: the condition is evaluated in Python."""
    if isinstance(value, bool) or value is None:
        raise ParameterError(f"{name} must be a number, got {value!r}")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value))
    elif isinstance(value, str) and _DECIMAL.match(value.strip()):
        number = Decimal(value.strip())
    else:
        raise ParameterError(f"{name} must be a number, got {value!r}")
    if not number.is_finite():
        raise ParameterError(f"{name} must be a finite number, got {value!r}")
    return number


def _numeric(value: Decimal, places: Decimal) -> Decimal:
    """`CAST(value AS NUMERIC(38, n))` / `ROUND(value, n)`: rounded to n places, half away from zero."""
    with localcontext() as ctx:
        ctx.prec = 80
        return value.quantize(places, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SumTolerance:
    """Match_Sum's NOT BETWEEN limit before the run: its bounds read `COUNT({COLUMN_NAME})`, which the run measures
    beside the sum (`between`)."""

    baseline: Decimal
    tolerance: Decimal

    def between(self, count: int) -> Between:
        """`CAST(B AS NUMERIC(38,8)) -/+ CAST(ABS(B * T) + SIGN(ABS(T)) * COUNT(col) * 0.000000005 AS NUMERIC(38,8))`."""
        with localcontext() as ctx:
            ctx.prec = 80
            base = _numeric(self.baseline, _EIGHT_PLACES)
            sign = Decimal(1) if self.tolerance != 0 else Decimal(0)
            margin = _numeric(abs(self.baseline * self.tolerance) + sign * Decimal(count) * Decimal("0.000000005"),
                              _EIGHT_PLACES)
            return Between(base - margin, base + margin)

    def __str__(self) -> str:
        return f"{self.baseline} within tolerance {self.tolerance}"


def _match_sum_condition(params: dict) -> SumTolerance:
    return SumTolerance(as_decimal("baseline_sum", params.get("baseline_sum")),
                        as_decimal("upper_tolerance", params.get("upper_tolerance")))


def _match_stdev_condition(params: dict) -> Between:
    """`CAST(SD AS DOUBLE PRECISION) -/+ ABS(CAST(SD AS DOUBLE PRECISION) * {UPPER_TOLERANCE})`, in doubles."""
    sd = float(as_number("baseline_sd", params.get("baseline_sd")))
    margin = abs(sd * float(as_number("upper_tolerance", params.get("upper_tolerance"))))
    return Between(sd - margin, sd + margin)


#: Conditions that are an expression rather than one placeholder: the SHA-256 of the vendored Postgres
#: `test_condition` each port was made from, and the port (params -> limit). The test types in EXACT_TEST_TYPES
#: compare as Decimal, never as float.
CONDITION_PORTS: dict[str, tuple[str, Callable[[dict], Any]]] = {
    # CAST({BASELINE_VALUE} AS DOUBLE PRECISION)
    "Match_Min_Val": ("8a31c67d694efd17306b33f1e680fc5573fefdc4af6fba52bebe86bc69ffe380",
                      lambda params: float(as_number("baseline_value", params.get("baseline_value")))),
    "Match_Max_Val": ("8a31c67d694efd17306b33f1e680fc5573fefdc4af6fba52bebe86bc69ffe380",
                      lambda params: float(as_number("baseline_value", params.get("baseline_value")))),
    # CAST({BASELINE_SUM} AS NUMERIC(38,8)) - CAST(ABS({BASELINE_SUM} * {UPPER_TOLERANCE}) + SIGN(ABS({UPPER_TOLERANCE}))
    #   * COUNT({COLUMN_NAME}) * 0.000000005 AS NUMERIC(38,8)) AND <the same, +>
    "Match_Sum": ("0d6aa8bba2b6a3646a3f6498f845d88ede57123b5a6ea44c91ffc882331f1efc", _match_sum_condition),
    # CAST({BASELINE_SD} AS DOUBLE PRECISION) - ABS(CAST({BASELINE_SD} AS DOUBLE PRECISION) * {UPPER_TOLERANCE}) AND
    #   <the same, +>
    "Match_Stdev": ("83ee4adff0b3c7fff26b7b82b97a7df5729cdc33407733e6935f2748099ef7ac", _match_stdev_condition),
    # ROUND({BASELINE_SUM}, 5)
    "Match_Fractional_Sum": ("8404752672096b49e556cad30e0a0c0252e0e4220f3fe47c295d8038803507ec",
                             lambda params: _numeric(as_decimal("baseline_sum", params.get("baseline_sum")),
                                                     _FIVE_PLACES)),
}
#: Types whose measure is an exact NUMERIC: SUM(CAST(... AS NUMERIC(38,8))) and the fractional sum at NUMERIC(38,5).
EXACT_TEST_TYPES = frozenset({"Match_Sum", "Match_Fractional_Sum"})
#: Run-time aggregates a condition reads beyond the measure, as vendored text (Match_Sum's tolerance counts values).
CONDITION_AGGREGATES = {"Match_Sum": "COUNT({COLUMN_NAME})"}


def threshold(test_type: TestType, params: dict) -> Any:
    """The condition's value, validated: a number; for a text measure (`measure_is_text`) the baseline date text; for
    an exact measure a Decimal; for a NOT BETWEEN condition a `Between` (or Match_Sum's `SumTolerance`, whose bounds
    the run finishes). A condition that is neither one placeholder nor a pinned port means the vendored condition
    changed under us."""
    if test_type.test_type in CONDITION_PORTS:
        sha, port = CONDITION_PORTS[test_type.test_type]
        if sha256_text(test_type.test_condition) != sha:
            raise ParameterError(f"{test_type.test_type}'s vendored test_condition changed: re-port it")
        return port(params)
    key = _CONDITIONS.get(test_type.test_condition.strip())
    if key is None:
        raise ParameterError(f"{test_type.test_type}: condition {test_type.test_condition!r} is not one placeholder "
                             f"this port reads")
    if test_type.measure_is_text:
        return as_to_char_seconds(key, params.get(key))
    return as_number(key, params.get(key))


def fails(test_type: TestType, measure: Any, limit: Any) -> bool:
    """TestGen's fail-when comparison, `measure <op> condition`, evaluated by RE on a non-NULL measure."""
    try:
        return _FAIL_WHEN[test_type.test_operator](measure, limit)
    except KeyError:
        raise ParameterError(f"{test_type.test_type}: operator {test_type.test_operator!r} is not supported") from None


def check_key(schema: str, table: str, column: str, test_type: str) -> str:
    """`schema.table.column::Test_Type`, or `schema.table::Test_Type` for a table check (design §5)."""
    path = f"{schema}.{table}.{column}" if column else f"{schema}.{table}"
    return f"{path}::{test_type}"
