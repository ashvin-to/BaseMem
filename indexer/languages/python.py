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
    "instantiate": """
        (assignment
            left: (identifier) @name
            right: (call
                function: (identifier) @func) @call) @assign
    """,
    "annotate": """
        (assignment
            left: (identifier) @name
            right: (call
                function: (attribute
                    attribute: (identifier) @func) @obj) @call) @assign
    """,
    "inherits": """
        (class_definition
            name: (identifier) @name
            superclasses: (argument_list
                (identifier) @base)) @symbol
    """,
    "call": """
        (call function: (identifier) @func) @call
    """,
    "method_call": """
        (call function: (attribute
            object: (_) @obj
            attribute: (identifier) @method)) @call
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
        (decorator (identifier) @name) @symbol
    """,
}
