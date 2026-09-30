"""Scala.

Previously on the generic path: 845 files of typelevel/cats gave 6022 symbols,
free calls at 80%, and member calls at 0.0%.
"""

SCALA_QUERIES = {
    "function": """
        (function_definition
            name: (identifier) @name
            body: (_) @body) @symbol
    """,
    "class": """
        (class_definition
            name: (identifier) @name
            body: (template_body) @body) @symbol
    """,
    "namespace": """
        (object_definition
            name: (identifier) @name
            body: (template_body) @body) @symbol
    """,
    "trait": """
        (trait_definition
            name: (identifier) @name
            body: (template_body) @body) @symbol
    """,
    "enum": """
        (enum_definition
            name: (identifier) @name
            body: (template_body) @body) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    # `other.run()` -- the receiver must be captured, or the call is untyped.
    "method_call": """
        (call_expression
            function: (field_expression
                value: (_) @obj
                id: (identifier) @method)) @call
    """,
    # `val w = new Widget()` types w.
    "instantiate": """
        (val_definition
            pattern: (identifier) @name
            (instance_expression
                (type_identifier) @func)) @assign
    """,
    # `def go(w: Widget)`
    "param": """
        (function_definition
            parameters: (parameters
                (parameter
                    name: (identifier) @name
                    type: (type_identifier) @func) @call) @assign) @symbol
    """,
    "inherits": """
        (class_definition
            name: (identifier) @name
            (extends
                (type_identifier) @base)) @symbol
    """,
    "import": """
        (import_declaration) @import
    """,
}
