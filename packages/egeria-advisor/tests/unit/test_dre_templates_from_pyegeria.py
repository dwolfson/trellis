"""B2 (BRIEF EA-CATCHUP-AND-DASHBOARDS-2026-11-10): EA reads Dr.Egeria
templates from the installed pyegeria when it ships them, and falls back to
its old paths, with a logged note, when it does not.

Every EA template loader is checked — TemplateIndex (the Dr.Egeria action
agent), agents.tools._templates_root (template tool, /api/templates fields,
plan composition) and CommandKeywordIndex — because each had its own path
list and they had drifted to different copies.
"""
import sys
import types

import pytest

import md_processing

from advisor import dre_templates
from advisor.agents import tools
from advisor.agents.dr_egeria_agent import TemplateIndex
from advisor.command_keyword_index import CommandKeywordIndex


def _write(root, level, family, command, body=""):
    d = root / level / family
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{command.replace(' ', '_')}.md").write_text(
        f"___\n\n## {command}\n> test\n\n### Display Name\n>\t**Input Required**: True\n{body}",
        encoding="utf-8",
    )


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    """A fake pyegeria `md_processing.templates` backed by tmp_path."""
    root = tmp_path / "pkg"
    for level in ("basic", "advanced"):
        _write(root, level, "Views & Reports", "Create Dashboard Sheet")
        _write(root, level, "Glossary", "Create Glossary")
    _write(root, "advanced", "Glossary", "Link Term-Term Relationship")

    fake = types.ModuleType("md_processing.templates")
    fake.templates_source = lambda level="basic": "package"
    fake.templates_root = lambda level="basic": root / level
    monkeypatch.setitem(sys.modules, "md_processing.templates", fake)
    monkeypatch.setattr(md_processing, "templates", fake, raising=False)
    return root


@pytest.fixture
def no_accessor(monkeypatch):
    """An installed pyegeria that predates md_processing.templates."""
    monkeypatch.delattr(md_processing, "templates", raising=False)
    monkeypatch.setitem(sys.modules, "md_processing.templates", None)
    monkeypatch.setattr(dre_templates, "_fallback_logged", set())


class TestPackagedTemplatesWin:
    def test_root_is_the_packaged_directory(self, packaged):
        assert dre_templates.installed_templates_root() == packaged
        assert dre_templates.installed_templates_source() == "package"

    def test_template_index_reads_packaged(self, packaged):
        idx = TemplateIndex()
        hit = idx.get_by_name("Create Dashboard Sheet", tier="basic")
        assert hit is not None
        assert hit["file_path"].startswith(str(packaged))
        assert hit["family"] == "Views & Reports"
        assert {e["tier"] for e in idx._entries} == {"basic", "advanced"}

    def test_tools_root_is_packaged(self, packaged, monkeypatch):
        # Even with a workspace templates dir configured, the packaged copy wins.
        monkeypatch.setenv("EGERIA_ROOT_PATH", str(packaged.parent))
        assert tools._templates_root() == packaged

    def test_keyword_index_scans_packaged_basic(self, packaged):
        assert CommandKeywordIndex()._find_template_root() == packaged / "basic"

    def test_no_fallback_note_when_packaged(self, packaged, monkeypatch):
        notes = []
        monkeypatch.setattr(dre_templates, "note_fallback", lambda *a: notes.append(a))
        TemplateIndex().load()
        tools._templates_root()
        CommandKeywordIndex()._find_template_root()
        assert notes == []

    def test_missing_level_means_unavailable(self, packaged, monkeypatch):
        sys.modules["md_processing.templates"].templates_source = (
            lambda level="basic": "missing" if level == "advanced" else "package"
        )
        assert dre_templates.installed_templates_root() is None


class TestFallbackWhenOlderPyegeria:
    def test_root_is_none(self, no_accessor):
        assert dre_templates.installed_templates_root() is None
        assert dre_templates.installed_templates_source() == "unavailable"

    def test_tools_falls_back_to_legacy_and_logs_once(self, no_accessor, monkeypatch, tmp_path):
        legacy = tmp_path / "legacy"
        monkeypatch.setattr(tools, "_legacy_templates_root", lambda: legacy)
        logged = []
        monkeypatch.setattr(dre_templates.logger, "info", lambda msg: logged.append(msg))
        assert tools._templates_root() == legacy
        assert tools._templates_root() == legacy
        assert len(logged) == 1
        assert "falling back" in logged[0] and str(legacy) in logged[0]

    def test_template_index_falls_back(self, no_accessor, monkeypatch, tmp_path):
        legacy = tmp_path / "clone"
        _write(legacy, "basic", "Glossary", "Create Glossary")
        monkeypatch.setattr(TemplateIndex, "_legacy_base_paths", lambda self: [legacy])
        idx = TemplateIndex()
        assert idx.get_by_name("Create Glossary")["file_path"].startswith(str(legacy))

    def test_keyword_index_falls_back(self, no_accessor, monkeypatch, tmp_path):
        monkeypatch.setattr(
            CommandKeywordIndex, "_find_legacy_template_root", lambda self: tmp_path
        )
        assert CommandKeywordIndex()._find_template_root() == tmp_path


def test_real_installed_pyegeria_if_it_ships_templates():
    """Against whatever pyegeria is installed: if it has the accessor, EA
    sees the Views & Reports family the 2026-08-17 clone lacked."""
    if dre_templates.installed_templates_root() is None:
        pytest.skip("installed pyegeria predates md_processing.templates")
    idx = TemplateIndex()
    assert idx.get_by_name("Create Dashboard Sheet", tier="basic") is not None
    glossary = idx.get_by_name("Create Glossary", tier="basic")
    text = open(glossary["file_path"], encoding="utf-8").read()
    assert "### Zone Membership" in text
