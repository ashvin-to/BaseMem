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
    # The receiver is the identifier being navigated from, which sits before the
    # suffix. Without it `w.go()` has no object to type and nothing can resolve.
    "method_call": """
        (call_expression
            (navigation_expression
                (simple_identifier) @obj
                (navigation_suffix
                    (simple_identifier) @method))) @call
    """,
    # `val v = Widget()` types `v`, which is what lets `v.go()` resolve.
    "instantiate": """
        (property_declaration
            (variable_declaration
                (simple_identifier) @name)
            (call_expression
                (simple_identifier) @func)) @assign
    """,
    # `fun run(w: Widget)` -- user_type wraps the type identifier.
    "param": """
        (function_declaration
            (function_value_parameters
                (parameter
                    (simple_identifier) @name
                    (user_type
                        (type_identifier) @func))) @call) @symbol
    """,
    "import": """
        (import_header) @import
    """,
}
