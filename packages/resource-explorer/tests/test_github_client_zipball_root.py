"""Tests for GitHubClient.zipball_root() — D6.7 (docs/unified-survey-
execution-model-plan.md), the one shared download+tempdir implementation
repo_survey_definition_adapter.py's _acquire_zipball_root and
IngestionPipeline.refresh_profile() both wrap now, instead of each keeping
its own copy of this pattern.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from resource_explorer.github.client import GitHubClient


def _client():
    return GitHubClient.__new__(GitHubClient)


class TestZipballRoot:
    def test_yields_download_zipball_result_and_cleans_up_tempdir(self):
        client = _client()
        repo = MagicMock()
        captured_dest = {}

        def _fake_download(repo_arg, dest_dir, subproject_path=None):
            captured_dest["dir"] = dest_dir
            assert dest_dir.is_dir()  # a real, existing tempdir
            return dest_dir / "extracted-root"

        client.download_zipball = _fake_download

        with client.zipball_root(repo) as root:
            assert root == captured_dest["dir"] / "extracted-root"
            assert captured_dest["dir"].is_dir()

        # tempdir removed after the context manager exits
        assert not captured_dest["dir"].exists()

    def test_forwards_subproject_path(self):
        client = _client()
        repo = MagicMock()
        calls = []

        def _fake_download(repo_arg, dest_dir, subproject_path=None):
            calls.append((repo_arg, subproject_path))
            return dest_dir

        client.download_zipball = _fake_download

        with client.zipball_root(repo, "sub/dir"):
            pass

        assert calls == [(repo, "sub/dir")]

    def test_download_error_propagates_and_still_cleans_up(self):
        client = _client()
        repo = MagicMock()
        captured_dest = {}

        def _fake_download(repo_arg, dest_dir, subproject_path=None):
            captured_dest["dir"] = dest_dir
            raise RuntimeError("network error")

        client.download_zipball = _fake_download

        try:
            with client.zipball_root(repo):
                pass
            assert False, "expected RuntimeError to propagate"
        except RuntimeError:
            pass

        assert not captured_dest["dir"].exists()
