"""PHP.

There was no query file, and the repository chosen for testing it earlier
(guzzlehttp/guzzle) turned out to have a README-only default branch, so php was
never actually exercised: 0 files, 0 symbols. Re-tested against
symfony/http-kernel, 338 files.

Note the field order below. tree-sitter requires a query's fields to appear in
the same order as the node's children, and a `simple_parameter` has `type` as
child 0 and `name` as child 1, so `name:` before `type:` is an impossible
pattern that compiles to nothing without raising.
"""

PHP_QUERIES = {
    "function": """
        (function_definition
            name: (name) @name
            body: (compound_statement) @body) @symbol
    """,
    "method": """
        (method_declaration
            name: (name) @name
            body: (compound_statement) @body) @symbol
    """,
    "method_signature": """
        (method_declaration
            name: (name) @name) @symbol
    """,
    "class": """
        (class_declaration
            name: (name) @name
            body: (declaration_list) @body) @symbol
    """,
    "interface": """
        (interface_declaration
            name: (name) @name
            body: (declaration_list) @body) @symbol
    """,
    "trait": """
        (trait_declaration
            name: (name) @name
            body: (declaration_list) @body) @symbol
    """,
    "enum": """
        (enum_declaration
            name: (name) @name
            body: (declaration_list) @body) @symbol
    """,
    "namespace": """
        (namespace_definition
            name: (name) @name) @symbol
    """,
    "call": """
        (function_call_expression
            function: (name) @func) @call
    """,
    # `$w->go()` is its own node type, not a function_call_expression wrapping a
    # member_access_expression, so it needs its own query.
    #
    # Capture the bare variable name rather than the whole `object` node: the
    # latter yields `$w`, while a parameter is recorded as `w`, so every lookup
    # would miss on the sigil. A receiver that is not a plain variable (`$this`,
    # `foo()->bar()`) is deliberately dropped -- its text is never a type name,
    # so it cannot resolve anything.
    "method_call": """
        (member_call_expression
            object: (variable_name (name) @obj)
            name: (name) @method) @call
    """,
    # `$v = new Widget()` types v.
    "instantiate": """
        (assignment_expression
            left: (variable_name (name) @name)
            right: (object_creation_expression
                (name) @func)) @assign
    """,
    # `function f(Widget $w)` -- note type: precedes name: in the node.
    "param": """
        (function_definition
            parameters: (formal_parameters
                (simple_parameter
                    type: (named_type (name) @func)
                    name: (variable_name (name) @name)) @call) @assign) @symbol
    """,
    "param_method": """
        (method_declaration
            parameters: (formal_parameters
                (simple_parameter
                    type: (named_type (name) @func)
                    name: (variable_name (name) @name)) @call) @assign) @symbol
    """,
    "inherits": """
        (class_declaration
            name: (name) @name
            (base_clause (name) @base)) @symbol
    """,
}
