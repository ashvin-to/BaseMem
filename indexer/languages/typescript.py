TS_QUERIES = {
    "function": """
        (function_declaration
            name: (identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "arrow": """
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function) @body) @symbol
    """,
    "class": """
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @symbol
    """,
    "method": """
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "method_signature": """
        (method_signature
            name: (property_identifier) @name) @symbol
    """,
    "interface": """
        (interface_declaration
            name: (type_identifier) @name
            body: (interface_body) @body) @symbol
    """,
    "type_alias": """
        (type_alias_declaration
            name: (type_identifier) @name
            value: (_) @body) @symbol
    """,
    "enum": """
        (enum_declaration
            name: (identifier) @name
            body: (enum_body) @body) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "optional_call": """
        (optional_call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "new": """
        (new_expression constructor: (identifier) @func) @call
    """,
    "import": """
        (import_statement
            source: (string) @source) @import
    """,
    "export": """
        (export_statement) @export
    """,
}
