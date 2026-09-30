"""C#.

Without a query file the indexer falls back to the language pack's generic
structure pass, which for C# produced symbols but *zero* call edges: 959 files in
Newtonsoft.Json yielded 1398 symbols and not one caller or callee. So
`get_callers` and `code_trace` came back empty for the whole language.
"""

CSHARP_QUERIES = {
    "function": """
        (method_declaration
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "method_signature": """
        (method_declaration
            name: (identifier) @name) @symbol
    """,
    "class": """
        (class_declaration
            name: (identifier) @name
            body: (declaration_list) @body) @symbol
    """,
    "interface": """
        (interface_declaration
            name: (identifier) @name) @symbol
    """,
    "struct": """
        (struct_declaration
            name: (identifier) @name
            body: (declaration_list) @body) @symbol
    """,
    "enum": """
        (enum_declaration
            name: (identifier) @name) @symbol
    """,
    "constructor": """
        (constructor_declaration
            name: (identifier) @name) @symbol
    """,
    # `other.Run()` — `expression` is the receiver and must be captured, or the
    # call arrives with no object to type.
    "method_call": """
        (invocation_expression
            function: (member_access_expression
                expression: (_) @obj
                name: (identifier) @method)) @call
    """,
    "call": """
        (invocation_expression
            function: (identifier) @func) @call
    """,
    # `var v = new Widget()` types v. There is no `value:` field on
    # variable_declarator in this grammar; the initialiser is just a child.
    "instantiate": """
        (variable_declaration
            (variable_declarator
                name: (identifier) @name
                (object_creation_expression
                    type: (identifier) @func))) @assign
    """,
    # `var v = other.Thing()` types v from a factory call.
    "instantiate_call": """
        (variable_declaration
            (variable_declarator
                name: (identifier) @name
                (invocation_expression
                    function: (identifier) @func))) @assign
    """,
    "new": """
        (object_creation_expression
            type: (identifier) @func) @call
    """,
    # `void Go(Widget w)` -- parameter types.
    #
    # Two things bite here. The type node varies (identifier, predefined_type,
    # generic_name), so match any node and let _normalize_type reduce it. And
    # tree-sitter requires fields in the node's own child order: `parameter` has
    # type as child 0 and name as child 1, so writing name before type is an
    # "impossible pattern" and the whole query silently compiles to nothing.
    "param": """
        (method_declaration
            parameters: (parameter_list
                (parameter
                    type: (_) @func
                    name: (identifier) @name) @call) @assign) @symbol
    """,
    "inherits": """
        (class_declaration
            name: (identifier) @name
            (base_list
                (identifier) @base)) @symbol
    """,
    "import": """
        (using_directive) @import
    """,
}
