"""A step is dispatched only to a Prefect worker on Resource Explorer's own code (2026-11-13).

DESIGN-PREFECT-ROLE-AND-RE-WORKER-2026-11-13 §1.6: a container worker advertises the commit its image was
built from (`re-worker-<sha12>-<host>`) and serves its own deployment and queue; RE sends a step there only
when that is its own commit. A worker on other code is refused in words and the step runs locally (the
existing fallback); a worker that advertises no commit (the host worker) keeps serving the default
deployment, as before.
"""
from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

import resource_explorer.surveyors.prefect_adapter as adapter
from resource_explorer import build_info

OWN = "0123456789ab"
OTHER = "fedcba987654"
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _own_sha(monkeypatch):
    monkeypatch.setenv("TRELLIS_RE_SHA", OWN + "cdef0123456789abcdef01234567")
    build_info.re_sha.cache_clear()
    yield
    build_info.re_sha.cache_clear()


def _worker(name, status="ONLINE"):
    return types.SimpleNamespace(name=name, status=types.SimpleNamespace(value=status))


def _client(workers, deployments=("RE Survey Flow/re-survey-step-deployment",)):
    c = MagicMock()
    known = {n: types.SimpleNamespace(id=n, name=n, work_pool_name="resource-explorer-pool") for n in deployments}

    async def read_deployment(name):
        if name not in known:
            raise LookupError(f"{name} not found")
        return known[name]

    c.read_deployment_by_name = AsyncMock(side_effect=read_deployment)
    c.read_workers_for_work_pool = AsyncMock(return_value=workers)
    return c


def _choose(client):
    return asyncio.run(adapter._choose_deployment(client, "resource-explorer-pool"))


SHA_DEP = f"RE Survey Flow/re-survey-step-{OWN}"


class TestChooseDeployment:
    def test_a_worker_on_this_commit_gets_its_own_deployment(self):
        c = _client([_worker(f"re-worker-{OWN}-pop-os"), _worker("re-host-worker-laz")],
                    deployments=("RE Survey Flow/re-survey-step-deployment", SHA_DEP))
        assert _choose(c).name == SHA_DEP

    def test_a_worker_with_no_commit_serves_the_default_deployment_as_before(self):
        c = _client([_worker("re-host-worker-laz")])
        assert _choose(c).name == "RE Survey Flow/re-survey-step-deployment"
        c = _client([_worker("re-host-worker-laz"), _worker(f"re-worker-{OTHER}-pop-os")])
        assert _choose(c).name == "RE Survey Flow/re-survey-step-deployment", "the other-code worker is not used"

    def test_only_workers_on_other_code_is_refused_naming_both_commits(self):
        c = _client([_worker(f"re-worker-{OTHER}-pop-os")])
        with pytest.raises(RuntimeError) as ei:
            _choose(c)
        assert str(ei.value) == (f"no online Prefect worker runs this Resource Explorer's code ({OWN}); "
                                 f"online workers on pool resource-explorer-pool run {OTHER}")

    def test_an_offline_worker_on_this_commit_does_not_count(self):
        c = _client([_worker(f"re-worker-{OWN}-pop-os", "OFFLINE")], deployments=(
            "RE Survey Flow/re-survey-step-deployment", SHA_DEP))
        with pytest.raises(RuntimeError, match="no online Prefect worker for pool resource-explorer-pool"):
            _choose(c)

    def test_an_unknown_own_commit_never_claims_parity(self, monkeypatch):
        monkeypatch.setenv("TRELLIS_RE_SHA", "")
        build_info.re_sha.cache_clear()
        with patch.object(build_info.subprocess, "run", side_effect=OSError("no git")):
            c = _client([_worker(f"re-worker-{OWN}-pop-os")])
            with pytest.raises(RuntimeError, match=r"\(commit unknown\)"):
                _choose(c)

    def test_a_matching_worker_whose_deployment_is_missing_is_said(self):
        c = _client([_worker(f"re-worker-{OWN}-pop-os")])
        with pytest.raises(RuntimeError, match=f"deployment '{SHA_DEP}' is missing"):
            _choose(c)

    def test_names(self):
        assert adapter.worker_sha(_worker(f"re-worker-{OWN}-pop-os")) == OWN
        assert adapter.worker_sha(_worker(f"re-worker-{OWN}")) == OWN
        for name in ("re-host-worker-laz", "ProcessWorker 856bbae1", f"re-worker-{OWN}x", None):
            assert adapter.worker_sha(_worker(name)) == ""
        assert adapter.sha_deployment(OWN) == f"re-survey-step-{OWN}"
        assert adapter.sha_work_queue(OWN) == f"re-{OWN}"


def test_a_refused_dispatch_runs_locally_and_says_why(monkeypatch):
    """The parity refusal goes through run_prefect_step's existing fallback: the step runs locally and
    dispatch_info carries the reason, which the run report shows ("ran locally: Prefect dispatch failed — …")."""
    client = _client([_worker(f"re-worker-{OTHER}-pop-os")])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    cfg = types.SimpleNamespace(prefect=types.SimpleNamespace(
        enabled=True, api_url="http://x/api", work_pool="resource-explorer-pool"))
    local = MagicMock(return_value={"ran": "locally"})
    info: dict = {}
    with patch.object(adapter, "get_config", lambda: cfg), \
         patch.object(adapter, "re_prefect_client", return_value=client), \
         patch.object(adapter.run_surveyor_step_task, "fn", local):
        out = adapter.run_prefect_step("database", "db1", "soda_data_quality", {}, dispatch_info=info)
    assert out == {"ran": "locally"}
    assert info["engine"] == "local"
    assert "runs this Resource Explorer's code" in info["dispatch_failed"]
    client.create_flow_run_from_deployment.assert_not_called()


