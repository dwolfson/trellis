"""Sub-surveyor: repo sub-resource survey → ClassificationAnnotation.

Assessment sub-resource cataloging plan (docs/assessment-sub-resource-
cataloging.md) — this is the *survey* half, explicitly separate from
*cataloging* (EgeriaPublisher._catalog_sub_resources() does that, later,
consuming this surveyor's finding). This surveyor never talks to Egeria.

D1: walks `project_file_inventory` (already persisted, no new fetch) to
determine which top-level folders and which well-known files are "worthy"
of becoming their own Egeria asset later — a recommendation, not a side
effect. D9: also captures metadata tiered by cost — free/whole-repo
(mode, size, CODEOWNERS-derived ownership) vs. expensive/worthy-subset-only
(last-updated/first-added commit dates, since there is no batch git-history
API). D10/D11: size/mode distributions persisted as metric snapshots,
append-only, for growth-over-time trending.
"""
from __future__ import annotations

import fnmatch
import logging
from datetime import datetime

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "SubResourceSurvey"

# D1 — well-known-significant filenames, matched by basename at any depth
# up to max_depth. Kept intentionally small and explainable in one line
# each; expected to need tuning after live use (see "Explicitly deferred").
_WELL_KNOWN_FILES = {
    "SECURITY.md", "LICENSE", "LICENSE.md", "LICENSE.txt",
    "CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "README.md", "CHANGELOG.md",
}

# D1 — a depth-1 folder's file count must fall in this range to be worthy
# ("meaningfully browsable" — not a lone file, not an unfiltered dump like
# node_modules). First-pass default, not validated against real repos yet.
_FOLDER_MIN_FILES = 2
_FOLDER_MAX_FILES = 200

# D10 — size-bucket boundaries in bytes. First-pass default.
_SIZE_BUCKETS = [
    ("<1KB", 0, 1_000),
    ("1KB-10KB", 1_000, 10_000),
    ("10KB-100KB", 10_000, 100_000),
    ("100KB-1MB", 100_000, 1_000_000),
    (">1MB", 1_000_000, None),
]

# D9 — where CODEOWNERS is looked for, in GitHub's own lookup order.
_CODEOWNERS_PATHS = ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"]


def _mode_kind(mode: str) -> str:
    """Coarse mode_distribution bucket from a raw git tree mode string."""
    if mode == "120000":
        return "symlink"
    if mode == "100755":
        return "executable"
    if mode == "100644":
        return "regular"
    return "unknown"


def _size_bucket(size: int) -> str:
    for label, lo, hi in _SIZE_BUCKETS:
        if size >= lo and (hi is None or size < hi):
            return label
    return _SIZE_BUCKETS[-1][0]


def _parse_codeowners(text: str) -> list[tuple[str, list[str]]]:
    """Return [(pattern, [owners])] in file order — CODEOWNERS' own rule is
    "last matching pattern wins", so callers must scan in this order and
    keep the last match, not the first."""
    rules: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, owners = parts[0], parts[1:]
        rules.append((pattern, owners))
    return rules


