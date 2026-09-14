"""Per-distribution deployment evidence — layer 1 of "Cataloguing in layers"
(project owner, 2026-09-14, `docs/catalogue-in-layers.md` if that lands, or
see the PR that added this module for the decision text).

Egeria's `SoftwareCapability` classified `Application` names a thing that
"supports specific business functions", hosted on a `SoftwareServer`. The
prior proposal classified every Python distribution in a workspace as a
`SoftwareLibrary` resource manager, which is a type error one level down from
the same mistake at repository scope. The fix starts here: before anything is
proposed to Egeria as an application, this module asks — for each
distribution the repository already declares (`repo_manifest_parse`'s
`distribution` findings) — whether DEPLOYMENT EVIDENCE exists for it. A
distribution is `application` only when it does; otherwise it is `library`
(importable, nothing deploys it) or `unknown` (nothing was ever manifest-
parsed, so there is no declared distribution to judge at all).

**Zero-fetch, by construction.** Every signal here is read from tables an
earlier step already wrote — `project_analysis_findings` kind="distribution"
(repo_manifest_parse's `DistributionParser`, which records console entry
points/`[project.scripts]`/`bin` and whether a publish workflow names the
ecosystem), kind="repo_conventions" check_name="deployment_docker" (Dockerfile/
compose/Helm chart PRESENCE, path only — no content), `project_file_inventory`
(path-only, for a `__main__.py` under a distribution's own package), and
`project_dependencies` (for a web-framework dependency, and for cross-
distribution consumption within the same repo). None of these signals require
downloading anything this classifier itself has not already been handed.

**What this CANNOT tell, and says so rather than guessing.** A Dockerfile's
mere presence does not say which distribution (if a repo declares more than
one) it builds, and a compose service's mere presence does not say which
distribution it names — both would need the file's CONTENT, which
`repo_conventions` never stored (only the path). When a repo declares exactly
one distribution, an unattributed Dockerfile/compose file is still real
evidence (there is nothing else it could be building) and counts. When a repo
declares more than one, the same presence is recorded as `could_not_check`
evidence rather than credited to any one of them — attributing it would be a
guess dressed as a finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Web-application/server frameworks whose mere presence in a distribution's
#: OWN manifest is corroborating (not sufficient on its own) deployment
#: evidence — already-collected `project_dependencies` rows, no new fetch.
_WEB_FRAMEWORK_DEP_PATTERNS = (
    "fastapi", "uvicorn", "flask", "django", "aiohttp", "starlette",
    "gunicorn", "hypercorn", "tornado",
    "express", "koa", "fastify", "hapi", "next",
)
#: CLI-framework dependencies — corroborating evidence for a console entry
#: point that is already the primary signal, not evidence on their own.
_CLI_FRAMEWORK_DEP_PATTERNS = ("typer", "click", "argparse", "commander", "yargs")

APPLICATION = "application"
LIBRARY = "library"
UNKNOWN = "unknown"
VERDICTS = (APPLICATION, LIBRARY, UNKNOWN)


@dataclass(frozen=True)
class EvidenceItem:
    kind: str            # console_script | dunder_main | dockerfile_present |
                          # compose_present | helm_present | web_framework_dependency
    path: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        d = {"kind": self.kind, "path": self.path}
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class DistributionEvidence:
    name: str
    ecosystem: str
    verdict: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    #: Names of OTHER distributions in this repo whose own manifest declares
    #: a dependency on this one, or None when it could not be derived (no
    #: manifest path recorded for one side of the comparison).
    consumers_in_repo: list[str] | None = None
    #: Evidence this classifier could not confirm because it would need file
    #: CONTENT no prior step stored — named, not silently dropped. Each is
    #: {"kind": ..., "reason": ...}.
    could_not_check: list[dict] = field(default_factory=list)

    def as_finding(self) -> dict:
        # check_name is the fixed category ("distribution") — the instance
        # identity lives in `detail.name`, same split dependency_support uses
        # (check_name="technology", label/detail carry the instance): the
        # per-instance identity for PUBLISHING (Egeria qualifiedName
        # uniqueness) is the Annotation's item_key, set by the surveyor from
        # this same `name`, not a column project_analysis_findings has.
        return {
            "check_name": "distribution",
            "label": self.verdict,
            "summary": self.summary(),
            "confidence": 90 if self.verdict != UNKNOWN else 0,
            "detail": {
                "name": self.name,
                "ecosystem": self.ecosystem,
                "evidence": [e.as_dict() for e in self.evidence],
                "consumers_in_repo": self.consumers_in_repo,
                "could_not_check": self.could_not_check,
            },
        }

    def summary(self) -> str:
        if self.verdict == UNKNOWN:
            return f"{self.name} — no manifest read yet, cannot judge deployment evidence"
        if self.verdict == LIBRARY:
            return f"{self.name} — importable {self.ecosystem} distribution, no deployment evidence found"
        kinds = ", ".join(sorted({e.kind for e in self.evidence}))
        return f"{self.name} — application ({kinds})"


def _looks_like_web_or_cli_dependency(dep_names: list[str], patterns: tuple[str, ...]) -> str | None:
    low_patterns = patterns
    for dep in dep_names:
        d = (dep or "").strip().lower()
        base = d.split("/")[-1] if "/" in d else d  # scoped npm packages
        for p in low_patterns:
            if base == p or base.startswith(p + "-") or base.startswith("@" + p):
                return dep
    return None


def classify_distribution(
    distribution: dict,
    *,
    all_distributions: list[dict],
    file_inventory_paths: list[str],
    docker_evidence_paths: list[str],
    dependency_rows: list[dict],
) -> DistributionEvidence:
    """Pure: one distribution's verdict + evidence.

    `distribution` is one row's `detail` dict from a `distribution`-kind
    finding (DistributionParser's shape: name, ecosystem, scripts, packages,
    manifest, publish_workflow). `all_distributions` is every such detail dict
    for the repo (needed to know whether Dockerfile/compose evidence can be
    attributed unambiguously, and to derive cross-distribution consumers).
    `docker_evidence_paths` is `repo_conventions` check_name="deployment_docker"
    detail.files (path-only). `dependency_rows` is `project_dependencies`
    (need `dep_name`, `source_file`).
    """
    name = str(distribution.get("name") or "")
    ecosystem = str(distribution.get("ecosystem") or "")
    scripts = distribution.get("scripts") or []
    packages = distribution.get("packages") or []
    manifest = str(distribution.get("manifest") or "")

    evidence: list[EvidenceItem] = []
    could_not_check: list[dict] = []

    # 1. Console entry point — [project.scripts] / bin. Strongest signal:
    # DistributionParser already reads it as a declared fact, not an
    # inference.
    for s in scripts:
        evidence.append(EvidenceItem("console_script", path=manifest, detail=s))

    # 2. A __main__.py under one of the distribution's own packages, or (no
    # packages declared) under a top-level directory matching the
    # distribution's own name — path-only match against project_file_inventory,
    # no content read.
    candidate_dirs = set(packages)
    normalized_name = name.split("/")[-1].replace("-", "_").lower()
    candidate_dirs.add(normalized_name)
    for p in file_inventory_paths:
        pl = p.replace("\\", "/").lower()
        if pl.endswith("__main__.py"):
            top = pl.split("/", 1)[0]
            if top in {c.lower() for c in candidate_dirs} or any(
                pl.startswith(f"{c.lower()}/") for c in candidate_dirs
            ):
                evidence.append(EvidenceItem("dunder_main", path=p))

    # 3/4. Dockerfile / compose / Helm presence — attributable only when this
    # repo declares exactly one distribution; otherwise recorded as
    # could_not_check, since attributing a shared file to one of several
    # distributions would need its CONTENT, which repo_conventions never
    # stored (path only).
    unambiguous = len(all_distributions) <= 1
    for p in docker_evidence_paths:
        pl = p.lower()
        if "compose" in pl:
            kind = "compose_present"
        elif "chart.yaml" in pl:
            kind = "helm_present"
        else:
            kind = "dockerfile_present"
        if unambiguous:
            evidence.append(EvidenceItem(kind, path=p))
        else:
            could_not_check.append({
                "kind": kind, "path": p,
                "reason": (f"repo declares {len(all_distributions)} distributions; attributing "
                           f"this file to '{name}' specifically would need its content, which "
                           "repo_conventions did not store"),
            })

    # 5. Web/CLI framework dependency, scoped to deps declared in THIS
    # distribution's own manifest — corroborating only, never sufficient
    # alone. Falling back to the WHOLE repo's dependency list when this
    # distribution's own manifest has none is only safe when the repo is
    # unambiguous (one distribution): live-verified 2026-09-14 against
    # egeria_trellis, where the unscoped fallback credited every
    # trellis-* shared library with "application" via fastapi/click deps
    # that actually belonged to resource-explorer/egeria-advisor's own
    # manifests — cross-distribution contamination in exactly the monorepo
    # case `unambiguous` already exists to guard against for Dockerfiles.
    own_deps = [d for d in dependency_rows if not manifest or str(d.get("source_file") or "") == manifest]
    if own_deps:
        dep_pool = own_deps
    elif unambiguous:
        dep_pool = dependency_rows
    else:
        dep_pool = []
    dep_names = [str(d.get("dep_name") or "") for d in dep_pool]
    web_hit = _looks_like_web_or_cli_dependency(dep_names, _WEB_FRAMEWORK_DEP_PATTERNS)
    if web_hit:
        evidence.append(EvidenceItem("web_framework_dependency", detail=web_hit))
    cli_hit = _looks_like_web_or_cli_dependency(dep_names, _CLI_FRAMEWORK_DEP_PATTERNS)
    if cli_hit and (scripts or evidence):
        evidence.append(EvidenceItem("cli_framework_dependency", detail=cli_hit))

    verdict = APPLICATION if evidence else LIBRARY

    # Cross-distribution consumers: another distribution in this repo whose
    # OWN manifest declares a dependency on this one's name.
    consumers: list[str] | None
    if manifest:
        consumers = []
        for other in all_distributions:
            other_name = str(other.get("name") or "")
            other_manifest = str(other.get("manifest") or "")
            if not other_manifest or other_name == name:
                continue
            other_deps = {str(d.get("dep_name") or "").strip().lower()
                          for d in dependency_rows if str(d.get("source_file") or "") == other_manifest}
            if name.strip().lower() in other_deps or normalized_name in other_deps:
                consumers.append(other_name)
    else:
        consumers = None  # no manifest path recorded — cannot derive

    return DistributionEvidence(
        name=name, ecosystem=ecosystem, verdict=verdict,
        evidence=evidence, consumers_in_repo=consumers, could_not_check=could_not_check,
    )


@dataclass
class RepoDeploymentEvidence:
    """One repository's result — every declared distribution, classified."""
    distributions: list[DistributionEvidence]
    #: True when repo_manifest_parse has never run for this repo — no
    #: `distribution` finding rows exist at all, so nothing here could be
    #: judged (all verdicts read `unknown`, not a real "no applications").
    no_manifest_read: bool = False

    @property
    def counts(self) -> dict[str, int]:
        out = {v: 0 for v in VERDICTS}
        for d in self.distributions:
            out[d.verdict] += 1
        return out

    def as_findings(self) -> list[dict]:
        rows = [d.as_finding() for d in self.distributions]
        c = self.counts
        rows.append({
            "check_name": "coverage",
            "label": "no_manifest_read" if self.no_manifest_read else "checked",
            "summary": (f"{c[APPLICATION]} application(s), {c[LIBRARY]} librar{'y' if c[LIBRARY]==1 else 'ies'}, "
                        f"{c[UNKNOWN]} unknown" if not self.no_manifest_read else
                        "No declared distributions to judge — repo_manifest_parse has not run"),
            "confidence": 100 if not self.no_manifest_read else 0,
            "detail": {**c, "distribution_count": len(self.distributions)},
        })
        return rows


def assess(
    distribution_findings: list[dict], *,
    file_inventory_paths: list[str],
    docker_evidence_paths: list[str],
    dependency_rows: list[dict],
) -> RepoDeploymentEvidence:
    """Pure: classify every declared distribution for a repo.

    `distribution_findings` are `project_analysis_findings` rows kind=
    "distribution" (each row's `detail` is DistributionParser's shape).
    """
    if not distribution_findings:
        return RepoDeploymentEvidence(distributions=[], no_manifest_read=True)

    details = [f.get("detail") or {} for f in distribution_findings]
    out = [
        classify_distribution(
            d, all_distributions=details,
            file_inventory_paths=file_inventory_paths,
            docker_evidence_paths=docker_evidence_paths,
            dependency_rows=dependency_rows,
        )
        for d in details
    ]
    return RepoDeploymentEvidence(distributions=out, no_manifest_read=False)