class TestBuildInfo:
    def test_the_image_build_arg_wins(self):
        assert build_info.re_sha().startswith(OWN) and build_info.re_sha_short() == OWN

    def test_a_checkout_answers_with_git(self, monkeypatch):
        monkeypatch.delenv("TRELLIS_RE_SHA")
        build_info.re_sha.cache_clear()
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        assert build_info.re_sha() == head

    def test_garbage_is_not_a_commit(self, monkeypatch):
        monkeypatch.setenv("TRELLIS_RE_SHA", "not-a-sha")
        build_info.re_sha.cache_clear()
        with patch.object(build_info.subprocess, "run", side_effect=OSError("no git")):
            assert build_info.re_sha() == ""


def test_deploy_takes_a_name_and_a_queue():
    from resource_explorer.cli.main import app
    from resource_explorer.prefect import flows

    sourced = MagicMock()
    with patch.object(flows.re_survey_flow, "from_source", return_value=sourced) as from_source:
        out = CliRunner().invoke(app, ["prefect", "deploy", "--name", f"re-survey-step-{OWN}",
                                       "--work-queue", f"re-{OWN}"])
    assert out.exit_code == 0, out.output
    assert from_source.call_args.kwargs["source"].endswith("packages/resource-explorer")
    kw = sourced.deploy.call_args.kwargs
    assert kw["name"] == f"re-survey-step-{OWN}" and kw["work_queue_name"] == f"re-{OWN}"
    with patch.object(flows.re_survey_flow, "from_source", return_value=sourced):
        CliRunner().invoke(app, ["prefect", "deploy"])
    kw = sourced.deploy.call_args.kwargs
    assert kw["name"] == "re-survey-step-deployment" and kw["work_queue_name"] is None, "the host default is unchanged"


# ── the image's prefect-worker role, run against stub commands ────────────────

ENTRYPOINT = REPO / "docker" / "entrypoint-resource-explorer.sh"


def _stub(bin_dir: Path, name: str, body: str):
    p = bin_dir / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run_role(tmp_path, *, sha, steps_line):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    _stub(bin_dir, "python", f'echo "{steps_line}"')
    _stub(bin_dir, "resource-explorer", f'echo "resource-explorer $*" >> {calls}')
    _stub(bin_dir, "prefect", f'echo "prefect $*" >> {calls}')
    _stub(bin_dir, "hostname", 'echo pop-os')
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "TRELLIS_RE_SHA": sha}
    r = subprocess.run(["bash", str(ENTRYPOINT), "prefect-worker"], env=env, capture_output=True, text=True,
                       check=False)
    return r, (calls.read_text() if calls.exists() else "")


NONE_MISSING = ("library steps · Egeria host: change_rates, hub_tables (none missing) · "
                "Files host: fs_activity (none missing)")


def test_the_role_deploys_its_own_deployment_then_serves_only_its_queue(tmp_path):
    r, calls = _run_role(tmp_path, sha=OWN + "cdef0123456789abcdef01234567", steps_line=NONE_MISSING)
    assert r.returncode == 0, r.stderr
    assert calls.splitlines() == [
        f"resource-explorer prefect deploy --name re-survey-step-{OWN} --work-queue re-{OWN}",
        (f"prefect worker start --pool resource-explorer-pool --type process --work-queue re-{OWN} "
         f"--name re-worker-{OWN}-pop-os"),
    ]
    assert NONE_MISSING in r.stderr


def test_the_role_refuses_without_a_commit(tmp_path):
    r, calls = _run_role(tmp_path, sha="", steps_line=NONE_MISSING)
    assert r.returncode == 1 and "TRELLIS_RE_SHA is not set" in r.stderr and calls == ""


def test_the_role_refuses_when_a_step_is_missing(tmp_path):
    r, calls = _run_role(tmp_path, sha=OWN, steps_line=(
        "library steps · Egeria host: change_rates (1 missing: hub_tables) · Files host: none installed "
        "(5 missing: fs_activity, fs_change_rates, fs_duplicates, fs_layout_signals, fs_permissions)"))
    assert r.returncode == 1 and "library steps are missing" in r.stderr and calls == ""


def test_the_image_carries_its_commit():
    """(Installing every step is test_dockerfile_installs_steps.py's.)"""
    text = (REPO / "docker" / "Dockerfile.resource-explorer").read_text()
    runtime = text.split("AS runtime", 1)[1]
    assert 'ENV TRELLIS_RE_SHA="${TRELLIS_RE_SHA}"' in runtime
    assert "TRELLIS_RE_SHA=${{ github.sha }}" in (REPO / ".github" / "workflows" / "images.yml").read_text()
    assert "--build-arg TRELLIS_RE_SHA=" in (REPO / "Makefile").read_text()
    assert os.access(ENTRYPOINT, os.R_OK)
