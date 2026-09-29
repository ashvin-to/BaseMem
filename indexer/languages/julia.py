JULIA_QUERIES = {
    "function": """
        (function_definition
            (signature
                (call_expression
                    (identifier) @name))) @symbol
    """,
    "struct": """
        (struct_definition
            (type_head
                (identifier) @name)) @symbol
    """,
    "call": """
        (call_expression
            (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            (dot_expression) @method) @call
    """,
}
