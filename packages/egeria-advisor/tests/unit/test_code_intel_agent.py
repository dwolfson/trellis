import pytest
from advisor.agents.code_intel_agent import (
    get_class_for_method,
    check_inheritance,
    get_class_hierarchy,
    get_codebase_stats,
    get_code_intel_agent
)
from advisor.code_symbol_store import get_symbol_store
from advisor.data_prep.code_parser import CodeElement
from advisor.db_consolidated import get_db_manager

def test_code_intel_agent():
    store = get_symbol_store()
    test_col = "test_col_intel_dummy"
    store.clear_collection(test_col)
    
    # Insert some inheritance structure:
    # BaseClass
    # ClassA(BaseClass)
    # ClassB(ClassA)
    el_base = CodeElement(
        type="class",
        name="BaseClass",
        file_path="test_file.py",
        line_number=1,
        end_line_number=10,
        docstring="Base class",
        signature="class BaseClass",
        body="...",
        bases=[]
    )
    
    el_a = CodeElement(
        type="class",
        name="ClassA",
        file_path="test_file.py",
        line_number=11,
        end_line_number=20,
        docstring="Class A",
        signature="class ClassA(BaseClass)",
        body="...",
        bases=["BaseClass"]
    )
    
    el_b = CodeElement(
        type="class",
        name="ClassB",
        file_path="test_file.py",
        line_number=21,
        end_line_number=30,
        docstring="Class B",
        signature="class ClassB(ClassA)",
        body="...",
        bases=["ClassA"]
    )
    
    el_method = CodeElement(
        type="method",
        name="some_test_method",
        file_path="test_file.py",
        line_number=25,
        end_line_number=28,
        docstring="A method in ClassB",
        signature="def some_test_method(self)",
        body="...",
        parent_class="ClassB"
    )
    
    store.upsert_symbols(test_col, [el_base, el_a, el_b, el_method])
    
    # 1. Test get_class_for_method
    res_method = get_class_for_method("some_test_method", test_col)
    assert len(res_method) == 1
    assert res_method[0]["parent_class"] == "ClassB"
    
    # 2. Test check_inheritance
    res_inh = check_inheritance("ClassB", "BaseClass", test_col)
    assert res_inh["inherits"] is True
    assert len(res_inh["path"]) == 1
    assert res_inh["path"][0]["depth"] == 2
    
    res_inh_false = check_inheritance("BaseClass", "ClassB", test_col)
    assert res_inh_false["inherits"] is False
    
    # 3. Test get_class_hierarchy
    res_hier = get_class_hierarchy("ClassA", test_col)
    assert len(res_hier["ancestors"]) == 1
    assert res_hier["ancestors"][0]["class_name"] == "BaseClass"
    assert len(res_hier["descendants"]) == 1
    assert res_hier["descendants"][0]["class_name"] == "ClassB"
    
    # 4. Test get_codebase_stats
    stats = get_codebase_stats(test_col)
    assert stats["classes"] == 3
    assert stats["methods"] == 1
    assert stats["total_loc"] == (10 - 1 + 1) + (20 - 11 + 1) + (30 - 21 + 1) + (28 - 25 + 1)
    
    # 5. Test CodeIntelAgent handler
    agent = get_code_intel_agent()
    # stats query
    res_handle_stats = agent.handle(f"How many classes are defined in {test_col}?")
    assert res_handle_stats["query_type"] == "code_intel"
    
    # inheritance query
    res_handle_inh = agent.handle(f"Does ClassB inherit from BaseClass in {test_col}?")
    assert res_handle_inh["query_type"] == "code_intel"
    
    # Clean up
    store.clear_collection(test_col)
