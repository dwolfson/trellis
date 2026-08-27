"""Supply-chain signals from workflow YAML — the three OpenSSF checks that a
repository's own CI configuration can actually answer.

Runs where CiWorkflowParser runs, at ingestion / "Refresh & profile" time,
because that is the one moment the zipball is already on disk. FossScorecard
then reads what this wrote, the same read-only relationship CiQualitySurveyor
already has with its findings.

**Why this parses YAML rather than scanning keywords.** CiWorkflowParser
concatenates every workflow into one lowercased blob and asks whether a word
appears anywhere — right for "does CI run tests at all", useless here. Every
check below turns on STRUCTURE: `permissions` at the top of a file means
something different from `permissions` inside one job, and a `${{ }}`
expression is dangerous in a `run:` block and ordinary in a `with:` block. A
blob cannot see any of that, and a check that cannot see the difference would
report a confident answer to a question it never asked.

**An unparseable workflow is not a failing one.** Malformed YAML, or a file
using a construct the loader rejects, is excluded and counted — never scored
as absent. The counts ride along in every finding's detail so a "pass" over
two of eleven workflows cannot read as a pass over eleven.

Measured across eleven real repositories on disk before the thresholds here
were fixed; see tests for what those measurements were.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

#: A pinned action reference: `uses: owner/repo@<40-hex>`. Tags and branches
#: are mutable — `@v4` today is not `@v4` tomorrow — which is the entire point
#: of the check, so nothing but a full commit SHA counts.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: Actions published by GitHub itself. Still mutable, still a supply-chain
#: dependency, and OpenSSF counts them — but a repo that pins everything
#: EXCEPT these is in a materially different position from one that pins
#: nothing, so they are counted separately rather than folded in silently.
_FIRST_PARTY = ("actions/", "github/")

#: Triggers that run with the base repository's secrets while the code under
#: test comes from a fork. Dangerous only in combination with checking out
#: that untrusted ref — the trigger alone is legitimate and common.
_PRIVILEGED_TRIGGERS = ("pull_request_target", "workflow_run")

#: Event fields an attacker controls. Interpolated into a `run:` block they
#: are shell injection; the same expression inside `with:` or `env:` is passed
#: as data and is not.
_UNTRUSTED_EXPR = re.compile(
    r"\$\{\{\s*github\.event\.(?:"
    r"issue\.title|issue\.body|pull_request\.title|pull_request\.body|"
    r"comment\.body|review\.body|review_comment\.body|"
    r"head_commit\.message|head_commit\.author|"
    r"pull_request\.head\.ref|pull_request\.head\.label|"
    r"discussion\.title|discussion\.body"
    r")", re.I)

#: Refs that resolve to the untrusted side of a fork PR.
_UNTRUSTED_REF = re.compile(
    r"github\.event\.pull_request\.head\.(sha|ref)|github\.event\.workflow_run\.head", re.I)


def _load(path: Path):
    """Parsed workflow, or None when it cannot be read as YAML.

    None is a real answer here and is propagated as such — see the module
    docstring on why an unparseable file must never be scored as a failing one.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover - pyyaml is a hard dependency
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _jobs(doc: dict) -> dict:
    jobs = doc.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _steps(job) -> list:
    steps = job.get("steps") if isinstance(job, dict) else None
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def _triggers(doc: dict) -> set:
    # `on` is YAML 1.1's boolean true, so a safe_load turns the key into the
    # bool True. Real, and it silently empties this set if unhandled.
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {t for t in on if isinstance(t, str)}
    if isinstance(on, dict):
        return set(on.keys())
    return set()


# ── the three checks ────────────────────────────────────────────────────────
def _check_token_permissions(docs: list) -> tuple:
    """Whether workflows narrow GITHUB_TOKEN from its default.

    Top-level `permissions` is the strong form — it applies to every job,
    including ones added later. Job-level only is real but weaker: a new job
    inherits the default again, so it is reported as partial rather than
    counted as a pass, since the difference is exactly what the check is for.
    """
    top, job_only, none_at_all = [], [], []
    for name, doc in docs:
        if "permissions" in doc:
            top.append(name)
        elif any("permissions" in j for j in _jobs(doc).values() if isinstance(j, dict)):
            job_only.append(name)
        else:
            none_at_all.append(name)
    detail = {"top_level": top, "job_level_only": job_only, "unset": none_at_all}
    if not none_at_all and not job_only:
        return "pass", f"All {len(top)} workflow(s) set permissions at the top level.", detail
    if none_at_all and not top and not job_only:
        return ("fail",
                f"No workflow sets permissions — all {len(none_at_all)} run with "
                "the default token scope.", detail)
    return ("partial",
            f"{len(top)} workflow(s) set top-level permissions, {len(job_only)} only "
            f"per-job, {len(none_at_all)} not at all.", detail)


