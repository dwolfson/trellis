"""Sub-surveyor: what can you talk to, and is the contract written down?

Answers two of the questions in the catalog from data already collected — the
file inventory, the parsed dependencies, and (new, §6 of
`SPEC-ACTIONABLE-AND-HONEST.md`) the two other walks that already know facts
this one used to ignore: `distribution` findings (repo_manifest_parse's
DistributionParser — `[project.scripts]`/`package.json bin`) and
`deployment_evidence` findings (a `__main__.py` under the distribution's own
package). No fetch either way — everything here is a second READ of a table
another step already wrote, never a second parse of the manifest itself.

    "What kind of interfaces does it have?"  -> the interface kinds below
    "Is there a published API?"              -> the `published_spec` finding

One analysis rather than two, because the second is a finding ABOUT the
first: a library with 171 exported symbols has an interface surface and no
published contract, and answering those separately would mean re-deriving
the same evidence twice and letting the two disagree.

**Three rungs, not two — the vendored-rule defect one analytic over.** The
old two-rung ladder ("specified" / "implied") put almost everything on the
wrong rung: a `[project.scripts]` entry point IS the CLI, not a hint of one,
and the old code answered "cli — implied. Depends on click" for a repo whose
own manifest names the entry point — a fact `repo_role.py`,
`distribution_parser.py` ("the CLI entry point as a fact"), and
`deployment_evidence.py` (#94, a console entry point is the strongest signal)
already knew and this file never read. That is the same shape as the
vendored-walk defect: a fact known by one walk and not read by another,
producing a confident sentence the repository itself contradicts.

  declared     a contract committed in the repo (openapi.yaml, .proto, …),
               OR an entry point the packaging declares
               ([project.scripts]/package.json bin) — read from the SAME
               `distribution` finding rows deployment_evidence.py reads,
               never a second parse of pyproject.toml/package.json.
  implemented  the interface exists in the code whether or not anything
               documents it. From stored evidence when it exists — a
               `__main__.py` under the distribution's own package
               (deployment_evidence's `dunder_main` evidence, itself
               path-only, no content read) is implemented-CLI evidence with
               no declared entry point. Where no prior step recorded the
               fact (FastAPI/Flask/Starlette route decorators, grpc service
               methods, graphql resolvers — nothing in this codebase records
               those; `arch_recovery`'s ast-grep code markers do, but that
               walk fetches a fresh zipball and is not Discovery-tier, so
               its output is not a fact this zero-fetch analysis may read),
               the rung is reported `could_not_check` with the reason, and
               the finding SAYS SO rather than silently guessing `implied`.
  implied      a dependency suggests an interface and nothing confirms it —
               and only reached when neither higher rung applies for that
               interface kind.

Measured across the catalog on 2026-08-26 to ground the detection rather than
guess at it: 9 openapi/swagger files across 4 repos, 32 .proto across 4, 2
GraphQL schemas across 2 — while 17 repos depend on an HTTP framework and 22 on
a CLI framework. The two sources disagree far more often than they overlap,
which is exactly why they are not merged into one verdict.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.step_outcome import StepOutcome, no_signal
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "InterfaceSurface"

#: Said once, so the annotation and the persisted finding cannot drift apart.
_NOTHING_TO_ASSESS = ("Neither a file inventory nor parsed dependencies are "
                             "recorded, so no interface could be detected — this is "
                             "not a finding that it exposes none. Run the file "
                             "inventory and dependency analyses first.")

#: The three-rung ladder (§6). `DECLARED` and `IMPLEMENTED` are both strong —
#: a committed contract or a packaging-declared entry point is exactly as
#: much a fact as code that provably runs; `IMPLIED` is a guess from a
#: dependency name. `SPECIFIED` is kept as the OLD label, still emitted
#: nowhere new but read by `curate_plan.py`, which has not been migrated —
#: see that module's comment. `detect()` itself never emits `SPECIFIED`
#: after this change; it emits `DECLARED`.
DECLARED = "declared"
IMPLEMENTED = "implemented"
IMPLIED = "implied"
#: Kept only as the historical name for DECLARED-via-spec-file, referenced by
#: a comment below; not used as a label value.
SPECIFIED = DECLARED

#: Confidence by rung — declared/implemented are both facts (packaging
#: manifest or running code), implied is a guess from a dependency name.
#: Kept as the same two numbers the old ladder used (100/60) so this change
#: does not also silently reweight every existing confidence-based reader;
#: IMPLEMENTED sits between them because it is a fact, but a weaker-attested
#: one than a committed contract or a declared entry point.
_CONFIDENCE = {DECLARED: 100, IMPLEMENTED: 90, IMPLIED: 60}

#: Spec files, checked against real paths in the catalog rather than invented.
#: Anchored to the basename or a directory segment so a stray "swagger" inside
#: a vendored bundle's filename does not count as this project's contract.
_SPEC_PATTERNS = {
    "openapi": re.compile(r"(^|/)(openapi|swagger)\.(ya?ml|json)$", re.I),
    "openapi_dir": re.compile(r"(^|/)(openapi|swagger)/[^/]+\.(ya?ml|json)$", re.I),
    "grpc": re.compile(r"\.proto$"),
    "graphql": re.compile(r"\.(graphql|gql)$", re.I),
    "asyncapi": re.compile(r"(^|/)asyncapi\.(ya?ml|json)$", re.I),
    "soap": re.compile(r"\.(wsdl)$", re.I),
}

#: Spec kind -> the interface kind it proves.
_SPEC_TO_INTERFACE = {
    "openapi": "http_api", "openapi_dir": "http_api", "grpc": "grpc",
    "graphql": "graphql", "asyncapi": "messaging", "soap": "soap",
}

#: Dependency names that IMPLY an interface. Drawn from what the catalog
#: actually contains — graphql frameworks are absent from every repo here, and
#: are listed anyway so a future one is not silently missed.
_DEPENDENCY_SIGNALS = {
    "http_api": {"fastapi", "flask", "django", "starlette", "express", "koa",
                 "axum", "actix-web", "gin", "spring-boot", "hapi", "tornado",
                 "sanic", "bottle", "falcon", "spring-boot-starter-web"},
    "grpc": {"grpcio", "grpc", "grpc-java", "google.golang.org/grpc", "tonic",
             "@grpc/grpc-js"},
    "graphql": {"graphql", "graphene", "strawberry-graphql", "apollo-server",
                "graphql-java"},
    "messaging": {"kafka-python", "confluent-kafka", "pika", "aio-pika",
                  "nats-py", "celery", "kombu"},
    "cli": {"typer", "click", "clap", "cobra", "commander", "picocli"},
}

#: Interface kinds for which "implemented" would mean route/handler/service-
#: method registrations in code — no survey step at Discovery tier records
#: this (see module docstring). `cli` is deliberately absent: a `__main__.py`
#: under the distribution's own package IS recorded, by deployment_evidence's
#: `dunder_main` evidence, so cli's implemented rung can actually be checked.
_ROUTE_LIKE_KINDS = {"http_api", "grpc", "graphql", "messaging", "soap"}

_COULD_NOT_CHECK_REASON = {
    "http_api": "route decorators are not recorded",
    "grpc": "gRPC service method registrations are not recorded",
    "graphql": "GraphQL resolver registrations are not recorded",
    "messaging": "message-handler/consumer registrations are not recorded",
    "soap": "SOAP service-method bindings are not recorded",
}

#: Trees whose contents are not this project's published contract.
#:
#: Three kinds, and the third was found by reading real output rather than
#: reasoning about it: OpenLineage was reported as publishing a gRPC API on the
#: strength of `integration/flink/flink1/src/test/resources/InputEvent.proto`
#: and `.../src/test/proto/ProtobufTestEvent.proto` — Maven/Gradle test
#: fixtures whose filenames literally say Test. A spec under a test tree is
#: something the project parses, not something it offers.
#:
#:   vendored   — belongs to a dependency
#:   generated  — build output, not source
#:   test       — fixtures, including Java's src/test and src/it layouts
_VENDORED = re.compile(
    r"(^|/)(node_modules|vendor|third_party|thirdparty|\.venv|site-packages|"
    r"dist|build|target|out|generated|"
    r"testdata|fixtures?|examples?|samples?|"
    r"tests?|src/test|src/it)/", re.I)


def _finding(name: str, label: str, summary: str, detail: dict) -> dict:
    return {"check_name": name, "label": label, "summary": summary,
            "confidence": _CONFIDENCE.get(label, 60), "detail": detail}


def _cli_entry_points(distribution_details: list) -> list[dict]:
    """console_script evidence from stored `distribution` finding detail
    dicts — DistributionParser's shape (`scripts`, `script_targets`,
    `script_table`, `manifest`). Never re-parses pyproject.toml/package.json;
    reads exactly the fields repo_manifest_parse already wrote."""
    out: list[dict] = []
    for d in distribution_details or []:
        scripts = d.get("scripts") or []
        if not scripts:
            continue
        targets = d.get("script_targets") or {}
        table = d.get("script_table") or "the packaging manifest"
        manifest = d.get("manifest") or ""
        for name in scripts:
            target = targets.get(name)
            value = f'{name} = "{target}"' if target else name
            out.append({"kind": "console_script", "value": f"{value} in {table}",
                        "source_analysis": "distribution", "path": manifest})
    return out


def _cli_dunder_main(deployment_evidence_details: list) -> list[dict]:
    """implemented-CLI evidence from stored `deployment_evidence` finding
    detail dicts (check_name="distribution") — each carries an `evidence`
    list already computed by deployment_evidence.classify_distribution, which
    itself only reads project_file_inventory paths (path-only, no content).
    Never re-walks the file tree here."""
    out: list[dict] = []
    for d in deployment_evidence_details or []:
        for item in d.get("evidence") or []:
            if item.get("kind") == "dunder_main":
                out.append({"kind": "dunder_main", "value": item.get("path", ""),
                            "source_analysis": "deployment_evidence", "path": item.get("path", "")})
    return out


def detect(
    file_paths: list, dependency_names: list,
    distribution_details: list | None = None,
    deployment_evidence_details: list | None = None,
) -> list:
    """Interface findings from paths, dependencies, and the entry-point/
    deployment facts other walks already recorded — evidence kept apart, and
    every finding's `detail` keeps `evidence` as a list of {kind, value,
    source_analysis} so a reader can see WHERE a rung came from, not just
    which rung it landed on.

    `distribution_details` / `deployment_evidence_details` are the `detail`
    dicts from `project_analysis_findings` kind="distribution" / kind=
    "deployment_evidence" rows — never re-parsed manifests or re-walked
    trees. Both default to `None` (treated as empty) so every existing call
    site — and the pre-existing tests written before those parameters
    existed — keeps working unchanged.
    """
    out: list = []

    # ── specs: declared via a committed contract ─────────────────────────
    specs: dict = {}
    for path in file_paths:
        if _VENDORED.search(path or ""):
            continue
        for kind, pattern in _SPEC_PATTERNS.items():
            if pattern.search(path):
                specs.setdefault(_SPEC_TO_INTERFACE[kind], []).append(path)

    for interface, paths in sorted(specs.items()):
        out.append(_finding(
            interface, DECLARED,
            f"{len(paths)} specification file(s): {', '.join(sorted(paths)[:3])}"
            + (" …" if len(paths) > 3 else ""),
            {"evidence": [{"kind": "specification_file", "value": p,
                          "source_analysis": "file_inventory"} for p in sorted(paths)[:20]],
             "spec_path": sorted(paths)[0], "file_count": len(paths),
             "routes": None},
        ))

    # ── cli: declared via a packaging-declared entry point ───────────────
    cli_declared = _cli_entry_points(distribution_details or [])
    if cli_declared and "cli" not in specs:
        names = ", ".join(e["value"] for e in cli_declared[:3])
        out.append(_finding(
            "cli", DECLARED, f"Entry point declared: {names}"
            + (" …" if len(cli_declared) > 3 else ""),
            {"evidence": cli_declared, "spec_path": cli_declared[0]["path"], "routes": None},
        ))

    # ── cli: implemented via a __main__.py, when not already declared ────
    cli_implemented = _cli_dunder_main(deployment_evidence_details or [])
    if cli_implemented and "cli" not in specs and not cli_declared:
        paths = ", ".join(e["value"] for e in cli_implemented[:3])
        out.append(_finding(
            "cli", IMPLEMENTED,
            f"No declared entry point, but the code runs as one: {paths}"
            + (" …" if len(cli_implemented) > 3 else ""),
            {"evidence": cli_implemented, "spec_path": "", "routes": None},
        ))

    # ── dependencies: weaker evidence, only when no higher rung landed ────
    already_ranked = specs.keys() | ({"cli"} if (cli_declared or cli_implemented) else set())
    names = {(n or "").lower().split("[")[0] for n in dependency_names}
    for interface, signals in sorted(_DEPENDENCY_SIGNALS.items()):
        matched = sorted(names & signals)
        if not matched or interface in already_ranked:
            # Already proven by a stronger rung — a weaker duplicate would
            # only muddy it.
            continue
        detail = {"evidence": [{"kind": "dependency", "value": m,
                                "source_analysis": "dependency"} for m in matched],
                   "spec_path": "", "dependencies": matched}
        summary = (f"Depends on {', '.join(matched[:3])} — suggests a "
                   f"{interface.replace('_', ' ')}, but nothing in the repo "
                   "declares or implements one.")
        if interface in _ROUTE_LIKE_KINDS:
            # The honest gap this rewrite exists to name: whether the
            # dependency is actually EXPOSED as a route/handler/service
            # method needs code content no Discovery-tier step recorded.
            # Reported, not guessed past.
            reason = _COULD_NOT_CHECK_REASON[interface]
            detail["routes"] = {"count": None, "modules": [], "could_not_check_reason": reason}
            summary += f" Whether it is implemented could not be checked: {reason}."
        else:
            detail["routes"] = None
        out.append(_finding(interface, IMPLIED, summary, detail))

    # ── the published-API answer ─────────────────────────────────────────────
    # Its own finding, and deliberately keyed on SPECS only. Neither a
    # declared entry point nor a dependency is a published CONTRACT; a
    # committed openapi.yaml is. Answering the question from a weaker signal
    # is the whole failure this separation exists to avoid.
    if specs:
        kinds = ", ".join(sorted(specs))
        out.append(_finding(
            "published_spec", "yes",
            f"A machine-readable contract is committed: {kinds}.",
            {"evidence": "specification file", "kinds": sorted(specs)},
        ))
    else:
        weaker = [f["check_name"] for f in out if f["label"] in (IMPLEMENTED, IMPLIED)]
        out.append(_finding(
            "published_spec", "no",
            ("No specification file found in the repository."
             + (f" Interfaces are declared or implemented without a published "
                f"contract ({', '.join(weaker)})." if weaker else "")),
            {"evidence": "absence of specification files",
             "implied_interfaces": weaker},
        ))
    return out


class InterfaceSurfaceSurveyor(BaseSurveyor):
    """Interface kinds and whether a contract is published."""

    def __init__(self, project, registry, surveyed_at: str | None = None) -> None:
        super().__init__(project, registry)
        self._surveyed_at = surveyed_at or datetime.now(timezone.utc).replace(
            tzinfo=None).isoformat()

    @property
    def step_name(self) -> str:
        return STEP

    @staticmethod
    def _detail(row: dict) -> dict:
        d = row.get("detail")
        if isinstance(d, dict):
            return d
        import json
        raw = row.get("detail_json")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def run(self) -> list[Annotation]:
        out: list[Annotation] = []
        try:
            slug = self.project.slug
            paths = self.registry.get_file_inventory(slug)   # own files only; the registry holds the filter
            deps = [d.get("dep_name") for d in (self.registry.query_dependencies(slug) or [])]

            # Read, never re-derive: the SAME `distribution` / `deployment_
            # evidence` finding rows repo_manifest_parse's DistributionParser
            # and deployment_evidence.py already wrote. Absent when those
            # steps have not run for this repo — treated the same as "no
            # rows", not as an error, since a repo surveyed before this
            # change (or without ingestion at all — see manifest_parse.py's
            # own docstring on the org-import/discovery path) legitimately
            # has none yet.
            distribution_details = [self._detail(r) for r in
                                    (self.registry.query_findings(slug, "distribution") or [])]
            deployment_evidence_details = [self._detail(r) for r in
                                           (self.registry.query_findings(slug, "deployment_evidence") or [])
                                           if r.get("check_name") == "distribution"]

            if not paths and not deps:
                # Neither input exists. "No interfaces" would be a finding about
                # the repo; this is a finding about our coverage of it.
                # Persist the reason, not just annotate it. The annotation says
                # "not established"; the results card reads FINDINGS, so returning
                # without writing one made the card render an absence where a stated
                # reason exists — "we have nothing" instead of "we could not tell, and
                # here is why". Found 2026-08-27 via kedro_kubeflow, which has neither
                # commits nor stats and showed a blank card.
                self.registry.upsert_finding(
                    slug, "interface_surface",
                    [{"check_name": "interface_surface", "label": "not_established",
                      "summary": _NOTHING_TO_ASSESS, "confidence": 0,
                      "detail": {"known": False}}],
                    surveyed_at=self._surveyed_at,
                )
                out.append(ClassificationAnnotation(
check_name="interface_surface",
summary=_NOTHING_TO_ASSESS,
                    analysis_step=STEP,
                    candidate_classifications=["not_established"],
                    confidence=0,
                ))
                return out

            findings = detect(paths, deps, distribution_details, deployment_evidence_details)
            self.registry.upsert_finding(slug, "interface_surface", findings,
                                         surveyed_at=self._surveyed_at)

            declared = [f["check_name"] for f in findings if f["label"] == DECLARED]
            implemented = [f["check_name"] for f in findings if f["label"] == IMPLEMENTED]
            implied = [f["check_name"] for f in findings if f["label"] == IMPLIED]
            published = next((f for f in findings
                              if f["check_name"] == "published_spec"), None)
            summary = (
                (f"Declared: {', '.join(declared)}. " if declared else "")
                + (f"Implemented: {', '.join(implemented)}. " if implemented else "")
                + (f"Implied by dependencies: {', '.join(implied)}. " if implied else "")
                + (f"Published contract: {published['label']}."
                   if published else "")
            ) or "No interface signals found in the file inventory or dependencies."
            # Coverage travels with the answer: detection reads DECLARED
            # dependencies and the recorded inventory (plus, now, the
            # distribution/deployment_evidence tables), so a spec that is
            # generated at build time is invisible here.
            summary += (f" Read from {len(paths)} recorded file(s), "
                        f"{len(deps)} declared dependenc(ies), "
                        f"{len(distribution_details)} distribution(s), and "
                        f"{len(deployment_evidence_details)} deployment-evidence row(s).")

            # A zero here has two very different meanings and they were
            # reported identically. Detection reads the recorded file inventory
            # and the DECLARED dependencies, so "no interface signals" means
            # either this repo genuinely exposes nothing, or there was nothing
            # to read — an empty inventory and no parsed manifests produce the
            # same reassuring sentence as a thoroughly-examined library.
            #
            # The inputs are the known-positive: having read real files and
            # real dependencies and still found no interface is a provable
            # zero. Having read neither is not a finding about the repo.
            examined = len(paths) + len(deps)
            if declared or implemented or implied or published:
                outcome = StepOutcome("recovered", detail={
                    "files_read": len(paths), "dependencies_read": len(deps)})
            else:
                outcome = no_signal(
                    "no interface signals in the recorded inventory or declared dependencies",
                    known_positive=examined > 0,
                    files_read=len(paths), dependencies_read=len(deps),
                )
            out.append(ClassificationAnnotation(
                check_name="interface_surface",
                summary=summary, analysis_step=STEP,
                candidate_classifications=declared + implemented + implied,
                confidence=80,
                json_properties={"declared": declared, "implemented": implemented,
                                 "implied": implied,
                                 "published_spec": published["label"] if published else "",
                                 "files_read": len(paths),
                                 "dependencies_read": len(deps),
                                 **outcome.as_row()},
            ))
        except Exception as exc:
            log.exception("InterfaceSurfaceSurveyor failed for %s", self.project.slug)
            self._warn(out, str(exc))
        return out
