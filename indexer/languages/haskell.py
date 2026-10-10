"""Haskell.

A call is `(apply (variable) arg...)` — the callee is the first `variable` child,
not the whole application. There is no dedicated call node, so without these
queries the language produced 3,536 symbols and not one edge.

`function_toplevel` drops bindings nested inside another binding of the same
kind: `bind` is also used for every `let` inside a do-block, which otherwise put
1,454 symbols into a single Analytics.hs.
"""

HASKELL_QUERIES = {
    "function_toplevel": """
        (bind
            name: (variable) @name) @symbol

        (function
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
    # A partially applied function (`f x`) and a saturated one (`f x y`) are both
    # `apply`; the callee is always the leading variable.
    "call": """
        (apply
            (variable) @func) @call
    """,
    # `Data.List.sort x` is a qualified name; the module part is not a callee.
    "method_call": """
        (apply
            (qualified
                (module) @obj
                (variable) @method)) @call
    """,
}