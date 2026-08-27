"""Supply-chain checks over workflow YAML.

Every "fail" these produce is an accusation about someone's repository, so the
tests here are weighted toward the ways a check could be confidently wrong:
a privileged trigger without an untrusted checkout, an expression in a place
where it is data rather than code, a file that would not parse.

Grounded against eleven real repositories on disk (superset, datahub, airbyte,
data-prep-kit, marquez, containers and others) before the patterns were fixed.
All three dangerous-workflow hits in that sample were verified by hand to be
genuine pull_request_target + PR-head checkouts — none were false positives.
"""
from pathlib import Path

import pytest

from resource_explorer.ingestion.supply_chain_parser import SupplyChainParser


def _repo(tmp_path: Path, **workflows) -> Path:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    for name, body in workflows.items():
        (d / f"{name}.yml").write_text(body)
    return tmp_path


def _labels(findings) -> dict:
    return {f["check_name"].replace("supply_chain_", ""): f["label"] for f in findings}


def test_no_workflows_reports_nothing_rather_than_three_failures(tmp_path):
    """A repo with no CI has not failed three supply-chain checks — it has no
    CI. Reporting failures would be findings about a thing that does not exist."""
    assert SupplyChainParser().parse(tmp_path) == []
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert SupplyChainParser().parse(tmp_path) == []


def test_on_key_survives_yaml_parsing_it_as_boolean_true(tmp_path):
    """`on:` is YAML 1.1's `true`. Unhandled, every trigger set reads as empty
    and dangerous-workflow can never fire at all."""
    r = _repo(tmp_path, wf="""
on:
  pull_request_target:
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
""")
    assert _labels(SupplyChainParser().parse(r))["dangerous_workflow"] == "fail"


def test_privileged_trigger_alone_is_not_dangerous(tmp_path):
    """pull_request_target is legitimate and common. It is dangerous only in
    combination with checking out the untrusted ref — flagging the trigger by
    itself would fail most well-run repositories."""
    r = _repo(tmp_path, wf="""
on:
  pull_request_target:
jobs:
  label:
    steps:
      - uses: actions/labeler@v5
""")
    assert _labels(SupplyChainParser().parse(r))["dangerous_workflow"] == "pass"


def test_untrusted_checkout_under_an_unprivileged_trigger_is_not_dangerous(tmp_path):
    """Under a plain `pull_request`, the PR head is what runs anyway and no
    secrets are exposed. The same two lines mean opposite things by trigger."""
    r = _repo(tmp_path, wf="""
on: pull_request
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
""")
    assert _labels(SupplyChainParser().parse(r))["dangerous_workflow"] == "pass"


def test_untrusted_expression_is_injection_in_run_and_data_in_with(tmp_path):
    """The distinguishing fact is where the expression lands, which is exactly
    what a keyword scan over concatenated text cannot see."""
    danger = _repo(tmp_path / "a", wf="""
on: issue_comment
jobs:
  x:
    steps:
      - run: echo "${{ github.event.issue.title }}"
""")
    safe = _repo(tmp_path / "b", wf="""
on: issue_comment
jobs:
  x:
    steps:
      - uses: some/action@v1
        with:
          title: ${{ github.event.issue.title }}
""")
    assert _labels(SupplyChainParser().parse(danger))["dangerous_workflow"] == "fail"
    assert _labels(SupplyChainParser().parse(safe))["dangerous_workflow"] == "pass"


def test_top_level_permissions_beat_job_level_only(tmp_path):
    """Job-level only is real but weaker — a job added later inherits the
    default again — so it is partial, not a pass."""
    top = _repo(tmp_path / "a", wf="permissions:\n  contents: read\non: push\njobs:\n  x:\n    steps: []\n")
    job = _repo(tmp_path / "b", wf="on: push\njobs:\n  x:\n    permissions:\n      contents: read\n    steps: []\n")
    none = _repo(tmp_path / "c", wf="on: push\njobs:\n  x:\n    steps: []\n")
    assert _labels(SupplyChainParser().parse(top))["token_permissions"] == "pass"
    assert _labels(SupplyChainParser().parse(job))["token_permissions"] == "partial"
    assert _labels(SupplyChainParser().parse(none))["token_permissions"] == "fail"


def test_only_a_full_sha_counts_as_pinned(tmp_path):
    """A tag is mutable — `@v4` today need not be `@v4` tomorrow — which is
    the whole reason the check exists."""
    sha = "b4ffde65f46336ab88eb53be808477a3936bae11"
    r = _repo(tmp_path, wf=f"""
on: push
jobs:
  x:
    steps:
      - uses: actions/checkout@{sha}
      - uses: third/party@v1
""")
    out = SupplyChainParser().parse(r)
    assert _labels(out)["pinned_dependencies"] == "partial"
    d = [f for f in out if f["check_name"].endswith("pinned_dependencies")][0]["detail"]
    assert d["pinned_count"] == 1 and d["unpinned_count"] == 1


def test_no_external_actions_is_unknown_not_a_pass(tmp_path):
    """Nothing to pin is not the same as everything pinned. A pass here would
    hand a perfect score to a workflow that proves nothing."""
    r = _repo(tmp_path, wf="on: push\njobs:\n  x:\n    steps:\n      - run: make test\n")
    assert _labels(SupplyChainParser().parse(r))["pinned_dependencies"] == "unknown"


def test_local_composite_actions_are_not_third_party(tmp_path):
    r = _repo(tmp_path, wf="on: push\njobs:\n  x:\n    steps:\n      - uses: ./.github/actions/setup\n")
    out = SupplyChainParser().parse(r)
    d = [f for f in out if f["check_name"].endswith("pinned_dependencies")][0]["detail"]
    assert d["local_actions"] == 1 and d["unpinned_count"] == 0


def test_an_unparseable_workflow_is_excluded_and_counted_never_scored(tmp_path):
    """Malformed YAML is not a failing workflow. Coverage rides in the summary
    so a pass over one of two files cannot read as a pass over two."""
    r = _repo(tmp_path,
              good="permissions:\n  contents: read\non: push\njobs:\n  x:\n    steps: []\n",
              bad="this: [is: not: valid\n")
    out = SupplyChainParser().parse(r)
    perms = [f for f in out if f["check_name"].endswith("token_permissions")][0]
    assert perms["label"] == "pass"
    assert perms["detail"]["workflows_parsed"] == 1
    assert perms["detail"]["workflows_total"] == 2
    assert "bad.yml" in perms["detail"]["unparseable"]
    assert "1 of 2" in perms["summary"]


def test_every_workflow_unparseable_yields_not_established_not_failures(tmp_path):
    r = _repo(tmp_path, bad="this: [is: not: valid\n")
    out = SupplyChainParser().parse(r)
    assert len(out) == 1
    assert out[0]["label"] == "not_established"
    assert out[0]["confidence"] == 0
