"""`file_profiles` (Files build step 5): column names, types and a value profile for every data file the walk found.

Design: BRIEF-FILES-5-FILE-PROFILES.md (architect, 2026-10-23), BRIEF-FILES-QUESTIONS-AND-ANALYSES-TO-RETIRE-CLASSIC.md
section 1a (what Egeria's file connectors own) and section 3 item 2. It answers F3 (which tabular or structured files are
here, with what columns) and feeds F7 (`data_class_match`, a later step).

Two sources, chosen per file (`source_for`), the choice recorded on every row (`stats_source`):

* **Egeria's CSV Survey Service** for a `.csv` file on a file system whose walk Egeria led (`led_by = egeria` on the walk's
  rows). Resource Explorer submits the survey per file (`submit_egeria_half`) and reads Egeria's report back by GUID
  (`read_back_egeria`): the rows then say `stats_source = egeria:<report guid>`. Resource Explorer measures nothing Egeria
  measured: a CSV routed to Egeria is never opened here, even when Egeria cannot run the survey (`not_installed`).
* **Resource Explorer's own profile** (pandas / pyarrow) for every other tabular or structured format, and for `.csv` on a
  file system Resource Explorer led. `stats_source = resource-explorer`.

Rules, each with a test (tests/test_file_profiles.py):

* a file over the profile limit (`PROFILE_LIMIT_BYTES`, the existing 50 MB) is profiled from its first 50 MB, or its first
  row groups for Parquet, with `sample_ratio` < 1 and `state = sampled`; never silently skipped. A format that cannot be
  read in part (one JSON document, a workbook) is a row with `state = over_limit`;
* a format the step does not read is a row with `state = not_applicable` (the card names the formats);
* a file the walk saw but this step may not read is a row with `state = not_permitted`;
* a secret-looking name (`walk_extensions.looks_secret`) or a link is never opened (`secret_name`, `link_not_followed`),
  and the check runs on EVERY file before it is routed: such a `.csv` is never submitted to Egeria either;
* the mount root is checked once per run: unreachable from here, every Resource Explorer file is `not_reachable` (its
  own count), never "not permitted";
* one run per file system at a time (a claim in `app_settings`, `ProjectRegistry.take_claim`): a second press while one
  runs is `AlreadyRunning` (409) and submits nothing;
* a delimited or workbook column whose header looks like data (a number, a date, or a value of its own column) is
  `header_suspect`: kept here, its name never published;
* nothing is written into the path.

The Egeria half rests on three ASSUMPTIONS, each named here, read from the repo's own design notes because the live probe was
not made by this build (no live calls). The coordinator's probe confirms or corrects them before the gate:

* A1 `CSV_SURVEY_REQUEST_TYPE = "survey-csv-file"` (multi-resource-questions-design.md section 1.4, read from Egeria's Java
  source 2026-09-20: `csv-file-survey-service` / `survey-csv-file`, technology type "CSV File"), started as the governance
  action type `CSV_SURVEY_QN = "FileSurvey::survey-csv-file"` with action target `fileToSurvey` (the pattern of
  `FileSurvey::survey-folder`, confirmed live 2026-08-24);
* A2 its target is a CSV file asset per file (the "CSV Data File" template the older catalog path already uses), read
  first by the qualifiedName that template gives it, `CSVFile::<fileSystemName>:<filePathName>` (Egeria
  DataAssetTemplateDefinition.CSV_FILE_TEMPLATE: DeployedImplementationType.CSV_FILE.getAssociatedTypeName() + "::" +
  FILE_SYSTEM_NAME + ":" + FILE_PATH_NAME; the associated type is `CSVFile`), with the unique-name read and a typed check;
  on a miss, a typed exact `pathName` search (`guid_by_exact_path_name`); created from the template only when BOTH miss
  on Egeria's explicit "not found". The coordinator's live probe (FILES5-CSVFILE-QN-PROBE, 2026-10-23) confirmed the
  pattern and showed the fileSystemName is the one Egeria uses (`egeria-deployment`), never RE's slug: it is read from
  the file system's root FileFolder in Egeria (`file_system_name_from_root`, by the GUID RE holds for it), and when it
  cannot be established the Egeria half refuses for that file system (`file_system_name_unknown`: nothing read or
  created);
* A3 Egeria's report carries one ResourceProfileAnnotation per column whose column name is in `profileProperties`
  (`columnName`, else the annotation's display name or summary), its counts in `profileCounts`, and its range in
  `valueRangeFrom` / `valueRangeTo` (`columns_from_report`).
"""
from __future__ import annotations

import functools
import io
import json
import logging
import os
import re
import socket
import stat as stat_mod
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)

STEP_KEY = "file_profiles"

#: The existing profiling limit (data_profiler._MAX_PROFILE_SIZE_MB): a file larger than this is profiled from its first
#: PROFILE_LIMIT_BYTES (sampled), never skipped.
PROFILE_LIMIT_BYTES = 50 * 1024 * 1024

#: Profile runs kept per file system (the newest; older runs are removed when a newer run is written).
RUNS_KEPT = 5

STATS_SOURCE_RE = "resource-explorer"
EGERIA_SOURCE_PREFIX = "egeria:"

# ── A1: the CSV Survey Service as this build ASSUMES Egeria names it (see the module docstring) ───────────────────────
CSV_SURVEY_REQUEST_TYPE = "survey-csv-file"
CSV_SURVEY_QN = "FileSurvey::survey-csv-file"
CSV_ACTION_TARGET = "fileToSurvey"

SOURCE_EGERIA = "egeria"
SOURCE_RE = "re"

#: Row states. Only MEASURED and SAMPLED rows carry measures.
MEASURED = "measured"
SAMPLED = "sampled"
NOT_APPLICABLE = "not_applicable"      # a format this step does not read
NOT_PERMITTED = "not_permitted"        # the walk saw it; this step may not read it
OVER_LIMIT = "over_limit"              # over the limit, in a format that cannot be read in part
UNREADABLE = "unreadable"              # opened, but could not be parsed (the error is on the run's step_runs row)
SECRET_NAME = "secret_name"            # a secret-looking name: never opened
LINK_NOT_FOLLOWED = "link_not_followed"
NOT_INSTALLED = "not_installed"        # routed to Egeria; Egeria's CSV Survey Service is not installed there
EGERIA_UNCHECKED = "egeria_unchecked"  # routed to Egeria; whether it is installed could not be read (never "absent")
SUBMIT_FAILED = "submit_failed"        # routed to Egeria; Egeria refused the survey or the file's asset
SUBMITTED = "submitted"                # routed to Egeria; submitted, Egeria's report not read back yet
FS_NAME_UNKNOWN = "file_system_name_unknown"  # routed to Egeria; the name Egeria uses for the file system is not known
NO_COLUMNS = "no_columns"              # routed to Egeria; its report was read back and carried no column profile
NOT_REACHABLE = "not_reachable"        # the mount root cannot be reached from this machine (checked once per run)
HEADER_SUSPECT = "header_suspect"      # a COLUMN row: its header looks like data; profiled, its name never published
PROFILED_STATES = (MEASURED, SAMPLED)

