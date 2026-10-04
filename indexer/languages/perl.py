PERL_QUERIES = {
    "function": """
        (subroutine_declaration_statement
            name: (bareword) @name) @symbol
    """,
    "call": """
        (function_call_expression
            function: (function)) @call
    """,
    "method_call": """
        (function_call_expression
            function: (scoped_call_expression) @method) @call
    """,
}
