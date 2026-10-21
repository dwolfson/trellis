"""The vendored `general_type` CASE (`configdata/quality/testgen/postgresql/general_type.sql`), ported to Python.

`general_type` (A text, B boolean, D date/timestamp, T time, N number, X anything else) decides which measures
the value profile takes for a column and which selection rules can apply. It is derived from the column's
catalog type, never measured. The CASE is not run against the target: RE already holds every column's type in
its stored inventory. Like the selection rules, the port is pinned to the SHA-256 of the CASE text it came from
(`GENERAL_TYPE_CASE_SHA256`), checked by tests/test_quality_catalogue.py.
"""
from __future__ import annotations

import re

from resource_explorer.surveyors.database.quality.catalogue import POSTGRES_DIR, sha256_text

GENERAL_TYPE_SQL = POSTGRES_DIR / "general_type.sql"
GENERAL_TYPE_CASE_SHA256 = "b059e1e13714472f197b29f3795436317bfd72ed990dfdab904fdb6716c91476"

#: Postgres's internal type names (`pg_type.typname`, which rows materialised from an Egeria survey can carry) ->
#: the `information_schema` names the CASE is written against.
_INTERNAL_NAMES = {
    "int2": "smallint", "int4": "integer", "int8": "bigint", "float4": "real", "float8": "double precision",
    "bool": "boolean", "varchar": "character varying", "bpchar": "character", "char": "character",
    "timestamptz": "timestamp with time zone", "timestamp": "timestamp without time zone",
    "timetz": "time with time zone", "time": "time without time zone", "decimal": "numeric",
}

_MODIFIER = re.compile(r"\(\s*(\d+)(?:\s*,\s*\d+)?\s*\)")


def vendored_case_text() -> str:
    """The CASE statement in the vendored file: every line from `CASE` to `END AS general_type,`."""
    lines = GENERAL_TYPE_SQL.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "CASE")
    end = next(i for i, line in enumerate(lines) if line.strip().startswith("END AS general_type"))
    return "\n".join(lines[start:end + 1]) + "\n"


def _information_schema_type(catalog_type: str) -> tuple[str, int | None]:
    """RE stores either `information_schema.columns.data_type` ("character varying") or, for a table only the
    catalog shows, `format_type()` ("character varying(20)", "timestamp(3) without time zone", "bit(1)").
    Reduce the second to the first, keeping the length modifier as `character_maximum_length`."""
    text = (catalog_type or "").strip()
    if text.endswith("[]"):
        return "ARRAY", None  # information_schema's word for every array type
    match = _MODIFIER.search(text)
    length = int(match.group(1)) if match else None
    if text.startswith("_"):
        return "ARRAY", None  # pg_type names an array type with a leading underscore (_int4)
    name = re.sub(r"\s+", " ", _MODIFIER.sub("", text)).strip()
    return _INTERNAL_NAMES.get(name.lower(), name), length


def general_type(catalog_type: str | None, character_maximum_length: int | None = None) -> str:
    """The CASE, term for term:

        WHEN c.data_type ILIKE '%char%' or c.data_type = 'text'                                  THEN 'A'
        WHEN c.data_type ILIKE 'boolean' OR (c.data_type = 'bit' AND c.character_maximum_length = 1) THEN 'B'
        WHEN c.data_type ILIKE 'date' OR c.data_type ILIKE 'timestamp%'                          THEN 'D'
        WHEN c.data_type ILIKE 'time with%'                                                       THEN 'T'
        WHEN LOWER(c.data_type) IN ('bigint', 'integer', 'smallint', 'double precision', 'real',
                                    'numeric', 'money')                                          THEN 'N'
        ELSE 'X'

    (`time with%` also matches "time without time zone": that is upstream's behaviour, kept.)"""
    data_type, length = _information_schema_type(catalog_type or "")
    if character_maximum_length is None:
        character_maximum_length = length
    lowered = data_type.lower()
    if "char" in lowered or data_type == "text":
        return "A"
    if lowered == "boolean" or (data_type == "bit" and character_maximum_length == 1):
        return "B"
    if lowered == "date" or lowered.startswith("timestamp"):
        return "D"
    if lowered.startswith("time with"):
        return "T"
    if lowered in ("bigint", "integer", "smallint", "double precision", "real", "numeric", "money"):
        return "N"
    return "X"


def case_matches_pin() -> bool:
    return sha256_text(vendored_case_text()) == GENERAL_TYPE_CASE_SHA256
