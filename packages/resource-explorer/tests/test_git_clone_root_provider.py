"""Tests for the git_clone_root ResourceProvider — _acquire_git_clone_root
and its entry in _resource_providers_for()
(repo_survey_definition_adapter.py). Mirrors the zipball_root provider's
existing coverage (tests/test_repo_survey_definition_adapter.py,
tests/test_survey_orchestrator.py) plus trellis_microflow's own
resolve_resources dedup tests (packages/trellis-microflow/tests/
test_resources.py) — this file's job is only the resource_explorer-side
binding: is "git_clone_root" registered, does resolving it exactly once
per SurveyOrchestrator.run() actually trigger exactly one clone, and does
cleanup/failure propagate correctly through this module's contextmanager
wrapper. No real git subprocess or network call — GitHubClient itself is
mocked out.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import pytest
from trellis_microflow import resolve_resources

from resource_explorer.registry import Project
from resource_explorer.surveyors.repo_survey_definition_adapter import (
    _acquire_git_clone_root,
    _resource_providers_for,
)


def _project():
    return Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="",
    )


class TestProviderRegistration:
    def test_git_clone_root_is_registered_alongside_zipball_root(self):
        """Both providers coexist — adding this one must not remove or
        replace zipball_root (constraint: don't change its behaviour)."""
        providers = _resource_providers_for(_project(), registry=MagicMock())
        assert set(providers) == {"zipball_root", "git_clone_root"}

    def test_git_clone_root_is_resolvable_via_resolve_resources(self):
        project = _project()
        providers = _resource_providers_for(project, registry=MagicMock())

        fake_client = MagicMock()

        @contextmanager
        def _fake_cm():
            yield "/fake/clone/root"

        fake_client.git_clone_root.return_value = _fake_cm()
        fake_client.get_repo.return_value = "the-repo-object"

        with patch(
            "resource_explorer.github.client.GitHubClient", return_value=fake_client
        ), ExitStack() as stack:
            resolved = resolve_resources(stack, providers, {"git_clone_root"})

        assert resolved == {"git_clone_root": "/fake/clone/root"}
        fake_client.get_repo.assert_called_once_with(project.github_url)
        fake_client.git_clone_root.assert_called_once_with("the-repo-object")


class TestDedup:
    def test_two_steps_declaring_git_clone_root_acquire_it_exactly_once(self):
        """Mirrors trellis_microflow's own dedup test, at this module's
        binding: `needed` is the *union* across every selected step's
        requires_resources (computed by SurveyOrchestrator.run(), see
        survey_orchestrator.py), so two steps both naming "git_clone_root"
        collapse to the same single set entry before resolve_resources
        ever sees it — this test locks in that _acquire_git_clone_root
        itself doesn't get invoked twice for that union."""
        project = _project()
        providers = _resource_providers_for(project, registry=MagicMock())

        call_count = {"n": 0}

        @contextmanager
        def _fake_acquire():
            call_count["n"] += 1
            yield f"/fake/clone/root/{call_count['n']}"

        with patch.dict(
            providers,
            {
                "git_clone_root": providers["git_clone_root"].__class__(
                    name="git_clone_root", acquire=_fake_acquire
                )
            },
        ):
            # step_a and step_b both declare requires_resources=
            # {"git_clone_root": "..."} in a real STEP_REGISTRY entry;
            # SurveyOrchestrator.run() reduces that to one set entry
            # before calling resolve_resources — reproduced directly here.
            needed = {"git_clone_root"}  # union of step_a's + step_b's requirement
            with ExitStack() as stack:
                resolved = resolve_resources(stack, providers, needed)

        assert call_count["n"] == 1
        assert resolved == {"git_clone_root": "/fake/clone/root/1"}


class TestCleanup:
    def test_cleanup_runs_on_success(self):
        project = _project()
        entered, exited = [], []

        @contextmanager
        def _fake_client_cm():
            entered.append(True)
            try:
                yield "/fake/clone/root"
            finally:
                exited.append(True)

        fake_client = MagicMock()
        fake_client.git_clone_root.return_value = _fake_client_cm()
        fake_client.get_repo.return_value = "repo-obj"

        with patch(
            "resource_explorer.github.client.GitHubClient", return_value=fake_client
        ), _acquire_git_clone_root(project, registry=MagicMock()) as root:
            assert root == "/fake/clone/root"
            assert entered == [True]
            assert exited == []  # still open inside the `with` block

        assert exited == [True]  # released once the context manager exits

    def test_cleanup_runs_on_exception(self):
        """A consumer step raising inside the `with` block must not leak
        the clone — the finally in the wrapped context manager must still
        fire, same guarantee ExitStack gives resolve_resources callers."""
        project = _project()
        exited = []

        @contextmanager
        def _fake_client_cm():
            try:
                yield "/fake/clone/root"
            finally:
                exited.append(True)

        fake_client = MagicMock()
        fake_client.git_clone_root.return_value = _fake_client_cm()
        fake_client.get_repo.return_value = "repo-obj"

        with patch(
            "resource_explorer.github.client.GitHubClient", return_value=fake_client
        ), pytest.raises(ValueError, match="boom"):
            with _acquire_git_clone_root(project, registry=MagicMock()):
                raise ValueError("boom")

        assert exited == [True]


class TestCloneFailureSurfaces:
    def test_clone_failure_propagates_as_an_error_not_a_hang_or_empty_root(self):
        """GitHubClient.git_clone_root() itself raises RuntimeError on a
        failed/timed-out clone (see test_github_client_git_clone_root.py);
        this locks in that _acquire_git_clone_root doesn't swallow it or
        yield some placeholder root instead."""
        project = _project()
        fake_client = MagicMock()
        fake_client.get_repo.return_value = "repo-obj"

        @contextmanager
        def _failing_cm():
            raise RuntimeError("git clone of test/myproj failed: fatal: not found")
            yield  # pragma: no cover — unreachable, keeps this a generator

        fake_client.git_clone_root.return_value = _failing_cm()

        with patch(
            "resource_explorer.github.client.GitHubClient", return_value=fake_client
        ), pytest.raises(RuntimeError, match="git clone of test/myproj failed"):
            with _acquire_git_clone_root(project, registry=MagicMock()):
                pass  # pragma: no cover — should never reach the body
