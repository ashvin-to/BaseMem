JAVA_QUERIES = {
    "function": """
        (method_declaration
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "class": """
        (class_declaration
            name: (identifier) @name
            body: (class_body) @body) @symbol
    """,
    "interface": """
        (interface_declaration
            name: (identifier) @name
            body: (interface_body) @body) @symbol
    """,
    "enum": """
        (enum_declaration
            name: (identifier) @name
            body: (enum_body) @body) @symbol
    """,
    "constructor": """
        (constructor_declaration
            name: (identifier) @name
            body: (constructor_body) @body) @symbol
    """,
    "call": """
        (method_invocation
            name: (identifier) @func) @call
    """,
    "import": """
        (import_declaration
            (scoped_identifier) @source) @import
    """,
}
