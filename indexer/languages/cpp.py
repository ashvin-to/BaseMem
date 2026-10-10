from .c import build_function_query

CPP_QUERIES = {
    "function": build_function_query(),
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
    # `argument:` is the receiver in C++ field_expression. Omitting it left every
    # `obj.method()` call with no object to type, so none could resolve.
    "method_call": """
        (call_expression
            function: (field_expression
                argument: (_) @obj
                field: (field_identifier) @method)) @call
    """,
    # Parameter types, so a call on a parameter resolves. Two shapes: a plain
    # declarator, and a pointer/qualified one. `const Helper *h` is normalised
    # down to `Helper` before it is stored.
    "param": """
        (function_definition
          declarator: (function_declarator
            declarator: (identifier)
            parameters: (parameter_list
              (parameter_declaration
                type: (_) @func
                declarator: (identifier) @name) @call))) @symbol

        (function_definition
          declarator: (function_declarator
            declarator: (identifier)
            parameters: (parameter_list
              (parameter_declaration
                type: (_) @func
                declarator: (pointer_declarator
                  declarator: (identifier) @name)) @call))) @symbol
    """,
    "import": """
        (preproc_include
            path: (string_literal) @source) @import
    """,
}
