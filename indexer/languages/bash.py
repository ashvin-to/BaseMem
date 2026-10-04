"""Bash.

Previously on the generic path: 559 files gave 3,434 symbols and 19,531 call
edges, with 22.1% of them resolved. Be aware this is a reorganisation rather
than a large gain -- the generic path already emitted the edges, so the win here
is attribution and method calls, not edge count.

Nearly every statement in a shell script is a `command` node, so a call query
matches `echo`, `cd` and the script's own functions alike. That is faithful to
what the file says, but it means most bash call edges point at commands with no
symbol in the project and cannot resolve.
"""

BASH_QUERIES = {
    "function": """
        (function_definition
            name: (word) @name
            body: (compound_statement) @body) @symbol
    """,
    "call": """
        (command
            name: (command_name (word) @func)) @call
    """,
    "variable_assignment": """
        (variable_assignment
            name: (variable_name) @name
            value: (_) @body) @symbol
    """,
}
