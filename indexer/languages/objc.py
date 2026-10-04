"""Objective-C.

Previously on the generic path: 88 files of AFNetworking gave 960 symbols and
10 call edges, so the graph was effectively empty.

A message send `[self helper]` is a `message_expression` with `receiver:` and
`method:` fields, which is a different node from a plain C-style call.
"""

OBJC_QUERIES = {
    "class": """
        (class_interface
            (identifier) @name
            superclass: (identifier)) @symbol
    """,
    "method_signature": """
        (method_declaration
            (method_type) @body
            (identifier) @name) @symbol
    """,
    "method": """
        (method_definition
            (method_type) @body
            (identifier) @name) @symbol
    """,
    "function": """
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @name)) @symbol
    """,
    # `[self helper]` -- receiver is the object being messaged.
    "method_call": """
        (message_expression
            receiver: (_) @obj
            method: (identifier) @method) @call
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "new": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "inherits": """
        (class_interface
            (identifier) @name
            superclass: (identifier) @base) @symbol
    """,
    "import": """
        (preproc_include
            path: (string_literal) @source) @import
    """,
}
