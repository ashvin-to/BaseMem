"""Config and infrastructure-as-code formats.

These are not callable languages, so they are indexed as *resources* rather than
functions/classes. Reusing symbol_type="resource" means the whole pipeline —
index, search, code_context, impact, the memory links — works on them unchanged,
which is the point: cbm treats Dockerfile/K8s nodes as first-class graph entities
for the same reason.

`table` is the SQL analogue (a statement kind that names an object). The
extractor's "function"/"class" query slots are reused deliberately.
"""

SQL_QUERIES = {
    # a created table is a resource; `function` is the extractor slot that fits
    "function": """
        (create_table
            (object_reference
                name: (identifier) @name)) @symbol
    """,
    "class": """
        (create_view
            (object_reference
                name: (identifier) @name)) @symbol
    """,
    "interface": """
        (create_type
            (object_reference
                name: (identifier) @name)) @symbol
    """,
    "enum": """
        (create_type
            (object_reference
                name: (identifier) @name)) @symbol
    """,
}

GRAPHQL_QUERIES = {
    "class": """
        (object_type_definition (name) @name) @symbol
    """,
    "interface": """
        (interface_type_definition (name) @name) @symbol
    """,
    "enum": """
        (enum_type_definition (name) @name) @symbol
    """,
    "function": """
        (field_definition (name) @name) @symbol
    """,
}

YAML_QUERIES = {
    # only top-level keys are resources; nested keys are structure
    "resource": """
        (block_mapping_pair
            key: (flow_node (plain_scalar (string_scalar) @name))
            value: (block_node)) @symbol
    """,
}

TOML_QUERIES = {
    "resource": """
        (table (bare_key) @name) @symbol
    """,
    "type_alias": """
        (pair (bare_key) @name) @symbol
    """,
}

DOCKERFILE_QUERIES = {
    "resource": """
        (from_instruction
            (image_spec name: (image_name) @name)) @symbol
    """,
}

HCL_QUERIES = {
    # resource "aws_s3_bucket" "b" { ... } — the label identifies the instance.
    "resource": """
        (block
            (string_lit
                (template_literal) @name)) @symbol
    """,
    "type_alias": """
        (block
            (identifier) @name) @symbol
    """,
}
