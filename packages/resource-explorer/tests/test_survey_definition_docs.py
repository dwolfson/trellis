"""resource_type inference in survey_definition_docs.py.

Was hardcoded "repo" at the route level (survey_definitions.py's
list_definitions()) regardless of what a document actually was — harmless
while every authored document happened to be repo-scoped, but would have
silently mislabeled the first database/filesystem Survey Definition ever
authored. Now read from the source filename's
`{resource_type}-survey-definition-*.md` convention.
"""
from __future__ import annotations

from pathlib import Path

from resource_explorer.surveyors import survey_definition_docs as D

_MINIMAL_DOC = """\
## Create Governance Action Process
### Qualified Name
GovActionProcess::X

## Create Governance Action Process Step
### Qualified Name
GovActionProcessStep::X::step_one
"""


def _write(tmp_path: Path, filename: str) -> Path:
    directory = tmp_path / "survey-definitions"
    directory.mkdir(exist_ok=True)
    path = directory / filename
    path.write_text(_MINIMAL_DOC)
    return directory


class TestResourceTypeFromFilename:
    def test_repo_prefix(self):
        assert D._resource_type_from_filename(Path("repo-survey-definition-full.md")) == "repo"

    def test_database_prefix(self):
        assert D._resource_type_from_filename(Path("database-survey-definition-full.md")) == "database"

    def test_filesystem_prefix(self):
        assert D._resource_type_from_filename(Path("filesystem-survey-definition-full.md")) == "filesystem"

    def test_unrecognized_prefix_falls_back_to_repo(self):
        """Matches the dataclass field's own default — a document following
        some other naming scheme entirely is not evidence it's a NEW
        resource type, just an unrecognized one."""
        assert D._resource_type_from_filename(Path("something-else.md")) == "repo"


class TestDocumentedDefinitionsSetsResourceType:
    def test_repo_document_gets_repo(self, tmp_path):
        directory = _write(tmp_path, "repo-survey-definition-x.md")
        docs = D.documented_definitions(directory)
        assert docs["X"].resource_type == "repo"

    def test_database_document_gets_database(self, tmp_path):
        directory = _write(tmp_path, "database-survey-definition-x.md")
        docs = D.documented_definitions(directory)
        assert docs["X"].resource_type == "database"

    def test_filesystem_document_gets_filesystem(self, tmp_path):
        directory = _write(tmp_path, "filesystem-survey-definition-x.md")
        docs = D.documented_definitions(directory)
        assert docs["X"].resource_type == "filesystem"
