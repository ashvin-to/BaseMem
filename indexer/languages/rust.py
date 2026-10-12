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
    # `value:` is the receiver and must be captured. Without it to_receiver is
    # always empty, the call cannot be typed, and resolution collapses to ~2%.
    "method_call": """
        (call_expression
            function: (field_expression
                value: (_) @obj
                field: (field_identifier) @method)) @call
    """,
    "param": """
        (function_item
            parameters: (parameters
                (parameter
                    pattern: (identifier) @name
                    type: (_) @func) @call) @assign) @symbol
    """,
    # `self` is typed by the impl block it appears in, so a call like self.close()
    # inside an impl has something to resolve against.
    "self_type": """
        (impl_item
            type: (type_identifier) @func
            body: (declaration_list
                (function_item
                    name: (identifier) @name) @assign)) @symbol
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
