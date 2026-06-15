"""Tree-sitter based code parser. Extracts symbols and edges from source files."""

import hashlib
from pathlib import Path
from typing import Optional

from tree_sitter import Language, Node, Parser, Query, QueryCursor

# ── Language grammars ────────────────────────────────────────────────

def _load_language(package):
    capsule = package.language()
    return Language(capsule)


_GRAMMAR_CACHE = {}
_QUERY_CACHE = {}


def _get_grammar(lang: str) -> Optional[Language]:
    if lang not in _GRAMMAR_CACHE:
        try:
            if lang == "python":
                import tree_sitter_python
                _GRAMMAR_CACHE[lang] = _load_language(tree_sitter_python)
            elif lang == "javascript":
                import tree_sitter_javascript
                _GRAMMAR_CACHE[lang] = _load_language(tree_sitter_javascript)
            elif lang == "typescript":
                import tree_sitter_typescript
                _GRAMMAR_CACHE[lang] = _load_language(tree_sitter_typescript.tsx)
            elif lang == "rust":
                import tree_sitter_rust
                _GRAMMAR_CACHE[lang] = _load_language(tree_sitter_rust)
        except ImportError:
            return None
    return _GRAMMAR_CACHE.get(lang)


SUPPORTED_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

# ── Queries per language ─────────────────────────────────────────────

PYTHON_QUERIES = {
    "function": """
        (function_definition
            name: (identifier) @name
            parameters: (parameters) @params
            body: (block) @body) @symbol
    """,
    "class": """
        (class_definition
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "call": """
        (call function: (identifier) @func) @call
    """,
    "method_call": """
        (call function: (attribute attribute: (identifier) @method) @attr) @call
    """,
    "import": """
        (import_statement
            name: (dotted_name) @name) @import
    """,
    "import_from": """
        (import_from_statement
            module_name: (dotted_name) @module
            name: (dotted_name) @name) @import_from
    """,
    "decorator": """
        (decorator (identifier) @name) @decorator
    """,
}

JS_QUERIES = {
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
            name: (identifier) @name
            body: (class_body) @body) @symbol
    """,
    "method": """
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "import": """
        (import_statement
            source: (string) @source) @import
    """,
    "require": """
        (call_expression
            function: (identifier) @func
            arguments: (arguments (string) @source)) @require
    """,
    "export": """
        (export_statement) @export
    """,
}

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
    "method_signature": """
        (method_signature
            name: (property_identifier) @name) @symbol
    """,
    "interface": """
        (interface_declaration
            name: (type_identifier) @name
            body: (object_type) @body) @symbol
    """,
    "type_alias": """
        (type_alias_declaration
            name: (type_identifier) @name
            value: (_) @body) @symbol
    """,
    "enum": """
        (enum_item
            name: (type_identifier) @name
            body: (enum_variant_list) @body) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "import": """
        (import_statement
            source: (string) @source) @import
    """,
    "import_type": """
        (import_type
            source: (string) @source) @import
    """,
    "export": """
        (export_statement) @export
    """,
}

