PYTHON_QUERIES = {
    "function": """
        (function_definition
            name: (identifier) @name
            parameters: (parameters) @params
            body: (block) @body) @symbol
    """,
    "class": """
        (class_definition
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "call": """
        (call function: (identifier) @func) @call
    """,
    "method_call": """
        (call function: (attribute attribute: (identifier) @method) @attr) @call
    """,
    "import": """
        (import_statement
            name: (dotted_name) @name) @import
    """,
    "import_from": """
        (import_from_statement
            module_name: (_) @module
            name: (_) @name) @import_from
    """,
    "relative_import": """
        (import_from_statement
            name: (relative_import) @name) @import_from
    """,
    "decorator": """
        (decorator (identifier) @name) @decorator
    """,
}
