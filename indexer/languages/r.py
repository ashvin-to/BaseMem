"""R.

An R function is an assignment, so the name lives on the left-hand side of a
`binary_operator` rather than inside the definition. Calls are `call` nodes; the
`$` and `::` pipes appear as the `function` of a call, which is how
`obj$run()` and `pkg::fn()` are recognised here.
"""

R_QUERIES = {
    "function": """
        (binary_operator
            lhs: (identifier) @name
            rhs: (function_definition)) @symbol

        (binary_operator
            lhs: (extract_operator) @name
            rhs: (function_definition)) @symbol
    """,
    "call": """
        (call
            function: (identifier) @func) @call
    """,
    # `obj$run()` -- lhs is the receiver, rhs the method.
    "method_call": """
        (call
            function: (extract_operator
                lhs: (_) @obj
                rhs: (identifier) @method)) @call
    """,
    # `pkg::fn()` and `pkg$fn()` at the top level.
    "scoped_call": """
        (extract_operator
            lhs: (identifier) @obj
            rhs: (identifier) @method) @call
    """,
    "import": """
        (library_require
            (string) @source) @import
    """,
}
