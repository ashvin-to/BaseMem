# zig's grammar uses capitalised node names (Decl, FnProto, IDENTIFIER).
ZIG_QUERIES = {
    "function": """
        (Decl
            (FnProto
                (IDENTIFIER) @name)) @symbol
    """,
    "call": """
        (SuffixExpr
            variable_type_function: (IDENTIFIER) @func
            (FnCallArguments)) @call
    """,
    "method_call": """
        (CallExpr
            (FieldAccess) @method) @call
    """,
}
