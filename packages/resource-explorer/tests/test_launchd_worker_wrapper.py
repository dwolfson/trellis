# SPDX-License-Identifier: Apache-2.0
"""The launchd worker wrapper (scripts/launchd/re-prefect-worker.sh) and re-config-parity.sh.

2026-11-14: on laz the wrapper never deployed re-survey-step-<sha> although the tree's
`resource-explorer prefect deploy` takes --work-queue. The test was `… --help | grep -q -- --work-queue` under
`set -o pipefail`. The plist sets PYTHONUNBUFFERED=1, so the help is written line by line; grep -q exits at the
first match, the help's next write hits a closed pipe (exit 1 or SIGPIPE), and pipefail reads the test as false.
Reproduced on laz with the plist's environment: PIPESTATUS "1 0"; capturing the help first finds the flag.

These tests run the REAL wrapper with stub executables in a throwaway tree, so they exercise the shell exactly
as launchd runs it. Nothing touches Prefect, Postgres or Egeria.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

LAUNCHD = Path(__file__).resolve().parents[1] / "scripts" / "launchd"
WRAPPER = LAUNCHD / "re-prefect-worker.sh"
PARITY = LAUNCHD / "re-config-parity.sh"

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win") or shutil.which("bash") is None or shutil.which("git") is None,
    reason="needs bash and git",
)

# The flag near the top and many lines after it, written one line at a time (as an unbuffered Python CLI
# does): the shape that made `| grep -q` fail.
BIG_HELP_WITH_FLAG = (
    "Usage: resource-explorer prefect deploy [OPTIONS]\n"
    "│ --work-queue        TEXT  Work queue for this deployment's runs │\n"
    + ("│ filler line describing another option at some length ............ │\n" * 4000)
)
BIG_HELP_WITHOUT_FLAG = (
    "Usage: resource-explorer prefect deploy [OPTIONS]\n"
    + ("│ filler line describing another option at some length ............ │\n" * 4000)
)


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def _tree(tmp_path: Path, *, help_text: str | None, help_exit: int = 0) -> tuple[Path, Path, Path]:
    """A fake RE_TREE: a git repo with one commit and stub .venv/bin executables that log their calls."""
    tree = tmp_path / "tree"
    bin_ = tree / ".venv" / "bin"
    bin_.mkdir(parents=True)
    log = tmp_path / "calls.log"
    help_file = tmp_path / "help.txt"
    help_file.write_text(help_text or "")
    # dotenv -f <file> run -- <cmd...>: run the command (PATH already has .venv/bin first).
    _stub(bin_ / "dotenv", 'shift 2; [ "$1" = run ] && shift; [ "$1" = -- ] && shift; exec "$@"\n')
    _stub(bin_ / "python", f'echo "python $*" >> "{log}"; echo "library steps (stub)"\n')
    _stub(
        bin_ / "resource-explorer",
        f'echo "resource-explorer $*" >> "{log}"\n'
        # Write the help one line at a time and fail on a closed pipe, like the real unbuffered CLI.
        f'if [ "$*" = "prefect deploy --help" ]; then\n'
        f'  while IFS= read -r line; do printf "%s\\n" "$line" || exit 1; done < "{help_file}"\n'
        f'  exit {help_exit}\nfi\n'
        "exit 0\n",
    )
    _stub(bin_ / "prefect", f'echo "prefect $*" >> "{log}"\n')
    env_file = tmp_path / "re-runtime-env.sh"
    env_file.write_text("# stub runtime env\n")
    dotenv = tmp_path / ".env"
    dotenv.write_text("")
    git = ["git", "-C", str(tree)]
    subprocess.run(git + ["init", "-q"], check=True)
    (tree / "README").write_text("x\n")
    subprocess.run(git + ["add", "README"], check=True)
    subprocess.run(
        git + ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
               "commit", "-q", "-m", "fixture"],
        check=True,
    )
    return tree, env_file, log


def _run_wrapper(tmp_path: Path, tree: Path, env_file: Path) -> subprocess.CompletedProcess:
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "RE_TREE": str(tree),
        "RE_DOTENV": str(tmp_path / ".env"),
        "RE_RUNTIME_ENV": str(env_file),
        "PREFECT_WORK_POOL": "resource-explorer-pool",
    }
    return subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=60)


def _sha12(tree: Path) -> str:
    return subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()[:12]


def test_large_help_with_flag_deploys_and_starts_a_sha_worker(tmp_path):
    tree, env_file, log = _tree(tmp_path, help_text=BIG_HELP_WITH_FLAG)
    proc = _run_wrapper(tmp_path, tree, env_file)
    assert proc.returncode == 0, proc.stderr
    sha12 = _sha12(tree)
    calls = log.read_text()
    assert f"resource-explorer prefect deploy --name re-survey-step-{sha12} --work-queue re-{sha12}" in calls
    assert "resource-explorer prefect prune-deployments --keep 3" in calls
    assert f"--work-queue re-{sha12} --name re-worker-{sha12}-" in calls
    assert "re-host-worker-" not in calls
    assert "WARNING" not in proc.stderr


def test_help_without_flag_serves_the_default_deployment_and_says_why(tmp_path):
    tree, env_file, log = _tree(tmp_path, help_text=BIG_HELP_WITHOUT_FLAG)
    proc = _run_wrapper(tmp_path, tree, env_file)
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text()
    assert "prefect deploy --name" not in calls
    assert "prune-deployments" not in calls
    assert "--name re-host-worker-" in calls
    assert "this tree's 'prefect deploy' has no --work-queue" in proc.stderr
    assert "--help' failed" not in proc.stderr


def test_failed_help_is_told_apart_from_a_missing_flag(tmp_path):
    tree, env_file, log = _tree(tmp_path, help_text="Traceback: boom\n", help_exit=3)
    proc = _run_wrapper(tmp_path, tree, env_file)
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text()
    assert "prefect deploy --name" not in calls
    assert "--name re-host-worker-" in calls
    assert "'resource-explorer prefect deploy --help' failed (exit 3)" in proc.stderr
    assert "'prefect deploy --help' failed, see above" in proc.stderr
    assert "has no --work-queue);" not in proc.stderr


# --- re-config-parity.sh --------------------------------------------------------------------------------

def _sleeper(env: dict) -> subprocess.Popen:
    # Not /bin/sleep: on macOS, ps eww hides the environment of system (SIP-protected) binaries.
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                            env={"PATH": "/usr/bin:/bin", **env})


def _parity(a: subprocess.Popen, b: subprocess.Popen) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(PARITY), str(a.pid), str(b.pid)], capture_output=True, text=True,
                          timeout=30, env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})


@pytest.mark.skipif(sys.platform != "darwin" and not Path("/proc").exists(), reason="needs ps eww")
def test_parity_ignores_the_wrappers_launch_variables_by_name(tmp_path):
    shared = {"EGERIA_VIEW_SERVER": "qs-view-server", "PREFECT_API_URL": "http://x/api"}
    web = _sleeper(shared)
    worker = _sleeper({**shared, "RE_TREE": "/t", "RE_DOTENV": "/t/.env", "RE_RUNTIME_ENV": "/r.sh"})
    try:
        time.sleep(0.5)
        proc = _parity(web, worker)
    finally:
        web.kill(); worker.kill()
    if "no settings read" in proc.stderr:
        pytest.skip("ps eww does not show other processes' environments here")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    ok = [ln for ln in proc.stdout.splitlines() if ln.startswith("parity: OK")]
    assert ok, proc.stdout
    for name in ("RE_TREE", "RE_DOTENV", "RE_RUNTIME_ENV"):
        assert name in ok[0]


@pytest.mark.skipif(sys.platform != "darwin" and not Path("/proc").exists(), reason="needs ps eww")
def test_parity_still_reports_any_other_worker_only_setting(tmp_path):
    shared = {"EGERIA_VIEW_SERVER": "qs-view-server"}
    web = _sleeper(shared)
    worker = _sleeper({**shared, "RE_TREE": "/t", "RE_SOMETHING_ELSE": "1"})
    try:
        time.sleep(0.5)
        proc = _parity(web, worker)
    finally:
        web.kill(); worker.kill()
    if "no settings read" in proc.stderr:
        pytest.skip("ps eww does not show other processes' environments here")
    assert proc.returncode == 1
    assert "RE_SOMETHING_ELSE" in proc.stdout
    assert "parity: DIFFERENT" in proc.stdout
    only = [ln for ln in proc.stdout.splitlines() if ln.startswith("only in pid")]
    assert only and all("RE_TREE" not in ln for ln in only), proc.stdout