RUST_QUERIES = {
    "function": """
        (function_item
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "struct": """
        (struct_item
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @symbol
    """,
    "enum": """
        (enum_item
            name: (type_identifier) @name
            body: (enum_variant_list) @body) @symbol
    """,
    "trait": """
        (trait_item
            name: (type_identifier) @name
            body: (declaration_list) @body) @symbol
    """,
    "impl": """
        (impl_item
            type: (type_identifier) @type) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (field_expression
                field: (field_identifier) @method)) @call
    """,
    "import": """
        (use_declaration
            argument: (scoped_identifier) @path) @import
    """,
    "macro": """
        (macro_invocation
            macro: (identifier) @name) @macro
    """,
}

LANGUAGE_QUERIES = {
    "python": PYTHON_QUERIES,
    "javascript": JS_QUERIES,
    "typescript": TS_QUERIES,
    "rust": RUST_QUERIES,
}


class CodeParser:
    """Parses source code into symbols and edges using tree-sitter."""

    def __init__(self, language: str):
        self.language = language
        self.grammar = _get_grammar(language)
        if self.grammar is None:
            raise ValueError(f"Unsupported or unavailable language: {language}")
        self.parser = Parser()
        self.parser.language = self.grammar
        self.queries = LANGUAGE_QUERIES.get(language, {})
        self._compiled_queries = {}

    @classmethod
    def for_file(cls, file_path: str) -> Optional["CodeParser"]:
        ext = Path(file_path).suffix.lower()
        lang = SUPPORTED_LANGUAGES.get(ext)
        if not lang:
            return None
        try:
            return cls(lang)
        except ValueError:
            return None

    @classmethod
    def supported_extension(cls, ext: str) -> bool:
        return ext.lower() in SUPPORTED_LANGUAGES

    def _get_query(self, name: str):
        if name not in self._compiled_queries:
            source = self.queries.get(name, "")
            if not source:
                return None
            self._compiled_queries[name] = Query(self.grammar, source)
        return self._compiled_queries[name]

    def parse(self, source_bytes: bytes, file_path: str = ""):
        """Parse source code and extract symbols and edges.

        Returns:
            symbols: list of dicts
            edges: list of dicts
        """
        tree = self.parser.parse(source_bytes)
        root = tree.root_node
        symbols = []
        edges = []
        _seen_ranges = set()

        if root is None or root.has_error:
            return symbols, edges

        text_lines = source_bytes.decode("utf-8", errors="replace").split("\n")

        # Extract definitions
        for kind, query_name in [
            ("function", "function"),
            ("class", "class"),
            ("method", "method"),
            ("method_signature", "method_signature"),
            ("interface", "interface"),
            ("type_alias", "type_alias"),
            ("enum", "enum"),
            ("struct", "struct"),
            ("trait", "trait"),
            ("impl", "impl"),
            ("arrow", "arrow"),
        ]:
            if query_name not in self.queries:
                continue
            q = self._get_query(query_name)
            if q is None:
                continue
            cursor = QueryCursor(q)
            for _p_idx, captures in cursor.matches(root):
                cap_map = {name: nodes for name, nodes in captures.items()}
                sym_node = _first_node(cap_map.get("symbol"))
                name_node = _first_node(cap_map.get("name"))
                if sym_node is None or name_node is None:
                    continue
                range_key = (sym_node.start_byte, sym_node.end_byte)
                if range_key in _seen_ranges:
                    continue
                _seen_ranges.add(range_key)

                sym_name = _node_text(name_node, source_bytes)
                kind_val = kind

                # For Python, detect async and method context
                if self.language == "python" and kind == "function":
                    is_async = sym_node.children and sym_node.children[0].type == "async"
                    is_method = _is_python_method(root, sym_node)
                    if is_async and is_method:
                        kind_val = "async_method"
                    elif is_async:
                        kind_val = "async_function"
                    elif is_method:
                        kind_val = "method"

                # For JavaScript, detect getter/setter
                if self.language in ("javascript", "typescript") and kind == "method":
                    kind_node = _first_node(cap_map.get("kind"))
                    if kind_node:
                        kt = _node_text(kind_node, source_bytes)
                        if kt in ("get", "set"):
                            kind_val = f"{kt}_{kind}"

                signature = ""
                if "params" in cap_map:
                    params_node = _first_node(cap_map["params"])
                    if params_node:
                        signature = _node_text(params_node, source_bytes)

                docstring = _extract_docstring(self.language, sym_node, source_bytes, text_lines)
                parent_id = None

                # Determine parent for methods
                if kind_val in ("method", "async_method", "method_signature"):
                    parent = _find_parent_class(root, sym_node)
                    if parent:
                        parent_name_node = _find_named_child(parent, self.language)
                        if parent_name_node:
                            parent_id = _node_text(parent_name_node, source_bytes)

                symbol = {
                    "file_path": file_path,
                    "symbol_name": sym_name,
                    "symbol_type": kind_val,
                    "language": self.language,
                    "kind": "",
                    "start_line": sym_node.start_point[0] + 1,
                    "end_line": sym_node.end_point[0] + 1,
                    "start_col": sym_node.start_point[1] + 1,
                    "end_col": sym_node.end_point[1] + 1,
                    "signature": signature,
                    "docstring": docstring,
                    "parent_id": parent_id,
                    "content_hash": _content_hash(source_bytes, sym_node),
                }
                symbols.append(symbol)

        # Extract calls
        calls = self._extract_calls(root, source_bytes, file_path)
        edges.extend(calls)

        # Extract imports
        imports = self._extract_imports(root, source_bytes, file_path)
        edges.extend(imports)

        return symbols, edges

    def _extract_calls(self, root: Node, source_bytes: bytes, file_path: str):
        edges = []
        q_call = self._get_query("call")
        q_mcall = self._get_query("method_call")

        if q_call:
            cursor = QueryCursor(q_call)
            for _p_idx, captures in cursor.matches(root):
                call_node = _first_node(captures.get("call"))
                func_node = _first_node(captures.get("func"))
                if call_node and func_node:
                    caller = _find_enclosing_func(root, call_node)
                    callee = _node_text(func_node, source_bytes)
                    edges.append({
                        "edge_type": "calls",
                        "from_name": caller or "",
                        "target_name": callee,
                        "file_path": file_path,
                        "line_number": func_node.start_point[0] + 1,
                    })

        if q_mcall:
            cursor = QueryCursor(q_mcall)
            for _p_idx, captures in cursor.matches(root):
                call_node = _first_node(captures.get("call"))
                method_node = _first_node(captures.get("method"))
                if call_node and method_node:
                    caller = _find_enclosing_func(root, call_node)
                    callee = _node_text(method_node, source_bytes)
                    edges.append({
                        "edge_type": "calls",
                        "from_name": caller or "",
                        "target_name": callee,
                        "file_path": file_path,
                        "line_number": method_node.start_point[0] + 1,
                    })

        return edges

    def _extract_imports(self, root: Node, source_bytes: bytes, file_path: str):
        edges = []
        q_import = self._get_query("import")
        q_from = self._get_query("import_from")

        if q_import:
            cursor = QueryCursor(q_import)
            for _p_idx, captures in cursor.matches(root):
                source_node = _first_node(captures.get("source"))
                name_node = _first_node(captures.get("name"))
                if source_node:
                    src = _node_text(source_node, source_bytes).strip("'\"")
                    edges.append({
                        "edge_type": "imports",
                        "from_name": src,
                        "target_name": None,
                        "file_path": file_path,
                        "line_number": source_node.start_point[0] + 1,
                    })
                elif name_node:
                    name = _node_text(name_node, source_bytes)
                    edges.append({
                        "edge_type": "imports",
                        "from_name": name,
                        "target_name": None,
                        "file_path": file_path,
                        "line_number": name_node.start_point[0] + 1,
                    })

        if q_from:
            cursor = QueryCursor(q_from)
            for _p_idx, captures in cursor.matches(root):
                module_node = _first_node(captures.get("module"))
                name_node = _first_node(captures.get("name"))
                if module_node:
                    module = _node_text(module_node, source_bytes)
                    name = _node_text(name_node, source_bytes) if name_node else "*"
                    edges.append({
                        "edge_type": "imports",
                        "from_name": f"{module}.{name}",
                        "target_name": None,
                        "file_path": file_path,
                        "line_number": module_node.start_point[0] + 1,
                    })

        return edges


# ── Helpers ──────────────────────────────────────────────────────────

def _node_text(node, source_bytes):
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _first_node(nodes):
    if not nodes:
        return None
    return nodes[0]


def _content_hash(source_bytes, node):
    return hashlib.sha256(source_bytes[node.start_byte:node.end_byte]).hexdigest()[:16]


def _is_python_method(root, func_node):
    """Check if a function_definition is inside a class."""
    parent = func_node.parent
    while parent is not None and parent.type != "module":
        if parent.type == "class_definition":
            return True
        parent = parent.parent
    return False


def _extract_docstring(language, sym_node, source_bytes, text_lines):
    """Extract docstring / comment text."""
    if language == "python":
        body = _find_child_of_type(sym_node, "block")
        if body and body.children:
            first = body.children[0]
            if first.type == "expression_statement" and first.children:
                maybe_str = first.children[0]
                if maybe_str.type == "string":
                    return _node_text(maybe_str, source_bytes).strip("\"'")
            elif first.type == "string":
                return _node_text(first, source_bytes).strip("\"'")
    elif language in ("javascript", "typescript"):
        start_line = sym_node.start_point[0]
        comment_lines = []
        for i in range(start_line - 1, max(start_line - 5, -1), -1):
            line = text_lines[i].strip() if i < len(text_lines) else ""
            if line.startswith("//"):
                comment_lines.insert(0, line[2:].strip())
            elif line.startswith("/*") or line.startswith("*"):
                comment_lines.insert(0, line.strip().strip("/*").strip("*").strip())
            elif line.startswith("/**"):
                comment_lines.insert(0, line.strip().strip("/**").strip().strip("*/"))
            else:
                break
        if comment_lines:
            return " ".join(comment_lines)
    elif language == "rust":
        start_line = sym_node.start_point[0]
        comments = []
        for i in range(start_line - 1, max(start_line - 5, -1), -1):
            line = text_lines[i].strip() if i < len(text_lines) else ""
            if line.startswith("///"):
                comments.insert(0, line[3:].strip())
            elif line.startswith("//!"):
                comments.insert(0, line[3:].strip())
            elif line.startswith("/*") or line.startswith("*"):
                comments.insert(0, line.strip().strip("/*").strip("*").strip())
            else:
                break
        if comments:
            return " ".join(comments)
    return ""


def _find_child_of_type(node, type_name):
    for c in node.children:
        if c.type == type_name:
            return c
    return None


def _find_parent_class(root, method_node):
    cursor = method_node.walk()
    parent = cursor.node.parent
    while parent is not None and parent.type not in ("module", "program"):
        if parent.type in ("class_definition", "class_declaration"):
            return parent
        parent = parent.parent
    return None


def _find_enclosing_func(root, node):
    """Walk up to find the enclosing function/method name."""
    cur = node.parent
    while cur is not None and cur.type not in ("module", "program", "source_file"):
        if cur.type in ("function_definition", "function_declaration", "function_item",
                        "method_definition", "async_function_definition", "async_method_definition",
                        "arrow_function"):
            for c in cur.children:
                if c.type in ("identifier", "property_identifier"):
                    return _node_text(c, root.text)  # use root.text for the source bytes
            return None
        cur = cur.parent
    return None


def _find_named_child(node, language):
    if language == "python":
        return _find_child_of_type(node, "identifier")
    elif language in ("javascript", "typescript"):
        return _find_child_of_type(node, "type_identifier") or _find_child_of_type(node, "identifier")
    elif language == "rust":
        return _find_child_of_type(node, "type_identifier") or _find_child_of_type(node, "identifier")
    return _find_child_of_type(node, "identifier")
