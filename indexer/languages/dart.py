"""Dart.

Previously on the generic path: 1519 files of riverpod gave 5991 symbols and
member calls resolving at 1.1%.

Dart writes a method call as a chain of `selector` siblings -- `w.go()` is
`(identifier) (selector (unconditional_assignable_selector (identifier)))
(selector (argument_part (arguments)))` -- so the receiver is a *sibling* of the
selector rather than a child, and has to be captured from the parent.
"""

DART_QUERIES = {
    "function": """
        (function_signature
            name: (identifier) @name
            (function_body) @body) @symbol
    """,
    "class": """
        (class_definition
            name: (identifier) @name
            body: (class_body) @body) @symbol
    """,
    "method": """
        (method_signature
            (function_signature
                name: (identifier) @name)) @symbol
    """,
    "enum": """
        (enum_signature
            name: (identifier) @name) @symbol
    """,
    "call": """
        (selector
            (argument_part
                (arguments
                    (identifier) @func))) @call
    """,
    # `w.go()` -- the receiver identifier precedes the selector.
    "method_call": """
        (selector
            (unconditional_assignable_selector
                (identifier) @method)
            (argument_part)) @call
    """,
    # `var v = Widget(1)` types v.
    "instantiate": """
        (initialized_variable_definition
            name: (identifier) @name
            value: (identifier) @func) @assign
    """,
    # `void f(Widget w)`
    "param": """
        (function_signature
            (formal_parameter_list
                (formal_parameter
                    (type_identifier) @func
                    name: (identifier) @name) @call) @assign) @symbol
    """,
    "inherits": """
        (class_definition
            name: (identifier) @name
            (superclass
                (type_identifier) @base)) @symbol
    """,
    "import": """
        (import_or_configuration
            (import_specification
                (string_literal) @source)) @import
    """,
}
