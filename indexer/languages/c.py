"""C.

Sized against the Linux kernel, where this query file was capturing 1.4% of the
structs and none of the macros, enums, enum constants or file-scope variables.

In 200 kernel .c files: 6,721 `struct`, 637 `#define`, 91 `enum`, 785 file-scope
variables -- against 95 structs and zero of everything else. Structs were the
single biggest miss because the previous query required a *named* struct *with a
body*, and the kernel is full of `typedef struct { ... } Foo;` and of
`struct foo *ptr;` forward references.
"""

C_QUERIES = {
    "function": """
        (function_definition
            declarator: (function_declarator
                declarator: (_) @name)) @symbol
    """,
    # A named struct with a body, the case that used to be the only one matched.
    "struct": """
        (struct_specifier
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @symbol
    """,
    "struct_toplevel": """
        (struct_specifier
            name: (type_identifier) @name) @symbol
    """,
    # `typedef struct { ... } Foo;` -- the struct is anonymous and the typedef
    # supplies the name.
    "struct_typedef": """
        (type_definition
            type: (struct_specifier
                body: (field_declaration_list) @body)
            declarator: (type_identifier) @name) @symbol
    """,
    "enum": """
        (enum_specifier
            name: (type_identifier) @name
            body: (enumerator_list) @body) @symbol
    """,
    "enum_toplevel": """
        (enum_specifier
            name: (type_identifier) @name) @symbol
    """,
    # The constants themselves. The kernel is full of them and they were absent.
    "enumerator": """
        (enumerator
            name: (identifier) @name) @symbol
    """,
    "type_alias": """
        (type_definition
            declarator: (type_identifier) @name) @symbol
    """,
    # `#define` and `#define F(x)`. The `macro` slot existed in this file for a
    # long time but was never in the parser's kind list, so it was never run.
    "macro": """
        (preproc_def
            name: (identifier) @name) @symbol

        (preproc_function_def
            name: (identifier) @name) @symbol
    """,
    # File-scope `static int x = 1;`. Locals are the same node, so the
    # top-level convention is what separates them.
    "variable_toplevel": """
        (declaration
            type: (_)
            declarator: (init_declarator
                declarator: (identifier) @name)) @symbol

        (declaration
            type: (_)
            declarator: (identifier) @name) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (field_expression
                argument: (_) @obj
                field: (field_identifier) @method)) @call
    """,
    "new": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "import": """
        (preproc_include
            path: (string_literal) @source) @import
    """,
}
