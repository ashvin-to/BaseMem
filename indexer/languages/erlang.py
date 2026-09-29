ERLANG_QUERIES = {
    "function": """
        (fun_decl
            clause: (function_clause
                name: (atom) @name)) @symbol
    """,
    "call": """
        (call
            (atom) @func) @call
    """,
}
