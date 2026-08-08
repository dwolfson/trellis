"""
Pytest configuration and shared fixtures for Egeria Advisor tests.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def sample_query():
    """Sample user query for testing."""
    return "How do I create a glossary?"


@pytest.fixture
def sample_code_query():
    """Sample code search query."""
    return "Show me examples of using the collection manager"


@pytest.fixture
def sample_quantitative_query():
    """Sample quantitative query."""
    return "How many lines of code are in the project?"


@pytest.fixture
def sample_relationship_query():
    """Sample relationship query."""
    return "What does the GlossaryManager import?"


@pytest.fixture
def mock_vector_results():
    """Mock vector search results."""
    return [
        {
            "id": "1",
            "distance": 0.85,
            "entity": {
                "content": "Example code for creating a glossary",
                "file_path": "examples/glossary_example.py",
                "type": "example"
            }
        },
        {
            "id": "2",
            "distance": 0.78,
            "entity": {
                "content": "GlossaryManager class documentation",
                "file_path": "pyegeria/glossary_manager.py",
                "type": "documentation"
            }
        }
    ]


@pytest.fixture
def mock_llm_response():
    """Mock LLM response."""
    return {
        "response": "To create a glossary in Egeria, you can use the GlossaryManager class...",
        "sources": ["examples/glossary_example.py", "pyegeria/glossary_manager.py"]
    }


@pytest.fixture
def test_config():
    """Test configuration."""
    return {
        "pgvector_host": "localhost",
        "pgvector_port": 5442,
        "ollama_host": "http://localhost:11434",
        "model_name": "llama3.2:3b",
        "embedding_model": "nomic-embed-text:latest",
        "top_k": 5,
        "temperature": 0.7
    }


@pytest.fixture
def sample_analytics_data():
    """Sample analytics data for testing."""
    return {
        "total_files": 100,
        "total_lines": 50000,
        "total_sloc": 30000,
        "average_complexity": 5.2,
        "average_maintainability": 65.3,
        "by_folder": {
            "pyegeria": {
                "files": 80,
                "loc": 40000,
                "sloc": 25000
            },
            "tests": {
                "files": 20,
                "loc": 10000,
                "sloc": 5000
            }
        }
    }


@pytest.fixture
def sample_relationship_data():
    """Sample relationship data for testing."""
    return {
        "modules": [
            {
                "name": "pyegeria.glossary_manager",
                "imports": ["pyegeria.client", "pyegeria.utils"],
                "classes": ["GlossaryManager"],
                "functions": ["create_glossary", "find_glossary"]
            }
        ],
        "import_graph": {
            "pyegeria.glossary_manager": ["pyegeria.client", "pyegeria.utils"]
        },
        "call_graph": {
            "create_glossary": ["_validate_input", "_make_request"]
        }
    }


@pytest.fixture
def sample_report_specs():
    """Sample report spec data for testing."""
    return {
        "total_specs": 88,
        "families": {
            "Glossary": ["Terms", "Glossaries"],
            "Collections": ["Collections", "BasicCollections"]
        },
        "target_types": {
            "GlossaryTerm": ["Terms"],
            "Collection": ["Collections"]
        },
        "output_types": ["DICT", "TABLE", "JSON", "MD"],
        "specs": [
            {
                "name": "Terms",
                "heading": "Glossary Terms",
                "description": "Display glossary term information",
                "target_type": "GlossaryTerm",
                "family": "Glossary",
                "aliases": ["Term"],
                "formats": [
                    {
                        "types": ["DICT", "TABLE"],
                        "columns": [
                            {"name": "Display Name", "key": "display_name"},
                            {"name": "Description", "key": "description"}
                        ]
                    }
                ]
            }
        ]
    }


# Markers for test categorization
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "quality: Quality tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "requires_pgvector: Tests that require pgvector")
    config.addinivalue_line("markers", "requires_ollama: Tests that require Ollama")