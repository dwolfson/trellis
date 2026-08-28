"""Which collection types is a project now eligible for, but not ingesting?

Collections are proposed once, by the onboarding wizard, from a scan of the
repo at the moment it was added. Nothing re-evaluates them afterwards, so a
repo that gains PDFs -- or its first notebook, or a new language -- keeps
ingesting exactly what it ingested on day one. `egeria_docs` is the case that
surfaced this: 15 PDFs sitting in `saved/education/`, inventoried by the
pipeline itself, and no `pdfs` collection to offer them to.

**This is a query, not a scan.** `project_file_inventory` already records every
path in the repo, so eligibility can be recomputed from data RE has already
collected -- no download, no walk, no GitHub call. That is what makes it cheap
enough to run on every refresh.

**It reports; it does not enable.** Turning a collection on changes what gets
embedded and costs real ingestion time, so the decision stays with a person.

**Eligibility mirrors what onboarding would actually propose**, not a plain
extension match. The first version of this module matched extensions alone and
reported "examples: 4583 matching files" for the Egeria repo -- every .java file
in it -- and "api_reference: 46" for GitHub workflow YAML. Both are things the
wizard would never propose: `examples` keys on RepoAnalyzer.EXAMPLE_DIRS
(directory names) and `api_reference` on RepoAnalyzer.API_SPEC_NAMES (specific
filenames). A check that cries wolf on a 4,583-file false positive is a check
nobody reads, so this defers to the same rules onboarding uses.
"""
from __future__ import annotations

from dataclasses import dataclass

from resource_explorer.configdata.collection_config import COLLECTION_TYPES
from resource_explorer.github.analyzer import RepoAnalyzer


# Collection types whose content comes from an API rather than the repo tree.
_API_SOURCED = frozenset({"release_notes"})


@dataclass(frozen=True)
class DriftFinding:
    collection_type: str
    matching_files: int
    min_required: int
    sample_paths: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        return (
            f"{self.collection_type}: {self.matching_files} matching file(s) "
            f"(needs {self.min_required})"
        )


def enabled_types(slug: str, collections: list[str] | None) -> set[str]:
    """Collection type names already active for a project.

    Names are not uniform: per-project collections are "{slug}_{type}"
    (pipeline.py:134), but shared ones are "{type}_{something}" -- e.g.
    "web_docs_egeria_project_org", which several projects share. Matching only
    the first shape would report web_docs as missing on every project using the
    shared one, which is the sort of false positive that gets a check ignored.
    """
    active: set[str] = set()
    for name in collections or []:
        for ctype in COLLECTION_TYPES:
            if name == f"{slug}_{ctype}" or name.startswith(f"{ctype}_") or name.endswith(f"_{ctype}"):
                active.add(ctype)
    return active


def detect_drift(registry, slug: str, *, sample: int = 3) -> list[DriftFinding]:
    """Collection types this project's files would qualify for but that are
    not enabled. Empty list means no drift -- not an error, and the common case.
    """
    project = registry.get(slug)
    if not project:
        return []

    active = enabled_types(slug, project.collections)
    candidates = {n: c for n, c in COLLECTION_TYPES.items() if n not in active}
    if not candidates:
        return []

    paths = registry.get_file_inventory(slug)
    if not paths:
        # No inventory yet (never indexed) is not drift: there is nothing to
        # be wrong about, and reporting every collection type as "missing"
        # would be noise on a fresh project.
        return []

    findings: list[DriftFinding] = []
    for name, ctype in candidates.items():
        hits = _eligible_paths(name, ctype, paths)
        if hits is None:
            continue
        minimum = getattr(ctype, "min_file_count", 1) or 1
        if len(hits) >= minimum:
            findings.append(DriftFinding(
                collection_type=name, matching_files=len(hits),
                min_required=minimum, sample_paths=tuple(sorted(hits)[:sample]),
            ))
    return sorted(findings, key=lambda f: (-f.matching_files, f.collection_type))


def _eligible_paths(name: str, ctype, paths: list[str]) -> list[str] | None:
    """Paths that make a project eligible for a collection type.

    None means "cannot be judged from files" -- release_notes comes from the
    GitHub releases API, so no file count speaks to it and silence is correct.
    """
    if name in _API_SOURCED:
        # release_notes declares .md/.txt extensions, but _ingest_releases
        # reads repo.get_releases() -- the GitHub API -- and never touches a
        # file. Its extensions are vestigial, and matching on them reported
        # every markdown file in a docs repo (4,226 of them) as evidence for a
        # collection that would not have read one.
        return None
    if name == "examples":
        dirs = tuple(d.lower() for d in RepoAnalyzer.EXAMPLE_DIRS)
        return [p for p in paths if p.lower().split("/", 1)[0] in dirs]
    if name == "api_reference":
        names = {n.lower() for n in RepoAnalyzer.API_SPEC_NAMES}
        return [p for p in paths if p.lower().rsplit("/", 1)[-1] in names]

    exts = tuple(e.lower() for e in (ctype.file_extensions or []))
    if not exts:
        return None
    return [p for p in paths if p.lower().endswith(exts)]
