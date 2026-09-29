KOTLIN_QUERIES = {
    "function": """
        (function_declaration
            (simple_identifier) @name) @symbol
    """,
    "class": """
        (class_declaration
            (type_identifier) @name) @symbol
    """,
    "method": """
        (class_declaration
            (type_identifier)
            (class_body
                (function_declaration
                    (simple_identifier) @name) @symbol))
    """,
    "call": """
        (call_expression
            (simple_identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            (navigation_expression
                (navigation_suffix
                    (simple_identifier) @method))) @call
    """,
    "import": """
        (import_header) @import
    """,
}
