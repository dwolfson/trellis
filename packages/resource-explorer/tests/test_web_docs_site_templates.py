"""web_docs skips site-generator scaffolding (owner, 2026-11-11, option A).

egeria_docs' web_docs collection was 7 chunks of noise: mkdocs-material templates under
site/overrides and a meta-refresh redirect stub (tests/fixtures/web_docs_egeria_docs, the real
files). They are now skipped and counted; real HTML docs, including a complete page that happens to
sit in a folder called `partials`, are kept.
"""
from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from rich.console import Console

from resource_explorer.configdata.collection_config import COLLECTION_TYPES
from resource_explorer.ingestion import site_templates as st

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_docs_egeria_docs"
WEB = COLLECTION_TYPES["web_docs"]

REAL_PAGE = """<!DOCTYPE html>
<html lang="en"><head><title>Glossaries</title></head>
<body><h1>Glossaries</h1><p>A glossary is a collection of terms that describe the concepts of an
organization. Each term has a summary, a description and examples, and terms are linked by
relationships such as synonym and antonym. """ + "More real documentation text. " * 20 + """</p></body></html>
"""


@pytest.fixture
def pipeline(monkeypatch):
    from resource_explorer.ingestion import artifact_tree_sink
    from resource_explorer.ingestion.pipeline import IngestionPipeline
    p = IngestionPipeline.__new__(IngestionPipeline)
    p.console = Console(file=io.StringIO(), width=200)
    p.trees_for = []
    monkeypatch.setattr(artifact_tree_sink, "build_trees",
                        lambda files, slug, kind: p.trees_for.extend(path for path, _ in files) or None)
    monkeypatch.setattr(IngestionPipeline, "_report_tree_result", lambda self, result, slug: None, raising=False)
    return p


def _tree(tmp_path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    return tmp_path


def test_egeria_docs_html_is_all_scaffolding(pipeline, tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE / "site", root / "site")
    chunks = pipeline._ingest_web_docs(root, "egeria_docs", WEB)
    assert chunks == [] and pipeline.trees_for == []
    out = pipeline.console.file.getvalue()
    assert "skipped 6 site template file(s)" in out and "skipped 1 redirect stub file(s)" in out


def test_each_real_file_is_classified(tmp_path):
    reasons = {}
    for f in sorted((FIXTURE / "site").rglob("*.html")):
        rel = f.relative_to(FIXTURE).as_posix()
        reasons[rel] = st.skip_reason(rel, f.read_text(encoding="utf-8"))
    assert reasons == {
        "site/docs/egeria-docs/index.html": "redirect stub",
        "site/overrides/404.html": "site template",
        "site/overrides/home.html": "site template",
        "site/overrides/main.html": "site template",
        "site/overrides/partials/comments.html": "site template",  # no template syntax, not a full page
        "site/overrides/partials/header.html": "site template",
        "site/overrides/partials/logo.html": "site template",
    }


def test_real_docs_are_kept(pipeline, tmp_path):
    root = _tree(tmp_path, {
        "site/docs/glossaries/index.html": REAL_PAGE,
        "public/partials/index.html": REAL_PAGE,     # a rendered page in a folder named partials
        "docs/overrides.html": REAL_PAGE,            # a FILE named like a template folder
        "site/overrides/main.html": "{% extends 'base.html' %}{% block content %}x{% endblock %}",
    })
    chunks = pipeline._ingest_web_docs(root, "proj", WEB)
    paths = {c.metadata["file_path"] for c in chunks}
    assert paths == {"site/docs/glossaries/index.html", "public/partials/index.html", "docs/overrides.html"}
    assert set(pipeline.trees_for) == paths


def test_extra_docs_paths_are_filtered_too(pipeline, tmp_path):
    extra = _tree(tmp_path / "extra", {"_templates/layout.html": "{% block body %}{% endblock %}",
                                       "guide/index.html": REAL_PAGE})
    root = _tree(tmp_path / "repo", {})
    chunks = pipeline._ingest_web_docs(root, "proj", WEB, extra_paths=[("extra", extra)])
    assert {c.metadata["file_path"] for c in chunks} == {"extra/guide/index.html"}


@pytest.mark.parametrize("folder", sorted(st.SITE_TEMPLATE_DIRS))
def test_every_template_folder(folder):
    assert st.skip_reason(f"docs/{folder}/x.html", "<div>{{ page.title }}</div>") == "site template"
    assert st.skip_reason(f"docs/{folder}/x.html", "<footer>partial, no syntax</footer>") == "site template"
    assert st.skip_reason(f"docs/{folder}/x.html", REAL_PAGE) is None


def test_a_redirect_with_real_content_is_kept():
    page = REAL_PAGE.replace("<head>", '<head><meta http-equiv="refresh" content="30">')
    assert st.skip_reason("docs/live.html", page) is None
