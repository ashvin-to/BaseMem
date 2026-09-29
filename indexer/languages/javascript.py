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
    "instantiate": """
        (variable_declarator
            name: (identifier) @name
            value: (new_expression
                constructor: (identifier) @func) @call) @assign
    """,
    "instantiate_call": """
        (variable_declarator
            name: (identifier) @name
            value: (call_expression
                function: (identifier) @func) @call) @assign
    """,
    "inherits": """
        (class_declaration
            name: (identifier) @name
            (class_heritage
                (identifier) @base)) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (member_expression
                object: (_) @obj
                property: (property_identifier) @method)) @call
    """,
    "optional_call": """
        (optional_call_expression
            function: (member_expression
                object: (_) @obj
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
