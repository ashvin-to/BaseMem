HASKELL_QUERIES = {
    "function": """
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