#: The in-flight claim of one run per file system (`ProjectRegistry.take_claim`); renewed per file, so a live run is
#: never taken over, and a crashed one frees itself after this many seconds.
CLAIM_STALE_SECONDS = 900
ALREADY_RUNNING_WORDS = "a data-file profile run for {slug} is already running"
CLAIM_LOST_WORDS = ("this data-file profile run for {slug} lost its claim (another run holds it now) · stopped, nothing "
                    "from it was stored{submitted}")
PUBLISH_ALREADY_RUNNING_WORDS = "a publish of the data-file profiles of {slug} is already running"
FS_NAME_UNKNOWN_WORDS = ("the name Egeria uses for this file system could not be established ({why}) · no CSV file was "
                         "read or created in Egeria")

#: The type the "CSV Data File" template creates, and the qualifiedName it gives the element (see A2).
CSV_FILE_TYPE = "CSVFile"


def csv_asset_qualified_name(file_system_name: str, canonical_path: str) -> str:
    """`CSVFile::<fileSystemName>:<filePathName>`: the qualifiedName Egeria's CSV Data File template gives the asset.
    `file_system_name` is the name Egeria uses for the file system (`file_system_name_from_root`), never RE's slug."""
    return f"{CSV_FILE_TYPE}::{file_system_name}:{canonical_path}"


#: The type of the file system's root folder in Egeria (the "File System Directory" template's element).
ROOT_FOLDER_TYPE = "FileFolder"


class FileSystemNameUnknown(RuntimeError):
    """The name Egeria uses for this file system could not be established: the Egeria half refuses (nothing is read or
    created in Egeria for its files)."""


def file_system_name_from_root(qualified_name: str, canonical_mount: str) -> str | None:
    """The fileSystemName out of the root FileFolder's qualifiedName, `FileFolder::<fileSystemName>:<directoryPathName>`
    (the File System Directory template's pattern, the same one the CSV Data File template uses). Only when the
    qualifiedName has exactly that shape AND ends in this file system's canonical mount; anything else is None (unknown,
    never guessed)."""
    qn = str(qualified_name or "")
    prefix, suffix = f"{ROOT_FOLDER_TYPE}::", f":{canonical_mount.rstrip('/')}"
    if not canonical_mount.strip("/") or not qn.startswith(prefix) or not qn.endswith(suffix):
        return None
    name = qn[len(prefix):len(qn) - len(suffix)]
    return name if name.strip() else None


class PathNameAmbiguous(RuntimeError):
    """Two or more elements of the type hold this exact pathName: nothing is adopted or created."""


def guid_by_exact_path_name(client, path_name: str, *, type_name: str) -> str | None:
    """A TYPED exact `pathName` search, the second read-first path. The contract of `egeria_lookup.guid_by_exact_value`
    (not on this branch's base), implemented here: one hit = its GUID; None ONLY on Egeria's explicit "No elements
    found"; two or more = `PathNameAmbiguous`; a raise, no answer, an empty list or an answer of another shape RAISES
    (a failed read is never "absent": absent licenses a create)."""
    from resource_explorer.egeria_lookup import _GUID, _guid_of, _is_miss

    answer = client.get_elements_by_property_value(path_name, ["pathName"], type_name, page_size=2)
    if _is_miss(answer):
        return None
    if isinstance(answer, dict) and answer:
        answer = [answer]
    if not isinstance(answer, list) or not answer:
        raise RuntimeError(f"the pathName search for {path_name!r} gave no usable answer ({answer!r:.80})")
    if len(answer) > 1:
        raise PathNameAmbiguous(f"{len(answer)} {type_name} elements hold the pathName {path_name!r}: nothing is "
                                "adopted or created")
    hit = answer[0] if isinstance(answer[0], dict) else {}
    guid = _guid_of(hit)
    if not _GUID.match(guid):
        raise RuntimeError(f"the pathName search for {path_name!r} answered an element with no GUID")
    return guid

#: Egeria half outcomes (the run's own word, said on the card).
EGERIA_HALF_NONE = "none"              # no file was routed to Egeria
EGERIA_HALF_SUBMITTED = "submitted"
EGERIA_HALF_NOT_INSTALLED = "not_installed"
EGERIA_HALF_UNCHECKED = "could_not_check"
EGERIA_HALF_PARTIAL = "partly_submitted"
EGERIA_HALF_SUBMIT_FAILED = "submit_failed"
EGERIA_HALF_FS_NAME_UNKNOWN = "file_system_name_unknown"

# ── formats ──────────────────────────────────────────────────────────────────────────────────────────────────────────

_DELIMITED = {"csv": ",", "tsv": "\t", "tab": "\t", "psv": "|"}
_LINES_JSON = {"jsonl", "ndjson"}
_WHOLE_ONLY = {"json", "xlsx", "xlsm", "xls", "ods", "feather", "arrow", "avro"}
_LIBRARY = {"xlsx": "openpyxl", "xlsm": "openpyxl", "xls": "xlrd", "ods": "odf", "avro": "fastavro"}


