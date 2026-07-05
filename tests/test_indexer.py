import os
import tempfile
from pathlib import Path
import sqlite3
import pytest

from indexer.indexer import CodeIndexer
from indexer.parser import CodeParser

@pytest.fixture
def temp_project():
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a CamelCase project name
        project_dir = Path(tmpdir) / "TestProject"
        project_dir.mkdir()
        yield project_dir


def test_indexer_lowercase_project_id(temp_project):
    """Test that project ID is lowercased."""
    indexer = CodeIndexer(str(temp_project))
    assert indexer.project_id == "testproject"
    indexer.close()


def test_indexer_gitignore_handling(temp_project):
    """Test that .gitignore and .basememignore rules are applied correctly."""
    # Setup test files
    (temp_project / ".gitignore").write_text("ignored_dir/\n*.txt\n")
    (temp_project / ".basememignore").write_text("secret_file.py\n")
    
    # Create files
    (temp_project / "ignored_dir").mkdir()
    (temp_project / "ignored_dir" / "test.py").write_text("def hidden(): pass")
    
    (temp_project / "valid.py").write_text("def valid(): pass")
    (temp_project / "readme.txt").write_text("Hello")
    (temp_project / "secret_file.py").write_text("def secret(): pass")
    
    indexer = CodeIndexer(str(temp_project))
    
    # Check _is_skipped
    assert indexer._is_skipped(str(temp_project / "ignored_dir" / "test.py")) is True
    assert indexer._is_skipped(str(temp_project / "readme.txt")) is True
    assert indexer._is_skipped(str(temp_project / "secret_file.py")) is True
    assert indexer._is_skipped(str(temp_project / "valid.py")) is False
    
    # Discover files should only yield valid.py
    files = list(indexer._discover_files(temp_project))
    assert len(files) == 1
    assert files[0].name == "valid.py"
    indexer.close()


def test_indexer_fuzzy_camelcase_search(temp_project):
    """Test fuzzy CamelCase segment searching."""
    (temp_project / "app.py").write_text(
        "class UserAccountController:\n"
        "    pass\n"
    )
    indexer = CodeIndexer(str(temp_project))
    indexer.index_project()
    
    # Exact match should work
    res = indexer.search_symbols("UserAccountController")
    assert len(res) == 1
    
    # Fuzzy segment search should work
    res = indexer.search_symbols("account")
    assert len(res) == 1
    assert res[0]["symbol_name"] == "UserAccountController"
    
    res2 = indexer.search_symbols("User")
    assert len(res2) == 1
    
    indexer.close()


def test_indexer_ast_references(temp_project):
    """Test that find_references uses AST edges before text fallback."""
    # File 1 defines a symbol
    (temp_project / "def_file.py").write_text(
        "def my_super_function():\n"
        "    pass\n"
    )
    # File 2 calls the symbol
    (temp_project / "call_file.py").write_text(
        "import def_file\n\n"
        "def another_function():\n"
        "    def_file.my_super_function()\n"
    )
    
    indexer = CodeIndexer(str(temp_project))
    indexer.index_project()
    
    # find_references should first yield the AST reference
    refs = indexer.find_references("my_super_function")
    assert len(refs) == 1
    assert refs[0]["file_path"] == "call_file.py"
    assert "[AST Usage]" in refs[0]["content"]
    assert refs[0]["line_number"] == 4
    
    indexer.close()


def test_indexer_type_filter(temp_project):
    """Test type filtering for search_symbols."""
    (temp_project / "app.py").write_text(
        "class Node:\n"
        "    pass\n"
        "def create_node():\n"
        "    pass\n"
    )
    indexer = CodeIndexer(str(temp_project))
    indexer.index_project()
    
    # Searching for node should return both
    res = indexer.search_symbols("node")
    assert len(res) == 2
    
    # Filter by type:class
    res2 = indexer.search_symbols("type:class node")
    assert len(res2) == 1
    assert res2[0]["symbol_type"] == "class"
    assert res2[0]["symbol_name"] == "Node"
    
    # Filter by type:function
    res3 = indexer.search_symbols("type:function node")
    assert len(res3) == 1
    assert res3[0]["symbol_type"] == "function"
    assert res3[0]["symbol_name"] == "create_node"
    
    # Filter by type:class only
    res4 = indexer.search_symbols("type:class")
    assert len(res4) == 1
    assert res4[0]["symbol_type"] == "class"
    assert res4[0]["symbol_name"] == "Node"
    
    indexer.close()

