"""Sub-surveyor: what can you talk to, and is the contract written down?

Answers two of the questions in the catalog from data already collected — the
file inventory and the parsed dependencies. No fetch.

    "What kind of interfaces does it have?"  -> the interface kinds below
    "Is there a published API?"              -> the `published_spec` finding

One analysis rather than two, because the second is a finding ABOUT the first:
a library with 171 exported symbols has an interface surface and no published
contract, and answering those separately would mean re-deriving the same
evidence twice and letting the two disagree.

**The distinction that carries the weight is evidence strength.** A committed
`openapi.yaml` IS an HTTP contract. A `fastapi` dependency SUGGESTS one — it
may be a test fixture, a dev tool, or one service inside a monorepo. Both are
worth reporting; conflating them is not. So every finding carries how it was
established, and a dependency-only signal never reports as a published API.

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

#: How a finding was established. `specified` is the strong one — a machine
#: readable contract is committed in the repo. `implied` means a dependency
#: suggests the capability without proving it is exposed.
SPECIFIED = "specified"
IMPLIED = "implied"

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
            "confidence": 100 if label == SPECIFIED else 60, "detail": detail}


def detect(file_paths: list, dependency_names: list) -> list:
    """Interface findings from paths and dependencies, evidence kept apart."""
    out: list = []

    # ── specs: strong evidence ───────────────────────────────────────────────
    specs: dict = {}
    for path in file_paths:
        if _VENDORED.search(path or ""):
            continue
        for kind, pattern in _SPEC_PATTERNS.items():
            if pattern.search(path):
                specs.setdefault(_SPEC_TO_INTERFACE[kind], []).append(path)

    for interface, paths in sorted(specs.items()):
        out.append(_finding(
            interface, SPECIFIED,
            f"{len(paths)} specification file(s): {', '.join(sorted(paths)[:3])}"
            + (" …" if len(paths) > 3 else ""),
            {"evidence": "specification file", "files": sorted(paths)[:20],
             "file_count": len(paths)},
        ))

    # ── dependencies: weaker evidence ────────────────────────────────────────
    names = {(n or "").lower().split("[")[0] for n in dependency_names}
    for interface, signals in sorted(_DEPENDENCY_SIGNALS.items()):
        matched = sorted(names & signals)
        if not matched or interface in specs:
            # Already proven by a spec — a weaker duplicate would only muddy it.
            continue
        out.append(_finding(
            interface, IMPLIED,
            f"Depends on {', '.join(matched[:3])} — suggests a {interface.replace('_', ' ')}, "
            "but nothing in the repo specifies one.",
            {"evidence": "dependency", "dependencies": matched},
        ))

    # ── the published-API answer ─────────────────────────────────────────────
    # Its own finding, and deliberately keyed on SPECS only. "Depends on fastapi"
    # is not a published API; a committed openapi.yaml is. Answering the
    # question from the weaker signal is the whole failure this separation
    # exists to avoid.
    if specs:
        kinds = ", ".join(sorted(specs))
        out.append(_finding(
            "published_spec", "yes",
            f"A machine-readable contract is committed: {kinds}.",
            {"evidence": "specification file", "kinds": sorted(specs)},
        ))
    else:
        implied = [f["check_name"] for f in out if f["label"] == IMPLIED]
        out.append(_finding(
            "published_spec", "no",
            ("No specification file found in the repository."
             + (f" Interfaces are implied by dependencies ({', '.join(implied)}) "
                "but no contract is published." if implied else "")),
            {"evidence": "absence of specification files",
             "implied_interfaces": implied},
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

    def run(self) -> list[Annotation]:
        out: list[Annotation] = []
        try:
            slug = self.project.slug
            with self.registry._conn() as conn:
                paths = [r["file_path"] for r in conn.execute(
                    "SELECT file_path FROM project_file_inventory WHERE project_slug = ?",
                    (slug,)).fetchall()]
            deps = [d.get("dep_name") for d in (self.registry.query_dependencies(slug) or [])]

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
summary=_NOTHING_TO_ASSESS,
                    analysis_step=STEP,
                    candidate_classifications=["not_established"],
                    confidence=0,
                ))
                return out

            findings = detect(paths, deps)
            self.registry.upsert_finding(slug, "interface_surface", findings,
                                         surveyed_at=self._surveyed_at)

            specified = [f["check_name"] for f in findings
                         if f["label"] == SPECIFIED]
            implied = [f["check_name"] for f in findings if f["label"] == IMPLIED]
            published = next((f for f in findings
                              if f["check_name"] == "published_spec"), None)
            summary = (
                (f"Specified: {', '.join(specified)}. " if specified else "")
                + (f"Implied by dependencies: {', '.join(implied)}. " if implied else "")
                + (f"Published contract: {published['label']}."
                   if published else "")
            ) or "No interface signals found in the file inventory or dependencies."
            # Coverage travels with the answer: detection reads DECLARED
            # dependencies and the recorded inventory, so a spec that is
            # generated at build time is invisible here.
            summary += (f" Read from {len(paths)} recorded file(s) and "
                        f"{len(deps)} declared dependenc(ies).")

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
            if specified or implied or published:
                outcome = StepOutcome("recovered", detail={
                    "files_read": len(paths), "dependencies_read": len(deps)})
            else:
                outcome = no_signal(
                    "no interface signals in the recorded inventory or declared dependencies",
                    known_positive=examined > 0,
                    files_read=len(paths), dependencies_read=len(deps),
                )
            out.append(ClassificationAnnotation(
                summary=summary, analysis_step=STEP,
                candidate_classifications=specified + implied,
                confidence=80,
                json_properties={"specified": specified, "implied": implied,
                                 "published_spec": published["label"] if published else "",
                                 "files_read": len(paths),
                                 "dependencies_read": len(deps),
                                 **outcome.as_row()},
            ))
        except Exception as exc:
            log.exception("InterfaceSurfaceSurveyor failed for %s", self.project.slug)
            self._warn(out, str(exc))
        return out
