"""No metric, no number.

Design §5: RE may emit a number only if a declared `GovernanceMetric` exists for
it, with `measurement` and `target` filled in. If you cannot write down what you
are measuring and what good looks like, you do not get to publish the score.

The rule existed as prose and two known violations for a week. This makes it
checkable: a score persisted under a metric name with no declaration fails here,
at the moment it is added, rather than being noticed later by someone reading
the design doc.

Deliberately checks the DECLARATION FILE rather than live Egeria. The rule is
about whether a human wrote down what the number means; whether the catalog has
caught up is a deployment question, and coupling this test to a running Egeria
would make it skip in CI — which is exactly where it needs to run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

METRICS_DOC = (
    Path(__file__).resolve().parents[1]
    / "docs" / "dr-egeria" / "governance-metrics" / "re-governance-metrics.md"
)

#: metric_name as persisted -> the GovernanceMetric qualifiedName declaring it.
#: A score persisted by a surveyor MUST appear here, and its declaration MUST
#: exist in the document. Adding a score means adding both.
DECLARED = {
    "activity": "GovernanceMetric::ResourceExplorer::RepositoryActivity::1.0",
    "community": "GovernanceMetric::ResourceExplorer::RepositoryCommunity::1.0",
    "release_cadence": "GovernanceMetric::ResourceExplorer::RepositoryReleaseCadence::1.0",
    "freshness": "GovernanceMetric::ResourceExplorer::RepositoryFreshness::1.0",
    "overall": "GovernanceMetric::ResourceExplorer::OverallRepositoryHealth::1.0",
}


def _doc() -> str:
    assert METRICS_DOC.exists(), f"the declarations are missing: {METRICS_DOC}"
    return METRICS_DOC.read_text()


def _blocks(doc: str) -> list[str]:
    return [b for b in doc.split("# Create Governance Metric")[1:]]


@pytest.mark.parametrize("metric_name,qualified_name", sorted(DECLARED.items()))
def test_every_published_health_score_is_declared(metric_name, qualified_name):
    assert qualified_name in _doc(), (
        f"health.py publishes '{metric_name}' with no GovernanceMetric declaring it. "
        "Either declare it in docs/dr-egeria/governance-metrics/, or stop publishing "
        "the number — design §5 allows no third option."
    )


def test_every_declaration_states_a_measurement_and_a_target():
    """The two fields ARE the rule. A declaration without them restates the
    metric's name and asserts nothing about what it means or what good looks
    like — which is the state these six were already in, minus the paperwork.
    """
    for block in _blocks(_doc()):
        name = re.search(r"## Display Name\s*\n(.+)", block)
        label = name.group(1).strip() if name else "?"
        for field in ("## Measurement", "## Target"):
            assert field in block, f"'{label}' has no {field}"
        measurement = block.split("## Measurement")[1].split("##")[0].strip()
        target = block.split("## Target")[1].split("##")[0].strip()
        assert len(measurement) > 40, f"'{label}' measurement is too thin to be a definition"
        assert len(target) > 20, f"'{label}' target does not say what good looks like"


def test_documentation_score_is_declared():
    assert "GovernanceMetric::ResourceExplorer::DocumentationSignalCount::1.0" in _doc()


def test_the_declarations_are_registered_to_reseed():
    """A declaration that does not reseed is a declaration that disappears on the
    next Egeria wipe — which happened to this deployment today."""
    import json

    batch = METRICS_DOC.parent / "_batch.json"
    assert batch.exists(), "no _batch.json — these would not be authored at all"
    spec = json.loads(batch.read_text())
    assert METRICS_DOC.name in spec["files"]
    assert spec["canary"]["qualified_name"] in _doc(), "the canary names a metric that is not declared"

    order = json.loads((METRICS_DOC.parents[1] / "_folder_order.json").read_text())
    assert METRICS_DOC.parent.name in order["folders"], (
        "a folder absent from _folder_order.json is NOT executed — bootstrap only "
        "runs what is named there"
    )


def test_command_headings_are_at_the_level_dr_egeria_reads():
    """Heading levels are load-bearing, and getting them wrong fails silently.

    Dr.Egeria reads `##` as the command and `###` as its fields. An earlier
    version of this document used `#`/`##`: every command was skipped with
    "No processor registered for 'Display Name'", the run exited 0, the
    bootstrap reported `heal ok: True`, and nothing was created. The canary
    caught it — but only because there was one.

    Asserted here so the next person editing this file finds out at commit time
    rather than from an empty catalog.
    """
    doc = _doc()
    assert "\n## Create Governance Metric\n" in doc, (
        "command headings must be '##'. At '#' Dr.Egeria does not recognise them "
        "and silently creates nothing while reporting success."
    )
    assert "\n# Create Governance Metric\n" not in doc
    for field in ("Display Name", "Measurement", "Target", "Qualified Name"):
        assert f"\n### {field}\n" in doc, f"'{field}' must be '###' to be read as a field"


def test_the_batch_is_not_marked_non_idempotent_by_copy_paste():
    """The survey-definitions batch is NOT idempotent — re-running it duplicates
    process-step edges and takes the definition out of service. That warning is
    specific to Link First/Next Process Step, which this batch does not use:
    'Create Governance Metric' creates an element and links nothing.

    Copying that caution across would make these metrics needlessly fragile to
    re-run, so the distinction is asserted rather than left to whoever reads the
    neighbouring manifest first.
    """
    import json

    spec = json.loads((METRICS_DOC.parent / "_batch.json").read_text())
    assert spec.get("idempotent") is True
    assert "post_heal" not in spec, (
        "post_heal exists to strip duplicate step edges after a non-idempotent "
        "heal; this batch creates no relationships and needs none"
    )
