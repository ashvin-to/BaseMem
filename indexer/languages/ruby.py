"""Ruby.

Ruby is a dynamic language, so the graph is name-based: `other.run` resolves
through the method name alone, since there is no static type to attach. What the
generic fallback could not do was record the calls at all -- 183 files of
sinatra produced 287 symbols and zero edges.
"""

RUBY_QUERIES = {
    "function": """
        (method
            name: (identifier) @name
            body: (body_statement) @body) @symbol
    """,
    "class": """
        (class
            name: (constant) @name
            body: (body_statement) @body) @symbol
    """,
    "namespace": """
        (module
            name: (constant) @name
            body: (body_statement) @body) @symbol

        (module
            name: (constant) @name) @symbol
    """,
    # `def self.make` -- a class method, named like any other method.
    "method": """
        (singleton_method
            name: (identifier) @name
            body: (body_statement) @body) @symbol
    """,
    # `other.run` -- receiver and method are both named fields here, so the
    # receiver is available for a member-call lookup.
    "method_call": """
        (call
            receiver: (_) @obj
            method: (identifier) @method) @call
    """,
    "call": """
        (call
            method: (identifier) @func) @call
    """,
    "inherits": """
        (class
            name: (constant) @name
            superclass: (superclass (constant) @base)) @symbol
    """,
}
