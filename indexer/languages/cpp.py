CPP_QUERIES = {
    "function": """
        (function_definition
            declarator: (function_declarator
                declarator: (_) @name)) @symbol
    """,
    "class": """
        (class_specifier
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @symbol
    """,
    "namespace": """
        (namespace_definition
            name: (namespace_identifier) @name
            body: (declaration_list) @body) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
        (call_expression
            function: (qualified_identifier
                name: (identifier) @func)) @call
    """,
    "method_call": """
        (call_expression
            function: (field_expression
                field: (field_identifier) @method)) @call
    """,
    "import": """
        (preproc_include
            path: (string_literal) @source) @import
    """,
}
