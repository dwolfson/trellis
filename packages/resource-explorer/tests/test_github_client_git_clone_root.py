"""Tests for GitHubClient.clone_git_root() / git_clone_root() — the
git_clone_root ResourceProvider's underlying implementation. Mirrors
test_github_client_zipball_root.py's structure exactly; the two providers
share the "download/clone into a tempdir, yield the root, clean up on
exit" shape, just with a subprocess clone instead of an HTTP zip download.

No real git subprocess or network call in any test here — subprocess.run
is monkeypatched throughout.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resource_explorer.github.client import GitHubClient


def _client(sha=None):
    """See test_github_client_zipball_root._client — `sha=None` is the
    uncacheable path, which must keep behaving exactly as before the
    SourceCache existed."""
    c = GitHubClient.__new__(GitHubClient)
    c._default_branch_sha = lambda repo: sha
    return c


def _fake_repo(full_name="test/myproj", clone_url="https://github.com/test/myproj.git"):
    repo = MagicMock()
    repo.full_name = full_name
    repo.clone_url = clone_url
    return repo


@pytest.fixture(autouse=True)
def _deterministic_config(monkeypatch):
    """get_config() is a plain module-global singleton, not lru_cache —
    patch it directly in every test rather than depending on whatever
    GITHUB_TOKEN/.env happens to be on the machine running the suite.
    Individual tests override .token via monkeypatch on the returned
    MagicMock where the token value itself matters."""
    import resource_explorer.github.client as client_mod

    fake_github_cfg = MagicMock(token="", clone_timeout_seconds=300, ssl_verify=True)
    monkeypatch.setattr(client_mod, "get_config", lambda: MagicMock(github=fake_github_cfg))
    return fake_github_cfg


class TestCloneGitRoot:
    def test_yields_dest_dir_and_cleans_up_tempdir(self, monkeypatch):
        """git_clone_root() (the context-manager form) mirrors zipball_root():
        a fresh tempdir, yielded while the clone "succeeded", removed on exit.

        clone_git_root() does `import subprocess` locally (matching this
        module's existing style — download_zipball/zipball_root also
        import inside the method) — patching the real `subprocess` module
        object works regardless, since a local `import subprocess` binds
        the same module object monkeypatch is patching here."""
        import subprocess as real_subprocess

        captured = {}

        def _fake_run(args, capture_output, env, timeout):
            captured["args"] = args
            captured["dest"] = args[-1]
            return MagicMock(returncode=0, stderr=b"")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with client.git_clone_root(repo) as root:
            assert str(root) == captured["dest"]
            assert root.parent.is_dir()  # the tempdir is real while open
            tempdir = root.parent

        assert not tempdir.exists()  # cleaned up after the context manager exits

    def test_clone_command_is_treeless_and_no_checkout(self, monkeypatch):
        """The whole point of this provider (design §5.7 gap 2): full history,
        no working-tree blob fetch. --depth must never appear — that would
        truncate history, which is exactly what co-change needs."""
        import subprocess as real_subprocess

        captured = {}

        def _fake_run(args, capture_output, env, timeout):
            captured["args"] = args
            return MagicMock(returncode=0, stderr=b"")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with client.git_clone_root(repo):
            pass

        args = captured["args"]
        assert "--filter=blob:none" in args
        assert "--no-checkout" in args
        assert not any(a.startswith("--depth") for a in args)

    def test_shallow_since_is_forwarded_as_an_option(self, monkeypatch):
        """Bounded window (design §5.6) is opt-in, not the default."""
        import subprocess as real_subprocess

        captured = {}

        def _fake_run(args, capture_output, env, timeout):
            captured["args"] = args
            return MagicMock(returncode=0, stderr=b"")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with client.git_clone_root(repo, shallow_since="3 months ago"):
            pass

        assert "--shallow-since=3 months ago" in captured["args"]

    def test_full_history_by_default(self, monkeypatch):
        import subprocess as real_subprocess

        captured = {}

        def _fake_run(args, capture_output, env, timeout):
            captured["args"] = args
            return MagicMock(returncode=0, stderr=b"")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with client.git_clone_root(repo):
            pass

        assert not any(a.startswith("--shallow-since") for a in captured["args"])

    def test_reuses_the_same_github_token_as_the_zipball_client(self, monkeypatch, _deterministic_config):
        """No second credential path — same GITHUB_TOKEN the zip download's
        Authorization header uses, just delivered to the git subprocess via
        GIT_CONFIG_* env vars instead of an HTTP header."""
        import subprocess as real_subprocess

        _deterministic_config.token = "s3cr3t-token"
        captured = {}

        def _fake_run(args, capture_output, env, timeout):
            captured["args"] = args
            captured["env"] = env
            return MagicMock(returncode=0, stderr=b"")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with client.git_clone_root(repo):
            pass

        env = captured["env"]
        # Delivered via GIT_CONFIG_* env vars, never as a CLI arg — argv is
        # visible to `ps` on a shared host, env vars are not.
        assert env.get("GIT_CONFIG_KEY_0") == "http.extraHeader"
        assert "Authorization: Basic" in env.get("GIT_CONFIG_VALUE_0", "")
        assert "s3cr3t-token" not in captured["args"]

    def test_no_auth_env_vars_when_token_is_unset(self, monkeypatch):
        """Public repo, no GITHUB_TOKEN configured — must not send a bogus
        empty Authorization header."""
        import subprocess as real_subprocess

        captured = {}

        def _fake_run(args, capture_output, env, timeout):
            captured["env"] = env
            return MagicMock(returncode=0, stderr=b"")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with client.git_clone_root(repo):
            pass

        assert "GIT_CONFIG_KEY_0" not in captured["env"]

    def test_nonzero_returncode_raises_runtimeerror(self, monkeypatch):
        """A clone failure must surface as an error, not a hang or a silent
        empty directory."""
        import subprocess as real_subprocess

        def _fake_run(args, capture_output, env, timeout):
            return MagicMock(returncode=128, stderr=b"fatal: repository not found")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with pytest.raises(RuntimeError, match="repository not found"):
            with client.git_clone_root(repo):
                pass

    def test_timeout_raises_runtimeerror_not_hang(self, monkeypatch):
        """Time-bound the subprocess — a hung clone must not wedge a survey."""
        import subprocess as real_subprocess

        def _fake_run(args, capture_output, env, timeout):
            raise real_subprocess.TimeoutExpired(cmd=args, timeout=timeout)

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with pytest.raises(RuntimeError, match="timed out"), client.git_clone_root(repo):
            pass

    def test_tempdir_cleaned_up_even_on_clone_failure(self, monkeypatch, tmp_path):
        import subprocess as real_subprocess
        from pathlib import Path

        captured = {}

        def _fake_run(args, capture_output, env, timeout):
            captured["dest"] = args[-1]
            return MagicMock(returncode=1, stderr=b"boom")

        monkeypatch.setattr(real_subprocess, "run", _fake_run)

        client = _client()
        repo = _fake_repo()

        with pytest.raises(RuntimeError), client.git_clone_root(repo):
            pass

        assert not Path(captured["dest"]).parent.exists()
