NIM_QUERIES = {
    "function": """
        (routine
            (symbol
                (ident) @name)) @symbol
    """,
    "call": """
        (primary
            (symbol
                (ident) @func)
            (primarySuffix
                (functionCall))) @call
    """,
    "method_call": """
        (methodCall
            (ident) @method) @call
    """,
}
