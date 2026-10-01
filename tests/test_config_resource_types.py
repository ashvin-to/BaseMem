"""Config files must not pollute code search.

YAML, TOML, HCL and Dockerfile keys were emitted into the generic `class` and
`struct` slots so the existing pipeline would pick them up. That worked for
extraction and failed for search: a CI workflow's top-level keys came back as
"classes", and in ansible they outnumbered the actual program beside them --
23,850 symbols from .yml files against 12,888 from 1,843 Python files.

They now carry their own `resource` type, so they stay queryable when you want
config structure and stay out of the way when you are looking for code.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

YAML = b"""name: build
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: make check
"""

HCL = b'''resource "aws_s3_bucket" "logs" {
  bucket = "my-logs"
}
'''


def _types(filename, src, tmp_path):
    from indexer.parser import CodeParser

    (tmp_path / filename).write_bytes(src)
    parser = CodeParser.for_file(filename)
    symbols, _edges = parser.parse(src, filename)
    return {s["symbol_name"]: s["symbol_type"] for s in symbols}


def test_yaml_keys_are_resources_not_classes(tmp_path):
    types = _types("ci.yml", YAML, tmp_path)
    assert types, "no symbols extracted from the workflow"
    assert "jobs" in types, f"expected a top-level key, got {sorted(types)}"
    assert all(t == "resource" for t in types.values()), (
        f"yaml keys leaked into code types: {types}"
    )


def test_no_yaml_symbol_is_typed_as_code(tmp_path):
    types = _types("ci.yml", YAML, tmp_path)
    for code_type in ("class", "function", "method", "struct"):
        assert code_type not in types.values(), (
            f"{code_type} came from a yaml file: {types}"
        )


def test_hcl_resources_are_resources(tmp_path):
    types = _types("main.tf", HCL, tmp_path)
    assert types, "no symbols extracted from the terraform file"
    assert all(t == "resource" for t in types.values()), types


def test_resource_slot_is_evaluated_before_type_alias(tmp_path):
    """Regression: the slot's position in the kind list is load-bearing.

    HCL has two queries that capture the same @symbol node, and the parser keeps
    whichever matched first by byte range. Moving `resource` to the end of the
    list let `type_alias` claim the block first, and every terraform resource
    was reported as the literal keyword `resource` instead of `aws_s3_bucket`.
    """
    types = _types("main.tf", HCL, tmp_path)
    assert types.get("aws_s3_bucket") == "resource", (
        f"expected the resource name, got {types}"
    )
    assert "resource" not in types, f"block keyword leaked through: {types}"


def test_code_still_uses_its_own_types(tmp_path):
    """The resource type must not leak the other way."""
    src = b"class Widget:\n    def go(self):\n        return 1\n"
    types = _types("m.py", src, tmp_path)
    assert types.get("Widget") == "class", types
    assert types.get("go") in ("method", "function"), types