def _has(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


def data_extensions() -> set[str]:
    """Every extension the walk counts as a data file (the existing map) plus `.json`."""
    from resource_explorer.surveyors.sub_surveyors.data_profiler import _DATA_EXTENSIONS

    return set(_DATA_EXTENSIONS) | {"json"}


def readable_extensions() -> set[str]:
    """The formats this step reads here: delimited text, JSON and JSON Lines, Parquet, and the whole-file formats whose
    library is installed (a workbook needs openpyxl, Avro needs fastavro). Anything else is `not_applicable`."""
    out = set(_DELIMITED) | _LINES_JSON | {"json", "parquet", "feather", "arrow"}
    out |= {ext for ext, mod in _LIBRARY.items() if _has(mod)}
    return out


def ext_of(file_path: str) -> str:
    name = file_path.rpartition("/")[2]
    return name.rpartition(".")[2].lower() if "." in name else ""


def source_for(file_path: str, led_by: str) -> str:
    """Who profiles this file: Egeria's CSV Survey Service for a `.csv` on an Egeria-led file system, else Resource Explorer."""
    return SOURCE_EGERIA if ext_of(file_path) == "csv" and led_by == "egeria" else SOURCE_RE


# ── the column profile (pure over a DataFrame) ───────────────────────────────────────────────────────────────────────

def general_type_of(dtype_text: str) -> str:
    """The database value profile's general type letters (A text, B boolean, D date/timestamp, T time, N number, X other)
    from a pandas or Arrow type name, so `data_class_match` reads file columns and database columns the same way."""
    t = (dtype_text or "").lower()
    if t.startswith("bool"):
        return "B"
    if t.startswith(("int", "uint", "float", "double", "decimal", "halffloat")):
        return "N"
    if t.startswith(("datetime", "timestamp", "date")):
        return "D"
    if t.startswith("time"):
        return "T"
    if t in ("object", "string", "str", "large_string", "utf8", "large_utf8") or t.startswith("string"):
        return "A"
    return "X"


def _text(v: Any) -> str:
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:  # noqa: BLE001
            pass
    return str(v)


def columns_from_frame(df: Any, *, declared: dict[str, str] | None = None, record_ct: int | None = None,
                       sample_ratio: float = 1.0, state: str = MEASURED) -> list[dict]:
    """One row per column. `declared` overrides the declared type (Parquet's schema type). `record_ct` is the rows read."""
    rows: list[dict] = []
    n = len(df) if record_ct is None else record_ct
    for i, col in enumerate(df.columns, start=1):
        s = df[col]
        dtype = (declared or {}).get(str(col)) or str(s.dtype)
        gtype = general_type_of(dtype)
        values = s.dropna()
        value_ct = int(values.shape[0])
        row = {"column_name": str(col), "ordinal": i, "declared_type": dtype, "inferred_general_type": gtype,
               "record_ct": int(n), "value_ct": value_ct, "null_ct": int(n) - value_ct, "distinct_ct": None,
               "min_text": None, "max_text": None, "min_len": None, "max_len": None,
               "sample_ratio": round(float(sample_ratio), 6), "stats_source": STATS_SOURCE_RE, "state": state}
        try:
            row["distinct_ct"] = int(values.nunique())
        except TypeError:          # unhashable cells (lists/dicts in JSON): not measured, never 0
            row["distinct_ct"] = None
        if value_ct:
            try:
                if gtype in ("N", "D", "B", "T"):
                    row["min_text"], row["max_text"] = _text(values.min()), _text(values.max())
                else:
                    texts = values.astype(str)
                    row["min_text"], row["max_text"] = str(texts.min()), str(texts.max())
                    lens = texts.str.len()
                    row["min_len"], row["max_len"] = int(lens.min()), int(lens.max())
            except (TypeError, ValueError):
                pass
        rows.append(row)
    return rows


_NUMBER_LIKE = re.compile(r"^[+-]?(\d+([.,]\d+)*|\.\d+)([eE][+-]?\d+)?%?$")
_DATE_LIKE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}([ T].*)?$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")


def header_looks_like_data(name: Any, series: Any) -> bool:
    """A header that reads as a VALUE: a number, a date, or equal to a value of its own column (a headerless CSV whose
    first row was taken as the header). Such a column's name is never published."""
    n = str(name).strip()
    if not n:
        return False
    if _NUMBER_LIKE.match(n) or _DATE_LIKE.match(n):
        return True
    try:
        return bool((series.dropna().astype(str).str.strip() == n).any())
    except Exception:  # noqa: BLE001 -- a column that cannot be compared is not flagged
        return False


def flag_header_suspects(df: Any, rows: list[dict]) -> list[dict]:
    """Mark the column rows whose header looks like data `header_suspect` (the profile stays; the name is not published)."""
    for row, col in zip(rows, df.columns):
        if header_looks_like_data(col, df[col]):
            row["state"] = HEADER_SUSPECT
    return rows


# ── reading one file (Resource Explorer's half) ──────────────────────────────────────────────────────────────────────

_O_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


class NotPermitted(Exception):
    pass


def _open_plain(path: Path):
    """Open without following a link or blocking, and require a regular file on the OPEN descriptor. Raises NotPermitted
    when the OS refuses (EACCES/EPERM); returns None for a link, FIFO, device or anything else that is not a plain file."""
    try:
        fd = os.open(path, _O_FLAGS)
    except PermissionError as exc:
        raise NotPermitted(str(exc)) from exc
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat_mod.S_ISREG(st.st_mode):
            os.close(fd)
            return None
        os.set_blocking(fd, True)
        return os.fdopen(fd, "rb")
    except OSError:
        os.close(fd)
        return None


def _cut_at_line(data: bytes) -> bytes:
    """A prefix ends at its last whole line: a half row is never profiled."""
    cut = data.rfind(b"\n")
    return data[: cut + 1] if cut >= 0 else data


def profile_file(path: Path, ext: str, size: int | None = None, *, limit: int = PROFILE_LIMIT_BYTES) -> dict:
    """Profile one file. Returns {state, columns, sample_ratio, bytes_read, size_bytes, error}. Raises nothing for a bad
    file: a parse failure is `unreadable` with the error, a refused open is `not_permitted`. The size, whether the file is
    sampled and its sample ratio come from `os.fstat` on the OPEN descriptor; `size` (the walk row's) is not used for any
    of them, since the file can have changed since the walk."""
    import pandas as pd

    out = {"state": MEASURED, "columns": [], "sample_ratio": 1.0, "bytes_read": 0, "size_bytes": None, "error": ""}
    try:
        fh = _open_plain(path)
    except NotPermitted as exc:
        return {**out, "state": NOT_PERMITTED, "error": str(exc)}
    if fh is None:
        return {**out, "state": LINK_NOT_FOLLOWED}
    try:
        size = os.fstat(fh.fileno()).st_size
    except OSError as exc:
        fh.close()
        return {**out, "state": UNREADABLE, "error": f"{type(exc).__name__}: {exc}"[:300]}
    out["size_bytes"] = size
    sampled = size > limit
    try:
        with fh:
            if ext == "parquet":
                return _profile_parquet(fh, size, limit, out)
            if ext in _WHOLE_ONLY and sampled:
                return {**out, "state": OVER_LIMIT}
            data = fh.read(limit)
            out["bytes_read"] = len(data)
            if sampled:
                data = _cut_at_line(data)
            ratio = (len(data) / size) if sampled and size else 1.0
            state = SAMPLED if sampled else MEASURED
            if ext in _DELIMITED:
                try:
                    df = pd.read_csv(io.BytesIO(data), sep=_DELIMITED[ext], low_memory=False)
                except UnicodeDecodeError:
                    df = pd.read_csv(io.BytesIO(data), sep=_DELIMITED[ext], low_memory=False, encoding="latin-1")
            elif ext in _LINES_JSON:
                df = pd.read_json(io.BytesIO(data), lines=True)
            elif ext == "json":
                df = _json_frame(data, pd)
                if df is None:
                    return {**out, "state": NOT_APPLICABLE, "error": "not tabular JSON (no list of records)"}
            elif ext in ("xlsx", "xlsm", "xls", "ods"):
                df = pd.read_excel(io.BytesIO(data))
            elif ext in ("feather", "arrow"):
                df = pd.read_feather(io.BytesIO(data))
            elif ext == "avro":
                import fastavro

                df = pd.DataFrame(list(fastavro.reader(io.BytesIO(data))))
            else:
                return {**out, "state": NOT_APPLICABLE}
            columns = columns_from_frame(df, sample_ratio=ratio, state=state)
            if ext in _DELIMITED or ext in ("xlsx", "xlsm", "xls", "ods"):
                columns = flag_header_suspects(df, columns)
            out.update(state=state, sample_ratio=ratio, columns=columns)
            return out
    except Exception as exc:  # noqa: BLE001 -- a file that cannot be parsed is a row that says so, never a silent skip
        return {**out, "state": UNREADABLE, "columns": [], "error": f"{type(exc).__name__}: {exc}"[:300]}