def _check_pinned_dependencies(docs: list) -> tuple:
    """Whether third-party actions are pinned to an immutable commit SHA."""
    pinned, unpinned, first_party_unpinned, local = [], [], [], 0
    for name, doc in docs:
        for job in _jobs(doc).values():
            for step in _steps(job):
                uses = step.get("uses")
                if not isinstance(uses, str):
                    continue
                if uses.startswith("./") or uses.startswith("docker://"):
                    # A local composite action is this repo's own code, not a
                    # third-party dependency to pin.
                    local += 1
                    continue
                ref = uses.partition("@")[2].strip()
                target = f"{name}:{uses}"
                if _SHA_RE.match(ref):
                    pinned.append(target)
                elif uses.startswith(_FIRST_PARTY):
                    first_party_unpinned.append(target)
                else:
                    unpinned.append(target)

    detail = {"pinned": pinned[:20], "unpinned": unpinned[:20],
              "first_party_unpinned": first_party_unpinned[:20],
              "pinned_count": len(pinned), "unpinned_count": len(unpinned),
              "first_party_unpinned_count": len(first_party_unpinned),
              "local_actions": local}
    total = len(pinned) + len(unpinned) + len(first_party_unpinned)
    if not total:
        # No external actions at all. Nothing to pin is not the same as
        # failing to pin, and it is not a pass either — there is no evidence.
        return "unknown", "No external actions are used, so pinning cannot be assessed.", detail
    if not unpinned and not first_party_unpinned:
        return "pass", f"All {len(pinned)} action reference(s) pinned to a commit SHA.", detail
    if not pinned:
        return ("fail",
                f"None of {total} action reference(s) are pinned to a commit SHA "
                f"({len(unpinned)} third-party, {len(first_party_unpinned)} GitHub-owned).",
                detail)
    return ("partial",
            f"{len(pinned)} of {total} action reference(s) pinned; "
            f"{len(unpinned)} third-party still on a mutable ref.", detail)


def _check_dangerous_workflow(docs: list) -> tuple:
    """Untrusted-code checkout under a privileged trigger, and script injection.

    Both are reported as one check because both are the same underlying
    mistake — attacker-controlled input reaching a privileged context — and
    OpenSSF scores them as one.
    """
    checkout_hits, injection_hits = [], []
    for name, doc in docs:
        privileged = bool(_triggers(doc) & set(_PRIVILEGED_TRIGGERS))
        for job_name, job in _jobs(doc).items():
            for step in _steps(job):
                with_ = step.get("with")
                ref = (with_ or {}).get("ref") if isinstance(with_, dict) else None
                if (privileged and isinstance(ref, str)
                        and _UNTRUSTED_REF.search(ref)):
                    checkout_hits.append(f"{name}:{job_name}")
                run = step.get("run")
                if isinstance(run, str) and _UNTRUSTED_EXPR.search(run):
                    injection_hits.append(f"{name}:{job_name}")

    detail = {"untrusted_checkout": sorted(set(checkout_hits)),
              "script_injection": sorted(set(injection_hits))}
    if checkout_hits or injection_hits:
        parts = []
        if checkout_hits:
            parts.append(f"{len(set(checkout_hits))} job(s) check out untrusted code "
                         "under a privileged trigger")
        if injection_hits:
            parts.append(f"{len(set(injection_hits))} job(s) interpolate "
                         "attacker-controlled text into a shell command")
        return "fail", "; ".join(parts) + ".", detail
    return ("pass",
            "No privileged-trigger checkout of untrusted code and no untrusted "
            "expression in a shell command.", detail)


_CHECKS = (
    ("supply_chain_token_permissions", _check_token_permissions),
    ("supply_chain_pinned_dependencies", _check_pinned_dependencies),
    ("supply_chain_dangerous_workflow", _check_dangerous_workflow),
)


class SupplyChainParser:
    """Workflow-YAML supply-chain findings, or nothing at all.

    Returns [] when there are no workflows — the same convention
    CiWorkflowParser and DependencyParser use. Three "fail" rows for a repo
    with no CI would be findings about a thing that does not exist.
    """

    def parse(self, local_root: Path) -> list[dict]:
        wf_dir = Path(local_root) / ".github" / "workflows"
        if not wf_dir.is_dir():
            return []
        files = sorted([*wf_dir.glob("*.yml"), *wf_dir.glob("*.yaml")])
        if not files:
            return []

        docs, unparseable = [], []
        for f in files:
            doc = _load(f)
            (docs.append((f.name, doc)) if doc is not None else unparseable.append(f.name))
        if not docs:
            return [{
                "check_name": "supply_chain_workflows_read",
                "label": "not_established",
                "summary": (f"None of {len(files)} workflow file(s) could be parsed as "
                            "YAML, so no supply-chain check could be evaluated."),
                "confidence": 0,
                "detail": {"unparseable": unparseable},
            }]

        coverage = {"workflows_parsed": len(docs), "workflows_total": len(files),
                    "unparseable": unparseable}
        out = []
        for check_name, fn in _CHECKS:
            try:
                label, summary, detail = fn(docs)
            except Exception as exc:
                log.debug("supply-chain check %s failed: %s", check_name, exc)
                label, summary, detail = ("not_established",
                                          f"Check errored ({type(exc).__name__}).", {})
            if unparseable:
                # Coverage travels with the answer, always — a pass over 2 of
                # 11 workflows is a different claim from a pass over 11.
                summary += f" ({len(docs)} of {len(files)} workflow(s) parsed.)"
            out.append({"check_name": check_name, "label": label, "summary": summary,
                        "confidence": 90 if label != "not_established" else 0,
                        "detail": {**detail, **coverage}})
        return out
