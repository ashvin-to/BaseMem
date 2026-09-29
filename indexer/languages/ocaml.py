OCAML_QUERIES = {
    "function": """
        (value_definition
            (let_binding
                pattern: (value_name) @name)) @symbol
    """,
    "type_alias": """
        (type_definition
            (type_binding
                name: (type_constructor) @name)) @symbol
    """,
    "class": """
        (class_definition
            (type_binding
                name: (type_constructor) @name)) @symbol
    """,
    "call": """
        (application_expression
            function: (value_path
                (value_name) @func)) @call
    """,
}
