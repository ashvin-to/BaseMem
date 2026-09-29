TS_QUERIES = {
    "function": """
        (function_declaration
            name: (identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "arrow": """
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function) @body) @symbol
    """,
    "class": """
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @symbol
    """,
    "method": """
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @symbol
    """,
    # `app.use = function (fn) {}` and `app.use = () => {}`. The function here is
    # anonymous, so it can only be named by the property it is assigned to.
    "assigned_method": """
        (assignment_expression
            left: (member_expression
                object: (_)
                property: (property_identifier) @name)
            right: [(function_expression) (arrow_function)]) @symbol
    """,
    "method_signature": """
        (method_signature
            name: (property_identifier) @name) @symbol
    """,
    "interface": """
        (interface_declaration
            name: (type_identifier) @name
            body: (interface_body) @body) @symbol
    """,
    "type_alias": """
        (type_alias_declaration
            name: (type_identifier) @name
            value: (_) @body) @symbol
    """,
    "enum": """
        (enum_declaration
            name: (identifier) @name
            body: (enum_body) @body) @symbol
    """,
    # `{ init: function () {}, close: () => {} }` -- a function-valued object key
    # is named by that key. Very common in exports and option objects.
    "assigned_method_literal": """
        (object
            (pair
                key: (property_identifier) @name
                value: [(function_expression) (arrow_function)]) @symbol) @pair
    """,
    "instantiate": """
        (variable_declarator
            name: (identifier) @name
            value: (new_expression
                constructor: (identifier) @func) @call) @assign
    """,
    "instantiate_call": """
        (variable_declarator
            name: (identifier) @name
            value: (call_expression
                function: (identifier) @func) @call) @assign
    """,
    "inherits": """
        (class_declaration
            name: (type_identifier) @name
            (class_heritage
                (extends_clause
                    value: (identifier) @base))) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (member_expression
                object: (_) @obj
                property: (property_identifier) @method)) @call
    """,
    "optional_call": """
        (optional_call_expression
            function: (member_expression
                object: (_) @obj
                property: (property_identifier) @method)) @call
    """,
    "new": """
        (new_expression constructor: (identifier) @func) @call
    """,
    "import": """
        (import_statement
            source: (string) @source) @import
    """,
    "export": """
        (export_statement) @export
    """,
}
