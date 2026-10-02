"""Lua.

Previously on the generic path: 115 files of luasocket gave 627 symbols and
member calls resolving at 0.0%.

A Lua name is either a plain identifier, a `a.b` field access, or a `a:b` method
call, and the grammar has a distinct node for each. `function Widget:go()` is a
`method_index_expression`, so the method is named separately from the table.
"""

LUA_QUERIES = {
    # `function Widget.new()` and a plain `function helper()`. Both go in the
    # `function` slot: the extractor only ever runs the slot names in its kind
    # list, and `function_signature` is not one of them, so a query under that
    # name is never evaluated.
    "function": """
        (function_declaration
            name: (dot_index_expression
                table: (identifier) @obj
                field: (identifier) @name)
            parameters: (parameters) @body) @symbol

        (function_declaration
            name: (identifier) @name
            parameters: (parameters) @body) @symbol
    """,
    # `function Widget:go()`
    "method": """
        (function_declaration
            name: (method_index_expression
                table: (identifier) @obj
                method: (identifier) @name)
            parameters: (parameters) @body) @symbol
    """,
    "call": """
        (function_call
            name: (identifier) @func) @call
    """,
    # `obj:method()` and `self.helper()`. Both forms go in `method_call` because
    # the edge extractor only runs the slot names it knows: a query under any
    # other name is never evaluated, which is how `self.helper()` went missing.
    "method_call": """
        (function_call
            name: (method_index_expression
                table: (_) @obj
                method: (identifier) @method)) @call

        (function_call
            name: (dot_index_expression
                table: (_) @obj
                field: (identifier) @method)) @call
    """,
    "inherits": """
        (function_declaration
            name: (method_index_expression
                method: (identifier) @name
                parameters: (parameters))
            body: (block
                (set_metafield_expression
                    (variable_list
                        (variable_declaration
                            (assignment_statement
                                (expression_list
                                    (dot_index_expression
                                        field: (identifier) @base)))))))) @symbol
    """,
}
