---
sessionId: session-260518-111831-c37i
isActive: true
---

# Requirements

### Overview & Goals
The objective is to port the existing Java `FileClassifier` and `FileClassification` classes to Python, utilizing the `pyegeria` library for Egeria metadata interactions instead of the native Java APIs.

### Scope
- **In Scope:**
    - Recreating `FileClassification` as a Python data class.
    - Recreating `FileClassifier` as a Python class.
    - Implementing `classify_file` and supporting methods in Python.
    - Using `pyegeria` to replace `ValidMetadataValuesClient` interactions.
    - Implementing caching mechanism for file reference data.
- **Out of Scope:**
    - Any changes to the original Java codebase.
    - Implementing complex error handling beyond basic mapping of the Java exceptions to Python exceptions (if applicable).

### Functional Requirements
- The Python `FileClassifier` should provide identical classification logic (filesystem attributes + Egeria metadata lookups) to the Java version.
- The Python `FileClassification` should store the same fields as the Java version.
- All file system operations should be done using standard Python `pathlib` or `os` modules.
- The `pyegeria` library should be used for all Egeria-related calls.


# Technical Design

### Current Implementation
The Java implementation (`FileClassifier.java`) uses:
- `java.nio.file.Files` and `java.io.File` for filesystem attribute retrieval (size, timestamps, read/write/execute permissions, symlink status).
- A `ValidMetadataValuesClient` (part of Egeria's Java frameworks) to query metadata (`getValidMetadataValue`, `getConsistentMetadataValues`) for file classification based on name/extension.
- A static cache (`Map<String, FileReferenceDataCache>`) to store metadata lookups.

### Proposed Changes
- **Data Model:** Create a Python `dataclass` named `FileClassification` that mirrors the Java `FileClassification`.
- **Logic:**
    - Create a Python class `FileClassifier` that takes a `pyegeria` client (or equivalent connector) in its constructor.
    - Implement `classify_file(path_name)` to:
        1. Convert to `pathlib.Path` and call `classify_file_object`.
    - Implement `classify_file_object(path: pathlib.Path)` to:
        1. **Retrieve File Attributes**:
           - Use `path.stat()` to get file size (`st_size`), last modification time (`st_mtime`), and last access time (`st_atime`). Note: Creation time (`st_ctime`) is platform-dependent (metadata change time on Unix, creation time on Windows).
           - Use `os.access(path, ...)` for `canRead`, `canWrite`, `canExecute`.
           - Use `path.is_symlink()` to determine `isSymLink`.
           - Determine `isHidden` (e.g., check for `.` prefix on file name for Unix, or Windows-specific file attributes).
        2. **Retrieve Extension**: Use `get_file_extension(path.name)`.
        3. **Metadata Lookup**:
           - Access `FileReferenceDataCache` using `fileName` and `fileExtension`.
           - If not cached, call `lookupFileReferenceData(fileName, fileExtension)` (this uses `pyegeria_client` to fetch metadata).
        4. **Return**: Populate and return a `FileClassification` instance.
    - **Caching:** Use a dictionary to cache results for `fileName` and `fileExtension` similar to the Java `fileNameReferenceDataCache` and `fileExtensionReferenceDataCache`.

### File Structure
- `pyegeria_examples/file_classifier/file_classification.py` (new)
- `pyegeria_examples/file_classifier/file_classifier.py` (new)


# Testing

### Validation Approach
- Verify `FileClassification` data class holds correct types for all fields.
- Test `FileClassifier.get_file_extension` with various filenames (e.g., `test.txt`, `.gitignore`, `archive.tar.gz`, `noextension`).
- Verify `classify_file` correctly populates filesystem attributes (size, read/write/execute, etc.) using dummy files.
- Verify `pyegeria` calls are made with correct parameters (mimicking the Java `ValidMetadataValuesClient` calls).
- Use a mock `pyegeria` client to verify metadata lookup logic and cache populating/retrieval.


# Delivery Steps

###   Step 1: Define FileClassification data class
Create a `FileClassification` Python data class that models the file classification information.\n- Use `dataclasses` for the data class definition.\n- Include all fields from the Java `FileClassification` class (e.g., `fileName`, `pathName`, `fileExtension`, etc.).\n- Add appropriate type hints and default values if necessary. ✓

###   Step 2: Implement FileClassifier and filesystem logic
Implement the `FileClassifier` Python class and its basic file system operations.\n- Implement `classify_file(path_name: str)` and `classify_file_object(path: pathlib.Path)`.\n- Use `pathlib` for file system interactions (e.g., `stat()`, `is_symlink()`, `exists()`).\n- Implement the `get_file_extension` helper method to match the Java logic.\n- Include the basic structure for the `FileReferenceDataCache` dictionary-based cache. ✓

###   Step 3: Integrate pyegeria for metadata lookup
Integrate `pyegeria` to fetch metadata for file classification.\n- Replace the Java `ValidMetadataValuesClient` with `pyegeria` methods for querying valid metadata values (`get_valid_metadata_value`, `get_consistent_metadata_values`).\n- Implement the logic to query metadata based on filename and file extension, matching the lookup logic in `FileClassifier.lookupFileReferenceData`.\n- Populate the `FileReferenceDataCache` with the results. ✓