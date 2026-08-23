"""Tests for resource_explorer.github.repo_role — offline and hermetic
(no network). Github/GithubException are mocked the same way
test_doc_locations.py mocks them.

Covers: README-intent-beats-inference (finding 60), each of the seven
roles firing from its own signal, multi-role ranking with a primary,
absence-as-evidence in both directions (trellis.md), and graceful
no-token/network-failure degradation."""
from __future__ import annotations

from unittest.mock import MagicMock

from github import GithubException

from resource_explorer.github import repo_role as rr


# ---------------------------------------------------------------------------
# Helpers for the mocked-Github tests
# ---------------------------------------------------------------------------

def _tree(paths: list[str], truncated: bool = False):
    tree = MagicMock()
    tree.truncated = truncated
    entries = []
    for p in paths:
        e = MagicMock()
        e.path = p
        e.type = "blob"
        entries.append(e)
    tree.tree = entries
    return tree


def _fake_repo(
    full_name="owner/repo",
    name="repo",
    owner_login="owner",
    description="",
    topics=None,
    homepage="",
    default_branch="main",
    tree_paths=None,
    readme_text=None,
    file_contents=None,  # dict path -> text, for get_contents()
):
    repo = MagicMock()
    repo.full_name = full_name
    repo.name = name
    repo.owner.login = owner_login
    repo.description = description
    repo.homepage = homepage
    repo.default_branch = default_branch
    repo.get_topics.return_value = topics or []
    repo.get_git_tree.return_value = _tree(tree_paths or [])

    if readme_text is not None:
        readme = MagicMock()
        readme.decoded_content = readme_text.encode("utf-8")
        repo.get_readme.return_value = readme
    else:
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})

    file_contents = file_contents or {}

    def get_contents(path):
        if path in file_contents:
            c = MagicMock()
            c.decoded_content = file_contents[path].encode("utf-8")
            return c
        raise GithubException(404, data={"message": "Not Found"})

    repo.get_contents.side_effect = get_contents
    return repo


def _fake_gh(repo):
    gh = MagicMock()
    gh.get_repo.return_value = repo
    # doc_locations.resolve_doc_locations tries org then user; make both
    # come back empty so sibling-repo listing never interferes here.
    gh.get_organization.side_effect = GithubException(404, data={"message": "Not Found"})
    gh.get_user.return_value.get_repos.return_value = []
    return gh


# ---------------------------------------------------------------------------
# Pure-function tests: README-stated intent
# ---------------------------------------------------------------------------

