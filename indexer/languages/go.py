"""Go.

Without a query file the indexer falls back to the language pack's generic
structure pass, which emits symbols and imports but essentially no call edges —
so on a Go repo `code_trace` and `get_callers` come back nearly empty. These
queries give Go a real call graph.

Go's grammar keeps methods in `method_declaration` (with a receiver) rather than
nesting them under the type, so the method query captures the type name too and
the parser's parent lookup stays satisfied by the enclosing function.
"""

GO_QUERIES = {
    "function": """
        (function_declaration
            name: (identifier) @name) @symbol
    """,
    "method": """
        (method_declaration
            name: (field_identifier) @name) @symbol
    """,
    "class": """
        (type_declaration
            (type_spec
                name: (type_identifier) @name
                type: (struct_type))) @symbol
    """,
    "interface": """
        (type_declaration
            (type_spec
                name: (type_identifier) @name
                type: (interface_type))) @symbol
    """,
    "type_alias": """
        (type_declaration
            (type_spec
                name: (type_identifier) @name)) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (selector_expression
                operand: (_) @obj
                field: (field_identifier) @method)) @call
    """,
    # s := NewThing()  /  x := &Widget{}
    "instantiate": """
        (short_var_declaration
            left: (expression_list
                (identifier) @name)
            right: (expression_list
                (call_expression
                    function: (identifier) @func) @call)) @assign
    """,
    "instantiate_new": """
        (short_var_declaration
            left: (expression_list
                (identifier) @name)
            right: (expression_list
                (unary_expression
                    operand: (composite_literal
                        type: (type_identifier) @func)))) @assign
    """,
    # The extractor reads @source/@name off the node, so a bare
    # (import_declaration) records almost nothing.
    # Parameter and receiver types. Without these, a call like s.startCheckers()
    # inside a method has no type for `s` and cannot resolve, which on a Go repo
    # silently empties the call graph for every receiver-based call.
    "param": """
        (method_declaration
            receiver: (parameter_list
                (parameter_declaration
                    name: (identifier) @name
                    type: (pointer_type
                        (type_identifier) @func))) @call) @assign
    """,
    "param_value": """
        (function_declaration
            parameters: (parameter_list
                (parameter_declaration
                    name: (identifier) @name
                    type: (type_identifier) @func) @call) @assign) @symbol
    """,
    "import": """
        (import_spec
            path: (interpreted_string_literal) @source) @import
    """,
}
