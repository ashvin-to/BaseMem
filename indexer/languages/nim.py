"""Nim.

The grammar has no `methodCall` node, so a query for one matches nothing and the
language silently emitted zero member calls. A dotted call is a `primary` holding
`symbol`, then a `primarySuffix` wrapping `qualifiedSuffix`, then a second
`primarySuffix` wrapping `functionCall`.

The `call` query anchors with `.` so the `functionCall` suffix must directly
follow the symbol. Without the anchor `path:splitFile()` also matched, recording
a bogus free call to `path` on every method call in the file.
"""

NIM_QUERIES = {
    "function": """
        (routine
            (symbol
                (ident) @name)) @symbol
    """,
    # `.` anchors the suffix directly after the symbol. A command-style call
    # (`echo parts[0]`) wraps its argument in `cmdCall`, not `functionCall`.
    "call": """
        (primary
            (symbol
                (ident) @func)
            . (primarySuffix
                [(functionCall) (cmdCall)])) @call
    """,
    "method_call": """
        (primary
            (symbol
                (ident) @obj)
            (primarySuffix
                (qualifiedSuffix
                    (symbol
                        (ident) @method)))) @call
    """,
}
