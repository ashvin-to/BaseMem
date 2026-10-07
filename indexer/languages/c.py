"""C.

Sized against the Linux kernel, where this query file was capturing 1.4% of the
structs and none of the macros, enums, enum constants or file-scope variables.

In 200 kernel .c files: 6,721 `struct`, 637 `#define`, 91 `enum`, 785 file-scope
variables -- against 95 structs and zero of everything else. Structs were the
single biggest miss because the previous query required a *named* struct *with a
body*, and the kernel is full of `typedef struct { ... } Foo;` and of
`struct foo *ptr;` forward references.
"""

def build_function_query(name_capture: str = "(_) @name") -> str:
    """Every declarator chain that can hold a function's name.

    The direct `declarator:` of a function_definition is only a
    function_declarator when the return type is not a pointer. `void *memcpy()`
    nests it as pointer_declarator > function_declarator, so a query written
    against the plain shape misses every pointer-returning function: 41,708 of
    them across the kernel, 6% of all C functions, among them memcpy, kmalloc
    and vzalloc. The index held their header declarations and none of the
    definitions.

    Each chain here is mutually exclusive and none is a duplicate, because
    tree-sitter rejects an impossible pattern outright -- a repeated one fails
    to compile and the whole language silently stops extracting. Shapes and
    counts are what tree-sitter actually produces across the kernel's 698,311
    function_definition nodes, not a guess at the grammar.
    """
    return "\n".join(
        (
            # `int f(void)` -- 652,381
            f"(function_definition declarator: (function_declarator declarator: {name_capture})) @symbol",
            # `void *f(void)` -- 41,708
            f"(function_definition declarator: (pointer_declarator declarator: (function_declarator declarator: {name_capture}))) @symbol",
            # `void **f(void)` -- 245
            f"(function_definition declarator: (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: {name_capture})))) @symbol",
            # `void ***f(void)` -- 2
            f"(function_definition declarator: (pointer_declarator declarator: (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: {name_capture}))))) @symbol",
            # `int (f)(void)` -- 3,864. The inner node is a plain child, not a
            # `declarator:` field: parenthesized_declarator has no such field,
            # and naming one makes tree-sitter reject the whole query.
            "(function_definition declarator: (parenthesized_declarator (identifier) @name)) @symbol",
            # 12
            f"(function_definition declarator: (parenthesized_declarator (function_declarator declarator: {name_capture}))) @symbol",
            # `void f(void)[3]` -- 4
            f"(function_definition declarator: (array_declarator declarator: (function_declarator declarator: {name_capture}))) @symbol",
            # `void *f(void)[3]` -- 1
            f"(function_definition declarator: (pointer_declarator declarator: (array_declarator declarator: (function_declarator declarator: {name_capture})))) @symbol",
            # `void *f` with no parameter list -- 1
            "(function_definition declarator: (pointer_declarator declarator: (identifier) @name)) @symbol",
            # A bare name -- 91
            "(function_definition declarator: (identifier) @name) @symbol",
        )
    )


C_FUNCTION_QUERY = build_function_query()


C_QUERIES = {
    "function": C_FUNCTION_QUERY,
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
