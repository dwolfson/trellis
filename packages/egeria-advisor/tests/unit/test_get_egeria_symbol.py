"""Regression test: get_egeria_symbol must read via ReCodeSymbolReader
(resource_explorer.project_code_symbols), not the deprecated CodeSymbolStore
(code_symbols/code_relationships, unwritten since the AST-ownership-transfer
migration Phase 8) — the old call site silently always missed and fell
through to the vector-search fallback for every query."""
from unittest.mock import MagicMock, patch

from advisor.agents.tools import _get_egeria_symbol_raw


def _fake_reader(symbols=None, methods=None):
    reader = MagicMock()
    reader.search_symbols.return_value = symbols or []
    reader.methods_for_class.return_value = methods or []
    return reader


class TestGetEgeriaSymbolRaw:
    def test_uses_re_code_symbol_reader_not_deprecated_store(self):
        reader = _fake_reader(symbols=[{
            "collection": "pyegeria", "kind": "class", "name": "ProjectManager",
            "qualified_name": "pyegeria.project_manager.ProjectManager",
            "signature": "class ProjectManager", "parent_class": None,
            "docstring": "Manages projects.", "start_line": 1,
        }])
        with patch(
            "advisor.re_code_symbol_reader.get_re_code_symbol_reader", return_value=reader,
        ) as mock_get_reader:
            result = _get_egeria_symbol_raw("ProjectManager")

        mock_get_reader.assert_called_once()
        reader.search_symbols.assert_called_once_with(
            name_pattern="ProjectManager", collection="pyegeria", limit=5,
        )
        assert "ProjectManager" in result
        assert "Manages projects." in result

    def test_class_result_fetches_methods_via_reader(self):
        reader = _fake_reader(
            symbols=[{
                "collection": "pyegeria", "kind": "class", "name": "ProjectManager",
                "qualified_name": "pyegeria.project_manager.ProjectManager",
                "signature": "class ProjectManager", "parent_class": None,
                "docstring": "", "start_line": 1,
            }],
            methods=[{"name": "create_project", "signature": "(self, name)", "docstring": "Create a project."}],
        )
        with patch("advisor.re_code_symbol_reader.get_re_code_symbol_reader", return_value=reader):
            result = _get_egeria_symbol_raw("ProjectManager")

        reader.methods_for_class.assert_called_once_with("ProjectManager")
        assert "create_project" in result

    def test_no_symbols_falls_back_to_vector_search(self):
        reader = _fake_reader(symbols=[])
        fake_vec_store = MagicMock()
        fake_vec_store.search_specific_collections.return_value = MagicMock(results=[])
        with patch("advisor.re_code_symbol_reader.get_re_code_symbol_reader", return_value=reader), \
             patch("advisor.multi_collection_store.get_multi_collection_store", return_value=fake_vec_store):
            result = _get_egeria_symbol_raw("NotARealSymbol")

        assert "No symbol found" in result
