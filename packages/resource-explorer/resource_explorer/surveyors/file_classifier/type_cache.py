"""
Local cache of file-type mappings, optionally refreshed from Egeria ValidMetadataValues.

The cache persists as a JSON file so the surveyor works offline.  When Egeria
credentials are present the cache is refreshed on demand (e.g. once per day or
when --refresh is passed).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_CACHE_PATH = Path("data/file_type_cache.json")
_REFRESH_AFTER_HOURS = 24

# Built-in defaults — used when the Egeria cache is empty or a key is missing.
# Egeria ValidMetadataValues take priority when available.
_BUILTIN_BY_EXTENSION: dict[str, dict] = {
    # Python
    "py":    {"deployedImplementationType": "Python Source File"},
    "pyi":   {"deployedImplementationType": "Python Source File"},
    "ipynb": {"deployedImplementationType": "Jupyter Notebook"},
    # Web / JS
    "js":    {"deployedImplementationType": "JavaScript Source"},
    "mjs":   {"deployedImplementationType": "JavaScript Source"},
    "cjs":   {"deployedImplementationType": "JavaScript Source"},
    "ts":    {"deployedImplementationType": "TypeScript Source"},
    "tsx":   {"deployedImplementationType": "TypeScript Source"},
    "jsx":   {"deployedImplementationType": "JavaScript Source"},
    "html":  {"deployedImplementationType": "HTML File"},
    "htm":   {"deployedImplementationType": "HTML File"},
    "css":   {"deployedImplementationType": "CSS Stylesheet"},
    # JVM
    "java":  {"deployedImplementationType": "Java Source"},
    "kt":    {"deployedImplementationType": "Kotlin Source"},
    "scala": {"deployedImplementationType": "Scala Source"},
    # Go / Rust / C
    "go":    {"deployedImplementationType": "Go Source"},
    "rs":    {"deployedImplementationType": "Rust Source"},
    "c":     {"deployedImplementationType": "C Source"},
    "h":     {"deployedImplementationType": "C Header"},
    "cpp":   {"deployedImplementationType": "C++ Source"},
    "cc":    {"deployedImplementationType": "C++ Source"},
    "hpp":   {"deployedImplementationType": "C++ Header"},
    # Docs
    "md":    {"deployedImplementationType": "Markdown Document"},
    "mdx":   {"deployedImplementationType": "Markdown Document"},
    "rst":   {"deployedImplementationType": "reStructuredText Document"},
    "txt":   {"deployedImplementationType": "Text File"},
    "pdf":   {"deployedImplementationType": "PDF Document"},
    # Config / data
    "toml":  {"deployedImplementationType": "TOML Configuration"},
    "yaml":  {"deployedImplementationType": "YAML Configuration"},
    "yml":   {"deployedImplementationType": "YAML Configuration"},
    "json":  {"deployedImplementationType": "JSON File"},
    "xml":   {"deployedImplementationType": "XML File"},
    "cfg":   {"deployedImplementationType": "Configuration File"},
    "ini":   {"deployedImplementationType": "Configuration File"},
    "env":   {"deployedImplementationType": "Environment Configuration"},
    "lock":  {"deployedImplementationType": "Dependency Lock File"},
    # Shell / scripts
    "sh":    {"deployedImplementationType": "Shell Script"},
    "bash":  {"deployedImplementationType": "Shell Script"},
    "zsh":   {"deployedImplementationType": "Shell Script"},
    "bat":   {"deployedImplementationType": "Batch Script"},
    "ps1":   {"deployedImplementationType": "PowerShell Script"},
    # SQL
    "sql":   {"deployedImplementationType": "SQL Script"},
    # Tabular / structured data
    "csv":      {"deployedImplementationType": "CSV Data File"},
    "tsv":      {"deployedImplementationType": "CSV Data File"},
    "tab":      {"deployedImplementationType": "CSV Data File"},
    "psv":      {"deployedImplementationType": "CSV Data File"},
    "xlsx":     {"deployedImplementationType": "Excel Spreadsheet"},
    "xls":      {"deployedImplementationType": "Excel Spreadsheet"},
    "xlsm":     {"deployedImplementationType": "Excel Spreadsheet"},
    "xlsb":     {"deployedImplementationType": "Excel Spreadsheet"},
    "ods":      {"deployedImplementationType": "OpenDocument Spreadsheet"},
    # Columnar / binary data formats
    "parquet":  {"deployedImplementationType": "Parquet Data File"},
    "avro":     {"deployedImplementationType": "Avro Data File"},
    "orc":      {"deployedImplementationType": "ORC Data File"},
    "arrow":    {"deployedImplementationType": "Arrow Data File"},
    "feather":  {"deployedImplementationType": "Arrow Data File"},
    "ipc":      {"deployedImplementationType": "Arrow Data File"},
    # HDF5 / NumPy
    "h5":       {"deployedImplementationType": "HDF5 Data File"},
    "hdf5":     {"deployedImplementationType": "HDF5 Data File"},
    "hdf":      {"deployedImplementationType": "HDF5 Data File"},
    "he5":      {"deployedImplementationType": "HDF5 Data File"},
    "npy":      {"deployedImplementationType": "NumPy Array File"},
    "npz":      {"deployedImplementationType": "NumPy Archive File"},
    # JSON variants
    "jsonl":    {"deployedImplementationType": "JSON Lines Data File"},
    "ndjson":   {"deployedImplementationType": "JSON Lines Data File"},
    "geojson":  {"deployedImplementationType": "GeoJSON File"},
    # Serialisation / caches
    "pkl":      {"deployedImplementationType": "Pickle Data File"},
    "pickle":   {"deployedImplementationType": "Pickle Data File"},
    "joblib":   {"deployedImplementationType": "Pickle Data File"},
    "msgpack":  {"deployedImplementationType": "MessagePack Data File"},
    # Databases
    "db":       {"deployedImplementationType": "SQLite Database"},
    "sqlite":   {"deployedImplementationType": "SQLite Database"},
    "sqlite3":  {"deployedImplementationType": "SQLite Database"},
    "duckdb":   {"deployedImplementationType": "DuckDB Database"},
    # Compressed archives
    "gz":       {"deployedImplementationType": "Compressed Archive"},
    "bz2":      {"deployedImplementationType": "Compressed Archive"},
    "xz":       {"deployedImplementationType": "Compressed Archive"},
    "zst":      {"deployedImplementationType": "Compressed Archive"},
    "tar":      {"deployedImplementationType": "Archive File"},
    "tgz":      {"deployedImplementationType": "Archive File"},
    "zip":      {"deployedImplementationType": "Archive File"},
    "rar":      {"deployedImplementationType": "Archive File"},
    "7z":       {"deployedImplementationType": "Archive File"},
    # ML model artifacts
    "pt":           {"deployedImplementationType": "PyTorch Model"},
    "pth":          {"deployedImplementationType": "PyTorch Model"},
    "ckpt":         {"deployedImplementationType": "Model Checkpoint"},
    "safetensors":  {"deployedImplementationType": "SafeTensors Model"},
    "onnx":         {"deployedImplementationType": "ONNX Model"},
    "pb":           {"deployedImplementationType": "TensorFlow Model"},
    "mlmodel":      {"deployedImplementationType": "Core ML Model"},
    "bin":          {"deployedImplementationType": "Binary Data File"},
    # Images
    "png":   {"deployedImplementationType": "Image File"},
    "jpg":   {"deployedImplementationType": "Image File"},
    "jpeg":  {"deployedImplementationType": "Image File"},
    "gif":   {"deployedImplementationType": "Image File"},
    "svg":   {"deployedImplementationType": "SVG Image"},
    "ico":   {"deployedImplementationType": "Image File"},
}

_BUILTIN_BY_NAME: dict[str, dict] = {
    "Dockerfile":        {"deployedImplementationType": "Dockerfile"},
    "Makefile":          {"deployedImplementationType": "Makefile"},
    "Justfile":          {"deployedImplementationType": "Makefile"},
    "LICENSE":           {"deployedImplementationType": "License File"},
    "LICENCE":           {"deployedImplementationType": "License File"},
    "NOTICE":            {"deployedImplementationType": "License File"},
    ".gitignore":        {"deployedImplementationType": "Git Configuration"},
    ".gitattributes":    {"deployedImplementationType": "Git Configuration"},
    "requirements.txt":  {"deployedImplementationType": "Python Requirements"},
    "pyproject.toml":    {"deployedImplementationType": "Python Project Config"},
    "setup.py":          {"deployedImplementationType": "Python Setup Script"},
    "setup.cfg":         {"deployedImplementationType": "Python Setup Config"},
    "Pipfile":           {"deployedImplementationType": "Pipenv Config"},
    "Pipfile.lock":      {"deployedImplementationType": "Dependency Lock File"},
    "package.json":      {"deployedImplementationType": "Node.js Package Config"},
    "package-lock.json": {"deployedImplementationType": "Dependency Lock File"},
    "yarn.lock":         {"deployedImplementationType": "Dependency Lock File"},
    "go.mod":            {"deployedImplementationType": "Go Module Config"},
    "go.sum":            {"deployedImplementationType": "Dependency Lock File"},
    "Cargo.toml":        {"deployedImplementationType": "Rust Package Config"},
    "Cargo.lock":        {"deployedImplementationType": "Dependency Lock File"},
    "pom.xml":           {"deployedImplementationType": "Maven Build Config"},
    "build.gradle":      {"deployedImplementationType": "Gradle Build Config"},
    "build.gradle.kts":  {"deployedImplementationType": "Gradle Build Config"},
}


class FileTypeCache:
    """
    Two-level lookup: filename → metadata, extension → metadata.

    Cache file structure:
    {
      "refreshed_at": "2026-05-18T12:00:00",
      "by_name": {"Dockerfile": {"fileType": "Docker", ...}, ...},
      "by_extension": {"py": {"fileType": "Python Source", ...}, ...}
    }
    """

    def __init__(self, cache_path: Path = _DEFAULT_CACHE_PATH) -> None:
        self._path = cache_path
        self._by_name: dict[str, dict] = {}
        self._by_ext: dict[str, dict] = {}
        self._refreshed_at: datetime | None = None
        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def lookup(self, file_name: str, extension: str | None) -> dict[str, Any]:
        """Return metadata dict (may be empty) for the given file.

        Priority: Egeria cache by name → Egeria cache by extension →
                  built-in by name → built-in by extension → empty dict.
        """
        if file_name in self._by_name:
            return self._by_name[file_name]
        if extension and extension in self._by_ext:
            return self._by_ext[extension]
        # Fall back to built-in defaults (no Egeria required)
        if file_name in _BUILTIN_BY_NAME:
            return _BUILTIN_BY_NAME[file_name]
        if extension and extension in _BUILTIN_BY_EXTENSION:
            return _BUILTIN_BY_EXTENSION[extension]
        return {}

    def needs_refresh(self) -> bool:
        if self._refreshed_at is None:
            return True
        return datetime.utcnow() - self._refreshed_at > timedelta(hours=_REFRESH_AFTER_HOURS)

    def refresh_from_egeria(self, pyegeria_client) -> None:
        """Pull ValidMetadataValues from Egeria and rebuild the cache."""
        try:
            by_name: dict[str, dict] = {}
            by_ext: dict[str, dict] = {}

            for prop_name, target in [("fileName", by_name), ("fileExtension", by_ext)]:
                try:
                    values = pyegeria_client.get_valid_metadata_values(
                        property_name=prop_name,
                        type_name="DataFile",
                    )
                    if not isinstance(values, list):
                        continue
                    for v in values:
                        props = v.get("properties", {})
                        key = props.get("preferredValue") or props.get("displayName", "")
                        add = props.get("additionalProperties", {})
                        if key:
                            target[key] = {
                                "fileType": add.get("fileType"),
                                "assetTypeName": add.get("assetTypeName"),
                                "encoding": add.get("encoding"),
                                "deployedImplementationType": add.get("deployedImplementationType"),
                            }
                except Exception as exc:
                    log.warning("FileTypeCache: failed to fetch %s from Egeria: %s", prop_name, exc)

            self._by_name = by_name
            self._by_ext = by_ext
            self._refreshed_at = datetime.utcnow()
            self._save()
            log.info(
                "FileTypeCache: refreshed — %d names, %d extensions",
                len(by_name),
                len(by_ext),
            )
        except Exception as exc:
            log.warning("FileTypeCache: refresh failed, using existing cache: %s", exc)

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._by_name = data.get("by_name", {})
            self._by_ext = data.get("by_extension", {})
            ts = data.get("refreshed_at")
            self._refreshed_at = datetime.fromisoformat(ts) if ts else None
        except Exception as exc:
            log.warning("FileTypeCache: could not load cache from %s: %s", self._path, exc)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {
                        "refreshed_at": self._refreshed_at.isoformat() if self._refreshed_at else None,
                        "by_name": self._by_name,
                        "by_extension": self._by_ext,
                    },
                    indent=2,
                )
            )
        except Exception as exc:
            log.warning("FileTypeCache: could not save cache to %s: %s", self._path, exc)


# Module-level singleton — shared across all FileClassifier instances in a process.
_cache: FileTypeCache | None = None


def get_cache(cache_path: Path = _DEFAULT_CACHE_PATH) -> FileTypeCache:
    global _cache
    if _cache is None:
        _cache = FileTypeCache(cache_path)
    return _cache