def _json_frame(data: bytes, pd):
    doc = json.loads(data.decode("utf-8", errors="replace"))
    if isinstance(doc, dict):
        lists = [v for v in doc.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
        doc = lists[0] if len(lists) == 1 else None
    if isinstance(doc, list) and doc and all(isinstance(x, dict) for x in doc):
        return pd.json_normalize(doc, max_level=0)
    return None


def _profile_parquet(fh, size: int, limit: int, out: dict) -> dict:
    """Parquet over the limit: the first row groups whose stored bytes fit the limit, with sample_ratio = rows read /
    rows in the file. When even the first row group is over the limit nothing is read (`over_limit`): a file over the
    limit is never read whole. The schema's types are the declared types."""
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(fh)
    meta = pf.metadata
    declared = {pf.schema_arrow.field(i).name: str(pf.schema_arrow.field(i).type) for i in range(len(pf.schema_arrow))}
    total_rows = meta.num_rows
    if size <= limit:
        table = pf.read()
        read_bytes = size
    else:
        groups, used = [], 0
        for g in range(meta.num_row_groups):
            b = meta.row_group(g).total_byte_size
            if used + b > limit:
                break
            groups.append(g)
            used += b
        if not groups:
            return {**out, "state": OVER_LIMIT, "error": "its first row group alone is over the limit"}
        table = pf.read_row_groups(groups)
        read_bytes = used
    df = table.to_pandas()
    ratio = (len(df) / total_rows) if total_rows else 1.0
    state = SAMPLED if ratio < 1 else MEASURED
    out.update(state=state, sample_ratio=ratio, bytes_read=min(read_bytes, size),
               columns=columns_from_frame(df, declared=declared, sample_ratio=ratio, state=state))
    return out


def marker_row(state: str, *, stats_source: str = "", sample_ratio: float | None = None, guid: str = "") -> dict:
    """The one row of a file that has no column rows: it carries the file's state."""
    return {"column_name": "", "ordinal": 0, "state": state, "stats_source": stats_source, "sample_ratio": sample_ratio,
            "egeria_report_guid": guid}


# ── the Egeria half ──────────────────────────────────────────────────────────────────────────────────────────────────

class CsvSurveyPort(Protocol):
    """The Egeria surface the CSV half uses. Every method raises on a transport/API failure (never an empty answer)."""

    def csv_survey_listed(self) -> bool: ...
    def egeria_file_system_name(self, fs_entity) -> str: ...
    def csv_asset_guid(self, fs_entity, rel_path: str, canonical_path: str, file_system_name: str) -> str: ...
    def initiate(self, process_qualified_name: str, action_target_name: str, target_guid: str,
                 request_parameters: dict | None = None) -> str: ...
    def report_guid_for_action(self, engine_action_guid: str) -> str | None: ...
    def read_report(self, report_guid: str): ...


@functools.lru_cache(maxsize=1)
def pyegeria_port_class():
    """The real port's class (built once, lazily, so importing this module does not import pyegeria)."""
    from resource_explorer.native_survey_run import PyegeriaSurveyPort

    class PyegeriaCsvSurveyPort(PyegeriaSurveyPort):
        """The real port: the native-survey port plus the two reads/writes the CSV half needs."""

        def csv_survey_listed(self) -> bool:
            """A1 as this build can read it through the view server: is the governance action type declared? The
            coordinator's probe adds the engine host's own list (`ServerOps.get_governance_engine_summaries`)."""
            return self.process_declared(CSV_SURVEY_QN)

        def __init__(self, identity=None) -> None:
            super().__init__(identity=identity)
            self._fs_surveyor = None

        def _surveyor_for(self, fs_entity):
            """ONE file-system surveyor (its Egeria clients) per port, so per run; closed by `close()`."""
            if self._fs_surveyor is None:
                from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyor

                s = EgeriaFileSystemSurveyor(platform_url=fs_entity.egeria_url or None,
                                             view_server=fs_entity.egeria_server or None, identity=self.principal())
                s.connect()
                self._fs_surveyor = s
            return self._fs_surveyor

        def egeria_file_system_name(self, fs_entity) -> str:
            """The name Egeria uses for this file system: read from its root FileFolder in Egeria BY the GUID Resource
            Explorer holds for it (`fs_entity.egeria_asset_guid`, set when the root folder was attached), out of that
            element's qualifiedName (`file_system_name_from_root`). Raises `FileSystemNameUnknown` (with why) when there
            is no GUID, the read-back does not match a FileFolder, or the qualifiedName does not carry the name."""
            from resource_explorer.egeria_absence import _is_guid

            guid = (fs_entity.egeria_asset_guid or "").strip()
            if not _is_guid(guid):
                raise FileSystemNameUnknown("its root folder is not attached in Egeria")
            self._enter()
            read = self._surveyor_for(fs_entity)._read_back_by_guid(guid, expect_type=ROOT_FOLDER_TYPE)
            if not read.get("matched"):
                raise FileSystemNameUnknown(f"its root folder could not be read back: {read.get('why') or 'no match'}")
            canonical = (fs_entity.canonical_mount_point or fs_entity.local_mount_point).rstrip("/")
            name = file_system_name_from_root(read.get("qualified_name", ""), canonical)
            if not name:
                raise FileSystemNameUnknown(
                    f"its root folder's qualifiedName {read.get('qualified_name', '')!r:.120} does not name it")
            return name

        def csv_asset_guid(self, fs_entity, rel_path: str, canonical_path: str, file_system_name: str) -> str:
            """A2: the file's CSV Data File asset, read FIRST by the template's qualifiedName
            (`csv_asset_qualified_name` with the name Egeria uses for the file system) with the unique-name read, typed
            `CSVFile`; on a miss, by a typed exact `pathName` search (`guid_by_exact_path_name`); created from the CSV
            Data File template only when BOTH say Egeria's explicit "not found" (a read that could not be made, or an
            ambiguous one, raises: nothing is created). The create uses the same file system name and path, so a re-run
            finds what this one made."""
            from resource_explorer.egeria_absence import _is_guid

            if not str(file_system_name or "").strip():
                raise FileSystemNameUnknown("no file system name was given")
            self._enter()
            s = self._surveyor_for(fs_entity)
            qn = csv_asset_qualified_name(file_system_name, canonical_path)
            guid = s._find_element_guid(qn, type_name=CSV_FILE_TYPE, qualified_name=True)
            if guid:
                return guid
            guid = guid_by_exact_path_name(s._metadata_expert, canonical_path, type_name=CSV_FILE_TYPE)
            if guid:
                return guid
            name = rel_path.rpartition("/")[2]
            made = s._create_data_file_asset({"file_path": rel_path, "file_name": name, "format": "CSV"},
                                             canonical_path, file_system_name, fallback=False)
            if not _is_guid(made):
                raise RuntimeError(f"Egeria did not return an element GUID for {qn} (it answered {made!r:.60})")
            return made

        def close(self) -> None:
            if self._fs_surveyor is not None:
                try:
                    self._fs_surveyor.close()
                except Exception:  # noqa: BLE001 -- closing never fails the run
                    log.debug("closing the file-system surveyor failed", exc_info=True)
                self._fs_surveyor = None
            super().close()

    return PyegeriaCsvSurveyPort


def make_port(identity=None):
    return pyegeria_port_class()(identity=identity)


def _short(exc: Exception) -> str:
    return " ".join(f"{type(exc).__name__}: {exc}".split())[:300]


class ClaimLost(RuntimeError):
    """The run's claim was renewed and is no longer ours (another run took it over): the run stops, storing nothing."""


def _true() -> bool:
    return True


def submit_egeria_half(port: CsvSurveyPort | None, fs_entity, files: list[dict], *,
                       heartbeat: Callable[[], Any] = _true) -> tuple[str, dict[str, list[dict]], dict]:
    """Submit Egeria's CSV Survey Service for each file routed to Egeria. Returns (half state, rows per file, actions per
    file {path: {engine_action_guid, asset_guid} | {error}}). Whether the service is installed is read FIRST; a failed read
    is `could_not_check`, never "not installed". Then the name Egeria uses for the file system: when it cannot be
    established the half refuses (`file_system_name_unknown`, nothing read or created in Egeria). `heartbeat` renews the
    run's claim before each file; False (the claim is lost) raises `ClaimLost`, naming how many were already submitted."""
    if not files:
        return EGERIA_HALF_NONE, {}, {}
    rows: dict[str, list[dict]] = {}
    actions: dict[str, dict] = {}
    if port is None:
        for f in files:
            rows[f["file_path"]] = [marker_row(EGERIA_UNCHECKED)]
            actions[f["file_path"]] = {"error": "no Egeria connection for this run"}
        return EGERIA_HALF_UNCHECKED, rows, actions
    try:
        listed = port.csv_survey_listed()
    except Exception as exc:  # noqa: BLE001 -- a failed read is said, never read as absence
        for f in files:
            rows[f["file_path"]] = [marker_row(EGERIA_UNCHECKED)]
            actions[f["file_path"]] = {"error": _short(exc)}
        return EGERIA_HALF_UNCHECKED, rows, actions
    if not listed:
        for f in files:
            rows[f["file_path"]] = [marker_row(NOT_INSTALLED)]
        return EGERIA_HALF_NOT_INSTALLED, rows, actions
    try:
        fs_name = port.egeria_file_system_name(fs_entity)
        if not str(fs_name or "").strip():
            raise FileSystemNameUnknown("Egeria's answer carried no name")
    except Exception as exc:  # noqa: BLE001 -- unknown is refused, never guessed (the slug is not Egeria's name)
        why = str(exc) if isinstance(exc, FileSystemNameUnknown) else _short(exc)
        for f in files:
            rows[f["file_path"]] = [marker_row(FS_NAME_UNKNOWN)]
            actions[f["file_path"]] = {"error": FS_NAME_UNKNOWN_WORDS.format(why=why)}
        return EGERIA_HALF_FS_NAME_UNKNOWN, rows, actions
    canonical_root = (fs_entity.canonical_mount_point or fs_entity.local_mount_point).rstrip("/")
    ok = 0
    for f in files:
        rel = f["file_path"]
        if heartbeat() is False:
            raise ClaimLost(CLAIM_LOST_WORDS.format(
                slug=fs_entity.slug, submitted=f" · {ok:,} CSV file{'' if ok == 1 else 's'} already submitted to Egeria"
                if ok else ""))
        try:
            asset = port.csv_asset_guid(fs_entity, rel, f"{canonical_root}/{rel}", fs_name)
            if not asset:
                raise RuntimeError("Egeria returned no asset for the file")
            action = port.initiate(CSV_SURVEY_QN, CSV_ACTION_TARGET, asset)
            actions[rel] = {"engine_action_guid": action, "asset_guid": asset}
            rows[rel] = [marker_row(SUBMITTED)]
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- one file refused does not end the run
            actions[rel] = {"error": _short(exc)}
            rows[rel] = [marker_row(SUBMIT_FAILED)]
    half = EGERIA_HALF_SUBMITTED if ok == len(files) else EGERIA_HALF_PARTIAL if ok else EGERIA_HALF_SUBMIT_FAILED
    return half, rows, actions


def _num(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def columns_from_report(report) -> list[dict]:
    """A3: one column row per ResourceProfileAnnotation of Egeria's CSV report, `stats_source = egeria:<report guid>`.
    An annotation that names no column is not a column (it is counted by the caller as not read). Duplicate column names
    are deduplicated by ordinal: the same (name, ordinal) twice is one column; one name at two ordinals becomes
    `name [ordinal]` for the second, so a file's rows never collide on the table's unique key."""
    guid = report.guid
    out: list[dict] = []
    seen: dict[str, set[int]] = {}
    for ann in report.annotations:
        d = ann.get("detail") or {}
        kind = (ann.get("annotation_type") or "") + " " + (d.get("type_name") or "")
        if "ResourceProfile" not in kind or "Log" in kind:
            continue
        props = d.get("profile_properties") or {}
        name = props.get("columnName") or props.get("fieldName") or d.get("display_name") or ann.get("summary") or ""
        if not name:
            continue
        counts = d.get("profile_counts") or {}
        record = _num(counts.get("recordCount") or counts.get("valueCount"))
        nulls = _num(counts.get("nullCount"))
        values = _num(counts.get("nonNullCount")) if counts.get("nonNullCount") is not None else (
            record - nulls if record is not None and nulls is not None else None)
        ordinal = _num(props.get("position") or props.get("ordinal")) or len(out) + 1
        name = str(name)
        ordinals = seen.setdefault(name, set())
        if ordinal in ordinals:             # the same column twice (same name, same ordinal): kept once
            continue
        if ordinals:                        # two columns of one name: told apart by ordinal
            name = f"{name} [{ordinal}]"
        ordinals.add(ordinal)
        out.append({
            "column_name": name, "ordinal": ordinal,
            "declared_type": str(d.get("inferred_data_type") or props.get("dataType") or ""),
            "inferred_general_type": general_type_of(str(d.get("inferred_data_type") or props.get("dataType") or "")),
            "record_ct": record, "value_ct": values, "null_ct": nulls,
            "distinct_ct": _num(counts.get("distinctCount") or counts.get("uniqueValueCount")),
            "min_text": (str(d["value_range_from"]) if d.get("value_range_from") not in (None, "") else None),
            "max_text": (str(d["value_range_to"]) if d.get("value_range_to") not in (None, "") else None),
            "min_len": _num(counts.get("minLength")), "max_len": _num(counts.get("maxLength")),
            "sample_ratio": None, "stats_source": f"{EGERIA_SOURCE_PREFIX}{guid}", "egeria_report_guid": guid,
            "egeria_datafield_guid": str(props.get("dataFieldGUID") or d.get("data_field_guid") or ""),
            "state": MEASURED,
        })
    return out


def read_back_egeria(fs_entity, registry, port: CsvSurveyPort, *, run_id: str | None = None) -> dict:
    """Read Egeria's CSV reports back for every file the run submitted. A file whose action has no report yet stays
    `submitted`; a report with no column profile is said (`no_columns`), never stored as an empty profile."""
    slug = fs_entity.slug
    run = latest_run_record(registry, slug) if run_id is None else run_record(registry, slug, run_id)
    if not run:
        return {"read": 0, "waiting": 0, "failed": 0, "no_columns": 0, "run_id": ""}
    run_id = run["surveyed_at"]
    actions = (run.get("metrics") or {}).get("egeria_actions") or {}
    states = {r["file_path"]: r for r in registry.filesystem_file_profile_states(slug, run_id)}
    counts = {"read": 0, "waiting": 0, "failed": 0, "no_columns": 0, "run_id": run_id, "errors": {}}
    for rel, act in actions.items():
        guid = act.get("engine_action_guid")
        if not guid or (states.get(rel) or {}).get("state") != SUBMITTED:
            continue
        try:
            report_guid = port.report_guid_for_action(guid)
            if not report_guid:
                counts["waiting"] += 1
                continue
            cols = columns_from_report(port.read_report(report_guid))
            if not cols:
                registry.replace_filesystem_file_profile(slug, run_id, rel, [marker_row(
                    NO_COLUMNS, stats_source=f"{EGERIA_SOURCE_PREFIX}{report_guid}", guid=report_guid)])
                counts["no_columns"] += 1
                continue
            registry.replace_filesystem_file_profile(slug, run_id, rel, cols)
        except Exception as exc:  # noqa: BLE001 -- one bad file stays submitted and is said; the request never fails
            counts["failed"] += 1
            counts["errors"][rel] = _short(exc)
            continue
        counts["read"] += 1
    return counts


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class NothingToProfile(RuntimeError):
    """No walk rows to profile from; the words say what to run first."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def machine() -> str:
    return socket.gethostname()


def walk_data_files(registry, slug: str) -> tuple[dict | None, list[dict]]:
    """The newest walk run and its data files (by extension)."""
    runs = registry.list_filesystem_walk_runs(slug)
    if not runs:
        return None, []
    newest = runs[0]
    exts = data_extensions()
    files = [r for r in registry.list_filesystem_walk_files(slug, newest["run_id"]) if ext_of(r["file_path"]) in exts]
    return newest, files


def run_record(registry, slug: str, run_id: str) -> dict | None:
    rows = registry.query_step_runs(slug=slug, step_key=STEP_KEY, surveyed_at=run_id, entity_type="filesystem", limit=1)
    return rows[0] if rows else None


def latest_run_record(registry, slug: str) -> dict | None:
    rows = registry.query_step_runs(slug=slug, step_key=STEP_KEY, entity_type="filesystem", limit=1)
    return rows[0] if rows else None


class AlreadyRunning(RuntimeError):
    """A profile run for this file system is in flight (a second press is refused, never queued or run twice)."""


def mount_reachable(root: Path) -> bool:
    """The mount root, checked ONCE per run: False when it does not exist or is not a directory from this machine. A root
    the OS refuses to stat is reachable (its files then say `not_permitted`, file by file)."""
    try:
        st = os.stat(root)
    except PermissionError:
        return True
    except OSError:
        return False
    return stat_mod.S_ISDIR(st.st_mode)


def _link_state(root: Path, rel: str) -> str | None:
    """LINK_NOT_FOLLOWED when the file, or a folder on its way down from the root, is a link (lstat, never followed);
    NOT_REACHABLE when a step of that way cannot be lstat'ed (it could be a link: the file is held, never opened);
    None when no step is a link."""
    path = root
    for part in Path(rel).parts:
        path = path / part
        try:
            if stat_mod.S_ISLNK(os.lstat(path).st_mode):
                return LINK_NOT_FOLLOWED
        except OSError:
            return NOT_REACHABLE
    return None


def _is_linked(root: Path, rel: str) -> bool:
    """Whether the file must be held as (possibly) linked: True for a link on the way down AND for a step that could not
    be checked (OSError), so a file whose way down is unknown is never opened or submitted."""
    return _link_state(root, rel) is not None


def precheck(f: dict, root: Path, reachable: bool) -> str | None:
    """The checks EVERY file gets before it is routed to Egeria or to Resource Explorer: a link (the walk's row, or lstat
    when the root is reachable) is `link_not_followed`; a way down that cannot be lstat'ed is `not_reachable` (held);
    a secret-looking name is `secret_name`. None: route it."""
    from resource_explorer.surveyors.filesystem import walk_extensions as we

    rel = f["file_path"]
    if f.get("hash_state") == we.LINK:
        return LINK_NOT_FOLLOWED
    if f.get("hash_state") == we.SECRET_NAME or we.looks_secret(rel.rpartition("/")[2]):
        return SECRET_NAME
    return _link_state(root, rel) if reachable else None


def last_published_run(registry, slug: str, *, before: str | None = None) -> str | None:
    """The newest profile run whose publish is COMPLETE (its proof says every annotation is in Egeria and the report was
    read back), older than `before` when given. The baseline `changed_rows` diffs against."""
    rows = registry.query_step_runs(slug=slug, step_key=PUBLISH_STEP_KEY, entity_type="filesystem", limit=200)
    for r in sorted(rows, key=lambda x: x.get("surveyed_at") or "", reverse=True):
        at = r.get("surveyed_at") or ""
        if (r.get("metrics") or {}).get("complete") and (before is None or at < before):
            return at
    return None


def run_file_profiles(fs_entity, registry, *, port: CsvSurveyPort | None = None,
                      port_factory: Callable[[], CsvSurveyPort] | None = None, limit: int = PROFILE_LIMIT_BYTES,
                      clock: Callable[[], float] = time.monotonic) -> dict:
    """Profile every data file of the newest walk, store the rows for this run and the run's own record, and return the
    run's summary. Raises NothingToProfile when there is no walk yet, AlreadyRunning when a run for this file system
    holds the claim (nothing is submitted or read). Writes nothing into the path."""
    slug = fs_entity.slug
    walk, files = walk_data_files(registry, slug)
    if walk is None:
        raise NothingToProfile("no walk of this file system yet · run the folder survey first")
    run_id = _now()
    claim_key = f"{STEP_KEY}:{registry._normalize_slug(slug)}"
    holder = f"{machine()}:{os.getpid()}:{run_id}"
    if not registry.take_claim(claim_key, holder, stale_after_seconds=CLAIM_STALE_SECONDS):
        raise AlreadyRunning(ALREADY_RUNNING_WORDS.format(slug=slug))
    try:
        return _run(fs_entity, registry, walk, files, run_id, port=port, port_factory=port_factory, limit=limit,
                    clock=clock, heartbeat=lambda: registry.refresh_claim(claim_key, holder))
    finally:
        registry.release_claim(claim_key, holder)


def _run(fs_entity, registry, walk: dict, files: list[dict], run_id: str, *, port, port_factory, limit: int, clock,
         heartbeat: Callable[[], Any]) -> dict:
    slug = fs_entity.slug
    led_by = walk.get("led_by") or "re"
    root = Path(fs_entity.local_mount_point)
    reachable = mount_reachable(root)
    readable = readable_extensions()

    all_rows: list[dict] = []
    egeria_files: list[dict] = []
    re_files: list[dict] = []
    for f in files:
        held = precheck(f, root, reachable)
        if held:
            all_rows.append({**marker_row(held), "file_path": f["file_path"]})
        elif source_for(f["file_path"], led_by) == SOURCE_EGERIA:
            egeria_files.append(f)
        else:
            re_files.append(f)

    made_here = None
    if egeria_files and port is None and port_factory is not None:
        try:
            port = made_here = port_factory()
        except Exception:  # noqa: BLE001 -- said as could_not_check below
            log.warning("%s: no Egeria port for the CSV half", slug, exc_info=True)
    try:
        egeria_state, egeria_rows, egeria_actions = submit_egeria_half(port, fs_entity, egeria_files,
                                                                       heartbeat=heartbeat)
    finally:
        if made_here is not None and hasattr(made_here, "close"):
            made_here.close()

    for rel, rows in egeria_rows.items():
        all_rows.extend({**r, "file_path": rel} for r in rows)

    errors: dict[str, str] = {}
    bytes_read = 0
    started = clock()
    for f in re_files:
        rel = f["file_path"]
        ext = ext_of(rel)
        path = root / rel
        if not reachable:
            rows = [marker_row(NOT_REACHABLE)]
        elif ext not in readable:
            rows = [marker_row(NOT_APPLICABLE)]
        elif not os.access(path, os.R_OK):
            rows = [marker_row(NOT_PERMITTED)]
        else:
            if heartbeat() is False:
                raise ClaimLost(CLAIM_LOST_WORDS.format(slug=slug, submitted=""))
            res = profile_file(path, ext, limit=limit)
            bytes_read += res["bytes_read"]
            if res["error"]:
                errors[rel] = res["error"]
            if res["state"] in PROFILED_STATES and res["columns"]:
                rows = res["columns"]
            elif res["state"] in PROFILED_STATES:
                rows = [marker_row(res["state"], stats_source=STATS_SOURCE_RE, sample_ratio=res["sample_ratio"])]
            else:
                rows = [marker_row(res["state"])]
        all_rows.extend({**r, "file_path": rel} for r in rows)
    seconds = max(0.0, clock() - started)

    published = last_published_run(registry, slug)
    stored = registry.add_filesystem_file_columns(slug, run_id, all_rows, keep_also=(published,) if published else ())
    metrics = {
        "walk_run_id": walk["run_id"], "led_by": led_by, "machine": machine(), "limit_bytes": limit,
        "mount_reachable": reachable,
        "data_files": len(files), "egeria_files": len(egeria_files), "re_files": len(re_files),
        "re_bytes_read": bytes_read, "re_seconds": round(seconds, 3),
        "egeria_half": egeria_state, "egeria_actions": egeria_actions, "errors": errors,
        "rows": stored["rows"], "pruned_runs": stored["pruned_runs"],
    }
    registry.record_step_run(slug, STEP_KEY, run_id, entity_type="filesystem", source="file-profiles",
                             executor="local", metrics=metrics)
    return {"run_id": run_id, **metrics}


# ── price before the run (X-06) ──────────────────────────────────────────────────────────────────────────────────────

def _mb(n: int) -> str:
    return f"{n / 1_000_000:,.1f} MB"


def price(registry, slug: str, *, limit: int = PROFILE_LIMIT_BYTES) -> dict:
    """The one cost line, from the walk rows: "N data files, M MB to read; Egeria will profile C CSV files, RE will profile
    R others; about T s". T is from the bytes per second the last run of this step measured ON THIS MACHINE, else "no run
    yet to price from". M counts what will be read: the first `limit` bytes of a file over the limit."""
    walk, files = walk_data_files(registry, slug)
    if walk is None:
        return {"walk": False, "words": "no walk yet · run the folder survey first"}
    led_by = walk.get("led_by") or "re"
    readable = readable_extensions()
    egeria = [f for f in files if source_for(f["file_path"], led_by) == SOURCE_EGERIA]
    re_side = [f for f in files if source_for(f["file_path"], led_by) == SOURCE_RE]
    re_bytes = sum(min(int(f.get("size_bytes") or 0), limit) for f in re_side if ext_of(f["file_path"]) in readable)
    egeria_bytes = sum(int(f.get("size_bytes") or 0) for f in egeria)
    rate = None
    host = machine()
    for r in registry.query_step_runs(slug=None, step_key=STEP_KEY, entity_type="filesystem", limit=50):
        m = r.get("metrics") or {}
        if m.get("machine") == host and m.get("re_seconds") and m.get("re_bytes_read"):
            rate = m["re_bytes_read"] / m["re_seconds"]
            break
    seconds = round(re_bytes / rate) if rate else None
    words = (f"{len(files):,} data files, {_mb(re_bytes + egeria_bytes)} to read; Egeria will profile {len(egeria):,} CSV "
             f"files, RE will profile {len(re_side):,} others; "
             + (f"about {seconds:,} s" if seconds is not None else "no run yet to price from"))
    return {"walk": True, "walk_run_id": walk["run_id"], "data_files": len(files), "bytes_to_read": re_bytes + egeria_bytes,
            "egeria_files": len(egeria), "re_files": len(re_side), "seconds": seconds,
            "bytes_per_second": round(rate) if rate else None, "words": words}


# ── what the card says (from the stored rows) ────────────────────────────────────────────────────────────────────────

FILES_SHOWN = 50


def card_counts(states: list[dict]) -> dict:
    """The card's counts, each from the stored rows of one run."""
    by = lambda *s: [r for r in states if r["state"] in s]  # noqa: E731
    profiled = by(MEASURED, SAMPLED, HEADER_SUSPECT)   # a file whose every header looks like data is still profiled
    egeria = [r for r in profiled if str(r.get("stats_source") or "").startswith(EGERIA_SOURCE_PREFIX)]
    not_read = by(NOT_APPLICABLE)
    formats = sorted({ext_of(r["file_path"]) or "(none)" for r in not_read})
    return {"files": len(states), "profiled": len(profiled), "by_egeria": len(egeria), "by_re": len(profiled) - len(egeria),
            "sampled": len(by(SAMPLED)), "not_read": len(not_read), "not_read_formats": formats,
            "not_permitted": len(by(NOT_PERMITTED)), "over_limit": len(by(OVER_LIMIT)), "unreadable": len(by(UNREADABLE)),
            "secret_name": len(by(SECRET_NAME)), "link_not_followed": len(by(LINK_NOT_FOLLOWED)),
            "not_installed": len(by(NOT_INSTALLED)), "egeria_unchecked": len(by(EGERIA_UNCHECKED)),
            "submit_failed": len(by(SUBMIT_FAILED)), "submitted": len(by(SUBMITTED)), "no_columns": len(by(NO_COLUMNS)),
            "file_system_name_unknown": len(by(FS_NAME_UNKNOWN)),
            "not_reachable": len(by(NOT_REACHABLE))}


def card_words(c: dict) -> str:
    """"P files profiled (E by Egeria, R by RE), S sampled, X not read (formats: ...), U not permitted", then
    " (N header suspect)" when any file has a header that looks like data."""
    fmts = f" (formats: {', '.join(c['not_read_formats'])})" if c["not_read_formats"] else ""
    suspect = int(c.get("header_suspect") or 0)
    return (f"{c['profiled']:,} files profiled ({c['by_egeria']:,} by Egeria, {c['by_re']:,} by RE), {c['sampled']:,} sampled, "
            f"{c['not_read']:,} not read{fmts}, {c['not_permitted']:,} not permitted"
            + (f" ({suspect:,} header suspect)" if suspect else ""))


def profiles_view(registry, slug: str) -> dict:
    """The price line and the newest run, every count from the stored rows."""
    out: dict = {"price": price(registry, slug), "run": None}
    runs = registry.list_filesystem_file_column_runs(slug)
    if not runs:
        return out
    run_id = runs[0]
    states = registry.filesystem_file_profile_states(slug, run_id)
    counts = card_counts(states)
    record = run_record(registry, slug, run_id) or {}
    m = record.get("metrics") or {}
    rows = registry.list_filesystem_file_columns(slug, run_id)
    counts["header_suspect"] = len({r["file_path"] for r in rows if r["state"] == HEADER_SUSPECT})
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        if r["column_name"]:
            col = {k: r[k] for k in ("column_name", "declared_type", "inferred_general_type", "record_ct", "null_ct",
                                     "distinct_ct", "min_len", "max_len")}
            if r["state"] == HEADER_SUSPECT:   # the header is a value: shown by position, never by the value
                col.update(column_name=f"column {r['ordinal']}", header_suspect=True)
            by_file.setdefault(r["file_path"], []).append(col)
    files = [{**s, "format": ext_of(s["file_path"]), "columns_list": by_file.get(s["file_path"], [])[:30]}
             for s in states[:FILES_SHOWN]]
    proof = latest_publish_proof(registry, slug, run_id)
    out["run"] = {"run_id": run_id, "counts": counts, "words": card_words(counts), "egeria_half": m.get("egeria_half", ""),
                  "walk_run_id": m.get("walk_run_id", ""), "files": files,
                  "files_not_shown": max(0, len(states) - FILES_SHOWN), "publish": proof}
    return out


# ── publish (Resource Explorer's profiles only; Egeria's own report stays Egeria's) ──────────────────────────────────

PUBLISH_STEP_KEY = "file_profiles_publish"
PROFILE_ANNOTATION_NAME = "Profile Data File Column"
_MEASURES = ("declared_type", "inferred_general_type", "record_ct", "value_ct", "null_ct", "distinct_ct", "min_len",
             "max_len", "sample_ratio")


def changed_rows(registry, slug: str, run_id: str) -> list[dict]:
    """Resource Explorer's column rows of this run whose profile differs from the last PUBLISHED run's (or that are new;
    with no complete publish yet, every row). Until the profile-publish reshape lands, only these publish. A
    `header_suspect` column never publishes (its name is a value)."""
    previous = last_published_run(registry, slug, before=run_id)
    before = {}
    if previous:
        before = {(r["file_path"], r["column_name"]): r for r in registry.list_filesystem_file_columns(slug, previous)}
    out = []
    for r in registry.list_filesystem_file_columns(slug, run_id):
        if not r["column_name"] or r["stats_source"] != STATS_SOURCE_RE or r["state"] not in PROFILED_STATES:
            continue
        old = before.get((r["file_path"], r["column_name"]))
        if old is None or any(old.get(k) != r.get(k) for k in _MEASURES):
            out.append(r)
    return out


def publish_specs(rows: list[dict], canonical_root: str) -> list[dict]:
    """One ResourceProfileAnnotation spec per column (the shape folder_survey_annotations.to_annotations takes). Counts and
    types only: the min/max VALUES stay here (they are the data itself)."""
    from resource_explorer.surveyors.file_type_profile import EGERIA_ANALYSIS_STEP

    specs = []
    for r in rows:
        counts = {k: int(r[k]) for k in ("record_ct", "value_ct", "null_ct", "distinct_ct", "min_len", "max_len")
                  if r.get(k) is not None}
        specs.append({
            "annotation_type_name": PROFILE_ANNOTATION_NAME, "kind": "profile", "analysis_step": EGERIA_ANALYSIS_STEP,
            "summary": f"{r['file_path']} · {r['column_name']} · surveyed by Resource Explorer",
            "explanation": f"column {r['ordinal']} of {r['file_path']}: {r['declared_type']} (general type "
                           f"{r['inferred_general_type']})" + (" · sampled" if r["state"] == SAMPLED else ""),
            "value_count": counts,
            "additional": {"filePath": f"{canonical_root}/{r['file_path']}", "columnName": r["column_name"],
                           "declaredType": r["declared_type"], "generalType": r["inferred_general_type"],
                           "sampleRatio": str(r["sample_ratio"]), "statsSource": r["stats_source"]},
        })
    return specs


def latest_publish_proof(registry, slug: str, run_id: str) -> dict | None:
    rows = registry.query_step_runs(slug=slug, step_key=PUBLISH_STEP_KEY, surveyed_at=run_id, entity_type="filesystem",
                                    limit=1)
    return (rows[0].get("metrics") or None) if rows else None
