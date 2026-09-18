JS_QUERIES = {
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
            name: (identifier) @name
            body: (class_body) @body) @symbol
    """,
    "method": """
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @symbol
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
    "require": """
        (call_expression
            function: (identifier) @func
            arguments: (arguments (string) @source)) @require
    """,
    "export": """
        (export_statement) @export
    """,
}