def _codeowners_match(path: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    """CODEOWNERS semantics: last matching pattern in the file wins."""
    owners: list[str] = []
    for pattern, pattern_owners in rules:
        candidate = pattern.lstrip("/")
        if candidate.endswith("/"):
            candidate += "*"
        if fnmatch.fnmatch(path, candidate) or fnmatch.fnmatch(path, f"{candidate}/*") or fnmatch.fnmatch(f"/{path}", pattern):
            owners = pattern_owners
    return owners


class SubResourceSurveyor(BaseSurveyor):
    """Reads project_file_inventory, produces a worthiness recommendation
    list (folders + well-known files) plus size/mode distribution metrics.
    Never calls Egeria — cataloging is EgeriaPublisher's job, later."""

    def __init__(
        self,
        project: Project,
        registry: ProjectRegistry,
        surveyed_at: str | None = None,
        max_depth: int = 2,
    ) -> None:
        super().__init__(project, registry)
        self._surveyed_at = surveyed_at or datetime.utcnow().isoformat()
        self._max_depth = max_depth

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            inventory = self.registry.get_file_inventory_with_sizes(self.project.slug)
            if not inventory:
                results.append(
                    ClassificationAnnotation(
                        summary="No file inventory available — run a Profile refresh first",
                        analysis_step=STEP,
                        candidate_classifications=[],
                        confidence=50,
                    )
                )
                return results

            findings = self._build_findings(inventory)
            worthy = [f for f in findings if f["worthy"]]

            self.registry.upsert_finding(
                self.project.slug, "repo_sub_resource_survey",
                [
                    {
                        "check_name": f["path"] or "(root)",
                        "label": "worthy" if f["worthy"] else "not_worthy",
                        "summary": f["reason"],
                        "confidence": 100,
                        "detail": {
                            "path": f["path"], "kind": f["entry_kind"], "reason": f["reason"],
                            "owners": f["owners"],
                            **({"last_updated_at": f["last_updated_at"]} if "last_updated_at" in f else {}),
                            **({"first_added_at": f["first_added_at"]} if "first_added_at" in f else {}),
                        },
                    }
                    for f in findings
                ],
                surveyed_at=self._surveyed_at,
            )

            self._persist_distributions(inventory)

            results.append(
                ClassificationAnnotation(
                    summary=(
                        f"Sub-resource survey: {len(findings)} considered, "
                        f"{len(worthy)} recommended for cataloging"
                    ),
                    analysis_step=STEP,
                    candidate_classifications=[f["path"] or "(root)" for f in worthy],
                    confidence=100,
                    json_properties={"considered": len(findings), "worthy": len(worthy)},
                )
            )
        except Exception as exc:
            log.exception("SubResourceSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results

    # ── D1: worthiness heuristics ────────────────────────────────────────

    def _build_findings(self, inventory: list[dict]) -> list[dict]:
        owners_rules = self._codeowners_rules()
        findings: list[dict] = []

        # Well-known files, any depth up to max_depth.
        worthy_root_files: list[dict] = []
        for entry in inventory:
            path = entry["file_path"].replace("\\", "/")
            depth = path.count("/") + 1  # "README.md" -> depth 1, "docs/README.md" -> depth 2
            if depth > self._max_depth:
                continue
            name = path.rsplit("/", 1)[-1]
            if name not in _WELL_KNOWN_FILES:
                continue
            finding = {
                "path": path, "entry_kind": "file", "worthy": True,
                "reason": "well_known_file",
                "owners": _codeowners_match(path, owners_rules),
            }
            findings.append(finding)
            if "/" not in path:
                worthy_root_files.append(finding)

        # Depth-1 folders.
        folder_counts: dict[str, int] = {}
        for entry in inventory:
            path = entry["file_path"].replace("\\", "/")
            if "/" not in path:
                continue
            top = path.split("/", 1)[0]
            folder_counts[top] = folder_counts.get(top, 0) + 1

        for folder, count in sorted(folder_counts.items()):
            if count < _FOLDER_MIN_FILES:
                worthy, reason = False, "too_small"
            elif count > _FOLDER_MAX_FILES:
                worthy, reason = False, "too_broad"
            else:
                worthy, reason = True, "top_level_structural_folder"
            findings.append({
                "path": folder, "entry_kind": "folder", "worthy": worthy,
                "reason": reason,
                "owners": _codeowners_match(folder, owners_rules),
            })

        # Synthetic root folder — required whenever a root-level file is
        # worthy, since NestedFile strictly requires a FileFolder parent
        # (D4/D5, confirmed live: a file can never attach directly to the
        # repo's SourceControlLibrary asset).
        if worthy_root_files:
            findings.append({
                "path": "", "entry_kind": "folder", "worthy": True,
                "reason": "root_container_for_worthy_files",
                "owners": [],
            })

        self._attach_tier2_dates(findings)
        return findings

    def _codeowners_rules(self) -> list[tuple[str, list[str]]]:
        """D9/D12 — one file fetch, best-effort. Never raises; a missing/
        unreachable CODEOWNERS just means every entry gets owners=[]."""
        try:
            from resource_explorer.github.client import GitHubClient
            client = GitHubClient()
            repo = client.get_repo(self.project.github_url)
            for path in _CODEOWNERS_PATHS:
                content = client.get_file_content(repo, path)
                if content:
                    return _parse_codeowners(content)
        except Exception:
            pass
        return []

    def _attach_tier2_dates(self, findings: list[dict]) -> None:
        """D9 Tier 2 — last-updated/first-added commit dates, fetched only
        for worthy entries (never the full inventory — see the plan's
        "Metadata capture" section on why a full-repo staleness pass isn't
        affordable). Best-effort per entry; a failure just omits the dates
        for that one entry rather than failing the whole survey."""
        worthy = [f for f in findings if f["worthy"] and f["path"]]
        if not worthy:
            return
        try:
            from resource_explorer.github.client import GitHubClient
            client = GitHubClient()
            repo = client.get_repo(self.project.github_url)
        except Exception:
            return

        for finding in worthy:
            try:
                commits = repo.get_commits(path=finding["path"])
                if commits.totalCount == 0:
                    continue
                finding["last_updated_at"] = commits[0].commit.author.date.isoformat()
                finding["first_added_at"] = commits[commits.totalCount - 1].commit.author.date.isoformat()
            except Exception:
                continue

    # ── D10/D11: full-repo distributions, append-only ────────────────────

    def _persist_distributions(self, inventory: list[dict]) -> None:
        # One combined upsert_metric() call, not two — upsert_metric()
        # attaches `detail` only to the first metric row of a call, so two
        # separate calls at the same surveyed_at would leave query_metrics()'
        # single `detail` key ambiguous between size_buckets/mode_counts
        # (whichever row SELECT happened to return last). One call with a
        # combined detail dict avoids that ambiguity entirely.
        size_buckets: dict[str, int] = {}
        total_bytes = 0
        for entry in inventory:
            size = entry["file_size_bytes"] or 0
            total_bytes += size
            bucket = _size_bucket(size)
            size_buckets[bucket] = size_buckets.get(bucket, 0) + 1

        mode_counts: dict[str, int] = {}
        for entry in inventory:
            kind = _mode_kind(entry.get("file_mode") or "")
            mode_counts[kind] = mode_counts.get(kind, 0) + 1

        metrics = {"total_size_bytes": float(total_bytes), "file_count": float(len(inventory))}
        metrics.update({f"mode_{k}_count": float(v) for k, v in mode_counts.items()})

        self.registry.upsert_metric(
            self.project.slug, "repo_sub_resource_survey", metrics,
            detail={"size_buckets": size_buckets, "mode_counts": mode_counts},
            surveyed_at=self._surveyed_at,
        )
