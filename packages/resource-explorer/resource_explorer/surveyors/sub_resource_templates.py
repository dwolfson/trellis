"""Extension/filename -> Egeria technology-type-name mapping, used to pick
the correct catalog template when creating a DataFile asset for a
cataloged sub-resource (Assessment sub-resource cataloging plan, D5a).

Deliberately NOT the same vocabulary as file_classifier/type_cache.py's
_BUILTIN_BY_EXTENSION — that module produces RE's own display labels
(e.g. "Python Source File") for the kind-distribution UI; this module
produces Egeria's own registered technology-type names (e.g. "Script
File"), confirmed live against a real Egeria instance to actually have a
catalog template behind them. The two are related but not the same
strings, and are expected to diverge further as each is tuned
independently — kept as separate small modules rather than merged.

Confirmed live, 2026-08-11 (see docs/assessment-sub-resource-cataloging.md,
D5a): several very plausible-looking technology types exist as named
concepts in Egeria's catalog but have NO registered template at all —
notably "Program File", "Markdown Document File", "Jupyter Notebook File",
"Log File", "Webpage File", and critically "File" itself (the single most
generic type has no template, so it can never be the fallback). The
fallback used here, "Data File", was confirmed live to actually work.
"""
from __future__ import annotations

from pathlib import PurePosixPath

# Extension (lowercase, no leading dot) -> Egeria technology-type name.
_TECH_TYPE_BY_EXTENSION: dict[str, str] = {
    # Compiled-language source -> "Source Code File" ("...needs to be
    # compiled into an executable form before it can run")
    "java": "Source Code File",
    "c": "Source Code File",
    "h": "Source Code File",
    "cpp": "Source Code File",
    "cc": "Source Code File",
    "hpp": "Source Code File",
    "go": "Source Code File",
    "rs": "Source Code File",
    "kt": "Source Code File",
    "scala": "Source Code File",
    # Interpreted-language source/scripts -> "Script File" ("...code that
    # is interpreted when it is run")
    "py": "Script File",
    "pyi": "Script File",
    "js": "Script File",
    "mjs": "Script File",
    "cjs": "Script File",
    "ts": "Script File",
    "tsx": "Script File",
    "jsx": "Script File",
    "rb": "Script File",
    "sh": "Script File",
    "bash": "Script File",
    "zsh": "Script File",
    "ps1": "Script File",
    "bat": "Script File",
    "sql": "Script File",
    # Documentation -> "Document File" (no more-specific markdown template
    # exists on the confirmed-live instance — see module docstring)
    "md": "Document File",
    "mdx": "Document File",
    "rst": "Document File",
    "txt": "Document File",
    "pdf": "Document File",
    # Structured data with a direct Egeria template match
    "json": "JSON Data File",
    "jsonl": "JSON Data File",
    "ndjson": "JSON Data File",
    "ipynb": "JSON Data File",  # no Jupyter-specific template; it's valid JSON
    "yaml": "YAML File",
    "yml": "YAML File",
    "xml": "XML Data File",
    "csv": "CSV Data File",
    "tsv": "CSV Data File",
    "parquet": "Parquet Data File",
    "avro": "Avro Data File",
    "xlsx": "Spreadsheet Data File",
    "xls": "Spreadsheet Data File",
    "xlsm": "Spreadsheet Data File",
    # Config -> "Properties File"
    "toml": "Properties File",
    "ini": "Properties File",
    "cfg": "Properties File",
    "env": "Properties File",
    "properties": "Properties File",
    # Archives -> "Archive File"
    "zip": "Archive File",
    "tar": "Archive File",
    "gz": "Archive File",
    "tgz": "Archive File",
    "7z": "Archive File",
    "rar": "Archive File",
    "bz2": "Archive File",
    "xz": "Archive File",
    # Compiled binaries -> "Executable File"
    "exe": "Executable File",
    "so": "Executable File",
    "dll": "Executable File",
}

# Exact filename (case-sensitive, as GitHub itself is) -> Egeria
# technology-type name — for files with no useful extension.
_TECH_TYPE_BY_NAME: dict[str, str] = {
    "Dockerfile": "Build Instruction File",
    "Makefile": "Build Instruction File",
    "Jenkinsfile": "Build Instruction File",
    # Dotfiles with no real extension per pathlib (PurePosixPath(".env").suffix
    # == "" — a leading-dot name has no stem/suffix split) — matched by exact
    # name instead.
    ".env": "Properties File",
    ".gitignore": "Properties File",
}

# Filename fragments (case-sensitive substring match) that mark a file as
# a build/CI instruction file regardless of extension — e.g.
# ".github/workflows/ci.yml", "buildspec.yml", "azure-pipelines.yml".
_BUILD_FILE_MARKERS: tuple[str, ...] = (
    "buildspec", "azure-pipelines", ".github/workflows/", "Jenkinsfile",
)

# The only confirmed-working generic fallback — deliberately NOT "File",
# which has no registered template on the live instance checked (D5a).
DEFAULT_TECHNOLOGY_TYPE = "Data File"


def resolve_technology_type(file_path: str) -> str:
    """Map a repo-relative file path to the Egeria technology-type name
    whose catalog template should be used to create its DataFile asset.

    Never raises — an unrecognized path always resolves to
    DEFAULT_TECHNOLOGY_TYPE, never to "File" (see module docstring)."""
    path = PurePosixPath(file_path)
    name = path.name

    if name in _TECH_TYPE_BY_NAME:
        return _TECH_TYPE_BY_NAME[name]

    lower_path = file_path.replace("\\", "/")
    if any(marker in lower_path for marker in _BUILD_FILE_MARKERS):
        return "Build Instruction File"

    ext = path.suffix.lstrip(".").lower()
    if ext in _TECH_TYPE_BY_EXTENSION:
        return _TECH_TYPE_BY_EXTENSION[ext]

    return DEFAULT_TECHNOLOGY_TYPE
