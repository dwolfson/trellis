import pytest
from unittest.mock import MagicMock
from advisor.agents.examples_agent import get_examples_agent

def test_examples_agent_composite_flow(monkeypatch, tmp_path):
    # 1. Get singleton agent instance
    agent = get_examples_agent()
    
    # 2. Mock ExamplesAgent fallback methods to bypass LLM / Ollama calls
    def mock_fallback(query, perspective=None):
        return f"def my_mock_code():\n    pass # Mock code example for {query}"
        
    def mock_fallback_api_reference(query, perspective=None):
        return f"| Mock Method | Description |\n|---|---|\n| mock_method | Mock API reference for {query}"
        
    monkeypatch.setattr(agent, "_fallback", mock_fallback)
    monkeypatch.setattr(agent, "_fallback_api_reference", mock_fallback_api_reference)
    
    # 3. Mock _find_dre_template_raw to simulate a Dr.Egeria template match
    mock_template = "**Family: glossary | Template: create_glossary**\n\n## Create Glossary\n### Display Name\n"
    monkeypatch.setattr(
        "advisor.agents.tools._find_dre_template_raw", 
        lambda query, level="basic", perspective=None: mock_template
    )
    
    # 4. Mock get_report_spec_doc_manager list_inbox and simulate the file read
    mock_spec_entry = {
        "doc_id": "report_123_glossary_overview",
        "title": "Glossary Overview Report",
        "status": "Active",
        "folder": "inbox",
        "path": str(tmp_path / "report_123_glossary_overview.md")
    }
    
    # Create the mock spec file with ### Description
    spec_file = tmp_path / "report_123_glossary_overview.md"
    spec_file.write_text("""
# Glossary Overview Report
## Create Report Spec
### Description
A custom report displaying details of Egeria glossaries.
""", encoding="utf-8")
    
    class MockDocManager:
        def list_inbox(self):
            return [mock_spec_entry]
            
    monkeypatch.setattr("advisor.report_spec_docs.get_report_spec_doc_manager", lambda: MockDocManager())
    
    # 5. Test code help / example mode (which invokes _fallback)
    res_code = agent.handle("glossary", perspective="developer")
    
    assert res_code["query_type"] == "example"
    assert "def my_mock_code():" in res_code["response"]
    assert "Related Dr.Egeria Templates" in res_code["response"]
    assert "## Create Glossary" in res_code["response"]
    assert "Related Report Specs" in res_code["response"]
    assert "Glossary Overview Report" in res_code["response"]
    assert "report_123_glossary_overview" in res_code["response"]
    assert "A custom report displaying details of Egeria glossaries." in res_code["response"]
    
    # 6. Test api reference/method discovery mode
    res_ref = agent.handle("what methods are available for glossary", perspective="developer")
    
    assert res_ref["query_type"] == "code_search"
    assert "| Mock Method |" in res_ref["response"]
    assert "Related Dr.Egeria Templates" in res_ref["response"]
    assert "Related Report Specs" in res_ref["response"]
