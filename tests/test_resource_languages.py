"""Config and IaC formats indexed as resources.

The bundled language pack does not map .sql/.graphql/.yaml/.toml/Dockerfile/.tf
at all, so those files were skipped before they were ever opened. They are mapped
locally now and indexed as resources rather than callables, so the normal
pipeline (search, code_context, impact, memory links) works on them unchanged.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

from indexer.parser import CodeParser, detect_language_for_file  # noqa: E402

CASES = [
    ("a.sql", b"CREATE TABLE users (id INT);\nCREATE VIEW active AS SELECT 1;\n", {"users", "active"}),
    ("a.graphql", b"type User { id: ID! }\ninterface Node { id: ID! }\n", {"User", "Node"}),
    ("a.yaml", b"service:\n  name: api\n", {"service"}),
    ("a.toml", b"[package]\nname = \"x\"\n", {"package"}),
    ("Dockerfile", b"FROM alpine:3\nRUN echo hi\n", {"alpine"}),
    ("a.tf", b"resource \"aws_s3_bucket\" \"b\" {\n  bucket = \"x\"\n}\n", {"aws_s3_bucket"}),
]


@pytest.mark.parametrize("ext", [".sql", ".graphql", ".gql", ".yaml", ".yml", ".toml", ".tf"])
def test_extension_maps_to_a_language(ext):
    assert detect_language_for_file(f"x{ext}") is not None


def test_dockerfile_maps_by_filename():
    assert detect_language_for_file("Dockerfile") == "dockerfile"
    assert detect_language_for_file("some/dir/Dockerfile") == "dockerfile"


def test_existing_mappings_still_work():
    assert detect_language_for_file("x.py") == "python"
    assert detect_language_for_file("x.go") == "go"
    assert detect_language_for_file("x.mjs") == "javascript"


@pytest.mark.parametrize("filename,source,expected", CASES, ids=[c[0] for c in CASES])
def test_resources_are_extracted(tmp_path, filename, source, expected):
    path = tmp_path / filename
    path.write_bytes(source)
    parser = CodeParser.for_file(str(path))
    assert parser is not None, f"no parser for {filename}"
    symbols, _edges = parser.parse(source, filename)
    names = {s["symbol_name"] for s in symbols}
    assert expected <= names, f"{filename} extracted {sorted(names)}, expected {sorted(expected)}"


def test_resources_reach_the_graph(tmp_path):
    """A resource must be a real symbol, not just a parse side-effect."""
    from indexer.indexer import CodeIndexer

    root = tmp_path / "InfraProj"
    root.mkdir()
    (root / "schema.sql").write_text("CREATE TABLE orders (id INT);\n", encoding="utf-8")
    ix = CodeIndexer(str(root))
    try:
        ix.index_project(_max_workers=1)
        assert ix.search_symbols("orders"), "the table did not reach the symbol graph"
    finally:
        ix.close()