class TestReadmeStatedIntent:
    def test_tutorial_intent_is_captured_with_quoted_line(self):
        readme = "# workshops\n\nThis repository is a workshop for learning OpenLineage."
        hits = rr._readme_stated_intent(readme)
        assert any(role == rr.ROLE_TUTORIAL for role, _ in hits)
        role, evidence = next(h for h in hits if h[0] == rr.ROLE_TUTORIAL)
        assert "workshop" in evidence.lower()

    def test_samples_intent_captured(self):
        readme = "This project contains sample code demonstrating the client SDK."
        hits = rr._readme_stated_intent(readme)
        assert any(role == rr.ROLE_SAMPLES for role, _ in hits)

    def test_library_intent_captured(self):
        readme = "This repo is a Python library for talking to the Foo API."
        hits = rr._readme_stated_intent(readme)
        assert any(role == rr.ROLE_LIBRARY for role, _ in hits)

    def test_documentation_intent_captured(self):
        readme = "This repository contains the assets required to build the Kubernetes website and documentation."
        hits = rr._readme_stated_intent(readme)
        assert any(role == rr.ROLE_DOCUMENTATION for role, _ in hits)

    def test_bare_keyword_without_subject_does_not_fire(self):
        # finding 60: "'Workshop' and 'example' appear in the READMEs of
        # real software" — an incidental mention must not fire the pattern.
        readme = "See our workshop talks and examples in the wiki for more info."
        hits = rr._readme_stated_intent(readme)
        assert hits == []

    def test_empty_readme_returns_empty(self):
        assert rr._readme_stated_intent("") == []
        assert rr._readme_stated_intent(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pure-function tests: deployment artifacts
# ---------------------------------------------------------------------------

class TestDeploymentArtifacts:
    def test_dockerfile_matches(self):
        assert "Dockerfile" in rr._deployment_artifacts(["Dockerfile", "README.md"])

    def test_dockerfile_variant_matches(self):
        assert "docker/Dockerfile.prod" in rr._deployment_artifacts(["docker/Dockerfile.prod"])

    def test_compose_file_matches(self):
        assert "docker-compose.yml" in rr._deployment_artifacts(["docker-compose.yml"])
        assert "compose.prod.yaml" in rr._deployment_artifacts(["compose.prod.yaml"])

    def test_helm_dir_matches(self):
        hits = rr._deployment_artifacts(["helm/Chart.yaml", "src/main.go"])
        assert "helm/Chart.yaml" in hits

    def test_charts_dir_matches(self):
        hits = rr._deployment_artifacts(["charts/foo/values.yaml"])
        assert hits == ["charts/foo/values.yaml"]

    def test_no_deployment_artifacts_returns_empty(self):
        assert rr._deployment_artifacts(["pyproject.toml", "src/foo.py"]) == []


# ---------------------------------------------------------------------------
# Pure-function tests: tutorial/sample dirs, ipynb ratio, doc dominance
# ---------------------------------------------------------------------------

class TestTutorialSampleDirs:
    def test_tutorials_dir_detected(self):
        hits = rr._tutorial_sample_dir_evidence(["tutorials/01-intro.md", "src/main.py"])
        assert hits[rr.ROLE_TUTORIAL] == ["tutorials/"]

    def test_workshops_dir_detected(self):
        hits = rr._tutorial_sample_dir_evidence(["workshops/airflow/docker-compose.yml"])
        assert hits[rr.ROLE_TUTORIAL] == ["workshops/"]

    def test_samples_dir_detected(self):
        hits = rr._tutorial_sample_dir_evidence(["samples/basic/main.go"])
        assert hits[rr.ROLE_SAMPLES] == ["samples/"]

    def test_examples_dir_detected(self):
        hits = rr._tutorial_sample_dir_evidence(["examples/quickstart/app.py"])
        assert hits[rr.ROLE_SAMPLES] == ["examples/"]

    def test_no_markers_returns_empty_lists(self):
        hits = rr._tutorial_sample_dir_evidence(["src/main.py", "README.md"])
        assert hits[rr.ROLE_TUTORIAL] == []
        assert hits[rr.ROLE_SAMPLES] == []


class TestIpynbPresence:
    """Notebook evidence is PRESENCE, not proportion. A ratio gate assumed
    single-role classification and so could never let a large repo carry a
    secondary `tutorial` role — which contradicts §5.5b's multi-valued
    decision — and it was an invented cut-off besides."""

    def test_enough_notebooks_fires(self):
        paths = [f"nb{i}.ipynb" for i in range(6)] + ["README.md"]
        evidence = rr._ipynb_ratio_evidence(paths)
        assert evidence is not None
        assert "ipynb" in evidence

    def test_a_large_repo_with_real_notebooks_still_fires(self):
        """The `odpi/egeria-workspaces` case that motivated the change: 37 real
        Jupyter notebooks, 0.6% of the tree. Unambiguously tutorial material,
        and invisible to a 20%-ratio gate."""
        paths = [f"nb{i}.ipynb" for i in range(37)] + [f"src/f{i}.py" for i in range(6000)]
        evidence = rr._ipynb_ratio_evidence(paths)
        assert evidence is not None
        assert "37" in evidence

    def test_the_ratio_is_still_reported_as_evidence(self):
        """Dropped as a GATE, kept as reported evidence so a reader can weigh
        it — the same "report the fraction, do not invent a cut-off" posture as
        finding 77's ranking work."""
        paths = [f"nb{i}.ipynb" for i in range(37)] + [f"src/f{i}.py" for i in range(6000)]
        assert "%" in rr._ipynb_ratio_evidence(paths)

    def test_incidental_notebooks_do_not_fire(self):
        paths = ["nb.ipynb"] + [f"src/f{i}.py" for i in range(20)]
        assert rr._ipynb_ratio_evidence(paths) is None

    def test_too_few_notebooks_does_not_fire(self):
        assert rr._ipynb_ratio_evidence(["a.ipynb", "b.ipynb"]) is None


class TestDocumentationDominance:
    def test_repo_name_matches_docs_suffix(self):
        evidence = rr._documentation_dominance_evidence("egeria-docs", ["a.md"] * 10)
        assert any("naming convention" in e for e in evidence)

    def test_repo_name_matches_website(self):
        evidence = rr._documentation_dominance_evidence("website", [])
        assert any("naming convention" in e for e in evidence)

    def test_github_io_suffix_matches(self):
        assert rr._name_matches_doc_convention("someorg.github.io") is True

    def test_ordinary_repo_name_does_not_match(self):
        assert rr._name_matches_doc_convention("milvus") is False

    def test_content_ratio_fires_on_markdown_heavy_repo(self):
        paths = [f"content/page{i}.md" for i in range(8)] + ["mkdocs.yml"]
        evidence = rr._documentation_dominance_evidence("somewebsite", paths)
        assert any("doc-shaped content" in e for e in evidence)
        assert any("mkdocs.yml" in e for e in evidence)

    def test_code_heavy_repo_does_not_fire_content_ratio(self):
        paths = [f"src/f{i}.py" for i in range(10)] + ["README.md"]
        evidence = rr._documentation_dominance_evidence("milvus", paths)
        assert evidence == []


# ---------------------------------------------------------------------------
# Full classify_repo_role() — one signal at a time
# ---------------------------------------------------------------------------

class TestClassifyRepoRoleSingleSignals:
    def test_documentation_role_from_name_and_content(self):
        repo = _fake_repo(
            full_name="odpi/egeria-docs", name="egeria-docs", owner_login="odpi",
            tree_paths=[f"docs/page{i}.md" for i in range(8)],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("odpi/egeria-docs", client=gh)
        assert result.primary is not None
        assert result.primary.role == rr.ROLE_DOCUMENTATION

    def test_application_role_from_deployment_artifacts(self):
        repo = _fake_repo(
            full_name="prometheus/prometheus", name="prometheus", owner_login="prometheus",
            tree_paths=["Dockerfile", "docker-compose.yml", "cmd/prometheus/main.go"],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("prometheus/prometheus", client=gh)
        assert result.has_role(rr.ROLE_APPLICATION)

    def test_middleware_role_when_keyword_present(self):
        repo = _fake_repo(
            full_name="acme/gateway", name="gateway", owner_login="acme",
            description="A lightweight API gateway and message broker middleware.",
            tree_paths=["Dockerfile", "src/main.go"],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("acme/gateway", client=gh)
        assert result.has_role(rr.ROLE_MIDDLEWARE)
        assert not result.has_role(rr.ROLE_APPLICATION)

    def test_library_role_from_pyproject_build_system(self):
        repo = _fake_repo(
            full_name="acme/pylib", name="pylib", owner_login="acme",
            tree_paths=["pyproject.toml", "src/pylib/__init__.py"],
            file_contents={"pyproject.toml": "[build-system]\nrequires = ['hatchling']\n"},
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("acme/pylib", client=gh)
        assert result.has_role(rr.ROLE_LIBRARY)

    def test_library_role_from_gradle_manifest(self):
        # odpi/egeria is a Gradle-built JVM monorepo with no pom.xml/go.mod
        # at all — live-verified this session; without build.gradle in the
        # bare-presence list it gets zero manifest evidence.
        repo = _fake_repo(
            full_name="odpi/egeria", name="egeria", owner_login="odpi",
            tree_paths=["build.gradle", "settings.gradle", "src/main/java/Foo.java"],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("odpi/egeria", client=gh)
        assert result.has_role(rr.ROLE_LIBRARY)

    def test_pyproject_without_build_system_does_not_fire_library(self):
        repo = _fake_repo(
            full_name="acme/toolsonly", name="toolsonly", owner_login="acme",
            tree_paths=["pyproject.toml"],
            file_contents={"pyproject.toml": "[tool.ruff]\nline-length = 100\n"},
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("acme/toolsonly", client=gh)
        assert not result.has_role(rr.ROLE_LIBRARY)

    def test_tool_role_from_console_scripts(self):
        repo = _fake_repo(
            full_name="acme/clitool", name="clitool", owner_login="acme",
            tree_paths=["pyproject.toml", "src/clitool/__main__.py"],
            file_contents={"pyproject.toml": "[project.scripts]\nclitool = 'clitool:main'\n"},
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("acme/clitool", client=gh)
        assert result.has_role(rr.ROLE_TOOL)

    def test_tutorial_role_from_readme_intent(self):
        repo = _fake_repo(
            full_name="OpenLineage/workshops", name="workshops", owner_login="OpenLineage",
            readme_text="This repository is a workshop showing how to deploy OpenLineage with Airflow.",
            tree_paths=["e3-airflow/docker-compose.yml", "flower/docker-compose.yml"],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("OpenLineage/workshops", client=gh)
        assert result.primary.role == rr.ROLE_TUTORIAL
        assert result.stated_intent is True

    def test_samples_role_from_dir_marker(self):
        repo = _fake_repo(
            full_name="acme/examples", name="examples", owner_login="acme",
            tree_paths=["examples/quickstart/main.py", "examples/advanced/main.py"],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("acme/examples", client=gh)
        assert result.has_role(rr.ROLE_SAMPLES)


# ---------------------------------------------------------------------------
# README-intent-beats-inference (finding 58/60)
# ---------------------------------------------------------------------------

class TestReadmeIntentBeatsInference:
    def test_stated_tutorial_outranks_deployment_artifacts(self):
        # exactly finding 58's `workshops` case: 44 of 45 components came
        # from compose files, but the README says the intent is a tutorial.
        repo = _fake_repo(
            full_name="OpenLineage/workshops", name="workshops", owner_login="OpenLineage",
            readme_text="This repo is a workshop for learning OpenLineage end to end.",
            tree_paths=[
                "e3-airflow/docker-compose.yml",
                "flower/docker-compose.yml",
                "airflow-scheduler/Dockerfile",
            ],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("OpenLineage/workshops", client=gh)

        # application still fired structurally and is retained as evidence...
        assert result.has_role(rr.ROLE_APPLICATION)
        # ...but the stated tutorial intent is primary, not application.
        assert result.primary.role == rr.ROLE_TUTORIAL
        assert result.stated_intent is True
        assert any("overrides" in n or "override" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Multi-role ranking with a primary (no stated intent)
# ---------------------------------------------------------------------------

class TestMultiRoleRanking:
    def test_application_and_library_both_present_application_primary(self):
        # trellis.md's own case in miniature: a web app that also ships a
        # published package manifest. No README intent stated, so the
        # structural precedence decides — deployment artifact outranks a
        # bare manifest file per _PRIMARY_PRECEDENCE.
        repo = _fake_repo(
            full_name="acme/monorepo", name="monorepo", owner_login="acme",
            tree_paths=["Dockerfile", "pyproject.toml", "src/app.py"],
            file_contents={"pyproject.toml": "[build-system]\nrequires = ['hatchling']\n"},
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("acme/monorepo", client=gh)

        assert result.has_role(rr.ROLE_APPLICATION)
        assert result.has_role(rr.ROLE_LIBRARY)
        assert result.primary.role == rr.ROLE_APPLICATION
        assert result.stated_intent is False

    def test_documentation_outranks_application_when_both_fire(self):
        repo = _fake_repo(
            full_name="kubernetes/website", name="website", owner_login="kubernetes",
            tree_paths=["Dockerfile"] + [f"content/en/docs/page{i}.md" for i in range(8)],
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("kubernetes/website", client=gh)

        assert result.has_role(rr.ROLE_APPLICATION)  # the site's own Dockerfile
        assert result.primary.role == rr.ROLE_DOCUMENTATION


# ---------------------------------------------------------------------------
# Absence as evidence, both directions
# ---------------------------------------------------------------------------

class TestAbsenceAsEvidence:
    def test_no_deployment_artifacts_confirms_library(self):
        # trellis.md's exact case: "no Dockerfiles, no compose files... it
        # has no deployment perspective at all" — confirmation, not a gap.
        repo = _fake_repo(
            full_name="acme/pylib", name="pylib", owner_login="acme",
            tree_paths=["pyproject.toml", "src/pylib/__init__.py"],
            file_contents={"pyproject.toml": "[build-system]\nrequires = ['hatchling']\n"},
        )
        gh = _fake_gh(repo)
        result = rr.classify_repo_role("acme/pylib", client=gh)

        lib = next(r for r in result.roles if r.role == rr.ROLE_LIBRARY)
        confirming = [e for e in lib.evidence if e.signal == "absence-as-evidence"]
        assert confirming
        assert "confirms library" in confirming[0].detail

    def test_no_deployment_artifacts_weakens_application_inferred_elsewhere(self):
        # application asserted only via a middleware-less entry point path
        # is not directly testable since entry points map to `tool`, so
        # simulate the weakening path directly against the mutator.
        roles = {rr.ROLE_APPLICATION: rr.RoleResult(role=rr.ROLE_APPLICATION)}
        roles[rr.ROLE_APPLICATION].add("some-other-signal", "inferred without a deployment artifact")
        rr._apply_absence_evidence(roles, has_deployment=False)
        weakening = [e for e in roles[rr.ROLE_APPLICATION].evidence if e.signal == "absence-as-evidence"]
        assert weakening
        assert "weakens application" in weakening[0].detail

    def test_deployment_present_adds_no_absence_notes(self):
        roles = {rr.ROLE_LIBRARY: rr.RoleResult(role=rr.ROLE_LIBRARY)}
        rr._apply_absence_evidence(roles, has_deployment=True)
        assert roles[rr.ROLE_LIBRARY].evidence == []


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_unreachable_repo_degrades_to_empty_with_note(self):
        gh = MagicMock()
        gh.get_repo.side_effect = GithubException(403, data={"message": "rate limit exceeded"})

        result = rr.classify_repo_role("owner/repo", client=gh)

        assert result.roles == []
        assert result.primary is None
        assert result.notes
        assert "owner/repo" in result.notes[0]

    def test_readme_fetch_failure_does_not_prevent_other_signals(self):
        repo = _fake_repo(
            full_name="acme/pylib", name="pylib", owner_login="acme",
            tree_paths=["pyproject.toml"],
            file_contents={"pyproject.toml": "[build-system]\nrequires = ['hatchling']\n"},
        )
        repo.get_readme.side_effect = GithubException(500, data={"message": "server error"})
        gh = _fake_gh(repo)

        result = rr.classify_repo_role("acme/pylib", client=gh)

        assert result.has_role(rr.ROLE_LIBRARY)

    def test_no_role_signals_found_returns_empty_with_note(self):
        repo = _fake_repo(
            full_name="acme/empty", name="empty", owner_login="acme",
            tree_paths=["LICENSE"],
        )
        gh = _fake_gh(repo)

        result = rr.classify_repo_role("acme/empty", client=gh)

        assert result.roles == []
        assert any("no role signals" in n for n in result.notes)
