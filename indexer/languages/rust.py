RUST_QUERIES = {
    "function": """
        (function_item
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "struct": """
        (struct_item
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @symbol
    """,
    "enum": """
        (enum_item
            name: (type_identifier) @name
            body: (enum_variant_list) @body) @symbol
    """,
    "trait": """
        (trait_item
            name: (type_identifier) @name
            body: (declaration_list) @body) @symbol
    """,
    "impl": """
        (impl_item
            type: (type_identifier) @type) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "scoped_call": """
        (call_expression
            function: (scoped_identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (field_expression
                field: (field_identifier) @method)) @call
    """,
    "import": """
        (use_declaration
            argument: (scoped_identifier) @path) @import
    """,
    "macro": """
        (macro_invocation
            macro: (identifier) @name) @macro
    """,
}
