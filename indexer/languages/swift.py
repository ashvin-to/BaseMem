"""Swift.

Swift's `call_expression` uses positional children rather than a `function:`
field, so a free call is `(call_expression (simple_identifier) ...)` and a method
call wraps a `navigation_expression` whose `target:` is the receiver.
"""

SWIFT_QUERIES = {
    "function": """
        (function_declaration
            name: (simple_identifier) @name
            body: (function_body) @body) @symbol
    """,
    "class": """
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @symbol
    """,
    "struct": """
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @symbol
    """,
    "interface": """
        (protocol_declaration
            name: (type_identifier) @name) @symbol
    """,
    "call": """
        (call_expression
            (simple_identifier) @func) @call
    """,
    # `other.go()` -- target is the receiver and must be captured, or the call
    # has nothing to resolve against.
    "method_call": """
        (call_expression
            (navigation_expression
                target: (_) @obj
                suffix: (navigation_suffix
                    suffix: (simple_identifier) @method))) @call
    """,
    # `let w = Widget()` types w.
    "instantiate": """
        (property_declaration
            (pattern
                (simple_identifier) @name)
            (call_expression
                (simple_identifier) @func)) @assign
    """,
    # `func m(w: Widget)`. Match positionally: the parameter's children are
    # `name:`, a literal `:` token, then the type under a second `name:` field,
    # and repeating a field like that is an impossible pattern.
    "param": """
        (function_declaration
            (parameter
                (simple_identifier) @name
                (user_type (_) @func)) @call
            body: (function_body) @body) @symbol
    """,
    "inherits": """
        (class_declaration
            name: (type_identifier) @name
            (inheritance_specifier
                inherits_from: (user_type (type_identifier) @base))) @symbol
    """,
    "import": """
        (import_declaration
            (identifier) @source) @import
    """,
}
