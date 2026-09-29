FSHARP_QUERIES = {
    # `let x = v` and `let f a b = ...` have different left-hand shapes, and the
    # extractor only ever runs the query named "function", so both go in one.
    "function": """
        (function_or_value_defn
            (value_declaration_left
                (identifier_pattern
                    (long_identifier_or_op
                        (identifier) @name)))) @symbol
        (function_or_value_defn
            (function_declaration_left
                (identifier) @name)) @symbol
    """,
    "struct": """
        (type_definition
            (record_type_defn
                (type_name
                    (identifier) @name))) @symbol
    """,
    "call": """
        (application_expression
            (long_identifier_or_op
                (identifier) @func)) @call
    """,
}
