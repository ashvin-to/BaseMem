HASKELL_QUERIES = {
    # `bind` is used for every binding, including a `let` inside a do-block or
    # where-clause, so the plain form put 1,454 symbols in one Analytics.hs.
    # `_toplevel` drops bindings nested inside another binding of the same kind.
    "function_toplevel": """
        (bind
            name: (variable) @name) @symbol
    """,
    "type_alias": """
        (data_type
            (plain_type
                (name) @name)) @symbol
    """,
    "class": """
        (class
            (name) @name) @symbol
    """,
}
